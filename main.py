"""Monitor autonomo de alta frecuencia (1m) Smart Money + Rupturas + Geometria para BTCUSDT en Bitget Demo."""

import os
import time
import threading                     
from datetime import datetime, timezone
from flask import Flask              

import ccxt
import pandas as pd
import numpy as np
import requests

app = Flask(__name__)

@app.route('/')
def home():
    return "Club MarketSharks - Radar de Alta Frecuencia 1m Activo", 200

# === CREDENCIALES DESDE ENVIRONMENT VARIABLES ===
SYMBOL = os.getenv("BITGET_SYMBOL", "BTC/USDT:USDT")
TIMEFRAME = "1m"  # <--- FORZADO A 1 MINUTO PARA SEÑALES ULTRA RÁPIDAS
POLL_SECONDS = 15  
CANDLE_LIMIT = 150
MAX_ZONES = 50
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN", "").strip()
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "").strip()

API_KEY = os.getenv("BITGET_API_KEY", "").strip()
SECRET_KEY = os.getenv("BITGET_API_SECRET", "").strip()  
PASSPHRASE = os.getenv("BITGET_PASSWORD", "").strip()

# =====================================================================
# ⚙️ CONFIGURACIÓN DE PARÁMETROS GEOMÉTRICOS Y TRADES (ESTILO ORO 1M)
# =====================================================================
OBJETIVO_GANANCIA_USD = 5.0   # Take Profit corto para scalping rápido ($5 USD)
CANTIDAD_BTC = 0.002          # Tamaño de orden un poco mayor para ver el P&L rápido
PERIODO_CANAL = 30           # 30 velas de 1m para el canal de regresión (Última media hora)
MULTIPLICADOR_CANAL = 1.8     # Ajuste estrecho para capturar extremos
InpHolguraPips = 8            # Holgura de 8 pips convertida a dólares para BTC ($8 USD)
InpProteccionSLPips = 20      # Protección por fuera de estructura ($20 USD)

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
exchange.set_sandbox_mode(True)  # MODO DEMO SEGURO ACTIVO


def calcular_lineas_geometricas_1m(df):
    """Calcula matemáticamente el canal de regresión y los pivotes horizontales idénticos a tus trazos visuales."""
    # 1. Regresión lineal para canal dinámico
    bloque = df['close'].iloc[-PERIODO_CANAL:].values
    x = np.arange(PERIODO_CANAL)
    coef = np.polyfit(x, bloque, 1)
    
    centro_array = coef * (PERIODO_CANAL - 1) + coef
    centro = float(np.atleast_1d(centro_array))
    
    std_dev = float(df['close'].iloc[-PERIODO_CANAL:].std())
    techo_canal = centro + (std_dev * MULTIPLICADOR_CANAL)
    piso_canal  = centro - (std_dev * MULTIPLICADOR_CANAL)
    
    # 2. Soportes y Resistencias horizontales mayores (Últimas 25 velas = 25 minutos)
    resistencia_maxima = float(df['high'].iloc[-25:-1].max())
    soporte_minimo = float(df['low'].iloc[-25:-1].min())
    
    return techo_canal, piso_canal, resistencia_maxima, soporte_minimo


