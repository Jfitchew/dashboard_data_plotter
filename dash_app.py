import os
import sys
import traceback

ROOT_DIR = os.path.dirname(__file__)
SRC_DIR = os.path.join(ROOT_DIR, "src")
if SRC_DIR not in sys.path:
    sys.path.insert(0, SRC_DIR)

from dashboard_data_plotter.ui.dash_app import main


if __name__ == "__main__":
    try:
        print("Starting Dash app on http://127.0.0.1:8050 ...")
        main(debug=True)
    except Exception as exc:
        print(f"Dash app failed to start: {type(exc).__name__}: {exc}")
        print("If dependencies are missing, install: pip install dash dash-bootstrap-components")
        traceback.print_exc()
        raise
