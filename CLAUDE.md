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
    ├── sensor.py            # HA sensor entities (Task 9)
    ├── database.py          # SQLite CRUD layer (Task 3) — TODO
    ├── ollama_client.py     # Ollama REST client (Task 7) — TODO
    ├── parsers/             # CSV/OFX/QIF importers (Task 4) — TODO
    └── services.yaml        # Service definitions — TODO

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

| # | Task | Status |
|---|------|--------|
| 1 | GitHub repo + project structure | ✅ Done |
| 2 | HA custom component skeleton | ✅ Done (combined with Task 1) |
| 3 | SQLite transaction database | ⬜ Next |
| 4 | Statement import service (CSV/OFX/QIF) | ⬜ Pending |
| 5 | Manual transaction entry service | ⬜ Pending |
| 6 | Ollama on Surface + Neural Engine verification | ⬜ Pending (user action required) |
| 7 | Ollama client integration | ⬜ Pending |
| 8 | Auto-categorisation pipeline with learning | ⬜ Pending |
| 9 | HA sensor entities for spending metrics | ⬜ Pending |
| 10 | Lovelace spending dashboard | ⬜ Pending |
| 11 | Secure file upload panel | ⬜ Pending |
| 12 | AI deep-analysis report service | ⬜ Pending |
| 13 | Security hardening | ⬜ Pending |
| 14 | Tests + GitHub Actions CI | ⬜ Pending |
| 15 | HACS packaging + docs | ⬜ Pending |

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

*Last updated: Task 1 & 2 complete — next: Task 3 (SQLite database layer)*
