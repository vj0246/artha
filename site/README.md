# Public showcase site

A single self-contained `index.html` — the public face of the project:
what it does, the results (with their honest caveats), the seven
published nulls, the look-ahead finding, and the four times the project
corrected itself.

**Static by design.** Every number here is a research result that
changes at most quarterly, so there is nothing to serve dynamically and
no backend to run: no database, no API, no secrets, no attack surface,
no bill. Update the numbers by editing this file when a study is re-run.

**Deliberately NOT the ops dashboard.** That one (`scripts/run_dashboard.py`)
shows live positions, equity and operational health with no
authentication and stays localhost-only — see ADR 0012. This page
contains no live trading state whatsoever.

Deploy: point Vercel at this directory (framework: Other, output
directory: `site`), or `vercel deploy --prod` from inside it.
