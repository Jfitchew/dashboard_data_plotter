from __future__ import annotations

from dataclasses import dataclass, field
from typing import Iterable, Optional

import numpy as np

from dashboard_data_plotter.core.datasets import ordered_source_ids
from dashboard_data_plotter.core.state import ProjectState
from dashboard_data_plotter.data.loaders import (
    aggregate_metric,
    filter_outliers_mad,
    prepare_angle_value_agg,
    sanitize_numeric,
    wrap_angle_deg,
)
from dashboard_data_plotter.plotting.helpers import (
    circular_interp_baseline,
    to_percent_of_mean,
)


@dataclass
class PlotTrace:
    label: str
    x: np.ndarray
    y: np.ndarray
    source_id: Optional[str] = None
    is_baseline: bool = False


@dataclass
class RadarPlotData:
    traces: list[PlotTrace] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    mode_label: str = "absolute"
    agg_label: str = "Mean"
    metric_label: str = ""
    baseline_label: str = ""
    compare: bool = False
    offset: float = 0.0


@dataclass
class CartesianPlotData:
    traces: list[PlotTrace] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    mode_label: str = "absolute"
    agg_label: str = "Mean"
    metric_label: str = ""
    baseline_label: str = ""
    compare: bool = False


@dataclass
class BarPlotData:
    labels: list[str] = field(default_factory=list)
    values: list[float] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    mode_label: str = "absolute"
    agg_label: str = "Mean"
    metric_label: str = ""
    baseline_label: str = ""
    compare: bool = False


@dataclass
class TimeSeriesPlotData:
    traces: list[PlotTrace] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    mode_label: str = "absolute"
    metric_label: str = ""
    baseline_label: str = ""
    compare: bool = False
    x_label: str = ""
    max_x: float = 0.0


def _agg_label(agg_mode: str) -> str:
    return {
        "mean": "Mean",
        "median": "Median",
        "trimmed_mean_10": "10% trimmed mean",
    }.get(str(agg_mode).lower(), "Mean")


def _apply_value_mode(values: np.ndarray, mode: str) -> np.ndarray:
    if mode == "absolute":
        return np.asarray(values, dtype=float)
    if mode == "percent_mean":
        return to_percent_of_mean(values)
    raise ValueError(f"Unknown value mode: {mode}")


def _series_pedal_stroke(
    df,
    metric_col: str,
    sentinels: list[float],
    outlier_threshold: Optional[float],
) -> tuple[np.ndarray, np.ndarray]:
    if "leftPedalCrankAngle" not in df.columns:
        raise KeyError("Angle column 'leftPedalCrankAngle' not found.")
    ang = wrap_angle_deg(
        sanitize_numeric(df["leftPedalCrankAngle"], sentinels),
        convert_br_to_standard=True,
    ).to_numpy(dtype=float)
    val = sanitize_numeric(df[metric_col], sentinels)
    if outlier_threshold is not None:
        val = filter_outliers_mad(val, outlier_threshold)
    val = val.to_numpy(dtype=float)
    mask = np.isfinite(ang) & np.isfinite(val)
    ang = ang[mask]
    val = val[mask]
    if ang.size == 0:
        raise ValueError("No valid values after filtering.")

    stroke_means = []
    stroke_vals = []
    start_angle = ang[0]
    prev = ang[0]
    wrapped = False
    for a, v in zip(ang, val):
        if prev - a > 180.0:
            wrapped = True
        stroke_vals.append(v)
        if wrapped and a >= start_angle:
            stroke_means.append(float(np.nanmean(stroke_vals)))
            stroke_vals = []
            wrapped = False
        prev = a

    if not stroke_means:
        raise ValueError("No valid pedal strokes after filtering.")
    x = np.arange(len(stroke_means), dtype=float)
    y = np.asarray(stroke_means, dtype=float)
    return x, y


