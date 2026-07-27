from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from hashlib import sha256
import json
import math
from pathlib import Path
from typing import Any, Mapping

import pandas as pd


STARTER_SNAPSHOT_KIND = "mlb_starter_pregame"
STARTER_SNAPSHOT_SCHEMA_VERSION = 1
STARTER_SIDES = {"away", "home"}


@dataclass(frozen=True)
class StarterSnapshotIssue:
    category: str
    detail: str
    path: str
    game_pk: int | None = None
    side: str | None = None

    def to_record(self) -> dict[str, Any]:
        return {
            "category": self.category,
            "detail": self.detail,
            "path": self.path,
            "game_pk": self.game_pk,
            "side": self.side,
        }


def _parse_utc(value: str | datetime, *, field_name: str) -> datetime:
    if isinstance(value, datetime):
        parsed = value
    else:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError(f"{field_name} must include a timezone offset")
    return parsed.astimezone(timezone.utc)


def _canonical_bytes(payload: Mapping[str, Any]) -> bytes:
    return (
        json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
        + "\n"
    ).encode("utf-8")


def _first_stat_split(payload: Mapping[str, Any]) -> Mapping[str, Any]:
    for block in payload.get("stats", []) or []:
        splits = block.get("splits") or []
        if splits:
            stat = splits[0].get("stat")
            if isinstance(stat, Mapping):
                return stat
    return {}


def _float_stat(stat: Mapping[str, Any], key: str) -> float | None:
    value = stat.get(key)
    if value in (None, "", "-.--", ".---", "--"):
        return None
    try:
        result = float(value)
    except (TypeError, ValueError):
        return None
    return result if math.isfinite(result) else None


def parse_innings_pitched(value: Any) -> float | None:
    """Convert baseball innings notation into arithmetic innings.

    MLB represents partial innings as ``.1`` and ``.2`` for one and two outs. Treating
    ``100.2`` as the decimal number 100.2 understates the denominator. This parser
    converts it to 100 + 2/3 and rejects impossible fractional-out digits.
    """

    if value in (None, "", "-.--", ".---", "--"):
        return None
    text = str(value).strip()
    if not text:
        return None
    if "." not in text:
        try:
            innings = int(text)
        except ValueError:
            return None
        return float(innings) if innings >= 0 else None

    whole_text, fraction_text = text.split(".", 1)
    try:
        whole = int(whole_text or "0")
    except ValueError:
        return None
    if whole < 0 or fraction_text not in {"0", "1", "2"}:
        return None
    return float(whole) + int(fraction_text) / 3.0


