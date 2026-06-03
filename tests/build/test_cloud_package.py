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


def test_is_fixture_carried_into_dist_main(tmp_path: Path) -> None:
    # #272 REGRESSION: champion_asis is a FIXTURE (is_fixture=True). The codegen MUST emit that
    # flag into dist/main.py — else the deployed config loses it and CRASHES the fail-loud
    # entry+exit gate at cloud init (DegradedConfigError). Build the champion fixture, prove the
    # flag survives the round-trip into the importable dist config.
    dist = tmp_path / "dist"
    cp.build(CHAMPION, dist_dir=dist)
    main_txt = (dist / "main.py").read_text()
    assert "is_fixture=True" in main_txt, "is_fixture flag dropped from dist/main.py codegen"
    out = subprocess.run(
        [sys.executable, "-c", "import main; print(main.STRATEGY_CONFIG.is_fixture)"],
        cwd=str(dist), capture_output=True, text=True,
    )
    assert out.returncode == 0, out.stderr
    assert out.stdout.strip() == "True", out.stdout


def test_non_fixture_omits_is_fixture_line(tmp_path: Path) -> None:
    # MUTATION-BITE control: a NON-fixture config must NOT emit the line, so the flag isn't
    # spuriously stamped on real champions. champion_entry wires entry+exit → is_fixture=False →
    # the codegen must omit the line (the conditional emit, proven by its absence here).
    dist = tmp_path / "dist"
    cp.build("strategies.champion_entry", dist_dir=dist)
    main_txt = (dist / "main.py").read_text()
    assert "is_fixture" not in main_txt, "is_fixture line emitted for a non-fixture champion"


def test_codegen_field_completeness_guard(tmp_path: Path) -> None:
    # #272: the codegen FAILS LOUD if StrategyConfig gains a field _emit_main doesn't handle
    # (the bug class that dropped is_fixture). Simulate a config carrying an unknown field and
    # assert the build raises rather than silently emitting an incomplete dist config.
    import dataclasses
    from engine.config import StrategyConfig

    @dataclasses.dataclass(slots=True)
    class _ExtendedConfig(StrategyConfig):
        new_field: str = "x"  # a field the emitter doesn't know about

    cfg = _ExtendedConfig(name="_x", version="0.0.0", phases={})
    with pytest.raises(ValueError, match="out of sync with StrategyConfig"):
        cp._emit_main(cfg, [], tmp_path / "d", Path("src"))


def test_deployable_strategy_emits_lean_entry(tmp_path: Path) -> None:
    # #238: a LEAN-deployable strategy (LEAN_ENTRY=True) gets the LEAN entry — lean_entry.py
    # + runtime.universe_select (the live filter→rank→cap) flattened into dist, and a
    # BCTAlgorithm subclass in main.py. NO UNIVERSE_SPEC, NO fingerprints.py (the retired
    # stored-universe-file mechanism — the universe is computed LIVE).
    dist = tmp_path / "dist"
    cp.build(CHAMPION, dist_dir=dist)
    assert (dist / "lean_entry.py").is_file()
    assert (dist / "universe_select.py").is_file()  # pulled transitively by lean_entry
    assert not (dist / "fingerprints.py").is_file()  # retired (#238)
    main_txt = (dist / "main.py").read_text()
    assert "class BCTAlgorithm(BctEngineAlgorithm):" in main_txt
    assert "UNIVERSE_SPEC" not in main_txt  # retired (#238)
    assert "membership_fp" not in main_txt and "order_fp" not in main_txt
    # flat dist imports in isolation (QCAlgorithm falls back to object without AlgorithmImports)
    out = subprocess.run(
        [sys.executable, "-c",
         "import main; print(main.BCTAlgorithm.STRATEGY_CONFIG.name)"],
        cwd=str(dist), capture_output=True, text=True,
    )
    assert out.returncode == 0, out.stderr
    assert "champion-asis" in out.stdout


