import os
import threading
import time
from flask import Flask
import requests

app = Flask(__name__)

@app.route('/')
def home():
    return "Club MarketSharks - Algoritmo Dual Completo (BUY/SELL) Activo", 200

# === CREDENCIALES DESDE ENVIRONMENT VARIABLES ===
TOKEN_TELEGRAM = os.getenv("TELEGRAM_TOKEN")
CHAT_ID_CANAL = os.getenv("TELEGRAM_CHAT_ID")

def enviar_senal_telegram(mensaje):
    if not TOKEN_TELEGRAM or not CHAT_ID_CANAL:
        return
    url = f"https://telegram.org{TOKEN_TELEGRAM}/sendMessage"
    payload = {"chat_id": CHAT_ID_CANAL, "text": mensaje, "parse_mode": "Markdown"}
    try:
        requests.post(url, json=payload, timeout=10)
    except:
        pass

def obtener_datos_binance(symbol, interval):
    url = "https://binance.com"
    params = {"symbol": symbol, "interval": interval, "limit": 210}
    try:
        response = requests.get(url, params=params, timeout=10)
        if response.status_code == 200:
            return response.json()
    except:
        return None

def calcular_ema_tradingview(precios_cierre, periodo=200):
    if len(precios_cierre) < periodo:
        return None
    sma_inicial = sum(precios_cierre[:periodo]) / periodo
    alpha = 2 / (periodo + 1)
    ema = sma_inicial
    for precio in precios_cierre[periodo:]:
        ema = (precio * alpha) + (ema * (1 - alpha))
    return ema

