# Kumo-QC Agent Notes

## Architecture Decisions
- Runtime knobs for LEAN deployments belong in `engine.config.RuntimeConfig`.
- Build codegen must emit non-default runtime values onto `BCTAlgorithm` and record them in manifest/metadata provenance.
- Keep `continuous_weekly` as a compatibility shim until all strategy/sweep callers migrate to `RuntimeConfig`.
- Watchlist carry is selection-gate subscription behavior in `runtime.lean_entry`, with pure helper logic in `runtime.watchlist_carry`; ranking phases may maintain watchlist state but must not subscribe names.
- George profile and attention files are optional runtime inputs; loaders must fail soft, preserve source/confidence fields, and populate plain maps consumed by phases.
- Sweep configs may carry runtime overrides and disabled phase choices; these are behavioral identity and must enter the sweep hash before any result reaches a leaderboard.
