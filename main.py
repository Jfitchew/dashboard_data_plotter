import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
SRC = os.path.join(HERE, "src")
if SRC not in sys.path:
    sys.path.insert(0, SRC)

from dashboard_data_plotter.app import main  # noqa: E402

if __name__ == "__main__":
    main()
