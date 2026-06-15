import os

# Strategy
SYMBOL        = os.getenv("SYMBOL", "SPY")
OR_MINUTES    = 50          # first 50 min after 9:30 ET = opening range
RR            = float(os.getenv("RR", "3.5"))
RISK_PCT      = float(os.getenv("RISK_PCT", "1.0"))   # % of account per trade
CAPITAL_START = float(os.getenv("CAPITAL_START", "1000.0"))
ENTRY_CUTOFF  = "15:00"    # no new entries after this ET time

# DB / files
DB_PATH       = os.getenv("DB_PATH", "orb_paper.db")

# Telegram
TELEGRAM_TOKEN   = os.getenv("TELEGRAM_TOKEN", "")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "")

# ── Live execution relay (MT5 EA polls this) ──────────────────────────────────
# MT5's hosted VPS is EA-only (no Python/Flask there). When enabled, every
# "TRADE OPENED" queues a signal via signal_server.push_signal();
# ORBSignalRelay_EA.mq5 polls GET /signal (WebRequest) and executes it.
# Lot sizing (risk%) is computed on the EA side, not here — only entry/SL/TP
# distances are sent. Paper balance tracking continues unchanged for comparison.
LIVE_TRADING_ENABLED = os.getenv("LIVE_TRADING_ENABLED", "false").lower() == "true"
SIGNAL_SECRET        = os.getenv("SIGNAL_SECRET", "")
SIGNAL_PORT          = int(os.getenv("PORT", os.getenv("SIGNAL_PORT", "8080")))
BRIDGE_SYMBOL        = os.getenv("BRIDGE_SYMBOL", "SP500")   # broker symbol for the chart the EA runs on
