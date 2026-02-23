from __future__ import annotations

from datetime import datetime
import json
import os
from typing import Any

REPORT_VERSION = 1


def _now_iso() -> str:
    return datetime.now().replace(microsecond=0).isoformat()


def report_assets_dir(report_path: str) -> str:
    base, _ = os.path.splitext(report_path)
    return f"{base}_assets"


def new_report_state(
    project_title: str,
    project_path: str,
    data_sources: list[dict[str, str]],
) -> dict[str, Any]:
    del project_path  # Reports are standalone and do not persist project references.
    now = _now_iso()
    title = f"{project_title} Report" if project_title else "Untitled Report"
    return {
        "version": REPORT_VERSION,
        "title": title,
        "created_at": now,
        "updated_at": now,
        "include_meta": False,
        "data_sources": list(data_sources),
        "snapshots": [],
    }


def touch_report(report: dict[str, Any]) -> None:
    report["updated_at"] = _now_iso()


def save_report(report: dict[str, Any], path: str) -> None:
    touch_report(report)
    payload = dict(report)
    payload.pop("project_title", None)
    payload.pop("project_path", None)
    with open(path, "w", encoding="utf-8") as handle:
        json.dump(payload, handle, indent=2)


def load_report(path: str) -> dict[str, Any]:
    with open(path, "r", encoding="utf-8") as handle:
        obj = json.load(handle)
    if not isinstance(obj, dict):
        return {}
    obj.pop("project_title", None)
    obj.pop("project_path", None)
    return obj
