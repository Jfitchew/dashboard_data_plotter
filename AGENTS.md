# AGENTS.md — Dashboard Data Plotter

This file defines **hard rules and invariants** for AI coding agents (OpenAI Codex).
Violating these rules is considered a breaking change.

---

## 🎯 Project intent

This is a **stateful Tkinter desktop application** with complex interactions between:
- UI state
- Dataset identity
- Dataset ordering
- Plot semantics
- Comparison logic

Small changes can silently break correctness.

Agents must follow the rules below.

---

## 🔐 Core invariants (DO NOT BREAK)

### Dataset handling
- Dataset identity is tracked via `source_id`
- Display names may change, identities must not
- Dataset plotting order **must exactly match**
  the Data Sources Treeview order
- Save All must preserve dataset order and names

### Plot types

#### Radar plots
- Depend on crank angle
- Use standard crank angle internally
- Use 52‑bin angular aggregation
- Support:
  - absolute values
  - % of dataset mean
  - comparison vs baseline

#### Bar plots
- Represent **mean metric per dataset**
- Must **ignore crank angle entirely**
- Must **not allow % of dataset mean**
- Must support baseline comparison
- Baseline bar must be present at zero

### UI state rules
- Selecting Bar plot:
  - disables angle selection
  - disables close‑loop
  - disables %-mean mode
- Switching back to Radar restores controls
- UI must never enter an invalid state

### Data cleaning
- Numeric parsing must use:
  ```python
  pd.to_numeric(..., errors="coerce")
  ```
- Sentinel values must be converted to NaN
- Missing values must never raise during plotting

---

## 🚫 Agents must NOT

- Reorder datasets alphabetically unless explicitly requested
- Change plot semantics silently
- Merge bar and radar logic


---

## ✅ Agents SHOULD

- Make minimal, localised edits
- Preserve function signatures
- Add helpers instead of duplicating logic
- Update CHANGELOG.md with a brief summary of code changes, and remove entries if changes are rolled back
- Update README if behaviour changes
- MAJOR version is manual (see `src/dashboard_data_plotter/version.py`); do not auto-bump it
- Packaged builds should be tagged in git as `MAJOR.BUILD` for changelog cutoffs
- Call out key manual checks after changes (2–4 items max) tied to the modified behavior
- Run through the testing checklist mentally

---

## 🧪 Mandatory mental test checklist

After any change, ensure the following still work:

1. Load single JSON dataset
2. Load multi‑dataset JSON
3. Paste multi‑dataset JSON
4. Rename datasets
5. Toggle Show / Hide
6. Switch Radar ↔ Bar
7. Enable comparison mode
8. Change baseline
9. Save All and reload saved file
10. Build EXE with PyInstaller

---

## 🏗️ Architecture map (current)

### core/
- `state.py`: ProjectState + plot settings + cleaning/analysis settings
- `datasets.py`: dataset identity/order/show/hide transitions
- `plotting.py`: plot preparation for radar/cartesian/bar/time series (no rendering)
- `io.py`: project save/load + settings apply
- `cleaning.py`: CleaningSettings (stub for future workflows)
- `analysis.py`: AnalysisSettings (stub for future workflows)

### ui/
- `tk_app.py`: Tkinter adapter (rendering + event wiring)
- `streamlit_app.py`: Streamlit adapter (rendering + event wiring)

If unsure, STOP and ask the user.

---

## 🧭 Guidance for Codex prompts

Good task:
> “Add feature X without breaking dataset ordering or comparison semantics. Follow AGENTS.md.”

Bad task:
> “Refactor everything to be cleaner.”

---

## Final rule

If a requested change conflicts with ANY rule above:
**STOP and ask for clarification before coding.**
