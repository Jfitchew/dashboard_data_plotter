from __future__ import annotations

import base64
import json
import math
import os
import sys
from pathlib import Path
from typing import List, Tuple

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from dashboard_data_plotter.core.state import ProjectState
from dashboard_data_plotter.core.datasets import (
    add_dataset,
    remove_dataset,
    rename_dataset,
    ordered_source_ids,
    reorder_datasets,
    set_all_show_flags,
    set_show_flag,
)
from dashboard_data_plotter.core.io import (
    apply_project_settings,
    build_dataset_data_payload,
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


WEB_THEMES: dict[str, dict[str, object]] = {
    "Slate": {
        "page_bg": "#f5f7fb",
        "surface": "#ffffff",
        "surface_alt": "#eef2fb",
        "text": "#1e2430",
        "muted": "#5a6478",
        "border": "#d8deea",
        "accent": "#1f6feb",
        "accent_soft": "#dce9ff",
        "shadow": "0 10px 28px rgba(14, 27, 48, 0.08)",
        "plot_bg": "#ffffff",
        "paper_bg": "#ffffff",
    },
    "Sand": {
        "page_bg": "#fbf7f0",
        "surface": "#fffdf8",
        "surface_alt": "#f3ead8",
        "text": "#2a251d",
        "muted": "#6d6253",
        "border": "#e2d3ba",
        "accent": "#b85c1e",
        "accent_soft": "#ffe6d5",
        "shadow": "0 10px 24px rgba(62, 36, 14, 0.08)",
        "plot_bg": "#fffdf8",
        "paper_bg": "#fffdf8",
    },
    "Forest": {
        "page_bg": "#f2f7f4",
        "surface": "#fbfffd",
        "surface_alt": "#deeee4",
        "text": "#173326",
        "muted": "#4f6c5f",
        "border": "#c7ddcf",
        "accent": "#1f8f5f",
        "accent_soft": "#d5f5e6",
        "shadow": "0 10px 24px rgba(16, 59, 39, 0.08)",
        "plot_bg": "#fbfffd",
        "paper_bg": "#fbfffd",
    },
}


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
    if "web_theme" not in st.session_state:
        st.session_state.web_theme = "Slate"
    if "web_left_tab" not in st.session_state:
        st.session_state.web_left_tab = "Project / Data"
    if "project_upload_token" not in st.session_state:
        st.session_state.project_upload_token = 0
    if "data_upload_token" not in st.session_state:
        st.session_state.data_upload_token = 0


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[3]


def _safe_read_text(path: Path, limit: int = 12000) -> str:
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return ""
    if len(text) > limit:
        return text[:limit].rstrip() + "\n\n... (truncated)"
    return text


def _active_web_theme() -> dict[str, object]:
    name = st.session_state.get("web_theme", "Slate")
    return WEB_THEMES.get(name, WEB_THEMES["Slate"])


def _inject_web_theme_css() -> None:
    theme = _active_web_theme()
    st.markdown(
        f"""
<style>
:root {{
  --ddp-page-bg: {theme["page_bg"]};
  --ddp-surface: {theme["surface"]};
  --ddp-surface-alt: {theme["surface_alt"]};
  --ddp-text: {theme["text"]};
  --ddp-muted: {theme["muted"]};
  --ddp-border: {theme["border"]};
  --ddp-accent: {theme["accent"]};
  --ddp-accent-soft: {theme["accent_soft"]};
  --ddp-shadow: {theme["shadow"]};
}}
[data-testid="stAppViewContainer"] {{
  background: linear-gradient(180deg, var(--ddp-page-bg) 0%, var(--ddp-page-bg) 100%);
}}
[data-testid="stAppViewContainer"] .main .block-container {{
  max-width: 1180px;
  padding-top: 0.8rem;
  padding-bottom: 1.25rem;
}}
[data-testid="stSidebar"] {{
  background: linear-gradient(180deg, var(--ddp-surface) 0%, var(--ddp-surface-alt) 100%);
  border-right: 1px solid var(--ddp-border);
}}
[data-testid="stSidebar"] [data-testid="stVerticalBlock"] > div {{
  color: var(--ddp-text);
}}
[data-testid="stSidebar"] .stButton > button {{
  min-height: 3.0rem;
  border-radius: 12px;
  border: 1px solid var(--ddp-border);
  font-weight: 700;
  justify-content: flex-start;
  padding-left: 0.8rem;
}}
[data-testid="stSidebar"] .stButton > button:hover {{
  border-color: var(--ddp-accent);
}}
.ddp-panel-card {{
  background: var(--ddp-surface);
  border: 1px solid var(--ddp-border);
  border-radius: 14px;
  padding: 0.55rem 0.7rem;
  box-shadow: var(--ddp-shadow);
  margin-bottom: 0.55rem;
}}
.ddp-panel-title {{
  font-weight: 700;
  color: var(--ddp-text);
  margin: 0 0 0.15rem 0;
}}
.ddp-panel-subtitle {{
  color: var(--ddp-muted);
  font-size: 0.9rem;
  margin: 0 0 0.6rem 0;
}}
.ddp-main-card {{
  background: var(--ddp-surface);
  border: 1px solid var(--ddp-border);
  border-radius: 16px;
  padding: 0.65rem 0.8rem;
  box-shadow: var(--ddp-shadow);
  margin-bottom: 0.55rem;
}}
@media (max-width: 900px) {{
  [data-testid="stSidebar"] {{
    min-width: 270px;
  }}
  [data-testid="stAppViewContainer"] .main .block-container {{
    max-width: 100%;
    padding-top: 0.55rem;
    padding-left: 0.7rem;
    padding-right: 0.7rem;
  }}
  .ddp-main-card {{
    padding: 0.65rem;
  }}
}}
</style>
        """,
        unsafe_allow_html=True,
    )


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


def _render_project_dataset_controls() -> None:
    state: ProjectState = st.session_state.project_state
    st.markdown('<div class="ddp-panel-card">', unsafe_allow_html=True)
    st.markdown('<p class="ddp-panel-title">Data sources</p>', unsafe_allow_html=True)
    st.markdown(
        '<p class="ddp-panel-subtitle">Order here defines plot and save order. Visibility is controlled on the Plot tab.</p>',
        unsafe_allow_html=True,
    )
    if not ordered_source_ids(state):
        st.info("No datasets loaded.")
        st.markdown("</div>", unsafe_allow_html=True)
        return

    for idx, sid in enumerate(ordered_source_ids(state), start=1):
        label = state.id_to_display.get(sid, sid)
        edit_key = f"rename_{sid}"
        if edit_key not in st.session_state:
            st.session_state[edit_key] = label
        cols = st.columns([5, 2, 2, 2])
        with cols[0]:
            st.text_input(f"Dataset {idx}", key=edit_key, label_visibility="collapsed")
            new_label = st.session_state.get(edit_key, "").strip()
            if new_label and new_label != label:
                try:
                    rename_dataset(state, sid, new_label)
                except Exception as exc:
                    st.warning(f"Rename failed for {label}: {exc}")
                    st.session_state[edit_key] = label
                else:
                    st.session_state[edit_key] = state.id_to_display.get(sid, new_label)
        with cols[1]:
            if st.button("Up", key=f"proj_up_{sid}") and idx > 1:
                order = ordered_source_ids(state)
                order[idx - 2], order[idx - 1] = order[idx - 1], order[idx - 2]
                reorder_datasets(state, order)
                st.rerun()
        with cols[2]:
            if st.button("Dn", key=f"proj_dn_{sid}") and idx < len(ordered_source_ids(state)):
                order = ordered_source_ids(state)
                order[idx - 1], order[idx] = order[idx], order[idx - 1]
                reorder_datasets(state, order)
                st.rerun()
        with cols[3]:
            if st.button("Remove", key=f"rm_{sid}"):
                remove_dataset(state, sid)
                st.rerun()
    st.markdown("</div>", unsafe_allow_html=True)


def _render_plot_dataset_visibility_controls() -> None:
    state: ProjectState = st.session_state.project_state
    st.markdown('<div class="ddp-panel-card">', unsafe_allow_html=True)
    st.markdown('<p class="ddp-panel-title">Datasets to plot</p>', unsafe_allow_html=True)
    st.markdown(
        '<p class="ddp-panel-subtitle">Show/hide datasets in the current plot while preserving Project / Data ordering.</p>',
        unsafe_allow_html=True,
    )
    if not ordered_source_ids(state):
        st.info("No datasets loaded.")
        st.markdown("</div>", unsafe_allow_html=True)
        return

    ctl_cols = st.columns(2)
    with ctl_cols[0]:
        if st.button("Show all", use_container_width=True):
            set_all_show_flags(state, True)
    with ctl_cols[1]:
        if st.button("Hide all", use_container_width=True):
            set_all_show_flags(state, False)

    for idx, sid in enumerate(ordered_source_ids(state), start=1):
        cols = st.columns([6, 2, 2, 2])
        label = state.id_to_display.get(sid, sid)
        with cols[0]:
            st.write(f"{idx}. {label}")
        with cols[1]:
            show = st.checkbox("Show", value=state.show_flag.get(sid, True), key=f"show_{sid}")
            set_show_flag(state, sid, show)
        with cols[2]:
            st.caption(" ")
        with cols[3]:
            st.caption(" ")
    st.markdown("</div>", unsafe_allow_html=True)


def _style_plotly_figure(fig: go.Figure) -> None:
    theme = _active_web_theme()
    fig.update_layout(
        paper_bgcolor=theme["paper_bg"],
        plot_bgcolor=theme["plot_bg"],
        font=dict(color=theme["text"]),
        margin=dict(l=20, r=20, t=56, b=20),
    )


def _render_plot_controls(*, plot_output=None) -> None:
    state: ProjectState = st.session_state.project_state
    cols = _collect_columns()
    plot_host = plot_output or st
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

    st.markdown('<div class="ddp-panel-card">', unsafe_allow_html=True)
    st.markdown('<p class="ddp-panel-title">Plot</p>', unsafe_allow_html=True)
    st.markdown(
        '<p class="ddp-panel-subtitle">Configure plot type, metrics, cleaning, comparison, and history.</p>',
        unsafe_allow_html=True,
    )
    st.markdown("</div>", unsafe_allow_html=True)

    st.markdown('<div class="ddp-panel-card">', unsafe_allow_html=True)
    st.markdown('<p class="ddp-panel-title">Plot type</p>', unsafe_allow_html=True)
    plot_type_options = ["Radar", "Cartesian", "Bar", "Time series"]
    if st.session_state.plot_type not in plot_type_options:
        st.session_state.plot_type = plot_type_options[0]
    plot_type_index = plot_type_options.index(st.session_state.plot_type)
    plot_type = st.selectbox("Plot type", plot_type_options, index=plot_type_index, key="plot_type")
    show_angle = plot_type in ("Radar", "Cartesian")
    allow_close_loop = plot_type in ("Radar", "Cartesian")
    allow_value_mode = plot_type in ("Radar", "Cartesian", "Time series")
    type_cols = st.columns(2)
    with type_cols[0]:
        radar_background = st.checkbox("Background image", key="radar_background")
    with type_cols[1]:
        st.caption("Interactive Plotly rendering is used in the web UI.")
    st.markdown("</div>", unsafe_allow_html=True)

    st.markdown('<div class="ddp-panel-card">', unsafe_allow_html=True)
    st.markdown('<p class="ddp-panel-title">Metrics</p>', unsafe_allow_html=True)
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
    st.markdown("</div>", unsafe_allow_html=True)

    range_col, outlier_col = st.columns(2)
    with outlier_col:
        st.markdown('<div class="ddp-panel-card">', unsafe_allow_html=True)
        st.markdown('<p class="ddp-panel-title">Outliers</p>', unsafe_allow_html=True)
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
        st.markdown("</div>", unsafe_allow_html=True)
    with range_col:
        st.markdown('<div class="ddp-panel-card">', unsafe_allow_html=True)
        st.markdown('<p class="ddp-panel-title">Range</p>', unsafe_allow_html=True)
        range_cols = st.columns([3, 3, 2])
        with range_cols[0]:
            range_low = st.text_input("Range min", key="range_low")
        with range_cols[1]:
            range_high = st.text_input("Range max", key="range_high")
        with range_cols[2]:
            range_fixed = st.checkbox("Fixed", key="range_fixed")
        st.markdown("</div>", unsafe_allow_html=True)

    st.markdown('<div class="ddp-panel-card">', unsafe_allow_html=True)
    st.markdown('<p class="ddp-panel-title">Mode</p>', unsafe_allow_html=True)
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
    st.markdown("</div>", unsafe_allow_html=True)

    history = st.session_state.plot_history
    history_index = st.session_state.plot_history_index
    st.markdown('<div class="ddp-panel-card">', unsafe_allow_html=True)
    st.markdown('<p class="ddp-panel-title">Plot actions and history</p>', unsafe_allow_html=True)
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
    st.markdown("</div>", unsafe_allow_html=True)

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
                plot_host.error("Enter both Range min and Range max, or untick Fixed.")
                return
            try:
                low_v = float(low_s)
                high_v = float(high_s)
            except ValueError:
                plot_host.error("Range values must be valid numbers.")
                return
            if not (math.isfinite(low_v) and math.isfinite(high_v)):
                plot_host.error("Range values must be finite numbers.")
                return
            if low_v > high_v:
                plot_host.error("Range min must be less than or equal to Range max.")
                return
            fixed_range = (low_v, high_v)

        resolved_outlier_threshold = None
        if remove_outliers:
            try:
                resolved_outlier_threshold = float(outlier_threshold)
            except ValueError:
                plot_host.error("Outlier threshold must be a valid number.")
                return

        if compare and not baseline_ids:
            plot_host.warning("Select at least one baseline dataset for comparison.")
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
                _style_plotly_figure(fig)
                plot_host.plotly_chart(fig, use_container_width=True)
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
                _style_plotly_figure(fig)
                plot_host.plotly_chart(fig, use_container_width=True)
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
                _style_plotly_figure(fig)
                plot_host.plotly_chart(fig, use_container_width=True)
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
                _style_plotly_figure(fig)
                plot_host.plotly_chart(fig, use_container_width=True)

            if plot_type != "Bar" and value_mode == "percent_mean":
                plot_host.caption("% of mean uses dataset-specific normalization.")

            if data.errors:
                plot_host.warning("Some datasets failed to plot:")
                for err in data.errors:
                    plot_host.write(f"- {err}")
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
            plot_host.error(str(exc))


def _render_sidebar_docs_toolbar() -> None:
    guide_text = _safe_read_text(_repo_root() / "GUIDE.md", limit=12000)
    changelog_text = _safe_read_text(_repo_root() / "CHANGELOG.md", limit=14000)
    st.markdown('<div class="ddp-panel-card">', unsafe_allow_html=True)
    cols = st.columns(2)
    if hasattr(st, "popover"):
        with cols[0]:
            with st.popover("Guide"):
                st.caption("Project guide (excerpt)")
                if guide_text:
                    st.code(guide_text, language="markdown")
                else:
                    st.info("GUIDE.md not found.")
        with cols[1]:
            with st.popover("Change log"):
                st.caption("Change log (excerpt)")
                if changelog_text:
                    st.code(changelog_text, language="markdown")
                else:
                    st.info("CHANGELOG.md not found.")
    else:
        with cols[0]:
            with st.expander("Guide", expanded=False):
                if guide_text:
                    st.code(guide_text, language="markdown")
                else:
                    st.info("GUIDE.md not found.")
        with cols[1]:
            with st.expander("Change log", expanded=False):
                if changelog_text:
                    st.code(changelog_text, language="markdown")
                else:
                    st.info("CHANGELOG.md not found.")

    theme_names = list(WEB_THEMES.keys())
    if st.session_state.web_theme not in theme_names:
        st.session_state.web_theme = theme_names[0]
    st.selectbox("Theme", theme_names, key="web_theme")
    st.markdown("</div>", unsafe_allow_html=True)


def _render_sidebar_section_nav() -> None:
    current = st.session_state.get("web_left_tab", "Project / Data")
    st.markdown('<div class="ddp-panel-card">', unsafe_allow_html=True)
    st.markdown('<p class="ddp-panel-title">Sections</p>', unsafe_allow_html=True)
    st.caption("Choose a workspace. Controls open in the main panel.")
    items = [
        ("Project / Data", "Load, organize, rename, and save datasets"),
        ("Plot", "Dataset visibility, plot settings, comparison, history"),
        ("Reports", "Report workflows and export (web parity in progress)"),
    ]
    for label, desc in items:
        is_active = current == label
        btn_label = f"{'Selected: ' if is_active else ''}{label}"
        if st.button(btn_label, key=f"nav_{label}", use_container_width=True):
            if not is_active:
                st.session_state.web_left_tab = label
                st.rerun()
        st.caption(desc)
    st.markdown("</div>", unsafe_allow_html=True)


def _load_project_obj(obj: object) -> None:
    state: ProjectState = st.session_state.project_state
    state.clear()
    st.session_state.plot_history = []
    st.session_state.plot_history_index = -1
    st.session_state.pending_plot_snapshot = None
    datasets = _datasets_from_json_obj(obj)
    _add_datasets(datasets, "PROJECT")
    _apply_settings_from_obj(obj)


def _render_project_data_sidebar() -> None:
    state: ProjectState = st.session_state.project_state
    st.markdown('<div class="ddp-panel-card">', unsafe_allow_html=True)
    st.markdown('<p class="ddp-panel-title">Project / Data</p>', unsafe_allow_html=True)
    st.markdown(
        '<p class="ddp-panel-subtitle">Load, organize, rename, and order datasets. This tab controls project structure and saved dataset order.</p>',
        unsafe_allow_html=True,
    )
    st.markdown("</div>", unsafe_allow_html=True)

    top_cols = st.columns(2, gap="large")
    with top_cols[0]:
        st.markdown('<div class="ddp-panel-card">', unsafe_allow_html=True)
        st.markdown('<p class="ddp-panel-title">Project file</p>', unsafe_allow_html=True)
        proj_file = st.file_uploader(
            "Load project",
            type=["json", "proj"],
            accept_multiple_files=False,
            key=f"project_uploader_{st.session_state.project_upload_token}",
            label_visibility="collapsed",
        )
        top_row = st.columns(3)
        with top_row[0]:
            if st.button("New project", use_container_width=True):
                state.clear()
                st.session_state.plot_history = []
                st.session_state.plot_history_index = -1
                st.session_state.pending_plot_snapshot = None
                st.rerun()
        with top_row[1]:
            if st.button("Load project...", use_container_width=True):
                if not proj_file:
                    st.warning("Select a project JSON file first.")
                else:
                    try:
                        obj = json.loads(proj_file.getvalue().decode("utf-8"))
                        _load_project_obj(obj)
                    except Exception as exc:
                        st.error(f"Project load failed: {exc}")
                    else:
                        st.session_state.project_upload_token += 1
                        st.success("Project loaded.")
                        st.rerun()
        with top_row[2]:
            payload = build_project_payload(state)
            st.download_button(
                "Save project...",
                data=json.dumps(payload, indent=2),
                file_name="dashboard_project.json",
                mime="application/json",
                use_container_width=True,
            )
        st.markdown("</div>", unsafe_allow_html=True)

    with top_cols[1]:
        st.markdown('<div class="ddp-panel-card">', unsafe_allow_html=True)
        st.markdown('<p class="ddp-panel-title">Data sources</p>', unsafe_allow_html=True)
        uploads = st.file_uploader(
            "Add data file(s)",
            type=["json"],
            accept_multiple_files=True,
            key=f"data_uploader_{st.session_state.data_upload_token}",
        )
        btn_cols = st.columns(2)
        with btn_cols[0]:
            if st.button("Add data file(s)...", use_container_width=True):
                if not uploads:
                    st.warning("No JSON files selected.")
                else:
                    loaded = 0
                    for f in uploads:
                        try:
                            obj = json.loads(f.getvalue().decode("utf-8"))
                            datasets = _datasets_from_json_obj(obj)
                            _add_datasets(datasets, f"FILE::{f.name}")
                            _apply_settings_from_obj(obj)
                            loaded += len(datasets)
                        except Exception as exc:
                            st.error(f"{f.name}: {exc}")
                    st.session_state.data_upload_token += 1
                    if loaded:
                        st.success(f"Loaded {loaded} dataset(s).")
                        st.rerun()
        with btn_cols[1]:
            visible_payload = build_dataset_data_payload(state, visible_only=True)
            st.download_button(
                "Save Data",
                data=json.dumps(visible_payload, indent=2),
                file_name="dashboard_data.data.json",
                mime="application/json",
                disabled=not bool(visible_payload),
                use_container_width=True,
            )
        st.markdown("</div>", unsafe_allow_html=True)

    st.markdown('<div class="ddp-panel-card">', unsafe_allow_html=True)
    st.markdown('<p class="ddp-panel-title">Paste data source</p>', unsafe_allow_html=True)
    st.caption("Paste a JSON dataset object or multi-dataset JSON, then load/save/clear from here.")
    paste_text = st.text_area("Paste JSON", key="paste_json_source", height=180, label_visibility="collapsed")
    paste_btns = st.columns(3)
    with paste_btns[0]:
        if st.button("Load pasted data", use_container_width=True):
            if not paste_text.strip():
                st.warning("Paste JSON content before loading.")
            else:
                try:
                    obj = json.loads(paste_text)
                    datasets = _datasets_from_json_obj(obj)
                    _add_datasets(datasets, "PASTE")
                    _apply_settings_from_obj(obj)
                except Exception as exc:
                    st.error(f"Paste error: {exc}")
                else:
                    st.success(f"Loaded {len(datasets)} dataset(s) from pasted JSON.")
                    st.rerun()
    with paste_btns[1]:
        st.download_button(
            "Save pasted data...",
            data=paste_text.encode("utf-8"),
            file_name="pasted_data.json",
            mime="application/json",
            disabled=not paste_text.strip(),
            use_container_width=True,
        )
    with paste_btns[2]:
        if st.button("Clear pasted data", use_container_width=True):
            st.session_state["paste_json_source"] = ""
            st.rerun()
    st.markdown("</div>", unsafe_allow_html=True)


def _render_project_data_main() -> None:
    state: ProjectState = st.session_state.project_state
    st.markdown('<div class="ddp-main-card">', unsafe_allow_html=True)
    st.subheader("Project / Data")
    st.caption("Dataset identity (`source_id`) is preserved internally; display names can be edited here.")
    _render_project_dataset_controls()
    order = ordered_source_ids(state)
    if order:
        rows = []
        for sid in order:
            df = state.loaded.get(sid)
            rows.append(
                {
                    "Show": bool(state.show_flag.get(sid, True)),
                    "Dataset": state.id_to_display.get(sid, sid),
                    "Rows": int(len(df)) if df is not None else 0,
                    "Columns": int(len(df.columns)) if df is not None else 0,
                    "Source ID": sid,
                }
            )
        st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)
    st.markdown("</div>", unsafe_allow_html=True)


