"""LRC 解析测试：标准/多标签/双语配对/乱序/非法行/offset/词级标签。"""

from app.core.lrc import parse_lrc


def test_standard_parse():
    doc = parse_lrc("[00:01.00]Hello\n[00:05.50]World\n")
    assert [line.time for line in doc.lines] == [1.0, 5.5]
    assert [line.text for line in doc.lines] == ["Hello", "World"]


def test_time_formats():
    doc = parse_lrc("[00:01]A\n[00:02.5]B\n[00:03.25]C\n[01:10.123]D\n")
    assert [line.time for line in doc.lines] == [1.0, 2.5, 3.25, 70.123]


def test_multiple_tags_one_line():
    doc = parse_lrc("[00:01.00][00:10.00]Repeat\n")
    assert [line.time for line in doc.lines] == [1.0, 10.0]
    assert doc.lines[0].text == "Repeat"


def test_bilingual_pairing_same_timestamp():
    doc = parse_lrc("[00:01.00]Hello\n[00:01.00]你好\n[00:05.00]Next\n")
    assert len(doc.lines) == 2
    assert doc.lines[0].text == "Hello"
    assert doc.lines[0].translation == "你好"
    assert doc.lines[1].text == "Next"
    assert doc.lines[1].translation is None


def test_bilingual_pairing_tolerance():
    doc = parse_lrc("[00:01.000]Main\n[00:01.049]Sub\n")
    assert len(doc.lines) == 1
    assert doc.lines[0].translation == "Sub"


def test_no_pairing_beyond_tolerance():
    doc = parse_lrc("[00:01.000]Main\n[00:01.051]Sub\n")
    assert len(doc.lines) == 2


def test_out_of_order_sorted():
    doc = parse_lrc("[00:10.00]Late\n[00:01.00]Early\n")
    assert [line.text for line in doc.lines] == ["Early", "Late"]


def test_illegal_lines_ignored():
    doc = parse_lrc("no tags here\n[abc]bad\n[00:x.y]bad\n[00:01.00]Good\n\n")
    assert len(doc.lines) == 1
    assert doc.lines[0].text == "Good"


def test_offset_applied():
    doc = parse_lrc("[offset:500]\n[00:01.00]A\n")
    assert doc.lines[0].time == 1.5


def test_offset_last_tag_wins_and_clamped():
    doc = parse_lrc("[offset:500]\n[00:01.00]A\n[offset:-1000]\n")
    assert doc.lines[0].time == 0.0  # 最后一个 offset 生效，负移位 clamp 到 0


def test_offset_invalid_ignored():
    doc = parse_lrc("[offset:abc]\n[00:01.00]A\n")
    assert doc.lines[0].time == 1.0


def test_metadata_tags():
    doc = parse_lrc("[ti:标题]\n[ar:歌手]\n[al:专辑]\n[00:01.00]A\n")
    assert doc.title == "标题"
    assert doc.artist == "歌手"
    assert doc.album == "专辑"


def test_word_tags_stripped_and_parsed():
    doc = parse_lrc("[00:10.00]<00:10.00>Word <00:11.00>next\n")
    line = doc.lines[0]
    assert "<" not in line.text
    assert line.words is not None and len(line.words) == 2
    assert line.words[0].text == "Word"
    assert line.words[0].start == 10.0
    assert line.words[1].end is None


def test_malformed_word_tags_tolerated():
    doc = parse_lrc("[00:10.00]<bad>text\n")
    assert doc.lines[0].text == "<bad>text"  # 不崩溃；仅剥离合法词级标签


def test_empty_input():
    doc = parse_lrc("")
    assert doc.lines == []
