import os
import threading
import time
import requests
from datetime import datetime
from zoneinfo import ZoneInfo

import ccxt
import pandas as pd

from flask import Flask

app = Flask(__name__)


@app.route("/")
def home():
    return "Club MarketSharks - Bot Demo + Telegram + Bitget", 200


@app.route("/health")
def health():
    return "ok", 200


# --- CONFIG ---
TOKEN_TELEGRAM = os.getenv("TELEGRAM_TOKEN", "").strip()
CHAT_ID_CANAL = os.getenv("TELEGRAM_CHAT_ID", "").strip()

BITGET_API_KEY = os.getenv("BITGET_API_KEY", "")
BITGET_API_SECRET = os.getenv("BITGET_API_SECRET", "")
BITGET_PASSWORD = os.getenv("BITGET_PASSWORD", "")

SYMBOL_CCXT = os.getenv("BITGET_SYMBOL", "BTC/USDT:USDT")
ORDER_SYMBOL = os.getenv("BITGET_ORDER_SYMBOL", "BTCUSDT")

MARGIN_PER_TRADE = float(os.getenv("MARGIN_PER_TRADE", "2.0"))
LEVERAGE = int(os.getenv("LEVERAGE", "75"))

TP_PCT = float(os.getenv("TP_PCT", "20.0"))
TRAILING_START_PCT = float(os.getenv("TRAILING_START_PCT", "3.0"))
TRAILING_DISTANCE_PCT = float(os.getenv("TRAILING_DISTANCE_PCT", "1.5"))

AUTO_SIGNAL_ENABLED = os.getenv("AUTO_SIGNAL_ENABLED", "true").lower() in {"1", "true", "yes", "on"}
AUTO_SIGNAL_COOLDOWN_SECONDS = int(os.getenv("AUTO_SIGNAL_COOLDOWN_SECONDS", "1800"))

# --- BITGET ---
exchange = None
try:
    exchange = ccxt.bitget({
        "apiKey": BITGET_API_KEY,
        "secret": BITGET_API_SECRET,
        "password": BITGET_PASSWORD,
        "enableRateLimit": True,
        "options": {"defaultType": "swap"},
    })
    exchange.set_sandbox_mode(True)
    print("✅ Bitget sandbox inicializado")
except Exception as e:
    print("⚠️ No se pudo inicializar Bitget:", e)
    exchange = None


# --- ESTADO LOCAL ---
POSITIONS = {}
LAST_AUTO_SIGNAL = None
STOP_THREADS = threading.Event()


# --- UTILIDADES ---
def hora_espana():
    return datetime.now(ZoneInfo("Europe/Madrid"))


def send_telegram(message, chat_id=None):
    target_chat = chat_id or CHAT_ID_CANAL
    if not TOKEN_TELEGRAM or not target_chat:
        return False

    url = f"https://api.telegram.org/bot{TOKEN_TELEGRAM}/sendMessage"
    payload = {
        "chat_id": target_chat,
        "text": message,
        "parse_mode": "Markdown",
    }

    try:
        requests.post(url, json=payload, timeout=10)
        return True
    except Exception as e:
        print("⚠️ Error enviando Telegram:", e)
        return False


def build_signal_message(signal, market_name):
    direction_text = "🟢 *COMPRA*" if signal["direction"] == "COMPRA" else "🔴 *VENTA*"
    return (
        f"🦈 *SEÑAL DEMO*\n\n"
        f"📊 *Mercado:* {market_name}\n"
        f"{direction_text}\n"
        f"💵 *Entrada:* $ {signal['price']:,.2f}\n"
        f"🛡️ *Stop:* $ {signal['stop']:.2f}\n"
        f"🎯 *Take:* $ {signal['take']:.2f}\n\n"
        f"📌 Motivo: {signal['reason']}"
    )


# --- DATOS DE MERCADO ---
def fetch_ohlcv(timeframe="1m", limit=80):
    if exchange is None:
        return None
    try:
        bars = exchange.fetch_ohlcv(SYMBOL_CCXT, timeframe=timeframe, limit=limit)
        if not bars:
            return None
        df = pd.DataFrame(bars, columns=["timestamp", "open", "high", "low", "close", "volume"])
        df["close"] = pd.to_numeric(df["close"], errors="coerce")
        df["high"] = pd.to_numeric(df["high"], errors="coerce")
        df["low"] = pd.to_numeric(df["low"], errors="coerce")
        return df
    except Exception as e:
        print("⚠️ Error fetching OHLCV:", e)
        return None


