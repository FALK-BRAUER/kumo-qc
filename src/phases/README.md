# src/phases/

The phase LIBRARY — every merged, useful phase implementation. Config switches them on/off; only enabled phases ship to `dist/`.

- **Layout:** `phases/<kind>/<impl>/<impl>.py` (one folder per implementation). Kinds: universe, signal, regime, ranking, entry, sizing, stops, trail, exit, adds, profit, reentry, rebalance, diagnostics, circuit_breaker, ...
- **Goes here:** a phase that passed the PR gate (tests + parity + charter + header) — merged regardless of champion status.
- **Does NOT:** experimental/unmerged phases (keep on a feat branch until they pass), strategy configs (`strategies/`).
- **Each impl:** implements the `PhaseInterface` Protocol, carries a nested typed `.Params` dataclass, owns its mirror test in `tests/phases/<kind>/<impl>/`.
