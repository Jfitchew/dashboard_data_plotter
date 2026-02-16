from __future__ import annotations

import base64
import json
import math
import os
import sys
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


def _assets_dir() -> str:
    if getattr(sys, "_MEIPASS", None):
        return os.path.join(sys._MEIPASS, "dashboard_data_plotter", "assets")
    return os.path.normpath(
        os.path.join(
            os.path.dirname(__file__),
            "..",
            "assets",
        )
    )


def _radar_background_image_path() -> str:
    base_dir = _assets_dir()
    candidates = (
        os.path.join(base_dir, "radar_background.png"),
        os.path.join(base_dir, "radar_background.jpg"),
        os.path.join(base_dir, "radar_background.jpeg"),
    )
    for path in candidates:
        if os.path.isfile(path):
            return path
    return candidates[0]


def _cartesian_background_image_path() -> str:
    base_dir = _assets_dir()
    return os.path.join(base_dir, "leg_muscles.jpeg")


def _encode_image_base64(path: str) -> tuple[str, str] | None:
    if not os.path.isfile(path):
        return None
    try:
        with open(path, "rb") as handle:
            encoded = base64.b64encode(handle.read()).decode("ascii")
    except OSError:
        return None
    ext = os.path.splitext(path)[1].lower()
    if ext == ".png":
        mime = "image/png"
    elif ext in (".jpg", ".jpeg"):
        mime = "image/jpeg"
    else:
        mime = "application/octet-stream"
    return encoded, mime


def _apply_radar_background_plotly(fig: go.Figure) -> bool:
    result = _encode_image_base64(_radar_background_image_path())
    if not result:
        return False
    encoded, mime = result
    fig.add_layout_image(
        dict(
            source=f"data:{mime};base64,{encoded}",
            xref="paper",
            yref="paper",
            x=0.5,
            y=0.5,
            sizex=0.9,
            sizey=0.9,
            sizing="contain",
            xanchor="center",
            yanchor="middle",
            layer="below",
            opacity=0.6,
        )
    )
    fig.update_layout(paper_bgcolor="rgba(0,0,0,0)")
    return True


def _cartesian_background_bands() -> list[tuple[float, float, str]]:
    return [
        (355.0, 95.0, "#E43C2F"),
        (80.0, 170.0, "#F48117"),
        (150.0, 185.0, "#F9DB2B"),
        (175.0, 235.0, "#3A9256"),
        (210.0, 275.0, "#2F8ADB"),
        (265.0, 5.0, "#8C58BD"),
    ]


def _apply_cartesian_background_plotly(fig: go.Figure) -> bool:
    result = _encode_image_base64(_cartesian_background_image_path())
    if result:
        encoded, mime = result
        fig.add_layout_image(
            dict(
                source=f"data:{mime};base64,{encoded}",
                xref="paper",
                yref="paper",
                x=0.5,
                y=0.5,
                sizex=1.0,
                sizey=1.0,
                sizing="contain",
                xanchor="center",
                yanchor="middle",
                layer="below",
                opacity=0.18,
            )
        )
    shapes = []
    for idx, (start, end, color) in enumerate(_cartesian_background_bands()):
        if idx % 2 == 0:
            y0, y1 = 0.6, 0.8
        else:
            y0, y1 = 0.7, 0.9
        if start <= end:
            shapes.append(dict(
                type="rect",
                xref="x",
                yref="paper",
                x0=start,
                x1=end,
                y0=y0,
                y1=y1,
                fillcolor=color,
                opacity=0.18,
                line=dict(width=0),
                layer="below",
            ))
        else:
            shapes.append(dict(
                type="rect",
                xref="x",
                yref="paper",
                x0=start,
                x1=360.0,
                y0=y0,
                y1=y1,
                fillcolor=color,
                opacity=0.18,
                line=dict(width=0),
                layer="below",
            ))
            shapes.append(dict(
                type="rect",
                xref="x",
                yref="paper",
                x0=0.0,
                x1=end,
                y0=y0,
                y1=y1,
                fillcolor=color,
                opacity=0.18,
                line=dict(width=0),
                layer="below",
            ))
    if shapes:
        fig.update_layout(shapes=shapes)
    return bool(encoded or shapes)


def _ensure_session_state() -> None:
    if "project_state" not in st.session_state:
        st.session_state.project_state = ProjectState()
    if "dataset_counter" not in st.session_state:
        st.session_state.dataset_counter = 0
    if "plot_history" not in st.session_state:
        st.session_state.plot_history = []
    if "plot_history_index" not in st.session_state:
        st.session_state.plot_history_index = -1
    if "auto_plot" not in st.session_state:
        st.session_state.auto_plot = False
    if "pending_plot_snapshot" not in st.session_state:
        st.session_state.pending_plot_snapshot = None


