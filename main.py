"""
ORB Paper Trading Bot — Streamlit Dashboard
Deploy: Railway  (Procfile: web: streamlit run main.py --server.port $PORT --server.headless true)

Env vars required:
  TELEGRAM_TOKEN    — Telegram bot token
  TELEGRAM_CHAT_ID  — Your chat ID
Optional:
  SYMBOL            — Default SPY
  RR                — Default 3.5
  RISK_PCT          — Default 1.0
  CAPITAL_START     — Default 1000.0
"""

import streamlit as st
import pandas as pd
import plotly.graph_objects as go
from datetime import datetime, timezone

import orb_trader as trader
import orb_scheduler as sched_mod
from orb_config import CAPITAL_START, RISK_PCT, RR, SYMBOL, OR_MINUTES

st.set_page_config(
    page_title="ORB 9:30 ET Bot",
    page_icon="📈",
    layout="wide",
)

trader.init_db()

# ── Header ────────────────────────────────────────────────────────────────────
st.title("ORB 9:30 ET Paper Trading Bot")
st.caption(
    f"{SYMBOL}  |  {OR_MINUTES}-min Opening Range  |  "
    f"Breakout + Tight SL  |  RR {RR}  |  "
    f"Risk {RISK_PCT}% per trade"
)

# ── Top metrics ───────────────────────────────────────────────────────────────
stats   = trader.get_stats()
balance = trader.get_balance()
pos     = trader.get_position()
sess    = trader.get_session()
net_pct = (balance - CAPITAL_START) / CAPITAL_START * 100

c1, c2, c3, c4, c5, c6 = st.columns(6)
c1.metric("Balance",       f"${balance:,.2f}", f"{net_pct:+.1f}%")
c2.metric("Total Trades",  stats.get("trades", 0))
c3.metric("Win Rate",      f"{stats.get('win_rate', 0):.1f}%")
c4.metric("Profit Factor", f"{stats.get('pf', 0):.2f}" if stats.get("trades") else "—")
c5.metric("Net P&L",       f"${stats.get('net', 0):+.2f}")
c6.metric("W / L",         f"{stats.get('wins', 0)} / {stats.get('losses', 0)}")

st.divider()

# ── Session state ─────────────────────────────────────────────────────────────
col_left, col_right = st.columns([1, 2])

with col_left:
    st.subheader("Today's Session")
    st.write(f"**Date:** {sess.get('date', '—')}")
    if sess.get("or_high"):
        st.write(f"**OR High:** {sess['or_high']:.2f}")
        st.write(f"**OR Low:** {sess['or_low']:.2f}")
        st.write(f"**OR Range:** {sess['or_high'] - sess['or_low']:.2f} pts")
    else:
        st.info("Opening Range: waiting for 10:20 ET")

    if sess.get("breakout_dir"):
        st.write(f"**Breakout:** {sess['breakout_dir'].upper()}")
    elif sess.get("or_high"):
        st.info("Watching for breakout...")

    if sess.get("trade_taken") and pos is None:
        st.success("Trade complete for today")

with col_right:
    st.subheader("Open Position")
    if pos:
        direction = pos["direction"].upper()
        entry     = pos["entry_price"]
        sl        = pos["sl"]
        tp        = pos["tp"]

        pc1, pc2, pc3, pc4 = st.columns(4)
        pc1.metric("Direction", direction)
        pc2.metric("Entry",     f"${entry:.2f}")
        pc3.metric("Stop",      f"${sl:.2f}", f"-{pos['sl_dist']:.2f} pts")
        pc4.metric("Target",    f"${tp:.2f}", f"+{abs(tp - entry):.2f} pts")

        st.caption(
            f"Risk: ${pos['risk_amount']:.2f}  |  "
            f"RR {pos['rr']}  |  Entered: {pos['entry_time'][:19]} UTC"
        )
    else:
        st.info("No open position")

st.divider()

