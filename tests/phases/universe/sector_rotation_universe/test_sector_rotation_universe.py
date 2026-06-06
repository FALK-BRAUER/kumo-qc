"""SectorRotationUniverse: keeps names in top-ranked sectors, fail-opens when sector data is absent."""
from datetime import datetime

from engine.context import PhaseContext
from phases.universe.sector_rotation_universe.sector_rotation_universe import SectorRotationUniverse


class _Sym:
    def __init__(self, value: str) -> None:
        self.value = value

    def __hash__(self) -> int:
        return hash(self.value)

    def __eq__(self, other: object) -> bool:
        return isinstance(other, _Sym) and other.value == self.value


class _QC:
    def __init__(self, names: list[str]) -> None:
        self._active = {_Sym(n) for n in names}


def _run(qc: _QC, top_sectors: int = 2) -> list[str]:
    phase = SectorRotationUniverse(SectorRotationUniverse.Params(top_sectors=top_sectors), logger=None)
    ctx = PhaseContext(qc=qc, time=datetime(2025, 1, 2), data=None)
    phase.evaluate(ctx)
    return ctx.bar_state.ranked_candidates


def test_keeps_active_names_in_top_sectors() -> None:
    qc = _QC(["AAA", "BBB", "CCC"])
    qc._sector = {"AAA": "Tech", "BBB": "Energy", "CCC": "Banks"}
    qc._sector_rs = {"Tech": 0.9, "Energy": 0.2, "Banks": 0.8}
    assert _run(qc, top_sectors=2) == ["AAA", "CCC"]


def test_missing_sector_data_keeps_all_active() -> None:
    assert _run(_QC(["BBB", "AAA"]), top_sectors=1) == ["AAA", "BBB"]
