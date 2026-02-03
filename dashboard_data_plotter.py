import json
import os
from datetime import datetime
import tkinter as tk
from tkinter import ttk, filedialog, messagebox, simpledialog

import numpy as np
import pandas as pd

import matplotlib
matplotlib.use("TkAgg")
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg, NavigationToolbar2Tk
from matplotlib.figure import Figure
from matplotlib.ticker import FuncFormatter

import traceback
from pathlib import Path


DEFAULT_SENTINELS = "9999"  # invalid values used in dataset




LOG_PATH = Path.home() / "PedalRadar_error.log"

def log_exception(context: str):
    try:
        with open(LOG_PATH, "a", encoding="utf-8") as f:
            f.write("\n\n" + "="*80 + "\n")
            f.write(f"{datetime.now().isoformat()}  |  {context}\n")
            traceback.print_exc(file=f)
    except Exception:
        # If logging fails, don't crash the app
        pass

def load_json_file_obj(path: str):
    """Load JSON from disk and return the parsed Python object."""
    with open(path, "r", encoding="utf-8") as f:
        text = f.read().strip()
    return json.loads(text)


def load_json_file_datasets(path: str):
    """
    Load a JSON file that may contain either:
      A) list-of-records: [ {..}, {..}, ... ]
      B) multi-dataset object: { "Name": {"rideData": [..]}, ... }
      C) dict name->records list: { "Name": [..], ... }
      D) single wrapper: {"rideData": [..]}

    Returns: list of (dataset_name, dataframe)
    """
    obj = load_json_file_obj(path)

    # local extractor to avoid ordering constraints
    def _extract_named(obj_):
        if isinstance(obj_, dict):
            if "rideData" in obj_ and isinstance(obj_["rideData"], list):
                return [("Dataset", obj_["rideData"])]

            out_ = []
            for name_, v_ in obj_.items():
                if isinstance(v_, dict) and "rideData" in v_ and isinstance(v_["rideData"], list):
                    out_.append((str(name_), v_["rideData"]))
                elif isinstance(v_, list):
                    out_.append((str(name_), v_))
            if out_:
                return out_
        if isinstance(obj_, list):
            return [("Dataset", obj_)]
        raise ValueError("Unrecognized JSON structure.")

    datasets = _extract_named(obj)

    out = []
    for name, records in datasets:
        if not isinstance(records, list) or (len(records) > 0 and not isinstance(records[0], dict)):
            continue
        df = pd.DataFrame(records)
        for c in df.columns:
            df[c] = pd.to_numeric(df[c], errors="coerce")
        out.append((str(name), df))

    if not out:
        raise ValueError("No valid datasets found in JSON file.")
    return out




def parse_sentinels(s: str):
    vals = []
    for part in s.split(","):
        part = part.strip()
        if not part:
            continue
        try:
            vals.append(float(part))
        except ValueError:
            pass
    return vals


def choose_decimals_from_ticks(ticks, max_decimals=4):
    ticks = np.asarray(ticks, dtype=float)
    ticks = np.unique(ticks[np.isfinite(ticks)])
    if ticks.size < 2:
        return 0

    diffs = np.diff(np.sort(ticks))
    diffs = diffs[diffs > 1e-12]
    if diffs.size == 0:
        return 0

    step = float(np.min(diffs))

    # decimals needed so that one tick step isn't rounded away
    decimals = int(np.ceil(-np.log10(step)))
    decimals = max(0, min(decimals, max_decimals))
    return decimals


def sanitize_numeric(series: pd.Series, sentinels):
    x = pd.to_numeric(series, errors="coerce")
    for v in sentinels:
        x = x.mask(x == v)
    return x


def wrap_angle_deg(a: pd.Series, convert_br_to_standard: bool) -> pd.Series:
    """
    Convert BR crank-angle convention to Standard if requested.

    Current mapping in your code (per latest agreed table):
      BR  90 = Standard   0
      BR   0 = Standard  90
      BR 270 = Standard 180
      BR 180 = Standard 270

    Formula:
      theta_std = (90 - theta_br) mod 360
    """
    a = pd.to_numeric(a, errors="coerce")
    if convert_br_to_standard:
        a = 90.0 - a
    return np.mod(a, 360.0)