def _setdefault_state(key: str, value) -> None:
    if key not in st.session_state:
        st.session_state[key] = value


def _snapshot_plot_settings(
    *,
    plot_type: str,
    angle_col: str,
    close_loop: bool,
    metric_col: str,
    agg_label: str,
    sentinels_str: str,
    value_mode: str,
    range_low: str,
    range_high: str,
    range_fixed: bool,
    remove_outliers: bool,
    outlier_method: str,
    outlier_threshold: str,
    radar_background: bool,
    compare: bool,
    baseline_display: str,
    baseline_displays: list[str],
) -> dict:
    return {
        "plot_type": plot_type,
        "angle_col": angle_col,
        "close_loop": close_loop,
        "metric_col": metric_col,
        "agg_label": agg_label,
        "sentinels_str": sentinels_str,
        "value_mode": value_mode,
        "range_low": range_low,
        "range_high": range_high,
        "range_fixed": range_fixed,
        "remove_outliers": remove_outliers,
        "outlier_method": outlier_method,
        "outlier_threshold": outlier_threshold,
        "radar_background": radar_background,
        "compare": compare,
        "baseline_display": baseline_display,
        "baseline_displays": baseline_displays,
    }


def _apply_plot_snapshot(snapshot: dict) -> None:
    for key, value in snapshot.items():
        st.session_state[key] = value


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

    if st.session_state.pending_plot_snapshot:
        _apply_plot_snapshot(st.session_state.pending_plot_snapshot)
        st.session_state.pending_plot_snapshot = None

    _setdefault_state("plot_type", "Radar")
    _setdefault_state("angle_col", cols[0])
    _setdefault_state("close_loop", True)
    _setdefault_state("metric_col", cols[0])
    _setdefault_state("agg_label", "mean")
    _setdefault_state("sentinels_str", DEFAULT_SENTINELS)
    _setdefault_state("value_mode", "absolute")
    _setdefault_state("range_low", "")
    _setdefault_state("range_high", "")
    _setdefault_state("range_fixed", False)
    _setdefault_state("remove_outliers", False)
    _setdefault_state("outlier_method", "Impulse")
    _setdefault_state("outlier_threshold", "4.0")
    _setdefault_state("radar_background", True)
    _setdefault_state("compare", False)
    _setdefault_state("baseline_display", "")
    _setdefault_state("baseline_displays", [])

    st.subheader("Plot")
    plot_type_options = ["Radar", "Cartesian", "Bar", "Time series"]
    if st.session_state.plot_type not in plot_type_options:
        st.session_state.plot_type = plot_type_options[0]
    plot_type_index = plot_type_options.index(st.session_state.plot_type)
    plot_type = st.selectbox("Plot type", plot_type_options, index=plot_type_index, key="plot_type")
    show_angle = plot_type in ("Radar", "Cartesian")
    allow_close_loop = plot_type in ("Radar", "Cartesian")
    allow_value_mode = plot_type in ("Radar", "Cartesian", "Time series")

    angle_col = st.session_state.angle_col
    if show_angle:
        if st.session_state.angle_col not in cols:
            st.session_state.angle_col = cols[0]
        angle_index = cols.index(st.session_state.angle_col)
        angle_col = st.selectbox("Angle column", cols, index=angle_index, key="angle_col")
    close_loop = False
    if allow_close_loop:
        close_loop = st.checkbox("Close loop", key="close_loop")
    else:
        st.caption("Close loop applies to Radar/Cartesian only.")
    if st.session_state.metric_col not in cols:
        st.session_state.metric_col = cols[0]
    metric_index = cols.index(st.session_state.metric_col)
    metric_col = st.selectbox("Metric column", cols, index=metric_index, key="metric_col")

    agg_label_options = ["mean", "median", "10% trimmed mean", "pedal_stroke", "roll_360deg"]
    if st.session_state.agg_label not in agg_label_options:
        st.session_state.agg_label = agg_label_options[0]
    agg_index = agg_label_options.index(st.session_state.agg_label)
    agg_label = st.selectbox("Aggregation", agg_label_options, index=agg_index, key="agg_label")
    agg_map = {
        "mean": "mean",
        "median": "median",
        "10% trimmed mean": "trimmed_mean_10",
        "pedal_stroke": "pedal_stroke",
        "roll_360deg": "roll_360deg",
    }
    agg_key = agg_map[agg_label]
    sentinels_str = st.text_input("Sentinel values (comma separated)", key="sentinels_str")
    sentinels = parse_sentinels(sentinels_str)

    value_mode = "absolute"
    if allow_value_mode:
        if st.session_state.value_mode not in ("absolute", "percent_mean"):
            st.session_state.value_mode = "absolute"
        value_mode = st.radio(
            "Value mode",
            ["absolute", "percent_mean"],
            format_func=lambda v: "Absolute" if v == "absolute" else "% of dataset mean",
            horizontal=True,
            key="value_mode",
        )
    else:
        st.caption("Bar plot uses absolute values only (percent of mean is disabled).")

    st.markdown("**Plot range**")
    range_cols = st.columns([3, 3, 2])
    with range_cols[0]:
        range_low = st.text_input("Range min", key="range_low")
    with range_cols[1]:
        range_high = st.text_input("Range max", key="range_high")
    with range_cols[2]:
        range_fixed = st.checkbox("Fixed", key="range_fixed")

    st.markdown("**Outlier removal**")
    outlier_cols = st.columns([2, 3, 3])
    with outlier_cols[0]:
        remove_outliers = st.checkbox("Active", key="remove_outliers")
    with outlier_cols[1]:
        outlier_method = st.selectbox(
            "Method",
            ["MAD", "Phase-MAD", "Hampel", "Impulse"],
            key="outlier_method",
        )
    with outlier_cols[2]:
        outlier_threshold = st.text_input("Threshold", key="outlier_threshold")

    radar_background = st.checkbox("Background image", key="radar_background")

    compare = st.checkbox("Compare vs baseline", key="compare")
    baseline_id = None
    baseline_ids: list[str] = []
    baseline_display = st.session_state.baseline_display
    baseline_displays = list(st.session_state.baseline_displays)
    if compare:
        baseline_options = [state.id_to_display.get(sid, sid) for sid in ordered_source_ids(state)]
        baseline_displays = [name for name in baseline_displays if name in baseline_options]
        if not baseline_displays and baseline_options:
            baseline_displays = [baseline_options[0]]
        baseline_displays = st.multiselect(
            "Baseline dataset(s)",
            baseline_options,
            default=baseline_displays,
            key="baseline_displays",
        )
        if baseline_displays:
            baseline_display = baseline_displays[0]
            st.session_state.baseline_display = baseline_display
            baseline_id = state.display_to_id.get(baseline_display)
            baseline_ids = [state.display_to_id.get(name) for name in baseline_displays]
            baseline_ids = [sid for sid in baseline_ids if sid]

    history = st.session_state.plot_history
    history_index = st.session_state.plot_history_index
    nav_cols = st.columns([3, 1, 1, 1, 2])
    with nav_cols[0]:
        plot_pressed = st.button("Plot")
    with nav_cols[1]:
        prev_pressed = st.button("Prev", disabled=history_index <= 0)
    with nav_cols[2]:
        delete_pressed = st.button("Delete", disabled=history_index < 0)
    with nav_cols[3]:
        next_pressed = st.button("Next", disabled=history_index >= len(history) - 1)
    with nav_cols[4]:
        if history:
            st.caption(f"History {history_index + 1}/{len(history)}")
        else:
            st.caption("History 0/0")

    if prev_pressed and history_index > 0:
        st.session_state.plot_history_index = history_index - 1
        st.session_state.pending_plot_snapshot = history[st.session_state.plot_history_index]
        st.session_state.auto_plot = True
        st.rerun()
    if next_pressed and history_index < len(history) - 1:
        st.session_state.plot_history_index = history_index + 1
        st.session_state.pending_plot_snapshot = history[st.session_state.plot_history_index]
        st.session_state.auto_plot = True
        st.rerun()
    if delete_pressed and history_index >= 0:
        history.pop(history_index)
        if history:
            st.session_state.plot_history_index = min(history_index, len(history) - 1)
            st.session_state.pending_plot_snapshot = history[st.session_state.plot_history_index]
            st.session_state.auto_plot = True
        else:
            st.session_state.plot_history_index = -1
            st.session_state.auto_plot = False
            st.session_state.pending_plot_snapshot = None
        st.rerun()

    do_plot = plot_pressed or st.session_state.auto_plot
    if do_plot:
        st.session_state.auto_plot = False
        fixed_range = None
        if range_fixed:
            low_s = range_low.strip()
            high_s = range_high.strip()
            if not low_s or not high_s:
                st.error("Enter both Range min and Range max, or untick Fixed.")
                return
            try:
                low_v = float(low_s)
                high_v = float(high_s)
            except ValueError:
                st.error("Range values must be valid numbers.")
                return
            if not (math.isfinite(low_v) and math.isfinite(high_v)):
                st.error("Range values must be finite numbers.")
                return
            if low_v > high_v:
                st.error("Range min must be less than or equal to Range max.")
                return
            fixed_range = (low_v, high_v)

        resolved_outlier_threshold = None
        if remove_outliers:
            try:
                resolved_outlier_threshold = float(outlier_threshold)
            except ValueError:
                st.error("Outlier threshold must be a valid number.")
                return

        if compare and not baseline_ids:
            st.warning("Select at least one baseline dataset for comparison.")
            return

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
                    baseline_ids=baseline_ids,
                    sentinels=sentinels,
                    outlier_threshold=resolved_outlier_threshold,
                    outlier_method=outlier_method,
                    close_loop=close_loop,
                )
                fig = go.Figure()
                for trace in data.traces:
                    fig.add_trace(go.Scatterpolar(
                        r=trace.y,
                        theta=trace.x,
                        mode="lines+markers",
                        name=trace.label,
                    ))
                if radar_background:
                    _apply_radar_background_plotly(fig)
                if fixed_range:
                    if compare:
                        low, high = fixed_range
                        fixed_range = (low + data.offset, high + data.offset)
                polar_kwargs = dict(angularaxis=dict(direction="clockwise", rotation=90))
                if fixed_range:
                    polar_kwargs["radialaxis"] = dict(range=list(fixed_range))
                fig.update_layout(
                    title=f"{metric_col} ({data.mode_label})",
                    polar=polar_kwargs,
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
                    baseline_ids=baseline_ids,
                    sentinels=sentinels,
                    outlier_threshold=resolved_outlier_threshold,
                    outlier_method=outlier_method,
                    close_loop=close_loop,
                )
                fig = go.Figure()
                for trace in data.traces:
                    fig.add_scatter(x=trace.x, y=trace.y, mode="lines+markers", name=trace.label)
                if radar_background:
                    _apply_cartesian_background_plotly(fig)
                layout_kwargs = dict(title=f"{metric_col} ({data.mode_label})", xaxis_title="Crank angle (deg)")
                if fixed_range:
                    layout_kwargs["yaxis"] = dict(range=list(fixed_range))
                fig.update_layout(**layout_kwargs)
                if compare:
                    fig.add_hline(y=0, line_width=2, line_dash="solid", line_color="black")
                st.plotly_chart(fig, use_container_width=True)
            elif plot_type == "Bar":
                data = prepare_bar_plot(
                    state,
                    metric_col=metric_col,
                    agg_mode=agg_key,
                    value_mode="absolute",
                    compare=compare,
                    baseline_id=baseline_id,
                    baseline_ids=baseline_ids,
                    sentinels=sentinels,
                    outlier_threshold=resolved_outlier_threshold,
                    outlier_method=outlier_method,
                )
                fig = go.Figure(data=[go.Bar(x=data.labels, y=data.values)])
                layout_kwargs = dict(title=f"{metric_col}", xaxis_title="Dataset")
                if fixed_range:
                    layout_kwargs["yaxis"] = dict(range=list(fixed_range))
                fig.update_layout(**layout_kwargs)
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
                    baseline_ids=baseline_ids,
                    sentinels=sentinels,
                    outlier_threshold=resolved_outlier_threshold,
                    outlier_method=outlier_method,
                )
                fig = go.Figure()
                for trace in data.traces:
                    fig.add_scatter(x=trace.x, y=trace.y, mode="lines+markers", name=trace.label)
                layout_kwargs = dict(
                    title=f"{metric_col} ({data.mode_label})",
                    xaxis_title=data.x_label,
                    yaxis_title=metric_col,
                )
                if fixed_range:
                    layout_kwargs["yaxis"] = dict(range=list(fixed_range))
                fig.update_layout(**layout_kwargs)
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
            if plot_pressed:
                snapshot = _snapshot_plot_settings(
                    plot_type=plot_type,
                    angle_col=angle_col,
                    close_loop=close_loop,
                    metric_col=metric_col,
                    agg_label=agg_label,
                    sentinels_str=sentinels_str,
                    value_mode=value_mode,
                    range_low=range_low,
                    range_high=range_high,
                    range_fixed=range_fixed,
                    remove_outliers=remove_outliers,
                    outlier_method=outlier_method,
                    outlier_threshold=outlier_threshold,
                    radar_background=radar_background,
                    compare=compare,
                    baseline_display=baseline_display,
                    baseline_displays=baseline_displays,
                )
                if st.session_state.plot_history_index < len(history) - 1:
                    del history[st.session_state.plot_history_index + 1:]
                history.append(snapshot)
                st.session_state.plot_history_index = len(history) - 1
                st.session_state.auto_plot = True
                st.rerun()
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
            st.checkbox("Remove outliers", key="clean_outliers")
            st.selectbox("Method", ["MAD", "Phase-MAD", "Hampel", "Impulse"], key="clean_outlier_method")
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
