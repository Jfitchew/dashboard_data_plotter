from __future__ import annotations

import argparse
import base64
import json
import math
import os
from pathlib import Path
from typing import Any

import pandas as pd
import plotly.graph_objects as go
from dash import Dash, Input, Output, State, dcc, html, dash_table, no_update
from dash.exceptions import PreventUpdate

from dashboard_data_plotter.core.datasets import (
    add_dataset,
    move_dataset,
    ordered_source_ids,
    remove_dataset,
    rename_dataset,
)
from dashboard_data_plotter.core.io import (
    PROJECT_SETTINGS_KEY,
    apply_project_settings,
    build_dataset_data_payload,
    build_project_payload,
    extract_project_settings,
)
from dashboard_data_plotter.core.plotting import (
    prepare_bar_plot,
    prepare_cartesian_plot,
    prepare_radar_plot,
    prepare_timeseries_plot,
)
from dashboard_data_plotter.core.reporting import load_report, new_report_state
from dashboard_data_plotter.core.state import ProjectState
from dashboard_data_plotter.data.loaders import DEFAULT_SENTINELS, make_unique_name, parse_sentinels

try:
    import dash_bootstrap_components as dbc
except Exception:  # pragma: no cover - optional dependency at runtime
    dbc = None


SECTION_LABELS = {
    "project_data": "Project / Data",
    "plot": "Plot",
    "reports": "Reports",
}

THEME_OPTIONS = [
    {"label": "Light", "value": "theme-lux"},
    {"label": "Dark", "value": "theme-superhero"},
]

DBC_THEME_URLS: dict[str, str] = {
    "theme-lux": dbc.themes.LUX if dbc is not None else "",
    "theme-superhero": dbc.themes.SUPERHERO if dbc is not None else "",
}

PANEL_HELP_TEXT: dict[str, str] = {
    "project_file": (
        "Create a new project or save the current project JSON.\n"
        "Dropping/browsing a project file auto-loads it.\n"
        "Dataset order and settings are preserved."
    ),
    "data_sources": (
        "Add dataset JSON files or paste JSON dataset objects.\n"
        "Uploaded files auto-load into the current project.\n"
        "Save Data exports visible datasets in user-defined order."
    ),
    "dataset_order": (
        "This table is the primary dataset manager.\n"
        "Select a row, then rename, move up/down, or remove.\n"
        "Table order defines plot order and save/export order."
    ),
    "plot_controls": (
        "Choose datasets to show and configure plot type, metrics, filtering, comparison, and history.\n"
        "Bar plots enforce absolute values only.\n"
        "Use Plot to render and add a snapshot to history."
    ),
    "plot_output": (
        "Rendered Plotly chart area.\n"
        "Warnings/notes appear below the chart when applicable.\n"
        "Controls are kept compact to maximize chart space."
    ),
    "plot_actions": (
        "Run plots and navigate plot history snapshots.\n"
        "Plot adds the current settings to history after a successful render.\n"
        "Prev/Next/Delete/Clear operate on the plot history list."
    ),
    "report_file": (
        "Create a new report JSON state or save the current report JSON.\n"
        "Dropping/browsing a report file auto-loads it.\n"
        "Windows-encoded JSON uploads are tolerated when possible."
    ),
    "report_preview": (
        "Quick JSON summary of the current report state.\n"
        "Save report downloads the edited JSON.\n"
        "HTML/PDF export integration is planned next."
    ),
    "report_content": (
        "Raw report JSON editor for now.\n"
        "Use this to inspect/edit report content, metadata, and snapshots.\n"
        "Rich content editing workflows will be added later."
    ),
}


def _dash_assets_dir() -> str:
    return str(Path(__file__).resolve().parents[1] / "assets" / "dash")


def _empty_project_session() -> dict[str, Any]:
    return {
        "project_payload": build_project_payload(ProjectState()),
        "dataset_counter": 0,
        "paste_json": "",
        "plot_ui": {},
        "plot_history": [],
        "plot_history_index": -1,
        "plot_result_figure": None,
        "plot_result_errors": [],
        "plot_result_note": "",
        "report_payload": None,
        "report_paste_json": "",
    }


def _decode_upload_contents(contents: str | None) -> str:
    if not contents:
        raise ValueError("No file content provided.")
    if "," not in contents:
        raise ValueError("Invalid upload payload.")
    _meta, b64 = contents.split(",", 1)
    raw = base64.b64decode(b64)
    for enc in ("utf-8-sig", "utf-8", "cp1252", "latin-1"):
        try:
            return raw.decode(enc)
        except UnicodeDecodeError:
            continue
    raise UnicodeDecodeError("utf-8", raw, 0, 1, "Unable to decode uploaded text content.")


def _next_source_id(session: dict[str, Any], prefix: str) -> str:
    counter = int(session.get("dataset_counter", 0)) + 1
    session["dataset_counter"] = counter
    return f"{prefix}::{counter}"


def _datasets_from_json_obj_preserve_meta(
    obj: object,
    *,
    source_prefix: str,
    session: dict[str, Any],
) -> list[tuple[str, str, pd.DataFrame]]:
    out: list[tuple[str, str, pd.DataFrame]] = []

    if isinstance(obj, dict):
        for key, value in obj.items():
            if key == PROJECT_SETTINGS_KEY:
                continue
            records = None
            source_id = None
            display_name = str(key)
            if isinstance(value, dict) and isinstance(value.get("rideData"), list):
                records = value.get("rideData")
                source_id = value.get("__source_id__")
                if value.get("__display__"):
                    display_name = str(value.get("__display__"))
            elif isinstance(value, list):
                records = value
            if records is None:
                continue
            if records and not isinstance(records[0], dict):
                continue
            df = pd.DataFrame(records)
            for c in df.columns:
                df[c] = pd.to_numeric(df[c], errors="coerce")
            sid = str(source_id).strip() if source_id else _next_source_id(session, source_prefix)
            out.append((sid, display_name, df))
        if out:
            return out
        if "rideData" in obj and isinstance(obj.get("rideData"), list):
            records = obj.get("rideData") or []
            if records and not isinstance(records[0], dict):
                return []
            df = pd.DataFrame(records)
            for c in df.columns:
                df[c] = pd.to_numeric(df[c], errors="coerce")
            out.append((_next_source_id(session, source_prefix), "Dataset", df))
            return out

    if isinstance(obj, list):
        if obj and not isinstance(obj[0], dict):
            return []
        df = pd.DataFrame(obj)
        for c in df.columns:
            df[c] = pd.to_numeric(df[c], errors="coerce")
        return [(_next_source_id(session, source_prefix), "Dataset", df)]

    raise ValueError("Unrecognized JSON structure.")


def _state_from_session(session_data: dict[str, Any] | None) -> tuple[ProjectState, dict[str, Any]]:
    session = dict(session_data or {})
    if "project_payload" not in session:
        session = _empty_project_session()
    payload = session.get("project_payload", {})
    if not isinstance(payload, dict):
        payload = {}

    state = ProjectState()
    existing_names: set[str] = set()
    max_counter = int(session.get("dataset_counter", 0))
    for name, value in payload.items():
        if name == PROJECT_SETTINGS_KEY:
            continue
        if not isinstance(value, dict) or not isinstance(value.get("rideData"), list):
            continue
        records = value.get("rideData") or []
        if records and not isinstance(records[0], dict):
            continue
        df = pd.DataFrame(records)
        for c in df.columns:
            df[c] = pd.to_numeric(df[c], errors="coerce")
        source_id = str(value.get("__source_id__") or "").strip() or str(name)
        display = str(value.get("__display__") or name)
        if display in existing_names:
            display = make_unique_name(display, existing_names)
        existing_names.add(display)
        try:
            add_dataset(state, source_id, display, df)
        except ValueError:
            source_id = make_unique_name(source_id, set(state.loaded.keys()))
            add_dataset(state, source_id, display, df)
        if "::" in source_id:
            try:
                max_counter = max(max_counter, int(str(source_id).rsplit("::", 1)[1]))
            except Exception:
                pass

    settings = extract_project_settings(payload)
    if settings:
        apply_project_settings(state, settings)

    session["dataset_counter"] = max_counter
    session.setdefault("paste_json", "")
    session["project_payload"] = build_project_payload(state)
    return state, session


def _session_from_state(state: ProjectState, session: dict[str, Any]) -> dict[str, Any]:
    out = dict(session)
    out["project_payload"] = build_project_payload(state)
    out.setdefault("paste_json", "")
    out.setdefault("dataset_counter", 0)
    out.setdefault("plot_ui", {})
    out.setdefault("plot_history", [])
    out.setdefault("plot_history_index", -1)
    out.setdefault("plot_result_figure", None)
    out.setdefault("plot_result_errors", [])
    out.setdefault("plot_result_note", "")
    out.setdefault("report_payload", None)
    out.setdefault("report_paste_json", "")
    return out


def _reset_dash_plot_runtime(session: dict[str, Any]) -> None:
    session["plot_ui"] = {}
    session["plot_history"] = []
    session["plot_history_index"] = -1
    session["plot_result_figure"] = None
    session["plot_result_errors"] = []
    session["plot_result_note"] = ""


def _error_group_card(title: str, exc: Exception) -> html.Div:
    return html.Div(
        className="ddp-card",
        children=[
            html.Div(
                className="ddp-card-header",
                children=[html.H3(title, className="ddp-card-title"), html.Span("Error", className="ddp-badge")],
            ),
            html.P(
                f"{type(exc).__name__}: {exc}",
                className="ddp-muted",
            ),
            html.P(
                "This section failed to render, but navigation and other sections remain available.",
                className="ddp-muted",
            ),
        ],
    )


