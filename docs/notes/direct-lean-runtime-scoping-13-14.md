# #13/#14 — direct-LEAN sweep runtime: SCOPING (read-only, build on HOLD)

*2026-06-02. HQ-authorized scoping only. Build queued behind a viable candidate (same discipline as
#332): don't invest in sweep-throughput until there's a strategy worth sweeping at scale — right now
there isn't (champion #270 not viable as-configured, DV-rank dead, let-winners-run realized-edge not
locally gradable).*

## Current runtime (the Docker-LEAN baseline)

`sweeps/adapters/local_lean.py::_default_run_lean` shells `lean backtest <project_dir>` (lean CLI
1.0.225) with the Docker-host fix. The lean CLI **only backtests via Docker** — it spins the official
LEAN engine image in a container per cell (`lean backtest` help: "Backtest a project locally using
Docker"; there is **no `--no-docker` flag**, only `--image` to override the image). So "Docker-LEAN"
*is* the lean CLI; the (C) WarmupGate + per-(config,window) run_dir isolation sit on top of it.

## Why "direct-LEAN" is NOT a CLI flag

There is no lean-CLI path that skips Docker for a backtest. "Direct" therefore means **run the LEAN
.NET engine host-native** (`QuantConnect.Lean.Launcher`), bypassing the CLI's container wrapper.

## The throughput reality (the load-bearing finding)

**Warmup dominates per-cell wall-time; container-spin does not.** Measured: ~2 min/cell, of which the
560-day daily warmup (coarse-select + indicator/consolidator build over ~700-1000 names/day) is the
bulk; the Docker container spin is ~seconds. So removing the container (direct-LEAN) saves ~seconds/
cell against a ~2 min warmup → **marginal throughput gain.** This is the SAME warmup-bound conclusion
as the #332 spike. **Direct-LEAN's value is NOT speed** — it's (a) no Docker dependency, (b) parallelism
headroom (escapes the per-container 7.75 GiB memory cap that drove the OOM the WarmupGate works around),
(c) Falk's stated preference for LEAN-direct as the eventual runtime. The actual per-cell speed lever
remains #332 (kill the warmup), also deferred.

## Approach options

| Option | What | Feasibility (host) | Cost | Notes |
|---|---|---|---|---|
| **A. lean-CLI-direct** | a `--no-docker` backtest | **NOT POSSIBLE** | — | lean CLI backtest is Docker-only |
| **B. host-native LEAN** | build + run `QuantConnect.Lean.Launcher` via dotnet, no container | **feasible** — LEAN source present at `~/reference/Lean/Launcher/QuantConnect.Lean.Launcher.csproj`; **but `dotnet` is NOT installed** | ~1-2 days | reimplements the Python-algo wiring + config.json the CLI abstracts (the risky part) |
| **C. persistent-container reuse** | keep ONE warm LEAN container, feed it backtests (amortize spin) | feasible | ~half-day | still Docker; saves only the ~seconds spin → marginal (warmup-bound) |

**Lean: B is the design-correct target** (Falk's LEAN-direct), but it's the ~1-2 day one. A and C are
not worth it (A impossible; C saves only the marginal spin).

### Option B build outline (when unblocked)
1. Install dotnet SDK; build LEAN from `~/reference/Lean` (pin the version — see reconciliation).
2. New runtime adapter (a `LocalLeanRun` sibling, `run_lean` variant) that invokes
   `dotnet QuantConnect.Lean.Launcher.dll` with a generated `config.json` (algorithm-location → our
   dist `main.py` via LEAN's Python plugin/pythonnet, data-folder → the local backfill, RAW
   normalization) instead of `lean backtest`. Same RunConfig Protocol → drops into run_sweep unchanged.
3. The Python-algo wiring is the risk: the lean CLI hides pythonnet setup, the algorithm-language
   config, and the data-folder plumbing. Host-native must reproduce it exactly.

## Reconciliation gate (mandatory before trusting direct results)

Direct-LEAN must be **decision-neutral vs the Docker-LEAN baseline** (the CLAUDE.md cloud/local-parity
discipline, generalized): run a reference cell BOTH ways → assert **byte-identical** statistics trio +
order count + trade rows. **Pin the LEAN version on both sides** — the host build and the Docker image
must be the same LEAN commit, else subtle fill/indicator drift (the same vendor-residual class as the
cloud/local 83% reconciliation). If direct ≠ Docker on the reference cell, direct-LEAN is not adopted
until the divergence is root-caused. Wire it like the cap250 selection-match recon gate (#325).

## Rough build cost

~1-2 days for Option B: dotnet+LEAN build (~1h, low risk) + the runtime adapter (~half-day) + the
Python-algo/config wiring (~half-day, the real risk) + the reconciliation gate + tests (~few hours).

## Recommendation

**HOLD the build** (HQ, 2026-06-02): the throughput gain is marginal (warmup-bound), so direct-LEAN is
not justified until (a) there's a viable candidate worth sweeping at scale AND (b) parallelism headroom
or Docker-removal actually bottlenecks. Sequence: **strategy-viability first** (the #270 profit-take leg
→ a candidate) **then** sweep-throughput infra (direct-LEAN #13/#14 + warmup-cache #332 together — they
share the "only matters at scale" gate). When pulled: build Option B, gate on the reconciliation.
