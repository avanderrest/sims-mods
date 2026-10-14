"""Minimal reader for The Sims 4's .package files (DBPF 2.1), for reading EA's tuning,
and a writer for our own small packages (tools/tuning.py).

Reading: lists a package's resources and returns their (decompressed) bytes. Supports the
compression types EA's simulation packages use: none, zlib, and the old internal "RefPack"
format. Writing: uncompressed only, which the game loads fine.
"""
import struct
import zlib

COMPRESSION_NONE = 0x0000
COMPRESSION_ZLIB = 0x5A42
COMPRESSION_REFPACK = 0xFFFF
COMPRESSION_DELETED = 0xFFE0


class Entry:
    __slots__ = ("type", "group", "instance", "offset", "file_size", "mem_size", "compression")

    def __init__(self, type_, group, instance, offset, file_size, mem_size, compression):
        self.type = type_
        self.group = group
        self.instance = instance
        self.offset = offset
        self.file_size = file_size
        self.mem_size = mem_size
        self.compression = compression

    def __repr__(self):
        return "Entry({:08X}:{:08X}:{:016X}, {} bytes)".format(self.type, self.group, self.instance, self.mem_size)


class Package:
    def __init__(self, path):
        self.path = str(path)
        with open(self.path, "rb") as f:
            self.data = f.read()
        if self.data[:4] != b"DBPF":
            raise ValueError("not a DBPF package: " + self.path)
        count = struct.unpack_from("<I", self.data, 36)[0]
        index_pos = struct.unpack_from("<I", self.data, 64)[0] or struct.unpack_from("<I", self.data, 40)[0]
        self.entries = self._read_index(index_pos, count)

    def _read_index(self, pos, count):
        data = self.data
        flags = struct.unpack_from("<I", data, pos)[0]
        pos += 4
        const = {}
        for bit, name in ((1, "type"), (2, "group"), (4, "inst_hi")):
            if flags & bit:
                const[name] = struct.unpack_from("<I", data, pos)[0]
                pos += 4
        entries = []
        for _ in range(count):
            vals = {}
            for name in ("type", "group", "inst_hi"):
                if name in const:
                    vals[name] = const[name]
                else:
                    vals[name] = struct.unpack_from("<I", data, pos)[0]
                    pos += 4
            inst_lo, offset, file_size, mem_size = struct.unpack_from("<IIII", data, pos)
            pos += 16
            compression = COMPRESSION_NONE
            if file_size & 0x80000000:
                compression = struct.unpack_from("<H", data, pos)[0]
                pos += 4  # compression type + committed flag
                file_size &= 0x7FFFFFFF
            entries.append(Entry(vals["type"], vals["group"], (vals["inst_hi"] << 32) | inst_lo,
                                 offset, file_size, mem_size, compression))
        return entries

    def read(self, entry):
        raw = self.data[entry.offset:entry.offset + entry.file_size]
        if entry.compression == COMPRESSION_NONE:
            return raw
        if entry.compression == COMPRESSION_ZLIB:
            return zlib.decompress(raw)
        if entry.compression == COMPRESSION_REFPACK:
            return refpack_decompress(raw)
        if entry.compression == COMPRESSION_DELETED:
            return b""
        raise ValueError("unknown compression {:04X} in {}".format(entry.compression, entry))


def refpack_decompress(src):
    """EA's RefPack (QFS) compression."""
    pos = 0
    flags = src[0]
    pos = 2
    size_bytes = 4 if flags & 0x80 else 3
    out_size = int.from_bytes(src[pos:pos + size_bytes], "big")
    pos += size_bytes
    out = bytearray()
    n = len(src)
    while pos < n:
        b0 = src[pos]
        if b0 < 0x80:
            b1 = src[pos + 1]
            pos += 2
            lit = b0 & 3
            copy = ((b0 & 0x1C) >> 2) + 3
            dist = ((b0 & 0x60) << 3) + b1 + 1
        elif b0 < 0xC0:
            b1, b2 = src[pos + 1], src[pos + 2]
            pos += 3
            lit = (b1 >> 6) & 3
            copy = (b0 & 0x3F) + 4
            dist = ((b1 & 0x3F) << 8) + b2 + 1
        elif b0 < 0xE0:
            b1, b2, b3 = src[pos + 1], src[pos + 2], src[pos + 3]
            pos += 4
            lit = b0 & 3
            copy = ((b0 & 0x0C) << 6) + b3 + 5
            dist = ((b0 & 0x10) << 12) + (b1 << 8) + b2 + 1
        elif b0 < 0xFC:
            pos += 1
            lit = ((b0 & 0x1F) << 2) + 4
            copy = 0
            dist = 0
        else:
            pos += 1
            lit = b0 & 3
            copy = 0
            dist = 0
        out += src[pos:pos + lit]
        pos += lit
        for _ in range(copy):
            out.append(out[-dist])
        if b0 >= 0xFC:
            break
    return bytes(out[:out_size])


def write_package(path, resources):
    """resources: [(type, group, instance, bytes)]. Writes an uncompressed DBPF 2.1 package."""
    header_size = 96
    body = bytearray()
    index = bytearray(struct.pack("<I", 0))   # flags: no fields shared between entries
    for type_, group, instance, data in resources:
        offset = header_size + len(body)
        body += data
        index += struct.pack("<IIIIIIIHH", type_, group, instance >> 32, instance & 0xFFFFFFFF, offset,
                             len(data) | 0x80000000, len(data), COMPRESSION_NONE, 1)
    header = bytearray(header_size)
    header[0:4] = b"DBPF"
    struct.pack_into("<II", header, 4, 2, 1)                       # version 2.1
    struct.pack_into("<I", header, 36, len(resources))             # index entry count
    struct.pack_into("<I", header, 44, len(index))                 # index size
    struct.pack_into("<I", header, 60, 3)                          # index version
    struct.pack_into("<I", header, 64, header_size + len(body))    # index position
    with open(str(path), "wb") as f:
        f.write(bytes(header) + bytes(body) + bytes(index))
