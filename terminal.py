"""
terminal.py — Polymarket Bloomberg Terminal

4-panel TUI:
  ┌──────────────────────┬──────────────────────┐
  │  TOP MOVERS          │  WHALE ACTIVITY       │
  ├──────────────────────┼──────────────────────┤
  │  MARKET BROWSER      │  WATCHLIST / POS.     │
  └──────────────────────┴──────────────────────┘
  [ STATUS BAR ]
"""

from __future__ import annotations

import asyncio
from datetime import datetime
from typing import ClassVar

from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Container, Horizontal, Vertical
from textual.reactive import reactive
from textual.widgets import (
    DataTable,
    Footer,
    Header,
    Label,
    Static,
)
from textual.widgets._data_table import RowKey

from data_feeds import DataFeed, Market, WhaleTrade
from market_detail import MarketDetailModal, sparkline, fmt_usd
from watchlist import Watchlist

# ── Colour helpers ────────────────────────────────────────────────────────────

def price_color(price: float) -> str:
    if price >= 0.7:
        return "bright_green"
    if price >= 0.5:
        return "green"
    if price >= 0.3:
        return "yellow"
    return "red"


def change_markup(pct: float, compact: bool = False) -> str:
    if pct > 0:
        icon = "▲"
        color = "green"
    elif pct < 0:
        icon = "▼"
        color = "red"
    else:
        icon = "─"
        color = "dim"
    val = f"{abs(pct):.2f}%" if not compact else f"{abs(pct):.1f}%"
    return f"[{color}]{icon} {val}[/]"


def truncate(s: str, n: int) -> str:
    return s if len(s) <= n else s[: n - 1] + "…"


# ── Panels ────────────────────────────────────────────────────────────────────

class PanelHeader(Static):
    """A styled panel title bar."""

    DEFAULT_CSS = """
    PanelHeader {
        background: $accent-darken-2;
        color: $text;
        text-style: bold;
        padding: 0 2;
        height: 1;
    }
    """


class TopMoversPanel(Vertical):
    DEFAULT_CSS = """
    TopMoversPanel {
        border: solid $accent-darken-2;
        height: 100%;
    }
    #movers-table {
        height: 1fr;
    }
    """

    def compose(self) -> ComposeResult:
        yield PanelHeader("▲▼  TOP MOVERS  — biggest % moves (last refresh)")
        yield DataTable(id="movers-table", cursor_type="row", zebra_stripes=True)

    def on_mount(self):
        t: DataTable = self.query_one("#movers-table")
        t.add_columns("Market", "YES", "Change", "Spark", "Vol 24h")

    def refresh_data(self, movers: list[Market]):
        t: DataTable = self.query_one("#movers-table")
        t.clear()
        for m in movers[:18]:
            yes = m.best_yes_price
            c_pct = m.price_change_pct
            spark = sparkline(m.price_history, width=10)
            color = "green" if c_pct > 0 else ("red" if c_pct < 0 else "dim")
            t.add_row(
                truncate(m.question, 32),
                f"[{price_color(yes)}]{yes:.3f}[/]",
                change_markup(c_pct),
                f"[{color}]{spark}[/]",
                fmt_usd(m.volume24hr),
                key=m.id,
            )


class WhaleActivityPanel(Vertical):
    DEFAULT_CSS = """
    WhaleActivityPanel {
        border: solid $accent-darken-2;
        height: 100%;
    }
    #whale-table {
        height: 1fr;
    }
    """

    def compose(self) -> ComposeResult:
        yield PanelHeader("🐋  WHALE ACTIVITY  — large trades  (live)")
        yield DataTable(id="whale-table", cursor_type="row", zebra_stripes=True)

    def on_mount(self):
        t: DataTable = self.query_one("#whale-table")
        t.add_columns("Age", "Side", "Market", "Out", "Price", "Size")

    def refresh_data(self, trades: list[WhaleTrade]):
        t: DataTable = self.query_one("#whale-table")
        t.clear()
        for trade in trades[:18]:
            color = "bright_green" if trade.side == "BUY" else "bright_red"
            t.add_row(
                f"[dim]{trade.age_str}[/]",
                f"[{color}]{trade.side_icon} {trade.side:<4}[/]",
                truncate(trade.question, 30),
                truncate(trade.outcome, 6),
                f"[{color}]{trade.price:.3f}[/]",
                f"[bold {color}]{fmt_usd(trade.size_usd)}[/]",
                key=trade.trade_id or str(id(trade)),
            )


