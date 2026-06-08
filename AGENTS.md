# Kumo-QC Agent Notes

## Architecture Decisions
- Runtime knobs for LEAN deployments belong in `engine.config.RuntimeConfig`.
- Build codegen must emit non-default runtime values onto `BCTAlgorithm` and record them in manifest/metadata provenance.
- Keep `continuous_weekly` as a compatibility shim until all strategy/sweep callers migrate to `RuntimeConfig`.
