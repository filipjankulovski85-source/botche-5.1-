# Botche 5.1 – BTC 5m Up/Down Rules
# 1. No trade first 75s
# 2. No trade last 85s
# 3. Buy at 88¢ (or 89¢ / 90¢)
# 4. Sell if price drops to 50¢

import os
from datetime import datetime, timedelta
from typing import Optional

from py_clob_client_v2 import ClobClient, OrderArgs, OrderType, Side, SignatureTypeV2, ApiCreds

HOST = "https://clob.polymarket.com"
CHAIN_ID = 137

NO_TRADE_START = 75
NO_TRADE_END = 85
BUY_PRICES = [0.88, 0.89, 0.90]
SELL_PRICE = 0.50
SHARES = 15


class Botche:
    def __init__(self, private_key=None, deposit_wallet=None, api_key=None, api_secret=None, api_passphrase=None, dry_run=True):
        self.dry_run = dry_run
        self.authenticated = False
        self.client = ClobClient(HOST, chain_id=CHAIN_ID)

        if private_key and deposit_wallet and api_key and api_secret and api_passphrase:
            creds = ApiCreds(api_key=api_key, api_secret=api_secret, api_passphrase=api_passphrase)
            self.client = ClobClient(
                host=HOST,
                chain_id=CHAIN_ID,
                key=private_key,
                creds=creds,
                signature_type=SignatureTypeV2.POLY_1271,
                funder=deposit_wallet,
            )
            self.authenticated = True

    def in_trading_window(self, window_start: datetime, window_end: datetime) -> bool:
        now = datetime.utcnow()
        elapsed = (now - window_start).total_seconds()
        remaining = (window_end - now).total_seconds()
        return elapsed >= NO_TRADE_START and remaining >= NO_TRADE_END

    def get_best_ask(self, token_id: str) -> Optional[float]:
        try:
            book = self.client.get_order_book(token_id)
            if book and book.asks:
                return float(book.asks[0].price)
        except Exception as e:
            print(f"Book error: {e}")
        return None

    def try_buy(self, token_id: str, window_start: datetime, window_end: datetime):
        if not self.in_trading_window(window_start, window_end):
            return {"status": "outside_trading_window"}

        best_ask = self.get_best_ask(token_id)
        if best_ask is None:
            return {"status": "no_book"}

        target = None
        for bp in BUY_PRICES:
            if best_ask <= bp:
                target = bp
                break
        if not target:
            return {"status": "price_too_high", "best_ask": best_ask}

        if self.dry_run or not self.authenticated:
            return {"status": "dry_run_buy", "price": best_ask, "size": SHARES}

        order = OrderArgs(token_id=token_id, price=best_ask, size=SHARES, side=Side.BUY)
        signed = self.client.create_order(order)
        resp = self.client.post_order(signed, OrderType.GTC)
        return {"status": "bought", "price": best_ask, "resp": resp}

    def try_sell(self, token_id: str):
        best_ask = self.get_best_ask(token_id)
        if best_ask and best_ask <= SELL_PRICE:
            if self.dry_run or not self.authenticated:
                return {"status": "dry_run_sell", "price": best_ask}
            order = OrderArgs(token_id=token_id, price=best_ask, size=SHARES, side=Side.SELL)
            signed = self.client.create_order(order)
            resp = self.client.post_order(signed, OrderType.GTC)
            return {"status": "sold", "price": best_ask, "resp": resp}
        return {"status": "no_sell", "best_ask": best_ask}


if __name__ == "__main__":
    bot = Botche(dry_run=True)
    print("Botche 5m rules loaded (dry-run).")
    print(f"Buy levels: {BUY_PRICES} | Sell at: {SELL_PRICE}")
    print(f"No trade first {NO_TRADE_START}s / last {NO_TRADE_END}s")