def _series_roll_360(
    df,
    metric_col: str,
    sentinels: list[float],
    outlier_threshold: Optional[float],
) -> tuple[np.ndarray, np.ndarray]:
    if "leftPedalCrankAngle" not in df.columns:
        raise KeyError("Angle column 'leftPedalCrankAngle' not found.")
    ang = wrap_angle_deg(
        sanitize_numeric(df["leftPedalCrankAngle"], sentinels),
        convert_br_to_standard=True,
    ).to_numpy(dtype=float)
    val = sanitize_numeric(df[metric_col], sentinels)
    if outlier_threshold is not None:
        val = filter_outliers_mad(val, outlier_threshold)
    val = val.to_numpy(dtype=float)
    mask = np.isfinite(ang) & np.isfinite(val)
    ang = ang[mask]
    val = val[mask]
    if ang.size == 0:
        raise ValueError("No valid values after filtering.")

    unwrapped = np.empty_like(ang, dtype=float)
    offset = 0.0
    prev = ang[0]
    unwrapped[0] = prev
    for idx in range(1, ang.size):
        a = ang[idx]
        if prev - a > 180.0:
            offset += 360.0
        unwrapped[idx] = a + offset
        prev = a

    out = []
    n = len(val)
    for i in range(n):
        target = unwrapped[i] + 360.0
        j = i + 1
        while j < n and unwrapped[j] < target:
            j += 1
        if j >= n:
            break
        window = val[i:j + 1]
        out.append(float(np.nanmean(window)))
    if not out:
        raise ValueError("No complete 360deg windows after filtering.")
    x = np.arange(len(out), dtype=float)
    return x, np.asarray(out, dtype=float)


def _resolve_sentinels(
    state: ProjectState,
    sentinels: Optional[Iterable[float]] = None,
) -> list[float]:
    if sentinels is not None:
        return list(sentinels)
    return list(state.cleaning_settings.sentinels)


def _resolve_outlier_threshold(
    state: ProjectState,
    outlier_threshold: Optional[float] = None,
) -> Optional[float]:
    if outlier_threshold is not None:
        return outlier_threshold
    if state.cleaning_settings.remove_outliers:
        return state.cleaning_settings.outlier_threshold
    return None


def _resolve_plot_inputs(
    state: ProjectState,
    angle_col: Optional[str] = None,
    metric_col: Optional[str] = None,
    agg_mode: Optional[str] = None,
    value_mode: Optional[str] = None,
    compare: Optional[bool] = None,
    baseline_id: Optional[str] = None,
):
    plot = state.plot_settings
    angle_col = angle_col if angle_col is not None else plot.angle_column
    metric_col = metric_col if metric_col is not None else plot.metric_column
    agg_mode = agg_mode if agg_mode is not None else plot.agg_mode
    value_mode = value_mode if value_mode is not None else plot.value_mode
    compare = bool(compare) if compare is not None else bool(plot.compare)
    baseline_id = baseline_id if baseline_id is not None else plot.baseline_source_id
    return angle_col, metric_col, agg_mode, value_mode, compare, baseline_id