def _inactive_section_placeholder(section_label: str) -> list[html.Div]:
    return [
        html.Div(
            className="ddp-card ddp-card--span-4",
            children=[
                html.Div(
                    className="ddp-card-header",
                    children=[
                        html.H3(section_label, className="ddp-card-title"),
                        html.Span("Idle", className="ddp-badge"),
                    ],
                ),
                html.P(
                    "Section UI is not rendered until selected to keep navigation and project loads responsive.",
                    className="ddp-muted",
                ),
                html.Div(className="ddp-placeholder-lines", children=[html.Div(className="ddp-line"), html.Div(className="ddp-line short")]),
            ],
        )
    ]


def _status_alert(message: str, kind: str = "info"):
    return html.Div(message, className=f"ddp-status {kind}")


def _help_icon(help_text: str) -> html.Span:
    lines = [ln.strip() for ln in str(help_text or "").splitlines() if ln.strip()]
    tooltip_lines = [html.Div(ln) for ln in lines] if lines else [html.Div("No additional help.")]
    return html.Span(
        className="ddp-help-wrap",
        children=[
            html.Span("?", className="ddp-help-icon", tabIndex=0, role="button", **{"aria-label": "Panel help"}),
            html.Span(className="ddp-help-tooltip", children=tooltip_lines),
        ],
    )


def _card_header_with_help(title: str, help_text: str) -> html.Div:
    return html.Div(
        className="ddp-card-header",
        children=[html.H3(title, className="ddp-card-title"), _help_icon(help_text)],
    )


def _dataset_table_rows(state: ProjectState) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for i, sid in enumerate(ordered_source_ids(state), start=1):
        df = state.loaded.get(sid)
        rows.append(
            {
                "order": i,
                "dataset": state.id_to_display.get(sid, sid),
                "rows": int(len(df)) if df is not None else 0,
                "columns": int(len(df.columns)) if df is not None else 0,
                "show": bool(state.show_flag.get(sid, True)),
                "source_id": sid,
            }
        )
    return rows


def _selected_dataset_id_from_rows(rows: list[dict[str, Any]], selected_rows: list[int] | None) -> str | None:
    if not rows:
        return None
    idxs = list(selected_rows or [])
    if not idxs:
        return None
    try:
        idx = int(idxs[0])
    except Exception:
        return None
    if idx < 0 or idx >= len(rows):
        return None
    sid = rows[idx].get("source_id")
    return str(sid) if sid else None


def _collect_columns(state: ProjectState) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for sid in ordered_source_ids(state):
        df = state.loaded.get(sid)
        if df is None:
            continue
        for col in df.columns:
            if col not in seen:
                seen.add(col)
                out.append(str(col))
    return out


def _default_plot_ui(state: ProjectState, session: dict[str, Any]) -> dict[str, Any]:
    cols = _collect_columns(state)
    angle_default = "leftPedalCrankAngle" if "leftPedalCrankAngle" in cols else (cols[0] if cols else "")
    metric_default = state.plot_settings.metric_column if state.plot_settings.metric_column in cols else (cols[0] if cols else "")
    agg_map_rev = {
        "mean": "mean",
        "median": "median",
        "trimmed_mean_10": "10% trimmed mean",
        "pedal_stroke": "pedal_stroke",
        "roll_360deg": "roll_360deg",
    }
    agg_label = agg_map_rev.get(str(state.plot_settings.agg_mode or "mean"), "mean")
    baseline_displays = [
        state.id_to_display.get(sid, sid)
        for sid in state.plot_settings.baseline_source_ids
        if sid in state.loaded
    ]
    ui = {
        "show_source_ids": [sid for sid in ordered_source_ids(state) if bool(state.show_flag.get(sid, True))],
        "plot_type": {
            "radar": "Radar",
            "cartesian": "Cartesian",
            "bar": "Bar",
            "timeseries": "Time series",
        }.get(str(state.plot_settings.plot_type or "radar").lower(), "Radar"),
        "angle_col": state.plot_settings.angle_column if state.plot_settings.angle_column in cols else angle_default,
        "close_loop": bool(state.plot_settings.close_loop),
        "metric_col": metric_default,
        "agg_label": agg_label,
        "sentinels_str": ",".join(str(v) for v in state.cleaning_settings.sentinels) if state.cleaning_settings.sentinels else DEFAULT_SENTINELS,
        "value_mode": str(state.plot_settings.value_mode or "absolute"),
        "range_low": str(state.plot_settings.range_low or ""),
        "range_high": str(state.plot_settings.range_high or ""),
        "range_fixed": bool(state.plot_settings.range_fixed),
        "remove_outliers": bool(state.cleaning_settings.remove_outliers),
        "outlier_method": str(state.cleaning_settings.outlier_method or "MAD"),
        "outlier_threshold": (
            "" if state.cleaning_settings.outlier_threshold is None else str(state.cleaning_settings.outlier_threshold)
        ),
        "radar_background": bool(state.plot_settings.radar_background),
        "compare": bool(state.plot_settings.compare),
        "baseline_displays": baseline_displays,
    }
    saved = session.get("plot_ui", {})
    if isinstance(saved, dict):
        ui.update({k: v for k, v in saved.items() if k in ui})
    return ui


def _sync_show_flags_from_ui(state: ProjectState, show_source_ids: list[str] | None) -> None:
    show_set = set(show_source_ids or [])
    for sid in ordered_source_ids(state):
        state.show_flag[sid] = sid in show_set


def _plot_snapshot_from_controls(controls: dict[str, Any]) -> dict[str, Any]:
    keys = [
        "show_source_ids",
        "plot_type",
        "angle_col",
        "close_loop",
        "metric_col",
        "agg_label",
        "sentinels_str",
        "value_mode",
        "range_low",
        "range_high",
        "range_fixed",
        "remove_outliers",
        "outlier_method",
        "outlier_threshold",
        "radar_background",
        "compare",
        "baseline_displays",
    ]
    snap = {k: controls.get(k) for k in keys}
    if isinstance(snap.get("show_source_ids"), list):
        snap["show_source_ids"] = list(snap["show_source_ids"])
    if isinstance(snap.get("baseline_displays"), list):
        snap["baseline_displays"] = list(snap["baseline_displays"])
    return snap


def _plotly_template_for_dash_theme(theme_class: str) -> str:
    return "plotly_dark" if theme_class == "theme-superhero" else "plotly_white"


def _figure_theme_layout(fig: go.Figure, theme_class: str = "theme-lux") -> None:
    fig.update_layout(
        template=_plotly_template_for_dash_theme(theme_class),
        margin=dict(l=20, r=20, t=56, b=24),
        legend=dict(orientation="v"),
    )


def _retheme_figure_dict(figure: dict[str, Any] | None, theme_class: str) -> dict[str, Any] | None:
    if not isinstance(figure, dict):
        return figure
    try:
        fig = go.Figure(figure)
        _figure_theme_layout(fig, theme_class)
        return fig.to_dict()
    except Exception:
        return figure


