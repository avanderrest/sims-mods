"""Reads and writes the Sims 4 binary SimData resource (type 0x545AC67A, "DATA", version 0x101).

Career/aspiration tuning only loads from this binary form. The layout is documented by EA's
010 Editor template for the format (the `CombinedBinaryTuning` template in
Llama-Logic/Binary-Templates); this module is a port of the open-source writer in Sims 4
Toolkit (@s4tk/models, MIT licensed), which reproduces EA's own files byte for byte.

Both of those sources are kept locally in `references/`, which is gitignored: this module
does not need them, and they are not ours to publish.

A SimData is a tiny relational database:
- a header, then one 28-byte TableInfo per table;
- each table is either an "object" table (rows shaped by a schema) or a "raw" table
  (a flat list of one data type);
- the schemas (each with a column list) follow the table data;
- the strings that name tables, schemas and columns are appended last, NUL separated.

Every offset in the file is relative to the field that holds it, which is why the writer
here is written as a two-pass "build buffers, then patch offsets" affair.
"""
import struct

# Data type codes, in the order EA's template lists them. The numbers are on disk.
BOOL, CHAR8, INT8, UINT8, INT16, UINT16, INT32, UINT32, INT64, UINT64, FLOAT, \
    STRING8, HASHEDSTRING8, OBJECT, VECTOR, FLOAT2, FLOAT3, FLOAT4, TABLESETREFERENCE, \
    RESOURCEKEY, LOCKEY, VARIANT, UNDEFINED = range(23)

NAMES = {
    BOOL: "Boolean", CHAR8: "Character", INT8: "Int8", UINT8: "UInt8", INT16: "Int16",
    UINT16: "UInt16", INT32: "Int32", UINT32: "UInt32", INT64: "Int64", UINT64: "UInt64",
    FLOAT: "Single", STRING8: "String", HASHEDSTRING8: "HashedString", OBJECT: "Object",
    VECTOR: "Vector", FLOAT2: "Float2", FLOAT3: "Float3", FLOAT4: "Float4",
    TABLESETREFERENCE: "TableSetReference", RESOURCEKEY: "ResourceKey",
    LOCKEY: "LocalizationKey", VARIANT: "Variant", UNDEFINED: "Undefined",
}
CODES = {name: code for code, name in NAMES.items()}
CODES["Float"] = FLOAT

ALIGNMENT = {code: 1 for code in NAMES}
for _code in (INT16, UINT16):
    ALIGNMENT[_code] = 2
for _code in (INT32, UINT32, FLOAT, STRING8, HASHEDSTRING8, OBJECT, VECTOR, FLOAT2,
              FLOAT3, FLOAT4, LOCKEY, VARIANT):
    ALIGNMENT[_code] = 4
for _code in (INT64, UINT64, TABLESETREFERENCE, RESOURCEKEY):
    ALIGNMENT[_code] = 8

SIZE = {
    BOOL: 1, CHAR8: 1, INT8: 1, UINT8: 1,
    INT16: 2, UINT16: 2,
    INT32: 4, UINT32: 4, FLOAT: 4, STRING8: 4, OBJECT: 4, LOCKEY: 4,
    INT64: 8, UINT64: 8, HASHEDSTRING8: 8, VECTOR: 8, FLOAT2: 8, TABLESETREFERENCE: 8,
    VARIANT: 8, FLOAT3: 12, FLOAT4: 16, RESOURCEKEY: 16,
}

RELOFFSET_NULL = -0x80000000        # on disk 0x80000000; relative offsets are signed
NO_NAME_HASH = 0x811C9DC5           # fnv32("")
HEADER_SIZE = 32
TABLE_HEADER_OFFSET = 24
VERSION = 0x101


def fnv32(text):
    h = 0x811C9DC5
    for b in text.lower().encode("utf-8"):
        h = (h * 0x01000193) & 0xFFFFFFFF
        h ^= b
    return h


def _pad(index, mask):
    """Bytes needed to align `index` to the boundary described by `mask` (size - 1)."""
    return -index & mask


class Column(object):
    def __init__(self, name, code, flags=0):
        self.name = name
        self.code = code if isinstance(code, int) else CODES[code]
        self.flags = flags


class Schema(object):
    def __init__(self, name, schema_hash, columns):
        self.name = name
        self.hash = schema_hash
        self.columns = list(columns)


class Cell(object):
    code = None


