"""Tkinter GUI。

上段: タイムチャート（クリックで編集）
下段: テキスト記法エディタ（編集すると上段に即時反映）
"""
from __future__ import annotations

import sys
import tkinter as tk
import tkinter.font as tkfont
from pathlib import Path
from tkinter import filedialog, messagebox, simpledialog, ttk

from .export import export_png
from .model import Cell, Chart, Signal, clock_wave, load_file, sample_chart, save_file
from .render import Line, Poly, Style, Text, build
from .textfmt import ParseError, format_chart, parse_chart

APP_NAME = "Time Chart Maker"
HINT = ("クリック: High/Low 切替（ドラッグで連続入力）　バス行: クリックで値入力　"
        "右クリック: メニュー　目盛りクリック: マーカー追加/削除　信号名ドラッグ: 並べ替え")
NOTATION_HELP = """記法:  名前 : 波形 | バス値, ...
  0 Low   1 High   x 不定
  p/n クロック(1 サイクル)
  = バス値   . 継続
  @title タイトル
  @marker 時刻 ラベル
  # コメント"""


def _pick_family(root: tk.Misc, candidates: list[str], fallback: str) -> str:
    families = set(tkfont.families(root))
    return next((f for f in candidates if f in families), fallback)


class ClockDialog(simpledialog.Dialog):
    def __init__(self, parent: tk.Misc, default_name: str):
        self.default_name = default_name
        super().__init__(parent, "クロックを追加")

    def body(self, master: tk.Frame):
        ttk.Label(master, text="名前").grid(row=0, column=0, sticky="w", padx=4, pady=4)
        self.name_var = tk.StringVar(value=self.default_name)
        name_entry = ttk.Entry(master, textvariable=self.name_var, width=16)
        name_entry.grid(row=0, column=1, sticky="we", padx=4, pady=4)

        ttk.Label(master, text="周期（サイクル数）").grid(row=1, column=0, sticky="w", padx=4, pady=4)
        self.period_var = tk.IntVar(value=1)
        ttk.Spinbox(master, from_=1, to=64, textvariable=self.period_var, width=6).grid(
            row=1, column=1, sticky="w", padx=4, pady=4)
        ttk.Label(master, text="1 = 1 サイクルごとに 1 周期", foreground="#6b7280").grid(
            row=2, column=1, sticky="w", padx=4)

        self.rising_var = tk.BooleanVar(value=True)
        ttk.Radiobutton(master, text="High から開始", variable=self.rising_var, value=True).grid(
            row=3, column=1, sticky="w", padx=4)
        ttk.Radiobutton(master, text="Low から開始", variable=self.rising_var, value=False).grid(
            row=4, column=1, sticky="w", padx=4)
        return name_entry

    def validate(self) -> bool:
        try:
            ok = self.period_var.get() >= 1
        except tk.TclError:
            ok = False
        if not ok:
            messagebox.showwarning("入力エラー", "周期は 1 以上の整数で入力してください", parent=self)
        return ok

    def apply(self) -> None:
        self.result = (self.name_var.get().strip() or "CLK", self.period_var.get(), self.rising_var.get())