def prepare_radar_plot(
    state: ProjectState,
    *,
    angle_col: Optional[str] = None,
    metric_col: Optional[str] = None,
    agg_mode: Optional[str] = None,
    value_mode: Optional[str] = None,
    compare: Optional[bool] = None,
    baseline_id: Optional[str] = None,
    sentinels: Optional[Iterable[float]] = None,
    outlier_threshold: Optional[float] = None,
    close_loop: Optional[bool] = None,
) -> RadarPlotData:
    angle_col, metric_col, agg_mode, value_mode, compare, baseline_id = _resolve_plot_inputs(
        state, angle_col, metric_col, agg_mode, value_mode, compare, baseline_id
    )
    if not angle_col:
        raise ValueError("Angle column is required for radar plot.")
    if not metric_col:
        raise ValueError("Metric column is required for radar plot.")
    sentinels = _resolve_sentinels(state, sentinels)
    outlier_threshold = _resolve_outlier_threshold(state, outlier_threshold)
    close_loop = bool(close_loop) if close_loop is not None else bool(state.plot_settings.close_loop)

    data = RadarPlotData(
        mode_label="absolute" if value_mode == "absolute" else "% of mean",
        agg_label=_agg_label(agg_mode),
        metric_label=metric_col,
        compare=compare,
    )
    order = ordered_source_ids(state)

    if compare:
        if not baseline_id or baseline_id not in state.loaded:
            raise ValueError("Baseline dataset is required for comparison.")
        b_label = state.id_to_display.get(baseline_id, baseline_id)
        data.baseline_label = b_label
        b_ang, b_val = prepare_angle_value_agg(
            state.loaded[baseline_id],
            angle_col,
            metric_col,
            sentinels,
            agg=agg_mode,
            outlier_threshold=outlier_threshold,
        )
        b_val2 = _apply_value_mode(b_val, value_mode)

        deltas: dict[str, tuple[np.ndarray, np.ndarray, str]] = {}
        max_abs = 0.0
        for sid in order:
            if not state.show_flag.get(sid, True):
                continue
            if sid == baseline_id:
                continue
            label = state.id_to_display.get(sid, sid)
            try:
                ang, val = prepare_angle_value_agg(
                    state.loaded[sid],
                    angle_col,
                    metric_col,
                    sentinels,
                    agg=agg_mode,
                    outlier_threshold=outlier_threshold,
                )
                val2 = _apply_value_mode(val, value_mode)
                base_at = circular_interp_baseline(b_ang, b_val2, ang)
                delta = val2 - base_at
                m = np.isfinite(delta) & np.isfinite(ang)
                ang = ang[m]
                delta = delta[m]
                if len(ang) == 0:
                    raise ValueError("No valid comparison values after filtering.")
                if close_loop and len(ang) > 2:
                    ang = np.concatenate([ang, [ang[0]]])
                    delta = np.concatenate([delta, [delta[0]]])
                deltas[sid] = (ang, delta, label)
                this_max = float(np.nanmax(np.abs(delta)))
                if np.isfinite(this_max):
                    max_abs = max(max_abs, this_max)
            except Exception as exc:
                data.errors.append(f"{label}: {exc}")

        if not deltas:
            return data

        if max_abs <= 0 or not np.isfinite(max_abs):
            max_abs = 1.0
        offset = 1.10 * max_abs
        data.offset = offset

        theta_ring = np.linspace(0.0, 360.0, 361)
        r_ring = np.full_like(theta_ring, offset, dtype=float)
        data.traces.append(
            PlotTrace(label=b_label, x=theta_ring, y=r_ring, source_id=baseline_id, is_baseline=True)
        )

        for _sid, (ang, delta, label) in deltas.items():
            data.traces.append(
                PlotTrace(label=label, x=ang, y=delta + offset, source_id=_sid, is_baseline=False)
            )
        return data

    for sid in order:
        if not state.show_flag.get(sid, True):
            continue
        label = state.id_to_display.get(sid, sid)
        try:
            ang, val = prepare_angle_value_agg(
                state.loaded[sid],
                angle_col,
                metric_col,
                sentinels,
                agg=agg_mode,
                outlier_threshold=outlier_threshold,
            )
            val2 = _apply_value_mode(val, value_mode)
            if close_loop and len(ang) > 2:
                ang = np.concatenate([ang, [ang[0]]])
                val2 = np.concatenate([val2, [val2[0]]])
            data.traces.append(PlotTrace(label=label, x=ang, y=val2, source_id=sid))
        except Exception as exc:
            data.errors.append(f"{label}: {exc}")

    return data


