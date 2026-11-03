# TODO

- **grid control** — a runtime control for the grid side: pin the grid
  power (`set grid W`) like pv/load/batt, or a grid machine (a priced
  import/export model) instead of the pure pv - batt - home balance.
- **update the status command** — the `show status` line grows with every
  feature (battery-state, cloud machine, profile); rework it into a
  compact multi-field report with stable, scriptable fields.
- **update the documentation, comments, etc.** — the README and the
  docstrings drifted during the recent changes (profiles, control
  surface, docker); sweep them for accuracy and fill the gaps.
