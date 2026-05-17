"""AI spending report generator — builds DB context and calls Ollama for narrative analysis."""
from __future__ import annotations

import logging
import os
from datetime import date, timedelta
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from .database import SpendingDatabase
    from .ollama_client import OllamaClient

_LOGGER = logging.getLogger(__name__)

# Categories excluded from "expenses" totals in report context
_INCOME_CATS = {"Income", "Transfer", "Savings & Investments"}

# ---------------------------------------------------------------------------
# Prompt library
# ---------------------------------------------------------------------------

REPORT_PROMPTS: dict[str, dict[str, str]] = {
    "monthly_summary": {
        "name": "Monthly Summary",
        "description": "Friendly 2-3 paragraph overview of this month's spending.",
        "system": (
            "You are a warm, supportive personal finance assistant. "
            "Write a friendly, conversational summary of the user's spending this month. "
            "Use clear language — no jargon. Mention the biggest categories, highlight "
            "anything noteworthy, and close with an encouraging sentence. "
            "Keep it to 2-3 short paragraphs."
        ),
        "user": (
            "Here is my spending data for {month_label}:\n\n{context}\n\n"
            "Please write a friendly monthly summary for me."
        ),
    },
    "budget_health": {
        "name": "Budget Health Check",
        "description": "Structured health check — flags concerns, rates overall health Green/Amber/Red.",
        "system": (
            "You are an experienced financial advisor reviewing a client's monthly statement. "
            "Provide a structured budget health check. "
            "Rate overall health as 🟢 Green, 🟡 Amber, or 🔴 Red and justify it in one sentence. "
            "Then list up to 3 concerns (if any) and up to 3 positives. "
            "Be direct and honest, not alarmist. Use bullet points."
        ),
        "user": (
            "Please review my spending for {month_label}:\n\n{context}\n\n"
            "Give me a budget health check."
        ),
    },
    "savings_tips": {
        "name": "Savings Opportunities",
        "description": "Top 3 concrete, personalised ways to reduce spending next month.",
        "system": (
            "You are a practical personal finance coach. "
            "Based only on the spending data provided, identify the top 3 specific, actionable "
            "ways this person could reduce their expenses next month. "
            "Be concrete — name the actual category or merchant, suggest a realistic target amount "
            "where possible, and explain the rationale briefly. "
            "Do not give generic advice like 'make a budget' — refer to their actual numbers."
        ),
        "user": (
            "Here is my spending breakdown for {month_label}:\n\n{context}\n\n"
            "What are my top 3 savings opportunities for next month?"
        ),
    },
    "month_comparison": {
        "name": "Month-on-Month Comparison",
        "description": "Compares this month to last month — flags significant changes.",
        "system": (
            "You are a financial analyst comparing two months of spending data. "
            "Identify which categories increased or decreased significantly (>10%). "
            "Write 2 concise paragraphs: first paragraph covers notable increases, "
            "second covers decreases or stable areas. "
            "End with a one-sentence verdict on whether this month's trend is positive or concerning."
        ),
        "user": (
            "Compare my spending:\n\n{context}\n\n"
            "Highlight the key changes between {prev_month_label} and {month_label}."
        ),
    },
    "category_spotlight": {
        "name": "Category Deep Dive",
        "description": "In-depth analysis of a single spending category.",
        "system": (
            "You are a personal finance expert doing a deep dive into one spending category. "
            "Analyse the transaction data for the category provided. Comment on: "
            "total amount, frequency, average transaction size, any patterns you spot, "
            "and whether the spend level seems reasonable. "
            "Suggest 1-2 specific ways to optimise this category if appropriate. "
            "Be conversational but precise."
        ),
        "user": (
            "Here is all my '{category}' spending for {month_label}:\n\n{context}\n\n"
            "Give me a deep dive analysis of this category."
        ),
    },
    "annual_overview": {
        "name": "Year-to-Date Overview",
        "description": "Identifies long-term patterns and habits across all available data.",
        "system": (
            "You are a personal finance expert providing a year-to-date review. "
            "Identify the user's dominant spending categories, any seasonal patterns visible, "
            "and overall financial habits. "
            "Write 3 sections: Key Patterns, Strengths, and Priorities for the rest of the year. "
            "Use the data provided — do not invent figures."
        ),
        "user": (
            "Here is my spending data across the available period:\n\n{context}\n\n"
            "Give me a year-to-date overview and forward-looking insights."
        ),
    },
}


# ---------------------------------------------------------------------------
# Context builders
# ---------------------------------------------------------------------------

