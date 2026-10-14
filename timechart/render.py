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
    margin: float = 16
    axis_h: float = 26
    marker_h: float = 26
    name_gap: float = 18
    title_size: int = 18
    font_size: int = 14
    small_size: int = 12
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
    anchor: str = "w"  # w / e / center / n / s


Primitive = Line | Poly | Text


@dataclass
class Layout:
    """クリック位置の判定に使うレイアウト情報。"""

    x0: float
    cell_w: float
    n_cells: int
    axis_top: float
    axis_bottom: float
    rows_top: float
    row_h: float
    n_rows: int
    width: float
    height: float

    @property
    def rows_bottom(self) -> float:
        return self.rows_top + self.n_rows * self.row_h

    def x_of(self, t: float) -> float:
        return self.x0 + t * self.cell_w

    def row_at(self, y: float) -> int:
        """y 位置の行（範囲外は端に丸める）。"""
        return max(0, min(self.n_rows - 1, int((y - self.rows_top) // self.row_h)))

    def hit(self, x: float, y: float) -> tuple | None:
        if self.axis_top <= y < self.axis_bottom and x >= self.x0 - self.cell_w / 2:
            t = round((x - self.x0) / self.cell_w)
            return ("axis", max(0, min(self.n_cells, t)))
        if self.n_rows and self.rows_top <= y < self.rows_bottom:
            row = int((y - self.rows_top) // self.row_h)
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


def wave_segments(cells: list[Cell]) -> list[list]:
    """セル列を [種類, 開始時刻, 終了時刻, ラベル] の区間に変換する。

    クロック(p/n)は半周期ごとの 0/1 に分解し、同じレベルが続く区間は結合する。
    """
    fine: list[tuple] = []
    for i, c in enumerate(cells):
        if c.state in ("p", "n"):
            a, b = ("1", "0") if c.state == "p" else ("0", "1")
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


def draw_wave(prims: list, cells: list[Cell], x0: float, cw: float, top: float, bot: float,
              style: Style, measure: Measure) -> None:
    mid = (top + bot) / 2
    s = min(4.0, cw / 8)
    segs = wave_segments(cells)
    for j, (kind, t0, t1, label) in enumerate(segs):
        prev = segs[j - 1] if j > 0 else None
        nxt = segs[j + 1] if j + 1 < len(segs) else None
        xa, xb = x0 + t0 * cw, x0 + t1 * cw
        sl = s if prev else 0
        sr = s if nxt else 0
        if kind in ("0", "1"):
            y = top if kind == "1" else bot
            pts: list[float] = []
            if prev and prev[0] not in ("0", "1"):
                pts += [xa, mid]
            pts += [xa + sl, y, xb - sr, y]
            if nxt:
                if nxt[0] in ("0", "1"):
                    pts += [xb + sr, top if nxt[0] == "1" else bot]
                else:
                    pts += [xb, mid]
            prims.append(Line(pts, style.line, 2))
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
    x0 = m + name_w + style.name_gap
    x_end = x0 + n * cw

    y = m
    title_w = 0.0
    if chart.title:
        prims.append(Text(m, y + style.title_size / 2, chart.title, style.text, style.title_size, bold=True))
        title_w = measure(chart.title, style.title_size, True)
        y += style.title_size + 12
    axis_top, axis_bottom = y, y + style.axis_h
    rows_top = axis_bottom + 4
    rows_bottom = rows_top + len(chart.signals) * style.row_h
    height = rows_bottom + (style.marker_h if chart.markers else 6) + m
    width = max(x_end + m + 8, m * 2 + title_w)

    # 行の背景（縞模様）
    for i in range(len(chart.signals)):
        if i % 2 == 0:
            top = rows_top + i * style.row_h
            prims.append(Poly([m / 2, top, x_end + 6, top, x_end + 6, top + style.row_h, m / 2, top + style.row_h],
                              style.zebra))

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
    for i, sig in enumerate(chart.signals):
        cy = rows_top + i * style.row_h + style.row_h / 2
        prims.append(Text(m, cy, sig.name, style.text, style.font_size, bold=True))
        draw_wave(prims, sig.cells(), x0, cw, cy - style.wave_h / 2, cy + style.wave_h / 2, style, measure)

    # マーカー
    for mk in chart.markers:
        if 0 <= mk.time <= n:
            x = x0 + mk.time * cw
            prims.append(Line([x, axis_bottom, x, rows_bottom + 4], style.marker, 1.5, dash=(6, 4)))
            if mk.label:
                prims.append(Text(x, rows_bottom + 6, mk.label, style.marker, style.small_size, bold=True,
                                  anchor="n"))

    layout = Layout(x0, cw, n, axis_top, axis_bottom, rows_top, style.row_h, len(chart.signals), width, height)
    return prims, layout
