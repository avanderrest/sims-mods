"""Compiles a mod's tuning XML into a .package, so pie-menu and phone entries can be made
without Sims 4 Studio. Used by build.py:

  mods/<name>/tuning/*.xml  -> build/<creator>_<name>.package

Each file is one tuning instance in the game's own format (<I c=... i="interaction" n=... s=...>).
Text shown in the game is written inline as {{string:Pay Off Debt}}: the build turns each one
into a string-table key (a hash of the text) and adds the text to a string table, copied
into every game language so it shows whatever language the game is set to.
"""
import re
from pathlib import Path

import dbpf

# Tuning resource types, by the i="..." attribute of the instance.
# The last three are also used by tools/scenario_export.py for the Scenarios menu.
TUNING_TYPES = {
    "interaction": 0xE882D22F,
    "snippet": 0x7DF2169C,
    "situation_goal": 1502554343,   # Types.SITUATION_GOAL
    "action": 209137191,            # Types.ACTION (LootActions)
}
STBL_TYPE = 0x220557DA
STBL_GROUP = 0x80000000
LOCALES = range(0x00, 0x13)   # every language code the game uses (English is 0x00)

_STRING = re.compile(r"\{\{string:(.+?)\}\}")
_INSTANCE = re.compile(r'<I\b[^>]*\bi="([^"]+)"[^>]*\bs="(\d+)"')


def fnv32(text):
    h = 0x811C9DC5
    for b in text.lower().encode("utf-8"):
        h = (h * 0x01000193) & 0xFFFFFFFF
        h ^= b
    return h


def fnv64(text):
    h = 0xCBF29CE484222325
    for b in text.lower().encode("utf-8"):
        h = (h * 0x100000001B3) & 0xFFFFFFFFFFFFFFFF
        h ^= b
    return h


def string_key(text):
    return fnv32(text)


def stbl(strings):
    """A string table (STBL version 5) for {key: text}."""
    import struct
    entries = bytearray()
    total = 0
    for key, text in sorted(strings.items()):
        data = text.encode("utf-8")
        entries += struct.pack("<IBH", key, 0, len(data)) + data
        total += len(data) + 1
    return b"STBL" + struct.pack("<HBQHI", 5, 0, len(strings), 0, total) + bytes(entries)


def compile_xml(text, strings):
    """Replaces {{string:...}} with string keys (collecting them in `strings`).
    Returns (resource type, instance id, bytes)."""
    def to_key(match):
        key = string_key(match.group(1))
        strings[key] = match.group(1)
        return "0x{:08X}".format(key)
    text = _STRING.sub(to_key, text)
    m = _INSTANCE.search(text)
    if m is None or m.group(1) not in TUNING_TYPES:
        raise ValueError("no <I i=... s=...> instance of a known type ({})".format(", ".join(TUNING_TYPES)))
    return TUNING_TYPES[m.group(1)], int(m.group(2)), text.encode("utf-8")


def build_package(mod_dir, out_file, package_name):
    files = sorted((Path(mod_dir) / "tuning").glob("*.xml"))
    if not files:
        return False
    strings, resources = {}, []
    for f in files:
        try:
            type_, instance, data = compile_xml(f.read_text(encoding="utf-8"), strings)
        except ValueError as e:
            raise SystemExit("{}: {}".format(f, e))
        resources.append((type_, 0, instance, data))
    if strings:
        table = stbl(strings)
        base = fnv64(package_name) & 0x00FFFFFFFFFFFFFF
        resources += [(STBL_TYPE, STBL_GROUP, (locale << 56) | base, table) for locale in LOCALES]
    dbpf.write_package(out_file, resources)
    return True
