# Botche 5.1 – BTC 5m Up/Down Rules Bot (Test Mode)
# Rules:
# 1. No trade in first 75 seconds of window
# 2. No trade in last 85 seconds of window
# 3. Buy Up or Down at 88¢ (or 89¢ / 90¢ if 88 not available)
# 4. Sell only if price reaches 50¢; otherwise hold to window end
# 5. Only ONE position per 5-minute window
# Test: start with 1000 coins, each buy costs 100 coins, track win/lose (max 200 records)

import streamlit as st
import requests
import pandas as pd
from datetime import datetime, timedelta
import time
import json

st.set_page_config(page_title="Botche 5m Up/Down", layout="wide")
st.title("Botche 5.1 – BTC 5m Up/Down (Test)")
st.caption("Test bank: 1000 coins · 100 coins per buy · one position per window · sell only at 50¢")

# Fixed rules
SHARES = 15
BUY_PRICES = [0.88, 0.89, 0.90]
SELL_PRICE = 0.50
NO_TRADE_START = 75
NO_TRADE_END = 85
START_BANK = 1000
COST_PER_BUY = 100
MAX_RECORDS = 200

# Session state
if "bank" not in st.session_state:
    st.session_state.bank = START_BANK
if "positions" not in st.session_state:
    st.session_state.positions = []
if "logs" not in st.session_state:
    st.session_state.logs = []
if "opened_windows" not in st.session_state:
    st.session_state.opened_windows = set()

def log(msg: str):
    ts = datetime.utcnow().strftime("%H:%M:%S")
    entry = f"[{ts}] {msg}"
    st.session_state.logs.insert(0, entry)
    st.session_state.logs = st.session_state.logs[:150]

def get_current_window():
    now = datetime.utcnow()
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
        r = requests.get(f"https://gamma-api.polymarket.com/events/slug/{slug}", timeout=12)
        if r.status_code == 200:
            return r.json()
    except Exception as e:
        log(f"Market fetch error: {e}")
    return None

def get_live_price(token_id):
    """Get live price via midpoint (preferred) or last trade."""
    try:
        r = requests.get(f"https://clob.polymarket.com/midpoint?token_id={token_id}", timeout=6)
        if r.status_code == 200:
            data = r.json()
            mid = data.get("mid_price") or data.get("mid")
            if mid is not None:
                return float(mid)
    except:
        pass
    try:
        r = requests.get(f"https://clob.polymarket.com/last-trade-price?token_id={token_id}", timeout=6)
        if r.status_code == 200:
            data = r.json()
            if data.get("price"):
                return float(data["price"])
    except:
        pass
    return None

def parse_list(val, default):
    if val is None:
        return default
    if isinstance(val, list):
        return val
    if isinstance(val, str):
        try:
            return json.loads(val)
        except:
            try:
                return eval(val)
            except:
                return default
    return default

# Sidebar
st.sidebar.header("Test Bank")
st.sidebar.metric("Coins", st.session_state.bank)
st.sidebar.write(f"Cost per buy: **{COST_PER_BUY}**")
st.sidebar.write(f"Records: **{len(st.session_state.positions)} / {MAX_RECORDS}**")
st.sidebar.header("Rules")
st.sidebar.write("One position per 5m window")
st.sidebar.write("Sell only at 50¢ (else hold to end)")
auto = st.sidebar.checkbox("Auto refresh (1s)", value=True)
if st.sidebar.button("Reset test"):
    st.session_state.bank = START_BANK
    st.session_state.positions = []
    st.session_state.logs = []
    st.session_state.opened_windows = set()
    st.rerun()

slug, window_start, window_end = get_current_window()
now = datetime.utcnow()
can_trade = in_trading_window(window_start, window_end, now)
already_opened = slug in st.session_state.opened_windows

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
    st.metric("Trading allowed", "YES" if (can_trade and not already_opened) else "NO")

st.sidebar.write(f"Window: `{slug}`")
log(f"Window {slug} | trading={'YES' if can_trade else 'NO'} | already_opened={already_opened}")

market = fetch_market(slug)
if not market or not market.get("markets"):
    prev_ts = int((window_start - timedelta(minutes=5)).timestamp())
    prev_slug = f"btc-updown-5m-{prev_ts}"
    market = fetch_market(prev_slug)
    if market:
        slug = prev_slug
        log(f"Using previous window {prev_slug}")

