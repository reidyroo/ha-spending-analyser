# HA Spending Analyser — Project Tracker

> **Purpose:** Local-first Home Assistant spending tracker with Edge AI categorisation via Ollama.  
> **Privacy:** All data stays on the local network — no external API calls for financial data.  
> **AI:** Ollama running on a Surface Pro, accessed as a LAN REST service.

---

## Quick Resume Guide

1. Open this project folder in Cowork.
2. Ask Claude: *"Resume the HA Spending Analyser build — check CLAUDE.md and pick up the next task."*
3. Claude will read this file, check the task list, and continue from where we left off.

---

## Release Process

Every time code changes are pushed that should be available via HACS auto-update, a new version must be tagged and released. Steps:

1. Bump version in **two files** (must match):
   - `custom_components/spending_analyser/const.py` → `VERSION = "x.y.z"`
   - `custom_components/spending_analyser/manifest.json` → `"version": "x.y.z"`
2. Commit: `git commit -m "chore: bump version to x.y.z"`
3. Push: `git push`
4. Tag + release:
   ```powershell
   git tag vX.Y.Z main
   git push origin vX.Y.Z
   gh release create vX.Y.Z --title "vX.Y.Z — <summary>" --notes "<bullet points>"
   ```

**Versioning convention:**
- `x.Y.0` — new features (new UI, new service, new sensor)
- `x.y.Z` — bug fixes and format additions (new bank parser, UI fix)

HACS checks the GitHub releases list for the latest tag. Without a release, HACS shows the old version even if commits were pushed.

---

## Credit Conservation Notes

- Batch file writes into single bash calls wherever possible.
- Avoid re-reading files just written.
- Keep responses lean — no long summaries after file creation.
- If credits are running low, complete the current task, update CLAUDE.md, and stop cleanly.

---

## Architecture Overview

```
HA Instance
└── custom_components/spending_analyser/
    ├── __init__.py          # Entry setup/unload
    ├── manifest.json        # HA component metadata
    ├── config_flow.py       # UI-based setup (Ollama host/port/model)
    ├── const.py             # All constants and defaults
    ├── strings.json         # UI labels
    ├── sensor.py            # HA sensor entities (Task 9) ✅
    ├── database.py          # SQLite CRUD layer (Task 3) ✅
    ├── ollama_client.py     # Ollama REST client (Task 7) ✅
    ├── parsers/             # CSV/OFX/QIF importers (Task 4) ✅
    │   ├── __init__.py      #   parse_statement() entry point
    │   ├── base.py          #   ParsedTransaction dataclass
    │   ├── csv_parser.py    #   midata, CommBank, ANZ, NAB, Westpac, generic
    │   ├── ofx_parser.py    #   OFX v1 SGML + v2 XML
    │   └── qif_parser.py    #   QIF
    └── services.yaml        # Service definitions ✅

www/spending_analyser/       # Lovelace custom card assets (Task 10)
config/spending_analyser/    # Runtime config overrides
tests/                       # pytest suite (Task 14)
docs/                        # Installation and usage docs (Task 15)
```

**Data flow:**
Bank statement → Upload panel (Task 11) → Parser (Task 4) → SQLite DB (Task 3)
                                                              ↓
                                                    Ollama categorisation (Tasks 7–8)
                                                              ↓
                                                    HA Sensor entities (Task 9)
                                                              ↓
                                                    Lovelace Dashboard (Task 10)

---

## Task Status

### v0.1.0 (complete)

