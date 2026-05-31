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
