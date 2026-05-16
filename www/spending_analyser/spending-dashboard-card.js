/**
 * Spending Dashboard Card — HA Spending Analyser
 * Local-first, no external dependencies.
 * Register in Lovelace resources as /local/spending_analyser/spending-dashboard-card.js
 */

const CARD_VERSION = '1.0.0';
const MONTH_NAMES = ['January','February','March','April','May','June',
                     'July','August','September','October','November','December'];
const EXCLUDED_FROM_CHART = new Set(['Income','Transfer','Savings & Investments']);
const MAX_CHART_BARS = 8;

/* ── Colour palette for categories (cycles if more than defined) ── */
const BAR_COLOURS = [
  '#4A90D9','#E67E22','#27AE60','#8E44AD','#E74C3C',
  '#16A085','#F39C12','#2980B9','#D35400','#1ABC9C',
];

/* ─────────────────────────────────────────────────────────────────
   Card element
───────────────────────────────────────────────────────────────── */
class SpendingDashboardCard extends HTMLElement {
  constructor() {
    super();
    this.attachShadow({ mode: 'open' });
    this._config = null;
    this._hass = null;
  }

  /* Called by HA when the user saves card config */
  setConfig(config) {
    if (!config.spending_entity) {
      throw new Error('spending_entity is required');
    }
    this._config = {
      title: 'Spending Dashboard',
      currency: '£',
      max_categories: MAX_CHART_BARS,
      spending_entity:       config.spending_entity,
      income_entity:         config.income_entity         || null,
      net_entity:            config.net_entity             || null,
      uncategorised_entity:  config.uncategorised_entity  || null,
      total_entity:          config.total_entity           || null,
      ...config,
    };
    this._render();
  }

  /* Called by HA on every state update */
  set hass(hass) {
    this._hass = hass;
    this._render();
  }

  getCardSize() { return 6; }

  static getStubConfig() {
    return {
      spending_entity:      'sensor.spending_analyser_monthly_spending',
      income_entity:        'sensor.spending_analyser_monthly_income',
      net_entity:           'sensor.spending_analyser_monthly_net',
      uncategorised_entity: 'sensor.spending_analyser_uncategorised_transactions',
      total_entity:         'sensor.spending_analyser_total_transactions',
      currency:             '£',
    };
  }

