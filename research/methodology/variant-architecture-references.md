# Variant Architecture — External References

The prior-art survey backing the **Variant Strategy** decision (see [docs/ARCHITECTURE.md](../../docs/ARCHITECTURE.md) §9 and the enforceable subset in [CONVENTIONS.md](../../CONVENTIONS.md)). Folded from ADR-0001 §7 (the standalone ADR was dissolved into the living charter by #222).

**Inputs:** independent analysis from three sources (in-house research sweep over LEAN/backtrader/vectorbt/nautilus/zipline, Perplexity, Gemini-2.5-pro) — all three converged on the same boundary.

## How the mature engines structure interchangeable variants

The landscape we triangulated against:

| Framework | Composition unit | Variant mechanism | Param-space declaration | Catalog |
|---|---|---|---|---|
| **QuantConnect / LEAN** | 5 swappable framework modules (Universe/Alpha/Portfolio/Risk/Execution) | subclass + setter injection (`AddAlpha(EmaCrossAlphaModel())`) | `GetParameter()` reading `config.json` (strings, **separate from code → drift-prone**) | string/path config |
| **NautilusTrader** | `Strategy` + typed `StrategyConfig` (msgspec) | typed config-driven composition | typed config fields | path-string registry **only at serialization edge** |
| **backtrader** | `Strategy` subclass; distinct `Sizer`/commission **classes** (not flags) | subclass + `params` tuple | `optstrategy(S, p=range(...))` — co-located at call site | direct reference |
| **vectorbt** | vectorized `IndicatorFactory` | broadcasting; `vbt.Param([...])` makes any arg a swept axis | `vbt.Param` inline — value knows its own axis | direct reference |
| **zipline** | `Pipeline` of `Factor`/`Filter` terms | term composition + `CustomFactor` subclass | constructor args on terms | direct reference |

## Read

Our `Slot(impl, params=.Params)` over a typed-Protocol, direct-reference library is **Nautilus's typed-config discipline + LEAN's per-slot module swap, minus the stringly-typed weaknesses of both** — a coherent, defensible point in the design space. The community's consistent signals corroborate the boundary rule (D1): backtrader uses **distinct Sizer classes, not a `mode` flag**; everyone uses params for numeric thresholds and new classes for algorithmic differences.

## Citations

LEAN Algorithm Framework + Optimization/Parameters docs · NautilusTrader Strategies & StrategyConfig · backtrader `optstrategy` + Strategy source · vectorbt optimization + IndicatorFactory · zipline Pipeline · Martin Fowler "Flag Argument" · "curve fitting in trading" / "overfitting in algo trading" (QuantifiedStrategies, AlgoTrading101).
