"""#archive ① — the emit↔parse CONTRACT for the entry-order tag (the single-source guarantee).

The entry tag is the one durable learn-substrate channel. lean_entry._build_entry_tag EMITS it
(cloud), sweeps.archive.snapshot PARSES it (local). If they desync, the parser silently returns
all-None → the entire learn-substrate is null, silently. These tests are the contract: encode →
parse round-trips every field + type, and BOTH production sites go through this module.
"""
from __future__ import annotations

from runtime.tag_schema import (
    COND_BITS,
    TAG_KEYS,
    encode_entry_tag,
    expand_cond,
    has_core,
    parse_entry_tag,
)


def test_round_trip_full_context_survives_value_and_type() -> None:
    bits = [True, True, False, True, True, True, False, True]  # 6/8
    tag = encode_entry_tag(score=7, conditions=bits, gap=0.0340, vol=1.612, tdist=0.0081, rank=12)
    p = parse_entry_tag(tag)
    assert p["decision_score"] == 7 and isinstance(p["decision_score"], int)
    assert p["decision_cond"] == "11011101"
    assert p["decision_gap"] == 0.0340 and isinstance(p["decision_gap"], float)
    assert p["decision_vol"] == 1.612
    assert p["decision_tdist"] == 0.0081
    assert p["decision_rank"] == 12 and isinstance(p["decision_rank"], int)
    # cond expands to the 8 bools in the SAME order it was encoded
    assert expand_cond(p["decision_cond"]) == {f"cond_{i}": bits[i] for i in range(COND_BITS)}
    assert has_core(p) is True


def test_round_trip_omits_none_never_fakes() -> None:
    # only score + conditions resolvable → the rest absent (None), not 0/garbage.
    tag = encode_entry_tag(score=8, conditions=[True] * 8, gap=None, vol=None, tdist=None, rank=None)
    p = parse_entry_tag(tag)
    assert p["decision_score"] == 8 and p["decision_cond"] == "11111111"
    assert p["decision_gap"] is None and p["decision_vol"] is None
    assert p["decision_tdist"] is None and p["decision_rank"] is None
    assert has_core(p) is True  # core present even with optional fields absent


def test_empty_and_no_core() -> None:
    p = parse_entry_tag(encode_entry_tag())  # nothing resolvable
    assert all(p[k] is None for k in TAG_KEYS)
    assert has_core(p) is False  # → CORE_MISSING
    assert expand_cond(None) == {f"cond_{i}": None for i in range(COND_BITS)}


def test_malformed_cond_treated_absent_not_banked() -> None:
    # a wrong-length / non-binary cond must NOT be banked as garbage — parsed as absent.
    assert parse_entry_tag("decision_cond=11x1")["decision_cond"] is None
    assert parse_entry_tag(f"decision_cond={'1' * (COND_BITS + 1)}")["decision_cond"] is None


def test_uncastable_numeric_is_absent_not_garbage() -> None:
    p = parse_entry_tag("decision_score=abc&decision_gap=NaN&decision_rank=1.5")
    assert p["decision_score"] is None  # non-int
    assert p["decision_gap"] is None    # NaN is not finite → absent
    assert p["decision_rank"] is None   # non-int


def test_both_production_sites_use_this_module() -> None:
    # the desync guard AS A TEST: both the emitter and the parser import THIS module's funcs, so a
    # key rename here moves both. Assert the import wiring (a regression if either re-implements).
    import runtime.lean_entry as le
    import sweeps.archive.snapshot as snap
    assert le.encode_entry_tag is encode_entry_tag
    # snapshot delegates _parse_entry_tag/_expand_cond to the shared funcs
    assert snap.parse_entry_tag is parse_entry_tag and snap.expand_cond is expand_cond
