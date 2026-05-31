"""Telegram notifications for the ORB paper trading bot."""
import requests
import logging
from orb_config import TELEGRAM_TOKEN, TELEGRAM_CHAT_ID

log = logging.getLogger("notify")


def send(msg: str):
    if not TELEGRAM_TOKEN or not TELEGRAM_CHAT_ID:
        log.info(f"[Telegram disabled] {msg}")
        return
    try:
        requests.post(
            f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage",
            data={"chat_id": TELEGRAM_CHAT_ID, "text": msg, "parse_mode": "HTML"},
            timeout=10,
        )
    except Exception as e:
        log.error(f"Telegram error: {e}")


def bot_started(symbol: str, capital: float, rr: float):
    send(
        f"<b>ORB Bot Started</b>\n"
        f"Symbol: {symbol} | Capital: ${capital:,.0f}\n"
        f"RR: {rr} | Risk: 1% per trade\n"
        f"Strategy: 50-min OR breakout + tight SL"
    )


def or_ready(symbol: str, high: float, low: float):
    send(
        f"<b>[ORB] Opening Range Set</b>\n"
        f"{symbol}  High: {high:.2f}  Low: {low:.2f}\n"
        f"Range: {high - low:.2f} pts — watching for breakout"
    )


def breakout_detected(symbol: str, direction: str, price: float, or_level: float):
    emoji = "UP" if direction == "long" else "DOWN"
    send(
        f"<b>[ORB] {emoji} Breakout</b> — {symbol}\n"
        f"Direction: {direction.upper()}\n"
        f"Break level: {or_level:.2f}  Current: {price:.2f}\n"
        f"Waiting for retest..."
    )


def trade_opened(pos: dict):
    direction = pos["direction"].upper()
    send(
        f"<b>[ORB TRADE ENTERED]</b>\n"
        f"{pos['symbol']} {direction}\n"
        f"Entry:  {pos['entry_price']:.2f}\n"
        f"Stop:   {pos['sl']:.2f}  ({pos['sl_dist']:.2f} pts)\n"
        f"Target: {pos['tp']:.2f}  (RR {pos['rr']})\n"
        f"Risk:   ${pos['risk_amount']:.2f}\n"
        f"Balance: ${pos['balance']:.2f}"
    )


def trade_closed(closed: dict):
    profit = closed["profit"]
    outcome = "WIN" if profit > 0 else "LOSS"
    sign = "+" if profit >= 0 else ""
    send(
        f"<b>[ORB TRADE CLOSED — {outcome}]</b>\n"
        f"{closed['symbol']} {closed['direction'].upper()}\n"
        f"Exit: {closed['exit_price']:.2f}  ({closed['exit_reason'].upper()})\n"
        f"P&amp;L: {sign}${profit:.2f}\n"
        f"Balance: ${closed['balance']:.2f}"
    )


def daily_summary(stats: dict, symbol: str):
    if stats.get("trades", 0) == 0:
        send(f"<b>[ORB Daily Summary]</b> {symbol}\nNo trades today.")
        return
    send(
        f"<b>[ORB Daily Summary]</b> {symbol}\n"
        f"Trades: {stats['trades']}  W/L: {stats['wins']}/{stats['losses']}\n"
        f"Win rate: {stats['win_rate']:.1f}%\n"
        f"Net P&amp;L: {'+' if stats['net'] >= 0 else ''}${stats['net']:.2f}\n"
        f"Balance: ${stats['balance']:.2f}"
    )


def no_signal(reason: str):
    send(f"[ORB] No signal today — {reason}")
