"""テキスト記法との相互変換。

    @title タイトル
    CLK       : p.......
    EN        : 0.1...0.
    DATA[7:0] : x.=.=.x. | A, B
    @marker 2 t1

`#` で始まる行はコメント。
"""
from __future__ import annotations

import re
import unicodedata

from .model import Chart, Marker, Signal

LINE_RE = re.compile(r"^(?P<name>.*?)\s*:\s*(?P<wave>[01pnxPNX=. \t]*?)\s*(?:\|(?P<data>.*))?$")


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
                raise ParseError(no, "波形に使えるのは 0 1 p n x = . の文字だけです")
            raise ParseError(no, "「名前 : 波形」の形で書いてください（例: CLK : p.......）")
        wave = re.sub(r"\s", "", m.group("wave")).lower()
        if wave.startswith("."):
            raise ParseError(no, "波形の先頭に . は使えません")
        data_text = m.group("data")
        data = [v.strip() for v in data_text.split(",")] if data_text and data_text.strip() else []
        chart.signals.append(Signal(m.group("name").strip(), wave, data))
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
        if s.is_bus and any(s.data):
            line += " | " + ", ".join(s.data)
        lines.append(line)
    for mk in chart.markers:
        lines.append(f"@marker {mk.time} {mk.label}".rstrip())
    return "\n".join(lines) + "\n"
