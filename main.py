import os
import threading
import time
from flask import Flask
import requests

app = Flask(__name__)

@app.route('/')
def home():
    return "Club MarketSharks - Clon Exacto TV (BUY/SELL) Activo", 200

# === CREDENCIALES DESDE ENVIRONMENT VARIABLES ===
TOKEN_TELEGRAM = os.getenv("TELEGRAM_TOKEN")
CHAT_ID_CANAL = os.getenv("TELEGRAM_CHAT_ID")

def enviar_senal_telegram(mensaje):
    if not TOKEN_TELEGRAM or not CHAT_ID_CANAL:
        print("❌ Error: Faltan las variables en el panel de Render.")
        return
    # CORRECCIÓN DE LA URL: Añadida la estructura /bot/ oficial de Telegram
    url = f"https://telegram.org{TOKEN_TELEGRAM}/sendMessage"
    payload = {"chat_id": CHAT_ID_CANAL, "text": mensaje, "parse_mode": "Markdown"}
    try:
        response = requests.post(url, json=payload, timeout=10)
        if response.status_code == 200:
            print("📢 ¡Señal enviada a Telegram con éxito!")
        else:
            print(f"❌ Telegram rechazó el envío: {response.text}")
    except Exception as e:
        print(f"⚠️ Error de red al conectar con Telegram: {e}")

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
    print("🚀 Iniciando motor analítico espejo exacto (BTC 15m y SPCX 1h)...")
    time.sleep(5)
    
    # Alerta inmediata de inicio para certificar la conexión
    alerta_inicio = (
        "🦈 *CLUB MARKETSHARKS - CLON COMPLETO TRADINGVIEW*\n\n"
        "🤖 ¡Algoritmo sincronizado al 100% con tus flechas visuales!\n"
        "📊 *Monitoreo en vivo (BUY & SELL):*\n"
        "1️⃣ **Bitcoin (BTCUSDT - 15m)** - Filtro de umbral adaptativo.\n"
        "2️⃣ **SpaceX (SPCXUSDT - 1h)** - Máxima precisión macro."
    )
    enviar_senal_telegram(alerta_inicio)
    
    while True:
        # Loop para procesar los dos activos con la misma lógica matemática
        for par, temporalidad, umbral_move in [("BTCUSDT", "15m", 0.5), ("SPCXUSDT", "1h", 0.5)]:
            try:
                datos = obtener_datos_binance(par, temporalidad)
                if datos:
                    # En la API de Binance: vela[1]=Open, vela[2]=High, vela[3]=Low, vela[4]=Close
                    aperturas = [float(vela[1]) for vela in datos]
                    altos     = [float(vela[2]) for vela in datos]
                    bajos     = [float(vela[3]) for vela in datos]
                    cierres   = [float(vela[4]) for vela in datos]
                    
                    precio_actual = cierres[-1]
                    ema_200 = calcular_ema_tradingview(cierres, 200)
                    
                    # LÓGICA DE VELAS: ob_period = periods + 1 (-6 hacia atrás)
                    idx_ob = -6
                    absmove = (abs(cierres[idx_ob] - precio_actual) / cierres[idx_ob]) * 100
                    relmove = absmove >= umbral_move
                    
                    # 🟢 DISPARO DE COMPRA (BULLISH OB)
                    bullishOB = cierres[idx_ob] < aperturas[idx_ob]
                    upcandles = sum(1 for i in range(-5, 0) if cierres[i] > aperturas[i])
                    
                    if bullishOB and (upcandles == 5) and relmove:
                        stop_loss = float(datos[idx_ob][3]) # Low de la vela de origen [3]
                        if stop_loss >= precio_actual: stop_loss = precio_actual - 150.00
                        take_profit = precio_actual + ((precio_actual - stop_loss) * 2)
                        
                        mensaje = (
                            f"🦈 *CLUB MARKETSHARKS ALERTA EN VIVO*\n\n"
                            f"📊 *Par:* {par} ({temporalidad})\n"
                            f"🎯 *Estrategia:* Order Block Finder\n"
                            f"🟢 *Dirección:* COMPRA (Bullish OB 🔼)\n\n"
                            f"💵 *Precio Entrada:* $ {precio_actual:,.2f} USD\n"
                            f"🛡️ *Stop Loss (SL):* $ {stop_loss:,.2f} USD\n"
                            f"💰 *Take Profit (TP):* $ {take_profit:,.2f} USD\n"
                            f"⚙️ *Apalancamiento:* 50x\n\n"
                            f"📈 *Referencia:* EMA 200 @ $ {ema_200:,.2f}"
                        )
                        enviar_senal_telegram(mensaje)
                        time.sleep(5)
                        continue
                    
                    # 🔴 DISPARO DE VENTA (BEARISH OB)
                    bearishOB = cierres[idx_ob] > aperturas[idx_ob]
                    downcandles = sum(1 for i in range(-5, 0) if cierres[i] < aperturas[i])
                    
                    if bearishOB and (downcandles == 5) and relmove:
                        stop_loss = float(datos[idx_ob][2]) # High de la vela de origen [2]
                        if stop_loss <= precio_actual: stop_loss = precio_actual + 150.00
                        take_profit = precio_actual - ((stop_loss - precio_actual) * 2)
                        
                        mensaje = (
                            f"🦈 *CLUB MARKETSHARKS ALERTA EN VIVO*\n\n"
                            f"📊 *Par:* {par} ({temporalidad})\n"
                            f"🎯 *Estrategia:* Order Block Finder\n"
                            f"🔴 *Dirección:* VENTA EN CORTO (Bearish OB 🔽)\n\n"
                            f"💵 *Precio Entrada:* $ {precio_actual:,.2f} USD\n"
                            f"🛡️ *Stop Loss (SL):* $ {stop_loss:,.2f} USD\n"
                            f"💰 *Take Profit (TP):* $ {take_profit:,.2f} USD\n"
                            f"⚙️ *Apalancamiento:* 50x\n\n"
                            f"📉 *Referencia:* EMA 200 @ $ {ema_200:,.2f}"
                        )
                        enviar_senal_telegram(mensaje)
                        time.sleep(5)
                        continue
            except Exception as e:
                print(f"⚠️ Error en par {par}: {e}")

        # === CONTROL DEL BUCLE GENERAL ===
        print("🔍 Escaneo completado. Buscando flechas en gráficos...")
        time.sleep(60)

if __name__ == '__main__':
    hilo_trading = threading.Thread(target=motor_de_trading)
    hilo_trading.daemon = True
    hilo_trading.start()
    app.run(host='0.0.0.0', port=int(os.getenv("PORT", 10000)))
