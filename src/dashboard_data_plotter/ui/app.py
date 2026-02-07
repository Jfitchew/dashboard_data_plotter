from dashboard_data_plotter.plotting.helpers import (
    to_percent_of_mean,
    circular_interp_baseline,
    fmt_abs_ticks,
    fmt_delta_ticks,
    choose_decimals_from_ticks,
)
from dashboard_data_plotter.data.loaders import (
    DEFAULT_SENTINELS,
    load_json_file_datasets,
    extract_named_datasets,
    make_unique_name,
    parse_sentinels,
    df_to_jsonable_records,
    prepare_angle_value,
    prepare_angle_value_agg,
)
from dashboard_data_plotter.utils.sortkeys import dataset_sort_key
from dashboard_data_plotter.utils.log import log_exception, DEFAULT_LOG_PATH
from dashboard_data_plotter.version import APP_TITLE
import os
import sys
import json
import base64
from datetime import datetime
import tempfile
import tkinter as tk
from tkinter import ttk, filedialog, messagebox, simpledialog
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
        self.title(APP_TITLE)
        self.geometry("1360x876")

        # Internal storage:
        #   source_id: unique ID (file path, or "PASTE::<name>")
        #   display_name: human name shown in listbox/legend/baseline chooser
        self.loaded = {}            # source_id -> DataFrame
        self.id_to_display = {}     # source_id -> display name
        self.display_to_id = {}     # display name -> source_id
        self.show_flag = {}         # source_id -> bool (whether to plot)

        self.angle_var = tk.StringVar(value="leftPedalCrankAngle")
        self.metric_var = tk.StringVar(value="")
        self.agg_var = tk.StringVar(value="median")
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

        # Comparison mode
        self.compare_var = tk.BooleanVar(value=False)
        self.baseline_display_var = tk.StringVar(value="")

        # Plot history
        self._history = []
        self._history_index = -1
        self._restoring_history = False

        self._build_ui()
        self._build_plot()

        self._set_plot_type_controls_state()
        self._set_compare_controls_state()

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
        for sid in self.loaded.keys():
            if sid not in ids:
                ids.append(sid)
        colors = self._dataset_color_cycle()
        return {sid: colors[idx % len(colors)] for idx, sid in enumerate(ids)}

    # ---------------- UI ----------------
    def _build_ui(self):
        self.columnconfigure(0, weight=0)
        self.columnconfigure(1, weight=1)
        self.rowconfigure(0, weight=1)

        left = ttk.Frame(self, padding=10)
        left.grid(row=0, column=0, sticky="ns")

        ttk.Label(left, text="Data sources", font=(
            "Segoe UI", 11, "bold")).grid(row=0, column=0, sticky="w")

        btns = ttk.Frame(left)
        btns.grid(row=1, column=0, sticky="ew", pady=(6, 6))
        self.btn_add_files = ttk.Button(
            btns, text="Add JSON file(s)...", command=self.add_files)
        self.btn_add_files.grid(row=0, column=0, sticky="ew")
        self.btn_clear_all = ttk.Button(
            btns, text="Clear all", command=self.clear_all, width=8)
        self.btn_clear_all.grid(row=0, column=1, padx=(6, 0))
        self.btn_save_all = ttk.Button(
            btns, text="Save all", command=self.save_all_datasets, width=8)
        self.btn_save_all.grid(row=0, column=2, padx=(6, 0))
        self.btn_remove = ttk.Button(
            btns, text="Remove", command=self.remove_selected, width=8)
        self.btn_remove.grid(row=0, column=3, padx=(6, 0))
        self.btn_rename = ttk.Button(
            btns, text="Rename", command=self.rename_selected, width=8)
        self.btn_rename.grid(row=0, column=4, padx=(6, 0))
        self.btn_move_up = ttk.Button(
            btns, text="Up", command=self.move_selected_up, width=3)
        self.btn_move_up.grid(row=0, column=5, padx=(6, 0))
        self.btn_move_down = ttk.Button(
            btns, text="Dn", command=self.move_selected_down, width=3)
        self.btn_move_down.grid(row=0, column=6, padx=(6, 0))

        # Treeview: show checkbox + dataset name
        tv_frame = ttk.Frame(left)
        tv_frame.grid(row=2, column=0, sticky="ew")
        tv_frame.columnconfigure(0, weight=1)

        self.files_tree = ttk.Treeview(
            tv_frame,
            columns=("show", "name"),
            show="headings",
            height=8,
            selectmode="extended",
        )
        self.files_tree.heading("show", text="Show",
                                command=self.toggle_all_show)
        self.files_tree.heading("name", text="Dataset",
                                command=self.sort_by_dataset_name)
        self.files_tree.column(
            "show", width=50, anchor="center", stretch=False)
        self.files_tree.column("name", width=340, anchor="w")

        self.files_tree.grid(row=0, column=0, sticky="ew")

        tv_scroll = ttk.Scrollbar(
            tv_frame, orient="vertical", command=self.files_tree.yview)
        tv_scroll.grid(row=0, column=1, sticky="ns")
        self.files_tree.configure(yscrollcommand=tv_scroll.set)

        # Toggle show when clicking the Show column; rename on double-click of name
        self.files_tree.bind("<Button-1>", self._on_tree_click, add=True)
        self.files_tree.bind(
            "<Double-1>", self._on_tree_double_click, add=True)

        # --- Paste JSON sources
        ttk.Label(left, text="Paste JSON data sources", font=(
            "Segoe UI", 10, "bold")).grid(row=3, column=0, sticky="w", pady=(10, 0))

        paste_frame = ttk.Frame(left)
        paste_frame.grid(row=4, column=0, sticky="ew", pady=(6, 6))

        self.paste_text = tk.Text(paste_frame, height=6, width=52, wrap="none")
        self.paste_text.grid(row=0, column=0, sticky="ew")

        paste_scroll = ttk.Scrollbar(
            paste_frame, orient="vertical", command=self.paste_text.yview)
        paste_scroll.grid(row=0, column=1, sticky="ns")
        self.paste_text.configure(yscrollcommand=paste_scroll.set)

        # Right-click context menu for the paste box
        self._paste_menu = tk.Menu(self, tearoff=0)
        self._paste_menu.add_command(
            label="Cut", command=lambda: self.paste_text.event_generate("<<Cut>>"))
        self._paste_menu.add_command(
            label="Copy", command=lambda: self.paste_text.event_generate("<<Copy>>"))
        self._paste_menu.add_command(
            label="Paste", command=lambda: self.paste_text.event_generate("<<Paste>>"))
        self._paste_menu.add_separator()
        self._paste_menu.add_command(
            label="Select All", command=lambda: self._select_all_in_paste())
        self._paste_menu.add_command(label="Clear", command=self.clear_paste)

        self.paste_text.bind("<Button-3>", self._show_paste_menu, add=True)

        paste_btns = ttk.Frame(left)
        paste_btns.grid(row=5, column=0, sticky="ew", pady=(2, 6))
        self.btn_load_paste = ttk.Button(
            paste_btns, text="Load pasted JSON", command=self.load_from_paste)
        self.btn_load_paste.grid(row=0, column=0, sticky="ew")
        self.btn_save_paste = ttk.Button(
            paste_btns, text="Save pasted JSON...", command=self.save_pasted_json)
        self.btn_save_paste.grid(row=0, column=1, padx=(6, 0))
        self.btn_clear_paste = ttk.Button(
            paste_btns, text="Clear pasted", command=self.clear_paste)
        self.btn_clear_paste.grid(row=0, column=2, padx=(6, 0))

        ttk.Separator(left).grid(row=6, column=0, sticky="ew", pady=10)

        ttk.Label(left, text="Plot settings", font=(
            "Segoe UI", 11, "bold")).grid(row=7, column=0, sticky="w")

        angle_frame = ttk.Frame(left)
        angle_frame.grid(row=8, column=0, sticky="ew", pady=(6, 2))

        # Plot type (radar/cartesian/bar)
        ttk.Label(angle_frame, text="Plot type:").grid(
            row=0, column=0, sticky="w")
        pt = ttk.Frame(angle_frame)
        pt.grid(row=0, column=1, sticky="w", padx=(8, 0))
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
        self.chk_plotly.grid(row=0, column=2, sticky="w", padx=(20, 0))

        self.rb_bar = ttk.Radiobutton(
            pt, text="Bar (avg)", variable=self.plot_type_var, value="bar",
            command=self._on_plot_type_change)
        self.rb_bar.grid(row=1, column=0, sticky="w")

        self.radar_background_chk = ttk.Checkbutton(
            pt,
            text="Background image",
            variable=self.radar_background_var,
        )
        self.radar_background_chk.grid(
            row=1, column=2, sticky="w", padx=(20, 0))

        ttk.Label(angle_frame, text="Angle column:").grid(
            row=1, column=0, sticky="w")
        self.angle_combo = ttk.Combobox(
            angle_frame,
            textvariable=self.angle_var,
            values=["leftPedalCrankAngle", "rightPedalCrankAngle"],
            state="readonly",
            width=30,
        )
        self.angle_combo.grid(row=1, column=1, sticky="w", padx=(8, 0))

        self.close_loop_chk = ttk.Checkbutton(
            angle_frame, text="Close loop", variable=self.close_loop_var)
        self.close_loop_chk.grid(row=1, column=1, sticky="e", padx=(0, 70))

        metric_frame = ttk.Frame(left)
        metric_frame.grid(row=9, column=0, sticky="ew", pady=(6, 2))
        ttk.Label(metric_frame, text="Metric column:").grid(
            row=0, column=0, sticky="w")
        self.metric_combo = ttk.Combobox(
            metric_frame, textvariable=self.metric_var, values=[], state="readonly", width=26)
        self.metric_combo.grid(row=0, column=1, sticky="w", padx=(8, 0))
        ttk.Label(metric_frame, text="Avg type:").grid(
            row=0, column=2, sticky="w", padx=(10, 0))
        self.agg_combo = ttk.Combobox(
            metric_frame, textvariable=self.agg_var,
            values=["mean", "median", "trimmed mean"], state="readonly", width=16)
        self.agg_combo.grid(row=0, column=3, sticky="w", padx=(6, 0))

        range_frame = ttk.Frame(left)
        range_frame.grid(row=10, column=0, sticky="ew", pady=(6, 2))
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

        sentinel_frame = ttk.Frame(left)
        sentinel_frame.grid(row=11, column=0, sticky="ew", pady=(6, 2))
        ttk.Label(sentinel_frame, text="Invalid values:").grid(
            row=0, column=0, sticky="w")
        self.sentinel_entry = ttk.Entry(
            sentinel_frame, textvariable=self.sentinels_var, width=32)
        self.sentinel_entry.grid(row=0, column=1, sticky="w", padx=(8, 0))

        ttk.Separator(left).grid(row=12, column=0, sticky="ew", pady=10)

        # Value mode
        ttk.Label(left, text="Value mode", font=("Segoe UI", 11, "bold")).grid(
            row=13, column=0, sticky="w")

        vm_frame = ttk.Frame(left)
        vm_frame.grid(row=14, column=0, sticky="ew", pady=(6, 2))
        self.rb_absolute = ttk.Radiobutton(
            vm_frame, text="Absolute metric values", variable=self.value_mode_var,
            value="absolute")
        self.rb_absolute.grid(row=0, column=0, sticky="w")
        self.rb_percent_mean = ttk.Radiobutton(
            vm_frame, text="% of dataset mean", variable=self.value_mode_var, value="percent_mean")
        self.rb_percent_mean.grid(row=0, column=1, sticky="w", padx=(20, 0))

        ttk.Separator(left).grid(row=15, column=0, sticky="ew", pady=10)

        # Comparison mode
        ttk.Label(left, text="Comparison mode", font=(
            "Segoe UI", 11, "bold")).grid(row=16, column=0, sticky="w")

        self.chk_compare = ttk.Checkbutton(
            left, text="Plot as difference vs Baseline:", variable=self.compare_var,
            command=self._on_compare_toggle)
        self.chk_compare.grid(row=17, column=0, sticky="w", pady=(6, 2))

        base_frame = ttk.Frame(left)
        base_frame.grid(row=17, column=0, sticky="e", padx=(0, 65))
        self.baseline_combo = ttk.Combobox(base_frame, textvariable=self.baseline_display_var,
                                           values=[], state="readonly", width=30)
        self.baseline_combo.grid(row=0, column=1, sticky="w", padx=(8, 0))

        ttk.Separator(left).grid(row=18, column=0, sticky="ew", pady=10)

        plot_btns = ttk.Frame(left)
        plot_btns.grid(row=19, column=0, sticky="ew", pady=(10, 0))
        plot_btns.columnconfigure(0, weight=1)
        self.plot_btn = ttk.Button(
            plot_btns, text="Plot / Refresh", command=self.plot)
        self.plot_btn.grid(row=0, column=0, sticky="ew")
        self.plot_btn.configure(style="Red.TButton")
        self.prev_btn = ttk.Button(
            plot_btns, text="Prev", command=self._plot_prev, state="disabled", width=5)
        self.prev_btn.grid(row=0, column=1, padx=(10, 0))
        self.delete_btn = ttk.Button(
            plot_btns, text="X", command=self._delete_history_entry, state="disabled", width=3)
        self.delete_btn.grid(row=0, column=2, padx=(2, 0))
        self.next_btn = ttk.Button(
            plot_btns, text="Next", command=self._plot_next, state="disabled", width=5)
        self.next_btn.grid(row=0, column=3, padx=(2, 0))

        style = ttk.Style()
        style.configure("Red.TButton", background="red", foreground="black")

        self.status = tk.StringVar(
            value="Load one or more JSON files, or paste a dataset object, to begin.")
        ttk.Label(left, textvariable=self.status, wraplength=380, foreground="#333").grid(
            row=20, column=0, sticky="w", pady=(10, 0))

        self._on_plot_type_change()
        self._set_compare_controls_state()
        self._add_tooltips()

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

        toolbar = NavigationToolbar2Tk(self.canvas, right, pack_toolbar=False)
        toolbar.update()
        toolbar.grid(row=2, column=0, sticky="ew", pady=(6, 0))

        self._redraw_empty()

    def _add_tooltips(self):
        tips = [
            (self.btn_add_files, "Load one or more JSON datasets from file."),
            (self.btn_remove, "Remove the selected dataset(s) from the list."),
            (self.btn_rename, "Rename the selected dataset."),
            (self.btn_clear_all, "Remove all loaded datasets."),
            (self.btn_save_all, "Save all datasets to a single JSON file in current order."),
            (self.btn_move_up, "Move the selected dataset(s) up in plot order."),
            (self.btn_move_down, "Move the selected dataset(s) down in plot order."),
            (self.files_tree, "Datasets in plot order. Click 'Show' to toggle visibility."),
            (self.paste_text,
             "Paste a JSON dataset object or a multi-dataset JSON blob here."),
            (self.btn_load_paste, "Load datasets from the pasted JSON."),
            (self.btn_save_paste, "Save the pasted JSON to a file."),
            (self.btn_clear_paste, "Clear the pasted JSON text."),
            (self.rb_radar, "Radar (polar) plot using crank angle."),
            (self.rb_cartesian, "Cartesian plot of metric vs crank angle (0-360°)."),
            (self.rb_bar, "Bar plot of mean metric per dataset."),
            (self.chk_plotly, "Open an interactive Plotly plot in your browser."),
            (self.radar_background_chk,
             "Toggle background image/bands\nfor radar/cartesian plots."),
            (self.angle_combo, "Crank angle column used for radar/cartesian plots."),
            (self.close_loop_chk,
             "Close loop by repeating the first point at 360°."),
            (self.metric_combo, "Metric column to plot."),
            (self.agg_combo,
             "Aggregate metric values per angle bin.\n"
             "Mean = average, Median = middle value,\n"
             "10% trimmed mean drops lowest/highest 10% first."),
            (self.range_low_entry, "Lower y-range bound (used when Fixed is on)."),
            (self.range_high_entry, "Upper y-range bound (used when Fixed is on)."),
            (self.range_fixed_chk,
             "Lock the y-range to the chosen values\n(easier to compare different plots)."),
            (self.sentinel_entry,
             "Comma-separated invalid/sentinel values to ignore."),
            (self.rb_absolute, "Plot absolute metric values."),
            (self.rb_percent_mean,
             "Plot values as percent of dataset mean (radar/cartesian only)."),
            (self.chk_compare,
             "Plot each dataset as a difference from the selected baseline."),
            (self.baseline_combo, "Choose the baseline dataset for comparison mode."),
            (self.plot_btn, "Plot or refresh using current settings."),
            (self.prev_btn, "Go to the previous plot in history."),
            (self.delete_btn, "Remove the current plot from history."),
            (self.next_btn, "Go to the next plot in history."),
        ]
        for widget, text in tips:
            ToolTip(widget, text)

    def _redraw_empty(self):
        self.ax.clear()
        self.ax.set_theta_zero_location("N")
        self.ax.set_theta_direction(-1)
        self.ax.set_title("Load data → choose metric & angle → Plot", pad=18)
        self.ax.grid(True)
        self.ax.set_position([0.02, 0.08, 0.8, 0.8])
        self.canvas.draw_idle()

    # ---------------- UI state helpers ----------------
    def _set_compare_controls_state(self):
        state = "readonly" if self.compare_var.get() else "disabled"
        self.baseline_combo.configure(state=state)

    def _set_plot_type_controls_state(self):
        plot_type = (self.plot_type_var.get() or "radar").strip().lower()
        is_bar = plot_type == "bar"
        try:
            self.angle_combo.configure(
                state="disabled" if is_bar else "readonly")
        except Exception:
            pass
        try:
            self.close_loop_chk.configure(
                state="disabled" if is_bar else "normal")
        except Exception:
            pass
        try:
            self.radar_background_chk.configure(
                state="normal" if plot_type in (
                    "radar", "cartesian") else "disabled"
            )
        except Exception:
            pass

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

    def _on_plot_type_change(self):
        is_bar = (self.plot_type_var.get() == "bar")
        if hasattr(self, "rb_percent_mean"):
            self.rb_percent_mean.configure(
                state=("disabled" if is_bar else "normal"))
        if is_bar and self.value_mode_var.get() == "percent_mean":
            self.value_mode_var.set("absolute")
        self._set_plot_type_controls_state()

    def _can_autoplot(self):
        if not self.loaded:
            return False
        if not self.metric_var.get().strip():
            return False
        plot_type = (self.plot_type_var.get() or "radar").strip().lower()
        if plot_type in ("radar", "cartesian") and not self.angle_var.get().strip():
            return False
        if self.compare_var.get():
            baseline_display = self.baseline_display_var.get().strip()
            baseline_id = self.display_to_id.get(baseline_display, "")
            if not baseline_id or baseline_id not in self.loaded:
                return False
        return True

    def _on_compare_toggle(self):
        self._set_compare_controls_state()

    def _snapshot_settings(self):
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
            "compare": bool(self.compare_var.get()),
            "baseline_display": self.baseline_display_var.get(),
            "range_low": self.range_low_var.get(),
            "range_high": self.range_high_var.get(),
            "range_fixed": bool(self.range_fixed_var.get()),
            "show_flag": dict(self.show_flag),
        }

    def _update_history_buttons(self):
        if not hasattr(self, "prev_btn") or not hasattr(self, "next_btn") or not hasattr(self, "delete_btn"):
            return
        has_current = 0 <= self._history_index < len(self._history)
        self.prev_btn.configure(
            state="normal" if self._history_index > 0 else "disabled")
        self.next_btn.configure(
            state="normal" if 0 <= self._history_index < len(
                self._history) - 1 else "disabled"
        )
        self.delete_btn.configure(
            state="normal" if has_current else "disabled")

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

    def _apply_snapshot(self, snap):
        missing = []
        for sid, flag in snap.get("show_flag", {}).items():
            if sid in self.loaded:
                self.show_flag[sid] = bool(flag)
                if self.files_tree.exists(sid):
                    name = self.files_tree.item(sid, "values")[1]
                    show_txt = "✓" if self.show_flag.get(sid, True) else ""
                    self.files_tree.item(sid, values=(show_txt, name))
            else:
                missing.append(sid)

        self.angle_var.set(snap.get("angle", self.angle_var.get()))
        self.metric_var.set(snap.get("metric", self.metric_var.get()))
        self.agg_var.set(snap.get("agg_mode", self.agg_var.get()))
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
        self.compare_var.set(bool(snap.get("compare", self.compare_var.get())))
        self.baseline_display_var.set(
            snap.get("baseline_display", self.baseline_display_var.get()))
        self.range_low_var.set(snap.get("range_low", self.range_low_var.get()))
        self.range_high_var.set(
            snap.get("range_high", self.range_high_var.get()))
        self.range_fixed_var.set(
            bool(snap.get("range_fixed", self.range_fixed_var.get())))

        self._on_plot_type_change()
        self._set_compare_controls_state()
        self.refresh_baseline_choices()

        if self.compare_var.get():
            baseline_display = self.baseline_display_var.get().strip()
            baseline_id = self.display_to_id.get(baseline_display, "")
            if not baseline_id or baseline_id not in self.loaded:
                self.compare_var.set(False)
                self._set_compare_controls_state()

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
        confirm = messagebox.askyesno(
            "Delete history entry",
            "Delete the current plot settings from history?",
        )
        if not confirm:
            return
        self._history.pop(self._history_index)
        if self._history_index >= len(self._history):
            self._history_index = len(self._history) - 1
        self._update_history_buttons()

    # ---------------- Tree / list actions ----------------
    def _on_tree_click(self, event):
        region = self.files_tree.identify("region", event.x, event.y)
        if region != "cell":
            return
        col = self.files_tree.identify_column(event.x)
        if col != "#1":
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
        if col != "#2":
            return
        row_id = self.files_tree.identify_row(event.y)
        if not row_id:
            return
        self.rename_dataset(row_id)

    def toggle_show(self, source_id: str):
        cur = bool(self.show_flag.get(source_id, True))
        new = not cur
        self.show_flag[source_id] = new
        show_txt = "✓" if new else ""
        if self.files_tree.exists(source_id):
            name = self.files_tree.item(source_id, "values")[1]
            self.files_tree.item(source_id, values=(show_txt, name))

    def toggle_all_show(self):
        items = self.files_tree.get_children("")
        if not items:
            return
        any_hidden = any(not self.show_flag.get(iid, True) for iid in items)
        new_state = True if any_hidden else False
        show_txt = "✓" if new_state else ""
        for iid in items:
            self.show_flag[iid] = new_state
            name = self.files_tree.item(iid, "values")[1]
            self.files_tree.item(iid, values=(show_txt, name))

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
        items = list(self.files_tree.get_children(""))
        selected = [iid for iid in items if iid in sel]
        for iid in selected:
            index = self.files_tree.index(iid)
            if index <= 0:
                continue
            self.files_tree.move(iid, "", index - 1)

    def move_selected_down(self):
        sel = list(self.files_tree.selection())
        if not sel:
            return
        items = list(self.files_tree.get_children(""))
        selected = [iid for iid in items if iid in sel]
        for iid in reversed(selected):
            index = self.files_tree.index(iid)
            if index >= len(items) - 1:
                continue
            self.files_tree.move(iid, "", index + 1)

    def sort_by_dataset_name(self):
        items = list(self.files_tree.get_children(""))
        if not items:
            return
        if not hasattr(self, "_dataset_sort_reverse"):
            self._dataset_sort_reverse = False
        reverse = self._dataset_sort_reverse
        items.sort(
            key=lambda iid: dataset_sort_key(
                self.files_tree.item(iid, "values")[1]),
            reverse=reverse,
        )
        for index, iid in enumerate(items):
            self.files_tree.move(iid, "", index)
        arrow = " ▼" if reverse else " ▲"
        self.files_tree.heading(
            "name", text="Dataset" + arrow, command=self.sort_by_dataset_name)
        self._dataset_sort_reverse = not reverse

    def get_plot_order_source_ids(self):
        try:
            ids = [iid for iid in self.files_tree.get_children(
                "") if iid in self.loaded]
            if ids:
                return ids
        except Exception:
            pass
        return list(self.loaded.keys())

    def rename_dataset(self, source_id: str):
        old = self.id_to_display.get(source_id, source_id)
        new_name = simpledialog.askstring(
            "Rename dataset", "New name:", initialvalue=old, parent=self)
        if not new_name:
            return
        new_name = new_name.strip()
        if not new_name:
            return
        if new_name in self.display_to_id and self.display_to_id[new_name] != source_id:
            new_name = make_unique_name(
                new_name, set(self.display_to_id.keys()))
        self.id_to_display[source_id] = new_name
        if old in self.display_to_id and self.display_to_id[old] == source_id:
            self.display_to_id.pop(old, None)
        self.display_to_id[new_name] = source_id
        if self.files_tree.exists(source_id):
            show_txt = "✓" if self.show_flag.get(source_id, True) else ""
            self.files_tree.item(source_id, values=(show_txt, new_name))
        if self.baseline_display_var.get() == old:
            self.baseline_display_var.set(new_name)
        self.refresh_baseline_choices()

    def _register_dataset(self, source_id: str, display: str, df: pd.DataFrame):
        display = make_unique_name(display, set(self.display_to_id.keys()))
        source_id = source_id if source_id else f"PASTE::{display}"
        self.loaded[source_id] = df
        self.id_to_display[source_id] = display
        self.display_to_id[display] = source_id
        self.show_flag[source_id] = True
        if not self.files_tree.exists(source_id):
            self.files_tree.insert(
                "", "end", iid=source_id, values=("✓", display))
        if not self.baseline_display_var.get():
            self.baseline_display_var.set(display)

    def _unique_paste_source_id(self, display: str) -> str:
        base = f"PASTE::{display}"
        if base not in self.loaded:
            return base
        i = 2
        candidate = f"{base} ({i})"
        while candidate in self.loaded:
            i += 1
            candidate = f"{base} ({i})"
        return candidate

    # ---------------- File load / paste ----------------
    def add_files(self):
        paths = filedialog.askopenfilenames(
            title="Select JSON file(s)",
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
                datasets = load_json_file_datasets(p)
                base = os.path.splitext(os.path.basename(p))[0]
                for name, df in datasets:
                    display = base if name == "Dataset" else str(name)
                    source_id = p if name == "Dataset" else f"{p}:::{display}"
                    if source_id in self.loaded:
                        continue
                    self._register_dataset(
                        source_id=source_id, display=display, df=df)
                    added += 1
            except Exception as e:
                log_exception("load data from JSON failed")
                messagebox.showerror(
                    "Load failed", f"{type(e).__name__}: {e}\n\nLog: {DEFAULT_LOG_PATH}")

        if added:
            self.status.set(
                f"Loaded {added} dataset(s) from file(s). Total: {len(self.loaded)}")
            self.refresh_metric_choices()
            self.refresh_baseline_choices()
            self._auto_default_metric()

    def _show_paste_menu(self, event):
        try:
            self._paste_menu.tk_popup(event.x_root, event.y_root)
        finally:
            self._paste_menu.grab_release()

    def _select_all_in_paste(self):
        self.paste_text.tag_add("sel", "1.0", "end-1c")
        self.paste_text.mark_set("insert", "1.0")
        self.paste_text.see("insert")

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
            datasets = extract_named_datasets(obj)
        except Exception as e:
            messagebox.showerror("Paste load error",
                                 f"{type(e).__name__}: {e}")
            return

        added = 0
        for name, records in datasets:
            if not isinstance(records, list) or (len(records) > 0 and not isinstance(records[0], dict)):
                continue
            display = make_unique_name(
                str(name), set(self.display_to_id.keys()))
            source_id = self._unique_paste_source_id(display)
            try:
                df = pd.DataFrame(records)
                for c in df.columns:
                    df[c] = pd.to_numeric(df[c], errors="coerce")
                if source_id in self.loaded:
                    continue
                self._register_dataset(
                    source_id=source_id, display=display, df=df)
                added += 1
            except Exception as e:
                messagebox.showwarning(
                    "Load failed", f"Failed to load dataset '{name}':\n{e}")

        if added == 0:
            messagebox.showinfo(
                "Nothing loaded", "No valid datasets found in the pasted JSON.")
            return

        self.status.set(
            f"Loaded {added} pasted dataset(s). Total: {len(self.loaded)}")
        self.refresh_metric_choices()
        self.refresh_baseline_choices()
        self._auto_default_metric()

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
        if not self.loaded:
            self.metric_combo["values"] = []
            self.metric_var.set("")
            return
        numeric_sets = []
        for df in self.loaded.values():
            numeric_cols = {
                c for c in df.columns if pd.api.types.is_numeric_dtype(df[c])}
            numeric_sets.append(numeric_cols)
        common = set.intersection(*numeric_sets) if numeric_sets else set()
        common_sorted = sorted(common)
        self.metric_combo["values"] = common_sorted
        if self.metric_var.get() and self.metric_var.get() not in common:
            self.metric_var.set("")
        self._auto_default_metric()

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
        displays = list(self.display_to_id.keys())
        displays.sort(key=dataset_sort_key)
        self.baseline_combo["values"] = displays
        cur = self.baseline_display_var.get()
        if cur and cur not in self.display_to_id:
            self.baseline_display_var.set(displays[0] if displays else "")
        if not cur and displays:
            self.baseline_display_var.set(displays[0])

    # ---------------- Saving ----------------
    def save_all_datasets(self):
        if not self.loaded:
            messagebox.showinfo("Save All", "No datasets are loaded.")
            return
        out_path = filedialog.asksaveasfilename(
            title="Save all datasets",
            defaultextension=".json",
            initialfile=f"all_datasets_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json",
            filetypes=[("JSON", ("*.json",)), ("All files", ("*.*",))],
        )
        if not out_path:
            return
        ids = self.get_plot_order_source_ids()
        for sid in self.loaded.keys():
            if sid not in ids:
                ids.append(sid)
        items = [(self.id_to_display.get(sid, sid), sid) for sid in ids]
        payload = {}
        existing = set()
        for disp, sid in items:
            name = make_unique_name(disp, existing)
            existing.add(name)
            df = self.loaded[sid]
            payload[name] = {"rideData": df_to_jsonable_records(df)}
        try:
            with open(out_path, "w", encoding="utf-8") as f:
                json.dump(payload, f, indent=2)
            self.status.set(f"Saved {len(payload)} dataset(s) to: {out_path}")
        except Exception as e:
            log_exception("save_all_datasets failed")
            messagebox.showerror(
                "Save failed", f"{type(e).__name__}: {e}\n\nLog: {DEFAULT_LOG_PATH}")

    # ---------------- Remove / clear ----------------
    def remove_selected(self):
        sel = list(self.files_tree.selection())
        if not sel:
            return
        for source_id in sel:
            if self.files_tree.exists(source_id):
                self.files_tree.delete(source_id)
            disp = self.id_to_display.pop(source_id, None)
            if disp is not None:
                self.display_to_id.pop(disp, None)
            self.loaded.pop(source_id, None)
            self.show_flag.pop(source_id, None)
        self.refresh_metric_choices()
        self.refresh_baseline_choices()
        self.status.set(f"Total loaded: {len(self.loaded)}")
        if not self.loaded:
            self._redraw_empty()

    def clear_all(self):
        for iid in self.files_tree.get_children(""):
            self.files_tree.delete(iid)
        self.loaded.clear()
        self.id_to_display.clear()
        self.display_to_id.clear()
        self.show_flag.clear()
        self.refresh_metric_choices()
        self.refresh_baseline_choices()
        self.status.set("Cleared all data sources.")
        self._redraw_empty()

    # ---------------- Plotting ----------------
    def _apply_value_mode(self, values: np.ndarray, mode: str):
        if mode == "absolute":
            return np.asarray(values, dtype=float), "absolute"
        if mode == "percent_mean":
            return to_percent_of_mean(values), "% of mean"
        raise ValueError(f"Unknown value mode: {mode}")

    def _open_plotly_figure(self, fig: go.Figure, title: str):
        with tempfile.NamedTemporaryFile(delete=False, suffix=".html") as handle:
            out_path = handle.name
        pio.write_html(fig, file=out_path, auto_open=False,
                       include_plotlyjs="cdn")
        webbrowser.open(f"file://{out_path}")
        self.status.set(
            f"{title} (interactive Plotly plot opened in browser).")

    def _plot_plotly_bar(self, angle_col, metric_col, sentinels, value_mode,
                         compare, baseline_id, baseline_display, fixed_range):
        color_map = self._dataset_color_map()
        baseline_color = color_map.get(baseline_id, "red")
        ordered = []
        for sid in self.get_plot_order_source_ids():
            if compare and sid == baseline_id:
                ordered.append(sid)
            elif self.show_flag.get(sid, True):
                ordered.append(sid)
        if compare and baseline_id and baseline_id not in ordered:
            ordered.append(baseline_id)

        baseline_mean = 0.0
        if compare:
            b_ang_deg, b_val = prepare_angle_value(
                self.loaded[baseline_id], angle_col or "leftPedalCrankAngle", metric_col, sentinels)
            b_val2, _ = self._apply_value_mode(b_val, value_mode)
            baseline_mean = float(np.nanmean(b_val2))

        labels, heights, errors, bar_colors = [], [], [], []
        for sid in ordered:
            label = self.id_to_display.get(sid, os.path.basename(sid))
            try:
                ang_deg, val = prepare_angle_value(
                    self.loaded[sid], angle_col or "leftPedalCrankAngle", metric_col, sentinels)
                val2, _ = self._apply_value_mode(val, value_mode)
                mval = float(np.nanmean(val2))
                heights.append(0.0 if compare and sid == baseline_id else (
                    mval - baseline_mean if compare else mval))
                labels.append(label)
                bar_colors.append(color_map.get(sid, "#1f77b4"))
            except Exception as e:
                errors.append(f"{label}: {e}")

        if not labels:
            messagebox.showinfo("Nothing to plot",
                                "No datasets produced valid bar values.")
            return
        range_minmax = self._minmax_from_values(heights)
        if range_minmax:
            self._update_range_entries(*range_minmax)

        mode_str = "absolute" if value_mode == "absolute" else "% of mean"
        if compare:
            b_label = self.id_to_display.get(baseline_id, baseline_display)
            title = f"Mean {metric_col} difference vs baseline {b_label} ({mode_str})"
            y_title = "Difference vs baseline"
        else:
            title = f"Mean {metric_col} per dataset ({mode_str})"
            y_title = metric_col

        fig = go.Figure()
        fig.add_bar(x=labels, y=heights, marker_color=bar_colors)
        fig.update_layout(
            title=title,
            xaxis_title="Dataset",
            yaxis_title=y_title,
            xaxis_tickangle=-45,
        )
        if fixed_range:
            fig.update_yaxes(range=[fixed_range[0], fixed_range[1]])
        fig.add_shape(type="line", x0=-0.5, x1=max(len(labels) - 0.5, 0.5),
                      y0=0, y1=0,
                      line=dict(color=baseline_color if compare else "black", width=1.8 if compare else 1.2))

        self._open_plotly_figure(fig, f"Plotted {len(labels)} bar(s).")
        if errors:
            messagebox.showwarning(
                "Partial plot", f"Plotted {len(labels)} bar(s) with errors.\n\n" + "\n".join(errors))

    def _plot_plotly_cartesian(self, angle_col, metric_col, sentinels, value_mode, agg_mode, close_loop,
                               compare, baseline_id, baseline_display, fixed_range):
        plotted, errors = 0, []
        fig = go.Figure()
        self._apply_cartesian_background_plotly(fig)
        range_values = []
        color_map = self._dataset_color_map()
        baseline_color = color_map.get(baseline_id, "red")

        if not compare:
            for sid in self.get_plot_order_source_ids():
                if not self.show_flag.get(sid, True):
                    continue
                label = self.id_to_display.get(sid, os.path.basename(sid))
                try:
                    ang_deg, val = prepare_angle_value_agg(
                        self.loaded[sid], angle_col, metric_col, sentinels, agg_mode)
                    val2, _ = self._apply_value_mode(val, value_mode)
                    m = np.isfinite(ang_deg) & np.isfinite(val2)
                    ang_deg2 = ang_deg[m]
                    val2 = val2[m]
                    if len(ang_deg2) == 0:
                        raise ValueError(
                            "No valid values after filtering.")
                    if close_loop and len(ang_deg2) > 2:
                        ang_deg2 = np.concatenate([ang_deg2, [360.0]])
                        val2 = np.concatenate([val2, [val2[0]]])
                    color = color_map.get(sid)
                    fig.add_scatter(
                        x=ang_deg2, y=val2, mode="lines+markers", name=label,
                        marker=dict(size=4, color=color), line=dict(color=color, width=1.5))
                    range_values.append(val2)
                    plotted += 1
                except Exception as e:
                    errors.append(f"{label}: {e}")

            mode_str = "absolute" if value_mode == "absolute" else "% of mean"
            title = f"{metric_col} ({mode_str})"
            y_title = metric_col
        else:
            b_label = self.id_to_display.get(
                baseline_id, os.path.basename(baseline_id))
            fig.add_scatter(
                x=[0, 360], y=[0, 0], mode="lines", name=b_label,
                line=dict(color=baseline_color, width=1.8), showlegend=True)
            try:
                b_ang_deg, b_val = prepare_angle_value_agg(
                    self.loaded[baseline_id], angle_col, metric_col, sentinels, agg_mode)
                b_val2, _ = self._apply_value_mode(b_val, value_mode)
            except Exception as e:
                messagebox.showerror(
                    "Baseline error", f"Baseline '{b_label}' failed:\n{e}")
                return

            for sid in self.get_plot_order_source_ids():
                if not self.show_flag.get(sid, True):
                    continue
                if sid == baseline_id:
                    continue
                label = self.id_to_display.get(sid, os.path.basename(sid))
                try:
                    ang_deg, val = prepare_angle_value_agg(
                        self.loaded[sid], angle_col, metric_col, sentinels, agg_mode)
                    val2, _ = self._apply_value_mode(val, value_mode)
                    base_at = circular_interp_baseline(
                        b_ang_deg, b_val2, ang_deg)
                    delta = val2 - base_at
                    m = np.isfinite(delta) & np.isfinite(ang_deg)
                    ang_deg2 = ang_deg[m]
                    delta2 = delta[m]
                    if len(ang_deg2) == 0:
                        raise ValueError(
                            "No valid comparison values after filtering.")
                    order = np.argsort(ang_deg2)
                    ang_deg2 = ang_deg2[order]
                    delta2 = delta2[order]
                    if close_loop and len(ang_deg2) > 2:
                        ang_deg2 = np.concatenate([ang_deg2, [360.0]])
                        delta2 = np.concatenate([delta2, [delta2[0]]])
                    color = color_map.get(sid)
                    fig.add_scatter(
                        x=ang_deg2, y=delta2, mode="lines+markers", name=label,
                        marker=dict(size=4, color=color), line=dict(color=color, width=1.5))
                    range_values.append(delta2)
                    plotted += 1
                except Exception as e:
                    errors.append(f"{label}: {e}")

            mode_str = "absolute" if value_mode == "absolute" else "% of mean"
            title = f"{metric_col} ({mode_str}) difference to Baseline ({b_label})"
            y_title = "Difference vs baseline"

        if plotted == 0:
            messagebox.showinfo(
                "Nothing to plot", "No datasets produced valid cartesian values.")
            return

        if range_values:
            range_minmax = self._minmax_from_values(
                np.concatenate(range_values))
            if range_minmax:
                self._update_range_entries(*range_minmax)

        if not compare:
            fig.add_shape(
                type="line", x0=0, x1=360, y0=0, y1=0,
                line=dict(color="black", width=1.2))

        fig.update_layout(
            title=title,
            xaxis_title="Crank angle (deg)",
            yaxis_title=y_title,
            xaxis=dict(range=[0, 360]),
            showlegend=True,
        )
        if fixed_range:
            fig.update_yaxes(range=[fixed_range[0], fixed_range[1]])

        self._open_plotly_figure(fig, f"Plotted {plotted} trace(s).")
        if errors:
            messagebox.showwarning(
                "Partial plot", f"Plotted {plotted} trace(s) with errors.\n\n" + "\n".join(errors))

    def _plot_plotly_radar(self, angle_col, metric_col, sentinels, value_mode, agg_mode, close_loop,
                           compare, baseline_id, baseline_display, fixed_range):
        plotted, errors = 0, []
        fig = go.Figure()
        bg_applied = self._apply_radar_background_plotly(fig)
        color_map = self._dataset_color_map()
        baseline_color = color_map.get(baseline_id, "red")

        if not compare:
            range_values = []
            for sid in self.get_plot_order_source_ids():
                if not self.show_flag.get(sid, True):
                    continue
                label = self.id_to_display.get(sid, os.path.basename(sid))
                try:
                    ang_deg, val = prepare_angle_value_agg(
                        self.loaded[sid], angle_col, metric_col, sentinels, agg_mode)
                    val2, _ = self._apply_value_mode(val, value_mode)
                    theta = np.asarray(ang_deg, dtype=float)
                    r = np.asarray(val2, dtype=float)
                    if close_loop and len(theta) > 2:
                        theta = np.concatenate([theta, [theta[0]]])
                        r = np.concatenate([r, [r[0]]])
                    color = color_map.get(sid)
                    fig.add_scatterpolar(
                        theta=theta, r=r, mode="lines+markers", name=label,
                        marker=dict(size=4, color=color), line=dict(color=color, width=1.5))
                    range_values.append(val2)
                    plotted += 1
                except Exception as e:
                    errors.append(f"{label}: {e}")

            if range_values:
                range_minmax = self._minmax_from_values(
                    np.concatenate(range_values))
                if range_minmax:
                    self._update_range_entries(*range_minmax)

            mode_str = "absolute" if value_mode == "absolute" else "% of mean"
            polar_layout = dict(
                angularaxis=dict(
                    direction="clockwise",
                    rotation=90,
                    showgrid=True,
                    showline=True,
                ),
                radialaxis=dict(showgrid=True, showline=True),
            )
            if bg_applied:
                polar_layout["bgcolor"] = "rgba(0,0,0,0)"
                polar_layout["angularaxis"]["gridcolor"] = "#A5A5A5"
                polar_layout["angularaxis"]["linecolor"] = "#A5A5A5"
                polar_layout["radialaxis"]["gridcolor"] = "#A5A5A5"
                polar_layout["radialaxis"]["linecolor"] = "#797979"
            fig.update_layout(
                title=f"{metric_col} ({mode_str})",
                polar=polar_layout,
                showlegend=True,
            )
            if fixed_range:
                fig.update_layout(
                    polar=dict(radialaxis=dict(range=[fixed_range[0], fixed_range[1]])))
        else:
            b_label = self.id_to_display.get(
                baseline_id, os.path.basename(baseline_id))
            try:
                b_ang_deg, b_val = prepare_angle_value_agg(
                    self.loaded[baseline_id], angle_col, metric_col, sentinels, agg_mode)
                b_val2, _ = self._apply_value_mode(b_val, value_mode)
            except Exception as e:
                messagebox.showerror(
                    "Baseline error", f"Baseline '{b_label}' failed:\n{e}")
                return

            deltas_by_id = {}
            max_abs = 0.0
            range_values = []

            for sid in self.get_plot_order_source_ids():
                if not self.show_flag.get(sid, True):
                    continue
                if sid == baseline_id:
                    continue
                label = self.id_to_display.get(sid, os.path.basename(sid))
                try:
                    ang_deg, val = prepare_angle_value_agg(
                        self.loaded[sid], angle_col, metric_col, sentinels, agg_mode)
                    val2, _ = self._apply_value_mode(val, value_mode)
                    base_at = circular_interp_baseline(
                        b_ang_deg, b_val2, ang_deg)
                    delta = val2 - base_at
                    m = np.isfinite(delta) & np.isfinite(ang_deg)
                    ang_deg2 = ang_deg[m]
                    delta2 = delta[m]
                    if len(ang_deg2) == 0:
                        raise ValueError(
                            "No valid comparison values after filtering.")
                    order = np.argsort(ang_deg2)
                    ang_deg2 = ang_deg2[order]
                    delta2 = delta2[order]
                    deltas_by_id[sid] = (ang_deg2, delta2)
                    range_values.append(delta2)
                    this_max = float(np.nanmax(np.abs(delta2)))
                    if np.isfinite(this_max):
                        max_abs = max(max_abs, this_max)
                except Exception as e:
                    errors.append(f"{label}: {e}")

            if not deltas_by_id:
                messagebox.showinfo(
                    "Nothing to plot", "No non-baseline datasets produced valid comparison traces.")
                return

            if max_abs <= 0 or not np.isfinite(max_abs):
                max_abs = 1.0
            offset = 1.10 * max_abs

            if range_values:
                range_minmax = self._minmax_from_values(
                    np.concatenate(range_values))
                if range_minmax:
                    self._update_range_entries(*range_minmax)

            theta_ring = np.linspace(0, 360, 361)
            r_ring = np.full_like(theta_ring, offset, dtype=float)
            fig.add_scatterpolar(
                theta=theta_ring, r=r_ring, mode="lines",
                line=dict(width=2.6, color=baseline_color),
                name=b_label)

            for sid, (ang_deg2, delta2) in deltas_by_id.items():
                label = self.id_to_display.get(sid, os.path.basename(sid))
                theta = np.asarray(ang_deg2, dtype=float)
                r = np.asarray(delta2 + offset, dtype=float)
                if close_loop and len(theta) > 2:
                    theta = np.concatenate([theta, [theta[0]]])
                    r = np.concatenate([r, [r[0]]])
                color = color_map.get(sid)
                fig.add_scatterpolar(
                    theta=theta, r=r, mode="lines+markers", name=label,
                    marker=dict(size=4, color=color), line=dict(color=color, width=1.5))
                plotted += 1

            tick_vals = np.linspace(-max_abs, max_abs, 5)
            decimals = choose_decimals_from_ticks(tick_vals)
            tick_text = [f"{v:.{decimals}f}" for v in tick_vals]
            tick_positions = tick_vals + offset

            mode_str = "absolute" if value_mode == "absolute" else "% of mean"
            radialaxis = dict(
                tickvals=tick_positions,
                ticktext=tick_text,
                showgrid=True,
                showline=True,
            )
            if fixed_range:
                radialaxis["range"] = [offset + fixed_range[0],
                                       offset + fixed_range[1]]
            polar_layout = dict(
                angularaxis=dict(
                    direction="clockwise",
                    rotation=90,
                    showgrid=True,
                    showline=True,
                ),
                radialaxis=radialaxis,
            )
            if bg_applied:
                polar_layout["bgcolor"] = "rgba(0,0,0,0)"
                polar_layout["angularaxis"]["gridcolor"] = "#A5A5A5"
                polar_layout["angularaxis"]["linecolor"] = "#A5A5A5"
                polar_layout["radialaxis"]["gridcolor"] = "#A5A5A5"
                polar_layout["radialaxis"]["linecolor"] = "#797979"
            fig.update_layout(
                title=f"{metric_col} ({mode_str}) difference to Baseline ({b_label})",
                polar=polar_layout,
                showlegend=True,
            )

        if plotted == 0:
            messagebox.showinfo(
                "Nothing to plot", "No datasets produced valid radar values.")
            return

        self._open_plotly_figure(fig, f"Plotted {plotted} trace(s).")
        if errors:
            messagebox.showwarning(
                "Partial plot", f"Plotted {plotted} trace(s) with errors.\n\n" + "\n".join(errors))

    def plot(self):
        if not self.loaded:
            messagebox.showinfo(
                "No data", "Load at least one dataset first (file or paste).")
            return

        angle_col = self.angle_var.get().strip()
        metric_col = self.metric_var.get().strip()
        if not metric_col:
            messagebox.showinfo("Missing selection", "Select a metric column.")
            return

        sentinels = parse_sentinels(self.sentinels_var.get())
        close_loop = bool(self.close_loop_var.get())
        value_mode = self.value_mode_var.get()
        agg_mode = (self.agg_var.get() or "mean").strip().lower()

        compare = bool(self.compare_var.get())
        baseline_display = self.baseline_display_var.get().strip()
        baseline_id = self.display_to_id.get(baseline_display, "")

        if compare and (not baseline_id or baseline_id not in self.loaded):
            messagebox.showinfo("Baseline required",
                                "Select a valid baseline dataset.")
            return

        plot_type = (self.plot_type_var.get() or "radar").strip().lower()
        if plot_type == "bar" and value_mode == "percent_mean":
            value_mode = "absolute"

        fixed_range = self._get_fixed_range()
        if fixed_range == "invalid":
            return

        if self.use_plotly_var.get():
            if plot_type == "bar":
                self._plot_plotly_bar(
                    angle_col, metric_col, sentinels, value_mode,
                    compare, baseline_id, baseline_display, fixed_range)
                self._push_history()
                return
            if not angle_col:
                messagebox.showinfo(
                    "Missing selection", "Select an angle column (required for Radar/Cartesian plots).")
                return
            if plot_type == "cartesian":
                self._plot_plotly_cartesian(
                    angle_col, metric_col, sentinels, value_mode, agg_mode, close_loop,
                    compare, baseline_id, baseline_display, fixed_range)
                self._push_history()
                return
                self._plot_plotly_radar(
                    angle_col, metric_col, sentinels, value_mode, agg_mode, close_loop,
                    compare, baseline_id, baseline_display, fixed_range)
            self._push_history()
            return

        # ---- BAR PLOT ----
        if plot_type == "bar":
            self.fig.clf()
            self.ax = self.fig.add_subplot(111)
            color_map = self._dataset_color_map()
            baseline_color = color_map.get(baseline_id, "red")

            ordered = []
            for sid in self.get_plot_order_source_ids():
                if compare and sid == baseline_id:
                    ordered.append(sid)
                elif self.show_flag.get(sid, True):
                    ordered.append(sid)
            if compare and baseline_id and baseline_id not in ordered:
                ordered.append(baseline_id)

            if compare:
                b_ang_deg, b_val = prepare_angle_value(
                    self.loaded[baseline_id], angle_col or "leftPedalCrankAngle", metric_col, sentinels)
                b_val2, _ = self._apply_value_mode(b_val, value_mode)
                baseline_mean = float(np.nanmean(b_val2))

            labels, heights, errors, bar_colors = [], [], [], []
            for sid in ordered:
                label = self.id_to_display.get(sid, os.path.basename(sid))
                try:
                    ang_deg, val = prepare_angle_value(
                        self.loaded[sid], angle_col or "leftPedalCrankAngle", metric_col, sentinels)
                    val2, _ = self._apply_value_mode(val, value_mode)
                    mval = float(np.nanmean(val2))
                    heights.append(0.0 if compare and sid == baseline_id else (
                        mval - baseline_mean if compare else mval))
                    labels.append(label)
                    bar_colors.append(color_map.get(sid, "#1f77b4"))
                except Exception as e:
                    errors.append(f"{label}: {e}")

            if not labels:
                messagebox.showinfo("Nothing to plot",
                                    "No datasets produced valid bar values.")
                self._redraw_empty()
                return

            x = np.arange(len(labels))
            # Reset margins to use full width (no right-side legend for bar plots).
            self.fig.subplots_adjust(left=0.08, right=0.98)
            baseline_label = b_label if compare else None
            baseline_handle = self.ax.axhline(
                0.0, color=baseline_color if compare else "black",
                linewidth=1.8 if compare else 1.2, label=baseline_label)
            self.ax.bar(x, heights, color=bar_colors)
            self.ax.set_xticks(x)
            self.ax.set_xticklabels(labels, rotation=45, ha="right")

            mode_str = "absolute" if value_mode == "absolute" else "% of mean"
            if compare:
                b_label = self.id_to_display.get(baseline_id, baseline_display)
                self.ax.set_title(
                    f"Mean {metric_col} difference vs baseline {b_label} ({mode_str})")
                self.ax.set_ylabel("Difference vs baseline")
            else:
                self.ax.set_title(
                    f"Mean {metric_col} per dataset ({mode_str})")
                self.ax.set_ylabel(metric_col)

            if fixed_range:
                self.ax.set_ylim(fixed_range[0], fixed_range[1])

            self.ax.grid(True, axis="y", linestyle=":")
            low, high = self.ax.get_ylim()
            self._update_range_entries(low, high)
            self.canvas.draw_idle()

            msg = f"Plotted {len(labels)} bar(s)."
            if errors:
                msg += " Some datasets failed (details shown)."
                messagebox.showwarning(
                    "Partial plot", msg + "\n\n" + "\n".join(errors))
            self.status.set(msg)
            self._push_history()
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

            plotted, errors = 0, []
            range_values = []
            color_map = self._dataset_color_map()
            baseline_color = color_map.get(baseline_id, "red")
            baseline_label = None

            if not compare:
                for sid in self.get_plot_order_source_ids():
                    if not self.show_flag.get(sid, True):
                        continue
                    label = self.id_to_display.get(sid, os.path.basename(sid))
                    try:
                        ang_deg, val = prepare_angle_value_agg(
                            self.loaded[sid], angle_col, metric_col, sentinels, agg_mode)
                        val2, _ = self._apply_value_mode(val, value_mode)
                        m = np.isfinite(ang_deg) & np.isfinite(val2)
                        ang_deg2 = ang_deg[m]
                        val2 = val2[m]
                        if len(ang_deg2) == 0:
                            raise ValueError(
                                "No valid values after filtering.")
                        if close_loop and len(ang_deg2) > 2:
                            ang_deg2 = np.concatenate([ang_deg2, [360.0]])
                            val2 = np.concatenate([val2, [val2[0]]])
                        color = color_map.get(sid)
                        self.ax.plot(ang_deg2, val2, marker="o",
                                     markersize=3, linewidth=1.5, label=label, color=color)
                        range_values.append(val2)
                        plotted += 1
                    except Exception as e:
                        errors.append(f"{label}: {e}")

                mode_str = "absolute" if value_mode == "absolute" else "% of mean"
                self.ax.set_title(f"{metric_col} ({mode_str})")
                self.ax.set_ylabel(metric_col)
            else:
                b_label = self.id_to_display.get(
                    baseline_id, os.path.basename(baseline_id))
                baseline_label = b_label
                try:
                    b_ang_deg, b_val = prepare_angle_value_agg(
                        self.loaded[baseline_id], angle_col, metric_col, sentinels, agg_mode)
                    b_val2, _ = self._apply_value_mode(b_val, value_mode)
                except Exception as e:
                    messagebox.showerror(
                        "Baseline error", f"Baseline '{b_label}' failed:\n{e}")
                    return

                for sid in self.get_plot_order_source_ids():
                    if not self.show_flag.get(sid, True):
                        continue
                    if sid == baseline_id:
                        continue
                    label = self.id_to_display.get(
                        sid, os.path.basename(sid))
                    try:
                        ang_deg, val = prepare_angle_value_agg(
                            self.loaded[sid], angle_col, metric_col, sentinels, agg_mode)
                        val2, _ = self._apply_value_mode(val, value_mode)
                        base_at = circular_interp_baseline(
                            b_ang_deg, b_val2, ang_deg)
                        delta = val2 - base_at
                        m = np.isfinite(delta) & np.isfinite(ang_deg)
                        ang_deg2 = ang_deg[m]
                        delta2 = delta[m]
                        if len(ang_deg2) == 0:
                            raise ValueError(
                                "No valid comparison values after filtering.")
                        order = np.argsort(ang_deg2)
                        ang_deg2 = ang_deg2[order]
                        delta2 = delta2[order]
                        if close_loop and len(ang_deg2) > 2:
                            ang_deg2 = np.concatenate([ang_deg2, [360.0]])
                            delta2 = np.concatenate([delta2, [delta2[0]]])
                        color = color_map.get(sid)
                        self.ax.plot(ang_deg2, delta2, marker="o",
                                     markersize=3, linewidth=1.5, label=label, color=color)
                        range_values.append(delta2)
                        plotted += 1
                    except Exception as e:
                        errors.append(f"{label}: {e}")

                mode_str = "absolute" if value_mode == "absolute" else "% of mean"
                self.ax.set_title(
                    f"{metric_col} ({mode_str}) difference to Baseline ({b_label})")
                self.ax.set_ylabel("Difference vs baseline")

            if plotted == 0:
                messagebox.showinfo(
                    "Nothing to plot", "No datasets produced valid cartesian values.")
                self._redraw_empty()
                return

            baseline_handle = self.ax.axhline(
                0.0, color=baseline_color if compare else "black",
                linewidth=1.8 if compare else 1.2, label=baseline_label)
            self.ax.set_xlabel("Crank angle (deg)")
            self.ax.set_xlim(0, 360)
            if plotted:
                # Reserve extra space on the right so the legend is fully visible,
                # and nudge the plot left.
                self.fig.subplots_adjust(left=0.1, right=0.84)
                handles, labels = self.ax.get_legend_handles_labels()
                if compare and baseline_label and baseline_handle and baseline_handle not in handles:
                    handles.append(baseline_handle)
                    labels.append(baseline_label)
                if compare and baseline_label and baseline_handle in handles:
                    idx = handles.index(baseline_handle)
                    handles.insert(0, handles.pop(idx))
                    labels.insert(0, labels.pop(idx))
                self.ax.legend(
                    handles, labels,
                    loc="upper left", bbox_to_anchor=(1.01, 1.02),
                    fontsize=9, frameon=False)
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
            self.canvas.draw_idle()

            msg = f"Plotted {plotted} trace(s)."
            if errors:
                msg += " Some datasets failed (details shown)."
                messagebox.showwarning(
                    "Partial plot", msg + "\n\n" + "\n".join(errors))
            self.status.set(msg)
            self._push_history()
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

        plotted, errors = 0, []
        color_map = self._dataset_color_map()
        baseline_color = color_map.get(baseline_id, "red")

        if not compare:
            for sid in self.get_plot_order_source_ids():
                if not self.show_flag.get(sid, True):
                    continue
                label = self.id_to_display.get(sid, os.path.basename(sid))
                try:
                    ang_deg, val = prepare_angle_value_agg(
                        self.loaded[sid], angle_col, metric_col, sentinels, agg_mode)
                    val2, _ = self._apply_value_mode(val, value_mode)

                    theta = np.deg2rad(ang_deg)
                    if close_loop and len(theta) > 2:
                        theta = np.concatenate([theta, [theta[0]]])
                        val2 = np.concatenate([val2, [val2[0]]])

                    color = color_map.get(sid)
                    self.ax.plot(theta, val2, marker="o",
                                 markersize=3, linewidth=1.5, label=label, color=color)
                    plotted += 1
                except Exception as e:
                    errors.append(f"{label}: {e}")

            mode_str = "absolute" if value_mode == "absolute" else "% of mean"
            self.ax.set_title(f"{metric_col} ({mode_str})", pad=18)
            self.ax.grid(True)
            self.ax.set_position([0.05, 0.05, 0.75, 0.80])
            if plotted:
                self.ax.legend(loc="upper right", bbox_to_anchor=(
                    1.25, 1.1), fontsize=9, frameon=False)
            if fixed_range:
                self.ax.set_rlim(fixed_range[0], fixed_range[1])
            else:
                self.ax.autoscale(enable=True, axis="y")
                self.ax.autoscale_view(scaley=True)
            low, high = self.ax.get_ylim()
            self._update_range_entries(low, high)
            fmt_abs_ticks(self.ax)

        else:
            b_label = self.id_to_display.get(
                baseline_id, os.path.basename(baseline_id))
            try:
                b_ang_deg, b_val = prepare_angle_value_agg(
                    self.loaded[baseline_id], angle_col, metric_col, sentinels, agg_mode)
                b_val2, _ = self._apply_value_mode(b_val, value_mode)
            except Exception as e:
                messagebox.showerror(
                    "Baseline error", f"Baseline '{b_label}' failed:\n{e}")
                return

            deltas_by_id = {}
            max_abs = 0.0
            for sid in self.get_plot_order_source_ids():
                if not self.show_flag.get(sid, True):
                    continue
                if sid == baseline_id:
                    continue
                label = self.id_to_display.get(sid, os.path.basename(sid))
                try:
                    ang_deg, val = prepare_angle_value_agg(
                        self.loaded[sid], angle_col, metric_col, sentinels, agg_mode)
                    val2, _ = self._apply_value_mode(val, value_mode)
                    base_at = circular_interp_baseline(
                        b_ang_deg, b_val2, ang_deg)
                    delta = val2 - base_at
                    m = np.isfinite(delta) & np.isfinite(ang_deg)
                    ang_deg2 = ang_deg[m]
                    delta2 = delta[m]
                    if len(ang_deg2) == 0:
                        raise ValueError(
                            "No valid comparison values after filtering.")
                    order = np.argsort(ang_deg2)
                    ang_deg2 = ang_deg2[order]
                    delta2 = delta2[order]
                    deltas_by_id[sid] = (ang_deg2, delta2)
                    this_max = float(np.nanmax(np.abs(delta2)))
                    if np.isfinite(this_max):
                        max_abs = max(max_abs, this_max)
                except Exception as e:
                    errors.append(f"{label}: {e}")

            if not deltas_by_id:
                messagebox.showinfo(
                    "Nothing to plot", "No non-baseline datasets produced valid comparison traces.")
                self._redraw_empty()
                return

            if max_abs <= 0 or not np.isfinite(max_abs):
                max_abs = 1.0
            offset = 1.10 * max_abs

            theta_ring = np.linspace(0, 2 * np.pi, 361)
            r_ring = np.full_like(theta_ring, offset, dtype=float)
            self.ax.plot(theta_ring, r_ring, linewidth=2.6,
                         color=baseline_color, label=b_label)

            for sid, (ang_deg2, delta2) in deltas_by_id.items():
                label = self.id_to_display.get(sid, os.path.basename(sid))
                theta = np.deg2rad(ang_deg2)
                r = delta2 + offset
                if close_loop and len(theta) > 2:
                    theta = np.concatenate([theta, [theta[0]]])
                    r = np.concatenate([r, [r[0]]])
                color = color_map.get(sid)
                self.ax.plot(theta, r, marker="o", markersize=3,
                             linewidth=1.5, label=label, color=color)
                plotted += 1

            mode_str = "absolute" if value_mode == "absolute" else "% of mean"
            self.ax.set_title(
                f"{metric_col} ({mode_str}) difference to Baseline ({b_label})", pad=18)
            self.ax.grid(True)
            self.ax.legend(loc="upper left", bbox_to_anchor=(
                1.02, 1.05), fontsize=9, frameon=False)
            self.ax.set_position([0.05, 0.03, 0.8, 0.85])
            if fixed_range:
                self.ax.set_rlim(offset + fixed_range[0],
                                 offset + fixed_range[1])
            else:
                self.ax.autoscale(enable=True, axis="y")
                self.ax.autoscale_view(scaley=True)
            low, high = self.ax.get_ylim()
            self._update_range_entries(low - offset, high - offset)
            fmt_delta_ticks(self.ax, offset)

        self.canvas.draw_idle()
        msg = f"Plotted {plotted} trace(s)."
        if errors:
            msg += " Some datasets failed (details shown)."
            messagebox.showwarning(
                "Partial plot", msg + "\n\n" + "\n".join(errors))
        self.status.set(msg)
        self._push_history()

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
