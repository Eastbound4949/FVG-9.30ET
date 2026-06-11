"""
signal_server.py — HTTP signal queue for the MT5 EA to poll.

MT5's hosted VPS is EA-only (no Python/Flask there), so the direction is
flipped: orb_scheduler.py queues a signal here, and ORBSignalRelay_EA.mq5
polls GET /signal via WebRequest. The signal is consumed (one-shot) on read.

Runs in a background thread inside the Railway worker, bound to $PORT.
"""

import hmac
import logging
import threading

from flask import Flask, jsonify, request

import orb_config as config

log = logging.getLogger(__name__)

app = Flask(__name__)
_lock = threading.Lock()
_pending: dict | None = None


def push_signal(payload: dict) -> None:
    """Queue a signal for the EA to pick up on its next poll."""
    global _pending
    with _lock:
        _pending = dict(payload)
    log.info(f"Signal queued for EA poll: {payload}")


def _authorized(req) -> bool:
    supplied = req.headers.get("X-Secret", "") or req.args.get("secret", "")
    return bool(config.SIGNAL_SECRET) and hmac.compare_digest(supplied, config.SIGNAL_SECRET)


@app.route("/signal", methods=["GET"])
def get_signal():
    if not _authorized(request):
        return jsonify({"error": "unauthorized"}), 401
    global _pending
    with _lock:
        payload = _pending
        _pending = None  # consume — one-shot delivery
    return jsonify(payload or {})


@app.route("/health", methods=["GET"])
def health():
    return jsonify({"status": "ok"})


def start_in_background() -> None:
    """Always starts — binds Railway's $PORT so /health responds for the
    platform healthcheck even when live trading is off. /signal returns 401
    until SIGNAL_SECRET is set to match the EA's InpSecret."""
    if not config.SIGNAL_SECRET:
        log.warning("SIGNAL_SECRET not set — /signal will reject all requests (401)")
    t = threading.Thread(
        target=lambda: app.run(host="0.0.0.0", port=config.SIGNAL_PORT, use_reloader=False),
        daemon=True,
    )
    t.start()
    log.info(f"Signal server listening on :{config.SIGNAL_PORT}")
