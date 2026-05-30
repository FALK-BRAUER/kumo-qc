# tests/

Test suite. **Mirrors `src/` 1:1** — every `src/<path>/<mod>.py` has `tests/<path>/test_<mod>.py`.

- **Holds:** `engine/`, `phases/<kind>/<impl>/`, `strategies/` (mirror of src), plus `harness/` and `integration/` (no src/ counterpart).
- **Goes here:** all tests. Source stays import-clean — no tests inside `src/`.
- **Does NOT:** non-test code, fixtures-as-production-data.
- **Run:** `mypy --strict src/` + `pytest`. Tests run against `src/`; parity tests run the built `dist/`.
