# Botche 5.1 – BTC 5m Up/Down (v2.2)
# Fixes (Phase 1):
# 1. Price to Beat read ONCE per window and cached (stable)
# 2. Hedge: only when the LIVE PRICE of the side you bought falls to 0.50
# 3. Other coins show Polymarket live Up/Down prices (not spot)
# 4. Max 280 records
# 5. Volume improved (prefer volumeNum / volumeClob, cached once)
#
# PHASE 1 FIXES:
# - Buy by USD, not shares. shares = usd / price (derived)
# - Stop-loss: recovered = shares * sell_price (real math)
# - Win payout: payout = shares * 1.0 (real math)
# - Check market active/closed/acceptingOrders before buying
# - Sidebar shows Bank (not "Coins") and USD amounts

import streamlit as st
import requests
import pandas as pd
from datetime import datetime, timedelta
import time
import json

st.set_page_config(page_title="Botche 5m Up/Down v2.2", layout="wide")
st.title("Botche 5.1 – BTC 5m Up/Down (v2.2)")
st.caption("Price to Beat · stop primary at 0.50 + 50% hedge opposite · buy by USD")

# Rules
PRIMARY_USD = 100              # $ per primary buy
HEDGE_RATIO = 0.50             # 50% of primary USD for hedge
HEDGE_USD = int(PRIMARY_USD * HEDGE_RATIO)   # $50
BUY_PRICES = [0.88, 0.89, 0.90]   # reference levels (trigger zone 0.879–0.901)
PULLBACK_LEVEL = 0.70
HEDGE_TRIGGER = 0.50          # stop primary + open hedge when bought side hits this
NO_TRADE_START = 75
NO_TRADE_END = 85
START_BANK = 1000
MAX_RECORDS = 280

# Volume ranges for Binance BTCUSDT 5m quote volume (USDT)
VOL_SMALL = 500_000
VOL_AVG = 2_000_000
VOL_HIGH = 5_000_000

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
if "window_meta" not in st.session_state:
    st.session_state.window_meta = {}
if "start_time" not in st.session_state:
    st.session_state.start_time = datetime.utcnow()

def log(msg: str):
    ts = datetime.utcnow().strftime("%H:%M:%S")
    entry = f"[{ts}] {msg}"
    st.session_state.logs.insert(0, entry)
    st.session_state.logs = st.session_state.logs[:200]