class Value(Cell):
    """A fixed-size scalar: bool, integer, float, LocalizationKey, TableSetReference
    or ResourceKey (the last as a (type, group, instance) tuple)."""

    def __init__(self, code, value):
        self.code = code if isinstance(code, int) else CODES[code]
        self.value = value


class Text(Cell):
    """A String or HashedString; the text itself lives in the file's character table."""

    def __init__(self, value, code=STRING8):
        self.code = code if isinstance(code, int) else CODES[code]
        self.value = value


class ObjectCell(Cell):
    code = OBJECT

    def __init__(self, schema, row):
        self.schema = schema
        self.row = row


class VectorCell(Cell):
    code = VECTOR

    def __init__(self, children):
        self.children = list(children)


class VariantCell(Cell):
    code = VARIANT

    def __init__(self, type_hash, child=None):
        self.type_hash = type_hash
        self.child = child


class Instance(object):
    """One tuning: a named row of an object table."""

    def __init__(self, name, schema, row):
        self.name = name
        self.schema = schema
        self.row = row


class SimData(object):
    def __init__(self, schemas, instances, version=VERSION, unused=0):
        self.schemas = list(schemas)
        self.instances = list(instances)
        self.version = version
        self.unused = unused


class _Writer(object):
    def __init__(self, buffer):
        self.buffer = buffer
        self.pos = 0

    def tell(self):
        return self.pos

    def seek(self, pos):
        self.pos = pos

    def skip(self, count):
        self.pos += count

    def save_pos(self, fn):
        saved = self.pos
        fn()
        self.pos = saved

    def _pack(self, fmt, value):
        struct.pack_into(fmt, self.buffer, self.pos, value)
        self.pos += struct.calcsize(fmt)

    def int8(self, v):
        self._pack("<b", v)

    def uint8(self, v):
        self._pack("<B", v)

    def int16(self, v):
        self._pack("<h", v)

    def uint16(self, v):
        self._pack("<H", v)

    def int32(self, v):
        self._pack("<i", v)

    def uint32(self, v):
        self._pack("<I", v)

    def int64(self, v):
        self._pack("<q", v)

    def uint64(self, v):
        self._pack("<Q", v)

    def float(self, v):
        self._pack("<f", v)

    def chars(self, text):
        data = text.encode("utf-8")
        self.buffer[self.pos:self.pos + len(data)] = data
        self.pos += len(data)


def _is_reference(cell):
    return cell.code in (OBJECT, VECTOR, VARIANT)


def _is_text(cell):
    return cell.code in (STRING8, HASHEDSTRING8)


