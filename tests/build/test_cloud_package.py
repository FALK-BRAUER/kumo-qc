"""Unit tests for the AST closure build — the single point of failure (#211)."""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

import cloud_package as cp

SAMPLE = "strategies._build_sample"


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
    _, dist = built
    m = json.loads((dist / "_manifest.json").read_text())
    assert m["data_fingerprint"] == "ba8307b6e556cca4"
    assert m["build_script_version"] == cp.BUILD_SCRIPT_VERSION
    assert "phase_signal_sample_bct.py" in m["files"]
    assert m["phase_markers"]["signal"] == "sample_bct_v1"


def test_metadata_emitted(built: tuple[cp.BuildResult, Path]) -> None:
    _, dist = built
    meta = (dist / "_metadata.py").read_text()
    assert "DATA_FINGERPRINT = 'ba8307b6e556cca4'" in meta
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
