import numpy as np
from matplotlib.ticker import FuncFormatter

def choose_decimals_from_ticks(ticks, max_decimals=4) -> int:
    ticks = np.asarray(ticks, dtype=float)
    ticks = np.unique(ticks[np.isfinite(ticks)])
    if ticks.size < 2:
        return 0

    diffs = np.diff(np.sort(ticks))
    diffs = diffs[diffs > 1e-12]
    if diffs.size == 0:
        return 0

    step = float(np.min(diffs))
    decimals = int(np.ceil(-np.log10(step)))
    decimals = max(0, min(decimals, max_decimals))
    return decimals


def to_percent_of_mean(values: np.ndarray) -> np.ndarray:
    v = np.asarray(values, dtype=float)
    mu = np.nanmean(v)
    if not np.isfinite(mu) or abs(mu) < 1e-12:
        raise ValueError("Mean is zero/invalid; cannot compute % of mean.")
    return 100.0 * v / mu


def circular_interp_baseline(b_ang_deg: np.ndarray, b_val: np.ndarray, q_ang_deg: np.ndarray) -> np.ndarray:
    """Interpolate baseline values at query angles with circular wrap."""
    if len(b_ang_deg) < 2:
        return np.full_like(q_ang_deg, b_val[0], dtype=float)

    order = np.argsort(b_ang_deg)
    b_ang = b_ang_deg[order].astype(float)
    b_v = b_val[order].astype(float)

    b_ang_ext = np.concatenate([b_ang - 360.0, b_ang, b_ang + 360.0])
    b_v_ext = np.concatenate([b_v, b_v, b_v])

    q = (q_ang_deg % 360.0).astype(float)
    return np.interp(q, b_ang_ext, b_v_ext)


def fmt_abs_ticks(ax):
    decimals = choose_decimals_from_ticks(ax.get_yticks())
    ax.yaxis.set_major_formatter(FuncFormatter(lambda r, pos: f"{r:.{decimals}f}"))


def fmt_delta_ticks(ax, offset: float):
    ticks = ax.get_yticks()
    decimals = choose_decimals_from_ticks(ticks)
    ax.yaxis.set_major_formatter(FuncFormatter(lambda r, pos: f"{(r - offset):.{decimals}f}"))
