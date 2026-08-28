"""Monitor autonomo de zonas Smart Money (15m) con filtros geometricos de canal, soportes y ejecucion en Bitget Demo."""

import os
import time
import threading                     
from datetime import datetime, timezone
from flask import Flask              

import ccxt
import pandas as pd
import numpy as np
import requests

try:
    import winsound
except ImportError:
    winsound = None

app = Flask(__name__)

@app.route('/')
def home():
    return "Club MarketSharks - Algoritmo Smart Money Pro con Filtro Geometrico Activo", 200

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
# ⚙️ CONFIGURACIÓN DE OBJETIVOS Y PARÁMETROS GEOMÉTRICOS (15m)
# =====================================================================
OBJETIVO_GANANCIA_USD = 10.0  
CANTIDAD_BTC = 0.001          
PERIODO_CANAL = 20           
MULTIPLICADOR_CANAL = 2.0     

# Memoria de operaciones activas
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
exchange.set_sandbox_mode(True)  


def calcular_lineas_geometricas_15m(df):
    """Calcula matematicamente el canal de regresion y los pivotes horizontales en 15m de forma segura."""
    # 1. Regresión lineal para canal dinámico
    bloque = df['close'].iloc[-PERIODO_CANAL:].values
    x = np.arange(PERIODO_CANAL)
    coef = np.polyfit(x, bloque, 1)
    
    # CORRECCIÓN CRUCIAL: Extraer estrictamente el valor numérico escalar puro
    centro_array = coef[0] * (PERIODO_CANAL - 1) + coef[1]
    centro = float(np.atleast_1d(centro_array)[0])
    
    std_dev = float(df['close'].iloc[-PERIODO_CANAL:].std())
    techo_canal = centro + (std_dev * MULTIPLICADOR_CANAL)
    piso_canal  = centro - (std_dev * MULTIPLICADOR_CANAL)
    
    # 2. Soportes y Resistencias mayores (últimas 30 velas)
    resistencia_maxima = float(df['high'].iloc[-30:-1].max())
    soporte_minimo = float(df['low'].iloc[-30:-1].min())
    
    return techo_canal, piso_canal, resistencia_maxima, soporte_minimo