def _build_plot_result(
    state: ProjectState,
    controls: dict[str, Any],
) -> tuple[dict[str, Any] | None, list[str], str]:
    cols = _collect_columns(state)
    if not cols:
        raise ValueError("No columns found in datasets.")

    show_source_ids = [sid for sid in controls.get("show_source_ids", []) if sid in state.loaded]
    _sync_show_flags_from_ui(state, show_source_ids)
    if not any(bool(state.show_flag.get(sid, True)) for sid in ordered_source_ids(state)):
        raise ValueError("Select at least one dataset to plot.")

    plot_type = str(controls.get("plot_type") or "Radar")
    angle_col = str(controls.get("angle_col") or "")
    metric_col = str(controls.get("metric_col") or "")
    agg_label = str(controls.get("agg_label") or "mean")
    agg_key = {
        "mean": "mean",
        "median": "median",
        "10% trimmed mean": "trimmed_mean_10",
        "pedal_stroke": "pedal_stroke",
        "roll_360deg": "roll_360deg",
    }.get(agg_label, "mean")
    value_mode = str(controls.get("value_mode") or "absolute")
    compare = bool(controls.get("compare"))
    baseline_displays = [str(x) for x in (controls.get("baseline_displays") or [])]
    baseline_ids = [state.display_to_id.get(name) for name in baseline_displays]
    baseline_ids = [sid for sid in baseline_ids if sid]
    baseline_id = baseline_ids[0] if baseline_ids else None
    sentinels = parse_sentinels(str(controls.get("sentinels_str") or DEFAULT_SENTINELS))

    range_fixed = bool(controls.get("range_fixed"))
    range_low = str(controls.get("range_low") or "").strip()
    range_high = str(controls.get("range_high") or "").strip()
    fixed_range = None
    if range_fixed:
        if not range_low or not range_high:
            raise ValueError("Enter both Range min and Range max, or untick Fixed.")
        low_v = float(range_low)
        high_v = float(range_high)
        if not (math.isfinite(low_v) and math.isfinite(high_v)):
            raise ValueError("Range values must be finite numbers.")
        if low_v > high_v:
            raise ValueError("Range min must be <= Range max.")
        fixed_range = (low_v, high_v)

    remove_outliers = bool(controls.get("remove_outliers"))
    outlier_threshold = None
    if remove_outliers:
        thresh_text = str(controls.get("outlier_threshold") or "").strip()
        if not thresh_text:
            raise ValueError("Outlier threshold is required when outlier removal is enabled.")
        outlier_threshold = float(thresh_text)
    outlier_method = str(controls.get("outlier_method") or "MAD")
    close_loop = bool(controls.get("close_loop"))

    if compare and not baseline_ids:
        raise ValueError("Select at least one baseline dataset for comparison.")

    note = ""
    errors: list[str] = []
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
            outlier_threshold=outlier_threshold,
            outlier_method=outlier_method,
            close_loop=close_loop,
        )
        fig = go.Figure()
        for trace in data.traces:
            fig.add_trace(go.Scatterpolar(r=trace.y, theta=trace.x, mode="lines+markers", name=trace.label))
        if fixed_range:
            radial_range = list(fixed_range)
            if compare:
                radial_range = [radial_range[0] + data.offset, radial_range[1] + data.offset]
        else:
            radial_range = None
        polar_kwargs = dict(angularaxis=dict(direction="clockwise", rotation=90))
        if radial_range is not None:
            polar_kwargs["radialaxis"] = dict(range=radial_range)
        fig.update_layout(title=f"{metric_col} ({data.mode_label})", polar=polar_kwargs)
        errors = list(data.errors)
        if value_mode == "percent_mean":
            note = "% of mean uses dataset-specific normalization."
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
            outlier_threshold=outlier_threshold,
            outlier_method=outlier_method,
            close_loop=close_loop,
        )
        fig = go.Figure()
        for trace in data.traces:
            fig.add_scatter(x=trace.x, y=trace.y, mode="lines+markers", name=trace.label)
        layout_kwargs: dict[str, Any] = dict(title=f"{metric_col} ({data.mode_label})", xaxis_title="Crank angle (deg)")
        if fixed_range:
            layout_kwargs["yaxis"] = dict(range=list(fixed_range))
        fig.update_layout(**layout_kwargs)
        if compare:
            fig.add_hline(y=0, line_width=2, line_color="#7f8c8d")
        errors = list(data.errors)
        if value_mode == "percent_mean":
            note = "% of mean uses dataset-specific normalization."
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
            outlier_threshold=outlier_threshold,
            outlier_method=outlier_method,
        )
        fig = go.Figure(data=[go.Bar(x=data.labels, y=data.values)])
        layout_kwargs = dict(title=metric_col, xaxis_title="Dataset")
        if fixed_range:
            layout_kwargs["yaxis"] = dict(range=list(fixed_range))
        fig.update_layout(**layout_kwargs)
        if compare:
            fig.add_hline(y=0, line_width=2, line_color="#7f8c8d")
        errors = list(data.errors)
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
            outlier_threshold=outlier_threshold,
            outlier_method=outlier_method,
        )
        fig = go.Figure()
        for trace in data.traces:
            fig.add_scatter(x=trace.x, y=trace.y, mode="lines+markers", name=trace.label)
        layout_kwargs = dict(title=f"{metric_col} ({data.mode_label})", xaxis_title=data.x_label, yaxis_title=metric_col)
        if fixed_range:
            layout_kwargs["yaxis"] = dict(range=list(fixed_range))
        fig.update_layout(**layout_kwargs)
        if compare and data.baseline_label:
            fig.add_scatter(x=[0, data.max_x], y=[0, 0], mode="lines", name=data.baseline_label, line=dict(width=1.6))
        errors = list(data.errors)
        if value_mode == "percent_mean":
            note = "% of mean uses dataset-specific normalization."

    _figure_theme_layout(fig)
    return fig.to_dict(), errors, note


def _add_datasets_to_state(
    state: ProjectState,
    session: dict[str, Any],
    obj: object,
    *,
    source_prefix: str,
) -> int:
    rows = _datasets_from_json_obj_preserve_meta(obj, source_prefix=source_prefix, session=session)
    existing = set(state.display_to_id.keys())
    count = 0
    for sid, display, df in rows:
        chosen = make_unique_name(display, existing)
        existing.add(chosen)
        source_id = sid
        if source_id in state.loaded:
            source_id = _next_source_id(session, source_prefix)
        add_dataset(state, source_id, chosen, df)
        count += 1
    return count


def _section_intro(section_key: str) -> tuple[str, str]:
    if section_key == "project_data":
        return (
            "Project / Data",
            "Load, organize, rename, and order datasets. This section will own project structure and save order.",
        )
    if section_key == "plot":
        return (
            "Plot",
            "Configure datasets to plot, plot type, metrics, range, mode, and history, then scroll to the output.",
        )
    return (
        "Reports",
        "Create, edit, preview, and export report content. Dash parity for reports will be added incrementally.",
    )


def _group_card(title: str, body: str, *, badge: str = "Phase 1") -> html.Div:
    return html.Div(
        className="ddp-card",
        children=[
            html.Div(
                className="ddp-card-header",
                children=[
                    html.H3(title, className="ddp-card-title"),
                    html.Span(badge, className="ddp-badge"),
                ],
            ),
            html.P(body, className="ddp-muted"),
            html.Div(
                className="ddp-placeholder-lines",
                children=[
                    html.Div(className="ddp-line"),
                    html.Div(className="ddp-line short"),
                ],
            ),
        ],
    )


def _section_groups(section_key: str) -> list[html.Div]:
    if section_key == "project_data":
        return [
            _group_card("Project file", "New/save project controls; uploaded project files auto-load."),
            _group_card("Data sources", "Upload or paste dataset JSON, plus Save Data export (visible-only order preserved)."),
            _group_card("Dataset order and names", "Rename, remove, and reorder datasets while preserving source_id identity."),
        ]
    if section_key == "plot":
        return [
            _group_card("Plot controls", "Compact dataset/metric/filter/mode/history controls grouped into a multi-column panel."),
            _group_card("Plot output", "Larger rendered chart workspace and plotting warnings/errors."),
        ]
    return [
        _group_card("Report file", "Create/open/save report workflows."),
        _group_card("Content and annotations", "Content blocks, plot snapshots, and annotation controls."),
        _group_card("Preview and export", "HTML/PDF preview and export workflows."),
    ]


def _project_data_groups(session_data: dict[str, Any] | None) -> list[html.Div]:
    state, session = _state_from_session(session_data)
    rows = _dataset_table_rows(state)
    dataset_options = [
        {"label": f'{r["order"]}. {r["dataset"]}', "value": r["source_id"]} for r in rows
    ]
    selected_sid = dataset_options[0]["value"] if dataset_options else None
    selected_sid = str(session.get("dataset_selected_sid") or selected_sid or "") or None
    if selected_sid and selected_sid not in state.loaded:
        selected_sid = dataset_options[0]["value"] if dataset_options else None
    selected_name = state.id_to_display.get(selected_sid, "") if selected_sid else ""
    selected_row_idx = 0
    if selected_sid:
        for idx, row in enumerate(rows):
            if row.get("source_id") == selected_sid:
                selected_row_idx = idx
                break
    visible_payload = build_dataset_data_payload(state, visible_only=True)
    project_payload = build_project_payload(state)

    project_file_card = html.Div(
        className="ddp-card ddp-card--span-4",
        children=[
            _card_header_with_help(
                "Project file",
                PANEL_HELP_TEXT["project_file"],
            ),
            dcc.Upload(
                id="project-upload",
                multiple=False,
                className="ddp-upload",
                children=html.Div(
                    ["Drop project JSON here or ", html.Span("browse")],
                    title="Drop or browse a project JSON file to auto-load project datasets and settings.",
                ),
            ),
            html.Div(
                className="ddp-button-row",
                children=[
                    html.Button("New project", id="project-new-btn", n_clicks=0, className="ddp-btn", title="Clear current project state and start a new empty project."),
                    html.Button("Save project", id="project-save-btn", n_clicks=0, className="ddp-btn ddp-btn-primary", title="Download the current project JSON including dataset order and settings."),
                ],
            ),
            html.Div(
                className="ddp-download-hints",
                children=f'{len(project_payload) - (1 if PROJECT_SETTINGS_KEY in project_payload else 0)} dataset(s) in project',
            ),
        ],
    )

    data_sources_card = html.Div(
        className="ddp-card ddp-card--span-4",
        children=[
            _card_header_with_help(
                "Data sources",
                PANEL_HELP_TEXT["data_sources"],
            ),
            html.Div("Drop dataset JSON file(s)", className="ddp-subtitle"),
            dcc.Upload(
                id="data-upload",
                multiple=True,
                className="ddp-upload",
                children=html.Div(
                    ["Drop dataset JSON file(s) here or ", html.Span("browse")],
                    title="Drop or browse one or more dataset JSON files to add them to the current project in file order.",
                ),
            ),
            html.Div(
                className="ddp-button-row",
                children=[
                    html.Button(
                        "Save Data",
                        id="data-save-btn",
                        n_clicks=0,
                        className="ddp-btn ddp-btn-primary",
                        title="Download a .data.json export containing only datasets currently marked Show, preserving table order.",
                        disabled=not bool(visible_payload),
                    ),
                ],
            ),
            html.Div(
                className="ddp-download-hints",
                children=f'{len(visible_payload)} visible dataset(s) ready for export',
            ),
            html.Div("Paste dataset JSON", className="ddp-subtitle"),
            html.Div(
                title="Paste a dataset JSON object, rideData object, or multi-dataset JSON payload here.",
                children=dcc.Textarea(
                    id="paste-json",
                    value=str(session.get("paste_json", "")),
                    className="ddp-textarea ddp-textarea--compact",
                    placeholder="Paste JSON dataset object or multi-dataset JSON here...",
                ),
            ),
            html.Div(
                className="ddp-button-row",
                children=[
                    html.Button("Add pasted JSON", id="paste-load-btn", n_clicks=0, className="ddp-btn", title="Parse the pasted JSON and add dataset(s) into the current project."),
                    html.Button("Save pasted JSON", id="paste-save-btn", n_clicks=0, className="ddp-btn", title="Download the pasted JSON text exactly as entered."),
                    html.Button("Clear", id="paste-clear-btn", n_clicks=0, className="ddp-btn", title="Clear the pasted JSON text box."),
                ],
            ),
        ],
    )

    dataset_order_card = html.Div(
        className="ddp-card ddp-card--span-8 ddp-card--row-span-2",
        children=[
            _card_header_with_help(
                "Dataset order and names",
                PANEL_HELP_TEXT["dataset_order"],
            ),
            html.Div(
                className="ddp-inline-form",
                children=[
                    html.Div(
                        title="Edit the display name for the currently selected dataset row.",
                        children=dcc.Input(
                            id="dataset-rename-input",
                            type="text",
                            value=selected_name,
                            placeholder="Selected row name",
                            className="ddp-input",
                        ),
                    ),
                    html.Button("Rename", id="dataset-rename-btn", n_clicks=0, className="ddp-btn", title="Apply the new display name to the selected dataset."),
                ],
            ),
            html.Div(
                className="ddp-button-row",
                children=[
                    html.Button("Up", id="dataset-up-btn", n_clicks=0, className="ddp-btn", title="Move selected dataset up"),
                    html.Button("Down", id="dataset-down-btn", n_clicks=0, className="ddp-btn", title="Move selected dataset down"),
                    html.Button("Remove", id="dataset-remove-btn", n_clicks=0, className="ddp-btn ddp-btn-danger", title="Remove selected dataset"),
                ],
            ),
            dash_table.DataTable(
                id="dataset-table",
                data=rows,
                columns=[
                    {"name": "#", "id": "order"},
                    {"name": "Dataset", "id": "dataset"},
                    {"name": "Rows", "id": "rows"},
                    {"name": "Cols", "id": "columns"},
                    {"name": "Show", "id": "show"},
                    {"name": "Source ID", "id": "source_id"},
                ],
                row_selectable="single",
                selected_rows=[selected_row_idx] if rows else [],
                tooltip_header={
                    "order": "Dataset order (drives plot and save/export order).",
                    "dataset": "Display name used in the UI and legends.",
                    "rows": "Number of rows in the loaded dataset.",
                    "columns": "Number of columns in the loaded dataset.",
                    "show": "Current Show/Hide flag used by plotting.",
                    "source_id": "Stable dataset identity used internally and for comparisons.",
                },
                style_table={"overflowX": "auto", "overflowY": "auto", "maxHeight": "520px", "marginTop": "0.6rem"},
                style_cell={"fontSize": "0.85rem", "padding": "0.35rem", "textAlign": "left"},
                style_header={"fontWeight": "700"},
                style_data_conditional=[
                    {"if": {"column_id": "source_id"}, "fontFamily": "monospace", "fontSize": "0.78rem"},
                    {"if": {"state": "selected"}, "backgroundColor": "rgba(39, 100, 255, 0.12)", "border": "1px solid rgba(39, 100, 255, 0.35)"},
                ],
                style_data={
                    "whiteSpace": "normal",
                    "height": "auto",
                },
                page_action="none",
            ),
        ],
    )

    return [
        project_file_card,
        dataset_order_card,
        data_sources_card,
    ]


