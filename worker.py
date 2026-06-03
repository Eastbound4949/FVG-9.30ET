"""
Standalone scheduler worker for FVG 9:30 ET ORB bot.
Starts at container launch — no page visit needed.
"""

import logging
import signal
import sys
import time

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
    force=True,
)
log = logging.getLogger("worker")

import orb_trader as trader
import orb_scheduler as sched_mod


def main():
    log.info("=" * 50)
    log.info("  FVG 9:30 ET ORB Bot — Worker Starting")
    log.info("  Signal check : every 5 min")
    log.info("  Daily summary: 21:00 UTC")
    log.info("=" * 50)

    trader.init_db()
    sched = sched_mod.start()

    def _shutdown(signum, frame):
        log.info("Worker shutting down...")
        sched.shutdown(wait=False)
        sys.exit(0)

    signal.signal(signal.SIGTERM, _shutdown)
    signal.signal(signal.SIGINT, _shutdown)

    while True:
        time.sleep(60)


if __name__ == "__main__":
    main()