class MarketBrowserPanel(Vertical):
    DEFAULT_CSS = """
    MarketBrowserPanel {
        border: solid $accent-darken-2;
        height: 100%;
    }
    #sort-bar {
        background: $surface-darken-1;
        padding: 0 2;
        height: 1;
        color: $text-muted;
    }
    #browser-table {
        height: 1fr;
    }
    """

    SORT_KEYS: ClassVar[list[str]] = ["volume24hr", "volume", "change", "price"]
    sort_index: reactive[int] = reactive(0)

    def __init__(self, feed: DataFeed, **kwargs):
        super().__init__(**kwargs)
        self._feed = feed

    def compose(self) -> ComposeResult:
        yield PanelHeader("📊  MARKET BROWSER  — ENTER to inspect  │  S to sort")
        yield Static("Sort: [bold]24h Vol[/] │ V: Volume │ P: Price │ C: Change", id="sort-bar")
        yield DataTable(id="browser-table", cursor_type="row", zebra_stripes=True)

    def on_mount(self):
        t: DataTable = self.query_one("#browser-table")
        t.add_columns("#", "Market", "YES", "NO", "Change", "Vol 24h", "Liq", "Cat")

    def refresh_data(self, markets: list[Market]):
        sort_key = self.SORT_KEYS[self.sort_index]
        if sort_key == "volume24hr":
            sorted_m = sorted(markets, key=lambda m: m.volume24hr, reverse=True)
        elif sort_key == "volume":
            sorted_m = sorted(markets, key=lambda m: m.volume, reverse=True)
        elif sort_key == "change":
            sorted_m = sorted(markets, key=lambda m: abs(m.price_change_pct), reverse=True)
        else:
            sorted_m = sorted(markets, key=lambda m: m.best_yes_price, reverse=True)

        t: DataTable = self.query_one("#browser-table")
        t.clear()
        for i, m in enumerate(sorted_m[:100], 1):
            yes = m.best_yes_price
            no  = m.best_no_price
            t.add_row(
                f"[dim]{i:3}[/]",
                truncate(m.question, 38),
                f"[{price_color(yes)}]{yes:.3f}[/]",
                f"[red]{no:.3f}[/]",
                change_markup(m.price_change_pct),
                fmt_usd(m.volume24hr),
                fmt_usd(m.liquidity),
                truncate(m.category, 12),
                key=m.id,
            )

        sort_labels = {
            "volume24hr": "[bold]24h Vol[/]",
            "volume":     "[bold]Volume[/]",
            "change":     "[bold]Change[/]",
            "price":      "[bold]Price[/]",
        }
        self.query_one("#sort-bar").update(
            f"Sort: {sort_labels[sort_key]}  │  S: cycle sort  │  ENTER: inspect"
        )

    def cycle_sort(self):
        self.sort_index = (self.sort_index + 1) % len(self.SORT_KEYS)

    def get_selected_market_id(self) -> str | None:
        t: DataTable = self.query_one("#browser-table")
        if t.cursor_row < 0:
            return None
        try:
            row_key: RowKey = t.get_row_at(t.cursor_row)
            return str(t.get_row(t.cursor_row))
        except Exception:
            return None

    def get_cursor_market(self, feed: DataFeed) -> Market | None:
        t: DataTable = self.query_one("#browser-table")
        try:
            row_key = t.coordinate_to_cell_key(
                t.cursor_coordinate
            ).row_key
            market_id = str(row_key.value)
            return feed.get_market(market_id)
        except Exception:
            return None


