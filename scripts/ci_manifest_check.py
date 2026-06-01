#!/usr/bin/env python3
"""CI manifest phase-marker check — derives required-set from engine single source.

This script is the CI-side complement to the runtime DegradedConfigError gate
(engine._validate_execution_stack). It reads dist/_manifest.json and verifies
that the built artifact declares all phase kinds the engine expects.

By importing REQUIRED_PHASES, ENTRY_PHASE_KINDS, and EXIT_PHASE_KINDS from the
engine module, this check stays in lockstep with the runtime taxonomy — no
hardcoded parallel list that can drift.
"""

import json
import sys
from pathlib import Path


def main() -> int:
    manifest_path = Path("dist/_manifest.json")
    if not manifest_path.exists():
        print("ERROR: dist/_manifest.json not found")
        return 1

    m = json.loads(manifest_path.read_text())
    phases = m.get("phase_markers", {})
    is_fixture = m.get("is_fixture", False)

    # Derive required-set from engine single source (DRY — no hardcoded list)
    sys.path.insert(0, str(Path(__file__).parent.parent / "src"))
    from engine.engine import (
        ENTRY_PHASE_KINDS,
        EXIT_PHASE_KINDS,
        REQUIRED_PHASES,
    )

    missing: list[str] = []

    # Base: all REQUIRED_PHASES must be present
    for kind in REQUIRED_PHASES:
        if kind not in phases or not phases[kind]:
            missing.append(kind)

    # Non-fixture champions must wire at least one entry-confirm phase
    # (matches runtime OR-gate: any(entry_selection, entry_timing) satisfies)
    if not is_fixture:
        has_entry = any(phases.get(k) for k in ENTRY_PHASE_KINDS)
        if not has_entry:
            missing.append(
                f"entry ({'|'.join(sorted(ENTRY_PHASE_KINDS))} — at least one required)"
            )

    # Non-fixture champions must wire at least one exit phase
    # (matches runtime OR-gate: any exit_* kind satisfies)
    if not is_fixture:
        has_exit = any(phases.get(k) for k in EXIT_PHASE_KINDS)
        if not has_exit:
            missing.append(
                f"exit ({'|'.join(sorted(EXIT_PHASE_KINDS))} — at least one required)"
            )

    # NOTE: regime and diagnostics are conventionally present but NOT
    # strictly required by the runtime (_validate_execution_stack). If they
    # should be hard-required, add them to engine.REQUIRED_PHASES — never
    # hardcode here (that's the #297 anti-drift contract).

    if missing:
        print(
            f"ERROR: missing phase markers: {missing} (is_fixture={is_fixture})"
        )
        return 1

    print(
        f"OK: {len(phases)} phase markers present (is_fixture={is_fixture})"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
