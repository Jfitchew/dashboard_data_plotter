from __future__ import annotations

import json
from typing import List, Tuple

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from dashboard_data_plotter.core.state import ProjectState
from dashboard_data_plotter.core.datasets import (
    add_dataset,
    ordered_source_ids,
    reorder_datasets,
    set_show_flag,
)
from dashboard_data_plotter.core.io import (
    apply_project_settings,
    build_project_payload,
    extract_project_settings,
)
from dashboard_data_plotter.core.plotting import (
    prepare_radar_plot,
    prepare_cartesian_plot,
    prepare_bar_plot,
    prepare_timeseries_plot,
)
from dashboard_data_plotter.data.loaders import (
    DEFAULT_SENTINELS,
    extract_named_datasets,
    make_unique_name,
    parse_sentinels,
)


def _ensure_session_state() -> None:
    if "project_state" not in st.session_state:
        st.session_state.project_state = ProjectState()
    if "dataset_counter" not in st.session_state:
        st.session_state.dataset_counter = 0


def _next_source_id(prefix: str) -> str:
    st.session_state.dataset_counter += 1
    return f"{prefix}::{st.session_state.dataset_counter}"


def _datasets_from_json_obj(obj: object) -> List[Tuple[str, pd.DataFrame]]:
    datasets = extract_named_datasets(obj)
    out: List[Tuple[str, pd.DataFrame]] = []
    for name, records in datasets:
        if not isinstance(records, list) or (records and not isinstance(records[0], dict)):
            continue
        df = pd.DataFrame(records)
        for c in df.columns:
            df[c] = pd.to_numeric(df[c], errors="coerce")
        out.append((str(name), df))
    return out


def _add_datasets(datasets: List[Tuple[str, pd.DataFrame]], source_prefix: str) -> None:
    state: ProjectState = st.session_state.project_state
    existing = set(state.display_to_id.keys())
    for name, df in datasets:
        display = make_unique_name(name, existing)
        existing.add(display)
        source_id = _next_source_id(source_prefix)
        add_dataset(state, source_id, display, df)


def _apply_settings_from_obj(obj: object) -> None:
    settings = extract_project_settings(obj)
    if settings:
        apply_project_settings(st.session_state.project_state, settings)


def _render_dataset_controls() -> None:
    state: ProjectState = st.session_state.project_state
    st.subheader("Datasets (order defines plot order)")
    if not ordered_source_ids(state):
        st.info("No datasets loaded.")
        return

    for idx, sid in enumerate(ordered_source_ids(state), start=1):
        cols = st.columns([6, 2, 2, 2])
        label = state.id_to_display.get(sid, sid)
        with cols[0]:
            st.write(f"{idx}. {label}")
        with cols[1]:
            show = st.checkbox("Show", value=state.show_flag.get(sid, True), key=f"show_{sid}")
            set_show_flag(state, sid, show)
        with cols[2]:
            if st.button("Up", key=f"up_{sid}") and idx > 1:
                order = ordered_source_ids(state)
                order[idx - 2], order[idx - 1] = order[idx - 1], order[idx - 2]
                reorder_datasets(state, order)
        with cols[3]:
            if st.button("Down", key=f"down_{sid}") and idx < len(ordered_source_ids(state)):
                order = ordered_source_ids(state)
                order[idx - 1], order[idx] = order[idx], order[idx - 1]
                reorder_datasets(state, order)


