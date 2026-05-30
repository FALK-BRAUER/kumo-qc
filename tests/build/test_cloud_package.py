"""Unit tests for the AST closure build — the single point of failure (#211)."""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

import cloud_package as cp

SAMPLE = "strategies._build_sample"
CHAMPION = "strategies.champion_asis"


@pytest.fixture
def built(tmp_path: Path) -> tuple[cp.BuildResult, Path]:
    dist = tmp_path / "dist"
    result = cp.build(SAMPLE, dist_dir=dist)
    return result, dist


def test_dist_is_flat_no_subdirs(built: tuple[cp.BuildResult, Path]) -> None:
    _, dist = built
    assert not any(p.is_dir() for p in dist.iterdir())


def test_engine_core_present(built: tuple[cp.BuildResult, Path]) -> None:
    _, dist = built
    for m in ("base.py", "config.py", "context.py", "engine.py", "logger.py"):
        assert (dist / m).is_file()


def test_enabled_phase_flattened(built: tuple[cp.BuildResult, Path]) -> None:
    _, dist = built
    assert (dist / "phase_signal_sample_bct.py").is_file()


def test_disabled_phase_excluded(built: tuple[cp.BuildResult, Path]) -> None:
    _, dist = built
    assert not list(dist.glob("*sample_off*"))  # disabled regime must NOT leak into dist


def test_transitive_shared_included(built: tuple[cp.BuildResult, Path]) -> None:
    _, dist = built
    assert (dist / "shared_sample_helper.py").is_file()  # phase imports it -> pulled


def test_imports_rewritten_no_pkg_prefix(built: tuple[cp.BuildResult, Path]) -> None:
    _, dist = built
    for f in dist.glob("*.py"):
        txt = f.read_text()
        assert "from engine." not in txt, f
        assert "from phases." not in txt, f


def test_manifest_fields(built: tuple[cp.BuildResult, Path]) -> None:
    result, dist = built
    m = json.loads((dist / "_manifest.json").read_text())
    # Assert CONSISTENCY (manifest == build result), not a hardcoded literal.
    # Substrate fingerprint may be "unknown" until #220 defines the substrate
    # (NO fixed-universe fingerprint — the 326 manifest was removed, #219).
    assert m["data_fingerprint"] == result.data_fingerprint
    assert m["build_script_version"] == cp.BUILD_SCRIPT_VERSION
    assert "phase_signal_sample_bct.py" in m["files"]
    assert m["phase_markers"]["signal"] == "sample_bct_v1"


def test_metadata_emitted(built: tuple[cp.BuildResult, Path]) -> None:
    result, dist = built
    meta = (dist / "_metadata.py").read_text()
    # metadata fingerprint == build result (consistency), not a hardcoded literal
    assert f"DATA_FINGERPRINT = {result.data_fingerprint!r}" in meta
    assert "CONFIG_HASH" in meta and "GIT_COMMIT" in meta


def test_flat_dist_importable(built: tuple[cp.BuildResult, Path]) -> None:
    _, dist = built
    # import dist/main.py in an isolated interpreter with ONLY dist on path -> proves flatness
    out = subprocess.run(
        [sys.executable, "-c",
         "import main; print(main.STRATEGY_CONFIG.name, list(main.STRATEGY_CONFIG.phases))"],
        cwd=str(dist), capture_output=True, text=True,
    )
    assert out.returncode == 0, out.stderr
    assert "_build_sample" in out.stdout
    assert "signal" in out.stdout and "regime" not in out.stdout  # only enabled wired


def test_list_valued_kind_roundtrips_no_duplicate_dict_key(tmp_path: Path) -> None:
    # REGRESSION: a multi-slot kind (regime = [SpySma200, VixPercentile]) must be emitted
    # as a LIST literal in dist/main.py. The old codegen wrote one `'regime':` dict line
    # per slot → the second silently overwrote the first → a phase vanished from dist while
    # present in src. Build the real champion (its regime has 2 slots) and prove both survive.
    dist = tmp_path / "dist"
    cp.build(CHAMPION, dist_dir=dist)
    main_txt = (dist / "main.py").read_text()
    assert main_txt.count("'regime':") == 1, "duplicate 'regime' dict key — list kind not grouped"
    out = subprocess.run(
        [sys.executable, "-c",
         "import main; r=main.STRATEGY_CONFIG.phases['regime']; "
         "print(isinstance(r, list), len(r) if isinstance(r, list) else 1, "
         "[s.impl.__name__ for s in (r if isinstance(r, list) else [r])])"],
        cwd=str(dist), capture_output=True, text=True,
    )
    assert out.returncode == 0, out.stderr
    # both regime phases present in the rebuilt dist config, in order
    assert "True 2 ['SpySma200', 'VixPercentile']" in out.stdout, out.stdout


