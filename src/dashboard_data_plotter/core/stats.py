from __future__ import annotations

from dataclasses import dataclass, field
from itertools import combinations
import math
from typing import Iterable, Optional

import numpy as np
import pandas as pd

from dashboard_data_plotter.core.datasets import ordered_source_ids
from dashboard_data_plotter.core.state import ProjectState
from dashboard_data_plotter.data.loaders import (
    aggregate_metric,
    apply_outlier_filter,
    normalize_outlier_method,
    prepare_angle_value_agg,
    sanitize_numeric,
    wrap_angle_deg,
)
from dashboard_data_plotter.plotting.helpers import to_percent_of_mean


@dataclass
class PairwiseStat:
    dataset_a: str
    dataset_b: str
    n: int
    corr_r: float
    p_value: float
    summary: str


@dataclass
class AngleRangeStat:
    index: int
    start_deg: float
    end_deg: float
    pairs: list[PairwiseStat] = field(default_factory=list)


@dataclass
class RadarCartesianStats:
    ranges: list[AngleRangeStat] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)


@dataclass
class BarWhisker:
    source_id: str
    label: str
    center: float
    low: float
    high: float
    has_whisker: bool


@dataclass
class BarStats:
    whiskers: list[BarWhisker] = field(default_factory=list)
    pairs: list[PairwiseStat] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)


def _get_plot_df(state: ProjectState, source_id: str, use_original_binned: bool) -> pd.DataFrame:
    if use_original_binned:
        binned = state.binned.get(source_id)
        if binned is not None and not binned.empty:
            return binned
    return state.loaded[source_id]


def _resolve_sentinels(state: ProjectState, sentinels: Optional[Iterable[float]]) -> list[float]:
    if sentinels is not None:
        return list(sentinels)
    return list(state.cleaning_settings.sentinels)


def _resolve_outlier_threshold(state: ProjectState, outlier_threshold: Optional[float]) -> Optional[float]:
    if outlier_threshold is not None:
        return outlier_threshold
    if state.cleaning_settings.remove_outliers:
        return state.cleaning_settings.outlier_threshold
    return None


def _resolve_outlier_method(state: ProjectState, outlier_method: Optional[str]) -> str:
    if outlier_method is not None:
        return normalize_outlier_method(outlier_method)
    return normalize_outlier_method(state.cleaning_settings.outlier_method)


def _fisher_corr_p_value(r: float, n: int) -> float:
    if n < 4 or not np.isfinite(r):
        return float("nan")
    rr = float(np.clip(r, -0.999999, 0.999999))
    z = math.atanh(rr) * math.sqrt(max(n - 3, 1))
    # two-sided normal approximation
    return float(math.erfc(abs(z) / math.sqrt(2.0)))


def _corr_stats(x: np.ndarray, y: np.ndarray) -> tuple[int, float, float, str]:
    mask = np.isfinite(x) & np.isfinite(y)
    xx = x[mask]
    yy = y[mask]
    n = int(xx.size)
    if n < 3:
        return n, float("nan"), float("nan"), "insufficient samples"
    sx = float(np.nanstd(xx))
    sy = float(np.nanstd(yy))
    if sx == 0.0 or sy == 0.0:
        return n, float("nan"), float("nan"), "zero spread"
    r = float(np.corrcoef(xx, yy)[0, 1])
    p = _fisher_corr_p_value(r, n)
    if not np.isfinite(p):
        summary = "insufficient samples"
    elif p < 0.05:
        summary = "significant"
    else:
        summary = "not significant"
    return n, r, p, summary


