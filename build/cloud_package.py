"""AST closure build: active StrategyConfig -> flat dist/ (#211, ARCH2-2).

Packages ONLY the active config's enabled phase closure:
  1. import the active strategy module -> its StrategyConfig
  2. enabled slots -> enabled phase classes -> their src modules (disabled never seeded)
  3. seed = enabled phase files + engine core; AST-walk transitive src imports (pulls shared/)
  4. flatten src/ -> dist/ (phase_<kind>_<impl>.py / shared_<m>.py / <engine>.py), rewrite imports
  5. emit dist/main.py (flat imports + rebuilt enabled config), dist/_manifest.json, dist/_metadata.py

dist/ is generated + git-tracked + NOT linted. LEAN runs dist/ both local and cloud.
The build script is the single point of failure -> unit-tested in tests/build/.
"""
from __future__ import annotations

import ast
import dataclasses
import hashlib
import importlib
import json
import re
import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

BUILD_SCRIPT_VERSION = "1.0.0"
ENGINE_CORE = ("base", "config", "context", "engine", "logger")
PROJECT_ROOTS = ("engine", "phases", "strategies", "runtime")


@dataclass(slots=True)
class BuildResult:
    config_hash: str
    data_fingerprint: str
    git_commit: str
    included: list[str]          # flat dist filenames
    phase_markers: dict[str, str]  # kind -> version_marker


def _src_root() -> Path:
    return Path(__file__).resolve().parent.parent / "src"


def _module_to_file(modname: str, src: Path) -> Path | None:
    """engine.base -> src/engine/base.py ; phases.signal.x.x -> src/phases/signal/x/x.py."""
    if modname.split(".")[0] not in PROJECT_ROOTS:
        return None
    p = src / Path(*modname.split(".")).with_suffix(".py")
    return p if p.is_file() else None


def _flat_name(path: Path, src: Path) -> str:
    """Flatten a src path to its dist filename (no subdirs allowed in dist)."""
    rel = path.relative_to(src)
    parts = rel.parts
    if parts[0] in ("engine", "runtime"):
        return parts[-1]                                   # engine/base.py -> base.py; runtime/lean_entry.py -> lean_entry.py
    if parts[0] == "phases":
        if parts[1] == "shared":
            return f"shared_{rel.stem}.py"                 # phases/shared/h.py -> shared_h.py
        return f"phase_{parts[1]}_{rel.stem}.py"           # phases/<kind>/<impl>/<impl>.py -> phase_<kind>_<impl>.py
    return rel.name


_RE_ENGINE = re.compile(r"\bfrom engine\.(\w+) import")
_RE_PHASE = re.compile(r"\bfrom phases\.(\w+)\.\w+\.(\w+) import")
_RE_SHARED = re.compile(r"\bfrom phases\.shared\.(\w+) import")
_RE_RUNTIME = re.compile(r"\bfrom runtime\.(\w+) import")


def _rewrite_imports(text: str) -> str:
    text = _RE_SHARED.sub(r"from shared_\1 import", text)
    text = _RE_PHASE.sub(r"from phase_\1_\2 import", text)
    text = _RE_ENGINE.sub(r"from \1 import", text)
    text = _RE_RUNTIME.sub(r"from \1 import", text)  # runtime/lean_entry.py -> lean_entry.py
    return text


