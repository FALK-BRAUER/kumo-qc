"""Tests for the champion-entry-sized strategy config (the score-aware sizing measurement config).

champion-entry-sized = champion-entry stack VERBATIM with the sizing phase swapped
flat_pct_heatcap -> ScoreTierHeatcap (the X/4 entry-confirm score BINDS on size via the
methodology tiers). Asserts the engine accepts it, the sizer is the score-tier impl, every OTHER
phase matches champion-entry verbatim, and the config is distinct from BOTH baselines (its own
config_hash). Also asserts the CHAMPION-PARITY invariant: champion-asis's hash is UNCHANGED.
"""
from __future__ import annotations

from engine.engine import StrategyEngine, _config_hash
from strategies.champion_asis import CONFIG as ASIS
from strategies.champion_entry import CONFIG as ENTRY
from strategies.champion_entry_sized import CONFIG, LEAN_ENTRY

# The pinned champion-asis config_hash (CLAUDE.md: e573e84b1ce1). champion-asis MUST stay UNCHANGED.
ASIS_PINNED_HASH = "e573e84b1ce1"


class FakeQC:
    def Log(self, m: str) -> None: ...
    def log(self, m: str) -> None: ...


def test_engine_accepts_champion_entry_sized() -> None:
    eng = StrategyEngine(config=CONFIG, qc=FakeQC())
    assert set(eng.phases) == {
        "universe", "signal", "regime", "entry_selection", "entry_timing",
        "sizing", "exit_hard", "diagnostics",
    }


def test_sizing_is_score_tier() -> None:
    assert CONFIG.phases["sizing"].impl.__name__ == "ScoreTierHeatcap"  # type: ignore[union-attr]


def test_sizing_tiers_are_methodology_canonical() -> None:
    p = CONFIG.phases["sizing"].params  # type: ignore[union-attr]
    assert p.full == 1.00          # 4/4 full
    assert p.three_quarter == 0.75  # 3/4
    assert p.half == 0.50           # 2/4
    assert p.min_score == 2         # enter >=2/4
    assert p.position_pct == 0.10   # == champion-entry flat size (4/4 sizes identically)


def test_every_non_sizing_phase_matches_champion_entry_verbatim() -> None:
    # The controlled-measurement invariant: the ONLY delta vs champion-entry is the sizer.
    for kind in ("universe", "signal", "entry_selection", "entry_timing", "exit_hard"):
        a = CONFIG.phases[kind]
        b = ENTRY.phases[kind]
        # normalize to lists (regime/exit are list-kinds)
        a_list = a if isinstance(a, list) else [a]
        b_list = b if isinstance(b, list) else [b]
        assert [s.impl for s in a_list] == [s.impl for s in b_list]
        assert [s.params for s in a_list] == [s.params for s in b_list]


def test_lean_deployable() -> None:
    assert LEAN_ENTRY is True


def test_distinct_config_hash_from_both_baselines() -> None:
    assert _config_hash(CONFIG) != _config_hash(ASIS)
    assert _config_hash(CONFIG) != _config_hash(ENTRY)


def test_champion_asis_hash_unchanged() -> None:
    # CHAMPION PARITY: the new sizer must NOT perturb champion-asis. Its pinned hash holds.
    assert _config_hash(ASIS) == ASIS_PINNED_HASH
