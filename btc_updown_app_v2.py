# Botche 5.1 – BTC 5m Up/Down (v2)
# Changes:
# - Price to Beat from Polymarket Gamma (eventMetadata.priceToBeat)
# - Hedge: if opposite side reaches 0.50 after primary buy, buy 50% size opposite (do not close primary)
# - Monitor spots for ETH / SOL / DOGE / BNB below BTC
# - Max 280 records (full day)
# - Volume per window + range (small / average / high / extreme)

import streamlit as st
import requests
import pandas as pd
from datetime import datetime, timedelta
import time
import json

st.set_page_config(page_title="Botche 5m Up/Down v2", layout="wide")
st.title("Botche 5.1 – BTC 5m Up/Down (v2)")
st.caption("Price to Beat · hedge at 0.50 (50%) · volume ranges · 280 records")

# Rules
SHARES = 15
BUY_PRICES = [0.88, 0.89, 0.90]
PULLBACK_LEVEL = 0.70
HEDGE_TRIGGER = 0.50
HEDGE_RATIO = 0.50          # 50% of primary cost
NO_TRADE_START = 75
NO_TRADE_END = 85
START_BANK = 1000
COST_PER_BUY = 100
MAX_RECORDS = 280

# Volume ranges (USD) – adjustable
VOL_SMALL = 50_000
VOL_AVG = 200_000
VOL_HIGH = 500_000

def volume_range(vol):
    if vol is None:
        return "—"
    if vol < VOL_SMALL:
        return "small"
    if vol < VOL_AVG:
        return "average"
    if vol < VOL_HIGH:
        return "high"
    return "extreme"

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
    st.session_state.window_state = {}
if "hedged_windows" not in st.session_state:
    st.session_state.hedged_windows = set()

def log(msg: str):
    ts = datetime.utcnow().strftime("%H:%M:%S")
    entry = f"[{ts}] {msg}"
    st.session_state.logs.insert(0, entry)
    st.session_state.logs = st.session_state.logs[:200]

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

def get_spots():
    """CoinGecko spots for monitoring."""
    try:
        r = requests.get(
            "https://api.coingecko.com/api/v3/simple/price?ids=bitcoin,ethereum,solana,dogecoin,binancecoin&vs_currencies=usd",
            timeout=8,
        )
        if r.status_code == 200:
            d = r.json()
            return {
                "BTC": d.get("bitcoin", {}).get("usd"),
                "ETH": d.get("ethereum", {}).get("usd"),
                "SOL": d.get("solana", {}).get("usd"),
                "DOGE": d.get("dogecoin", {}).get("usd"),
                "BNB": d.get("binancecoin", {}).get("usd"),
            }
    except:
        pass
    return {}

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
st.sidebar.write(f"Primary cost: **{COST_PER_BUY}**")
st.sidebar.write(f"Hedge cost: **{int(COST_PER_BUY * HEDGE_RATIO)}**")
st.sidebar.write(f"Records: **{len(st.session_state.positions)} / {MAX_RECORDS}**")
st.sidebar.header("Rules")
st.sidebar.write("One primary buy per window")
st.sidebar.write("Buy: 0.88 → 0.89 → 0.90")
st.sidebar.write("Hedge opposite at 0.50 (50%)")
st.sidebar.write("Pullback rule if >0.88 early")
auto = st.sidebar.checkbox("Auto refresh (1s)", value=True)
if st.sidebar.button("Reset test"):
    st.session_state.bank = START_BANK
    st.session_state.positions = []
    st.session_state.logs = []
    st.session_state.opened_windows = set()
    st.session_state.window_state = {}
    st.session_state.hedged_windows = set()
    st.rerun()

slug, window_start, window_end = get_current_window()
now = datetime.utcnow()
elapsed = (now - window_start).total_seconds()
can_trade = in_trading_window(window_start, window_end, now)
already_opened = slug in st.session_state.opened_windows
already_hedged = slug in st.session_state.hedged_windows

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

spots = get_spots()

market = fetch_market(slug)
if not market or not market.get("markets"):
    prev_ts = int((window_start - timedelta(minutes=5)).timestamp())
    prev_slug = f"btc-updown-5m-{prev_ts}"
    market = fetch_market(prev_slug)
    if market:
        slug = prev_slug
        log(f"Using previous window {prev_slug}")