# === BUCLE DE TRADING EN TIEMPO REAL MULTI-ACTIVO ===
def motor_de_trading():
    print("🚀 Iniciando motor analítico dual completo (BTC 15m y SPCX 1h)...")
    time.sleep(5)
    
    alerta_inicio = (
        "🦈 *CLUB MARKETSHARKS - MOTOR ALGORÍTMICO ACTUALIZADO*\n\n"
        "🤖 ¡Sincronización total completada en ambas direcciones!\n"
        "📊 *Estrategia espejo activa 24/7 (BUY & SELL):*\n"
        "1️⃣ **Bitcoin (BTCUSDT - 15m):** Operaciones rápidas al alza y a la baja.\n"
        "2️⃣ **SpaceX (SPCXUSDT - 1h):** Operaciones de tendencia macro al alza y a la baja."
    )
    enviar_senal_telegram(alerta_inicio)
    
    while True:
        # =====================================================================
        # 1️⃣ MONITOR DE BITCOIN (BTCUSDT - 15m)
        # =====================================================================
        try:
            datos_btc = obtener_datos_binance("BTCUSDT", "15m")
            if datos_btc:
                aperturas = [float(v[1]) for v in datos_btc]
                cierres   = [float(v[4]) for v in datos_btc]
                precio_actual = cierres[-1]
                ema_200 = calcular_ema_tradingview(cierres, 200)
                
                if ema_200:
                    idx_ob = -6
                    absmove = (abs(cierres[idx_ob] - precio_actual) / cierres[idx_ob]) * 100
                    relmove = absmove >= 0.5
                    
                    # 🟢 BTC COMPRA (Precio > EMA 200 + Vela Origen Roja + 5 Velas Verdes)
                    if precio_actual > ema_200 and (cierres[idx_ob] < aperturas[idx_ob]) and sum(1 for i in range(-5, 0) if cierres[i] > aperturas[i]) == 5 and relmove:
                        stop_loss = float(datos_btc[idx_ob][3]) # Low de la vela OB
                        if stop_loss >= precio_actual or (precio_actual - stop_loss) > 600:
                            stop_loss = precio_actual - 200.00
                        take_profit = precio_actual + ((precio_actual - stop_loss) * 2)
                        
                        mensaje = f"🦈 *CLUB MARKETSHARKS ALERTA EN VIVO*\n\n📊 *Par:* BTCUSDT (15m)\n🎯 *Estrategia:* Order Block + EMA 200\n🟢 *Dirección:* COMPRA (Bullish OB)\n\n💵 *Precio Entrada:* $ {precio_actual:,.2f} USD\n🛡️ *Stop Loss (SL):* $ {stop_loss:,.2f} USD\n💰 *Take Profit (TP):* $ {take_profit:,.2f} USD\n⚙️ *Apalancamiento:* 50x (Recomendado)\n\n📈 *Filtro Trend:* Por encima de EMA 200 ($ {ema_200:,.2f})"
                        enviar_senal_telegram(mensaje)
                        time.sleep(10)
                    
                    # 🔴 BTC VENTA (Precio < EMA 200 + Vela Origen Verde + 5 Velas Rojas)
                    elif precio_actual < ema_200 and (cierres[idx_ob] > aperturas[idx_ob]) and sum(1 for i in range(-5, 0) if cierres[i] < aperturas[i]) == 5 and relmove:
                        stop_loss = float(datos_btc[idx_ob][2]) # High de la vela OB
                        if stop_loss <= precio_actual or (stop_loss - precio_actual) > 600:
                            stop_loss = precio_actual + 200.00
                        take_profit = precio_actual - ((stop_loss - precio_actual) * 2)
                        
                        mensaje = f"🦈 *CLUB MARKETSHARKS ALERTA EN VIVO*\n\n📊 *Par:* BTCUSDT (15m)\n🎯 *Estrategia:* Order Block + EMA 200\n🔴 *Dirección:* VENTA EN CORTO (Bearish OB)\n\n💵 *Precio Entrada:* $ {precio_actual:,.2f} USD\n🛡️ *Stop Loss (SL):* $ {stop_loss:,.2f} USD\n💰 *Take Profit (TP):* $ {take_profit:,.2f} USD\n⚙️ *Apalancamiento:* 50x (Recomendado)\n\n📉 *Filtro Trend:* Por debajo de EMA 200 ($ {ema_200:,.2f})"
                        enviar_senal_telegram(mensaje)
                        time.sleep(10)
        except Exception as e:
            print(f"⚠️ Error en bloque BTC: {e}")

        # =====================================================================
        # 2️⃣ MONITOR DE SPACEX (SPCXUSDT - 1h)
        # =====================================================================
        try:
            datos_spcx = obtener_datos_binance("SPCXUSDT", "1h")
            if datos_spcx:
                aperturas = [float(v[1]) for v in datos_spcx]
                cierres   = [float(v[4]) for v in datos_spcx]
                precio_actual = cierres[-1]
                ema_200 = calcular_ema_tradingview(cierres, 200)
                
                if ema_200:
                    idx_ob = -6
                    absmove = (abs(cierres[idx_ob] - precio_actual) / cierres[idx_ob]) * 100
                    relmove = absmove >= 0.5
                    
                    # 🟢 SPCX COMPRA
                    if precio_actual > ema_200 and (cierres[idx_ob] < aperturas[idx_ob]) and sum(1 for i in range(-5, 0) if cierres[i] > aperturas[i]) == 5 and relmove:
                        stop_loss = float(datos_spcx[idx_ob][3])
                        if stop_loss >= precio_actual or (precio_actual - stop_loss) > (precio_actual * 0.05):
                            stop_loss = precio_actual * 0.99
                        take_profit = precio_actual + ((precio_actual - stop_loss) * 2)
                        
                        mensaje = f"🦈 *CLUB MARKETSHARKS ALERTA EN VIVO*\n\n📊 *Par:* SPCXUSDT (1h) - SpaceX\n🎯 *Estrategia:* Order Block + EMA 200\n🟢 *Dirección:* COMPRA (Bullish OB)\n\n💵 *Precio Entrada:* $ {precio_actual:,.2f} USD\n🛡️ *Stop Loss (SL):* $ {stop_loss:,.2f} USD\n💰 *Take Profit (TP):* $ {take_profit:,.2f} USD\n⚙️ *Apalancamiento:* 50x (Recomendado)\n\n📈 *Filtro Trend:* Por encima de EMA 200 ($ {ema_200:,.2f})"
                        enviar_senal_telegram(mensaje)
                        time.sleep(10)
                    
                    # 🔴 SPCX VENTA
                    elif precio_actual < ema_200 and (cierres[idx_ob] > aperturas[idx_ob]) and sum(1 for i in range(-5, 0) if cierres[i] < aperturas[i]) == 5 and relmove:
                        stop_loss = float(datos_spcx[idx_ob][2])
                        if stop_loss <= precio_actual or (stop_loss - precio_actual) > (precio_actual * 0.05):
                            stop_loss = precio_actual * 1.01
                        take_profit = precio_actual - ((stop_loss - precio_actual) * 2)
                        
                        mensaje = f"🦈 *CLUB MARKETSHARKS ALERTA EN VIVO*\n\n📊 *Par:* SPCXUSDT (1h) - SpaceX\n🎯 *Estrategia:* Order Block + EMA 200\n🔴 *Dirección:* VENTA EN CORTO (Bearish OB)\n\n💵 *Precio Entrada:* $ {precio_actual:,.2f} USD\n🛡️ *Stop Loss (SL):* $ {stop_loss:,.2f} USD\n💰 *Take Profit (TP):* $ {take_profit:,.2f} USD\n⚙️ *Apalancamiento:* 50x (Recomendado)\n\n📉 *Filtro Trend:* Por debajo de EMA 200 ($ {ema_200:,.2f})"
                        enviar_senal_telegram(mensaje)
                        time.sleep(10)
        except Exception as e:
            print(f"⚠️ Error en bloque SPCX: {e}")

        # === CONTROL DEL BUCLE GENERAL ===
        print("🔍 Escaneo dual completado. Analizando mercados...")
        time.sleep(60)

if __name__ == '__main__':
    hilo_trading = threading.Thread(target=motor_de_trading)
    hilo_trading.daemon = True
    hilo_trading.start()
    app.run(host='0.0.0.0', port=int(os.getenv("PORT", 10000)))
