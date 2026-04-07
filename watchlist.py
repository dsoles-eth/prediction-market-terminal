"""
watchlist.py — Load/save user watchlist and tracked positions.

Watchlist is stored in ~/.pm_terminal/watchlist.json.
Each entry records the market_id, question, and the price at which
the user started watching (for P&L display).
"""

import json
import os
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Optional, List

WATCHLIST_PATH = Path.home() / ".pm_terminal" / "watchlist.json"
ALERTS_PATH    = Path.home() / ".pm_terminal" / "alerts.json"

DEFAULT_WATCHLIST = [
    {
        "market_id": "",
        "condition_id": "0xdd22472e552920b8438158ea7238bfadfa4f736aa62cdc4159b74d3ec7e10a65",
        "question": "Will Donald Trump be president on July 4, 2025?",
        "tracked_price": 0.97,
        "note": "High-conviction YES position",
    },
    {
        "market_id": "",
        "condition_id": "0x5f65177b394277fd294cd75650044e2a2e8f5508b9e48fce3c7fc4009e5b54",
        "question": "Bitcoin above $100k by end of 2025?",
        "tracked_price": 0.54,
        "note": "Tracking macro sentiment",
    },
]


@dataclass
class WatchlistEntry:
    market_id: str          # Gamma market id (may be empty)
    condition_id: str       # CLOB condition id
    question: str
    tracked_price: float    # price when user started watching (0 = unknown)
    note: str = ""

    def pnl_pct(self, current_price: float) -> Optional[float]:
        if self.tracked_price > 0 and current_price > 0:
            return (current_price - self.tracked_price) / self.tracked_price * 100
        return None


class Watchlist:
    def __init__(self):
        self.entries: list[WatchlistEntry] = []
        self._path = WATCHLIST_PATH
        self.load()

    # ── Persistence ──────────────────────────────────────────────────────────

    def load(self):
        if self._path.exists():
            try:
                raw = json.loads(self._path.read_text())
                self.entries = [WatchlistEntry(**e) for e in raw]
                return
            except Exception:
                pass
        # First run — seed with defaults
        self.entries = [WatchlistEntry(**e) for e in DEFAULT_WATCHLIST]
        self._ensure_dir()
        self.save()

    def save(self):
        self._ensure_dir()
        self._path.write_text(
            json.dumps([asdict(e) for e in self.entries], indent=2)
        )

    def _ensure_dir(self):
        self._path.parent.mkdir(parents=True, exist_ok=True)

    # ── Mutations ────────────────────────────────────────────────────────────

    def add(
        self,
        condition_id: str,
        question: str,
        current_price: float,
        market_id: str = "",
        note: str = "",
    ) -> bool:
        for e in self.entries:
            if e.condition_id == condition_id:
                return False   # already watching
        self.entries.append(
            WatchlistEntry(
                market_id=market_id,
                condition_id=condition_id,
                question=question,
                tracked_price=current_price,
                note=note,
            )
        )
        self.save()
        return True

    def remove(self, condition_id: str) -> bool:
        before = len(self.entries)
        self.entries = [e for e in self.entries if e.condition_id != condition_id]
        if len(self.entries) < before:
            self.save()
            return True
        return False

    def get(self, condition_id: str) -> Optional[WatchlistEntry]:
        for e in self.entries:
            if e.condition_id == condition_id:
                return e
        return None

    def __len__(self):
        return len(self.entries)

    def __iter__(self):
        return iter(self.entries)


# ── Price Alerts ──────────────────────────────────────────────────────────────

@dataclass
class PriceAlert:
    condition_id: str
    market_title: str
    threshold: float
    direction: str      # "above" | "below"
    current_price: float


class AlertManager:
    def __init__(self):
        self._path = ALERTS_PATH
        self.alerts: List[PriceAlert] = []
        self._ensure_dir()
        self.load()

    def _ensure_dir(self):
        self._path.parent.mkdir(parents=True, exist_ok=True)

    def load(self):
        if self._path.exists():
            try:
                raw = json.loads(self._path.read_text())
                self.alerts = [PriceAlert(**a) for a in raw]
            except Exception:
                self.alerts = []

    def save(self):
        self._ensure_dir()
        self._path.write_text(
            json.dumps([asdict(a) for a in self.alerts], indent=2)
        )

    def add(self, condition_id: str, market_title: str,
            threshold: float, direction: str, current_price: float):
        # Remove any existing alert for same market
        self.alerts = [a for a in self.alerts if a.condition_id != condition_id]
        self.alerts.append(PriceAlert(
            condition_id=condition_id,
            market_title=market_title,
            threshold=threshold,
            direction=direction,
            current_price=current_price,
        ))
        self.save()

    def remove(self, condition_id: str):
        self.alerts = [a for a in self.alerts if a.condition_id != condition_id]
        self.save()

    def check_and_fire(self, by_condition: dict) -> List[PriceAlert]:
        """Return alerts that have triggered. Removes them from the list."""
        triggered: List[PriceAlert] = []
        remaining: List[PriceAlert] = []
        for alert in self.alerts:
            market = by_condition.get(alert.condition_id)
            if market is None:
                remaining.append(alert)
                continue
            price = market.best_yes_price
            fired = (
                (alert.direction == "above" and price >= alert.threshold) or
                (alert.direction == "below" and price <= alert.threshold)
            )
            if fired:
                triggered.append(alert)
            else:
                remaining.append(alert)
        if triggered:
            self.alerts = remaining
            self.save()
        return triggered
