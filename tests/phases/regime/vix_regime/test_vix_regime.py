"""VixRegime: blocks above threshold, passes below, configurable missing-data behavior."""
from datetime import datetime

from engine.context import PhaseContext
from phases.regime.vix_regime.vix_regime import VixRegime


class _QC:
    pass


def _eval(vix: float | None, missing_vix_blocks: bool = False):
    qc = _QC()
    if vix is not None:
        qc.vix_level = vix
    phase = VixRegime(VixRegime.Params(high_threshold=28.0, missing_vix_blocks=missing_vix_blocks), logger=None)
    return phase.evaluate(PhaseContext(qc=qc, time=datetime(2025, 1, 2), data=None))


def test_blocks_high_vix() -> None:
    assert _eval(31.0).blocked


def test_passes_low_vix() -> None:
    assert not _eval(18.0).blocked


def test_missing_vix_defaults_to_skip_for_architecture_proof() -> None:
    assert not _eval(None).blocked


def test_missing_vix_can_fail_closed_for_deployable_configs() -> None:
    assert _eval(None, missing_vix_blocks=True).blocked
