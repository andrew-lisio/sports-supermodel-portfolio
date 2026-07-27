from __future__ import annotations

from datetime import date
import json
from pathlib import Path
import sys

import pandas as pd

from supermodel.odds_input import (
    OddsInputError,
    build_moneyline_template,
    moneylines_from_records,
)
from supermodel.workflow import capture_official_slate, evaluate_captured_slate


def _require_streamlit():
    try:
        import streamlit as st
    except ImportError as exc:  # pragma: no cover - exercised by users without UI extra
        raise SystemExit(
            "The web interface requires Streamlit. Install it with: "
            "python -m pip install -e \".[ui]\""
        ) from exc
    return st


def _context_table(captured) -> pd.DataFrame:
    template = build_moneyline_template(captured.contexts)
    display_columns = [
        "include",
        "game_date",
        "game_pk",
        "game_number",
        "game_datetime_utc",
        "away_team",
        "home_team",
        "away_starter",
        "home_starter",
        "lineups_confirmed",
        "weather",
        "wind",
        "away_odds",
        "home_odds",
    ]
    return template[display_columns]


def render_app() -> None:
    st = _require_streamlit()
    st.set_page_config(page_title="Sports SuperModel", page_icon="⚾", layout="wide")
    st.title("⚾ Sports SuperModel")
    st.caption(
        "V2.3.3 production plus V2.4 shadow · seven winner models per track · "
        "Poisson score model · Monte Carlo simulation · no Kelly criterion or stake sizing"
    )

    with st.expander("Important recreational-use notice", expanded=True):
        st.markdown(
            "This experimental software is for recreational, educational, and research use only. "
            "It is not gambling, financial, legal, or professional advice and does not guarantee "
            "accuracy or profit. Users are responsible for legal-age and jurisdictional compliance, "
            "independent verification, and all decisions or losses. Read `DISCLAIMER.md` before use."
        )

    with st.sidebar:
        st.header("Run settings")
        game_date_value = st.date_input("Slate date", value=date.today())
        game_date = game_date_value.isoformat()
        simulations = st.number_input(
            "Simulations per game",
            min_value=1_000,
            max_value=1_000_000,
            value=100_000,
            step=10_000,
        )
        top_n = st.number_input("Top picks", min_value=1, max_value=15, value=5, step=1)
        odds_format = st.selectbox("Odds input format", ["american", "decimal"])
        include_parlays = st.checkbox("Create optional two-leg comparison", value=True)
        data_dir = st.text_input("Historical data directory", value="data/2026")
        snapshot_dir = st.text_input("Snapshot directory", value="runtime/snapshots")
        output_dir = st.text_input("Output directory", value="runtime/reports")
        evidence_ledger = st.text_input(
            "Prospective evidence ledger", value="runtime/evidence/prospective.jsonl"
        )
        adaptive_overlay = st.text_input(
            "V2.4 adaptive overlay", value="runtime/models/v2_4_adaptive_overlay.json"
        )
        st.caption("Run the app from the repository root so these relative paths resolve correctly.")

    capture_key = f"captured:{game_date}"
    if st.button("1. Fetch official MLB slate", type="primary"):
        with st.spinner("Fetching official schedule, probable pitchers, lineups, and weather context..."):
            try:
                captured = capture_official_slate(
                    game_date=game_date,
                    snapshot_dir=snapshot_dir,
                )
            except Exception as exc:  # Streamlit should show a useful error instead of crashing.
                st.error(f"Could not capture the slate: {exc}")
            else:
                st.session_state[capture_key] = captured
                st.session_state.pop(f"edited:{game_date}", None)
                st.success(
                    f"Captured {len(captured.contexts)} official games at "
                    f"{captured.captured_at.isoformat()}"
                )

    captured = st.session_state.get(capture_key)
    if captured is None:
        st.info("Fetch the official slate to create an editable moneyline table.")
        return

    st.subheader("2. Enter the market lines")
    st.write(
        "Type both sides of each two-way moneyline directly into the table. Uncheck or leave both "
        "odds cells blank to skip a game. Official `game_pk` values keep doubleheaders separate."
    )
    base_frame = _context_table(captured)
    state_key = f"edited:{game_date}"
    if state_key not in st.session_state:
        st.session_state[state_key] = base_frame

    disabled_columns = [
        "game_date",
        "game_pk",
        "game_number",
        "game_datetime_utc",
        "away_team",
        "home_team",
        "away_starter",
        "home_starter",
        "lineups_confirmed",
        "weather",
        "wind",
    ]
    edited = st.data_editor(
        st.session_state[state_key],
        use_container_width=True,
        hide_index=True,
        disabled=disabled_columns,
        num_rows="fixed",
        column_config={
            "include": st.column_config.CheckboxColumn("Include"),
            "away_odds": st.column_config.NumberColumn(
                f"Away odds ({odds_format})", format="%.2f" if odds_format == "decimal" else "%d"
            ),
            "home_odds": st.column_config.NumberColumn(
                f"Home odds ({odds_format})", format="%.2f" if odds_format == "decimal" else "%d"
            ),
        },
        key=f"editor:{game_date}",
    )
    st.session_state[state_key] = edited

    template_for_download = edited.copy()
    template_for_download["odds_format"] = odds_format
    st.download_button(
        "Download this slate as CSV",
        data=template_for_download.to_csv(index=False).encode("utf-8"),
        file_name=f"moneylines_{game_date}.csv",
        mime="text/csv",
    )

    acknowledged = st.checkbox(
        "I understand that this is experimental recreational research software and not advice."
    )
    run_clicked = st.button("3. Run every model and simulate the slate", disabled=not acknowledged)
    if not run_clicked:
        return

    records = edited.copy()
    records["odds_format"] = odds_format
    try:
        moneylines = moneylines_from_records(
            records.to_dict("records"),
            default_date=game_date,
            default_format=odds_format,
        )
    except OddsInputError as exc:
        st.error(str(exc))
        return

    with st.spinner(
        f"Fitting all seven winner models and running {int(simulations):,} simulations per game..."
    ):
        try:
            result = evaluate_captured_slate(
                captured_slate=captured,
                moneylines=moneylines,
                data_dir=Path(data_dir),
                snapshot_dir=Path(snapshot_dir),
                output_dir=Path(output_dir),
                evidence_ledger=Path(evidence_ledger),
                adaptive_overlay_path=Path(adaptive_overlay),
                simulations=int(simulations),
                top_n=int(top_n),
                include_parlays=include_parlays,
                input_source=f"streamlit_editor:{odds_format}",
            )
        except Exception as exc:
            st.error(f"Evaluation failed: {exc}")
            return

    st.success("Evaluation complete")
    st.subheader("Confidence-first production rankings with V2.4 shadow comparison")
    display_columns = [
        "confidence_rank",
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
        "shadow_adaptive_overlay_status",
        "shadow_adaptive_overlay_training_games",
        "simulated_away_runs",
        "simulated_home_runs",
        "fair_odds",
        "edge_vs_no_vig",
        "top_supporting_group",
        "top_supporting_sensitivity",
        "top_opposing_group",
        "top_opposing_sensitivity",
        "lineups_confirmed",
    ]
    available = [column for column in display_columns if column in result.evaluation.columns]
    display = result.evaluation[available].copy()
    if "pick_probability" in display:
        display["pick_probability_pct"] = 100.0 * display.pop("pick_probability")
    if "shadow_pick_probability" in display:
        display["shadow_pick_probability_pct"] = 100.0 * display.pop(
            "shadow_pick_probability"
        )
    if "edge_vs_no_vig" in display:
        display["edge_vs_no_vig_pct"] = 100.0 * display.pop("edge_vs_no_vig")
    if "top_supporting_sensitivity" in display:
        display["top_supporting_sensitivity_pp"] = (
            100.0 * display.pop("top_supporting_sensitivity")
        )
    if "top_opposing_sensitivity" in display:
        display["top_opposing_sensitivity_pp"] = (
            100.0 * display.pop("top_opposing_sensitivity")
        )
    st.dataframe(
        display,
        use_container_width=True,
        hide_index=True,
        column_config={
            "pick_probability_pct": st.column_config.NumberColumn(
                "Pick probability", format="%.1f%%"
            ),
            "shadow_pick_probability_pct": st.column_config.NumberColumn(
                "V2.4 shadow probability", format="%.1f%%"
            ),
            "edge_vs_no_vig_pct": st.column_config.NumberColumn(
                "Edge vs no-vig", format="%.1f%%"
            ),
            "top_supporting_sensitivity_pp": st.column_config.NumberColumn(
                "Top support (pp)", format="%+.2f"
            ),
            "top_opposing_sensitivity_pp": st.column_config.NumberColumn(
                "Top opposition (pp)", format="%+.2f"
            ),
        },
    )
    st.caption(
        "Primary pick/probability/rank columns are V2.3.3 production. Columns prefixed "
        "`shadow_` are the exact V2.4 candidate. Downloadable files store decimals. "
        "Feature-group values are non-additive sensitivities, not causal contributions."
    )

    sensitivity_columns = [
        column
        for column in result.evaluation.columns
        if column.startswith("shadow_ensemble_pick_sensitivity_")
    ]
    if sensitivity_columns:
        with st.expander("Feature-group sensitivity details"):
            game_labels = {
                f"{row.away_team} at {row.home_team} — pick {row.pick}": index
                for index, row in result.evaluation.iterrows()
            }
            selected_label = st.selectbox("Game", list(game_labels))
            selected = result.evaluation.loc[game_labels[selected_label]]
            sensitivity = pd.DataFrame({
                "feature_group": [
                    column.removeprefix("shadow_ensemble_pick_sensitivity_")
                    for column in sensitivity_columns
                ],
                "effect_on_pick_probability_pp": [
                    100.0 * float(selected[column]) for column in sensitivity_columns
                ],
            }).sort_values(
                "effect_on_pick_probability_pp", key=lambda values: values.abs(), ascending=False
            )
            st.dataframe(
                sensitivity,
                use_container_width=True,
                hide_index=True,
                column_config={
                    "effect_on_pick_probability_pp": st.column_config.NumberColumn(
                        "Effect on pick probability (pp)", format="%+.2f"
                    ),
                },
            )
            st.caption(
                "Each row compares the normal seven-model ensemble probability with the "
                "probability after replacing that group by training medians. Effects can "
                "interact and therefore do not sum to the final probability."
            )

    col1, col2 = st.columns(2)
    with col1:
        st.download_button(
            "Download results CSV",
            data=result.evaluation.to_csv(index=False).encode("utf-8"),
            file_name=result.csv_path.name,
            mime="text/csv",
        )
    with col2:
        st.download_button(
            "Download results JSON",
            data=json.dumps(result.evaluation.to_dict("records"), indent=2, default=str),
            file_name=result.json_path.name,
            mime="application/json",
        )

    if result.parlays is not None and not result.parlays.empty:
        st.subheader("Optional two-leg comparison")
        st.dataframe(result.parlays, use_container_width=True, hide_index=True)

    with st.expander("Saved reproducibility artifacts"):
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


def launch() -> None:
    """Launch the local Streamlit interface from the installed console script."""

    try:
        from streamlit.web import cli as stcli
    except ImportError as exc:  # pragma: no cover
        raise SystemExit(
            "The web interface requires Streamlit. Install it with: "
            "python -m pip install -e \".[ui]\""
        ) from exc
    sys.argv = ["streamlit", "run", str(Path(__file__).resolve())]
    raise SystemExit(stcli.main())


if __name__ == "__main__":
    render_app()
