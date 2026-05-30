"""Unit tests for pyramid_engine (Phase 3b #172). Run: python pyramid_engine.test.py"""
from pyramid_engine import VARIANTS, add_dollars, should_add


def test_add_sizes():
    assert add_dollars("Pa", 1) == 250.0 and add_dollars("Pa", 2) == 125.0
    assert add_dollars("Pb", 1) == 200.0 and add_dollars("Pb", 2) == 200.0
    assert add_dollars("Pa", 3) == 0.0  # beyond scheme


def test_pa_price_thresholds():
    # lot1 add fires at +5%, lot2 add at +10% (clearly-above to avoid float boundary)
    assert should_add("Pa", 1, entry_price=100, close=105.5)
    assert not should_add("Pa", 1, entry_price=100, close=104.9)
    assert should_add("Pa", 2, entry_price=100, close=110.5)
    assert not should_add("Pa", 2, entry_price=100, close=109)
    assert not should_add("Pa", 3, entry_price=100, close=200)  # no 3rd add


def test_pb_wider():
    assert should_add("Pb", 1, entry_price=100, close=110.5)
    assert not should_add("Pb", 1, entry_price=100, close=109)
    assert should_add("Pb", 2, entry_price=100, close=120.5)


def test_pc_atr():
    assert should_add("Pc", 1, entry_price=100, close=105.5, entry_atr=5)
    assert not should_add("Pc", 1, entry_price=100, close=104, entry_atr=5)
    assert should_add("Pc", 2, entry_price=100, close=110.5, entry_atr=5)
    assert not should_add("Pc", 1, entry_price=100, close=999, entry_atr=None)  # safe


def test_pd_vol_confirmed():
    assert should_add("Pd", 1, entry_price=100, close=101, daily_tr=3.1, vol_20d_avg=2.0)
    assert not should_add("Pd", 1, entry_price=100, close=101, daily_tr=2.9, vol_20d_avg=2.0)
    assert not should_add("Pd", 1, entry_price=100, close=101, daily_tr=None, vol_20d_avg=2.0)


def test_pe_cross():
    assert should_add("Pe", 1, entry_price=100, close=101, tk_cross=True)
    assert not should_add("Pe", 1, entry_price=100, close=101, tk_cross=False)


def test_pe_rampup_trigger():
    # fires on tk_cross like Pe, not otherwise
    assert should_add("Pe-rampup", 1, entry_price=100, close=101, tk_cross=True)
    assert not should_add("Pe-rampup", 1, entry_price=100, close=101, tk_cross=False)
    # capped: bounded by ADD_SIZES length (3 adds -> idx 0,1,2)
    assert should_add("Pe-rampup", 3, entry_price=100, close=101, tk_cross=True)
    assert not should_add("Pe-rampup", 4, entry_price=100, close=101, tk_cross=True)


def test_pe_rampup_sizes():
    # anti-Kelly grow-with-evidence: lot2=idx0=200, then 400, 600
    assert add_dollars("Pe-rampup", 1) == 200.0
    assert add_dollars("Pe-rampup", 2) == 400.0
    assert add_dollars("Pe-rampup", 3) == 600.0
    assert add_dollars("Pe-rampup", 4) == 0.0  # capped beyond scheme


def test_pe_rampup_uncapped_grows():
    # uncapped: fires on every cross + keeps growing 200*(idx+1) unbounded
    assert should_add("Pe-rampup", 9, entry_price=100, close=101, tk_cross=True, uncapped=True)
    assert add_dollars("Pe-rampup", 1, uncapped=True) == 200.0
    assert add_dollars("Pe-rampup", 4, uncapped=True) == 800.0   # idx3 -> 200*4
    assert add_dollars("Pe-rampup", 10, uncapped=True) == 2000.0  # idx9 -> 200*10


def test_pe_conviction_trigger():
    assert should_add("Pe-conviction", 1, entry_price=100, close=101, tk_cross=True)
    assert not should_add("Pe-conviction", 1, entry_price=100, close=101, tk_cross=False)
    assert should_add("Pe-conviction", 3, entry_price=100, close=101, tk_cross=True)
    assert not should_add("Pe-conviction", 4, entry_price=100, close=101, tk_cross=True)


def test_pe_conviction_sizes():
    # decreasing 300, 200, 100
    assert add_dollars("Pe-conviction", 1) == 300.0
    assert add_dollars("Pe-conviction", 2) == 200.0
    assert add_dollars("Pe-conviction", 3) == 100.0
    assert add_dollars("Pe-conviction", 4) == 0.0  # capped beyond scheme


def test_pe_conviction_uncapped_floors():
    # uncapped: fires every cross + floors at 100 (never below, never 0)
    assert should_add("Pe-conviction", 9, entry_price=100, close=101, tk_cross=True, uncapped=True)
    assert add_dollars("Pe-conviction", 1, uncapped=True) == 300.0
    assert add_dollars("Pe-conviction", 3, uncapped=True) == 100.0
    assert add_dollars("Pe-conviction", 4, uncapped=True) == 100.0   # floor, not 0
    assert add_dollars("Pe-conviction", 20, uncapped=True) == 100.0  # still floored


def test_pe_winscale_trigger():
    assert should_add("Pe-winscale", 1, entry_price=100, close=101, tk_cross=True)
    assert not should_add("Pe-winscale", 1, entry_price=100, close=101, tk_cross=False)
    assert should_add("Pe-winscale", 3, entry_price=100, close=101, tk_cross=True)
    assert not should_add("Pe-winscale", 4, entry_price=100, close=101, tk_cross=True)


def test_pe_winscale_sizes():
    # gain-conditional vs entry, index-independent (clearly-above to dodge float boundary)
    assert add_dollars("Pe-winscale", 1, entry_price=100, close=104) == 300.0    # <+5% -> base
    assert add_dollars("Pe-winscale", 1, entry_price=100, close=105.5) == 500.0  # >=+5%
    assert add_dollars("Pe-winscale", 1, entry_price=100, close=110.5) == 600.0  # >=+10%
    assert add_dollars("Pe-winscale", 1, entry_price=100, close=109.99) == 500.0  # just under +10%
    # same regardless of add index
    assert add_dollars("Pe-winscale", 3, entry_price=100, close=110.5) == 600.0
    # missing price context -> fall back to base 300
    assert add_dollars("Pe-winscale", 1) == 300.0
    assert add_dollars("Pe-winscale", 1, entry_price=100, close=None) == 300.0
    assert add_dollars("Pe-winscale", 4) == 0.0  # capped beyond scheme


def test_pe_winscale_uncapped_gain_conditional():
    # uncapped: fires every cross + gain-conditional sizing at any index
    assert should_add("Pe-winscale", 9, entry_price=100, close=120, tk_cross=True, uncapped=True)
    assert add_dollars("Pe-winscale", 9, uncapped=True, entry_price=100, close=120) == 600.0
    assert add_dollars("Pe-winscale", 9, uncapped=True, entry_price=100, close=105.5) == 500.0
    assert add_dollars("Pe-winscale", 9, uncapped=True, entry_price=100, close=101) == 300.0


def test_all_variants_safe_at_max():
    # idx beyond scheme always False/0 — no crashes
    for v in VARIANTS:
        assert should_add(v, 5, entry_price=100, close=200, entry_atr=5,
                          daily_tr=10, vol_20d_avg=1, tk_cross=True) is False
        assert add_dollars(v, 5) == 0.0


if __name__ == "__main__":
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    for fn in fns:
        fn()
        print(f"  ok  {fn.__name__}")
    print(f"\n{len(fns)}/{len(fns)} passed")
