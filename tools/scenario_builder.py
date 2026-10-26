"""Local web builder for scenario files and the in-game Scenarios menu export.

Run:

    py -3.11 tools/scenario_builder.py

It serves one page on http://127.0.0.1:8765: pick a scenario, edit it as a form or as JSON,
validate, save into Mods/HouseRules/scenarios/, and export a .package for the game's own
Scenarios screen. No third-party packages, no network access.

The file format and validation live in mods/scenarios/scripts/scenario_logic.py; the menu
export lives in tools/scenario_export.py.
"""
import argparse
import json
import re
import shutil
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import config
import scenario_export
from scenario_export import SCENARIO_DIR, slugify, validate

HERE = Path(__file__).resolve().parent
PAGE = HERE / "scenario_builder.html"
DEFAULT_INSTALLED = config.MODS_DIR / config.CREATOR / "scenarios"

_BAD_NAME = re.compile(r"[^A-Za-z0-9 _\-]")


class BuildError(ValueError):
    pass


def safe_name(name):
    name = Path(str(name or "")).name
    if name.lower().endswith(".json"):
        name = name[:-5]
    name = name.strip()
    if not name or _BAD_NAME.search(name):
        raise BuildError("scenario name may only use letters, numbers, spaces, _ and -")
    return name


def validate_text(text):
    logic = scenario_export.load_logic()
    return logic.parse(text)


def read_source(source, name, installed_dir):
    name = safe_name(name)
    directory = installed_dir if source == "installed" else SCENARIO_DIR
    path = (directory / (name + ".json")).resolve()
    if directory.resolve() not in path.parents:
        raise BuildError("scenario path escapes its folder")
    if not path.exists():
        raise BuildError("no such scenario: {}".format(name))
    return path


def scan(directory):
    items = []
    if not Path(directory).is_dir():
        return items
    for path in sorted(Path(directory).glob("*.json")):
        try:
            validate_text(path.read_text(encoding="utf-8"))
            valid = True
        except Exception:
            valid = False
        items.append({"name": path.stem, "valid": valid})
    return items


def meta():
    logic = scenario_export.load_logic()
    return {
        "goal_types": list(logic.GOAL_TYPES),
        "who": list(logic.WHO),
        "relationships": list(logic.RELATIONSHIP_LEVELS),
        "rule_types": list(logic.RULE_TYPES),
        "penalty_types": list(logic.PENALTY_TYPES),
    }


def error_list(exc):
    if isinstance(exc, scenario_export.ExportError) or type(exc).__name__ == "ScenarioError":
        text = str(exc)
        return [part.strip() for part in text.split(";") if part.strip()] or [text]
    return [str(exc)]


class Handler(BaseHTTPRequestHandler):
    installed_dir = DEFAULT_INSTALLED
    install_package = True
    server_version = "HouseRulesScenarioBuilder/1.0"

    def log_message(self, fmt, *args):
        print("[builder] " + (fmt % args))

    def _send(self, status, body, content_type):
        if isinstance(body, str):
            body = body.encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _json(self, status, payload):
        self._send(status, json.dumps(payload), "application/json; charset=utf-8")

    def _body(self):
        length = int(self.headers.get("Content-Length") or 0)
        raw = self.rfile.read(length) if length else b"{}"
        try:
            return json.loads(raw.decode("utf-8"))
        except ValueError as exc:
            raise BuildError("request body is not JSON: {}".format(exc))

    def do_GET(self):
        parsed = urlparse(self.path)
        try:
            if parsed.path in ("/", "/index.html"):
                page = PAGE.read_text(encoding="utf-8")
                injection = "<script>window.__META__ = {};</script>\n</head>".format(
                    json.dumps(meta()))
                page = page.replace("</head>", injection, 1)
                self._send(200, page, "text/html; charset=utf-8")
                return
            if parsed.path == "/api/state":
                self._json(200, {
                    "installed_dir": str(self.installed_dir),
                    "examples_dir": str(SCENARIO_DIR),
                    "installed": scan(self.installed_dir),
                    "examples": scan(SCENARIO_DIR),
                    "meta": meta(),
                })
                return
            if parsed.path == "/api/scenario":
                query = parse_qs(parsed.query)
                source = (query.get("source") or ["installed"])[0]
                name = (query.get("name") or [""])[0]
                path = read_source(source, name, self.installed_dir)
                text = path.read_text(encoding="utf-8")
                data, warnings = validate_text(text)
                self._json(200, {
                    "name": path.stem,
                    "source": source,
                    "data": data,
                    "warnings": warnings,
                    "text": text,
                })
                return
            self._json(404, {"error": "no such page"})
        except Exception as exc:
            self._json(400, {"error": str(exc), "errors": error_list(exc)})

    def do_POST(self):
        parsed = urlparse(self.path)
        try:
            body = self._body()
            if parsed.path == "/api/validate":
                data, warnings = validate_text(body.get("text") or "")
                self._json(200, {"ok": True, "warnings": warnings})
                return
            if parsed.path == "/api/save":
                data, warnings = validate_text(body.get("text") or "")
                name = safe_name(body.get("name") or data.get("name"))
                self.installed_dir.mkdir(parents=True, exist_ok=True)
                path = self.installed_dir / (name + ".json")
                path.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n",
                                encoding="utf-8")
                self._json(200, {
                    "ok": True,
                    "name": name,
                    "path": str(path),
                    "warnings": warnings,
                    "notes": ["Saved to " + str(path)],
                })
                return
            if parsed.path == "/api/delete":
                name = safe_name(body.get("name"))
                path = self.installed_dir / (name + ".json")
                if path.exists():
                    path.unlink()
                self._json(200, {"ok": True, "notes": ["Deleted " + str(path)]})
                return
            if parsed.path == "/api/export":
                data, warnings = validate_text(body.get("text") or "")
                name = safe_name(body.get("name") or data.get("name"))
                slug = slugify(name)
                out = config.BUILD_DIR / ("{}_scenario_{}.package".format(config.CREATOR, slug))
                result, built = scenario_export.build(
                    data, out, slug=slug,
                    package_name="{}_scenario_{}".format(config.CREATOR, slug))
                installed_path = None
                if self.install_package:
                    destination = config.MODS_DIR / config.CREATOR / built.name
                    destination.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(str(built), str(destination))
                    installed_path = str(destination)
                self._json(200, {
                    "ok": True,
                    "path": str(built),
                    "installed_path": installed_path,
                    "files": sorted(result.files),
                    "warnings": warnings + result.warnings,
                    "unsupported": result.unsupported,
                })
                return
            self._json(404, {"error": "no such endpoint"})
        except Exception as exc:
            self._json(400, {"error": str(exc), "errors": error_list(exc)})


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--dir", default=str(DEFAULT_INSTALLED),
                        help="installed scenarios folder (default: %(default)s)")
    parser.add_argument("--no-install", action="store_true",
                        help="do not copy an exported .package into the Mods folder")
    parser.add_argument("--no-browser", action="store_true", help="do not open the browser")
    args = parser.parse_args(argv)

    Handler.installed_dir = Path(args.dir)
    Handler.install_package = not args.no_install
    address = (args.host, args.port)
    server = ThreadingHTTPServer(address, Handler)
    url = "http://{}:{}/".format(args.host, args.port)
    print("Scenario builder: {}".format(url))
    print("  installed: {}".format(Handler.installed_dir))
    print("  examples:  {}".format(SCENARIO_DIR))
    if not args.no_browser:
        webbrowser.open(url)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