def _plot_groups(session_data: dict[str, Any] | None) -> list[html.Div]:
    state, session = _state_from_session(session_data)
    cols = _collect_columns(state)
    ui = _default_plot_ui(state, session)
    order = ordered_source_ids(state)
    show_options = [{"label": f"{i}. {state.id_to_display.get(sid, sid)}", "value": sid} for i, sid in enumerate(order, start=1)]
    baseline_options = [state.id_to_display.get(sid, sid) for sid in order]
    plot_type = ui.get("plot_type", "Radar")
    show_angle = plot_type in ("Radar", "Cartesian")
    allow_close_loop = plot_type in ("Radar", "Cartesian")
    allow_value_mode = plot_type in ("Radar", "Cartesian", "Time series")
    history = session.get("plot_history", []) if isinstance(session.get("plot_history"), list) else []
    history_index = int(session.get("plot_history_index", -1))
    history_text = f"History {history_index + 1}/{len(history)}" if history else "History 0/0"
    figure = session.get("plot_result_figure")
    errors = session.get("plot_result_errors") if isinstance(session.get("plot_result_errors"), list) else []
    note = str(session.get("plot_result_note") or "")

    graph_children: list[Any] = []
    if figure:
        graph_children.append(dcc.Graph(id="plot-graph", figure=figure, className="ddp-graph"))
    else:
        graph_children.append(html.Div("Press Plot to generate a chart.", className="ddp-empty-plot"))
    if note:
        graph_children.append(html.Div(note, className="ddp-inline-note"))
    if errors:
        graph_children.append(
            html.Ul([html.Li(e) for e in errors], className="ddp-error-list")
        )

    return [
        html.Div(
            className="ddp-card ddp-card--span-4 ddp-card--row-span-2 ddp-card--plot-controls",
            children=[
                _card_header_with_help(
                    "Plot controls",
                    PANEL_HELP_TEXT["plot_controls"],
                ),
                html.P("Dataset visibility, plot settings, filtering, comparison, and history", className="ddp-muted"),
                html.Div(
                    className="ddp-control-group",
                    children=[
                        html.Div("Datasets to plot", className="ddp-subtitle"),
                        dcc.Checklist(
                            id="plot-show-source-ids",
                            options=show_options,
                            value=[sid for sid in ui.get("show_source_ids", []) if sid in state.loaded],
                            className="ddp-checklist ddp-checklist--scroll",
                            inputClassName="ddp-checklist-input",
                            labelClassName="ddp-checklist-label",
                        ),
                        html.Div(className="ddp-button-row", children=[
                            html.Button("Show all", id="plot-show-all-btn", n_clicks=0, className="ddp-btn"),
                            html.Button("Hide all", id="plot-hide-all-btn", n_clicks=0, className="ddp-btn"),
                        ]),
                    ],
                ),
                html.Div(
                    className="ddp-control-group",
                    children=[
                        html.Div("Plot type", className="ddp-subtitle"),
                        html.Div(
                            className="ddp-plot-type-row",
                            children=[
                                html.Div(
                                    className="ddp-plot-type-main",
                                    children=dcc.Dropdown(
                                        id="plot-type",
                                        options=[{"label": x, "value": x} for x in ["Radar", "Cartesian", "Bar", "Time series"]],
                                        value=ui.get("plot_type", "Radar"),
                                        clearable=False,
                                        className="ddp-theme-dropdown",
                                    ),
                                ),
                                html.Div(
                                    className="ddp-plot-type-bg",
                                    title="Show radar background image placeholder support in Dash (where available).",
                                    children=dcc.Checklist(
                                        id="plot-radar-background",
                                        options=[{"label": "Background", "value": "on"}],
                                        value=["on"] if ui.get("radar_background", True) else [],
                                        className="ddp-checklist compact",
                                    ),
                                ),
                            ],
                        ),
                    ],
                ),
                html.Div(
                    className="ddp-control-group",
                    children=[
                        html.Div(
                            className="ddp-metrics-title-row",
                            children=[
                                html.Div("Metrics", className="ddp-subtitle"),
                                html.Div(
                                    className="ddp-metrics-close-loop",
                                    children=dcc.Checklist(
                                        id="plot-close-loop",
                                        options=[{"label": "Close loop", "value": "on"}],
                                        value=["on"] if (allow_close_loop and ui.get("close_loop", True)) else [],
                                        className="ddp-checklist compact",
                                    ),
                                ),
                            ],
                        ),
                        dcc.Dropdown(
                            id="plot-angle-col",
                            options=[{"label": c, "value": c} for c in cols],
                            value=ui.get("angle_col") if ui.get("angle_col") in cols else (cols[0] if cols else None),
                            clearable=False,
                            className="ddp-theme-dropdown",
                            disabled=(not show_angle) or (not cols),
                            placeholder="Angle column",
                        ),
                        dcc.Dropdown(
                            id="plot-metric-col",
                            options=[{"label": c, "value": c} for c in cols],
                            value=ui.get("metric_col") if ui.get("metric_col") in cols else (cols[0] if cols else None),
                            clearable=False,
                            className="ddp-theme-dropdown",
                            placeholder="Metric column",
                        ),
                        dcc.Dropdown(
                            id="plot-agg-label",
                            options=[{"label": x, "value": x} for x in ["mean", "median", "10% trimmed mean", "pedal_stroke", "roll_360deg"]],
                            value=ui.get("agg_label", "mean"),
                            clearable=False,
                            className="ddp-theme-dropdown",
                        ),
                        html.Div(
                            className="ddp-range-row ddp-range-row--metrics",
                            children=[
                                html.Div(
                                    className="ddp-range-fixed",
                                    children=dcc.Checklist(id="plot-range-fixed", options=[{"label": "Fixed range", "value": "on"}], value=["on"] if ui.get("range_fixed") else [], className="ddp-checklist compact"),
                                ),
                                html.Div(children=dcc.Input(id="plot-range-low", type="text", value=ui.get("range_low", ""), className="ddp-input", placeholder="Range min")),
                                html.Div(children=dcc.Input(id="plot-range-high", type="text", value=ui.get("range_high", ""), className="ddp-input", placeholder="Range max")),
                            ],
                        ),
                    ],
                ),
                html.Div(
                    className="ddp-control-group",
                    children=[
                        html.Div("Outliers", className="ddp-subtitle"),
                        html.Div(
                            className="ddp-outliers-row",
                            children=[
                                html.Div(
                                    className="ddp-outliers-remove",
                                    children=dcc.Checklist(
                                        id="plot-remove-outliers",
                                        options=[{"label": "Remove", "value": "on"}],
                                        value=["on"] if ui.get("remove_outliers") else [],
                                        className="ddp-checklist compact",
                                    ),
                                ),
                                html.Div(
                                    className="ddp-outliers-method",
                                    children=dcc.Dropdown(
                                        id="plot-outlier-method",
                                        options=[{"label": x, "value": x} for x in ["MAD", "Phase-MAD", "Hampel", "Impulse"]],
                                        value=ui.get("outlier_method", "MAD"),
                                        clearable=False,
                                        className="ddp-theme-dropdown",
                                    ),
                                ),
                                html.Div(
                                    className="ddp-outliers-threshold",
                                    children=dcc.Input(id="plot-outlier-threshold", type="text", value=ui.get("outlier_threshold", ""), className="ddp-input", placeholder="Threshold"),
                                ),
                            ],
                        ),
                    ],
                ),
                html.Div(
                    className="ddp-control-group",
                    children=[
                        html.Div("Mode", className="ddp-subtitle"),
                        dcc.RadioItems(
                            id="plot-value-mode",
                            options=[{"label": "Absolute", "value": "absolute"}, {"label": "% of dataset mean", "value": "percent_mean"}],
                            value=ui.get("value_mode", "absolute") if allow_value_mode else "absolute",
                            className="ddp-radio-inline",
                            inputClassName="ddp-radio-input",
                            labelClassName="ddp-radio-label",
                            inline=True,
                        ),
                        html.Div("Bar plot uses absolute values only." if not allow_value_mode else "", className="ddp-inline-note"),
                        dcc.Checklist(id="plot-compare", options=[{"label": "Compare vs baseline", "value": "on"}], value=["on"] if ui.get("compare") else [], className="ddp-checklist compact"),
                        dcc.Dropdown(
                            id="plot-baseline-displays",
                            options=[{"label": x, "value": x} for x in baseline_options],
                            value=[x for x in ui.get("baseline_displays", []) if x in baseline_options],
                            multi=True,
                            className="ddp-theme-dropdown",
                            placeholder="Baseline dataset(s)",
                        ),
                    ],
                ),
            ],
        ),
        html.Div(
            className="ddp-card ddp-card--span-8 ddp-card--plot-actions ddp-card--toolbar",
            children=[
                html.Div(
                    className="ddp-actions-row",
                    children=[
                        html.Button("Plot", id="plot-run-btn", n_clicks=0, className="ddp-btn ddp-btn-primary ddp-btn--plot-main"),
                        html.Button("Prev", id="plot-prev-btn", n_clicks=0, className="ddp-btn", disabled=history_index <= 0),
                        html.Button("🗑", id="plot-delete-history-btn", n_clicks=0, className="ddp-btn", title="Delete current history entry", disabled=history_index < 0),
                        html.Button("Next", id="plot-next-btn", n_clicks=0, className="ddp-btn", disabled=history_index >= len(history) - 1),
                        html.Button("Clear All", id="plot-clear-history-btn", n_clicks=0, className="ddp-btn", disabled=not bool(history)),
                        html.Div(history_text, className="ddp-download-hints ddp-actions-history-text"),
                        _help_icon(PANEL_HELP_TEXT["plot_actions"]),
                    ],
                ),
            ],
        ),
        html.Div(
            className="ddp-card ddp-card--span-8 ddp-card--plot-output",
            children=[
                _card_header_with_help(
                    "Plot output",
                    PANEL_HELP_TEXT["plot_output"],
                ),
                html.P("Larger plot workspace with controls grouped into a compact column.", className="ddp-muted"),
                html.Div(graph_children),
            ],
        ),
    ]


