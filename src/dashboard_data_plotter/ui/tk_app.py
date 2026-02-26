from dashboard_data_plotter.plotting.helpers import (
    to_percent_of_mean,
    circular_interp_baseline,
    fmt_abs_ticks,
    fmt_delta_ticks,
    choose_decimals_from_ticks,
)
from dashboard_data_plotter.core.state import (
    ProjectState,
    set_plot_type,
    set_metric,
    set_angle,
    set_agg_mode,
    set_value_mode,
    set_compare,
    set_baseline,
    set_baselines,
    set_use_original_binned,
    update_cleaning_settings,
)
from dashboard_data_plotter.core.datasets import (
    add_dataset,
    remove_dataset,
    rename_dataset as state_rename_dataset,
    toggle_show_flag,
    set_all_show_flags,
    reorder_datasets,
    ordered_source_ids,
)
from dashboard_data_plotter.core.io import (
    extract_project_settings,
    apply_project_settings,
    build_project_payload,
    build_dataset_data_payload,
    PROJECT_SETTINGS_KEY,
)
from dashboard_data_plotter.core.reporting import (
    new_report_state,
    report_assets_dir,
    save_report as save_report_file,
    load_report as load_report_file,
)
from dashboard_data_plotter.core.report_pdf import export_report_pdf as export_report_pdf_file
from dashboard_data_plotter.core.plotting import (
    prepare_radar_plot,
    prepare_cartesian_plot,
    prepare_bar_plot,
    prepare_timeseries_plot,
    _aggregate_timeseries_baseline,
)
from dashboard_data_plotter.data.loaders import (
    DEFAULT_SENTINELS,
    extract_named_datasets,
    extract_named_binned_datasets,
    load_json_file_obj,
    make_unique_name,
    parse_sentinels,
    prepare_angle_value,
    prepare_angle_value_agg,
    aggregate_metric,
    sanitize_numeric,
    apply_outlier_filter,
    normalize_outlier_method,
    wrap_angle_deg,
)
from dashboard_data_plotter.utils.sortkeys import dataset_sort_key
from dashboard_data_plotter.utils.log import (
    log_exception,
    log_event,
    DEFAULT_LOG_PATH,
    RICH_EDITOR_LOG_PATH,
)
from dashboard_data_plotter.version import APP_TITLE, BUILD_VERSION, MAJOR_VERSION
import os
import sys
import json
import base64
import html
import shutil
import uuid
import socket
from datetime import datetime
import csv
import re
import tempfile
import ctypes
import subprocess
import tkinter as tk
from tkinter import ttk, filedialog, messagebox, colorchooser, simpledialog
import tkinter.font as tkfont
import webbrowser

import numpy as np
import pandas as pd

from matplotlib.figure import Figure
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg, NavigationToolbar2Tk
from matplotlib import image as mpimg
import plotly.graph_objects as go
import plotly.io as pio

import matplotlib
matplotlib.use("TkAgg")


class ToolTip:
    def __init__(self, widget, text):
        self.widget = widget
        self.text = text
        self._tip = None
        self._after_id = None
        widget.bind("<Enter>", self._schedule, add=True)
        widget.bind("<Leave>", self._hide, add=True)
        widget.bind("<ButtonPress>", self._hide, add=True)

    def _schedule(self, _event=None):
        self._cancel()
        self._after_id = self.widget.after(600, self._show)

    def _cancel(self):
        if self._after_id is not None:
            try:
                self.widget.after_cancel(self._after_id)
            except Exception:
                pass
            self._after_id = None

    def _show(self):
        if self._tip or not self.text:
            return
        try:
            x = self.widget.winfo_rootx() + 12
            y = self.widget.winfo_rooty() + self.widget.winfo_height() + 8
            self._tip = tk.Toplevel(self.widget)
            self._tip.wm_overrideredirect(True)
            self._tip.wm_geometry(f"+{x}+{y}")
            label = tk.Label(
                self._tip,
                text=self.text,
                justify="left",
                background="#FFFFE0",
                relief="solid",
                borderwidth=1,
                font=("Segoe UI", 9),
                padx=6,
                pady=3,
                wraplength=360,
            )
            label.pack()
        except Exception:
            self._tip = None

    def _hide(self, _event=None):
        self._cancel()
        if self._tip is not None:
            try:
                self._tip.destroy()
            except Exception:
                pass
            self._tip = None


