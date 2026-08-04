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

AUTO_SIGNAL_ENABLED = os.getenv("AUTO_SIGNAL_ENABLED", "false").lower() in {"1", "true", "yes", "on"}
AUTO_SIGNAL_COOLDOWN_SECONDS = int(os.getenv("AUTO_SIGNAL_COOLDOWN_SECONDS", "86400"))

MIN_PROFIT_CLOSE_PCT = float(os.getenv("MIN_PROFIT_CLOSE_PCT", "15.0"))
MAX_POSITION_DURATION_SECONDS = int(os.getenv("MAX_POSITION_DURATION_SECONDS", "600"))

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
STARTUP_MENU_SENT = False


# --- UTILIDADES ---
def hora_espana():
    return datetime.now(ZoneInfo("Europe/Madrid"))


def send_telegram(message, chat_id=None, reply_markup=None):
    target_chat = chat_id or CHAT_ID_CANAL
    if not TOKEN_TELEGRAM or not target_chat:
        print("⚠️ No se envía Telegram: falta TOKEN_TELEGRAM o TELEGRAM_CHAT_ID")
        return False

    url = f"https://api.telegram.org/bot{TOKEN_TELEGRAM}/sendMessage"
    payload = {
        "chat_id": target_chat,
        "text": message,
        "parse_mode": "Markdown",
    }
    if reply_markup:
        payload["reply_markup"] = reply_markup

    try:
        r = requests.post(url, json=payload, timeout=10)
        if r.status_code != 200:
            print("⚠️ Error Telegram:", r.text)
            return False
        return True
    except Exception as e:
        print("⚠️ Error enviando Telegram:", e)
        return False


def send_start_menu(chat_id):
    keyboard = {
        "inline_keyboard": [
            [{"text": "⚡ Señal BTC", "callback_data": "senal_btc"}],
            [
                {"text": "▶️ Auto ON", "callback_data": "auto_on"},
                {"text": "🛑 Auto OFF", "callback_data": "auto_off"},
            ],
        ]
    }
    send_telegram(
        "🦈 MarketSharks VIP\n\nElige una señal manual para BTCUSDT:",
        chat_id=chat_id,
        reply_markup=keyboard,
    )


def build_signal_message(signal, market_name):
    direction_text = "🟢 *COMPRA*" if signal["direction"] == "COMPRA" else "🔴 *VENTA*"
    return (
        f"🦈 *SEÑAL BTCUSDT*\n\n"
        f"📊 *Mercado:* {market_name}\n"
        f"{direction_text}\n"
        f"💵 *Entrada:* $ {signal['price']:,.2f}\n"
        f"🛡️ *Stop:* $ {signal['stop']:.2f}\n"
        f"🎯 *Take 20%:* $ {signal['take']:.2f}\n\n"
        f"📌 Motivo: {signal['reason']}"
    )


# --- DATOS DE MERCADO ---
def fetch_ohlcv_timeframe(timeframe, limit=80):
    if exchange is None:
        return None
    try:
        bars = exchange.fetch_ohlcv(SYMBOL_CCXT, timeframe=timeframe, limit=limit)
        if not bars:
            return None
        df = pd.DataFrame(bars, columns=["timestamp", "open", "high", "low", "close", "volume"])
        df["open"] = pd.to_numeric(df["open"], errors="coerce")
        df["high"] = pd.to_numeric(df["high"], errors="coerce")
        df["low"] = pd.to_numeric(df["low"], errors="coerce")
        df["close"] = pd.to_numeric(df["close"], errors="coerce")
        return df
    except Exception as e:
        print("⚠️ Error fetching OHLCV:", e)
        return None


def find_order_block(df):
    if df is None or len(df) < 20:
        return None, None, None, None

    atr = (df["high"] - df["low"]).rolling(14).mean().iloc[-1]
    for i in range(len(df) - 3, 1, -1):
        base = df.iloc[i]
        impulse = df.iloc[i + 1]

        if base["close"] < base["open"] and impulse["close"] > impulse["open"]:
            if impulse["high"] > base["high"] and (impulse["high"] - impulse["low"]) > atr * 1.1:
                return "long", base["low"], base["high"], atr

        if base["close"] > base["open"] and impulse["close"] < impulse["open"]:
            if impulse["low"] < base["low"] and (impulse["high"] - impulse["low"]) > atr * 1.1:
                return "short", base["high"], base["low"], atr

    return None, None, None, atr


