from __future__ import annotations

import argparse
import sys


def main(argv: list[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    if args and args[0] == "--ddp-rich-html-editor":
        from dashboard_data_plotter.ui.rich_html_editor import main as rich_editor_main

        return rich_editor_main(args[1:])
    if args and args[0] == "--ddp-dash-web":
        parser = argparse.ArgumentParser(add_help=False)
        parser.add_argument("--host", default="127.0.0.1")
        parser.add_argument("--port", type=int, default=8050)
        parser.add_argument("--startup-session-file", default="")
        ns, _unknown = parser.parse_known_args(args[1:])

        from dashboard_data_plotter.ui.dash_app import main as dash_main

        dash_main(
            host=ns.host,
            port=ns.port,
            startup_session_file=ns.startup_session_file,
            debug=False,
            use_reloader=False,
        )
        return 0

    from dashboard_data_plotter.ui.tk_app import main as tk_main

    tk_main()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
