from __future__ import annotations

from runtime.lean_entry import BctEngineAlgorithm


def _algo() -> BctEngineAlgorithm:
    algo = BctEngineAlgorithm()
    algo.logged: list[str] = []
    algo.log = lambda m: algo.logged.append(m)  # type: ignore[method-assign,assignment]
    algo._security_profiles = {}
    algo._industry_by_ticker = {}
    algo._sector_by_ticker = {}
    algo._proxy_by_ticker = {}
    algo._proxy_etfs_by_ticker = {}
    algo._george_attention_ticker = {}
    algo._george_attention_industry = {}
    algo._george_source_role_counts = {}
    return algo


def test_optional_george_context_loader_populates_runtime_maps(tmp_path) -> None:
    profiles = tmp_path / "profiles.csv"
    profiles.write_text(
        "ticker,sector,industry,subindustry,proxy_etf,proxy_etfs,source,confidence\n"
        "ATI,Materials,Specialty Metals,Steel,XME,XLB;XME;COPX,manual,0.9\n",
        encoding="utf-8",
    )
    attention = tmp_path / "attention.csv"
    attention.write_text(
        "ticker,industry,source_role,attention_score,confidence\n"
        "ATI,Specialty Metals,scanner_candidate,2.0,0.5\n",
        encoding="utf-8",
    )
    algo = _algo()
    algo.SECURITY_PROFILE_SOURCE = str(profiles)
    algo.GEORGE_ATTENTION_SOURCE = str(attention)

    algo._load_optional_george_context()

    assert algo._industry_by_ticker == {"ati": "specialty metals"}
    assert algo._sector_by_ticker == {"ati": "materials"}
    assert algo._proxy_by_ticker == {"ati": "xme"}
    assert algo._proxy_etfs_by_ticker == {"ati": ["xme", "xlb", "copx"]}
    assert algo._george_attention_ticker == {"ati": 1.0}
    assert algo._george_attention_industry == {"specialty metals": 1.0}
    assert algo._george_source_role_counts == {"scanner_candidate": 1}
    assert any(m.startswith("GEORGE_PROFILE_LOAD|") and "loaded=1" in m for m in algo.logged)
    assert any(m.startswith("GEORGE_ATTENTION_LOAD|") and "ticker=1" in m for m in algo.logged)


def test_optional_george_context_loader_fails_soft_on_missing_file(tmp_path) -> None:
    algo = _algo()
    algo.SECURITY_PROFILE_SOURCE = str(tmp_path / "missing_profiles.csv")
    algo.GEORGE_ATTENTION_SOURCE = str(tmp_path / "missing_attention.csv")

    algo._load_optional_george_context()

    assert algo._industry_by_ticker == {}
    assert algo._george_attention_ticker == {}
    assert any("GEORGE_PROFILE_LOAD|" in m and "loaded=0" in m for m in algo.logged)
    assert any("GEORGE_ATTENTION_LOAD|" in m and "loaded=0" in m for m in algo.logged)