def prepare_cartesian_plot(
    state: ProjectState,
    *,
    angle_col: Optional[str] = None,
    metric_col: Optional[str] = None,
    agg_mode: Optional[str] = None,
    value_mode: Optional[str] = None,
    compare: Optional[bool] = None,
    baseline_id: Optional[str] = None,
    sentinels: Optional[Iterable[float]] = None,
    outlier_threshold: Optional[float] = None,
    close_loop: Optional[bool] = None,
) -> CartesianPlotData:
    angle_col, metric_col, agg_mode, value_mode, compare, baseline_id = _resolve_plot_inputs(
        state, angle_col, metric_col, agg_mode, value_mode, compare, baseline_id
    )
    if not angle_col:
        raise ValueError("Angle column is required for cartesian plot.")
    if not metric_col:
        raise ValueError("Metric column is required for cartesian plot.")
    sentinels = _resolve_sentinels(state, sentinels)
    outlier_threshold = _resolve_outlier_threshold(state, outlier_threshold)
    close_loop = bool(close_loop) if close_loop is not None else bool(state.plot_settings.close_loop)

    data = CartesianPlotData(
        mode_label="absolute" if value_mode == "absolute" else "% of mean",
        agg_label=_agg_label(agg_mode),
        metric_label=metric_col,
        compare=compare,
    )
    order = ordered_source_ids(state)

    if compare:
        if not baseline_id or baseline_id not in state.loaded:
            raise ValueError("Baseline dataset is required for comparison.")
        b_label = state.id_to_display.get(baseline_id, baseline_id)
        data.baseline_label = b_label
        b_ang, b_val = prepare_angle_value_agg(
            state.loaded[baseline_id],
            angle_col,
            metric_col,
            sentinels,
            agg=agg_mode,
            outlier_threshold=outlier_threshold,
        )
        b_val2 = _apply_value_mode(b_val, value_mode)

        for sid in order:
            if not state.show_flag.get(sid, True):
                continue
            if sid == baseline_id:
                continue
            label = state.id_to_display.get(sid, sid)
            try:
                ang, val = prepare_angle_value_agg(
                    state.loaded[sid],
                    angle_col,
                    metric_col,
                    sentinels,
                    agg=agg_mode,
                    outlier_threshold=outlier_threshold,
                )
                val2 = _apply_value_mode(val, value_mode)
                base_at = circular_interp_baseline(b_ang, b_val2, ang)
                delta = val2 - base_at
                m = np.isfinite(delta) & np.isfinite(ang)
                ang = ang[m]
                delta = delta[m]
                if len(ang) == 0:
                    raise ValueError("No valid comparison values after filtering.")
                order_idx = np.argsort(ang)
                ang = ang[order_idx]
                delta = delta[order_idx]
                if close_loop and len(ang) > 2:
                    ang = np.concatenate([ang, [360.0]])
                    delta = np.concatenate([delta, [delta[0]]])
                data.traces.append(PlotTrace(label=label, x=ang, y=delta, source_id=sid))
            except Exception as exc:
                data.errors.append(f"{label}: {exc}")
        return data

    for sid in order:
        if not state.show_flag.get(sid, True):
            continue
        label = state.id_to_display.get(sid, sid)
        try:
            ang, val = prepare_angle_value_agg(
                state.loaded[sid],
                angle_col,
                metric_col,
                sentinels,
                agg=agg_mode,
                outlier_threshold=outlier_threshold,
            )
            val2 = _apply_value_mode(val, value_mode)
            order_idx = np.argsort(ang)
            ang = ang[order_idx]
            val2 = val2[order_idx]
            if close_loop and len(ang) > 2:
                ang = np.concatenate([ang, [360.0]])
                val2 = np.concatenate([val2, [val2[0]]])
            data.traces.append(PlotTrace(label=label, x=ang, y=val2, source_id=sid))
        except Exception as exc:
            data.errors.append(f"{label}: {exc}")

    return data


def prepare_bar_plot(
    state: ProjectState,
    *,
    metric_col: Optional[str] = None,
    agg_mode: Optional[str] = None,
    value_mode: Optional[str] = None,
    compare: Optional[bool] = None,
    baseline_id: Optional[str] = None,
    sentinels: Optional[Iterable[float]] = None,
    outlier_threshold: Optional[float] = None,
) -> BarPlotData:
    _, metric_col, agg_mode, value_mode, compare, baseline_id = _resolve_plot_inputs(
        state, None, metric_col, agg_mode, value_mode, compare, baseline_id
    )
    if value_mode == "percent_mean":
        raise ValueError("Bar plot does not support % of dataset mean.")
    if not metric_col:
        raise ValueError("Metric column is required for bar plot.")
    sentinels = _resolve_sentinels(state, sentinels)
    outlier_threshold = _resolve_outlier_threshold(state, outlier_threshold)

    data = BarPlotData(
        mode_label="absolute",
        agg_label=_agg_label(agg_mode),
        metric_label=metric_col,
        compare=compare,
    )
    order = ordered_source_ids(state)

    baseline_value = None
    if compare:
        if not baseline_id or baseline_id not in state.loaded:
            raise ValueError("Baseline dataset is required for comparison.")
        baseline_label = state.id_to_display.get(baseline_id, baseline_id)
        data.baseline_label = baseline_label
        baseline_value = aggregate_metric(
            state.loaded[baseline_id][metric_col],
            sentinels,
            agg=agg_mode,
            outlier_threshold=outlier_threshold,
        )

    ordered_ids = []
    for sid in order:
        if compare and sid == baseline_id:
            ordered_ids.append(sid)
        elif state.show_flag.get(sid, True):
            ordered_ids.append(sid)
    if compare and baseline_id and baseline_id not in ordered_ids:
        ordered_ids.append(baseline_id)

    for sid in ordered_ids:
        label = state.id_to_display.get(sid, sid)
        try:
            val = aggregate_metric(
                state.loaded[sid][metric_col],
                sentinels,
                agg=agg_mode,
                outlier_threshold=outlier_threshold,
            )
            if compare and baseline_value is not None:
                if sid == baseline_id:
                    val = 0.0
                else:
                    val = val - baseline_value
            data.labels.append(label)
            data.values.append(val)
        except Exception as exc:
            data.errors.append(f"{label}: {exc}")

    return data


