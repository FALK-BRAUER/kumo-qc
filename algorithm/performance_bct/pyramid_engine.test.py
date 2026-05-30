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
