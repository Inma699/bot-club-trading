"""Monitor autonomo de zonas Smart Money para BTCUSDT con ejecucion y cierre automatico en Bitget Demo."""

import os
import time
import threading                     
from datetime import datetime, timezone
from flask import Flask              

import ccxt
import pandas as pd
import requests

try:
    import winsound
except ImportError:
    winsound = None

app = Flask(__name__)

@app.route('/')
def home():
    return "Club MarketSharks - Algoritmo Smart Money con Cierre por Ganancia Activo", 200

# === CREDENCIALES DESDE ENVIRONMENT VARIABLES ===
SYMBOL = os.getenv("BITGET_SYMBOL", "BTC/USDT:USDT")
TIMEFRAME = os.getenv("SMART_MONEY_TIMEFRAME", "15m")
POLL_SECONDS = int(os.getenv("SMART_MONEY_POLL_SECONDS", "15"))
CANDLE_LIMIT = int(os.getenv("SMART_MONEY_CANDLE_LIMIT", "200"))
MAX_ZONES = int(os.getenv("SMART_MONEY_MAX_ZONES", "100"))
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN", "").strip()
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "").strip()

API_KEY = os.getenv("BITGET_API_KEY", "").strip()
SECRET_KEY = os.getenv("BITGET_API_SECRET", "").strip()  
PASSPHRASE = os.getenv("BITGET_PASSWORD", "").strip()

# =====================================================================
# ⚙️ CONFIGURACIÓN DE OBJETIVOS DE DINERO PARA EL CIERRE AUTOMÁTICO
# =====================================================================
OBJETIVO_GANANCIA_USD = 10.0  # El bot cerrará la posición al ganar esta cantidad exacta de dólares.
CANTIDAD_BTC = 0.001          # Tamaño de cada trade (Aproximadamente $80 USD de margen nominal)

# Memoria en segundo plano para rastrear las posiciones abiertas por el bot
POSICIONES_ACTIVAS_BOT = []

exchange_config = {
    "enableRateLimit": True,
    "options": {"defaultType": "swap"},
}

if API_KEY and SECRET_KEY and PASSPHRASE:
    exchange_config["apiKey"] = API_KEY
    exchange_config["secret"] = SECRET_KEY
    exchange_config["password"] = PASSPHRASE

exchange = ccxt.bitget(exchange_config)
exchange.set_sandbox_mode(True)  # Modo Demo activo para tu seguridad


def ejecutar_orden_demo(side, precio_actual):
    """Abre una posicion de mercado simulada en Bitget Demo en MODO AISLADO y x75 de Apalancamiento."""
    global POSICIONES_ACTIVAS_BOT
    if not API_KEY or not SECRET_KEY:
        print("Aviso: Falta configuración de API Keys en las Variables de Entorno.", flush=True)
        return
        
    try:
        # 1. Configurar obligatoriamente el Apalancamiento a x75 en la API
        try:
            exchange.set_leverage(leverage=75, symbol=SYMBOL, params={"marginMode": "isolated"})
            print("⚙️ [BITGET DEMO] Apalancamiento configurado con éxito a x75 (Aislado).", flush=True)
        except Exception as le:
            print(f"⚠️ Nota de apalancamiento (puede estar ya configurado): {le}", flush=True)

        # 2. Configurar la dirección del trade
        if side == "COMPRA":
            ccxt_side = "buy"
            hold_side = "long"   
        else:
            ccxt_side = "sell"
            hold_side = "short"  
            
        print(f"🛒 [BITGET DEMO] Enviando orden de mercado {ccxt_side.upper()} (holdSide: {hold_side})...", flush=True)
        
        # 3. Lanzar la orden especificando Modo Aislado y el holdSide requerido
        orden = exchange.create_market_order(
            symbol=SYMBOL,
            side=ccxt_side,
            amount=CANTIDAD_BTC,
            params={
                "holdSide": hold_side,    
                "marginMode": "isolated"   # <--- Forzado a Modo Aislado por tus instrucciones
            }
        )
        
        POSICIONES_ACTIVAS_BOT.append({
            "direccion": side,        
            "precio_entrada": precio_actual,
            "cantidad": CANTIDAD_BTC,
            "hold_side": hold_side    
        })
        
        print(f"✅ [BITGET DEMO] Orden ejecutada con éxito ID: {orden.get('id', 'N/A')}", flush=True)
        
    except Exception as e:
        print(f"❌ Error al colocar orden en Bitget Demo: {e}", flush=True)


