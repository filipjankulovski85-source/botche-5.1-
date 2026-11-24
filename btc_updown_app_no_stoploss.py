# Botche 5.1 – BTC 5m Up/Down Rules Bot (Test Mode)
# Rules:
# 1. No trade first 75s / last 85s
# 2. Buy at 0.88 (or 0.89 / 0.90)
# 3. Special rule: if price was already >0.88 in the first 75s,
#    it must first drop to ≤0.70, then on the way up (inside trading window)
#    reach 0.88/0.89/0.90 to buy
# 4. No stop-loss – hold to window end only
# 5. Only ONE buy per 5-minute window
# Test bank: 1000 coins, 100 per buy

import streamlit as st
import requests
import pandas as pd
from datetime import datetime, timedelta
import time
import json

st.set_page_config(page_title="Botche 5m Up/Down", layout="wide")
st.title("Botche 5.1 – BTC 5m Up/Down (Test)")
st.caption("Buy 0.88/0.89/0.90 · no stop-loss · pullback rule if >0.88 in first 75s")

# Fixed rules
SHARES = 15
BUY_PRICES = [0.88, 0.89, 0.90]
PULLBACK_LEVEL = 0.70
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
if "window_state" not in st.session_state:
    # per window: track if price was high early and if pullback happened
    st.session_state.window_state = {}

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

def get_btc_spot():
    """Public BTC price as proxy for Chainlink TWAP (spot, not true TWAP)."""
    try:
        r = requests.get(
            "https://api.coingecko.com/api/v3/simple/price?ids=bitcoin&vs_currencies=usd",
            timeout=6,
        )
        if r.status_code == 200:
            return r.json().get("bitcoin", {}).get("usd")
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
st.sidebar.write("One buy per 5m window")
st.sidebar.write("Buy: 0.88 → 0.89 → 0.90")
st.sidebar.write("No stop-loss (hold to end)")
st.sidebar.write("Pullback rule if >0.88 in first 75s")
auto = st.sidebar.checkbox("Auto refresh (1s)", value=True)
if st.sidebar.button("Reset test"):
    st.session_state.bank = START_BANK
    st.session_state.positions = []
    st.session_state.logs = []
    st.session_state.opened_windows = set()
    st.session_state.window_state = {}
    st.rerun()

slug, window_start, window_end = get_current_window()
now = datetime.utcnow()
elapsed = (now - window_start).total_seconds()
can_trade = in_trading_window(window_start, window_end, now)
already_opened = slug in st.session_state.opened_windows

# Init window state
if slug not in st.session_state.window_state:
    st.session_state.window_state[slug] = {
        "high_early": {"Up": False, "Down": False},
        "pulled_back": {"Up": False, "Down": False},
    }
ws = st.session_state.window_state[slug]

col1, col2, col3, col4 = st.columns(4)
with col1:
    st.metric("Now (UTC)", now.strftime("%H:%M:%S"))
with col2:
    rem = window_end - now
    st.metric("Time left", str(rem).split(".")[0] if rem.total_seconds() > 0 else "Ended")
with col3:
    st.metric("Elapsed", f"{int(elapsed)}s")
with col4:
    st.metric("Trading allowed", "YES" if (can_trade and not already_opened) else "NO")

st.sidebar.write(f"Window: `{slug}`")
log(f"Window {slug} | elapsed {int(elapsed)}s | trading={'YES' if can_trade else 'NO'}")

btc_price = get_btc_spot()

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

    # Three columns: Up | BTC price | Down
    c_up, c_btc, c_down = st.columns([1, 1, 1])

    live_prices = {}
    for i in range(min(2, len(outcomes))):
        out = outcomes[i]
        price = prices[i] if i < len(prices) else 0.5
        tok = tokens[i] if i < len(tokens) else None
        live_price = get_live_price(tok) if tok else None
        live_prices[out] = live_price if live_price is not None else price

        col = c_up if i == 0 else c_down
        with col:
            st.markdown(f"### {out}")
            st.metric(f"Live price {out}", f"{live_prices[out]:.3f}")
            log(f"{out} live = {live_prices[out]:.3f}")

    with c_btc:
        st.markdown("### BTC")
        if btc_price:
            st.metric("BTC spot (TWAP proxy)", f"${btc_price:,.0f}")
        else:
            st.metric("BTC spot (TWAP proxy)", "—")
        st.caption("Chainlink TWAP not public; showing spot proxy")

    # Trading logic
    for i in range(min(2, len(outcomes))):
        out = outcomes[i]
        tok = tokens[i] if i < len(tokens) else None
        live_price = live_prices.get(out)
        if live_price is None:
            continue

        # Track early high and pullback
        if elapsed < NO_TRADE_START and live_price > 0.88:
            ws["high_early"][out] = True
            log(f"{out} high early (>0.88) – pullback required")
        if ws["high_early"][out] and live_price <= PULLBACK_LEVEL:
            ws["pulled_back"][out] = True
            log(f"{out} pulled back to ≤0.70 – now eligible on way up")

        # Determine if buy is allowed by pullback rule
        needs_pullback = ws["high_early"][out]
        pullback_ok = (not needs_pullback) or ws["pulled_back"][out]

        # Buy
        if (
            can_trade
            and not already_opened
            and pullback_ok
            and st.session_state.bank >= COST_PER_BUY
            and len(st.session_state.positions) < MAX_RECORDS
        ):
            target = next((bp for bp in BUY_PRICES if abs(live_price - bp) <= 0.015), None)
            if target:
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
                    "resolution": "pending",
                }
                st.session_state.positions.append(pos)
                st.session_state.bank -= COST_PER_BUY
                st.session_state.opened_windows.add(slug)
                log(f"BUY {out} @ {live_price:.3f} (target {target}) | bank={st.session_state.bank}")
                st.success(f"BUY {out} @ {live_price:.3f}")

else:
    st.error("Could not load 5m market.")
    log("Market load failed")

# Resolve open positions at window end
for pos in st.session_state.positions:
    if pos["status"] == "open":
        end = datetime.fromisoformat(pos["window_end"])
        if now > end:
            pos["status"] = "resolved"
            # Simple placeholder resolution (real one needs Chainlink TWAP start vs end)
            won = pos["buy_price"] >= 0.70
            pos["result"] = "WIN" if won else "LOSE"
            pos["resolution"] = "resolved " + ("UP" if won else "DOWN")
            if won:
                payout = int(COST_PER_BUY / pos["buy_price"])
                pos["pnl"] = payout - COST_PER_BUY
                st.session_state.bank += payout
            else:
                pos["pnl"] = -COST_PER_BUY
            log(f"RESOLVED {pos['outcome']} → {pos['result']} | bank={st.session_state.bank}")

# Positions table
st.header("Positions")
if st.session_state.positions:
    df = pd.DataFrame(st.session_state.positions[-MAX_RECORDS:])
    show = [c for c in ["outcome", "buy_price", "opened", "status", "result", "resolution", "pnl"] if c in df.columns]
    st.dataframe(df[show], use_container_width=True, hide_index=True)
else:
    st.info("No positions yet.")

# Logs
st.header("Live Log")
if st.session_state.logs:
    st.code("\n".join(st.session_state.logs[:40]), language="text")
else:
    st.write("No logs yet.")

st.divider()
st.caption("Botche 5.1 · buy 0.88/0.89/0.90 · no stop-loss · pullback rule · one buy/window")

if auto:
    time.sleep(1)
    st.rerun()
