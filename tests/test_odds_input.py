from __future__ import annotations

import json

import pandas as pd
import pytest

from supermodel.odds_input import (
    OddsInputError,
    build_moneyline_template,
    decimal_to_american,
    load_moneylines,
    moneylines_from_records,
    parse_user_odds,
)
from supermodel.providers import PregameContext


def test_parse_user_odds_supports_american_and_decimal():
    assert parse_user_odds("+125") == 125
    assert parse_user_odds("-145") == -145
    assert parse_user_odds("EVEN") == 100
    assert parse_user_odds("2.25", odds_format="decimal") == 125
    assert decimal_to_american(1.5) == -200


def test_parse_user_odds_rejects_invalid_values():
    with pytest.raises(OddsInputError):
        parse_user_odds("-95")
    with pytest.raises(OddsInputError):
        parse_user_odds("1.0", odds_format="decimal")


def test_moneyline_records_skip_blank_rows_and_require_two_sides():
    rows = [
        {
            "game_date": "2030-07-20",
            "game_pk": 1,
            "away_team": "aaa",
            "home_team": "bbb",
            "away_odds": "+120",
            "home_odds": "-130",
        },
        {
            "game_date": "2030-07-20",
            "game_pk": 2,
            "away_team": "CCC",
            "home_team": "DDD",
            "away_odds": None,
            "home_odds": None,
        },
    ]
    lines = moneylines_from_records(rows)
    assert len(lines) == 1
    assert lines[0].away_team == "AAA"
    assert lines[0].away_odds == 120

    rows[1]["away_odds"] = 110
    with pytest.raises(OddsInputError, match="both away_odds and home_odds"):
        moneylines_from_records(rows)


def test_load_moneylines_supports_csv_and_json(tmp_path):
    frame = pd.DataFrame(
        [
            {
                "game_date": "2030-07-20",
                "game_pk": 99,
                "away_team": "AAA",
                "home_team": "BBB",
                "away_odds": 2.2,
                "home_odds": 1.75,
                "odds_format": "decimal",
            }
        ]
    )
    csv_path = tmp_path / "lines.csv"
    frame.to_csv(csv_path, index=False)
    assert load_moneylines(csv_path)[0].away_odds == 120

    json_path = tmp_path / "lines.json"
    json_path.write_text(json.dumps({"moneylines": frame.to_dict("records")}), encoding="utf-8")
    assert load_moneylines(json_path)[0].home_odds == -133


def test_template_contains_official_identity_and_context():
    context = PregameContext(
        game_date="2030-07-20",
        game_pk=123,
        game_number=2,
        game_datetime="2030-07-20T23:05:00Z",
        away_team="AAA",
        home_team="BBB",
        away_probable_pitcher_name="Away Starter",
        home_probable_pitcher_name="Home Starter",
        lineups_confirmed=True,
        weather_condition="Clear",
        wind_description="5 mph",
    )
    frame = build_moneyline_template([context])
    assert frame.iloc[0].game_pk == 123
    assert frame.iloc[0].game_number == 2
    assert frame.iloc[0].away_starter == "Away Starter"
    assert pd.isna(frame.iloc[0].away_odds)
