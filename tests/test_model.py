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
    assert lay.hit(lay.x_of(3.5), lay.rows_top + lay.row_h * 1.5) == ("cell", 1, 3)
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