def get_current_window(prefix="btc"):
    now = datetime.utcnow()
    minute = (now.minute // 5) * 5
    start = now.replace(minute=minute, second=0, microsecond=0)
    ts = int(start.timestamp())
    end = start + timedelta(minutes=5)
    return f"{prefix}-updown-5m-{ts}", start, end

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

def is_market_tradeable(market):
    """Check active / closed / acceptingOrders before buying."""
    if not market or not market.get("markets"):
        return False
    m = market["markets"][0]
    if m.get("closed") is True:
        return False
    if m.get("active") is False:
        return False
    if m.get("acceptingOrders") is False:
        return False
    return True

def get_binance_5m_volume(window_start):
    """BTCUSDT 5m quote volume (USDT) from Binance public API. Read once per window."""
    try:
        start_ms = int(window_start.timestamp() * 1000)
        r = requests.get(
            "https://data-api.binance.vision/api/v3/klines",
            params={"symbol": "BTCUSDT", "interval": "5m", "startTime": start_ms, "limit": 1},
            timeout=8,
        )
        if r.status_code == 200:
            data = r.json()
            if data and len(data) > 0:
                # index 7 = quote asset volume (USDT)
                return float(data[0][7])
    except Exception as e:
        log(f"Binance volume error: {e}")
    return None

def get_other_coin_prices():
    """Polymarket live Up/Down prices for ETH, SOL, DOGE, BNB."""
    coins = ["eth", "sol", "doge", "bnb"]
    result = {}
    for coin in coins:
        slug, _, _ = get_current_window(coin)
        mkt = fetch_market(slug)
        if not mkt or not mkt.get("markets"):
            result[coin.upper()] = {"Up": None, "Down": None}
            continue
        mm = mkt["markets"][0]
        tokens = parse_list(mm.get("clobTokenIds"), [])
        outcomes = parse_list(mm.get("outcomes"), ["Up", "Down"])
        prices = {}
        for i, out in enumerate(outcomes[:2]):
            tok = tokens[i] if i < len(tokens) else None
            prices[out] = get_live_price(tok) if tok else None
        result[coin.upper()] = prices
    return result

# Sidebar
st.sidebar.header("Test Bank")
st.sidebar.metric("Bank", st.session_state.bank)
st.sidebar.write(f"Primary buy: **${PRIMARY_USD}**")
st.sidebar.write(f"Hedge buy: **${HEDGE_USD}** ({int(HEDGE_RATIO*100)}%)")
st.sidebar.write(f"Records: **{len(st.session_state.positions)} / {MAX_RECORDS}**")
st.sidebar.header("Rules")
st.sidebar.write("One primary buy per window")
st.sidebar.write("Buy zone: 0.879 → 0.901")
st.sidebar.write("Stop primary at 0.50 + 50% hedge")
st.sidebar.write("Pullback rule if >0.88 early")
auto = st.sidebar.checkbox("Auto refresh (1s)", value=True)
if st.sidebar.button("Reset test"):
    st.session_state.bank = START_BANK
    st.session_state.positions = []
    st.session_state.logs = []
    st.session_state.opened_windows = set()
    st.session_state.window_state = {}
    st.session_state.hedged_windows = set()
    st.session_state.window_meta = {}
    st.session_state.start_time = datetime.utcnow()
    st.rerun()

slug, window_start, window_end = get_current_window("btc")
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

col1, col2, col3, col4, col5 = st.columns(5)
with col1:
    st.metric("Now (UTC)", now.strftime("%H:%M:%S"))
with col2:
    rem = window_end - now
    st.metric("Time left", str(rem).split(".")[0] if rem.total_seconds() > 0 else "Ended")
with col3:
    st.metric("Elapsed", f"{int(elapsed)}s")
with col4:
    st.metric("Trading allowed", "YES" if (can_trade and not already_opened) else "NO")
with col5:
    runtime = now - st.session_state.start_time
    hrs, rem_sec = divmod(int(runtime.total_seconds()), 3600)
    mins, secs = divmod(rem_sec, 60)
    st.metric("Running time", f"{hrs:02d}:{mins:02d}:{secs:02d}")

st.sidebar.write(f"Window: `{slug}`")

# Cache price_to_beat + Binance volume once per window
if slug not in st.session_state.window_meta:
    market = fetch_market(slug)
    if not market or not market.get("markets"):
        prev_ts = int((window_start - timedelta(minutes=5)).timestamp())
        prev_slug = f"btc-updown-5m-{prev_ts}"
        market = fetch_market(prev_slug)
        if market:
            slug = prev_slug
            log(f"Using previous window {prev_slug}")
    ptb = None
    if market:
        meta = market.get("eventMetadata") or {}
        ptb = meta.get("priceToBeat")
    vol = get_binance_5m_volume(window_start)
    st.session_state.window_meta[slug] = {"price_to_beat": ptb, "volume": vol}
    log(f"Cached Price to Beat={ptb} Binance volume={vol} for {slug}")

meta = st.session_state.window_meta.get(slug, {})
price_to_beat = meta.get("price_to_beat")
volume = meta.get("volume")

market = fetch_market(slug)
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

    with c_ptb:
        st.markdown("### Price to Beat")
        if price_to_beat is not None:
            st.metric("Price to Beat", f"${float(price_to_beat):,.2f}")
        else:
            st.metric("Price to Beat", "—")
        if volume is not None:
            st.metric("Binance 5m volume", f"${volume:,.0f}")
            st.caption(f"Range: **{volume_range(volume)}**")
        else:
            st.metric("Binance 5m volume", "—")

    # Polymarket live prices for other coins
    st.markdown("#### Polymarket live prices (monitoring)")
    other = get_other_coin_prices()
    ocols = st.columns(4)
    for i, coin in enumerate(["ETH", "SOL", "DOGE", "BNB"]):
        with ocols[i]:
            st.markdown(f"**{coin}**")
            up = other.get(coin, {}).get("Up")
            dn = other.get(coin, {}).get("Down")
            st.metric("Up", f"{up:.3f}" if up is not None else "—")
            st.metric("Down", f"{dn:.3f}" if dn is not None else "—")

    # Check if market is tradeable (Phase 1 fix #8)
    tradeable = is_market_tradeable(market)
    if not tradeable:
        st.warning("⚠️ Market is NOT active / accepting orders. Trading disabled this tick.")

    # Trading logic
    primary_pos = None
    for pos in st.session_state.positions:
        if pos.get("window") == slug and pos.get("type") == "primary" and pos["status"] == "open":
            primary_pos = pos
            break

    for i in range(min(2, len(outcomes))):
        out = outcomes[i]
        tok = tokens[i] if i < len(tokens) else None
        live_price = live_prices.get(out)
        if live_price is None:
            continue

        # Early high / pullback
        if elapsed < NO_TRADE_START and live_price > 0.88:
            ws["high_early"][out] = True
        if ws["high_early"][out] and live_price <= PULLBACK_LEVEL:
            ws["pulled_back"][out] = True

        needs_pullback = ws["high_early"][out]
        pullback_ok = (not needs_pullback) or ws["pulled_back"][out]

        # Debug log every few seconds
        if int(elapsed) % 10 == 0:
            log(f"Check {out}: price={live_price:.3f} trade={can_trade} opened={already_opened} pullback_ok={pullback_ok}")

        # Primary buy – wider trigger so it actually catches the levels
        if (
            can_trade
            and tradeable
            and not already_opened
            and pullback_ok
            and st.session_state.bank >= PRIMARY_USD
            and len(st.session_state.positions) < MAX_RECORDS
        ):
            # Buy if price is in the 0.875–0.905 zone (covers 0.88/0.89/0.90)
            if 0.879 <= live_price <= 0.901:
                target = min(BUY_PRICES, key=lambda bp: abs(live_price - bp))
                # Phase 1 fix: buy by USD, derive shares from price
                shares = PRIMARY_USD / live_price
                pos = {
                    "token": tok,
                    "outcome": out,
                    "type": "primary",
                    "buy_price": round(live_price, 4),
                    "shares": round(shares, 4),
                    "cost": PRIMARY_USD,
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
                st.session_state.bank -= PRIMARY_USD
                st.session_state.opened_windows.add(slug)
                log(f"PRIMARY BUY {out} @ {live_price:.4f} | ${PRIMARY_USD} → {shares:.2f} shares (target {target}) | bank={st.session_state.bank}")
                st.success(f"PRIMARY BUY {out} @ {live_price:.4f} | ${PRIMARY_USD} → {shares:.2f} shares")
            else:
                pass

        # Stop primary at 0.50 AND open 50% opposite hedge at the same time
        if (
            primary_pos
            and out == primary_pos["outcome"]
            and live_price <= HEDGE_TRIGGER
            and not already_hedged
            and st.session_state.bank >= HEDGE_USD
            and len(st.session_state.positions) < MAX_RECORDS
        ):
            # 1. Stop-loss the primary (Phase 1 fix: recovered = shares * sell_price)
            recovered = primary_pos["shares"] * live_price
            primary_pos["status"] = "stopped"
            primary_pos["sell_price"] = round(live_price, 4)
            primary_pos["result"] = "stop @ 0.50"
            primary_pos["pnl"] = round(recovered - primary_pos["cost"], 4)
            primary_pos["resolution"] = "stopped"
            st.session_state.bank += recovered
            log(f"STOP primary {out} @ {live_price:.4f} | recovered=${recovered:.2f} (pnl=${primary_pos['pnl']:.2f})")

            # 2. Open opposite hedge (50% USD)
            opp_out = "Down" if out == "Up" else "Up"
            opp_idx = outcomes.index(opp_out) if opp_out in outcomes else None
            if opp_idx is not None:
                opp_tok = tokens[opp_idx] if opp_idx < len(tokens) else None
                opp_price = live_prices.get(opp_out)
                if opp_price is not None and opp_price > 0.01:
                    # Phase 1 fix: buy by USD, derive shares
                    hedge_shares = HEDGE_USD / opp_price
                    pos = {
                        "token": opp_tok,
                        "outcome": opp_out,
                        "type": "hedge",
                        "buy_price": round(opp_price, 4),
                        "shares": round(hedge_shares, 4),
                        "cost": HEDGE_USD,
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
                    st.session_state.bank -= HEDGE_USD
                    st.session_state.hedged_windows.add(slug)
                    log(f"HEDGE BUY {opp_out} @ {opp_price:.4f} | ${HEDGE_USD} → {hedge_shares:.2f} shares | bank={st.session_state.bank}")
                    st.warning(f"STOP primary @ {live_price:.4f} + HEDGE {opp_out} @ {opp_price:.4f}")

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
                    # Phase 1 fix: payout = shares * 1.0 (real math)
                    payout = pos["shares"] * 1.0
                    pos["pnl"] = round(payout - pos["cost"], 4)
                    st.session_state.bank += payout
                else:
                    pos["pnl"] = -pos["cost"]
                log(f"RESOLVED {pos['type']} {pos['outcome']} → {pos['result']} | pnl=${pos['pnl']:.2f}")
            else:
                pos["resolution"] = "pending resolution"

# Positions table
st.header("Positions (max 280)")
if st.session_state.positions:
    df = pd.DataFrame(st.session_state.positions[-MAX_RECORDS:])
    show = [c for c in ["type", "outcome", "buy_price", "shares", "cost", "opened", "status", "result", "resolution", "pnl", "volume", "vol_range", "price_to_beat"] if c in df.columns]
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
st.caption("Botche 5.1 v2.2 · buy by USD · stop primary at 0.50 + 50% opposite hedge")

if auto:
    time.sleep(1)
    st.rerun()