def ejecutar_orden_demo(side, precio_actual):
    """Abre una posicion en Bitget Demo en MODO AISLADO y apalancamiento x75."""
    global POSICIONES_ACTIVAS_BOT
    if not API_KEY or not SECRET_KEY:
        print("Aviso: Falta configuración de API Keys en las Variables de Entorno.", flush=True)
        return
        
    try:
        try:
            exchange.set_leverage(leverage=75, symbol=SYMBOL, params={"marginMode": "isolated"})
        except Exception as le:
            print(f"⚠️ Apalancamiento ya establecido o nota: {le}", flush=True)

        if side == "COMPRA":
            ccxt_side = "buy"
            hold_side = "long"   
        else:
            ccxt_side = "sell"
            hold_side = "short"  
            
        print(f"🛒 [BITGET DEMO 15M] Enviando orden {ccxt_side.upper()} (Aislado x75)...", flush=True)
        
        orden = exchange.create_market_order(
            symbol=SYMBOL,
            side=ccxt_side,
            amount=CANTIDAD_BTC,
            params={
                "holdSide": hold_side,    
                "marginMode": "isolated"   
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
    global POSICIONES_ACTIVAS_BOT
    if not POSICIONES_ACTIVAS_BOT: return

    for pos in POSICIONES_ACTIVAS_BOT[:]:
        entrada = pos["precio_entrada"]
        cantidad = pos["cantidad"]
        
        pnl_usd = (precio_actual - entrada) * cantidad if pos["direccion"] == "COMPRA" else (entrada - precio_actual) * cantidad
        print(f"📊 [RASTREADOR 15M] P&L de posición {pos['direccion']}: {pnl_usd:+.2f} USD", flush=True)

        if pnl_usd >= OBJETIVO_GANANCIA_USD:
            print(f"🎯 [TARGET 15M ALCANZADO] Cerrando trade con ganancias...", flush=True)
            try:
                lado_cierre = "sell" if pos["direccion"] == "COMPRA" else "buy"
                hold_side_cierre = pos["hold_side"]
                
                orden_cierre = exchange.create_market_order(
                    symbol=SYMBOL,
                    side=lado_cierre,
                    amount=cantidad,
                    params={
                        "reduceOnly": True,
                        "holdSide": hold_side_cierre,
                        "marginMode": "isolated"  
                    }
                )
                
                msg_cierre = (
                    f"🎯 *SHARK TAKE PROFIT AUTOMÁTICO (15m)*\n"
                    f"───────────────────────\n"
                    f"✅ Posición {pos['direccion']} (Aislado x75) liquidada.\n"
                    f"💰 Ganancia Realizada: *+{pnl_usd:.2f} USD*\n"
                    f"📈 Entrada: `{entrada:,.2f}` | 📉 Salida: `{precio_actual:,.2f}`"
                )
                enviar_telegram_directo(msg_cierre)
                POSICIONES_ACTIVAS_BOT.remove(pos)
                print(f"🔒 Posición liquidada con éxito.", flush=True)
            except Exception as error:
                print(f"❌ Error ejecutando el cierre en Bitget: {error}", flush=True)


def enviar_telegram_directo(message):
    if not TELEGRAM_TOKEN or not TELEGRAM_CHAT_ID: return False
    url = f"https://telegram.org{TELEGRAM_TOKEN}/sendMessage"
    try:
        requests.post(url, json={"chat_id": TELEGRAM_CHAT_ID, "text": message, "parse_mode": "Markdown"}, timeout=10)
        return True
    except: return False


def descargar_velas():
    candles = exchange.fetch_ohlcv(SYMBOL, TIMEFRAME, limit=CANDLE_LIMIT)
    if len(candles) < 30: raise RuntimeError("Bitget devolvio pocas velas")
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


def enviar_telegram_filtrado(side, color, zone_type, price, zone_low, zone_high, filtro_motivo, techo, piso):
    if not TELEGRAM_TOKEN or not TELEGRAM_CHAT_ID: return False
    direction = "🟢 COMPRA (LONG)" if side == "COMPRA" else "🔴 VENTA (SHORT)"
    
    message = (
        f"🦈 *SHARK PRO GEOMETRIC ALERT (15m)*\n"
        f"───────────────────────\n"
        f"🎬 *ACCIÓN EN DIRECTO:* **{direction}**\n"
        f"📊 *Precio:* `{price:,.2f}`\n"
        f"📌 *Filtro Estructural:* `{filtro_motivo}`\n"
        f"📐 *Zona Mitigada:* `{zone_type} ({color})`\n"
        f"📐 *Rango Zona:* `{zone_low:,.2f} - {zone_high:,.2f}`\n"
        f"📈 *Bordes Canal 15m:* `[{piso:,.1f} - {techo:,.1f}]`\n"
        f"───────────────────────\n"
        f"💡 *Estrategia:* Confirmación de confluencia geométrica e institucional de alta probabilidad. Posición abierta en Bitget Demo (Aislado x75)."
    )
    
    url = f"https://telegram.org{TELEGRAM_TOKEN}/sendMessage"
    try:
        response = requests.post(url, json={"chat_id": TELEGRAM_CHAT_ID, "text": message, "parse_mode": "Markdown"}, timeout=10)
        return response.ok
    except: 
        return False


def revisar_zonas(frame, zones, notified, techo, piso, res, sup):
    previous = frame.iloc[-2]
    current = frame.iloc[-1]
    current_timestamp = int(current["timestamp"])

    for zone in zones:
        zone_id = (zone["side"], zone["type"], zone["created_at"])
        entered = toca_zona(current, zone) and not toca_zona(previous, zone)
        
        if entered and (zone_id, current_timestamp) not in notified:
            notified.add((zone_id, current_timestamp))
            price = float(current["close"])
            
            validar_operacion = False
            motivo = ""
            
            if zone["side"] == "COMPRA":
                if price <= (piso + 35.0) or price <= (sup + 35.0):
                    validar_operacion = True
                    motivo = "CONFLUENCIA EN SOPORTE / PISO DEL CANAL MACRO"
            else: 
                if price >= (techo - 35.0) or price >= (res - 35.0):
                    validar_operacion = True
                    motivo = "CONFLUENCIA EN RESISTENCIA / TECHO DEL CANAL MACRO"
                    
            if validar_operacion:
                enviar_telegram_filtrado(zone["side"], zone["color"], zone["type"], price, zone["low"], zone["high"], motivo, techo, piso)
                ejecutar_orden_demo(zone["side"], price)
                print(f"💎 [SEÑAL VALIDADA 15M] {zone['side']} por {motivo}", flush=True)
            else:
                print(f"🚫 [SEÑAL FILTRADA] {zone['side']} ignorada por estar en el centro del canal (RUIDO).", flush=True)


def bucle_infinito_bot():
    notified = set()
    last_candle_timestamp = None
    zones = []
    
    while True:
        try:
            frame = descargar_velas()
            precio_actual = float(frame.iloc[-1]["close"])
            closed_timestamp = int(frame.iloc[-2]["timestamp"])
            
            techo, piso, res, sup = calcular_lineas_geometricas_15m(frame)
            
            if closed_timestamp != last_candle_timestamp:
                zones = calcular_zonas(frame)
                last_candle_timestamp = closed_timestamp
                print(f"📊 [15m] Canal recalculado | Techo: {techo:,.1f} | Piso: {piso:,.1f}", flush=True)
            
            revisar_zonas(frame, zones, notified, techo, piso, res, sup)
            monitorear_y_cerrar_por_ganancia(precio_actual)
            
            time.sleep(POLL_SECONDS)
        except Exception as e:
            print(f"⚠️ Error en ejecución: {e}", flush=True)
            time.sleep(10)


if __name__ == "__main__":
    threading.Thread(target=bucle_infinito_bot, daemon=True).start()
    port = int(os.environ.get("PORT", 10000))
    app.run(host="0.0.0.0", port=port)