price_to_beat = None
volume = None
if market:
    meta = market.get("eventMetadata") or {}
    price_to_beat = meta.get("priceToBeat")
    # Volume: prefer event volume, fall back to market volume
    volume = market.get("volume") or market.get("volumeNum")
    if volume is None and market.get("markets"):
        volume = market["markets"][0].get("volume") or market["markets"][0].get("volumeNum")
    try:
        volume = float(volume) if volume is not None else None
    except:
        volume = None

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

    # Up | Price to Beat | Down
    c_up, c_ptb, c_down = st.columns([1, 1, 1])

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

    with c_ptb:
        st.markdown("### Price to Beat")
        if price_to_beat is not None:
            st.metric("Price to Beat", f"${float(price_to_beat):,.2f}")
        else:
            st.metric("Price to Beat", "—")
        if volume is not None:
            st.metric("Window volume", f"${volume:,.0f}")
            st.caption(f"Range: **{volume_range(volume)}**")
        else:
            st.metric("Window volume", "—")

    # Monitoring spots
    st.markdown("#### Spot prices (monitoring)")
    scols = st.columns(5)
    for i, coin in enumerate(["BTC", "ETH", "SOL", "DOGE", "BNB"]):
        with scols[i]:
            val = spots.get(coin)
            st.metric(coin, f"${val:,.2f}" if val else "—")

    # Trading logic
    primary_outcome = None
    for pos in st.session_state.positions:
        if pos.get("window") == slug and pos.get("type") == "primary" and pos["status"] == "open":
            primary_outcome = pos["outcome"]
            break

    for i in range(min(2, len(outcomes))):
        out = outcomes[i]
        tok = tokens[i] if i < len(tokens) else None
        live_price = live_prices.get(out)
        if live_price is None:
            continue

        # Early high / pullback tracking
        if elapsed < NO_TRADE_START and live_price > 0.88:
            ws["high_early"][out] = True
        if ws["high_early"][out] and live_price <= PULLBACK_LEVEL:
            ws["pulled_back"][out] = True

        needs_pullback = ws["high_early"][out]
        pullback_ok = (not needs_pullback) or ws["pulled_back"][out]

        # Primary buy
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
                    "type": "primary",
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
                    "volume": volume,
                    "vol_range": volume_range(volume),
                    "price_to_beat": price_to_beat,
                }
                st.session_state.positions.append(pos)
                st.session_state.bank -= COST_PER_BUY
                st.session_state.opened_windows.add(slug)
                log(f"PRIMARY BUY {out} @ {live_price:.3f} | bank={st.session_state.bank}")
                st.success(f"PRIMARY BUY {out} @ {live_price:.3f}")

        # Hedge: opposite side reaches 0.50 after primary exists, not yet hedged
        if (
            primary_outcome
            and out != primary_outcome
            and not already_hedged
            and live_price <= HEDGE_TRIGGER
            and st.session_state.bank >= int(COST_PER_BUY * HEDGE_RATIO)
            and len(st.session_state.positions) < MAX_RECORDS
        ):
            hedge_cost = int(COST_PER_BUY * HEDGE_RATIO)
            pos = {
                "token": tok,
                "outcome": out,
                "type": "hedge",
                "buy_price": round(live_price, 3),
                "shares": int(SHARES * HEDGE_RATIO),
                "cost": hedge_cost,
                "opened": now.strftime("%H:%M:%S"),
                "window": slug,
                "window_end": window_end.isoformat(),
                "status": "open",
                "result": "-",
                "pnl": 0,
                "resolution": "pending",
                "volume": volume,
                "vol_range": volume_range(volume),
                "price_to_beat": price_to_beat,
            }
            st.session_state.positions.append(pos)
            st.session_state.bank -= hedge_cost
            st.session_state.hedged_windows.add(slug)
            log(f"HEDGE BUY {out} @ {live_price:.3f} (50%) | bank={st.session_state.bank}")
            st.warning(f"HEDGE BUY {out} @ {live_price:.3f} (−{hedge_cost})")

else:
    st.error("Could not load 5m market.")
    log("Market load failed")

# Resolve open positions
for pos in st.session_state.positions:
    if pos["status"] == "open":
        end = datetime.fromisoformat(pos["window_end"])
        if now > end + timedelta(seconds=20):
            resolved_market = fetch_market(pos["window"])
            winner = None
            if resolved_market and resolved_market.get("markets"):
                rm = resolved_market["markets"][0]
                outcome_prices = parse_list(rm.get("outcomePrices"), [])
                outcomes = parse_list(rm.get("outcomes"), ["Up", "Down"])
                best_p = -1
                for i, p in enumerate(outcome_prices):
                    try:
                        fp = float(p)
                        if fp > best_p:
                            best_p = fp
                            winner = outcomes[i] if i < len(outcomes) else None
                    except:
                        pass
                if best_p < 0.95:
                    winner = None
            if winner:
                won = (str(pos["outcome"]).strip().lower() == str(winner).strip().lower())
                pos["status"] = "resolved"
                pos["result"] = "WIN" if won else "LOSE"
                pos["resolution"] = f"{winner} won"
                if won:
                    payout = int(pos["cost"] / max(pos["buy_price"], 0.01))
                    pos["pnl"] = payout - pos["cost"]
                    st.session_state.bank += payout
                else:
                    pos["pnl"] = -pos["cost"]
                log(f"RESOLVED {pos['type']} {pos['outcome']} → {pos['result']}")
            else:
                pos["resolution"] = "pending resolution"

# Positions table
st.header("Positions (max 280)")
if st.session_state.positions:
    df = pd.DataFrame(st.session_state.positions[-MAX_RECORDS:])
    show = [c for c in ["type", "outcome", "buy_price", "cost", "opened", "status", "result", "resolution", "pnl", "volume", "vol_range", "price_to_beat"] if c in df.columns]
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
st.caption("Botche 5.1 v2 · Price to Beat · hedge at 0.50 · volume ranges · 280 records")

if auto:
    time.sleep(1)
    st.rerun()
