import json
import os
from typing import Any, Dict, List, Tuple

import numpy as np
import pandas as pd

DEFAULT_SENTINELS = "9999"  # invalid values used in dataset


def load_json_file_obj(path: str) -> Any:
    """Load JSON from disk and return the parsed Python object."""
    with open(path, "r", encoding="utf-8") as f:
        text = f.read().strip()
    return json.loads(text)


def parse_sentinels(s: str) -> List[float]:
    vals: List[float] = []
    for part in str(s).split(","):
        part = part.strip()
        if not part:
            continue
        try:
            vals.append(float(part))
        except ValueError:
            pass
    return vals


def extract_named_datasets(obj: Any) -> List[Tuple[str, List[Dict[str, Any]]]]:
    """
    Accepts:
      A) { "Name": { "rideData": [ ... ] }, ... }      (pasted format)
      B) { "Name": [ ...records... ], ... }           (fallback)
      C) { "rideData": [ ... ] }                      (single dataset wrapper)
      D) [ ...records... ]                            (single unnamed dataset)

    Returns: list of (name, records_list)
    """
    if isinstance(obj, dict):
        if "rideData" in obj and isinstance(obj["rideData"], list):
            return [("Dataset", obj["rideData"])]

        out: List[Tuple[str, List[Dict[str, Any]]]] = []
        for name, v in obj.items():
            if isinstance(v, dict) and "rideData" in v and isinstance(v["rideData"], list):
                out.append((str(name), v["rideData"]))
            elif isinstance(v, list):
                out.append((str(name), v))
        if out:
            return out

    if isinstance(obj, list):
        return [("Dataset", obj)]

    raise ValueError("Unrecognized JSON structure.")


def extract_named_binned_datasets(obj: Any) -> List[Tuple[str, List[Dict[str, Any]]]]:
    """
    Extract left_pedalstroke_avg records for each dataset name (if present).

    Returns: list of (name, records_list)
    """
    if isinstance(obj, dict):
        if "left_pedalstroke_avg" in obj and isinstance(obj["left_pedalstroke_avg"], list):
            return [("Dataset", obj["left_pedalstroke_avg"])]

        out: List[Tuple[str, List[Dict[str, Any]]]] = []
        for name, v in obj.items():
            if isinstance(v, dict) and "left_pedalstroke_avg" in v and isinstance(
                v["left_pedalstroke_avg"], list
            ):
                out.append((str(name), v["left_pedalstroke_avg"]))
        return out

    return []


def load_json_file_datasets(path: str) -> List[Tuple[str, pd.DataFrame]]:
    """
    Load a JSON file that may contain either:
      A) list-of-records: [ {..}, {..}, ... ]
      B) multi-dataset object: { "Name": {"rideData": [..]}, ... }
      C) dict name->records list: { "Name": [..], ... }
      D) single wrapper: {"rideData": [..]}

    Returns: list of (dataset_name, dataframe)
    """
    obj = load_json_file_obj(path)
    datasets = extract_named_datasets(obj)

    out: List[Tuple[str, pd.DataFrame]] = []
    for name, records in datasets:
        if not isinstance(records, list) or (len(records) > 0 and not isinstance(records[0], dict)):
            continue
        df = pd.DataFrame(records)
        for c in df.columns:
            df[c] = pd.to_numeric(df[c], errors="coerce")
        out.append((str(name), df))

    if not out:
        raise ValueError("No valid datasets found in JSON file.")
    return out


def df_to_jsonable_records(df: pd.DataFrame) -> List[Dict[str, Any]]:
    """Convert DataFrame to JSON-safe list-of-dicts (np types -> Python, NaN -> None)."""
    df2 = df.where(pd.notna(df), None)
    out: List[Dict[str, Any]] = []
    for rec in df2.to_dict(orient="records"):
        clean: Dict[str, Any] = {}
        for k, v in rec.items():
            if isinstance(v, np.generic):
                v = v.item()
            clean[k] = v
        out.append(clean)
    return out


def make_unique_name(name: str, existing_names: set) -> str:
    base = str(name).strip() if str(name).strip() else "Dataset"
    if base not in existing_names:
        return base
    i = 2
    while f"{base} ({i})" in existing_names:
        i += 1
    return f"{base} ({i})"