def _render_reports_sidebar() -> None:
    st.markdown('<div class="ddp-panel-card">', unsafe_allow_html=True)
    st.markdown('<p class="ddp-panel-title">Reports</p>', unsafe_allow_html=True)
    st.markdown(
        '<p class="ddp-panel-subtitle">Windows report editing/export features are not yet fully ported to Streamlit. This tab mirrors the grouped layout and exposes the current web scope.</p>',
        unsafe_allow_html=True,
    )
    st.markdown("</div>", unsafe_allow_html=True)

    for title, desc in (
        ("Report file", "Create/open/save report workflows are currently Windows-first."),
        ("Content and annotations", "Rich HTML editor, plot snapshots, and annotation tools are pending for web parity."),
        ("Preview and export", "HTML/PDF report export parity is pending in the Streamlit adapter."),
    ):
        st.markdown('<div class="ddp-panel-card">', unsafe_allow_html=True)
        st.markdown(f'<p class="ddp-panel-title">{title}</p>', unsafe_allow_html=True)
        st.caption(desc)
        st.button("Coming soon", disabled=True, use_container_width=True, key=f"report_{title}")
        st.markdown("</div>", unsafe_allow_html=True)


def _render_reports_main() -> None:
    st.markdown('<div class="ddp-main-card">', unsafe_allow_html=True)
    st.subheader("Reports")
    st.info(
        "The Streamlit adapter now matches the Windows left-tab menu structure, but report editing/export parity is still pending."
    )
    st.markdown("</div>", unsafe_allow_html=True)