def monitorear_y_cerrar_por_ganancia(precio_actual):
    """Revisa las posiciones activas del bot y las liquida en modo aislado si alcanzaron el objetivo."""
    global POSICIONES_ACTIVAS_BOT
    if not POSICIONES_ACTIVAS_BOT:
        return

    for pos in POSICIONES_ACTIVAS_BOT[:]:
        entrada = pos["precio_entrada"]
        cantidad = pos["cantidad"]
        
        if pos["direccion"] == "COMPRA":
            pnl_usd = (precio_actual - entrada) * cantidad
        else: 
            pnl_usd = (entrada - precio_actual) * cantidad
            
        print(f"📊 [RASTREADOR] P&L actual de la posición {pos['direccion']}: {pnl_usd:+.2f} USD", flush=True)

        if pnl_usd >= OBJETIVO_GANANCIA_USD:
            print(f"🎯 [TARGET ALCANZADO] Beneficio de +{pnl_usd:.2f} USD detectado. Cerrando trade...", flush=True)
            try:
                lado_cierre = "sell" if pos["direccion"] == "COMPRA" else "buy"
                hold_side_cierre = "long" if pos["direccion"] == "COMPRA" else "short"
                
                # Ejecutar la orden de reducción en modo aislado
                orden_cierre = exchange.create_market_order(
                    symbol=SYMBOL,
                    side=lado_cierre,
                    amount=cantidad,
                    params={
                        "reduceOnly": True,
                        "holdSide": hold_side_cierre,
                        "marginMode": "isolated"  # <--- Forzado a Modo Aislado también en el cierre
                    }
                )
                
                msg_cierre = (
                    f"🎯 *SHARK TAKE PROFIT AUTOMÁTICO*\n"
                    f"───────────────────────\n"
                    f"✅ Posición {pos['direccion']} (Aislado x75) cerrada en Bitget Demo.\n"
                    f"💰 Ganancia Realizada: *+{pnl_usd:.2f} USD*\n"
                    f"📈 Precio Entrada: `{entrada:,.2f}`\n"
                    f"📉 Precio Salida: `{precio_actual:,.2f}`"
                )
                enviar_telegram_directo(msg_cierre)
                
                POSICIONES_ACTIVAS_BOT.remove(pos)
                print(f"🔒 [CERRADO] Posición liquidada con éxito ID: {orden_cierre.get('id', 'N/A')}", flush=True)
                
            except Exception as error:
                print(f"❌ Error crítico ejecutando el cierre automático en Bitget: {error}", flush=True)


def enviar_telegram_directo(message):
    if not TELEGRAM_TOKEN or not TELEGRAM_CHAT_ID: return False
    url = f"https://telegram.org{TELEGRAM_TOKEN}/sendMessage"
    try:
        requests.post(url, json={"chat_id": TELEGRAM_CHAT_ID, "text": message, "parse_mode": "Markdown"}, timeout=10)
        return True
    except Exception: return False


def descargar_velas():
    candles = exchange.fetch_ohlcv(SYMBOL, TIMEFRAME, limit=CANDLE_LIMIT)
    if len(candles) < 30: raise RuntimeError("Bitget devolvio muy pocas velas")
    frame = pd.DataFrame(candles, columns=["timestamp", "open", "high", "low", "close", "volume"])
    for column in ["open", "high", "low", "close", "volume"]:
        frame[column] = pd.to_numeric(frame[column], errors="coerce")
    return frame.dropna().reset_index(drop=True)


def calcular_zonas(frame):
    zones = []
    ranges = (frame["high"] - frame["low"]).rolling(14).mean().shift(1)
    last_index = len(frame) - 2
    for index in range(2, last_index - 1):
        base = frame.iloc[index]
        impulse = frame.iloc[index + 1]
        average_range = ranges.iloc[index]
        if pd.isna(average_range) or average_range <= 0: continue

        impulse_range = impulse["high"] - impulse["low"]
        bullish_impulse = (base["close"] < base["open"] and impulse["close"] > impulse["open"] and impulse["close"] > base["high"] and impulse_range >= average_range * 1.1)
        bearish_impulse = (base["close"] > base["open"] and impulse["close"] < impulse["open"] and impulse["close"] < base["low"] and impulse_range >= average_range * 1.1)

        if bullish_impulse:
            zones.append({"side": "COMPRA", "color": "AZUL", "type": "Order Block", "low": float(base["low"]), "high": float(base["high"]), "created_at": int(base["timestamp"])})
        elif bearish_impulse:
            zones.append({"side": "VENTA", "color": "ROSA", "type": "Order Block", "low": float(base["low"]), "high": float(base["high"]), "created_at": int(base["timestamp"])})

    for index in range(2, last_index):
        older = frame.iloc[index - 2]
        current = frame.iloc[index]
        if current["low"] > older["high"]:
            zones.append({"side": "COMPRA", "color": "VERDE", "type": "Fair Value Gap", "low": float(older["high"]), "high": float(current["low"]), "created_at": int(current["timestamp"])})
        elif current["high"] < older["low"]:
            zones.append({"side": "VENTA", "color": "ROJO", "type": "Fair Value Gap", "low": float(current["high"]), "high": float(older["low"]), "created_at": int(current["timestamp"])})

    swing_frame = frame.iloc[max(0, last_index - 49):last_index]
    range_high = float(swing_frame["high"].max())
    range_low = float(swing_frame["low"].min())
    zones.extend([
        {"side": "VENTA", "color": "ROSA", "type": "Premium", "low": range_high * 0.95 + range_low * 0.05, "high": range_high, "created_at": int(frame.iloc[last_index]["timestamp"])},
        {"side": "COMPRA", "color": "AZUL", "type": "Discount", "low": range_low, "high": range_low * 0.95 + range_high * 0.05, "created_at": int(frame.iloc[last_index]["timestamp"])},
    ])
    return zones[-MAX_ZONES:]


