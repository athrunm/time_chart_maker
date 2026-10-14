"""タイムチャートのデータモデル。

波形は WaveDrom 風の文字列で保持する（1 文字 = 1 サイクル）。

    0 : Low
    1 : High
    2-9 : 多値信号のレベル（max_level 以下）
    p : クロック（立ち上がりから始まる 1 周期）
    n : クロック（立ち下がりから始まる 1 周期）
    x : 不定
    = : バス値（data の値を先頭から順に使う）
    . : 直前の状態を継続
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

STATES = "0123456789pnx="
WAVE_CHARS = STATES + "."
MAX_LEVEL_LIMIT = 9
DEFAULT_MULTI_MAX = 5


def wave_max_digit(wave: str) -> int:
    return max((int(ch) for ch in wave if ch.isdigit()), default=0)


@dataclass
class Cell:
    """1 サイクル分の状態。start はバス値の区切り（新しい値の開始）を表す。"""

    state: str
    label: str = ""
    start: bool = True


def continuation(prev: Cell | None) -> Cell:
    if prev is None:
        return Cell("x")
    return Cell(prev.state, prev.label, start=False)


def expand(wave: str, data: list[str]) -> list[Cell]:
    cells: list[Cell] = []
    di = 0
    prev: Cell | None = None
    for ch in wave:
        if ch == ".":
            cell = continuation(prev)
        elif ch == "=":
            cell = Cell("=", data[di] if di < len(data) else "", start=True)
            di += 1
        else:
            cell = Cell(ch)
        cells.append(cell)
        prev = cell
    return cells


def normalize(cells: list[Cell]) -> None:
    """継続中のバスセルに、直前のセルの値を引き継がせる。"""
    for i in range(1, len(cells)):
        c, p = cells[i], cells[i - 1]
        if c.state == "=" and not c.start and p.state == "=":
            c.label = p.label


def compress(cells: list[Cell]) -> tuple[str, list[str]]:
    wave: list[str] = []
    data: list[str] = []
    prev: Cell | None = None
    for c in cells:
        if c.state == "=":
            if prev is not None and prev.state == "=" and not c.start:
                wave.append(".")
            else:
                wave.append("=")
                data.append(c.label)
        elif prev is not None and prev.state == c.state:
            wave.append(".")
        else:
            wave.append(c.state)
        prev = c
    return "".join(wave), data


@dataclass
class Signal:
    name: str
    wave: str = ""
    data: list[str] = field(default_factory=list)
    max_level: int = 1  # 2 以上なら多値信号（0〜max_level）
    level_names: dict[int, str] = field(default_factory=dict)  # 多値信号の各値の意味（例: {0: "停止"}）

    @property
    def is_bus(self) -> bool:
        return "=" in self.wave

    @property
    def is_multi(self) -> bool:
        return self.max_level > 1

    def set_max_level(self, n: int) -> None:
        """最大値を変更する。最大値を超えるレベルは最大値に丸める。"""
        n = max(1, min(MAX_LEVEL_LIMIT, n))
        cells = self.cells()
        for c in cells:
            if c.state.isdigit() and int(c.state) > n:
                c.state = str(n)
        self.max_level = n
        self.level_names = {k: v for k, v in self.level_names.items() if k <= n} if n > 1 else {}
        self.set_cells(cells)

    def level_label(self, level: int) -> str:
        """値の表示用ラベル。意味が設定されていれば「2:低速」の形にする。"""
        name = self.level_names.get(level, "")
        return f"{level}:{name}" if name else str(level)

    def cells(self) -> list[Cell]:
        return expand(self.wave, self.data)

    def set_cells(self, cells: list[Cell]) -> None:
        normalize(cells)
        self.wave, self.data = compress(cells)

    def set_length(self, n: int) -> None:
        cells = self.cells()[:n]
        while len(cells) < n:
            cells.append(continuation(cells[-1]) if cells else Cell("0"))
        self.set_cells(cells)

    def set_cell(self, t: int, cell: Cell) -> None:
        cells = self.cells()
        while len(cells) <= t:
            cells.append(continuation(cells[-1]) if cells else Cell("0"))
        cells[t] = cell
        self.set_cells(cells)

    def set_bus_value(self, t: int, value: str) -> None:
        """バス値を設定する。空文字は前の値の継続、x は不定。"""
        value = value.strip()
        if value == "":
            cells = self.cells()
            prev = cells[min(t, len(cells)) - 1] if t > 0 and cells else None
            self.set_cell(t, continuation(prev))
        elif value.lower() == "x":
            self.set_cell(t, Cell("x"))
        else:
            self.set_cell(t, Cell("=", value, start=True))


@dataclass
class Marker:
    time: int
    label: str = ""


@dataclass
class Chart:
    title: str = ""
    signals: list[Signal] = field(default_factory=list)
    markers: list[Marker] = field(default_factory=list)

    @property
    def length(self) -> int:
        return max((len(s.wave) for s in self.signals), default=0)

    def set_length(self, n: int) -> None:
        for s in self.signals:
            s.set_length(n)
        self.markers = [m for m in self.markers if m.time <= n]

    def insert_cycle(self, t: int) -> None:
        """全信号の t サイクル目に 1 サイクル挿入する（直前の状態を継続）。"""
        for s in self.signals:
            cells = s.cells()
            if not cells or t > len(cells):
                continue
            if t == 0:
                first = cells[0]
                cells.insert(0, Cell(first.state, first.label))
                if first.state == "=":
                    first.start = False
            else:
                cells.insert(t, continuation(cells[t - 1]))
            s.set_cells(cells)
        for m in self.markers:
            if m.time > t:
                m.time += 1

    def delete_cycle(self, t: int) -> None:
        """全信号の t サイクル目を削除する。"""
        for s in self.signals:
            cells = s.cells()
            if t >= len(cells):
                continue
            removed = cells.pop(t)
            if t < len(cells):
                nxt = cells[t]
                if removed.start and nxt.state == "=" and not nxt.start:
                    nxt.start = True
            s.set_cells(cells)
        markers: list[Marker] = []
        for m in self.markers:
            time = m.time - 1 if m.time > t else m.time
            if all(k.time != time for k in markers):
                markers.append(Marker(time, m.label))
        self.markers = markers

    def toggle_marker(self, time: int, label: str) -> None:
        for m in self.markers:
            if m.time == time:
                self.markers.remove(m)
                return
        self.markers.append(Marker(time, label))
        self.markers.sort(key=lambda m: m.time)

    def next_marker_label(self) -> str:
        used = {m.label for m in self.markers}
        i = 1
        while f"t{i}" in used:
            i += 1
        return f"t{i}"

    # ---- 保存 / 読込 ----
    def to_dict(self) -> dict:
        return {
            "title": self.title,
            "signals": [{"name": s.name, "wave": s.wave, "data": list(s.data),
                         **({"max": s.max_level} if s.is_multi else {}),
                         **({"levels": {str(k): v for k, v in sorted(s.level_names.items())}}
                            if s.is_multi and s.level_names else {})} for s in self.signals],
            "markers": [{"time": m.time, "label": m.label} for m in self.markers],
        }

    @classmethod
    def from_dict(cls, d: dict) -> "Chart":
        signals = []
        for s in d.get("signals", []):
            wave = str(s.get("wave", ""))
            bad = set(wave) - set(WAVE_CHARS)
            if bad:
                raise ValueError(f"信号 {s.get('name')!r} に使用できない文字があります: {''.join(sorted(bad))}")
            max_level = int(s.get("max", 1))
            if not 1 <= max_level <= MAX_LEVEL_LIMIT or wave_max_digit(wave) > max_level:
                raise ValueError(f"信号 {s.get('name')!r} の値が最大値 {max_level} を超えています")
            names = {int(k): str(v) for k, v in dict(s.get("levels", {})).items() if str(v)}
            if any(not 0 <= k <= max_level for k in names):
                raise ValueError(f"信号 {s.get('name')!r} の値の意味が最大値 {max_level} の範囲外です")
            signals.append(Signal(str(s.get("name", "")), wave, [str(v) for v in s.get("data", [])], max_level,
                                  names if max_level > 1 else {}))
        markers = [Marker(int(m["time"]), str(m.get("label", ""))) for m in d.get("markers", [])]
        return cls(str(d.get("title", "")), signals, markers)


def clock_wave(length: int, period: int = 2, rising: bool = True) -> str:
    """周期 period（セル数）のクロック波形を作る。period=1 は p/n 記法を使う。"""
    if length <= 0:
        return ""
    if period <= 1:
        return ("p" if rising else "n") + "." * (length - 1)
    first = (period + 1) // 2
    hi, lo = ("1", "0") if rising else ("0", "1")
    cells = [Cell(hi if i % period < first else lo) for i in range(length)]
    return compress(cells)[0]


def save_file(path: str | Path, chart: Chart, settings: dict | None = None) -> None:
    doc = {"app": "time_chart_maker", "version": 1, **chart.to_dict(), "settings": settings or {}}
    Path(path).write_text(json.dumps(doc, ensure_ascii=False, indent=2), encoding="utf-8")


def load_file(path: str | Path) -> tuple[Chart, dict]:
    doc = json.loads(Path(path).read_text(encoding="utf-8"))
    return Chart.from_dict(doc), dict(doc.get("settings", {}))


def sample_chart() -> Chart:
    return Chart(
        title="サンプル: データ転送",
        signals=[
            Signal("CLK", clock_wave(16, 1)),
            Signal("CS_N", "1.0...........1."),
            Signal("EN", "0..1........0..."),
            Signal("LEVEL", "0...2...5.3...0.", max_level=5, level_names={0: "停止", 2: "低速", 5: "高速"}),
            Signal("DATA[7:0]", "x...=...=...=.x.", ["0x1F", "0xA0", "0x3C"]),
        ],
        markers=[Marker(4, "t1"), Marker(12, "t2")],
    )
