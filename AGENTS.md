# AGENTS.md — Dashboard Data Plotter

This file defines **strict rules** for AI agents (OpenAI Codex) modifying this repository.

The goal is to allow safe iteration without breaking UI wiring, dataset semantics,
or plotting correctness.

---

## 🧠 High-level intent

Dashboard Data Plotter is a **stateful Tkinter application** with tight coupling between:
- UI widgets
- Dataset order
- Plot logic
- Comparison semantics

Small changes in one area can silently break others.

Agents must respect the invariants below.

---

## 🚨 Non-negotiable invariants

### Dataset identity & order
- Dataset order is defined by the **Treeview order** in the Data Sources panel
- Plotting order MUST follow the Treeview order
- Save All must preserve this order
- Renaming a dataset must not change its identity or break references

### Plot semantics
- Radar plots:
  - Depend on crank angle
  - Use 52-bin angular aggregation
  - Support absolute and comparison modes
- Bar plots:
  - Represent **mean metric per dataset**
  - Must ignore crank angle
  - Must NOT allow “% of dataset mean”
  - Must support baseline comparison with zero line

### UI logic
- When Bar plot is selected:
  - Angle column selection must be disabled
  - Close-loop option must be disabled
  - “% of dataset mean” must be disabled and auto-reset to Absolute
- When Radar plot is selected:
  - All angle-related controls must be re-enabled

### Data handling
- All numeric parsing must use:
  ```python
  pd.to_numeric(..., errors="coerce")
  ```
- Sentinel values must be converted to NaN
- Missing data must never raise during plotting

---

## ❌ What agents must NOT do

- Do NOT reorder datasets alphabetically unless explicitly instructed
- Do NOT refactor UI layout without user request
- Do NOT change plotting definitions silently (e.g. mean definition)
- Do NOT introduce new dependencies without asking
- Do NOT convert this app to a web framework

---

## ✅ What agents SHOULD do

- Make minimal, localised changes
- Preserve existing function signatures where possible
- Add UI state guards instead of deleting options
- Add helper functions instead of duplicating logic
- Prefer explicitness over clever abstractions

---

## 🧪 Testing expectations

After any change, the following must still work:
1. Load multi-dataset JSON
2. Rename datasets
3. Toggle Show flags
4. Switch Radar ↔ Bar plot
5. Enable/disable comparison mode
6. Save All and reload the saved file
7. Package with PyInstaller without runtime errors

---

## 🧩 If unsure

If a requested change conflicts with any rule above:
- STOP
- Explain the conflict
- Ask for clarification before coding