def prepare_angle_value(df: pd.DataFrame, angle_col: str, metric_col: str, sentinels):
    """
    Returns:
        ang_deg (np.ndarray): sorted unique angles [0..360)
        val (np.ndarray): mean metric at each angle (averages duplicates)
    """
    if angle_col not in df.columns:
        raise KeyError(f"Angle column '{angle_col}' not found.")
    if metric_col not in df.columns:
        raise KeyError(f"Metric column '{metric_col}' not found.")

    convert_br = angle_col in ("leftPedalCrankAngle", "rightPedalCrankAngle")
    ang = wrap_angle_deg(
        sanitize_numeric(df[angle_col], sentinels),
        convert_br_to_standard=convert_br
    )
    val = sanitize_numeric(df[metric_col], sentinels)

    plot_df = pd.DataFrame({"angle_deg": ang, "value": val}).dropna()
    
    # --- enforce 52-bin quantization to avoid float noise / extra points ---
    BIN_COUNT = 52
    BIN_W = 360.0 / BIN_COUNT
    plot_df["angle_bin"] = (np.round(plot_df["angle_deg"] / BIN_W) * BIN_W) % 360.0
    
    # group by the bin, not the raw angle
    plot_df = (
        plot_df.groupby("angle_bin", as_index=False)["value"]
        .mean()
        .rename(columns={"angle_bin": "angle_deg"})
        .sort_values("angle_deg")
    )
    
    if plot_df.empty:
        raise ValueError("No valid rows after removing NaNs/sentinels.")
        
    return plot_df["angle_deg"].to_numpy(), plot_df["value"].to_numpy()
    


def to_percent_of_mean(values: np.ndarray):
    """
    Convert values to % of that dataset's mean:
        100 * value / mean(value)
    """
    v = np.asarray(values, dtype=float)
    mu = np.nanmean(v)
    if not np.isfinite(mu) or abs(mu) < 1e-12:
        raise ValueError("Mean is zero/invalid; cannot compute % of mean.")
    return 100.0 * v / mu


def circular_interp_baseline(b_ang_deg: np.ndarray, b_val: np.ndarray, q_ang_deg: np.ndarray):
    """
    Interpolate baseline values at query angles with circular wrap.
    Extends baseline angles by -360 and +360 copies to avoid edge discontinuity.
    """
    if len(b_ang_deg) < 2:
        return np.full_like(q_ang_deg, b_val[0], dtype=float)

    order = np.argsort(b_ang_deg)
    b_ang = b_ang_deg[order].astype(float)
    b_v = b_val[order].astype(float)

    b_ang_ext = np.concatenate([b_ang - 360.0, b_ang, b_ang + 360.0])
    b_v_ext = np.concatenate([b_v, b_v, b_v])

    q = (q_ang_deg % 360.0).astype(float)
    return np.interp(q, b_ang_ext, b_v_ext)


def extract_named_datasets(obj):
    """
    Accepts:
      A) { "Name": { "rideData": [ ... ] }, ... }      (your pasted format)
      B) { "Name": [ ...records... ], ... }           (fallback)
      C) { "rideData": [ ... ] }                      (single dataset wrapper)
      D) [ ...records... ]                            (single unnamed dataset)

    Returns: list of (name, records_list)
    """
    if isinstance(obj, dict):
        if "rideData" in obj and isinstance(obj["rideData"], list):
            return [("Dataset", obj["rideData"])]

        out = []
        for name, v in obj.items():
            if isinstance(v, dict) and "rideData" in v and isinstance(v["rideData"], list):
                out.append((str(name), v["rideData"]))
            elif isinstance(v, list):
                out.append((str(name), v))
        if out:
            return out

    if isinstance(obj, list):
        return [("Dataset", obj)]

    raise ValueError("Unrecognized pasted JSON structure.")


def make_unique_name(name, existing_names):
    base = name.strip() if str(name).strip() else "Dataset"
    if base not in existing_names:
        return base
    i = 2
    while f"{base} ({i})" in existing_names:
        i += 1
    return f"{base} ({i})"


