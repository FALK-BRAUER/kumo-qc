"""#368 fail-loud guard — weekly_miss_action (in-window throw vs legit skip vs canonical value)."""
from __future__ import annotations

from runtime.warmup_weekly_cache import weekly_miss_action


def test_in_window_trimmed_throws() -> None:
    # computable (ready) + armed + trimmed (320<560) + TRADED on asof → THROW (real cache gap)
    assert weekly_miss_action(rederive_ready=True, armed=True, warmup_days=320, weekly_floor=560) == "throw"
    assert weekly_miss_action(rederive_ready=True, armed=True, warmup_days=320, weekly_floor=560,
                              traded_on_asof=True) == "throw"


def test_sparse_always_value_never_throw() -> None:
    # #370 (2')-(i): a SPARSE name (raw-zip cache can't match ff-dense) → 'value' (always re-derive,
    # routed around the cache), NEVER throw — even ready+armed+trimmed+traded (the dense throw condition).
    assert weekly_miss_action(rederive_ready=True, armed=True, warmup_days=320, weekly_floor=560,
                              traded_on_asof=True, is_sparse=True) == "value"


def test_delisted_not_traded_on_asof_returns_value() -> None:
    # #370: ready + armed + trimmed BUT the symbol did NOT trade on asof (last bar < asof — delisted/
    # halted, a universe-lag query like HCP@2025-02-27) → 'value' (carry-forward, == full-warmup), NOT
    # throw. The cache legitimately has no asof key (no bar); this is not a build gap.
    assert weekly_miss_action(rederive_ready=True, armed=True, warmup_days=320, weekly_floor=560,
                              traded_on_asof=False) == "value"


def test_legit_uncomputable_skips() -> None:
    # NOT ready (pre-78wk-from-listing / post-delisting / sparse) → SKIP, never throw — even armed+trimmed
    assert weekly_miss_action(rederive_ready=False, armed=True, warmup_days=320, weekly_floor=560) == "skip"
    assert weekly_miss_action(rederive_ready=False, armed=True, warmup_days=560, weekly_floor=560) == "skip"


def test_untrimmed_or_unarmed_returns_value() -> None:
    # full warmup (not trimmed) → canonical re-derive value, NO throw
    assert weekly_miss_action(rederive_ready=True, armed=True, warmup_days=560, weekly_floor=560) == "value"
    # unarmed (no cache, the 560-baseline path) → value, never throws
    assert weekly_miss_action(rederive_ready=True, armed=False, warmup_days=320, weekly_floor=560) == "value"
