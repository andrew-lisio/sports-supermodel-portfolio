from datetime import datetime

import pandas as pd

from supermodel.refresh_orchestrator import _write_json_atomic


def test_refresh_state_is_written_atomically(tmp_path):
    path = tmp_path / "state" / "refresh.json"
    _write_json_atomic(path, {"status": "PASS", "at": datetime(2026, 7, 30).isoformat()})
    assert path.exists()
    assert '"status": "PASS"' in path.read_text(encoding="utf-8")
