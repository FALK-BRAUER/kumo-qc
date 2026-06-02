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

from typing import Any

from sweeps.types import SweepConfig

# Bump on ANY change to the emitted dict SHAPE so the mine can gate on serializer drift.
CONFIG_SERIALIZER_VERSION = "276b.v1"


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
            "params": dict(choice.params),
            "free_params": choice.free_params,
        }
    return {
        "name": name or config.config_hash,
        "version": CONFIG_SERIALIZER_VERSION,
        "config_hash": config.config_hash,
        "phases": phases,
    }
