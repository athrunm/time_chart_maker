"""タイムチャートを描画プリミティブ（線・多角形・文字）に変換する。

Tk キャンバスと Pillow（PNG 出力）の両方が同じプリミティブを描くことで、
画面と出力画像の見た目を揃える。
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

from .model import Cell, Chart

# measure(text, size_px, bold) -> 幅(px)
Measure = Callable[[str, int, bool], float]


@dataclass
class Style:
    cell_w: float = 40
    row_h: float = 44
    wave_h: float = 24
    level_h: float = 13  # 多値信号の 1 レベルあたりの高さ
    margin: float = 16
    axis_h: float = 26
    marker_h: float = 26
    name_gap: float = 18
    title_size: int = 18
    font_size: int = 14
    small_size: int = 12
    value_size: int = 10
    show_grid: bool = True

    background: str = "#ffffff"
    line: str = "#1f2937"
    text: str = "#111827"
    muted: str = "#6b7280"
    grid: str = "#d1d5db"
    zebra: str = "#f5f7fa"
    bus_fill: str = "#dbeafe"
    x_fill: str = "#e5e7eb"
    hatch: str = "#9ca3af"
    marker: str = "#dc2626"


@dataclass
class Line:
    points: list[float]
    color: str
    width: float = 1.5
    dash: tuple[int, int] | None = None


@dataclass
class Poly:
    points: list[float]
    fill: str


@dataclass
class Text:
    x: float
    y: float
    text: str
    color: str
    size: int
    bold: bool = False
    anchor: str = "w"  # w / e / center / n / s / nw / sw


Primitive = Line | Poly | Text


@dataclass
class Layout:
    """クリック位置の判定に使うレイアウト情報。"""

    x0: float
    cell_w: float
    n_cells: int
    axis_top: float
    axis_bottom: float
    row_bounds: list[float]  # 行の境界の y 座標（行数 + 1 個）
    waves: list[tuple[float, float]]  # 各行の波形の上端・下端
    width: float
    height: float

    @property
    def n_rows(self) -> int:
        return len(self.waves)

    @property
    def rows_top(self) -> float:
        return self.row_bounds[0]

    @property
    def rows_bottom(self) -> float:
        return self.row_bounds[-1]

    def x_of(self, t: float) -> float:
        return self.x0 + t * self.cell_w

    def row_at(self, y: float) -> int | None:
        for i in range(self.n_rows):
            if self.row_bounds[i] <= y < self.row_bounds[i + 1]:
                return i
        return None

    def nearest_boundary(self, y: float) -> int:
        """y に最も近い行の境界の番号（行の並べ替え先）。"""
        return min(range(len(self.row_bounds)), key=lambda i: abs(self.row_bounds[i] - y))

    def level_at(self, row: int, y: float, max_level: int) -> int:
        """多値信号の行で、y 位置に対応するレベル。"""
        top, bot = self.waves[row]
        return max(0, min(max_level, round((bot - y) / (bot - top) * max_level)))

    def hit(self, x: float, y: float) -> tuple | None:
        if self.axis_top <= y < self.axis_bottom and x >= self.x0 - self.cell_w / 2:
            t = round((x - self.x0) / self.cell_w)
            return ("axis", max(0, min(self.n_cells, t)))
        row = self.row_at(y)
        if row is not None:
            if x < self.x0:
                return ("name", row)
            t = int((x - self.x0) // self.cell_w)
            if 0 <= t < self.n_cells:
                return ("cell", row, t)
        return None


def tick_step(cell_w: float, min_px: float = 26) -> int:
    for step in (1, 2, 5, 10, 20, 50, 100, 200, 500):
        if step * cell_w >= min_px:
            return step
    return 1000


def fit_text(text: str, avail: float, size: int, measure: Measure) -> str:
    if measure(text, size, False) <= avail:
        return text
    while text and measure(text + "…", size, False) > avail:
        text = text[:-1]
    return text + "…" if text else ""


def wave_segments(cells: list[Cell], max_level: int = 1) -> list[list]:
    """セル列を [種類, 開始時刻, 終了時刻, ラベル] の区間に変換する。

    クロック(p/n)は半周期ごとの 0 / 最大値 に分解し、同じレベルが続く区間は結合する。
    """
    high = str(max_level)
    fine: list[tuple] = []
    for i, c in enumerate(cells):
        if c.state in ("p", "n"):
            a, b = (high, "0") if c.state == "p" else ("0", high)
            fine.append((a, i, i + 0.5, "", True))
            fine.append((b, i + 0.5, i + 1, "", True))
        else:
            fine.append((c.state, i, i + 1, c.label, c.start))
    segs: list[list] = []
    for kind, t0, t1, label, start in fine:
        if segs and segs[-1][0] == kind and (kind != "=" or not start):
            segs[-1][2] = t1
        else:
            segs.append([kind, t0, t1, label])
    return segs


def _hatch(prims: list, a: float, b: float, top: float, bot: float, color: str) -> None:
    h = bot - top
    u = a - h
    while u < b:
        sx, ex = max(u, a), min(u + h, b)
        if sx < ex:
            prims.append(Line([sx, bot - (sx - u), ex, bot - (ex - u)], color, 1))
        u += 7


def wave_height(max_level: int, style: Style) -> float:
    return max(style.wave_h, style.level_h * max_level) if max_level > 1 else style.wave_h


def axis_label(level: int, names: dict[int, str]) -> str:
    """多値信号の左側の一覧に書く文字（例: "2 低速"）。"""
    return f"{level} {names[level]}" if names.get(level) else str(level)


def draw_wave(prims: list, cells: list[Cell], x0: float, cw: float, top: float, bot: float,
              style: Style, measure: Measure, max_level: int = 1,
              level_names: dict[int, str] | None = None) -> None:
    level_names = level_names or {}
    mid = (top + bot) / 2
    s = min(4.0, cw / 8)
    multi = max_level > 1

    def level_y(kind: str) -> float:
        return bot - (bot - top) * min(int(kind), max_level) / max_level

    segs = wave_segments(cells, max_level)
    for j, (kind, t0, t1, label) in enumerate(segs):
        prev = segs[j - 1] if j > 0 else None
        nxt = segs[j + 1] if j + 1 < len(segs) else None
        xa, xb = x0 + t0 * cw, x0 + t1 * cw
        sl = s if prev else 0
        sr = s if nxt else 0
        if kind.isdigit():
            y = level_y(kind)
            pts: list[float] = []
            if prev and not prev[0].isdigit():
                pts += [xa, mid]
            pts += [xa + sl, y, xb - sr, y]
            if nxt:
                pts += [xb + sr, level_y(nxt[0])] if nxt[0].isdigit() else [xb, mid]
            prims.append(Line(pts, style.line, 2))
            # 値は区間の左端（変化の直後）に書く。中央だと補助線やマーカーと重なりやすい
            # 意味が設定されていれば「2:低速」、入りきらなければ数字だけにする
            if multi:
                avail = (xb - sr) - (xa + sl) - 6
                name = level_names.get(int(kind))
                shown = next((t for t in ([f"{kind}:{name}"] if name else []) + [kind]
                              if measure(t, style.value_size, False) <= avail), None)
                if shown:
                    at_top = int(kind) >= max_level
                    prims.append(Text(xa + sl + 3, y + 3 if at_top else y - 3, shown, style.muted,
                                      style.value_size, anchor="nw" if at_top else "sw"))
            continue
        left = [xa, mid] if prev else []
        right = [xb, mid] if nxt else []
        poly = [xa + sl, top, xb - sr, top] + right + [xb - sr, bot, xa + sl, bot] + left
        prims.append(Poly(poly, style.bus_fill if kind == "=" else style.x_fill))
        if kind == "x":
            _hatch(prims, xa + sl, xb - sr, top, bot, style.hatch)
        prims.append(Line(left + [xa + sl, top, xb - sr, top] + right, style.line, 2))
        prims.append(Line(left + [xa + sl, bot, xb - sr, bot] + right, style.line, 2))
        if kind == "=" and label:
            shown = fit_text(label, (xb - sr) - (xa + sl) - 6, style.small_size, measure)
            if shown:
                prims.append(Text((xa + xb) / 2, mid, shown, style.text, style.small_size, anchor="center"))


def build(chart: Chart, style: Style, measure: Measure) -> tuple[list[Primitive], Layout]:
    prims: list[Primitive] = []
    m = style.margin
    n = chart.length
    cw = style.cell_w
    name_w = max([measure(s.name, style.font_size, True) for s in chart.signals] + [48])
    # 多値信号の左側の値一覧（縦軸）の幅
    axis_w = max([measure(axis_label(k, s.level_names), style.value_size, False)
                  for s in chart.signals if s.is_multi for k in range(s.max_level + 1)], default=0)
    x0 = m + name_w + style.name_gap + (axis_w + 12 if axis_w else 0)
    x_end = x0 + n * cw

    y = m
    title_w = 0.0
    if chart.title:
        prims.append(Text(m, y + style.title_size / 2, chart.title, style.text, style.title_size, bold=True))
        title_w = measure(chart.title, style.title_size, True)
        y += style.title_size + 12
    axis_top, axis_bottom = y, y + style.axis_h

    # 行の配置（多値信号の行は最大値に応じて高くする）
    pad = style.row_h - style.wave_h
    row_bounds = [axis_bottom + 4]
    waves: list[tuple[float, float]] = []
    for sig in chart.signals:
        wh = wave_height(sig.max_level, style)
        top = row_bounds[-1] + pad / 2
        waves.append((top, top + wh))
        row_bounds.append(row_bounds[-1] + wh + pad)
    rows_bottom = row_bounds[-1]
    height = rows_bottom + (style.marker_h if chart.markers else 6) + m
    width = max(x_end + m + 8, m * 2 + title_w)

    # 行の背景（縞模様）
    for i in range(0, len(chart.signals), 2):
        top, bot = row_bounds[i], row_bounds[i + 1]
        prims.append(Poly([m / 2, top, x_end + 6, top, x_end + 6, bot, m / 2, bot], style.zebra))

    # 補助線
    if style.show_grid:
        for t in range(n + 1):
            x = x0 + t * cw
            prims.append(Line([x, axis_bottom, x, rows_bottom], style.grid, 1, dash=(2, 3)))

    # 時間軸
    step = tick_step(cw)
    prims.append(Line([x0, axis_bottom, x_end, axis_bottom], style.muted, 1))
    for t in range(n + 1):
        x = x0 + t * cw
        labeled = t % step == 0
        prims.append(Line([x, axis_bottom - (6 if labeled else 3), x, axis_bottom], style.muted, 1))
        if labeled:
            prims.append(Text(x, axis_bottom - 8, str(t), style.muted, style.small_size, anchor="s"))

    # 信号
    for sig, (top, bot) in zip(chart.signals, waves):
        cy = (top + bot) / 2
        prims.append(Text(m, cy, sig.name, style.text, style.font_size, bold=True))
        if sig.is_multi:
            for k in range(sig.max_level + 1):
                ly = bot - (bot - top) * k / sig.max_level
                prims.append(Line([x0 - 6, ly, x0 - 2, ly], style.muted, 1))
                prims.append(Text(x0 - 9, ly, axis_label(k, sig.level_names), style.muted, style.value_size,
                                  anchor="e"))
        draw_wave(prims, sig.cells(), x0, cw, top, bot, style, measure, sig.max_level, sig.level_names)

    # マーカー
    for mk in chart.markers:
        if 0 <= mk.time <= n:
            x = x0 + mk.time * cw
            prims.append(Line([x, axis_bottom, x, rows_bottom + 4], style.marker, 1.5, dash=(6, 4)))
            if mk.label:
                prims.append(Text(x, rows_bottom + 6, mk.label, style.marker, style.small_size, bold=True,
                                  anchor="n"))

    layout = Layout(x0, cw, n, axis_top, axis_bottom, row_bounds, waves, width, height)
    return prims, layout
