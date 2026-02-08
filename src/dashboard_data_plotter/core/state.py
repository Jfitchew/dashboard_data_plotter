from __future__ import annotations

from dataclasses import dataclass, field

import pandas as pd


@dataclass
class ProjectState:
    """Shared, UI-agnostic project state for loaded datasets."""

    loaded: dict[str, pd.DataFrame] = field(default_factory=dict)
    id_to_display: dict[str, str] = field(default_factory=dict)
    display_to_id: dict[str, str] = field(default_factory=dict)
    show_flag: dict[str, bool] = field(default_factory=dict)

    def clear(self) -> None:
        self.loaded.clear()
        self.id_to_display.clear()
        self.display_to_id.clear()
        self.show_flag.clear()
