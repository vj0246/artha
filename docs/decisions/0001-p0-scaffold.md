# ADR 0001: P0 scaffold decisions

Date: 2026-07-08

- **Repo location:** `Personal Projects\Quant\artha`, inside OneDrive, per VJ's
  explicit choice. Mitigation for OneDrive sync risk: `data/` is git-ignored and
  must live outside OneDrive via `ARTHA_DATA_DIR` (enforced when the P1 config
  module lands). GitHub is the backup of record.
- **GPU constraint recorded:** RTX 2050 with 4 GB VRAM. The transformer stretch
  (plan §15.2) remains conditional and is limited to small models (PatchTST-small
  scale, batch-size constrained). LightGBM primary track is unaffected.
- **CLAUDE.md source:** the plan references "Appendix C" for CLAUDE.md contents,
  but no Appendix C exists in the document. CLAUDE.md was written from Appendix A
  item 2 instead.
- **Dependencies:** only what P0/P1 groundwork needs (polars, duckdb, pydantic +
  dev tooling). LightGBM, scikit-learn, HTTP clients, pykiteconnect enter
  pyproject at the phase that needs them, not before.
- **Toolchain:** uv 0.11.x, Python 3.12 pinned via `.python-version`, ruff
  (format + lint), mypy --strict, pytest + hypothesis, pre-commit, GitHub Actions
  with `astral-sh/setup-uv@v5` and `uv sync --locked` against a committed lock.
