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
import logging
import traceback
from datetime import datetime
from typing import ClassVar, Optional

logging.basicConfig(
    filename="/tmp/pm_terminal_crash.log",
    level=logging.DEBUG,
    format="%(asctime)s %(levelname)s %(message)s",
)

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
from watchlist import Watchlist, AlertManager, PriceAlert
from textual.widgets import Input
from textual.screen import ModalScreen

# ── Colour helpers ────────────────────────────────────────────────────────────

CATEGORIES = ["ALL", "CRYPTO", "POLITICS", "SPORTS", "FINANCE", "OTHER"]

CATEGORY_KEYWORDS = {
    "CRYPTO":   ["bitcoin", "btc", "ethereum", "eth", "crypto", "solana", "sol",
                 "doge", "token", "coinbase", "binance", "nft", "defi", "blockchain",
                 "matic", "polygon", "xrp", "ripple", "cardano", "ada", "memecoin"],
    "POLITICS": ["trump", "biden", "harris", "election", "senate", "congress",
                 "president", "vote", "republican", "democrat", "ukraine", "russia",
                 "iran", "israel", "nato", "tariff", "fed", "powell", "white house",
                 "governor", "mayor", "parliament", "minister", "prime minister",
                 "ceasefire", "war", "military", "sanctions"],
    "SPORTS":   ["nba", "nfl", "mlb", "nhl", "soccer", "football", "basketball",
                 "baseball", "champions", "league", "cup", "playoff", "super bowl",
                 "world cup", "championship", "lakers", "celtics", "warriors",
                 "ufc", "tennis", "golf", "formula", "f1", "olympic", "espn",
                 "lebron", "curry", "mahomes", "messi", "ronaldo"],
    "FINANCE":  ["gdp", "inflation", "recession", "interest rate", "federal reserve",
                 "sp500", "nasdaq", "dow", "s&p", "oil", "gold", "ipo", "earnings",
                 "stock", "bond", "yield", "unemployment", "cpi", "fomc"],
}


def categorize_market(title: str) -> str:
    """Classify a market title into a category."""
    t = title.lower()
    for cat, keywords in CATEGORY_KEYWORDS.items():
        if any(kw in t for kw in keywords):
            return cat
    return "OTHER"


def volume_bar(vol: float, max_vol: float, width: int = 8) -> str:
    """Render a Unicode block volume bar."""
    if max_vol <= 0:
        return "░" * width
    ratio = min(vol / max_vol, 1.0)
    filled = int(ratio * width)
    bar = "█" * filled + "░" * (width - filled)
    return f"[cyan]{bar}[/]"


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


class AlertInputModal(ModalScreen):
    """Modal to set a price alert on a market."""

    DEFAULT_CSS = """
    AlertInputModal {
        align: center middle;
    }
    #alert-dialog {
        width: 60;
        height: 14;
        border: thick $accent;
        background: $surface;
        padding: 1 2;
    }
    #alert-title { text-style: bold; color: $accent; margin-bottom: 1; }
    #alert-price-input { margin: 1 0; }
    #alert-hint { color: $text-muted; }
    """

    def __init__(self, market, **kwargs):
        super().__init__(**kwargs)
        self._market = market

    def compose(self) -> ComposeResult:
        with Vertical(id="alert-dialog"):
            yield Static("🔔 Set Price Alert", id="alert-title")
            yield Static(
                f"Market: {truncate(self._market.question, 50)}\n"
                f"Current YES: {self._market.best_yes_price:.3f}",
                id="alert-market-info"
            )
            yield Input(
                placeholder="e.g.  above 0.75  or  below 0.30",
                id="alert-price-input",
            )
            yield Static(
                "Type 'above X' or 'below X' then ENTER. ESC to cancel.",
                id="alert-hint"
            )

    def on_input_submitted(self, event: Input.Submitted) -> None:
        val = event.value.strip().lower()
        threshold = None
        direction = None
        try:
            if val.startswith("above "):
                direction = "above"
                threshold = float(val[6:].strip())
            elif val.startswith("below "):
                direction = "below"
                threshold = float(val[6:].strip())
            else:
                threshold = float(val)
                direction = "above" if threshold > self._market.best_yes_price else "below"
        except ValueError:
            self.dismiss(None)
            return
        self.dismiss((direction, threshold))

    def on_key(self, event) -> None:
        if event.key == "escape":
            self.dismiss(None)