class PolarCompareApp(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("Pedalling Metric Polar Compare (Tkinter)")
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

        # Comparison mode
        self.compare_var = tk.BooleanVar(value=False)
        self.baseline_display_var = tk.StringVar(value="")

        self._build_ui()
        self._build_plot()

    def _build_ui(self):
        self.columnconfigure(0, weight=0)
        self.columnconfigure(1, weight=1)
        self.rowconfigure(0, weight=1)

        left = ttk.Frame(self, padding=10)
        left.grid(row=0, column=0, sticky="ns")

        ttk.Label(left, text="Data sources", font=("Segoe UI", 11, "bold")).grid(row=0, column=0, sticky="w")

        btns = ttk.Frame(left)
        btns.grid(row=1, column=0, sticky="ew", pady=(6, 6))
        ttk.Button(btns, text="Add JSON file(s)...", command=self.add_files).grid(row=0, column=0, sticky="ew")
        ttk.Button(btns, text="Remove", command=self.remove_selected).grid(row=0, column=1, padx=(6, 0))
        ttk.Button(btns, text="Rename…", command=self.rename_selected).grid(row=0, column=2, padx=(6, 0))
        ttk.Button(btns, text="Clear all", command=self.clear_all).grid(row=0, column=3, padx=(6, 0))

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
        self.files_tree.heading("show", text="Show", command=self.toggle_all_show)
        self.files_tree.heading("name", text="Dataset", command=lambda: self.sort_by_dataset_name())
        self.files_tree.column("show", width=50, anchor="center", stretch=False)
        self.files_tree.column("name", width=340, anchor="w")

        self.files_tree.grid(row=0, column=0, sticky="ew")

        tv_scroll = ttk.Scrollbar(tv_frame, orient="vertical", command=self.files_tree.yview)
        tv_scroll.grid(row=0, column=1, sticky="ns")
        self.files_tree.configure(yscrollcommand=tv_scroll.set)

        # Toggle show when clicking the Show column; rename on double-click of name
        self.files_tree.bind("<Button-1>", self._on_tree_click, add=True)
        self.files_tree.bind("<Double-1>", self._on_tree_double_click, add=True)


        # --- Paste JSON sources
        ttk.Label(left, text="Paste JSON data sources", font=("Segoe UI", 10, "bold")).grid(row=3, column=0, sticky="w", pady=(10, 0))

        paste_frame = ttk.Frame(left)
        paste_frame.grid(row=4, column=0, sticky="ew", pady=(6, 6))

        self.paste_text = tk.Text(paste_frame, height=6, width=52, wrap="none")
        self.paste_text.grid(row=0, column=0, sticky="ew")

        paste_scroll = ttk.Scrollbar(paste_frame, orient="vertical", command=self.paste_text.yview)
        paste_scroll.grid(row=0, column=1, sticky="ns")
        self.paste_text.configure(yscrollcommand=paste_scroll.set)

        # Right-click context menu for the paste box
        self._paste_menu = tk.Menu(self, tearoff=0)
        self._paste_menu.add_command(label="Cut", command=lambda: self.paste_text.event_generate("<<Cut>>"))
        self._paste_menu.add_command(label="Copy", command=lambda: self.paste_text.event_generate("<<Copy>>"))
        self._paste_menu.add_command(label="Paste", command=lambda: self.paste_text.event_generate("<<Paste>>"))
        self._paste_menu.add_separator()
        self._paste_menu.add_command(label="Select All", command=lambda: self._select_all_in_paste())
        self._paste_menu.add_command(label="Clear", command=self.clear_paste)

        self.paste_text.bind("<Button-3>", self._show_paste_menu, add=True)

        paste_btns = ttk.Frame(left)
        paste_btns.grid(row=5, column=0, sticky="ew", pady=(2, 6))
        ttk.Button(paste_btns, text="Load pasted JSON", command=self.load_from_paste).grid(row=0, column=0, sticky="ew")
        ttk.Button(paste_btns, text="Save pasted JSON…", command=self.save_pasted_json).grid(row=0, column=1, padx=(6, 0))
        ttk.Button(paste_btns, text="Clear pasted", command=self.clear_paste).grid(row=0, column=2, padx=(6, 0))


        ttk.Separator(left).grid(row=6, column=0, sticky="ew", pady=10)

        ttk.Label(left, text="Plot settings", font=("Segoe UI", 11, "bold")).grid(row=7, column=0, sticky="w")

        angle_frame = ttk.Frame(left)
        angle_frame.grid(row=8, column=0, sticky="ew", pady=(6, 2))
        ttk.Label(angle_frame, text="Angle column:").grid(row=0, column=0, sticky="w")
        ttk.Combobox(
            angle_frame,
            textvariable=self.angle_var,
            values=["leftPedalCrankAngle", "rightPedalCrankAngle"],
            state="readonly",
            width=30,
        ).grid(row=0, column=1, sticky="w", padx=(8, 0))

        metric_frame = ttk.Frame(left)
        metric_frame.grid(row=9, column=0, sticky="ew", pady=(6, 2))
        ttk.Label(metric_frame, text="Metric column:").grid(row=0, column=0, sticky="w")
        self.metric_combo = ttk.Combobox(metric_frame, textvariable=self.metric_var, values=[], state="readonly", width=30)
        self.metric_combo.grid(row=0, column=1, sticky="w", padx=(8, 0))

        ttk.Checkbutton(left, text="Close loop (connect 360°)", variable=self.close_loop_var).grid(
            row=10, column=0, sticky="w", pady=(6, 2)
        )

        sentinel_frame = ttk.Frame(left)
        sentinel_frame.grid(row=11, column=0, sticky="ew", pady=(6, 2))
        ttk.Label(sentinel_frame, text="Invalid values:").grid(row=0, column=0, sticky="w")
        ttk.Entry(sentinel_frame, textvariable=self.sentinels_var, width=32).grid(
            row=0, column=1, sticky="w", padx=(8, 0)
        )

        ttk.Separator(left).grid(row=12, column=0, sticky="ew", pady=10)

        # Value mode
        ttk.Label(left, text="Value mode", font=("Segoe UI", 11, "bold")).grid(row=13, column=0, sticky="w")

        vm_frame = ttk.Frame(left)
        vm_frame.grid(row=14, column=0, sticky="ew", pady=(6, 2))
        ttk.Radiobutton(vm_frame, text="Absolute metric values", variable=self.value_mode_var, value="absolute").grid(
            row=0, column=0, sticky="w"
        )
        ttk.Radiobutton(vm_frame, text="% of dataset mean", variable=self.value_mode_var, value="percent_mean").grid(
            row=1, column=0, sticky="w"
        )

        ttk.Separator(left).grid(row=15, column=0, sticky="ew", pady=10)

        # Comparison mode
        ttk.Label(left, text="Comparison mode", font=("Segoe UI", 11, "bold")).grid(row=16, column=0, sticky="w")

        ttk.Checkbutton(
            left,
            text="Plot as difference vs baseline",
            variable=self.compare_var,
            command=self._on_compare_toggle,
        ).grid(row=17, column=0, sticky="w", pady=(6, 2))

        base_frame = ttk.Frame(left)
        base_frame.grid(row=18, column=0, sticky="ew", pady=(6, 2))
        ttk.Label(base_frame, text="Baseline:").grid(row=0, column=0, sticky="w")
        self.baseline_combo = ttk.Combobox(
            base_frame,
            textvariable=self.baseline_display_var,
            values=[],
            state="readonly",
            width=30,
        )
        self.baseline_combo.grid(row=0, column=1, sticky="w", padx=(8, 0))

        ttk.Button(left, text="Plot / Refresh", command=self.plot).grid(row=19, column=0, sticky="ew", pady=(10, 0))

        self.status = tk.StringVar(value="Load one or more JSON files, or paste a dataset object, to begin.")
        ttk.Label(left, textvariable=self.status, wraplength=380, foreground="#333").grid(
            row=20, column=0, sticky="w", pady=(10, 0)
        )

        self._set_compare_controls_state()

    def _build_plot(self):
        right = ttk.Frame(self, padding=10)
        right.grid(row=0, column=1, sticky="nsew")
        right.rowconfigure(1, weight=1)
        right.columnconfigure(0, weight=1)

        ttk.Label(right, text="Polar plot", font=("Segoe UI", 11, "bold")).grid(row=0, column=0, sticky="w")

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

    def _set_compare_controls_state(self):
        state = "readonly" if self.compare_var.get() else "disabled"
        self.baseline_combo.configure(state=state)

    def _on_compare_toggle(self):
        self._set_compare_controls_state()

    def _on_tree_click(self, event):
        # Toggle the show flag when clicking in the "Show" column
        region = self.files_tree.identify("region", event.x, event.y)
        if region != "cell":
            return
        col = self.files_tree.identify_column(event.x)
        if col != "#1":  # first column = "show"
            return
        row_id = self.files_tree.identify_row(event.y)
        if not row_id:
            return
        self.toggle_show(row_id)
        # prevent selection change glitches
        return "break"

    def _on_tree_double_click(self, event):
        # Double-click in name column to rename
        region = self.files_tree.identify("region", event.x, event.y)
        if region != "cell":
            return
        col = self.files_tree.identify_column(event.x)
        if col != "#2":  # second column = "name"
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
        # Get all dataset rows
        items = self.files_tree.get_children("")
        if not items:
            return
    
        # Decide whether to turn everything ON or OFF
        # Rule: if ANY dataset is currently hidden → turn ALL ON
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
            messagebox.showinfo("Rename", "Select exactly one dataset to rename.")
            return
        self.rename_dataset(sel[0])

    def sort_by_dataset_name(self):
        items = list(self.files_tree.get_children(""))
        if not items:
            return
    
        if not hasattr(self, "_dataset_sort_reverse"):
            self._dataset_sort_reverse = False
    
        reverse = self._dataset_sort_reverse
    
        # Sort by the NAME column (values[1]) case-insensitively
        items.sort(
            key=lambda iid: self.files_tree.item(iid, "values")[1].casefold(),
            reverse=reverse,
        )
    
        for index, iid in enumerate(items):
            self.files_tree.move(iid, "", index)
    
        # Update header label on the correct column id: "name"
        arrow = " ▼" if reverse else " ▲"
        self.files_tree.heading("name", text="Dataset" + arrow, command=self.sort_by_dataset_name)
    
        self._dataset_sort_reverse = not reverse



    def rename_dataset(self, source_id: str):
        old = self.id_to_display.get(source_id, source_id)
        new_name = simpledialog.askstring("Rename dataset", "New name:", initialvalue=old, parent=self)
        if not new_name:
            return

        new_name = new_name.strip()
        if not new_name:
            return

        # Ensure unique
        if new_name in self.display_to_id and self.display_to_id[new_name] != source_id:
            new_name = make_unique_name(new_name, set(self.display_to_id.keys()))

        # Update maps
        self.id_to_display[source_id] = new_name
        # Remove old reverse mapping
        if old in self.display_to_id and self.display_to_id[old] == source_id:
            self.display_to_id.pop(old, None)
        self.display_to_id[new_name] = source_id

        # Update tree row
        if self.files_tree.exists(source_id):
            show_txt = "✓" if self.show_flag.get(source_id, True) else ""
            self.files_tree.item(source_id, values=(show_txt, new_name))

        # Update baseline selection if it was pointing at old name
        if self.baseline_display_var.get() == old:
            self.baseline_display_var.set(new_name)

        self.refresh_baseline_choices()

    def _register_dataset(self, source_id: str, display: str, df: pd.DataFrame):
        # Ensure display unique
        display = make_unique_name(display, set(self.display_to_id.keys()))
        source_id = source_id if source_id else f"PASTE::{display}"

        self.loaded[source_id] = df
        self.id_to_display[source_id] = display
        self.display_to_id[display] = source_id
        self.show_flag[source_id] = True

        # Insert into treeview (iid = source_id for easy lookup)
        if not self.files_tree.exists(source_id):
            self.files_tree.insert("", "end", iid=source_id, values=("✓", display))

        # If no baseline selected, pick the first loaded
        if not self.baseline_display_var.get():
            self.baseline_display_var.set(display)

    def add_files(self):
        paths = filedialog.askopenfilenames(
            title="Select JSON file(s)",
            filetypes=[
                ("JSON / TXT", ("*.json", "*.txt")),   # ✅ robust on Windows Tk
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

                # If the JSON contains multiple named datasets, register each one.
                for name, df in datasets:
                    display = base if name == "Dataset" else str(name)
                    source_id = p if name == "Dataset" else f"{p}:::{display}"

                    # avoid duplicates by source_id
                    if source_id in self.loaded:
                        continue

                    self._register_dataset(source_id=source_id, display=display, df=df)
                    added += 1

            except Exception as e:
                log_exception("load data from JSON failed")
                messagebox.showerror("Load failed", f"{type(e).__name__}: {e}\n\nLog: {LOG_PATH}")
        
                messagebox.showwarning("Load failed", f"Could not load:{p} {e}")

        if added:
            self.status.set(f"Loaded {added} dataset(s) from file(s). Total: {len(self.loaded)}")
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
            messagebox.showinfo("No text", "Paste the JSON object into the box first.")
            return

        try:
            obj = json.loads(raw)
        except Exception as e:
            messagebox.showerror("JSON parse error", f"Could not parse JSON:\n{e}")
            return

        try:
            datasets = extract_named_datasets(obj)
        except Exception as e:
            messagebox.showerror("Format error", f"JSON parsed but structure not recognized:\n{e}")
            return

        added = 0
        for name, records in datasets:
            if not isinstance(records, list) or (len(records) > 0 and not isinstance(records[0], dict)):
                continue

            display = str(name)
            display = make_unique_name(display, set(self.display_to_id.keys()))
            source_id = f"PASTE::{display}"

            try:
                df = pd.DataFrame(records)
                for c in df.columns:
                    df[c] = pd.to_numeric(df[c], errors="coerce")

                if source_id in self.loaded:
                    continue

                self._register_dataset(source_id=source_id, display=display, df=df)
                added += 1

            except Exception as e:
                messagebox.showwarning("Load failed", f"Failed to load dataset '{name}':\n{e}")

        if added == 0:
            messagebox.showinfo("Nothing loaded", "No valid datasets found in the pasted JSON.")
            return

        self.status.set(f"Loaded {added} pasted dataset(s). Total: {len(self.loaded)}")
        self.refresh_metric_choices()
        self.refresh_baseline_choices()
        self._auto_default_metric()

    def save_pasted_json(self):
        raw = self.paste_text.get("1.0", "end").strip()
        if not raw:
            messagebox.showinfo("No text", "Nothing to save — paste JSON into the box first.")
            return

        try:
            obj = json.loads(raw)
        except Exception as e:
            messagebox.showerror("JSON parse error", f"Could not parse JSON:\n{e}")
            return

        default_name = datetime.now().strftime("pasted_datasets_%Y%m%d_%H%M%S.json")

        out_path = filedialog.asksaveasfilename(
            title="Save pasted datasets JSON",
            defaultextension=".json",
            initialfile=default_name,
            filetypes=[
                ("JSON", ("*.json",)),
                ("All files", ("*.*",)),
            ],
        )

        if not out_path:
            return

        try:
            with open(out_path, "w", encoding="utf-8") as f:
                json.dump(obj, f, indent=2)
            self.status.set(f"Saved pasted JSON to: {out_path}")
        except Exception as e:
            messagebox.showerror("Save failed", f"Could not save:\n{e}")

    def refresh_metric_choices(self):
        if not self.loaded:
            self.metric_combo["values"] = []
            self.metric_var.set("")
            return

        numeric_sets = []
        for df in self.loaded.values():
            numeric_cols = {c for c in df.columns if pd.api.types.is_numeric_dtype(df[c])}
            numeric_sets.append(numeric_cols)

        common = set.intersection(*numeric_sets) if numeric_sets else set()
        common_sorted = sorted(common)
        self.metric_combo["values"] = common_sorted

        if self.metric_var.get() and self.metric_var.get() not in common:
            self.metric_var.set("")

        self._auto_default_metric()

    def _auto_default_metric(self):
        """Prefer leftPedalPower where available; otherwise keep current if valid."""
        vals = list(self.metric_combo["values"])
        cur = self.metric_var.get().strip()

        if cur and cur in vals:
            return

        if "leftPedalPower" in vals:
            self.metric_var.set("leftPedalPower")
            return

        # fallback candidates
        for candidate in ["FilteredleftPedalPower", "rightPedalPower", "power", "Power"]:
            if candidate in vals:
                self.metric_var.set(candidate)
                return

        if vals:
            self.metric_var.set(vals[0])


    def refresh_baseline_choices(self):
        displays = list(self.display_to_id.keys())
        displays.sort()
        self.baseline_combo["values"] = displays

        cur = self.baseline_display_var.get()
        if cur and cur not in self.display_to_id:
            self.baseline_display_var.set(displays[0] if displays else "")

        if not cur and displays:
            self.baseline_display_var.set(displays[0])

    def remove_selected(self):
        sel = list(self.files_tree.selection())
        if not sel:
            return

        for source_id in sel:
            # Remove from tree + internal maps
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


    def _apply_value_mode(self, values: np.ndarray, mode: str):
        if mode == "absolute":
            return np.asarray(values, dtype=float), "absolute"
        if mode == "percent_mean":
            return to_percent_of_mean(values), "% of mean"
        raise ValueError(f"Unknown value mode: {mode}")

    def plot(self):
        if not self.loaded:
            messagebox.showinfo("No data", "Load at least one dataset first (file or paste).")
            return

        angle_col = self.angle_var.get().strip()
        metric_col = self.metric_var.get().strip()
        if not angle_col or not metric_col:
            messagebox.showinfo("Missing selection", "Select both an angle column and a metric column.")
            return

        sentinels = parse_sentinels(self.sentinels_var.get())
        close_loop = bool(self.close_loop_var.get())
        value_mode = self.value_mode_var.get()

        compare = bool(self.compare_var.get())
        baseline_display = self.baseline_display_var.get().strip()
        baseline_id = self.display_to_id.get(baseline_display, "")

        if compare and (not baseline_id or baseline_id not in self.loaded):
            messagebox.showinfo("Baseline required", "Select a valid baseline dataset.")
            return

        self.ax.clear()
        self.ax.set_theta_zero_location("N")
        self.ax.set_theta_direction(-1)

        plotted = 0
        errors = []

        if not compare:
            # NORMAL MODE: plot chosen value mode for every dataset
            for source_id, df in self.loaded.items():
                if not self.show_flag.get(source_id, True):
                    continue
                label = self.id_to_display.get(source_id, os.path.basename(source_id))
                try:
                    ang_deg, val = prepare_angle_value(df, angle_col, metric_col, sentinels)
                    val2, _ = self._apply_value_mode(val, value_mode)

                    theta = np.deg2rad(ang_deg)
                    if close_loop and len(theta) > 2:
                        theta = np.concatenate([theta, [theta[0]]])
                        val2 = np.concatenate([val2, [val2[0]]])

                    self.ax.plot(theta, val2, marker="o", markersize=3, linewidth=1.5, label=label)
                    plotted += 1
                except Exception as e:
                    errors.append(f"{label}: {e}")

            mode_str = "absolute" if value_mode == "absolute" else "% of mean"
            self.ax.set_title(f"{metric_col} ({mode_str})", pad=18)
            self.ax.figure.text(
                0.45, 0.02, f"Angle: {angle_col}",
                ha="center", va="top", fontsize=11, color="gray"
            )
            self.ax.grid(True)
            self.ax.set_position([0.02, 0.08, 0.8, 0.8])
            
            if plotted:
                self.ax.legend(loc="upper left", bbox_to_anchor=(1.02, 1.05), fontsize=9, frameon=False)

            decimals = choose_decimals_from_ticks(self.ax.get_yticks())
            self.ax.yaxis.set_major_formatter(FuncFormatter(lambda r, pos: f"{r:.{decimals}f}"))

        else:
            # COMPARISON MODE: plot (dataset_value_mode - baseline_value_mode)
            b_df = self.loaded[baseline_id]
            b_label = self.id_to_display.get(baseline_id, os.path.basename(baseline_id))

            try:
                b_ang_deg, b_val = prepare_angle_value(b_df, angle_col, metric_col, sentinels)
                b_val2, _ = self._apply_value_mode(b_val, value_mode)
            except Exception as e:
                messagebox.showerror("Baseline error", f"Baseline '{b_label}' failed:\n{e}")
                return

            deltas_by_id = {}
            max_abs = 0.0

            for source_id, df in self.loaded.items():
                if not self.show_flag.get(source_id, True):
                    continue
                if source_id == baseline_id:
                    continue  # baseline already represented by red ring
                label = self.id_to_display.get(source_id, os.path.basename(source_id))
                try:
                    ang_deg, val = prepare_angle_value(df, angle_col, metric_col, sentinels)
                    val2, _ = self._apply_value_mode(val, value_mode)

                    base_at = circular_interp_baseline(b_ang_deg, b_val2, ang_deg)
                    delta = val2 - base_at

                    m = np.isfinite(delta) & np.isfinite(ang_deg)
                    ang_deg2 = ang_deg[m]
                    delta2 = delta[m]
                    if len(ang_deg2) == 0:
                        raise ValueError("No valid comparison values after filtering.")

                    order = np.argsort(ang_deg2)
                    ang_deg2 = ang_deg2[order]
                    delta2 = delta2[order]

                    deltas_by_id[source_id] = (ang_deg2, delta2)
                    this_max = float(np.nanmax(np.abs(delta2)))
                    if np.isfinite(this_max):
                        max_abs = max(max_abs, this_max)

                except Exception as e:
                    errors.append(f"{label}: {e}")

            if not deltas_by_id:
                messagebox.showinfo(
                    "Nothing to plot",
                    "No non-baseline datasets produced valid comparison traces.",
                )
                self._redraw_empty()
                return

            if max_abs <= 0 or not np.isfinite(max_abs):
                max_abs = 1.0

            # Offset radius defines where "0 difference" ring sits
            offset = 1.10 * max_abs

            # Baseline ring at "0"
            theta_ring = np.linspace(0, 2 * np.pi, 361)
            r_ring = np.full_like(theta_ring, offset, dtype=float)
            self.ax.plot(theta_ring, r_ring, linewidth=2.2, color="red", label=f"Baseline = 0 ({b_label})")

            # Plot each dataset delta around baseline ring
            for source_id, (ang_deg2, delta2) in deltas_by_id.items():
                label = self.id_to_display.get(source_id, os.path.basename(source_id))
                theta = np.deg2rad(ang_deg2)
                r = delta2 + offset

                if close_loop and len(theta) > 2:
                    theta = np.concatenate([theta, [theta[0]]])
                    r = np.concatenate([r, [r[0]]])

                self.ax.plot(theta, r, marker="o", markersize=3, linewidth=1.5, label=label)
                plotted += 1

            mode_str = "absolute" if value_mode == "absolute" else "% of mean"
            self.ax.set_title(
                f"{metric_col} ({mode_str}) difference to Baseline ({b_label})",
                pad=18,
            )
            self.ax.figure.text(
                0.45, 0.02, f"Angle: {angle_col}",
                ha="center", va="top", fontsize=11, color="gray"
            )
            self.ax.grid(True)
            self.ax.legend(loc="upper left", bbox_to_anchor=(1.02, 1.05), fontsize=9, frameon=False)
            self.ax.set_position([0.02, 0.08, 0.8, 0.8])
            
            # Auto decimals based on tick spacing; show labels as (r - offset)
            ticks = self.ax.get_yticks()
            decimals = choose_decimals_from_ticks(ticks)
            self.ax.yaxis.set_major_formatter(
                FuncFormatter(lambda r, pos: f"{(r - offset):.{decimals}f}")
            )

        self.canvas.draw_idle()

        msg = f"Plotted {plotted} trace(s)."
        if errors:
            msg += " Some datasets failed (details shown)."
            messagebox.showwarning("Partial plot", msg + "\n\n" + "\n".join(errors))
        self.status.set(msg)


if __name__ == "__main__":
    try:
        import matplotlib  # noqa
        import pandas  # noqa
        import numpy  # noqa
    except Exception as e:
        raise SystemExit(
            "Missing dependencies. Install with:\n"
            "  pip install matplotlib pandas numpy\n"
        ) from e

    app = PolarCompareApp()
    app.mainloop()