def write(model):
    """Serializes a SimData model to the bytes stored in the package."""
    name_hashes = {}

    def hash_name(name):
        if name not in name_hashes:
            name_hashes[name] = fnv32(name)
        return name_hashes[name]

    raw_tables = []          # [{"code": code, "rows": [(cell, ref)]}]
    object_tables = []       # [{"schema": serial schema, "rows": [[(cell, ref)]]}]

    def raw_table(code):
        for table in raw_tables:
            if table["code"] == code:
                return table
        table = {"code": code, "rows": []}
        raw_tables.append(table)
        return table

    def object_table(schema_hash):
        for table in object_tables:
            if table["schema"]["hash"] == schema_hash:
                return table
        table = {"schema": schema_by_hash[schema_hash], "rows": []}
        object_tables.append(table)
        return table

    # Schemas: assign each column's offset in the order given, then write them in
    # ascending order of their name hash (which is what the game expects on disk).
    schema_by_hash = {}
    serial_schemas = []
    for schema in model.schemas:
        columns = [{"name": c.name, "code": c.code, "flags": c.flags, "offset": 0}
                   for c in schema.columns]
        size = 0
        for column in columns:
            size += _pad(size, ALIGNMENT[column["code"]] - 1)
            column["offset"] = size
            size += SIZE[column["code"]]
        largest_padding = 0
        for column in columns:
            padding = _pad(size, ALIGNMENT[column["code"]] - 1)
            largest_padding = max(largest_padding, padding)
        size += largest_padding
        for column in columns:
            hash_name(column["name"])
        columns.sort(key=lambda c: hash_name(c["name"]))
        hash_name(schema.name)
        serial = {"name": schema.name, "hash": schema.hash, "size": size, "columns": columns}
        schema_by_hash[serial["hash"]] = serial
        serial_schemas.append(serial)

    # Tables: walk every cell, putting referenced values in their own tables.
    char_table_length = [0]
    strings_to_add = []

    def add_cell(cell):
        if cell.code == OBJECT:
            return add_object_cell(cell)
        if cell.code == VECTOR:
            return add_vector_cell(cell)
        if cell.code == VARIANT:
            return add_variant_cell(cell)
        if cell.code in (CHAR8, STRING8, HASHEDSTRING8):
            return add_text_cell(cell)
        return add_primitive_cell(cell)

    def add_primitive_cell(cell):
        table = raw_table(cell.code)
        ref = (cell.code, len(table["rows"]))
        table["rows"].append((cell, None))
        return ref

    def add_text_cell(cell, as_char=False):
        char_ref = (CHAR8, char_table_length[0])
        char_table_length[0] += len(cell.value.encode("utf-8")) + 1
        strings_to_add.append(cell.value)
        if cell.code == CHAR8 or as_char:
            return char_ref
        table = raw_table(cell.code)
        table["rows"].append((cell, char_ref))
        return (cell.code, len(table["rows"]) - 1)

    def add_vector_cell(cell):
        child_type = cell.children[0].code if cell.children else None
        if child_type in (VECTOR, VARIANT):
            first = None
            for child in cell.children:
                table = raw_table(child.code)
                ref = (child.code, len(table["rows"]))
                table["rows"].append((child, add_cell(child)))
                first = first or ref
            return first
        if child_type is None:
            return None
        first = None
        for child in cell.children:
            ref = add_cell(child)
            if first is None:
                first = ref
        return first

    def add_variant_cell(cell):
        child_type = cell.child.code if cell.child is not None else None
        if child_type in (VECTOR, VARIANT):
            child = cell.child
            table = raw_table(child.code)
            ref = (child.code, len(table["rows"]))
            table["rows"].append((child, add_cell(child)))
            return ref
        return add_cell(cell.child) if cell.child is not None else None

    def add_object_cell(cell, table=None):
        table = table or object_table(cell.schema.hash)
        ref = (OBJECT, cell.schema.hash, len(table["rows"]))
        row = []
        for column in table["schema"]["columns"]:
            child = cell.row[column["name"]]
            if _is_reference(child):
                row.append((child, add_cell(child)))
            elif _is_text(child):
                row.append((child, add_text_cell(child, True)))
            else:
                row.append((child, None))
        table["rows"].append(row)
        return ref

    for instance in model.instances:
        hash_name(instance.name)
        table = object_table(instance.schema.hash)
        if not table.get("name") and instance.name:
            table["name"] = instance.name
        add_object_cell(instance, table)

    # The string table: names of tables, schemas and columns.
    string_offsets = {}
    string_parts = []
    offset = 0
    for name in name_hashes:
        string_offsets[name] = offset
        data = name.encode("utf-8") + b"\0"
        string_parts.append(data)
        offset += len(data)
    string_table = b"".join(string_parts)

    # Object tables are written in schema order; the game depends on it.
    schema_order = [schema["hash"] for schema in serial_schemas]
    object_tables.sort(key=lambda t: schema_order.index(t["schema"]["hash"]))

    # Schema block.
    schema_offsets = {}
    columns_start = 0
    schema_size_total = 0
    for i, schema in enumerate(serial_schemas):
        columns_start += 24
        schema_size_total += 24 + 20 * len(schema["columns"])
        schema_offsets[schema["hash"]] = 24 * i
    schema_buffer = bytearray(schema_size_total)
    encoder = _Writer(schema_buffer)

    def name_offset(name):
        return schema_size_total - encoder.tell() + string_offsets[name]

    filled_columns = 0
    # All schema headers come first, then every schema's column block (EA's layout:
    # columns start after 24 bytes per schema, not after this schema's own header).
    columns_start = 24 * len(serial_schemas)
    for schema in serial_schemas:
        encoder.int32(name_offset(schema["name"]))
        encoder.uint32(name_hashes[schema["name"]])
        encoder.uint32(schema["hash"])
        encoder.uint32(schema["size"])
        column_offset_pos = encoder.tell()
        encoder.skip(4)
        encoder.uint32(len(schema["columns"]))
        first_column_pos = [0]

        def write_columns():
            encoder.seek(columns_start + filled_columns)
            for j, column in enumerate(schema["columns"]):
                if j == 0:
                    first_column_pos[0] = encoder.tell()
                encoder.int32(name_offset(column["name"]))
                encoder.uint32(name_hashes[column["name"]])
                encoder.uint16(column["code"])
                encoder.uint16(column["flags"])
                encoder.uint32(column["offset"])
                encoder.int32(RELOFFSET_NULL)
                schema_state[0] += 20

        schema_state = [filled_columns]
        encoder.save_pos(write_columns)
        filled_columns = schema_state[0]
        end = encoder.tell()
        encoder.seek(column_offset_pos)
        encoder.int32(first_column_pos[0] - encoder.tell())
        encoder.seek(end)

    # Header, table headers and table data.
    total_size = HEADER_SIZE
    has_char_table = bool(strings_to_add)
    num_tables = len(raw_tables) + len(object_tables) + (1 if has_char_table else 0)
    total_size += num_tables * 28
    object_positions = {}
    for table in object_tables:
        total_size += _pad(total_size, 15)
        total_size += _pad(total_size, table["schema"]["size"] - 1)
        object_positions[table["schema"]["hash"]] = total_size
        total_size += table["schema"]["size"] * len(table["rows"])
    raw_positions = {}
    for table in raw_tables:
        total_size += _pad(total_size, 15)
        total_size += _pad(total_size, ALIGNMENT[table["code"]] - 1)
        raw_positions[table["code"]] = total_size
        total_size += SIZE[table["code"]] * len(table["rows"])
    if has_char_table:
        total_size += _pad(total_size, 15)
        raw_positions[CHAR8] = total_size
        total_size += char_table_length[0]
    total_size += _pad(total_size, 15)

    buffer = bytearray(total_size)
    encoder = _Writer(buffer)
    encoder.chars("DATA")
    encoder.uint32(model.version)
    encoder.int32(TABLE_HEADER_OFFSET)
    encoder.int32(num_tables)
    header_schema_pos = encoder.tell()
    encoder.int32(total_size - header_schema_pos)
    encoder.int32(len(serial_schemas))
    if model.version >= 0x101:
        encoder.uint32(model.unused or 0)
    encoder.seek(HEADER_SIZE)

    def bytes_left():
        return total_size - encoder.tell()

    def ref_offset(ref):
        if ref is None:
            return RELOFFSET_NULL
        if ref[0] == OBJECT:
            pos = object_positions[ref[1]]
            offset = schema_by_hash[ref[1]]["size"] * ref[2]
        else:
            pos = raw_positions[ref[0]]
            offset = SIZE[ref[0]] * ref[1]
        return pos + offset - encoder.tell()

    def write_cell(entry):
        cell, ref = entry
        encode_value(cell, ref_offset(ref))

    def encode_value(cell, offset):
        if cell.code == BOOL:
            encoder.uint8(1 if cell.value else 0)
        elif cell.code == INT8:
            encoder.int8(cell.value)
        elif cell.code == UINT8 or cell.code == CHAR8:
            encoder.uint8(cell.value)
        elif cell.code == INT16:
            encoder.int16(cell.value)
        elif cell.code == UINT16:
            encoder.uint16(cell.value)
        elif cell.code == INT32:
            encoder.int32(cell.value)
        elif cell.code in (UINT32, LOCKEY):
            encoder.uint32(cell.value)
        elif cell.code == INT64:
            encoder.int64(cell.value)
        elif cell.code in (UINT64, TABLESETREFERENCE):
            encoder.uint64(cell.value)
        elif cell.code == FLOAT:
            encoder.float(cell.value)
        elif cell.code in (STRING8, HASHEDSTRING8, OBJECT):
            encoder.int32(offset)
            if cell.code == HASHEDSTRING8:
                encoder.uint32(fnv32(cell.value))
        elif cell.code == VECTOR:
            encoder.int32(offset)
            encoder.uint32(len(cell.children))
        elif cell.code == VARIANT:
            encoder.int32(offset)
            encoder.uint32(cell.type_hash)
        elif cell.code == RESOURCEKEY:
            type_, group, instance = cell.value
            encoder.uint64(instance)
            encoder.uint32(type_)
            encoder.uint32(group)
        else:
            raise ValueError("cannot encode data type {} ({})".format(cell.code, NAMES.get(cell.code)))

    for table in object_tables:
        schema = table["schema"]
        if table.get("name") is None:
            encoder.int32(RELOFFSET_NULL)
            encoder.uint32(NO_NAME_HASH)
        else:
            encoder.int32(bytes_left() + len(schema_buffer) + string_offsets[table["name"]])
            encoder.uint32(name_hashes[table["name"]])
        encoder.int32(bytes_left() + schema_offsets[schema["hash"]])
        encoder.uint32(OBJECT)
        encoder.uint32(schema["size"])
        table_pos = object_positions[schema["hash"]]
        encoder.int32(table_pos - encoder.tell())
        encoder.uint32(len(table["rows"]))

        def write_rows(table=table, schema=schema, table_pos=table_pos):
            encoder.seek(table_pos)
            for i, row in enumerate(table["rows"]):
                if i > 0:
                    encoder.skip(schema["size"])
                for j, column in enumerate(schema["columns"]):
                    def write_one(column=column, entry=row[j]):
                        encoder.skip(column["offset"])
                        write_cell(entry)
                    encoder.save_pos(write_one)
        encoder.save_pos(write_rows)

    for table in raw_tables:
        encoder.int32(RELOFFSET_NULL)
        encoder.uint32(NO_NAME_HASH)
        encoder.int32(RELOFFSET_NULL)
        encoder.uint32(table["code"])
        encoder.uint32(SIZE[table["code"]])
        table_offset = raw_positions[table["code"]]
        encoder.int32(table_offset - encoder.tell())
        encoder.uint32(len(table["rows"]))

        def write_raw(table=table, table_offset=table_offset):
            encoder.seek(table_offset)
            for entry in table["rows"]:
                write_cell(entry)
        encoder.save_pos(write_raw)

    if has_char_table:
        encoder.int32(RELOFFSET_NULL)
        encoder.uint32(NO_NAME_HASH)
        encoder.int32(RELOFFSET_NULL)
        encoder.uint32(CHAR8)
        encoder.uint32(1)
        table_offset = raw_positions[CHAR8]
        encoder.int32(table_offset - encoder.tell())
        encoder.uint32(char_table_length[0])

        def write_chars(table_offset=table_offset):
            encoder.seek(table_offset)
            for text in strings_to_add:
                encoder.chars(text)
                encoder.skip(1)
        encoder.save_pos(write_chars)

    return bytes(buffer) + bytes(schema_buffer) + string_table


