from __future__ import annotations

from datetime import date, datetime, timezone
import json
import math
from pathlib import Path
import sys
from typing import Any

import pandas as pd

from supermodel.odds_input import OddsInputError, build_moneyline_template, moneylines_from_records
from supermodel.workflow import capture_official_slate, evaluate_captured_slate


_DATA_DIR = Path("data/2026")
_SNAPSHOT_DIR = Path("runtime/snapshots")
_OUTPUT_DIR = Path("runtime/reports")
_EVIDENCE_LEDGER = Path("runtime/evidence/prospective.jsonl")
_ADAPTIVE_OVERLAY = Path("runtime/models/v2_4_adaptive_overlay.json")
_DEFAULT_SIMULATIONS = 100_000
_DEFAULT_TOP_N = 5


_APP_CSS = """
<style>
    .stApp {
        background:
            radial-gradient(circle at 4% 0%, rgba(46, 204, 113, 0.09), transparent 25rem),
            radial-gradient(circle at 96% 8%, rgba(56, 189, 248, 0.08), transparent 24rem),
            #071019;
    }
    [data-testid="stHeader"] { background: rgba(7, 16, 25, 0.85); }
    [data-testid="stSidebar"] { display: none; }
    .block-container { max-width: 1420px; padding-top: 1.4rem; padding-bottom: 4rem; }
    .ssm-hero {
        border: 1px solid rgba(148, 163, 184, 0.18);
        border-radius: 22px;
        padding: 1.4rem 1.55rem;
        margin-bottom: 1rem;
        background: linear-gradient(135deg, rgba(15, 31, 45, 0.96), rgba(8, 20, 30, 0.93));
        box-shadow: 0 20px 50px rgba(0,0,0,0.24);
    }
    .ssm-eyebrow { color: #54d98c; font-size: .76rem; font-weight: 800; letter-spacing: .12em; text-transform: uppercase; }
    .ssm-title { color: #f8fafc; font-size: 2.15rem; line-height: 1.08; font-weight: 850; margin: .3rem 0 .45rem; }
    .ssm-subtitle { color: #a7b6c7; font-size: 1rem; margin: 0; }
    .ssm-status-grid { display: grid; grid-template-columns: repeat(4, minmax(0, 1fr)); gap: .65rem; margin-top: 1.05rem; }
    .ssm-status {
        border: 1px solid rgba(148,163,184,.16); border-radius: 14px; padding: .72rem .8rem;
        background: rgba(3, 10, 17, .38);
    }
    .ssm-status-label { color: #7f92a8; font-size: .7rem; letter-spacing: .08em; text-transform: uppercase; font-weight: 750; }
    .ssm-status-value { color: #f8fafc; font-size: .96rem; font-weight: 750; margin-top: .12rem; }
    .ssm-section-title { color: #f8fafc; font-size: 1.22rem; font-weight: 780; margin: .4rem 0 .1rem; }
    .ssm-section-copy { color: #8ea0b5; margin-bottom: .7rem; }
    .ssm-game-card {
        border: 1px solid rgba(148, 163, 184, 0.17);
        border-radius: 18px;
        padding: .82rem 1rem .45rem;
        background: rgba(12, 25, 37, .82);
        margin-bottom: .65rem;
    }
    .ssm-game-card.locked { opacity: .70; background: rgba(16, 24, 32, .68); }
    .ssm-game-kicker { color: #8394a8; font-size: .72rem; text-transform: uppercase; letter-spacing: .08em; font-weight: 700; }
    .ssm-matchup { color: #f8fafc; font-size: 1.14rem; font-weight: 800; margin-top: .12rem; }
    .ssm-meta { color: #9baabd; font-size: .82rem; margin-top: .24rem; }
    .ssm-pill {
        display: inline-block; border-radius: 999px; padding: .18rem .52rem; margin-right: .28rem;
        background: rgba(84, 217, 140, .11); color: #6fe0a0; border: 1px solid rgba(84, 217, 140, .22);
        font-size: .7rem; font-weight: 750;
    }
    .ssm-pill.warn { background: rgba(251, 191, 36, .10); color: #facc55; border-color: rgba(251, 191, 36, .20); }
    .ssm-pill.locked { background: rgba(248, 113, 113, .10); color: #f89191; border-color: rgba(248, 113, 113, .20); }
    .ssm-result-card {
        border: 1px solid rgba(148, 163, 184, 0.18); border-radius: 18px; padding: 1rem 1.05rem;
        background: linear-gradient(145deg, rgba(13, 29, 42, .95), rgba(8, 18, 28, .96));
        margin-bottom: .65rem;
    }
    .ssm-rank { color: #63df9a; font-size: .72rem; text-transform: uppercase; letter-spacing: .10em; font-weight: 800; }
    .ssm-pick { color: #f8fafc; font-size: 1.25rem; font-weight: 850; margin: .16rem 0; }
    .ssm-small { color: #8fa0b3; font-size: .8rem; }
    .ssm-model-label { color: #7f92a8; font-size: .66rem; text-transform: uppercase; letter-spacing: .08em; font-weight: 750; }
    .ssm-model-value { color: #f8fafc; font-size: 1rem; font-weight: 780; }
    .ssm-disagree { color: #facc55; font-weight: 750; }
    .ssm-agree { color: #6fe0a0; font-weight: 750; }
    div[data-testid="stButton"] > button { border-radius: 12px; font-weight: 750; }
    div[data-testid="stNumberInput"] input, div[data-testid="stTextInput"] input,
    div[data-baseweb="select"] > div { border-radius: 11px; }
    [data-testid="stMetric"] {
        border: 1px solid rgba(148, 163, 184, 0.16); border-radius: 15px; padding: .7rem .8rem;
        background: rgba(10, 22, 33, .72);
    }
    @media (max-width: 900px) {
        .ssm-status-grid { grid-template-columns: repeat(2, minmax(0, 1fr)); }
        .ssm-title { font-size: 1.75rem; }
    }
</style>
"""