def parse_pitcher_season_stats(payload: Mapping[str, Any]) -> dict[str, float | None]:
    """Normalize the public MLB season-pitching response without inventing metrics.

    The returned record contains only fields derivable from the supplied point-in-time
    payload. xERA, xFIP, SIERA and pitch-quality metrics remain absent because the MLB
    basic season endpoint does not provide them.
    """

    stat = _first_stat_split(payload)
    innings = parse_innings_pitched(stat.get("inningsPitched"))
    strikeouts = _float_stat(stat, "strikeOuts")
    walks = _float_stat(stat, "baseOnBalls")
    hit_batters = _float_stat(stat, "hitBatsmen")
    home_runs = _float_stat(stat, "homeRuns")
    batters_faced = _float_stat(stat, "battersFaced")
    hits = _float_stat(stat, "hits")
    earned_runs = _float_stat(stat, "earnedRuns")
    ground_outs = _float_stat(stat, "groundOuts")
    air_outs = _float_stat(stat, "airOuts")
    games_pitched = _float_stat(stat, "gamesPlayed")
    games_started = _float_stat(stat, "gamesStarted")
    era = _float_stat(stat, "era")
    whip = _float_stat(stat, "whip")

    hit_batters_for_fip = hit_batters or 0.0
    fip = None
    if innings and innings > 0 and None not in (strikeouts, walks, home_runs):
        # Transparent fixed in-season FIP proxy. The fixed constant is recorded in the
        # normalized snapshot and is never labeled as official FIP or Statcast xERA.
        fip = (
            13.0 * float(home_runs)
            + 3.0 * (float(walks) + hit_batters_for_fip)
            - 2.0 * float(strikeouts)
        ) / innings + 3.10

    def per_batter(numerator: float | None) -> float | None:
        if numerator is None or not batters_faced or batters_faced <= 0:
            return None
        return 100.0 * numerator / batters_faced

    def per_nine(numerator: float | None) -> float | None:
        if numerator is None or not innings or innings <= 0:
            return None
        return 9.0 * numerator / innings

    k_rate = per_batter(strikeouts)
    bb_rate = per_batter(walks)
    k_minus_bb = (
        k_rate - bb_rate if k_rate is not None and bb_rate is not None else None
    )
    ground_to_air = None
    if ground_outs is not None and air_outs and air_outs > 0:
        ground_to_air = ground_outs / air_outs

    return {
        "available": float(bool(stat)),
        "games_pitched": games_pitched,
        "games_started": games_started,
        "season_innings": innings,
        "season_era": era,
        "season_whip": whip,
        "starter_fip": fip,
        "starter_k_rate": k_rate,
        "starter_bb_rate": bb_rate,
        "starter_k_minus_bb": k_minus_bb,
        "starter_k_per_9": per_nine(strikeouts),
        "starter_bb_per_9": per_nine(walks),
        "starter_hr_per_9": per_nine(home_runs),
        "starter_hits_per_9": per_nine(hits),
        "starter_ground_to_air": ground_to_air,
        "batters_faced": batters_faced,
        "strikeouts": strikeouts,
        "walks": walks,
        "hit_batters": hit_batters,
        "home_runs": home_runs,
        "hits": hits,
        "earned_runs": earned_runs,
        "fip_constant": 3.10,
    }


def build_starter_snapshot_payload(
    *,
    game_pk: int,
    scheduled_start: str | datetime,
    side: str,
    team_id: int,
    pitcher_id: int,
    pitcher_name: str | None,
    season: int,
    identity_source: str,
    raw_payload: Mapping[str, Any],
) -> dict[str, Any]:
    if int(game_pk) <= 0:
        raise ValueError("game_pk must be positive")
    if side not in STARTER_SIDES:
        raise ValueError(f"side must be one of {sorted(STARTER_SIDES)}")
    if int(team_id) <= 0 or int(pitcher_id) <= 0:
        raise ValueError("team_id and pitcher_id must be positive")
    if int(season) < 1876:
        raise ValueError("season is not plausible")
    scheduled = _parse_utc(scheduled_start, field_name="scheduled_start")
    raw = dict(raw_payload)
    return {
        "starter_snapshot_schema_version": STARTER_SNAPSHOT_SCHEMA_VERSION,
        "game_pk": int(game_pk),
        "scheduled_start": scheduled.isoformat().replace("+00:00", "Z"),
        "side": side,
        "team_id": int(team_id),
        "pitcher_id": int(pitcher_id),
        "pitcher_name": str(pitcher_name) if pitcher_name else None,
        "season": int(season),
        "identity_source": str(identity_source),
        "stats_source": "mlb_stats_api:v1/people/stats:season",
        "raw_payload_sha256": sha256(_canonical_bytes(raw)).hexdigest(),
        "normalized": parse_pitcher_season_stats(raw),
        "raw_payload": raw,
    }


def _snapshot_files(snapshot_root: str | Path) -> list[Path]:
    root = Path(snapshot_root)
    kind_root = root / STARTER_SNAPSHOT_KIND
    if not kind_root.exists():
        return []
    return sorted(kind_root.rglob("*.json"))


