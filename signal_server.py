"""
signal_server.py — HTTP signal queue for the MT5 EA to poll.

MT5's hosted VPS is EA-only (no Python/Flask there), so the direction is
flipped: orb_scheduler.py queues a signal here, and ORBSignalRelay_EA.mq5
polls GET /signal via WebRequest. The signal is consumed (one-shot) on read.

Runs in a background thread inside the Railway worker, bound to $PORT.
"""

import hmac
import json
import logging
import sqlite3
import threading

from flask import Flask, jsonify, request

import orb_config as config

log = logging.getLogger(__name__)

app = Flask(__name__)
_lock = threading.Lock()

# SQLite-backed signal store so a Railway restart doesn't drop a queued signal.
_DB = config.DB_PATH


def _db():
    c = sqlite3.connect(_DB, check_same_thread=False)
    c.execute("""
        CREATE TABLE IF NOT EXISTS pending_signal (
            id      INTEGER PRIMARY KEY CHECK (id = 1),
            payload TEXT
        )
    """)
    return c


def push_signal(payload: dict) -> None:
    """Queue a signal for the EA to pick up on its next poll."""
    with _lock:
        with _db() as c:
            c.execute(
                "INSERT OR REPLACE INTO pending_signal (id, payload) VALUES (1, ?)",
                (json.dumps(payload),),
            )
    log.info(f"Signal queued for EA poll: {payload}")


def _pop_signal() -> dict | None:
    with _lock:
        with _db() as c:
            row = c.execute("SELECT payload FROM pending_signal WHERE id=1").fetchone()
            if row is None:
                return None
            c.execute("DELETE FROM pending_signal WHERE id=1")
            return json.loads(row[0])


def _authorized(req) -> bool:
    supplied = req.headers.get("X-Secret", "") or req.args.get("secret", "")
    return bool(config.SIGNAL_SECRET) and hmac.compare_digest(supplied, config.SIGNAL_SECRET)


@app.route("/signal", methods=["GET"])
def get_signal():
    if not _authorized(request):
        return jsonify({"error": "unauthorized"}), 401
    payload = _pop_signal()
    return jsonify(payload or {})


@app.route("/push", methods=["POST"])
def push():
    """External signal injection for testing. Requires same X-Secret auth."""
    if not _authorized(request):
        return jsonify({"error": "unauthorized"}), 401
    body = request.get_json(silent=True) or {}
    required = {"symbol", "direction", "sl_points", "tp_points"}
    if not required.issubset(body.keys()):
        return jsonify({"error": f"missing fields: {required - body.keys()}"}), 400
    push_signal(body)
    return jsonify({"queued": body})


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
