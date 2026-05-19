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
from datetime import datetime, timezone, timedelta

API_KEY       = os.environ.get("DELTA_API_KEY", "")
API_SECRET    = os.environ.get("DELTA_API_SECRET", "")
TG_TOKEN      = os.environ.get("TELEGRAM_TOKEN", "")
TG_CHAT_ID    = os.environ.get("TELEGRAM_CHAT_ID", "")
CAPITAL       = float(os.environ.get("CAPITAL", "100"))
TESTNET_URL   = "https://cdn-ind.testnet.deltaex.org"
SYMBOL        = "BTCUSD"
PRODUCT_ID    = 84
DATA_FILE     = "bot_data.json"

# ─────────────────────────────────────────
# SUBHASH STRATEGY PARAMETERS
# ─────────────────────────────────────────
ROUND_STEP       = 500
SL_POINTS        = 250
MAX_SL_ATTEMPTS  = 5
MIN_RR           = 3
TRAIL_RR         = 1.5
CAPITAL_RISK_PCT = 0.02
MAX_TRADES_DAY   = 4
CHECK_INTERVAL   = 30

# ─────────────────────────────────────────
# TRADING WINDOW (IST)
# Entry: 6:30 PM se 9:30 AM IST tak
# ─────────────────────────────────────────
IST = timezone(timedelta(hours=5, minutes=30))

