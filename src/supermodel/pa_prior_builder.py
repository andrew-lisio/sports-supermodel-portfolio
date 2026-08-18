from __future__ import annotations

from collections import Counter, defaultdict
import json
from pathlib import Path
from typing import Any
import zipfile

import pandas as pd

from .pa_simulator import PA_EVENT_ORDER

_REQUIRED_COLUMNS = (
    "gametype",
    "pa",
    "k",
    "k_safe",
    "walk",
    "hbp",
    "single",
    "double",
    "triple",
    "hr",
    "roe",
    "fc",
    "xi",
    "othout",
    "sh",
    "sf",
    "outs_pre",
    "outs_post",
    "br1_pre",
    "br2_pre",
    "br3_pre",
    "br1_post",
    "br2_post",
    "br3_post",
    "runs",
)


def _flag(row: Any, name: str) -> bool:
    value = getattr(row, name)
    return bool(pd.notna(value) and float(value) != 0.0)


def _classify_event(row: Any) -> str:
    # A strikeout with a safe reach is a reach, not an out. Retrosheet also exposes
    # reach-on-error, fielder's choice, and interference separately.
    if _flag(row, "k_safe") or _flag(row, "roe") or _flag(row, "fc") or _flag(row, "xi"):
        return "REACH"
    if _flag(row, "k"):
        return "K"
    if _flag(row, "walk"):
        return "BB"
    if _flag(row, "hbp"):
        return "HBP"
    if _flag(row, "single"):
        return "1B"
    if _flag(row, "double"):
        return "2B"
    if _flag(row, "triple"):
        return "3B"
    if _flag(row, "hr"):
        return "HR"
    if _flag(row, "othout") or _flag(row, "sh") or _flag(row, "sf"):
        return "OUT"
    raise ValueError("Retrosheet PA row could not be mapped to the PA event contract")


def _base_mask(row: Any, suffix: str) -> int:
    mask = 0
    if pd.notna(getattr(row, f"br1_{suffix}")):
        mask |= 1
    if pd.notna(getattr(row, f"br2_{suffix}")):
        mask |= 2
    if pd.notna(getattr(row, f"br3_{suffix}")):
        mask |= 4
    return mask


def _distribution(counter: Counter[tuple[int, int, int]]) -> list[dict[str, Any]]:
    total = sum(counter.values())
    if total <= 0:
        raise ValueError("transition distribution cannot be empty")
    return [
        {
            "count": int(count),
            "next_base_mask": int(next_mask),
            "outs_added": int(outs_added),
            "probability": float(count / total),
            "runs": int(runs),
        }
        for (outs_added, next_mask, runs), count in sorted(counter.items())
    ]


def build_pa_prior_payload_from_retrosheet(
    archive_path: str | Path,
    *,
    csv_member: str | None = None,
    source_label: str = "Retrosheet parsed play-by-play 2024 regular season",
) -> dict[str, Any]:
    """Rebuild the packaged PA event/transition prior from a Retrosheet plays ZIP.

    Only regular-season rows marked as plate appearances are used. The resulting
    transition table contains every 3-outs-state x 8-base-mask x 9-event key; missing
    exact states use the event-level empirical fallback rather than fabricated values.
    """

    archive = Path(archive_path)
    if not archive.exists():
        raise FileNotFoundError(archive)
    with zipfile.ZipFile(archive) as zf:
        members = [name for name in zf.namelist() if name.lower().endswith(".csv")]
        member = csv_member or (members[0] if len(members) == 1 else None)
        if member is None or member not in zf.namelist():
            raise ValueError("could not resolve exactly one Retrosheet CSV member")
        with zf.open(member) as handle:
            frame = pd.read_csv(handle, usecols=list(_REQUIRED_COLUMNS), low_memory=False)

    frame = frame.loc[(frame["gametype"] == "regular") & (frame["pa"] == 1)].copy()
    exact: dict[tuple[int, int, str], Counter[tuple[int, int, int]]] = defaultdict(Counter)
    fallback: dict[str, Counter[tuple[int, int, int]]] = {
        event: Counter() for event in PA_EVENT_ORDER
    }
    event_counts: Counter[str] = Counter()

    for row in frame.itertuples(index=False):
        event = _classify_event(row)
        outs_pre = int(row.outs_pre)
        outs_post = int(row.outs_post)
        if outs_pre not in (0, 1, 2) or outs_post < outs_pre or outs_post > 3:
            raise ValueError(f"invalid outs transition {outs_pre}->{outs_post}")
        before = _base_mask(row, "pre")
        after = _base_mask(row, "post")
        runs = int(row.runs)
        outcome = (outs_post - outs_pre, after, runs)
        exact[(outs_pre, before, event)][outcome] += 1
        fallback[event][outcome] += 1
        event_counts[event] += 1

    total_pas = len(frame)
    if sum(event_counts.values()) != total_pas:
        raise ValueError("not every Retrosheet PA was classified exactly once")
    missing_events = [event for event in PA_EVENT_ORDER if not fallback[event]]
    if missing_events:
        raise ValueError(f"events missing from source corpus: {missing_events}")

    event_fallback = {
        event: _distribution(fallback[event]) for event in PA_EVENT_ORDER
    }
    transitions: dict[str, list[dict[str, Any]]] = {}
    for outs_pre in range(3):
        for base_mask in range(8):
            for event in PA_EVENT_ORDER:
                counter = exact.get((outs_pre, base_mask, event))
                transitions[f"{outs_pre}:{base_mask}:{event}"] = (
                    _distribution(counter) if counter else event_fallback[event]
                )

    return {
        "event_counts": {event: int(event_counts[event]) for event in PA_EVENT_ORDER},
        "event_fallback_transitions": event_fallback,
        "event_order": list(PA_EVENT_ORDER),
        "event_probabilities": {
            event: float(event_counts[event] / total_pas) for event in PA_EVENT_ORDER
        },
        "plate_appearances": int(total_pas),
        "schema_version": 1,
        "source": source_label,
        "source_file": f"{archive.name}/{member}",
        "transition_keys": len(transitions),
        "transitions": transitions,
    }


def write_pa_prior_payload(payload: dict[str, Any], output_path: str | Path) -> Path:
    output = Path(output_path)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return output


def build_and_write_pa_priors(
    archive_path: str | Path,
    output_path: str | Path,
    *,
    csv_member: str | None = None,
    source_label: str = "Retrosheet parsed play-by-play 2024 regular season",
) -> Path:
    payload = build_pa_prior_payload_from_retrosheet(
        archive_path,
        csv_member=csv_member,
        source_label=source_label,
    )
    return write_pa_prior_payload(payload, output_path)
