"""Golden tests for the SimData writer.

The expected bytes below are copies of EA's own resources for these tunings
(aspiration_nobleCareer_Level2 from EP21 and objective_CareerAssignments_Noble_EnactDecree
from EP21). If the writer ever drifts from the game's layout these fail, which is the point:
the career panel silently ignores a SimData it cannot parse.
"""
import binascii

import simdata
import tuning


def aspiration(name, instance, objectives):
    schema = simdata.Schema("AspirationCareer", tuning.ASPIRATION_SCHEMA_HASH,
                            [simdata.Column("objectives", simdata.VECTOR)])
    row = {"objectives": simdata.VectorCell(
        [simdata.Value(simdata.TABLESETREFERENCE, value) for value in objectives])}
    return simdata.SimData([schema], [simdata.Instance(name, schema, row)], unused=0x8D)


def objective(name, display_text, tooltip, satisfaction_points=0, show_progress=True):
    schema = simdata.Schema("Objective", tuning.OBJECTIVE_SCHEMA_HASH, [
        simdata.Column("display_age_list", simdata.VARIANT),
        simdata.Column("display_text", simdata.LOCKEY),
        simdata.Column("satisfaction_points", simdata.INT32),
        simdata.Column("show_progress", simdata.BOOL),
        simdata.Column("tooltip", simdata.LOCKEY),
    ])
    row = {
        "display_age_list": simdata.VariantCell(tuning.OBJECTIVE_AGE_LIST),
        "display_text": simdata.Value(simdata.LOCKEY, display_text),
        "satisfaction_points": simdata.Value(simdata.INT32, satisfaction_points),
        "show_progress": simdata.Value(simdata.BOOL, show_progress),
        "tooltip": simdata.Value(simdata.LOCKEY, tooltip),
    }
    return simdata.SimData([schema], [simdata.Instance(name, schema, row)], unused=0x8D)


EA_ASPIRATION_LEVEL2 = (
    "4441544101010000180000000200000070000000010000008d00000000000000a8000000297690a65800"
    "00000d000000080000002c0000000100000000000080c59d1c8100000080120000000800000020000000"
    "020000000000000000000000100000000200000000000000000000006067000000000000c54207000000"
    "0000370000001b35f1a80536af8c08000000080000000100000014000000e900b8e30e00000000000000"
    "000000806f626a656374697665730041737069726174696f6e4361726565720061737069726174696f6e"
    "5f6e6f626c654361726565725f4c6576656c3200"
)

EA_OBJECTIVE = (
    "4441544101010000180000000100000050000000010000008d000000000000000e0100008829328a3800"
    "00000d000000180000000c0000000100000000000000000000805538a0c169e4ff120000000001000000"
    "ae3f840a0000000000000000c40000003e456900e36744481800000008000000050000008200000005bf"
    "df7e060000000c0000000000008061000000357b308a1400000008000000000000806e00000038e89d90"
    "000000001000000000000080680000002a7848cc140000001400000000000080140000000498dfe11500"
    "00000000000000000080646973706c61795f6167655f6c69737400646973706c61795f74657874007361"
    "74697366616374696f6e5f706f696e74730073686f775f70726f677265737300746f6f6c746970004f62"
    "6a656374697665006f626a6563746976655f43617265657241737369676e6d656e74735f4e6f626c655f"
    "456e61637444656372656500"
)


def test_aspiration_matches_eas_bytes():
    model = aspiration("aspiration_nobleCareer_Level2", 466308, [26464, 475845])
    assert simdata.write(model) == binascii.unhexlify(EA_ASPIRATION_LEVEL2)


def test_objective_matches_eas_bytes():
    model = objective("objective_CareerAssignments_Noble_EnactDecree", 0x12FFE469, 0x0A843FAE)
    assert simdata.write(model) == binascii.unhexlify(EA_OBJECTIVE)


def test_writer_is_deterministic():
    model = aspiration("aspiration_nobleCareer_Level2", 466308, [26464, 475845])
    assert simdata.write(model) == simdata.write(model)


def _schemas(data):
    """(hash, name, [column names]) for each schema header in a written SimData."""
    import struct

    def text(pos):
        end = data.index(b"\0", pos)
        return data[pos:end].decode()

    count = struct.unpack_from("<i", data, 20)[0]
    start = 16 + struct.unpack_from("<i", data, 16)[0]
    found = {}
    for i in range(count):
        header = start + 24 * i
        name_rel = struct.unpack_from("<i", data, header)[0]
        schema_hash = struct.unpack_from("<I", data, header + 8)[0]
        ncols = struct.unpack_from("<I", data, header + 20)[0]
        columns = header + 16 + struct.unpack_from("<i", data, header + 16)[0]
        names = []
        for j in range(ncols):
            pos = columns + 20 * j
            names.append(text(pos + struct.unpack_from("<i", data, pos)[0]))
        found[schema_hash] = (text(header + name_rel), sorted(names))
    return found


def test_nested_schemas_keep_their_column_blocks():
    # Regression: the column blocks used to be written after each schema's own header, so
    # with more than one schema they landed on top of the following headers.
    child = simdata.Schema("Child", 0x22222222, [simdata.Column("value", simdata.INT32)])
    parent = simdata.Schema("Parent", 0x11111111, [
        simdata.Column("child", simdata.OBJECT),
        simdata.Column("name", simdata.LOCKEY),
    ])
    row = {
        "child": simdata.ObjectCell(child, {"value": simdata.Value(simdata.INT32, 7)}),
        "name": simdata.Value(simdata.LOCKEY, 1),
    }
    data = simdata.write(simdata.SimData(
        [parent, child], [simdata.Instance("thing", parent, row)]))

    assert _schemas(data) == {
        0x11111111: ("Parent", ["child", "name"]),
        0x22222222: ("Child", ["value"]),
    }
