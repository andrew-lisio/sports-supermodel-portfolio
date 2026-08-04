from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

from supermodel.live_context import LiveContextAssessment, LiveContextRefreshReport
from supermodel.providers import PregameContext
from supermodel.publisher import (
    game_input_fingerprint,
    publish_slate,
    publisher_lock,
)
from supermodel.workflow import CapturedSlate


NOW = datetime(2026, 7, 30, 12, tzinfo=timezone.utc)


def _context() -> PregameContext:
    return PregameContext(
        game_date="2026-07-30",
        away_team="ATL",
        home_team="MIA",
        game_pk=123,
        game_datetime="2026-07-30T23:00:00Z",
        status_abstract="Preview",
        status_detailed="Scheduled",
        weather_run_factor=1.04,
        away_starter_stats_snapshot_sha256="volatile-one",
        provenance={"capture": "first"},
    )




def _live_report(tmp_path: Path) -> LiveContextRefreshReport:
    assessment = LiveContextAssessment(
        game_pk=123,
        away_team="ATL",
        home_team="MIA",
        scheduled_start_utc="2026-07-30T23:00:00Z",
        assessed_at_utc=NOW.isoformat().replace("+00:00", "Z"),
        starter_status="PASS",
        lineup_status="PENDING",
        roster_status="PASS",
        weather_status="PASS",
        roof_status="PENDING",
        overall_status="PASS",
        block_reasons=(),
        warning_reasons=("LINEUP_NOT_YET_POSTED",),
        probable_pitchers_confirmed=True,
        lineups_confirmed=False,
        away_probable_pitcher_name=None,
        home_probable_pitcher_name=None,
        roof_value=None,
    )
    path = tmp_path / "live-context.json"
    path.write_text("{}", encoding="utf-8")
    return LiveContextRefreshReport(
        status="PASS",
        slate_date="2026-07-30",
        captured_at_utc=NOW.isoformat().replace("+00:00", "Z"),
        snapshot_path=str(path),
        game_count=1,
        blocked_game_pks=(),
        assessments=(assessment,),
        roster_snapshot_paths=(),
        transaction_snapshot_path=None,
    )


def test_game_input_fingerprint_ignores_transport_provenance():
    first = _context()
    second = _context()
    second.away_starter_stats_snapshot_sha256 = "volatile-two"
    second.provenance = {"capture": "second"}
    assert game_input_fingerprint(context=first, model_data_hash="model") == game_input_fingerprint(
        context=second, model_data_hash="model"
    )
    second.weather_run_factor = 1.08
    assert game_input_fingerprint(context=first, model_data_hash="model") != game_input_fingerprint(
        context=second, model_data_hash="model"
    )
    assert game_input_fingerprint(
        context=first, model_data_hash="model", live_context_hash="one"
    ) != game_input_fingerprint(
        context=first, model_data_hash="model", live_context_hash="two"
    )


def test_publisher_only_runs_changed_baseball_inputs(tmp_path, monkeypatch):
    schedule = tmp_path / "schedule.json"
    schedule.write_text("{}", encoding="utf-8")
    context = _context()
    captured = CapturedSlate(
        game_date="2026-07-30",
        captured_at=NOW,
        schedule_path=schedule,
        pregame_paths=(),
        starter_paths=(),
        advanced_paths=(),
        contexts=(context,),
    )
    monkeypatch.setattr("supermodel.publisher.capture_official_slate", lambda **kwargs: captured)
    monkeypatch.setattr(
        "supermodel.publisher.refresh_live_context",
        lambda **kwargs: _live_report(tmp_path),
    )
    monkeypatch.setattr("supermodel.publisher.model_data_fingerprint", lambda **kwargs: "model")

    class FakeStore:
        snapshots = {}

        def __init__(self, root):
            self.root = root

        def latest(self, game_pk, *, model_track="production"):
            return self.snapshots.get((game_pk, model_track))

    monkeypatch.setattr("supermodel.publisher.LocalSimulationSnapshotStore", FakeStore)
    calls = []

    def fake_evaluate(**kwargs):
        calls.append(kwargs)
        for game_pk, input_hash in kwargs["snapshot_input_hashes"].items():
            for track in ("production", "shadow"):
                FakeStore.snapshots[(game_pk, track)] = SimpleNamespace(
                    input_snapshot_hash=input_hash,
                    simulations=kwargs["simulations"],
                )
        artifact = tmp_path / "evaluation.json"
        artifact.write_text("{}", encoding="utf-8")
        manifest = tmp_path / "manifest.json"
        manifest.write_text("{}", encoding="utf-8")
        return SimpleNamespace(json_path=artifact, simulation_manifest_paths=(manifest,))

    monkeypatch.setattr("supermodel.publisher.evaluate_captured_slate", fake_evaluate)
    common = dict(
        slate_date="2026-07-30",
        data_dir=tmp_path / "data",
        history_cache_path=tmp_path / "history.csv",
        publisher_state_path=tmp_path / "state.json",
        publisher_report_root=tmp_path / "reports",
        publisher_lock_path=tmp_path / "publisher.lock",
        simulation_store_root=tmp_path / "simulations",
        refresh=False,
        captured_at=NOW,
    )
    first = publish_slate(**common)
    second = publish_slate(**common)
    assert first.status == "PASS"
    assert first.published_game_pks == (123,)
    assert first.market_quotes_persisted is False
    assert first.evidence_recorded is False
    assert first.storage_backend == "local"
    assert first.shared_report_ref is not None
    assert first.shared_report_ref.startswith("file://")
    assert first.shared_state_ref is not None
    assert second.status == "SKIPPED_UNCHANGED"
    assert second.unchanged_game_pks == (123,)
    assert len(calls) == 1
    assert calls[0]["persist_market_quotes"] is False
    assert calls[0]["record_evidence"] is False
    assert calls[0]["live_context_assessments"][123].roster_status == "PASS"
    assert first.live_context_status == "PASS"
    assert first.live_context_provider == "mlb_stats_api"