def _strip_docstrings(source: str) -> str:
    """Remove module/class/function DOCSTRINGS from a generated dist file (#276b-1 deploy-size: QC
    caps each file at 64,000 chars on /files/update; the verbose two-clock-seam docstrings push
    dist/lean_entry.py past it). The dist is GENERATED + deploy-only + not-linted + not-human-read —
    src/ KEEPS the full docstrings (the rationale lives where humans read it). config_hash is over
    the CONFIG, not file contents → UNAFFECTED.

    AST-SAFE line-range removal: preserves comments + formatting + ALL code; drops ONLY a true
    docstring (the body's FIRST statement, an Expr wrapping a str Constant), and ONLY when the body
    has other statements (never empties a body, e.g. a docstring-only stub) and the docstring is not
    sharing the def/class header line. A module-level string that is NOT the first statement (a real
    value) is untouched."""
    tree = ast.parse(source)
    drop: set[int] = set()
    for node in ast.walk(tree):
        if not isinstance(node, (ast.Module, ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            continue
        body = getattr(node, "body", [])
        if len(body) <= 1:
            continue  # never empty a body
        first = body[0]
        if not (isinstance(first, ast.Expr)
                and isinstance(getattr(first, "value", None), ast.Constant)
                and isinstance(first.value.value, str)):
            continue
        if not isinstance(node, ast.Module) and first.lineno == node.lineno:
            continue  # docstring shares the header line — don't touch the header
        for ln in range(first.lineno, (first.end_lineno or first.lineno) + 1):
            drop.add(ln)
    if not drop:
        return source
    return "\n".join(line for i, line in enumerate(source.split("\n"), start=1) if i not in drop)


def _strip_comments(source: str) -> str:
    """Remove COMMENTS from a generated dist file (#276b deploy-size: QC's 64,000-char/file cap —
    lean_entry.py grew past it even docstring-stripped, from the funnel/tag/censored instrumentation).
    The dist is GENERATED + deploy-only + not-human-read; src/ keeps the comments (the rationale lives
    where humans read it). config_hash is over the CONFIG, not file contents → UNAFFECTED.

    TOKENIZE-SAFE (string-aware): drops only true COMMENT tokens (never a `#` inside a string literal).
    A full-line comment → its line is dropped; a trailing inline comment → only the comment is cut, the
    code (rstripped) is kept. Pre-existing blank lines + all code/strings are preserved (a blank line
    inside a real triple-quoted string is untouched — only comment-emptied lines are dropped)."""
    import io
    import tokenize

    lines = source.split("\n")
    blanked_full: set[int] = set()
    try:
        toks = list(tokenize.generate_tokens(io.StringIO(source).readline))
    except (tokenize.TokenError, IndentationError):
        return source  # never corrupt the dist over a tokenize edge — fall back to un-stripped
    for tok in toks:
        if tok.type != tokenize.COMMENT:
            continue
        r, c = tok.start[0] - 1, tok.start[1]
        before = lines[r][:c]
        if before.strip():
            lines[r] = before.rstrip()       # code + trailing comment → keep code only
        else:
            blanked_full.add(r)              # full-line comment → drop the line
    return "\n".join(line for i, line in enumerate(lines) if i not in blanked_full)


def _imports_in(path: Path) -> list[str]:
    tree = ast.parse(path.read_text(), filename=str(path))
    mods: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module:
            mods.append(node.module)
        elif isinstance(node, ast.Import):
            mods.extend(a.name for a in node.names)
    return mods


def _closure(seeds: list[Path], src: Path) -> set[Path]:
    """Transitive set of src files reachable from seeds via project-root imports."""
    seen: set[Path] = set()
    stack = list(seeds)
    while stack:
        f = stack.pop()
        if f in seen:
            continue
        seen.add(f)
        for mod in _imports_in(f):
            dep = _module_to_file(mod, src)
            if dep is not None and dep not in seen:
                stack.append(dep)
    return seen


def _load_config(strategy_module: str) -> Any:
    src = _src_root()
    if str(src) not in sys.path:
        sys.path.insert(0, str(src))
    mod = importlib.import_module(strategy_module)
    for attr in ("CONFIG", "STRATEGY_CONFIG", "EXAMPLE_CONFIG"):
        if hasattr(mod, attr):
            return getattr(mod, attr)
    raise ValueError(f"{strategy_module}: no StrategyConfig found (CONFIG/STRATEGY_CONFIG/EXAMPLE_CONFIG)")


def _is_deployable(strategy_module: str) -> bool:
    """Whether the strategy is LEAN-DEPLOYABLE (#238): it gets the LEAN entry subclass
    (runtime.lean_entry.BctEngineAlgorithm) + the live-coarse universe wiring in the
    generated main.py. A strategy opts in by declaring `LEAN_ENTRY = True`.

    #238 retired UNIVERSE_SPEC (the stored-universe-file ObjectStore keys + pinned
    fingerprints — the 326 scar): the universe is computed LIVE from QC's coarse feed, so
    there is no artifact to bind/verify. The discriminator is now a plain flag, not a spec.
    Config-only fixtures (sample/example) omit LEAN_ENTRY → config-only main.py, no entry."""
    src = _src_root()
    if str(src) not in sys.path:
        sys.path.insert(0, str(src))
    mod = importlib.import_module(strategy_module)
    flag = getattr(mod, "LEAN_ENTRY", False)
    if not isinstance(flag, bool):
        raise ValueError(f"{strategy_module}: LEAN_ENTRY must be a bool, got {type(flag).__name__}")
    return flag


def _enabled_slots(config: Any) -> list[tuple[str, Any]]:
    out: list[tuple[str, Any]] = []
    for kind, value in config.phases.items():
        slots = value if isinstance(value, list) else [value]
        for s in slots:
            if s.enabled:
                out.append((kind, s))
    return out


def _git_commit() -> str:
    try:
        return subprocess.check_output(
            ["git", "rev-parse", "HEAD"], cwd=str(_src_root().parent), text=True
        ).strip()
    except Exception:
        return "unknown"


def _data_fingerprint() -> str:
    mf = _src_root().parent / "data" / "MANIFEST.json"
    if mf.is_file():
        try:
            return str(json.loads(mf.read_text()).get("fingerprint", "unknown"))
        except Exception:
            return "unknown"
    return "unknown"


def _params_canonical(params: Any) -> str:
    """Params string for the config hash, EXCLUDING a phase's STRUCTURAL fields
    (`Params._HASH_EXCLUDE`). MUST stay byte-identical to engine._params_canonical — the build hash
    is asserted == the engine pin. #276b-1: `resolution` (clock-routing) is phase-determined (the
    chain-clock guard enforces it) → redundant for behavioral identity, excluded so champion-asis
    stays at e573e84b1ce1 when the shared sizer gains the structural knob. (DRY DEBT: this duplicates
    engine._config_hash — see #297; they MUST match. Unify in a shared module in a follow-up.)"""
    exclude = getattr(type(params), "_HASH_EXCLUDE", frozenset())
    if not exclude or not dataclasses.is_dataclass(params):
        return repr(params)
    inner = ", ".join(
        f"{f.name}={getattr(params, f.name)!r}"
        for f in dataclasses.fields(params) if f.name not in exclude
    )
    return f"{type(params).__qualname__}({inner})"


def _config_hash(config: Any) -> str:
    parts = [config.name, config.version]
    for kind in sorted(config.phases):
        value = config.phases[kind]
        slots = value if isinstance(value, list) else [value]
        for s in slots:
            parts.append(f"{kind}:{s.impl.__name__}:{s.enabled}:{_params_canonical(s.params)}")
    return hashlib.sha256("|".join(parts).encode()).hexdigest()[:12]


def build(strategy_module: str, *, dist_dir: Path | None = None, verbose: bool = False) -> BuildResult:
    config = _load_config(strategy_module)
    deployable = _is_deployable(strategy_module)
    return _build_core(config, deployable, dist_dir, strategy_module, verbose)


def build_from_config(
    config: Any, *, deployable: bool = True, dist_dir: Path | None = None, verbose: bool = False
) -> BuildResult:
    """Build a dist from an IN-MEMORY StrategyConfig object (the #323 sweep bridge — a
    SweepConfig is mapped to a StrategyConfig that has no backing module file). Identical
    closure/emit/audit path as build(strategy_module); `deployable` is explicit (no LEAN_ENTRY
    module flag to read). The generated main.py carries config.name as its marker."""
    return _build_core(config, deployable, dist_dir, getattr(config, "name", "config"), verbose)


def _build_core(
    config: Any, deployable: bool, dist_dir: Path | None, label: str, verbose: bool
) -> BuildResult:
    src = _src_root()
    dist = dist_dir if dist_dir is not None else src.parent / "dist"
    enabled = _enabled_slots(config)

    # seed = enabled phase module files + engine core
    seeds: list[Path] = []
    for _kind, slot in enabled:
        f = _module_to_file(slot.impl.__module__, src)
        if f is None:
            raise ValueError(f"phase {slot.impl.__name__}: module {slot.impl.__module__} not under src/")
        seeds.append(f)
    for m in ENGINE_CORE:
        seeds.append(src / "engine" / f"{m}.py")
    # The LEAN entry (#213/#238) is seeded only for deployable strategies (LEAN_ENTRY=True);
    # it pulls runtime.universe_select (the live filter→rank→cap) transitively. Config-only
    # fixtures (sample/example) stay minimal — no LEAN entry.
    if deployable:
        seeds.append(src / "runtime" / "lean_entry.py")

    closure = _closure(seeds, src)

    # write dist
    if dist.exists():
        shutil.rmtree(dist)
    dist.mkdir(parents=True)
    included: list[str] = []
    for f in sorted(closure):
        flat = _flat_name(f, src)
        # #276b-1/#276b: strip docstrings AND comments from the generated dist file (QC 64k/file
        # deploy cap — lean_entry.py grew past it even docstring-only-stripped; src/ keeps the
        # rationale, dist is deploy-only + not-human-read). config_hash unaffected (hashes the config).
        (dist / flat).write_text(_strip_comments(_strip_docstrings(_rewrite_imports(f.read_text()))))
        included.append(flat)

    # generated flat entry + manifest + metadata
    phase_markers = _emit_main(config, enabled, dist, src, deployable)
    result = BuildResult(
        config_hash=_config_hash(config),
        data_fingerprint=_data_fingerprint(),
        git_commit=_git_commit(),
        included=sorted(included + ["main.py", "_manifest.json", "_metadata.py"]),
        phase_markers=phase_markers,
    )
    _emit_manifest(result, dist, is_fixture=getattr(config, "is_fixture", False))
    _emit_metadata(result, dist)

    # audits
    for item in dist.iterdir():
        if item.is_dir():
            raise RuntimeError(f"dist/ has a subdir {item.name} — flat invariant violated")
    if verbose:
        print(f"built {label}: {len(included)} phase/engine files + main/manifest/metadata")
        print(f"hash={result.config_hash} data={result.data_fingerprint} commit={result.git_commit[:8]}")
    return result


def _emit_main(
    config: Any,
    enabled: list[tuple[str, Any]],
    dist: Path,
    src: Path,
    deployable: bool = False,
) -> dict[str, str]:
    """Generate dist/main.py: flat imports of enabled phases + rebuilt enabled config.
    If the strategy is LEAN-deployable (#238 LEAN_ENTRY=True), also emit the LEAN entry
    subclass so the same dist artifact runs on QC (the universe is computed live — no
    UNIVERSE_SPEC); otherwise emit only the config (sample/example)."""
    markers: dict[str, str] = {}
    # engine __init__ is dropped in flat dist; import the flat modules directly instead
    imports = [
        "from config import Slot, StrategyConfig",
        "from engine import StrategyEngine",
    ]
    # Group enabled slots by kind, preserving first-seen order. A kind may carry MULTIPLE
    # slots (regime, exit_*, diagnostics) — those MUST be emitted as a list literal, never
    # as repeated dict keys (a repeated key silently drops all but the last → a phase would
    # vanish from dist while present in src). Single-slot kinds emit a bare Slot.
    seen_cls: set[str] = set()
    grouped: dict[str, list[Any]] = {}
    for kind, slot in enabled:
        grouped.setdefault(kind, []).append(slot)

    def _slot_file(slot: Any) -> Path:
        """Resolve an enabled slot's src file. build() already validated every enabled
        slot resolves (raises before _emit_main if not), so None is unreachable here;
        the guard makes the invariant explicit and narrows Path | None -> Path."""
        f = _module_to_file(slot.impl.__module__, src)
        if f is None:
            raise ValueError(
                f"phase {slot.impl.__name__}: module {slot.impl.__module__} not under src/"
            )
        return f

    def _render_slot(slot: Any) -> str:
        cls = slot.impl.__name__
        flat_mod = _flat_name(_slot_file(slot), src)[:-3]  # strip .py
        if cls not in seen_cls:
            imports.append(f"from {flat_mod} import {cls}")
            seen_cls.add(cls)
        params_kwargs = ", ".join(f"{f.name}={getattr(slot.params, f.name)!r}"
                                  for f in dataclasses.fields(slot.params))
        return f"Slot(impl={cls}, params={cls}.Params({params_kwargs}))"

    slot_lines: list[str] = []
    for kind, slots in grouped.items():
        rendered = [_render_slot(s) for s in slots]
        # Emit a list literal if the source config had a list for this kind OR there are
        # multiple enabled slots — round-trips multi-sub-phase kinds faithfully.
        original_is_list = isinstance(config.phases.get(kind), list)
        if original_is_list or len(rendered) > 1:
            slot_lines.append(f'    {kind!r}: [{", ".join(rendered)}],')
        else:
            slot_lines.append(f'    {kind!r}: {rendered[0]},')
        # record marker(s) — one per slot, joined for multi-slot kinds (accurate provenance)
        marker_texts: list[str] = []
        for s in slots:
            try:
                marker_texts.append(s.impl(s.params, None).version_marker)
            except Exception:
                marker_texts.append(_flat_name(_slot_file(s), src)[:-3])
        markers[kind] = ",".join(marker_texts)
    if deployable:
        imports.append("from lean_entry import BctEngineAlgorithm")
    # #272: FAIL LOUD if StrategyConfig gains a field this codegen doesn't emit — a dropped
    # field silently changes the deployed config (the exact bug class that lost is_fixture and
    # would have crashed the fail-loud gate at cloud init). Keep _EMITTED in lockstep with the
    # dataclass; an unhandled new field fails the BUILD, not silently at deploy.
    _EMITTED = {"name", "version", "phases", "is_fixture"}
    _actual = {f.name for f in dataclasses.fields(config)}
    if _actual != _EMITTED:
        raise ValueError(
            f"cloud_package codegen out of sync with StrategyConfig fields: "
            f"unhandled {sorted(_actual - _EMITTED)}, stale {sorted(_EMITTED - _actual)} — "
            f"update _emit_main to emit every field (a dropped field silently changes dist)"
        )
    body = "\n".join(imports) + "\n\n"
    body += f'STRATEGY_CONFIG = StrategyConfig(\n    name={config.name!r},\n    version={config.version!r},\n'
    # carry is_fixture into the deployed config — else a fixture (e.g. champion_asis) would
    # lose the flag and CRASH the fail-loud entry+exit gate at cloud init (DegradedConfigError).
    if getattr(config, "is_fixture", False):
        body += "    is_fixture=True,\n"
    body += "    phases={\n"
    body += "\n".join(slot_lines) + "\n    },\n)\n\n"
    if deployable:
        # The LEAN entry subclass (#213/#238/Y). QC instantiates this top-level QCAlgorithm;
        # lean_entry._coarse_selection applies apply_floors → rank_and_cap (the selection
        # gate); the dv_rank_cap phase exposes qc._ranked_today∩active. No per-bar filter
        # phase. No UNIVERSE_SPEC: the universe is computed live, not loaded.
        body += (
            "\nclass BCTAlgorithm(BctEngineAlgorithm):\n"
            "    STRATEGY_CONFIG = STRATEGY_CONFIG\n"
        )
    else:
        body += "# Not LEAN-deployable — config-only build (sample/example); no LEAN entry emitted.\n"
    (dist / "main.py").write_text(body)
    return markers


def _emit_manifest(result: BuildResult, dist: Path, is_fixture: bool = False) -> None:
    (dist / "_manifest.json").write_text(json.dumps({
        "config_hash": result.config_hash,
        "data_fingerprint": result.data_fingerprint,
        "git_commit": result.git_commit,
        "build_script_version": BUILD_SCRIPT_VERSION,
        "phase_markers": result.phase_markers,
        "is_fixture": is_fixture,
        "files": result.included,
    }, indent=2, sort_keys=True))


def _emit_metadata(result: BuildResult, dist: Path) -> None:
    (dist / "_metadata.py").write_text(
        '"""Generated build metadata — logged on LEAN startup. Do not edit."""\n'
        f'GIT_COMMIT = {result.git_commit!r}\n'
        f'CONFIG_HASH = {result.config_hash!r}\n'
        f'DATA_FINGERPRINT = {result.data_fingerprint!r}\n'
        f'BUILD_SCRIPT_VERSION = {BUILD_SCRIPT_VERSION!r}\n'
    )


if __name__ == "__main__":
    mod = sys.argv[1] if len(sys.argv) > 1 else "strategies._build_sample"
    build(mod, verbose=True)