def compute_radar_cartesian_stats(
    state: ProjectState,
    *,
    angle_col: str,
    metric_col: str,
    agg_mode: str,
    value_mode: str,
    sentinels: Optional[Iterable[float]] = None,
    outlier_threshold: Optional[float] = None,
    outlier_method: Optional[str] = None,
    use_original_binned: bool = False,
) -> RadarCartesianStats:
    sentinels = _resolve_sentinels(state, sentinels)
    outlier_threshold = _resolve_outlier_threshold(state, outlier_threshold)
    outlier_method = _resolve_outlier_method(state, outlier_method)

    result = RadarCartesianStats()
    per_dataset: dict[str, pd.Series] = {}
    labels: dict[str, str] = {}

    for sid in ordered_source_ids(state):
        if not state.show_flag.get(sid, True):
            continue
        labels[sid] = state.id_to_display.get(sid, sid)
        try:
            df = _get_plot_df(state, sid, use_original_binned)
            ang, val = prepare_angle_value_agg(
                df,
                angle_col,
                metric_col,
                sentinels,
                agg=agg_mode,
                outlier_threshold=outlier_threshold,
                outlier_method=outlier_method,
            )
            vals = np.asarray(val, dtype=float)
            if value_mode == "percent_mean":
                vals = to_percent_of_mean(vals)
            elif value_mode != "absolute":
                raise ValueError(f"Unsupported value mode '{value_mode}'.")
            bins = np.round(np.asarray(ang, dtype=float) * 1000.0) / 1000.0
            per_dataset[sid] = pd.Series(vals, index=bins)
        except Exception as exc:
            result.errors.append(f"{labels[sid]}: {exc}")

    if len(per_dataset) < 2:
        return result

    bin_count = 52
    bin_w = 360.0 / float(bin_count)
    for idx in range(13):
        start = idx * 4 * bin_w
        end = (idx * 4 + 4) * bin_w
        stat = AngleRangeStat(index=idx + 1, start_deg=start, end_deg=end)
        target_bins = [round(((idx * 4 + b) * bin_w) % 360.0, 3) for b in range(4)]
        for sid_a, sid_b in combinations(per_dataset.keys(), 2):
            sa = per_dataset[sid_a].reindex(target_bins)
            sb = per_dataset[sid_b].reindex(target_bins)
            n, r, p, summary = _corr_stats(sa.to_numpy(dtype=float), sb.to_numpy(dtype=float))
            stat.pairs.append(
                PairwiseStat(
                    dataset_a=labels[sid_a],
                    dataset_b=labels[sid_b],
                    n=n,
                    corr_r=r,
                    p_value=p,
                    summary=summary,
                )
            )
        result.ranges.append(stat)
    return result


def _rolling_360_median_series(
    df: pd.DataFrame,
    metric_col: str,
    sentinels: list[float],
    outlier_threshold: Optional[float],
    outlier_method: str,
) -> np.ndarray:
    if "leftPedalCrankAngle" not in df.columns:
        raise KeyError("Angle column 'leftPedalCrankAngle' not found.")
    if metric_col not in df.columns:
        raise KeyError(f"Metric column '{metric_col}' not found.")

    ang_series = wrap_angle_deg(
        sanitize_numeric(df["leftPedalCrankAngle"], sentinels),
        convert_br_to_standard=True,
    )
    val = sanitize_numeric(df[metric_col], sentinels)
    val = apply_outlier_filter(
        val,
        threshold=outlier_threshold,
        method=outlier_method,
        angle_series=ang_series if normalize_outlier_method(outlier_method) == "phase_mad" else None,
    )
    ang = ang_series.to_numpy(dtype=float)
    vv = val.to_numpy(dtype=float)
    mask = np.isfinite(ang) & np.isfinite(vv)
    ang = ang[mask]
    vv = vv[mask]
    if ang.size == 0:
        raise ValueError("No valid values after filtering.")

    unwrapped = np.empty_like(ang, dtype=float)
    offset = 0.0
    unwrapped[0] = ang[0]
    for i in range(1, ang.size):
        if ang[i - 1] - ang[i] > 180.0:
            offset += 360.0
        unwrapped[i] = ang[i] + offset

    out: list[float] = []
    n = len(vv)
    for i in range(n):
        target = unwrapped[i] + 360.0
        j = i + 1
        while j < n and unwrapped[j] < target:
            j += 1
        if j >= n:
            break
        window = vv[i:j + 1]
        out.append(float(np.nanmedian(window)))
    arr = np.asarray(out, dtype=float)
    arr = arr[np.isfinite(arr)]
    if arr.size == 0:
        raise ValueError("No complete 360deg median windows after filtering.")
    return arr