def test_non_deployable_strategy_is_config_only(tmp_path: Path) -> None:
    # The sample strategy declares NO LEAN_ENTRY -> config-only main.py, no LEAN entry.
    dist = tmp_path / "dist"
    cp.build(SAMPLE, dist_dir=dist)
    main_txt = (dist / "main.py").read_text()
    assert "BctEngineAlgorithm" not in main_txt
    assert not (dist / "lean_entry.py").is_file()


def test_lean_entry_flag_rejects_non_bool() -> None:
    # A non-bool LEAN_ENTRY must fail at BUILD time (fail-fast), not silently. Inject a fake
    # strategy module with a malformed flag.
    import types
    m = types.ModuleType("strategies._fake_bad_flag")
    m.LEAN_ENTRY = "yes"  # type: ignore[attr-defined]  # not a bool
    sys.modules["strategies._fake_bad_flag"] = m
    try:
        with pytest.raises(ValueError, match="LEAN_ENTRY must be a bool"):
            cp._is_deployable("strategies._fake_bad_flag")
    finally:
        del sys.modules["strategies._fake_bad_flag"]


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


def _imported_names(tree: "ast.Module") -> set[str]:
    """All names bound by `from X import a, b` in the module (the symbols main.py can reference)."""
    import ast
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            for alias in node.names:
                names.add(alias.asname or alias.name)
    return names


def _called_class_names(tree: "ast.Module") -> set[str]:
    """Capitalised names invoked as constructors anywhere in the module (e.g. DvRankPredictor(...),
    OracleSignal.Params(...)). These MUST all be imported, or cloud Initialize NameErrors."""
    import ast
    called: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            fn = node.func
            base = fn
            while isinstance(base, ast.Attribute):  # OracleSignal.Params -> base OracleSignal
                base = base.value
            if isinstance(base, ast.Name) and base.id[:1].isupper():
                called.add(base.id)
    return called


def test_injected_impl_param_import_emitted(tmp_path: Path) -> None:
    """#322 regression: a config with an INJECTED impl object in its Params (OracleSignal's
    predictor=DvRankPredictor(...)) must emit the import for that injected class in main.py — else
    cloud Initialize fails 'name DvRankPredictor is not defined'. GENERAL: every class-constructor
    name referenced in the generated main.py is bound by an import (catches any future injected
    impl, e.g. the #286 booster phases, not just DvRankPredictor)."""
    import ast
    dist = tmp_path / "dist"
    cp.build("strategies.learned_dvrank", dist_dir=dist)
    main_src = (dist / "main.py").read_text()
    # the specific symbol that broke the first deploy is emitted...
    assert "import DvRankPredictor" in main_src
    assert "DvRankPredictor(" in main_src  # ...and used in the config literal
    # ...and GENERALLY: no class-constructor name is referenced without an import (the bug class).
    tree = ast.parse(main_src)
    imported = _imported_names(tree)
    # builtins / dunder that are legitimately not imported-from (none expected here, but be safe).
    BUILTINS = {"Slot", "StrategyConfig", "StrategyEngine"}  # all explicitly imported anyway
    undefined = {n for n in _called_class_names(tree) if n not in imported and n not in BUILTINS}
    assert not undefined, f"main.py references un-imported class(es): {undefined}"

    # THE REAL GUARD (HQ): actually IMPORT the generated main.py in an isolated interpreter with
    # ONLY the dist on path — executes the config literal, so a missing OR WRONG-MODULE-PATH injected
    # import raises NameError/ImportError HERE (pre-deploy), exactly the cloud-Initialize failure a
    # string/AST check would miss. This is the test that would have caught 'DvRankPredictor is not
    # defined' before the deploy.
    out = subprocess.run(
        [sys.executable, "-c", "import main; assert main.STRATEGY_CONFIG.name == 'learned-dvrank'"],
        cwd=str(dist), capture_output=True, text=True,
    )
    assert out.returncode == 0, f"generated dist failed to import (the Initialize bug class):\n{out.stderr}"