def generate_signal():
    df_1h = fetch_ohlcv_timeframe("1h", 80)
    df_15m = fetch_ohlcv_timeframe("15m", 80)
    if df_1h is None or df_15m is None:
        return None

    current = float(df_15m["close"].iloc[-1])
    range_20 = df_15m["high"].tail(20).max() - df_15m["low"].tail(20).min()
    range_pct = range_20 / current * 100

    if range_pct < 0.45:
        return None

    ob_side, zone_low, zone_high, atr_1h = find_order_block(df_1h)
    if ob_side is None:
        return None

    ema15_13 = df_15m["close"].ewm(span=13, adjust=False).mean().iloc[-1]
    ema15_5 = df_15m["close"].ewm(span=5, adjust=False).mean().iloc[-1]
    if df_15m["close"].iloc[-1] < df_15m["close"].iloc[-2]:
        return None

    if ob_side == "long":
        if not (zone_low * 0.995 <= current <= zone_high * 1.01):
            return None
        if current < ema15_13:
            return None
        stop = min(zone_low * 0.994, current - atr_1h * 0.8)
        take = current * 1.12
        reason = "Order Block long + confirmación 15m"
    else:
        if not (zone_high * 0.995 >= current >= zone_low * 1.01):
            return None
        if current > ema15_13:
            return None
        stop = max(zone_high * 1.006, current + atr_1h * 0.8)
        take = current * 0.88
        reason = "Order Block short + confirmación 15m"

    return {
        "direction": "COMPRA" if ob_side == "long" else "VENTA",
        "price": current,
        "stop": float(stop),
        "take": float(take),
        "reason": reason,
    }


def open_position(signal, chat_id=None):
    if signal is None:
        return None

    side = "long" if signal["direction"] == "COMPRA" else "short"
    price = float(signal["price"])
    tp_price = price * (1 + 0.12) if side == "long" else price * (1 - 0.12)

    contratos = round((MARGIN_PER_TRADE * LEVERAGE) / price, 4)
    key = f"{side}-{int(time.time() * 1000)}"

    # Intentar abrir en Bitget primero; sólo crear la posición local si la apertura remota fue exitosa
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
            open_resp = exchange.privateMixPostV2MixOrderPlaceOrder(params)
            print("open order response:", open_resp)

            take_side = "sell" if side == "long" else "buy"
            tp_params = {
                "symbol": ORDER_SYMBOL,
                "productType": "USDT-FUTURES",
                "marginMode": "isolated",
                "marginCoin": "USDT",
                "side": take_side,
                "tradeSide": "close",
                "orderType": "limit",
                "price": str(tp_price),
                "size": str(contratos),
                "timeInForce": "GTC",
            }
            # evitar enviar `reduceOnly` si la API lo rechaza
            try:
                tp_resp = exchange.privateMixPostV2MixOrderPlaceOrder(tp_params)
                print("tp order response:", tp_resp)
            except Exception as e2:
                print("⚠️ Error creando TP en Bitget (se ignorará y se seguirá con posición local):", e2)

            # Sólo registrar la posición local si no hubo excepción en la apertura
            POSITIONS[key] = {
                "side": side,
                "entry": price,
                "stop": float(signal["stop"]),
                "take": float(tp_price),
                "highest": price,
                "trailing_active": False,
                "contracts": contratos,
                "opened_at": time.time(),
            }
        except Exception as e:
            print("⚠️ Error orden Bitget:", e)
            send_telegram(f"⚠️ Error en Bitget al abrir posición: {e}", chat_id=chat_id)
            return None

    # En caso de exchange None, registramos la posición local igualmente (modo demo)
    if exchange is None:
        POSITIONS[key] = {
            "side": side,
            "entry": price,
            "stop": float(signal["stop"]),
            "take": float(tp_price),
            "highest": price,
            "trailing_active": False,
            "contracts": contratos,
            "opened_at": time.time(),
        }

    send_telegram(
        f"✅ Operación BTC abierta en Bitget\n"
        f"📊 Mercado: BTCUSDT\n"
        f"🔹 Dirección: {signal['direction']}\n"
        f"💵 Entrada: $ {price:,.2f}\n"
        f"🎯 TP 12%: $ {tp_price:,.2f}\n"
        f"🆔 ID local: {key}",
        chat_id=chat_id,
    )
    return key


def close_position(key, reason):
    pos = POSITIONS.get(key)
    if not pos:
        return False

    if exchange is not None:
        try:
            side_close = "sell" if pos["side"] == "long" else "buy"
            params = {
                "symbol": ORDER_SYMBOL,
                "productType": "USDT-FUTURES",
                "marginMode": "isolated",
                "marginCoin": "USDT",
                "side": side_close,
                "tradeSide": "close",
                "orderType": "market",
                "size": str(pos["contracts"]),
            }
            close_resp = exchange.privateMixPostV2MixOrderPlaceOrder(params)
            print("close order response:", close_resp)
        except Exception as e:
            print("⚠️ Error cerrando posición en Bitget:", e)
            send_telegram(f"⚠️ Falló cierre real en Bitget: {e}")
            return False

        # Si el cierre remoto fue exitoso, entonces eliminamos la posición local
        POSITIONS.pop(key, None)

    text = (
        f"✅ Posición BTC cerrada ({reason})\n"
        f"📊 Mercado: BTCUSDT\n"
        f"💵 Entrada: $ {pos['entry']:,.2f}\n"
        f"🎯 TP 12%: $ {pos['take']:,.2f}"
    )
    send_telegram(text)
    return True


