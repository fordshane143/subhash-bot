"""
Subhash Strategy — Bitcoin Trading Bot
Delta Exchange India Testnet | 24/7 Railway Deploy
"""

import os
import time
import hmac
import hashlib
import json
import logging
import requests
from datetime import datetime, timedelta

# ─────────────────────────────────────────
# CONFIG — Railway Environment Variables se aayega
# ─────────────────────────────────────────
API_KEY       = os.environ.get("DELTA_API_KEY", "")
API_SECRET    = os.environ.get("DELTA_API_SECRET", "")
TG_TOKEN      = os.environ.get("TELEGRAM_TOKEN", "")
TG_CHAT_ID    = os.environ.get("TELEGRAM_CHAT_ID", "")
CAPITAL       = float(os.environ.get("CAPITAL", "100"))
TESTNET_URL   = "https://cdn-ind.testnet.deltaex.org"
SYMBOL        = "BTCUSD"
PRODUCT_ID    = 84   # BTCUSD Perpetual on India Testnet

# ─────────────────────────────────────────
# SUBHASH STRATEGY PARAMETERS
# ─────────────────────────────────────────
ROUND_STEP       = 500      # nearest 500-point round level
ENTRY_BUFFER     = 150      # points buffer from round level
SL_POINTS        = 250      # stop loss in points
MAX_SL_ATTEMPTS  = 5        # max SL hits before day pause
MIN_RR           = 3        # minimum risk:reward (1:3)
TRAIL_RR         = 1.5      # start trailing at 1:1.5
CAPITAL_RISK_PCT = 0.02     # 2% capital per trade
MAX_TRADES_DAY   = 4        # max trades per day
CANDLE_COUNT     = 5        # candles for bias detection
CHECK_INTERVAL   = 30       # seconds between price checks

# ─────────────────────────────────────────
# LOGGING
# ─────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S"
)
log = logging.getLogger("SubhashBot")

# ─────────────────────────────────────────
# TELEGRAM
# ─────────────────────────────────────────
def tg(msg: str):
    """Send Telegram message."""
    if not TG_TOKEN or not TG_CHAT_ID:
        return
    try:
        requests.post(
            f"https://api.telegram.org/bot{TG_TOKEN}/sendMessage",
            json={"chat_id": TG_CHAT_ID, "text": msg, "parse_mode": "HTML"},
            timeout=10
        )
    except Exception as e:
        log.warning(f"Telegram error: {e}")

# ─────────────────────────────────────────
# DELTA API
# ─────────────────────────────────────────
def sign(method: str, path: str, body: str = "") -> dict:
    """Generate HMAC-SHA256 signature for Delta API."""
    timestamp = str(int(time.time()))
    msg = method + timestamp + path + body
    sig = hmac.new(
        API_SECRET.encode(),
        msg.encode(),
        hashlib.sha256
    ).hexdigest()
    return {
        "api-key": API_KEY,
        "timestamp": timestamp,
        "signature": sig,
        "Content-Type": "application/json"
    }

def delta_get(path: str, auth: bool = False) -> dict:
    headers = sign("GET", path) if auth else {"Content-Type": "application/json"}
    try:
        r = requests.get(f"{TESTNET_URL}{path}", headers=headers, timeout=10)
        return r.json()
    except Exception as e:
        log.error(f"GET {path} failed: {e}")
        return {}

def delta_post(path: str, body: dict) -> dict:
    body_str = json.dumps(body)
    headers = sign("POST", path, body_str)
    try:
        r = requests.post(f"{TESTNET_URL}{path}", headers=headers, data=body_str, timeout=10)
        return r.json()
    except Exception as e:
        log.error(f"POST {path} failed: {e}")
        return {}

def delta_delete(path: str) -> dict:
    headers = sign("DELETE", path)
    try:
        r = requests.delete(f"{TESTNET_URL}{path}", headers=headers, timeout=10)
        return r.json()
    except Exception as e:
        log.error(f"DELETE {path} failed: {e}")
        return {}

def get_price() -> float:
    data = delta_get(f"/v2/tickers/{SYMBOL}")
    try:
        return float(data["result"]["close"])
    except:
        return 0.0

