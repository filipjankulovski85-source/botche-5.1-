# Botche 5.1 – BTC 5m Up/Down Rules Bot
# Rules:
# 1. No trade in first 75 seconds of window
# 2. No trade in last 85 seconds of window
# 3. Buy Up or Down at 88¢ (or 89¢ / 90¢ if 88 not available)
# 4. If price drops to 50¢ → sell

import streamlit as st
import requests
import pandas as pd
from datetime import datetime, timedelta
import time

st.set_page_config(page_title="Botche 5m Up/Down", layout="wide")
st.title("Botche 5.1 – BTC 5m Up/Down")
st.caption("Rules: no trade first 75s · no trade last 85s · buy 88/89/90¢ · sell at 50¢")

# Fixed rules
SHARES = 15
BUY_PRICES = [0.88, 0.89, 0.90]
SELL_PRICE = 0.50
NO_TRADE_START = 75   # seconds
NO_TRADE_END = 85     # seconds before window end

if "positions" not in st.session_state:
    st.session_state.positions = []

def get_current_window():
    now = datetime.utcnow()
    # Floor to 5-minute boundary
    minute = (now.minute // 5) * 5
    start = now.replace(minute=minute, second=0, microsecond=0)
    ts = int(start.timestamp())
    end = start + timedelta(minutes=5)
    return f"btc-updown-5m-{ts}", start, end

def in_trading_window(start, end, now):
    elapsed = (now - start).total_seconds()
    remaining = (end - now).total_seconds()
    return elapsed >= NO_TRADE_START and remaining >= NO_TRADE_END

def fetch_market(slug):
    try:
        r = requests.get(f"https://gamma-api.polymarket.com/events/slug/{slug}", timeout=10)
        if r.status_code == 200:
            return r.json()
    except Exception as e:
        st.sidebar.warning(str(e))
    return None

def get_book(token_id):
    try:
        r = requests.get(f"https://clob.polymarket.com/book?token_id={token_id}", timeout=8)
        if r.status_code == 200:
            return r.json()
    except:
        pass
    return None

# Sidebar status
st.sidebar.header("Rules (fixed)")
st.sidebar.write(f"Shares: **{SHARES}**")
st.sidebar.write(f"Buy levels: **{BUY_PRICES}**")
st.sidebar.write(f"Sell at: **{SELL_PRICE}**")
st.sidebar.write(f"No trade first **{NO_TRADE_START}s**")
st.sidebar.write(f"No trade last **{NO_TRADE_END}s**")
auto = st.sidebar.checkbox("Auto refresh", value=True)

slug, window_start, window_end = get_current_window()
now = datetime.utcnow()
can_trade = in_trading_window(window_start, window_end, now)

col1, col2, col3, col4 = st.columns(4)
with col1:
    st.metric("Now (UTC)", now.strftime("%H:%M:%S"))
with col2:
    rem = window_end - now
    st.metric("Time left", str(rem).split(".")[0] if rem.total_seconds() > 0 else "Ended")
with col3:
    elapsed = (now - window_start).total_seconds()
    st.metric("Elapsed", f"{int(elapsed)}s")
with col4:
    st.metric("Trading allowed", "YES" if can_trade else "NO")

st.sidebar.write(f"Window: `{slug}`")

market = fetch_market(slug)
if market and market.get("markets"):
    m = market["markets"][0]
    # Robust parsing for API fields that may be lists or JSON strings
    raw_tokens = m.get("clobTokenIds", "[]")
    if isinstance(raw_tokens, str):
        try:
            tokens = eval(raw_tokens)
        except:
            tokens = []
    else:
        tokens = raw_tokens or []

    raw_outcomes = m.get("outcomes", ["Up", "Down"])
    if isinstance(raw_outcomes, str):
        try:
            outcomes = eval(raw_outcomes)
        except:
            outcomes = ["Up", "Down"]
    else:
        outcomes = raw_outcomes or ["Up", "Down"]

    raw_prices = m.get("outcomePrices", ["0.5", "0.5"])
    if isinstance(raw_prices, str):
        try:
            raw_prices = eval(raw_prices)
        except:
            raw_prices = ["0.5", "0.5"]
    prices = []
    for p in (raw_prices or ["0.5", "0.5"]):
        try:
            prices.append(float(p))
        except (TypeError, ValueError):
            prices.append(0.5)

    st.subheader(market.get("title", slug))

    c1, c2 = st.columns(2)
    for i, (out, price, tok) in enumerate(zip(outcomes, prices, tokens)):
        with (c1 if i == 0 else c2):
            st.markdown(f"### {out}")
            st.metric("Price", f"{price:.2f}¢")
            book = get_book(tok)
            best_ask = None
            if book and book.get("asks"):
                best_ask = float(book["asks"][0]["price"])
                st.write(f"Best ask: **{best_ask:.2f}**")

            # Buy logic
            if can_trade and best_ask:
                target = None
                for bp in BUY_PRICES:
                    if best_ask <= bp:
                        target = bp
                        break
                if target:
                    already = any(p["token"] == tok and p["window"] == slug and p["status"] == "open" for p in st.session_state.positions)
                    if not already:
                        pos = {
                            "token": tok,
                            "outcome": out,
                            "buy_price": round(best_ask, 2),
                            "shares": SHARES,
                            "opened": now.strftime("%H:%M:%S"),
                            "window": slug,
                            "window_end": window_end.isoformat(),
                            "status": "open",
                            "result": "-",
                        }
                        st.session_state.positions.append(pos)
                        st.success(f"BUY {SHARES} {out} @ {best_ask:.2f}")

            # Sell logic (for open positions of this token)
            if best_ask and best_ask <= SELL_PRICE:
                for pos in st.session_state.positions:
                    if pos["token"] == tok and pos["status"] == "open":
                        pos["status"] = "sold"
                        pos["sell_price"] = best_ask
                        pos["result"] = "sold @ 50¢"
                        st.warning(f"SELL {out} @ {best_ask:.2f}")

else:
    st.warning("Could not load current 5m market.")

# Positions
st.header("Positions")
if st.session_state.positions:
    # Resolve expired
    for pos in st.session_state.positions:
        if pos["status"] == "open":
            end = datetime.fromisoformat(pos["window_end"])
            if now > end:
                pos["status"] = "resolved"
                pos["result"] = "window ended"

    df = pd.DataFrame(st.session_state.positions)
    show = [c for c in ["outcome", "buy_price", "shares", "opened", "status", "result"] if c in df.columns]
    st.dataframe(df[show], use_container_width=True, hide_index=True)
else:
    st.info("No positions yet.")

st.divider()
st.caption("Botche 5.1 · 5-minute BTC Up/Down · Dry-run simulation")

if auto:
    time.sleep(8)
    st.rerun()
