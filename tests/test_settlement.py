from supermodel.settlement import settle_evidence_events, summarize_performance


def event(sequence, event_type, payload):
    return {
        "sequence": sequence,
        "event_type": event_type,
        "game_pk": 1,
        "recorded_at": f"2026-08-04T1{sequence}:00:00Z",
        "payload": payload,
    }


def test_settlement_computes_metrics_roi_and_clv():
    events = [
        event(
            1,
            "prediction",
            {
                "away_team": "AWAY",
                "home_team": "HOME",
                "production_home_probability": 0.60,
                "home_probability": 0.55,
                "home_odds": -120,
                "away_odds": 110,
                "offered_home_implied": 0.545,
            },
        ),
        event(2, "closing_line", {"closing_home_implied": 0.58}),
        event(3, "outcome", {"home_won": 1}),
    ]
    settled = settle_evidence_events(events)
    assert len(settled) == 1
    assert settled[0].production_correct
    assert settled[0].realized_roi > 0
    assert settled[0].closing_line_value > 0
    summary = summarize_performance(settled)
    assert summary.production_accuracy == 1.0
    assert summary.shadow_accuracy == 1.0


def test_empty_performance_is_explicit():
    summary = summarize_performance([])
    assert summary.status == "NO_SETTLED_GAMES"
    assert summary.settled_games == 0
