"""
APScheduler for ORB bot.
Runs a state-machine job every 5 minutes during market hours.

ORB state machine (resets each morning):
  idle       → market not open or before 10:20 ET
  or_ready   → OR computed, watching for breakout
  breakout   → breakout detected, waiting for retest
  in_trade   → position open, monitoring SL/TP
  done       → trade taken or cutoff passed for the day
"""

import logging
from datetime import time
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.interval import IntervalTrigger
from apscheduler.triggers.cron import CronTrigger

import orb_trader as trader
import orb_strategy as strat
import orb_notify as notify
import signal_server
from orb_config import SYMBOL, CAPITAL_START, LIVE_TRADING_ENABLED, BRIDGE_SYMBOL, BRIDGE_SCALE

log = logging.getLogger("scheduler")
logging.basicConfig(level=logging.INFO,
                    format="%(asctime)s %(levelname)s %(message)s")

_events_cache: list[dict] = []


def _cache_event(msg: str, level: str):
    from datetime import datetime, timezone
    ts = datetime.now(timezone.utc).strftime("%H:%M UTC")
    _events_cache.insert(0, {"ts": ts, "msg": msg, "level": level})
    if len(_events_cache) > 200:
        _events_cache.pop()


def get_cached_events() -> list[dict]:
    return _events_cache


def _log(msg: str, level: str = "INFO"):
    trader.log_event(msg, level)
    _cache_event(msg, level)
    log.info(msg)


def _send_live_signal(setup: dict, pos: dict):
    """Queue an entry signal for the MT5 EA to pick up via /signal poll.

    Best-effort: paper balance/state tracking already happened in
    trader.open_trade() — this just hands the EA the entry/SL/TP distances.
    Lot sizing (risk%) is computed on the EA side from its own input, not here.
    """
    if not LIVE_TRADING_ENABLED:
        return

    sl_points = setup["sl_dist"] * BRIDGE_SCALE
    tp_points = abs(setup["target"] - setup["entry"]) * BRIDGE_SCALE

    payload = {
        "symbol": BRIDGE_SYMBOL,
        "direction": "sell" if setup["direction"] == "short" else "buy",
        "sl_points": round(sl_points, 4),
        "tp_points": round(tp_points, 4),
        "client_tag": f"orb-{setup['bar_time']}",
    }
    signal_server.push_signal(payload)
    _log(
        f"LIVE SIGNAL QUEUED: {payload['direction'].upper()} {payload['symbol']} "
        f"SL {payload['sl_points']}pts / TP {payload['tp_points']}pts",
        "TRADE",
    )


def _send_heartbeat_signal():
    """On startup/redeploy, record a zero-impact paper open+close on SYMBOL
    (visible in the dashboard) AND queue a matching min-size open+close round
    trip on BRIDGE_SYMBOL for the EA relay path (Railway -> WebRequest -> MT5
    order) to be verified end-to-end. The EA opens this at SYMBOL_VOLUME_MIN
    and closes it immediately on receipt."""
    spy_price = None
    try:
        df = strat.fetch_today(SYMBOL)
        bar = strat.get_latest_bar(df)
        if bar:
            spy_price = bar["close"]
            trader.record_heartbeat_trade(SYMBOL, spy_price)
    except Exception as e:
        _log(f"Heartbeat paper trade on {SYMBOL} failed: {e}", "ERROR")

    payload = {
        "symbol": BRIDGE_SYMBOL,
        "direction": "buy",
        "sl_points": 1.0,
        "tp_points": 1.0,
        "client_tag": "heartbeat",
    }
    signal_server.push_signal(payload)
    _log(f"Startup heartbeat queued: open+close test trade on {BRIDGE_SYMBOL}", "INFO")

    spy_line = f"Paper: {SYMBOL} open+close @ {spy_price:.2f}\n" if spy_price else ""
    notify.send(f"<b>Startup Heartbeat</b>\n{spy_line}"
                f"Live relay: queued open+close test trade on {BRIDGE_SYMBOL} "
                f"(EA opens at min size then closes it immediately)")