def _load_and_validate_snapshot(path: Path) -> tuple[dict[str, Any] | None, list[StarterSnapshotIssue]]:
    issues: list[StarterSnapshotIssue] = []
    try:
        envelope = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        return None, [StarterSnapshotIssue("invalid_json", str(exc), str(path))]

    payload = envelope.get("payload") or {}
    game_pk = payload.get("game_pk")
    side = payload.get("side")

    def issue(category: str, detail: str) -> None:
        issues.append(
            StarterSnapshotIssue(
                category,
                detail,
                str(path),
                int(game_pk) if isinstance(game_pk, int) or str(game_pk).isdigit() else None,
                str(side) if side is not None else None,
            )
        )

    if envelope.get("kind") != STARTER_SNAPSHOT_KIND:
        issue("identity", f"Unexpected snapshot kind {envelope.get('kind')!r}")
    try:
        captured = _parse_utc(envelope["captured_at"], field_name="captured_at")
        scheduled = _parse_utc(payload["scheduled_start"], field_name="scheduled_start")
        if captured > scheduled:
            issue("post_start", "Starter snapshot was captured after scheduled start")
    except (KeyError, TypeError, ValueError) as exc:
        issue("timestamp", str(exc))

    if side not in STARTER_SIDES:
        issue("identity", f"Invalid side {side!r}")
    try:
        expected_identity = f"{int(payload['game_pk'])}:{side}:{int(payload['pitcher_id'])}"
        if str(envelope.get("identity")) != expected_identity:
            issue("identity", "Envelope identity does not match game/side/pitcher")
    except (KeyError, TypeError, ValueError):
        issue("identity", "Snapshot lacks valid game_pk or pitcher_id")

    raw = payload.get("raw_payload")
    if not isinstance(raw, Mapping):
        issue("payload", "raw_payload is not a JSON object")
    else:
        actual_raw_hash = sha256(_canonical_bytes(raw)).hexdigest()
        if payload.get("raw_payload_sha256") != actual_raw_hash:
            issue("payload", "raw_payload_sha256 mismatch")
        expected_normalized = parse_pitcher_season_stats(raw)
        normalized = payload.get("normalized")
        if not isinstance(normalized, Mapping):
            issue("payload", "normalized starter metrics are missing")
        else:
            for key, expected in expected_normalized.items():
                observed = normalized.get(key)
                if expected is None and observed is None:
                    continue
                try:
                    if expected is None or observed is None or not math.isclose(
                        float(expected), float(observed), rel_tol=1e-10, abs_tol=1e-10
                    ):
                        issue("payload", f"Normalized metric mismatch for {key}")
                        break
                except (TypeError, ValueError):
                    issue("payload", f"Invalid normalized metric for {key}")
                    break

    body_hash = sha256(_canonical_bytes(envelope)).hexdigest()
    if body_hash[:16] not in path.name:
        issue("envelope_hash", "Filename does not match immutable envelope digest")

    return envelope, issues