class DashboardDataPlotter(tk.Tk):
    def __init__(self):
        super().__init__()
        self.project_title = "Untitled Project"
        self.project_path = ""
        self._project_dirty = False
        self._suspend_dirty = False
        self._update_title_bar()
        self._startup_window_size = (1500, 876)
        self.geometry("1500x876")
        self._init_styles()

        # Internal storage:
        #   source_id: unique ID (file path, or "PASTE::<name>")
        #   display_name: human name shown in listbox/legend/baseline chooser
        self.state = ProjectState()

        self.angle_var = tk.StringVar(value="leftPedalCrankAngle")
        self.metric_var = tk.StringVar(value="")
        self.agg_var = tk.StringVar(value="median")
        self.remove_outliers_var = tk.BooleanVar(value=False)
        self.outlier_method_var = tk.StringVar(value="MAD")
        self.outlier_thresh_var = tk.StringVar(value="4.0")
        self.show_outliers_var = tk.BooleanVar(value=False)
        self.outlier_warnings_var = tk.BooleanVar(value=True)
        self._outlier_warnings_disable_notice_shown = False
        self.close_loop_var = tk.BooleanVar(value=True)
        self.sentinels_var = tk.StringVar(value=DEFAULT_SENTINELS)

        # Value mode used for BOTH normal plots and comparison plots
        # "absolute" or "percent_mean"
        self.value_mode_var = tk.StringVar(value="absolute")

        # Plot type
        # "radar", "cartesian", or "bar"
        self.plot_type_var = tk.StringVar(value="radar")

        # Plot backend
        self.use_plotly_var = tk.BooleanVar(value=False)
        self.radar_background_var = tk.BooleanVar(value=True)

        # Plot range controls
        self.range_low_var = tk.StringVar(value="")
        self.range_high_var = tk.StringVar(value="")
        self.range_fixed_var = tk.BooleanVar(value=False)
        self.use_original_binned_var = tk.BooleanVar(value=False)

        # Comparison mode
        self.compare_var = tk.BooleanVar(value=False)
        self.baseline_display_var = tk.StringVar(value="")
        self.baseline_multi_displays: list[str] = []
        self.baseline_menu_var = tk.StringVar(value="Select baseline")
        self._baseline_menu_vars: dict[str, tk.BooleanVar] = {}
        self._baseline_menu_displays: list[str] = []
        self._baseline_menu_widget: tk.Menu | None = None
        self._baseline_popup: tk.Toplevel | None = None
        self._baseline_popup_binding = None

        # Plot history
        self._history = []
        self._history_index = -1
        self._restoring_history = False

        # Report state
        self.report_path = ""
        self.report_state = None
        self._last_plotly_fig = None
        self._last_plotly_title = ""
        self._report_dirty = False
        self._report_temp_assets_dir = ""
        self.report_hide_meta_var = tk.BooleanVar(value=False)

        # Annotations (matplotlib only)
        self.annotation_mode_var = tk.BooleanVar(value=False)
        self._annotations = []
        self._annotation_artists = []
        self._annotation_format = self._default_annotation_format()
        self._annotation_drag_state = None
        self._load_annotation_format_from_project_options()
        self._plot_hover_targets = []
        self._plot_hover_annotation = None
        self._plot_selected_marker = None
        self._plot_dataset_listbox_source_ids: list[str] = []
        self._suspend_plot_dataset_listbox_event = False
        self._text_context_menu_target = None
        self._text_context_menu = None
        self._web_app_proc = None
        self._web_app_url = ""
        self._web_app_handoff_path = ""

        self._init_styles()
        self._init_text_context_menu_support()
        self._build_ui()
        self._build_plot()
        self._apply_startup_window_geometry()

        self._set_plot_type_controls_state()
        self._set_compare_controls_state()
        self._update_outlier_show_state()
        self.protocol("WM_DELETE_WINDOW", self._on_close)

    def _apply_startup_window_geometry(self):
        # Clamp the initial window to the current screen and place it near the
        # top-center so the bottom edge stays visible on shorter displays.
        try:
            self.update_idletasks()
            screen_w = max(1, int(self.winfo_screenwidth()))
            screen_h = max(1, int(self.winfo_screenheight()))
            default_w, default_h = self._startup_window_size
            width = min(default_w, max(900, screen_w - 40))
            height = min(default_h, max(650, screen_h - 100))
            width = min(width, screen_w)
            height = min(height, screen_h)
            x = max(0, (screen_w - width) // 2)
            y = max(0, min(24, screen_h - height))
            self.geometry(f"{width}x{height}+{x}+{y}")
        except Exception:
            # Fall back to Tk/window-manager default placement if geometry
            # probing is unavailable on the current platform.
            pass

    def _init_styles(self):
        try:
            style = ttk.Style(self)
            salmon = "#eed8cf"
            style.configure("OutlierRow.TFrame", background=salmon)
            style.configure("OutlierRow.TLabel", background=salmon)
            style.configure("OutlierRow.TCheckbutton", background=salmon)
            style.configure("Baseline.TMenubutton", background="white")
            try:
                default_font = tkfont.nametofont("TkDefaultFont")
                section_label_font = (
                    default_font.actual("family"),
                    default_font.actual("size"),
                    "bold",
                )
            except Exception:
                section_label_font = ("Segoe UI", 9, "bold")
            style.configure("Section.TLabelframe.Label",
                            font=section_label_font)
            style.configure(
                "LeftPanel.TNotebook",
                background="#d8dde6",
                tabmargins=(2, 2, 2, 0),
            )
            style.configure(
                "LeftPanel.TNotebook.Tab",
                font=("Segoe UI", 10, "bold"),
                padding=(14, 7),
                background="#dce2eb",
                foreground="#1f2937",
            )
            style.map(
                "LeftPanel.TNotebook.Tab",
                background=[
                    ("selected", "#ffffff"),
                    ("active", "#eaf0f8"),
                    ("!selected", "#dce2eb"),
                ],
                foreground=[
                    ("selected", "#111111"),
                    ("active", "#111111"),
                    ("!selected", "#334155"),
                ],
            )
        except Exception:
            pass

    def _dataset_color_cycle(self):
        prop_cycle = matplotlib.rcParams.get("axes.prop_cycle")
        if prop_cycle:
            colors = prop_cycle.by_key().get("color", [])
            if colors:
                return list(colors)
        return [
            "#1f77b4",
            "#ff7f0e",
            "#2ca02c",
            "#d62728",
            "#9467bd",
            "#8c564b",
            "#e377c2",
            "#7f7f7f",
            "#bcbd22",
            "#17becf",
        ]

    def _dataset_color_map(self):
        ids = list(self.get_plot_order_source_ids())
        for sid in self.state.loaded.keys():
            if sid not in ids:
                ids.append(sid)
        colors = self._dataset_color_cycle()
        return {sid: colors[idx % len(colors)] for idx, sid in enumerate(ids)}

    def _update_title_bar(self):
        title = self.project_title or "Untitled Project"
        dirty = " *" if self._project_dirty else ""
        self.title(f"{APP_TITLE} — {title}{dirty}")

    def _mark_dirty(self):
        if self._suspend_dirty:
            return
        if not self._project_dirty:
            self._project_dirty = True
            self._update_title_bar()

    def _clear_dirty(self):
        if self._project_dirty:
            self._project_dirty = False
        self._update_title_bar()

    def _prompt_save_if_dirty(self, action_label: str) -> bool:
        if not self._project_dirty:
            return True
        choice = messagebox.askyesnocancel(
            "Unsaved changes",
            f"The current project has unsaved changes.\n\nSave before {action_label}?",
        )
        if choice is None:
            return False
        if choice:
            return self.save_project()
        return True

    def _sanitize_filename(self, name: str) -> str:
        base = re.sub(r"[<>:\"/\\\\|?*]+", "_", name).strip()
        return base if base else "project"

    def _normalize_project_title(self, title: str) -> str:
        text = (title or "").strip()
        lower = text.lower()
        if lower.endswith(".proj.json"):
            text = text[:-10]
        elif lower.endswith(".proj"):
            text = text[:-5]
        text = text.strip().rstrip(".")
        return text or "Untitled Project"

    def _project_title_from_path(self, path: str) -> str:
        filename = os.path.basename(path or "").strip()
        return self._normalize_project_title(filename)

    def _ensure_project_title(self) -> bool:
        if self.project_title and self.project_title != "Untitled Project":
            return True
        title = simpledialog.askstring(
            "Project title", "Enter a title for this project:", parent=self)
        if not title:
            return False
        self.project_title = title.strip() or "Untitled Project"
        self._update_title_bar()
        return True

    def _changelog_user_path(self) -> str:
        base_dir = os.path.join(os.path.expanduser("~"),
                                ".dashboard_data_plotter")
        return os.path.join(base_dir, "CHANGELOG.md")

    def _changelog_repo_path(self) -> str:
        return os.path.normpath(
            os.path.join(
                os.path.dirname(__file__),
                "..",
                "..",
                "..",
                "CHANGELOG.md",
            )
        )

    def _changelog_packaged_path(self) -> str:
        if getattr(sys, "_MEIPASS", None):
            return os.path.join(sys._MEIPASS, "CHANGELOG.md")
        return ""

    def _next_changelog_release_id(self) -> str:
        major = str(MAJOR_VERSION).strip() or "0"
        try:
            next_build = int(str(BUILD_VERSION).strip()) + 1
        except (TypeError, ValueError):
            next_build = 1
        return f"{major}.{next_build}"

    def _default_changelog_text(self) -> str:
        today = datetime.now().date().isoformat()
        release_id = self._next_changelog_release_id()
        return (
            "# Change Log\n\n"
            f"{release_id} - New Build Release\n"
            f"  - {release_id}.1 - {today} - Change log initialized.\n"
        )

    def _ensure_changelog_file(self) -> str:
        repo_path = self._changelog_repo_path()
        user_path = self._changelog_user_path()
        user_dir = os.path.dirname(user_path)
        if not os.path.isdir(user_dir):
            try:
                os.makedirs(user_dir, exist_ok=True)
            except OSError:
                pass

        packaged_path = self._changelog_packaged_path()
        if packaged_path and os.path.isfile(packaged_path):
            return packaged_path

        if repo_path and os.path.isfile(repo_path):
            return repo_path
        if os.path.isfile(user_path):
            return user_path

        for target in (repo_path, user_path):
            if not target:
                continue
            try:
                with open(target, "w", encoding="utf-8") as handle:
                    handle.write(self._default_changelog_text())
                return target
            except OSError:
                continue

        return ""

    def _render_markdown(self, widget: tk.Text, markdown_text: str) -> None:
        widget.configure(state="normal")
        widget.delete("1.0", "end")

        base_font = ("Segoe UI", 10)
        widget.tag_configure("base", font=base_font)
        widget.tag_configure("h1", font=("Segoe UI", 14, "bold"))
        widget.tag_configure("h2", font=("Segoe UI", 12, "bold"))
        widget.tag_configure("h3", font=("Segoe UI", 11, "bold"))
        widget.tag_configure("bullet", lmargin1=18, lmargin2=28)
        widget.tag_configure("indent", lmargin1=32, lmargin2=42)
        widget.tag_configure("bold", font=("Segoe UI", 10, "bold"))

        def insert_with_bold(text: str, tag: str) -> None:
            parts = re.split(r"(\\*\\*[^*]+\\*\\*)", text)
            for part in parts:
                if part.startswith("**") and part.endswith("**") and len(part) > 4:
                    widget.insert("end", part[2:-2], ("bold",))
                else:
                    widget.insert("end", part, (tag,))

        for raw_line in markdown_text.splitlines():
            line = raw_line.rstrip("\n")
            stripped = line.lstrip()
            if not stripped:
                widget.insert("end", "\n", ("base",))
                continue

            if stripped.startswith("<!--") and stripped.endswith("-->"):
                continue

            if stripped.startswith("#"):
                level = len(stripped) - len(stripped.lstrip("#"))
                text = stripped[level:].strip()
                tag = "h1" if level == 1 else "h2" if level == 2 else "h3"
                widget.insert("end", text + "\n", (tag,))
                continue

            if line.startswith("  - "):
                bullet_text = line[4:]
                widget.insert("end", "• ", ("indent",))
                insert_with_bold(bullet_text, "indent")
                widget.insert("end", "\n", ("indent",))
                continue

            if stripped.startswith("- "):
                bullet_text = stripped[2:]
                widget.insert("end", "• ", ("bullet",))
                insert_with_bold(bullet_text, "bullet")
                widget.insert("end", "\n", ("bullet",))
                continue

            insert_with_bold(line, "base")
            widget.insert("end", "\n", ("base",))

        widget.configure(state="disabled")

    def _open_changelog(self) -> None:
        changelog_path = self._ensure_changelog_file()
        if not changelog_path:
            messagebox.showerror(
                "Change Log",
                "Unable to locate or create CHANGELOG.md.",
            )
            return

        try:
            with open(changelog_path, "r", encoding="utf-8") as handle:
                changelog_text = handle.read()
        except OSError as exc:
            messagebox.showerror(
                "Change Log", f"Failed to read change log: {exc}")
            return

        dialog = tk.Toplevel(self)
        dialog.title("Change Log")
        dialog.transient(self)
        dialog.grab_set()
        dialog.geometry("720x640")
        self._center_dialog(dialog)

        container = ttk.Frame(dialog, padding=10)
        container.pack(fill="both", expand=True)

        text_frame = ttk.Frame(container)
        text_frame.pack(fill="both", expand=True)

        text_widget = tk.Text(text_frame, wrap="word")
        text_widget.pack(side="left", fill="both", expand=True)

        scrollbar = ttk.Scrollbar(
            text_frame, orient="vertical", command=text_widget.yview)
        scrollbar.pack(side="right", fill="y")
        text_widget.configure(yscrollcommand=scrollbar.set)

        self._render_markdown(text_widget, changelog_text)

        btn_frame = ttk.Frame(container)
        btn_frame.pack(fill="x", pady=(10, 0))
        ttk.Button(btn_frame, text="Close",
                   command=dialog.destroy).pack(side="right")

        dialog.bind("<Escape>", lambda _e: dialog.destroy(), add=True)
        dialog.focus_set()

    def _center_dialog(self, dialog: tk.Toplevel) -> None:
        try:
            dialog.update_idletasks()
            self.update_idletasks()
            width = dialog.winfo_width() or dialog.winfo_reqwidth()
            height = dialog.winfo_height() or dialog.winfo_reqheight()
            parent_x = self.winfo_rootx()
            parent_y = self.winfo_rooty()
            parent_w = self.winfo_width()
            parent_h = self.winfo_height()
            x = max(parent_x + (parent_w - width) // 2, 0)
            y = max(parent_y + (parent_h - height) // 2, 0)
            dialog.geometry(f"{width}x{height}+{x}+{y}")
        except Exception:
            return

    def _guide_repo_path(self) -> str:
        return os.path.normpath(
            os.path.join(
                os.path.dirname(__file__),
                "..",
                "..",
                "..",
                "GUIDE.md",
            )
        )

    def _guide_packaged_path(self) -> str:
        if getattr(sys, "_MEIPASS", None):
            return os.path.join(sys._MEIPASS, "GUIDE.md")
        return ""

    def _open_guide(self) -> None:
        candidate_paths = [
            self._guide_repo_path(),
            self._guide_packaged_path(),
        ]
        guide_path = ""
        for path in candidate_paths:
            if path and os.path.isfile(path):
                guide_path = path
                break
        if not guide_path:
            messagebox.showerror(
                "Guide",
                "Unable to locate GUIDE.md.",
            )
            return
        try:
            with open(guide_path, "r", encoding="utf-8") as handle:
                guide_text = handle.read()
        except OSError as exc:
            messagebox.showerror(
                "Guide", f"Failed to read guide: {exc}")
            return

        dialog = tk.Toplevel(self)
        dialog.title("Guide")
        dialog.transient(self)
        dialog.grab_set()
        dialog.geometry("760x680")
        self._center_dialog(dialog)

        container = ttk.Frame(dialog, padding=10)
        container.pack(fill="both", expand=True)

        text_frame = ttk.Frame(container)
        text_frame.pack(fill="both", expand=True)

        text_widget = tk.Text(text_frame, wrap="word")
        text_widget.pack(side="left", fill="both", expand=True)

        scrollbar = ttk.Scrollbar(
            text_frame, orient="vertical", command=text_widget.yview)
        scrollbar.pack(side="right", fill="y")
        text_widget.configure(yscrollcommand=scrollbar.set)

        self._render_markdown(text_widget, guide_text)

        btn_frame = ttk.Frame(container)
        btn_frame.pack(fill="x", pady=(10, 0))
        ttk.Button(btn_frame, text="Close",
                   command=dialog.destroy).pack(side="right")

        dialog.bind("<Escape>", lambda _e: dialog.destroy(), add=True)
        dialog.focus_set()

    def _pick_free_local_port(self, preferred: int = 8050) -> int:
        for candidate in (preferred, 8051, 8052, 8060, 0):
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            try:
                sock.bind(("127.0.0.1", int(candidate)))
                return int(sock.getsockname()[1])
            except OSError:
                continue
            finally:
                try:
                    sock.close()
                except Exception:
                    pass
        raise OSError("Unable to allocate a free localhost port.")

    def _is_local_port_open(self, port: int) -> bool:
        try:
            with socket.create_connection(("127.0.0.1", int(port)), timeout=0.2):
                return True
        except OSError:
            return False

    def _launch_web_app(self) -> None:
        try:
            existing = self._web_app_proc
            if existing is not None and existing.poll() is None and self._web_app_url:
                webbrowser.open(self._web_app_url)
                self.status.set(f"Opened existing web app: {self._web_app_url}")
                return

            port = self._pick_free_local_port(8050)
            url = f"http://127.0.0.1:{port}"
            src_root = os.path.abspath(os.path.join(
                os.path.dirname(__file__), "..", ".."))
            project_root = os.path.abspath(os.path.join(src_root, ".."))
            env = dict(os.environ)
            handoff_path = self._write_dash_startup_handoff_file()

            if getattr(sys, "frozen", False):
                cmd = [
                    sys.executable,
                    "--ddp-dash-web",
                    "--host",
                    "127.0.0.1",
                    "--port",
                    str(port),
                    "--startup-session-file",
                    handoff_path,
                ]
            else:
                py_path = env.get("PYTHONPATH", "")
                env["PYTHONPATH"] = src_root + (os.pathsep + py_path if py_path else "")
                cmd = [
                    sys.executable,
                    "-m",
                    "dashboard_data_plotter.ui.dash_app",
                    "--host",
                    "127.0.0.1",
                    "--port",
                    str(port),
                    "--startup-session-file",
                    handoff_path,
                    "--no-debug",
                    "--no-reloader",
                ]

            popen_kwargs = {
                "cwd": project_root,
                "env": env,
            }
            if os.name == "nt":
                popen_kwargs["creationflags"] = getattr(subprocess, "CREATE_NO_WINDOW", 0)

            proc = subprocess.Popen(cmd, **popen_kwargs)
            self._web_app_proc = proc
            self._web_app_url = url
            self._web_app_handoff_path = handoff_path
            self.status.set(f"Starting web app on {url} ...")
            self.after(250, lambda: self._finish_web_app_launch(proc, url, port, attempts=40))
        except Exception as exc:
            log_exception("tk._launch_web_app failed")
            messagebox.showerror(
                "Web app",
                f"Failed to start web app:\n{type(exc).__name__}: {exc}",
            )

    def _finish_web_app_launch(self, proc, url: str, port: int, attempts: int = 40) -> None:
        if self._web_app_proc is not proc:
            return
        if proc.poll() is not None:
            self._web_app_proc = None
            self._web_app_url = ""
            self._cleanup_web_app_handoff_file()
            messagebox.showerror(
                "Web app",
                "The web app process exited before startup completed.\n\n"
                "Check that Dash dependencies are installed and try again.",
            )
            self.status.set("Web app failed to start.")
            return
        if self._is_local_port_open(port):
            webbrowser.open(url)
            self.status.set(f"Web app running: {url}")
            self._cleanup_web_app_handoff_file()
            return
        if attempts <= 0:
            webbrowser.open(url)
            self.status.set(f"Web app may still be starting: {url}")
            return
        self.after(250, lambda: self._finish_web_app_launch(proc, url, port, attempts - 1))

    def _dash_startup_handoff_payload(self) -> dict:
        payload = {
            "project_session": {
                "project_payload": build_project_payload(self.state),
                "dataset_counter": 0,
                "paste_json": "",
                "plot_ui": {},
                "plot_history": [],
                "plot_history_index": -1,
                "plot_result_figure": None,
                "plot_result_errors": [],
                "plot_result_note": "",
                "report_payload": None,
                "report_paste_json": "",
                "handoff_meta": {
                    "from": "tk_app",
                    "project_title": str(self.project_title or ""),
                    "project_path": str(self.project_path or ""),
                },
            },
            "ui_session": {
                "section": "project_data",
                "theme": "theme-lux",
                "sidebar_collapsed": False,
            },
        }
        if isinstance(self.report_state, dict):
            try:
                # JSON round-trip ensures the handoff is serializable and detached
                # from mutable Tk report state objects.
                payload["project_session"]["report_payload"] = json.loads(
                    json.dumps(self.report_state)
                )
            except Exception:
                log_exception("tk._dash_startup_handoff_payload report serialize failed")
        return payload

    def _write_dash_startup_handoff_file(self) -> str:
        self._cleanup_web_app_handoff_file()
        handoff = self._dash_startup_handoff_payload()
        fd, path = tempfile.mkstemp(prefix="ddp_dash_startup_", suffix=".json")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                json.dump(handoff, handle, ensure_ascii=False)
        except Exception:
            try:
                os.close(fd)
            except Exception:
                pass
            try:
                os.remove(path)
            except Exception:
                pass
            raise
        self._web_app_handoff_path = path
        return path

    def _cleanup_web_app_handoff_file(self) -> None:
        path = str(self._web_app_handoff_path or "").strip()
        if not path:
            return
        self._web_app_handoff_path = ""
        try:
            if os.path.isfile(path):
                os.remove(path)
        except Exception:
            pass

    def _init_text_context_menu_support(self) -> None:
        self._text_context_menu = tk.Menu(self, tearoff=0)
        self._text_context_menu.add_command(
            label="Cut", command=lambda: self._text_context_menu_action("cut"))
        self._text_context_menu.add_command(
            label="Copy", command=lambda: self._text_context_menu_action("copy"))
        self._text_context_menu.add_command(
            label="Paste", command=lambda: self._text_context_menu_action("paste"))
        self._text_context_menu.add_separator()
        self._text_context_menu.add_command(
            label="Select All",
            command=lambda: self._text_context_menu_action("select_all"),
        )
        self._text_context_menu.add_command(
            label="Clear", command=lambda: self._text_context_menu_action("clear"))

        for widget_class in ("Text", "Entry", "TEntry", "TCombobox"):
            self.bind_class(
                widget_class,
                "<Button-3>",
                self._show_text_context_menu,
                add=True,
            )

    def _text_context_menu_state(self, widget) -> tuple[bool, bool]:
        state = "normal"
        try:
            state = str(widget.cget("state"))
        except Exception:
            pass
        editable = state not in {"disabled", "readonly"}
        has_selection = False
        try:
            if isinstance(widget, tk.Text):
                has_selection = bool(widget.tag_ranges("sel"))
            else:
                has_selection = bool(widget.selection_present())
        except Exception:
            has_selection = False
        return editable, has_selection

    def _show_text_context_menu(self, event):
        widget = getattr(event, "widget", None)
        if widget is None or self._text_context_menu is None:
            return None
        try:
            widget.focus_set()
        except Exception:
            pass
        self._text_context_menu_target = widget
        editable, has_selection = self._text_context_menu_state(widget)
        normal_or_disabled = "normal" if has_selection else "disabled"
        self._text_context_menu.entryconfigure(
            "Cut", state="normal" if (editable and has_selection) else "disabled")
        self._text_context_menu.entryconfigure("Copy", state=normal_or_disabled)
        self._text_context_menu.entryconfigure(
            "Paste", state="normal" if editable else "disabled")
        self._text_context_menu.entryconfigure("Select All", state="normal")
        self._text_context_menu.entryconfigure(
            "Clear", state="normal" if editable else "disabled")
        try:
            self._text_context_menu.tk_popup(event.x_root, event.y_root)
        finally:
            self._text_context_menu.grab_release()
        return "break"

    def _text_context_menu_action(self, action: str) -> None:
        widget = self._text_context_menu_target
        if widget is None:
            return
        try:
            widget.focus_set()
        except Exception:
            pass

        if action == "cut":
            try:
                widget.event_generate("<<Cut>>")
            except Exception:
                pass
            return
        if action == "copy":
            try:
                widget.event_generate("<<Copy>>")
            except Exception:
                pass
            return
        if action == "paste":
            try:
                widget.event_generate("<<Paste>>")
            except Exception:
                pass
            return
        if action == "select_all":
            try:
                if isinstance(widget, tk.Text):
                    widget.tag_add("sel", "1.0", "end-1c")
                    widget.mark_set("insert", "1.0")
                    widget.see("insert")
                else:
                    widget.selection_range(0, "end")
                    widget.icursor(0)
                    widget.xview_moveto(0)
            except Exception:
                pass
            return
        if action == "clear":
            try:
                if isinstance(widget, tk.Text):
                    widget.delete("1.0", "end")
                else:
                    widget.delete(0, "end")
            except Exception:
                pass

    # ---------------- UI ----------------
    def _build_ui(self):
        self.columnconfigure(0, weight=0)
        self.columnconfigure(1, weight=2)
        self.columnconfigure(0, minsize=420)
        self.rowconfigure(0, weight=1)

        left = ttk.Frame(self, padding=10)
        left.grid(row=0, column=0, sticky="ns")
        left.columnconfigure(0, weight=1)
        left.rowconfigure(1, weight=1)

        tabs_tools = ttk.Frame(left)
        tabs_tools.grid(row=0, column=0, sticky="ew", pady=(0, 4))
        tabs_tools.columnconfigure(0, weight=1)
        self.btn_web_app = ttk.Button(
            tabs_tools, text="Web app", command=self._launch_web_app, width=10)
        self.btn_web_app.grid(row=0, column=0, sticky="w")
        self.btn_guide = ttk.Button(
            tabs_tools, text="Guide", command=self._open_guide, width=10)
        self.btn_guide.grid(row=0, column=1, sticky="e")
        self.btn_change_log = ttk.Button(
            tabs_tools, text="Change log", command=self._open_changelog, width=12)
        self.btn_change_log.grid(row=0, column=2, sticky="e", padx=(6, 0))

        left_notebook = ttk.Notebook(left, style="LeftPanel.TNotebook")
        left_notebook.grid(row=1, column=0, sticky="nsew")

        project_data_tab = ttk.Frame(left_notebook, padding=8)
        plot_tab = ttk.Frame(left_notebook, padding=8)
        report_tab = ttk.Frame(left_notebook, padding=8)
        project_data_tab.columnconfigure(0, weight=1)
        plot_tab.columnconfigure(0, weight=1)
        report_tab.columnconfigure(0, weight=1)
        left_notebook.add(project_data_tab, text="Project / Data")
        left_notebook.add(plot_tab, text="Plot")
        left_notebook.add(report_tab, text="Reports")

        ttk.Label(project_data_tab, text="Project / Data", font=(
            "Segoe UI", 12, "bold")).grid(row=0, column=0, sticky="w")
        ttk.Label(
            project_data_tab,
            text="Load, organize, rename, and order datasets. This tab controls project structure and saved dataset order.",
            foreground="#555",
            wraplength=380,
        ).grid(row=1, column=0, sticky="w", pady=(2, 8))

        project_file_group = ttk.LabelFrame(
            project_data_tab, text="Project file", padding=8, style="Section.TLabelframe")
        project_file_group.grid(row=2, column=0, sticky="ew")
        proj_btns = ttk.Frame(project_file_group)
        proj_btns.grid(row=0, column=0, sticky="ew")
        self.btn_new_project = ttk.Button(
            proj_btns, text="New project", command=self.new_project, width=12)
        self.btn_new_project.grid(row=0, column=0, sticky="ew")
        self.btn_load_project = ttk.Button(
            proj_btns, text="Load project...", command=self.load_project, width=12)
        self.btn_load_project.grid(row=0, column=1, padx=(6, 0))
        self.btn_save_project = ttk.Button(
            proj_btns, text="Save project...", command=self.save_project, width=12)
        self.btn_save_project.grid(row=0, column=2, padx=(6, 0))

        data_group = ttk.LabelFrame(
            project_data_tab, text="Data sources", padding=8, style="Section.TLabelframe")
        data_group.grid(row=3, column=0, sticky="ew", pady=(8, 0))
        data_group.columnconfigure(0, weight=1)

        data_btns = ttk.Frame(data_group)
        data_btns.grid(row=0, column=0, sticky="ew", pady=(0, 6))
        self.btn_add_files = ttk.Button(
            data_btns, text="Add data file(s)...", command=self.add_files)
        self.btn_add_files.grid(row=0, column=0, padx=(0, 0))
        self.btn_remove = ttk.Button(
            data_btns, text="Remove", command=self.remove_selected, width=8)
        self.btn_remove.grid(row=0, column=1, padx=(6, 0), pady=(0, 0))
        self.btn_save_data = ttk.Button(
            data_btns, text="Save Data", command=self.save_data, width=11)
        self.btn_save_data.grid(row=0, column=2, padx=(3, 0), pady=(0, 0))
        self.btn_rename = ttk.Button(
            data_btns, text="Rename", command=self.rename_selected, width=8)
        self.btn_rename.grid(row=0, column=3, padx=(6, 0), pady=(0, 0))
        self.btn_move_up = ttk.Button(
            data_btns, text="Up", command=self.move_selected_up, width=3)
        self.btn_move_up.grid(row=0, column=4, padx=(6, 0), pady=(0, 0))
        self.btn_move_down = ttk.Button(
            data_btns, text="Dn", command=self.move_selected_down, width=3)
        self.btn_move_down.grid(row=0, column=5, padx=(3, 0), pady=(0, 0))

        # Treeview: dataset list (show/hide state is still tracked in state, but
        # visibility control is handled from the Plot tab list for now).
        tv_frame = ttk.Frame(data_group)
        tv_frame.grid(row=1, column=0, sticky="ew")
        tv_frame.columnconfigure(0, weight=1)

        self.files_tree = ttk.Treeview(
            tv_frame,
            columns=("show", "order", "name", "rows", "cols", "source_id"),
            displaycolumns=("order", "name", "rows", "cols", "source_id"),
            show="headings",
            height=8,
            selectmode="extended",
        )
        self.files_tree.heading("show", text="Show",
                                command=self.toggle_all_show)
        self.files_tree.heading("order", text="#")
        self.files_tree.heading("name", text="Dataset",
                                anchor="w", command=self.sort_by_dataset_name)
        self.files_tree.heading("rows", text="Rows")
        self.files_tree.heading("cols", text="Cols")
        self.files_tree.heading("source_id", text="Source ID", anchor="e")
        self.files_tree.column("show", width=50, anchor="center", stretch=False)
        self.files_tree.column("order", width=38, anchor="center", stretch=False)
        self.files_tree.column("name", width=118, anchor="w", stretch=False)
        self.files_tree.column("rows", width=56, anchor="e", stretch=False)
        self.files_tree.column("cols", width=44, anchor="e", stretch=False)
        self.files_tree.column("source_id", width=132, anchor="e", stretch=False)

        self.files_tree.grid(row=0, column=0, sticky="ew")

        tv_scroll = ttk.Scrollbar(
            tv_frame, orient="vertical", command=self.files_tree.yview)
        tv_scroll.grid(row=0, column=1, sticky="ns")
        self.files_tree.configure(yscrollcommand=tv_scroll.set)

        # Rename on double-click of name. Show/hide is handled on the Plot tab.
        self.files_tree.bind("<Button-1>", self._on_tree_click, add=True)
        self.files_tree.bind(
            "<Double-1>", self._on_tree_double_click, add=True)

        # --- Paste JSON sources
        paste_group = ttk.LabelFrame(
            project_data_tab, text="Paste data source", padding=8, style="Section.TLabelframe")
        paste_group.grid(row=4, column=0, sticky="ew", pady=(8, 0))
        paste_group.columnconfigure(0, weight=1)

        paste_header = ttk.Frame(paste_group)
        paste_header.grid(row=0, column=0, sticky="w", pady=(0, 5))
        ttk.Label(
            paste_header,
            text="Paste a JSON dataset object or multi-dataset JSON, then load/save/clear from here.",
            foreground="#555",
            wraplength=300,
        ).grid(row=0, column=0, sticky="w", padx=(0, 0))

        paste_btns = ttk.Frame(paste_group)
        paste_btns.grid(row=2, column=0, sticky="e", pady=(6, 0))
        self.btn_load_paste = ttk.Button(
            paste_btns, text="Load pasted data", command=self.load_from_paste)
        self.btn_load_paste.grid(row=0, column=0, sticky="ew")
        self.btn_save_paste = ttk.Button(
            paste_btns, text="Save pasted data...", command=self.save_pasted_json)
        self.btn_save_paste.grid(row=0, column=1, padx=(6, 0))
        self.btn_clear_paste = ttk.Button(
            paste_btns, text="Clear pasted data", command=self.clear_paste)
        self.btn_clear_paste.grid(row=0, column=2, padx=(6, 0))

        paste_frame = ttk.Frame(paste_group)
        paste_frame.grid(row=1, column=0, sticky="ew")

        self.paste_text = tk.Text(paste_frame, height=6, width=60, wrap="none")
        self.paste_text.grid(row=0, column=0, sticky="ew")

        paste_scroll = ttk.Scrollbar(
            paste_frame, orient="vertical", command=self.paste_text.yview)
        paste_scroll.grid(row=0, column=1, sticky="ns")
        self.paste_text.configure(yscrollcommand=paste_scroll.set)

        ttk.Label(plot_tab, text="Plot", font=(
            "Segoe UI", 12, "bold")).grid(row=0, column=0, sticky="w")
        ttk.Label(
            plot_tab,
            text="Choose datasets, then configure plot type, metrics and mode settings.",
            foreground="#555",
            wraplength=380,
        ).grid(row=1, column=0, sticky="w", pady=(2, 8))

        # Plot tab dataset visibility selector (selection = shown in plots)
        plot_select_group = ttk.LabelFrame(
            plot_tab, text="Datasets to plot", padding=8, style="Section.TLabelframe")
        plot_select_group.grid(row=2, column=0, sticky="ew")
        plot_select_group.columnconfigure(0, weight=1)

        plot_ds_header = ttk.Frame(plot_select_group)
        plot_ds_header.grid(row=0, column=0, sticky="ew", pady=(0, 4))
        ttk.Label(
            plot_ds_header,
            text="Selection controls plot visibility (manage names/order in Project / Data)",
            foreground="#555",
        ).grid(row=0, column=0, sticky="w")

        plot_ds_frame = ttk.Frame(plot_select_group)
        plot_ds_frame.grid(row=2, column=0, sticky="ew")
        plot_ds_frame.columnconfigure(0, weight=1)
        self.plot_datasets_tree = ttk.Treeview(
            plot_ds_frame,
            columns=("show", "name"),
            show="headings",
            height=7,
            selectmode="extended",
        )
        self.plot_datasets_tree.heading(
            "show", text="Show", command=self.toggle_all_show)
        self.plot_datasets_tree.heading("name", text="Dataset")
        self.plot_datasets_tree.column(
            "show", width=50, anchor="center", stretch=False)
        self.plot_datasets_tree.column("name", width=330, anchor="w")
        self.plot_datasets_tree.grid(row=0, column=0, sticky="ew")
        plot_ds_scroll = ttk.Scrollbar(
            plot_ds_frame, orient="vertical", command=self.plot_datasets_tree.yview)
        plot_ds_scroll.grid(row=0, column=1, sticky="ns")
        self.plot_datasets_tree.configure(yscrollcommand=plot_ds_scroll.set)
        self.plot_datasets_tree.bind(
            "<Button-1>", self._on_plot_datasets_tree_click, add=True)

        plot_type_group = ttk.LabelFrame(
            plot_tab, text="Plot type", padding=8, style="Section.TLabelframe")
        plot_type_group.grid(row=3, column=0, sticky="ew")
        plot_type_group.columnconfigure(0, weight=1)

        plot_type_frame = ttk.Frame(plot_type_group)
        plot_type_frame.grid(row=0, column=0, sticky="ew")

        # Plot type (radar/cartesian/bar)
        pt = ttk.Frame(plot_type_frame)
        pt.grid(row=0, column=0, sticky="w", padx=(8, 0))
        self.rb_radar = ttk.Radiobutton(
            pt, text="Radar (polar)", variable=self.plot_type_var, value="radar",
            command=self._on_plot_type_change)
        self.rb_radar.grid(row=0, column=0, sticky="w")
        self.rb_cartesian = ttk.Radiobutton(
            pt, text="Cartesian (0-360°)", variable=self.plot_type_var, value="cartesian",
            command=self._on_plot_type_change)
        self.rb_cartesian.grid(row=0, column=1, sticky="w", padx=(8, 0))
        self.chk_plotly = ttk.Checkbutton(
            pt, text="Interactive (Plotly)", variable=self.use_plotly_var)
        self.chk_plotly.grid(row=0, column=3, sticky="w", padx=(150, 0))

        self.rb_bar = ttk.Radiobutton(
            pt, text="Bar (avg)", variable=self.plot_type_var, value="bar",
            command=self._on_plot_type_change)
        self.rb_bar.grid(row=1, column=0, sticky="w")
        self.rb_timeseries = ttk.Radiobutton(
            pt, text="Time series", variable=self.plot_type_var, value="timeseries",
            command=self._on_plot_type_change)
        self.rb_timeseries.grid(row=1, column=1, sticky="w", padx=(8, 0))

        self.radar_background_chk = ttk.Checkbutton(
            pt,
            text="Background image",
            variable=self.radar_background_var,
        )
        self.radar_background_chk.grid(
            row=1, column=3, sticky="w", padx=(150, 0))

        metrics_group = ttk.LabelFrame(
            plot_tab, text="Metrics", padding=8, style="Section.TLabelframe")
        metrics_group.grid(row=4, column=0, sticky="ew", pady=(8, 0))
        metrics_group.columnconfigure(0, weight=1)

        metric_frame = ttk.Frame(metrics_group)
        metric_frame.grid(row=0, column=0, sticky="w")

        ttk.Label(metric_frame, text="Angle column:").grid(
            row=0, column=0, sticky="w")
        self.angle_combo = ttk.Combobox(
            metric_frame,
            textvariable=self.angle_var,
            values=["leftPedalCrankAngle", "rightPedalCrankAngle"],
            state="readonly",
            width=30,
        )
        self.angle_combo.grid(row=0, column=1, sticky="w", padx=(8, 0))

        self.close_loop_chk = ttk.Checkbutton(
            metric_frame, text="Close loop", variable=self.close_loop_var)
        self.close_loop_chk.grid(row=0, column=2, sticky="e", padx=(10, 0))

        ttk.Label(metric_frame, text="Metric column:").grid(
            row=1, column=0, sticky="w")
        self.metric_combo = ttk.Combobox(
            metric_frame, textvariable=self.metric_var, values=[], state="readonly", width=30)
        self.metric_combo.grid(row=1, column=1, sticky="w", padx=(8, 0))
        ttk.Label(metric_frame, text="Avg type:").grid(
            row=1, column=2, sticky="e", padx=(10, 0))
        self.agg_combo = ttk.Combobox(
            metric_frame, textvariable=self.agg_var,
            values=["mean", "median", "10% trimmed mean"], state="readonly", width=16)
        self.agg_combo.grid(row=1, column=3, sticky="w", padx=(6, 0))
        self.agg_combo.bind("<<ComboboxSelected>>",
                            lambda _e: self._update_outlier_show_state())

        outliers_group = ttk.LabelFrame(
            plot_tab, text="Outliers", padding=8, style="Section.TLabelframe")
        outliers_group.grid(row=5, column=0, sticky="ew", pady=(8, 0))
        outliers_group.columnconfigure(0, weight=1)

        outlier_row = ttk.Frame(outliers_group, style="OutlierRow.TFrame")
        outlier_row.grid(row=1, column=0, sticky="ew")
        outlier_row.columnconfigure(0, weight=0)
        outlier_row.columnconfigure(1, weight=0)
        outlier_row.columnconfigure(2, weight=0)
        outlier_row.columnconfigure(3, weight=0)
        outlier_row.columnconfigure(4, weight=0)
        outlier_row.columnconfigure(5, weight=0)
        outlier_row.columnconfigure(6, weight=1)

        ttk.Label(outlier_row, text="Remove?", style="OutlierRow.TLabel").grid(
            row=0, column=0, sticky="w")
        self.outlier_chk = ttk.Checkbutton(
            outlier_row, text="", variable=self.remove_outliers_var,
            command=self._on_outlier_toggle, style="OutlierRow.TCheckbutton")
        self.outlier_chk.grid(row=0, column=1, sticky="w", padx=(2, 0))
        ttk.Label(outlier_row, text="Method", style="OutlierRow.TLabel").grid(
            row=0, column=2, sticky="w", padx=(6, 0))
        self.outlier_method_combo = ttk.Combobox(
            outlier_row,
            textvariable=self.outlier_method_var,
            values=["MAD", "Phase-MAD", "Hampel", "Impulse"],
            state="readonly",
            width=12,
        )
        self.outlier_method_combo.grid(
            row=0, column=3, sticky="w", padx=(2, 0))
        ttk.Label(outlier_row, text="Threshold", style="OutlierRow.TLabel").grid(
            row=0, column=4, sticky="w", padx=(6, 0))
        self.outlier_entry = ttk.Entry(
            outlier_row, textvariable=self.outlier_thresh_var, width=8)
        self.outlier_entry.grid(row=0, column=5, sticky="w", padx=(2, 0))
        self.outlier_show_chk = ttk.Checkbutton(
            outlier_row, text="Show", variable=self.show_outliers_var, style="OutlierRow.TCheckbutton")
        self.outlier_show_chk.grid(row=0, column=6, sticky="w", padx=(10, 0))
        self.outlier_warnings_chk = ttk.Checkbutton(
            outlier_row,
            text="Warnings?",
            variable=self.outlier_warnings_var,
            command=self._on_outlier_warnings_toggle,
        )
        self.outlier_warnings_chk.grid(row=0, column=7, sticky="e")

        range_group = ttk.LabelFrame(
            plot_tab, text="Range", padding=8, style="Section.TLabelframe")
        range_group.grid(row=6, column=0, sticky="ew", pady=(8, 0))
        range_group.columnconfigure(0, weight=1)

        range_frame = ttk.Frame(range_group)
        range_frame.grid(row=0, column=0, sticky="ew")
        ttk.Label(range_frame, text="Range (min, max):").grid(
            row=0, column=0, sticky="w")
        self.range_low_entry = ttk.Entry(
            range_frame, textvariable=self.range_low_var, width=10)
        self.range_low_entry.grid(row=0, column=1, sticky="w", padx=(8, 4))
        self.range_high_entry = ttk.Entry(
            range_frame, textvariable=self.range_high_var, width=10)
        self.range_high_entry.grid(row=0, column=2, sticky="w")
        self.range_fixed_chk = ttk.Checkbutton(
            range_frame, text="Fixed", variable=self.range_fixed_var)
        self.range_fixed_chk.grid(row=0, column=3, sticky="w", padx=(8, 0))

        plot_modes_group = ttk.LabelFrame(
            plot_tab, text="Mode", padding=8, style="Section.TLabelframe")
        plot_modes_group.grid(row=7, column=0, sticky="ew", pady=(8, 0))
        plot_modes_group.columnconfigure(0, weight=1)

        # Value mode
        vm_row = ttk.Frame(plot_modes_group)
        vm_row.grid(row=0, column=0, sticky="ew")
        vm_row.columnconfigure(3, weight=1)
        ttk.Label(vm_row, text="Value:").grid(
            row=0, column=0, sticky="w")
        self.rb_absolute = ttk.Radiobutton(
            vm_row, text="Absolute metric values", variable=self.value_mode_var,
            value="absolute")
        self.rb_absolute.grid(row=0, column=1, sticky="w", padx=(12, 0))
        self.rb_percent_mean = ttk.Radiobutton(
            vm_row, text="% of dataset mean", variable=self.value_mode_var, value="percent_mean")
        self.rb_percent_mean.grid(row=0, column=2, sticky="w", padx=(20, 0))
        self.original_binned_btn = ttk.Button(
            vm_row, text="Original Dashboard Bins", command=self._on_original_binned_toggle)
        self.original_binned_btn.grid(
            row=0, column=4, sticky="e", padx=(10, 0))

        ttk.Separator(plot_modes_group).grid(
            row=1, column=0, sticky="ew", pady=6)

        # Comparison mode
        comp_row = ttk.Frame(plot_modes_group)
        comp_row.grid(row=2, column=0, sticky="ew")
        ttk.Label(comp_row, text="Comparison:").grid(
            row=0, column=0, sticky="w")
        self.chk_compare = ttk.Checkbutton(
            comp_row, text="Difference vs Baseline:", variable=self.compare_var,
            command=self._on_compare_toggle)
        self.chk_compare.grid(row=0, column=1, sticky="w", padx=(12, 0))
        self.baseline_menu_btn = ttk.Menubutton(
            comp_row, textvariable=self.baseline_menu_var, width=34, direction="below")
        self.baseline_menu_btn.configure(style="Baseline.TMenubutton")
        self.baseline_menu_btn.grid(row=0, column=2, sticky="w", padx=(8, 0))
        self.baseline_menu_btn.bind(
            "<ButtonRelease-1>", self._toggle_baseline_popup, add=True)
        self.baseline_menu_btn.bind(
            "<Return>", self._toggle_baseline_popup, add=True)
        self.baseline_menu_btn.bind(
            "<space>", self._toggle_baseline_popup, add=True)

        plot_actions_group = ttk.LabelFrame(
            plot_tab, text="Plot actions and history", padding=8, style="Section.TLabelframe")
        plot_actions_group.grid(row=8, column=0, sticky="ew", pady=(8, 0))
        plot_actions_group.columnconfigure(0, weight=1)

        plot_btns = ttk.Frame(plot_actions_group)
        plot_btns.grid(row=0, column=0, sticky="ew")
        plot_btns.columnconfigure(0, weight=1)
        self.plot_btn = ttk.Button(
            plot_btns, text="Plot / Refresh", command=self.plot)
        self.plot_btn.grid(row=0, column=0, sticky="ew")
        self.plot_btn.configure(style="Red.TButton")
        self.export_plot_btn = ttk.Button(
            plot_btns, text="Export Plot Data", command=self.export_plot_data)
        self.export_plot_btn.grid(row=0, column=1, padx=(10, 0))
        self.prev_btn = ttk.Button(
            plot_btns, text="Prev", command=self._plot_prev, state="disabled", width=5)
        self.prev_btn.grid(row=0, column=2, padx=(10, 0))
        self.delete_btn = ttk.Button(
            plot_btns, text="X", command=self._delete_history_entry, state="disabled", width=3)
        self.delete_btn.grid(row=0, column=3, padx=(2, 0))
        self.next_btn = ttk.Button(
            plot_btns, text="Next", command=self._plot_next, state="disabled", width=5)
        self.next_btn.grid(row=0, column=4, padx=(2, 0))
        self.clear_history_btn = ttk.Button(
            plot_btns, text="Clear", command=self._clear_history, state="disabled", width=6)
        self.clear_history_btn.grid(row=0, column=5, padx=(6, 0))
        self.history_label_var = tk.StringVar(value="History 0/0")
        self.history_label = ttk.Label(
            plot_btns, textvariable=self.history_label_var)
        self.history_label.grid(row=0, column=6, padx=(8, 0))

        style = ttk.Style()
        style.configure(
            "Red.TButton",
            background="red",
            foreground="black",
            font=("Segoe UI", 10, "bold"),
            padding=(8, 4),
        )

        self.status = tk.StringVar(
            value="Load one or more JSON files, or paste a dataset object, to begin.")

        ttk.Label(report_tab, text="Reports", font=(
            "Segoe UI", 12, "bold")).grid(row=0, column=0, sticky="w")
        ttk.Label(
            report_tab,
            text="Create, edit, preview, and export report content independently of project/data setup.",
            foreground="#555",
            wraplength=380,
        ).grid(row=1, column=0, sticky="w", pady=(2, 8))

        report_btns = ttk.LabelFrame(
            report_tab, text="Report file", padding=8, style="Section.TLabelframe")
        report_btns.grid(row=2, column=0, sticky="ew")
        report_btns.columnconfigure(0, weight=1)
        report_btns.columnconfigure(1, weight=1)
        report_btns.columnconfigure(2, weight=1)
        report_btns.columnconfigure(3, weight=1)
        self.btn_new_report = ttk.Button(
            report_btns, text="New report...", command=self.new_report, width=12)
        self.btn_new_report.grid(row=0, column=0, sticky="ew")
        self.btn_open_report = ttk.Button(
            report_btns, text="Open report...", command=self.open_report, width=12)
        self.btn_open_report.grid(row=0, column=1, sticky="ew", padx=(6, 0))
        self.btn_manage_report = ttk.Button(
            report_btns, text="Edit report", command=self.manage_report_content, width=14)
        self.btn_manage_report.grid(row=0, column=2, sticky="ew", padx=(6, 0))
        self.btn_save_report = ttk.Button(
            report_btns, text="Save report", command=self.save_report, width=12)
        self.btn_save_report.grid(row=0, column=3, sticky="ew", padx=(6, 0))

        report_btns2 = ttk.LabelFrame(
            report_tab, text="Content and annotations", padding=8, style="Section.TLabelframe")
        report_btns2.grid(row=3, column=0, sticky="ew", pady=(8, 0))
        report_btns2.columnconfigure(0, weight=1)
        report_btns2.columnconfigure(1, weight=1)
        report_btns2.columnconfigure(2, weight=0)
        report_btns2.columnconfigure(3, weight=1)
        self.btn_add_text_block = ttk.Button(
            report_btns2, text="Add content", command=self.add_report_text_block, width=14)
        self.btn_add_text_block.grid(row=0, column=0, sticky="ew")
        self.btn_add_snapshot = ttk.Button(
            report_btns2, text="Add plot snapshot", command=self.add_report_snapshot, width=17)
        self.btn_add_snapshot.grid(row=0, column=1, sticky="ew", padx=(6, 0))
        self.chk_annotate = ttk.Checkbutton(
            report_btns2, text="Annotate", variable=self.annotation_mode_var,
            command=self._on_annotation_toggle)
        self.chk_annotate.grid(row=0, column=2, sticky="w", padx=(10, 0))
        self.btn_clear_annotations = ttk.Button(
            report_btns2, text="Clear annotations", command=self.clear_annotations)
        self.btn_clear_annotations.grid(
            row=0, column=3, sticky="ew", padx=(6, 0))

        report_btns3 = ttk.LabelFrame(
            report_tab, text="Preview and export", padding=8, style="Section.TLabelframe")
        report_btns3.grid(row=4, column=0, sticky="ew", pady=(8, 0))
        report_btns3.columnconfigure(0, weight=1)
        report_btns3.columnconfigure(1, weight=0)
        report_btns3.columnconfigure(2, weight=1)
        report_btns3.columnconfigure(3, weight=1)
        self.btn_view_report = ttk.Button(
            report_btns3, text="Preview report", command=self.view_report, width=13)
        self.btn_view_report.grid(row=0, column=0, sticky="ew")
        self.chk_report_include_meta = ttk.Checkbutton(
            report_btns3,
            text="Incl meta",
            variable=self.report_hide_meta_var,
            command=self._on_report_include_meta_toggle,
        )
        self.chk_report_include_meta.grid(
            row=0, column=1, sticky="w", padx=(8, 8))

        self.btn_export_report_html = ttk.Button(
            report_btns3, text="Export HTML...", command=self.export_report_html, width=12)
        self.btn_export_report_html.grid(row=0, column=2, sticky="ew")
        self.btn_export_report_pdf = ttk.Button(
            report_btns3, text="Export PDF...", command=self.export_report_pdf, width=12)
        self.btn_export_report_pdf.grid(
            row=0, column=3, sticky="ew", padx=(6, 0))

        ttk.Label(left, textvariable=self.status, wraplength=380, foreground="#333").grid(
            row=2, column=0, sticky="ew", pady=(10, 0))

        self._on_plot_type_change(apply_default_agg=False)
        self._set_compare_controls_state()
        self._on_outlier_toggle()
        self._add_tooltips()

    def _sync_treeview_from_state(self):
        for iid in self.files_tree.get_children(""):
            if iid not in self.state.loaded:
                self.files_tree.delete(iid)
        for index, sid in enumerate(ordered_source_ids(self.state)):
            display = self.state.id_to_display.get(sid, sid)
            df = self.state.loaded.get(sid)
            row_count = int(len(df)) if df is not None else 0
            col_count = int(len(df.columns)) if df is not None else 0
            show_txt = "\u2713" if self.state.show_flag.get(sid, True) else ""
            values = (show_txt, index + 1, display, row_count, col_count, sid)
            if not self.files_tree.exists(sid):
                self.files_tree.insert(
                    "", "end", iid=sid, values=values)
            else:
                self.files_tree.item(sid, values=values)
            self.files_tree.move(sid, "", index)
        self._sync_plot_datasets_tree_from_state()

    def _sync_plot_datasets_tree_from_state(self) -> None:
        tree = getattr(self, "plot_datasets_tree", None)
        if tree is None:
            return
        order = list(ordered_source_ids(self.state))
        for iid in tree.get_children(""):
            if iid not in self.state.loaded:
                tree.delete(iid)
        for index, sid in enumerate(order):
            display = self.state.id_to_display.get(sid, sid)
            show_txt = "\u2713" if self.state.show_flag.get(sid, True) else ""
            if not tree.exists(sid):
                tree.insert("", "end", iid=sid, values=(show_txt, display))
            else:
                tree.item(sid, values=(show_txt, display))
            tree.move(sid, "", index)

    def _on_plot_datasets_tree_click(self, event):
        tree = getattr(self, "plot_datasets_tree", None)
        if tree is None:
            return
        region = tree.identify("region", event.x, event.y)
        if region != "cell":
            return
        col = tree.identify_column(event.x)
        if col != "#1":
            return
        row_id = tree.identify_row(event.y)
        if not row_id:
            return
        self.toggle_show(row_id)
        return "break"

    def _sync_state_settings_from_ui(self):
        set_plot_type(self.state, self.plot_type_var.get())
        set_angle(self.state, self.angle_var.get())
        set_metric(self.state, self.metric_var.get())
        set_agg_mode(self.state, self._normalize_agg_mode(self.agg_var.get()))
        set_value_mode(self.state, self.value_mode_var.get())
        set_compare(self.state, self.compare_var.get())
        baseline_display = self.baseline_display_var.get().strip()
        baseline_id = self.state.display_to_id.get(baseline_display, "")
        set_baseline(
            self.state, baseline_id if baseline_id in self.state.loaded else "")
        baseline_ids = [
            self.state.display_to_id.get(name, "")
            for name in self.baseline_multi_displays
        ]
        baseline_ids = [
            sid for sid in baseline_ids if sid in self.state.loaded]
        if baseline_id and baseline_id in self.state.loaded and baseline_id not in baseline_ids:
            baseline_ids.insert(0, baseline_id)
        set_baselines(self.state, baseline_ids)
        set_use_original_binned(self.state, self.use_original_binned_var.get())
        sentinels = parse_sentinels(self.sentinels_var.get())
        outlier_threshold = None
        if self.remove_outliers_var.get():
            try:
                outlier_threshold = float(self.outlier_thresh_var.get())
            except Exception:
                outlier_threshold = None
        outlier_method = self._normalize_outlier_method(
            self.outlier_method_var.get())
        update_cleaning_settings(
            self.state,
            sentinels=sentinels,
            remove_outliers=self.remove_outliers_var.get(),
            outlier_threshold=outlier_threshold,
            outlier_method=outlier_method,
        )

    def _datasets_from_json_obj(self, obj):
        out = []
        if isinstance(obj, dict):
            if "rideData" in obj and isinstance(obj["rideData"], list):
                records = obj["rideData"]
                df = pd.DataFrame(records)
                for c in df.columns:
                    df[c] = pd.to_numeric(df[c], errors="coerce")
                out.append((
                    "Dataset",
                    df,
                    str(obj.get("__source_id__", "")) or "",
                    str(obj.get("__display__", "")) or "",
                ))
                return out

            for name, value in obj.items():
                if isinstance(value, dict) and "rideData" in value and isinstance(value["rideData"], list):
                    records = value["rideData"]
                    df = pd.DataFrame(records)
                    for c in df.columns:
                        df[c] = pd.to_numeric(df[c], errors="coerce")
                    out.append((
                        str(name),
                        df,
                        str(value.get("__source_id__", "")) or "",
                        str(value.get("__display__", "")) or "",
                    ))
                elif isinstance(value, list):
                    records = value
                    if records and not isinstance(records[0], dict):
                        continue
                    df = pd.DataFrame(records)
                    for c in df.columns:
                        df[c] = pd.to_numeric(df[c], errors="coerce")
                    out.append((str(name), df, "", ""))
            if out:
                return out

        datasets = extract_named_datasets(obj)
        for name, records in datasets:
            if not isinstance(records, list) or (len(records) > 0 and not isinstance(records[0], dict)):
                continue
            df = pd.DataFrame(records)
            for c in df.columns:
                df[c] = pd.to_numeric(df[c], errors="coerce")
            out.append((str(name), df, "", ""))
        return out

    def _binned_from_json_obj(self, obj):
        datasets = extract_named_binned_datasets(obj)
        out = {}
        for name, records in datasets:
            if not isinstance(records, list) or (len(records) > 0 and not isinstance(records[0], dict)):
                continue
            df = pd.DataFrame(records)
            for c in df.columns:
                df[c] = pd.to_numeric(df[c], errors="coerce")
            out[str(name)] = df
        return out

    def _sync_ui_from_state_settings(self):
        plot = self.state.plot_settings
        cleaning = self.state.cleaning_settings

        self.plot_type_var.set(plot.plot_type or self.plot_type_var.get())
        self.angle_var.set(plot.angle_column or self.angle_var.get())

        desired_metric = plot.metric_column or ""
        self.agg_var.set({
            "trimmed_mean_10": "10% trimmed mean",
            "pedal_stroke": "pedal stroke",
            "roll_360deg": "roll 360deg",
        }.get(plot.agg_mode, plot.agg_mode or self.agg_var.get()))
        self.value_mode_var.set(plot.value_mode or self.value_mode_var.get())
        self.compare_var.set(bool(plot.compare))
        self.close_loop_var.set(bool(plot.close_loop))
        self.use_plotly_var.set(bool(plot.use_plotly))
        self.radar_background_var.set(bool(plot.radar_background))
        self.range_low_var.set(str(plot.range_low or ""))
        self.range_high_var.set(str(plot.range_high or ""))
        self.range_fixed_var.set(bool(plot.range_fixed))
        self.use_original_binned_var.set(bool(plot.use_original_binned))
        self._update_original_binned_label()

        if cleaning.sentinels:
            self.sentinels_var.set(", ".join(str(v)
                                   for v in cleaning.sentinels))
        self.remove_outliers_var.set(bool(cleaning.remove_outliers))
        self.outlier_thresh_var.set(
            "" if cleaning.outlier_threshold is None else str(cleaning.outlier_threshold))
        self.outlier_method_var.set(
            self._format_outlier_method_label(cleaning.outlier_method))

        self.refresh_metric_choices()
        if desired_metric and desired_metric in self.metric_combo["values"]:
            self.metric_var.set(desired_metric)
        baseline_display = ""
        if plot.baseline_source_id:
            baseline_display = self.state.id_to_display.get(
                plot.baseline_source_id, "")
        if baseline_display:
            self.baseline_display_var.set(baseline_display)

        self.baseline_multi_displays = [
            self.state.id_to_display.get(sid, sid)
            for sid in plot.baseline_source_ids
            if sid in self.state.loaded
        ]
        if not self.baseline_multi_displays and baseline_display:
            self.baseline_multi_displays = [baseline_display]

        self.refresh_baseline_choices()

        self._sync_treeview_from_state()
        self._on_plot_type_change()
        self._set_compare_controls_state()
        self._on_outlier_toggle()
        self._sync_state_settings_from_ui()

    def _build_plot(self):
        right = ttk.Frame(self, padding=10)
        right.grid(row=0, column=1, sticky="nsew")
        right.rowconfigure(1, weight=1)
        right.columnconfigure(0, weight=1)

        ttk.Label(right, text="Plot", font=("Segoe UI", 11, "bold")
                  ).grid(row=0, column=0, sticky="w")

        self.fig = Figure(figsize=(8, 6), dpi=100)
        self.ax = self.fig.add_subplot(111, projection="polar")
        self.ax.set_theta_zero_location("N")
        self.ax.set_theta_direction(-1)

        self.canvas = FigureCanvasTkAgg(self.fig, master=right)
        self.canvas.get_tk_widget().grid(row=1, column=0, sticky="nsew")
        self.canvas.mpl_connect("button_press_event", self._on_plot_click)
        self.canvas.mpl_connect("motion_notify_event", self._on_plot_motion)
        self.canvas.mpl_connect("button_release_event", self._on_plot_release)

        toolbar = NavigationToolbar2Tk(self.canvas, right, pack_toolbar=False)
        toolbar.update()
        toolbar.grid(row=2, column=0, sticky="ew", pady=(6, 0))

        self._redraw_empty()

    def _add_tooltips(self):
        tips = [
            (self.btn_new_project, "Start a new (empty) project."),
            (self.btn_load_project, "Load a saved project JSON file."),
            (self.btn_save_project,
             "Save the current project to a JSON file (optionally include plot history)."),
            (self.btn_guide, "Open the in-app workflow guide."),
            (self.btn_add_files, "Add one or more data files to this project."),
            (self.btn_remove, "Remove the selected dataset(s) from the list."),
            (self.btn_save_data,
             "Save JSON data for datasets currently checked as Show."),
            (self.btn_rename, "Rename the selected dataset."),
            (self.btn_move_up, "Move the selected dataset(s) up in plot order."),
            (self.btn_move_down, "Move the selected dataset(s) down in plot order."),
            (self.files_tree, "Datasets in project/plot order. Rename, select, and reorder here; visibility is controlled on the Plot tab."),
            (self.plot_datasets_tree,
             "Plot-tab datasets in plot order. Click the Show column to toggle plot visibility."),
            (self.paste_text,
             "Paste a JSON dataset object or a multi-dataset JSON blob here."),
            (self.btn_load_paste, "Load datasets from the pasted JSON."),
            (self.btn_save_paste, "Save the pasted JSON to a file."),
            (self.btn_clear_paste, "Clear the pasted JSON text."),
            (self.rb_radar, "Radar (polar) plot using crank angle."),
            (self.rb_cartesian, "Cartesian plot of metric vs crank angle (0-360°)."),
            (self.rb_bar, "Bar plot of mean metric per dataset."),
            (self.rb_timeseries, "Time series plot of full data for metric."),
            (self.chk_plotly, "Open an interactive Plotly plot in your browser."),
            (self.radar_background_chk,
             "Toggle background image/bands\nfor radar/cartesian plots."),
            (self.angle_combo, "Crank angle column used for radar/cartesian plots."),
            (self.close_loop_chk,
             "Close loop by repeating the first point at 360°."),
            (self.metric_combo, "Metric column to plot."),
            (self.agg_combo,
             "Average type depends on plot:\n"
             "Radar/Cartesian: mean, median, 10% trimmed mean.\n"
             "Time series: raw, pedal stroke, or roll 360deg."),
            (self.outlier_chk,
             "Toggle outlier filtering on/off for plotting."),
            (self.outlier_method_combo,
             "Choose outlier method:\n"
             "MAD = global robust z-score.\n"
             "Phase-MAD = robust z-score per crank-angle bin.\n"
             "Hampel = rolling median filter.\n"
             "Impulse = acceleration-based spike detector."),
            (self.outlier_entry,
             "Outlier threshold (default 4.0).\n"
             "Lower = more aggressive removal."),
            (self.outlier_show_chk,
             "Show detected outlier points on the plot."),
            (self.outlier_warnings_chk,
             "When ticked, warnings are shown about likely outliers in plotted data."),
            (self.range_low_entry,
             "Lower y-axis bound for the plot area (used when Fixed is on).\n"
             "Does not change or filter the data."),
            (self.range_high_entry,
             "Upper y-axis bound for the plot area (used when Fixed is on).\n"
             "Does not change or filter the data."),
            (self.range_fixed_chk,
             "Lock the y-range to the chosen values\n(easier to compare different plots)."),
            (self.original_binned_btn,
             "Use the pre-binned 52-row left_pedalstroke_avg data\n"
             "when available (radar/cartesian/bar only).\n"
             "Radar/Cartesian compare mode uses the baseline dataset's\n"
             "bin angles and matches other datasets by bin index."),
            (self.rb_absolute, "Plot absolute metric values."),
            (self.rb_percent_mean,
             "Plot values as percent of dataset mean (radar/cartesian only)."),
            (self.chk_compare,
             "Plot each dataset as a difference from the selected baseline."),
            (self.baseline_menu_btn,
             "Choose one or more baseline datasets for comparison mode."),
            (self.plot_btn, "Plot or refresh using current settings."),
            (self.export_plot_btn, "Export the currently displayed plot data to CSV."),
            (self.prev_btn, "Go to the previous plot in history."),
            (self.delete_btn, "Remove the current plot from history."),
            (self.next_btn, "Go to the next plot in history."),
            (self.clear_history_btn, "Clear all plot history entries."),
            (self.history_label, "Current position within the plot history."),
            (self.btn_new_report, "Create a new report file for plot snapshots."),
            (self.btn_open_report, "Open an existing report JSON file."),
            (self.btn_view_report, "Preview the current report in your browser."),
            (self.btn_save_report, "Save the current report JSON file."),
            (self.chk_report_include_meta,
             "When checked, preview/export includes report metadata (data sources, plot settings, dates)."),
            (self.btn_export_report_html,
             "Export the report to a shareable HTML file."),
            (self.btn_export_report_pdf,
             "Export the report to a PDF (requires reportlab)."),
            (self.btn_add_snapshot,
             "Add the current plot (with annotations) to the report."),
            (self.btn_add_text_block,
             "Add report content (text, rich text/HTML, images) not tied to a plot snapshot."),
            (self.btn_manage_report,
             "Edit, remove, and reorder report snapshots and text blocks."),
            (self.chk_annotate, "Enable click-to-add text annotations on the plot."),
            (self.btn_clear_annotations,
             "Remove all annotations from the current plot."),
        ]
        for widget, text in tips:
            ToolTip(widget, text)

    def _redraw_empty(self):
        self._reset_plot_hover_state(redraw=False)
        if getattr(self.ax, "name", "") != "polar":
            self.fig.clf()
            self.ax = self.fig.add_subplot(111, projection="polar")
        self.ax.clear()
        self.ax.set_theta_zero_location("N")
        self.ax.set_theta_direction(-1)
        self.ax.set_title("Load data → choose metric & angle → Plot", pad=18)
        self.ax.grid(True)
        # self.ax.set_position([0.05, 0.08, 0.8, 0.8])
        self.canvas.draw_idle()

    def _reset_plot_hover_state(self, redraw: bool = False) -> None:
        self._plot_hover_targets = []
        for attr in ("_plot_hover_annotation", "_plot_selected_marker"):
            artist = getattr(self, attr, None)
            if artist is None:
                continue
            try:
                artist.remove()
            except Exception:
                pass
            setattr(self, attr, None)
        if redraw:
            self.canvas.draw_idle()

    def _register_line_hover_trace(self, line, *, label: str, source_id: str = "",
                                   x_display=None, y_values=None) -> None:
        if line is None:
            return
        try:
            x_values = np.asarray(line.get_xdata(), dtype=float)
            y_line = np.asarray(line.get_ydata(), dtype=float)
        except Exception:
            return
        if x_values.size == 0 or y_line.size == 0:
            return
        y_display = y_line if y_values is None else np.asarray(
            y_values, dtype=float)
        if y_display.size != y_line.size:
            y_display = y_line
        if x_display is None:
            x_disp = x_values
        else:
            x_disp = np.asarray(x_display)
            if x_disp.size != x_values.size:
                x_disp = x_values
        self._plot_hover_targets.append({
            "kind": "line",
            "artist": line,
            "label": str(label or ""),
            "source_id": str(source_id or ""),
            "x_data": x_values,
            "y_data": y_line,
            "x_display": x_disp,
            "y_display": y_display,
        })

    def _register_bar_hover_targets(self, bars, labels, values) -> None:
        for bar, label, y_val in zip(list(bars), list(labels), np.asarray(values, dtype=float)):
            try:
                x_pos = float(bar.get_x() + (bar.get_width() / 2.0))
            except Exception:
                continue
            self._plot_hover_targets.append({
                "kind": "bar",
                "artist": bar,
                "label": str(label or ""),
                "x_data": x_pos,
                "y_data": float(y_val),
                "x_display": str(label or ""),
                "y_display": float(y_val),
            })

    def _format_probe_value(self, value) -> str:
        if isinstance(value, (str, bytes)):
            return str(value)
        try:
            num = float(value)
        except Exception:
            return str(value)
        if not np.isfinite(num):
            return str(value)
        return f"{num:.6g}"

    def _probe_text_for_hit(self, hit: dict) -> str:
        label = str(hit.get("label", "") or "Point")
        x_text = self._format_probe_value(
            hit.get("x_display", hit.get("x_data")))
        y_text = self._format_probe_value(
            hit.get("y_display", hit.get("y_data")))
        return f"{label}\nx: {x_text}\ny: {y_text}"

    def _hit_test_plot_point(self, event) -> dict | None:
        if getattr(event, "inaxes", None) != self.ax:
            return None
        ex = getattr(event, "x", None)
        ey = getattr(event, "y", None)
        if ex is None or ey is None:
            return None
        best = None
        best_dist = None
        for target in reversed(list(self._plot_hover_targets)):
            artist = target.get("artist")
            if artist is None:
                continue
            try:
                contains, details = artist.contains(event)
            except Exception:
                continue
            if not contains:
                continue
            kind = target.get("kind")
            if kind == "line":
                inds_raw = details.get("ind") if isinstance(details, dict) else None
                if inds_raw is None:
                    inds = []
                else:
                    try:
                        inds = list(inds_raw)
                    except Exception:
                        inds = [inds_raw]
                if not inds:
                    continue
                x_vals = target.get("x_data")
                y_vals = target.get("y_data")
                x_disp_vals = target.get("x_display")
                y_disp_vals = target.get("y_display")
                for idx in inds:
                    if idx < 0 or idx >= len(x_vals) or idx >= len(y_vals):
                        continue
                    try:
                        px, py = artist.axes.transData.transform(
                            (x_vals[idx], y_vals[idx]))
                        dist = ((float(px) - float(ex)) ** 2 +
                                (float(py) - float(ey)) ** 2) ** 0.5
                    except Exception:
                        dist = 0.0
                    if best_dist is None or dist < best_dist:
                        best_dist = dist
                        best = {
                            "kind": "line",
                            "target": target,
                            "artist": artist,
                            "index": int(idx),
                            "x_data": float(x_vals[idx]),
                            "y_data": float(y_vals[idx]),
                            "x_display": x_disp_vals[idx] if idx < len(x_disp_vals) else x_vals[idx],
                            "y_display": y_disp_vals[idx] if idx < len(y_disp_vals) else y_vals[idx],
                            "label": target.get("label", ""),
                        }
            elif kind == "bar":
                x_val = float(target.get("x_data", 0.0))
                y_val = float(target.get("y_data", 0.0))
                try:
                    px, py = artist.axes.transData.transform((x_val, y_val))
                    dist = ((float(px) - float(ex)) ** 2 +
                            (float(py) - float(ey)) ** 2) ** 0.5
                except Exception:
                    dist = 0.0
                if best_dist is None or dist < best_dist:
                    best_dist = dist
                    best = {
                        "kind": "bar",
                        "target": target,
                        "artist": artist,
                        "index": 0,
                        "x_data": x_val,
                        "y_data": y_val,
                        "x_display": target.get("x_display", x_val),
                        "y_display": target.get("y_display", y_val),
                        "label": target.get("label", ""),
                    }
        return best

    def _update_plot_hover_tooltip(self, event) -> None:
        if self.use_plotly_var.get():
            return
        hit = self._hit_test_plot_point(event)
        ann = self._plot_hover_annotation
        if hit is None:
            if ann is not None and ann.get_visible():
                ann.set_visible(False)
                self.canvas.draw_idle()
            return
        if ann is None or getattr(ann, "axes", None) != self.ax:
            try:
                ann = self.ax.annotate(
                    "",
                    xy=(0, 0),
                    xytext=(10, 10),
                    textcoords="offset points",
                    ha="left",
                    va="bottom",
                    fontsize=8,
                    color="#111111",
                    bbox=dict(boxstyle="round,pad=0.2", fc="#fffff2",
                              ec="#999999", alpha=0.95),
                    zorder=20,
                )
                ann.set_visible(False)
                self._plot_hover_annotation = ann
            except Exception:
                return
        ann.xy = (hit["x_data"], hit["y_data"])
        ann.set_text(self._probe_text_for_hit(hit))
        ann.set_visible(True)
        self.canvas.draw_idle()

    def _set_selected_plot_point(self, hit: dict | None) -> None:
        marker = self._plot_selected_marker
        if hit is None:
            if marker is not None:
                try:
                    marker.remove()
                except Exception:
                    pass
                self._plot_selected_marker = None
                self.canvas.draw_idle()
            return
        if marker is None or getattr(marker, "axes", None) != self.ax:
            try:
                marker = self.ax.scatter(
                    [hit["x_data"]],
                    [hit["y_data"]],
                    s=80,
                    facecolors="none",
                    edgecolors="#111111",
                    linewidths=1.3,
                    zorder=19,
                )
                self._plot_selected_marker = marker
            except Exception:
                return
        else:
            try:
                marker.set_offsets(
                    np.array([[hit["x_data"], hit["y_data"]]], dtype=float))
            except Exception:
                try:
                    marker.remove()
                except Exception:
                    pass
                self._plot_selected_marker = None
                return
        self.canvas.draw_idle()

    def _warn_fixed_range_no_data(self, values, fixed_range, context: str) -> None:
        if not fixed_range:
            return
        try:
            arr = np.asarray(values, dtype=float)
        except Exception:
            return
        if arr.size == 0:
            return
        finite = arr[np.isfinite(arr)]
        if finite.size == 0:
            return
        low, high = fixed_range
        if finite.max() < low or finite.min() > high:
            messagebox.showwarning(
                "Fixed range hides data",
                f"All {context} values are outside the fixed range [{low}, {high}].\n\n"
                "Clear Fixed range or adjust the bounds to see the plot.",
            )

    def _collect_trace_values(self, traces, offset: float = 0.0, skip_baseline: bool = False):
        values = []
        for trace in traces:
            if skip_baseline and getattr(trace, "is_baseline", False):
                continue
            try:
                vals = np.asarray(trace.y, dtype=float)
            except Exception:
                continue
            if offset:
                vals = vals - offset
            values.append(vals)
        if not values:
            return np.array([])
        return np.concatenate(values)

    def _default_annotation_format(self) -> dict[str, object]:
        return {
            "font_family": "Segoe UI",
            "font_size": 12,
            "bold": False,
            "italic": False,
            "text_color": "blue",
            "arrow_color": "blue",
            "offset_x": 20,
            "offset_y": 40,
        }

    def _is_valid_annotation_color(self, value: str) -> bool:
        try:
            return bool(value) and bool(matplotlib.colors.is_color_like(value))
        except Exception:
            return False

    def _normalize_annotation_format(self, obj) -> dict[str, object]:
        fmt = dict(self._default_annotation_format())
        if not isinstance(obj, dict):
            return fmt

        font_family = str(obj.get("font_family") or "").strip()
        if font_family:
            fmt["font_family"] = font_family

        try:
            font_size = int(obj.get("font_size"))
            if font_size >= 6:
                fmt["font_size"] = min(font_size, 72)
        except Exception:
            pass

        fmt["bold"] = bool(obj.get("bold"))
        fmt["italic"] = bool(obj.get("italic"))

        for key in ["text_color", "arrow_color"]:
            color = str(obj.get(key) or "").strip()
            if color and self._is_valid_annotation_color(color):
                fmt[key] = color

        for key in ["offset_x", "offset_y"]:
            try:
                value = int(obj.get(key))
                fmt[key] = max(-150, min(150, value))
            except Exception:
                pass
        return fmt

    def _annotation_font_weight(self, fmt: dict[str, object]) -> str:
        return "bold" if bool(fmt.get("bold")) else "normal"

    def _annotation_font_style(self, fmt: dict[str, object]) -> str:
        return "italic" if bool(fmt.get("italic")) else "normal"

    def _annotation_format_payload(self) -> dict[str, object]:
        return self._normalize_annotation_format(self._annotation_format)

    def _remember_annotation_format(self) -> None:
        payload = self._annotation_format_payload()
        self._annotation_format = dict(payload)
        if self.report_state is not None:
            self.report_state["annotation_format"] = dict(payload)
            self._report_dirty = True
        self.state.analysis_settings.report_options["annotation_format"] = json.dumps(
            payload)

    def _load_annotation_format_from_project_options(self) -> None:
        raw = self.state.analysis_settings.report_options.get(
            "annotation_format", "")
        if not raw:
            return
        try:
            payload = json.loads(raw)
        except Exception:
            return
        self._annotation_format = self._normalize_annotation_format(payload)

    def _apply_report_annotation_format(self) -> None:
        if not isinstance(self.report_state, dict):
            return
        if "annotation_format" not in self.report_state:
            return
        payload = self._normalize_annotation_format(
            self.report_state.get("annotation_format", {}))
        self._annotation_format = dict(payload)
        self.state.analysis_settings.report_options["annotation_format"] = json.dumps(
            payload)

    def _prompt_annotation_format_dialog(
        self,
        initial: dict[str, object] | None = None,
        *,
        title: str = "Annotation format",
    ) -> dict[str, object] | None:
        initial = self._normalize_annotation_format(
            initial if isinstance(
                initial, dict) else self._annotation_format_payload()
        )
        dialog = tk.Toplevel(self)
        dialog.title(title)
        dialog.transient(self)
        dialog.grab_set()
        dialog.geometry("430x360")
        self._center_dialog(dialog)

        container = ttk.Frame(dialog, padding=10)
        container.pack(fill="both", expand=True)

        ttk.Label(container, text="Font family:").grid(
            row=0, column=0, sticky="w")
        families = sorted(set(tkfont.families(self)))
        if not families:
            families = [str(initial.get("font_family") or "Segoe UI")]
        font_family_var = tk.StringVar(
            value=str(initial.get("font_family") or families[0]))
        family_combo = ttk.Combobox(
            container, textvariable=font_family_var, values=families, state="normal")
        family_combo.grid(row=1, column=0, columnspan=2,
                          sticky="ew", pady=(2, 8))

        ttk.Label(container, text="Font size:").grid(
            row=2, column=0, sticky="w")
        font_size_var = tk.StringVar(value=str(initial.get("font_size", 9)))
        ttk.Entry(container, textvariable=font_size_var,
                  width=8).grid(row=2, column=1, sticky="w")

        bold_var = tk.BooleanVar(value=bool(initial.get("bold")))
        italic_var = tk.BooleanVar(value=bool(initial.get("italic")))
        ttk.Checkbutton(container, text="Bold", variable=bold_var).grid(
            row=3, column=0, sticky="w", pady=(8, 0))
        ttk.Checkbutton(container, text="Italic", variable=italic_var).grid(
            row=3, column=1, sticky="w", pady=(8, 0))

        text_color_var = tk.StringVar(
            value=str(initial.get("text_color") or "#111111"))
        arrow_color_var = tk.StringVar(
            value=str(initial.get("arrow_color") or "#333333"))

        def _pick_color(var: tk.StringVar) -> None:
            chosen = colorchooser.askcolor(color=var.get(), parent=dialog)
            if chosen and chosen[1]:
                var.set(str(chosen[1]))

        ttk.Label(container, text="Text colour:").grid(
            row=4, column=0, sticky="w", pady=(10, 0))
        color_row1 = ttk.Frame(container)
        color_row1.grid(row=5, column=0, columnspan=2,
                        sticky="ew", pady=(2, 6))
        ttk.Entry(color_row1, textvariable=text_color_var,
                  width=16).pack(side="left")
        ttk.Button(color_row1, text="Choose…", command=lambda: _pick_color(
            text_color_var)).pack(side="left", padx=(6, 0))

        ttk.Label(container, text="Arrow colour:").grid(
            row=6, column=0, sticky="w")
        color_row2 = ttk.Frame(container)
        color_row2.grid(row=7, column=0, columnspan=2,
                        sticky="ew", pady=(2, 8))
        ttk.Entry(color_row2, textvariable=arrow_color_var,
                  width=16).pack(side="left")
        ttk.Button(color_row2, text="Choose…", command=lambda: _pick_color(
            arrow_color_var)).pack(side="left", padx=(6, 0))

        ttk.Label(container, text="Caption offset relative to selected point (points):").grid(
            row=8, column=0, columnspan=2, sticky="w")
        offset_row = ttk.Frame(container)
        offset_row.grid(row=9, column=0, columnspan=2, sticky="w", pady=(2, 8))
        ttk.Label(offset_row, text="X:").pack(side="left")
        offset_x_var = tk.StringVar(value=str(initial.get("offset_x", 8)))
        ttk.Entry(offset_row, textvariable=offset_x_var,
                  width=7).pack(side="left", padx=(2, 10))
        ttk.Label(offset_row, text="Y:").pack(side="left")
        offset_y_var = tk.StringVar(value=str(initial.get("offset_y", 8)))
        ttk.Entry(offset_row, textvariable=offset_y_var,
                  width=7).pack(side="left", padx=(2, 0))

        btns = ttk.Frame(container)
        btns.grid(row=10, column=0, columnspan=2, sticky="ew", pady=(8, 0))
        result = {"ok": False}

        def _confirm():
            result["ok"] = True
            dialog.destroy()

        def _cancel():
            dialog.destroy()

        ttk.Button(btns, text="Cancel", command=_cancel).pack(side="right")
        ttk.Button(btns, text="Apply", command=_confirm).pack(
            side="right", padx=(0, 6))

        container.columnconfigure(0, weight=1)
        dialog.bind("<Escape>", lambda _e: _cancel(), add=True)
        dialog.protocol("WM_DELETE_WINDOW", _cancel)
        family_combo.focus_set()
        self.wait_window(dialog)

        if not result["ok"]:
            return None

        updated = {
            "font_family": font_family_var.get().strip() or str(initial.get("font_family") or "Segoe UI"),
            "font_size": font_size_var.get().strip(),
            "bold": bool(bold_var.get()),
            "italic": bool(italic_var.get()),
            "text_color": text_color_var.get().strip() or str(initial.get("text_color") or "#111111"),
            "arrow_color": arrow_color_var.get().strip() or str(initial.get("arrow_color") or "#333333"),
            "offset_x": offset_x_var.get().strip(),
            "offset_y": offset_y_var.get().strip(),
        }
        return self._normalize_annotation_format(updated)

    def configure_annotation_format(self) -> None:
        updated = self._prompt_annotation_format_dialog()
        if not updated:
            return
        self._annotation_format = dict(updated)
        self._remember_annotation_format()
        self.status.set("Updated default annotation format.")

    # ---------------- Annotations ----------------
    def _on_annotation_toggle(self):
        if self.annotation_mode_var.get() and self.use_plotly_var.get():
            self.annotation_mode_var.set(False)
            messagebox.showinfo(
                "Annotations unavailable",
                "Annotations are only supported on the embedded Matplotlib plot.\n\n"
                "Turn off Plotly (Interactive) to annotate.",
            )
            return
        if self.annotation_mode_var.get():
            self.status.set(
                "Annotation mode on: click the plot to add a label.")
        else:
            self.status.set("Annotation mode off.")

    def _reset_annotations(self, redraw: bool = True) -> None:
        self._annotation_drag_state = None
        for artist in list(self._annotation_artists):
            try:
                artist.remove()
            except Exception:
                pass
        self._annotation_artists.clear()
        self._annotations.clear()
        if redraw:
            self.canvas.draw_idle()

    def clear_annotations(self):
        if not self._annotations:
            return
        confirm = messagebox.askyesno(
            "Clear annotations",
            "Remove all annotations from the current plot?",
        )
        if not confirm:
            return
        self._reset_annotations()

    def _prompt_annotation_text(self, title: str, initial_text: str = "") -> str | None:
        dialog = tk.Toplevel(self)
        dialog.title(title)
        dialog.transient(self)
        dialog.grab_set()
        dialog.geometry("420x260")
        self._center_dialog(dialog)

        container = ttk.Frame(dialog, padding=10)
        container.pack(fill="both", expand=True)

        ttk.Label(container, text="Annotation text:").pack(anchor="w")
        text_widget = tk.Text(container, height=5, wrap="word")
        text_widget.pack(fill="both", expand=True, pady=(2, 10))
        if initial_text:
            text_widget.insert("1.0", initial_text)

        hint = ttk.Label(
            container,
            text="Format? updates the default font/arrow settings for new annotations.",
            foreground="#555",
        )
        hint.pack(anchor="w")

        btns = ttk.Frame(container)
        btns.pack(fill="x", pady=(10, 0))
        result = {"ok": False, "text": None}

        def _confirm():
            result["ok"] = True
            result["text"] = text_widget.get("1.0", "end").strip()
            dialog.destroy()

        def _cancel():
            dialog.destroy()

        def _format():
            self.configure_annotation_format()

        ttk.Button(btns, text="Cancel", command=_cancel).pack(side="right")
        ttk.Button(btns, text="Add", command=_confirm).pack(
            side="right", padx=(0, 6))
        ttk.Button(btns, text="Format?", command=_format).pack(side="left")

        dialog.bind("<Escape>", lambda _e: _cancel(), add=True)
        dialog.protocol("WM_DELETE_WINDOW", _cancel)
        text_widget.focus_set()
        self.wait_window(dialog)

        if not result["ok"]:
            return None
        text = result.get("text")
        return text if text else None

    def _prompt_annotation_edit(
        self,
        initial_text: str,
        on_format=None,
    ) -> tuple[str, str | None]:
        dialog = tk.Toplevel(self)
        dialog.title("Edit annotation")
        dialog.transient(self)
        dialog.grab_set()
        dialog.geometry("420x280")
        self._center_dialog(dialog)

        container = ttk.Frame(dialog, padding=10)
        container.pack(fill="both", expand=True)

        ttk.Label(container, text="Annotation text:").pack(anchor="w")
        text_widget = tk.Text(container, height=5, wrap="word")
        text_widget.pack(fill="both", expand=True, pady=(2, 10))
        if initial_text:
            text_widget.insert("1.0", initial_text)

        if callable(on_format):
            hint = ttk.Label(
                container,
                text="Format... updates the selected annotation's font/arrow style.",
                foreground="#555",
            )
            hint.pack(anchor="w")

        btns = ttk.Frame(container)
        btns.pack(fill="x", pady=(10, 0))
        result = {"action": "cancel", "text": None}

        def _update():
            result["action"] = "update"
            result["text"] = text_widget.get("1.0", "end").strip()
            dialog.destroy()

        def _delete():
            result["action"] = "delete"
            dialog.destroy()

        def _cancel():
            dialog.destroy()

        def _format():
            try:
                on_format()
            except Exception:
                pass

        ttk.Button(btns, text="Cancel", command=_cancel).pack(side="right")
        ttk.Button(btns, text="Update", command=_update).pack(
            side="right", padx=(0, 6))
        ttk.Button(btns, text="Delete", command=_delete).pack(side="left")
        if callable(on_format):
            ttk.Button(btns, text="Format...", command=_format).pack(
                side="left", padx=(6, 0))

        dialog.bind("<Escape>", lambda _e: _cancel(), add=True)
        dialog.protocol("WM_DELETE_WINDOW", _cancel)
        text_widget.focus_set()
        self.wait_window(dialog)

        return result["action"], result["text"]

    def _find_annotation_index(self, event) -> int | None:
        for idx, artist in enumerate(list(self._annotation_artists)):
            try:
                contains, _ = artist.contains(event)
            except Exception:
                continue
            if contains:
                return idx
        return None

    def _remove_annotation_at(self, index: int) -> None:
        if index < 0 or index >= len(self._annotation_artists):
            return
        artist = self._annotation_artists.pop(index)
        try:
            artist.remove()
        except Exception:
            pass
        if index < len(self._annotations):
            self._annotations.pop(index)
        self.canvas.draw_idle()

    def _start_annotation_drag(self, index: int, event) -> None:
        if index < 0 or index >= len(self._annotation_artists):
            return
        artist = self._annotation_artists[index]
        try:
            start_offset = artist.get_position()
        except Exception:
            start_offset = (20, 40)
        self._annotation_drag_state = {
            "index": index,
            "artist": artist,
            "press_x": float(getattr(event, "x", 0.0) or 0.0),
            "press_y": float(getattr(event, "y", 0.0) or 0.0),
            "start_offset": (float(start_offset[0]), float(start_offset[1])),
            "dragged": False,
        }

    def _annotation_drag_threshold_px(self) -> float:
        return 4.0

    def _on_plot_motion(self, event):
        drag = self._annotation_drag_state
        if not isinstance(drag, dict):
            self._update_plot_hover_tooltip(event)
            return
        artist = drag.get("artist")
        if artist is None:
            self._update_plot_hover_tooltip(event)
            return
        ex = getattr(event, "x", None)
        ey = getattr(event, "y", None)
        if ex is None or ey is None:
            return
        dx_px = float(ex) - float(drag.get("press_x", 0.0))
        dy_px = float(ey) - float(drag.get("press_y", 0.0))
        if (not drag.get("dragged")) and (
            (dx_px * dx_px + dy_px * dy_px) ** 0.5 < self._annotation_drag_threshold_px()
        ):
            return
        drag["dragged"] = True
        dpi = float(getattr(self.fig, "dpi", 100) or 100.0)
        scale = 72.0 / dpi
        start_x, start_y = drag.get("start_offset", (20.0, 40.0))
        new_x = start_x + (dx_px * scale)
        new_y = start_y + (dy_px * scale)
        try:
            artist.set_position((new_x, new_y))
        except Exception:
            return
        self.canvas.draw_idle()

    def _on_plot_release(self, event):
        drag = self._annotation_drag_state
        self._annotation_drag_state = None
        if not isinstance(drag, dict):
            return
        index = int(drag.get("index", -1))
        if index < 0 or index >= len(self._annotation_artists):
            return
        if not drag.get("dragged"):
            self._edit_annotation_at(index)
            return
        artist = self._annotation_artists[index]
        try:
            offset_x, offset_y = artist.get_position()
        except Exception:
            return
        fmt = self._annotation_format_payload()
        if index < len(self._annotations) and isinstance(self._annotations[index], dict):
            fmt = self._normalize_annotation_format(
                self._annotations[index].get("format", {}))
            self._annotations[index]["format"] = dict(fmt)
        fmt["offset_x"] = int(round(float(offset_x)))
        fmt["offset_y"] = int(round(float(offset_y)))
        fmt = self._normalize_annotation_format(fmt)
        if index < len(self._annotations) and isinstance(self._annotations[index], dict):
            self._annotations[index]["format"] = dict(fmt)
        try:
            artist.set_position((int(fmt["offset_x"]), int(fmt["offset_y"])))
        except Exception:
            pass
        self.canvas.draw_idle()
        self.status.set("Moved annotation.")

    def _edit_annotation_at(self, index: int) -> None:
        if index < 0 or index >= len(self._annotation_artists):
            return
        current_text = ""
        if index < len(self._annotations):
            current_text = str(self._annotations[index].get("text", ""))
        else:
            try:
                current_text = str(self._annotation_artists[index].get_text())
            except Exception:
                current_text = ""

        def _annotation_format_for_index() -> dict[str, object]:
            if index < len(self._annotations):
                item = self._annotations[index]
                if isinstance(item, dict):
                    return self._normalize_annotation_format(item.get("format", {}))
            return self._annotation_format_payload()

        def _apply_annotation_artist_format(artist, fmt: dict[str, object]) -> None:
            artist.set_fontsize(int(fmt.get("font_size", 14)))
            artist.set_color(str(fmt.get("text_color") or "blue"))
            artist.set_fontname(str(fmt.get("font_family") or "Segoe UI"))
            artist.set_fontweight(self._annotation_font_weight(fmt))
            artist.set_fontstyle(self._annotation_font_style(fmt))
            try:
                artist.set_position(
                    (int(fmt.get("offset_x", 20)), int(fmt.get("offset_y", 40)))
                )
            except Exception:
                pass
            arrow_patch = getattr(artist, "arrow_patch", None)
            if arrow_patch is not None:
                try:
                    arrow_patch.set_color(
                        str(fmt.get("arrow_color") or "blue"))
                except Exception:
                    try:
                        arrow_patch.set_edgecolor(
                            str(fmt.get("arrow_color") or "blue"))
                    except Exception:
                        pass

        def _format_selected_annotation() -> None:
            current_fmt = _annotation_format_for_index()
            updated_fmt = self._prompt_annotation_format_dialog(
                current_fmt,
                title="Annotation format (selected annotation)",
            )
            if not updated_fmt:
                return
            try:
                _apply_annotation_artist_format(
                    self._annotation_artists[index], updated_fmt)
            except Exception:
                return
            if index < len(self._annotations) and isinstance(self._annotations[index], dict):
                self._annotations[index]["format"] = dict(updated_fmt)
            self.canvas.draw_idle()
            self.status.set("Updated selected annotation format.")

        action, updated_text = self._prompt_annotation_edit(
            current_text,
            on_format=_format_selected_annotation,
        )
        if action == "delete":
            self._remove_annotation_at(index)
            return
        if action != "update":
            return
        if not updated_text:
            return
        try:
            self._annotation_artists[index].set_text(updated_text)
        except Exception:
            return
        if index < len(self._annotations):
            self._annotations[index]["text"] = updated_text
        self.canvas.draw_idle()

    def _on_plot_click(self, event):
        if self.use_plotly_var.get():
            return
        if getattr(event, "button", None) not in (1, None):
            return
        if event.inaxes != self.ax:
            return
        existing_index = self._find_annotation_index(event)
        if existing_index is not None:
            self._start_annotation_drag(existing_index, event)
            return
        if not self.annotation_mode_var.get():
            hit = self._hit_test_plot_point(event)
            self._set_selected_plot_point(hit)
            if hit is not None:
                self.status.set(
                    f"Selected {hit.get('label') or 'point'} (x={self._format_probe_value(hit.get('x_display'))}, y={self._format_probe_value(hit.get('y_display'))})"
                )
            return
        if event.xdata is None or event.ydata is None:
            return
        text = self._prompt_annotation_text("Add annotation")
        if not text:
            return
        fmt = self._annotation_format_payload()
        annotation = self.ax.annotate(
            text,
            xy=(event.xdata, event.ydata),
            xytext=(int(fmt.get("offset_x", 8)), int(fmt.get("offset_y", 8))),
            textcoords="offset points",
            arrowprops=dict(
                arrowstyle="->",
                color=str(fmt.get("arrow_color") or "#333333"),
                linewidth=1,
            ),
            fontsize=int(fmt.get("font_size", 9)),
            color=str(fmt.get("text_color") or "#111111"),
            fontname=str(fmt.get("font_family") or "Segoe UI"),
            fontweight=self._annotation_font_weight(fmt),
            fontstyle=self._annotation_font_style(fmt),
            bbox=dict(boxstyle="round,pad=0.2",
                      fc="white", ec="#999999", alpha=0.8),
        )
        self._annotation_artists.append(annotation)
        self._annotations.append(
            {
                "text": text,
                "x": float(event.xdata),
                "y": float(event.ydata),
                "coords": "data",
                "plot_type": (self.plot_type_var.get() or "").strip().lower(),
                "format": dict(fmt),
            }
        )
        self.canvas.draw_idle()

    # ---------------- Report helpers ----------------
    def _report_data_sources(self) -> list[dict[str, str]]:
        sources = []
        for sid in ordered_source_ids(self.state):
            sources.append(
                {
                    "source_id": sid,
                    "display": self.state.id_to_display.get(sid, sid),
                }
            )
        return sources

    def _ensure_report_state(self) -> bool:
        if self.report_state:
            if "annotation_format" not in self.report_state:
                self.report_state["annotation_format"] = self._annotation_format_payload(
                )
                self._report_dirty = True
            self._ensure_report_snapshots_list()
            return True
        confirm = messagebox.askyesno(
            "Create report",
            "No report is open. Create a new report now?",
        )
        if not confirm:
            return False
        return self.new_report()

    def _ensure_report_snapshots_list(self) -> list:
        if not isinstance(self.report_state, dict):
            return []
        snapshots = self.report_state.get("snapshots")
        if isinstance(snapshots, list):
            return snapshots
        self.report_state["snapshots"] = []
        self._report_dirty = True
        return self.report_state["snapshots"]

    def _report_item_kind(self, item: dict) -> str:
        if not isinstance(item, dict):
            return "snapshot"
        kind = str(item.get("kind", "snapshot")).strip().lower()
        if kind in {"text", "snapshot"}:
            return kind
        return "snapshot"

    def _report_item_display_label(self, item: dict, index: int) -> str:
        if not isinstance(item, dict):
            return f"{index + 1}. [invalid item]"
        kind = self._report_item_kind(item)
        if kind == "text":
            fmt = str(item.get("content_format", "text")).strip().lower()
            kind_label = "HTML" if fmt == "html" else "Text"
        else:
            kind_label = "Snapshot"
        title = str(item.get("title", "")).strip()
        if kind == "snapshot" and not title:
            title = str(item.get("plot_title", "")).strip()
        if not title:
            title = kind_label
        created_at = str(item.get("created_at", "")).strip()
        created_date = created_at.split("T", 1)[0] if created_at else ""
        suffix = f" ({created_date})" if created_date else ""
        return f"{index + 1}. [{kind_label}] {title}{suffix}"

    def _autosave_report_if_path(self) -> bool:
        if not self.report_path or not self.report_state:
            return True
        try:
            save_report_file(self.report_state, self.report_path)
        except Exception as exc:
            messagebox.showerror("Report", f"Failed to save report:\n{exc}")
            return False
        self._report_dirty = False
        return True

    def _prompt_save_report_if_dirty(self, action_label: str) -> bool:
        if not self.report_state or not self._report_dirty:
            return True
        choice = messagebox.askyesnocancel(
            "Unsaved report",
            f"The current report has unsaved changes.\n\nSave before {action_label}?",
        )
        if choice is None:
            return False
        if choice:
            return self.save_report()
        return True

    def _report_include_meta_enabled(self) -> bool:
        if isinstance(self.report_state, dict):
            raw = self.report_state.get("include_meta")
            if isinstance(raw, bool):
                return raw
        return bool(self.report_hide_meta_var.get())

    def _sync_report_meta_toggle_from_state(self) -> None:
        include_meta = False
        if isinstance(self.report_state, dict):
            raw = self.report_state.get("include_meta")
            if isinstance(raw, bool):
                include_meta = raw
            else:
                self.report_state["include_meta"] = include_meta
                self._report_dirty = True
        self.report_hide_meta_var.set(include_meta)

    def _on_report_include_meta_toggle(self) -> None:
        if not isinstance(self.report_state, dict):
            return
        include_meta = bool(self.report_hide_meta_var.get())
        if self.report_state.get("include_meta") != include_meta:
            self.report_state["include_meta"] = include_meta
            self._report_dirty = True

    def _prompt_report_save_path(self) -> str:
        if not self._ensure_project_title():
            return ""
        default_name = f"{self._sanitize_filename(self.project_title)}.rep.json"
        initial_dir = os.path.dirname(
            self.report_path) if self.report_path else ""
        initial_name = os.path.basename(
            self.report_path) if self.report_path else default_name
        out_path = filedialog.asksaveasfilename(
            title="Save report",
            defaultextension=".rep.json",
            initialdir=initial_dir or None,
            initialfile=initial_name,
            filetypes=[("Report (.rep.json)", ("*.rep.json",)),
                       ("JSON", ("*.json",)),
                       ("All files", ("*.*",))],
        )
        return out_path or ""

    def _current_report_assets_dir(self) -> str:
        if self.report_path:
            assets_dir = report_assets_dir(self.report_path)
            os.makedirs(assets_dir, exist_ok=True)
            return assets_dir
        if not self._report_temp_assets_dir:
            base_dir = os.path.join(
                os.path.expanduser("~"),
                ".dashboard_data_plotter",
                "reports",
            )
            os.makedirs(base_dir, exist_ok=True)
            stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            self._report_temp_assets_dir = os.path.join(
                base_dir, f"unsaved_{stamp}_{uuid.uuid4().hex[:6]}"
            )
            os.makedirs(self._report_temp_assets_dir, exist_ok=True)
        return self._report_temp_assets_dir

    def _ensure_report_path(self) -> bool:
        out_path = self._prompt_report_save_path()
        if not out_path:
            return False
        prior_path = self.report_path
        self.report_path = out_path
        assets_dir = report_assets_dir(out_path)
        os.makedirs(assets_dir, exist_ok=True)
        if prior_path and prior_path != out_path:
            old_assets = report_assets_dir(prior_path)
        else:
            old_assets = self._report_temp_assets_dir
        if old_assets and os.path.isdir(old_assets):
            for name in os.listdir(old_assets):
                src_path = os.path.join(old_assets, name)
                dst_path = os.path.join(assets_dir, name)
                if os.path.isfile(src_path):
                    shutil.copy2(src_path, dst_path)
        return True

    def new_report(self) -> bool:
        if not self._prompt_save_report_if_dirty("creating a new report"):
            return False
        dialog = tk.Toplevel(self)
        dialog.title("New report")
        dialog.transient(self)
        dialog.grab_set()
        dialog.geometry("520x220")
        self._center_dialog(dialog)

        container = ttk.Frame(dialog, padding=10)
        container.pack(fill="both", expand=True)

        ttk.Label(container, text="Report title:").pack(anchor="w")
        title_var = tk.StringVar(
            value=self.project_title or "Untitled Project")
        title_entry = ttk.Entry(container, textvariable=title_var)
        title_entry.pack(fill="x", pady=(2, 8))

        ttk.Label(
            container,
            text="New report prepared. Please add plot snapshots and/or text blocks.",
            wraplength=480,
            foreground="#444",
        ).pack(anchor="w", pady=(0, 12))

        btns = ttk.Frame(container)
        btns.pack(fill="x", pady=(6, 0))
        result = {"ok": False}

        def _confirm():
            result["ok"] = True
            dialog.destroy()

        def _cancel():
            dialog.destroy()

        ttk.Button(btns, text="Cancel", command=_cancel).pack(side="right")
        ttk.Button(btns, text="Create report", command=_confirm).pack(
            side="right", padx=(0, 6))

        dialog.bind("<Escape>", lambda _e: _cancel(), add=True)
        dialog.protocol("WM_DELETE_WINDOW", _cancel)
        title_entry.focus_set()
        self.wait_window(dialog)

        if not result["ok"]:
            return False

        title = title_var.get().strip() or "Untitled Project"
        self.project_title = title
        self._update_title_bar()
        self.report_state = new_report_state(
            self.project_title,
            self.project_path,
            self._report_data_sources(),
        )
        self.report_state["annotation_format"] = self._annotation_format_payload()
        self.report_state["include_meta"] = bool(
            self.report_hide_meta_var.get())
        self.report_path = ""
        self._report_dirty = True
        self._report_temp_assets_dir = ""
        self.status.set(
            "New report prepared. Add snapshots and/or text blocks.")
        return True

    def open_report(self) -> bool:
        if not self._prompt_save_report_if_dirty("opening another report"):
            return False
        in_path = filedialog.askopenfilename(
            title="Open report",
            filetypes=[("Report (.rep.json)", ("*.rep.json",)),
                       ("JSON", ("*.json",)),
                       ("All files", ("*.*",))],
        )
        if not in_path:
            return False
        try:
            self.report_state = load_report_file(in_path)
            if not isinstance(self.report_state, dict):
                raise ValueError("Invalid report file.")
        except Exception as exc:
            messagebox.showerror("Report", f"Failed to open report:\n{exc}")
            return False
        self.report_path = in_path
        assets_dir = report_assets_dir(in_path)
        os.makedirs(assets_dir, exist_ok=True)
        self._report_dirty = False
        self._report_temp_assets_dir = ""
        self._ensure_report_snapshots_list()
        self._apply_report_annotation_format()
        self._sync_report_meta_toggle_from_state()
        self.status.set(f"Opened report: {in_path}")
        return True

    def save_report(self) -> bool:
        if not self.report_state:
            self.new_report()
        if self.report_state is not None:
            self.report_state["annotation_format"] = self._annotation_format_payload(
            )
            self.report_state["include_meta"] = self._report_include_meta_enabled()
            self._ensure_report_snapshots_list()
        if not self.report_state:
            return False
        if not self._ensure_report_path():
            return False
        try:
            save_report_file(self.report_state, self.report_path)
        except Exception as exc:
            messagebox.showerror("Report", f"Failed to save report:\n{exc}")
            return False
        self._report_dirty = False
        self.status.set(f"Saved report: {self.report_path}")
        return True

    def _prompt_report_snapshot(
        self,
        *,
        initial_title: str | None = None,
        initial_comments: str = "",
        dialog_title: str = "Add report snapshot",
        confirm_label: str = "Add snapshot",
    ) -> tuple[str, str] | None:
        dialog = tk.Toplevel(self)
        dialog.title(dialog_title)
        dialog.transient(self)
        dialog.grab_set()
        dialog.geometry("520x360")
        self._center_dialog(dialog)

        container = ttk.Frame(dialog, padding=10)
        container.pack(fill="both", expand=True)

        ttk.Label(container, text="Snapshot title:").pack(anchor="w")
        default_title = ""
        if initial_title is None:
            if self.use_plotly_var.get() and self._last_plotly_title:
                default_title = self._last_plotly_title
            elif hasattr(self, "ax"):
                default_title = self.ax.get_title()
        else:
            default_title = initial_title
        title_var = tk.StringVar(value=default_title)
        title_entry = ttk.Entry(container, textvariable=title_var)
        title_entry.pack(fill="x", pady=(2, 10))

        ttk.Label(container, text="Comments:").pack(anchor="w")
        text_widget = tk.Text(container, height=10, wrap="word")
        text_widget.pack(fill="both", expand=True)
        if initial_comments:
            text_widget.insert("1.0", initial_comments)

        btns = ttk.Frame(container)
        btns.pack(fill="x", pady=(10, 0))
        result = {"ok": False, "title": "", "comments": ""}

        def _confirm():
            result["ok"] = True
            result["title"] = title_var.get().strip()
            result["comments"] = text_widget.get("1.0", "end").strip()
            dialog.destroy()

        def _cancel():
            dialog.destroy()

        ttk.Button(btns, text="Cancel", command=_cancel).pack(side="right")
        ttk.Button(btns, text=confirm_label, command=_confirm).pack(
            side="right", padx=(0, 6))

        dialog.bind("<Escape>", lambda _e: _cancel(), add=True)
        dialog.protocol("WM_DELETE_WINDOW", _cancel)
        title_entry.focus_set()
        self.wait_window(dialog)

        if not result["ok"]:
            return None
        return result["title"], result["comments"]

    def _prompt_report_text_block(
        self,
        *,
        initial_title: str = "",
        initial_body: str = "",
        initial_format: str = "text",
        dialog_title: str = "Add text block",
        confirm_label: str = "Add block",
    ) -> tuple[str, str, str] | None:
        if os.name == "nt":
            rich_result = self._prompt_report_text_block_rich_windows(
                initial_title=initial_title,
                initial_body=initial_body,
                initial_format=initial_format,
            )
            if rich_result == ("", "", "__cancelled__"):
                return None
            if rich_result is not None:
                return rich_result

        # Fallback plain Tk editor (used if rich editor is unavailable)
        dialog = tk.Toplevel(self)
        dialog.title(dialog_title)
        dialog.transient(self)
        dialog.grab_set()
        dialog.geometry("560x380")
        self._center_dialog(dialog)

        container = ttk.Frame(dialog, padding=10)
        container.pack(fill="both", expand=True)

        ttk.Label(container, text="Block title (optional):").pack(anchor="w")
        title_var = tk.StringVar(value=initial_title)
        title_entry = ttk.Entry(container, textvariable=title_var)
        title_entry.pack(fill="x", pady=(2, 10))

        fmt_var = tk.StringVar(
            value="html" if str(initial_format).strip(
            ).lower() == "html" else "text"
        )
        fmt_row = ttk.Frame(container)
        fmt_row.pack(fill="x", pady=(0, 6))
        ttk.Label(fmt_row, text="Content type:").pack(side="left")
        ttk.Radiobutton(fmt_row, text="Plain text", value="text",
                        variable=fmt_var).pack(side="left", padx=(8, 0))
        ttk.Radiobutton(fmt_row, text="HTML (rich)", value="html",
                        variable=fmt_var).pack(side="left", padx=(8, 0))
        ttk.Button(
            fmt_row,
            text="Paste rich from clipboard",
            command=lambda: _paste_clipboard_rich(),
        ).pack(side="right")
        ttk.Button(
            fmt_row,
            text="Paste image",
            command=lambda: _paste_clipboard_image(),
        ).pack(side="right", padx=(0, 6))

        ttk.Label(container, text="Content:").pack(anchor="w")
        text_widget = tk.Text(container, height=12, wrap="word")
        text_widget.pack(fill="both", expand=True)
        if initial_body:
            text_widget.insert("1.0", initial_body)

        ttk.Label(
            container,
            text="Paste plain notes or raw HTML (e.g. copied web/doc extracts, including <img> tags). HTML preview/export renders directly.",
            wraplength=520,
            foreground="#555",
        ).pack(anchor="w", pady=(6, 0))

        btns = ttk.Frame(container)
        btns.pack(fill="x", pady=(10, 0))
        result = {"ok": False, "title": "", "body": "", "format": "text"}

        def _insert_at_cursor(text_value: str) -> None:
            if not text_value:
                return
            try:
                text_widget.insert("insert", text_value)
                text_widget.focus_set()
            except Exception:
                pass

        def _set_editor_content(text_value: str) -> None:
            text_widget.delete("1.0", "end")
            if text_value:
                text_widget.insert("1.0", text_value)
            text_widget.focus_set()

        def _paste_clipboard_rich() -> None:
            html_clip = self._get_clipboard_html_fragment_windows()
            if html_clip:
                fmt_var.set("html")
                _set_editor_content(html_clip)
                return
            try:
                plain = self.clipboard_get()
            except Exception:
                plain = ""
            if plain:
                fmt_var.set("text")
                _set_editor_content(str(plain))
                return
            messagebox.showinfo(
                "Clipboard",
                "No text/HTML content was found in the clipboard.",
                parent=dialog,
            )

        def _paste_clipboard_image() -> None:
            rel_path = self._save_clipboard_image_report_asset()
            if not rel_path:
                messagebox.showinfo(
                    "Clipboard",
                    "No image was found in the clipboard.",
                    parent=dialog,
                )
                return
            fmt_var.set("html")
            tag = f'<img src="{html.escape(rel_path, quote=True)}" alt="Pasted image" />'
            current = text_widget.get("1.0", "end").strip()
            if current:
                _insert_at_cursor("\n" + tag + "\n")
            else:
                _set_editor_content(tag)

        def _confirm():
            result["ok"] = True
            result["title"] = title_var.get().strip()
            result["body"] = text_widget.get("1.0", "end").strip()
            result["format"] = "html" if fmt_var.get() == "html" else "text"
            dialog.destroy()

        def _cancel():
            dialog.destroy()

        ttk.Button(btns, text="Cancel", command=_cancel).pack(side="right")
        ttk.Button(btns, text=confirm_label, command=_confirm).pack(
            side="right", padx=(0, 6))

        dialog.bind("<Escape>", lambda _e: _cancel(), add=True)
        dialog.protocol("WM_DELETE_WINDOW", _cancel)
        title_entry.focus_set()
        self.wait_window(dialog)

        if not result["ok"]:
            return None
        return result["title"], result["body"], result["format"]

    def _prompt_report_text_block_rich_windows(
        self,
        *,
        initial_title: str,
        initial_body: str,
        initial_format: str,
    ) -> tuple[str, str, str] | None:
        if os.name != "nt":
            return None
        html_body = ""
        if str(initial_format).strip().lower() == "html":
            html_body = self._render_report_rich_html_block(
                initial_body,
                asset_prefix="",
                embed_assets=True,
                asset_root=self._current_report_assets_dir(),
            )
        else:
            html_body = self._plain_text_to_editor_html(initial_body)

        result = self._run_windows_rich_html_editor(
            {
                "title": initial_title,
                "html": html_body,
            }
        )
        if result is None:
            return None
        if result.get("cancelled"):
            return ("", "", "__cancelled__")
        raw_title = str(result.get("title", "")).strip()
        raw_html = str(result.get("html", "") or "")
        normalized_html = self._normalize_report_rich_html_for_storage(
            raw_html)
        return raw_title, normalized_html, "html"

    def _run_windows_rich_html_editor(self, payload: dict[str, str]) -> dict | None:
        src_root = os.path.abspath(os.path.join(
            os.path.dirname(__file__), "..", ".."))
        temp_dir = tempfile.mkdtemp(prefix="ddp_rich_editor_")
        in_path = os.path.join(temp_dir, "input.json")
        out_path = os.path.join(temp_dir, "output.json")
        try:
            log_event(
                "tk.rich_editor.launch",
                f"title_len={len(str(payload.get('title', '') or ''))} html_len={len(str(payload.get('html', '') or ''))}",
                RICH_EDITOR_LOG_PATH,
            )
            with open(in_path, "w", encoding="utf-8") as handle:
                json.dump(payload, handle, ensure_ascii=False)

            env = dict(os.environ)
            if getattr(sys, "frozen", False):
                # In PyInstaller builds, `sys.executable -m ...` relaunches the main app.
                # Route through the app entrypoint with a hidden dispatch flag instead.
                cmd = [
                    sys.executable,
                    "--ddp-rich-html-editor",
                    in_path,
                    out_path,
                ]
            else:
                py_path = env.get("PYTHONPATH", "")
                env["PYTHONPATH"] = src_root + \
                    (os.pathsep + py_path if py_path else "")
                cmd = [
                    sys.executable,
                    "-m",
                    "dashboard_data_plotter.ui.rich_html_editor",
                    in_path,
                    out_path,
                ]
            proc = subprocess.run(
                cmd,
                cwd=os.path.abspath(os.path.join(src_root, "..")),
                env=env,
                capture_output=True,
                text=True,
            )
            log_event(
                "tk.rich_editor.exit",
                f"returncode={proc.returncode} stdout_len={len(proc.stdout or '')} stderr_len={len(proc.stderr or '')}",
                RICH_EDITOR_LOG_PATH,
            )
            if proc.returncode != 0:
                stderr = (proc.stderr or "").strip()
                if stderr:
                    log_event("tk.rich_editor.stderr", stderr, RICH_EDITOR_LOG_PATH)
                if "No module named 'webview'" in stderr or "No module named webview" in stderr:
                    messagebox.showinfo(
                        "Rich editor unavailable",
                        "The Windows rich text editor requires the optional package 'pywebview'.\n\n"
                        "Install it to enable Word/web-style paste and editing.\n\n"
                        "Falling back to the basic text editor for now.",
                    )
                    return None
                messagebox.showerror(
                    "Rich editor",
                    "Failed to open the rich content editor.\n\n"
                    + (stderr or f"Exit code {proc.returncode}")
                )
                return None
            if not os.path.isfile(out_path):
                log_event("tk.rich_editor.output", "missing_output_json", RICH_EDITOR_LOG_PATH)
                return None
            with open(out_path, "r", encoding="utf-8") as handle:
                result = json.load(handle)
            log_event(
                "tk.rich_editor.output",
                f"ok={bool(isinstance(result, dict) and result.get('ok'))}",
                RICH_EDITOR_LOG_PATH,
            )
            if not isinstance(result, dict):
                return {"cancelled": True}
            if result.get("ok"):
                return result
            return {"cancelled": True}
        except Exception as exc:
            log_exception("tk._run_windows_rich_html_editor failed", RICH_EDITOR_LOG_PATH)
            messagebox.showerror(
                "Rich editor", f"Failed to open rich editor:\n{exc}")
            return None
        finally:
            try:
                shutil.rmtree(temp_dir, ignore_errors=True)
            except Exception:
                pass

    def _plain_text_to_editor_html(self, text: str) -> str:
        if not text:
            return ""
        parts = []
        for line in str(text).splitlines():
            if line.strip():
                parts.append(f"<p>{html.escape(line)}</p>")
            else:
                parts.append("<p><br></p>")
        return "".join(parts)

    def _normalize_report_rich_html_for_storage(self, html_text: str) -> str:
        html_text = self._sanitize_report_html_block(html_text or "")
        if not html_text:
            return ""

        def _replace_data_uri_img(match: re.Match) -> str:
            quote = match.group(1)
            src = (match.group(2) or "").strip()
            lower = src.lower()
            if not lower.startswith("data:image/"):
                return match.group(0)
            rel_path = self._save_data_uri_image_report_asset(src)
            if not rel_path:
                return match.group(0)
            return f'src={quote}{html.escape(rel_path, quote=True)}{quote}'

        return re.sub(r"src=(['\"])([^'\"]+)\1", _replace_data_uri_img, html_text, flags=re.IGNORECASE)

    def _save_data_uri_image_report_asset(self, data_uri: str) -> str:
        match = re.match(
            r"^data:image/([a-zA-Z0-9.+-]+);base64,(.+)$", data_uri, flags=re.IGNORECASE | re.DOTALL)
        if not match:
            return ""
        subtype = (match.group(1) or "png").lower()
        b64 = match.group(2).strip()
        ext = {
            "jpeg": ".jpg",
            "jpg": ".jpg",
            "png": ".png",
            "gif": ".gif",
            "bmp": ".bmp",
            "webp": ".webp",
        }.get(subtype, ".png")
        try:
            blob = base64.b64decode(b64, validate=False)
        except Exception:
            return ""
        rel_name = os.path.join(
            "rich", f"richimg_{datetime.now().strftime('%Y%m%d_%H%M%S')}_{uuid.uuid4().hex[:6]}{ext}")
        out_path = os.path.join(self._current_report_assets_dir(), rel_name)
        try:
            os.makedirs(os.path.dirname(out_path), exist_ok=True)
            with open(out_path, "wb") as handle:
                handle.write(blob)
        except Exception:
            return ""
        return rel_name.replace("\\", "/")

    def _get_clipboard_html_fragment_windows(self) -> str:
        if os.name != "nt":
            return ""
        try:
            fmt_id = ctypes.windll.user32.RegisterClipboardFormatW(
                "HTML Format")
        except Exception:
            return ""
        if not fmt_id:
            return ""

        user32 = ctypes.windll.user32
        kernel32 = ctypes.windll.kernel32
        if not user32.OpenClipboard(None):
            return ""
        try:
            handle = user32.GetClipboardData(fmt_id)
            if not handle:
                return ""
            ptr = kernel32.GlobalLock(handle)
            if not ptr:
                return ""
            try:
                size = kernel32.GlobalSize(handle)
                if not size:
                    return ""
                raw = ctypes.string_at(ptr, size)
            finally:
                kernel32.GlobalUnlock(handle)
        finally:
            user32.CloseClipboard()

        # CF_HTML payload is ASCII header + HTML bytes. Keep embedded fragment when possible.
        text = raw.decode("utf-8", errors="replace").rstrip("\x00")
        if not text:
            return ""
        if "StartFragment:" not in text:
            return text
        try:
            start_html = self._cf_html_offset(text, "StartHTML")
            end_html = self._cf_html_offset(text, "EndHTML")
            start_frag = self._cf_html_offset(text, "StartFragment")
            end_frag = self._cf_html_offset(text, "EndFragment")
            if min(start_html, end_html, start_frag, end_frag) < 0:
                return text
            html_bytes = raw[start_html:end_html]
            html_text = html_bytes.decode("utf-8", errors="replace")
            rel_start = max(0, start_frag - start_html)
            rel_end = max(rel_start, end_frag - start_html)
            fragment = html_text[rel_start:rel_end]
            return fragment.strip() or html_text.strip()
        except Exception:
            return text

    def _cf_html_offset(self, header_text: str, key: str) -> int:
        match = re.search(rf"{re.escape(key)}:(\d+)", header_text)
        if not match:
            return -1
        try:
            return int(match.group(1))
        except Exception:
            return -1

    def _save_clipboard_image_report_asset(self) -> str:
        try:
            from PIL import ImageGrab
        except Exception:
            return ""
        try:
            clip = ImageGrab.grabclipboard()
        except Exception:
            return ""
        if clip is None:
            return ""
        image_obj = None
        if hasattr(clip, "save"):
            image_obj = clip
        elif isinstance(clip, list):
            # File list clipboard content; not handled here.
            return ""
        if image_obj is None:
            return ""

        assets_dir = self._current_report_assets_dir()
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        rel_name = f"clipimg_{stamp}_{uuid.uuid4().hex[:6]}.png"
        out_path = os.path.join(assets_dir, rel_name)
        try:
            image_obj.save(out_path, format="PNG")
        except Exception:
            return ""
        return rel_name

    def add_report_snapshot(self) -> None:
        if not self._ensure_report_state():
            return

        if not self.state.loaded:
            messagebox.showinfo(
                "No data", "Load at least one dataset and plot first.")
            return

        snapshot_prompt = self._prompt_report_snapshot()
        if snapshot_prompt is None:
            return
        snap_title, comments = snapshot_prompt

        plot_type = (self.plot_type_var.get() or "").strip().lower()
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        metric_col = (self.metric_var.get() or "").strip()
        metric_part = self._sanitize_filename_part(metric_col)
        plot_part = self._sanitize_filename_part(plot_type)

        assets_dir = self._current_report_assets_dir()

        assets = {}
        plot_backend = "matplotlib"
        if self.use_plotly_var.get():
            plot_backend = "plotly"
            if self._last_plotly_fig is None:
                messagebox.showinfo(
                    "No Plotly plot", "Plot a Plotly chart before adding a snapshot.")
                return
            html_name = f"plotly_{plot_part}_{metric_part}_{timestamp}.html"
            html_path = os.path.join(assets_dir, html_name)
            try:
                fig_for_report = go.Figure(self._last_plotly_fig)
                fig_for_report.update_layout(title=None)
                pio.write_html(
                    fig_for_report,
                    file=html_path,
                    auto_open=False,
                    include_plotlyjs="cdn",
                )
            except Exception as exc:
                messagebox.showerror(
                    "Report", f"Failed to save Plotly snapshot:\n{exc}")
                return
            assets["html"] = html_name
        else:
            image_name = f"plot_{plot_part}_{metric_part}_{timestamp}.png"
            image_path = os.path.join(assets_dir, image_name)
            saved_titles: list[tuple[Any, str]] = []
            try:
                # Save report snapshots without embedded plot titles; report headings handle titling.
                for axis in getattr(self.fig, "axes", []):
                    try:
                        current_title = axis.get_title()
                        saved_titles.append((axis, current_title))
                        axis.set_title("")
                    except Exception:
                        continue
                self.fig.savefig(image_path, dpi=200, bbox_inches="tight")
            except Exception as exc:
                messagebox.showerror(
                    "Report", f"Failed to save plot snapshot:\n{exc}")
                return
            finally:
                for axis, axis_title in saved_titles:
                    try:
                        axis.set_title(axis_title)
                    except Exception:
                        pass
            assets["image"] = image_name

        plot_title = ""
        if self.use_plotly_var.get() and self._last_plotly_title:
            plot_title = self._last_plotly_title
        elif hasattr(self, "ax"):
            plot_title = self.ax.get_title()

        snapshot = {
            "id": uuid.uuid4().hex,
            "created_at": datetime.now().replace(microsecond=0).isoformat(),
            "user_title": "" if (snap_title or "").strip() == (plot_title or "").strip() else snap_title,
            "title": snap_title or plot_title,
            "plot_type": plot_type,
            "plot_backend": plot_backend,
            "plot_title": plot_title,
            "plot_settings": self._snapshot_settings(),
            "comments": comments,
            "annotations": list(self._annotations),
            "assets": assets,
        }

        snapshots = self._ensure_report_snapshots_list()
        snapshots.append(snapshot)
        self._report_dirty = True
        if not self._autosave_report_if_path():
            return

        self.status.set("Added snapshot to report.")

    def add_report_text_block(self) -> None:
        if not self._ensure_report_state():
            return
        prompt = self._prompt_report_text_block()
        if prompt is None:
            return
        block_title, block_body, block_format = prompt
        if not block_title and not block_body:
            messagebox.showinfo("Report", "Nothing to add.")
            return

        block = {
            "id": uuid.uuid4().hex,
            "kind": "text",
            "created_at": datetime.now().replace(microsecond=0).isoformat(),
            "title": block_title,
            "content": block_body,
            "content_format": block_format,
        }
        snapshots = self._ensure_report_snapshots_list()
        snapshots.append(block)
        self._report_dirty = True
        if not self._autosave_report_if_path():
            return
        self.status.set("Added text block to report.")

    def manage_report_content(self) -> None:
        if not self._ensure_report_state():
            return
        snapshots = self._ensure_report_snapshots_list()

        dialog = tk.Toplevel(self)
        dialog.title("Manage report content")
        dialog.transient(self)
        dialog.grab_set()
        dialog.geometry("760x420")
        self._center_dialog(dialog)

        container = ttk.Frame(dialog, padding=10)
        container.pack(fill="both", expand=True)
        container.columnconfigure(0, weight=1)
        container.columnconfigure(1, weight=0)
        container.rowconfigure(1, weight=1)

        ttk.Label(
            container,
            text="Edit, remove, or reorder report snapshots and text blocks.",
            foreground="#444",
        ).grid(row=0, column=0, columnspan=2, sticky="w", pady=(0, 8))

        list_frame = ttk.Frame(container)
        list_frame.grid(row=1, column=0, sticky="nsew")
        list_frame.columnconfigure(0, weight=1)
        list_frame.rowconfigure(0, weight=1)

        listbox = tk.Listbox(list_frame, activestyle="dotbox")
        listbox.grid(row=0, column=0, sticky="nsew")
        scrollbar = ttk.Scrollbar(
            list_frame, orient="vertical", command=listbox.yview)
        scrollbar.grid(row=0, column=1, sticky="ns")
        listbox.configure(yscrollcommand=scrollbar.set)

        right = ttk.Frame(container)
        right.grid(row=1, column=1, sticky="ns", padx=(10, 0))

        def _selected_index() -> int | None:
            sel = listbox.curselection()
            if not sel:
                return None
            idx = int(sel[0])
            if idx < 0 or idx >= len(snapshots):
                return None
            return idx

        def _refresh(select_index: int | None = None) -> None:
            listbox.delete(0, "end")
            for idx, item in enumerate(snapshots):
                listbox.insert(
                    "end", self._report_item_display_label(item, idx))
            if not snapshots:
                return
            if select_index is None:
                select_index = min(len(snapshots) - 1, 0)
            select_index = max(0, min(select_index, len(snapshots) - 1))
            listbox.selection_clear(0, "end")
            listbox.selection_set(select_index)
            listbox.activate(select_index)
            listbox.see(select_index)

        def _commit_status(msg: str) -> None:
            self._report_dirty = True
            if not self._autosave_report_if_path():
                return
            self.status.set(msg)

        def _add_text() -> None:
            prompt = self._prompt_report_text_block()
            if prompt is None:
                return
            block_title, block_body, block_format = prompt
            if not block_title and not block_body:
                return
            snapshots.append(
                {
                    "id": uuid.uuid4().hex,
                    "kind": "text",
                    "created_at": datetime.now().replace(microsecond=0).isoformat(),
                    "title": block_title,
                    "content": block_body,
                    "content_format": block_format,
                }
            )
            _refresh(len(snapshots) - 1)
            _commit_status("Added text block to report.")

        def _edit_selected() -> None:
            idx = _selected_index()
            if idx is None:
                return
            item = snapshots[idx]
            if not isinstance(item, dict):
                messagebox.showerror(
                    "Report", "Selected report item is invalid.")
                return
            kind = self._report_item_kind(item)
            if kind == "text":
                prompt = self._prompt_report_text_block(
                    initial_title=str(item.get("title", "")),
                    initial_body=str(item.get("content", "")),
                    initial_format=str(item.get("content_format", "text")),
                    dialog_title="Edit text block",
                    confirm_label="Save changes",
                )
                if prompt is None:
                    return
                title, body, content_format = prompt
                item["title"] = title
                item["content"] = body
                item["content_format"] = "html" if content_format == "html" else "text"
                _refresh(idx)
                _commit_status("Updated text block.")
                return

            prompt = self._prompt_report_snapshot(
                initial_title=str(item.get("title", "")),
                initial_comments=str(item.get("comments", "")),
                dialog_title="Edit snapshot details",
                confirm_label="Save changes",
            )
            if prompt is None:
                return
            title, comments = prompt
            item["user_title"] = "" if (title or "").strip() == str(
                item.get("plot_title", "")).strip() else title
            item["title"] = title or str(item.get("plot_title", "")).strip()
            item["comments"] = comments
            _refresh(idx)
            _commit_status("Updated snapshot details.")

        def _delete_selected() -> None:
            idx = _selected_index()
            if idx is None:
                return
            item = snapshots[idx]
            kind = self._report_item_kind(item) if isinstance(
                item, dict) else "snapshot"
            kind_label = "text block" if kind == "text" else "snapshot"
            if not messagebox.askyesno("Remove report item", f"Remove selected {kind_label}?"):
                return
            del snapshots[idx]
            next_idx = min(idx, len(snapshots) - 1) if snapshots else None
            _refresh(next_idx)
            _commit_status(f"Removed {kind_label} from report.")

        def _move_selected(delta: int) -> None:
            idx = _selected_index()
            if idx is None:
                return
            new_idx = idx + delta
            if new_idx < 0 or new_idx >= len(snapshots):
                return
            snapshots[idx], snapshots[new_idx] = snapshots[new_idx], snapshots[idx]
            _refresh(new_idx)
            _commit_status("Reordered report content.")

        ttk.Button(right, text="Add text...", command=_add_text, width=14).pack(
            fill="x", pady=(0, 6))
        ttk.Button(right, text="Edit selected...", command=_edit_selected, width=14).pack(
            fill="x", pady=(0, 6))
        ttk.Button(right, text="Remove", command=_delete_selected, width=14).pack(
            fill="x", pady=(0, 12))
        ttk.Button(right, text="Move up", command=lambda: _move_selected(-1), width=14).pack(
            fill="x", pady=(0, 6))
        ttk.Button(right, text="Move down", command=lambda: _move_selected(1), width=14).pack(
            fill="x", pady=(0, 12))
        ttk.Button(right, text="Close", command=dialog.destroy,
                   width=14).pack(fill="x")

        listbox.bind("<Double-Button-1>",
                     lambda _e: _edit_selected(), add=True)
        dialog.bind("<Escape>", lambda _e: dialog.destroy(), add=True)
        dialog.protocol("WM_DELETE_WINDOW", dialog.destroy)

        _refresh(0 if snapshots else None)
        self.wait_window(dialog)

    def _build_report_html(
        self,
        report: dict,
        asset_prefix: str,
        pdf_mode: bool,
        include_meta: bool = True,
        embed_assets: bool = False,
        asset_root: str = "",
    ) -> str:
        title = html.escape(str(report.get("title", "Report")))
        created_at = html.escape(str(report.get("created_at", "")))
        updated_at = html.escape(str(report.get("updated_at", "")))

        data_sources = report.get("data_sources", [])
        snapshots = report.get("snapshots", [])
        if not isinstance(snapshots, list):
            snapshots = []

        css = """
        body { font-family: "Segoe UI", Arial, sans-serif; color: #1b1b1b; margin: 24px; }
        h1 { margin-bottom: 4px; }
        .meta { color: #555; margin-bottom: 16px; }
        .section { margin-top: 24px; }
        .snapshot { border: 1px solid #ddd; border-radius: 8px; padding: 16px; margin-bottom: 18px; }
        .snapshot h3 { margin-top: 0; }
        .snapshot-body { display: flex; gap: 16px; align-items: flex-start; }
        .snapshot-left { flex: 0 0 60%; }
        .snapshot-right { flex: 0 0 40%; }
        .plot-img { width: 100%; height: auto; border: 1px solid #ccc; background: #fafafa; }
        .plot-frame { width: 100%; height: 280px; border: 1px solid #ccc; }
        .settings { font-size: 0.9em; color: #444; }
        .comments { font-size: 0.98em; font-weight: 600; line-height: 1.35; margin-top: 8px; color: #1f4aa8; }
        .rich-content { margin-top: 8px; line-height: 1.35; color: #222; }
        .rich-content img { max-width: 100%; height: auto; }
        .rich-content table { border-collapse: collapse; max-width: 100%; display: block; overflow-x: auto; }
        .rich-content th, .rich-content td { border: 1px solid #d8d8d8; padding: 4px 6px; }
        .rich-content pre { white-space: pre-wrap; background: #f7f7f7; padding: 8px; border: 1px solid #e2e2e2; }
        .pill { display: inline-block; background: #f0f0f0; padding: 2px 8px; border-radius: 10px; font-size: 0.85em; }
        @media (max-width: 900px) {
          .snapshot-body { flex-direction: column; }
          .snapshot-left { flex: 1 1 auto; }
        }
        """

        lines = [
            "<!doctype html>",
            "<html>",
            "<head>",
            "<meta charset=\"utf-8\" />",
            f"<title>{title}</title>",
            f"<style>{css}</style>",
            "</head>",
            "<body>",
            f"<h1>{title}</h1>",
        ]
        if include_meta:
            lines.append(
                f"<div class=\"meta\">Created: {created_at} | Updated: {updated_at}</div>")

        if include_meta and data_sources:
            lines.append("<div class=\"section\"><h2>Data Sources</h2><ul>")
            for item in data_sources:
                display = html.escape(str(item.get("display", "")))
                raw_source_id = str(item.get("source_id", ""))
                source_id = html.escape(
                    raw_source_id.replace("PASTE", "Originally"))
                lines.append(
                    f"<li>{display} <span class=\"pill\">{source_id}</span></li>")
            lines.append("</ul></div>")

        lines.append("<div class=\"section\"><h2>Analysis</h2>")
        if not snapshots:
            lines.append("<p>No report content yet.</p>")
        else:
            for snap in snapshots:
                item_kind = self._report_item_kind(
                    snap) if isinstance(snap, dict) else "snapshot"
                if item_kind == "text":
                    raw_title = str(snap.get("title", "")).strip()
                    body = str(snap.get("content", ""))
                    content_format = str(
                        snap.get("content_format", "text")).strip().lower()
                    snap_time = html.escape(str(snap.get("created_at", "")))
                    snap_date = snap_time.split("T", 1)[0] if snap_time else ""
                    lines.append("<div class=\"snapshot\">")
                    if raw_title:
                        lines.append(f"<h3>{html.escape(raw_title)}</h3>")
                    elif include_meta:
                        lines.append("<h3>Text block</h3>")
                    if include_meta:
                        lines.append(
                            f"<div class=\"meta\">Added: {snap_date}</div>")
                    if body:
                        if content_format == "html":
                            lines.append(
                                f"<div class=\"rich-content\">{self._render_report_rich_html_block(body, asset_prefix=asset_prefix, embed_assets=embed_assets, asset_root=asset_root)}</div>")
                        else:
                            lines.append(
                                f"<div class=\"comments\">{self._render_markdown_html(body)}</div>")
                    else:
                        lines.append("<p><em>Empty text block.</em></p>")
                    lines.append("</div>")
                    continue
                raw_title = str(snap.get("title", "")).strip()
                raw_user_title = str(snap.get("user_title", "")).strip()
                raw_plot_title = str(snap.get("plot_title", "")).strip()
                effective_user_title = raw_user_title
                if raw_plot_title and effective_user_title == raw_plot_title:
                    effective_user_title = ""
                if include_meta:
                    display_title = raw_title or "Snapshot"
                else:
                    # Metadata-hidden mode should not show auto/original plot titles.
                    # Only an explicit user snapshot title is rendered.
                    display_title = effective_user_title
                snap_title = html.escape(display_title)
                snap_time = html.escape(str(snap.get("created_at", "")))
                snap_date = snap_time.split("T", 1)[0] if snap_time else ""
                comments = str(snap.get("comments", ""))
                assets = snap.get("assets", {}) if isinstance(
                    snap.get("assets", {}), dict) else {}

                lines.append("<div class=\"snapshot\">")
                if display_title:
                    lines.append(f"<h3>{snap_title}</h3>")
                if include_meta:
                    lines.append(
                        f"<div class=\"meta\">Captured: {snap_date}</div>")

                lines.append("<div class=\"snapshot-body\">")
                lines.append("<div class=\"snapshot-left\">")
                img_rel = assets.get("image")
                html_rel = assets.get("html")
                if img_rel:
                    if embed_assets and asset_root:
                        img_path = os.path.join(asset_root, img_rel)
                        data_uri = self._load_asset_data_uri(img_path)
                        if data_uri:
                            lines.append(
                                f"<img class=\"plot-img\" src=\"{data_uri}\" alt=\"Plot image\" />")
                        else:
                            lines.append(
                                "<p><em>Image snapshot missing.</em></p>")
                    else:
                        img_path = html.escape(os.path.join(
                            asset_prefix, img_rel).replace("\\", "/"))
                        lines.append(
                            f"<img class=\"plot-img\" src=\"{img_path}\" alt=\"Plot image\" />")
                elif html_rel and not pdf_mode:
                    if embed_assets and asset_root:
                        html_path = os.path.join(asset_root, html_rel)
                        html_doc = self._read_asset_text(html_path)
                        if html_doc:
                            srcdoc = html.escape(html_doc)
                            lines.append(
                                f"<iframe class=\"plot-frame\" srcdoc=\"{srcdoc}\"></iframe>")
                        else:
                            lines.append(
                                "<p><em>Interactive plot missing.</em></p>")
                    else:
                        html_path = html.escape(os.path.join(
                            asset_prefix, html_rel).replace("\\", "/"))
                        lines.append(
                            f"<iframe class=\"plot-frame\" src=\"{html_path}\"></iframe>")
                elif html_rel and pdf_mode:
                    lines.append(
                        "<p><em>Interactive plot available in HTML export.</em></p>")

                if comments:
                    lines.append(
                        f"<div class=\"comments\">{self._render_markdown_html(comments)}</div>")
                lines.append("</div>")
                lines.append("<div class=\"snapshot-right\">")

                settings = snap.get("plot_settings", {})
                if include_meta and isinstance(settings, dict):
                    lines.append(
                        "<div class=\"settings\"><strong>Plot settings:</strong><ul>")
                    hidden_keys = {
                        "close_loop",
                        "plot_type",
                        "use_plotly",
                        "radar_background",
                        "show_outliers",
                        "outlier_warnings",
                        "use_original_binned",
                        "show_flag",
                    }
                    for key, value in settings.items():
                        if key in hidden_keys:
                            continue
                        lines.append(
                            f"<li>{html.escape(str(key))}: {html.escape(str(value))}</li>")
                    lines.append("</ul></div>")

                lines.append("</div>")
                lines.append("</div>")
                lines.append("</div>")
        lines.append("</div>")
        lines.append("</body></html>")
        return "\n".join(lines)

    def _load_asset_data_uri(self, path: str) -> str:
        if not os.path.isfile(path):
            return ""
        ext = os.path.splitext(path)[1].lower()
        mime = {
            ".png": "image/png",
            ".jpg": "image/jpeg",
            ".jpeg": "image/jpeg",
            ".gif": "image/gif",
            ".bmp": "image/bmp",
        }.get(ext, "application/octet-stream")
        try:
            with open(path, "rb") as handle:
                data = base64.b64encode(handle.read()).decode("ascii")
        except OSError:
            return ""
        return f"data:{mime};base64,{data}"

    def _read_asset_text(self, path: str) -> str:
        if not os.path.isfile(path):
            return ""
        try:
            with open(path, "r", encoding="utf-8") as handle:
                return handle.read()
        except OSError:
            return ""

    def _render_markdown_html(self, text: str) -> str:
        if not text:
            return ""
        escaped = html.escape(text)
        lines = escaped.splitlines()
        out_lines = []
        in_list = False

        for line in lines:
            if line.startswith("- "):
                if not in_list:
                    out_lines.append("<ul>")
                    in_list = True
                item = line[2:].strip()
                out_lines.append(
                    f"<li>{self._render_markdown_inline(item)}</li>")
                continue

            if in_list:
                out_lines.append("</ul>")
                in_list = False
            out_lines.append(self._render_markdown_inline(line))

        if in_list:
            out_lines.append("</ul>")

        return "<br/>".join(out_lines)

    def _render_markdown_inline(self, text: str) -> str:
        # Bold **text**
        text = re.sub(r"\*\*([^*]+)\*\*", r"<strong>\1</strong>", text)
        # Italic *text* (avoid bold markers)
        text = re.sub(r"(?<!\*)\*([^*]+)\*(?!\*)", r"<em>\1</em>", text)
        return text

    def _sanitize_report_html_block(self, text: str) -> str:
        if not text:
            return ""
        # Allow pasted rich HTML, but strip active scripting content.
        text = re.sub(r"(?is)<script\b[^>]*>.*?</script>", "", text)
        text = re.sub(r"(?is)<iframe\b[^>]*>.*?</iframe>", "", text)
        text = re.sub(r"(?is)<object\b[^>]*>.*?</object>", "", text)
        text = re.sub(r"(?is)<embed\b[^>]*>", "", text)
        return text

    def _render_report_rich_html_block(
        self,
        text: str,
        *,
        asset_prefix: str,
        embed_assets: bool,
        asset_root: str,
    ) -> str:
        html_block = self._sanitize_report_html_block(text)
        if not html_block:
            return ""

        def _replace_img_src(match: re.Match) -> str:
            quote = match.group(1)
            src = match.group(2).strip()
            lower_src = src.lower()
            if lower_src.startswith(("http://", "https://", "data:", "file://")):
                return match.group(0)
            rel = src.replace("\\", "/").lstrip("./")
            if not rel:
                return match.group(0)
            if embed_assets and asset_root:
                data_uri = self._load_asset_data_uri(
                    os.path.join(asset_root, rel))
                if data_uri:
                    return f'src={quote}{data_uri}{quote}'
            if asset_prefix:
                joined = os.path.join(asset_prefix, rel).replace("\\", "/")
                return f'src={quote}{html.escape(joined, quote=True)}{quote}'
            return match.group(0)

        return re.sub(r"src=(['\"])([^'\"]+)\1", _replace_img_src, html_block, flags=re.IGNORECASE)

    def _iter_text_block_asset_relpaths(self, report: dict) -> list[str]:
        out: list[str] = []
        seen: set[str] = set()
        snapshots = report.get("snapshots", []) if isinstance(
            report, dict) else []
        if not isinstance(snapshots, list):
            return out
        for item in snapshots:
            if not isinstance(item, dict) or self._report_item_kind(item) != "text":
                continue
            if str(item.get("content_format", "text")).strip().lower() != "html":
                continue
            body = str(item.get("content", ""))
            if not body:
                continue
            for match in re.finditer(r"(?i)<img\b[^>]*\bsrc=(['\"])([^'\"]+)\1", body):
                src = (match.group(2) or "").strip()
                if not src:
                    continue
                low = src.lower()
                if low.startswith(("http://", "https://", "data:", "file://")):
                    continue
                rel = src.replace("\\", "/").lstrip("./")
                if not rel or rel in seen:
                    continue
                seen.add(rel)
                out.append(rel)
        return out

    def export_report_html(self) -> None:
        if not self.report_state:
            messagebox.showinfo(
                "Export report", "Open or create a report first.")
            return
        base_name = ""
        if self.report_path:
            base_name = os.path.splitext(os.path.basename(self.report_path))[0]
        if not base_name:
            base_name = self._sanitize_filename(self.project_title or "report")
        if base_name.endswith(".rep"):
            base_name = base_name[:-4]
        default_name = f"{base_name}.rep.html"
        out_path = filedialog.asksaveasfilename(
            title="Export report to HTML",
            defaultextension=".rep.html",
            initialfile=default_name,
            filetypes=[("Report HTML", ("*.rep.html", "*.html")),
                       ("All files", ("*.*",))],
        )
        if not out_path:
            return

        report_assets = self._current_report_assets_dir()
        html_text = self._build_report_html(
            self.report_state,
            "",
            pdf_mode=False,
            include_meta=self._report_include_meta_enabled(),
            embed_assets=True,
            asset_root=report_assets,
        )
        try:
            with open(out_path, "w", encoding="utf-8") as handle:
                handle.write(html_text)
        except Exception as exc:
            messagebox.showerror("Report", f"Failed to export HTML:\n{exc}")
            return
        self.status.set(f"Exported report HTML: {out_path}")

    def export_report_pdf(self) -> None:
        if not self.report_state:
            messagebox.showinfo(
                "Export report", "Open or create a report first.")
            return

        base_name = ""
        if self.report_path:
            base_name = os.path.splitext(os.path.basename(self.report_path))[0]
        if not base_name:
            base_name = self._sanitize_filename(self.project_title or "report")
        if base_name.endswith(".rep"):
            base_name = base_name[:-4]
        default_name = f"{base_name}.rep.pdf"
        out_path = filedialog.asksaveasfilename(
            title="Export report to PDF",
            defaultextension=".rep.pdf",
            initialfile=default_name,
            filetypes=[("Report PDF", ("*.rep.pdf", "*.pdf")),
                       ("All files", ("*.*",))],
        )
        if not out_path:
            return

        report_assets = self._current_report_assets_dir()
        try:
            warnings = export_report_pdf_file(
                self.report_state,
                report_assets,
                out_path,
                include_meta=self._report_include_meta_enabled(),
            )
        except ImportError:
            messagebox.showerror(
                "Export report",
                "PDF export requires the optional package 'reportlab'.\n\n"
                "Install it in your environment to enable PDF export.",
            )
            return
        except Exception as exc:
            messagebox.showerror("Report", f"Failed to export PDF:\n{exc}")
            return
        self.status.set(f"Exported report PDF: {out_path}")
        if warnings:
            messagebox.showwarning(
                "Report export",
                "Report PDF saved with some warnings.\n\n" +
                "\n".join(warnings),
            )

    def view_report(self) -> None:
        if not self.report_state:
            messagebox.showinfo(
                "View report", "Open or create a report first.")
            return
        try:
            temp_dir = tempfile.mkdtemp(prefix="ddp_report_")
        except Exception as exc:
            messagebox.showerror(
                "Report", f"Failed to create temp folder:\n{exc}")
            return

        export_assets_dir = os.path.join(temp_dir, "assets")
        os.makedirs(export_assets_dir, exist_ok=True)

        report_assets = self._current_report_assets_dir()
        for snap in self._ensure_report_snapshots_list():
            if not isinstance(snap, dict) or self._report_item_kind(snap) != "snapshot":
                continue
            assets = snap.get("assets", {})
            if not isinstance(assets, dict):
                continue
            for key in ("image", "html"):
                rel_path = assets.get(key)
                if not rel_path:
                    continue
                src_path = os.path.join(report_assets, rel_path)
                dst_path = os.path.join(export_assets_dir, rel_path)
                if os.path.isfile(src_path):
                    shutil.copy2(src_path, dst_path)
        for rel_path in self._iter_text_block_asset_relpaths(self.report_state):
            src_path = os.path.join(report_assets, rel_path)
            dst_path = os.path.join(export_assets_dir, rel_path)
            if not os.path.isfile(src_path):
                continue
            os.makedirs(os.path.dirname(dst_path), exist_ok=True)
            shutil.copy2(src_path, dst_path)

        html_text = self._build_report_html(
            self.report_state,
            "assets",
            pdf_mode=False,
            include_meta=self._report_include_meta_enabled(),
        )
        out_path = os.path.join(temp_dir, "report_preview.html")
        try:
            with open(out_path, "w", encoding="utf-8") as handle:
                handle.write(html_text)
        except Exception as exc:
            messagebox.showerror("Report", f"Failed to create preview:\n{exc}")
            return
        webbrowser.open(f"file://{out_path}")
        self.status.set("Opened report preview in browser.")

    # ---------------- UI state helpers ----------------
    def _set_compare_controls_state(self):
        state = "normal" if self.compare_var.get() else "disabled"
        self.baseline_menu_btn.configure(state=state)
        if not self.compare_var.get():
            self._close_baseline_popup(apply_selection=False)

    def _set_plot_type_controls_state(self):
        plot_type = (self.plot_type_var.get() or "radar").strip().lower()
        is_bar = plot_type == "bar"
        no_angle = plot_type in ("bar", "timeseries")
        try:
            self.angle_combo.configure(
                state="disabled" if no_angle else "readonly")
        except Exception:
            pass
        try:
            self.close_loop_chk.configure(
                state="disabled" if no_angle else "normal")
        except Exception:
            pass
        try:
            self.radar_background_chk.configure(
                state="normal" if plot_type in (
                    "radar", "cartesian") else "disabled"
            )
        except Exception:
            pass
        try:
            self.original_binned_btn.configure(
                state="disabled" if plot_type == "timeseries" else "normal"
            )
        except Exception:
            pass
        if plot_type == "timeseries":
            self.use_original_binned_var.set(False)
            self._update_original_binned_label()

    def _update_original_binned_label(self):
        if not hasattr(self, "original_binned_btn"):
            return
        if self.use_original_binned_var.get():
            self.original_binned_btn.configure(text="Original ✓")
        else:
            self.original_binned_btn.configure(text="Original")

    def _on_original_binned_toggle(self):
        if (self.plot_type_var.get() or "").strip().lower() == "timeseries":
            self.use_original_binned_var.set(False)
            self._update_original_binned_label()
            return
        self.use_original_binned_var.set(
            not self.use_original_binned_var.get())
        self._update_original_binned_label()
        self._refresh_angle_choices()
        self.refresh_metric_choices()
        self._refresh_angle_choices()
        self._sync_state_settings_from_ui()

    def _get_fixed_range(self):
        if not self.range_fixed_var.get():
            return None
        low_s = self.range_low_var.get().strip()
        high_s = self.range_high_var.get().strip()
        if not low_s or not high_s:
            messagebox.showinfo(
                "Range required", "Enter both lower and upper range values or untick Fixed.")
            return "invalid"
        try:
            low = float(low_s)
            high = float(high_s)
        except ValueError:
            messagebox.showinfo(
                "Invalid range", "Range values must be valid numbers.")
            return "invalid"
        if not (np.isfinite(low) and np.isfinite(high)):
            messagebox.showinfo(
                "Invalid range", "Range values must be finite numbers.")
            return "invalid"
        if low > high:
            messagebox.showinfo(
                "Invalid range", "Lower range must be less than or equal to upper range.")
            return "invalid"
        return (low, high)

    def _update_range_entries(self, low, high):
        if self.range_fixed_var.get():
            return
        if low is None or high is None:
            return
        self.range_low_var.set(f"{low:.6g}")
        self.range_high_var.set(f"{high:.6g}")

    def _minmax_from_values(self, values):
        arr = np.asarray(values, dtype=float).ravel()
        arr = arr[np.isfinite(arr)]
        if arr.size == 0:
            return None
        return float(np.nanmin(arr)), float(np.nanmax(arr))

    def _radar_metric_range_from_values(self, values):
        minmax = self._minmax_from_values(values)
        if not minmax:
            return None
        low, high = minmax
        span = high - low
        low = low - (0.20 * span)
        if not np.isfinite(low) or not np.isfinite(high):
            return None
        if low >= high:
            if high == 0.0:
                low = -0.1
            else:
                low = high - max(1e-9, 0.20 * abs(high))
        return float(low), float(high)

    def _bar_label_decimals(self, values) -> int:
        arr = np.asarray(values, dtype=float).ravel()
        arr = arr[np.isfinite(arr)]
        if arr.size == 0:
            return 0
        spread = float(np.nanmax(arr) - np.nanmin(arr))
        max_abs = float(np.nanmax(np.abs(arr)))
        scale = spread if spread > 0 else (max_abs if max_abs > 0 else 1.0)
        resolution = max(scale / 200.0, 1e-9)
        return int(np.clip(np.ceil(-np.log10(resolution)), 0, 6))

    def _format_bar_value(self, value: float, decimals: int) -> str:
        text = f"{float(value):.{decimals}f}"
        if "." in text:
            text = text.rstrip("0").rstrip(".")
        return text if text else "0"

    def _bar_label_layout(self, labels: list[str]) -> tuple[int, float]:
        longest = max((len(str(label)) for label in labels), default=0)
        font_size = 8 if longest > 15 else 9
        extra = max(0, longest - 15)
        bottom_margin = min(0.22 + extra * 0.004, 0.42)
        return font_size, bottom_margin

    def _on_plot_type_change(self, apply_default_agg=True):
        plot_type = self.plot_type_var.get()
        is_bar = (plot_type == "bar")
        if hasattr(self, "agg_combo"):
            if plot_type == "timeseries":
                self.agg_combo["values"] = [
                    "raw", "pedal stroke", "roll 360deg"]
                if apply_default_agg:
                    self.agg_var.set("raw")
                elif self.agg_var.get() not in self.agg_combo["values"]:
                    self.agg_var.set("raw")
            else:
                self.agg_combo["values"] = [
                    "mean", "median", "10% trimmed mean"]
                if apply_default_agg:
                    self.agg_var.set("mean" if is_bar else "median")
                elif self.agg_var.get() not in self.agg_combo["values"]:
                    self.agg_var.set("median")
        if hasattr(self, "rb_percent_mean"):
            self.rb_percent_mean.configure(
                state=("disabled" if is_bar else "normal"))
        if is_bar and self.value_mode_var.get() == "percent_mean":
            self.value_mode_var.set("absolute")
        self._set_plot_type_controls_state()
        self._refresh_angle_choices()
        self.refresh_metric_choices()
        self._update_outlier_show_state()

    def _can_autoplot(self):
        if not self.state.loaded:
            return False
        if not self.metric_var.get().strip():
            return False
        plot_type = (self.plot_type_var.get() or "radar").strip().lower()
        if plot_type in ("radar", "cartesian") and not self.angle_var.get().strip():
            return False
        if self.compare_var.get():
            baseline_names = self.baseline_multi_displays or [
                self.baseline_display_var.get().strip()]
            baseline_ids = [self.state.display_to_id.get(
                name, "") for name in baseline_names]
            baseline_ids = [
                sid for sid in baseline_ids if sid in self.state.loaded]
            if not baseline_ids:
                return False
        return True

    def _on_compare_toggle(self):
        self._set_compare_controls_state()

    def _on_outlier_toggle(self):
        state = "normal"
        try:
            self.outlier_entry.configure(state=state)
        except Exception:
            pass
        try:
            self.outlier_method_combo.configure(state=state)
        except Exception:
            pass
        self._update_outlier_show_state()

    def _on_outlier_warnings_toggle(self):
        if self.outlier_warnings_var.get():
            return
        if self._outlier_warnings_disable_notice_shown:
            return
        self._outlier_warnings_disable_notice_shown = True
        messagebox.showwarning(
            "Outlier warnings disabled",
            "You will no longer see warnings of outliers in the data metrics that you plot which may lead to visual artefacts. Consider applying the Outlier Removal method to improve the data plots.",
        )

    def _update_outlier_show_state(self):
        allowed = self._can_show_outliers()
        if not allowed:
            self.show_outliers_var.set(False)
        try:
            self.outlier_show_chk.configure(
                state="normal" if allowed else "disabled")
        except Exception:
            pass

    def _can_show_outliers(self):
        plot_type = (self.plot_type_var.get() or "radar").strip().lower()
        agg_mode = self._normalize_agg_mode(self.agg_var.get())
        return plot_type == "timeseries" and agg_mode == "raw"

    def _get_outlier_threshold(self):
        if not self.remove_outliers_var.get():
            return None
        raw = self.outlier_thresh_var.get().strip()
        if not raw:
            messagebox.showinfo(
                "Outlier threshold required",
                "Enter an outlier threshold value or untick Remove outliers.",
            )
            return "invalid"
        try:
            value = float(raw)
        except ValueError:
            messagebox.showinfo(
                "Invalid outlier threshold",
                "Outlier threshold must be a valid number.",
            )
            return "invalid"
        if value <= 0:
            messagebox.showinfo(
                "Invalid outlier threshold",
                "Outlier threshold must be greater than 0.",
            )
            return "invalid"
        return value

    def _get_outlier_threshold_value(self):
        raw = self.outlier_thresh_var.get().strip()
        if not raw:
            return None
        try:
            value = float(raw)
        except ValueError:
            return None
        if value <= 0:
            return None
        return value

    def _normalize_agg_mode(self, value: str) -> str:
        raw = str(value or "").strip().lower()
        if raw in ("raw",):
            return "raw"
        if raw in ("pedal stroke", "per pedal stroke", "pedal_stroke"):
            return "pedal_stroke"
        if raw in ("roll 360deg", "rolling 360deg", "roll_360deg"):
            return "roll_360deg"
        if raw in ("10% trimmed mean", "trimmed mean", "trimmed_mean_10"):
            return "trimmed_mean_10"
        if raw == "median":
            return "median"
        return "mean"

    def _normalize_outlier_method(self, value: str) -> str:
        return normalize_outlier_method(value)

    def _format_outlier_method_label(self, method: str) -> str:
        key = normalize_outlier_method(method)
        if key == "phase_mad":
            return "Phase-MAD"
        if key == "hampel":
            return "Hampel"
        if key == "impulse":
            return "Impulse"
        return "MAD"

    def _get_plot_sids(self, plot_type, compare, baseline_id):
        if plot_type == "bar":
            ordered = []
            for sid in self.get_plot_order_source_ids():
                if compare and sid == baseline_id:
                    ordered.append(sid)
                elif self.state.show_flag.get(sid, True):
                    ordered.append(sid)
            if compare and baseline_id and baseline_id not in ordered:
                ordered.append(baseline_id)
            return ordered

        sids = [sid for sid in self.get_plot_order_source_ids()
                if self.state.show_flag.get(sid, True)]
        if compare and baseline_id and baseline_id not in sids:
            sids.append(baseline_id)
        return sids

    def _warn_outliers_if_needed(self, plot_type, angle_col, metric_col, sentinels, compare, baseline_id):
        if not self.outlier_warnings_var.get():
            return
        if self._restoring_history:
            return
        if self.show_outliers_var.get() and self._can_show_outliers():
            return
        if self.remove_outliers_var.get():
            return
        threshold = self._get_outlier_threshold_value()
        if threshold is None:
            return
        method = self._normalize_outlier_method(self.outlier_method_var.get())
        sids = self._get_plot_sids(plot_type, compare, baseline_id)
        if not sids:
            return
        flagged = []
        for sid in sids:
            df = self._get_plot_df_for_sid(sid, plot_type)
            if df is None or metric_col not in df.columns:
                continue
            values = sanitize_numeric(df[metric_col], sentinels)
            angle_values = None
            if method == "phase_mad" and angle_col and angle_col in df.columns:
                convert_br = angle_col in (
                    "leftPedalCrankAngle", "rightPedalCrankAngle")
                angle_values = wrap_angle_deg(
                    sanitize_numeric(df[angle_col], sentinels),
                    convert_br_to_standard=convert_br,
                )
            filtered = apply_outlier_filter(
                values,
                threshold=threshold,
                method=method,
                angle_series=angle_values,
            )
            before = np.isfinite(values.to_numpy(dtype=float))
            after = np.isfinite(filtered.to_numpy(dtype=float))
            count = int(np.sum(before & ~after))
            if count > 0:
                label = self.state.id_to_display.get(
                    sid, os.path.basename(sid))
                flagged.append(f"{label} ({count})")
        if flagged:
            messagebox.showwarning(
                "Outliers detected",
                "Outliers detected above the current threshold setting in:\n\n"
                + "\n".join(flagged)
                + "\n\nConsider enabling 'Remove outliers' to clean these artefacts.",
            )

    def _warn_outlier_removal_rate(self, plot_type, angle_col, metric_col, sentinels, compare, baseline_id, threshold):
        if not self.outlier_warnings_var.get():
            return
        if self._restoring_history:
            return
        if not self.remove_outliers_var.get():
            return
        if threshold is None:
            return
        method = self._normalize_outlier_method(self.outlier_method_var.get())
        sids = self._get_plot_sids(plot_type, compare, baseline_id)
        if not sids:
            return
        flagged = []
        for sid in sids:
            df = self._get_plot_df_for_sid(sid, plot_type)
            if df is None or metric_col not in df.columns:
                continue
            values = sanitize_numeric(df[metric_col], sentinels)
            angle_values = None
            if method == "phase_mad" and angle_col and angle_col in df.columns:
                convert_br = angle_col in (
                    "leftPedalCrankAngle", "rightPedalCrankAngle")
                angle_values = wrap_angle_deg(
                    sanitize_numeric(df[angle_col], sentinels),
                    convert_br_to_standard=convert_br,
                )
            filtered = apply_outlier_filter(
                values,
                threshold=threshold,
                method=method,
                angle_series=angle_values,
            )
            before = np.isfinite(values.to_numpy(dtype=float))
            after = np.isfinite(filtered.to_numpy(dtype=float))
            total = int(np.sum(before))
            removed = int(np.sum(before & ~after))
            if total > 0 and (removed / total) > 0.05:
                label = self.state.id_to_display.get(
                    sid, os.path.basename(sid))
                pct = 100.0 * removed / total
                flagged.append(f"{label} ({pct:.1f}%)")
        if flagged:
            messagebox.showwarning(
                "High outlier removal",
                "Outlier removal exceeded 5% of data in:\n\n"
                + "\n".join(flagged)
                + "\n\nConsider increasing the outlier threshold.",
            )

    def _warn_original_binned_integrity_if_needed(
        self,
        plot_type,
        angle_col,
        metric_col,
        sentinels,
        compare,
        baseline_ids,
    ) -> None:
        if self._restoring_history:
            return
        plot_type = (plot_type or "").strip().lower()
        if plot_type not in ("radar", "cartesian"):
            return
        if not self._use_original_binned_for_plot(plot_type):
            return

        baseline_id = baseline_ids[0] if baseline_ids else ""
        sids = self._get_plot_sids(plot_type, compare, baseline_id)
        if not sids:
            return

        expected_rows = None
        if compare and baseline_id:
            baseline_df = self.state.binned.get(baseline_id)
            if baseline_df is not None and not baseline_df.empty:
                expected_rows = len(baseline_df)

        issues = []
        for sid in sids:
            label = self.state.id_to_display.get(sid, os.path.basename(sid))
            df = self.state.binned.get(sid)
            if df is None or df.empty:
                issues.append(f"{label}: missing/empty left_pedalstroke_avg block.")
                continue

            row_count = len(df)
            if row_count != 52:
                issues.append(f"{label}: expected 52 binned rows, found {row_count}.")
            if expected_rows is not None and row_count != expected_rows:
                issues.append(
                    f"{label}: row count {row_count} does not match baseline ({expected_rows}) for index-aligned comparison."
                )

            if angle_col and angle_col not in df.columns:
                issues.append(f"{label}: missing angle column '{angle_col}' in left_pedalstroke_avg.")
                continue
            if metric_col and metric_col not in df.columns:
                issues.append(f"{label}: missing metric column '{metric_col}' in left_pedalstroke_avg.")
                continue

            if angle_col and metric_col:
                convert_br = angle_col in ("leftPedalCrankAngle", "rightPedalCrankAngle")
                ang = wrap_angle_deg(
                    sanitize_numeric(df[angle_col], sentinels),
                    convert_br_to_standard=convert_br,
                ).to_numpy(dtype=float)
                vals = sanitize_numeric(df[metric_col], sentinels).to_numpy(dtype=float)
                missing_angles = int(np.sum(~np.isfinite(ang)))
                missing_vals = int(np.sum(~np.isfinite(vals)))
                if missing_angles > 0:
                    issues.append(f"{label}: {missing_angles} bin angle value(s) are missing/invalid.")
                if missing_vals > 0:
                    issues.append(f"{label}: {missing_vals} '{metric_col}' bin value(s) are missing/invalid.")

        if not issues:
            return

        msg = (
            "Original Dashboard Bins integrity check found issues in imported left_pedalstroke_avg data:\n\n"
            + "\n".join(issues[:12])
        )
        if len(issues) > 12:
            msg += f"\n... and {len(issues) - 12} more issue(s)."
        if compare and baseline_id:
            b_label = self.state.id_to_display.get(baseline_id, baseline_id)
            msg += (
                "\n\nComparison alignment note:\n"
                f"- Baseline bin angles come from '{b_label}'\n"
                "- Other datasets are matched by bin index (row position)."
            )
        messagebox.showwarning("Original Dashboard Bins check", msg)

    def _collect_outlier_points(
        self,
        plot_type,
        angle_col,
        metric_col,
        sentinels,
        value_mode,
        agg_mode,
        compare,
        baseline_id,
        outlier_threshold,
        color_map=None,
        baseline_ids=None,
    ):
        if not self.show_outliers_var.get():
            return []
        if not self._can_show_outliers():
            return []
        threshold = self._get_outlier_threshold_value()
        if threshold is None:
            return []

        method = self._normalize_outlier_method(self.outlier_method_var.get())
        plot_type = (plot_type or "").strip().lower()
        if plot_type == "bar":
            return []

        outliers = []
        sids = self._get_plot_sids(plot_type, compare, baseline_id)
        if not sids:
            return []

        if plot_type == "timeseries":
            if agg_mode != "raw":
                return []

            baseline_series = None
            resolved_baseline_ids = [
                sid for sid in (baseline_ids or []) if sid in self.state.loaded
            ]
            if not resolved_baseline_ids and baseline_id in self.state.loaded:
                resolved_baseline_ids = [baseline_id]
            if compare and resolved_baseline_ids:
                try:
                    baseline_series = _aggregate_timeseries_baseline(
                        self.state,
                        resolved_baseline_ids,
                        metric_col=metric_col,
                        agg_mode=agg_mode,
                        value_mode=value_mode,
                        sentinels=sentinels,
                        outlier_threshold=outlier_threshold,
                        outlier_method=method,
                    )
                except Exception:
                    baseline_series = None

            for sid in sids:
                if compare and sid == baseline_id:
                    continue
                df = self.state.loaded.get(sid)
                if df is None or metric_col not in df.columns:
                    continue
                values = sanitize_numeric(df[metric_col], sentinels)
                filtered = apply_outlier_filter(
                    values, threshold=threshold, method=method)
                before = np.isfinite(values.to_numpy(dtype=float))
                after = np.isfinite(filtered.to_numpy(dtype=float))
                mask = before & ~after
                if not np.any(mask):
                    continue
                vals = values.to_numpy(dtype=float)
                if value_mode == "percent_mean":
                    vals = to_percent_of_mean(vals)
                t = np.arange(len(vals), dtype=float) / 100.0

                if compare:
                    if baseline_series is None:
                        continue
                    min_len = min(len(vals), len(baseline_series))
                    if min_len == 0:
                        continue
                    t = t[:min_len]
                    vals = vals[:min_len] - baseline_series[:min_len]
                    mask = mask[:min_len]

                item = {
                    "source_id": sid,
                    "label": self.state.id_to_display.get(sid, sid),
                    "x": t[mask],
                    "y": vals[mask],
                }
                if color_map:
                    item["color"] = color_map.get(sid, "#1f77b4")
                outliers.append(item)
            return outliers

        if plot_type in ("cartesian", "radar"):
            baseline_ang = None
            baseline_vals = None
            if compare and baseline_id in self.state.loaded:
                baseline_df = self._get_plot_df_for_sid(baseline_id, plot_type)
                try:
                    baseline_ang, baseline_vals = prepare_angle_value_agg(
                        baseline_df,
                        angle_col,
                        metric_col,
                        sentinels,
                        agg=agg_mode,
                        outlier_threshold=outlier_threshold,
                        outlier_method=method,
                    )
                    if value_mode == "percent_mean":
                        baseline_vals = to_percent_of_mean(baseline_vals)
                except Exception:
                    baseline_ang, baseline_vals = None, None

            for sid in sids:
                if compare and sid == baseline_id:
                    continue
                df = self._get_plot_df_for_sid(sid, plot_type)
                if df is None or metric_col not in df.columns or angle_col not in df.columns:
                    continue
                convert_br = angle_col in (
                    "leftPedalCrankAngle", "rightPedalCrankAngle")
                ang = wrap_angle_deg(
                    sanitize_numeric(df[angle_col], sentinels),
                    convert_br_to_standard=convert_br,
                )
                values = sanitize_numeric(df[metric_col], sentinels)
                filtered = apply_outlier_filter(
                    values,
                    threshold=threshold,
                    method=method,
                    angle_series=ang if method == "phase_mad" else None,
                )
                before = np.isfinite(values.to_numpy(dtype=float))
                after = np.isfinite(filtered.to_numpy(dtype=float))
                mask = before & ~after
                if not np.any(mask):
                    continue
                ang_vals = ang.to_numpy(dtype=float)
                vals = values.to_numpy(dtype=float)
                if value_mode == "percent_mean":
                    vals = to_percent_of_mean(vals)
                ang_vals = ang_vals[mask]
                vals = vals[mask]

                if compare and baseline_ang is not None and baseline_vals is not None:
                    base_at = circular_interp_baseline(
                        baseline_ang, baseline_vals, ang_vals)
                    vals = vals - base_at

                outliers.append(
                    {
                        "source_id": sid,
                        "label": self.state.id_to_display.get(sid, sid),
                        "x": ang_vals,
                        "y": vals,
                    }
                )

            return outliers

        return []

    def _add_outlier_markers_matplotlib(self, plot_type, outlier_points):
        if not outlier_points:
            return
        plot_type = (plot_type or "").strip().lower()
        for item in outlier_points:
            x = item["x"]
            y = item["y"]
            color = item.get("color", "#d62728")
            if x is None or y is None or len(x) == 0:
                continue
            if plot_type == "radar":
                theta = np.deg2rad(x)
                self.ax.scatter(
                    theta,
                    y,
                    s=64,
                    marker="x",
                    color=color,
                    alpha=0.95,
                    linewidths=2.0,
                    zorder=5,
                )
            else:
                self.ax.scatter(
                    x,
                    y,
                    s=64,
                    marker="x",
                    color=color,
                    alpha=0.95,
                    linewidths=2.0,
                    zorder=5,
                )

    def _add_outlier_markers_plotly(self, fig, plot_type, outlier_points):
        if not outlier_points:
            return
        plot_type = (plot_type or "").strip().lower()
        for item in outlier_points:
            x = item["x"]
            y = item["y"]
            color = item.get("color", "#d62728")
            if x is None or y is None or len(x) == 0:
                continue
            if plot_type == "radar":
                fig.add_trace(
                    go.Scatterpolar(
                        r=y,
                        theta=x,
                        mode="markers",
                        name=f"{item['label']} outliers",
                        marker=dict(color=color, size=12, symbol="x",
                                    line=dict(color=color, width=2)),
                        showlegend=False,
                    )
                )
            else:
                fig.add_trace(
                    go.Scatter(
                        x=x,
                        y=y,
                        mode="markers",
                        name=f"{item['label']} outliers",
                        marker=dict(color=color, size=12, symbol="x",
                                    line=dict(color=color, width=2)),
                        showlegend=False,
                    )
                )

    def _snapshot_settings(self):
        self._sync_state_settings_from_ui()
        return {
            "angle": self.angle_var.get(),
            "metric": self.metric_var.get(),
            "agg_mode": self.agg_var.get(),
            "close_loop": bool(self.close_loop_var.get()),
            "sentinels": self.sentinels_var.get(),
            "value_mode": self.value_mode_var.get(),
            "plot_type": self.plot_type_var.get(),
            "use_plotly": bool(self.use_plotly_var.get()),
            "radar_background": bool(self.radar_background_var.get()),
            "remove_outliers": bool(self.remove_outliers_var.get()),
            "outlier_method": self.outlier_method_var.get(),
            "outlier_threshold": self.outlier_thresh_var.get(),
            "show_outliers": bool(self.show_outliers_var.get()),
            "outlier_warnings": bool(self.outlier_warnings_var.get()),
            "compare": bool(self.compare_var.get()),
            "baseline_display": self.baseline_display_var.get(),
            "baseline_displays": list(self.baseline_multi_displays),
            "range_low": self.range_low_var.get(),
            "range_high": self.range_high_var.get(),
            "range_fixed": bool(self.range_fixed_var.get()),
            "use_original_binned": bool(self.use_original_binned_var.get()),
            "show_flag": dict(self.state.show_flag),
        }

    def _update_history_buttons(self):
        if not hasattr(self, "prev_btn") or not hasattr(self, "next_btn") or not hasattr(self, "delete_btn"):
            return
        history_len = len(self._history)
        has_current = 0 <= self._history_index < len(self._history)
        self.prev_btn.configure(
            state="normal" if self._history_index > 0 else "disabled")
        self.next_btn.configure(
            state="normal" if 0 <= self._history_index < len(
                self._history) - 1 else "disabled"
        )
        self.delete_btn.configure(
            state="normal" if has_current else "disabled")
        if hasattr(self, "clear_history_btn"):
            self.clear_history_btn.configure(
                state="normal" if history_len > 0 else "disabled")
        if hasattr(self, "history_label_var"):
            if history_len:
                self.history_label_var.set(
                    f"History {self._history_index + 1}/{history_len}")
            else:
                self.history_label_var.set("History 0/0")

    def _history_payload(self):
        payload = []
        for snap in self._history:
            if not isinstance(snap, dict):
                continue
            saved = dict(snap)
            show_flag = snap.get("show_flag", {})
            if isinstance(show_flag, dict):
                # Persist visibility by source_id so history does not remap onto
                # unrelated datasets when display names are de-duplicated on load.
                saved["show_flag"] = {
                    str(sid): bool(flag)
                    for sid, flag in show_flag.items()
                    if sid
                }
            payload.append(saved)
        return payload

    def _apply_history_settings(
        self,
        settings,
        source_id_map=None,
        display_to_source_map=None,
    ):
        if not isinstance(settings, dict):
            return
        history = settings.get("plot_history")
        if not isinstance(history, list):
            self._update_history_buttons()
            return
        new_history = []
        for snap in history:
            if not isinstance(snap, dict):
                continue
            restored = dict(snap)
            show_flag = snap.get("show_flag", {})
            if isinstance(show_flag, dict):
                restored_show = {}
                for key, flag in show_flag.items():
                    key_str = str(key)
                    mapped_sid = ""
                    if isinstance(source_id_map, dict):
                        mapped_sid = str(
                            source_id_map.get(key_str, "")).strip()
                    if mapped_sid and mapped_sid in self.state.loaded:
                        restored_show[mapped_sid] = bool(flag)
                        continue
                    if key_str in self.state.loaded:
                        restored_show[key_str] = bool(flag)
                        continue
                    # Backward compatibility for old saves that keyed by display name.
                    if isinstance(display_to_source_map, dict):
                        mapped_sid = str(
                            display_to_source_map.get(key_str, "")).strip()
                        if mapped_sid and mapped_sid in self.state.loaded:
                            restored_show[mapped_sid] = bool(flag)
                restored["show_flag"] = restored_show
            new_history.append(restored)
        self._history = new_history
        try:
            history_index = int(settings.get("plot_history_index", -1))
        except (TypeError, ValueError):
            history_index = -1
        if new_history:
            self._history_index = max(
                0, min(history_index, len(new_history) - 1))
        else:
            self._history_index = -1
        self._update_history_buttons()

    def _push_history(self):
        if self._restoring_history:
            return
        snapshot = self._snapshot_settings()
        if self.use_plotly_var.get() and 0 <= self._history_index < len(self._history):
            if snapshot == self._history[self._history_index]:
                return
        if 0 <= self._history_index < len(self._history) - 1:
            insert_at = self._history_index + 1
            self._history.insert(insert_at, snapshot)
            self._history_index = insert_at
        else:
            self._history.append(snapshot)
            self._history_index = len(self._history) - 1
        self._update_history_buttons()
        self._mark_dirty()

    def _apply_snapshot(self, snap):
        missing = []
        for sid, flag in snap.get("show_flag", {}).items():
            if sid in self.state.loaded:
                self.state.show_flag[sid] = bool(flag)
            else:
                missing.append(sid)
        self._sync_treeview_from_state()

        self.angle_var.set(snap.get("angle", self.angle_var.get()))
        self.metric_var.set(snap.get("metric", self.metric_var.get()))
        snap_agg = snap.get("agg_mode", self.agg_var.get())
        norm_agg = self._normalize_agg_mode(snap_agg)
        if norm_agg == "trimmed_mean_10":
            display_agg = "10% trimmed mean"
        elif norm_agg == "pedal_stroke":
            display_agg = "pedal stroke"
        elif norm_agg == "roll_360deg":
            display_agg = "roll 360deg"
        else:
            display_agg = norm_agg
        self.agg_var.set(display_agg)
        self.close_loop_var.set(
            bool(snap.get("close_loop", self.close_loop_var.get())))
        self.sentinels_var.set(snap.get("sentinels", self.sentinels_var.get()))
        self.value_mode_var.set(
            snap.get("value_mode", self.value_mode_var.get()))
        self.plot_type_var.set(snap.get("plot_type", self.plot_type_var.get()))
        self.use_plotly_var.set(
            bool(snap.get("use_plotly", self.use_plotly_var.get())))
        self.radar_background_var.set(
            bool(snap.get("radar_background", self.radar_background_var.get())))
        self.remove_outliers_var.set(
            bool(snap.get("remove_outliers", self.remove_outliers_var.get())))
        self.outlier_method_var.set(
            snap.get("outlier_method", self.outlier_method_var.get()))
        self.outlier_thresh_var.set(
            snap.get("outlier_threshold", self.outlier_thresh_var.get()))
        self.show_outliers_var.set(
            bool(snap.get("show_outliers", self.show_outliers_var.get())))
        self._on_outlier_toggle()
        self.compare_var.set(bool(snap.get("compare", self.compare_var.get())))
        self.baseline_display_var.set(
            snap.get("baseline_display", self.baseline_display_var.get()))
        raw_baselines = snap.get(
            "baseline_displays", self.baseline_multi_displays)
        if isinstance(raw_baselines, list):
            self.baseline_multi_displays = [
                str(name) for name in raw_baselines]
        self.range_low_var.set(snap.get("range_low", self.range_low_var.get()))
        self.range_high_var.set(
            snap.get("range_high", self.range_high_var.get()))
        self.range_fixed_var.set(
            bool(snap.get("range_fixed", self.range_fixed_var.get())))
        self.use_original_binned_var.set(
            bool(snap.get("use_original_binned", self.use_original_binned_var.get())))
        self._update_original_binned_label()
        self._refresh_angle_choices()
        self.refresh_metric_choices()

        self._on_plot_type_change(apply_default_agg=False)
        self._set_compare_controls_state()
        self.refresh_baseline_choices()

        if self.compare_var.get():
            baseline_display = self.baseline_display_var.get().strip()
            baseline_id = self.state.display_to_id.get(baseline_display, "")
            if not baseline_id or baseline_id not in self.state.loaded:
                self.compare_var.set(False)
                self._set_compare_controls_state()

        self._sync_state_settings_from_ui()

        if missing:
            messagebox.showwarning(
                "Missing datasets",
                "Some datasets from this history entry are not loaded:\n\n"
                + "\n".join(missing),
            )

    def _plot_prev(self):
        if self._history_index <= 0:
            return
        self._history_index -= 1
        snap = self._history[self._history_index]
        self._update_history_buttons()
        self._restoring_history = True
        try:
            self._apply_snapshot(snap)
            self.plot()
        finally:
            self._restoring_history = False

    def _plot_next(self):
        if self._history_index >= len(self._history) - 1:
            return
        self._history_index += 1
        snap = self._history[self._history_index]
        self._update_history_buttons()
        self._restoring_history = True
        try:
            self._apply_snapshot(snap)
            self.plot()
        finally:
            self._restoring_history = False

    def _delete_history_entry(self):
        if not (0 <= self._history_index < len(self._history)):
            return
        self._history.pop(self._history_index)
        if self._history_index >= len(self._history):
            self._history_index = len(self._history) - 1
        self._update_history_buttons()
        self._mark_dirty()
        if self._history_index < 0:
            self._redraw_empty()
            return
        self._redraw_empty()

    def _clear_history(self):
        if not self._history:
            return
        confirm = messagebox.askyesno(
            "Clear history",
            "Clear all plot history entries?",
        )
        if not confirm:
            return
        self._history.clear()
        self._history_index = -1
        self._update_history_buttons()
        self._mark_dirty()

    # ---------------- Tree / list actions ----------------
    def _on_tree_click(self, event):
        region = self.files_tree.identify("region", event.x, event.y)
        if region != "cell":
            return
        col = self.files_tree.identify_column(event.x)
        try:
            col_index = int(str(col).lstrip("#")) - 1
        except Exception:
            return
        display_cols = self.files_tree.cget("displaycolumns")
        if isinstance(display_cols, str):
            display_cols = tuple(c.strip() for c in display_cols.split() if c.strip())
        else:
            display_cols = tuple(display_cols)
        col_key = display_cols[col_index] if 0 <= col_index < len(display_cols) else None
        if col_key != "show":
            return
        row_id = self.files_tree.identify_row(event.y)
        if not row_id:
            return
        self.toggle_show(row_id)
        return "break"

    def _on_tree_double_click(self, event):
        region = self.files_tree.identify("region", event.x, event.y)
        if region != "cell":
            return
        col = self.files_tree.identify_column(event.x)
        try:
            col_index = int(str(col).lstrip("#")) - 1
        except Exception:
            return
        display_cols = self.files_tree.cget("displaycolumns")
        if isinstance(display_cols, str):
            display_cols = tuple(c.strip() for c in display_cols.split() if c.strip())
        else:
            display_cols = tuple(display_cols)
        col_key = display_cols[col_index] if 0 <= col_index < len(display_cols) else None
        if col_key != "name":
            return
        row_id = self.files_tree.identify_row(event.y)
        if not row_id:
            return
        self.rename_dataset(row_id)

    def toggle_show(self, source_id: str):
        toggle_show_flag(self.state, source_id)
        self._sync_treeview_from_state()

    def toggle_all_show(self):
        items = list(ordered_source_ids(self.state))
        if not items:
            return
        any_hidden = any(not self.state.show_flag.get(iid, True)
                         for iid in items)
        new_state = True if any_hidden else False
        set_all_show_flags(self.state, new_state, items)
        self._sync_treeview_from_state()

    def rename_selected(self):
        sel = list(self.files_tree.selection())
        if len(sel) != 1:
            messagebox.showinfo(
                "Rename", "Select exactly one dataset to rename.")
            return
        self.rename_dataset(sel[0])

    def move_selected_up(self):
        sel = list(self.files_tree.selection())
        if not sel:
            return
        order = ordered_source_ids(self.state)
        selected = [iid for iid in order if iid in sel]
        for iid in selected:
            idx = order.index(iid)
            if idx <= 0:
                continue
            if order[idx - 1] in selected:
                continue
            order[idx - 1], order[idx] = order[idx], order[idx - 1]
        reorder_datasets(self.state, order)
        self._sync_treeview_from_state()
        self._mark_dirty()

    def move_selected_down(self):
        sel = list(self.files_tree.selection())
        if not sel:
            return
        order = ordered_source_ids(self.state)
        selected = [iid for iid in order if iid in sel]
        for iid in reversed(selected):
            idx = order.index(iid)
            if idx >= len(order) - 1:
                continue
            if order[idx + 1] in selected:
                continue
            order[idx + 1], order[idx] = order[idx], order[idx + 1]
        reorder_datasets(self.state, order)
        self._sync_treeview_from_state()
        self._mark_dirty()

    def sort_by_dataset_name(self):
        items = ordered_source_ids(self.state)
        if not items:
            return
        if not hasattr(self, "_dataset_sort_reverse"):
            self._dataset_sort_reverse = False
        reverse = self._dataset_sort_reverse
        items.sort(
            key=lambda iid: dataset_sort_key(
                self.state.id_to_display.get(iid, iid)),
            reverse=reverse,
        )
        reorder_datasets(self.state, items)
        self._sync_treeview_from_state()
        arrow = " \u25bc" if reverse else " \u25b2"
        self.files_tree.heading(
            "name", text="Dataset" + arrow, command=self.sort_by_dataset_name)
        self._dataset_sort_reverse = not reverse
        self._mark_dirty()

    def get_plot_order_source_ids(self):
        return ordered_source_ids(self.state)

    def rename_dataset(self, source_id: str):
        old = self.state.id_to_display.get(source_id, source_id)
        new_name = simpledialog.askstring(
            "Rename dataset", "New name:", initialvalue=old, parent=self)
        if not new_name:
            return
        new_name = new_name.strip()
        if not new_name:
            return
        new_name = state_rename_dataset(self.state, source_id, new_name)
        self._sync_treeview_from_state()
        if self.baseline_display_var.get() == old:
            self.baseline_display_var.set(new_name)
        self.refresh_baseline_choices()
        self._mark_dirty()

    def _register_dataset(self, source_id: str, display: str, df: pd.DataFrame):
        display = display if display else "Dataset"
        source_id = source_id if source_id else f"PASTE::{display}"
        display = add_dataset(self.state, source_id, display, df)
        self._sync_treeview_from_state()
        if not self.baseline_display_var.get():
            self.baseline_display_var.set(display)
        self._mark_dirty()

    def _unique_paste_source_id(self, display: str) -> str:
        base = f"PASTE::{display}"
        if base not in self.state.loaded:
            return base
        i = 2
        candidate = f"{base} ({i})"
        while candidate in self.state.loaded:
            i += 1
            candidate = f"{base} ({i})"
        return candidate

    def _unique_project_source_id(self, display: str, source_id: str = "") -> str:
        base = source_id.strip() if source_id else f"PROJECT::{display}"
        if base not in self.state.loaded:
            return base
        i = 2
        candidate = f"{base} ({i})"
        while candidate in self.state.loaded:
            i += 1
            candidate = f"{base} ({i})"
        return candidate

    # ---------------- File load / paste ----------------
    def add_files(self):
        paths = filedialog.askopenfilenames(
            title="Select data file(s)",
            filetypes=[
                ("JSON / TXT", ("*.json", "*.txt")),
                ("JSON", ("*.json",)),
                ("Text", ("*.txt",)),
                ("All files", ("*.*",)),
            ],
        )
        if not paths:
            return

        added = 0
        for p in paths:
            try:
                obj = load_json_file_obj(p)
                datasets = self._datasets_from_json_obj(obj)
                binned_by_name = self._binned_from_json_obj(obj)
                if not datasets:
                    raise ValueError("No valid datasets found in JSON file.")
                base = os.path.splitext(os.path.basename(p))[0]
                for name, df, _source_id, display_override in datasets:
                    display = display_override or (
                        base if name == "Dataset" else str(name))
                    source_id = p if name == "Dataset" else f"{p}:::{display}"
                    if source_id in self.state.loaded:
                        continue
                    self._register_dataset(
                        source_id=source_id, display=display, df=df)
                    binned_df = binned_by_name.get(str(name))
                    if binned_df is not None:
                        self.state.binned[source_id] = binned_df
                    added += 1
            except Exception as e:
                log_exception("load data from JSON failed")
                messagebox.showerror(
                    "Load failed", f"{type(e).__name__}: {e}\n\nLog: {DEFAULT_LOG_PATH}")

        if added:
            self.status.set(
                f"Loaded {added} dataset(s) from file(s). Total: {len(self.state.loaded)}")
            self.refresh_metric_choices()
            self._refresh_angle_choices()
            self.refresh_baseline_choices()
            self._auto_default_metric()
            self._mark_dirty()

    def clear_paste(self):
        self.paste_text.delete("1.0", "end")

    def load_from_paste(self):
        raw = self.paste_text.get("1.0", "end").strip()
        if not raw:
            messagebox.showinfo(
                "No text", "Paste the JSON object into the box first.")
            return
        try:
            obj = json.loads(raw)
            datasets = self._datasets_from_json_obj(obj)
            binned_by_name = self._binned_from_json_obj(obj)
        except Exception as e:
            messagebox.showerror("Paste load error",
                                 f"{type(e).__name__}: {e}")
            return

        added = 0
        for name, df, _source_id, display_override in datasets:
            display = display_override or make_unique_name(
                str(name), set(self.state.display_to_id.keys()))
            source_id = self._unique_paste_source_id(display)
            try:
                if source_id in self.state.loaded:
                    continue
                self._register_dataset(
                    source_id=source_id, display=display, df=df)
                binned_df = binned_by_name.get(str(name))
                if binned_df is not None:
                    self.state.binned[source_id] = binned_df
                added += 1
            except Exception as e:
                messagebox.showwarning(
                    "Load failed", f"Failed to load dataset '{name}':\n{e}")

        if added == 0:
            messagebox.showinfo(
                "Nothing loaded", "No valid datasets found in the pasted JSON.")
            return

        self.status.set(
            f"Loaded {added} pasted dataset(s). Total: {len(self.state.loaded)}")
        self.refresh_metric_choices()
        self._refresh_angle_choices()
        self.refresh_baseline_choices()
        self._auto_default_metric()
        if added:
            self._mark_dirty()

    def save_pasted_json(self):
        raw = self.paste_text.get("1.0", "end").strip()
        if not raw:
            messagebox.showinfo(
                "No text", "Nothing to save — paste JSON into the box first.")
            return
        try:
            obj = json.loads(raw)
        except Exception as e:
            messagebox.showerror("JSON parse error",
                                 f"Could not parse JSON:\n{e}")
            return
        default_name = datetime.now().strftime("pasted_datasets_%Y%m%d_%H%M%S.json")
        out_path = filedialog.asksaveasfilename(
            title="Save pasted datasets JSON",
            defaultextension=".json",
            initialfile=default_name,
            filetypes=[("JSON", ("*.json",)), ("All files", ("*.*",))],
        )
        if not out_path:
            return
        try:
            with open(out_path, "w", encoding="utf-8") as f:
                json.dump(obj, f, indent=2)
            self.status.set(f"Saved pasted JSON to: {out_path}")
        except Exception as e:
            messagebox.showerror("Save failed", f"Could not save:\n{e}")

    # ---------------- Metrics / baseline lists ----------------
    def refresh_metric_choices(self):
        if not self.state.loaded:
            self.metric_combo["values"] = []
            self.metric_var.set("")
            return
        numeric_sets = []
        plot_type = (self.plot_type_var.get() or "radar").strip().lower()
        for df in self._iter_plot_source_dfs(plot_type):
            numeric_cols = {
                c for c in df.columns if pd.api.types.is_numeric_dtype(df[c])}
            numeric_sets.append(numeric_cols)
        common = set.intersection(*numeric_sets) if numeric_sets else set()
        common_sorted = sorted(common)
        self.metric_combo["values"] = common_sorted
        if self.metric_var.get() and self.metric_var.get() not in common:
            self.metric_var.set("")
        self._auto_default_metric()

    def _refresh_angle_choices(self):
        if not hasattr(self, "angle_combo"):
            return
        plot_type = (self.plot_type_var.get() or "radar").strip().lower()
        if plot_type == "timeseries":
            return
        if not self._use_original_binned_for_plot(plot_type):
            default = ["leftPedalCrankAngle", "rightPedalCrankAngle"]
            self.angle_combo["values"] = default
            if self.angle_var.get() not in default:
                self.angle_var.set(default[0] if default else "")
            return

        angle_sets = []
        for df in self._iter_plot_source_dfs(plot_type):
            angle_cols = {
                c
                for c in df.columns
                if pd.api.types.is_numeric_dtype(df[c]) and "angle" in c.lower()
            }
            if angle_cols:
                angle_sets.append(angle_cols)

        common = set.intersection(*angle_sets) if angle_sets else set()
        if not common:
            common = {"leftPedalCrankAngle"}
        values = sorted(common)
        self.angle_combo["values"] = values
        if self.angle_var.get() not in values:
            self.angle_var.set(values[0] if values else "")

    def _use_original_binned_for_plot(self, plot_type: str) -> bool:
        if plot_type == "timeseries":
            return False
        return bool(self.use_original_binned_var.get())

    def _get_plot_df_for_sid(self, source_id: str, plot_type: str):
        df = None
        if self._use_original_binned_for_plot(plot_type):
            df = self.state.binned.get(source_id)
            if df is not None and not df.empty:
                return df
        return self.state.loaded.get(source_id)

    def _iter_plot_source_dfs(self, plot_type: str):
        for sid in self.state.loaded.keys():
            df = self._get_plot_df_for_sid(sid, plot_type)
            if df is not None:
                yield df

    def _auto_default_metric(self):
        vals = list(self.metric_combo["values"])
        cur = self.metric_var.get().strip()
        if cur and cur in vals:
            return
        if "leftPedalPower" in vals:
            self.metric_var.set("leftPedalPower")
            return
        for candidate in ["FilteredleftPedalPower", "rightPedalPower", "power", "Power"]:
            if candidate in vals:
                self.metric_var.set(candidate)
                return
        if vals:
            self.metric_var.set(vals[0])

    def refresh_baseline_choices(self):
        displays = [self.state.id_to_display.get(
            sid, sid) for sid in ordered_source_ids(self.state)]
        cur = self.baseline_display_var.get()
        if cur and cur not in self.state.display_to_id:
            self.baseline_display_var.set(displays[0] if displays else "")
        if not cur and displays:
            self.baseline_display_var.set(displays[0])
        self.baseline_multi_displays = [
            name for name in self.baseline_multi_displays if name in displays]
        if not self.baseline_multi_displays and self.baseline_display_var.get() in displays:
            self.baseline_multi_displays = [self.baseline_display_var.get()]
        self._rebuild_baseline_menu(displays)

    def _baseline_menu_label(self) -> str:
        if not self.baseline_multi_displays:
            return "Select baseline"
        if len(self.baseline_multi_displays) == 1:
            return self.baseline_multi_displays[0]
        return f"Baselines ({len(self.baseline_multi_displays)})"

    def _update_baseline_menu_label(self) -> None:
        if hasattr(self, "baseline_menu_var"):
            self.baseline_menu_var.set(self._baseline_menu_label())

    def _toggle_baseline_popup(self, _event=None):
        if self._baseline_popup is not None:
            return "break"
        self._open_baseline_popup()
        return "break"

    def _open_baseline_popup(self) -> None:
        if self._baseline_popup is not None:
            return
        if not self.compare_var.get():
            return
        if not self._baseline_menu_displays:
            self.refresh_baseline_choices()
        if not self._baseline_menu_displays:
            return
        popup = tk.Toplevel(self)
        popup.overrideredirect(True)
        popup.transient(self)
        popup.configure(background="white")
        popup.bind("<Escape>", lambda _e: self._close_baseline_popup(
            apply_selection=False), add=True)
        self._baseline_popup = popup

        container = tk.Frame(popup, background="white",
                             borderwidth=1, relief="solid")
        container.pack(fill="both", expand=True)
        canvas = tk.Canvas(container, background="white", highlightthickness=0)
        scrollbar = tk.Scrollbar(
            container, orient="vertical", command=canvas.yview)
        canvas.configure(yscrollcommand=scrollbar.set)
        canvas.pack(side="left", fill="both", expand=True)
        scrollbar.pack(side="right", fill="y")
        frame = tk.Frame(canvas, background="white")
        window_id = canvas.create_window((0, 0), window=frame, anchor="nw")

        def _on_frame_config(_event=None):
            canvas.configure(scrollregion=canvas.bbox("all"))
            canvas.itemconfigure(window_id, width=canvas.winfo_width())

        frame.bind("<Configure>", _on_frame_config)
        canvas.bind("<Configure>", _on_frame_config)
        for name in self._baseline_menu_displays:
            var = self._baseline_menu_vars.get(name)
            if var is None:
                var = tk.BooleanVar(value=name in self.baseline_multi_displays)
                self._baseline_menu_vars[name] = var
            cb = tk.Checkbutton(
                frame,
                text=name,
                variable=var,
                background="white",
                activebackground="#f0f0f0",
                anchor="w",
                command=self._on_baseline_menu_toggle,
            )
            cb.pack(fill="x", padx=8, pady=2)

        self._position_baseline_popup(popup)
        popup.after_idle(
            lambda: self._reposition_baseline_popup_if_open(popup))
        popup.lift()
        try:
            popup.attributes("-topmost", True)
            popup.attributes("-topmost", False)
        except Exception:
            pass
        popup.after(1, popup.focus_set)
        popup.after(50, self._bind_baseline_click_away)

    def _position_baseline_popup(self, popup: tk.Toplevel) -> None:
        self.update_idletasks()
        popup.update_idletasks()
        width = max(self.baseline_menu_btn.winfo_width(),
                    popup.winfo_reqwidth())
        height = min(popup.winfo_reqheight(), 260)
        screen_w = self.winfo_screenwidth()
        screen_h = self.winfo_screenheight()
        anchor_ok = (
            self.baseline_menu_btn.winfo_ismapped()
            and self.baseline_menu_btn.winfo_width() > 1
            and self.baseline_menu_btn.winfo_height() > 1
        )
        if anchor_ok:
            btn_root_x = self.baseline_menu_btn.winfo_rootx()
            btn_root_y = self.baseline_menu_btn.winfo_rooty()
            if btn_root_x == 0 and btn_root_y == 0:
                btn_root_x = self.winfo_rootx() + self.baseline_menu_btn.winfo_x()
                btn_root_y = self.winfo_rooty() + self.baseline_menu_btn.winfo_y()
            x = btn_root_x
            y = btn_root_y + self.baseline_menu_btn.winfo_height()
            if x + width > screen_w:
                x = max(0, screen_w - width - 10)
            if y + height > screen_h:
                y = max(0, btn_root_y - height)
            if x < 0 or y < 0:
                anchor_ok = False
        if not anchor_ok:
            pointer_x = self.winfo_pointerx()
            pointer_y = self.winfo_pointery()
            x = max(0, min(pointer_x - int(width / 2), screen_w - width))
            y = max(0, min(pointer_y + 8, screen_h - height))
        popup.geometry(f"{width}x{height}+{x}+{y}")

    def _reposition_baseline_popup_if_open(self, popup: tk.Toplevel) -> None:
        if self._baseline_popup is not popup:
            return
        self._position_baseline_popup(popup)

    def _close_baseline_popup(self, apply_selection: bool = True) -> None:
        if self._baseline_menu_widget is not None:
            try:
                self._baseline_menu_widget.unpost()
            except Exception:
                pass
        if apply_selection and self._baseline_popup is not None:
            if not self._commit_baseline_menu_selection(show_message=True):
                return
        if self._baseline_popup is None:
            return
        try:
            if self._baseline_popup_binding is not None:
                self.unbind_all("<Button-1>")
                self._baseline_popup_binding = None
            self._baseline_popup.destroy()
        except Exception:
            pass
        self._baseline_popup = None

    def _bind_baseline_click_away(self) -> None:
        if self._baseline_popup is None:
            return
        if self._baseline_popup_binding is not None:
            return
        self._baseline_popup_binding = self.bind_all(
            "<Button-1>",
            self._on_baseline_popup_click_away,
            add=True,
        )

    def _on_baseline_popup_click_away(self, event) -> None:
        popup = self._baseline_popup
        if popup is None:
            return
        widget = event.widget
        if widget is popup or widget.winfo_toplevel() is popup:
            return
        if widget is self.baseline_menu_btn:
            return
        self._close_baseline_popup(apply_selection=True)

    def _baseline_label_for_title(self, baseline_display: str) -> str:
        if len(self.baseline_multi_displays) > 1:
            return "multiple datasets"
        return baseline_display

    def _baseline_label_for_legend(self, baseline_display: str) -> str:
        if len(self.baseline_multi_displays) > 1:
            return "Baseline (multiple datasets)"
        return baseline_display

    def _apply_top_legend(self, handles, labels, font_size: int = 9) -> None:
        if not handles:
            return
        if getattr(self.ax, "legend_", None) is not None:
            try:
                self.ax.legend_.remove()
            except Exception:
                pass
        self.ax.legend(
            handles,
            labels,
            loc="upper left",
            bbox_to_anchor=(1.02, 1.0),
            fontsize=font_size,
            frameon=False,
        )

    def _apply_plotly_legend_layout(self, fig: go.Figure) -> None:
        fig.update_layout(
            legend=dict(
                orientation="v",
                yanchor="top",
                y=1.0,
                xanchor="left",
                x=1.02,
            ),
            title=dict(x=0.5, xanchor="center", y=0.99, yanchor="top"),
            margin=dict(l=60, r=140, t=60, b=60),
        )

    def _set_plot_title(self, title: str, *, pad: int = 2, y: float = 1.02) -> None:
        self.ax.set_title(title, pad=pad, y=y)

    def _rebuild_baseline_menu(self, displays: list[str]) -> None:
        self._baseline_menu_vars = {}
        self._baseline_menu_displays = list(displays)
        menu = self._baseline_menu_widget
        if menu is not None:
            try:
                menu.delete(0, "end")
            except Exception:
                pass
        for name in displays:
            var = tk.BooleanVar(value=name in self.baseline_multi_displays)
            self._baseline_menu_vars[name] = var
            if menu is not None:
                menu.add_checkbutton(
                    label=name,
                    variable=var,
                    command=self._on_baseline_menu_toggle,
                )
        self._update_baseline_menu_label()
        self._close_baseline_popup(apply_selection=False)

    def _on_baseline_menu_toggle(self) -> None:
        # Keep the popup open; commit happens on click-away.
        return

    def _commit_baseline_menu_selection(self, show_message: bool = True) -> bool:
        if not self._baseline_menu_displays:
            return True
        prev = list(self.baseline_multi_displays)
        picked = [
            name
            for name in self._baseline_menu_displays
            if self._baseline_menu_vars.get(name) and self._baseline_menu_vars[name].get()
        ]
        if not picked:
            if show_message:
                messagebox.showinfo("Selection required",
                                    "Select at least one baseline dataset.")
            picked = prev or self._baseline_menu_displays[:1]
            for name, var in self._baseline_menu_vars.items():
                var.set(name in picked)
            if not picked:
                return False
            if show_message:
                return False
        self.baseline_multi_displays = list(picked)
        if picked:
            self.baseline_display_var.set(picked[0])
        self._update_baseline_menu_label()
        self._sync_state_settings_from_ui()
        return True

    def _open_baseline_multi_select(self):
        if not self.compare_var.get():
            return
        displays = [self.state.id_to_display.get(
            sid, sid) for sid in ordered_source_ids(self.state)]
        if not displays:
            messagebox.showinfo(
                "No datasets", "Load at least one dataset first.")
            return

        win = tk.Toplevel(self)
        win.title("Select baseline datasets")
        win.transient(self)
        win.grab_set()

        ttk.Label(win, text="Select one or more baseline datasets:").grid(
            row=0, column=0, sticky="w", padx=10, pady=(10, 6))
        box = ttk.Frame(win)
        box.grid(row=1, column=0, sticky="nsew", padx=10)

        vars_by_name = {}
        selected = set(self.baseline_multi_displays)
        for idx, name in enumerate(displays):
            var = tk.BooleanVar(value=name in selected)
            vars_by_name[name] = var
            ttk.Checkbutton(box, text=name, variable=var).grid(
                row=idx, column=0, sticky="w")

        def _apply_selection():
            picked = [name for name in displays if vars_by_name[name].get()]
            if not picked:
                messagebox.showinfo("Selection required",
                                    "Select at least one baseline dataset.")
                return
            self.baseline_multi_displays = picked
            self.baseline_display_var.set(picked[0])
            self._sync_state_settings_from_ui()
            win.destroy()

        btns = ttk.Frame(win)
        btns.grid(row=2, column=0, sticky="e", padx=10, pady=(8, 10))
        ttk.Button(btns, text="Cancel", command=win.destroy).grid(
            row=0, column=0, padx=(0, 6))
        ttk.Button(btns, text="Apply", command=_apply_selection).grid(
            row=0, column=1)

    # ---------------- Project lifecycle ----------------
    def _reset_project_state(self):
        self._close_baseline_popup(apply_selection=False)
        self._last_plotly_fig = None
        self._last_plotly_title = ""
        self.report_state = None
        self._report_dirty = False
        self.report_path = ""
        self.project_title = "Untitled Project"
        self.project_path = ""
        self.plot_type_var.set("radar")
        self.value_mode_var.set("absolute")
        self.compare_var.set(False)
        self.baseline_display_var.set("")
        self.baseline_multi_displays = []
        self.angle_var.set("leftPedalCrankAngle")
        self.metric_var.set("")
        self.agg_var.set("median")
        self.close_loop_var.set(True)
        self.use_plotly_var.set(False)
        self.radar_background_var.set(True)
        self.range_low_var.set("")
        self.range_high_var.set("")
        self.range_fixed_var.set(False)
        self.use_original_binned_var.set(False)
        self.remove_outliers_var.set(False)
        self.outlier_method_var.set("MAD")
        self.outlier_thresh_var.set("4.0")
        self.show_outliers_var.set(False)
        self.outlier_warnings_var.set(True)
        self.sentinels_var.set(DEFAULT_SENTINELS)
        self.state.clear()
        self._sync_treeview_from_state()
        self._annotation_format = self._default_annotation_format()
        self._history.clear()
        self._history_index = -1
        self._update_history_buttons()
        self._mark_dirty()
        self.refresh_metric_choices()
        self.refresh_baseline_choices()
        self._refresh_angle_choices()
        self._auto_default_metric()
        self._redraw_empty()
        self._set_plot_type_controls_state()
        self._set_compare_controls_state()
        self._update_outlier_show_state()

    def new_project(self):
        if not self._prompt_save_if_dirty("starting a new project"):
            return
        self._suspend_dirty = True
        try:
            self._reset_project_state()
            self.project_title = "Untitled Project"
            self.project_path = ""
            self._clear_dirty()
        finally:
            self._suspend_dirty = False
        self.status.set("Started a new project.")

    def load_project(self):
        if not self._prompt_save_if_dirty("loading a new project"):
            return
        path = filedialog.askopenfilename(
            title="Load project",
            filetypes=[("Project (.proj.json)", ("*.proj.json",)),
                       ("JSON", ("*.json",)),
                       ("All files", ("*.*",))],
        )
        if not path:
            return
        try:
            obj = load_json_file_obj(path)
            settings = extract_project_settings(obj) or {}
            datasets = self._datasets_from_json_obj(obj)
            binned_by_name = self._binned_from_json_obj(obj)
            if not datasets:
                raise ValueError("No valid datasets found in JSON file.")

            self._suspend_dirty = True
            self._reset_project_state()

            source_id_map = {}
            display_candidates = {}
            for name, df, source_id, display_override in datasets:
                display = display_override or str(name)
                original_source_id = str(source_id or "").strip()
                source_id = self._unique_project_source_id(
                    display, original_source_id)
                self._register_dataset(
                    source_id=source_id, display=display, df=df)
                if original_source_id:
                    source_id_map[original_source_id] = source_id
                display_key = str(display).strip()
                if display_key:
                    display_candidates.setdefault(
                        display_key, []).append(source_id)
                binned_df = binned_by_name.get(str(name))
                if binned_df is not None:
                    self.state.binned[source_id] = binned_df

            if settings:
                display_to_source_map = {
                    name: sids[0]
                    for name, sids in display_candidates.items()
                    if len(sids) == 1
                }
                apply_project_settings(self.state, settings)
                self._load_annotation_format_from_project_options()
                self._sync_ui_from_state_settings()
                self._apply_history_settings(
                    settings,
                    source_id_map=source_id_map,
                    display_to_source_map=display_to_source_map,
                )

            self._sync_treeview_from_state()
            self.refresh_metric_choices()
            self._refresh_angle_choices()
            self.refresh_baseline_choices()
            self._auto_default_metric()
            if self._history:
                self._history_index = len(self._history) - 1
                self._update_history_buttons()
                self._restoring_history = True
                try:
                    self._apply_snapshot(self._history[self._history_index])
                    self.plot()
                finally:
                    self._restoring_history = False

            self.project_title = str(
                settings.get("project_title") or "").strip()
            if not self.project_title:
                self.project_title = self._project_title_from_path(path)
            else:
                self.project_title = self._normalize_project_title(
                    self.project_title)
            self.project_path = path
            self._clear_dirty()
            self.status.set(f"Loaded project: {os.path.basename(path)}")
        except Exception as e:
            log_exception("load_project failed")
            messagebox.showerror(
                "Load failed", f"{type(e).__name__}: {e}\n\nLog: {DEFAULT_LOG_PATH}")
        finally:
            self._suspend_dirty = False

    def save_project(self) -> bool:
        if not self._ensure_project_title():
            return False
        include_history = messagebox.askyesno(
            "Save plot history",
            "Do you want to save your plot history with this project?",
        )
        self.project_title = self._normalize_project_title(self.project_title)
        initial_dir = os.path.dirname(
            self.project_path) if self.project_path else ""
        initial_name = f"{self._sanitize_filename(self.project_title)}.proj.json"
        out_path = filedialog.asksaveasfilename(
            title="Save project",
            defaultextension=".proj.json",
            initialdir=initial_dir or None,
            initialfile=initial_name,
            filetypes=[("Project (.proj.json)", ("*.proj.json",)),
                       ("JSON", ("*.json",)),
                       ("All files", ("*.*",))],
        )
        if not out_path:
            return False
        try:
            new_title = self._project_title_from_path(out_path).strip()
            if new_title:
                self.project_title = new_title
            self.state.analysis_settings.report_options["annotation_format"] = json.dumps(
                self._annotation_format_payload()
            )
            payload = build_project_payload(self.state)
            settings = payload.get(PROJECT_SETTINGS_KEY)
            if isinstance(settings, dict):
                settings["project_title"] = self.project_title
                if include_history:
                    settings["plot_history"] = self._history_payload()
                    settings["plot_history_index"] = self._history_index
                else:
                    settings.pop("plot_history", None)
                    settings.pop("plot_history_index", None)
            with open(out_path, "w", encoding="utf-8") as handle:
                json.dump(payload, handle, indent=2)
            self.project_path = out_path
            self._clear_dirty()
            self._update_title_bar()
            self.status.set(f"Saved project to: {out_path}")
            if self.report_state and self._report_dirty:
                save_report = messagebox.askyesno(
                    "Save report",
                    "Do you want to save the current report as well?",
                )
                if save_report:
                    self.save_report()
            return True
        except Exception as e:
            log_exception("save_project failed")
            messagebox.showerror(
                "Save failed", f"{type(e).__name__}: {e}\n\nLog: {DEFAULT_LOG_PATH}")
            return False

    def save_data(self) -> bool:
        visible_ids = [
            sid for sid in ordered_source_ids(self.state)
            if bool(self.state.show_flag.get(sid, True))
        ]
        if not visible_ids:
            messagebox.showinfo(
                "No visible datasets",
                "No datasets are checked as Show.",
            )
            return False

        if not self._ensure_project_title():
            return False

        initial_dir = os.path.dirname(
            self.project_path) if self.project_path else ""
        initial_name = f"{self._sanitize_filename(self.project_title)}.data.json"
        out_path = filedialog.asksaveasfilename(
            title="Save data",
            defaultextension=".data.json",
            initialdir=initial_dir or None,
            initialfile=initial_name,
            filetypes=[("Data (.data.json)", ("*.data.json",)),
                       ("JSON", ("*.json",)),
                       ("All files", ("*.*",))],
        )
        if not out_path:
            return False
        try:
            payload = build_dataset_data_payload(self.state, visible_only=True)
            with open(out_path, "w", encoding="utf-8") as handle:
                json.dump(payload, handle, indent=2)
            self.status.set(
                f"Saved {len(visible_ids)} visible dataset(s) to: {out_path}")
            return True
        except Exception as e:
            log_exception("save_data failed")
            messagebox.showerror(
                "Save failed", f"{type(e).__name__}: {e}\n\nLog: {DEFAULT_LOG_PATH}")
            return False

    def _on_close(self):
        if not self._prompt_save_if_dirty("closing the application"):
            return
        if not self._prompt_save_report_if_dirty("closing the application"):
            return
        self.destroy()

    # ---------------- Remove / clear ----------------
    def remove_selected(self):
        sel = list(self.files_tree.selection())
        if not sel:
            return
        for source_id in sel:
            remove_dataset(self.state, source_id)
        self._sync_treeview_from_state()
        self.refresh_metric_choices()
        self.refresh_baseline_choices()
        self.status.set(f"Total loaded: {len(self.state.loaded)}")
        self._mark_dirty()
        if not self.state.loaded:
            self._redraw_empty()

    def clear_all(self):
        self.state.clear()
        self._sync_treeview_from_state()
        self._history.clear()
        self._history_index = -1
        self._update_history_buttons()
        self.refresh_metric_choices()
        self.refresh_baseline_choices()
        self.status.set("Cleared all data sources.")
        self._redraw_empty()
        self._mark_dirty()

    # ---------------- Plotting ----------------    # ---------------- Plotting ----------------
    def _open_plotly_figure(self, fig: go.Figure, title: str):
        with tempfile.NamedTemporaryFile(delete=False, suffix=".html") as handle:
            out_path = handle.name
        pio.write_html(fig, file=out_path, auto_open=False,
                       include_plotlyjs="cdn")
        webbrowser.open(f"file://{out_path}")
        self.status.set(
            f"{title} (interactive Plotly plot opened in browser).")

    def _plot_plotly_bar(self, angle_col, metric_col, sentinels, value_mode, agg_mode, outlier_threshold,
                         compare, baseline_id, baseline_ids, baseline_display, fixed_range):
        color_map = self._dataset_color_map()
        baseline_color = color_map.get(baseline_id, "red")
        try:
            data = prepare_bar_plot(
                self.state,
                metric_col=metric_col,
                agg_mode=agg_mode,
                value_mode=value_mode,
                compare=compare,
                baseline_id=baseline_id,
                baseline_ids=baseline_ids,
                sentinels=sentinels,
                outlier_threshold=outlier_threshold,
            )
        except Exception as e:
            messagebox.showerror("Bar plot error", str(e))
            return False

        if not data.labels:
            messagebox.showinfo("Nothing to plot",
                                "No datasets produced valid bar values.")
            return False

        range_minmax = self._minmax_from_values(data.values)
        if range_minmax:
            self._update_range_entries(*range_minmax)
        self._warn_fixed_range_no_data(data.values, fixed_range, "bar plot")

        mode_str = data.mode_label
        if data.compare:
            b_label = data.baseline_label or self.state.id_to_display.get(
                baseline_id, baseline_display)
            b_label_title = self._baseline_label_for_title(b_label)
            title = f"{data.agg_label} {metric_col} difference vs baseline {b_label_title} ({mode_str})"
            y_title = "Difference vs baseline"
        else:
            title = f"{data.agg_label} {metric_col} per dataset ({mode_str})"
            y_title = metric_col

        bar_colors = [color_map.get(self.state.display_to_id.get(
            label, ""), "#1f77b4") for label in data.labels]
        decimals = self._bar_label_decimals(data.values)
        text_values = [self._format_bar_value(
            v, decimals) for v in data.values]
        longest_label = max((len(str(label))
                            for label in data.labels), default=0)
        tick_font_size = 9 if longest_label <= 15 else 8
        value_label_angle = -55 if len(data.labels) >= 15 else 0
        fig = go.Figure()
        fig.add_bar(
            x=data.labels,
            y=data.values,
            marker_color=bar_colors,
            text=text_values,
            textposition="outside",
            textangle=value_label_angle,
            cliponaxis=False,
        )
        fig.update_layout(
            title=title,
            xaxis_title="Dataset",
            yaxis_title=y_title,
            xaxis_tickangle=-45,
            xaxis=dict(automargin=True, tickfont=dict(size=tick_font_size)),
        )
        self._apply_plotly_legend_layout(fig)
        if fixed_range:
            fig.update_yaxes(range=[fixed_range[0], fixed_range[1]])
        fig.add_shape(type="line", x0=-0.5, x1=max(len(data.labels) - 0.5, 0.5),
                      y0=0, y1=0,
                      line=dict(color=baseline_color if compare else "black", width=1.8 if compare else 1.2))

        self._last_plotly_fig = fig
        self._last_plotly_title = title
        self._open_plotly_figure(fig, f"Plotted {len(data.labels)} bar(s).")
        if data.errors:
            messagebox.showwarning(
                "Partial plot", f"Plotted {len(data.labels)} bar(s) with errors.\n\n" + "\n".join(data.errors))
        return True

    def _plot_plotly_timeseries(self, metric_col, sentinels, value_mode, agg_mode, outlier_threshold,
                                compare, baseline_id, baseline_ids, baseline_display, fixed_range):
        color_map = self._dataset_color_map()
        baseline_color = color_map.get(baseline_id, "red")

        try:
            data = prepare_timeseries_plot(
                self.state,
                metric_col=metric_col,
                agg_mode=agg_mode,
                value_mode=value_mode,
                compare=compare,
                baseline_id=baseline_id,
                baseline_ids=baseline_ids,
                sentinels=sentinels,
                outlier_threshold=outlier_threshold,
            )
        except Exception as e:
            messagebox.showerror("Time series error", str(e))
            return False

        if not data.traces:
            messagebox.showinfo(
                "Nothing to plot", "No datasets produced valid time series values.")
            return False

        fig = go.Figure()
        range_values = []
        show_outliers = self.show_outliers_var.get() and self._can_show_outliers()
        marker_size = 2 if show_outliers else 3
        line_width = 1.2 if show_outliers else 1.3
        line_alpha = 0.5 if show_outliers else 1.0
        for trace in data.traces:
            color = color_map.get(trace.source_id, "#1f77b4")
            fig.add_scatter(
                x=trace.x,
                y=trace.y,
                mode="lines+markers",
                name=trace.label,
                marker=dict(size=marker_size, color=color),
                line=dict(color=color, width=line_width),
                opacity=line_alpha,
            )
            range_values.append(trace.y)
        self._warn_fixed_range_no_data(
            self._collect_trace_values(data.traces),
            fixed_range,
            "time series plot",
        )
        outlier_points = self._collect_outlier_points(
            "timeseries",
            "",
            metric_col,
            sentinels,
            value_mode,
            agg_mode,
            compare,
            baseline_id,
            outlier_threshold,
            color_map=color_map,
            baseline_ids=baseline_ids,
        )
        self._add_outlier_markers_plotly(fig, "timeseries", outlier_points)

        mode_str = data.mode_label
        if agg_mode == "pedal_stroke":
            base_title = f"Pedal stroke {metric_col} ({mode_str})"
        elif agg_mode == "roll_360deg":
            base_title = f"Roll 360deg {metric_col} ({mode_str})"
        else:
            base_title = f"Time series {metric_col} ({mode_str})"

        if data.compare and data.baseline_label:
            b_label_title = self._baseline_label_for_title(data.baseline_label)
            title = f"{base_title} difference to Baseline ({b_label_title})"
            y_title = "Difference vs baseline"
        else:
            title = base_title
            y_title = metric_col

        if range_values:
            range_minmax = self._minmax_from_values(
                np.concatenate(range_values))
            if range_minmax:
                self._update_range_entries(*range_minmax)

        if data.compare and data.baseline_label:
            baseline_legend_label = self._baseline_label_for_legend(
                data.baseline_label)
            fig.add_scatter(
                x=[0, data.max_x], y=[0, 0], mode="lines", name=baseline_legend_label,
                line=dict(color=baseline_color, width=1.6), showlegend=True)

        fig.update_layout(
            title=title,
            xaxis_title=data.x_label,
            yaxis_title=y_title,
            showlegend=True,
        )
        self._apply_plotly_legend_layout(fig)
        if fixed_range:
            fig.update_yaxes(range=[fixed_range[0], fixed_range[1]])

        self._last_plotly_fig = fig
        self._last_plotly_title = title
        self._open_plotly_figure(fig, f"Plotted {len(data.traces)} trace(s).")
        if data.errors:
            messagebox.showwarning(
                "Partial plot", f"Plotted {len(data.traces)} trace(s) with errors.\n\n" + "\n".join(data.errors))
        return True

    def _plot_plotly_cartesian(self, angle_col, metric_col, sentinels, value_mode, agg_mode, outlier_threshold, close_loop,
                               compare, baseline_id, baseline_ids, baseline_display, fixed_range):
        fig = go.Figure()
        self._apply_cartesian_background_plotly(fig)
        color_map = self._dataset_color_map()
        baseline_color = color_map.get(baseline_id, "red")

        try:
            data = prepare_cartesian_plot(
                self.state,
                angle_col=angle_col,
                metric_col=metric_col,
                agg_mode=agg_mode,
                value_mode=value_mode,
                compare=compare,
                baseline_id=baseline_id,
                baseline_ids=baseline_ids,
                sentinels=sentinels,
                outlier_threshold=outlier_threshold,
                close_loop=close_loop,
            )
        except Exception as e:
            messagebox.showerror("Cartesian plot error", str(e))
            return False

        if not data.traces:
            messagebox.showinfo(
                "Nothing to plot", "No datasets produced valid cartesian values.")
            return False

        range_values = []
        for trace in data.traces:
            color = color_map.get(trace.source_id, "#1f77b4")
            fig.add_scatter(
                x=trace.x, y=trace.y, mode="lines+markers", name=trace.label,
                marker=dict(size=4, color=color), line=dict(color=color, width=1.5))
            range_values.append(trace.y)
        self._warn_fixed_range_no_data(
            self._collect_trace_values(data.traces),
            fixed_range,
            "cartesian plot",
        )
        outlier_points = self._collect_outlier_points(
            "cartesian",
            angle_col,
            metric_col,
            sentinels,
            value_mode,
            agg_mode,
            compare,
            baseline_id,
            outlier_threshold,
        )
        self._add_outlier_markers_plotly(fig, "cartesian", outlier_points)

        mode_str = data.mode_label
        if data.compare:
            b_label = data.baseline_label or self.state.id_to_display.get(
                baseline_id, baseline_display)
            b_label_title = self._baseline_label_for_title(b_label)
            baseline_legend_label = self._baseline_label_for_legend(b_label)
            fig.add_scatter(
                x=[0, 360], y=[0, 0], mode="lines", name=baseline_legend_label,
                line=dict(color=baseline_color, width=1.8), showlegend=True)
            title = f"{data.agg_label} {metric_col} ({mode_str}) difference to Baseline ({b_label_title})"
            y_title = "Difference vs baseline"
        else:
            title = f"{data.agg_label} {metric_col} ({mode_str})"
            y_title = metric_col

        if range_values:
            range_minmax = self._minmax_from_values(
                np.concatenate(range_values))
            if range_minmax:
                self._update_range_entries(*range_minmax)

        fig.update_layout(
            title=title,
            xaxis_title="Crank angle (deg)",
            yaxis_title=y_title,
            showlegend=True,
        )
        self._apply_plotly_legend_layout(fig)
        if fixed_range:
            fig.update_yaxes(range=[fixed_range[0], fixed_range[1]])

        self._last_plotly_fig = fig
        self._last_plotly_title = title
        self._open_plotly_figure(fig, f"Plotted {len(data.traces)} trace(s).")
        if data.errors:
            messagebox.showwarning(
                "Partial plot", f"Plotted {len(data.traces)} trace(s) with errors.\n\n" + "\n".join(data.errors))
        return True

    def _plot_plotly_radar(self, angle_col, metric_col, sentinels, value_mode, agg_mode, outlier_threshold, close_loop,
                           compare, baseline_id, baseline_ids=None, baseline_display="", fixed_range=None):
        # Backward compatibility for older positional call shape:
        # (..., compare, baseline_id, baseline_display, fixed_range)
        if fixed_range is None and isinstance(baseline_display, (tuple, list)) and len(baseline_display) == 2:
            if baseline_ids is None or isinstance(baseline_ids, str):
                fixed_range = baseline_display
                baseline_display = str(baseline_ids or "")
                baseline_ids = None
        if baseline_ids is None:
            baseline_ids = [baseline_id] if baseline_id else []
        elif isinstance(baseline_ids, str):
            baseline_ids = [baseline_ids] if baseline_ids else []
        else:
            baseline_ids = [sid for sid in baseline_ids if sid]

        fig = go.Figure()
        self._apply_radar_background_plotly(fig)
        color_map = self._dataset_color_map()
        baseline_color = color_map.get(baseline_id, "red")

        try:
            data = prepare_radar_plot(
                self.state,
                angle_col=angle_col,
                metric_col=metric_col,
                agg_mode=agg_mode,
                value_mode=value_mode,
                compare=compare,
                baseline_id=baseline_id,
                baseline_ids=baseline_ids,
                sentinels=sentinels,
                outlier_threshold=outlier_threshold,
                close_loop=close_loop,
            )
        except Exception as e:
            messagebox.showerror("Radar plot error", str(e))
            return False

        if not data.traces:
            messagebox.showinfo(
                "Nothing to plot", "No datasets produced valid radar values.")
            return False

        baseline_legend_label = ""
        if data.compare and data.baseline_label:
            baseline_legend_label = self._baseline_label_for_legend(
                data.baseline_label)
        for trace in data.traces:
            color = color_map.get(trace.source_id, "#1f77b4")
            label = baseline_legend_label if trace.is_baseline and baseline_legend_label else trace.label
            fig.add_scatterpolar(
                r=trace.y,
                theta=trace.x,
                mode="lines+markers",
                name=label,
                marker=dict(size=4, color=color),
                line=dict(color=color, width=1.5),
            )
        if data.compare:
            radar_vals = self._collect_trace_values(
                data.traces, offset=data.offset, skip_baseline=True)
        else:
            radar_vals = self._collect_trace_values(data.traces)
        self._warn_fixed_range_no_data(radar_vals, fixed_range, "radar plot")
        outlier_points = self._collect_outlier_points(
            "radar",
            angle_col,
            metric_col,
            sentinels,
            value_mode,
            agg_mode,
            compare,
            baseline_id,
            outlier_threshold,
        )
        self._add_outlier_markers_plotly(fig, "radar", outlier_points)

        mode_str = data.mode_label
        if data.compare:
            b_label = data.baseline_label or self.state.id_to_display.get(
                baseline_id, baseline_display)
            b_label_title = self._baseline_label_for_title(b_label)
            title = f"{data.agg_label} {metric_col} ({mode_str}) difference to Baseline ({b_label_title})"
        else:
            title = f"{data.agg_label} {metric_col} ({mode_str})"

        fig.update_layout(
            title=title,
            showlegend=True,
            polar=dict(
                angularaxis=dict(direction="clockwise", rotation=90),
            ),
        )
        self._apply_plotly_legend_layout(fig)
        if fixed_range:
            fig.update_polars(radialaxis=dict(
                range=[fixed_range[0], fixed_range[1]]))
        else:
            auto_range = self._radar_metric_range_from_values(radar_vals)
            if auto_range:
                if data.compare:
                    fig.update_polars(radialaxis=dict(
                        range=[auto_range[0] + data.offset, auto_range[1] + data.offset]))
                else:
                    fig.update_polars(radialaxis=dict(
                        range=[auto_range[0], auto_range[1]]))

        self._last_plotly_fig = fig
        self._last_plotly_title = title
        self._open_plotly_figure(fig, f"Plotted {len(data.traces)} trace(s).")
        if data.errors:
            messagebox.showwarning(
                "Partial plot", f"Plotted {len(data.traces)} trace(s) with errors.\n\n" + "\n".join(data.errors))
        return True

    def _sanitize_filename_part(self, value: str) -> str:
        raw = re.sub(r"[^A-Za-z0-9]+", "_", str(value or "")).strip("_")
        return raw or "data"

    def _column_name_from_label(self, label: str, default: str) -> str:
        raw = re.sub(r"[^a-z0-9]+", "_",
                     str(label or "").strip().lower()).strip("_")
        return raw or default

    def export_plot_data(self):
        if not self.state.loaded:
            messagebox.showinfo(
                "No data", "Load at least one dataset first (file or paste).")
            return

        angle_col = self.angle_var.get().strip()
        metric_col = self.metric_var.get().strip()
        if not metric_col:
            messagebox.showinfo("Missing selection", "Select a metric column.")
            return

        self._sync_state_settings_from_ui()

        sentinels = parse_sentinels(self.sentinels_var.get())
        close_loop = bool(self.close_loop_var.get())
        value_mode = self.value_mode_var.get()
        agg_mode = self._normalize_agg_mode(self.agg_var.get())
        outlier_threshold = self._get_outlier_threshold()
        if outlier_threshold == "invalid":
            return

        compare = bool(self.compare_var.get())
        baseline_display = self.baseline_display_var.get().strip()
        baseline_names = self.baseline_multi_displays or [baseline_display]
        baseline_ids = [self.state.display_to_id.get(
            name, "") for name in baseline_names]
        baseline_ids = [
            sid for sid in baseline_ids if sid in self.state.loaded]
        baseline_id = baseline_ids[0] if baseline_ids else ""

        if compare and not baseline_ids:
            messagebox.showinfo("Baseline required",
                                "Select one or more valid baseline datasets.")
            return

        plot_type = (self.plot_type_var.get() or "radar").strip().lower()
        if plot_type == "bar" and value_mode == "percent_mean":
            value_mode = "absolute"

        if plot_type in ("radar", "cartesian") and not angle_col:
            messagebox.showinfo(
                "Missing selection", "Select an angle column (required for Radar/Cartesian plots).")
            return

        rows = []
        headers = []
        errors = []
        y_label = "delta_vs_baseline" if compare else "value"

        try:
            if plot_type == "bar":
                data = prepare_bar_plot(
                    self.state,
                    metric_col=metric_col,
                    agg_mode=agg_mode,
                    value_mode=value_mode,
                    compare=compare,
                    baseline_id=baseline_id,
                    baseline_ids=baseline_ids,
                    sentinels=sentinels,
                    outlier_threshold=outlier_threshold,
                )
                if not data.labels:
                    messagebox.showinfo("Nothing to export",
                                        "No datasets produced valid bar values.")
                    return
                headers = ["dataset", y_label]
                for label, value in zip(data.labels, data.values):
                    rows.append([label, value])
                errors = data.errors

            elif plot_type == "timeseries":
                data = prepare_timeseries_plot(
                    self.state,
                    metric_col=metric_col,
                    agg_mode=agg_mode,
                    value_mode=value_mode,
                    compare=compare,
                    baseline_id=baseline_id,
                    baseline_ids=baseline_ids,
                    sentinels=sentinels,
                    outlier_threshold=outlier_threshold,
                )
                if not data.traces:
                    messagebox.showinfo("Nothing to export",
                                        "No datasets produced valid time series values.")
                    return
                x_label = self._column_name_from_label(data.x_label, "x")
                headers = ["dataset", x_label, y_label]
                for trace in data.traces:
                    for x, y in zip(trace.x, trace.y):
                        rows.append([trace.label, x, y])
                errors = data.errors

            elif plot_type == "cartesian":
                data = prepare_cartesian_plot(
                    self.state,
                    angle_col=angle_col,
                    metric_col=metric_col,
                    agg_mode=agg_mode,
                    value_mode=value_mode,
                    compare=compare,
                    baseline_id=baseline_id,
                    baseline_ids=baseline_ids,
                    sentinels=sentinels,
                    outlier_threshold=outlier_threshold,
                    close_loop=close_loop,
                )
                if not data.traces:
                    messagebox.showinfo("Nothing to export",
                                        "No datasets produced valid cartesian values.")
                    return
                headers = ["dataset", "angle_deg", y_label]
                for trace in data.traces:
                    for x, y in zip(trace.x, trace.y):
                        rows.append([trace.label, x, y])
                errors = data.errors

            else:
                data = prepare_radar_plot(
                    self.state,
                    angle_col=angle_col,
                    metric_col=metric_col,
                    agg_mode=agg_mode,
                    value_mode=value_mode,
                    compare=compare,
                    baseline_id=baseline_id,
                    baseline_ids=baseline_ids,
                    sentinels=sentinels,
                    outlier_threshold=outlier_threshold,
                    close_loop=close_loop,
                )
                if not data.traces:
                    messagebox.showinfo("Nothing to export",
                                        "No datasets produced valid radar values.")
                    return
                headers = ["dataset", "angle_deg", y_label]
                for trace in data.traces:
                    if data.compare:
                        if trace.is_baseline:
                            y_values = np.zeros_like(trace.y, dtype=float)
                        else:
                            y_values = trace.y - data.offset
                    else:
                        y_values = trace.y
                    for x, y in zip(trace.x, y_values):
                        rows.append([trace.label, x, y])
                errors = data.errors
        except Exception as exc:
            messagebox.showerror("Export failed", str(exc))
            return

        if not rows:
            messagebox.showinfo(
                "Nothing to export", "No plot data was generated.")
            return

        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        metric_part = self._sanitize_filename_part(metric_col)
        plot_part = self._sanitize_filename_part(plot_type)
        default_name = f"plot_data_{plot_part}_{metric_part}_{timestamp}.csv"
        out_path = filedialog.asksaveasfilename(
            title="Export plot data",
            defaultextension=".csv",
            filetypes=[("CSV files", "*.csv")],
            initialfile=default_name,
        )
        if not out_path:
            return

        def _csv_value(value):
            if value is None:
                return ""
            if isinstance(value, (np.floating, np.integer)):
                value = value.item()
            if isinstance(value, float) and (np.isnan(value) or np.isinf(value)):
                return ""
            return value

        try:
            with open(out_path, "w", encoding="utf-8", newline="") as handle:
                writer = csv.writer(handle)
                writer.writerow(headers)
                for row in rows:
                    writer.writerow([_csv_value(cell) for cell in row])
        except Exception as exc:
            messagebox.showerror("Export failed", f"Could not save:\n{exc}")
            return

        self.status.set(f"Exported {len(rows)} row(s) to {out_path}")
        if errors:
            messagebox.showwarning(
                "Partial export", f"Exported {len(rows)} row(s) with errors.\n\n" + "\n".join(errors))
        else:
            messagebox.showinfo(
                "Export complete", f"Exported {len(rows)} row(s).")

    def plot(self):
        if not self.state.loaded:
            messagebox.showinfo(
                "No data", "Load at least one dataset first (file or paste).")
            return

        self._reset_annotations(redraw=False)
        self._reset_plot_hover_state(redraw=False)
        use_plotly = self.use_plotly_var.get()
        use_plotly_live = use_plotly and not self._restoring_history
        if use_plotly and self.annotation_mode_var.get():
            self.annotation_mode_var.set(False)

        angle_col = self.angle_var.get().strip()
        metric_col = self.metric_var.get().strip()
        if not metric_col:
            messagebox.showinfo("Missing selection", "Select a metric column.")
            return

        self._sync_state_settings_from_ui()

        sentinels = parse_sentinels(self.sentinels_var.get())
        close_loop = bool(self.close_loop_var.get())
        value_mode = self.value_mode_var.get()
        agg_mode = self._normalize_agg_mode(self.agg_var.get())
        agg_label = {
            "mean": "Mean",
            "median": "Median",
            "trimmed_mean_10": "10% trimmed mean",
        }.get(agg_mode, "Mean")
        outlier_threshold = self._get_outlier_threshold()
        if outlier_threshold == "invalid":
            return

        compare = bool(self.compare_var.get())
        baseline_display = self.baseline_display_var.get().strip()
        baseline_names = self.baseline_multi_displays or [baseline_display]
        baseline_ids = [self.state.display_to_id.get(
            name, "") for name in baseline_names]
        baseline_ids = [
            sid for sid in baseline_ids if sid in self.state.loaded]
        baseline_id = baseline_ids[0] if baseline_ids else ""

        if compare and not baseline_ids:
            messagebox.showinfo("Baseline required",
                                "Select one or more valid baseline datasets.")
            return

        plot_type = (self.plot_type_var.get() or "radar").strip().lower()
        if plot_type == "bar" and value_mode == "percent_mean":
            value_mode = "absolute"

        fixed_range = self._get_fixed_range()
        if fixed_range == "invalid":
            return

        self._warn_original_binned_integrity_if_needed(
            plot_type,
            angle_col,
            metric_col,
            sentinels,
            compare,
            baseline_ids,
        )

        if use_plotly_live:
            if plot_type == "timeseries":
                plotted_ok = self._plot_plotly_timeseries(
                    metric_col, sentinels, value_mode, agg_mode, outlier_threshold,
                    compare, baseline_id, baseline_ids, baseline_display, fixed_range)
                if not plotted_ok:
                    return
                self._push_history()
                self._warn_outliers_if_needed(
                    plot_type, angle_col, metric_col, sentinels, compare, baseline_id)
                self._warn_outlier_removal_rate(
                    plot_type, angle_col, metric_col, sentinels, compare, baseline_id, outlier_threshold)
                return
            if plot_type == "bar":
                plotted_ok = self._plot_plotly_bar(
                    angle_col, metric_col, sentinels, value_mode, agg_mode, outlier_threshold,
                    compare, baseline_id, baseline_ids, baseline_display, fixed_range)
                if not plotted_ok:
                    return
                self._push_history()
                self._warn_outliers_if_needed(
                    plot_type, angle_col, metric_col, sentinels, compare, baseline_id)
                self._warn_outlier_removal_rate(
                    plot_type, angle_col, metric_col, sentinels, compare, baseline_id, outlier_threshold)
                return
            if not angle_col:
                messagebox.showinfo(
                    "Missing selection", "Select an angle column (required for Radar/Cartesian plots).")
                return
            if plot_type == "cartesian":
                plotted_ok = self._plot_plotly_cartesian(
                    angle_col, metric_col, sentinels, value_mode, agg_mode, outlier_threshold, close_loop,
                    compare, baseline_id, baseline_ids, baseline_display, fixed_range)
                if not plotted_ok:
                    return
                self._push_history()
                self._warn_outliers_if_needed(
                    plot_type, angle_col, metric_col, sentinels, compare, baseline_id)
                self._warn_outlier_removal_rate(
                    plot_type, angle_col, metric_col, sentinels, compare, baseline_id, outlier_threshold)
                return
            plotted_ok = self._plot_plotly_radar(
                angle_col, metric_col, sentinels, value_mode, agg_mode, outlier_threshold, close_loop,
                compare, baseline_id, baseline_ids, baseline_display, fixed_range)
            if not plotted_ok:
                return
            self._push_history()
            self._warn_outliers_if_needed(
                plot_type, angle_col, metric_col, sentinels, compare, baseline_id)
            self._warn_outlier_removal_rate(
                plot_type, angle_col, metric_col, sentinels, compare, baseline_id, outlier_threshold)
            return

        # ---- TIME SERIES PLOT ----
        if plot_type == "timeseries":
            self.fig.clf()
            self.ax = self.fig.add_subplot(111)
            self.ax.clear()

            color_map = self._dataset_color_map()
            baseline_color = color_map.get(baseline_id, "red")

            try:
                data = prepare_timeseries_plot(
                    self.state,
                    metric_col=metric_col,
                    agg_mode=agg_mode,
                    value_mode=value_mode,
                    compare=compare,
                    baseline_id=baseline_id,
                    sentinels=sentinels,
                    outlier_threshold=outlier_threshold,
                )
            except Exception as e:
                messagebox.showerror("Time series error", str(e))
                return

            if not data.traces:
                messagebox.showinfo(
                    "Nothing to plot", "No datasets produced valid time series values.")
                return

            plotted = 0
            range_values = []
            show_outliers = self.show_outliers_var.get() and self._can_show_outliers()
            marker_size = 1 if show_outliers else 3
            line_width = 1.2 if show_outliers else 1.5
            line_alpha = 0.5 if show_outliers else 1.0
            for trace in data.traces:
                color = color_map.get(trace.source_id, "#1f77b4")
                marker = "o"
                line, = self.ax.plot(
                    trace.x,
                    trace.y,
                    marker=marker,
                    markersize=marker_size,
                    linewidth=line_width,
                    label=trace.label,
                    color=color,
                    alpha=line_alpha,
                )
                self._register_line_hover_trace(
                    line,
                    label=trace.label,
                    source_id=trace.source_id,
                    x_display=trace.x,
                    y_values=trace.y,
                )
                range_values.append(trace.y)
                plotted += 1
            self._warn_fixed_range_no_data(
                self._collect_trace_values(data.traces),
                fixed_range,
                "time series plot",
            )

            mode_str = data.mode_label
            if agg_mode == "pedal_stroke":
                base_title = f"Pedal stroke {metric_col} ({mode_str})"
            elif agg_mode == "roll_360deg":
                base_title = f"Roll 360deg {metric_col} ({mode_str})"
            else:
                base_title = f"Time series {metric_col} ({mode_str})"

            if data.compare and data.baseline_label:
                baseline_legend_label = self._baseline_label_for_legend(
                    data.baseline_label)
                b_label_title = self._baseline_label_for_title(
                    data.baseline_label)
                self.ax.plot([0, data.max_x], [0, 0], color=baseline_color,
                             linewidth=1.6, label=baseline_legend_label)
                title = f"{base_title} difference to Baseline ({b_label_title})"
                y_title = "Difference vs baseline"
            else:
                title = base_title
                y_title = metric_col

            if range_values:
                range_minmax = self._minmax_from_values(
                    np.concatenate(range_values))
                if range_minmax:
                    self._update_range_entries(*range_minmax)

            self._set_plot_title(title)
            self.ax.set_xlabel(data.x_label)
            self.ax.set_ylabel(y_title)
            self.ax.grid(True, linestyle=":")
            if plotted:
                self.fig.subplots_adjust(
                    left=0.08, right=0.78, top=0.9, bottom=0.1)
                handles, labels = self.ax.get_legend_handles_labels()
                self._apply_top_legend(handles, labels, font_size=9)

            if fixed_range:
                self.ax.set_ylim(fixed_range[0], fixed_range[1])

            outlier_points = self._collect_outlier_points(
                plot_type,
                angle_col,
                metric_col,
                sentinels,
                value_mode,
                agg_mode,
                compare,
                baseline_id,
                outlier_threshold,
                color_map=color_map,
                baseline_ids=baseline_ids,
            )
            self._add_outlier_markers_matplotlib(plot_type, outlier_points)
            self.canvas.draw_idle()

            msg = f"Plotted {plotted} trace(s)."
            if data.errors:
                msg += " Some datasets failed (details shown)."
                messagebox.showwarning(
                    "Partial plot", msg + "\n\n" + "\n".join(data.errors))
            self.status.set(msg)
            self._push_history()
            self._warn_outliers_if_needed(
                plot_type, angle_col, metric_col, sentinels, compare, baseline_id)
            self._warn_outlier_removal_rate(
                plot_type, angle_col, metric_col, sentinels, compare, baseline_id, outlier_threshold)
            return

        # ---- BAR PLOT ----
        if plot_type == "bar":
            self.fig.clf()
            self.ax = self.fig.add_subplot(111)
            color_map = self._dataset_color_map()
            baseline_color = color_map.get(baseline_id, "red")

            try:
                data = prepare_bar_plot(
                    self.state,
                    metric_col=metric_col,
                    agg_mode=agg_mode,
                    value_mode=value_mode,
                    compare=compare,
                    baseline_id=baseline_id,
                    sentinels=sentinels,
                    outlier_threshold=outlier_threshold,
                )
            except Exception as e:
                messagebox.showerror("Bar plot error", str(e))
                return

            if not data.labels:
                messagebox.showinfo("Nothing to plot",
                                    "No datasets produced valid bar values.")
                self._redraw_empty()
                return

            self._warn_fixed_range_no_data(
                data.values,
                fixed_range,
                "bar plot",
            )

            x = np.arange(len(data.labels))
            # self.fig.subplots_adjust(left=0.08, right=0.98)
            baseline_label = data.baseline_label if data.compare else None
            baseline_handle = self.ax.axhline(
                0.0, color=baseline_color if compare else "black",
                linewidth=1.8 if compare else 1.2, label=baseline_label)

            bar_colors = [color_map.get(self.state.display_to_id.get(
                label, ""), "#1f77b4") for label in data.labels]
            bars = self.ax.bar(x, data.values, color=bar_colors)
            self._register_bar_hover_targets(bars, data.labels, data.values)
            self.ax.set_xticks(x)
            tick_font_size, bottom_margin = self._bar_label_layout(data.labels)
            self.ax.set_xticklabels(
                data.labels,
                rotation=45,
                ha="right",
                rotation_mode="anchor",
                fontsize=tick_font_size,
            )
            self.fig.subplots_adjust(bottom=bottom_margin)

            mode_str = data.mode_label
            if data.compare:
                b_label = data.baseline_label or self.state.id_to_display.get(
                    baseline_id, baseline_display)
                b_label_title = self._baseline_label_for_title(b_label)
                self._set_plot_title(
                    f"{data.agg_label} {metric_col} difference vs baseline {b_label_title} ({mode_str})"
                )
                self.ax.set_ylabel("Difference vs baseline")
            else:
                self._set_plot_title(
                    f"{data.agg_label} {metric_col} per dataset ({mode_str})"
                )
                self.ax.set_ylabel(metric_col)

            if fixed_range:
                self.ax.set_ylim(fixed_range[0], fixed_range[1])

            decimals = self._bar_label_decimals(data.values)
            text_values = [self._format_bar_value(
                v, decimals) for v in data.values]
            y_values = np.asarray(data.values, dtype=float)
            y_span = float(np.nanmax(y_values) -
                           np.nanmin(y_values)) if y_values.size else 0.0
            y_max_abs = float(np.nanmax(np.abs(y_values))
                              ) if y_values.size else 0.0
            y_offset = max(y_span * 0.02, y_max_abs * 0.015, 1e-6)
            value_label_rotation = 55 if len(data.labels) >= 15 else 0
            value_label_ha = "left" if value_label_rotation else "center"
            for bar, y_val, label_text in zip(bars, y_values, text_values):
                x_pos = bar.get_x() + bar.get_width() / 2
                if data.compare and y_val < 0:
                    y_pos = 0.0 - y_offset
                    va = "top"
                else:
                    y_pos = y_val + y_offset
                    va = "bottom"
                self.ax.text(
                    x_pos,
                    y_pos,
                    label_text,
                    ha=value_label_ha,
                    va=va,
                    fontsize=8,
                    rotation=value_label_rotation,
                    rotation_mode="anchor",
                )
            if not fixed_range:
                self.ax.margins(y=0.14)

            self.ax.grid(True, axis="y", linestyle=":")
            low, high = self.ax.get_ylim()
            self._update_range_entries(low, high)
            outlier_points = self._collect_outlier_points(
                plot_type,
                angle_col,
                metric_col,
                sentinels,
                value_mode,
                agg_mode,
                compare,
                baseline_id,
                outlier_threshold,
            )
            self._add_outlier_markers_matplotlib(plot_type, outlier_points)
            self.canvas.draw_idle()

            msg = f"Plotted {len(data.labels)} bar(s)."
            if data.errors:
                msg += " Some datasets failed (details shown)."
                messagebox.showwarning(
                    "Partial plot", msg + "\n\n" + "\n".join(data.errors))
            self.status.set(msg)
            self._push_history()
            self._warn_outliers_if_needed(
                plot_type, angle_col, metric_col, sentinels, compare, baseline_id)
            self._warn_outlier_removal_rate(
                plot_type, angle_col, metric_col, sentinels, compare, baseline_id, outlier_threshold)
            return

        # ---- CARTESIAN PLOT ----
        if plot_type == "cartesian":
            if not angle_col:
                messagebox.showinfo(
                    "Missing selection", "Select an angle column (required for Cartesian plot).")
                return

            self.fig.clf()
            self.ax = self.fig.add_subplot(111)
            self.ax.clear()
            self._apply_cartesian_background_matplotlib(self.ax)

            color_map = self._dataset_color_map()
            baseline_color = color_map.get(baseline_id, "red")

            try:
                data = prepare_cartesian_plot(
                    self.state,
                    angle_col=angle_col,
                    metric_col=metric_col,
                    agg_mode=agg_mode,
                    value_mode=value_mode,
                    compare=compare,
                    baseline_id=baseline_id,
                    sentinels=sentinels,
                    outlier_threshold=outlier_threshold,
                    close_loop=close_loop,
                )
            except Exception as e:
                messagebox.showerror("Cartesian plot error", str(e))
                return

            if not data.traces:
                messagebox.showinfo(
                    "Nothing to plot", "No datasets produced valid cartesian values.")
                self._redraw_empty()
                return

            plotted = 0
            range_values = []
            for trace in data.traces:
                color = color_map.get(trace.source_id, "#1f77b4")
                line, = self.ax.plot(trace.x, trace.y, marker="o",
                                     markersize=3, linewidth=1.5, label=trace.label, color=color)
                self._register_line_hover_trace(
                    line,
                    label=trace.label,
                    source_id=trace.source_id,
                    x_display=trace.x,
                    y_values=trace.y,
                )
                range_values.append(trace.y)
                plotted += 1
            self._warn_fixed_range_no_data(
                self._collect_trace_values(data.traces),
                fixed_range,
                "cartesian plot",
            )

            baseline_label = data.baseline_label if data.compare else None
            baseline_handle = self.ax.axhline(
                0.0, color=baseline_color if compare else "black",
                linewidth=1.8 if compare else 1.2, label=baseline_label)
            self.ax.set_xlabel("Crank angle (deg)")
            self.ax.set_xlim(0, 360)

            mode_str = data.mode_label
            if data.compare:
                b_label = data.baseline_label or self.state.id_to_display.get(
                    baseline_id, baseline_display)
                b_label_title = self._baseline_label_for_title(b_label)
                baseline_legend_label = self._baseline_label_for_legend(
                    b_label)
                self._set_plot_title(
                    f"{data.agg_label} {metric_col} ({mode_str}) difference to Baseline ({b_label_title})"
                )
                self.ax.set_ylabel("Difference vs baseline")
            else:
                self._set_plot_title(
                    f"{data.agg_label} {metric_col} ({mode_str})"
                )
                self.ax.set_ylabel(metric_col)

            if plotted:
                self.fig.subplots_adjust(
                    left=0.08, right=0.78, top=0.9, bottom=0.1)
                handles, labels = self.ax.get_legend_handles_labels()
                if compare and baseline_label and baseline_handle and baseline_handle not in handles:
                    handles.append(baseline_handle)
                    labels.append(baseline_label)
                if compare and baseline_label and baseline_handle in handles:
                    idx = handles.index(baseline_handle)
                    handles.insert(0, handles.pop(idx))
                    labels.insert(0, labels.pop(idx))
                if compare and baseline_label:
                    labels = [
                        baseline_legend_label if label == baseline_label else label
                        for label in labels
                    ]
                self._apply_top_legend(handles, labels, font_size=9)

            if fixed_range:
                self.ax.set_ylim(fixed_range[0], fixed_range[1])
            elif range_values:
                range_minmax = self._minmax_from_values(
                    np.concatenate(range_values))
                if range_minmax:
                    self.ax.set_ylim(range_minmax[0], range_minmax[1])
            self.ax.grid(True, linestyle=":")
            low, high = self.ax.get_ylim()
            self._update_range_entries(low, high)
            outlier_points = self._collect_outlier_points(
                plot_type,
                angle_col,
                metric_col,
                sentinels,
                value_mode,
                agg_mode,
                compare,
                baseline_id,
                outlier_threshold,
            )
            self._add_outlier_markers_matplotlib(plot_type, outlier_points)
            self.canvas.draw_idle()

            msg = f"Plotted {plotted} trace(s)."
            if data.errors:
                msg += " Some datasets failed (details shown)."
                messagebox.showwarning(
                    "Partial plot", msg + "\n\n" + "\n".join(data.errors))
            self.status.set(msg)
            self._push_history()
            self._warn_outliers_if_needed(
                plot_type, angle_col, metric_col, sentinels, compare, baseline_id)
            return

        # ---- RADAR PLOT ----
        if not angle_col:
            messagebox.showinfo(
                "Missing selection", "Select an angle column (required for Radar plot).")
            return

        if getattr(self.ax, "name", "") != "polar":
            self.fig.clf()
            self.ax = self.fig.add_subplot(111, projection="polar")

        self.ax.clear()
        self.ax.set_theta_zero_location("N")
        self.ax.set_theta_direction(-1)
        self._apply_radar_background_matplotlib(self.ax)

        color_map = self._dataset_color_map()
        baseline_color = color_map.get(baseline_id, "red")

        try:
            data = prepare_radar_plot(
                self.state,
                angle_col=angle_col,
                metric_col=metric_col,
                agg_mode=agg_mode,
                value_mode=value_mode,
                compare=compare,
                baseline_id=baseline_id,
                baseline_ids=baseline_ids,
                sentinels=sentinels,
                outlier_threshold=outlier_threshold,
                close_loop=close_loop,
            )
        except Exception as e:
            messagebox.showerror("Radar plot error", str(e))
            return

        if not data.traces:
            messagebox.showinfo(
                "Nothing to plot", "No datasets produced valid radar values.")
            self._redraw_empty()
            return

        plotted = 0
        for trace in data.traces:
            color = baseline_color if trace.is_baseline else color_map.get(
                trace.source_id, "#1f77b4")
            theta = np.deg2rad(trace.x)
            line, = self.ax.plot(theta, trace.y, marker="o",
                                 markersize=3, linewidth=1.5, label=trace.label, color=color)
            self._register_line_hover_trace(
                line,
                label=trace.label,
                source_id=trace.source_id,
                x_display=trace.x,
                y_values=trace.y,
            )
            if not trace.is_baseline:
                plotted += 1
        if data.compare:
            radar_vals = self._collect_trace_values(
                data.traces, offset=data.offset, skip_baseline=True)
        else:
            radar_vals = self._collect_trace_values(data.traces)
        self._warn_fixed_range_no_data(radar_vals, fixed_range, "radar plot")

        mode_str = data.mode_label
        if data.compare:
            b_label = data.baseline_label or self.state.id_to_display.get(
                baseline_id, baseline_display)
            b_label_title = self._baseline_label_for_title(b_label)
            baseline_legend_label = self._baseline_label_for_legend(b_label)
            self._set_plot_title(
                f"{data.agg_label} {metric_col} ({mode_str}) difference to Baseline ({b_label_title})",
                pad=8,
                y=1.08,
            )
            self.ax.grid(True)
            handles, labels = self.ax.get_legend_handles_labels()
            labels = [
                baseline_legend_label if label == b_label else label
                for label in labels
            ]
            self.fig.subplots_adjust(
                left=0.06, right=0.76, top=0.92, bottom=0.08)
            self._apply_top_legend(handles, labels, font_size=9)
            self.ax.set_position([0.06, 0.08, 0.68, 0.8])
            auto_range = None
            if fixed_range:
                self.ax.set_rlim(data.offset + fixed_range[0],
                                 data.offset + fixed_range[1])
            else:
                auto_range = self._radar_metric_range_from_values(radar_vals)
                if auto_range:
                    self.ax.set_rlim(
                        data.offset + auto_range[0],
                        data.offset + auto_range[1],
                    )
                else:
                    self.ax.autoscale(enable=True, axis="y")
                    self.ax.autoscale_view(scaley=True)
            low, high = self.ax.get_ylim()
            if fixed_range:
                self._update_range_entries(
                    low - data.offset, high - data.offset)
            elif auto_range:
                self._update_range_entries(auto_range[0], auto_range[1])
            else:
                self._update_range_entries(
                    low - data.offset, high - data.offset)
            fmt_delta_ticks(self.ax, data.offset)
        else:
            self._set_plot_title(
                f"{data.agg_label} {metric_col} ({mode_str})",
                pad=8,
                y=1.08,
            )
            self.ax.grid(True)
            self.fig.subplots_adjust(
                left=0.06, right=0.76, top=0.92, bottom=0.08)
            self.ax.set_position([0.06, 0.08, 0.68, 0.8])
            if plotted:
                handles, labels = self.ax.get_legend_handles_labels()
                self._apply_top_legend(handles, labels, font_size=9)
            auto_range = None
            if fixed_range:
                self.ax.set_rlim(fixed_range[0], fixed_range[1])
            else:
                auto_range = self._radar_metric_range_from_values(radar_vals)
                if auto_range:
                    self.ax.set_rlim(auto_range[0], auto_range[1])
                else:
                    self.ax.autoscale(enable=True, axis="y")
                    self.ax.autoscale_view(scaley=True)
            low, high = self.ax.get_ylim()
            if fixed_range:
                self._update_range_entries(low, high)
            elif auto_range:
                self._update_range_entries(auto_range[0], auto_range[1])
            else:
                self._update_range_entries(low, high)
            fmt_abs_ticks(self.ax)

        outlier_points = self._collect_outlier_points(
            plot_type,
            angle_col,
            metric_col,
            sentinels,
            value_mode,
            agg_mode,
            compare,
            baseline_id,
            outlier_threshold,
        )
        self._add_outlier_markers_matplotlib(plot_type, outlier_points)
        self.canvas.draw_idle()
        msg = f"Plotted {plotted} trace(s)."
        if data.errors:
            msg += " Some datasets failed (details shown)."
            messagebox.showwarning(
                "Partial plot", msg + "\n\n" + "\n".join(data.errors))
        self.status.set(msg)
        self._push_history()
        self._warn_outliers_if_needed(
            plot_type, angle_col, metric_col, sentinels, compare, baseline_id)
        self._warn_outlier_removal_rate(
            plot_type, angle_col, metric_col, sentinels, compare, baseline_id, outlier_threshold)

    def _radar_background_image_path(self):
        base_dir = self._assets_dir()
        candidates = (
            os.path.join(base_dir, "radar_background.png"),
            os.path.join(base_dir, "radar_background.jpg"),
            os.path.join(base_dir, "radar_background.jpeg"),
        )
        for path in candidates:
            if os.path.isfile(path):
                return path
        return candidates[0]

    def _cartesian_background_image_path(self):
        base_dir = self._assets_dir()
        return os.path.join(base_dir, "leg_muscles.jpeg")

    def _assets_dir(self):
        if getattr(sys, "_MEIPASS", None):
            return os.path.join(sys._MEIPASS, "dashboard_data_plotter", "assets")
        return os.path.normpath(
            os.path.join(
                os.path.dirname(__file__),
                "..",
                "assets",
            )
        )

    def _apply_radar_background_plotly(self, fig):
        if not self.radar_background_var.get():
            return False
        image_path = self._radar_background_image_path()
        if not os.path.isfile(image_path):
            return False
        try:
            with open(image_path, "rb") as handle:
                encoded = base64.b64encode(handle.read()).decode("ascii")
        except OSError:
            return False

        fig.add_layout_image(
            dict(
                source=f"data:image/png;base64,{encoded}",
                xref="paper",
                yref="paper",
                x=0.5,
                y=0.5,
                sizex=0.9,
                sizey=0.9,
                sizing="contain",
                xanchor="center",
                yanchor="middle",
                layer="below",
                opacity=0.6,
            )
        )
        fig.update_layout(paper_bgcolor="rgba(0,0,0,0)")
        return True

    def _cartesian_background_bands(self):
        return [
            (355.0, 95.0, "#E43C2F"),
            (80.0, 170.0, "#F48117"),
            (150.0, 185.0, "#F9DB2B"),
            (175.0, 235.0, "#3A9256"),
            (210.0, 275.0, "#2F8ADB"),
            (265.0, 5.0, "#8C58BD"),
        ]

    def _apply_cartesian_background_matplotlib(self, ax):
        if not self.radar_background_var.get():
            return False
        image_path = self._cartesian_background_image_path()
        if os.path.isfile(image_path):
            try:
                image = mpimg.imread(image_path)
                ax.imshow(
                    image,
                    extent=[120, 240, 0, 0.65],
                    transform=ax.get_xaxis_transform(),
                    zorder=0,
                    aspect="auto",
                    alpha=0.40,
                )
            except Exception:
                pass
        for idx, (start, end, color) in enumerate(self._cartesian_background_bands()):
            if idx % 2 == 0:
                ymin, ymax = 0.6, 0.8
            else:
                ymin, ymax = 0.7, 0.9
            if start <= end:
                ax.axvspan(start, end, ymin=ymin, ymax=ymax,
                           color=color, alpha=0.18, zorder=1)
            else:
                ax.axvspan(start, 360.0, ymin=ymin, ymax=ymax,
                           color=color, alpha=0.18, zorder=1)
                ax.axvspan(0.0, end, ymin=ymin, ymax=ymax,
                           color=color, alpha=0.18, zorder=1)
        return True

    def _apply_cartesian_background_plotly(self, fig):
        if not self.radar_background_var.get():
            return False
        image_path = self._cartesian_background_image_path()
        if os.path.isfile(image_path):
            try:
                with open(image_path, "rb") as handle:
                    encoded = base64.b64encode(handle.read()).decode("ascii")
                fig.add_layout_image(
                    dict(
                        source=f"data:image/jpeg;base64,{encoded}",
                        xref="paper",
                        yref="paper",
                        x=0.5,
                        y=0.5,
                        sizex=1.0,
                        sizey=1.0,
                        sizing="contain",
                        xanchor="center",
                        yanchor="middle",
                        layer="below",
                        opacity=0.18,
                    )
                )
            except OSError:
                pass
        shapes = []
        for idx, (start, end, color) in enumerate(self._cartesian_background_bands()):
            if idx % 2 == 0:
                y0, y1 = 0.6, 0.8
            else:
                y0, y1 = 0.7, 0.9
            if start <= end:
                shapes.append(dict(
                    type="rect",
                    xref="x",
                    yref="paper",
                    x0=start,
                    x1=end,
                    y0=y0,
                    y1=y1,
                    fillcolor=color,
                    opacity=0.18,
                    line=dict(width=0),
                    layer="below",
                ))
            else:
                shapes.append(dict(
                    type="rect",
                    xref="x",
                    yref="paper",
                    x0=start,
                    x1=360.0,
                    y0=y0,
                    y1=y1,
                    fillcolor=color,
                    opacity=0.18,
                    line=dict(width=0),
                    layer="below",
                ))
                shapes.append(dict(
                    type="rect",
                    xref="x",
                    yref="paper",
                    x0=0.0,
                    x1=end,
                    y0=y0,
                    y1=y1,
                    fillcolor=color,
                    opacity=0.18,
                    line=dict(width=0),
                    layer="below",
                ))
        if shapes:
            fig.update_layout(shapes=shapes)
        return True

    def _apply_radar_background_matplotlib(self, ax):
        if not self.radar_background_var.get():
            return
        image_path = self._radar_background_image_path()
        if not os.path.isfile(image_path):
            return
        try:
            image = mpimg.imread(image_path)
        except Exception:
            return
        ax.set_facecolor("none")
        ax.patch.set_alpha(0.0)
        ax.imshow(
            image,
            extent=[0, 1, 0, 1],
            transform=ax.transAxes,
            zorder=0,
            aspect="auto",
            alpha=0.5,
        )


def main():
    app = DashboardDataPlotter()
    app.mainloop()
