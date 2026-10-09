"""Build mods into the game's Mods folder.

Run with Python 3.7:  py -3.7 tools/build.py [mod-name ...] [--no-install]

First runs pytest on every mods/<name>/tests/ (with that mod's scripts/ importable);
nothing is built if a test fails.

For each folder in mods/ (or only the ones named):
  mods/<name>/scripts/**.py   -> compiled and zipped into build/<creator>_<name>.ts4script
  mods/<name>/package/*.package -> copied as-is (made in Sims 4 Studio)
Then everything is copied to Mods/<creator>/ unless --no-install is given.
Script files may sit at most one folder deep inside Mods, which is why we use one flat folder.
"""
import os
import py_compile
import shutil
import sys
import tempfile
import zipfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import config  # noqa: E402


def build_scripts(mod_dir, out_file):
    src = mod_dir / "scripts"
    sources = sorted(src.rglob("*.py"))
    if not sources:
        return False
    with tempfile.TemporaryDirectory() as tmp, \
            zipfile.ZipFile(out_file, "w", zipfile.ZIP_STORED) as zf:
        for py in sources:
            rel = py.relative_to(src)
            pyc = Path(tmp) / rel.with_suffix(".pyc")
            pyc.parent.mkdir(parents=True, exist_ok=True)
            # dfile is what shows up in tracebacks.
            py_compile.compile(str(py), cfile=str(pyc), dfile=str(rel), doraise=True)
            zf.write(pyc, rel.with_suffix(".pyc").as_posix())
    return True


def main(argv):
    if sys.version_info[:2] != (3, 7):
        sys.exit("Run this with Python 3.7 (py -3.7): the game only loads 3.7 bytecode.")

    install = "--no-install" not in argv
    names = [a for a in argv if not a.startswith("--")]
    mod_dirs = [d for d in sorted(config.MODS_SRC_DIR.iterdir())
                if d.is_dir() and (not names or d.name in names)]
    if names and len(mod_dirs) != len(names):
        sys.exit("unknown mod(s): {}".format(set(names) - {d.name for d in mod_dirs}))

    tested = [str(d / "tests") for d in mod_dirs if (d / "tests").is_dir()]
    if tested:
        import subprocess
        # Each mod's scripts/ goes on the path so tests can import the pure-logic modules.
        env = dict(os.environ, PYTHONPATH=os.pathsep.join(
            str(d / "scripts") for d in mod_dirs if (d / "tests").is_dir()))
        if subprocess.call([sys.executable, "-m", "pytest", "-q", *tested], env=env) != 0:
            sys.exit("tests failed: nothing was built")

    config.BUILD_DIR.mkdir(exist_ok=True)
    built = []
    for mod_dir in mod_dirs:
        base = "{}_{}".format(config.CREATOR, mod_dir.name)
        script_out = config.BUILD_DIR / (base + ".ts4script")
        if build_scripts(mod_dir, script_out):
            built.append(script_out)
        for pkg in sorted((mod_dir / "package").glob("*.package")):
            out = config.BUILD_DIR / "{}_{}".format(base, pkg.name)
            shutil.copy2(pkg, out)
            built.append(out)

    for f in built:
        print("built", f.relative_to(config.ROOT))
    if not built:
        print("nothing to build (no scripts/ or package/ content yet)")
        return

    if install:
        dest = config.MODS_DIR / config.CREATOR
        dest.mkdir(parents=True, exist_ok=True)
        for f in built:
            shutil.copy2(f, dest / f.name)
        print("installed to", dest)
        print("Make sure Script Mods are enabled in Game Options > Other, then restart the game.")


if __name__ == "__main__":
    main(sys.argv[1:])