def _render_plot_controls() -> None:
    state: ProjectState = st.session_state.project_state
    cols = _collect_columns()
    if not cols:
        st.warning("No columns found in datasets.")
        return

    st.subheader("Plot")
    plot_type = st.selectbox("Plot type", ["Radar", "Cartesian", "Bar", "Time series"])
    angle_col = ""
    if plot_type in ("Radar", "Cartesian"):
        angle_col = st.selectbox("Angle column", cols, index=0)
    metric_col = st.selectbox("Metric column", cols, index=0)

    agg_label = st.selectbox("Aggregation", ["mean", "median", "10% trimmed mean", "pedal_stroke", "roll_360deg"])
    agg_map = {
        "mean": "mean",
        "median": "median",
        "10% trimmed mean": "trimmed_mean_10",
        "pedal_stroke": "pedal_stroke",
        "roll_360deg": "roll_360deg",
    }
    agg_key = agg_map[agg_label]
    sentinels_str = st.text_input("Sentinel values (comma separated)", value=DEFAULT_SENTINELS)
    sentinels = parse_sentinels(sentinels_str)

    value_mode = "absolute"
    if plot_type in ("Radar", "Cartesian", "Time series"):
        value_mode = st.radio(
            "Value mode",
            ["absolute", "percent_mean"],
            format_func=lambda v: "Absolute" if v == "absolute" else "% of dataset mean",
            horizontal=True,
        )
    else:
        st.caption("Bar plot uses absolute values only (percent of mean is disabled).")

    compare = st.checkbox("Compare vs baseline")
    baseline_id = None
    if compare:
        baseline_display = st.selectbox(
            "Baseline dataset",
            [state.id_to_display.get(sid, sid) for sid in ordered_source_ids(state)],
        )
        baseline_id = state.display_to_id.get(baseline_display)

    if st.button("Plot"):
        try:
            if plot_type == "Radar":
                data = prepare_radar_plot(
                    state,
                    angle_col=angle_col,
                    metric_col=metric_col,
                    agg_mode=agg_key,
                    value_mode=value_mode,
                    compare=compare,
                    baseline_id=baseline_id,
                    sentinels=sentinels,
                )
                fig = go.Figure()
                for trace in data.traces:
                    fig.add_trace(go.Scatterpolar(
                        r=trace.y,
                        theta=trace.x,
                        mode="lines+markers",
                        name=trace.label,
                    ))
                fig.update_layout(
                    title=f"{metric_col} ({data.mode_label})",
                    polar=dict(angularaxis=dict(direction="clockwise", rotation=90)),
                )
                st.plotly_chart(fig, use_container_width=True)
            elif plot_type == "Cartesian":
                data = prepare_cartesian_plot(
                    state,
                    angle_col=angle_col,
                    metric_col=metric_col,
                    agg_mode=agg_key,
                    value_mode=value_mode,
                    compare=compare,
                    baseline_id=baseline_id,
                    sentinels=sentinels,
                )
                fig = go.Figure()
                for trace in data.traces:
                    fig.add_scatter(x=trace.x, y=trace.y, mode="lines+markers", name=trace.label)
                fig.update_layout(title=f"{metric_col} ({data.mode_label})", xaxis_title="Crank angle (deg)")
                st.plotly_chart(fig, use_container_width=True)
            elif plot_type == "Bar":
                data = prepare_bar_plot(
                    state,
                    metric_col=metric_col,
                    agg_mode=agg_key,
                    value_mode="absolute",
                    compare=compare,
                    baseline_id=baseline_id,
                    sentinels=sentinels,
                )
                fig = go.Figure(data=[go.Bar(x=data.labels, y=data.values)])
                fig.update_layout(title=f"{metric_col}", xaxis_title="Dataset")
                if compare:
                    fig.add_hline(y=0, line_width=2, line_dash="solid", line_color="black")
                st.plotly_chart(fig, use_container_width=True)
            else:
                data = prepare_timeseries_plot(
                    state,
                    metric_col=metric_col,
                    agg_mode=agg_key,
                    value_mode=value_mode,
                    compare=compare,
                    baseline_id=baseline_id,
                    sentinels=sentinels,
                )
                fig = go.Figure()
                for trace in data.traces:
                    fig.add_scatter(x=trace.x, y=trace.y, mode="lines+markers", name=trace.label)
                fig.update_layout(
                    title=f"{metric_col} ({data.mode_label})",
                    xaxis_title=data.x_label,
                    yaxis_title=metric_col,
                )
                if compare and data.baseline_label:
                    fig.add_scatter(
                        x=[0, data.max_x], y=[0, 0], mode="lines",
                        name=data.baseline_label, line=dict(width=1.6),
                    )
                st.plotly_chart(fig, use_container_width=True)

            if plot_type != "Bar" and value_mode == "percent_mean":
                st.caption("% of mean uses dataset-specific normalization.")

            if data.errors:
                st.warning("Some datasets failed to plot:")
                for err in data.errors:
                    st.write(f"- {err}")
        except Exception as exc:
            st.error(str(exc))


