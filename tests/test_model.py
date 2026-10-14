import json

import pytest

from timechart.export import render_image
from timechart.model import Cell, Chart, Marker, Signal, clock_wave, load_file, sample_chart, save_file
from timechart.render import Style, build, wave_segments
from timechart.textfmt import ParseError, format_chart, parse_chart


def measure(text, size, bold):
    return len(text) * size * 0.6


@pytest.mark.parametrize("wave,data", [
    ("0.1..0", []),
    ("p.......", []),
    ("x.=.=..x", ["A", "B"]),
    ("==.=", ["A", "A", "B"]),
])
def test_expand_compress_roundtrip(wave, data):
    s = Signal("S", wave, data)
    s.set_cells(s.cells())
    assert (s.wave, s.data) == (wave, data)


def test_clock_wave():
    assert clock_wave(4, 1) == "p..."
    assert clock_wave(8, 2) == "1010" * 2
    assert clock_wave(8, 4) == "1.0.1.0."
    assert clock_wave(6, 4, rising=False) == "0.1.0."


def test_set_cell_pads_and_compresses():
    s = Signal("S", "0...")
    s.set_cell(2, Cell("1"))
    assert s.wave == "0.10"
    s.set_cell(6, Cell("1"))
    assert s.wave == "0.10..1"


def test_bus_value_edit():
    s = Signal("D", "=.....", ["A"])
    s.set_bus_value(3, "B")
    assert (s.wave, s.data) == ("=..=..", ["A", "B"])
    s.set_bus_value(3, "")  # 継続に戻す
    assert (s.wave, s.data) == ("=.....", ["A"])
    s.set_bus_value(0, "Z")  # 先頭を変えると後続の継続も変わる
    assert (s.wave, s.data) == ("=.....", ["Z"])
    s.set_bus_value(2, "x")
    assert (s.wave, s.data) == ("=.x=..", ["Z", "Z"])


def test_insert_delete_cycle():
    c = Chart(signals=[Signal("A", "01"), Signal("D", "=.=", ["a", "b"])], markers=[Marker(2, "t1")])
    c.insert_cycle(1)
    assert c.signals[0].wave == "0.1"
    assert c.signals[1].wave == "=..="
    assert c.markers[0].time == 3
    c.delete_cycle(0)
    assert c.signals[0].wave == "01"
    assert (c.signals[1].wave, c.signals[1].data) == ("=.=", ["a", "b"])
    assert c.markers[0].time == 2


def test_text_roundtrip():
    text = format_chart(sample_chart())
    assert format_chart(parse_chart(text)) == text


def test_parse_details():
    c = parse_chart("# comment\n@title T\nDATA[7:0] : x.=. =. | A, B\nCLK:P...\n@marker 2 t1\n")
    assert c.title == "T"
    assert [(s.name, s.wave, s.data) for s in c.signals] == [
        ("DATA[7:0]", "x.=.=.", ["A", "B"]), ("CLK", "p...", [])]
    assert c.markers == [Marker(2, "t1")]


@pytest.mark.parametrize("text,line", [("A : 01\nB : 0y1\n", 2), ("@marker x\n", 1), ("hello\n", 1), ("A : .1\n", 1)])
def test_parse_errors(text, line):
    with pytest.raises(ParseError) as e:
        parse_chart(text)
    assert e.value.line_no == line


def test_wave_segments_merge_clock_halves():
    segs = wave_segments(Signal("C", "p.1.").cells())
    assert [s[0] for s in segs] == ["1", "0", "1", "0", "1"]
    assert segs[-1][1:3] == [2, 4]


def test_layout_hit():
    _, lay = build(sample_chart(), Style(), measure)
    mid1 = (lay.row_bounds[1] + lay.row_bounds[2]) / 2
    assert lay.hit(lay.x_of(3.5), mid1) == ("cell", 1, 3)
    assert lay.hit(lay.x0 - 5, lay.rows_top + 1) == ("name", 0)
    assert lay.hit(lay.x_of(4.2), lay.axis_top + 1) == ("axis", 4)


