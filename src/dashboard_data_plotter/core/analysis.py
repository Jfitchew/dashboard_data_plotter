from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
import pandas as pd

from dashboard_data_plotter.data.loaders import (
    apply_outlier_filter,
    normalize_outlier_method,
    sanitize_numeric,
    wrap_angle_deg,
)
from dashboard_data_plotter.plotting.helpers import to_percent_of_mean


@dataclass
class AnalysisSettings:
    """Configuration for analysis and reporting workflows."""

    stats_mode: str = ""
    report_options: dict[str, str] = field(default_factory=dict)


@dataclass
class PairwiseStat:
    dataset_a: str
    dataset_b: str
    n: int
    correlation: float
    p_value: float
    mean_delta: float


@dataclass
class AngleRangeStat:
    range_label: str
    start_deg: float
    end_deg: float
    pairwise: list[PairwiseStat] = field(default_factory=list)


@dataclass
class PlotStatsResult:
    mode: str
    value_mode_label: str
    metric_label: str
    agg_label: str
    angle_ranges: list[AngleRangeStat] = field(default_factory=list)
    pairwise: list[PairwiseStat] = field(default_factory=list)


def _pearson_corr(x: np.ndarray, y: np.ndarray) -> float:
    if x.size < 2 or y.size < 2:
        return float("nan")
    x = np.asarray(x, dtype=float)
    y = np.asarray(y, dtype=float)
    xm = x - np.nanmean(x)
    ym = y - np.nanmean(y)
    denom = np.sqrt(np.nansum(xm * xm) * np.nansum(ym * ym))
    if not np.isfinite(denom) or denom <= 0:
        return float("nan")
    return float(np.nansum(xm * ym) / denom)


def _permutation_p_value(x: np.ndarray, y: np.ndarray, rng: np.random.Generator, permutations: int = 400) -> float:
    if x.size < 4 or y.size < 4:
        return 1.0
    obs = _pearson_corr(x, y)
    if not np.isfinite(obs):
        return 1.0
    abs_obs = abs(obs)
    hits = 0
    y_copy = np.array(y, dtype=float)
    for _ in range(permutations):
        rng.shuffle(y_copy)
        r = _pearson_corr(x, y_copy)
        if np.isfinite(r) and abs(r) >= abs_obs:
            hits += 1
    return float((hits + 1) / (permutations + 1))


def _pairwise_stats(label_to_values: dict[str, np.ndarray], rng: np.random.Generator) -> list[PairwiseStat]:
    labels = list(label_to_values.keys())
    out: list[PairwiseStat] = []
    for i in range(len(labels)):
        for j in range(i + 1, len(labels)):
            a = labels[i]
            b = labels[j]
            xa = np.asarray(label_to_values[a], dtype=float)
            xb = np.asarray(label_to_values[b], dtype=float)
            n = min(len(xa), len(xb))
            if n < 2:
                out.append(PairwiseStat(a, b, n, float("nan"), 1.0, float("nan")))
                continue
            va = xa[:n]
            vb = xb[:n]
            m = np.isfinite(va) & np.isfinite(vb)
            va = va[m]
            vb = vb[m]
            n_eff = int(va.size)
            if n_eff < 2:
                out.append(PairwiseStat(a, b, n_eff, float("nan"), 1.0, float("nan")))
                continue
            corr = _pearson_corr(va, vb)
            pval = _permutation_p_value(va, vb, rng)
            mean_delta = float(np.nanmean(va - vb)) if n_eff else float("nan")
            out.append(PairwiseStat(a, b, n_eff, corr, pval, mean_delta))
    return out