def test_publisher_lock_rejects_overlap(tmp_path):
    lock = tmp_path / "publisher.lock"
    with publisher_lock(lock, now=NOW):
        try:
            with publisher_lock(lock, now=NOW):
                raise AssertionError("overlapping lock should not be acquired")
        except RuntimeError as exc:
            assert "already running" in str(exc)
    assert not lock.exists()


def test_odds_only_change_reprices_without_resimulation(tmp_path, monkeypatch):
    from supermodel.odds_provider import OddsHTTPResponse

    schedule = tmp_path / "schedule.json"
    schedule.write_text("{}", encoding="utf-8")
    context = _context()
    captured = CapturedSlate(
        game_date="2026-07-30",
        captured_at=NOW,
        schedule_path=schedule,
        pregame_paths=(),
        starter_paths=(),
        advanced_paths=(),
        contexts=(context,),
    )
    monkeypatch.setattr("supermodel.publisher.capture_official_slate", lambda **kwargs: captured)
    monkeypatch.setattr(
        "supermodel.publisher.refresh_live_context",
        lambda **kwargs: _live_report(tmp_path),
    )
    monkeypatch.setattr("supermodel.publisher.model_data_fingerprint", lambda **kwargs: "model")

    class FakeStore:
        snapshots = {}

        def __init__(self, root):
            self.root = root

        def latest(self, game_pk, *, model_track="production"):
            return self.snapshots.get((game_pk, model_track))

    monkeypatch.setattr("supermodel.publisher.LocalSimulationSnapshotStore", FakeStore)
    evaluation_calls = []

    def fake_evaluate(**kwargs):
        evaluation_calls.append(kwargs)
        for game_pk, input_hash in kwargs["snapshot_input_hashes"].items():
            for track in ("production", "shadow"):
                FakeStore.snapshots[(game_pk, track)] = SimpleNamespace(
                    input_snapshot_hash=input_hash,
                    simulations=kwargs["simulations"],
                )
        artifact = tmp_path / "evaluation.json"
        artifact.write_text("{}", encoding="utf-8")
        manifest = tmp_path / "manifest.json"
        manifest.write_text("{}", encoding="utf-8")
        return SimpleNamespace(json_path=artifact, simulation_manifest_paths=(manifest,))

    monkeypatch.setattr("supermodel.publisher.evaluate_captured_slate", fake_evaluate)

    class FakeOddsClient:
        def __init__(self):
            self.calls = 0

        def fetch_mlb_odds(self, **kwargs):
            self.calls += 1
            away_price = -120 if self.calls == 1 else -125
            return OddsHTTPResponse(
                payload=[
                    {
                        "id": "event",
                        "commence_time": "2026-07-30T23:00:00Z",
                        "away_team": "Atlanta Braves",
                        "home_team": "Miami Marlins",
                        "bookmakers": [
                            {
                                "key": "fanduel",
                                "title": "FanDuel",
                                "last_update": f"2026-07-30T12:0{self.calls}:00Z",
                                "markets": [
                                    {
                                        "key": "h2h",
                                        "outcomes": [
                                            {"name": "Atlanta Braves", "price": away_price},
                                            {"name": "Miami Marlins", "price": 105},
                                        ],
                                    }
                                ],
                            }
                        ],
                    }
                ],
                headers={},
            )

    odds_client = FakeOddsClient()
    common = dict(
        slate_date="2026-07-30",
        data_dir=tmp_path / "data",
        history_cache_path=tmp_path / "history.csv",
        publisher_state_path=tmp_path / "state.json",
        publisher_report_root=tmp_path / "reports",
        publisher_lock_path=tmp_path / "publisher.lock",
        market_store_root=tmp_path / "markets",
        simulation_store_root=tmp_path / "simulations",
        odds_snapshot_root=tmp_path / "odds",
        odds_client=odds_client,
        odds_bookmakers=("fanduel",),
        refresh=False,
    )
    first = publish_slate(**common, captured_at=NOW)
    second = publish_slate(**common, captured_at=NOW.replace(minute=5))
    assert first.status == "PASS"
    assert first.market_quotes_persisted is True
    assert second.status == "PRICES_UPDATED"
    assert second.odds_quotes_changed == 1
    assert len(evaluation_calls) == 1
