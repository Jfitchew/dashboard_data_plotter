# Change Log

3.29 - New Build Release
  - 3.29.87 - 2026-02-19 - Increased radar auto-range lower-bound buffer from 10% to 20% of span when Fixed range is off.
  - 3.29.86 - 2026-02-19 - Documented changelog numbering policy: use the next build number (`BUILD_VERSION + 1`) for release headers and keep entries top-first.
  - 3.29.85 - 2026-02-19 - Removed git-based changelog auto-generation; the app now reads and maintains a single manual `CHANGELOG.md` source.
  - 3.29.84 - 2026-02-19 - Rotated bar value labels automatically when plotting 15+ datasets to reduce overlap in both Matplotlib and Plotly bar charts.
  - 3.29.83 - 2026-02-19 - Restored backward compatibility for Plotly radar helper call arity so older positional call sites still work while supporting multi-baseline IDs.
  - 3.29.82 - 2026-02-19 - Hardened plot-history visibility restore to remap by saved source IDs first and only use unambiguous imported display-name fallback, preventing misbinding after name de-duplication.
  - 3.29.81 - 2026-02-19 - Prevented failed Plotly plot attempts from being added to plot history; history now updates only after a successful render.
  - 3.29.80 - 2026-02-19 - Fixed project save name normalization to prevent repeated `.proj` suffixes and hardened project-load clearing so non-polar current views do not block loading.
  - 3.29.79 - 2026-02-19 - Stabilized "% of dataset mean" normalization by falling back to full data-span scaling when mixed-sign data makes the mean near zero.
  - 3.29.78 - 2026-02-19 - Updated radar auto-range so the inner radial bound defaults to `minimum - 10% * (maximum - minimum)` while keeping the outer bound at the plotted maximum (when Fixed range is off).
  - 3.29.77 - 2026-02-18 - Anchored the baseline multi-select popup below the baseline dropdown button with a post-layout reposition pass and pointer-based fallback placement.
  - 3.29.76 - 2026-02-18 - Made the baseline dropdown list draggable/closable and centered it when the anchor control is unavailable or returns invalid coordinates.
  - 3.29.75 - 2026-02-16 - Fix Plotly radar call to pass baseline_ids.
  - 3.29.74 - 2026-02-16 - Delete history entries without confirmation and render the previous plot.
  - 3.29.73 - 2026-02-16 - Update project title to match the saved filename.
  - 3.29.72 - 2026-02-16 - Reset plot/UI state before loading a new project to avoid stale plot errors.
  - 3.29.71 - 2026-02-16 - Positioned baseline dropdown near the control and made it scrollable.
  - 3.29.70 - 2026-02-16 - Reworked baseline dropdown click-away handling to keep items visible.
  - 3.29.69 - 2026-02-16 - Prevented baseline dropdown from closing immediately on mouse release.
  - 3.29.68 - 2026-02-16 - Removed blocking grab from baseline dropdown and closed it on click-away.
  - 3.29.67 - 2026-02-16 - Stabilized baseline dropdown focus/visibility handling.
  - 3.29.66 - 2026-02-16 - Fixed baseline multi-select button to reopen the dropdown reliably.
  - 3.29.65 - 2026-02-16 - Kept baseline multi-select dropdown open until focus leaves it.
  - 3.29.64 - 2026-02-16 - Lifted radar titles to avoid overlap with angle labels.
  - 3.29.63 - 2026-02-16 - Restored right-side legends and widened plot panel to make room for them.
  - 3.29.62 - 2026-02-16 - Adjusted legend placement and title spacing to keep legends above plots without overlap.
  - 3.29.61 - 2026-02-16 - Updated baseline labels and legend layout; reduced plot whitespace and set baseline menu background to white.
  - 3.29.60 - 2026-02-16 - Moved baseline multi-selection into the comparison dropdown menu.
  - 3.29.59 - 2026-02-16 - Added multi-baseline comparison selection and averaged baseline logic for radar, cartesian, bar, and time-series plots.
  - 3.29.58 - 2026-02-11 - Export report HTML as a standalone file with embedded assets.
  - 3.29.57 - 2026-02-11 - Allow report export to succeed when assets are locked; warn instead.
  - 3.29.56 - 2026-02-11 - Bundle GUIDE.md and CHANGELOG.md in PyInstaller builds.
  - 3.29.55 - 2026-02-11 - Fix HTML/PDF export default filenames to avoid double .rep.
  - 3.29.54 - 2026-02-11 - Restore report preview without forcing a save dialog.
  - 3.29.53 - 2026-02-11 - Show Matplotlib previews when navigating Plotly plot history.
  - 3.29.52 - 2026-02-10 - Fixed report export dialogs and snapshot save flow.
  - 3.29.51 - 2026-02-10 - Warn when fixed plot range hides all data.
  - 3.29.50 - 2026-02-10 - Adjusted report export defaults and button order.
  - 3.29.49 - 2026-02-10 - Added in-app guide and Guide button.
  - 3.29.48 - 2026-02-10 - Adjusted report button layout and labels.
  - 3.29.47 - 2026-02-10 - Updated report lifecycle prompts and project/report extensions.
  - 3.29.46 - 2026-02-10 - Fixed Markdown regex for report preview.
  - 3.29.45 - 2026-02-10 - Fixed markdown rendering in report comments.
  - 3.29.44 - 2026-02-10 - Adjusted report layout and comment placement.
  - 3.29.43 - 2026-02-10 - Improved report layout, markdown comments, and data source labels.
  - 3.29.42 - 2026-02-10 - Added report snapshots with annotations and HTML/PDF export.

3.19 - New Build Release
  - 3.19.42 - Added bar-value annotations (including comparison bars), adaptive significant-digit rounding, and long-label spacing/font adjustments for bar charts.
  - 3.19.41 - Added changelog support and in-app change log viewer.