def _collect_columns() -> List[str]:
    state: ProjectState = st.session_state.project_state
    seen = set()
    cols: List[str] = []
    for sid in ordered_source_ids(state):
        df = state.loaded.get(sid)
        if df is None:
            continue
        for col in df.columns:
            if col not in seen:
                seen.add(col)
                cols.append(col)
    return cols


def main() -> None:
    st.set_page_config(page_title="Dashboard Data Plotter (Streamlit)", layout="wide")
    _ensure_session_state()

    st.title("Dashboard Data Plotter")
    st.caption("Streamlit UI using shared core state and plotting.")

    with st.sidebar:
        step = st.selectbox(
            "Workflow",
            ["Load", "Clean", "Align", "Plot", "Analysis", "Report"],
        )

        if step == "Load":
            st.subheader("Load")
            uploaded = st.file_uploader(
                "Upload JSON file(s)",
                type=["json"],
                accept_multiple_files=True,
            )
            if st.button("Load uploaded files"):
                if not uploaded:
                    st.warning("No files selected.")
                else:
                    for f in uploaded:
                        try:
                            obj = json.loads(f.getvalue().decode("utf-8"))
                            datasets = _datasets_from_json_obj(obj)
                            _add_datasets(datasets, f"FILE::{f.name}")
                            _apply_settings_from_obj(obj)
                        except Exception as exc:
                            st.error(f"{f.name}: {exc}")

            pasted = st.text_area("Paste JSON", height=160)
            if st.button("Load pasted JSON"):
                if not pasted.strip():
                    st.warning("Paste JSON content before loading.")
                else:
                    try:
                        obj = json.loads(pasted)
                        datasets = _datasets_from_json_obj(obj)
                        _add_datasets(datasets, "PASTE")
                        _apply_settings_from_obj(obj)
                    except Exception as exc:
                        st.error(f"Paste error: {exc}")

            if st.button("Clear datasets"):
                st.session_state.project_state.clear()

            payload = build_project_payload(st.session_state.project_state)
            st.download_button(
                label="Save project JSON",
                data=json.dumps(payload, indent=2),
                file_name="dashboard_project.json",
                mime="application/json",
            )

        elif step == "Clean":
            st.subheader("Clean")
            st.info("Cleaning config is stored in project settings.")
            st.caption("TODO: Wire these controls to core/cleaning.py (CleaningSettings).")
            st.text_input("Sentinel values", value=DEFAULT_SENTINELS, key="clean_sentinels")
            st.checkbox("Remove outliers (MAD)", key="clean_outliers")
            st.text_input("Outlier threshold", value="4.0", key="clean_outlier_threshold")

        elif step == "Align":
            st.subheader("Align")
            st.info("Alignment step placeholder (future work).")

        elif step == "Plot":
            st.subheader("Plot")
        elif step == "Analysis":
            st.subheader("Analysis")
            st.info("Analysis step placeholder (future work).")
            st.caption("TODO: Implement analysis workflows in core/analysis.py and bind UI controls here.")
        elif step == "Report":
            st.subheader("Report")
            st.info("Report step placeholder (future work).")

    if step in ("Load", "Clean"):
        _render_dataset_controls()

    if step == "Plot":
        _render_plot_controls()


if __name__ == "__main__":
    main()
