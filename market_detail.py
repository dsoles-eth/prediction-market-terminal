"""
market_detail.py — Market detail modal screen.

Shown when user presses Enter on a market in the browser.
Displays: outcomes, ASCII price chart, recent trades, order book depth.
"""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING

from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Container, Horizontal, Vertical, ScrollableContainer
from textual.screen import ModalScreen
from textual.widgets import DataTable, Label, Static, LoadingIndicator

from data_feeds import DataFeed, Market, WhaleTrade

if TYPE_CHECKING:
    pass


# ── Sparkline helpers ─────────────────────────────────────────────────────────

BLOCKS = "▁▂▃▄▅▆▇█"


def sparkline(values: list[float], width: int = 24) -> str:
    if not values:
        return "─" * width
    mn, mx = min(values), max(values)
    span = mx - mn or 1e-9
    chars = [BLOCKS[int((v - mn) / span * 7)] for v in values[-width:]]
    return "".join(chars)


def ascii_chart(values: list[float], width: int = 52, height: int = 8) -> list[str]:
    """Render a simple ASCII line chart."""
    if not values or len(values) < 2:
        return ["No price history available"]
    mn, mx = min(values), max(values)
    span = mx - mn or 1e-9

    rows = []
    for row in range(height - 1, -1, -1):
        threshold = mn + span * (row / (height - 1))
        line_chars = []
        for i, v in enumerate(values[-width:]):
            above = v >= threshold
            if i > 0:
                prev = values[max(0, len(values) - width + i - 1)]
                was_above = prev >= threshold
                if above and not was_above:
                    line_chars.append("╭")
                elif not above and was_above:
                    line_chars.append("╰")
                elif above:
                    line_chars.append("─")
                else:
                    line_chars.append(" ")
            else:
                line_chars.append("─" if above else " ")

        price_label = f"{threshold:5.2f}│"
        rows.append(price_label + "".join(line_chars))

    rows.append(f"      └{'─' * min(width, len(values))}")
    return rows


def fmt_usd(v: float) -> str:
    if v >= 1_000_000:
        return f"${v/1_000_000:.1f}M"
    if v >= 1_000:
        return f"${v/1_000:.1f}K"
    return f"${v:.2f}"


# ── Modal ─────────────────────────────────────────────────────────────────────

