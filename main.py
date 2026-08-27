"""Monitor autonomo de zonas Smart Money para BTCUSDT."""

import os
import time
import threading                     # Intervención para Render
from datetime import datetime, timezone
from flask import Flask              # Intervención para Render

import ccxt
import pandas as pd
import requests

try:
    import winsound
except ImportError:
    winsound = None

# =====================================================================
# CONFIGURACIÓN FLASK PARA ENGAÑAR A RENDER (MANTIENE EL BOT VIVO GRATIS)
# =====================================================================
app = Flask(__name__)

@app.route('/')
def home():
    return "Club MarketSharks - Nuevo Algoritmo Smart Money Activo", 200
# =====================================================================

SYMBOL = os.getenv("BITGET_SYMBOL", "BTC/USDT:USDT")
TIMEFRAME = os.getenv("SMART_MONEY_TIMEFRAME", "15m")
POLL_SECONDS = int(os.getenv("SMART_MONEY_POLL_SECONDS", "15"))
CANDLE_LIMIT = int(os.getenv("SMART_MONEY_CANDLE_LIMIT", "200"))
MAX_ZONES = int(os.getenv("SMART_MONEY_MAX_ZONES", "100"))
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN", "").strip()
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "").strip()

exchange = ccxt.bitget({
    "enableRateLimit": True,
    "options": {"defaultType": "swap"},
})


def descargar_velas():
    """Descarga velas públicas; no necesita API key ni TradingView."""
    candles = exchange.fetch_ohlcv(SYMBOL, TIMEFRAME, limit=CANDLE_LIMIT)
    if len(candles) < 30:
        raise RuntimeError("Bitget devolvio muy pocas velas")

    frame = pd.DataFrame(
        candles,
        columns=["timestamp", "open", "high", "low", "close", "volume"],
    )
    for column in ["open", "high", "low", "close", "volume"]:
        frame[column] = pd.to_numeric(frame[column], errors="coerce")
    return frame.dropna().reset_index(drop=True)


def calcular_zonas(frame):
    """Encuentra Order Blocks, Fair Value Gaps y Premium/Discount."""
    zones = []
    ranges = (frame["high"] - frame["low"]).rolling(14).mean().shift(1)

    # Las zonas se crean con velas cerradas; la ultima se usa solo para el toque.
    last_index = len(frame) - 2
    for index in range(2, last_index - 1):
        base = frame.iloc[index]
        impulse = frame.iloc[index + 1]
        average_range = ranges.iloc[index]
        if pd.isna(average_range) or average_range <= 0:
            continue

        impulse_range = impulse["high"] - impulse["low"]
        bullish_impulse = (
            base["close"] < base["open"]
            and impulse["close"] > impulse["open"]
            and impulse["close"] > base["high"]
            and impulse_range >= average_range * 1.1
        )
        bearish_impulse = (
            base["close"] > base["open"]
            and impulse["close"] < impulse["open"]
            and impulse["close"] < base["low"]
            and impulse_range >= average_range * 1.1
        )

        if bullish_impulse:
            zones.append({
                "side": "COMPRA",
                "color": "AZUL",
                "type": "Order Block",
                "low": float(base["low"]),
                "high": float(base["high"]),
                "created_at": int(base["timestamp"]),
            })
        elif bearish_impulse:
            zones.append({
                "side": "VENTA",
                "color": "ROSA",
                "type": "Order Block",
                "low": float(base["low"]),
                "high": float(base["high"]),
                "created_at": int(base["timestamp"]),
            })

    # Fair Value Gaps: desequilibrios entre la vela actual y la de hace dos velas.
    for index in range(2, last_index):
        older = frame.iloc[index - 2]
        current = frame.iloc[index]
        if current["low"] > older["high"]:
            zones.append({
                "side": "COMPRA",
                "color": "VERDE",
                "type": "Fair Value Gap",
                "low": float(older["high"]),
                "high": float(current["low"]),
                "created_at": int(current["timestamp"]),
            })
        elif current["high"] < older["low"]:
            zones.append({
                "side": "VENTA",
                "color": "ROJO",
                "type": "Fair Value Gap",
                "low": float(current["high"]),
                "high": float(older["low"]),
                "created_at": int(current["timestamp"]),
            })

    # Premium/Discount del rango reciente, equivalente a las franjas de retroceso.
    swing_frame = frame.iloc[max(0, last_index - 49):last_index]
    range_high = float(swing_frame["high"].max())
    range_low = float(swing_frame["low"].min())
    zones.extend([
        {
            "side": "VENTA",
            "color": "ROSA",
            "type": "Premium",
            "low": range_high * 0.95 + range_low * 0.05,
            "high": range_high,
            "created_at": int(frame.iloc[last_index]["timestamp"]),
        },
        {
            "side": "COMPRA",
            "color": "AZUL",
            "type": "Discount",
            "low": range_low,
            "high": range_low * 0.95 + range_high * 0.05,
            "created_at": int(frame.iloc[last_index]["timestamp"]),
        },
    ])

    return zones[-MAX_ZONES:]


