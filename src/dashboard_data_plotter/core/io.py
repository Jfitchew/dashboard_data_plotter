from __future__ import annotations

from typing import Any, Iterable, Optional, Tuple

import json

import pandas as pd

from dashboard_data_plotter.core.datasets import ordered_source_ids
from dashboard_data_plotter.core.datasets import reorder_datasets
from dashboard_data_plotter.core.state import ProjectState
from dashboard_data_plotter.data.loaders import (
    df_to_jsonable_records,
    load_json_file_datasets,
    load_json_file_obj,
    make_unique_name,
)

PROJECT_SETTINGS_KEY = "__project_settings__"
PROJECT_SETTINGS_VERSION = 3


def build_project_settings(state: ProjectState) -> dict[str, Any]:
    plot = state.plot_settings
    cleaning = state.cleaning_settings
    order = [state.id_to_display.get(sid, sid) for sid in ordered_source_ids(state)]
    visibility = {
        state.id_to_display.get(sid, sid): bool(state.show_flag.get(sid, True))
        for sid in ordered_source_ids(state)
    }
    baseline_displays = [
        state.id_to_display.get(sid, sid)
        for sid in plot.baseline_source_ids
        if sid in state.loaded
    ]
    if not baseline_displays and plot.baseline_source_id:
        baseline_displays = [state.id_to_display.get(plot.baseline_source_id, "")]
    baseline_display = baseline_displays[0] if baseline_displays else ""

    return {
        "version": PROJECT_SETTINGS_VERSION,
        "dataset_order": order,
        "dataset_visibility": visibility,
        "plot": {
            "plot_type": plot.plot_type,
            "angle_column": plot.angle_column,
            "metric_column": plot.metric_column,
            "agg_mode": plot.agg_mode,
            "value_mode": plot.value_mode,
            "compare": plot.compare,
            "baseline_display": baseline_display,
            "baseline_displays": baseline_displays,
            "close_loop": plot.close_loop,
            "use_plotly": plot.use_plotly,
            "radar_background": plot.radar_background,
            "use_original_binned": plot.use_original_binned,
            "range_low": plot.range_low,
            "range_high": plot.range_high,
            "range_fixed": plot.range_fixed,
        },
        "cleaning": {
            "sentinels": list(cleaning.sentinels),
            "remove_outliers": cleaning.remove_outliers,
            "outlier_threshold": cleaning.outlier_threshold,
            "outlier_method": cleaning.outlier_method,
        },
        "analysis": {
            "stats_mode": state.analysis_settings.stats_mode,
            "report_options": dict(state.analysis_settings.report_options),
        },
        "alignment": {},
    }


def extract_project_settings(obj: Any) -> Optional[dict[str, Any]]:
    if isinstance(obj, dict):
        settings = obj.get(PROJECT_SETTINGS_KEY)
        if isinstance(settings, dict):
            return settings
    return None


