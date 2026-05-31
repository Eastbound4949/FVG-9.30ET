"""
SQLite-backed paper trading engine for ORB bot.
Handles balance, open position, trade history, session state.
"""

import sqlite3
import json
import logging
from datetime import datetime, timezone, date
from orb_config import DB_PATH, CAPITAL_START, RISK_PCT, RR, SYMBOL

log = logging.getLogger("trader")


def _conn():
    c = sqlite3.connect(DB_PATH, check_same_thread=False)
    c.row_factory = sqlite3.Row
    return c


def init_db():
    with _conn() as c:
        c.executescript("""
            CREATE TABLE IF NOT EXISTS state (
                key   TEXT PRIMARY KEY,
                value TEXT
            );
            CREATE TABLE IF NOT EXISTS trades (
                id           INTEGER PRIMARY KEY AUTOINCREMENT,
                symbol       TEXT,
                direction    TEXT,
                entry_time   TEXT,
                entry_price  REAL,
                sl           REAL,
                tp           REAL,
                sl_dist      REAL,
                rr           REAL,
                risk_amount  REAL,
                exit_time    TEXT,
                exit_price   REAL,
                exit_reason  TEXT,
                profit       REAL,
                balance      REAL
            );
            CREATE TABLE IF NOT EXISTS equity_log (
                ts      TEXT,
                balance REAL,
                note    TEXT
            );
            CREATE TABLE IF NOT EXISTS events (
                id    INTEGER PRIMARY KEY AUTOINCREMENT,
                ts    TEXT,
                level TEXT,
                msg   TEXT
            );
        """)
        # Seed initial state if first run
        if not _get_raw("balance"):
            _set_raw("balance", str(CAPITAL_START))
            _set_raw("position", "null")
            _set_raw("session_state", json.dumps({
                "date": "", "or_high": None, "or_low": None,
                "breakout_dir": None, "trade_taken": False,
            }))
            _log_equity(CAPITAL_START, "init")
            log_event("DB initialised", "INFO")


# ── Low-level state helpers ───────────────────────────────────────────────────

def _get_raw(key: str):
    with _conn() as c:
        row = c.execute("SELECT value FROM state WHERE key=?", (key,)).fetchone()
        return row["value"] if row else None


def _set_raw(key: str, value: str):
    with _conn() as c:
        c.execute("INSERT OR REPLACE INTO state VALUES (?,?)", (key, value))


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _log_equity(balance: float, note: str = ""):
    with _conn() as c:
        c.execute("INSERT INTO equity_log VALUES (?,?,?)", (utc_now(), balance, note))


# ── Balance ───────────────────────────────────────────────────────────────────

def get_balance() -> float:
    return float(_get_raw("balance") or CAPITAL_START)


def set_balance(bal: float, note: str = ""):
    _set_raw("balance", str(bal))
    _log_equity(bal, note)


# ── Position ──────────────────────────────────────────────────────────────────

def get_position() -> dict | None:
    raw = _get_raw("position")
    v = json.loads(raw) if raw else None
    return v if v else None


def set_position(pos: dict | None):
    _set_raw("position", json.dumps(pos))


# ── Session state (resets each trading day) ───────────────────────────────────

def get_session() -> dict:
    raw = _get_raw("session_state")
    if raw:
        return json.loads(raw)
    return {"date": "", "or_high": None, "or_low": None,
            "breakout_dir": None, "trade_taken": False}


def set_session(sess: dict):
    _set_raw("session_state", json.dumps(sess))


def reset_session_if_new_day():
    """Reset session state when a new trading day starts."""
    today = str(date.today())
    sess = get_session()
    if sess.get("date") != today:
        new_sess = {"date": today, "or_high": None, "or_low": None,
                    "breakout_dir": None, "trade_taken": False}
        set_session(new_sess)
        log_event(f"New trading day — session reset ({today})", "INFO")
        return True
    return False


# ── Trade management ──────────────────────────────────────────────────────────

def open_trade(signal: dict) -> dict:
    bal = get_balance()
    risk_amount = bal * (RISK_PCT / 100)
    pos = {
        "symbol":       signal["symbol"],
        "direction":    signal["direction"],
        "entry_time":   utc_now(),
        "entry_price":  signal["entry"],
        "sl":           signal["stop"],
        "tp":           signal["target"],
        "sl_dist":      signal["sl_dist"],
        "rr":           signal["rr"],
        "risk_amount":  risk_amount,
        "balance":      bal,
    }
    set_position(pos)
    # Mark session: trade taken
    sess = get_session()
    sess["trade_taken"] = True
    set_session(sess)
    log_event(
        f"TRADE OPENED: {pos['direction'].upper()} {pos['symbol']} "
        f"@ {pos['entry_price']:.2f}  SL={pos['sl']:.2f}  TP={pos['tp']:.2f}  "
        f"Risk=${risk_amount:.2f}", "TRADE"
    )
    return pos


