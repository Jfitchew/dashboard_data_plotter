## Dashboard Data Plotter - Workflow Guide

This guide focuses on the core workflow: projects, datasets, plot settings, plot history, and reports/content.

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
- If a saved project includes plot history, the app restores and displays the most recent history entry automatically.

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
- **Save Data** exports only datasets currently marked **Show** to a multi-dataset `.data.json` file (without project settings/history).

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
  - Bar: mean metric per dataset.
  - Time series: raw, pedal stroke, or roll 360deg.

- **Value mode**
  - Absolute values.
  - % of dataset mean (Radar/Cartesian only).

- **Comparison**
  - Difference vs baseline dataset(s).
  - Select one or more baselines from the dropdown checklist.
  - Selected baselines are averaged into a baseline group for comparison.

- **Range**
  - Fix plot Y-axis range for consistent comparisons.

- **Outliers**
  - Optional filtering and display.

---

## Plot History

Each successful plot adds a **history entry**.

Controls:
- **Prev / Next**: navigate history entries.
- **X**: delete the current history entry.
- **Clear**: remove all history entries.

You can also save plot history inside the project file when saving.

---

## Reports and Snapshots

Reports let you capture **frozen snapshots** of plots with comments/annotations and add standalone narrative content blocks.

Workflow:
1. Click **New report...** (report title defaults from the current project title).
2. Plot a chart.
3. (Optional) Click **Format...** to set annotation style defaults.
4. (Optional) Toggle **Annotate** and click the plot to add text annotations.
5. (Optional) Drag existing annotations to reposition them.
6. Click **Add snapshot...** to capture the plot, comments, and settings.
7. (Optional) Click **Add content** to add text/rich content blocks that are not tied to a plot.
8. (Optional) Use **Manage content...** to edit/remove/reorder snapshots and content blocks.
9. (Optional) Tick **Incl meta** to include metadata in preview/export.
10. **Preview report** to open a browser view.
11. **Save report** as `*.rep.json`.
12. Export to **HTML** or **PDF** for client sharing.

Notes:
- Matplotlib snapshots are saved as images.
- Plotly snapshots are saved as interactive HTML.
- Reports are standalone (they do not store project file references).
- Snapshot comments and plain-text content support basic Markdown (bold, italics, bullet lists).
- Rich content blocks can include pasted HTML/images (Windows rich editor when available); PDF export may use a text fallback for complex rich content.

---

## Tips for Reliable Results

- Keep dataset order intentional (it drives plotting order).
- Use **Comparison** with a stable baseline (or baseline group) for consistent deltas.
- Fix the plot range when comparing multiple plots.
- Save the project before closing so plot history is preserved.