def build_angle_group_stats(
    *,
    traces: list[tuple[str, np.ndarray, np.ndarray]],
    group_size: int = 4,
    n_bins: int = 52,
    metric_label: str,
    agg_label: str,
    value_mode_label: str,
) -> PlotStatsResult:
    bins = np.linspace(0.0, 360.0, n_bins, endpoint=False)
    groups = []
    for start in range(0, n_bins, group_size):
        end_excl = min(start + group_size, n_bins)
        start_deg = float(bins[start])
        end_deg = float((end_excl) * (360.0 / n_bins))
        groups.append((start, end_excl, start_deg, end_deg))

    rng = np.random.default_rng(42)
    result = PlotStatsResult(
        mode="angle_grouped",
        value_mode_label=value_mode_label,
        metric_label=metric_label,
        agg_label=agg_label,
    )
    for start, end_excl, start_deg, end_deg in groups:
        by_label: dict[str, np.ndarray] = {}
        for label, ang, val in traces:
            ang = np.asarray(ang, dtype=float)
            val = np.asarray(val, dtype=float)
            m = np.isfinite(ang) & np.isfinite(val)
            ang = ang[m]
            val = val[m]
            if ang.size == 0:
                continue
            idx = np.floor((ang % 360.0) / (360.0 / n_bins)).astype(int)
            idx = np.clip(idx, 0, n_bins - 1)
            take = (idx >= start) & (idx < end_excl)
            if np.any(take):
                by_label[label] = val[take]
        pairwise = _pairwise_stats(by_label, rng)
        result.angle_ranges.append(
            AngleRangeStat(
                range_label=f"{start_deg:.1f}°–{end_deg:.1f}°",
                start_deg=start_deg,
                end_deg=end_deg,
                pairwise=pairwise,
            )
        )
    return result


def rolling_360_medians_for_bar(
    df: pd.DataFrame,
    *,
    metric_col: str,
    sentinels: list[float],
    outlier_threshold: float | None,
    outlier_method: str | None,
) -> np.ndarray:
    if "leftPedalCrankAngle" not in df.columns or metric_col not in df.columns:
        return np.asarray([], dtype=float)
    angle_series = wrap_angle_deg(
        sanitize_numeric(df["leftPedalCrankAngle"], sentinels),
        convert_br_to_standard=True,
    )
    ang = angle_series.to_numpy(dtype=float)
    vals = sanitize_numeric(df[metric_col], sentinels)
    vals = apply_outlier_filter(
        vals,
        threshold=outlier_threshold,
        method=outlier_method,
        angle_series=angle_series if normalize_outlier_method(outlier_method) == "phase_mad" else None,
    )
    vals = vals.to_numpy(dtype=float)
    m = np.isfinite(ang) & np.isfinite(vals)
    ang = ang[m]
    vals = vals[m]
    if ang.size == 0:
        return np.asarray([], dtype=float)

    unwrapped = np.rad2deg(np.unwrap(np.deg2rad(ang), discont=np.deg2rad(180.0)))

    meds = []
    direction = float(np.nanmedian(np.diff(unwrapped))) if len(unwrapped) > 1 else 1.0
    for i in range(len(vals)):
        if direction < 0:
            target = unwrapped[i] - 360.0
            j = i + 1
            while j < len(vals) and unwrapped[j] > target:
                j += 1
        else:
            target = unwrapped[i] + 360.0
            j = i + 1
            while j < len(vals) and unwrapped[j] < target:
                j += 1
        if j >= len(vals):
            break
        w = vals[i:j + 1]
        meds.append(float(np.nanmedian(w)))
    return np.asarray(meds, dtype=float)


def build_bar_stats(
    *,
    series_by_label: dict[str, np.ndarray],
    metric_label: str,
    agg_label: str,
) -> PlotStatsResult:
    transformed: dict[str, np.ndarray] = {}
    for label, values in series_by_label.items():
        arr = np.asarray(values, dtype=float)
        arr = arr[np.isfinite(arr)]
        transformed[label] = arr
    rng = np.random.default_rng(42)
    pairwise = _pairwise_stats(transformed, rng)
    return PlotStatsResult(
        mode="bar_rolling360",
        value_mode_label="absolute",
        metric_label=metric_label,
        agg_label=agg_label,
        pairwise=pairwise,
    )


def maybe_to_percent(values: np.ndarray, enabled: bool) -> np.ndarray:
    if not enabled:
        return np.asarray(values, dtype=float)
    return np.asarray(to_percent_of_mean(values), dtype=float)