  /* ── Render ── */
  _render() {
    if (!this._hass || !this._config) return;

    const cfg = this._config;
    const cur = cfg.currency;

    const spendState  = this._state(cfg.spending_entity);
    const incomeState = this._state(cfg.income_entity);
    const netState    = this._state(cfg.net_entity);
    const uncatState  = this._state(cfg.uncategorised_entity);
    const totalState  = this._state(cfg.total_entity);

    const spending    = parseFloat(spendState?.state  ?? 0);
    const income      = parseFloat(incomeState?.state ?? 0);
    const net         = parseFloat(netState?.state    ?? 0);
    const uncatCount  = parseInt(uncatState?.state    ?? 0, 10);
    const totalTx     = parseInt(totalState?.state    ?? 0, 10);

    const byCategory  = spendState?.attributes?.by_category ?? {};
    const periodStart = spendState?.attributes?.period_start ?? '';

    const monthLabel  = _monthLabel(periodStart);
    const netPositive = net >= 0;

    /* Build category rows, sorted desc, filtered */
    const catRows = Object.entries(byCategory)
      .filter(([cat]) => !EXCLUDED_FROM_CHART.has(cat))
      .sort(([,a],[,b]) => b - a)
      .slice(0, cfg.max_categories);

    const maxCatAmount = catRows.length ? catRows[0][1] : 1;

    this.shadowRoot.innerHTML = `
      <style>${this._css()}</style>
      <ha-card>
        <div class="card-header">
          <span class="title">${cfg.title}</span>
          <span class="period">${monthLabel}</span>
        </div>

        <div class="card-body">

          <!-- Hero total -->
          <div class="hero">
            <div class="hero-amount">${cur}${_fmt(spending)}</div>
            <div class="hero-label">spent this month</div>
          </div>

          <!-- Income / Net row -->
          ${(incomeState || netState) ? `
          <div class="summary-row">
            ${incomeState ? `
            <div class="summary-pill income">
              <span class="pill-icon">↑</span>
              <span class="pill-label">Income</span>
              <span class="pill-value">${cur}${_fmt(income)}</span>
            </div>` : ''}
            ${netState ? `
            <div class="summary-pill ${netPositive ? 'surplus' : 'deficit'}">
              <span class="pill-icon">${netPositive ? '✓' : '!'}</span>
              <span class="pill-label">${netPositive ? 'Surplus' : 'Deficit'}</span>
              <span class="pill-value">${netPositive ? '+' : '−'}${cur}${_fmt(Math.abs(net))}</span>
            </div>` : ''}
          </div>` : ''}

          <!-- Category bar chart -->
          ${catRows.length ? `
          <div class="section-heading">Category Breakdown</div>
          <div class="chart">
            ${catRows.map(([cat, amt], i) => `
            <div class="bar-row">
              <div class="bar-label" title="${cat}">${cat}</div>
              <div class="bar-track">
                <div class="bar-fill"
                     style="width:${_pct(amt, maxCatAmount)}%;background:${BAR_COLOURS[i % BAR_COLOURS.length]}">
                </div>
              </div>
              <div class="bar-amount">${cur}${_fmt(amt)}</div>
            </div>`).join('')}
          </div>` : `
          <div class="empty-chart">No spending data for this period</div>`}

          <!-- Footer stats -->
          <div class="footer">
            ${totalState ? `<span class="stat">${totalTx.toLocaleString()} transactions total</span>` : ''}
            ${uncatCount > 0 ? `
            <span class="stat warn">
              ⚠ ${uncatCount} uncategorised
            </span>` : ''}
          </div>

          <!-- Uncategorised sample -->
          ${uncatCount > 0 && uncatState?.attributes?.sample?.length ? `
          <details class="uncat-details">
            <summary>Review uncategorised transactions</summary>
            <table class="uncat-table">
              <thead><tr><th>Date</th><th>Description</th><th>Amount</th></tr></thead>
              <tbody>
                ${uncatState.attributes.sample.map(tx => `
                <tr>
                  <td>${tx.date}</td>
                  <td class="desc">${tx.description}</td>
                  <td class="amt ${tx.amount < 0 ? 'neg' : 'pos'}">${tx.amount < 0 ? '−' : '+'}${cur}${_fmt(Math.abs(tx.amount))}</td>
                </tr>`).join('')}
              </tbody>
            </table>
            <p class="uncat-hint">Use <code>spending_analyser.recategorise</code> in Developer Tools → Services to fix these.</p>
          </details>` : ''}

        </div>
      </ha-card>`;
  }

  _state(entityId) {
    if (!entityId || !this._hass) return null;
    return this._hass.states[entityId] ?? null;
  }