| # | Task | Status |
|---|------|--------|
| 1 | GitHub repo + project structure | ✅ Done |
| 2 | HA custom component skeleton | ✅ Done |
| 3 | SQLite transaction database | ✅ Done |
| 4 | Statement import service (CSV/OFX/QIF) | ✅ Done |
| 5 | Manual transaction entry service | ✅ Done |
| 6 | Ollama on Surface + Neural Engine verification | ✅ Done (user confirmed) |
| 7 | Ollama client integration | ✅ Done |
| 8 | Auto-categorisation pipeline with learning | ✅ Done |
| 9 | HA sensor entities for spending metrics | ✅ Done |
| 10 | Lovelace spending dashboard | ✅ Done |
| 11 | Secure file upload panel | ✅ Done |
| 12 | AI deep-analysis report service | ✅ Done |
| 13 | Security hardening | ✅ Done |
| 14 | Tests + GitHub Actions CI | ✅ Done |
| 15 | HACS packaging + docs | ✅ Done |

### v0.2.0 (complete)

| # | Task | Status |
|---|------|--------|
| 16 | Transfer/reconciliation exclusion from spending sensors | ✅ Done — "Transfer" & "Income" excluded from MonthlySpending and MonthlyNet; credit card payments categorised as Transfer are not double-counted |
| 17 | Transaction review & categorisation UI (`review.html`) | ✅ Done — table view, inline category dropdowns, AI suggest per row, bulk suggest, save, pagination, search/filter |
| 18 | Ollama test panel (connectivity + prompt test) | ✅ Done — embedded in review page; tests connection and live categorisation with latency display |
| 19 | HTTP API endpoints for UI | ✅ Done — `/api/spending_analyser/transactions`, `/categories`, `/recategorise`, `/ollama_test` |
| 20 | Dashboard YAML fixes | ✅ Done — `type: stat` → `type: entity`; Import button navigates to upload panel |
| 21 | Long-lived token setup UI | ✅ Done — both upload and review pages guide the user through one-time token creation |

### v0.3.0 (backlog — ideas for next session)

| # | Task | Notes |
|---|------|-------|
| 22 | Transfer auto-detection on import | Pattern match "CREDIT CARD PAYMENT", "BARCLAYCARD", "JOHN LEWIS FINANCIAL" etc. and pre-categorise as Transfer |
| 23 | Review page: "Apply AI to all + save" one-click workflow | Bulk suggest + confirm all in a single action |
| 24 | Review page: sort by column | Click date/amount/category headers to sort |
| 25 | Month picker for dashboard + review | Filter data to a specific past month |
| 26 | Budget alerts | HA notifications when spending in a category exceeds monthly budget |
| 27 | CSV export of transactions | Download filtered view as CSV |

---

## Key Decisions Made

- **Database:** SQLite via `aiosqlite` — local, no external dependencies, included in HA backups.
- **AI model default:** `phi3:mini` (fast, NPU-friendly). Can be changed in config flow.
- **Import formats:** CSV (configurable columns), OFX, QIF.
- **Deduplication:** Hash of `date + description + amount` on import.
- **Sensor update interval:** 15 minutes (configurable via `const.py`).
- **HA minimum version:** 2024.1.0 (required for `async_forward_entry_setups`).

---

## GitHub Setup (user action required after Task 1)

```bash
cd "C:\Code\Claude\HA Spending Analyser"
git init
git add .
git commit -m "chore: initial component skeleton (Tasks 1–2)"
git remote add origin https://github.com/reidyroo/ha-spending-analyser.git
git push -u origin main
```

## HA Installation (dev/testing)

Copy `custom_components/spending_analyser/` into your HA config's `custom_components/` folder and restart HA. Then add the integration via **Settings → Devices & Services → Add Integration → Spending Analyser**.

---

## Ollama Setup Checklist (Task 6 — user action)

- [ ] Install Ollama: https://ollama.com/download
- [ ] Pull model: `ollama pull phi3:mini`
- [ ] Verify NPU usage: Windows Task Manager → Performance → NPU graph should spike during inference
- [ ] Confirm LAN access from HA host: `curl http://<surface-ip>:11434/api/tags`
- [ ] Note the Surface's local IP for the HA config flow

---

*Last updated: All tasks (3–15) complete — integration is feature-complete and ready for HA installation.*
