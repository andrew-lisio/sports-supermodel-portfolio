from __future__ import annotations

import json
from pathlib import Path

import pytest

from supermodel.pa_prior_builder import build_pa_prior_payload_from_retrosheet


def test_packaged_pa_prior_has_reproducible_retrosheet_contract():
    packaged = json.loads(
        Path("src/supermodel/resources/pa_priors_2024.json").read_text(encoding="utf-8")
    )
    assert packaged["plate_appearances"] == 182449
    assert packaged["transition_keys"] == 216
    assert packaged["event_counts"] == {
        "1B": 25902,
        "2B": 7771,
        "3B": 697,
        "BB": 14929,
        "HBP": 2020,
        "HR": 5453,
        "K": 41147,
        "OUT": 82566,
        "REACH": 1964,
    }


def test_uploaded_retrosheet_archive_rebuilds_packaged_pa_prior_when_available():
    archive = Path("/mnt/data/2024plays.zip")
    if not archive.exists():
        pytest.skip("canonical Retrosheet source archive is not mounted")
    rebuilt = build_pa_prior_payload_from_retrosheet(archive)
    packaged = json.loads(
        Path("src/supermodel/resources/pa_priors_2024.json").read_text(encoding="utf-8")
    )
    assert rebuilt == packaged
