from __future__ import annotations

import sys


def main(argv: list[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    if args and args[0] == "--ddp-rich-html-editor":
        from dashboard_data_plotter.ui.rich_html_editor import main as rich_editor_main

        return rich_editor_main(args[1:])

    from dashboard_data_plotter.ui.tk_app import main as tk_main

    tk_main()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
