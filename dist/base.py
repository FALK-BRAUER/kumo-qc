from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol, runtime_checkable

from context import PhaseContext


class CharterViolation(Exception):
    """Raised at engine init when config violates a charter invariant."""


class UniverseLoadError(Exception):
    """Raised when the universe is empty/unresolved — fail loud, never trade-everything."""


class DegradedDataError(Exception):
    """Raised (#261) when the live engine path hits degraded / malformed / missing / not-ready
    data that would otherwise produce a SILENT-0 / wrong-set / cold-score MIRAGE.

    The anti-mirage contract (Falk's mandate): an outage/degraded state must CRASH loudly with
    diagnosable context (symbol / day / value), NEVER silently pass a 0, a wrong set, or a cold
    score (the empty-warmup mirage faked the −0.616 baseline because nothing crashed). Carries
    the offending context in its message — not a bare assert.

    Fires ONLY on broken-data scenarios (the guards are dormant on the valid happy path):
      - a non-finite / negative dollar-volume or price entering the selection gate (#261-1/2);
      - QC firing the coarse callback on a trading day with a missing/empty feed (#261-5);
      - a populated coarse feed collapsing to a ZERO selection — degraded data (#261-6);
      - an invested position with a cold daily-Ichimoku at stop-evaluation time (#261-8)."""


class UniverseFingerprintError(Exception):
    """Raised when a loaded universe artifact's recomputed fingerprint != the pinned value.
    The structural anti-#182 guard: same key but DIFFERENT bytes (cloud ObjectStore !=
    local) screams here instead of silently diverging. Do not run on mismatch."""


class DependencyError(Exception):
    """Raised at init when a phase's REQUIRES_UPSTREAM is unmet or mis-ordered."""


class ConfigError(Exception):
    """Raised at init when a required phase kind is missing/disabled."""


class DegradedConfigError(Exception):
    """Raised (#270/#272) at init when a CHAMPION config is structurally incomplete in a way that
    would let it trade a phantom/blind execution model — the fail-loud-phase-stack gate, the
    config-time analogue of DegradedDataError.

    The anti-mirage contract on the CONFIG (Falk's mandate, #270): there is NO implicit execution
    default. A config that would FIRE entries with no wired entry-confirm phase, or fire exits with
    no wired exit phase, must CRASH at init — never silently blind-fill the open (the daily-MOO
    champion_asis traded a phantom model through all of #262/#268 precisely because nothing forced
    'no entry-confirm wired' to crash). Carries which required execution phase is missing.

    A blind-open / placeholder-entry config is allowed ONLY as an explicitly-declared FIXTURE
    (`StrategyConfig.is_fixture=True`) for regression/parity scaffolding — never as a champion."""


class DegradedScheduleError(Exception):
    """Raised (#313) at runtime when the scheduled AFTER-CLOSE daily-decision event has silently
    STOPPED FIRING — the daily DECISION clock keeping pace with elapsed trading days is the
    load-bearing invariant of the two-clock model.

    The #313 watchdog: the daily decision fires on a scheduled `after_market_close` event (a
    brand-new mechanism). If that event silently does NOT fire (a LEAN/QC scheduling change, a
    cloud-vs-local divergence — the 276b-0 under-fire failure class), the system goes DARK: no
    candidates, no decisions, while trading days elapse — the exact fail-SILENT the charter says
    must CRASH, never mirage. This guard counts post-warmup trading days (the universe coarse
    callback, which fires reliably daily) vs daily decisions; if they diverge beyond the 1-day
    pending tolerance, it RAISES rather than run blind. Cloud-proven once + enforced forever."""


@dataclass(slots=True)
class PhaseResult:
    decision: Any
    blocked: bool
    reason: str
    facts: dict[str, Any]
    metrics: dict[str, Any]


@runtime_checkable
class PhaseInterface(Protocol):

    # Class-level metadata (declared on each phase class).
    PHASE_KIND: str
    PHASE_RESOLUTION: str  # #270/#274: "daily" (decision clock) | "intraday" (execution clock)
    REQUIRES_UPSTREAM: list[str]
    PROVIDES_DOWNSTREAM: list[str]

    @property
    def enabled(self) -> bool: ...

    @property
    def version_marker(self) -> str: ...

    def evaluate(self, ctx: PhaseContext) -> PhaseResult: ...


class BasePhase:

    PHASE_KIND: str = ""
    # #270/#274 two-clock: default "daily" (the decision clock). A phase that must run on the
    # intraday execution clock (entry-confirm / exit / stops) overrides this to "intraday".
    # Default-daily keeps every existing phase on the daily clock → behaviour unchanged until a
    # phase opts into intraday.
    PHASE_RESOLUTION: str = "daily"
    REQUIRES_UPSTREAM: list[str] = []
    PROVIDES_DOWNSTREAM: list[str] = []

    def __init__(self, params: Any, logger: Any) -> None:
        self._params = params
        self._logger = logger

    @property
    def enabled(self) -> bool:
        return bool(getattr(self._params, "enabled", True))

    @property
    def version_marker(self) -> str:
        raise NotImplementedError

    def evaluate(self, ctx: PhaseContext) -> PhaseResult:
        raise NotImplementedError