def job_run():
    """Main job — runs every 5 minutes. Drives the full ORB state machine."""
    try:
        # ── Skip non-market hours ─────────────────────────────────────────────
        if not strat.is_market_open():
            return

        # ── Reset session on new day ──────────────────────────────────────────
        trader.reset_session_if_new_day()
        sess = trader.get_session()
        now_t = strat.et_now_time()

        # ── If in trade: check SL/TP on latest bar ───────────────────────────
        if trader.get_position() is not None:
            df = strat.fetch_today(SYMBOL)
            bar = strat.get_latest_bar(df)
            if bar:
                closed = trader.check_and_close(bar["high"], bar["low"])
                if closed:
                    notify.trade_closed(closed)
                    _log(f"Trade closed: {closed['exit_reason'].upper()} @ {closed['exit_price']:.2f}  P&L=${closed['profit']:+.2f}", "TRADE")
                # EOD close at 15:55 ET
                if now_t >= time(15, 55) and trader.get_position():
                    closed = trader.close_eod(bar["close"])
                    if closed:
                        notify.trade_closed(closed)
                        _log(f"EOD close @ {bar['close']:.2f}  P&L=${closed['profit']:+.2f}", "TRADE")
            return

        # ── Session already done (trade taken or cutoff passed) ──────────────
        if sess.get("trade_taken") or now_t >= time(15, 0):
            return

        # ── Fetch today's bars ────────────────────────────────────────────────
        df = strat.fetch_today(SYMBOL)
        if df.empty:
            _log(f"No data from yfinance for {SYMBOL}")
            return

        # ── Phase 1: compute OR after 10:20 ET ───────────────────────────────
        if now_t >= time(10, 21) and sess["or_high"] is None:
            result = strat.compute_or(df)
            if result:
                or_high, or_low = result
                sess["or_high"] = or_high
                sess["or_low"]  = or_low
                trader.set_session(sess)
                _log(f"OR set: High={or_high:.2f}  Low={or_low:.2f}  Range={or_high-or_low:.2f}", "INFO")
                notify.or_ready(SYMBOL, or_high, or_low)
            else:
                _log("OR computation failed — not enough bars")
            return

        # ── Phase 2: watch for breakout ───────────────────────────────────────
        if sess["or_high"] is not None and sess["breakout_dir"] is None:
            direction = strat.check_breakout(df, sess["or_high"], sess["or_low"])
            if direction:
                sess["breakout_dir"] = direction
                trader.set_session(sess)
                bar = strat.get_latest_bar(df)
                price = bar["close"] if bar else 0
                _log(f"BREAKOUT {direction.upper()}: price={price:.2f}", "INFO")
                notify.breakout_detected(SYMBOL, direction, price,
                                         sess["or_high"] if direction == "long" else sess["or_low"])
            return

        # ── Phase 3: watch for retest ─────────────────────────────────────────
        if sess["breakout_dir"] is not None:
            setup = strat.check_retest(df, sess["breakout_dir"], sess["or_high"], sess["or_low"])
            if setup:
                pos = trader.open_trade(setup)
                notify.trade_opened(pos)
                _log(f"TRADE ENTERED: {setup['direction'].upper()} entry={setup['entry']:.2f} "
                     f"SL={setup['stop']:.2f} TP={setup['target']:.2f}", "TRADE")
                _send_live_signal(setup, pos)

    except Exception as e:
        _log(f"job_run error: {e}", "ERROR")
        log.exception("Unhandled error in job_run")


def job_daily_summary():
    """Send Telegram daily summary at 16:15 ET (20:15/21:15 UTC)."""
    try:
        stats = trader.get_stats()
        notify.daily_summary(stats, SYMBOL)
        _log("Daily summary sent")
    except Exception as e:
        _log(f"daily_summary error: {e}", "ERROR")


def start() -> BackgroundScheduler:
    trader.init_db()
    sched = BackgroundScheduler(timezone="UTC")

    # Main ORB job every 5 minutes
    sched.add_job(job_run, IntervalTrigger(minutes=5),
                  id="orb_main", replace_existing=True)

    # Daily summary — 21:00 UTC (covers both EDT=16:00 and EST=17:00)
    sched.add_job(job_daily_summary, CronTrigger(hour=21, minute=0, timezone="UTC"),
                  id="daily_summary", replace_existing=True)

    sched.start()

    # Always-on: binds Railway's $PORT so /health responds for the platform
    # healthcheck (dashboard moved to a fixed local port, see start.sh).
    signal_server.start_in_background()

    if LIVE_TRADING_ENABLED:
        _send_heartbeat_signal()

    bal = trader.get_balance()
    notify.bot_started(SYMBOL, bal, CAPITAL_START)
    _log(f"Scheduler started — {SYMBOL} paper trading | Balance=${bal:.2f}", "INFO")
    return sched
