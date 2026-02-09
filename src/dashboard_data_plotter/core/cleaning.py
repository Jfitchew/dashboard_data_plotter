from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional


@dataclass
class CleaningSettings:
    """Configuration for dataset cleaning and alignment steps.

    TODO: Move cleaning/alignment logic here as workflows are implemented.
    """

    sentinels: list[float] = field(default_factory=list)
    remove_outliers: bool = False
    outlier_threshold: Optional[float] = None
    outlier_method: str = "mad"