def compute_bar_stats(
    state: ProjectState,
    *,
    metric_col: str,
    agg_mode: str,
    compare: bool,
    baseline_id: str,
    sentinels: Optional[Iterable[float]] = None,
    outlier_threshold: Optional[float] = None,
    outlier_method: Optional[str] = None,
    use_original_binned: bool = False,
) -> BarStats:
    sentinels = _resolve_sentinels(state, sentinels)
    outlier_threshold = _resolve_outlier_threshold(state, outlier_threshold)
    outlier_method = _resolve_outlier_method(state, outlier_method)

    result = BarStats()
    order = ordered_source_ids(state)

    absolute_centers: dict[str, float] = {}
    absolute_lohi: dict[str, tuple[float, float]] = {}
    roll_series: dict[str, np.ndarray] = {}

    baseline_center = 0.0
    if compare:
        if not baseline_id or baseline_id not in state.loaded:
            raise ValueError("Baseline dataset is required for comparison.")

    ordered_ids: list[str] = []
    for sid in order:
        if compare and sid == baseline_id:
            ordered_ids.append(sid)
        elif state.show_flag.get(sid, True):
            ordered_ids.append(sid)

    for sid in ordered_ids:
        label = state.id_to_display.get(sid, sid)
        try:
            df = _get_plot_df(state, sid, use_original_binned)
            center = aggregate_metric(
                df[metric_col],
                sentinels,
                agg=agg_mode,
                outlier_threshold=outlier_threshold,
                outlier_method=outlier_method,
            )
            series = _rolling_360_median_series(
                df,
                metric_col,
                sentinels,
                outlier_threshold,
                outlier_method,
            )
            q1 = float(np.nanpercentile(series, 25))
            q3 = float(np.nanpercentile(series, 75))
            absolute_centers[sid] = center
            absolute_lohi[sid] = (q1, q3)
            roll_series[sid] = series
        except Exception as exc:
            result.errors.append(f"{label}: {exc}")

    if compare and baseline_id in absolute_centers:
        baseline_center = absolute_centers[baseline_id]

    for sid in ordered_ids:
        if sid not in absolute_centers:
            continue
        label = state.id_to_display.get(sid, sid)
        center = absolute_centers[sid]
        low_abs, high_abs = absolute_lohi[sid]
        has_whisker = True
        if compare:
            if sid == baseline_id:
                result.whiskers.append(
                    BarWhisker(
                        source_id=sid,
                        label=label,
                        center=0.0,
                        low=0.0,
                        high=0.0,
                        has_whisker=False,
                    )
                )
                continue
            center = center - baseline_center
            low_abs = low_abs - baseline_center
            high_abs = high_abs - baseline_center
            has_whisker = True
        result.whiskers.append(
            BarWhisker(
                source_id=sid,
                label=label,
                center=center,
                low=low_abs,
                high=high_abs,
                has_whisker=has_whisker,
            )
        )

    valid_ids = [sid for sid in ordered_ids if sid in roll_series]
    if compare and baseline_id in roll_series:
        base = roll_series[baseline_id]
        for sid in valid_ids:
            if sid == baseline_id:
                continue
            series = roll_series[sid]
            n = min(len(series), len(base))
            if n <= 0:
                continue
            delta = series[:n] - base[:n]
            idx = np.arange(n, dtype=float)
            nn, r, p, summary = _corr_stats(idx, delta)
            result.pairs.append(
                PairwiseStat(
                    dataset_a=state.id_to_display.get(sid, sid),
                    dataset_b=state.id_to_display.get(baseline_id, baseline_id),
                    n=nn,
                    corr_r=r,
                    p_value=p,
                    summary=f"delta trend vs baseline: {summary}",
                )
            )
    else:
        for sid_a, sid_b in combinations(valid_ids, 2):
            sa = roll_series[sid_a]
            sb = roll_series[sid_b]
            n = min(len(sa), len(sb))
            if n <= 0:
                continue
            nn, r, p, summary = _corr_stats(sa[:n], sb[:n])
            result.pairs.append(
                PairwiseStat(
                    dataset_a=state.id_to_display.get(sid_a, sid_a),
                    dataset_b=state.id_to_display.get(sid_b, sid_b),
                    n=nn,
                    corr_r=r,
                    p_value=p,
                    summary=summary,
                )
            )

    return result
