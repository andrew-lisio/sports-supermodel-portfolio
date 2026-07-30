from datetime import datetime, timedelta, timezone

from supermodel.worker import WorkerPolicy, next_poll_seconds


def test_worker_polls_faster_within_two_hours_of_first_pitch():
    policy = WorkerPolicy()
    now = datetime(2026, 7, 30, 16, tzinfo=timezone.utc)
    start = (now + timedelta(minutes=90)).isoformat().replace("+00:00", "Z")
    assert next_poll_seconds(now=now, next_game_start_utc=start, policy=policy) == 600


def test_worker_uses_base_interval_outside_near_game_window():
    policy = WorkerPolicy()
    now = datetime(2026, 7, 30, 14, tzinfo=timezone.utc)
    start = (now + timedelta(hours=5)).isoformat().replace("+00:00", "Z")
    assert next_poll_seconds(now=now, next_game_start_utc=start, policy=policy) == 1800


def test_worker_uses_overnight_interval():
    policy = WorkerPolicy()
    # 06:00 UTC is 02:00 EDT.
    now = datetime(2026, 7, 30, 6, tzinfo=timezone.utc)
    assert next_poll_seconds(now=now, next_game_start_utc=None, policy=policy) == 3600