def get_balance() -> float:
    data = delta_get("/v2/wallet/balances", auth=True)
    try:
        for b in data.get("result", []):
            if b.get("asset_symbol") in ("USDT", "USD"):
                return float(b.get("available_balance", CAPITAL))
        return CAPITAL
    except:
        return CAPITAL

def place_order(side: str, size: int, sl: float, target: float) -> dict:
    body = {
        "product_id": PRODUCT_ID,
        "size": size,
        "side": side,
        "order_type": "market_order",
        "stop_loss_order": {
            "order_type": "market_order",
            "stop_price": round(sl, 1)
        },
        "bracket_stop_loss_limit_price": round(sl, 1),
        "bracket_take_profit_price": round(target, 1),
        "bracket_take_profit_limit_price": round(target, 1),
    }
    return delta_post("/v2/orders", body)

def close_position(side: str, size: int) -> dict:
    close_side = "sell" if side == "buy" else "buy"
    body = {
        "product_id": PRODUCT_ID,
        "size": size,
        "side": close_side,
        "order_type": "market_order",
        "reduce_only": True,
    }
    return delta_post("/v2/orders", body)

def get_open_position() -> dict:
    data = delta_get(f"/v2/positions?product_id={PRODUCT_ID}", auth=True)
    try:
        result = data.get("result", [])
        if isinstance(result, list):
            for p in result:
                if abs(float(p.get("size", 0))) > 0:
                    return p
        elif isinstance(result, dict) and abs(float(result.get("size", 0))) > 0:
            return result
    except:
        pass
    return {}

