# docs/adr/ — Architecture Decision Records

Numbered, immutable-once-accepted records of significant architecture decisions and their rationale.

- **Holds:** one `NNNN-kebab-title.md` per decision (context → decision → consequences), plus the references/research that backed it.
- **Goes here:** cross-cutting design choices that shape the engine (phase boundaries, variant policy, sweep contract, parity model).
- **Does NOT:** per-phase contracts (→ `docs/PHASES.md`), the charter rules (→ `CONVENTIONS.md`), or implementation specs (→ tickets / `docs/superpowers/specs/`).

Supersede a decision with a new ADR that references the old one; don't rewrite history.
