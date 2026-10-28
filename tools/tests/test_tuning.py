import struct

import dbpf
import tuning


def read_stbl(data):
    assert data[:4] == b"STBL"
    _, _, count, _, _ = struct.unpack_from("<HBQHI", data, 4)
    pos = 21
    strings = {}
    for _ in range(count):
        key, _, length = struct.unpack_from("<IBH", data, pos)
        pos += 7
        strings[key] = data[pos:pos + length].decode("utf-8")
        pos += length
    return strings


def test_text_only_mod_builds_an_english_string_table(tmp_path):
    mod = tmp_path / "labels"
    (mod / "text").mkdir(parents=True)
    (mod / "text" / "labels.txt").write_text(
        "# a comment\n\nPoorer than the club leader\nSimilar to the club leader\n",
        encoding="utf-8")
    out = tmp_path / "out.package"

    assert tuning.build_package(mod, out, "Test_labels")
    package = dbpf.Package(out)
    tables = [entry for entry in package.entries if entry.type == tuning.STBL_TYPE]
    assert len(tables) == len(tuning.LOCALES)
    strings = read_stbl(package.read(tables[0]))
    assert strings[tuning.string_key("Poorer than the club leader")] == "Poorer than the club leader"
    assert strings[tuning.string_key("Similar to the club leader")] == "Similar to the club leader"
    assert len(strings) == 2


def test_mod_without_tuning_or_text_is_not_built(tmp_path):
    mod = tmp_path / "empty"
    mod.mkdir()
    assert not tuning.build_package(mod, tmp_path / "out.package", "Test_empty")


def test_text_and_tuning_share_the_package(tmp_path):
    mod = tmp_path / "mixed"
    (mod / "tuning").mkdir(parents=True)
    (mod / "text").mkdir()
    (mod / "text" / "labels.txt").write_text("A label\n", encoding="utf-8")
    (mod / "tuning" / "test.xml").write_text(
        '<I c="TestInteraction" i="interaction" n="Test" s="12345">'
        '<T n="pie_menu_name">{{string:A label}}</T></I>',
        encoding="utf-8")
    out = tmp_path / "out.package"

    assert tuning.build_package(mod, out, "Test_mixed")
    package = dbpf.Package(out)
    assert len([entry for entry in package.entries if entry.type == tuning.STBL_TYPE]) == len(tuning.LOCALES)
    strings = read_stbl(package.read(next(
        entry for entry in package.entries if entry.type == tuning.STBL_TYPE)))
    assert strings[tuning.string_key("A label")] == "A label"