def _iso_month(year: int, month: int) -> tuple[str, str]:
    first = date(year, month, 1)
    if month == 12:
        last = date(year, 12, 31)
    else:
        last = date(year, month + 1, 1) - timedelta(days=1)
    return first.isoformat(), last.isoformat()


def _month_name(year: int, month: int) -> str:
    return date(year, month, 1).strftime("%B %Y")


def _prev_month(year: int, month: int) -> tuple[int, int]:
    if month == 1:
        return year - 1, 12
    return year, month - 1


def _fmt(amount: float, currency: str = "£") -> str:
    return f"{currency}{abs(amount):,.2f}"


async def _category_context(
    db: "SpendingDatabase",
    date_from: str,
    date_to: str,
    currency: str,
    month_label: str,
    category: str,
) -> str:
    """Build context for the category spotlight prompt."""
    rows = await db.async_get_transactions(
        category=category, date_from=date_from, date_to=date_to, limit=200
    )
    if not rows:
        return f"No transactions found in '{category}' for {month_label}."

    total = sum(abs(r["amount"]) for r in rows if r["amount"] < 0)
    avg = total / len(rows) if rows else 0
    lines = [
        f"Category: {category}",
        f"Period: {month_label}",
        f"Total: {_fmt(total, currency)}",
        f"Transactions: {len(rows)}",
        f"Average: {_fmt(avg, currency)}",
        "",
        "Individual transactions:",
    ]
    for r in rows[:30]:
        lines.append(f"  {r['date']}  {r['description'][:45]}  {_fmt(r['amount'], currency)}")
    if len(rows) > 30:
        lines.append(f"  ... and {len(rows) - 30} more")
    return "\n".join(lines)


async def _monthly_context(
    db: "SpendingDatabase",
    year: int,
    month: int,
    currency: str,
    include_prev: bool = False,
) -> tuple[str, str]:
    """Build spending context for one (optionally two) months. Returns (context, month_label)."""
    date_from, date_to = _iso_month(year, month)
    month_label = _month_name(year, month)

    cat_rows = await db.async_get_spending_by_category(date_from, date_to)
    all_rows  = await db.async_get_transactions(date_from=date_from, date_to=date_to, limit=5000)

    total_expense = sum(abs(r["total"]) for r in cat_rows)
    total_income  = sum(r["amount"] for r in all_rows if r["amount"] > 0)
    net = total_income - total_expense

    lines = [
        f"=== {month_label} ===",
        f"Total expenses : {_fmt(total_expense, currency)}",
        f"Total income   : {_fmt(total_income, currency)}",
        f"Net            : {'+'if net>=0 else '-'}{_fmt(net, currency)}",
        "",
        "Expense breakdown by category:",
    ]
    for r in cat_rows:
        if r["category"] not in _INCOME_CATS and r["total"] < 0:
            pct = (abs(r["total"]) / total_expense * 100) if total_expense else 0
            lines.append(
                f"  {r['category']:<28} {_fmt(r['total'], currency):>10}  ({pct:.0f}%)"
            )

    # Top 5 individual transactions this month
    big_tx = sorted(
        [r for r in all_rows if r["amount"] < 0],
        key=lambda r: r["amount"]
    )[:5]
    if big_tx:
        lines += ["", "Largest individual expenses:"]
        for r in big_tx:
            lines.append(f"  {r['date']}  {r['description'][:40]}  {_fmt(r['amount'], currency)}")

    context = "\n".join(lines)

    if include_prev:
        py, pm = _prev_month(year, month)
        prev_from, prev_to = _iso_month(py, pm)
        prev_label = _month_name(py, pm)
        prev_cat = await db.async_get_spending_by_category(prev_from, prev_to)
        prev_expense = sum(abs(r["total"]) for r in prev_cat)
        prev_all = await db.async_get_transactions(date_from=prev_from, date_to=prev_to, limit=5000)
        prev_income = sum(r["amount"] for r in prev_all if r["amount"] > 0)
        prev_net = prev_income - prev_expense

        prev_lines = [
            f"\n=== {prev_label} (previous month) ===",
            f"Total expenses : {_fmt(prev_expense, currency)}",
            f"Total income   : {_fmt(prev_income, currency)}",
            f"Net            : {'+'if prev_net>=0 else '-'}{_fmt(prev_net, currency)}",
            "",
            "Expense breakdown by category:",
        ]
        for r in prev_cat:
            if r["category"] not in _INCOME_CATS and r["total"] < 0:
                pct = (abs(r["total"]) / prev_expense * 100) if prev_expense else 0
                prev_lines.append(
                    f"  {r['category']:<28} {_fmt(r['total'], currency):>10}  ({pct:.0f}%)"
                )
        context += "\n" + "\n".join(prev_lines)

    return context, month_label


