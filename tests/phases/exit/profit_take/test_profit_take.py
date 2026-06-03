"""#364 R2 ProfitTake — partial_trim / tenkan_ratchet / scale_out_ladder. Partial-exit + per-position
state in _position_meta['pt']. Constructor (Params, logger)."""
from datetime import datetime

from engine.context import PhaseContext
from phases.exit.profit_take.profit_take import ProfitTake


class _Sym:
    def __init__(self, v): self.value = v
    def __hash__(self): return hash(self.value)
    def __eq__(self, o): return isinstance(o, _Sym) and o.value == self.value


class _Ichi:
    def __init__(self, tenkan, kijun):
        self.is_ready = True
        self.tenkan = type("V", (), {"current": type("C", (), {"value": tenkan})()})()
        self.kijun = type("V", (), {"current": type("C", (), {"value": kijun})()})()


class _Holding:
    def __init__(self, qty=99): self.invested = True; self.quantity = qty


class _Sec:
    def __init__(self, close): self.close = close


class _PF(dict):
    def items(self): return dict.items(self)


class _QC:
    def __init__(self, holdings, meta, ind, sec):
        self.portfolio = _PF(holdings)
        self._position_meta = meta
        self._indicators = ind
        self.securities = sec
        self.logged = []
    def log(self, m): self.logged.append(m)


def _run(qc, params):
    ctx = PhaseContext(qc=qc, time=datetime(2025, 6, 16), data=None)
    res = ProfitTake(params, logger=None).evaluate(ctx)
    return res, ctx.bar_state.exit_intents


def _qc(close, entry, tenkan, kijun, qty=99, pt=None):
    s = _Sym("X")
    meta = {s: {"entry_price": entry}}
    if pt is not None:
        meta[s]["pt"] = pt
    return _QC({s: _Holding(qty)}, meta, {s: {"d_ichi": _Ichi(tenkan, kijun)}}, {s: _Sec(close)})


# ---- partial_trim ----
def test_partial_trim_sells_half_at_threshold_once():
    qc = _qc(close=120.0, entry=100.0, tenkan=110.0, kijun=105.0)  # +20% gain
    res, intents = _run(qc, ProfitTake.Params(mode="partial_trim", trim_at_gain=0.20, trim_frac=0.5))
    assert res.facts["trims"] == 1
    assert intents[0].qty == -49 and intents[0].ticker == "X"  # int(99*0.5)
    assert qc._position_meta[_Sym("X")]["pt"]["trimmed"] is True
    # already trimmed + still above kijun → no further trim
    res2, intents2 = _run(qc, ProfitTake.Params(mode="partial_trim"))
    assert res2.facts["trims"] == 0


def test_partial_trim_below_threshold_no_trim():
    qc = _qc(close=110.0, entry=100.0, tenkan=115.0, kijun=108.0)  # +10% < 20%
    res, intents = _run(qc, ProfitTake.Params(mode="partial_trim", trim_at_gain=0.20))
    assert res.facts["trims"] == 0 and intents == []


def test_partial_trim_exits_rest_below_kijun_after_trimmed():
    qc = _qc(close=104.0, entry=100.0, tenkan=112.0, kijun=106.0, pt={"trimmed": True})  # below kijun 106
    res, intents = _run(qc, ProfitTake.Params(mode="partial_trim"))
    assert res.facts["trims"] == 1 and intents[0].qty == -99  # full exit of the rest


# ---- tenkan_ratchet ----
def test_tenkan_ratchet_holds_above_stop():
    qc = _qc(close=120.0, entry=100.0, tenkan=110.0, kijun=105.0)  # close>=tenkan → crossed, stop=kijun105
    res, intents = _run(qc, ProfitTake.Params(mode="tenkan_ratchet"))
    assert res.facts["trims"] == 0  # close 120 > stop 105 → hold
    assert qc._position_meta[_Sym("X")]["pt"]["crossed"] is True


def test_tenkan_ratchet_exits_below_ratcheted_stop():
    # pre-set a ratcheted stop at 115 (from a prior higher Kijun); close 112 < 115 → full exit, never lowered
    qc = _qc(close=112.0, entry=100.0, tenkan=118.0, kijun=108.0, pt={"crossed": True, "stop": 115.0})
    res, intents = _run(qc, ProfitTake.Params(mode="tenkan_ratchet"))
    assert res.facts["trims"] == 1 and intents[0].qty == -99
    # stop never lowered (kijun 108 < prior 115 → stays 115)
    assert qc._position_meta[_Sym("X")]["pt"]["stop"] == 115.0


# ---- scale_out_ladder ----
def test_scale_out_ladder_rung1():
    qc = _qc(close=120.0, entry=100.0, tenkan=110.0, kijun=105.0)  # +20% → rung1
    res, intents = _run(qc, ProfitTake.Params(mode="scale_out_ladder", ladder1=0.20, ladder2=0.40))
    assert res.facts["trims"] == 1 and intents[0].qty == -33  # 99//3
    assert 1 in qc._position_meta[_Sym("X")]["pt"]["rungs"]


def test_scale_out_ladder_rung2_after_rung1():
    qc = _qc(close=140.0, entry=100.0, tenkan=120.0, kijun=110.0, pt={"rungs": [1]})  # +40% → rung2
    res, intents = _run(qc, ProfitTake.Params(mode="scale_out_ladder", ladder1=0.20, ladder2=0.40))
    assert res.facts["trims"] == 1 and intents[0].qty == -33
    assert 2 in qc._position_meta[_Sym("X")]["pt"]["rungs"]


def test_scale_out_ladder_final_below_kijun():
    qc = _qc(close=108.0, entry=100.0, tenkan=115.0, kijun=110.0, pt={"rungs": [1, 2]})  # below kijun
    res, intents = _run(qc, ProfitTake.Params(mode="scale_out_ladder"))
    assert res.facts["trims"] == 1 and intents[0].qty == -99  # final rest, full exit


def test_not_invested_or_no_entry_skipped():
    s = _Sym("X")
    qc = _QC({s: _Holding(99)}, {s: {}}, {s: {"d_ichi": _Ichi(110, 105)}}, {s: _Sec(120)})  # no entry_price
    res, intents = _run(qc, ProfitTake.Params(mode="partial_trim"))
    assert res.facts["trims"] == 0 and intents == []
