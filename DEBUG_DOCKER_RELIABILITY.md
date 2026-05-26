# Docker Reliability Issue — 2026-05-26

## Symptoms
- `lean backtest` commands execute but return 0% results with truncated logs (stops at ~2025-02-23)
- No error messages in logs — silent container crashes
- First BT in a session often works, subsequent BTs fail or return degraded results
- Container cleanup (`docker rm -f`) between runs helps but doesn't fully resolve

## Workaround
- Run `docker ps -a | grep lean | awk '{print $1}' | xargs docker rm -f` before EVERY BT
- Use fresh containers for each BT (don't reuse)
- If first BT after cleanup works, stop — don't attempt second BT in same session

## Impact
- BT results from this worker need verification by another BT-capable worker
- Code implementations (e82, e18) are valid and pushed to origin
- Another worker should verify with their own BT run before accepting results

## Resolution
- This worker moved to CODE-PRIMARY role
- Implementations written here, BT verification done by other workers
