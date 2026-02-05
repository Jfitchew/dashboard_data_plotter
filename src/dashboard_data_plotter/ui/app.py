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
)
from dashboard_data_plotter.utils.sortkeys import dataset_sort_key
from dashboard_data_plotter.utils.log import log_exception, DEFAULT_LOG_PATH
import os
import json
from datetime import datetime
import tempfile
import tkinter as tk
from tkinter import ttk, filedialog, messagebox, simpledialog
import webbrowser

import numpy as np
import pandas as pd

from matplotlib.figure import Figure
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg, NavigationToolbar2Tk
import plotly.graph_objects as go
import plotly.io as pio

import matplotlib
matplotlib.use("TkAgg")


class DashboardDataPlotter(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("Dashboard Data Plotter (Tkinter)")
        self.geometry("1390x860")

        # Internal storage:
        #   source_id: unique ID (file path, or "PASTE::<name>")
        #   display_name: human name shown in listbox/legend/baseline chooser
        self.loaded = {}            # source_id -> DataFrame
        self.id_to_display = {}     # source_id -> display name
        self.display_to_id = {}     # display name -> source_id
        self.show_flag = {}         # source_id -> bool (whether to plot)

        self.angle_var = tk.StringVar(value="leftPedalCrankAngle")
        self.metric_var = tk.StringVar(value="")
        self.close_loop_var = tk.BooleanVar(value=True)
        self.sentinels_var = tk.StringVar(value=DEFAULT_SENTINELS)

        # Value mode used for BOTH normal plots and comparison plots
        # "absolute" or "percent_mean"
        self.value_mode_var = tk.StringVar(value="absolute")

        # Plot type
        self.plot_type_var = tk.StringVar(value="radar")  # "radar" or "bar"

        # Plot backend
        self.use_plotly_var = tk.BooleanVar(value=False)

        # Comparison mode
        self.compare_var = tk.BooleanVar(value=False)
        self.baseline_display_var = tk.StringVar(value="")

        self._build_ui()
        self._build_plot()

        self._set_plot_type_controls_state()
        self._set_compare_controls_state()

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
        ttk.Button(btns, text="Add JSON file(s)...", command=self.add_files).grid(
            row=0, column=0, sticky="ew")
        ttk.Button(btns, text="Remove", command=self.remove_selected).grid(
            row=0, column=1, padx=(6, 0))
        ttk.Button(btns, text="Rename…", command=self.rename_selected).grid(
            row=0, column=2, padx=(6, 0))
        ttk.Button(btns, text="Clear all", command=self.clear_all).grid(
            row=0, column=3, padx=(6, 0))
        ttk.Button(btns, text="Save All…", command=self.save_all_datasets).grid(
            row=0, column=4, padx=(6, 0))

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
        ttk.Button(paste_btns, text="Load pasted JSON",
                   command=self.load_from_paste).grid(row=0, column=0, sticky="ew")
        ttk.Button(paste_btns, text="Save pasted JSON…",
                   command=self.save_pasted_json).grid(row=0, column=1, padx=(6, 0))
        ttk.Button(paste_btns, text="Clear pasted", command=self.clear_paste).grid(
            row=0, column=2, padx=(6, 0))

        ttk.Separator(left).grid(row=6, column=0, sticky="ew", pady=10)

        ttk.Label(left, text="Plot settings", font=(
            "Segoe UI", 11, "bold")).grid(row=7, column=0, sticky="w")

        angle_frame = ttk.Frame(left)
        angle_frame.grid(row=8, column=0, sticky="ew", pady=(6, 2))

        # Plot type (radar vs bar)
        ttk.Label(angle_frame, text="Plot type:").grid(
            row=0, column=0, sticky="w")
        # pt = ttk.Frame(angle_frame)
        # pt.grid(row=0, column=1, sticky="w", padx=(8, 0))
        ttk.Radiobutton(angle_frame, text="Radar (polar)", variable=self.plot_type_var, value="radar",
                        command=self._on_plot_type_change).grid(row=0, column=1, sticky="w")
        ttk.Radiobutton(angle_frame, text="Bar (avg)", variable=self.plot_type_var, value="bar",
                        command=self._on_plot_type_change).grid(row=0, column=1, sticky="e")
        ttk.Checkbutton(angle_frame, text="Use Plotly (interactive)",
                        variable=self.use_plotly_var).grid(row=2, column=0, columnspan=2, sticky="w")
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

        metric_frame = ttk.Frame(left)
        metric_frame.grid(row=9, column=0, sticky="ew", pady=(6, 2))
        ttk.Label(metric_frame, text="Metric column:").grid(
            row=0, column=0, sticky="w")
        self.metric_combo = ttk.Combobox(
            metric_frame, textvariable=self.metric_var, values=[], state="readonly", width=30)
        self.metric_combo.grid(row=0, column=1, sticky="w", padx=(8, 0))

        self.close_loop_chk = ttk.Checkbutton(
            left, text="Close loop (connect 360°)", variable=self.close_loop_var)
        self.close_loop_chk.grid(row=10, column=0, sticky="w", pady=(6, 2))

        sentinel_frame = ttk.Frame(left)
        sentinel_frame.grid(row=11, column=0, sticky="ew", pady=(6, 2))
        ttk.Label(sentinel_frame, text="Invalid values:").grid(
            row=0, column=0, sticky="w")
        ttk.Entry(sentinel_frame, textvariable=self.sentinels_var,
                  width=32).grid(row=0, column=1, sticky="w", padx=(8, 0))

        ttk.Separator(left).grid(row=12, column=0, sticky="ew", pady=10)

        # Value mode
        ttk.Label(left, text="Value mode", font=("Segoe UI", 11, "bold")).grid(
            row=13, column=0, sticky="w")

        vm_frame = ttk.Frame(left)
        vm_frame.grid(row=14, column=0, sticky="ew", pady=(6, 2))
        ttk.Radiobutton(vm_frame, text="Absolute metric values", variable=self.value_mode_var,
                        value="absolute").grid(row=0, column=0, sticky="w")
        self.rb_percent_mean = ttk.Radiobutton(
            vm_frame, text="% of dataset mean", variable=self.value_mode_var, value="percent_mean")
        self.rb_percent_mean.grid(row=1, column=0, sticky="w")

        ttk.Separator(left).grid(row=15, column=0, sticky="ew", pady=10)

        # Comparison mode
        ttk.Label(left, text="Comparison mode", font=(
            "Segoe UI", 11, "bold")).grid(row=16, column=0, sticky="w")

        ttk.Checkbutton(left, text="Plot as difference vs baseline", variable=self.compare_var,
                        command=self._on_compare_toggle).grid(row=17, column=0, sticky="w", pady=(6, 2))

        base_frame = ttk.Frame(left)
        base_frame.grid(row=18, column=0, sticky="ew", pady=(6, 2))
        ttk.Label(base_frame, text="Baseline:").grid(
            row=0, column=0, sticky="w")
        self.baseline_combo = ttk.Combobox(base_frame, textvariable=self.baseline_display_var,
                                           values=[], state="readonly", width=30)
        self.baseline_combo.grid(row=0, column=1, sticky="w", padx=(8, 0))

        ttk.Button(left, text="Plot / Refresh", command=self.plot).grid(row=19,
                                                                        column=0, sticky="ew", pady=(10, 0))

        self.status = tk.StringVar(
            value="Load one or more JSON files, or paste a dataset object, to begin.")
        ttk.Label(left, textvariable=self.status, wraplength=380, foreground="#333").grid(
            row=20, column=0, sticky="w", pady=(10, 0))

        self._on_plot_type_change()
        self._set_compare_controls_state()

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
        is_bar = (self.plot_type_var.get() or "radar").strip().lower() == "bar"
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

    def _on_plot_type_change(self):
        is_bar = (self.plot_type_var.get() == "bar")
        if hasattr(self, "rb_percent_mean"):
            self.rb_percent_mean.configure(
                state=("disabled" if is_bar else "normal"))
        if is_bar and self.value_mode_var.get() == "percent_mean":
            self.value_mode_var.set("absolute")
        self._set_plot_type_controls_state()

    def _on_compare_toggle(self):
        self._set_compare_controls_state()

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
        pio.write_html(fig, file=out_path, auto_open=False, include_plotlyjs="cdn")
        webbrowser.open(f"file://{out_path}")
        self.status.set(f"{title} (interactive Plotly plot opened in browser).")

    def _plot_plotly_bar(self, angle_col, metric_col, sentinels, value_mode,
                         compare, baseline_id, baseline_display):
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

        labels, heights, errors = [], [], []
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
            except Exception as e:
                errors.append(f"{label}: {e}")

        if not labels:
            messagebox.showinfo("Nothing to plot",
                                "No datasets produced valid bar values.")
            return

        mode_str = "absolute" if value_mode == "absolute" else "% of mean"
        if compare:
            b_label = self.id_to_display.get(baseline_id, baseline_display)
            title = f"Mean {metric_col} difference vs baseline {b_label} ({mode_str})"
            y_title = "Difference vs baseline"
        else:
            title = f"Mean {metric_col} per dataset ({mode_str})"
            y_title = metric_col

        fig = go.Figure()
        fig.add_bar(x=labels, y=heights, marker_color="#1f77b4")
        fig.update_layout(
            title=title,
            xaxis_title="Dataset",
            yaxis_title=y_title,
            xaxis_tickangle=-45,
        )
        fig.add_shape(type="line", x0=-0.5, x1=max(len(labels) - 0.5, 0.5),
                      y0=0, y1=0, line=dict(color="red" if compare else "black", width=1.2))

        self._open_plotly_figure(fig, f"Plotted {len(labels)} bar(s).")
        if errors:
            messagebox.showwarning(
                "Partial plot", f"Plotted {len(labels)} bar(s) with errors.\n\n" + "\n".join(errors))

    def _plot_plotly_radar(self, angle_col, metric_col, sentinels, value_mode, close_loop,
                           compare, baseline_id, baseline_display):
        plotted, errors = 0, []
        fig = go.Figure()

        if not compare:
            for sid in self.get_plot_order_source_ids():
                if not self.show_flag.get(sid, True):
                    continue
                label = self.id_to_display.get(sid, os.path.basename(sid))
                try:
                    ang_deg, val = prepare_angle_value(
                        self.loaded[sid], angle_col, metric_col, sentinels)
                    val2, _ = self._apply_value_mode(val, value_mode)
                    theta = np.asarray(ang_deg, dtype=float)
                    r = np.asarray(val2, dtype=float)
                    if close_loop and len(theta) > 2:
                        theta = np.concatenate([theta, [theta[0]]])
                        r = np.concatenate([r, [r[0]]])
                    fig.add_scatterpolar(
                        theta=theta, r=r, mode="lines+markers", name=label, marker=dict(size=4))
                    plotted += 1
                except Exception as e:
                    errors.append(f"{label}: {e}")

            mode_str = "absolute" if value_mode == "absolute" else "% of mean"
            fig.update_layout(
                title=f"{metric_col} ({mode_str})",
                polar=dict(
                    angularaxis=dict(direction="clockwise", rotation=90),
                ),
                showlegend=True,
            )
        else:
            b_label = self.id_to_display.get(
                baseline_id, os.path.basename(baseline_id))
            try:
                b_ang_deg, b_val = prepare_angle_value(
                    self.loaded[baseline_id], angle_col, metric_col, sentinels)
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
                    ang_deg, val = prepare_angle_value(
                        self.loaded[sid], angle_col, metric_col, sentinels)
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
                return

            if max_abs <= 0 or not np.isfinite(max_abs):
                max_abs = 1.0
            offset = 1.10 * max_abs

            theta_ring = np.linspace(0, 360, 361)
            r_ring = np.full_like(theta_ring, offset, dtype=float)
            fig.add_scatterpolar(
                theta=theta_ring, r=r_ring, mode="lines", line=dict(width=2.2, color="red"),
                name=f"Baseline = 0 ({b_label})")

            for sid, (ang_deg2, delta2) in deltas_by_id.items():
                label = self.id_to_display.get(sid, os.path.basename(sid))
                theta = np.asarray(ang_deg2, dtype=float)
                r = np.asarray(delta2 + offset, dtype=float)
                if close_loop and len(theta) > 2:
                    theta = np.concatenate([theta, [theta[0]]])
                    r = np.concatenate([r, [r[0]]])
                fig.add_scatterpolar(
                    theta=theta, r=r, mode="lines+markers", name=label, marker=dict(size=4))
                plotted += 1

            tick_vals = np.linspace(-max_abs, max_abs, 5)
            decimals = choose_decimals_from_ticks(tick_vals)
            tick_text = [f"{v:.{decimals}f}" for v in tick_vals]
            tick_positions = tick_vals + offset

            mode_str = "absolute" if value_mode == "absolute" else "% of mean"
            fig.update_layout(
                title=f"{metric_col} ({mode_str}) difference to Baseline ({b_label})",
                polar=dict(
                    angularaxis=dict(direction="clockwise", rotation=90),
                    radialaxis=dict(tickvals=tick_positions, ticktext=tick_text),
                ),
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

        if self.use_plotly_var.get():
            if plot_type == "bar":
                self._plot_plotly_bar(
                    angle_col, metric_col, sentinels, value_mode,
                    compare, baseline_id, baseline_display)
                return
            if not angle_col:
                messagebox.showinfo(
                    "Missing selection", "Select an angle column (required for Radar plot).")
                return
            self._plot_plotly_radar(
                angle_col, metric_col, sentinels, value_mode, close_loop,
                compare, baseline_id, baseline_display)
            return

        # ---- BAR PLOT ----
        if plot_type == "bar":
            self.fig.clf()
            self.ax = self.fig.add_subplot(111)

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

            labels, heights, errors = [], [], []
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
                except Exception as e:
                    errors.append(f"{label}: {e}")

            if not labels:
                messagebox.showinfo("Nothing to plot",
                                    "No datasets produced valid bar values.")
                self._redraw_empty()
                return

            x = np.arange(len(labels))
            self.ax.axhline(
                0.0, color="red" if compare else "black", linewidth=1.2)
            self.ax.bar(x, heights)
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

            self.ax.grid(True, axis="y", linestyle=":")
            self.canvas.draw_idle()

            msg = f"Plotted {len(labels)} bar(s)."
            if errors:
                msg += " Some datasets failed (details shown)."
                messagebox.showwarning(
                    "Partial plot", msg + "\n\n" + "\n".join(errors))
            self.status.set(msg)
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

        plotted, errors = 0, []

        if not compare:
            for sid in self.get_plot_order_source_ids():
                if not self.show_flag.get(sid, True):
                    continue
                label = self.id_to_display.get(sid, os.path.basename(sid))
                try:
                    ang_deg, val = prepare_angle_value(
                        self.loaded[sid], angle_col, metric_col, sentinels)
                    val2, _ = self._apply_value_mode(val, value_mode)

                    theta = np.deg2rad(ang_deg)
                    if close_loop and len(theta) > 2:
                        theta = np.concatenate([theta, [theta[0]]])
                        val2 = np.concatenate([val2, [val2[0]]])

                    self.ax.plot(theta, val2, marker="o",
                                 markersize=3, linewidth=1.5, label=label)
                    plotted += 1
                except Exception as e:
                    errors.append(f"{label}: {e}")

            mode_str = "absolute" if value_mode == "absolute" else "% of mean"
            self.ax.set_title(f"{metric_col} ({mode_str})", pad=18)
            self.ax.grid(True)
            self.ax.set_position([0.02, 0.08, 0.8, 0.8])
            if plotted:
                self.ax.legend(loc="upper left", bbox_to_anchor=(
                    1.02, 1.05), fontsize=9, frameon=False)
            fmt_abs_ticks(self.ax)

        else:
            b_label = self.id_to_display.get(
                baseline_id, os.path.basename(baseline_id))
            try:
                b_ang_deg, b_val = prepare_angle_value(
                    self.loaded[baseline_id], angle_col, metric_col, sentinels)
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
                    ang_deg, val = prepare_angle_value(
                        self.loaded[sid], angle_col, metric_col, sentinels)
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
            self.ax.plot(theta_ring, r_ring, linewidth=2.2,
                         color="red", label=f"Baseline = 0 ({b_label})")

            for sid, (ang_deg2, delta2) in deltas_by_id.items():
                label = self.id_to_display.get(sid, os.path.basename(sid))
                theta = np.deg2rad(ang_deg2)
                r = delta2 + offset
                if close_loop and len(theta) > 2:
                    theta = np.concatenate([theta, [theta[0]]])
                    r = np.concatenate([r, [r[0]]])
                self.ax.plot(theta, r, marker="o", markersize=3,
                             linewidth=1.5, label=label)
                plotted += 1

            mode_str = "absolute" if value_mode == "absolute" else "% of mean"
            self.ax.set_title(
                f"{metric_col} ({mode_str}) difference to Baseline ({b_label})", pad=18)
            self.ax.grid(True)
            self.ax.legend(loc="upper left", bbox_to_anchor=(
                1.02, 1.05), fontsize=9, frameon=False)
            self.ax.set_position([0.02, 0.08, 0.8, 0.8])
            fmt_delta_ticks(self.ax, offset)

        self.canvas.draw_idle()
        msg = f"Plotted {plotted} trace(s)."
        if errors:
            msg += " Some datasets failed (details shown)."
            messagebox.showwarning(
                "Partial plot", msg + "\n\n" + "\n".join(errors))
        self.status.set(msg)


def main():
    app = DashboardDataPlotter()
    app.mainloop()
