# Botche 5.1 – BTC 5m Up/Down

Streamlit dashboard + rules bot for Polymarket **BTC 5-minute** Up/Down markets.

## Rules

| Rule | Description |
|------|-------------|
| 1 | No trade in the **first 75 seconds** of the window |
| 2 | No trade in the **last 85 seconds** of the window |
| 3 | Buy Up or Down at **88¢** (or 89¢ / 90¢ if 88 not available) |
| 4 | If price drops → **sell at 50¢** |

Size: **15 shares**. Dry-run by default.

## Files

- `btc_updown_app.py` – main dashboard (shows trading window status, prices, simulated buys/sells)
- `botche.py` – rules engine (same logic)
- `monitor.py` – open/closed positions + BTC price view
- `requirements.txt`

## Deploy without installing Python

1. Upload `btc_updown_app.py` + `requirements.txt` to a public GitHub repo.
2. Go to [https://share.streamlit.io](https://share.streamlit.io) → Create app → select the repo.
3. You get a free public link.

## Run locally

```bash
pip install -r requirements.txt
streamlit run btc_updown_app.py     # dashboard
python botche.py                    # rules bot (dry-run)
streamlit run monitor.py            # positions monitor
```

## Wallet setup (for live trading later)

Use a dedicated EOA signer + Deposit Wallet:

```bash
POLYMARKET_PRIVATE_KEY=0x...
POLYMARKET_DEPOSIT_WALLET=0x...
CLOB_API_KEY=...
CLOB_SECRET=...
CLOB_PASS_PHRASE=...
```

The bot uses `SignatureTypeV2.POLY_1271` when these are set.

## Notes

- Dry-run only until you explicitly enable live trading.
- Never commit private keys.
- Always test with small sizes first.