def test_universe_spec_strategy_emits_lean_entry(tmp_path: Path) -> None:
    # #213: a strategy binding a UNIVERSE_SPEC gets the LEAN entry — lean_entry.py +
    # runtime fingerprints flattened into dist, and a BCTAlgorithm subclass in main.py
    # carrying the spec (ObjectStore keys + pinned fps).
    dist = tmp_path / "dist"
    cp.build(CHAMPION, dist_dir=dist)
    assert (dist / "lean_entry.py").is_file()
    assert (dist / "fingerprints.py").is_file()  # pulled transitively by lean_entry
    main_txt = (dist / "main.py").read_text()
    assert "class BCTAlgorithm(BctEngineAlgorithm):" in main_txt
    assert "membership_fp" in main_txt and "order_fp" in main_txt
    # flat dist imports in isolation (QCAlgorithm falls back to object without AlgorithmImports)
    out = subprocess.run(
        [sys.executable, "-c",
         "import main; print(main.BCTAlgorithm.UNIVERSE_SPEC['eligible_key'])"],
        cwd=str(dist), capture_output=True, text=True,
    )
    assert out.returncode == 0, out.stderr
    assert "filter.json" in out.stdout


def test_no_spec_strategy_is_config_only(tmp_path: Path) -> None:
    # The sample strategy declares NO UNIVERSE_SPEC -> config-only main.py, no LEAN entry.
    dist = tmp_path / "dist"
    cp.build(SAMPLE, dist_dir=dist)
    main_txt = (dist / "main.py").read_text()
    assert "BctEngineAlgorithm" not in main_txt
    assert not (dist / "lean_entry.py").is_file()


def test_universe_spec_validation_rejects_incomplete() -> None:
    # A malformed UNIVERSE_SPEC must fail at BUILD time (fail-fast), not as a QC-runtime
    # KeyError post-deploy. Inject a fake strategy module with an incomplete spec.
    import types
    m = types.ModuleType("strategies._fake_bad_spec")
    m.UNIVERSE_SPEC = {"eligible_key": "x"}  # missing universe_key/membership_fp/order_fp
    sys.modules["strategies._fake_bad_spec"] = m
    try:
        with pytest.raises(ValueError, match="missing"):
            cp._load_universe_spec("strategies._fake_bad_spec")
    finally:
        del sys.modules["strategies._fake_bad_spec"]


def test_flat_name_unit() -> None:
    src = cp._src_root()
    assert cp._flat_name(src / "engine" / "base.py", src) == "base.py"
    assert cp._flat_name(src / "phases" / "signal" / "sample_bct" / "sample_bct.py", src) == "phase_signal_sample_bct.py"
    assert cp._flat_name(src / "phases" / "shared" / "sample_helper.py", src) == "shared_sample_helper.py"


def test_rewrite_imports_unit() -> None:
    assert cp._rewrite_imports("from engine.base import X") == "from base import X"
    assert cp._rewrite_imports("from phases.signal.sample_bct.sample_bct import S") == "from phase_signal_sample_bct import S"
    assert cp._rewrite_imports("from phases.shared.h import f") == "from shared_h import f"


def test_module_to_file_unit() -> None:
    src = cp._src_root()
    assert cp._module_to_file("engine.base", src) == src / "engine" / "base.py"
    assert cp._module_to_file("os", src) is None  # stdlib not resolved


def test_config_hash_deterministic(built: tuple[cp.BuildResult, Path]) -> None:
    r1, _ = built
    cfg = cp._load_config(SAMPLE)
    assert cp._config_hash(cfg) == r1.config_hash  # stable