# ── Equity curve ──────────────────────────────────────────────────────────────
st.subheader("Equity Curve")
eq = trader.get_equity_log()
if len(eq) > 1:
    df_eq = pd.DataFrame(eq)
    df_eq["ts"] = pd.to_datetime(df_eq["ts"])
    fig = go.Figure()
    fig.add_trace(go.Scatter(
        x=df_eq["ts"], y=df_eq["balance"],
        mode="lines", name="Balance",
        line=dict(color="#00e676", width=2),
        fill="tozeroy", fillcolor="rgba(0,230,118,0.07)",
    ))
    fig.add_hline(y=CAPITAL_START, line_dash="dot", line_color="gray",
                  annotation_text=f"Start ${CAPITAL_START:,.0f}")
    fig.update_layout(
        height=280, template="plotly_dark",
        margin=dict(l=0, r=0, t=10, b=0),
        yaxis_title="Balance (USD)",
    )
    st.plotly_chart(fig, use_container_width=True)
else:
    st.info("Equity curve appears after first trade closes.")

# ── Trade history ─────────────────────────────────────────────────────────────
st.subheader("Trade History")
trades = trader.get_trades(100)
if trades:
    df_t = pd.DataFrame(trades)
    df_t["entry_time"] = pd.to_datetime(df_t["entry_time"]).dt.strftime("%m-%d %H:%M")
    df_t["exit_time"]  = pd.to_datetime(df_t["exit_time"]).dt.strftime("%m-%d %H:%M")
    df_t["profit_fmt"] = df_t["profit"].map(lambda x: f"${x:+.2f}")
    df_t["balance_fmt"]= df_t["balance"].map(lambda x: f"${x:,.2f}")

    def color_row(val):
        try:
            v = float(val.replace("$","").replace("+",""))
            return "color: #00e676" if v > 0 else "color: #ff5252"
        except Exception:
            return ""

    display = df_t[[
        "direction", "entry_time", "entry_price", "exit_time",
        "exit_price", "exit_reason", "profit_fmt", "balance_fmt", "rr",
    ]].rename(columns={
        "entry_time": "In", "exit_time": "Out", "entry_price": "Entry",
        "exit_price": "Exit", "exit_reason": "Reason",
        "profit_fmt": "P&L", "balance_fmt": "Balance",
        "direction": "Dir", "rr": "RR",
    })
    st.dataframe(
        display.style.map(color_row, subset=["P&L"]),
        use_container_width=True, hide_index=True,
    )
else:
    st.info("No completed trades yet.")

# ── Event log ─────────────────────────────────────────────────────────────────
st.subheader("Bot Log")
events = trader.get_events(30)
if events:
    for ev in events[:30]:
        colour = {"TRADE": "#00e676", "ERROR": "#ff5252"}.get(ev["level"], "#aaaaaa")
        st.markdown(
            f"<span style='color:{colour};font-family:monospace;font-size:13px'>"
            f"[{ev['ts']}] {ev['msg']}</span>",
            unsafe_allow_html=True,
        )
else:
    st.caption("No events yet — bot runs every 5 minutes.")

# ── Sidebar ───────────────────────────────────────────────────────────────────
with st.sidebar:
    st.header("Config")
    st.write(f"**Symbol:** {SYMBOL}")
    st.write(f"**Starting capital:** ${CAPITAL_START:,.0f}")
    st.write(f"**Risk per trade:** {RISK_PCT}%")
    st.write(f"**R:R:** {RR}")
    st.write(f"**OR period:** {OR_MINUTES} min (9:30–10:20 ET)")
    st.write(f"**Entry cutoff:** 3:00 PM ET")
    st.write(f"**Stop loss:** Retest candle extremity")
    st.divider()
    st.write(f"**Scheduler:** Every 5 min")
    st.write(f"**Daily summary:** 21:00 UTC")
    st.divider()
    if st.button("Run signal check now"):
        sched_mod.job_run()
        st.rerun()
    if st.button("Send daily summary now"):
        sched_mod.job_daily_summary()
        st.rerun()
    st.divider()
    st.caption(f"UTC: {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M')}")

# Auto-refresh every 60 seconds
st.markdown("<meta http-equiv='refresh' content='60'>", unsafe_allow_html=True)
