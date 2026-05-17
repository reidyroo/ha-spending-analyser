# HA Spending Analyser

A local-first Home Assistant integration for tracking and analysing household spending — powered by an on-device Ollama AI running on your LAN. No data leaves your network.

[![CI](https://github.com/reidyroo/ha-spending-analyser/actions/workflows/ci.yml/badge.svg)](https://github.com/reidyroo/ha-spending-analyser/actions/workflows/ci.yml)
[![hacs_badge](https://img.shields.io/badge/HACS-Custom-41BDF5.svg)](https://github.com/hacs/integration)

---

## Features

- **Import bank statements** — CSV (midata, First Direct, John Lewis/Newday, CommBank, ANZ, NAB, Westpac), OFX/QFX, QIF
- **AI categorisation** — transactions are automatically categorised by a local Ollama model on import
- **Learning** — correcting a category teaches the AI for all future imports
- **6 AI report types** — monthly summary, budget health check, savings tips, month comparison, category deep dive, year-to-date overview
- **6 HA sensor entities** — monthly spending, income, net, top category, uncategorised count, total transactions
- **Lovelace custom card** — drag-and-drop spending dashboard with category bar chart
- **Secure upload panel** — browser-based file import with rate limiting and file validation
- **Privacy** — all data stays on your local network; SQLite database included in HA backups

---

## Requirements

| Requirement | Notes |
|---|---|
| Home Assistant | ≥ 2024.1.0 |
| Python | ≥ 3.11 |
| [Ollama](https://ollama.com) | Running on your LAN (e.g. Surface Pro, NUC, Raspberry Pi 5) |
| Ollama model | `phi3:mini` recommended — pull with `ollama pull phi3:mini` |

---

## Installation

### HACS (recommended)

1. Open HACS → **Integrations** → ⋮ → **Custom repositories**
2. Add `https://github.com/reidyroo/ha-spending-analyser` as an **Integration**
3. Search for **HA Spending Analyser** and install
4. Restart Home Assistant

### Manual

1. Copy `custom_components/spending_analyser/` into your HA config's `custom_components/` folder
2. Restart Home Assistant

---

## Configuration

1. Go to **Settings → Devices & Services → Add Integration → Spending Analyser**
2. Enter your Ollama server details:
   - **Host** — LAN IP of the machine running Ollama (e.g. `192.168.1.50`)
   - **Port** — default `11434`
   - **Model** — default `phi3:mini`
3. Click **Submit** — HA will test the connection before saving

> The database is stored at `config/spending_analyser/spending_analyser.db` and is included in standard HA backups.

---

## Lovelace Dashboard Card

### 1. Register the card resource

**Settings → Dashboards → Resources → Add resource:**
- URL: `/local/spending_analyser/spending-dashboard-card.js`
- Type: JavaScript module

Copy `www/spending_analyser/` to your HA config's `www/` folder first.

### 2. Add the card

```yaml
type: custom:spending-dashboard-card
title: Spending Dashboard
currency: "£"
spending_entity:      sensor.spending_analyser_monthly_spending
income_entity:        sensor.spending_analyser_monthly_income
net_entity:           sensor.spending_analyser_monthly_net
uncategorised_entity: sensor.spending_analyser_uncategorised_transactions
total_entity:         sensor.spending_analyser_total_transactions
```

A full example dashboard is in [`lovelace/spending_dashboard.yaml`](lovelace/spending_dashboard.yaml).

---

## Importing Statements

### Via the sidebar panel

Navigate to **Import Statement** in the HA sidebar. Drag and drop a statement file and click **Import**.

### Via Developer Tools → Services

```yaml
service: spending_analyser.import_statement
data:
  file_path: /config/statements/may_2026.csv
  categorise: true
```

The file must be within your HA config directory.

### Supported formats

| Format | Auto-detected banks |
|---|---|
| CSV | midata (UK), First Direct, John Lewis/Newday, CommBank, ANZ, NAB, Westpac, St George/BOQ, generic |
| OFX / QFX | All banks supporting OFX v1 (SGML) or v2 (XML) |
| QIF | Quicken Interchange Format |

---

## Services

| Service | Description |
|---|---|
| `spending_analyser.import_statement` | Import a statement file from the HA config directory |
| `spending_analyser.add_transaction` | Add a single transaction manually |
| `spending_analyser.recategorise` | Fix a transaction's category and teach the AI |
| `spending_analyser.generate_report` | Generate an AI narrative report via Ollama |

---

## AI Reports

Call `spending_analyser.generate_report` from **Developer Tools → Services**:

```yaml
service: spending_analyser.generate_report
data:
  prompt: monthly_summary
  currency: "£"
```

| Prompt | Description |
|---|---|
| `monthly_summary` | Friendly 2-3 paragraph overview of the month |
| `budget_health` | 🟢/🟡/🔴 health rating with concerns and positives |
| `savings_tips` | Top 3 personalised, data-driven savings recommendations |
| `month_comparison` | What changed vs last month and whether it's concerning |
| `category_spotlight` | Deep dive into one category (add `category: "Dining & Takeaway"`) |
| `annual_overview` | Year-to-date patterns and priorities for the rest of the year |

Reports appear as **persistent notifications** in HA and are saved as Markdown files in `config/spending_analyser/reports/`.

---

## Sensors

All sensors are grouped under the **Spending Analyser** device.

| Entity | State | Key attributes |
|---|---|---|
| `sensor.spending_analyser_monthly_spending` | £ total expenses | `by_category` dict |
| `sensor.spending_analyser_monthly_income` | £ total income | — |
| `sensor.spending_analyser_monthly_net` | £ net (+ = surplus) | — |
| `sensor.spending_analyser_top_spending_category` | Category name | amount, count |
| `sensor.spending_analyser_uncategorised_transactions` | Count | `sample` list of first 10 |
| `sensor.spending_analyser_total_transactions` | Cumulative count | — |

Sensors refresh every 15 minutes (configurable in `const.py`).

---

## Ollama Model Recommendations

| Model | RAM | Notes |
|---|---|---|
| `phi3:mini` ⭐ | ~2.2 GB | Default. NPU-accelerated on Surface Pro. Fast, reliable categorisation. |
| `llama3.2:3b` | ~2.0 GB | Good alternative if phi3 misfires on edge cases. |
| `gemma2:2b` | ~1.6 GB | Smallest footprint. Good if RAM is constrained. |

```bash
ollama pull phi3:mini
```

---

## Development

```bash
git clone https://github.com/reidyroo/ha-spending-analyser
cd ha-spending-analyser
pip install -r requirements_test.txt
pytest tests/ -v
```

---

## Privacy & Security

- No data is sent to external services — Ollama runs on your LAN
- The upload API requires a valid HA bearer token (`requires_auth = True`)
- File uploads are validated (extension whitelist, magic bytes, 10 MB limit, rate-limited)
- File paths in service calls are constrained to the HA config directory
- The SQLite database is local and included in HA backups

---

## Licence

MIT — see [LICENSE](LICENSE)