class MarketDetailModal(ModalScreen):
    """Full-screen modal with market detail."""

    BINDINGS = [
        Binding("escape", "dismiss", "Close"),
        Binding("q", "dismiss", "Close"),
        Binding("a", "add_watchlist", "Add to Watchlist"),
        Binding("r", "remove_watchlist", "Remove from Watchlist"),
    ]

    DEFAULT_CSS = """
    MarketDetailModal {
        align: center middle;
    }

    #modal-container {
        width: 90%;
        height: 90%;
        background: $surface;
        border: thick $accent;
        padding: 0 1;
    }

    #modal-title {
        text-align: center;
        text-style: bold;
        color: $accent;
        background: $surface-darken-1;
        padding: 0 2;
        margin-bottom: 1;
    }

    #modal-subtitle {
        color: $text-muted;
        text-align: center;
        margin-bottom: 1;
    }

    .section-header {
        text-style: bold;
        color: $warning;
        border-bottom: solid $accent-darken-2;
        margin-top: 1;
    }

    #chart-area {
        height: 12;
        border: solid $surface-lighten-2;
        padding: 0 1;
        margin-bottom: 1;
    }

    #chart-label {
        font-family: "Courier New", monospace;
        color: $success;
    }

    #outcomes-table {
        height: 8;
        margin-bottom: 1;
    }

    #trades-table {
        height: 10;
        margin-bottom: 1;
    }

    #orderbook-area {
        height: 12;
    }

    #orderbook-bids, #orderbook-asks {
        width: 1fr;
    }

    #close-hint {
        text-align: center;
        color: $text-muted;
        margin-top: 1;
    }

    LoadingIndicator {
        height: 3;
    }
    """

    def __init__(self, market: Market, feed: DataFeed, watchlist=None, **kwargs):
        super().__init__(**kwargs)
        self.market    = market
        self.feed      = feed
        self.watchlist = watchlist
        self._trades: list[WhaleTrade] = []
        self._orderbook: dict = {}

    def compose(self) -> ComposeResult:
        with Container(id="modal-container"):
            yield Label(f"  {self.market.question}  ", id="modal-title")
            yield Label(
                f"Category: {self.market.category}  │  "
                f"Volume: {fmt_usd(self.market.volume)}  │  "
                f"24h Vol: {fmt_usd(self.market.volume24hr)}  │  "
                f"Liquidity: {fmt_usd(self.market.liquidity)}",
                id="modal-subtitle",
            )

            yield Label("▸ OUTCOMES", classes="section-header")
            yield DataTable(id="outcomes-table", cursor_type="row", zebra_stripes=True)

            yield Label("▸ 24H PRICE CHART  (sparkline history)", classes="section-header")
            with ScrollableContainer(id="chart-area"):
                yield Static("Loading chart…", id="chart-label")

            with Horizontal():
                with Vertical(id="orderbook-bids"):
                    yield Label("▸ ORDER BOOK — BIDS", classes="section-header")
                    yield DataTable(id="bids-table", cursor_type="none", zebra_stripes=False)
                with Vertical(id="orderbook-asks"):
                    yield Label("▸ ORDER BOOK — ASKS", classes="section-header")
                    yield DataTable(id="asks-table", cursor_type="none", zebra_stripes=False)

            yield Label("▸ RECENT TRADES", classes="section-header")
            yield DataTable(id="trades-table", cursor_type="row", zebra_stripes=True)

            yield Label("[dim]ESC / Q  to close  │  A  add watchlist  │  R  remove watchlist[/dim]", id="close-hint")

    def on_mount(self) -> None:
        self._init_outcomes_table()
        self._render_chart()
        self._init_trades_table()
        self._init_orderbook_tables()
        self.run_worker(self._load_async_data, exclusive=True)

    # ── Table init ────────────────────────────────────────────────────────────

    def _init_outcomes_table(self):
        t: DataTable = self.query_one("#outcomes-table")
        t.add_columns("Outcome", "Price", "Implied %", "Change")
        for out in self.market.outcomes:
            price = out.price
            implied = f"{price * 100:.1f}%"
            change = ""
            if self.market.price_change_pct and out.name.upper() in ("YES", "Y"):
                pct = self.market.price_change_pct
                arrow = "▲" if pct > 0 else "▼"
                change = f"{arrow} {abs(pct):.2f}%"
            style = "green" if out.name.upper() in ("YES", "Y") else "red"
            t.add_row(out.name, f"{price:.3f}", implied, change)

    def _render_chart(self):
        history = self.market.price_history
        chart_widget: Static = self.query_one("#chart-label")
        if len(history) < 2:
            spark = sparkline(history, width=50)
            chart_widget.update(
                f"Sparkline: [{('green' if history and history[-1] > history[0] else 'red')}]{spark}[/]\n"
                f"[dim](Collecting price history — updates every refresh cycle)[/dim]"
            )
            return

        chart_lines = ascii_chart(history, width=50, height=7)
        current = history[-1]
        start   = history[0]
        change  = (current - start) / start * 100 if start else 0
        color   = "green" if change >= 0 else "red"
        spark   = sparkline(history)

        text = (
            f"[{color}]{'  '.join(chart_lines[:4])}[/]\n"
            f"[{color}]{'  '.join(chart_lines[4:])}[/]\n"
            f"\nSpark: [{color}]{spark}[/]   "
            f"Current: [{color}]{current:.3f}[/]   "
            f"Change: [{color}]{change:+.2f}%[/]"
        )
        chart_widget.update(text)

    def _init_trades_table(self):
        t: DataTable = self.query_one("#trades-table")
        t.add_columns("Age", "Side", "Outcome", "Price", "Size", "ID")
        t.add_row("[dim]Loading trades…[/dim]", "", "", "", "", "")

    def _init_orderbook_tables(self):
        bids: DataTable = self.query_one("#bids-table")
        asks: DataTable = self.query_one("#asks-table")
        for tbl in (bids, asks):
            tbl.add_columns("Price", "Size", "Total")
        bids.add_row("[dim]Loading…[/dim]", "", "")
        asks.add_row("[dim]Loading…[/dim]", "", "")

    # ── Async data loading ────────────────────────────────────────────────────

    async def _load_async_data(self):
        self._trades = await self.feed.fetch_market_trades(self.market.condition_id)
        self._refresh_trades_table()

        # Try to fetch orderbook for YES token (first outcome)
        # The CLOB API requires token_id; use condition_id as fallback
        ob = await self.feed.fetch_orderbook(self.market.condition_id)
        if ob:
            self._orderbook = ob
            self._refresh_orderbook(ob)

    def _refresh_trades_table(self):
        t: DataTable = self.query_one("#trades-table")
        t.clear()
        if not self._trades:
            t.add_row("[dim]No recent trades found[/dim]", "", "", "", "", "")
            return
        for trade in self._trades[:15]:
            color = "green" if trade.side == "BUY" else "red"
            t.add_row(
                trade.age_str,
                f"[{color}]{trade.side_icon} {trade.side}[/]",
                trade.outcome,
                f"{trade.price:.3f}",
                fmt_usd(trade.size_usd),
                trade.trade_id[:12] + "…" if len(trade.trade_id) > 12 else trade.trade_id,
            )

    def _refresh_orderbook(self, ob: dict):
        bids_tbl: DataTable = self.query_one("#bids-table")
        asks_tbl: DataTable = self.query_one("#asks-table")
        bids_tbl.clear()
        asks_tbl.clear()

        bids = sorted(ob.get("bids", []), key=lambda x: float(x.get("price", 0)), reverse=True)
        asks = sorted(ob.get("asks", []), key=lambda x: float(x.get("price", 0)))

        def fill(tbl: DataTable, rows: list[dict], color: str):
            if not rows:
                tbl.add_row("[dim]—[/dim]", "[dim]—[/dim]", "[dim]—[/dim]")
                return
            cumulative = 0.0
            for entry in rows[:10]:
                p = float(entry.get("price", 0))
                s = float(entry.get("size", 0))
                cumulative += s
                tbl.add_row(
                    f"[{color}]{p:.3f}[/]",
                    f"{s:.1f}",
                    f"{cumulative:.1f}",
                )

        fill(bids_tbl, bids, "green")
        fill(asks_tbl, asks, "red")

    # ── Key actions ──────────────────────────────────────────────────────────

    def action_add_watchlist(self):
        if self.watchlist is None:
            return
        added = self.watchlist.add(
            condition_id=self.market.condition_id,
            question=self.market.question,
            current_price=self.market.best_yes_price,
            market_id=self.market.id,
        )
        self.notify(
            "Added to watchlist!" if added else "Already in watchlist",
            severity="information" if added else "warning",
        )

    def action_remove_watchlist(self):
        if self.watchlist is None:
            return
        removed = self.watchlist.remove(self.market.condition_id)
        self.notify(
            "Removed from watchlist." if removed else "Not in watchlist",
            severity="information" if removed else "warning",
        )