def get_last_price():
    if exchange is None:
        return None
    try:
        ticker = exchange.fetch_ticker(SYMBOL_CCXT)
        return float(ticker.get("last") or ticker.get("close") or 0)
    except Exception as e:
        print("⚠️ Error obteniendo precio:", e)
        return None


# --- MOTOR DE SEÑALES ---
def generate_signal():
    df = fetch_ohlcv("1m", 80)
    if df is None or len(df) < 20:
        return None

    close = df["close"].astype(float)
    ema5 = close.ewm(span=5, adjust=False).mean()
    ema13 = close.ewm(span=13, adjust=False).mean()

    price = float(close.iloc[-1])
    ema5_now = float(ema5.iloc[-1])
    ema13_now = float(ema13.iloc[-1])
    ema5_prev = float(ema5.iloc[-2])
    ema13_prev = float(ema13.iloc[-2])
    momentum = float(price - close.iloc[-2])

    recent_low = float(df["low"].tail(3).min())
    recent_high = float(df["high"].tail(3).max())

    if ema5_now > ema13_now and ema5_prev <= ema13_prev and momentum > 0:
        direction = "COMPRA"
        stop = min(recent_low, price * 0.995)
        distance = max(price - stop, 1.0)
        take = price + distance * 2
        reason = "Cruce EMA5/EMA13 con impulso positivo"
    elif ema5_now < ema13_now and ema5_prev >= ema13_prev and momentum < 0:
        direction = "VENTA"
        stop = max(recent_high, price * 1.005)
        distance = max(stop - price, 1.0)
        take = price - distance * 2
        reason = "Cruce EMA5/EMA13 con impulso negativo"
    else:
        if price > ema13_now:
            direction = "COMPRA"
            stop = price * 0.995
            take = price * 1.01
            reason = "Fallback conservador: precio por encima de EMA13"
        elif price < ema13_now:
            direction = "VENTA"
            stop = price * 1.005
            take = price * 0.99
            reason = "Fallback conservador: precio por debajo de EMA13"
        else:
            return None

    return {
        "direction": direction,
        "price": price,
        "stop": float(stop),
        "take": float(take),
        "reason": reason,
    }


# --- GESTIÓN DE POSICIONES DEMO ---
def open_position(signal):
    if signal is None:
        return None

    side = "long" if signal["direction"] == "COMPRA" else "short"
    price = float(signal["price"])

    contratos = round((MARGIN_PER_TRADE * LEVERAGE) / price, 4)
    key = f"{side}-{int(time.time() * 1000)}"

    POSITIONS[key] = {
        "side": side,
        "entry": price,
        "stop": float(signal["stop"]),
        "take": float(signal["take"]),
        "highest": price,
        "trailing_active": False,
        "contracts": contratos,
    }

    # Intento de apertura real en Bitget si hay credenciales
    if exchange is not None:
        try:
            order_side = "buy" if side == "long" else "sell"
            params = {
                "symbol": ORDER_SYMBOL,
                "productType": "USDT-FUTURES",
                "marginMode": "isolated",
                "marginCoin": "USDT",
                "side": order_side,
                "tradeSide": "open",
                "orderType": "market",
                "size": str(contratos),
            }
            exchange.privateMixPostV2MixOrderPlaceOrder(params)
        except Exception as e:
            print("⚠️ Apertura real fallida, se mantiene solo demo:", e)

    return key


def close_position(key, reason):
    pos = POSITIONS.pop(key, None)
    if not pos:
        return False

    if pos["side"] == "long":
        text = f"✅ Posición larga cerrada ({reason})"
    else:
        text = f"✅ Posición corta cerrada ({reason})"

    send_telegram(text)
    return True