def check_and_close(bar_high: float, bar_low: float) -> dict | None:
    pos = get_position()
    if pos is None:
        return None

    d = pos["direction"]
    hit_sl = hit_tp = False

    if d == "long":
        if bar_low <= pos["sl"]:
            hit_sl = True
        elif bar_high >= pos["tp"]:
            hit_tp = True
    else:
        if bar_high >= pos["sl"]:
            hit_sl = True
        elif bar_low <= pos["tp"]:
            hit_tp = True

    if not hit_sl and not hit_tp:
        return None

    exit_reason = "tp" if hit_tp else "sl"
    exit_price  = pos["tp"] if hit_tp else pos["sl"]
    profit      = pos["risk_amount"] * pos["rr"] if hit_tp else -pos["risk_amount"]
    new_bal     = get_balance() + profit
    set_balance(new_bal, exit_reason)
    set_position(None)

    closed = {
        **pos,
        "exit_time":   utc_now(),
        "exit_price":  exit_price,
        "exit_reason": exit_reason,
        "profit":      profit,
        "balance":     new_bal,
    }

    with _conn() as c:
        c.execute("""
            INSERT INTO trades
              (symbol, direction, entry_time, entry_price, sl, tp, sl_dist, rr,
               risk_amount, exit_time, exit_price, exit_reason, profit, balance)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)
        """, (
            closed["symbol"], closed["direction"], closed["entry_time"],
            closed["entry_price"], closed["sl"], closed["tp"],
            closed["sl_dist"], closed["rr"], closed["risk_amount"],
            closed["exit_time"], closed["exit_price"], closed["exit_reason"],
            closed["profit"], closed["balance"],
        ))

    sign = "+" if profit >= 0 else ""
    log_event(
        f"TRADE CLOSED ({exit_reason.upper()}): {d.upper()} {pos['symbol']} "
        f"exit={exit_price:.2f}  P&L={sign}${profit:.2f}  Balance=${new_bal:.2f}",
        "TRADE"
    )
    return closed


def close_eod(close_price: float) -> dict | None:
    """Close open trade at EOD market price."""
    pos = get_position()
    if pos is None:
        return None
    d = pos["direction"]
    profit = pos["risk_amount"] * (
        (close_price - pos["entry_price"]) / pos["sl_dist"]
        if d == "long"
        else (pos["entry_price"] - close_price) / pos["sl_dist"]
    )
    new_bal = get_balance() + profit
    set_balance(new_bal, "eod_close")
    set_position(None)

    closed = {**pos, "exit_time": utc_now(), "exit_price": close_price,
              "exit_reason": "eod_close", "profit": profit, "balance": new_bal}

    with _conn() as c:
        c.execute("""
            INSERT INTO trades
              (symbol, direction, entry_time, entry_price, sl, tp, sl_dist, rr,
               risk_amount, exit_time, exit_price, exit_reason, profit, balance)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)
        """, (
            closed["symbol"], closed["direction"], closed["entry_time"],
            closed["entry_price"], closed["sl"], closed["tp"],
            closed["sl_dist"], closed["rr"], closed["risk_amount"],
            closed["exit_time"], closed["exit_price"], closed["exit_reason"],
            closed["profit"], closed["balance"],
        ))

    log_event(f"EOD CLOSE: {d.upper()} @ {close_price:.2f}  P&L=${profit:+.2f}", "TRADE")
    return closed


# ── Event log ─────────────────────────────────────────────────────────────────

def log_event(msg: str, level: str = "INFO"):
    log.info(msg)
    with _conn() as c:
        c.execute("INSERT INTO events (ts, level, msg) VALUES (?,?,?)",
                  (utc_now(), level, msg))


def get_events(limit: int = 50) -> list[dict]:
    with _conn() as c:
        rows = c.execute(
            "SELECT ts, level, msg FROM events ORDER BY id DESC LIMIT ?", (limit,)
        ).fetchall()
        return [dict(r) for r in rows]


# ── Query helpers ─────────────────────────────────────────────────────────────

def get_trades(limit: int = 100) -> list[dict]:
    with _conn() as c:
        rows = c.execute(
            "SELECT * FROM trades ORDER BY id DESC LIMIT ?", (limit,)
        ).fetchall()
        return [dict(r) for r in rows]


def get_equity_log() -> list[dict]:
    with _conn() as c:
        rows = c.execute(
            "SELECT * FROM equity_log ORDER BY rowid DESC LIMIT 500"
        ).fetchall()
        return [dict(r) for r in reversed(rows)]


def get_stats() -> dict:
    trades = get_trades(10000)
    if not trades:
        return {"trades": 0, "wins": 0, "losses": 0,
                "win_rate": 0, "pf": 0, "net": 0, "balance": get_balance()}
    wins   = [t for t in trades if t["profit"] > 0]
    losses = [t for t in trades if t["profit"] <= 0]
    net    = sum(t["profit"] for t in trades)
    gw     = sum(t["profit"] for t in wins)
    gl     = abs(sum(t["profit"] for t in losses))
    return {
        "trades":   len(trades),
        "wins":     len(wins),
        "losses":   len(losses),
        "win_rate": len(wins) / len(trades) * 100,
        "pf":       round(gw / gl, 2) if gl else float("inf"),
        "net":      round(net, 2),
        "balance":  round(get_balance(), 2),
    }