def toca_zona(candle, zone):
    return float(candle["high"]) >= zone["low"] and float(candle["low"]) <= zone["high"]


def sonar_senal(side):
    if winsound is None: return
    tonos = [(1200, 350), (1600, 350)] if side == "COMPRA" else [(700, 450), (500, 450)]
    try:
        for f, d in tonos: winsound.Beep(f, d)
    except: pass


def enviar_telegram(side, color, zone_type, price, zone_low, zone_high):
    if not TELEGRAM_TOKEN or not TELEGRAM_CHAT_ID: return False
    direction = "🟢 COMPRA (LONG)" if side == "COMPRA" else "🔴 VENTA (SHORT)"
    
    if zone_type == "Order Block":
        significado = "Suelo fuerte donde las grandes instituciones acumularon compras." if side == "COMPRA" else "Techo fuerte donde las grandes instituciones acumularon ventas."
        accion = "Espera a que el precio de un REBOTE AL ALZA." if side == "COMPRA" else "Espera a que el precio de un REBOTE A LA BAJA."
        nota_seguridad = f"Si cae por debajo de {zone_low:,.2f}, el suelo se invalida." if side == "COMPRA" else f"Si sube por encima de {zone_high:,.2f}, el techo se invalida."
    elif zone_type == "Fair Value Gap":
        significado = "Hueco de ineficiencia dejado por algoritmos."


        # (Viene del bloque IF / ELIF superior de la función enviar_telegram)
        accion = "Zona de soporte temporal." if side == "COMPRA" else "Zona de resistencia temporal."
        nota_seguridad = f"Invalidación si cruza {zone_low:,.2f}" if side == "COMPRA" else f"Invalidación si cruza {zone_high:,.2f}"
    else:
        significado = "El precio entró en la zona más BARATA." if side == "COMPRA" else "El precio entró en la zona más CARA."
        accion = "Buscar entradas al alza." if side == "COMPRA" else "Buscar entradas a la baja."
        nota_seguridad = "Vigila la fuerza de la tendencia."

    message = (
        f"🦈 *SHARK SMART MONEY ALERT*\n"
        f"───────────────────────\n"
        f"🎬 *ACCIÓN:* **{direction}**\n"
        f"📊 *Precio:* `{price:,.2f}`\n"
        f"📌 *Zona:* `{zone_type} ({color})`\n"
        f"📐 *Rango:* `{zone_low:,.2f} - {zone_high:,.2f}`\n"
        f"───────────────────────\n"
        f"📖 *¿Qué significa?*\n_{significado}_\n\n"
        f"💡 *Estrategia:* \n*{accion}*\n\n"
        f"⚠️ *Invalidación:* `{nota_seguridad}`"
    )

    url = f"https://telegram.org{TELEGRAM_TOKEN}/sendMessage"
    try:
        response = requests.post(url, json={"chat_id": TELEGRAM_CHAT_ID, "text": message, "parse_mode": "Markdown"}, timeout=10)
        return response.ok
    except: 
        return False


def revisar_zonas(frame, zones, notified):
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
            
            enviar_telegram(zone["side"], zone["color"], zone["type"], price, zone["low"], zone["high"])
            ejecutar_orden_demo(zone["side"], price)
            print(f"[{datetime.now(timezone.utc).isoformat(timespec='seconds')}] SEÑAL EMITIDA: {zone['side']} | BTC {price:,.2f}", flush=True)


def bucle_infinito_bot():
    notified = set()
    last_candle_timestamp = None
    zones = []
    print(f"Monitor Smart Money activo: {SYMBOL} | {TIMEFRAME} | cada {POLL_SECONDS}s", flush=True)
    
    while True:
        try:
            frame = descargar_velas()
            precio_actual = float(frame.iloc[-1]["close"])
            closed_timestamp = int(frame.iloc[-2]["timestamp"])
            
            if closed_timestamp != last_candle_timestamp:
                zones = calcular_zonas(frame)
                last_candle_timestamp = closed_timestamp
            
            revisar_zonas(frame, zones, notified)
            
            # 🚨 LLAMADA CRUCIAL AL RASTREADOR: Revisa ganancias cada 15 segundos en vivo
            monitorear_y_cerrar_por_ganancia(precio_actual)
            
            time.sleep(POLL_SECONDS)
        except Exception as e:
            print(f"⚠️ Error en ejecución: {e}", flush=True)
            time.sleep(10)


if __name__ == "__main__":
    threading.Thread(target=bucle_infinito_bot, daemon=True).start()
    port = int(os.environ.get("PORT", 10000))
    app.run(host="0.0.0.0", port=port)


