import traceback
from datetime import datetime
from pathlib import Path
from typing import Any

DEFAULT_LOG_PATH = Path.home() / "DashboardDataPlotter_error.log"
RICH_EDITOR_LOG_PATH = Path.home() / "DashboardDataPlotter_rich_editor.log"


def _safe_text(value: Any, max_len: int = 800) -> str:
    try:
        text = str(value)
    except Exception:
        text = repr(value)
    text = text.replace("\r", "\\r").replace("\n", "\\n")
    if len(text) > max_len:
        return text[: max_len - 3] + "..."
    return text


def log_event(context: str, message: str, log_path: Path = DEFAULT_LOG_PATH) -> None:
    """Append a concise single-line diagnostic event to a log file."""
    try:
        with open(log_path, "a", encoding="utf-8") as f:
            f.write(f"{datetime.now().isoformat()}  |  {context}  |  {_safe_text(message)}\n")
    except Exception:
        pass

def log_exception(context: str, log_path: Path = DEFAULT_LOG_PATH) -> None:
    """Append the current exception traceback to a log file."""
    try:
        with open(log_path, "a", encoding="utf-8") as f:
            f.write("\n\n" + "=" * 80 + "\n")
            f.write(f"{datetime.now().isoformat()}  |  {context}\n")
            traceback.print_exc(file=f)
    except Exception:
        # Never crash the app due to logging failures
        pass