def _render_plot_page() -> None:
    st.markdown('<div class="ddp-main-card">', unsafe_allow_html=True)
    st.subheader("Plot")
    st.caption("Use the grouped controls below, then scroll to the generated plot output.")
    st.markdown("</div>", unsafe_allow_html=True)

    info_cols = st.columns([1.2, 1], gap="large")
    with info_cols[0]:
        _render_plot_dataset_visibility_controls()
    with info_cols[1]:
        st.markdown('<div class="ddp-panel-card">', unsafe_allow_html=True)
        st.markdown('<p class="ddp-panel-title">Plot guidance</p>', unsafe_allow_html=True)
        st.caption("Keep dataset order and naming in Project / Data. Use the controls here only for plot visibility and plot settings.")
        st.caption("The generated chart appears after the control groups, so web users can scroll naturally from settings to results.")
        st.markdown("</div>", unsafe_allow_html=True)

    _render_plot_controls()


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
    _inject_web_theme_css()

    st.title("Dashboard Data Plotter")
    st.caption("Streamlit UI using shared core state and plotting, with Windows-style left menu tabs.")

    with st.sidebar:
        _render_sidebar_docs_toolbar()
        _render_sidebar_section_nav()

    left_tab = st.session_state.web_left_tab
    if left_tab == "Project / Data":
        _render_project_data_sidebar()
        _render_project_data_main()
    elif left_tab == "Plot":
        _render_plot_page()
    else:
        _render_reports_sidebar()
        _render_reports_main()


if __name__ == "__main__":
    main()