class WatchlistPanel(Vertical):
    DEFAULT_CSS = """
    WatchlistPanel {
        border: solid $accent-darken-2;
        height: 100%;
    }
    #watchlist-table {
        height: 1fr;
    }
    #watchlist-hint {
        background: $surface-darken-1;
        padding: 0 2;
        height: 1;
        color: $text-muted;
    }
    """

    def __init__(self, watchlist: Watchlist, **kwargs):
        super().__init__(**kwargs)
        self._watchlist = watchlist

    def compose(self) -> ComposeResult:
        yield PanelHeader("👁  WATCHLIST  /  MY POSITIONS")
        yield DataTable(id="watchlist-table", cursor_type="row", zebra_stripes=True)
        yield Static("A: add  │  R: remove  │  ENTER: inspect", id="watchlist-hint")

    def on_mount(self):
        t: DataTable = self.query_one("#watchlist-table")
        t.add_columns("Market", "Tracked", "Current", "P&L", "Note")
        self.refresh_data({})

    def refresh_data(self, feed_markets: dict[str, Market]):
        """
        feed_markets: condition_id -> Market  (from DataFeed.by_condition)
        """
        t: DataTable = self.query_one("#watchlist-table")
        t.clear()

        if not self._watchlist.entries:
            t.add_row("[dim]No markets on watchlist[/dim]", "", "", "", "")
            return

        for entry in self._watchlist:
            current = None
            m = feed_markets.get(entry.condition_id)
            if m:
                current = m.best_yes_price

            tracked_str = f"{entry.tracked_price:.3f}" if entry.tracked_price else "—"

            if current is not None:
                cur_str = f"[{price_color(current)}]{current:.3f}[/]"
                pnl = entry.pnl_pct(current)
                pnl_str = change_markup(pnl) if pnl is not None else "—"
            else:
                cur_str  = "[dim]—[/dim]"
                pnl_str  = "[dim]—[/dim]"

            t.add_row(
                truncate(entry.question, 30),
                tracked_str,
                cur_str,
                pnl_str,
                truncate(entry.note, 16),
                key=entry.condition_id,
            )

    def get_cursor_condition_id(self) -> str | None:
        t: DataTable = self.query_one("#watchlist-table")
        try:
            row_key = t.coordinate_to_cell_key(
                t.cursor_coordinate
            ).row_key
            return str(row_key.value)
        except Exception:
            return None


# ── Main App ──────────────────────────────────────────────────────────────────

APP_CSS = """
Screen {
    background: $background;
}

#app-grid {
    height: 1fr;
    layout: grid;
    grid-size: 2 2;
    grid-rows: 1fr 1fr;
    grid-columns: 1fr 1fr;
    padding: 0;
}

TopMoversPanel {
    row-span: 1;
    column-span: 1;
}

WhaleActivityPanel {
    row-span: 1;
    column-span: 1;
}

MarketBrowserPanel {
    row-span: 1;
    column-span: 1;
}

WatchlistPanel {
    row-span: 1;
    column-span: 1;
}

#status-bar {
    background: $primary-darken-2;
    color: $text;
    padding: 0 2;
    height: 1;
    text-style: italic;
}

#header-subtitle {
    dock: top;
    background: $primary-darken-3;
    color: $accent;
    text-align: center;
    text-style: bold;
    padding: 0 2;
    height: 1;
}
"""

TITLE_ART = (
    "▐█▌ POLYMARKET TERMINAL  │  Bloomberg-style prediction market feed"
)


