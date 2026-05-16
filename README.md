# HA Spending Analyser

A Home Assistant custom component for tracking personal spending — entirely on your local network, with Edge AI categorisation powered by [Ollama](https://ollama.com) running on your own hardware.

## Features

- Import bank/credit card statements (CSV, OFX, QIF) directly from the HA dashboard
- Manual transaction entry via the HA interface
- Automatic categorisation using a local LLM (no data leaves your network)
- HA sensor entities for spending metrics — use them in automations or history graphs
- Lovelace dashboard with charts, trends, and category breakdowns
- AI-generated spending analysis reports (monthly patterns, anomalies, savings suggestions)
- HACS-installable

## Requirements

- Home Assistant 2024.1.0 or later
- [Ollama](https://ollama.com) running on a machine on your LAN (e.g. a Surface Pro with Neural Engine)
- Recommended model: `phi3:mini` (fast, low resource usage)

## Installation

### Via HACS (recommended)
1. Add this repo as a custom HACS repository.
2. Install **HA Spending Analyser**.
3. Restart Home Assistant.

### Manual
Copy `custom_components/spending_analyser/` into your HA `config/custom_components/` folder and restart.

## Setup

1. Go to **Settings → Devices & Services → Add Integration**.
2. Search for **Spending Analyser**.
3. Enter your Ollama host IP, port (default 11434), and model name.
4. The integration will test connectivity and complete setup.

## Ollama (Edge AI) Setup

```bash
# Install Ollama on your Surface / local machine
# https://ollama.com/download

ollama pull phi3:mini

# Verify it's reachable from your HA host
curl http://<your-machine-ip>:11434/api/tags
```

To verify Neural Engine usage on Windows: open Task Manager → Performance → NPU — usage should spike during inference.

## Privacy

All financial data is stored in a local SQLite database inside your HA config directory and is included in HA backups. Ollama calls are LAN-only. No data is ever sent to external services.

## Development Status

See [CLAUDE.md](CLAUDE.md) for the full build task tracker and architecture notes.