def is_entry_allowed():
    now = datetime.now(IST)
    mins = now.hour * 60 + now.minute
    # 6:30 PM = 1110 mins, 9:30 AM = 570 mins
    # Window: >= 1110 OR <= 570 (crosses midnight)
    return mins >= 1110 or mins <= 570

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
def tg(msg):
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
# DATA SAVE
# ─────────────────────────────────────────
def save_data(price=0):
    try:
        t = state.active_trade
        active = None
        if t:
            active = {
                "side": t["side"], "entry": t["entry"],
                "sl": t.get("trail_sl") or t["sl"],
                "target": t["target"], "size": t["size"],
                "bias": t.get("bias", ""),
                "entry_time": t["entry_time"].strftime("%H:%M:%S") if isinstance(t.get("entry_time"), datetime) else "",
            }
        total = state.wins + state.losses
        lower = (price // ROUND_STEP) * ROUND_STEP if price else 0
        data = {
            "price": price, "lower": lower, "upper": lower + ROUND_STEP,
            "capital": CAPITAL, "wins": state.wins, "losses": state.losses,
            "total_pnl": round(state.total_pnl, 2),
            "win_rate": round(state.wins / total * 100) if total else 0,
            "sl_attempts": state.sl_attempts, "today_trades": state.today_trades,
            "max_trades": MAX_TRADES_DAY, "max_sl": MAX_SL_ATTEMPTS,
            "active_trade": active, "trades": state.trade_history[-50:],
            "updated": datetime.now(IST).strftime("%Y-%m-%d %H:%M:%S IST"),
            "entry_window": is_entry_allowed(), "status": "running",
        }
        with open(DATA_FILE, "w") as f:
            json.dump(data, f)
    except Exception as e:
        log.error(f"save_data error: {e}")

# ─────────────────────────────────────────
# DELTA API
# ─────────────────────────────────────────
def sign(method, path, body=""):
    timestamp = str(int(time.time()))
    msg = method + timestamp + path + body
    sig = hmac.new(API_SECRET.encode(), msg.encode(), hashlib.sha256).hexdigest()
    return {"api-key": API_KEY, "timestamp": timestamp, "signature": sig, "Content-Type": "application/json"}

def delta_get(path, auth=False):
    headers = sign("GET", path) if auth else {"Content-Type": "application/json"}
    try:
        r = requests.get(f"{TESTNET_URL}{path}", headers=headers, timeout=10)
        return r.json()
    except Exception as e:
        log.error(f"GET {path} failed: {e}")
        return {}

def delta_post(path, body):
    body_str = json.dumps(body)
    headers = sign("POST", path, body_str)
    try:
        r = requests.post(f"{TESTNET_URL}{path}", headers=headers, data=body_str, timeout=10)
        return r.json()
    except Exception as e:
        log.error(f"POST {path} failed: {e}")
        return {}

def get_price():
    data = delta_get(f"/v2/tickers/{SYMBOL}")
    try:
        return float(data["result"]["close"])
    except:
        return 0.0

def get_balance():
    data = delta_get("/v2/wallet/balances", auth=True)
    try:
        for b in data.get("result", []):
            if b.get("asset_symbol") in ("USDT", "USD"):
                return float(b.get("available_balance", CAPITAL))
        return CAPITAL
    except:
        return CAPITAL

def place_order(side, size, sl, target):
    """Single order — ya buy ya sell, dono nahi."""
    body = {
        "product_id": PRODUCT_ID, "size": size, "side": side,
        "order_type": "market_order",
        "stop_loss_order": {"order_type": "market_order", "stop_price": round(sl, 1)},
        "bracket_take_profit_price": round(target, 1),
        "bracket_take_profit_limit_price": round(target, 1),
    }
    return delta_post("/v2/orders", body)

def close_current_position(side, size):
    """
    Existing position close karo.
    LONG close karne ke liye SELL, SHORT close ke liye BUY.
    reduce_only=True ensures sirf close hoga, naya open nahi.
    """
    close_side = "sell" if side == "buy" else "buy"
    body = {
        "product_id": PRODUCT_ID, "size": size,
        "side": close_side, "order_type": "market_order",
        "reduce_only": True
    }
    return delta_post("/v2/orders", body)

# ─────────────────────────────────────────
# STRATEGY — LEVEL CROSSOVER
# ─────────────────────────────────────────
def nearest_round_levels(price):
    lower = (price // ROUND_STEP) * ROUND_STEP
    return lower, lower + ROUND_STEP

def detect_bias(candles):
    if len(candles) < 3:
        return "NEUTRAL"
    recent = candles[-3:]
    bearish = sum(1 for c in recent if c["close"] < c["open"])
    bullish = sum(1 for c in recent if c["close"] > c["open"])
    if bearish >= 2: return "BEARISH"
    if bullish >= 2: return "BULLISH"
    return "NEUTRAL"

def calc_position_size(capital):
    return max(1, int(capital * CAPITAL_RISK_PCT / SL_POINTS))

def check_crossover(prev_price, curr_price):
    """
    Round level CROSS hone pe signal deta hai.

    SELL signal:
    - Price upar se neeche cross kare round level ko
    - Jaise prev=77,100 curr=76,950 → $77,000 cross hua SELL

    BUY signal:
    - Price neeche se upar cross kare round level ko
    - Jaise prev=76,900 curr=77,050 → $77,000 cross hua BUY
    """
    if prev_price <= 0 or curr_price <= 0:
        return None

    prev_lower, prev_upper = nearest_round_levels(prev_price)
    curr_lower, curr_upper = nearest_round_levels(curr_price)

    # SELL: price ne level ko upar se neeche cross kiya
    # prev_price > level AND curr_price < level
    for level in [prev_lower, prev_upper, curr_lower, curr_upper]:
        if prev_price > level and curr_price < level:
            sl     = round(curr_price + SL_POINTS, 1)
            target = round(curr_price - SL_POINTS * MIN_RR, 1)
            log.info(f"SELL CROSSOVER: ${prev_price:.1f} → ${curr_price:.1f} | Level crossed: ${level:.0f}")
            return {"side": "sell", "entry": curr_price, "sl": sl, "target": target, "bias": f"CROSS↓${level:.0f}"}

        # BUY: price ne level ko neeche se upar cross kiya
        if prev_price < level and curr_price > level:
            sl     = round(curr_price - SL_POINTS, 1)
            target = round(curr_price + SL_POINTS * MIN_RR, 1)
            log.info(f"BUY CROSSOVER: ${prev_price:.1f} → ${curr_price:.1f} | Level crossed: ${level:.0f}")
            return {"side": "buy", "entry": curr_price, "sl": sl, "target": target, "bias": f"CROSS↑${level:.0f}"}

    return None

# ─────────────────────────────────────────
# BOT STATE
# ─────────────────────────────────────────
class BotState:
    def __init__(self):
        self.active_trade    = None   # SIRF EK trade at a time
        self.prev_price      = 0.0    # crossover detect karne ke liye
        self.sl_attempts     = 0
        self.today_trades    = 0
        self.last_reset      = datetime.now(IST).date()
        self.candles         = []
        self.wins            = 0
        self.losses          = 0
        self.total_pnl       = 0.0
        self.trade_history   = []
        self.window_notified = False

    def reset_daily(self):
        today = datetime.now(IST).date()
        if today != self.last_reset:
            self.sl_attempts     = 0
            self.today_trades    = 0
            self.last_reset      = today
            self.window_notified = False
            log.info("Daily counters reset")
            tg("🌅 <b>Naya Din!</b>\nCounters reset ho gaye.")

    def add_candle(self, price):
        now = datetime.now(IST)
        if not self.candles:
            self.candles.append({"open": price, "high": price, "low": price, "close": price, "time": now})
            return
        last = self.candles[-1]
        if (now - last["time"]).seconds >= 300:
            self.candles.append({"open": price, "high": price, "low": price, "close": price, "time": now})
            if len(self.candles) > 20: self.candles.pop(0)
        else:
            last["close"] = price
            last["high"]  = max(last["high"], price)
            last["low"]   = min(last["low"], price)

state = BotState()

# ─────────────────────────────────────────
# TRADE MANAGEMENT
# ─────────────────────────────────────────
def enter_trade(signal, capital):
    """
    Naya trade enter karo.
    Agar koi active trade hai — pehle close karo, phir naya open karo.
    Delta mein reduce_only se close, phir fresh order se open.
    """
    # Agar active trade hai — pehle close karo
    if state.active_trade:
        log.info(f"Active {state.active_trade['side'].upper()} trade close kar rahe hain...")
        close_current_position(state.active_trade["side"], state.active_trade["size"])
        time.sleep(2)  # close hone ka wait karo
        state.active_trade = None

    size   = calc_position_size(capital)
    result = place_order(signal["side"], size, signal["sl"], signal["target"])

    if result.get("success"):
        state.active_trade = {
            **signal, "size": size,
            "entry_time": datetime.now(IST),
            "trail_sl": None
        }
        state.today_trades += 1
        now_str = datetime.now(IST).strftime("%H:%M IST")
        tg(
            f"🚀 <b>TRADE ENTERED</b>\n"
            f"Side: <b>{signal['side'].upper()}</b>\n"
            f"Entry: <b>${signal['entry']:,.1f}</b>\n"
            f"Stop Loss: <b>${signal['sl']:,.1f}</b> ({SL_POINTS} pts)\n"
            f"Target: <b>${signal['target']:,.1f}</b> (1:{MIN_RR})\n"
            f"Size: {size} | Signal: {signal['bias']}\n"
            f"Trade #{state.today_trades}/{MAX_TRADES_DAY} | {now_str}"
        )
        log.info(f"TRADE ENTERED — {signal['side'].upper()} @ {signal['entry']}")
    else:
        err = result.get("error", {}).get("code", "Unknown")
        log.error(f"Order failed: {err}")
        tg(f"⚠️ Order place nahi hua: {err}")

def check_trade(price):
    t = state.active_trade
    if not t:
        return

    sl     = t.get("trail_sl") or t["sl"]
    target = t["target"]
    pnl    = (price - t["entry"]) * t["size"] if t["side"] == "buy" else (t["entry"] - price) * t["size"]

    sl_hit  = (t["side"] == "buy"  and price <= sl)     or (t["side"] == "sell" and price >= sl)
    tgt_hit = (t["side"] == "buy"  and price >= target) or (t["side"] == "sell" and price <= target)

    if sl_hit or tgt_hit:
        reason = "🎯 Target Hit!" if tgt_hit else "❌ Stop Loss Hit"
        is_win = tgt_hit
        state.wins      += 1 if is_win else 0
        state.losses    += 0 if is_win else 1
        state.total_pnl += pnl
        if not is_win:
            state.sl_attempts += 1

        close_current_position(t["side"], t["size"])

        state.trade_history.append({
            "side": t["side"], "entry": t["entry"], "exit": round(price, 1),
            "pnl": round(pnl, 2), "result": "WIN" if is_win else "LOSS",
            "reason": reason, "time": datetime.now(IST).strftime("%d/%m %H:%M"),
            "size": t["size"],
        })

        total = state.wins + state.losses
        wr    = round(state.wins / total * 100) if total else 0
        tg(
            f"{'✅' if is_win else '❌'} <b>{reason}</b>\n"
            f"{t['side'].upper()} | ${t['entry']:,.1f} → ${price:,.1f}\n"
            f"P&L: <b>{'+' if pnl>=0 else ''}{pnl:.2f} USD</b>\n"
            f"Total P&L: ${state.total_pnl:+.2f}\n"
            f"Win Rate: {wr}% ({state.wins}W/{state.losses}L)"
        )
        log.info(f"TRADE CLOSED — {reason} | PnL: {pnl:+.2f}")
        state.active_trade = None
        return

    # Trailing SL
    trail_trigger = SL_POINTS * TRAIL_RR
    if t["side"] == "sell" and price < t["entry"] - trail_trigger:
        new_trail = round(price + SL_POINTS * 0.6, 1)
        if t.get("trail_sl") is None or new_trail < t["trail_sl"]:
            state.active_trade["trail_sl"] = new_trail
            log.info(f"Trail SL → {new_trail}")
            tg(f"📉 <b>Trail SL Updated</b> → ${new_trail:,.1f}")

    if t["side"] == "buy" and price > t["entry"] + trail_trigger:
        new_trail = round(price - SL_POINTS * 0.6, 1)
        if t.get("trail_sl") is None or new_trail > t["trail_sl"]:
            state.active_trade["trail_sl"] = new_trail
            log.info(f"Trail SL → {new_trail}")
            tg(f"📈 <b>Trail SL Updated</b> → ${new_trail:,.1f}")

# ─────────────────────────────────────────
# MAIN LOOP
# ─────────────────────────────────────────
def main():
    log.info("=" * 50)
    log.info("  Subhash Bot — BTC Trading Agent")
    log.info("  Entry: Level Crossover | 6:30PM-9:30AM IST")
    log.info("=" * 50)

    if not API_KEY or not API_SECRET:
        log.error("API keys missing!")
        return

    my_ip = requests.get("https://api.ipify.org").text.strip()
    log.info(f"Railway IP: {my_ip}")

    tg(
        f"🤖 <b>Subhash Bot Started!</b>\n"
        f"Capital: ${CAPITAL} | Symbol: BTCUSD\n"
        f"Entry: Level Crossover (500 pt levels)\n"
        f"Window: 6:30 PM – 9:30 AM IST\n"
        f"SL: {SL_POINTS} pts | Target: 1:{MIN_RR}\n"
        f"Max Trades/Day: {MAX_TRADES_DAY} | Sirf ek at a time"
    )

    balance = get_balance()
    log.info(f"Balance: ${balance:.2f}")
    save_data()

    while True:
        try:
            state.reset_daily()
            price = get_price()

            if price <= 0:
                log.warning("Price fetch failed...")
                time.sleep(CHECK_INTERVAL)
                continue

            state.add_candle(price)
            lower, upper = nearest_round_levels(price)
            in_window = is_entry_allowed()
            now_ist   = datetime.now(IST).strftime("%H:%M IST")

            log.info(
                f"BTC: ${price:,.1f} | Levels: ${lower:,.0f}/${upper:,.0f} | "
                f"SL:{state.sl_attempts}/{MAX_SL_ATTEMPTS} | "
                f"Trades:{state.today_trades}/{MAX_TRADES_DAY} | "
                f"Window:{'✅' if in_window else '❌'} | {now_ist}"
            )

            # Active trade manage karo — hamesha
            if state.active_trade:
                check_trade(price)

            # Naya trade — sirf window mein aur limits ke andar
            elif (in_window
                  and state.today_trades < MAX_TRADES_DAY
                  and state.sl_attempts < MAX_SL_ATTEMPTS):

                # Crossover check karo
                signal = check_crossover(state.prev_price, price)
                if signal:
                    enter_trade(signal, get_balance())

            elif not in_window and not state.window_notified and not state.active_trade:
                log.info("Entry window closed (9:30 AM - 6:30 PM IST)")
                state.window_notified = True

            elif state.sl_attempts >= MAX_SL_ATTEMPTS:
                log.info("Max SL attempts — paused today")

            # Prev price update karo crossover ke liye
            state.prev_price = price
            save_data(price)

        except Exception as e:
            log.error(f"Error: {e}")
            tg(f"⚠️ <b>Bot Error:</b> {e}")

        time.sleep(CHECK_INTERVAL)

if __name__ == "__main__":
    main()