def test_save_load_and_render(tmp_path):
    path = tmp_path / "c.json"
    save_file(path, sample_chart(), {"cell_w": 30})
    chart, settings = load_file(path)
    assert chart == sample_chart()
    assert settings == {"cell_w": 30}
    assert json.loads(path.read_text(encoding="utf-8"))["app"] == "time_chart_maker"
    img = render_image(chart, Style(cell_w=30), scale=1)
    assert img.width > 30 * 16


def test_load_rejects_bad_wave(tmp_path):
    path = tmp_path / "bad.json"
    path.write_text(json.dumps({"signals": [{"name": "A", "wave": "01q"}]}), encoding="utf-8")
    with pytest.raises(ValueError):
        load_file(path)


def test_multi_level_text_roundtrip():
    c = parse_chart("LEVEL : 0.2.5.3. | max=5\nAUTO : 0.3.\nSMALL : 0.2. | max=3\n")
    assert [(s.wave, s.max_level, s.data) for s in c.signals] == [
        ("0.2.5.3.", 5, []), ("0.3.", 5, []), ("0.2.", 3, [])]
    text = format_chart(c)
    assert "AUTO  : 0.3. | max=5" in text
    assert format_chart(parse_chart(text)) == text


@pytest.mark.parametrize("text", ["A : 0.6. | max=5\n", "A : 0. | max=10\n", "A : =.3. | X\n"])
def test_multi_level_errors(text):
    with pytest.raises(ParseError):
        parse_chart(text)


def test_set_max_level_clamps():
    s = Signal("L", "0.5.3.", max_level=5)
    s.set_max_level(3)
    assert (s.wave, s.max_level) == ("0.3...", 3)


def test_multi_level_layout_and_render(tmp_path):
    chart = Chart(signals=[Signal("A", "01"), Signal("L", "0525", max_level=5)])
    prims, lay = build(chart, Style(), measure)
    top, bot = lay.waves[1]
    assert bot - top > lay.waves[0][1] - lay.waves[0][0]  # 多値の行は高い
    assert lay.level_at(1, top, 5) == 5
    assert lay.level_at(1, bot, 5) == 0
    assert lay.level_at(1, (top + bot) / 2, 4) == 2
    assert lay.nearest_boundary(lay.rows_bottom + 50) == 2
    texts = [p.text for p in prims if hasattr(p, "text")]
    assert {"0", "5", "2"} <= set(texts)  # 左側の一覧と区間の値
    path = tmp_path / "m.json"
    save_file(path, chart)
    assert load_file(path)[0] == chart


def test_level_names_text_roundtrip():
    c = parse_chart("L : 0.2.5. | max=5, 0=停止, 2=低速, 5=高速\nB : 0.3. | 0=OFF\n")
    assert c.signals[0].level_names == {0: "停止", 2: "低速", 5: "高速"}
    assert (c.signals[1].max_level, c.signals[1].level_names) == (5, {0: "OFF"})
    text = format_chart(c)
    assert "L : 0.2.5. | max=5, 0=停止, 2=低速, 5=高速" in text
    assert format_chart(parse_chart(text)) == text
    with pytest.raises(ParseError):
        parse_chart("L : 0.2. | max=3, 4=過大\n")


def test_level_names_model_and_render(tmp_path):
    s = Signal("L", "0.5.", max_level=5, level_names={0: "停止", 5: "高速"})
    assert s.level_label(5) == "5:高速" and s.level_label(3) == "3"
    s.set_max_level(3)
    assert s.level_names == {0: "停止"}
    chart = Chart(signals=[Signal("L", "0...2...", max_level=5, level_names={0: "停止", 2: "低速"})])
    path = tmp_path / "n.json"
    save_file(path, chart)
    assert load_file(path)[0] == chart
    texts = [p.text for p in build(chart, Style(cell_w=40), measure)[0] if hasattr(p, "text")]
    assert "0 停止" in texts and "2 低速" in texts  # 左側の一覧
    assert "0:停止" in texts and "2:低速" in texts  # 区間の表示
    narrow = [p.text for p in build(chart, Style(cell_w=6), measure)[0] if hasattr(p, "text")]
    assert "2:低速" not in narrow  # 狭いと数字だけ（または非表示）
