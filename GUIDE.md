# Dashboard Data Plotter — Workflow Guide

This guide focuses on the core workflow: projects, datasets, plot settings, plot history, and reports.

---

## Projects

**Projects** store your datasets, plot settings, plot history (optional), and UI state.

Typical flow:
1. **New project** to start clean.
2. **Load datasets** (files or pasted JSON).
3. **Set plot settings** and visualize.
4. **Save project** as `*.proj.json`.

Key points:
- Project files preserve dataset order and names.
- Project title is stored and used in default save names.
- You can load a project to restore settings and plot history.

---

## Datasets

You can add datasets in three ways:
- **Add data file(s)...** from JSON/TXT.
- **Paste data source** (JSON) and click **Load pasted data**.
- **Load project** (brings datasets back).

Tips:
- The **Data sources** list defines **plot order**.
- Use **Rename**, **Up**, and **Dn** to manage ordering and labels.
- **Show / Hide** controls whether a dataset appears in plots.

---

## Plot Settings

Choose how to visualize:

- **Plot type**
  - **Radar (polar)**: metric vs crank angle (52-bin aggregation).
  - **Cartesian**: metric vs crank angle on XY axes.
  - **Bar**: mean per dataset (ignores crank angle).
  - **Time series**: full metric trace.

- **Angle column**
  - Used by Radar and Cartesian plots only.

- **Metric column**
  - Choose the metric to plot.

- **Avg type**
  - Radar/Cartesian: mean, median, 10% trimmed mean.
  - Time series: raw, pedal stroke, or roll 360deg.

- **Value mode**
  - Absolute values.
  - % of dataset mean (Radar/Cartesian only).

- **Comparison**
  - Difference vs baseline dataset.
  - Select a baseline from the dropdown.

- **Range**
  - Fix plot Y-axis range for consistent comparisons.

- **Outliers**
  - Optional filtering and display.

---

## Plot History

Every time you plot, a **history entry** is saved.

Controls:
- **Prev / Next**: navigate history entries.
- **X**: delete the current history entry.
- **Clear**: remove all history entries.

You can also save plot history inside the project file when saving.

---

## Reports and Snapshots

Reports let you capture **frozen snapshots** of plots with comments and annotations.

Workflow:
1. Click **New report...** (enter project title if prompted).
2. Plot a chart.
3. (Optional) toggle **Annotate** and click the plot to add text annotations.
4. Click **Add snapshot...** to capture the plot, comments, and settings.
5. **Preview report** to open a browser view.
6. **Save report** as `*.rep.json`.
7. Export to **HTML** or **PDF** for client sharing.

Notes:
- Matplotlib snapshots are saved as images.
- Plotly snapshots are saved as interactive HTML.
- Comments support basic Markdown (bold, italics, bullet lists).

---

## Tips for Reliable Results

- Keep dataset order intentional (it drives plotting order).
- Use **Comparison** with a stable baseline for consistent deltas.
- Fix the plot range when comparing multiple plots.
- Save the project before closing so plot history is preserved.