def toca_zona(candle, zone):
    return float(candle["high"]) >= zone["low"] and float(candle["low"]) <= zone["high"]


def sonar_senal(side):
    if winsound is None:
        return

    if side == "COMPRA":
        tonos = [(1200, 350), (1600, 350)]
    else:
        tonos = [(700, 450), (500, 450)]

    try:
        for frecuencia, duracion in tonos:
            winsound.Beep(frecuencia, duracion)
    except RuntimeError as error:
        print(f"Aviso: no se pudo reproducir el sonido: {error}", flush=True)


def enviar_telegram(side, color, zone_type, price, zone_low, zone_high):
    if not TELEGRAM_TOKEN or not TELEGRAM_CHAT_ID:
        print("Aviso: faltan TELEGRAM_TOKEN o TELEGRAM_CHAT_ID; señal sólo en terminal.", flush=True)
        return False

    direction = "🟢 COMPRA" if side == "COMPRA" else "🔴 VENTA"
    message = (
        f"🦈 *SEÑAL BTCUSDT*\n\n"
        f"{direction}\n"
        f"Zona: {color}\n"
        f"Tipo: {zone_type}\n"
        f"Precio: `{price:,.2f}`\n"
        f"Rango: `{zone_low:,.2f} - {zone_high:,.2f}`"
    )
    url = f"https://telegram.org{TELEGRAM_TOKEN}/sendMessage"
    try:
        response = requests.post(
            url,
            json={"chat_id": TELEGRAM_CHAT_ID, "text": message, "parse_mode": "Markdown"},
            timeout=10,
        )
        if response.ok:
            print("Telegram: señal enviada.", flush=True)
            return True
        print(f"Error Telegram ({response.status_code}): {response.text[:200]}", flush=True)
    except requests.RequestException as error:
        print(f"Error enviando señal a Telegram: {error}", flush=True)
    return False


def revisar_zonas(frame, zones, notified):
    """Emite una señal al tocar la vela cerrada o la vela en formacion."""
    previous = frame.iloc[-2]
    current = frame.iloc[-1]
    current_timestamp = int(current["timestamp"])

    for zone in zones:
        zone_id = (zone["side"], zone["type"], zone["created_at"])
        entered = toca_zona(current, zone) and not toca_zona(previous, zone)
        if entered and (zone_id, current_timestamp) not in notified:
            notified.add((zone_id, current_timestamp))
            sonar_senal(zone["side"])
            price = float(current["close"])
            enviar_telegram(
                zone["side"], zone["color"], zone["type"], price,
                zone["low"], zone["high"],
            )
            print(
                f"[{datetime.now(timezone.utc).isoformat(timespec='seconds')}] "
                f"SEÑAL {zone['side']} | Zona {zone['color']} | "
                f"Tipo: {zone['type']} | "
                f"BTC {float(current['close']):,.2f} | "
                f"rango {zone['low']:,.2f} - {zone['high']:,.2f}",
                flush=True,
            )


def bucle_infinito_bot():
    """El bucle infinito original del bot se mueve aquí dentro para que corra de fondo."""
    notified = set()
    last_candle_timestamp = None
    zones = []
    print(
        f"Monitor Smart Money activo: {SYMBOL} | {TIMEFRAME} | "
        f"consulta cada {POLL_SECONDS}s",
        flush=True,
    )
    
    while True:
        try:
            frame = descargar_velas()
            closed_timestamp = int(frame.iloc[-2]["timestamp"])
            if closed_timestamp != last_candle_timestamp:
                zones = calcular_zonas(frame)
                last_candle_timestamp = closed_timestamp
            
            # Revisar toques en cada ciclo de 15 segundos
            revisar_zonas(frame, zones, notified)
            time.sleep(POLL_SECONDS)
        except Exception as e:
            print(f"⚠️ Error en ejecución: {e}", flush=True)
            time.sleep(10)


if __name__ == "__main__":
    # 1. Lanzamos el bot infinito en segundo plano para que analice y mande alertas
    threading.Thread(target=bucle_infinito_bot, daemon=True).start()
    
    # 2. Encendemos Flask en el hilo principal para que Render vea el puerto abierto y no dé error
    port = int(os.environ.get("PORT", 10000))
    app.run(host="0.0.0.0", port=port)