def get_last_price():
    if exchange is None:
        return None
    try:
        ticker = exchange.fetch_ticker(SYMBOL_CCXT)
        last = ticker.get("last")
        if last is None:
            last = ticker.get("close")
        return float(last) if last is not None else None
    except Exception as e:
        print("⚠️ Error obteniendo precio de Bitget:", e)
        return None


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

                age = time.time() - pos["opened_at"]
                profit_pct = ((price - pos["entry"]) / pos["entry"] * 100) if pos["side"] == "long" else ((pos["entry"] - price) / pos["entry"] * 100)

                if profit_pct >= 12.0:
                    close_position(key, "TP 12%")
                    continue

                if age >= MAX_POSITION_DURATION_SECONDS:
                    close_position(key, "Tiempo límite 10m")
                    continue

                if pos["side"] == "long":
                    if price <= pos["stop"]:
                        close_position(key, "Stop Loss")
                    elif price >= pos["take"]:
                        close_position(key, "TP 12%")
                    else:
                        if price > pos["highest"]:
                            pos["highest"] = price
                else:
                    if price >= pos["stop"]:
                        close_position(key, "Stop Loss")
                    elif price <= pos["take"]:
                        close_position(key, "TP 12%")
                    else:
                        if price < pos["highest"]:
                            pos["highest"] = price
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
    open_position(signal, chat_id=CHAT_ID_CANAL)
    return True


def telegram_listener():
    global AUTO_SIGNAL_ENABLED
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

                    if text in {"/start", "/menu", "menu"}:
                        send_start_menu(chat_id)
                    elif text in {"/senal", "/senalahora", "/signal", "senal", "signal", "!senal"}:
                        handle_manual_request(chat_id=chat_id, market_name="BTCUSDT")
                    elif text in {"/senalbtc", "senalbtc", "btcmanual"}:
                        handle_manual_request(chat_id=chat_id, market_name="BTCUSDT")
                    elif text in {"/senalspx", "senalspx", "spxmanual"}:
                        handle_manual_request(chat_id=chat_id, market_name="SPXUSDT")

                if "callback_query" in update:
                    callback = update["callback_query"]
                    chat_id = callback.get("message", {}).get("chat", {}).get("id")
                    data = callback.get("data", "")
                    answer_url = f"https://api.telegram.org/bot{TOKEN_TELEGRAM}/answerCallbackQuery"

                    if data == "senal_btc":
                        requests.post(answer_url, json={"callback_query_id": callback.get("id"), "text": "Generando señal BTC..."}, timeout=10)
                        handle_manual_request(chat_id=chat_id, market_name="BTCUSDT")

                    if data == "senal_spx":
                        requests.post(answer_url, json={"callback_query_id": callback.get("id"), "text": "Generando señal SPX..."}, timeout=10)
                        handle_manual_request(chat_id=chat_id, market_name="SPXUSDT")

                    if data == "auto_on":
                        requests.post(answer_url, json={"callback_query_id": callback.get("id"), "text": "Auto señales activadas"}, timeout=10)
                        AUTO_SIGNAL_ENABLED = True
                        send_telegram("▶️ Señales automáticas activadas.", chat_id=chat_id)

                    if data == "auto_off":
                        requests.post(answer_url, json={"callback_query_id": callback.get("id"), "text": "Auto señales desactivadas"}, timeout=10)
                        AUTO_SIGNAL_ENABLED = False
                        send_telegram("🛑 Señales automáticas desactivadas.", chat_id=chat_id)

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
            if AUTO_SIGNAL_ENABLED and can_send_auto_signal():
                signal = generate_signal()
                if signal:
                    send_telegram(build_signal_message(signal, "BTCUSDT"))
                    open_position(signal, chat_id=CHAT_ID_CANAL)
                    LAST_AUTO_SIGNAL = {
                        "timestamp": time.time(),
                        "direction": signal["direction"],
                    }
            time.sleep(30)
        except Exception as e:
            print("⚠️ Error en auto_trading_loop:", e)
            time.sleep(5)


# --- ARRANQUE ---
def send_channel_startup_message():
    global STARTUP_MENU_SENT
    if STARTUP_MENU_SENT:
        return
    if not CHAT_ID_CANAL:
        print("⚠️ No se envía mensaje inicial: TELEGRAM_CHAT_ID vacío")
        return

    send_start_menu(CHAT_ID_CANAL)
    STARTUP_MENU_SENT = True


if __name__ == "__main__":
    hilo_listener = threading.Thread(target=telegram_listener, daemon=True)
    hilo_listener.start()

    hilo_monitor = threading.Thread(target=monitor_positions, daemon=True)
    hilo_monitor.start()

    hilo_auto = threading.Thread(target=auto_trading_loop, daemon=True)
    hilo_auto.start()

    try:
        send_channel_startup_message()
    except Exception as e:
        print("⚠️ Error enviando mensaje inicial al canal:", e)

    puerto = int(os.getenv("PORT", "10000"))
    app.run(host="0.0.0.0", port=puerto)
