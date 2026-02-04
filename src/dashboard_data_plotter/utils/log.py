import traceback
from datetime import datetime
from pathlib import Path

DEFAULT_LOG_PATH = Path.home() / "DashboardDataPlotter_error.log"

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
