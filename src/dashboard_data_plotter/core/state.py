from __future__ import annotations

from dataclasses import dataclass, field
from typing import Iterable, Optional

import pandas as pd

from dashboard_data_plotter.core.analysis import AnalysisSettings
from dashboard_data_plotter.core.cleaning import CleaningSettings


@dataclass
class PlotSettings:
    plot_type: str = "radar"
    angle_column: str = "leftPedalCrankAngle"
    metric_column: str = ""
    agg_mode: str = "mean"
    value_mode: str = "absolute"
    compare: bool = False
    baseline_source_id: str = ""
    close_loop: bool = True
    use_plotly: bool = False
    radar_background: bool = True
    range_low: str = ""
    range_high: str = ""
    range_fixed: bool = False


@dataclass
class ProjectState:
    """Shared, UI-agnostic project state for loaded datasets and settings."""

    loaded: dict[str, pd.DataFrame] = field(default_factory=dict)
    id_to_display: dict[str, str] = field(default_factory=dict)
    display_to_id: dict[str, str] = field(default_factory=dict)
    show_flag: dict[str, bool] = field(default_factory=dict)
    dataset_order: list[str] = field(default_factory=list)
    plot_settings: PlotSettings = field(default_factory=PlotSettings)
    cleaning_settings: CleaningSettings = field(default_factory=CleaningSettings)
    analysis_settings: AnalysisSettings = field(default_factory=AnalysisSettings)

    def clear(self) -> None:
        self.loaded.clear()
        self.id_to_display.clear()
        self.display_to_id.clear()
        self.show_flag.clear()
        self.dataset_order.clear()
        self.plot_settings = PlotSettings()
        self.cleaning_settings = CleaningSettings()
        self.analysis_settings = AnalysisSettings()


def set_plot_type(state: ProjectState, plot_type: str) -> None:
    state.plot_settings.plot_type = str(plot_type)


def set_metric(state: ProjectState, metric: str) -> None:
    state.plot_settings.metric_column = str(metric)


def set_angle(state: ProjectState, angle: str) -> None:
    state.plot_settings.angle_column = str(angle)


def set_agg_mode(state: ProjectState, agg_mode: str) -> None:
    state.plot_settings.agg_mode = str(agg_mode)


def set_value_mode(state: ProjectState, value_mode: str) -> None:
    state.plot_settings.value_mode = str(value_mode)


def set_compare(state: ProjectState, compare: bool) -> None:
    state.plot_settings.compare = bool(compare)


def set_baseline(state: ProjectState, baseline_source_id: str) -> None:
    state.plot_settings.baseline_source_id = str(baseline_source_id)


def update_cleaning_settings(
    state: ProjectState,
    sentinels: Iterable[float],
    remove_outliers: bool,
    outlier_threshold: Optional[float],
    outlier_method: str,
) -> None:
    state.cleaning_settings.sentinels = list(sentinels)
    state.cleaning_settings.remove_outliers = bool(remove_outliers)
    state.cleaning_settings.outlier_threshold = outlier_threshold
    state.cleaning_settings.outlier_method = str(outlier_method or "impulse")