def sanitize_numeric(series: pd.Series, sentinels: List[float]) -> pd.Series:
    x = pd.to_numeric(series, errors="coerce")
    for v in sentinels:
        x = x.mask(x == v)
    return x


def wrap_angle_deg(a: pd.Series, convert_br_to_standard: bool) -> pd.Series:
    """
    Convert BR crank-angle convention to Standard if requested.

    Mapping:
      BR  90 = Standard   0
      BR   0 = Standard  90
      BR 270 = Standard 180
      BR 180 = Standard 270

    Formula:
      theta_std = (90 - theta_br) mod 360
    """
    a = pd.to_numeric(a, errors="coerce")
    if convert_br_to_standard:
        a = 90.0 - a
    return np.mod(a, 360.0)


def _trimmed_mean(values: pd.Series, trim_fraction: float = 0.10) -> float:
    arr = pd.to_numeric(values, errors="coerce").to_numpy(dtype=float)
    arr = arr[np.isfinite(arr)]
    if arr.size == 0:
        return float("nan")
    arr.sort()
    trim = int(np.floor(arr.size * trim_fraction))
    if trim * 2 >= arr.size:
        return float(np.nanmean(arr))
    return float(np.nanmean(arr[trim:arr.size - trim]))


def normalize_outlier_method(method: str | None) -> str:
    raw = str(method or "").strip().lower()
    if raw in ("phase-mad", "phase_mad", "phase mad", "phase"):
        return "phase_mad"
    if raw in ("hampel", "hampel filter"):
        return "hampel"
    if raw in ("impulse", "impulse filter", "accel", "acceleration", "jerk"):
        return "impulse"
    return "mad"


def filter_outliers_mad(series: pd.Series, threshold: float) -> pd.Series:
    x = pd.to_numeric(series, errors="coerce")
    median = float(np.nanmedian(x))
    mad = float(np.nanmedian(np.abs(x - median)))
    if not np.isfinite(mad) or mad == 0.0:
        return x
    z = 0.6745 * (x - median) / mad
    return x.mask(np.abs(z) > threshold)


def filter_outliers_phase_mad(
    angle_series: pd.Series,
    value_series: pd.Series,
    threshold: float,
    bin_count: int = 52,
) -> pd.Series:
    ang = pd.to_numeric(angle_series, errors="coerce")
    val = pd.to_numeric(value_series, errors="coerce")
    if bin_count <= 0:
        return val
    bin_w = 360.0 / float(bin_count)
    angle_bin = (np.round(ang / bin_w) * bin_w) % 360.0
    df = pd.DataFrame({"angle_bin": angle_bin, "value": val})

    def _mask_group(group: pd.DataFrame) -> pd.Series:
        x = group["value"]
        median = float(np.nanmedian(x))
        mad = float(np.nanmedian(np.abs(x - median)))
        if not np.isfinite(mad) or mad == 0.0:
            return pd.Series(False, index=group.index)
        z = 0.6745 * (x - median) / mad
        return np.abs(z) > threshold

    mask = df.groupby("angle_bin", dropna=False,
                      group_keys=False).apply(_mask_group)
    mask = mask.reindex(df.index, fill_value=False)
    return val.mask(mask)


def filter_outliers_hampel(
    series: pd.Series,
    threshold: float,
    window: int = 11,
) -> pd.Series:
    x = pd.to_numeric(series, errors="coerce")
    if window < 3:
        return x
    if window % 2 == 0:
        window += 1
    rolling_median = x.rolling(
        window=window, center=True, min_periods=1).median()
    diff = (x - rolling_median).abs()
    rolling_mad = diff.rolling(
        window=window, center=True, min_periods=1).median()
    with np.errstate(divide="ignore", invalid="ignore"):
        z = 0.6745 * diff / rolling_mad
    mask = (rolling_mad > 0) & np.isfinite(z) & (z > threshold)
    return x.mask(mask)


def filter_outliers_impulse(series: pd.Series, threshold: float) -> pd.Series:
    x = pd.to_numeric(series, errors="coerce")
    accel = x.diff().diff()
    accel_median = float(np.nanmedian(accel))
    mad = float(np.nanmedian(np.abs(accel - accel_median)))
    if not np.isfinite(mad) or mad == 0.0:
        return x
    scale = 1.4826 * mad
    upper = accel_median + threshold * scale
    lower = accel_median - threshold * scale
    mask = (accel > upper) | (accel < lower)
    mask = mask & ~mask.shift(1).fillna(False)
    return x.mask(mask)