def apply_project_settings(state: ProjectState, settings: dict[str, Any]) -> None:
    if not isinstance(settings, dict):
        return
    plot = settings.get("plot", {}) if isinstance(settings.get("plot", {}), dict) else {}
    cleaning = settings.get("cleaning", {}) if isinstance(settings.get("cleaning", {}), dict) else {}
    analysis = settings.get("analysis", {}) if isinstance(settings.get("analysis", {}), dict) else {}
    order_display = settings.get("dataset_order", [])
    visibility = settings.get("dataset_visibility", {})

    if isinstance(plot, dict):
        if "plot_type" in plot:
            state.plot_settings.plot_type = str(plot.get("plot_type") or "")
        if "angle_column" in plot:
            state.plot_settings.angle_column = str(plot.get("angle_column") or "")
        if "metric_column" in plot:
            state.plot_settings.metric_column = str(plot.get("metric_column") or "")
        if "agg_mode" in plot:
            state.plot_settings.agg_mode = str(plot.get("agg_mode") or "")
        if "value_mode" in plot:
            state.plot_settings.value_mode = str(plot.get("value_mode") or "")
        if "compare" in plot:
            state.plot_settings.compare = bool(plot.get("compare"))
        if "close_loop" in plot:
            state.plot_settings.close_loop = bool(plot.get("close_loop"))
        if "use_plotly" in plot:
            state.plot_settings.use_plotly = bool(plot.get("use_plotly"))
        if "radar_background" in plot:
            state.plot_settings.radar_background = bool(plot.get("radar_background"))
        if "use_original_binned" in plot:
            state.plot_settings.use_original_binned = bool(plot.get("use_original_binned"))
        if "range_low" in plot:
            state.plot_settings.range_low = str(plot.get("range_low") or "")
        if "range_high" in plot:
            state.plot_settings.range_high = str(plot.get("range_high") or "")
        if "range_fixed" in plot:
            state.plot_settings.range_fixed = bool(plot.get("range_fixed"))

        baseline_displays_raw = plot.get("baseline_displays", [])
        baseline_ids: list[str] = []
        if isinstance(baseline_displays_raw, list):
            for item in baseline_displays_raw:
                sid = state.display_to_id.get(str(item), "")
                if sid and sid not in baseline_ids:
                    baseline_ids.append(sid)
        baseline_display = str(plot.get("baseline_display") or "")
        baseline_id = state.display_to_id.get(baseline_display, "")
        if baseline_id and baseline_id not in baseline_ids:
            baseline_ids.insert(0, baseline_id)
        state.plot_settings.baseline_source_ids = baseline_ids
        state.plot_settings.baseline_source_id = baseline_ids[0] if baseline_ids else ""

    if isinstance(cleaning, dict):
        sentinels = cleaning.get("sentinels", [])
        if isinstance(sentinels, list):
            state.cleaning_settings.sentinels = [float(v) for v in sentinels if v is not None]
        if "remove_outliers" in cleaning:
            state.cleaning_settings.remove_outliers = bool(cleaning.get("remove_outliers"))
        if "outlier_threshold" in cleaning:
            state.cleaning_settings.outlier_threshold = cleaning.get("outlier_threshold")
        if "outlier_method" in cleaning:
            state.cleaning_settings.outlier_method = str(cleaning.get("outlier_method") or "impulse")

    if isinstance(analysis, dict):
        if "stats_mode" in analysis:
            state.analysis_settings.stats_mode = str(analysis.get("stats_mode") or "")
        report = analysis.get("report_options")
        if isinstance(report, dict):
            state.analysis_settings.report_options = {str(k): str(v) for k, v in report.items()}

    if isinstance(visibility, dict):
        for name, flag in visibility.items():
            sid = state.display_to_id.get(name)
            if sid:
                state.show_flag[sid] = bool(flag)

    if isinstance(order_display, list) and order_display:
        new_order = []
        seen = set()
        for name in order_display:
            sid = state.display_to_id.get(name)
            if sid and sid not in seen:
                new_order.append(sid)
                seen.add(sid)
        for sid in ordered_source_ids(state):
            if sid not in seen:
                new_order.append(sid)
                seen.add(sid)
        try:
            reorder_datasets(state, new_order)
        except ValueError:
            pass


def build_project_payload(state: ProjectState) -> dict[str, Any]:
    payload: dict[str, Any] = {}
    existing = set()
    for sid in ordered_source_ids(state):
        display = state.id_to_display.get(sid, sid)
        name = make_unique_name(display, existing)
        existing.add(name)
        df = state.loaded[sid]
        payload[name] = {
            "rideData": df_to_jsonable_records(df),
            "__source_id__": sid,
            "__display__": display,
        }
    payload[PROJECT_SETTINGS_KEY] = build_project_settings(state)
    return payload


def save_project_to_file(state: ProjectState, path: str) -> None:
    payload = build_project_payload(state)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2)


def load_project_from_file(path: str) -> Tuple[list[Tuple[str, pd.DataFrame]], Optional[dict[str, Any]]]:
    datasets = load_json_file_datasets(path)
    settings = extract_project_settings(load_json_file_obj(path))
    return datasets, settings
