"""Decompile EA's game scripts into ea_scripts/ so they can be read and searched.

Run with Python 3.7:  py -3.7 tools/decompile.py
Re-run after a game patch. Files that fail to decompile are listed in
ea_scripts/_failures.txt; the original .pyc is kept next to where the .py would be.
"""
import io
import sys
import zipfile
from concurrent.futures import ProcessPoolExecutor, as_completed
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import config  # noqa: E402


def _decompile_one(pyc_path):
    """Returns None on success, or an error string."""
    pyc_path = Path(pyc_path)
    py_path = pyc_path.with_suffix(".py")
    if py_path.exists():  # done by an earlier run
        pyc_path.unlink()
        return None
    # The decompilers dump parser traces to stdout/stderr when they struggle; silence them.
    sys.stdout = sys.stderr = io.StringIO()
    errors = []
    for name in ("decompyle3", "uncompyle6"):
        try:
            main = __import__(name + ".main", fromlist=["decompile_file"])
            out = io.StringIO()
            main.decompile_file(str(pyc_path), out)
            py_path.write_text(out.getvalue(), encoding="utf-8")
            pyc_path.unlink()
            return None
        except Exception as e:  # decompilers raise all sorts of things
            errors.append("{}: {}".format(name, str(e).splitlines()[0] if str(e) else type(e).__name__))
    return "; ".join(errors)


def main():
    if sys.version_info[:2] != (3, 7):
        sys.exit("Run this with Python 3.7 (py -3.7), the version the game uses.")

    pycs = []
    for zip_path in config.EA_SCRIPT_ZIPS:
        if not zip_path.exists():
            print("missing, skipped:", zip_path)
            continue
        dest = config.EA_SCRIPTS_DIR / zip_path.stem
        print("extracting", zip_path.name)
        with zipfile.ZipFile(zip_path) as zf:
            for member in zf.namelist():
                if member.endswith(".pyc"):
                    zf.extract(member, dest)
                    pycs.append(dest / member)

    print("decompiling {} files...".format(len(pycs)))
    failures = []
    with ProcessPoolExecutor() as pool:
        futures = {pool.submit(_decompile_one, str(p)): p for p in pycs}
        for i, fut in enumerate(as_completed(futures), 1):
            err = fut.result()
            if err:
                failures.append("{}\t{}".format(futures[fut].relative_to(config.EA_SCRIPTS_DIR), err))
            if i % 500 == 0:
                print("  {}/{}".format(i, len(pycs)))

    (config.EA_SCRIPTS_DIR / "_failures.txt").write_text("\n".join(sorted(failures)), encoding="utf-8")
    print("done: {} ok, {} failed (see ea_scripts/_failures.txt)".format(
        len(pycs) - len(failures), len(failures)))


if __name__ == "__main__":
    main()