def _require_streamlit():
    try:
        import streamlit as st
    except ImportError as exc:  # pragma: no cover - exercised by users without UI extra
        raise SystemExit(
            "The web interface requires Streamlit. Install it with: "
            'python -m pip install -e ".[ui]"'
        ) from exc
    return st


def _parse_game_time(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _is_game_locked(context: Any, *, now: datetime | None = None) -> bool:
    """Return whether a game can no longer accept a point-in-time pregame market."""

    status = " ".join(
        str(value or "")
        for value in (
            getattr(context, "status_abstract", None),
            getattr(context, "status_detailed", None),
        )
    ).strip().lower()
    if any(token in status for token in ("live", "in progress", "final", "completed", "game over")):
        return True
    start = _parse_game_time(getattr(context, "game_datetime", None))
    if start is None:
        return False
    timestamp = now or datetime.now(timezone.utc)
    if timestamp.tzinfo is None or timestamp.utcoffset() is None:
        timestamp = timestamp.replace(tzinfo=timezone.utc)
    return timestamp.astimezone(timezone.utc) >= start


def _format_game_time(value: str | None) -> str:
    parsed = _parse_game_time(value)
    if parsed is None:
        return "Time TBD"
    local = parsed.astimezone()
    hour = local.strftime("%I").lstrip("0") or "0"
    return f"{local.strftime('%a %b')} {local.day} · {hour}:{local.strftime('%M %p')}"


def _format_probability(value: Any) -> str:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return "—"
    if not math.isfinite(number):
        return "—"
    return f"{100.0 * number:.1f}%"


def _format_number(value: Any, digits: int = 1, *, signed: bool = False) -> str:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return "—"
    if not math.isfinite(number):
        return "—"
    prefix = "+" if signed and number > 0 else ""
    return f"{prefix}{number:.{digits}f}"


def _odds_text_to_number(value: Any, odds_format: str) -> float | int | None:
    text = str(value or "").strip().replace(",", "")
    if not text:
        return None
    try:
        number = float(text)
    except ValueError as exc:
        raise OddsInputError(f"Invalid odds value: {value!r}") from exc
    if not math.isfinite(number):
        raise OddsInputError(f"Invalid odds value: {value!r}")
    if odds_format == "american":
        if -100 < number < 100:
            raise OddsInputError("American odds must be at least +100 or at most -100.")
        return int(number)
    if number <= 1.0:
        raise OddsInputError("Decimal odds must be greater than 1.00.")
    return number


def _context_table(captured, *, now: datetime | None = None) -> pd.DataFrame:
    template = build_moneyline_template(captured.contexts)
    lock_by_pk = {
        context.game_pk: _is_game_locked(context, now=now) for context in captured.contexts
    }
    template["locked"] = template["game_pk"].map(lock_by_pk).fillna(False)
    template.loc[template["locked"], "include"] = False
    return template


def _inject_branding(st) -> None:
    st.markdown(_APP_CSS, unsafe_allow_html=True)
    st.markdown(
        """
        <div class="ssm-hero">
          <div class="ssm-eyebrow">MLB decision intelligence</div>
          <div class="ssm-title">Sports SuperModel</div>
          <p class="ssm-subtitle">Production-grade V2.3.3 analysis with V2.4 RC2 shadow tracking on the same slate.</p>
          <div class="ssm-status-grid">
            <div class="ssm-status"><div class="ssm-status-label">Production</div><div class="ssm-status-value">V2.3.3</div></div>
            <div class="ssm-status"><div class="ssm-status-label">Shadow</div><div class="ssm-status-value">V2.4 RC2</div></div>
            <div class="ssm-status"><div class="ssm-status-label">Ensemble</div><div class="ssm-status-value">7 models per track</div></div>
            <div class="ssm-status"><div class="ssm-status-label">Simulation</div><div class="ssm-status-value">100,000 per game</div></div>
          </div>
        </div>
        """,
        unsafe_allow_html=True,
    )


def _capture_slate(st, *, game_date: str, force: bool = False):
    capture_key = f"captured:{game_date}"
    if force:
        st.session_state.pop(capture_key, None)
        st.session_state.pop(f"odds:{game_date}", None)
        st.session_state.pop(f"result:{game_date}", None)
        for key in list(st.session_state):
            if key.startswith((f"odds-away:{game_date}:", f"odds-home:{game_date}:", f"odds-include:{game_date}:")):
                st.session_state.pop(key, None)
    if capture_key in st.session_state:
        return st.session_state[capture_key]
    with st.spinner("Loading the official MLB slate and point-in-time context…"):
        try:
            captured = capture_official_slate(
                game_date=game_date,
                snapshot_dir=_SNAPSHOT_DIR,
            )
        except Exception as exc:  # Streamlit should show a useful error instead of crashing.
            st.session_state[f"capture_error:{game_date}"] = str(exc)
            return None
    st.session_state[capture_key] = captured
    st.session_state.pop(f"capture_error:{game_date}", None)
    return captured


def _game_header_html(context: Any, *, locked: bool) -> str:
    starter_away = getattr(context, "away_probable_pitcher_name", None) or "Starter TBD"
    starter_home = getattr(context, "home_probable_pitcher_name", None) or "Starter TBD"
    venue = getattr(context, "venue_name", None) or "Venue TBD"
    weather = getattr(context, "weather_condition", None) or "Weather TBD"
    lineups = bool(getattr(context, "lineups_confirmed", False))
    status_pill = (
        '<span class="ssm-pill locked">Started · locked</span>'
        if locked
        else '<span class="ssm-pill">Pregame</span>'
    )
    lineup_pill = (
        '<span class="ssm-pill">Lineups confirmed</span>'
        if lineups
        else '<span class="ssm-pill warn">Lineups pending</span>'
    )
    card_class = "ssm-game-card locked" if locked else "ssm-game-card"
    game_number = getattr(context, "game_number", None)
    game_label = f"Game {game_number}" if game_number and int(game_number) > 1 else "MLB matchup"
    return f"""
    <div class="{card_class}">
      <div class="ssm-game-kicker">{game_label} · {_format_game_time(getattr(context, 'game_datetime', None))}</div>
      <div class="ssm-matchup">{getattr(context, 'away_team', 'Away')} at {getattr(context, 'home_team', 'Home')}</div>
      <div class="ssm-meta">{starter_away} vs {starter_home} · {venue} · {weather}</div>
      <div style="margin-top:.45rem">{status_pill}{lineup_pill}</div>
    </div>
    """


def _render_odds_cards(st, captured, *, game_date: str, odds_format: str) -> pd.DataFrame:
    base = _context_table(captured)
    state_key = f"odds:{game_date}"
    odds_state = st.session_state.setdefault(state_key, {})
    rows: list[dict[str, Any]] = []

    for context in captured.contexts:
        game_pk = int(context.game_pk) if context.game_pk is not None else None
        locked = _is_game_locked(context)
        st.markdown(_game_header_html(context, locked=locked), unsafe_allow_html=True)
        left, middle, right = st.columns([1.35, 1.35, 0.72])
        away_key = f"odds-away:{game_date}:{game_pk}"
        home_key = f"odds-home:{game_date}:{game_pk}"
        include_key = f"odds-include:{game_date}:{game_pk}"
        if away_key not in st.session_state:
            st.session_state[away_key] = odds_state.get(str(game_pk), {}).get("away", "")
        if home_key not in st.session_state:
            st.session_state[home_key] = odds_state.get(str(game_pk), {}).get("home", "")
        if include_key not in st.session_state:
            st.session_state[include_key] = not locked

        with left:
            away_value = st.text_input(
                f"{context.away_team} moneyline",
                key=away_key,
                placeholder="+125" if odds_format == "american" else "2.25",
                disabled=locked,
            )
        with middle:
            home_value = st.text_input(
                f"{context.home_team} moneyline",
                key=home_key,
                placeholder="-145" if odds_format == "american" else "1.67",
                disabled=locked,
            )
        with right:
            include = st.checkbox("Analyze", key=include_key, disabled=locked)
        odds_state[str(game_pk)] = {"away": away_value, "home": home_value}

        matching = base.loc[base["game_pk"] == game_pk]
        if matching.empty:
            continue
        row = matching.iloc[0].to_dict()
        row.update(
            {
                "include": bool(include and not locked),
                "away_odds": away_value,
                "home_odds": home_value,
                "odds_format": odds_format,
                "locked": locked,
            }
        )
        rows.append(row)
    return pd.DataFrame(rows)


def _render_result_cards(st, evaluation: pd.DataFrame, *, top_n: int) -> None:
    if evaluation.empty:
        st.warning("The model returned no eligible games.")
        return
    if "is_top_pick" in evaluation.columns:
        ranked = evaluation[evaluation["is_top_pick"]].copy()
        sort_column = "selection_rank" if "selection_rank" in ranked.columns else "confidence_rank"
        ranked = ranked.sort_values(sort_column).head(top_n)
    else:
        ranked = evaluation.sort_values("confidence_rank").head(top_n)
    if ranked.empty:
        st.warning(
            "No games passed the consensus and confidence gates. Review the complete "
            "table for PASS/CONFLICT matchups rather than forcing five picks."
        )
        return
    for _, row in ranked.iterrows():
        disagree = bool(row.get("production_shadow_disagree", False))
        production_pick = row.get("pick", "—")
        shadow_pick = row.get("shadow_pick", "—")
        agreement_text = "V2.3.3 and V2.4 disagree" if disagree else "Production and shadow agree"
        agreement_class = "ssm-disagree" if disagree else "ssm-agree"
        simulated_score = (
            f"{row.get('away_team', 'Away')} {_format_number(row.get('simulated_away_runs'))} · "
            f"{row.get('home_team', 'Home')} {_format_number(row.get('simulated_home_runs'))}"
        )
        st.markdown(
            f"""
            <div class="ssm-result-card">
              <div class="ssm-rank">Top-pick rank #{int(row.get('selection_rank', row.get('confidence_rank', 0)))}</div>
              <div class="ssm-pick">{production_pick} <span class="ssm-small">{row.get('pick_odds', '—')}</span></div>
              <div class="ssm-small">{row.get('away_team', 'Away')} at {row.get('home_team', 'Home')} · Simulated score: {simulated_score}</div>
              <div style="margin-top:.8rem; display:grid; grid-template-columns:repeat(4,minmax(0,1fr)); gap:.65rem">
                <div><div class="ssm-model-label">V2.3.3 probability</div><div class="ssm-model-value">{_format_probability(row.get('pick_probability'))}</div></div>
                <div><div class="ssm-model-label">Production overlap</div><div class="ssm-model-value">{row.get('model_overlap', '—')}/{row.get('model_count', 7)}</div></div>
                <div><div class="ssm-model-label">V2.4 shadow</div><div class="ssm-model-value">{shadow_pick} · {_format_probability(row.get('shadow_pick_probability'))}</div></div>
                <div><div class="ssm-model-label">Shadow overlap</div><div class="ssm-model-value">{row.get('shadow_model_overlap', '—')}/7</div></div>
              </div>
              <div class="{agreement_class}" style="margin-top:.72rem">{agreement_text}</div>
            </div>
            """,
            unsafe_allow_html=True,
        )


def _results_table(evaluation: pd.DataFrame) -> pd.DataFrame:
    display_columns = [
        "confidence_rank",
        "selection_rank",
        "selection_status",
        "selection_reasons",
        "away_team",
        "home_team",
        "pick",
        "pick_odds",
        "pick_probability",
        "model_overlap",
        "model_count",
        "shadow_pick",
        "shadow_pick_probability",
        "shadow_model_overlap",
        "production_shadow_disagree",
        "simulated_away_runs",
        "simulated_home_runs",
        "fair_odds",
        "edge_vs_no_vig",
        "lineups_confirmed",
        "history_freshness_status",
        "history_checked_through",
    ]
    available = [column for column in display_columns if column in evaluation.columns]
    display = evaluation[available].copy()
    if "pick_probability" in display:
        display["pick_probability_pct"] = 100.0 * display.pop("pick_probability")
    if "shadow_pick_probability" in display:
        display["shadow_pick_probability_pct"] = 100.0 * display.pop(
            "shadow_pick_probability"
        )
    if "edge_vs_no_vig" in display:
        display["edge_vs_no_vig_pct"] = 100.0 * display.pop("edge_vs_no_vig")
    return display


def _render_advanced_results(st, result, captured) -> None:
    with st.expander("Advanced results, attribution, and downloads"):
        st.markdown("#### Complete comparison table")
        st.dataframe(
            _results_table(result.evaluation),
            use_container_width=True,
            hide_index=True,
            column_config={
                "pick_probability_pct": st.column_config.NumberColumn(
                    "V2.3.3 probability", format="%.1f%%"
                ),
                "shadow_pick_probability_pct": st.column_config.NumberColumn(
                    "V2.4 probability", format="%.1f%%"
                ),
                "edge_vs_no_vig_pct": st.column_config.NumberColumn(
                    "Edge vs no-vig", format="%+.1f%%"
                ),
            },
        )

        sensitivity_columns = [
            column
            for column in result.evaluation.columns
            if column.startswith("shadow_ensemble_pick_sensitivity_")
        ]
        if sensitivity_columns:
            st.markdown("#### V2.4 feature-group sensitivity")
            game_labels = {
                f"{row.away_team} at {row.home_team} — {row.shadow_pick}": index
                for index, row in result.evaluation.iterrows()
            }
            selected_label = st.selectbox("Game", list(game_labels), key="advanced-game")
            selected = result.evaluation.loc[game_labels[selected_label]]
            sensitivity = pd.DataFrame(
                {
                    "feature_group": [
                        column.removeprefix("shadow_ensemble_pick_sensitivity_")
                        for column in sensitivity_columns
                    ],
                    "effect_on_pick_probability_pp": [
                        100.0 * float(selected[column]) for column in sensitivity_columns
                    ],
                }
            ).sort_values(
                "effect_on_pick_probability_pp", key=lambda values: values.abs(), ascending=False
            )
            st.dataframe(
                sensitivity,
                use_container_width=True,
                hide_index=True,
                column_config={
                    "effect_on_pick_probability_pp": st.column_config.NumberColumn(
                        "Effect on shadow probability (pp)", format="%+.2f"
                    ),
                },
            )
            st.caption(
                "Sensitivity values compare the normal ensemble with the same feature group "
                "replaced by training medians. They are diagnostic, non-causal, and non-additive."
            )

        st.markdown("#### Downloads")
        download_1, download_2, download_3 = st.columns(3)
        with download_1:
            st.download_button(
                "Results CSV",
                data=result.evaluation.to_csv(index=False).encode("utf-8"),
                file_name=result.csv_path.name,
                mime="text/csv",
                use_container_width=True,
            )
        with download_2:
            st.download_button(
                "Results JSON",
                data=json.dumps(result.evaluation.to_dict("records"), indent=2, default=str),
                file_name=result.json_path.name,
                mime="application/json",
                use_container_width=True,
            )
        with download_3:
            template = _context_table(captured)
            st.download_button(
                "Slate template",
                data=template.to_csv(index=False).encode("utf-8"),
                file_name=f"moneylines_{captured.game_date}.csv",
                mime="text/csv",
                use_container_width=True,
            )

        with st.expander("Reproducibility artifacts"):
            st.code(
                "\n".join(
                    str(path)
                    for path in [
                        result.csv_path,
                        result.parlay_path,
                        result.json_path,
                        result.market_snapshot_path,
                        result.evidence_ledger_path,
                        result.adaptive_overlay_path,
                        captured.schedule_path,
                    ]
                    if path is not None
                )
            )


def render_app() -> None:
    st = _require_streamlit()
    st.set_page_config(
        page_title="Sports SuperModel",
        page_icon="⚾",
        layout="wide",
        initial_sidebar_state="collapsed",
    )
    _inject_branding(st)

    controls = st.container(border=True)
    with controls:
        left, middle, right, action = st.columns([1.15, 1, 1, .8])
        with left:
            game_date_value = st.date_input("Slate date", value=date.today())
        game_date = game_date_value.isoformat()
        with middle:
            odds_format = st.selectbox(
                "Odds format",
                ["american", "decimal"],
                format_func=lambda value: "American" if value == "american" else "Decimal",
            )
        with right:
            top_n = st.selectbox("Top picks shown", [3, 5, 7, 10], index=1)
        with action:
            refresh = st.button("Refresh slate", use_container_width=True)

        settings_left, settings_right = st.columns([1.4, 1])
        with settings_left:
            st.caption(
                "The app captures official starter, lineup, bullpen, weather, park, and recent-form "
                "context. Current team/starter history drives the base models; weather and park apply "
                "bounded score-simulation adjustments. Other advanced live context is recorded for "
                "prospective validation and does not alter the base prediction unless explicitly activated."
            )
        with settings_right:
            include_parlays = st.toggle("Show two-leg comparison", value=True)

    captured = _capture_slate(st, game_date=game_date, force=refresh)
    if captured is None:
        st.error(
            "The official slate could not be loaded. Check your connection and use Refresh slate."
        )
        error = st.session_state.get(f"capture_error:{game_date}")
        if error:
            with st.expander("Technical details"):
                st.code(error)
        return

    available_games = sum(not _is_game_locked(context) for context in captured.contexts)
    locked_games = len(captured.contexts) - available_games
    metric_1, metric_2, metric_3, metric_4 = st.columns(4)
    metric_1.metric("Official games", len(captured.contexts))
    metric_2.metric("Pregame available", available_games)
    metric_3.metric("Started / locked", locked_games)
    metric_4.metric("Captured", captured.captured_at.astimezone().strftime("%I:%M %p"))

    st.markdown('<div class="ssm-section-title">Enter today’s market</div>', unsafe_allow_html=True)
    st.markdown(
        '<div class="ssm-section-copy">Add both sides of each moneyline. Leave a game unchecked to exclude it.</div>',
        unsafe_allow_html=True,
    )
    edited = _render_odds_cards(st, captured, game_date=game_date, odds_format=odds_format)

    selected_count = int(edited.get("include", pd.Series(dtype=bool)).fillna(False).sum())
    complete_count = int(
        (
            edited.get("include", pd.Series(dtype=bool)).fillna(False)
            & edited.get("away_odds", pd.Series(dtype=str)).astype(str).str.strip().ne("")
            & edited.get("home_odds", pd.Series(dtype=str)).astype(str).str.strip().ne("")
        ).sum()
    )
    run_left, run_middle, run_right = st.columns([1.35, 1, 1])
    with run_left:
        acknowledged = st.checkbox(
            "I understand this is experimental recreational research software, not advice."
        )
    with run_middle:
        st.metric("Complete selected games", f"{complete_count}/{selected_count}")
    with run_right:
        run_clicked = st.button(
            "Run full slate analysis",
            type="primary",
            use_container_width=True,
            disabled=not acknowledged or complete_count == 0,
        )

    result_key = f"result:{game_date}"
    result = st.session_state.get(result_key)
    if run_clicked:
        records = edited.copy()
        try:
            records["away_odds"] = [
                _odds_text_to_number(value, odds_format) for value in records["away_odds"]
            ]
            records["home_odds"] = [
                _odds_text_to_number(value, odds_format) for value in records["home_odds"]
            ]
            moneylines = moneylines_from_records(
                records.to_dict("records"),
                default_date=game_date,
                default_format=odds_format,
            )
        except OddsInputError as exc:
            st.error(str(exc))
            return

        with st.spinner(
            "Running V2.3.3 production, V2.4 RC2 shadow, all seven models, and "
            "100,000 simulations per game…"
        ):
            try:
                result = evaluate_captured_slate(
                    captured_slate=captured,
                    moneylines=moneylines,
                    data_dir=_DATA_DIR,
                    snapshot_dir=_SNAPSHOT_DIR,
                    output_dir=_OUTPUT_DIR,
                    evidence_ledger=_EVIDENCE_LEDGER,
                    adaptive_overlay_path=_ADAPTIVE_OVERLAY,
                    simulations=_DEFAULT_SIMULATIONS,
                    top_n=int(top_n),
                    include_parlays=include_parlays,
                    input_source=f"streamlit_cards:{odds_format}",
                )
            except Exception as exc:
                st.error(f"Evaluation failed: {exc}")
                return
        st.session_state[result_key] = result
        st.success("Slate analysis complete. V2.4 shadow evidence was recorded for eligible games.")

    if result is None:
        with st.expander("Method and data safeguards"):
            st.markdown(
                "V2.3.3 remains the production track. V2.4 RC2 runs on the same captured slate "
                "in shadow mode and writes versioned prospective evidence. Each track uses the "
                "canonical seven-model ensemble; score probabilities use 100,000 simulations per game."
            )
        return
    st.markdown('<div class="ssm-section-title">Confidence board</div>', unsafe_allow_html=True)
    st.markdown(
        '<div class="ssm-section-copy">Official selections are ranked by V2.3.3 production confidence, with V2.4 RC2 shown beside them.</div>',
        unsafe_allow_html=True,
    )
    _render_result_cards(st, result.evaluation, top_n=int(top_n))

    if result.parlays is not None and not result.parlays.empty:
        with st.expander("Two-leg comparison"):
            st.dataframe(result.parlays, use_container_width=True, hide_index=True)

    _render_advanced_results(st, result, captured)

    with st.expander("Recreational-use notice"):
        st.markdown(
            "This experimental software is for recreational, educational, and research use only. "
            "It does not guarantee accuracy or profit. Independently verify all inputs and outputs."
        )


def launch() -> None:
    """Launch the local Streamlit interface from the installed console script."""

    try:
        from streamlit.web import cli as stcli
    except ImportError as exc:  # pragma: no cover
        raise SystemExit(
            "The web interface requires Streamlit. Install it with: "
            'python -m pip install -e ".[ui]"'
        ) from exc
    sys.argv = ["streamlit", "run", str(Path(__file__).resolve())]
    raise SystemExit(stcli.main())


if __name__ == "__main__":
    render_app()
