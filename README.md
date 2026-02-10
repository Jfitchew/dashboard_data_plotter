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
- Load **one or more JSON files** from disk
- Load **multi‑dataset JSON objects** (file‑based or pasted)
- Paste JSON objects directly into the UI
- Save all currently loaded datasets into a **single multi‑dataset JSON**
- Saved files include a `__project_settings__` block with plot/cleaning settings, dataset order, visibility, and plot history
- Rename datasets without changing their identity
- Toggle dataset visibility (Show / Hide)
- Export the currently displayed plot data to CSV

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
- **Right panel**
  - Matplotlib figure canvas
  - Toolbar (zoom, pan, save image)

When the **Use Plotly (interactive)** option is enabled, plots are rendered as interactive Plotly charts
in your default web browser instead of the embedded Matplotlib canvas.

Dataset order in the **Data Sources panel defines plotting order everywhere**.

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

---

## Design philosophy

- Explicit > clever
- UI logic and data logic are separated
- Dataset order is sacred
- Comparison semantics must be visually obvious
- Errors should never crash the app

All of these rules are enforced in **AGENTS.md**.