  _css() {
    return `
      ha-card {
        font-family: var(--primary-font-family, sans-serif);
        color: var(--primary-text-color);
        overflow: hidden;
      }
      .card-header {
        display: flex;
        justify-content: space-between;
        align-items: baseline;
        padding: 16px 20px 0;
      }
      .title {
        font-size: 1.1rem;
        font-weight: 600;
        color: var(--primary-text-color);
      }
      .period {
        font-size: 0.82rem;
        color: var(--secondary-text-color);
      }
      .card-body {
        padding: 12px 20px 16px;
      }

      /* Hero */
      .hero {
        text-align: center;
        padding: 16px 0 12px;
      }
      .hero-amount {
        font-size: 2.6rem;
        font-weight: 700;
        letter-spacing: -1px;
        color: var(--primary-color);
      }
      .hero-label {
        font-size: 0.8rem;
        color: var(--secondary-text-color);
        margin-top: 2px;
      }

      /* Pills */
      .summary-row {
        display: flex;
        gap: 10px;
        justify-content: center;
        margin-bottom: 18px;
        flex-wrap: wrap;
      }
      .summary-pill {
        display: flex;
        align-items: center;
        gap: 6px;
        padding: 6px 14px;
        border-radius: 20px;
        font-size: 0.85rem;
        background: var(--secondary-background-color);
      }
      .pill-icon { font-size: 0.9rem; }
      .pill-label { color: var(--secondary-text-color); }
      .pill-value { font-weight: 600; }
      .income .pill-icon  { color: #27AE60; }
      .surplus .pill-icon { color: #27AE60; }
      .surplus .pill-value{ color: #27AE60; }
      .deficit .pill-icon { color: #E74C3C; }
      .deficit .pill-value{ color: #E74C3C; }

      /* Chart */
      .section-heading {
        font-size: 0.78rem;
        font-weight: 600;
        text-transform: uppercase;
        letter-spacing: 0.06em;
        color: var(--secondary-text-color);
        margin-bottom: 10px;
      }
      .chart { display: flex; flex-direction: column; gap: 7px; }
      .bar-row {
        display: grid;
        grid-template-columns: 130px 1fr 68px;
        align-items: center;
        gap: 8px;
      }
      .bar-label {
        font-size: 0.82rem;
        white-space: nowrap;
        overflow: hidden;
        text-overflow: ellipsis;
        color: var(--primary-text-color);
      }
      .bar-track {
        background: var(--secondary-background-color);
        border-radius: 4px;
        height: 10px;
        overflow: hidden;
      }
      .bar-fill {
        height: 100%;
        border-radius: 4px;
        transition: width 0.4s ease;
        min-width: 4px;
      }
      .bar-amount {
        font-size: 0.82rem;
        text-align: right;
        color: var(--secondary-text-color);
      }

      .empty-chart {
        text-align: center;
        color: var(--secondary-text-color);
        font-size: 0.85rem;
        padding: 20px 0;
      }

      /* Footer */
      .footer {
        display: flex;
        justify-content: space-between;
        flex-wrap: wrap;
        gap: 4px;
        margin-top: 14px;
        padding-top: 10px;
        border-top: 1px solid var(--divider-color);
      }
      .stat {
        font-size: 0.78rem;
        color: var(--secondary-text-color);
      }
      .stat.warn { color: #E67E22; font-weight: 600; }

      /* Uncategorised details */
      .uncat-details {
        margin-top: 10px;
        font-size: 0.82rem;
      }
      .uncat-details summary {
        cursor: pointer;
        color: var(--primary-color);
        padding: 4px 0;
      }
      .uncat-table {
        width: 100%;
        border-collapse: collapse;
        margin-top: 8px;
        font-size: 0.8rem;
      }
      .uncat-table th {
        text-align: left;
        color: var(--secondary-text-color);
        font-weight: 600;
        padding: 4px 6px;
        border-bottom: 1px solid var(--divider-color);
      }
      .uncat-table td { padding: 4px 6px; }
      .uncat-table .desc {
        max-width: 180px;
        overflow: hidden;
        text-overflow: ellipsis;
        white-space: nowrap;
      }
      .uncat-table .neg { color: #E74C3C; text-align: right; }
      .uncat-table .pos { color: #27AE60; text-align: right; }
      .uncat-hint {
        margin-top: 8px;
        color: var(--secondary-text-color);
        font-size: 0.75rem;
      }
      .uncat-hint code {
        background: var(--secondary-background-color);
        padding: 1px 4px;
        border-radius: 3px;
        font-size: 0.73rem;
      }
    `;
  }
}

/* ── Helpers ── */
function _fmt(n) {
  return Number(n).toLocaleString('en-GB', { minimumFractionDigits: 2, maximumFractionDigits: 2 });
}

function _pct(value, max) {
  if (!max) return 0;
  return Math.max(2, Math.round((value / max) * 100));
}

function _monthLabel(isoDate) {
  if (!isoDate) {
    const now = new Date();
    return `${MONTH_NAMES[now.getMonth()]} ${now.getFullYear()}`;
  }
  const [y, m] = isoDate.split('-').map(Number);
  return `${MONTH_NAMES[m - 1]} ${y}`;
}

/* ── Register ── */
customElements.define('spending-dashboard-card', SpendingDashboardCard);

window.customCards = window.customCards || [];
window.customCards.push({
  type:        'spending-dashboard-card',
  name:        'Spending Dashboard',
  description: 'Monthly spending overview with AI category breakdown.',
  preview:     false,
});

console.info(`%c SPENDING-DASHBOARD-CARD %c v${CARD_VERSION} `,
  'background:#4A90D9;color:#fff;font-weight:bold;padding:2px 6px;border-radius:3px 0 0 3px',
  'background:#222;color:#4A90D9;font-weight:bold;padding:2px 6px;border-radius:0 3px 3px 0');
