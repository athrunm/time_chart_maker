"""Pillow を使った PNG 出力。"""
from __future__ import annotations

import math
import sys
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

from .model import Chart
from .render import Line, Poly, Style, Text, build

PIL_ANCHOR = {"w": "lm", "e": "rm", "center": "mm", "n": "mt", "s": "mb"}

_FONT_CANDIDATES = {
    False: [
        "C:/Windows/Fonts/meiryo.ttc",
        "C:/Windows/Fonts/YuGothM.ttc",
        "C:/Windows/Fonts/msgothic.ttc",
        "/System/Library/Fonts/ヒラギノ角ゴシック W3.ttc",
        "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
        "/usr/share/fonts/noto-cjk/NotoSansCJK-Regular.ttc",
    ],
    True: [
        "C:/Windows/Fonts/meiryob.ttc",
        "C:/Windows/Fonts/YuGothB.ttc",
        "/System/Library/Fonts/ヒラギノ角ゴシック W6.ttc",
        "/usr/share/fonts/opentype/noto/NotoSansCJK-Bold.ttc",
        "/usr/share/fonts/noto-cjk/NotoSansCJK-Bold.ttc",
    ],
}


def _find_font(bold: bool) -> str | None:
    for path in _FONT_CANDIDATES[bold] + (_FONT_CANDIDATES[False] if bold else []):
        if Path(path).exists():
            return path
    return None


class FontCache:
    def __init__(self) -> None:
        self._paths = {b: _find_font(b) for b in (False, True)}
        self._fonts: dict = {}

    def get(self, size: int, bold: bool = False):
        key = (size, bold)
        if key not in self._fonts:
            path = self._paths[bold]
            self._fonts[key] = ImageFont.truetype(path, size) if path else ImageFont.load_default(size)
        return self._fonts[key]

    def measure(self, text: str, size: int, bold: bool) -> float:
        return self.get(size, bold).getlength(text)


def _dashed(draw: ImageDraw.ImageDraw, pts: list[float], dash: tuple[float, float], fill: str, width: int) -> None:
    on, off = dash
    for i in range(0, len(pts) - 2, 2):
        x1, y1, x2, y2 = pts[i:i + 4]
        length = math.hypot(x2 - x1, y2 - y1)
        if length == 0:
            continue
        dx, dy = (x2 - x1) / length, (y2 - y1) / length
        pos = 0.0
        while pos < length:
            end = min(pos + on, length)
            draw.line([x1 + dx * pos, y1 + dy * pos, x1 + dx * end, y1 + dy * end], fill=fill, width=width)
            pos = end + off


def render_image(chart: Chart, style: Style | None = None, scale: float = 2.0) -> Image.Image:
    style = style or Style()
    fonts = FontCache()
    prims, layout = build(chart, style, fonts.measure)
    size = (max(1, math.ceil(layout.width * scale)), max(1, math.ceil(layout.height * scale)))
    img = Image.new("RGB", size, style.background)
    draw = ImageDraw.Draw(img)
    for p in prims:
        if isinstance(p, Poly):
            draw.polygon([v * scale for v in p.points], fill=p.fill)
        elif isinstance(p, Line):
            pts = [v * scale for v in p.points]
            width = max(1, round(p.width * scale))
            if p.dash:
                _dashed(draw, pts, (p.dash[0] * scale, p.dash[1] * scale), p.color, width)
            else:
                draw.line(pts, fill=p.color, width=width, joint="curve")
        elif isinstance(p, Text):
            font = fonts.get(max(1, round(p.size * scale)), p.bold)
            draw.text((p.x * scale, p.y * scale), p.text, fill=p.color, font=font, anchor=PIL_ANCHOR[p.anchor])
    return img


def export_png(chart: Chart, path: str | Path, style: Style | None = None, scale: float = 2.0) -> None:
    render_image(chart, style, scale).save(path)


if __name__ == "__main__":
    # python -m timechart.export input.json output.png
    from .model import load_file

    chart, settings = load_file(sys.argv[1])
    st = Style(cell_w=settings.get("cell_w", 40), show_grid=settings.get("show_grid", True))
    export_png(chart, sys.argv[2], st)