async def _annual_context(
    db: "SpendingDatabase", currency: str, months_back: int = 12
) -> str:
    """Build aggregated context across multiple months."""
    today = date.today()
    lines: list[str] = ["Year-to-date spending summary:"]
    for i in range(months_back - 1, -1, -1):
        # Walk backwards from months_back to current month
        d = (today.replace(day=1) - timedelta(days=1)) if i > 0 else today
        for _ in range(i):
            d = (d.replace(day=1) - timedelta(days=1))
        y, m = d.year, d.month
        date_from, date_to = _iso_month(y, m)
        cat_rows = await db.async_get_spending_by_category(date_from, date_to)
        total = sum(abs(r["total"]) for r in cat_rows)
        label = _month_name(y, m)
        lines.append(f"  {label:<18}  {_fmt(total, currency):>10}")

    lines += ["", "Category totals (year-to-date):"]
    ytd_from = (today.replace(day=1) - timedelta(days=30 * (months_back - 1))).replace(day=1).isoformat()
    ytd_to   = today.isoformat()
    ytd_rows = await db.async_get_spending_by_category(ytd_from, ytd_to)
    for r in ytd_rows:
        if r["category"] not in _INCOME_CATS:
            lines.append(f"  {r['category']:<28}  {_fmt(r['total'], currency):>10}")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Public generator
# ---------------------------------------------------------------------------

class ReportGenerator:
    def __init__(
        self,
        db: "SpendingDatabase",
        ollama: "OllamaClient",
        currency: str = "£",
        reports_dir: str = "",
    ) -> None:
        self._db = db
        self._ollama = ollama
        self._currency = currency
        self._reports_dir = reports_dir

    async def async_generate(
        self,
        prompt_key: str,
        category: str | None = None,
        year: int | None = None,
        month: int | None = None,
        months_back: int = 12,
    ) -> dict[str, Any]:
        """Generate a report. Returns dict with 'title', 'text', 'file_path'."""
        if prompt_key not in REPORT_PROMPTS:
            raise ValueError(f"Unknown prompt key '{prompt_key}'. Valid: {list(REPORT_PROMPTS)}")

        today = date.today()
        year  = year  or today.year
        month = month or today.month
        prompt_def = REPORT_PROMPTS[prompt_key]

        # ── Build context ──────────────────────────────────────────
        month_label = _month_name(year, month)
        py, pm = _prev_month(year, month)
        prev_month_label = _month_name(py, pm)

        if prompt_key == "category_spotlight":
            if not category:
                raise ValueError("'category' is required for the category_spotlight prompt")
            date_from, date_to = _iso_month(year, month)
            context = await _category_context(
                self._db, date_from, date_to, self._currency, month_label, category
            )
        elif prompt_key == "month_comparison":
            context, _ = await _monthly_context(
                self._db, year, month, self._currency, include_prev=True
            )
        elif prompt_key == "annual_overview":
            context = await _annual_context(self._db, self._currency, months_back)
        else:
            context, _ = await _monthly_context(self._db, year, month, self._currency)

        # ── Fill prompt templates ──────────────────────────────────
        user_message = prompt_def["user"].format(
            context=context,
            month_label=month_label,
            prev_month_label=prev_month_label,
            category=category or "",
        )

        _LOGGER.info("Generating '%s' report via Ollama…", prompt_def["name"])

        # ── Call Ollama ────────────────────────────────────────────
        report_text = await self._ollama.async_generate_report(
            system_prompt=prompt_def["system"],
            user_message=user_message,
        )

        title = f"{prompt_def['name']} — {month_label}"

        # ── Save to file ───────────────────────────────────────────
        file_path: str | None = None
        if self._reports_dir:
            os.makedirs(self._reports_dir, exist_ok=True)
            slug = f"{year:04d}-{month:02d}_{prompt_key}"
            file_path = os.path.join(self._reports_dir, f"{slug}.md")
            with open(file_path, "w", encoding="utf-8") as fh:
                fh.write(f"# {title}\n\n")
                fh.write(f"*Generated by Spending Analyser · {today.isoformat()}*\n\n")
                fh.write("---\n\n")
                fh.write(report_text)
                fh.write("\n\n---\n\n## Raw data used\n\n```\n")
                fh.write(context)
                fh.write("\n```\n")
            _LOGGER.info("Report saved to %s", file_path)

        return {
            "title":     title,
            "text":      report_text,
            "file_path": file_path,
            "prompt":    prompt_key,
        }
