# 📊 Polymarket Terminal

> **Like Bloomberg, but for prediction markets.**

A Bloomberg Terminal-style TUI (terminal user interface) for [Polymarket](https://polymarket.com) — real-time market prices, whale flow, top movers, and your personal watchlist, all in a beautiful 4-panel terminal display.

---

## Screenshot

```
╔══════════════════════════════════════════════════════════════════════════════╗
║  ▐█▌ POLYMARKET TERMINAL  │  Bloomberg-style prediction market feed         ║
╠════════════════════════════════════╦═════════════════════════════════════════╣
║  ▲▼  TOP MOVERS                   ║  🐋  WHALE ACTIVITY  — trades > $5K     ║
║ ─────────────────────────────────  ║  ────────────────────────────────────── ║
║  1  Trump approval > 50%  0.612 ▲  ║  3s  ▲ BUY   Will Fed cut rates?  $42K ║
║  2  Bitcoin above $100K   0.538 ▼  ║  1m  ▼ SELL  Trump acquitted    $18.5K ║
║  3  AI beats top human    0.891 ▲  ║  2m  ▲ BUY   SPX above 5000     $11K  ║
║  4  Fed rate cut June     0.445 ▼  ║  4m  ▲ BUY   Elon Musk CEO again $9K  ║
║  5  Recession by 2026     0.312 ─  ║  5m  ▼ SELL  Recession 2025     $7.2K ║
╠════════════════════════════════════╬═════════════════════════════════════════╣
║  📊  MARKET BROWSER                ║  👁  WATCHLIST / MY POSITIONS           ║
║  Sort: 24h Vol │ S: cycle          ║ ─────────────────────────────────────── ║
║  #   Market            YES  Change  ║  Market              Track  Cur  P&L   ║
║   1  Will Trump be…  0.972  ▲0.3%  ║  Trump pres. 7/4…  0.970 0.972 +0.2% ║
║   2  Bitcoin $100k?  0.538  ▼1.2%  ║  Bitcoin $100K…    0.540 0.538 -0.4% ║
║   3  Fed cuts June?  0.445  ▲0.8%  ║                                        ║
║  [ENTER to inspect market]         ║  [A add  │  R remove  │  ENTER inspect] ║
╚════════════════════════════════════╩═════════════════════════════════════════╝
  ⚡ Last update: 14:32:01  │  Markets: 147  │  Whale trades: 23  │  Refresh #4
```

When you press **ENTER** on a market, a detail modal appears:

```
┌──────────────────────────────────────────────────────────────────────────────┐
│            Will Donald Trump be president on July 4, 2025?                   │
│  Category: Politics  │  Volume: $4.2M  │  24h Vol: $182K  │  Liq: $56K     │
│                                                                              │
│  ▸ OUTCOMES                                                                  │
│    YES  0.972   97.2%   ▲ 0.21%                                             │
│    NO   0.028    2.8%   ▼ 0.21%                                             │
│                                                                              │
│  ▸ 24H PRICE CHART                                                          │
│    0.98│  ─────────────────────────────────────────────────────────────╮    │
│    0.97│──────────────────────────────╮  ╭─────────────────────────────╯    │
│    0.96│                              ╰──╯                                   │
│         └────────────────────────────────────────────────────────────────   │
│    Spark: ▁▂▃▄▅▆▅▆▇▇▇▇▇▇▇█████  Current: 0.972  Change: +0.21%             │
│                                                                              │
│  [ORDER BOOK — BIDS]          [ORDER BOOK — ASKS]                           │
│    0.971  850.0   850.0          0.972   320.0   320.0                      │
│    0.970  1200.0  2050.0         0.973   500.0   820.0                      │
│                                                                              │
│  ▸ RECENT TRADES                                                            │
│    12s  ▲ BUY   YES  0.972  $2,100                                         │
│    45s  ▼ SELL  YES  0.971  $850                                            │
│                                                                              │
│  ESC / Q to close  │  A add watchlist  │  R remove watchlist                │
└──────────────────────────────────────────────────────────────────────────────┘
```

---

## Install & Run

**Prerequisites:** Python 3.11+

```bash
# 1. Clone
git clone https://github.com/your-username/prediction-market-terminal
cd prediction-market-terminal

# 2. Install dependencies
pip install -r requirements.txt

# 3. Launch
python run_terminal.py

# With custom refresh interval (seconds)
python run_terminal.py --refresh 15
```

No API keys needed. All data is public read-only from Polymarket's APIs.

---

## Keyboard Shortcuts

| Key | Action |
|-----|--------|
| `ENTER` | Inspect the selected market (open detail modal) |
| `A` | Add focused market to watchlist |
| `S` | Cycle market browser sort (24h Vol → Volume → Change → Price) |
| `R` | Force manual data refresh |
| `W` | Move focus to watchlist panel |
| `B` | Move focus to market browser panel |
| `?` | Show help overlay |
| `Q` / `Ctrl+C` | Quit |
| `ESC` | Close modal / go back |

---

## Layout

```
┌─────────────────────────────┬──────────────────────────────┐
│  TOP MOVERS (price change)  │  WHALE ACTIVITY (last 5min)  │
├─────────────────────────────┼──────────────────────────────┤
│  MARKET BROWSER (scrollable)│  MY POSITIONS / WATCHLIST    │
└─────────────────────────────┴──────────────────────────────┘
                    [ STATUS BAR ]
```

### Panel Details

**Top Movers** — Markets with the biggest % price change since the last refresh.  
Includes ASCII sparklines (▁▂▃▄▅▆▇█) showing the price trend over time.  
Color: 🟢 green = rising, 🔴 red = falling.

**Whale Activity** — Live feed of trades over $5,000 USD.  
Shows age (e.g. "2m"), direction (▲ BUY / ▼ SELL), market, outcome, and size.  
Yellow flash for brand-new trades.

**Market Browser** — Scrollable list of all active Polymarket markets.  
Sortable by: 24h Volume, Total Volume, Price Change, YES Price.  
Press ENTER to open the detail modal.

**Watchlist / Positions** — Your personally tracked markets.  
Shows tracked price vs current price, with P&L percentage.  
Stored at `~/.pm_terminal/watchlist.json`.

---

## Data Sources

| API | Usage |
|-----|-------|
| `gamma-api.polymarket.com/markets` | Market prices, volumes, outcomes |
| `data-api.polymarket.com/trades?size_threshold=5000` | Whale trade activity |
| `clob.polymarket.com/book` | Order book depth (in market detail) |

All public, no authentication required.

---

## Watchlist File

Stored at `~/.pm_terminal/watchlist.json`. Edit manually or use the `A`/`R` keys.

```json
[
  {
    "market_id": "",
    "condition_id": "0xabc...",
    "question": "Will X happen?",
    "tracked_price": 0.54,
    "note": "High conviction"
  }
]
```

---

## Architecture

```
run_terminal.py         ← Entry point / CLI arg parsing
  └─ terminal.py        ← Main Textual app, 4-panel layout
       ├─ data_feeds.py ← Async polling, in-memory cache, event dispatch
       ├─ market_detail.py ← Detail modal (chart, trades, order book)
       └─ watchlist.py  ← ~/.pm_terminal/watchlist.json persistence
```

---

## License

MIT — build freely, trade responsibly.

---

*Built with [Textual](https://textual.textualize.io/) by Textualize.*
