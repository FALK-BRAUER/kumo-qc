from __future__ import annotations

from runtime.security_profiles import load_security_profile_maps, read_security_profiles


def test_security_profiles_load_maps_with_defaults(tmp_path) -> None:
    path = tmp_path / "profiles.csv"
    path.write_text(
        "ticker,sector,industry,subindustry,proxy_etf,source,confidence\n"
        "ATI,Materials,Specialty Metals,Steel,XME,manual,0.8\n"
        "BTCM,,,,,unknown,bad\n",
        encoding="utf-8",
    )

    profiles = read_security_profiles(path)
    maps = load_security_profile_maps(path)

    assert [p.ticker for p in profiles] == ["ati", "btcm"]
    assert maps["industry_by_ticker"]["ati"] == "specialty metals"
    assert maps["sector_by_ticker"]["ati"] == "materials"
    assert maps["proxy_by_ticker"]["ati"] == "xme"
    assert maps["security_profiles"]["btcm"]["industry"] == "unknown"
    assert maps["security_profiles"]["btcm"]["confidence"] == 0.0