class App(tk.Tk):
    def __init__(self, path: str | None = None):
        super().__init__()
        self.geometry("1180x760")
        self.minsize(720, 480)

        self.ui_family = _pick_family(self, ["Meiryo UI", "Meiryo", "Yu Gothic UI", "Hiragino Sans",
                                             "Noto Sans CJK JP"], "TkDefaultFont")
        self.mono_family = _pick_family(self, ["BIZ UDGothic", "MS Gothic", "Osaka-Mono", "Noto Sans Mono CJK JP",
                                               "Consolas"], "TkFixedFont")
        self._fonts: dict = {}

        self.chart: Chart = sample_chart()
        self.style_ = Style()
        self.path: Path | None = None
        self.layout = None

        self.history: list[str] = []
        self.hpos = -1
        self.saved_text = ""
        self._editor_known = ""
        self._parse_job: str | None = None
        self._paint: dict | None = None
        self._row_drag: dict | None = None

        self.cell_w_var = tk.IntVar(value=int(self.style_.cell_w))
        self.grid_var = tk.BooleanVar(value=self.style_.show_grid)
        self.len_var = tk.IntVar(value=self.chart.length)
        self.status_var = tk.StringVar(value=HINT)

        self._build_menu()
        self._build_ui()
        self._bind_keys()
        self.protocol("WM_DELETE_WINDOW", self.on_quit)

        if path:
            self.open_path(Path(path))
        else:
            self._reset_history()
            self.saved_text = self.history[0]
            self.refresh(editor=True)

    # ------------------------------------------------------------------ UI
    def _build_menu(self) -> None:
        bar = tk.Menu(self)
        m = tk.Menu(bar, tearoff=False)
        m.add_command(label="新規", accelerator="Ctrl+N", command=self.on_new)
        m.add_command(label="開く...", accelerator="Ctrl+O", command=self.on_open)
        m.add_command(label="保存", accelerator="Ctrl+S", command=self.on_save)
        m.add_command(label="名前を付けて保存...", accelerator="Ctrl+Shift+S", command=self.on_save_as)
        m.add_separator()
        m.add_command(label="PNG 出力...", accelerator="Ctrl+E", command=self.on_export)
        m.add_separator()
        m.add_command(label="終了", command=self.on_quit)
        bar.add_cascade(label="ファイル", menu=m)

        m = tk.Menu(bar, tearoff=False)
        m.add_command(label="元に戻す", accelerator="Ctrl+Z", command=self.undo)
        m.add_command(label="やり直し", accelerator="Ctrl+Y", command=self.redo)
        m.add_separator()
        m.add_command(label="タイトルを変更...", command=self.on_title)
        bar.add_cascade(label="編集", menu=m)

        m = tk.Menu(bar, tearoff=False)
        m.add_command(label="信号を追加", command=self.add_signal)
        m.add_command(label="バスを追加", command=self.add_bus)
        m.add_command(label="クロックを追加...", command=self.add_clock)
        m.add_separator()
        m.add_command(label="マーカーを追加...", command=self.add_marker)
        bar.add_cascade(label="挿入", menu=m)
        self.config(menu=bar)

    def _build_ui(self) -> None:
        tb = ttk.Frame(self, padding=(6, 4))
        tb.pack(side="top", fill="x")
        ttk.Button(tb, text="＋信号", command=self.add_signal).pack(side="left")
        ttk.Button(tb, text="＋バス", command=self.add_bus).pack(side="left", padx=(4, 0))
        ttk.Button(tb, text="＋クロック", command=self.add_clock).pack(side="left", padx=(4, 0))
        ttk.Button(tb, text="＋マーカー", command=self.add_marker).pack(side="left", padx=(4, 0))
        ttk.Separator(tb, orient="vertical").pack(side="left", fill="y", padx=10)

        ttk.Label(tb, text="サイクル数").pack(side="left")
        sp = ttk.Spinbox(tb, from_=1, to=999, width=5, textvariable=self.len_var, command=self.on_length)
        sp.pack(side="left", padx=(4, 0))
        sp.bind("<Return>", lambda e: self.on_length())
        sp.bind("<FocusOut>", lambda e: self.on_length())

        ttk.Label(tb, text="セル幅").pack(side="left", padx=(12, 0))
        ttk.Scale(tb, from_=12, to=120, variable=self.cell_w_var, length=140,
                  command=lambda v: self.on_view_change()).pack(side="left", padx=(4, 0))
        ttk.Checkbutton(tb, text="補助線", variable=self.grid_var, command=self.on_view_change).pack(
            side="left", padx=(12, 0))
        ttk.Button(tb, text="PNG 出力", command=self.on_export).pack(side="right")

        status = tk.Label(self, textvariable=self.status_var, anchor="w", padx=8, fg="#374151", bg="#f3f4f6")
        status.pack(side="bottom", fill="x")
        self.status_label = status

        paned = ttk.Panedwindow(self, orient="vertical")
        paned.pack(fill="both", expand=True)

        cf = ttk.Frame(paned)
        self.canvas = tk.Canvas(cf, background=self.style_.background, highlightthickness=0)
        xs = ttk.Scrollbar(cf, orient="horizontal", command=self.canvas.xview)
        ys = ttk.Scrollbar(cf, orient="vertical", command=self.canvas.yview)
        self.canvas.configure(xscrollcommand=xs.set, yscrollcommand=ys.set)
        self.canvas.grid(row=0, column=0, sticky="nsew")
        ys.grid(row=0, column=1, sticky="ns")
        xs.grid(row=1, column=0, sticky="ew")
        cf.rowconfigure(0, weight=1)
        cf.columnconfigure(0, weight=1)
        paned.add(cf, weight=3)

        ef = ttk.Frame(paned)
        self.editor = tk.Text(ef, height=9, undo=False, wrap="none", font=(self.mono_family, 11),
                              padx=6, pady=4)
        eys = ttk.Scrollbar(ef, orient="vertical", command=self.editor.yview)
        self.editor.configure(yscrollcommand=eys.set)
        self.editor.grid(row=0, column=0, sticky="nsew")
        eys.grid(row=0, column=1, sticky="ns")
        tk.Label(ef, text=NOTATION_HELP, justify="left", anchor="nw", font=(self.mono_family, 10),
                 fg="#4b5563", padx=10).grid(row=0, column=2, sticky="nw")
        ef.rowconfigure(0, weight=1)
        ef.columnconfigure(0, weight=1)
        self.editor.tag_configure("error", background="#fee2e2")
        paned.add(ef, weight=1)

        c = self.canvas
        c.bind("<ButtonPress-1>", self.on_press)
        c.bind("<B1-Motion>", self.on_motion)
        c.bind("<ButtonRelease-1>", self.on_release)
        c.bind("<Double-Button-1>", self.on_double)
        c.bind("<Button-3>", self.on_right)
        c.bind("<Motion>", self.on_hover)
        c.bind("<MouseWheel>", self.on_wheel)
        c.bind("<Shift-MouseWheel>", lambda e: c.xview_scroll(-1 if e.delta > 0 else 1, "units"))
        c.bind("<Control-MouseWheel>", self.on_zoom)
        self.editor.bind("<<Modified>>", self.on_editor_modified)

    def _bind_keys(self) -> None:
        keys = [("<Control-n>", self.on_new), ("<Control-o>", self.on_open), ("<Control-s>", self.on_save),
                ("<Control-S>", self.on_save_as), ("<Control-e>", self.on_export),
                ("<Control-z>", self.undo), ("<Control-y>", self.redo)]
        # エディタにも直接割り当て、Text 標準のキー操作（Ctrl+O で改行など）より優先する
        for widget in (self, self.editor):
            for seq, fn in keys:
                widget.bind(seq, lambda e, f=fn: (f(), "break")[1])

    # ------------------------------------------------------------ 描画
    def _font(self, size: int, bold: bool) -> tkfont.Font:
        key = (size, bold)
        if key not in self._fonts:
            self._fonts[key] = tkfont.Font(self, family=self.ui_family, size=-size,
                                           weight="bold" if bold else "normal")
        return self._fonts[key]

    def _measure(self, text: str, size: int, bold: bool) -> float:
        return self._font(size, bold).measure(text)

    def redraw(self) -> None:
        self.style_.cell_w = self.cell_w_var.get()
        self.style_.show_grid = self.grid_var.get()
        prims, self.layout = build(self.chart, self.style_, self._measure)
        c = self.canvas
        c.delete("all")
        for p in prims:
            if isinstance(p, Poly):
                c.create_polygon(*p.points, fill=p.fill, outline="")
            elif isinstance(p, Line):
                c.create_line(*p.points, fill=p.color, width=p.width, dash=p.dash or "",
                              capstyle="round", joinstyle="round")
            elif isinstance(p, Text):
                c.create_text(p.x, p.y, text=p.text, fill=p.color, anchor=p.anchor, font=self._font(p.size, p.bold))
        c.configure(scrollregion=(0, 0, self.layout.width, self.layout.height))

    def refresh(self, editor: bool = True) -> None:
        """モデルの内容を画面に反映する。editor=True ならテキストも書き換える。"""
        self.redraw()
        if editor:
            self._set_editor_text(format_chart(self.chart))
        self.len_var.set(self.chart.length)
        self._update_title()

    def _len_valid(self) -> bool:
        try:
            self.len_var.get()
            return True
        except tk.TclError:
            return False

    def _set_editor_text(self, text: str) -> None:
        self._editor_known = text
        if self.editor.get("1.0", "end-1c") == text:
            return
        insert = self.editor.index("insert")
        top = self.editor.yview()[0]
        self.editor.delete("1.0", "end")
        self.editor.insert("1.0", text)
        self.editor.mark_set("insert", insert)
        self.editor.yview_moveto(top)
        self.editor.tag_remove("error", "1.0", "end")

    def _update_title(self) -> None:
        name = self.path.name if self.path else "無題"
        mark = " *" if self.is_dirty() else ""
        self.title(f"{name}{mark} - {APP_NAME}")

    def set_status(self, text: str, error: bool = False) -> None:
        self.status_var.set(text)
        self.status_label.configure(fg="#b91c1c" if error else "#374151")

    # ------------------------------------------------------------ 履歴
    def _reset_history(self) -> None:
        self.history = [format_chart(self.chart)]
        self.hpos = 0

    def commit(self, editor: bool = True) -> None:
        """モデルの変更を確定し、履歴に積んで画面を更新する。"""
        text = format_chart(self.chart)
        if text != self.history[self.hpos]:
            del self.history[self.hpos + 1:]
            self.history.append(text)
            self.hpos += 1
        self.refresh(editor=editor)

    def _restore(self) -> None:
        self.chart = parse_chart(self.history[self.hpos])
        self.set_status(HINT)
        self.refresh(editor=True)

    def undo(self) -> None:
        self._flush_editor()
        if self.hpos > 0:
            self.hpos -= 1
            self._restore()

    def redo(self) -> None:
        if self.hpos + 1 < len(self.history):
            self.hpos += 1
            self._restore()

    def is_dirty(self) -> bool:
        return bool(self.history) and self.history[self.hpos] != self.saved_text

    # ------------------------------------------------------------ テキスト編集
    def on_editor_modified(self, _event=None) -> None:
        if not self.editor.edit_modified():
            return
        self.editor.edit_modified(False)
        if self._parse_job:
            self.after_cancel(self._parse_job)
        self._parse_job = self.after(300, self._apply_editor)

    def _flush_editor(self) -> None:
        if self._parse_job:
            self.after_cancel(self._parse_job)
            self._apply_editor()

    def _apply_editor(self) -> None:
        self._parse_job = None
        text = self.editor.get("1.0", "end-1c")
        if text == self._editor_known:
            return
        self._editor_known = text
        self.editor.tag_remove("error", "1.0", "end")
        try:
            chart = parse_chart(text)
        except ParseError as e:
            self.editor.tag_add("error", f"{e.line_no}.0", f"{e.line_no}.end")
            self.set_status(str(e), error=True)
            return
        self.chart = chart
        self.set_status(HINT)
        self.commit(editor=False)

    # ------------------------------------------------------------ マウス操作
    def _xy(self, event) -> tuple[float, float]:
        return self.canvas.canvasx(event.x), self.canvas.canvasy(event.y)

    def _hit(self, event):
        if not self.layout:
            return None
        return self.layout.hit(*self._xy(event))

    def on_press(self, event) -> None:
        self._flush_editor()
        hit = self._hit(event)
        if not hit:
            return
        if hit[0] == "cell":
            _, row, t = hit
            sig = self.chart.signals[row]
            if sig.is_bus:
                self.edit_bus_value(row, t)
                return
            cells = sig.cells()
            cur = cells[t].state if t < len(cells) else "0"
            value = "0" if cur in ("1", "p", "n") else "1"
            self._paint = {"row": row, "value": value, "last": None}
            self._paint_at(t)
        elif hit[0] == "name":
            self._row_drag = {"row": hit[1], "target": hit[1]}
        elif hit[0] == "axis":
            t = hit[1]
            exists = any(m.time == t for m in self.chart.markers)
            label = "" if exists else simpledialog.askstring(
                "マーカー", f"時刻 {t} のマーカー名", initialvalue=self.chart.next_marker_label(), parent=self)
            if exists or label is not None:
                self.chart.toggle_marker(t, (label or "").strip())
                self.commit()

    def _paint_at(self, t: int) -> None:
        p = self._paint
        if p["last"] == t:
            return
        p["last"] = t
        sig = self.chart.signals[p["row"]]
        cells = sig.cells()
        if t < len(cells) and cells[t].state == p["value"]:
            return
        sig.set_cell(t, Cell(p["value"]))
        self.redraw()

    def on_motion(self, event) -> None:
        x, y = self._xy(event)
        if self._paint and self.layout:
            t = int((x - self.layout.x0) // self.layout.cell_w)
            if 0 <= t < self.layout.n_cells:
                self._paint_at(t)
        elif self._row_drag and self.layout:
            lay = self.layout
            target = max(0, min(lay.n_rows, round((y - lay.rows_top) / lay.row_h)))
            self._row_drag["target"] = target
            self.canvas.delete("dragline")
            yy = lay.rows_top + target * lay.row_h
            self.canvas.create_line(4, yy, lay.width, yy, fill="#2563eb", width=3, tags="dragline")

    def on_release(self, _event) -> None:
        if self._paint:
            self._paint = None
            self.commit()
        elif self._row_drag:
            self.canvas.delete("dragline")
            row, target = self._row_drag["row"], self._row_drag["target"]
            self._row_drag = None
            if target not in (row, row + 1):
                sig = self.chart.signals.pop(row)
                self.chart.signals.insert(target - 1 if target > row else target, sig)
                self.commit()

    def on_double(self, event) -> None:
        hit = self._hit(event)
        if hit and hit[0] == "name":
            self._row_drag = None
            self.rename_signal(hit[1])

    def on_hover(self, event) -> None:
        hit = self._hit(event)
        cursor = ""
        if hit:
            cursor = {"cell": "hand2", "name": "fleur", "axis": "plus"}.get(hit[0], "")
        self.canvas.configure(cursor=cursor)

    def on_wheel(self, event) -> None:
        self.canvas.yview_scroll(-1 if event.delta > 0 else 1, "units")

    def on_zoom(self, event) -> None:
        w = self.cell_w_var.get() + (4 if event.delta > 0 else -4)
        self.cell_w_var.set(max(12, min(120, w)))
        self.on_view_change()

    def on_right(self, event) -> None:
        self._flush_editor()
        hit = self._hit(event)
        if not hit:
            return
        menu = tk.Menu(self, tearoff=False)
        if hit[0] == "cell":
            _, row, t = hit
            sig = self.chart.signals[row]

            def setc(state: str):
                sig.set_cell(t, Cell(state))
                self.commit()

            menu.add_command(label="High (1)", command=lambda: setc("1"))
            menu.add_command(label="Low (0)", command=lambda: setc("0"))
            menu.add_command(label="不定 (x)", command=lambda: setc("x"))
            menu.add_command(label="クロック 立ち上がり (p)", command=lambda: setc("p"))
            menu.add_command(label="クロック 立ち下がり (n)", command=lambda: setc("n"))
            menu.add_command(label="バス値...", command=lambda: self.edit_bus_value(row, t))
            menu.add_separator()
            menu.add_command(label=f"{t} サイクル目の前に 1 サイクル挿入",
                             command=lambda: (self.chart.insert_cycle(t), self.commit()))
            menu.add_command(label=f"{t} サイクル目を削除",
                             command=lambda: (self.chart.delete_cycle(t), self.commit()))
            menu.add_separator()
            self._add_signal_items(menu, row)
        elif hit[0] == "name":
            self._add_signal_items(menu, hit[1])
        elif hit[0] == "axis":
            t = hit[1]
            mk = next((m for m in self.chart.markers if m.time == t), None)
            if mk:
                menu.add_command(label=f"マーカー「{mk.label}」の名前を変更...", command=lambda: self.rename_marker(mk))
                menu.add_command(label="マーカーを削除",
                                 command=lambda: (self.chart.markers.remove(mk), self.commit()))
            else:
                menu.add_command(label=f"時刻 {t} にマーカーを追加...", command=lambda: self.add_marker(t))
        menu.tk_popup(event.x_root, event.y_root)

    def _add_signal_items(self, menu: tk.Menu, row: int) -> None:
        n = len(self.chart.signals)
        menu.add_command(label="名前を変更...", command=lambda: self.rename_signal(row))
        menu.add_command(label="上へ移動", state="normal" if row > 0 else "disabled",
                         command=lambda: self.move_signal(row, -1))
        menu.add_command(label="下へ移動", state="normal" if row < n - 1 else "disabled",
                         command=lambda: self.move_signal(row, 1))
        menu.add_command(label="複製", command=lambda: self.duplicate_signal(row))
        menu.add_command(label="削除", command=lambda: self.delete_signal(row))

    # ------------------------------------------------------------ 編集操作
    def edit_bus_value(self, row: int, t: int) -> None:
        sig = self.chart.signals[row]
        cells = sig.cells()
        current = cells[t].label if t < len(cells) and cells[t].state == "=" else ""
        value = simpledialog.askstring(
            "バス値", f"{sig.name} / {t} サイクル目の値\n（空欄: 前の値を継続、x: 不定）",
            initialvalue=current, parent=self)
        if value is None:
            return
        sig.set_bus_value(t, value)
        self.commit()

    def _unique_name(self, base: str) -> str:
        names = {s.name for s in self.chart.signals}
        if base not in names:
            return base
        i = 2
        while f"{base}{i}" in names:
            i += 1
        return f"{base}{i}"

    def _length_or_default(self) -> int:
        return self.chart.length or 16

    def add_signal(self) -> None:
        n = self._length_or_default()
        self.chart.signals.append(Signal(self._unique_name("SIG"), "0" + "." * (n - 1)))
        self.commit()

    def add_bus(self) -> None:
        n = self._length_or_default()
        self.chart.signals.append(Signal(self._unique_name("BUS"), "=" + "." * (n - 1), ["A"]))
        self.commit()

    def add_clock(self) -> None:
        dlg = ClockDialog(self, self._unique_name("CLK"))
        if not dlg.result:
            return
        name, period, rising = dlg.result
        self.chart.signals.append(Signal(name, clock_wave(self._length_or_default(), period, rising)))
        self.commit()

    def add_marker(self, time: int | None = None) -> None:
        if time is None:
            time = simpledialog.askinteger("マーカー", "時刻（サイクル境界の番号）", minvalue=0,
                                           maxvalue=max(self.chart.length, 0), parent=self)
            if time is None:
                return
        label = simpledialog.askstring("マーカー", f"時刻 {time} のマーカー名",
                                       initialvalue=self.chart.next_marker_label(), parent=self)
        if label is None:
            return
        self.chart.markers = [m for m in self.chart.markers if m.time != time]
        self.chart.toggle_marker(time, label.strip())
        self.commit()

    def rename_marker(self, mk) -> None:
        label = simpledialog.askstring("マーカー", "マーカー名", initialvalue=mk.label, parent=self)
        if label is not None:
            mk.label = label.strip()
            self.commit()

    def rename_signal(self, row: int) -> None:
        sig = self.chart.signals[row]
        name = simpledialog.askstring("名前を変更", "信号名", initialvalue=sig.name, parent=self)
        if name is None or not name.strip():
            return
        if name.strip()[0] in "@#":
            messagebox.showwarning(APP_NAME, "信号名の先頭に @ や # は使えません", parent=self)
            return
        sig.name = name.strip()
        self.commit()

    def move_signal(self, row: int, delta: int) -> None:
        s = self.chart.signals
        s[row], s[row + delta] = s[row + delta], s[row]
        self.commit()

    def duplicate_signal(self, row: int) -> None:
        src = self.chart.signals[row]
        self.chart.signals.insert(row + 1, Signal(self._unique_name(src.name), src.wave, list(src.data)))
        self.commit()

    def delete_signal(self, row: int) -> None:
        del self.chart.signals[row]
        self.commit()

    def on_title(self) -> None:
        title = simpledialog.askstring("タイトル", "チャートのタイトル", initialvalue=self.chart.title, parent=self)
        if title is not None:
            self.chart.title = title.strip()
            self.commit()

    def on_length(self) -> None:
        if not self._len_valid():
            self.len_var.set(self.chart.length)
            return
        n = max(1, min(999, self.len_var.get()))
        if n != self.chart.length:
            self.chart.set_length(n)
            self.commit()

    def on_view_change(self) -> None:
        self.redraw()

    # ------------------------------------------------------------ ファイル
    def _settings(self) -> dict:
        return {"cell_w": self.cell_w_var.get(), "show_grid": self.grid_var.get()}

    def _confirm_discard(self) -> bool:
        self._flush_editor()
        if not self.is_dirty():
            return True
        ans = messagebox.askyesnocancel(APP_NAME, "変更を保存しますか？", parent=self)
        if ans is None:
            return False
        return self.on_save() if ans else True

    def on_new(self) -> None:
        if not self._confirm_discard():
            return
        self.chart = Chart(signals=[Signal("CLK", clock_wave(16, 1)), Signal("SIG", "0" + "." * 15)])
        self.path = None
        self._reset_history()
        self.saved_text = self.history[0]
        self.refresh()

    def on_open(self) -> None:
        if not self._confirm_discard():
            return
        name = filedialog.askopenfilename(parent=self, filetypes=[("タイムチャート", "*.json"), ("すべて", "*.*")])
        if name:
            self.open_path(Path(name))

    def open_path(self, path: Path) -> None:
        try:
            chart, settings = load_file(path)
        except Exception as e:  # noqa: BLE001 - 読込失敗はすべてユーザーに伝える
            messagebox.showerror(APP_NAME, f"ファイルを開けませんでした:\n{e}", parent=self)
            if not self.history:
                self._reset_history()
                self.refresh()
            return
        self.chart = chart
        self.path = path
        self.cell_w_var.set(int(settings.get("cell_w", self.cell_w_var.get())))
        self.grid_var.set(bool(settings.get("show_grid", self.grid_var.get())))
        self._reset_history()
        self.saved_text = self.history[0]
        self.refresh()
        self.set_status(f"開きました: {path}")

    def on_save(self) -> bool:
        if self.path is None:
            return self.on_save_as()
        self._flush_editor()
        try:
            save_file(self.path, self.chart, self._settings())
        except OSError as e:
            messagebox.showerror(APP_NAME, f"保存できませんでした:\n{e}", parent=self)
            return False
        self.saved_text = self.history[self.hpos]
        self._update_title()
        self.set_status(f"保存しました: {self.path}")
        return True

    def on_save_as(self) -> bool:
        name = filedialog.asksaveasfilename(parent=self, defaultextension=".json",
                                            filetypes=[("タイムチャート", "*.json")],
                                            initialfile=self.path.name if self.path else "timechart.json")
        if not name:
            return False
        self.path = Path(name)
        return self.on_save()

    def on_export(self) -> None:
        self._flush_editor()
        initial = (self.path.stem if self.path else "timechart") + ".png"
        name = filedialog.asksaveasfilename(parent=self, defaultextension=".png",
                                            filetypes=[("PNG 画像", "*.png")], initialfile=initial)
        if not name:
            return
        try:
            export_png(self.chart, name, Style(cell_w=self.cell_w_var.get(), show_grid=self.grid_var.get()))
        except OSError as e:
            messagebox.showerror(APP_NAME, f"PNG を出力できませんでした:\n{e}", parent=self)
            return
        self.set_status(f"PNG を出力しました: {name}")

    def on_quit(self) -> None:
        if self._confirm_discard():
            self.destroy()


def main() -> None:
    try:  # Windows の高 DPI 対応（ぼやけ防止）
        import ctypes
        ctypes.windll.shcore.SetProcessDpiAwareness(1)
    except Exception:  # noqa: BLE001
        pass
    App(sys.argv[1] if len(sys.argv) > 1 else None).mainloop()


if __name__ == "__main__":
    main()
