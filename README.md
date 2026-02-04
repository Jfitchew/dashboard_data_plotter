# Dashboard Data Plotter

Dashboard Data Plotter is a local Python (Tkinter) application for analysing cycling pedal-stroke
metrics across multiple test runs.

It supports:
- Loading one or more JSON datasets (single or multi-dataset JSON files)
- Visual comparison of pedal-stroke metrics across datasets
- Radar (polar) plots across the pedal stroke
- Bar plots summarising per-dataset averages
- Baseline comparison modes
- Consistent dataset ordering, naming, and saving

The tool is designed for biomechanical and performance analysis use cases
(e.g. pedal force, power, dead-centre metrics).

---

## Data format

### Single dataset JSON
```json
[
  { "leftPedalCrankAngle": 90, "leftPedalPower": 210 },
  ...
]
```

### Multi-dataset JSON
```json
{
  "R1": { "rideData": [ {...}, {...} ] },
  "R2": { "rideData": [ {...}, {...} ] }
}
```

Each dataset is expected to represent approximately **52 angular bins**
covering the full 360° pedal stroke.

Sentinel values such as `-999` or `-99` are treated as missing data.

---

## Application structure

- **Tkinter UI**
  - Left panel: Data Sources and Plot Settings
  - Right panel: Matplotlib figure canvas
- **Dataset handling**
  - Multiple datasets loaded simultaneously
  - Order in the Data Sources panel defines plotting order
- **Plot types**
  - Radar (polar): metric vs crank angle
  - Bar: mean metric per dataset
- **Comparison mode**
  - Optional baseline dataset
  - Radar: differences plotted around a zero ring
  - Bar: differences plotted around zero

---

## Key invariants (do not break)

- Dataset plotting order must match the order shown in the Data Sources panel
- Bar plots must NOT depend on crank angle selection
- “% of dataset mean” is invalid for bar plots
- All plots must work with multiple datasets enabled/disabled via “Show”
- Save All must reproduce a valid multi-dataset JSON file

---

## Running

```bash
python dashboard_data_plotter.py
```

No external services are required.