def ejecutar_orden_demo(side, precio_actual):
    """Abre una posición en Bitget Demo en MODO AISLADO x75 con parámetros Mix V2 válidos."""
    global POSICIONES_ACTIVAS_BOT
    if not API_KEY or not SECRET_KEY:
        print("Aviso: Falta configuración de API Keys en las Variables de Entorno.", flush=True)
        return
        
    try:
        # Configurar apalancamiento x75 enviando los parámetros complementarios para cuentas Hedge
        try:
            exchange.set_leverage(
                leverage=75, 
                symbol=SYMBOL, 
                params={
                    "marginMode": "isolated",
                    "productType": "usd-perpetual",
                    "holdSide": "long" if side == "COMPRA" else "short"
                }
            )
        except:
            pass

        if side == "COMPRA":
            ccxt_side = "buy"
            hold_side = "long"   
        else:
            ccxt_side = "sell"
            hold_side = "short"  
            
        print(f"🛒 [BITGET DEMO 1M] Enviando orden {ccxt_side.upper()} (holdSide: {hold_side})...", flush=True)
        
        orden = exchange.create_market_order(
            symbol=SYMBOL,
            side=ccxt_side,
            amount=CANTIDAD_BTC,
            params={
                "holdSide": hold_side,    
                "marginMode": "isolated",
                "productType": "usd-perpetual"
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
        print(f"📊 [RASTREADOR M1] P&L de posición {pos['direccion']}: {pnl_usd:+.2f} USD", flush=True)

        if pnl_usd >= OBJETIVO_GANANCIA_USD:
            print(f"🎯 [TARGET M1 ALCANZADO] Cerrando trade con ganancias en la nube...", flush=True)
            try:
                lado_cierre = "sell" if pos["direccion"] == "COMPRA" else "buy"
                
                orden_cierre = exchange.create_market_order(
                    symbol=SYMBOL,
                    side=lado_cierre,
                    amount=cantidad,
                    params={
                        "reduceOnly": True,
                        "holdSide": pos["hold_side"], 
                        "marginMode": "isolated",
                        "productType": "usd-perpetual"
                    }
                )
                
                msg_cierre = (
                    f"🎯 *SHARK SCALPER 1M: TAKE PROFIT*\n"
                    f"───────────────────────\n"
                    f"✅ Posición {pos['direccion']} (Aislado x75) liquidada.\n"
                    f"💰 Ganancia Realizada: *+{pnl_usd:.2f} USD*\n"
                    f"📈 Entrada: `{entrada:,.2f}` | 📉 Salida: `{precio_actual:,.2f}`"
                )
                enviar_telegram_directo(msg_cierre)
                POSICIONES_ACTIVAS_BOT.remove(pos)
                print(f"🔒 Posición liquidada con éxito.", flush=True)
            except Exception as error:
                print(f"❌ Error ejecutando el cierre en Bitget V2: {error}", flush=True)


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


def calcular_zonas_smc(frame):
    zones = []
    ranges = (frame["high"] - frame["low"]).rolling(14).mean().shift(1)
    last_index = len(frame) - 2
    for index in range(2, last_index - 1):
        base = frame.iloc[index]
        impulse = frame.iloc[index + 1]
        average_range = ranges.iloc[index]
        if pd.isna(average_range) or average_range <= 0: continue

        impulse_range = impulse["high"] - impulse["low"]
        bullish_impulse = (base["close"] < base["open"] and impulse["close"] > impulse["open"] and impulse["close"] > base["high"] and impulse_range >= average_range * 1.2)
        bearish_impulse = (base["close"] > base["open"] and impulse["close"] < impulse["open"] and impulse["close"] < base["low"] and impulse_range >= average_range * 1.2)

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

    return zones[-MAX_ZONES:]


def toca_zona(candle, zone):
    return float(candle["high"]) >= zone["low"] and float(candle["low"]) <= zone["high"]


def enviar_telegram_filtrado(side, modo_tipo, price, techo, piso, filtro_motivo):
    if not TELEGRAM_TOKEN or not TELEGRAM_CHAT_ID: return False
    direction = "🟢 COMPRA (LONG)" if side == "COMPRA" else "🔴 VENTA (SHORT)"
    
    message = (
        f"🦈 *SHARK SCALPER 1M DIRECTO (Nube)*\n"
        f"───────────────────────\n"
        f"🎬 *ACCIÓN DETECTADA:* **{direction}**\n"
        f"📊 *Precio Entrada:* `{price:,.2f}`\n"
        f"📌 *Modo Entrada:* `{modo_tipo}`\n"
        f"🛠️ *Confluencia:* `{filtro_motivo}`\n"
        f"📈 *Canal Geométrico 1m:* `[{piso:,.1f} - {techo:,.1f}]`\n"
        f"───────────────────────\n"
        f"💼 Orden enviada con éxito a Bitget Demo (Aislado x75)."
    )
    
    url = f"https://telegram.org{TELEGRAM_TOKEN}/sendMessage"
    try:
        requests.post(url, json={"chat_id": TELEGRAM_CHAT_ID, "text": message, "parse_mode": "Markdown"}, timeout=10)
        return True
    except: 
        return False


def revisar_y_operar_1m(frame, zones, notified, techo, piso, res, sup):
    previous = frame.iloc[-2]
    current = frame.iloc[-1]
    current_timestamp = int(current["timestamp"])
    price = float(current["close"])

    # --- LÓGICA DE REBOTES EN EXTREMOS (SMART MONEY) ---
    for zone in zones:
        zone_id = (zone["side"], zone["type"], zone["created_at"])
        entered = toca_zona(current, zone) and not toca_zona(previous, zone)
        
        if entered and (zone_id, current_timestamp) not in notified:
            notified.add((zone_id, current_timestamp))
            
            validar_rebote = False
            motivo_geo = ""
            
            if zone["side"] == "COMPRA" and (price <= (piso + InpHolguraPips) or price <= (sup + InpHolguraPips)):
                validar_rebote = True
                motivo_geo = "Toque en Soporte Horizontal / Pared Baja Canal 1m"
            elif zone["side"] == "VENTA" and (price >= (techo - InpHolguraPips) or price >= (res - InpHolguraPips)):
                validar_rebote = True
                motivo_geo = "Toque en Resistencia Horizontal / Pared Alta Canal 1m"
                
            if validar_rebote and len(POSICIONES_ACTIVAS_BOT) == 0:
                enviar_telegram_filtrado(zone["side"], f"REBOTE {zone['type']}", price, techo, piso, motivo_geo)
                ejecutar_orden_demo(zone["side"], price)
                return

    # --- LÓGICA DE RUPTURAS EXPLOSIVAS DE EXTREMOS (BREAKOUT COMO TU CAPTURA) ---
    if len(POSICIONES_ACTIVAS_BOT) == 0:
        if price > (techo + InpHolguraPips) or price > (res + InpHolguraPips):
            enviar_telegram_filtrado("COMPRA", "RUPTURA DE CANAL (BREAKOUT)", price, techo, piso, "Escape alcista fuera del Rango Geométrico")
            ejecutar_orden_demo("COMPRA", price)
        elif price < (piso - InpHolguraPips) or price < (sup - InpHolguraPips):
            enviar_telegram_filtrado("VENTA", "RUPTURA DE CANAL (BREAKOUT)", price, techo, piso, "Escape bajista fuera del Rango Geométrico")
            ejecutar_orden_demo("VENTA", price)


def bucle_infinito_bot():
    notified = set()
    last_candle_timestamp = None
    zones = []
    
    while True:
        try:
            frame = descargar_velas()
            precio_actual = float(frame.iloc[-1]["close"])
            closed_timestamp = int(frame.iloc[-2]["timestamp"])
            
            # Dibujar y calcular líneas de control geométrico en cada iteración
            techo, piso, res, sup = calcular_lineas_geometricas_1m(frame)
            
            if closed_timestamp != last_candle_timestamp:
                zones = calcular_zonas_smc(frame)
                last_candle_timestamp = closed_timestamp
                print(f"📊 [1m] Líneas geométricas actualizadas | Techo: {techo:,.1f} | Piso: {piso:,.1f}", flush=True)
            
            revisar_y_operar_1m(frame, zones, notified, techo, piso, res, sup)
            monitorear_y_cerrar_por_ganancia(precio_actual)
            
            time.sleep(POLL_SECONDS)
        except Exception as e:
            print(f"⚠️ Error en ejecución 1m: {e}", flush=True)
            time.sleep(10)


if __name__ == "__main__":
    threading.Thread(target=bucle_infinito_bot, daemon=True).start()
    port = int(os.environ.get("PORT", 10000))
    app.run(host="0.0.0.0", port=port)
