"""Outline a compiled EA .pyc that the decompilers couldn't recover.

Prints every class and function (with argument names, annotations from the bytecode, and
the global/attribute names each one uses), which is usually enough to find a hook point.
Run with the game's Python: py -3.7 tools/pyc_outline.py ea_scripts/simulation/sims/household.pyc [filter]
"""
import dis
import marshal
import sys
import types


def _args(code):
    n = code.co_argcount + code.co_kwonlyargcount
    names = list(code.co_varnames[:n])
    if code.co_flags & 0x04:
        names.append("*" + code.co_varnames[n])
        n += 1
    if code.co_flags & 0x08:
        names.append("**" + code.co_varnames[n])
    return names


def _annotations(parent, func_name):
    """Annotations are built in the *parent* code just before MAKE_FUNCTION."""
    instrs = list(dis.get_instructions(parent))
    for i, ins in enumerate(instrs):
        if ins.opname == "LOAD_CONST" and isinstance(ins.argval, types.CodeType) and ins.argval.co_name == func_name:
            for back in range(i - 1, max(i - 6, -1), -1):
                prev = instrs[back]
                if prev.opname == "LOAD_CONST" and isinstance(prev.argval, tuple) and back > 0:
                    if instrs[back + 1].opname == "BUILD_CONST_KEY_MAP":
                        n = instrs[back + 1].arg
                        values = [x.argval for x in instrs[back - n:back]]
                        return dict(zip(prev.argval, values))
            return {}
    return {}


def outline(code, depth=0, parent=None, flt=None):
    for const in code.co_consts:
        if not isinstance(const, types.CodeType):
            continue
        is_class = any(ins.opname == "STORE_NAME" and ins.argval == "__module__"
                       for ins in dis.get_instructions(const))
        ann = _annotations(code, const.co_name) if not is_class else {}
        line = "{}{} {}({}){}".format(
            "    " * depth, "class" if is_class else "def", const.co_name,
            ", ".join(_args(const)) if not is_class else "",
            "  annotations={}".format(ann) if ann else "")
        uses = sorted(set(const.co_names))
        text = line + "\n" + "    " * (depth + 1) + "uses: " + ", ".join(uses)
        if flt is None or flt.lower() in text.lower() or is_class:
            print(line)
            if not is_class:
                print("    " * (depth + 1) + "uses: " + ", ".join(uses[:40]))
        outline(const, depth + 1, code, flt)


def main():
    path = sys.argv[1]
    flt = sys.argv[2] if len(sys.argv) > 2 else None
    with open(path, "rb") as f:
        code = marshal.loads(f.read()[16:])
    outline(code, flt=flt)


if __name__ == "__main__":
    main()