def monitor_positions():
    while not STOP_THREADS.is_set():
        try:
            price = get_last_price()
            if price is None:
                time.sleep(2)
                continue

            for key in list(POSITIONS.keys()):
                pos = POSITIONS.get(key)
                if not pos:
                    continue

                if pos["side"] == "long":
                    if price >= pos["take"]:
                        close_position(key, "TP")
                    elif price <= pos["stop"]:
                        close_position(key, "Stop Loss")
                    else:
                        if price > pos["highest"]:
                            pos["highest"] = price

                        beneficio_pct = (price - pos["entry"]) / pos["entry"] * 100
                        if (not pos["trailing_active"]) and beneficio_pct >= TRAILING_START_PCT:
                            pos["trailing_active"] = True

                        if pos["trailing_active"]:
                            trail_price = pos["highest"] * (1 - TRAILING_DISTANCE_PCT / 100)
                            if price <= trail_price:
                                close_position(key, "Trailing Stop")
                else:  # short
                    if price <= pos["take"]:
                        close_position(key, "TP")
                    elif price >= pos["stop"]:
                        close_position(key, "Stop Loss")
                    else:
                        if price < pos["highest"]:
                            pos["highest"] = price

                        beneficio_pct = (pos["entry"] - price) / pos["entry"] * 100
                        if (not pos["trailing_active"]) and beneficio_pct >= TRAILING_START_PCT:
                            pos["trailing_active"] = True

                        if pos["trailing_active"]:
                            trail_price = pos["highest"] * (1 + TRAILING_DISTANCE_PCT / 100)
                            if price >= trail_price:
                                close_position(key, "Trailing Stop")
        except Exception as e:
            print("⚠️ Error en monitor_positions:", e)

        time.sleep(2)


# --- TELEGRAM ---
def handle_manual_request(chat_id, market_name="BTCUSDT"):
    signal = generate_signal()
    if not signal:
        send_telegram("⚠️ No se pudo construir una señal en este momento.", chat_id=chat_id)
        return False

    message = build_signal_message(signal, market_name)
    send_telegram(message, chat_id=chat_id)

    # abrir posición demo
    open_position(signal)
    return True


def telegram_listener():
    if not TOKEN_TELEGRAM:
        print("⚠️ TOKEN_TELEGRAM no configurado; listener inactivo")
        return

    offset = None
    while not STOP_THREADS.is_set():
        try:
            url = f"https://api.telegram.org/bot{TOKEN_TELEGRAM}/getUpdates"
            params = {"timeout": 10}
            if offset is not None:
                params["offset"] = offset

            r = requests.get(url, params=params, timeout=15)
            if r.status_code != 200:
                time.sleep(2)
                continue

            updates = r.json().get("result", [])
            for update in updates:
                offset = update.get("update_id", 0) + 1

                if "message" in update:
                    message = update["message"]
                    chat_id = message.get("chat", {}).get("id")
                    text = (message.get("text") or "").strip().lower()

                    if text in {"/senal", "/senalahora", "/signal", "senal", "signal", "!senal"}:
                        handle_manual_request(chat_id=chat_id, market_name="BTCUSDT")
                    elif text in {"/senalbtc", "senalbtc", "btcmanual"}:
                        handle_manual_request(chat_id=chat_id, market_name="BTCUSDT")
                    elif text in {"/senalspx", "senalspx", "spxmanual"}:
                        handle_manual_request(chat_id=chat_id, market_name="SPXUSDT")

        except Exception as e:
            print("⚠️ Error en listener de Telegram:", e)
        time.sleep(1)


# --- MOTOR AUTOMÁTICO ---
def can_send_auto_signal():
    global LAST_AUTO_SIGNAL
    if not AUTO_SIGNAL_ENABLED:
        return False
    if LAST_AUTO_SIGNAL is None:
        return True
    return (time.time() - LAST_AUTO_SIGNAL["timestamp"]) >= AUTO_SIGNAL_COOLDOWN_SECONDS


def auto_trading_loop():
    print("🚀 Motor automático iniciado")
    while not STOP_THREADS.is_set():
        try:
            if can_send_auto_signal():
                signal = generate_signal()
                if signal:
                    send_telegram(build_signal_message(signal, "BTCUSDT"))
                    open_position(signal)
                    LAST_AUTO_SIGNAL = {
                        "timestamp": time.time(),
                        "direction": signal["direction"],
                    }
            time.sleep(30)
        except Exception as e:
            print("⚠️ Error en auto_trading_loop:", e)
            time.sleep(5)


# --- ARRANQUE ---
if __name__ == "__main__":
    hilo_listener = threading.Thread(target=telegram_listener, daemon=True)
    hilo_listener.start()

    hilo_monitor = threading.Thread(target=monitor_positions, daemon=True)
    hilo_monitor.start()

    hilo_auto = threading.Thread(target=auto_trading_loop, daemon=True)
    hilo_auto.start()

    puerto = int(os.getenv("PORT", "10000"))
    app.run(host="0.0.0.0", port=puerto)
