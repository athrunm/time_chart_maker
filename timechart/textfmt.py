"""テキスト記法との相互変換。

    @title タイトル
    CLK       : p.......
    EN        : 0.1...0.
    DATA[7:0] : x.=.=.x. | A, B
    LEVEL     : 0.2.5.3. | max=5, 0=停止, 2=低速, 5=高速
    @marker 2 t1

`#` で始まる行はコメント。
"""
from __future__ import annotations

import re
import unicodedata

from .model import DEFAULT_MULTI_MAX, MAX_LEVEL_LIMIT, Chart, Marker, Signal, wave_max_digit

LINE_RE = re.compile(r"^(?P<name>.*?)\s*:\s*(?P<wave>[0-9pnxPNX=. \t]*?)\s*(?:\|(?P<data>.*))?$")
# 多値信号の指定: max=N（最大値）、K=名前（値 K の意味）
OPT_RE = re.compile(r"^(max|\d+)\s*=\s*(.*)$", re.I)


class ParseError(ValueError):
    def __init__(self, line_no: int, message: str):
        super().__init__(f"{line_no}行目: {message}")
        self.line_no = line_no


def parse_chart(text: str) -> Chart:
    chart = Chart()
    for no, raw in enumerate(text.splitlines(), start=1):
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("@"):
            key, _, rest = line[1:].partition(" ")
            rest = rest.strip()
            if key == "title":
                chart.title = rest
            elif key == "marker":
                time, _, label = rest.partition(" ")
                if not time.isdigit():
                    raise ParseError(no, "@marker の後には時刻（整数）を書いてください（例: @marker 4 t1）")
                chart.markers.append(Marker(int(time), label.strip()))
            else:
                raise ParseError(no, f"不明な指定 @{key} です（@title / @marker が使えます）")
            continue
        m = LINE_RE.match(line)
        if not m:
            if ":" in line:
                raise ParseError(no, "波形に使えるのは 0〜9 p n x = . の文字だけです")
            raise ParseError(no, "「名前 : 波形」の形で書いてください（例: CLK : p.......）")
        wave = re.sub(r"\s", "", m.group("wave")).lower()
        if wave.startswith("."):
            raise ParseError(no, "波形の先頭に . は使えません")
        data_text = m.group("data") or ""
        items = [v.strip() for v in data_text.split(",")] if data_text.strip() else []
        opts = [OPT_RE.match(v) for v in items]
        top = wave_max_digit(wave)
        names: dict[int, str] = {}
        if "=" not in wave and items and all(opts):
            max_level = None
            for mo in opts:
                key, val = mo.group(1).lower(), mo.group(2).strip()
                if key == "max":
                    if not val.isdigit() or not 1 <= int(val) <= MAX_LEVEL_LIMIT:
                        raise ParseError(no, f"max は 1〜{MAX_LEVEL_LIMIT} で指定してください")
                    max_level = int(val)
                elif val:
                    names[int(key)] = val
            if max_level is None:
                max_level = max(DEFAULT_MULTI_MAX, top)
            if top > max_level:
                raise ParseError(no, f"値 {top} が max={max_level} を超えています")
            over = [k for k in names if k > max_level]
            if over:
                raise ParseError(no, f"値 {over[0]} の意味が max={max_level} を超えています")
            data = []
        else:
            if top > 1 and "=" in wave:
                raise ParseError(no, "2 以上の値とバス値(=)は同じ信号に混在できません")
            max_level = max(DEFAULT_MULTI_MAX, top) if top > 1 else 1
            data = items
        chart.signals.append(Signal(m.group("name").strip(), wave, data, max_level,
                                    names if max_level > 1 else {}))
    chart.markers.sort(key=lambda mk: mk.time)
    return chart


def display_width(text: str) -> int:
    return sum(2 if unicodedata.east_asian_width(ch) in "WF" else 1 for ch in text)


def format_chart(chart: Chart) -> str:
    lines: list[str] = []
    if chart.title:
        lines.append(f"@title {chart.title}")
    width = max((display_width(s.name) for s in chart.signals), default=0)
    for s in chart.signals:
        line = f"{s.name}{' ' * (width - display_width(s.name))} : {s.wave}"
        if s.is_multi:
            line += " | " + ", ".join([f"max={s.max_level}"] +
                                      [f"{k}={v}" for k, v in sorted(s.level_names.items())])
        elif s.is_bus and any(s.data):
            line += " | " + ", ".join(s.data)
        lines.append(line)
    for mk in chart.markers:
        lines.append(f"@marker {mk.time} {mk.label}".rstrip())
    return "\n".join(lines) + "\n"
