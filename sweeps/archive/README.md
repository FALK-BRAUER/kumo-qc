# sweeps/archive/

The durable results-archive snapshotter (#276b, `docs/notes/results-archive-design.md`). The ONE
channel that survives the cloud BT purge — without it every run's trades + decision context evaporate.

- `snapshot.py` — `persist_run(...)`: writes `results/archive/<config_hash>/<backtest_id>/` with
  `result.json` (full config + provenance + ALL QC statistics + 3-state status) and
  `trades.jsonl.gz` (one closed trade per line, decision context parsed from the entry-order TAG).
  FAIL-LOUD: raises on fetch error, schema-drift, bad status, or empty-trades-when-orders>0. The
  `/orders/read` fetch and the write-destination are INJECTED (tests mock them — ZERO real QC/LEAN).

Goes here: the snapshot writer + its schemas. Does NOT go here: the `/orders/read` prod wiring (lives
in `adapters/qc_cloud_prod.py` / the local adapter — they inject the fetch), or any engine import
(the config is passed pre-serialized to keep this module phase-agnostic).
