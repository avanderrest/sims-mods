import json
import threading
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer

import pytest

import scenario_builder

SCENARIO = {
    "name": "Builder Test",
    "description": "Made in the builder test",
    "start": {"money": 500},
    "goals": [{"id": "art", "type": "skill", "skill": "Painting", "level": 4, "who": "active"}],
    "outcomes": {"win": {"notification": "Done"}},
    "menu": {"category": "CHALLENGE", "difficulty": "HARD"},
}


@pytest.fixture()
def server(tmp_path):
    scenario_builder.Handler.installed_dir = tmp_path
    scenario_builder.Handler.install_package = False
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), scenario_builder.Handler)
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    try:
        yield "http://127.0.0.1:{}".format(httpd.server_address[1])
    finally:
        httpd.shutdown()
        httpd.server_close()
        thread.join(timeout=5)


def request(url, body=None):
    data = None if body is None else json.dumps(body).encode("utf-8")
    req = urllib.request.Request(url, data=data,
                                 headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=10) as response:
            return response.status, response.read().decode("utf-8")
    except urllib.error.HTTPError as error:
        return error.code, error.read().decode("utf-8")


def test_page_injects_meta_and_builder_script(server):
    status, page = request(server + "/")
    assert status == 200
    assert "window.__META__" in page
    assert "Scenario Builder" in page
    assert '"goal_types"' in page


def test_state_lists_examples(server):
    status, body = request(server + "/api/state")
    assert status == 200
    state = json.loads(body)
    assert {"full_house", "rags_to_riches", "starving_artist"} <= {
        item["name"] for item in state["examples"]}
    assert "skill" in state["meta"]["goal_types"]


def test_validate_save_and_export_round_trip(server, tmp_path):
    status, body = request(server + "/api/validate", {"text": json.dumps(SCENARIO)})
    assert status == 200
    assert json.loads(body)["ok"] is True

    status, body = request(server + "/api/save",
                           {"name": "Builder Test", "text": json.dumps(SCENARIO)})
    assert status == 200
    assert (tmp_path / "Builder Test.json").exists()

    status, body = request(server + "/api/export",
                           {"name": "Builder Test", "text": json.dumps(SCENARIO)})
    assert status == 200
    result = json.loads(body)
    assert result["ok"] is True
    assert "HouseRules_Scenario_Builder_Test" in result["files"]
    assert result["installed_path"] is None
    assert result["path"].endswith("HouseRules_scenario_Builder_Test.package")


def test_bad_json_is_a_400_with_errors(server):
    status, body = request(server + "/api/validate", {"text": "{not json"})
    assert status == 400
    assert json.loads(body)["errors"]