class PolymarketTerminal(App):
    """The main Bloomberg Terminal for Polymarket."""

    TITLE   = "Polymarket Terminal"
    CSS     = APP_CSS

    BINDINGS = [
        Binding("q", "quit", "Quit",         show=True),
        Binding("r", "manual_refresh", "Refresh",     show=True),
        Binding("s", "cycle_sort",     "Sort",         show=True),
        Binding("enter", "inspect_market", "Inspect",  show=True),
        Binding("a", "add_watchlist",  "Watch",        show=True),
        Binding("w", "focus_watchlist","Watchlist",    show=True),
        Binding("b", "focus_browser",  "Browser",      show=True),
        Binding("?", "show_help",      "Help",         show=False),
        Binding("ctrl+c", "quit", "Quit",      show=False),
    ]

    def __init__(self, refresh_interval: int = 30, **kwargs):
        super().__init__(**kwargs)
        self.feed              = DataFeed(refresh_interval=refresh_interval)
        self.watchlist         = Watchlist()
        self._refresh_interval = refresh_interval
        self._active_panel     = "browser"  # "browser" | "watchlist" | "movers" | "whale"

    # ── Compose ───────────────────────────────────────────────────────────────

    def compose(self) -> ComposeResult:
        yield Header(show_clock=True)
        yield Static(TITLE_ART, id="header-subtitle")

        with Container(id="app-grid"):
            yield TopMoversPanel(id="movers-panel")
            yield WhaleActivityPanel(id="whale-panel")
            yield MarketBrowserPanel(self.feed, id="browser-panel")
            yield WatchlistPanel(self.watchlist, id="watchlist-panel")

        yield Static(
            "  ⚡ Connecting to Polymarket…",
            id="status-bar",
        )
        yield Footer()

    # ── Lifecycle ─────────────────────────────────────────────────────────────

    async def on_mount(self) -> None:
        self.feed.add_listener(self._on_data_update)
        await self.feed.start()

    async def on_unmount(self) -> None:
        await self.feed.stop()

    # ── Data callback ─────────────────────────────────────────────────────────

    async def _on_data_update(self):
        """Called by DataFeed after every successful poll."""
        self._refresh_all_panels()

    def _refresh_all_panels(self):
        # Top Movers
        movers: TopMoversPanel = self.query_one("#movers-panel")
        movers.refresh_data(self.feed.top_movers)

        # Whale Activity
        whale: WhaleActivityPanel = self.query_one("#whale-panel")
        whale.refresh_data(self.feed.whale_trades)

        # Market Browser
        browser: MarketBrowserPanel = self.query_one("#browser-panel")
        browser.refresh_data(list(self.feed.markets.values()))

        # Watchlist
        wl: WatchlistPanel = self.query_one("#watchlist-panel")
        wl.refresh_data(self.feed.by_condition)

        # Status bar
        status: Static = self.query_one("#status-bar")
        status.update(f"  ⚡ {self.feed.status_msg}")

    # ── Actions ───────────────────────────────────────────────────────────────

    def action_manual_refresh(self):
        self.notify("Refreshing data…", timeout=2)
        asyncio.create_task(self.feed._fetch_all())

    def action_cycle_sort(self):
        browser: MarketBrowserPanel = self.query_one("#browser-panel")
        browser.cycle_sort()
        browser.refresh_data(list(self.feed.markets.values()))

    def action_inspect_market(self):
        """Open detail modal for the market under cursor."""
        market = self._get_focused_market()
        if market:
            self.push_screen(
                MarketDetailModal(
                    market=market,
                    feed=self.feed,
                    watchlist=self.watchlist,
                )
            )
        else:
            self.notify("Select a market first (use arrow keys)", severity="warning")

    def action_add_watchlist(self):
        market = self._get_focused_market()
        if market is None:
            self.notify("No market selected", severity="warning")
            return
        added = self.watchlist.add(
            condition_id=market.condition_id,
            question=market.question,
            current_price=market.best_yes_price,
            market_id=market.id,
        )
        if added:
            self.notify(f"Added: {market.question[:40]}", severity="information")
            wl: WatchlistPanel = self.query_one("#watchlist-panel")
            wl.refresh_data(self.feed.by_condition)
        else:
            self.notify("Already on watchlist", severity="warning")

    def action_focus_watchlist(self):
        self._active_panel = "watchlist"
        self.query_one("#watchlist-panel").query_one("#watchlist-table").focus()

    def action_focus_browser(self):
        self._active_panel = "browser"
        self.query_one("#browser-panel").query_one("#browser-table").focus()

    def action_show_help(self):
        self.notify(
            "ENTER: inspect market  │  A: add watchlist  │  S: cycle sort  │  "
            "R: refresh  │  W: watchlist panel  │  B: browser panel  │  Q: quit",
            timeout=8,
            title="Keyboard Shortcuts",
        )

    # ── Helpers ───────────────────────────────────────────────────────────────

    def _get_focused_market(self) -> Market | None:
        """Return the market under cursor, regardless of which panel is focused."""
        # Try browser first (most common)
        try:
            browser: MarketBrowserPanel = self.query_one("#browser-panel")
            t: DataTable = browser.query_one("#browser-table")
            if t.has_focus:
                return browser.get_cursor_market(self.feed)
        except Exception:
            pass

        # Try movers panel
        try:
            movers: TopMoversPanel = self.query_one("#movers-panel")
            mt: DataTable = movers.query_one("#movers-table")
            if mt.has_focus:
                row_key = mt.coordinate_to_cell_key(mt.cursor_coordinate).row_key
                return self.feed.get_market(str(row_key.value))
        except Exception:
            pass

        # Try watchlist
        try:
            wl: WatchlistPanel = self.query_one("#watchlist-panel")
            cid = wl.get_cursor_condition_id()
            if cid and wl.query_one("#watchlist-table").has_focus:
                return self.feed.get_market(cid)
        except Exception:
            pass

        # Fallback: try any focused DataTable
        try:
            for t in self.query(DataTable):
                if t.has_focus:
                    row_key = t.coordinate_to_cell_key(t.cursor_coordinate).row_key
                    m = self.feed.get_market(str(row_key.value))
                    if m:
                        return m
        except Exception:
            pass

        return None

    # ── DataTable click events ────────────────────────────────────────────────

    def on_data_table_row_selected(self, event: DataTable.RowSelected) -> None:
        """Double-click or Enter on a DataTable row."""
        # Identify which table fired this
        sender_id = event.data_table.id
        if sender_id in ("browser-table", "movers-table"):
            market_id = str(event.row_key.value) if event.row_key else None
            if market_id:
                market = self.feed.get_market(market_id)
                if market:
                    self.push_screen(
                        MarketDetailModal(
                            market=market,
                            feed=self.feed,
                            watchlist=self.watchlist,
                        )
                    )
