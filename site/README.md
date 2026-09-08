# Public showcase site

`index.html` is the public face of the project: the results with their
honest caveats, a 20-metric wall, seven charts built from the
repository's own result files, the seven published nulls, the
look-ahead finding, and the upgrade that was refused.

Design brief: numbers and figures carry the page, prose does not. Every
caption is one line. If a section needs a paragraph to justify itself,
it is the wrong section.

## How it's built

`template.html` holds the markup, styles and chart code with a
`__DATA__` placeholder. `scripts/build_site.py` reads the latest report
JSONs plus the construction-v2 daily series, extracts exactly the
metrics the page shows, and injects them to produce `index.html`.

```
uv run --no-sync python scripts/build_site.py
```

Re-run after any study, then redeploy. Never hand-edit `index.html` —
edit the template and rebuild, or your change is lost on the next build.

## Why it is static, with no backend

Every number on the page is a research result that changes at most
quarterly. A backend would add hosting cost, secrets to manage, an
attack surface and another thing to monitor, in exchange for serving
data that does not move. Static HTML on a CDN is faster, free and
harder to break. There are no external requests at all: the data,
styles and chart code are inlined in the single file.

If the page ever needs to show live paper-trading results, the right
design is still not a backend — it is a nightly job committing a small
JSON snapshot.

## What is deliberately NOT here

The operations dashboard (`scripts/run_dashboard.py`) shows live
positions, equity and operational health with no authentication. It
stays localhost-only (ADR 0012). This page contains no live trading
state whatsoever.

## Deploying

**There is exactly ONE Artha site. Redeploy it; never create a second.**

    https://artha-quant.vercel.app

Verified live 2026-09-08 and byte-identical to `site/index.html` at
commit a658a0c, so the deployed page is current. It is also the
`homepage` on the GitHub repo — keep those two in agreement.

Preferred mechanism: connect the GitHub repository in the Vercel
dashboard with root directory `site`, so every push redeploys.

Three Vercel projects were built from this one repo. Keep `artha`;
delete the other two:

| Project | URL | State |
|---|---|---|
| `artha` | `artha-quant.vercel.app` | **KEEP** — git-linked, serves the current build |
| `artha-quant` | `artha-quant-woad.vercel.app` | delete — git-linked to the same repo, so every push double-builds, and the URL 404s (root directory never set to `site`) |
| `artha-nse` | `artha-nse.vercel.app` | delete — 2026-07-22 API push, no git link, still publicly serving a STALE July build (19KB vs the current 43KB) |

`artha-nse` is the one worth removing first: it is a second, older, public
copy of these results with none of the corrections since July. Its
project-scoped URL (`artha-nse-vivaanjain246-6796s-projects.vercel.app`)
sits behind Vercel Authentication, but the short alias does not, so the
stale page is readable by anyone who finds it.

Two things learned the hard way on that API deploy, both of which cost a
redeploy:

1. **The API token can CREATE a project but not deploy again to an
   existing one** — the second call returns 403 "You don't have
   permission to create a Preview/Production Deployment for this
   project". So an API deploy must carry the complete file set in the
   very first call that creates the project. A name that has been used
   once is effectively burned for further API deploys.
2. **Deployment Protection is ON at the team level.** The URL answers
   200 with Vercel's SSO login page, not the site. Turn it off at
   Project → Settings → Deployment Protection → Vercel Authentication →
   Disabled, or the page is unreadable to anyone but the account owner.

Both disappear once the GitHub connection replaces API deploys, which is
the reason to prefer it.
