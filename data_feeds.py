"""
data_feeds.py — Async Polymarket data pipeline

Polls Gamma API (markets) + Data API (whale trades).
Caches everything in-memory, notifies listeners on update.
"""

import asyncio
import json
import os
import time
import requests
from dataclasses import dataclass, field
from typing import Optional, Callable, Awaitable, List

GAMMA_API   = "https://gamma-api.polymarket.com"
DATA_API    = "https://data-api.polymarket.com"
CLOB_API    = "https://clob.polymarket.com"

WHALE_THRESHOLD = 500     # shares (API param) — filter by USD client-side
WHALE_USD_MIN   = 1_000   # minimum USD value for whale feed display


# ── Data models ──────────────────────────────────────────────────────────────

@dataclass
class Outcome:
    name: str
    price: float


@dataclass
class Market:
    id: str
    condition_id: str
    question: str
    outcomes: list[Outcome]
    volume: float
    volume24hr: float
    liquidity: float
    category: str
    end_date: str
    active: bool
    price_history: list[float] = field(default_factory=list)
    price_change_pct: float = 0.0   # set by DataFeed after comparing snapshots

    @property
    def best_yes_price(self) -> float:
        for o in self.outcomes:
            if o.name.upper() in ("YES", "Y"):
                return o.price
        return self.outcomes[0].price if self.outcomes else 0.5

    @property
    def best_no_price(self) -> float:
        for o in self.outcomes:
            if o.name.upper() in ("NO", "N"):
                return o.price
        return self.outcomes[1].price if len(self.outcomes) > 1 else 0.5


@dataclass
class WhaleTrade:
    trade_id: str
    market_id: str          # condition_id
    question: str
    outcome: str
    price: float
    size_usd: float
    side: str               # BUY / SELL
    timestamp: int

    @property
    def age_str(self) -> str:
        diff = time.time() - self.timestamp
        if diff < 60:
            return f"{int(diff)}s"
        if diff < 3600:
            return f"{int(diff/60)}m"
        return f"{int(diff/3600)}h"

    @property
    def side_icon(self) -> str:
        return "▲" if self.side.upper() == "BUY" else "▼"


# ── Helpers ───────────────────────────────────────────────────────────────────

def _parse_json_field(val):
    """Gamma API sometimes returns JSON arrays as strings."""
    if isinstance(val, str):
        try:
            return json.loads(val)
        except Exception:
            return []
    return val or []


def _safe_float(val, default: float = 0.0) -> float:
    try:
        return float(val)
    except (TypeError, ValueError):
        return default


def _fetch_markets_sync(limit: int = 150) -> list[dict]:
    try:
        resp = requests.get(
            f"{GAMMA_API}/markets",
            params={
                "limit": limit,
                "active": "true",
                "order": "volume24hr",
                "ascending": "false",
            },
            timeout=12,
            headers={"User-Agent": "pm-terminal/1.0"},
        )
        resp.raise_for_status()
        return resp.json()
    except Exception as exc:
        return []


def _fetch_whale_trades_sync(limit: int = 100) -> list[dict]:
    """
    Fetch recent large trades.
    size_threshold is in SHARES (not USD).
    We fetch 5000+ share trades and compute USD = shares * price client-side.
    """
    try:
        resp = requests.get(
            f"{DATA_API}/trades",
            params={
                "size_threshold": WHALE_THRESHOLD,  # 5000 shares minimum
                "limit": limit,
            },
            timeout=12,
            headers={"User-Agent": "pm-terminal/1.0"},
        )
        resp.raise_for_status()
        data = resp.json()
        # API may return {"data": [...]} or directly a list
        if isinstance(data, dict):
            return data.get("data", data.get("trades", []))
        return data
    except Exception:
        return []


def _fetch_market_trades_sync(condition_id: str, limit: int = 20) -> list[dict]:
    try:
        resp = requests.get(
            f"{DATA_API}/trades",
            params={"market": condition_id, "limit": limit},
            timeout=10,
            headers={"User-Agent": "pm-terminal/1.0"},
        )
        resp.raise_for_status()
        data = resp.json()
        if isinstance(data, dict):
            return data.get("data", [])
        return data
    except Exception:
        return []


def _fetch_orderbook_sync(token_id: str) -> dict:
    try:
        resp = requests.get(
            f"{CLOB_API}/book",
            params={"token_id": token_id},
            timeout=8,
            headers={"User-Agent": "pm-terminal/1.0"},
        )
        resp.raise_for_status()
        return resp.json()
    except Exception:
        return {}


# ── Main feed ─────────────────────────────────────────────────────────────────

