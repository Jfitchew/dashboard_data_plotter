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
    now = _now_iso()
    title = f"{project_title} Report" if project_title else "Untitled Report"
    return {
        "version": REPORT_VERSION,
        "title": title,
        "created_at": now,
        "updated_at": now,
        "project_title": project_title,
        "project_path": project_path,
        "data_sources": list(data_sources),
        "snapshots": [],
    }


def touch_report(report: dict[str, Any]) -> None:
    report["updated_at"] = _now_iso()


def save_report(report: dict[str, Any], path: str) -> None:
    touch_report(report)
    with open(path, "w", encoding="utf-8") as handle:
        json.dump(report, handle, indent=2)


def load_report(path: str) -> dict[str, Any]:
    with open(path, "r", encoding="utf-8") as handle:
        obj = json.load(handle)
    return obj if isinstance(obj, dict) else {}