def _reports_groups(session_data: dict[str, Any] | None) -> list[html.Div]:
    state, session = _state_from_session(session_data)
    report_payload = session.get("report_payload") if isinstance(session.get("report_payload"), dict) else None
    if report_payload is None:
        data_sources = [{"source_id": sid, "display": state.id_to_display.get(sid, sid)} for sid in ordered_source_ids(state)]
        report_payload = new_report_state("Dashboard Data Plotter", "", data_sources)
    report_text = json.dumps(report_payload, indent=2)
    return [
        html.Div(
            className="ddp-card ddp-card--span-4",
            children=[
                _card_header_with_help(
                    "Report file",
                    PANEL_HELP_TEXT["report_file"],
                ),
                html.P("Create/load/save basic report JSON state (rich editing/export remains to be ported).", className="ddp-muted"),
                dcc.Upload(id="report-upload", multiple=False, className="ddp-upload", children=html.Div(["Drop report JSON here or ", html.Span("browse")])),
                html.Div(className="ddp-button-row", children=[
                    html.Button("New report", id="report-new-btn", n_clicks=0, className="ddp-btn"),
                    html.Button("Save report", id="report-save-btn", n_clicks=0, className="ddp-btn ddp-btn-primary"),
                ]),
                html.Div("Report file loads automatically after browse/drop/paste.", className="ddp-inline-note"),
            ],
        ),
        html.Div(
            className="ddp-card ddp-card--span-8",
            children=[
                _card_header_with_help(
                    "Preview and export",
                    PANEL_HELP_TEXT["report_preview"],
                ),
                html.P("Report JSON summary and download; HTML/PDF export integration is planned next.", className="ddp-muted"),
                html.Div(f'Title: {report_payload.get("title", "Untitled")} | Snapshots: {len(report_payload.get("snapshots", []))}', className="ddp-download-hints"),
                html.Div(json.dumps({"title": report_payload.get("title"), "include_meta": report_payload.get("include_meta"), "snapshots": len(report_payload.get("snapshots", []))}, indent=2), className="ddp-pre-json"),
            ],
        ),
        html.Div(
            className="ddp-card ddp-card--span-12",
            children=[
                _card_header_with_help(
                    "Content and annotations",
                    PANEL_HELP_TEXT["report_content"],
                ),
                html.P("Preview/edit raw report JSON for now. Rich content editor and snapshot management will be added later.", className="ddp-muted"),
                dcc.Textarea(id="report-json-editor", value=report_text, className="ddp-textarea"),
            ],
        ),
    ]


def _sidebar() -> html.Div:
    return html.Aside(
        id="app-sidebar",
        className="ddp-sidebar",
        children=[
            html.Div(
                className="ddp-brand",
                children=[
                    html.Div("DDP", className="ddp-brand-icon", title="Dashboard Data Plotter"),
                    html.Div(
                        className="ddp-brand-copy",
                        children=[
                            html.Div("Dashboard Data Plotter", className="ddp-brand-title"),
                            html.Div("Dash Web App (Phase 1 Shell)", className="ddp-brand-subtitle"),
                        ],
                    ),
                    html.Button(
                        id="sidebar-toggle-btn",
                        n_clicks=0,
                        className="ddp-sidebar-toggle",
                        title="Collapse / expand sidebar",
                        children=[
                            html.Span("<<", className="ddp-when-expanded"),
                            html.Span(">>", className="ddp-when-collapsed"),
                        ],
                    ),
                ],
            ),
            html.Div(
                className="ddp-nav-group",
                children=[
                    html.Div("Sections", className="ddp-nav-title"),
                    html.Button(
                        [html.Span("PD", className="ddp-nav-icon", title="Project / Data section"), html.Span("Project / Data", className="ddp-nav-label")],
                        id="nav-project-data",
                        n_clicks=0,
                        className="ddp-nav-btn",
                        title="Project / Data",
                    ),
                    html.Button(
                        [html.Span("PL", className="ddp-nav-icon", title="Plot section"), html.Span("Plot", className="ddp-nav-label")],
                        id="nav-plot",
                        n_clicks=0,
                        className="ddp-nav-btn",
                        title="Plot",
                    ),
                    html.Button(
                        [html.Span("RP", className="ddp-nav-icon", title="Reports section"), html.Span("Reports", className="ddp-nav-label")],
                        id="nav-reports",
                        n_clicks=0,
                        className="ddp-nav-btn",
                        title="Reports",
                    ),
                ],
            ),
            html.Div(
                className="ddp-nav-group",
                children=[
                    html.Div([html.Span("TH", className="ddp-nav-icon", title="Theme settings"), html.Span("Theme", className="ddp-nav-title-text")], className="ddp-nav-title ddp-nav-title-row", title="Theme settings"),
                    dcc.Dropdown(
                        id="theme-select",
                        options=THEME_OPTIONS,
                        value="theme-lux",
                        clearable=False,
                        className="ddp-theme-dropdown",
                    ),
                ],
            ),
            html.Div(
                className="ddp-nav-group",
                children=[
                    html.Div([html.Span("TL", className="ddp-nav-icon", title="Tools"), html.Span("Tools", className="ddp-nav-title-text")], className="ddp-nav-title ddp-nav-title-row", title="Tools"),
                    html.Details(
                        className="ddp-details",
                        children=[
                            html.Summary([html.Span("G", className="ddp-nav-icon", title="Guide / help"), html.Span("Guide", className="ddp-nav-label")], title="Guide / help"),
                            html.P("Phase 1 shell only. Phase 2+ will wire real controls and workflows."),
                        ],
                    ),
                    html.Details(
                        className="ddp-details",
                        children=[
                            html.Summary([html.Span("CL", className="ddp-nav-icon", title="Change log"), html.Span("Change log", className="ddp-nav-label")], title="Change log"),
                            html.P("Dash adapter scaffold added as a parallel web UI migration path."),
                        ],
                    ),
                ],
            ),
        ],
    )


