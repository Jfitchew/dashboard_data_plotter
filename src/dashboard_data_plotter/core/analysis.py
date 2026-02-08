from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class AnalysisSettings:
    """Configuration for analysis and reporting workflows.

    TODO: Move analysis/report logic here as workflows are implemented.
    """

    stats_mode: str = ""
    report_options: dict[str, str] = field(default_factory=dict)