class DataFeed:
    """
    Async data feed for Polymarket.

    Usage:
        feed = DataFeed(refresh_interval=30)
        feed.add_listener(my_async_callback)
        await feed.start()
    """

    def __init__(self, refresh_interval: int = 30):
        self.refresh_interval = refresh_interval

        # Live data stores
        self.markets:      dict[str, Market]     = {}   # id -> Market
        self.by_condition: dict[str, Market]     = {}   # condition_id -> Market
        self.whale_trades: list[WhaleTrade]      = []
        self.top_movers:   list[Market]          = []   # sorted by |price_change_pct|

        # Internal state
        self._prev_prices: dict[str, float]      = {}   # market_id -> best_yes_price
        self._listeners:   list[Callable]        = []
        self._alert_listeners: list[Callable]    = []   # called with (List[PriceAlert],)
        self._running      = False
        self._lock         = asyncio.Lock()
        self.last_update:  float                 = 0.0
        self.status_msg:   str                   = "Connecting…"
        self.error_msg:    str                   = ""
        self.fetch_count:  int                   = 0
        self._alert_manager = None   # set by app after init

    # ── Public API ────────────────────────────────────────────────────────────

    def add_listener(self, coro: Callable[[], Awaitable[None]]):
        self._listeners.append(coro)

    def remove_listener(self, coro):
        self._listeners = [l for l in self._listeners if l != coro]

    async def _notify(self):
        for listener in list(self._listeners):
            try:
                await listener()
            except Exception:
                pass

    async def start(self):
        self._running = True
        await self._fetch_all()
        asyncio.create_task(self._poll_loop(), name="datafeed-poll")

    async def stop(self):
        self._running = False

    def get_markets_sorted(self, key: str = "volume24hr") -> list[Market]:
        markets = list(self.markets.values())
        if key == "volume24hr":
            markets.sort(key=lambda m: m.volume24hr, reverse=True)
        elif key == "volume":
            markets.sort(key=lambda m: m.volume, reverse=True)
        elif key == "price":
            markets.sort(key=lambda m: m.best_yes_price, reverse=True)
        elif key == "change":
            markets.sort(key=lambda m: abs(m.price_change_pct), reverse=True)
        return markets

    def get_market(self, market_id: str) -> Optional[Market]:
        return self.markets.get(market_id) or self.by_condition.get(market_id)

    async def fetch_market_trades(self, condition_id: str) -> list[WhaleTrade]:
        loop = asyncio.get_event_loop()
        raw = await loop.run_in_executor(None, _fetch_market_trades_sync, condition_id)
        return [self._parse_trade(t) for t in raw]

    async def fetch_orderbook(self, token_id: str) -> dict:
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(None, _fetch_orderbook_sync, token_id)

    # ── Internals ─────────────────────────────────────────────────────────────

    async def _poll_loop(self):
        while self._running:
            await asyncio.sleep(self.refresh_interval)
            await self._fetch_all()

    async def _fetch_all(self):
        loop = asyncio.get_event_loop()
        self.status_msg = "Fetching…"
        try:
            markets_raw, trades_raw = await asyncio.gather(
                loop.run_in_executor(None, _fetch_markets_sync),
                loop.run_in_executor(None, _fetch_whale_trades_sync),
            )
        except Exception as exc:
            self.error_msg = str(exc)
            self.status_msg = f"Error: {exc}"
            return

        async with self._lock:
            self._process_markets(markets_raw)
            self._process_trades(trades_raw)
            self.last_update = time.time()
            self.fetch_count += 1
            self.status_msg = (
                f"Last update: {time.strftime('%H:%M:%S')}  "
                f"│  Markets: {len(self.markets)}  "
                f"│  Whale trades: {len(self.whale_trades)}  "
                f"│  Refresh #{self.fetch_count}"
            )

        await self._notify()
        await self._check_alerts()

    async def _check_alerts(self):
        if self._alert_manager is None:
            return
        triggered = self._alert_manager.check_and_fire(self.by_condition)
        if not triggered:
            return
        for alert in triggered:
            await self._fire_alert(alert)

    async def _fire_alert(self, alert):
        """Send alert via Telegram if configured, otherwise notify listeners."""
        msg = (
            f"🔔 PM Alert: {alert.market_title[:60]}\n"
            f"YES price crossed {alert.direction} {alert.threshold:.3f}"
        )
        tg_token = os.environ.get("PM_TERMINAL_TELEGRAM_TOKEN")
        tg_chat  = os.environ.get("PM_TERMINAL_TELEGRAM_CHAT_ID")
        if tg_token and tg_chat:
            try:
                loop = asyncio.get_event_loop()
                await loop.run_in_executor(
                    None,
                    lambda: requests.post(
                        f"https://api.telegram.org/bot{tg_token}/sendMessage",
                        json={"chat_id": tg_chat, "text": msg},
                        timeout=8,
                    )
                )
            except Exception:
                pass
        # Notify in-app listeners regardless
        for cb in list(self._alert_listeners):
            try:
                await cb(alert)
            except Exception:
                pass

    def add_alert_listener(self, coro: Callable):
        self._alert_listeners.append(coro)

    def _process_markets(self, raw: list[dict]):
        new_markets: dict[str, Market] = {}
        new_by_cond: dict[str, Market] = {}

        movers: list[Market] = []

        for item in raw:
            mid = str(item.get("id", ""))
            if not mid:
                continue

            cid = str(item.get("conditionId", item.get("condition_id", "")))

            outcomes_raw   = _parse_json_field(item.get("outcomes", []))
            prices_raw     = _parse_json_field(item.get("outcomePrices", []))

            outcomes: list[Outcome] = []
            for i, name in enumerate(outcomes_raw):
                price = _safe_float(prices_raw[i] if i < len(prices_raw) else 0.5)
                outcomes.append(Outcome(name=str(name), price=price))

            if not outcomes:
                outcomes = [Outcome("YES", 0.5), Outcome("NO", 0.5)]

            vol     = _safe_float(item.get("volume"))
            vol24   = _safe_float(item.get("volume24hr"))
            liq     = _safe_float(item.get("liquidity"))
            cat     = str(item.get("groupItemTitle", item.get("category", "General")) or "General")
            end_dt  = str(item.get("endDate", ""))
            active  = bool(item.get("active", True))
            question = str(item.get("question", "Unknown Market"))

            # Price history: inherit from previous fetch
            prev_market = self.markets.get(mid)
            if prev_market:
                history = prev_market.price_history.copy()
            else:
                history = []

            yes_price = outcomes[0].price
            history.append(yes_price)
            if len(history) > 30:
                history = history[-30:]

            # Price change vs previous snapshot
            prev_price = self._prev_prices.get(mid, yes_price)
            if prev_price > 0:
                change_pct = (yes_price - prev_price) / prev_price * 100
            else:
                change_pct = 0.0

            market = Market(
                id=mid,
                condition_id=cid,
                question=question,
                outcomes=outcomes,
                volume=vol,
                volume24hr=vol24,
                liquidity=liq,
                category=cat,
                end_date=end_dt,
                active=active,
                price_history=history,
                price_change_pct=change_pct,
            )

            new_markets[mid]  = market
            if cid:
                new_by_cond[cid] = market

            if abs(change_pct) > 0:
                movers.append(market)

            # Save current price for next diff
            self._prev_prices[mid] = yes_price

        self.markets      = new_markets
        self.by_condition = new_by_cond

        movers.sort(key=lambda m: abs(m.price_change_pct), reverse=True)
        self.top_movers = movers[:20] if movers else list(new_markets.values())[:20]

    def _process_trades(self, raw: list[dict]):
        trades: list[WhaleTrade] = []
        for item in raw:
            t = self._parse_trade(item)
            if t and t.size_usd >= WHALE_USD_MIN:
                trades.append(t)
        # Include all trades if filter leaves nothing (graceful fallback)
        if not trades:
            trades = [t for item in raw if (t := self._parse_trade(item))]
        trades.sort(key=lambda t: t.size_usd, reverse=True)
        self.whale_trades = trades[:50]

    def _parse_trade(self, item: dict) -> Optional[WhaleTrade]:
        try:
            # Support both Data API field names and legacy formats
            tid  = str(item.get("transactionHash", item.get("id", item.get("taker_order_id", ""))))
            # conditionId in Data API, market in legacy
            cid  = str(item.get("conditionId", item.get("market", "")))
            # title is the market question in the Data API
            name = str(item.get("title", item.get("name", item.get("question", "Unknown"))))

            # Look up human-readable question from our cache (may be better)
            if cid and cid in self.by_condition:
                name = self.by_condition[cid].question

            outcome  = str(item.get("outcome", "YES"))
            price    = _safe_float(item.get("price"))
            # size = number of shares; size_usd = shares * price
            shares   = _safe_float(item.get("size", item.get("amount")))
            size_usd = shares * price if price > 0 else shares
            side     = str(item.get("side", "BUY")).upper()

            ts_raw   = item.get("timestamp", item.get("match_time", item.get("last_update", "")))
            try:
                ts = int(float(ts_raw))
                if ts > 1e12:   # milliseconds → seconds
                    ts = ts // 1000
            except (TypeError, ValueError):
                ts = int(time.time())

            return WhaleTrade(
                trade_id=tid,
                market_id=cid,
                question=name,
                outcome=outcome,
                price=price,
                size_usd=size_usd,
                side=side,
                timestamp=ts,
            )
        except Exception:
            return None