def _main_content(section_key: str) -> html.Div:
    title, subtitle = _section_intro(section_key)
    groups = _section_groups(section_key)
    return html.Main(
        className="ddp-main",
        children=[
            html.Div(
                className="ddp-hero",
                children=[
                    html.Div(
                        [
                            html.H1(title, className="ddp-page-title"),
                            html.P(subtitle, className="ddp-page-subtitle"),
                        ]
                    ),
                    html.Div(
                        className="ddp-hero-note",
                        children=[
                            html.Div("Phase 1"),
                            html.Small("Navigation + themed layout shell"),
                        ],
                    ),
                ],
            ),
            html.Div(className="ddp-group-grid", children=groups),
        ],
    )


def _main_content_for_state(section_key: str, project_session: dict[str, Any] | None) -> html.Div:
    title, subtitle = _section_intro(section_key)
    project_groups = _inactive_section_placeholder("Project / Data")
    plot_groups = _inactive_section_placeholder("Plot")
    reports_groups = _inactive_section_placeholder("Reports")

    if section_key == "project_data":
        try:
            project_groups = _project_data_groups(project_session)
        except Exception as exc:
            project_groups = [_error_group_card("Project / Data", exc)]
    elif section_key == "plot":
        try:
            plot_groups = _plot_groups(project_session)
        except Exception as exc:
            plot_groups = [_error_group_card("Plot", exc)]
    elif section_key == "reports":
        try:
            reports_groups = _reports_groups(project_session)
        except Exception as exc:
            reports_groups = [_error_group_card("Reports", exc)]
    return html.Main(
        className="ddp-main",
        children=[
            html.Div(
                className="ddp-hero",
                children=[
                    html.Div(
                        [
                            html.H1(title, className="ddp-page-title"),
                            html.P(subtitle, className="ddp-page-subtitle"),
                        ]
                    ),
                    html.Div(
                        className="ddp-hero-note",
                        children=[
                            html.Div("Phase 2/3" if section_key == "project_data" else ("Phase 4" if section_key == "plot" else ("Phase 5" if section_key == "reports" else "Phase 1"))),
                            html.Small("Live state" if section_key in {"project_data", "plot", "reports"} else "Layout shell"),
                        ],
                    ),
                ],
            ),
            html.Div(id="project-status-slot", className="ddp-status-wrap"),
            html.Div(id="plot-status-slot", className="ddp-status-wrap"),
            html.Div(id="report-status-slot", className="ddp-status-wrap"),
            html.Div(
                className=f"ddp-section-wrap{' is-hidden' if section_key != 'project_data' else ''}",
                children=html.Div(className="ddp-group-grid", children=project_groups),
            ),
            html.Div(
                className=f"ddp-section-wrap{' is-hidden' if section_key != 'plot' else ''}",
                children=html.Div(className="ddp-group-grid", children=plot_groups),
            ),
            html.Div(
                className=f"ddp-section-wrap{' is-hidden' if section_key != 'reports' else ''}",
                children=html.Div(className="ddp-group-grid", children=reports_groups),
            ),
            dcc.Download(id="download-project"),
            dcc.Download(id="download-data"),
            dcc.Download(id="download-paste"),
            dcc.Download(id="download-report"),
        ],
    )

def _root_layout(
    initial_project_session: dict[str, Any] | None = None,
    initial_ui_session: dict[str, Any] | None = None,
) -> html.Div:
    project_session = initial_project_session if isinstance(initial_project_session, dict) else _empty_project_session()
    ui_session = (
        initial_ui_session
        if isinstance(initial_ui_session, dict)
        else {"section": "project_data", "theme": "theme-lux", "sidebar_collapsed": False}
    )
    return html.Div(
        id="app-shell",
        className="ddp-app-shell theme-lux",
        children=[
            html.Link(id="dbc-theme-link", rel="stylesheet", href=DBC_THEME_URLS.get("theme-lux", "")),
            dcc.Store(
                id="ui-session",
                storage_type="session",
                data=ui_session,
            ),
            # Project payloads can exceed browser Web Storage quotas; keep the large
            # per-page working state in memory and reserve session storage for small UI state.
            dcc.Store(id="project-session", storage_type="memory", data=project_session),
            _sidebar(),
            html.Div(id="main-content-slot", children=_main_content_for_state("project_data", project_session)),
        ],
    )


def _load_startup_handoff(startup_session_file: str | None) -> tuple[dict[str, Any], dict[str, Any]]:
    project_session = _empty_project_session()
    ui_session: dict[str, Any] = {"section": "project_data", "theme": "theme-lux", "sidebar_collapsed": False}
    path = str(startup_session_file or "").strip()
    if not path:
        return project_session, ui_session
    try:
        with open(path, "r", encoding="utf-8") as handle:
            raw = json.load(handle)
        if not isinstance(raw, dict):
            return project_session, ui_session

        incoming_project_session = raw.get("project_session")
        if isinstance(incoming_project_session, dict):
            state, session = _state_from_session(incoming_project_session)
            project_session = _session_from_state(state, session)
            report_payload = incoming_project_session.get("report_payload")
            if isinstance(report_payload, dict):
                project_session["report_payload"] = report_payload
            report_paste_json = incoming_project_session.get("report_paste_json")
            if isinstance(report_paste_json, str):
                project_session["report_paste_json"] = report_paste_json
            handoff_meta = incoming_project_session.get("handoff_meta")
            if isinstance(handoff_meta, dict):
                project_session["handoff_meta"] = handoff_meta

        incoming_ui_session = raw.get("ui_session")
        if isinstance(incoming_ui_session, dict):
            for key in ("section", "theme", "sidebar_collapsed"):
                if key in incoming_ui_session:
                    ui_session[key] = incoming_ui_session[key]
        if ui_session.get("section") not in {"project_data", "plot", "reports"}:
            ui_session["section"] = "project_data"
        if ui_session.get("theme") not in DBC_THEME_URLS:
            ui_session["theme"] = "theme-lux"
        ui_session["sidebar_collapsed"] = bool(ui_session.get("sidebar_collapsed", False))
    except Exception:
        pass
    finally:
        try:
            if path and os.path.isfile(path):
                os.remove(path)
        except Exception:
            pass
    return project_session, ui_session


def create_app(*, startup_session_file: str | None = None) -> Dash:
    if dbc is None:
        raise RuntimeError(
            "Dash Phase 1 requires optional dependencies `dash` and `dash-bootstrap-components`."
        )
    initial_project_session, initial_ui_session = _load_startup_handoff(startup_session_file)
    app = Dash(
        __name__,
        assets_folder=_dash_assets_dir(),
        suppress_callback_exceptions=True,
        title="Dashboard Data Plotter (Dash)",
    )
    app.layout = _root_layout(initial_project_session, initial_ui_session)
    _register_callbacks(app)
    return app