# ─────────────────────────────────────────
# STRATEGY LOGIC
# ─────────────────────────────────────────
def nearest_round_levels(price: float) -> tuple:
    lower = (price // ROUND_STEP) * ROUND_STEP
    upper = lower + ROUND_STEP
    return lower, upper

def detect_bias(candles: list) -> str:
    """Bearish/Bullish bias from recent candles."""
    if len(candles) < 3:
        return "NEUTRAL"
    recent = candles[-3:]
    bearish = sum(1 for c in recent if c["close"] < c["open"])
    bullish = sum(1 for c in recent if c["close"] > c["open"])
    if bearish >= 2:
        return "BEARISH"
    if bullish >= 2:
        return "BULLISH"
    return "NEUTRAL"

def calc_position_size(capital: float) -> int:
    risk_amt = capital * CAPITAL_RISK_PCT
    size = max(1, int(risk_amt / SL_POINTS))
    return size

def should_enter(price: float, candles: list) -> dict | None:
    lower, upper = nearest_round_levels(price)
    bias = detect_bias(candles)

    dist_upper = abs(price - upper)
    dist_lower = abs(price - lower)

    # Subhash rule: price near round level = potential trade
    # Near UPPER level → prefer SELL (resistance)
    if dist_upper <= ENTRY_BUFFER:
        # Sell if bearish or neutral (upper = resistance)
        if bias in ("BEARISH", "NEUTRAL"):
            sl     = round(price + SL_POINTS, 1)
            target = round(price - SL_POINTS * MIN_RR, 1)
            log.info(f"SELL setup @ {price} | upper level {upper} | bias {bias}")
            return {"side": "sell", "entry": price, "sl": sl, "target": target, "bias": bias}

    # Near LOWER level → prefer BUY (support)
    if dist_lower <= ENTRY_BUFFER:
        # Buy if bullish or neutral (lower = support)
        if bias in ("BULLISH", "NEUTRAL"):
            sl     = round(price - SL_POINTS, 1)
            target = round(price + SL_POINTS * MIN_RR, 1)
            log.info(f"BUY setup @ {price} | lower level {lower} | bias {bias}")
            return {"side": "buy", "entry": price, "sl": sl, "target": target, "bias": bias}

    # Strong trend override — if price is falling fast, sell at any resistance
    if len(candles) >= 3:
        recent = candles[-3:]
        strong_bear = all(c["close"] < c["open"] for c in recent)
        strong_bull = all(c["close"] > c["open"] for c in recent)

        if strong_bear and dist_upper <= ENTRY_BUFFER * 2:
            sl     = round(price + SL_POINTS, 1)
            target = round(price - SL_POINTS * MIN_RR, 1)
            log.info(f"STRONG BEAR SELL @ {price} | bias {bias}")
            return {"side": "sell", "entry": price, "sl": sl, "target": target, "bias": "STRONG_BEAR"}

        if strong_bull and dist_lower <= ENTRY_BUFFER * 2:
            sl     = round(price - SL_POINTS, 1)
            target = round(price + SL_POINTS * MIN_RR, 1)
            log.info(f"STRONG BULL BUY @ {price} | bias {bias}")
            return {"side": "buy", "entry": price, "sl": sl, "target": target, "bias": "STRONG_BULL"}

    return None

# ─────────────────────────────────────────
# BOT STATE
# ─────────────────────────────────────────
class BotState:
    def __init__(self):
        self.active_trade   = None
        self.sl_attempts    = 0
        self.today_trades   = 0
        self.last_reset     = datetime.now().date()
        self.candles        = []
        self.last_price     = 0.0
        self.wins           = 0
        self.losses         = 0
        self.total_pnl      = 0.0

    def reset_daily(self):
        today = datetime.now().date()
        if today != self.last_reset:
            self.sl_attempts  = 0
            self.today_trades = 0
            self.last_reset   = today
            log.info("Daily counters reset")
            tg("🌅 <b>Naya Din!</b>\nSL attempts aur trade count reset ho gaya.")

    def add_candle(self, price: float):
        """Build simple candles from price ticks."""
        now = datetime.now()
        if not self.candles:
            self.candles.append({"open": price, "high": price, "low": price, "close": price, "time": now})
            return
        last = self.candles[-1]
        # New 5-min candle
        if (now - last["time"]).seconds >= 300:
            self.candles.append({"open": price, "high": price, "low": price, "close": price, "time": now})
            if len(self.candles) > 20:
                self.candles.pop(0)
        else:
            last["close"] = price
            last["high"]  = max(last["high"], price)
            last["low"]   = min(last["low"], price)

state = BotState()

# ─────────────────────────────────────────
# TRADE MANAGEMENT
# ─────────────────────────────────────────
def enter_trade(signal: dict, capital: float):
    size = calc_position_size(capital)
    result = place_order(signal["side"], size, signal["sl"], signal["target"])

    if result.get("success"):
        state.active_trade = {**signal, "size": size, "entry_time": datetime.now(), "trail_sl": None}
        state.today_trades += 1
        msg = (
            f"🚀 <b>TRADE ENTERED</b>\n"
            f"Side: <b>{signal['side'].upper()}</b>\n"
            f"Entry: <b>${signal['entry']:,.1f}</b>\n"
            f"Stop Loss: <b>${signal['sl']:,.1f}</b> ({SL_POINTS} pts)\n"
            f"Target: <b>${signal['target']:,.1f}</b> (1:{MIN_RR})\n"
            f"Size: {size} contracts\n"
            f"Bias: {signal['bias']}\n"
            f"Trade #{state.today_trades} today"
        )
        log.info(f"TRADE ENTERED — {signal['side'].upper()} @ {signal['entry']}")
        tg(msg)
    else:
        err = result.get("error", {}).get("code", "Unknown")
        log.error(f"Order failed: {err}")
        tg(f"⚠️ Order place nahi hua: {err}")

def check_trade(price: float):
    t = state.active_trade
    if not t:
        return

    sl     = t.get("trail_sl") or t["sl"]
    target = t["target"]
    pnl    = (price - t["entry"]) * t["size"] if t["side"] == "buy" else (t["entry"] - price) * t["size"]

    # SL hit
    sl_hit = (t["side"] == "buy" and price <= sl) or (t["side"] == "sell" and price >= sl)
    # Target hit
    tgt_hit = (t["side"] == "buy" and price >= target) or (t["side"] == "sell" and price <= target)

    if sl_hit or tgt_hit:
        reason = "🎯 Target Hit!" if tgt_hit else "❌ Stop Loss Hit"
        is_win = tgt_hit
        state.wins   += 1 if is_win else 0
        state.losses += 0 if is_win else 1
        state.total_pnl += pnl
        if not is_win:
            state.sl_attempts += 1

        close_position(t["side"], t["size"])

        win_rate = round(state.wins / (state.wins + state.losses) * 100) if (state.wins + state.losses) > 0 else 0
        msg = (
            f"{'✅' if is_win else '❌'} <b>{reason}</b>\n"
            f"Side: {t['side'].upper()}\n"
            f"Entry: ${t['entry']:,.1f} → Exit: ${price:,.1f}\n"
            f"P&L: <b>{'+'if pnl>=0 else ''}{pnl:.2f} USD</b>\n"
            f"Total P&L: ${state.total_pnl:+.2f}\n"
            f"Win Rate: {win_rate}% ({state.wins}W/{state.losses}L)\n"
            f"SL Attempts today: {state.sl_attempts}/{MAX_SL_ATTEMPTS}"
        )
        log.info(f"TRADE CLOSED — {reason} | PnL: {pnl:+.2f}")
        tg(msg)
        state.active_trade = None
        return

    # Trailing SL update
    trail_trigger = SL_POINTS * TRAIL_RR
    if t["side"] == "sell" and price < t["entry"] - trail_trigger:
        new_trail = round(price + SL_POINTS * 0.6, 1)
        if t.get("trail_sl") is None or new_trail < t["trail_sl"]:
            state.active_trade["trail_sl"] = new_trail
            log.info(f"Trail SL updated → {new_trail}")
            tg(f"📉 <b>Trail SL Updated</b>\nNew SL: ${new_trail:,.1f}")

    if t["side"] == "buy" and price > t["entry"] + trail_trigger:
        new_trail = round(price - SL_POINTS * 0.6, 1)
        if t.get("trail_sl") is None or new_trail > t["trail_sl"]:
            state.active_trade["trail_sl"] = new_trail
            log.info(f"Trail SL updated → {new_trail}")
            tg(f"📈 <b>Trail SL Updated</b>\nNew SL: ${new_trail:,.1f}")

# ─────────────────────────────────────────
# MAIN LOOP
# ─────────────────────────────────────────
def main():
    log.info("=" * 50)
    log.info("  Subhash Bot — BTC Trading Agent")
    log.info("  Delta Exchange India Testnet")
    log.info("=" * 50)

    if not API_KEY or not API_SECRET:
        log.error("DELTA_API_KEY aur DELTA_API_SECRET set karo!")
        return

    tg(
        f"🤖 <b>Subhash Bot Started!</b>\n"
        f"Capital: ${CAPITAL}\n"
        f"Strategy: Round Level + Price Action\n"
        f"Symbol: BTCUSD Perpetual\n"
        f"Max Trades/Day: {MAX_TRADES_DAY}\n"
        f"Risk/Trade: {CAPITAL_RISK_PCT*100}% = ${CAPITAL*CAPITAL_RISK_PCT:.2f}\n"
        f"SL: {SL_POINTS} pts | Target: 1:{MIN_RR}"
    )

    balance = get_balance()
    log.info(f"Balance: ${balance:.2f}")

    while True:
        try:
            state.reset_daily()
            price = get_price()

            if price <= 0:
                log.warning("Price fetch failed, retry in 30s...")
                time.sleep(CHECK_INTERVAL)
                continue

            state.add_candle(price)
            lower, upper = nearest_round_levels(price)
            log.info(f"BTC: ${price:,.1f} | Levels: ${lower:,.0f} / ${upper:,.0f} | SL: {state.sl_attempts}/{MAX_SL_ATTEMPTS} | Trades: {state.today_trades}/{MAX_TRADES_DAY}")

            # Manage existing trade
            if state.active_trade:
                check_trade(price)

            # Look for new setup
            elif state.today_trades < MAX_TRADES_DAY and state.sl_attempts < MAX_SL_ATTEMPTS:
                signal = should_enter(price, state.candles)
                if signal:
                    balance = get_balance()
                    enter_trade(signal, balance)
            elif state.sl_attempts >= MAX_SL_ATTEMPTS:
                log.info(f"Max SL attempts reached ({MAX_SL_ATTEMPTS}) — paused for today")

        except Exception as e:
            log.error(f"Main loop error: {e}")
            tg(f"⚠️ <b>Bot Error:</b> {e}")

        time.sleep(CHECK_INTERVAL)

if __name__ == "__main__":
    main()
