import os
import threading
import time
from flask import Flask
import requests

app = Flask(__name__)

@app.route('/')
def home():
    return "Club MarketSharks - Clon Matemático TradingView Activo", 200

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

def obtener_datos_binance():
    url = "https://binance.com"
    params = {"symbol": "BTCUSDT", "interval": "15m", "limit": 210}
    try:
        response = requests.get(url, params=params, timeout=10)
        if response.status_code == 200:
            return response.json()
    except:
        return None

def calcular_ema_tradingview(precios_cierre, periodo=200):
    """Calcula la EMA usando el método de suavizado exacto de TradingView"""
    if len(precios_cierre) < periodo:
        return None
    # TradingView inicializa la EMA con la media aritmética (SMA) de los primeros periodos
    sma_inicial = sum(precios_cierre[:periodo]) / periodo
    alpha = 2 / (periodo + 1)
    ema = sma_inicial
    for precio in precios_cierre[periodo:]:
        ema = (precio * alpha) + (ema * (1 - alpha))
    return ema

def motor_de_trading():
    print("🚀 Motor espejo TradingView iniciado...")
    time.sleep(5)
    
    while True:
        try:
            datos = obtener_datos_binance()
            if datos:
                # En Binance: index 1=Open, 2=High, 3=Low, 4=Close
                aperturas = [float(v[1]) for v in datos]
                altos     = [float(v[2]) for v in datos]
                bajos     = [float(v[3]) for v in datos]
                cierres   = [float(v[4]) for v in datos]
                
                precio_actual = cierres[-1]
                ema_200 = calcular_ema_tradingview(cierres, 200)
                
                if ema_200:
                    # Filtro original: Precio por encima de la EMA 200 Amarilla
                    por_encima_ema = precio_actual > ema_200
                    
                    # === LÓGICA CLONADA DE TU PINE SCRIPT ===
                    # ob_period = periods + 1 (5 + 1 = 6 velas atrás)
                    idx_ob = -6 
                    
                    # 1. Bullish Order Block Identification (Vela de origen bajista)
                    bullishOB = cierres[idx_ob] < aperturas[idx_ob]
                    
                    # 2. Las siguientes 5 velas deben ser ALCISTAS consecutivas
                    upcandles = 0
                    for i in range(-5, 0): # Revisa las últimas 5 velas cerradas
                        if cierres[i] > aperturas[i]:
                            upcandles += 1
                            
                    # 3. Movimiento mínimo de umbral (Percent move >= 0.5)
                    absmove = (abs(cierres[idx_ob] - precio_actual) / cierres[idx_ob]) * 100
                    relmove = absmove >= 0.5
                    
                    # GATILLO DE ENTRADA EFECTUADO
                    OB_bull_detectado = bullishOB and (upcandles == 5) and relmove and por_encima_ema
                    
                    if OB_bull_detectado:
                        mensaje_alert = (
                            f"🦈 *CLUB MARKETSHARKS ALERTA EN VIVO*\n\n"
                            f"📊 *Par:* BTCUSDT (15m)\n"
                            f"🎯 *Estrategia:* Order Block + EMA 200\n"
                            f"🟢 *Señal:* BULLISH OB Confirmado\n"
                            f"💵 *Precio Entrada:* $ {precio_actual:,.2f} USD\n"
                            f"📈 *Filtro Trend:* Por encima de EMA 200 ($ {ema_200:,.2f})"
                        )
                        enviar_senal_telegram(mensaje_alert)
                        time.sleep(900) # Evita duplicados durante la misma vela de 15m
                        continue

            print("🔍 Escaneo completado minuto a minuto. Analizando mercado...")
            time.sleep(60)
            
        except Exception as e:
            print(f"⚠️ Error: {e}")
            time.sleep(30)

if __name__ == '__main__':
    hilo_trading = threading.Thread(target=motor_de_trading)
    hilo_trading.daemon = True
    hilo_trading.start()
    puerto = int(os.getenv("PORT", 10000))
    app.run(host='0.0.0.0', port=puerto)