class MarketBrowserPanel(Vertical):
    DEFAULT_CSS = """
    MarketBrowserPanel {
        border: solid $accent-darken-2;
        height: 100%;
    }
    #filter-bar {
        background: $primary-darken-3;
        padding: 0 2;
        height: 1;
        color: $accent;
    }
    #search-input {
        height: 1;
        border: none;
        background: $surface-darken-2;
        padding: 0 2;
        display: none;
    }
    #search-input.visible {
        display: block;
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
    cat_index:  reactive[int] = reactive(0)

    def __init__(self, feed: DataFeed, **kwargs):
        super().__init__(**kwargs)
        self._feed = feed
        self._all_markets: list[Market] = []
        self._search_query: str = ""
        self._search_active: bool = False

    def compose(self) -> ComposeResult:
        yield PanelHeader("📊  MARKET BROWSER  — ENTER inspect │ F filter │ / search")
        yield Static("", id="filter-bar")
        yield Input(placeholder="Search markets… (ESC to clear)", id="search-input")
        yield Static("", id="sort-bar")
        yield DataTable(id="browser-table", cursor_type="row", zebra_stripes=True)

    def on_mount(self):
        t: DataTable = self.query_one("#browser-table")
        t.add_columns("#", "Market", "VOL", "YES", "Change", "Vol 24h", "Cat")
        self._update_filter_bar()

    def _update_filter_bar(self):
        cats_count: dict = {c: 0 for c in CATEGORIES}
        cats_count["ALL"] = len(self._all_markets)
        for m in self._all_markets:
            cat = categorize_market(m.question)
            cats_count[cat] = cats_count.get(cat, 0) + 1
        parts = []
        for i, cat in enumerate(CATEGORIES):
            count = cats_count.get(cat, 0)
            if i == self.cat_index:
                parts.append(f"[bold reverse] {cat}:{count} [/]")
            else:
                parts.append(f" {cat}:{count} ")
        self.query_one("#filter-bar").update("  ".join(parts))

    def _filtered_markets(self) -> list[Market]:
        markets = self._all_markets
        if self.cat_index > 0:
            cat = CATEGORIES[self.cat_index]
            markets = [m for m in markets if categorize_market(m.question) == cat]
        if self._search_query:
            q = self._search_query.lower()
            markets = [m for m in markets if q in m.question.lower()]
        return markets

    def refresh_data(self, markets: list[Market]):
        self._all_markets = markets
        self._update_filter_bar()
        self._rebuild_table()

    def _rebuild_table(self):
        sort_key = self.SORT_KEYS[self.sort_index]
        filtered = self._filtered_markets()
        if sort_key == "volume24hr":
            sorted_m = sorted(filtered, key=lambda m: m.volume24hr, reverse=True)
        elif sort_key == "volume":
            sorted_m = sorted(filtered, key=lambda m: m.volume, reverse=True)
        elif sort_key == "change":
            sorted_m = sorted(filtered, key=lambda m: abs(m.price_change_pct), reverse=True)
        else:
            sorted_m = sorted(filtered, key=lambda m: m.best_yes_price, reverse=True)

        max_vol = max((m.volume24hr for m in sorted_m), default=1.0) or 1.0
        t: DataTable = self.query_one("#browser-table")
        t.clear()
        for i, m in enumerate(sorted_m[:100], 1):
            yes = m.best_yes_price
            t.add_row(
                f"[dim]{i:3}[/]",
                truncate(m.question, 34),
                volume_bar(m.volume24hr, max_vol, width=7),
                f"[{price_color(yes)}]{yes:.3f}[/]",
                change_markup(m.price_change_pct),
                fmt_usd(m.volume24hr),
                truncate(categorize_market(m.question), 8),
                key=m.id,
            )
        sort_labels = {
            "volume24hr": "[bold]24h Vol[/]", "volume": "[bold]Volume[/]",
            "change": "[bold]Change[/]",      "price":  "[bold]Price[/]",
        }
        total = len(self._all_markets)
        filt  = len(filtered)
        shown = min(100, filt)
        count_str = f"Showing {shown}/{filt}" if filt < total else f"{shown}/{total}"
        self.query_one("#sort-bar").update(
            f"Sort: {sort_labels[sort_key]}  │  S:cycle  │  {count_str}  │  ENTER:inspect"
        )

    def cycle_sort(self):
        self.sort_index = (self.sort_index + 1) % len(self.SORT_KEYS)
        self._rebuild_table()

    def cycle_category(self):
        self.cat_index = (self.cat_index + 1) % len(CATEGORIES)
        self._update_filter_bar()
        self._rebuild_table()

    def activate_search(self):
        inp: Input = self.query_one("#search-input")
        inp.add_class("visible")
        inp.focus()
        self._search_active = True

    def deactivate_search(self):
        inp: Input = self.query_one("#search-input")
        inp.remove_class("visible")
        inp.value = ""
        self._search_query = ""
        self._search_active = False
        self.query_one("#browser-table").focus()
        self._rebuild_table()

    def on_input_changed(self, event: Input.Changed) -> None:
        if event.input.id == "search-input":
            self._search_query = event.value
            self._rebuild_table()

    def on_input_submitted(self, event: Input.Submitted) -> None:
        if event.input.id == "search-input":
            self.query_one("#browser-table").focus()

    def on_key(self, event) -> None:
        if event.key == "escape" and self._search_active:
            self.deactivate_search()
            event.stop()

    def get_cursor_market(self, feed: DataFeed) -> Optional[Market]:
        t: DataTable = self.query_one("#browser-table")
        try:
            row_key = t.coordinate_to_cell_key(t.cursor_coordinate).row_key
            return feed.get_market(str(row_key.value))
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
        Binding("ctrl+q", "quit",           "Quit",      show=True),
        Binding("r",      "manual_refresh", "Refresh",   show=True),
        Binding("s",      "cycle_sort",     "Sort",      show=True),
        Binding("f",      "cycle_filter",   "Filter",    show=True),
        Binding("slash",  "activate_search","Search",    show=True),
        Binding("l",      "set_alert",      "Alert",     show=True),
        Binding("enter",  "inspect_market", "Inspect",   show=True),
        Binding("a",      "add_watchlist",  "Watch",     show=True),
        Binding("w",      "focus_watchlist","Watchlist", show=True),
        Binding("b",      "focus_browser",  "Browser",   show=True),
        Binding("?",      "show_help",      "Help",      show=False),
        Binding("ctrl+c", "quit",           "Quit",      show=False),
    ]

    def __init__(self, refresh_interval: int = 30, **kwargs):
        super().__init__(**kwargs)
        self.feed              = DataFeed(refresh_interval=refresh_interval)
        self.watchlist         = Watchlist()
        self.alerts            = AlertManager()
        self._refresh_interval = refresh_interval
        self._active_panel     = "browser"

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
        self.feed._alert_manager = self.alerts
        self.feed.add_listener(self._on_data_update)
        self.feed.add_alert_listener(self._on_alert_triggered)
        await self.feed.start()

    async def on_unmount(self) -> None:
        await self.feed.stop()

    def on_exception(self, error: Exception) -> None:
        """Catch any unhandled Textual exception — log it instead of crashing."""
        tb = traceback.format_exc()
        logging.error(f"Unhandled exception: {error}\n{tb}")
        self.notify(f"Error: {error}", severity="error", timeout=8)

    # ── Data callback ─────────────────────────────────────────────────────────

    async def _on_data_update(self):
        """Called by DataFeed after every successful poll."""
        self._refresh_all_panels()

    async def _on_alert_triggered(self, alert) -> None:
        """Called when a price alert fires."""
        self.notify(
            f"🔔 {alert.market_title[:50]}\nYES crossed {alert.direction} {alert.threshold:.3f}",
            title="Price Alert",
            severity="warning",
            timeout=10,
        )

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
        self.run_worker(self.feed._fetch_all, exclusive=False, exit_on_error=False)

    def action_cycle_sort(self):
        try:
            browser: MarketBrowserPanel = self.query_one("#browser-panel")
            browser.cycle_sort()
        except Exception:
            pass

    def action_cycle_filter(self):
        try:
            browser: MarketBrowserPanel = self.query_one("#browser-panel")
            browser.cycle_category()
        except Exception:
            pass

    def action_activate_search(self):
        try:
            browser: MarketBrowserPanel = self.query_one("#browser-panel")
            browser.activate_search()
        except Exception:
            pass

    def action_set_alert(self):
        market = self._get_focused_market()
        if market is None:
            self.notify("Select a market first", severity="warning")
            return

        def on_alert_result(result) -> None:
            if result is None:
                return
            direction, threshold = result
            self.alerts.add(
                condition_id=market.condition_id,
                market_title=market.question,
                threshold=threshold,
                direction=direction,
                current_price=market.best_yes_price,
            )
            self.notify(
                f"Alert set: {market.question[:40]}\nFires when YES goes {direction} {threshold:.3f}",
                title="Alert Created",
                severity="information",
                timeout=5,
            )

        self.push_screen(AlertInputModal(market=market), callback=on_alert_result)

    def action_inspect_market(self):
        """Open detail modal for the market under cursor."""
        try:
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
        except Exception:
            pass

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
        try:
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
        except Exception:
            pass
