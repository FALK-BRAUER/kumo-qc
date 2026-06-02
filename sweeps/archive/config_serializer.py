"""`serialize_config(...)` — SweepConfig → a plain dict for the results-archive `result.json`.

DECOUPLING (the snapshotter's contract, snapshot.py module docstring): `persist_run` takes the
config PRE-SERIALIZED as a plain dict so the writer NEVER imports engine / sweeps types. This
serializer is the call-site helper that does that flattening — it lives in sweeps/archive (the
caller's side), NOT in snapshot.py, so the writer stays type-agnostic.

Shape (stable; the #303 mine reads it back):

    {
      "name": "<name>",            # logical config name (defaults to the config_hash)
      "version": "<version>",      # serializer/provenance version tag
      "config_hash": "<12-hex>",   # the SweepConfig.config_hash (cross-check vs result.json key)
      "phases": {                  # one entry PER phase kind, deterministically ordered by kind
        "<kind>": {
          "impl": "<impl_name>",
          "params": { "<field>": <value>, ... },   # the resolved param assignment for THIS variant
          "free_params": <int>                      # swept-axis DoF this phase contributes
        },
        ...
      }
    }

Determinism: phases are emitted sorted by kind, params are a plain dict (json.dumps sort_keys at the
write site gives byte-stable output). Param VALUES are passed through verbatim — the runner only
ever stores JSON-native scalars in PhaseChoice.params, so no lossy coercion is applied here.
"""
from __future__ import annotations

import dataclasses
import datetime as _dt
import enum
from pathlib import PurePath
from typing import Any

from sweeps.types import SweepConfig

# Bump on ANY change to the emitted dict SHAPE so the mine can gate on serializer drift.
# v2 (#322): injected-impl param VALUES (e.g. OracleSignal's predictor=DvRankPredictor(...)) are
# JSON-flattened to {"__type__": <cls>, <field>: <val>, ...} instead of passed through verbatim
# (a dataclass object is not JSON-serializable → persist_run's json.dumps raised TypeError).
# v3 (#9 storage-uniformity): _jsonify NEVER raises — any non-JSON-native scalar (datetime, Path,
# set, Enum) is coerced rather than passed through to a json.dumps TypeError; + a documented
# reversible round-trip (`unjsonify`) for the structural form (dict/list/__type__/JSON scalars).
CONFIG_SERIALIZER_VERSION = "276b.v3"

# The reserved key that tags a flattened dataclass instance (so the mine + unjsonify recognize it).
TYPE_KEY = "__type__"


def _jsonify(value: Any) -> Any:
    """JSON-safe ANY PhaseChoice param value — NEVER raises (the #9 storage-uniformity contract).

    - JSON-native scalars (str/int/float/bool/None) pass through.
    - An INJECTED impl object (a dataclass instance, e.g. a predictor) → {"__type__": ClassName,
      <field>: <val>} so result.json is serializable AND the #303 mine reads the booster's params
      (e.g. rank_cap) back from the archive.
    - dict / list / tuple recurse (tuple → list; the archive treats sequences as lists).
    - Non-JSON-native scalars are COERCED one-way (write-only, NOT round-trippable back to the
      original type): datetime/date → ISO string; Path → str; set/frozenset → sorted list; Enum →
      its .value. This prevents a stray non-native param from raising json.dumps TypeError at the
      write site (which would evaporate the whole run, #276b fail-loud — but here a benign coercion
      is correct: params are provenance, not behaviour)."""
    if dataclasses.is_dataclass(value) and not isinstance(value, type):
        out: dict[str, Any] = {TYPE_KEY: type(value).__name__}
        for f in dataclasses.fields(value):
            out[f.name] = _jsonify(getattr(value, f.name))
        return out
    if isinstance(value, enum.Enum):
        return _jsonify(value.value)
    if isinstance(value, dict):
        return {k: _jsonify(v) for k, v in value.items()}
    if isinstance(value, (list, tuple, set, frozenset)):
        seq = sorted(value, key=repr) if isinstance(value, (set, frozenset)) else value
        return [_jsonify(v) for v in seq]
    if isinstance(value, (_dt.datetime, _dt.date)):
        return value.isoformat()
    if isinstance(value, PurePath):
        return str(value)
    return value  # JSON-native scalar (or already-coerced) — pass through


def unjsonify(value: Any) -> Any:
    """The reversible inverse of `_jsonify` for its STRUCTURAL form — the round-trip the #303 mine
    relies on to read params back from the archive. dict / list recurse; a {"__type__": Name, ...}
    dataclass-flattening is returned as a plain dict (the mine reads its fields by name — we do NOT
    reconstruct the original class, since the archive carries only the name, not the import path).
    JSON-native scalars pass through.

    ROUND-TRIP CONTRACT: `unjsonify(_jsonify(x))` recovers x EXACTLY for JSON-native scalars, dicts,
    and lists, and recovers a dataclass as its field-dict (tagged with __type__). It does NOT undo
    the one-way scalar coercions (datetime/Path/set/Enum/tuple) — those are write-only provenance.
    For values built only from the round-trippable set, it is a true inverse (asserted in tests)."""
    if isinstance(value, dict):
        return {k: unjsonify(v) for k, v in value.items()}
    if isinstance(value, list):
        return [unjsonify(v) for v in value]
    return value


def serialize_config(config: SweepConfig, *, name: str | None = None) -> dict[str, Any]:
    """Flatten a SweepConfig to the plain dict persist_run stores in result.json.

    `name` is the logical config label (defaults to the config_hash when the caller has none).
    The phases map is keyed by phase kind and deterministically ordered, so two serializations of
    the same config are byte-identical under sort_keys.
    """
    phases: dict[str, Any] = {}
    for choice in sorted(config.choices, key=lambda c: c.kind):
        phases[choice.kind] = {
            "impl": choice.impl_name,
            "params": {k: _jsonify(v) for k, v in choice.params},
            "free_params": choice.free_params,
        }
    return {
        "name": name or config.config_hash,
        "version": CONFIG_SERIALIZER_VERSION,
        "config_hash": config.config_hash,
        "phases": phases,
    }
