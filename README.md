# Dashboard Data Plotter

Dashboard Data Plotter is a **local, offline Python desktop application** built with **Tkinter + Matplotlib**
for analysing cycling, biomechanical, and other structured numerical datasets, with optional **Plotly**
interactive plotting in the system browser.

Although originally focused on pedal‑stroke analysis, the application has evolved into a
**general dashboard‑style data comparison tool**, supporting both angular (radar) and aggregate (bar)
visualisations across multiple datasets.

The project is intentionally designed to be **Codex‑friendly**: modular, explicit, rule‑driven,
and resistant to accidental semantic breakage.

---

## Core capabilities

### Data loading
- Start with an **untitled project** or load a saved project JSON
- Add **one or more data files** (JSON/TXT today; CSV planned)
- Load **multi‑dataset JSON objects** (file‑based or pasted)
- Paste JSON objects directly into the UI
- Project title is stored in the project JSON and used as the default save filename
- Save the **entire project** to JSON (default extension `.proj.json`, prompted to include plot history)
- Project files include a `__project_settings__` block with project title, plot/cleaning settings, dataset order, visibility, and plot history (if saved)
- Rename datasets without changing their identity
- Toggle dataset visibility (Show / Hide)
- Export the currently displayed plot data to CSV
- Open the in-app **Guide** for workflow help

### Supported JSON formats

#### Single dataset (list of records)
```json
[
  { "leftPedalCrankAngle": 90, "leftPedalPower": 210 },
  { "leftPedalCrankAngle": 180, "leftPedalPower": 320 }
]
```

#### Multi‑dataset object
```json
{
  "R1": { "rideData": [ {...}, {...} ] },
  "R2": { "rideData": [ {...}, {...} ] }
}
```

Project saves may also include per‑dataset metadata inside each dataset object:
`__source_id__` and `__display__` are used to keep plot history aligned with dataset identity.

Each dataset typically represents **~52 angular bins** over a full 360° cycle,
but the app is tolerant of missing or sparse data.

---

## Visualisation modes

### Radar (polar) plot
- Metric value vs crank angle
- Uses **standard crank angle convention**
  - 0° = Top Dead Centre (TDC)
  - Clockwise positive
- Automatically converts Body Rocket crank‑angle conventions
- Optional background image support for radar plots (see below)
- Supports:
  - Absolute metric values
  - % of dataset mean
  - Comparison vs baseline (difference ring)

### Cartesian (0–360°) plot
- Metric value vs crank angle on Cartesian axes
- Uses the same 52-bin angular aggregation as radar plots
- Supports:
  - Absolute metric values
  - % of dataset mean
  - Comparison vs baseline (signed delta on y, with a zero reference line)

### Bar plot
- One bar per dataset
- Represents **mean metric value per dataset**
- Supports:
  - Absolute values
  - Difference vs baseline
- Shows value labels on bars with spread-aware rounding
  - In comparison mode, positive labels are shown above bars and negative labels at the base near zero
- X-axis label spacing adapts to long dataset names, with smaller tick font for names longer than 15 characters
- Explicitly **does not use crank angle**
- “% of dataset mean” is intentionally disabled for bar plots

---

## Comparison mode

When comparison mode is enabled:
- A **baseline dataset** is selected
- Radar plots:
  - Baseline drawn as a **zero reference ring**
  - Other datasets plotted as angular differences
- Cartesian plots:
  - Baseline provides the interpolation reference
  - Other datasets plotted as signed angular deltas with a y=0 reference line
- Bar plots:
  - Baseline bar fixed at **0**
  - Other bars show ± difference relative to baseline

---

## UI structure

- **Left panel**
  - Data Sources list (order matters)
  - Paste JSON pane
  - Plot settings
  - Comparison controls
  - Change log button (opens `CHANGELOG.md` in-app; auto-populated from git history with room for manual entries)
- **Right panel**
  - Matplotlib figure canvas
  - Toolbar (zoom, pan, save image)

When the **Use Plotly (interactive)** option is enabled, plots are rendered as interactive Plotly charts
in your default web browser instead of the embedded Matplotlib canvas. When navigating plot history,
interactive plots are shown inline as Matplotlib previews; click Plot to reopen the interactive view.

Dataset order in the **Data Sources panel defines plotting order everywhere**.

---

## Reports and snapshots

The Tkinter app can capture **frozen snapshots** of plots (with annotations and comments) into a
JSON report file. Snapshots are saved as static images (Matplotlib) or HTML (Plotly), so they do not
change if datasets later change.

Report workflow:
1. Plot a chart.
2. (Optional) Toggle **Annotate** and click the plot to add text annotations.
3. Click **Add snapshot...** to include the plot and comments in the report.
4. Use **Export HTML...** or **Export PDF...** to share with clients.

Report files are stored as JSON (default extension `.rep.json`) and create a sibling `*_assets` folder with the snapshot files.
PDF export uses the optional `weasyprint` dependency; if it is not installed, the app will prompt you.
Snapshot comments accept basic Markdown (bold, italics, bullet lists).

---

## Radar/Cartesian background images (optional)

If you want a background image behind radar plots, place an image at:

```
src/dashboard_data_plotter/assets/radar_background.png
```

You can also use `radar_background.jpg` or `radar_background.jpeg`. When present, the image is
rendered behind both the Matplotlib and Plotly radar plots. Use the "Background image"
checkbox in the Plot settings panel to toggle it on or off. If the file is missing, radar plots
render normally without a background.

For Cartesian plots, the app uses:

```
src/dashboard_data_plotter/assets/leg_muscles.jpeg
```

When present, it is rendered behind the Plotly/Matplotlib Cartesian plot along with angular color
bands. If the file is missing, Cartesian plots render normally without a background.

---

## Project layout

```
dashboard_data_plotter/
  main.py
  README.md
  AGENTS.md
  requirements.txt

  scripts/
    run_dev.bat
    build_exe.bat

  src/dashboard_data_plotter/
    app.py
    ui/
      tk_app.py
      streamlit_app.py
    core/
      state.py
      datasets.py
      cleaning.py
      plotting.py
      analysis.py
      io.py
    data/
      loaders.py
    plotting/
      helpers.py
    utils/
      log.py
      sortkeys.py
```

---

## Running locally

```bat
scripts\run_dev.bat
```

This will:
1. Create a virtual environment
2. Install dependencies
3. Run the application

---

## Streamlit UI (optional)

The Streamlit UI mirrors most plotting controls from the Tkinter app, including:
- Plot type selection (Radar / Cartesian / Bar / Time series)
- Close loop, outlier removal (MAD / Phase-MAD / Hampel / Impulse), fixed range
- Baseline comparison
- Optional background images/bands
- Plot history (Prev / Next / Delete)

To run the Streamlit UI:

```bat
streamlit run streamlit_app.py
```

---

## Building a Windows executable

```bat
scripts\build_exe.bat
```

Produces:
```
dist\DashboardDataPlotter.exe
```

### Versioning and changelog
- `MAJOR_VERSION` lives in `src/dashboard_data_plotter/version.py` and is **manual only**
- `BUILD_VERSION` also lives in `src/dashboard_data_plotter/version.py` and increments for each packaged build
- Each build should be tagged in git as `MAJOR.BUILD` (for example `3.19`)
- The in-app Change Log auto-populates from git commits **since the most recent build tag**

---

## Design philosophy

- Explicit > clever
- UI logic and data logic are separated
- Dataset order is sacred
- Comparison semantics must be visually obvious
- Errors should never crash the app

All of these rules are enforced in **AGENTS.md**.
