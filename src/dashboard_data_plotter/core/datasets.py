from __future__ import annotations

from typing import Iterable, Optional

import pandas as pd

from dashboard_data_plotter.core.state import ProjectState
from dashboard_data_plotter.data.loaders import make_unique_name


def ensure_dataset_order(state: ProjectState) -> None:
    if not state.dataset_order and state.loaded:
        state.dataset_order = list(state.loaded.keys())


def ordered_source_ids(state: ProjectState) -> list[str]:
    ensure_dataset_order(state)
    return [sid for sid in state.dataset_order if sid in state.loaded]


def add_dataset(state: ProjectState, source_id: str, display_name: str, df: pd.DataFrame) -> str:
    if not source_id:
        raise ValueError("source_id is required.")
    display_name = str(display_name).strip() or "Dataset"
    existing = set(state.display_to_id.keys())
    if display_name in existing and state.display_to_id.get(display_name) != source_id:
        display_name = make_unique_name(display_name, existing)

    if source_id in state.loaded:
        raise ValueError(f"Dataset already loaded: {source_id}")

    state.loaded[source_id] = df
    state.id_to_display[source_id] = display_name
    state.display_to_id[display_name] = source_id
    state.show_flag[source_id] = True
    if source_id not in state.dataset_order:
        state.dataset_order.append(source_id)
    return display_name


def remove_dataset(state: ProjectState, source_id: str) -> None:
    if source_id not in state.loaded:
        return
    display = state.id_to_display.pop(source_id, None)
    if display is not None and state.display_to_id.get(display) == source_id:
        state.display_to_id.pop(display, None)
    state.loaded.pop(source_id, None)
    state.binned.pop(source_id, None)
    state.show_flag.pop(source_id, None)
    if source_id in state.dataset_order:
        state.dataset_order.remove(source_id)
    if state.plot_settings.baseline_source_id == source_id:
        state.plot_settings.baseline_source_id = ""
    if source_id in state.plot_settings.baseline_source_ids:
        state.plot_settings.baseline_source_ids = [
            sid for sid in state.plot_settings.baseline_source_ids if sid != source_id
        ]
        if state.plot_settings.baseline_source_id not in state.plot_settings.baseline_source_ids:
            state.plot_settings.baseline_source_id = (
                state.plot_settings.baseline_source_ids[0]
                if state.plot_settings.baseline_source_ids
                else ""
            )


def rename_dataset(state: ProjectState, source_id: str, new_name: str) -> str:
    if source_id not in state.loaded:
        raise KeyError(f"Unknown dataset: {source_id}")
    new_name = str(new_name).strip()
    if not new_name:
        raise ValueError("New name cannot be blank.")
    if new_name in state.display_to_id and state.display_to_id[new_name] != source_id:
        new_name = make_unique_name(new_name, set(state.display_to_id.keys()))
    old = state.id_to_display.get(source_id, source_id)
    state.id_to_display[source_id] = new_name
    if old in state.display_to_id and state.display_to_id[old] == source_id:
        state.display_to_id.pop(old, None)
    state.display_to_id[new_name] = source_id
    return new_name


def set_show_flag(state: ProjectState, source_id: str, show: bool) -> None:
    if source_id not in state.loaded:
        raise KeyError(f"Unknown dataset: {source_id}")
    state.show_flag[source_id] = bool(show)


def toggle_show_flag(state: ProjectState, source_id: str) -> bool:
    if source_id not in state.loaded:
        raise KeyError(f"Unknown dataset: {source_id}")
    new_state = not bool(state.show_flag.get(source_id, True))
    state.show_flag[source_id] = new_state
    return new_state


def set_all_show_flags(state: ProjectState, show: bool, source_ids: Optional[Iterable[str]] = None) -> None:
    ids = list(source_ids) if source_ids is not None else ordered_source_ids(state)
    for sid in ids:
        if sid in state.loaded:
            state.show_flag[sid] = bool(show)


def reorder_datasets(state: ProjectState, new_order: Iterable[str]) -> None:
    new_list = [sid for sid in new_order if sid in state.loaded]
    existing = set(state.loaded.keys())
    if set(new_list) != existing:
        missing = existing - set(new_list)
        extras = set(new_list) - existing
        if missing or extras:
            raise ValueError("New order must include all loaded datasets exactly once.")
    state.dataset_order = new_list


def move_dataset(state: ProjectState, source_id: str, offset: int) -> None:
    ensure_dataset_order(state)
    if source_id not in state.dataset_order:
        return
    idx = state.dataset_order.index(source_id)
    new_idx = max(0, min(len(state.dataset_order) - 1, idx + offset))
    if new_idx == idx:
        return
    state.dataset_order.pop(idx)
    state.dataset_order.insert(new_idx, source_id)