def apply_outlier_filter(
    series: pd.Series,
    *,
    threshold: float | None,
    method: str | None = None,
    angle_series: pd.Series | None = None,
    angle_bin_count: int = 52,
) -> pd.Series:
    if threshold is None:
        return pd.to_numeric(series, errors="coerce")
    method_key = normalize_outlier_method(method)
    if method_key == "phase_mad" and angle_series is not None:
        return filter_outliers_phase_mad(angle_series, series, threshold, bin_count=angle_bin_count)
    if method_key == "hampel":
        return filter_outliers_hampel(series, threshold)
    if method_key == "impulse":
        return filter_outliers_impulse(series, threshold)
    return filter_outliers_mad(series, threshold)


def aggregate_metric(
    series: pd.Series,
    sentinels: List[float],
    agg: str = "mean",
    outlier_threshold: float | None = None,
    outlier_method: str | None = None,
) -> float:
    values = sanitize_numeric(series, sentinels)
    values = apply_outlier_filter(
        values, threshold=outlier_threshold, method=outlier_method)
    agg_key = str(agg).lower()
    if agg_key == "median":
        return float(np.nanmedian(values.to_numpy(dtype=float)))
    if agg_key == "trimmed_mean_10":
        return float(_trimmed_mean(values, 0.10))
    return float(np.nanmean(values.to_numpy(dtype=float)))


def prepare_angle_value_agg(
    df: pd.DataFrame,
    angle_col: str,
    metric_col: str,
    sentinels: List[float],
    agg: str = "mean",
    outlier_threshold: float | None = None,
    outlier_method: str | None = None,
):
    """
    Returns:
        ang_deg (np.ndarray): sorted unique angles [0..360)
        val (np.ndarray): aggregated metric at each angle (duplicates combined)
    """
    if angle_col not in df.columns:
        raise KeyError(f"Angle column '{angle_col}' not found.")
    if metric_col not in df.columns:
        raise KeyError(f"Metric column '{metric_col}' not found.")

    convert_br = angle_col in ("leftPedalCrankAngle", "rightPedalCrankAngle")
    ang = wrap_angle_deg(
        sanitize_numeric(df[angle_col], sentinels),
        convert_br_to_standard=convert_br,
    )
    val = sanitize_numeric(df[metric_col], sentinels)
    val = apply_outlier_filter(
        val,
        threshold=outlier_threshold,
        method=outlier_method,
        angle_series=ang if normalize_outlier_method(
            outlier_method) == "phase_mad" else None,
        angle_bin_count=52,
    )

    plot_df = pd.DataFrame({"angle_deg": ang, "value": val}).dropna()

    # enforce 52-bin quantization to avoid float noise / extra points
    BIN_COUNT = 52
    BIN_W = 360.0 / BIN_COUNT
    plot_df["angle_bin"] = (
        np.round(plot_df["angle_deg"] / BIN_W) * BIN_W) % 360.0

    agg_key = str(agg).lower()
    if agg_key == "median":
        agg_func = "median"
    elif agg_key == "trimmed_mean_10":
        def agg_func(s): return _trimmed_mean(s, 0.10)
    else:
        agg_func = "mean"
    plot_df = (
        plot_df.groupby("angle_bin", as_index=False)["value"]
        .agg(agg_func)
        .rename(columns={"angle_bin": "angle_deg"})
        .sort_values("angle_deg")
    )

    if plot_df.empty:
        raise ValueError("No valid rows after removing NaNs/sentinels.")

    return plot_df["angle_deg"].to_numpy(), plot_df["value"].to_numpy()


def prepare_angle_value(df: pd.DataFrame, angle_col: str, metric_col: str, sentinels: List[float]):
    """
    Returns:
        ang_deg (np.ndarray): sorted unique angles [0..360)
        val (np.ndarray): mean metric at each angle (averages duplicates)
    """
    return prepare_angle_value_agg(df, angle_col, metric_col, sentinels, agg="mean")