# --- Reading the XML form ------------------------------------------------------------
# Sims 4 Studio (and this tool) spell a SimData out as XML: one <I> per tuning, its
# columns as child elements, and a <Schemas> block that says what each column holds.
# The writer above is validated by parsing that XML and reproducing EA's own bytes.

def _parse_value(text, code):
    if code == BOOL:
        return text.strip().lower() in ("1", "true")
    if code == FLOAT:
        return float(text)
    if code == RESOURCEKEY:
        type_, group, instance = text.split("-")
        return (int(type_, 16), int(group, 16), int(instance, 16))
    return int(text, 0)


def _cell_from_xml(node, code):
    value = (node.text or "").strip()
    if code == VECTOR:
        return VectorCell([_cell_from_xml(child, CODES.get(child.get("type"), STRING8))
                           for child in node])
    if code == VARIANT:
        child = next(iter(node), None)
        return VariantCell(int(node.get("variant"), 0),
                           _cell_from_xml(child, _child_code(child)) if child is not None else None)
    if code == OBJECT:
        raise ValueError("nested object cells are not supported (only tuning-level rows)")
    if code in (STRING8, HASHEDSTRING8):
        return Text(value, code)
    return Value(code, _parse_value(value, code))


def _child_code(node):
    if node.get("type"):
        return CODES[node.get("type")]
    if node.tag == "L":
        return VECTOR
    if node.tag == "V":
        return VARIANT
    raise ValueError("cell <{}> has no type attribute".format(node.tag))


def from_xml(text):
    """Builds a SimData model from Sims 4 Studio's XML form."""
    import xml.etree.ElementTree as ET
    root = ET.fromstring(text)
    schemas = []
    by_name = {}
    for node in root.find("Schemas"):
        columns = [Column(c.get("name"), CODES[c.get("type")], int(c.get("flags", "0"), 0))
                   for c in node.find("Columns")]
        schema = Schema(node.get("name"), int(node.get("schema_hash"), 0), columns)
        schemas.append(schema)
        by_name[schema.name] = schema
    instances = []
    for node in root.find("Instances"):
        schema = by_name[node.get("schema")]
        row = {}
        for column in schema.columns:
            cell = node.find("./*[@name='{}']".format(column.name))
            if cell is None:
                raise ValueError("{}: no value for column {}".format(node.get("name"), column.name))
            row[column.name] = _cell_from_xml(cell, column.code)
        instances.append(Instance(node.get("name"), schema, row))
    return SimData(schemas, instances, int(root.get("version", "0x101"), 0),
                   int(root.get("u", "0"), 0))