def audit_starter_snapshots(snapshot_root: str | Path) -> dict[str, Any]:
    """Audit immutable point-in-time starter captures and identity changes."""

    files = _snapshot_files(snapshot_root)
    valid: list[tuple[Path, dict[str, Any]]] = []
    issues: list[StarterSnapshotIssue] = []
    for path in files:
        envelope, snapshot_issues = _load_and_validate_snapshot(path)
        issues.extend(snapshot_issues)
        if envelope is not None and not snapshot_issues:
            valid.append((path, envelope))

    by_game_side: dict[tuple[int, str], list[tuple[Path, dict[str, Any]]]] = {}
    for item in valid:
        payload = item[1]["payload"]
        key = (int(payload["game_pk"]), str(payload["side"]))
        by_game_side.setdefault(key, []).append(item)

    identity_changes: list[dict[str, Any]] = []
    latest_rows: list[dict[str, Any]] = []
    for (game_pk, side), items in sorted(by_game_side.items()):
        ordered = sorted(items, key=lambda item: item[1]["captured_at"])
        pitcher_ids = [int(item[1]["payload"]["pitcher_id"]) for item in ordered]
        unique_ids = list(dict.fromkeys(pitcher_ids))
        if len(unique_ids) > 1:
            identity_changes.append(
                {
                    "game_pk": game_pk,
                    "side": side,
                    "pitcher_ids_in_capture_order": unique_ids,
                    "captures": len(ordered),
                }
            )
        path, envelope = ordered[-1]
        payload = envelope["payload"]
        latest_rows.append(
            {
                "game_pk": game_pk,
                "side": side,
                "pitcher_id": int(payload["pitcher_id"]),
                "pitcher_name": payload.get("pitcher_name"),
                "captured_at": envelope["captured_at"],
                "scheduled_start": payload["scheduled_start"],
                "available": bool((payload.get("normalized") or {}).get("available")),
                "path": str(path),
            }
        )

    sides_by_game: dict[int, set[str]] = {}
    for row in latest_rows:
        sides_by_game.setdefault(int(row["game_pk"]), set()).add(str(row["side"]))
    complete_games = sum(sides == STARTER_SIDES for sides in sides_by_game.values())
    partial_games = sum(sides != STARTER_SIDES for sides in sides_by_game.values())
    unique_pitchers = {int(row["pitcher_id"]) for row in latest_rows}
    issue_counts: dict[str, int] = {}
    for item in issues:
        issue_counts[item.category] = issue_counts.get(item.category, 0) + 1

    return {
        "schema_version": STARTER_SNAPSHOT_SCHEMA_VERSION,
        "generated_at_utc": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "snapshot_root": str(Path(snapshot_root)),
        "status": (
            "FAIL" if issues else "PASS" if files else "PENDING"
        ),
        "summary": {
            "snapshot_files": len(files),
            "valid_snapshots": len(valid),
            "games": len(sides_by_game),
            "complete_two_starter_games": complete_games,
            "partial_games": partial_games,
            "unique_pitchers": len(unique_pitchers),
            "identity_changes": len(identity_changes),
        },
        "identity_changes": identity_changes,
        "latest_snapshots": latest_rows,
        "issue_counts": issue_counts,
        "issues": [item.to_record() for item in issues],
    }


def latest_starter_training_rows(snapshot_root: str | Path) -> pd.DataFrame:
    """Return one latest valid pregame row per official game and side."""

    valid: list[dict[str, Any]] = []
    for path in _snapshot_files(snapshot_root):
        envelope, issues = _load_and_validate_snapshot(path)
        if envelope is None or issues:
            continue
        payload = envelope["payload"]
        normalized = payload.get("normalized") or {}
        row = {
            "game_pk": int(payload["game_pk"]),
            "side": str(payload["side"]),
            "team_id": int(payload["team_id"]),
            "pitcher_id": int(payload["pitcher_id"]),
            "pitcher_name": payload.get("pitcher_name"),
            "season": int(payload["season"]),
            "captured_at": envelope["captured_at"],
            "scheduled_start": payload["scheduled_start"],
            "identity_source": payload.get("identity_source"),
            "stats_source": payload.get("stats_source"),
            "raw_payload_sha256": payload.get("raw_payload_sha256"),
            "snapshot_path": str(path),
            **normalized,
        }
        valid.append(row)
    if not valid:
        return pd.DataFrame()
    frame = pd.DataFrame(valid)
    frame["captured_at_dt"] = pd.to_datetime(frame["captured_at"], utc=True)
    frame = frame.sort_values(["game_pk", "side", "captured_at_dt"])
    frame = frame.groupby(["game_pk", "side"], as_index=False).tail(1)
    return frame.drop(columns=["captured_at_dt"]).sort_values(
        ["game_pk", "side"]
    ).reset_index(drop=True)


def write_starter_audit_report(snapshot_root: str | Path, output: str | Path) -> dict[str, Any]:
    report = audit_starter_snapshots(snapshot_root)
    path = Path(output)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(report, indent=2), encoding="utf-8")
    return report


def export_starter_training_rows(snapshot_root: str | Path, output: str | Path) -> Path:
    frame = latest_starter_training_rows(snapshot_root)
    path = Path(output)
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.suffix.lower() == ".json":
        path.write_text(
            json.dumps(frame.to_dict("records"), indent=2, default=str),
            encoding="utf-8",
        )
    else:
        frame.to_csv(path, index=False)
    return path
