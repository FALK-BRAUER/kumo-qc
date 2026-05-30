# archive/

Superseded files kept for reference (recoverable history; not active config/code).

## LEAN config variants (archived 2026-05-30, #207 Step C)
**Canonical config = `lean.json` at repo root** (LEAN's default config name — what the `lean` CLI reads).

Archived variants carried NOTHING unique vs lean.json (verified by diff):
- `lean-api.json` — identical except `map-file-provider`/`factor-file-provider` written as short class names (`LocalDiskMapFileProvider`) vs fully-qualified (`QuantConnect.Data.Auxiliary.LocalDiskMapFileProvider`) — functionally the same provider — plus a stale `file-database-last-update` timestamp.
- `lean_disk.json` — identical except a stale `file-database-last-update` timestamp.

Both were timestamp/naming churn, not distinct configurations. No settings lost by archiving.