def prepare_timeseries_plot(
    state: ProjectState,
    *,
    metric_col: Optional[str] = None,
    agg_mode: Optional[str] = None,
    value_mode: Optional[str] = None,
    compare: Optional[bool] = None,
    baseline_id: Optional[str] = None,
    sentinels: Optional[Iterable[float]] = None,
    outlier_threshold: Optional[float] = None,
) -> TimeSeriesPlotData:
    _, metric_col, agg_mode, value_mode, compare, baseline_id = _resolve_plot_inputs(
        state, None, metric_col, agg_mode, value_mode, compare, baseline_id
    )
    if not metric_col:
        raise ValueError("Metric column is required for time series plot.")
    sentinels = _resolve_sentinels(state, sentinels)
    outlier_threshold = _resolve_outlier_threshold(state, outlier_threshold)

    data = TimeSeriesPlotData(
        mode_label="absolute" if value_mode == "absolute" else "% of mean",
        metric_label=metric_col,
        compare=compare,
    )
    order = ordered_source_ids(state)

    x_label = "Time (s)"
    if agg_mode == "pedal_stroke":
        x_label = "Pedal stroke #"
    elif agg_mode == "roll_360deg":
        x_label = "Record #"
    data.x_label = x_label

    baseline_series = None
    baseline_label = ""
    if compare:
        if not baseline_id or baseline_id not in state.loaded:
            raise ValueError("Baseline dataset is required for comparison.")
        baseline_label = state.id_to_display.get(baseline_id, baseline_id)
        data.baseline_label = baseline_label
        if agg_mode == "pedal_stroke":
            _, b_vals = _series_pedal_stroke(
                state.loaded[baseline_id], metric_col, sentinels, outlier_threshold
            )
            baseline_series = _apply_value_mode(b_vals, value_mode)
        elif agg_mode == "roll_360deg":
            _, b_vals = _series_roll_360(
                state.loaded[baseline_id], metric_col, sentinels, outlier_threshold
            )
            baseline_series = _apply_value_mode(b_vals, value_mode)
        else:
            vals = sanitize_numeric(state.loaded[baseline_id][metric_col], sentinels)
            if outlier_threshold is not None:
                vals = filter_outliers_mad(vals, outlier_threshold)
            baseline_series = _apply_value_mode(vals.to_numpy(dtype=float), value_mode)

    for sid in order:
        if not state.show_flag.get(sid, True):
            continue
        if compare and sid == baseline_id:
            continue
        label = state.id_to_display.get(sid, sid)
        try:
            if agg_mode == "pedal_stroke":
                t, vals = _series_pedal_stroke(
                    state.loaded[sid], metric_col, sentinels, outlier_threshold
                )
                val2 = _apply_value_mode(vals, value_mode)
            elif agg_mode == "roll_360deg":
                t, vals = _series_roll_360(
                    state.loaded[sid], metric_col, sentinels, outlier_threshold
                )
                val2 = _apply_value_mode(vals, value_mode)
            else:
                vals = sanitize_numeric(state.loaded[sid][metric_col], sentinels)
                if outlier_threshold is not None:
                    vals = filter_outliers_mad(vals, outlier_threshold)
                val2 = _apply_value_mode(vals.to_numpy(dtype=float), value_mode)
                t = np.arange(len(val2), dtype=float) / 100.0

            if compare:
                if baseline_series is None:
                    raise ValueError("Baseline data missing.")
                min_len = min(len(val2), len(baseline_series))
                if min_len == 0:
                    raise ValueError("No valid values after filtering.")
                y = val2[:min_len] - baseline_series[:min_len]
                t = t[:min_len]
            else:
                y = val2

            m = np.isfinite(t) & np.isfinite(y)
            t = t[m]
            y = y[m]
            if len(t) == 0:
                raise ValueError("No valid values after filtering.")
            data.traces.append(PlotTrace(label=label, x=t, y=y, source_id=sid))
            if len(t):
                data.max_x = max(data.max_x, float(np.nanmax(t)))
        except Exception as exc:
            data.errors.append(f"{label}: {exc}")

    return data