def _register_callbacks(app: Dash) -> None:
    @app.callback(
        Output("ui-session", "data"),
        Input("nav-project-data", "n_clicks"),
        Input("nav-plot", "n_clicks"),
        Input("nav-reports", "n_clicks"),
        Input("sidebar-toggle-btn", "n_clicks"),
        Input("theme-select", "value"),
        State("ui-session", "data"),
        prevent_initial_call=True,
    )
    def _update_ui_state(
        n_project: int,
        n_plot: int,
        n_reports: int,
        n_sidebar_toggle: int,
        theme_value: str,
        current: dict[str, Any] | None,
    ) -> dict[str, Any]:
        from dash import ctx

        data = dict(current or {})
        data.setdefault("section", "project_data")
        data["theme"] = theme_value or "theme-lux"
        data.setdefault("sidebar_collapsed", False)

        trigger = ctx.triggered_id
        if trigger == "nav-project-data":
            data["section"] = "project_data"
        elif trigger == "nav-plot":
            data["section"] = "plot"
        elif trigger == "nav-reports":
            data["section"] = "reports"
        elif trigger == "sidebar-toggle-btn":
            data["sidebar_collapsed"] = not bool(data.get("sidebar_collapsed", False))

        return data

    @app.callback(
        Output("main-content-slot", "children"),
        Output("app-shell", "className"),
        Output("dbc-theme-link", "href"),
        Output("nav-project-data", "className"),
        Output("nav-plot", "className"),
        Output("nav-reports", "className"),
        Input("ui-session", "data"),
        Input("project-session", "data"),
    )
    def _render_from_ui_state(data: dict[str, Any] | None, project_session: dict[str, Any] | None):
        state = dict(data or {})
        section = state.get("section", "project_data")
        theme_class = state.get("theme", "theme-lux")
        sidebar_collapsed = bool(state.get("sidebar_collapsed", False))
        if theme_class not in DBC_THEME_URLS:
            theme_class = "theme-lux"
        shell_class = f"ddp-app-shell {theme_class}{' sidebar-collapsed' if sidebar_collapsed else ''}"
        themed_project_session = dict(project_session or {}) if isinstance(project_session, dict) else project_session
        if isinstance(themed_project_session, dict):
            themed_project_session["plot_result_figure"] = _retheme_figure_dict(
                themed_project_session.get("plot_result_figure"),
                theme_class,
            )

        def nav_class(key: str) -> str:
            base = "ddp-nav-btn"
            return f"{base} is-active" if key == section else base

        return (
            _main_content_for_state(section, themed_project_session),
            shell_class,
            DBC_THEME_URLS.get(theme_class, DBC_THEME_URLS["theme-lux"]),
            nav_class("project_data"),
            nav_class("plot"),
            nav_class("reports"),
        )

    @app.callback(
        Output("dataset-rename-input", "value"),
        Input("dataset-table", "selected_rows", allow_optional=True),
        State("project-session", "data", allow_optional=True),
        prevent_initial_call=True,
    )
    def _sync_dataset_name_input(selected_rows: list[int] | None, project_session: dict[str, Any] | None):
        state, _session = _state_from_session(project_session)
        selected_sid = _selected_dataset_id_from_rows(_dataset_table_rows(state), selected_rows)
        if not selected_sid:
            return ""
        return state.id_to_display.get(selected_sid, "")

    @app.callback(
        Output("project-session", "data"),
        Output("project-status-slot", "children"),
        Output("download-project", "data"),
        Output("download-data", "data"),
        Output("download-paste", "data"),
        Input("project-new-btn", "n_clicks", allow_optional=True),
        Input("project-upload", "contents", allow_optional=True),
        Input("project-save-btn", "n_clicks", allow_optional=True),
        Input("data-upload", "contents", allow_optional=True),
        Input("data-save-btn", "n_clicks", allow_optional=True),
        Input("paste-load-btn", "n_clicks", allow_optional=True),
        Input("paste-save-btn", "n_clicks", allow_optional=True),
        Input("paste-clear-btn", "n_clicks", allow_optional=True),
        Input("dataset-rename-btn", "n_clicks", allow_optional=True),
        Input("dataset-up-btn", "n_clicks", allow_optional=True),
        Input("dataset-down-btn", "n_clicks", allow_optional=True),
        Input("dataset-remove-btn", "n_clicks", allow_optional=True),
        State("project-upload", "filename", allow_optional=True),
        State("data-upload", "filename", allow_optional=True),
        State("paste-json", "value", allow_optional=True),
        State("dataset-table", "selected_rows", allow_optional=True),
        State("dataset-rename-input", "value", allow_optional=True),
        State("project-session", "data", allow_optional=True),
        prevent_initial_call=True,
    )
    def _project_data_actions(
        _new_clicks,
        project_contents,
        _save_project_clicks,
        data_contents,
        _save_data_clicks,
        _paste_load_clicks,
        _paste_save_clicks,
        _paste_clear_clicks,
        _rename_clicks,
        _up_clicks,
        _down_clicks,
        _remove_clicks,
        project_filename,
        data_filenames,
        paste_json_value,
        selected_rows,
        rename_value,
        project_session,
    ):
        from dash import ctx

        trigger = ctx.triggered_id
        if trigger is None:
            raise PreventUpdate

        download_project = no_update
        download_data = no_update
        download_paste = no_update

        state, session = _state_from_session(project_session)
        selected_sid = _selected_dataset_id_from_rows(_dataset_table_rows(state), selected_rows)
        session["dataset_selected_sid"] = selected_sid or ""
        session["paste_json"] = paste_json_value or ""
        status = no_update

        try:
            if trigger == "project-new-btn":
                state = ProjectState()
                session = _empty_project_session()
                status = _status_alert("Started a new project.", "success")

            elif trigger == "project-upload":
                if not project_contents:
                    status = _status_alert("Select a project JSON file first.", "warning")
                else:
                    raw = _decode_upload_contents(project_contents)
                    obj = json.loads(raw)
                    state = ProjectState()
                    session["dataset_counter"] = 0
                    loaded_count = _add_datasets_to_state(state, session, obj, source_prefix="PROJECT")
                    settings = extract_project_settings(obj)
                    if settings:
                        apply_project_settings(state, settings)
                    _reset_dash_plot_runtime(session)
                    session["report_payload"] = None
                    status = _status_alert(
                        f"Loaded project {project_filename or ''} with {loaded_count} dataset(s).".strip(),
                        "success",
                    )

            elif trigger == "project-save-btn":
                payload = build_project_payload(state)
                download_project = dcc.send_string(
                    lambda io: io.write(json.dumps(payload, indent=2)),
                    filename="dashboard_project.json",
                )
                status = _status_alert("Prepared project JSON download.", "success")

            elif trigger == "data-upload":
                if not data_contents:
                    status = _status_alert("Select one or more dataset JSON files first.", "warning")
                else:
                    contents_list = data_contents if isinstance(data_contents, list) else [data_contents]
                    names_list = data_filenames if isinstance(data_filenames, list) else [data_filenames]
                    added = 0
                    failures: list[str] = []
                    for idx, contents in enumerate(contents_list):
                        fname = str(names_list[idx]) if idx < len(names_list) else f"file_{idx+1}.json"
                        try:
                            raw = _decode_upload_contents(contents)
                            obj = json.loads(raw)
                            added += _add_datasets_to_state(state, session, obj, source_prefix=f"FILE::{fname}")
                            settings = extract_project_settings(obj)
                            if settings:
                                apply_project_settings(state, settings)
                            _reset_dash_plot_runtime(session)
                            session["report_payload"] = None
                        except Exception as exc:
                            failures.append(f"{fname}: {exc}")
                    if failures and not added:
                        status = _status_alert("Failed to load dataset file(s): " + " | ".join(failures[:3]), "danger")
                    elif failures:
                        status = _status_alert(
                            f"Loaded {added} dataset(s). Some files failed: {' | '.join(failures[:2])}",
                            "warning",
                        )
                    else:
                        status = _status_alert(f"Loaded {added} dataset(s) from uploaded files.", "success")

            elif trigger == "data-save-btn":
                payload = build_dataset_data_payload(state, visible_only=True)
                if not payload:
                    status = _status_alert("No visible datasets to export.", "warning")
                else:
                    download_data = dcc.send_string(
                        lambda io: io.write(json.dumps(payload, indent=2)),
                        filename="dashboard_data.data.json",
                    )
                    status = _status_alert(f"Prepared Save Data export for {len(payload)} visible dataset(s).", "success")

            elif trigger == "paste-load-btn":
                text = (paste_json_value or "").strip()
                if not text:
                    status = _status_alert("Paste JSON content before loading.", "warning")
                else:
                    obj = json.loads(text)
                    added = _add_datasets_to_state(state, session, obj, source_prefix="PASTE")
                    settings = extract_project_settings(obj)
                    if settings:
                        apply_project_settings(state, settings)
                    _reset_dash_plot_runtime(session)
                    session["report_payload"] = None
                    status = _status_alert(f"Loaded {added} dataset(s) from pasted JSON.", "success")

            elif trigger == "paste-save-btn":
                text = (paste_json_value or "").strip()
                if not text:
                    status = _status_alert("No pasted JSON to save.", "warning")
                else:
                    download_paste = dcc.send_string(
                        lambda io: io.write(text),
                        filename="pasted_data.json",
                    )
                    status = _status_alert("Prepared pasted JSON download.", "success")

            elif trigger == "paste-clear-btn":
                session["paste_json"] = ""
                status = _status_alert("Cleared pasted JSON text.", "success")

            elif trigger == "dataset-rename-btn":
                if not selected_sid:
                    status = _status_alert("Select a dataset to rename.", "warning")
                else:
                    new_name = str(rename_value or "").strip()
                    if not new_name:
                        status = _status_alert("Dataset name cannot be blank.", "warning")
                    else:
                        old = state.id_to_display.get(selected_sid, selected_sid)
                        renamed = rename_dataset(state, selected_sid, new_name)
                        _reset_dash_plot_runtime(session)
                        status = _status_alert(f'Renamed "{old}" to "{renamed}".', "success")

            elif trigger == "dataset-up-btn":
                if not selected_sid:
                    status = _status_alert("Select a dataset to move.", "warning")
                else:
                    move_dataset(state, selected_sid, -1)
                    _reset_dash_plot_runtime(session)
                    status = _status_alert("Moved dataset up.", "success")

            elif trigger == "dataset-down-btn":
                if not selected_sid:
                    status = _status_alert("Select a dataset to move.", "warning")
                else:
                    move_dataset(state, selected_sid, +1)
                    _reset_dash_plot_runtime(session)
                    status = _status_alert("Moved dataset down.", "success")

            elif trigger == "dataset-remove-btn":
                if not selected_sid:
                    status = _status_alert("Select a dataset to remove.", "warning")
                else:
                    label = state.id_to_display.get(selected_sid, selected_sid)
                    remove_dataset(state, selected_sid)
                    _reset_dash_plot_runtime(session)
                    session["report_payload"] = None
                    status = _status_alert(f'Removed dataset "{label}".', "success")

            else:
                raise PreventUpdate

        except json.JSONDecodeError as exc:
            status = _status_alert(f"JSON error: {exc}", "danger")
        except Exception as exc:
            status = _status_alert(f"{type(exc).__name__}: {exc}", "danger")

        session = _session_from_state(state, session)
        return session, status, download_project, download_data, download_paste

    @app.callback(
        Output("project-session", "data", allow_duplicate=True),
        Output("plot-status-slot", "children"),
        Input("plot-show-all-btn", "n_clicks", allow_optional=True),
        Input("plot-hide-all-btn", "n_clicks", allow_optional=True),
        Input("plot-run-btn", "n_clicks", allow_optional=True),
        Input("plot-prev-btn", "n_clicks", allow_optional=True),
        Input("plot-next-btn", "n_clicks", allow_optional=True),
        Input("plot-delete-history-btn", "n_clicks", allow_optional=True),
        Input("plot-clear-history-btn", "n_clicks", allow_optional=True),
        State("plot-show-source-ids", "value", allow_optional=True),
        State("plot-type", "value", allow_optional=True),
        State("plot-angle-col", "value", allow_optional=True),
        State("plot-close-loop", "value", allow_optional=True),
        State("plot-metric-col", "value", allow_optional=True),
        State("plot-agg-label", "value", allow_optional=True),
        State("plot-sentinels-str", "value", allow_optional=True),
        State("plot-value-mode", "value", allow_optional=True),
        State("plot-range-low", "value", allow_optional=True),
        State("plot-range-high", "value", allow_optional=True),
        State("plot-range-fixed", "value", allow_optional=True),
        State("plot-remove-outliers", "value", allow_optional=True),
        State("plot-outlier-method", "value", allow_optional=True),
        State("plot-outlier-threshold", "value", allow_optional=True),
        State("plot-radar-background", "value", allow_optional=True),
        State("plot-compare", "value", allow_optional=True),
        State("plot-baseline-displays", "value", allow_optional=True),
        State("project-session", "data", allow_optional=True),
        prevent_initial_call=True,
    )
    def _plot_actions(
        _show_all_clicks,
        _hide_all_clicks,
        _run_clicks,
        _prev_clicks,
        _next_clicks,
        _delete_clicks,
        _clear_clicks,
        show_source_ids,
        plot_type,
        angle_col,
        close_loop_values,
        metric_col,
        agg_label,
        sentinels_str,
        value_mode,
        range_low,
        range_high,
        range_fixed_values,
        remove_outliers_values,
        outlier_method,
        outlier_threshold,
        radar_background_values,
        compare_values,
        baseline_displays,
        project_session,
    ):
        from dash import ctx

        trigger = ctx.triggered_id
        if trigger is None:
            raise PreventUpdate

        state, session = _state_from_session(project_session)
        controls = _default_plot_ui(state, session)
        controls.update(
            {
                "show_source_ids": list(show_source_ids or []),
                "plot_type": plot_type or controls.get("plot_type", "Radar"),
                "angle_col": angle_col or controls.get("angle_col", ""),
                "close_loop": "on" in (close_loop_values or []),
                "metric_col": metric_col or controls.get("metric_col", ""),
                "agg_label": agg_label or controls.get("agg_label", "mean"),
                "sentinels_str": sentinels_str if sentinels_str is not None else controls.get("sentinels_str", DEFAULT_SENTINELS),
                "value_mode": value_mode or controls.get("value_mode", "absolute"),
                "range_low": range_low if range_low is not None else controls.get("range_low", ""),
                "range_high": range_high if range_high is not None else controls.get("range_high", ""),
                "range_fixed": "on" in (range_fixed_values or []),
                "remove_outliers": "on" in (remove_outliers_values or []),
                "outlier_method": outlier_method or controls.get("outlier_method", "MAD"),
                "outlier_threshold": outlier_threshold if outlier_threshold is not None else controls.get("outlier_threshold", ""),
                "radar_background": "on" in (radar_background_values or []),
                "compare": "on" in (compare_values or []),
                "baseline_displays": list(baseline_displays or []),
            }
        )

        history = list(session.get("plot_history", [])) if isinstance(session.get("plot_history"), list) else []
        history_index = int(session.get("plot_history_index", -1))
        status = no_update

        try:
            if trigger == "plot-show-all-btn":
                controls["show_source_ids"] = list(ordered_source_ids(state))
                _sync_show_flags_from_ui(state, controls["show_source_ids"])
                status = _status_alert("All datasets set to Show for plotting.", "success")

            elif trigger == "plot-hide-all-btn":
                controls["show_source_ids"] = []
                _sync_show_flags_from_ui(state, [])
                status = _status_alert("All datasets hidden from plotting.", "success")

            elif trigger == "plot-prev-btn":
                if history_index > 0:
                    history_index -= 1
                    snap = history[history_index]
                    controls.update({k: v for k, v in snap.items()})
                    fig_dict, errs, note = _build_plot_result(state, controls)
                    session["plot_result_figure"] = fig_dict
                    session["plot_result_errors"] = errs
                    session["plot_result_note"] = note
                    status = _status_alert("Loaded previous plot from history.", "success")
                else:
                    status = _status_alert("No previous history entry.", "warning")

            elif trigger == "plot-next-btn":
                if history_index < len(history) - 1:
                    history_index += 1
                    snap = history[history_index]
                    controls.update({k: v for k, v in snap.items()})
                    fig_dict, errs, note = _build_plot_result(state, controls)
                    session["plot_result_figure"] = fig_dict
                    session["plot_result_errors"] = errs
                    session["plot_result_note"] = note
                    status = _status_alert("Loaded next plot from history.", "success")
                else:
                    status = _status_alert("No next history entry.", "warning")

            elif trigger == "plot-delete-history-btn":
                if 0 <= history_index < len(history):
                    history.pop(history_index)
                    if history:
                        history_index = min(history_index, len(history) - 1)
                        snap = history[history_index]
                        controls.update({k: v for k, v in snap.items()})
                        fig_dict, errs, note = _build_plot_result(state, controls)
                        session["plot_result_figure"] = fig_dict
                        session["plot_result_errors"] = errs
                        session["plot_result_note"] = note
                    else:
                        history_index = -1
                        session["plot_result_figure"] = None
                        session["plot_result_errors"] = []
                        session["plot_result_note"] = ""
                    status = _status_alert("Deleted history entry.", "success")
                else:
                    status = _status_alert("No history entry selected.", "warning")

            elif trigger == "plot-clear-history-btn":
                history = []
                history_index = -1
                session["plot_result_figure"] = None
                session["plot_result_errors"] = []
                session["plot_result_note"] = ""
                status = _status_alert("Cleared plot history.", "success")

            elif trigger == "plot-run-btn":
                # Enforce bar semantics in UI snapshot even if controls still show prior values.
                if controls.get("plot_type") == "Bar":
                    controls["value_mode"] = "absolute"
                fig_dict, errs, note = _build_plot_result(state, controls)
                session["plot_result_figure"] = fig_dict
                session["plot_result_errors"] = errs
                session["plot_result_note"] = note
                snap = _plot_snapshot_from_controls(controls)
                if history_index < len(history) - 1:
                    history = history[: history_index + 1]
                history.append(snap)
                history_index = len(history) - 1
                status = _status_alert("Plot rendered and added to history.", "success")

            else:
                raise PreventUpdate

        except Exception as exc:
            status = _status_alert(f"{type(exc).__name__}: {exc}", "danger")

        session["plot_ui"] = controls
        session["plot_history"] = history
        session["plot_history_index"] = history_index
        session = _session_from_state(state, session)
        return session, status

    @app.callback(
        Output("project-session", "data", allow_duplicate=True),
        Output("report-status-slot", "children"),
        Output("download-report", "data"),
        Input("report-new-btn", "n_clicks", allow_optional=True),
        Input("report-upload", "contents", allow_optional=True),
        Input("report-save-btn", "n_clicks", allow_optional=True),
        State("report-upload", "filename", allow_optional=True),
        State("report-json-editor", "value", allow_optional=True),
        State("project-session", "data", allow_optional=True),
        prevent_initial_call=True,
    )
    def _report_actions(
        _new_clicks,
        report_contents,
        _save_clicks,
        report_filename,
        report_json_editor,
        project_session,
    ):
        from dash import ctx

        trigger = ctx.triggered_id
        if trigger is None:
            raise PreventUpdate
        state, session = _state_from_session(project_session)
        status = no_update
        download_report = no_update
        try:
            if trigger == "report-new-btn":
                data_sources = [{"source_id": sid, "display": state.id_to_display.get(sid, sid)} for sid in ordered_source_ids(state)]
                session["report_payload"] = new_report_state("Dashboard Data Plotter", "", data_sources)
                status = _status_alert("Created a new report state.", "success")
            elif trigger == "report-upload":
                if not report_contents:
                    status = _status_alert("Select a report JSON file first.", "warning")
                else:
                    raw = _decode_upload_contents(report_contents)
                    obj = json.loads(raw)
                    if not isinstance(obj, dict):
                        raise ValueError("Report file must contain a JSON object.")
                    session["report_payload"] = obj
                    status = _status_alert(f"Loaded report {report_filename or ''}.".strip(), "success")
            elif trigger == "report-save-btn":
                text = (report_json_editor or "").strip()
                if not text:
                    raise ValueError("Report JSON editor is empty.")
                obj = json.loads(text)
                if not isinstance(obj, dict):
                    raise ValueError("Report JSON must be an object.")
                session["report_payload"] = obj
                download_report = dcc.send_string(lambda io: io.write(json.dumps(obj, indent=2)), filename="dashboard_report.json")
                status = _status_alert("Prepared report JSON download.", "success")
            else:
                raise PreventUpdate
        except json.JSONDecodeError as exc:
            status = _status_alert(f"JSON error: {exc}", "danger")
        except Exception as exc:
            status = _status_alert(f"{type(exc).__name__}: {exc}", "danger")

        session = _session_from_state(state, session)
        return session, status, download_report


def main(**run_kwargs) -> None:
    startup_session_file = run_kwargs.pop("startup_session_file", None)
    app = create_app(startup_session_file=startup_session_file)
    app.run(**run_kwargs)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Dashboard Data Plotter Dash UI")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8050)
    parser.add_argument("--startup-session-file", default="")
    parser.add_argument("--debug", dest="debug", action="store_true", default=False)
    parser.add_argument("--no-debug", dest="debug", action="store_false")
    parser.add_argument("--reloader", dest="use_reloader", action="store_true", default=False)
    parser.add_argument("--no-reloader", dest="use_reloader", action="store_false")
    args = parser.parse_args()
    main(
        host=args.host,
        port=args.port,
        startup_session_file=args.startup_session_file,
        debug=args.debug,
        use_reloader=args.use_reloader,
    )
