import json

from supermodel.api_server import ReadOnlyAPI
from supermodel.service_runtime import job_run


def test_read_only_api_health_and_unavailable_resources(tmp_path):
    api = ReadOnlyAPI(tmp_path / "runtime")
    status, payload = api.response("/healthz")
    assert int(status) == 200
    assert payload["service"] == "api"

    status, payload = api.response("/api/v1/slate/latest")
    assert int(status) == 503
    assert payload["status"] == "UNAVAILABLE"


def test_read_only_api_returns_published_state(tmp_path):
    path = tmp_path / "runtime" / "state" / "slate_publisher.json"
    path.parent.mkdir(parents=True)
    path.write_text(json.dumps({"status": "PASS", "games": 15}), encoding="utf-8")
    status, payload = ReadOnlyAPI(tmp_path / "runtime").response("/api/v1/slate/latest")
    assert int(status) == 200
    assert payload["games"] == 15


def test_job_run_records_success_and_failure(tmp_path):
    root = tmp_path / "jobs"
    with job_run("publisher", root=root) as state:
        state["games"] = 15
    record = json.loads(next((root / "publisher").glob("*.json")).read_text())
    assert record["status"] == "PASS"
    assert record["payload"]["games"] == 15