if market and market.get("markets"):
    m = market["markets"][0]
    tokens = parse_list(m.get("clobTokenIds"), [])
    outcomes = parse_list(m.get("outcomes"), ["Up", "Down"])
    raw_prices = parse_list(m.get("outcomePrices"), ["0.5", "0.5"])
    prices = []
    for p in raw_prices:
        try:
            prices.append(float(p))
        except:
            prices.append(0.5)

    st.subheader(market.get("title", slug))

    c1, c2 = st.columns(2)
    for i in range(min(2, len(outcomes))):
        out = outcomes[i]
        price = prices[i] if i < len(prices) else 0.5
        tok = tokens[i] if i < len(tokens) else None
        col = c1 if i == 0 else c2
        with col:
            st.markdown(f"### {out}")
            live_price = None
            if tok:
                live_price = get_live_price(tok)
            display_price = live_price if live_price is not None else price
            st.metric(f"Live price {out}", f"{display_price:.3f}")
            if live_price is not None:
                log(f"{out} live price = {live_price:.3f}")
            else:
                st.write(f"(fallback gamma {price:.3f})")
                log(f"{out} no live price, gamma={price:.3f}")

            # Buy when live price first reaches 0.88 on either side
            if can_trade and not already_opened and live_price is not None and st.session_state.bank >= COST_PER_BUY:
                if live_price <= 0.90 and len(st.session_state.positions) < MAX_RECORDS:
                    pos = {
                        "token": tok,
                        "outcome": out,
                        "buy_price": round(live_price, 3),
                        "shares": SHARES,
                        "cost": COST_PER_BUY,
                        "opened": now.strftime("%H:%M:%S"),
                        "window": slug,
                        "window_end": window_end.isoformat(),
                        "status": "open",
                        "result": "-",
                        "pnl": 0,
                    }
                    st.session_state.positions.append(pos)
                    st.session_state.bank -= COST_PER_BUY
                    st.session_state.opened_windows.add(slug)
                    log(f"BUY {out} FIRST at {live_price:.3f} | cost {COST_PER_BUY} | bank={st.session_state.bank}")
                    st.success(f"BUY {out} @ {live_price:.3f} (−{COST_PER_BUY} coins)")

            # Sell only at 50¢
            if live_price is not None and live_price <= SELL_PRICE:
                for pos in st.session_state.positions:
                    if pos["token"] == tok and pos["status"] == "open":
                        pos["status"] = "sold"
                        pos["sell_price"] = live_price
                        pos["result"] = "sold @ 50¢"
                        recovered = int(COST_PER_BUY * (live_price / pos["buy_price"]))
                        pos["pnl"] = recovered - COST_PER_BUY
                        st.session_state.bank += recovered
                        log(f"SELL {out} @ {live_price:.3f} | recovered ~{recovered} | bank={st.session_state.bank}")
                        st.warning(f"SELL {out} @ {live_price:.3f}")

else:
    st.error("Could not load 5m market.")
    log("Market load failed")

# Resolve positions that reached window end
for pos in st.session_state.positions:
    if pos["status"] == "open":
        end = datetime.fromisoformat(pos["window_end"])
        if now > end:
            pos["status"] = "resolved"
            # Simple win/lose: if buy price was high (>=0.7) treat as likely win for test, else lose
            # In real use you would check the actual resolution
            won = pos["buy_price"] >= 0.70
            pos["result"] = "WIN" if won else "LOSE"
            if won:
                payout = int(COST_PER_BUY * (1.0 / pos["buy_price"]))  # rough
                pos["pnl"] = payout - COST_PER_BUY
                st.session_state.bank += payout
            else:
                pos["pnl"] = -COST_PER_BUY
            log(f"RESOLVED {pos['outcome']} → {pos['result']} | pnl={pos['pnl']} | bank={st.session_state.bank}")

# Positions table
st.header("Positions (max 200)")
if st.session_state.positions:
    df = pd.DataFrame(st.session_state.positions[-MAX_RECORDS:])
    show = [c for c in ["outcome", "buy_price", "cost", "opened", "status", "result", "pnl"] if c in df.columns]
    st.dataframe(df[show], use_container_width=True, hide_index=True)
else:
    st.info("No positions yet.")

# Logs
st.header("Live Log")
if st.session_state.logs:
    st.code("\n".join(st.session_state.logs[:50]), language="text")
else:
    st.write("No logs yet.")

st.divider()
st.caption("Botche 5.1 Test · 1000 coins start · 100 per buy · one position per window · sell only at 50¢")

if auto:
    time.sleep(1)
    st.rerun()
