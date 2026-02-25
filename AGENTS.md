# AGENTS.md - Dashboard Data Plotter

This file defines hard rules and invariants for AI coding agents (OpenAI Codex).
Violating these rules is considered a breaking change.

## Project intent

This is a stateful desktop-first plotting application (Tkinter primary) with shared core logic and additional adapters/tools (Streamlit UI, report export, rich HTML editor).

Correctness depends on interactions between:
- UI state
- Dataset identity
- Dataset ordering
- Plot semantics
- Comparison logic
- Project/report serialization

Small changes can silently break behavior. Agents must follow the rules below.

## Core invariants (DO NOT BREAK)

### Dataset handling
- Dataset identity is tracked via `source_id`.
- Display names may change; identities must not.
- Dataset plotting order must exactly match the Data Sources Treeview order.
- Save All / Save Data must preserve dataset order and display names.
- Comparison baseline selection must use `source_id` values (not names).
- Multi-baseline ordering must remain stable and user-driven (do not sort unless explicitly requested).

### Plot types

#### Radar plots
- Depend on crank angle.
- Use standard crank angle internally.
- Use 52-bin angular aggregation.
- Support:
  - absolute values
  - percent of dataset mean
  - comparison vs baseline

#### Bar plots
- Represent mean metric per dataset.
- Must ignore crank angle entirely.
- Must not allow percent-of-dataset-mean mode.
- Must support baseline comparison.
- Baseline bar must be present at zero.

### UI state rules
- Selecting Bar plot:
  - disables angle selection
  - disables close-loop
  - disables percent-mean mode
- Switching back to Radar restores controls.
- UI must never enter an invalid state.

### Data cleaning and numeric safety
- Numeric parsing must use `pd.to_numeric(..., errors="coerce")`.
- Sentinel values must be converted to `NaN`.
- Missing/invalid values must not raise during plotting.
- Prefer tolerant parsing/loading behavior over hard failure for partially valid datasets.

### Serialization compatibility
- Project/report load paths should tolerate missing keys and older saved payloads where practical.
- Do not rename/remove serialized keys silently without compatibility handling.
- Save payload ordering must be deterministic where user order matters (datasets, report content blocks, snapshots).

## Architecture and separation rules

- Keep `core/` free of Tkinter/Streamlit UI concerns.
- Keep UI adapters (`ui/`) focused on rendering, event wiring, and state orchestration.
- Do not move plotting math/aggregation logic into UI files.
- Do not merge bar/radar/time-series preparation logic into one branchy function unless explicitly requested.
- Prefer adding small helpers in `core/`/`data/` over duplicating logic in `tk_app.py`.
- Preserve function signatures unless the change requires a coordinated call-site update.
- In `tk_app.py` (large file), prefer localized edits and helper extraction over broad refactors.

## Reporting/export rules

- Report content order is user-authored and must be preserved.
- Export code (`core/reporting.py`, `core/report_pdf.py`) must not mutate report content unexpectedly.
- Keep HTML/PDF export behavior resilient to unsupported rich content (degrade gracefully, do not crash).

## Agents must NOT

- Reorder datasets alphabetically unless explicitly requested.
- Change plot semantics silently.
- Merge bar and radar logic.
- Introduce UI-only assumptions into `core/` or `data/`.
- Break project/report backward compatibility without an explicit migration plan.

## Agents SHOULD

- Make minimal, localized edits.
- Preserve function signatures where possible.
- Add helpers instead of duplicating logic.
- In final responses for coding tasks, offer 1-2 concise suggestions for follow-on code improvements or features that either move the project toward the mission-statement end goal (broader cycling-data insight, progressive automation, higher-quality reporting) or reflect best practice for cycling data analytics tools.
- Update `CHANGELOG.md` with a brief summary for user-visible behavior changes and important tooling/process-document updates; remove entries if changes are rolled back.
- Use `src/dashboard_data_plotter/version.py` `BUILD_VERSION` as the middle number in new changelog entry versions (`MAJOR.BUILD.xxx`), e.g. if `BUILD_VERSION = "43"` then new entries should be `3.43.xxx`.
- Update `README.md` / `GUIDE.md` if user-facing behavior or workflow changes.
- MAJOR version is manual (see `src/dashboard_data_plotter/version.py`); do not auto-bump it.
- Packaged builds should be tagged in git as `MAJOR.BUILD` for changelog cutoffs.
- Call out key manual checks after changes (2-4 items max) tied to modified behavior.
- Run through the testing checklist mentally.

## Validation expectations (pragmatic)

- Run targeted checks that match the scope of the change.
- Do not claim validation you did not run.
- PyInstaller build validation is required for packaging/build changes, entrypoint changes, or dependency changes; otherwise it is a release-level check, not a per-edit requirement.

## Mandatory mental test checklist

After changes that could affect plotting/state/serialization, ensure the following still work:

1. Load single JSON dataset
2. Load multi-dataset JSON
3. Paste multi-dataset JSON
4. Rename datasets
5. Toggle Show / Hide
6. Switch Radar <-> Bar
7. Enable comparison mode
8. Change baseline (single and multi-baseline if applicable)
9. Save All / Save Data and reload saved file
10. Build EXE with PyInstaller (release-impact changes)

## Architecture map (current)

### Top level / entrypoints
- `main.py`: bootstrap `src/` onto `sys.path` and run package app entrypoint
- `src/dashboard_data_plotter/app.py`: main CLI/app dispatcher (Tk app vs rich HTML editor helper mode)
- `streamlit_app.py`: root convenience launcher for Streamlit adapter

### core/
- `state.py`: `ProjectState`, plot settings, cleaning/analysis settings updates
- `datasets.py`: dataset identity/order/show/hide/reorder transitions
- `plotting.py`: plot preparation for radar/cartesian/bar/time series (no rendering)
- `io.py`: project save/load payloads + settings apply
- `cleaning.py`: cleaning settings model (future workflow support)
- `analysis.py`: analysis settings model (future workflow support)
- `reporting.py`: report state create/load/save and report asset path helpers
- `report_pdf.py`: direct PDF report export rendering (ReportLab path)

### data/
- `loaders.py`: JSON dataset extraction/loading, numeric sanitization, sentinel handling, angle prep, outlier filtering, aggregation helpers

### plotting/
- `helpers.py`: rendering-side numeric formatting/interpolation helpers shared by UI plotting backends

### ui/
- `tk_app.py`: Tkinter adapter (rendering + event wiring + desktop workflows)
- `streamlit_app.py`: Streamlit adapter (rendering + event wiring)
- `rich_html_editor.py`: desktop rich HTML content editor helper (pywebview/fallback flow)

### utils/
- `log.py`: logging helpers
- `sortkeys.py`: sorting helpers/utilities

If unsure, stop and ask the user before changing architecture boundaries.

## Guidance for Codex prompts

Good task:
> "Add feature X without breaking dataset ordering or comparison semantics. Follow AGENTS.md."

Bad task:
> "Refactor everything to be cleaner."

## Final rule

If a requested change conflicts with any rule above, stop and ask for clarification before coding.
