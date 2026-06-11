from __future__ import annotations

from strategies.bct_opportunity_ranker_scanner import CONFIG, DEFAULT_OPPORTUNITY_RANKER_OBJECTSTORE_KEY, LEAN_ENTRY


def test_opportunity_ranker_strategy_wires_model_key_and_top20() -> None:
    assert CONFIG.name == "bct-opportunity-ranker-scanner"
    assert CONFIG.runtime.scanner_ranker_enabled is True
    assert CONFIG.runtime.scanner_ranker_top_x == 20
    assert CONFIG.runtime.scanner_ranker_model_path == DEFAULT_OPPORTUNITY_RANKER_OBJECTSTORE_KEY

    ranking = CONFIG.phases["ranking"]
    assert not isinstance(ranking, list)
    assert ranking.impl.__name__ == "LambdamartScannerRanker"


def test_opportunity_ranker_strategy_is_deployable() -> None:
    assert LEAN_ENTRY is True
