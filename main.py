import os
import threading
import time
from flask import Flask
import requests

app = Flask(__name__)

@app.route('/')
def home():
    return "Club MarketSharks - Clon Matemático Corregido", 200

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
    if len(precios_cierre) < periodo:
        return None
    sma_inicial = sum(precios_cierre[:periodo]) / periodo
    alpha = 2 / (periodo + 1)
    ema = sma_inicial
    for precio in precios_cierre[periodo:]:
        ema = (precio * alpha) + (ema * (1 - alpha))
    return ema

# === BUCLE DE TRADING AUTOMÁTICO ===
def motor_de_trading():
    print("🚀 Motor espejo corregido iniciado...")
    time.sleep(5)
    
    # Alerta inmediata de inicio para confirmar la conexión de red
    alerta_inicio = "🦈 *CLUB MARKETSHARKS*\n\n🤖 El algoritmo se ha conectado con éxito al mercado en vivo. Escaneando BTCUSDT en intervalos de 15 minutos de forma automática..."
    enviar_senal_telegram(alerta_inicio)
    
    while True:
        try:
            datos = obtener_datos_binance()
            if datos:
                # CORRECCIÓN DE LA ESTRUCTURA DE BINANCE:
                # index 1 = Open, 4 = Close
                aperturas = [float(vela[1]) for vela in datos]
                cierres   = [float(vela[4]) for vela in datos]
                
                precio_actual = cierres[-1]
                ema_200 = calcular_ema_tradingview(cierres, 200)
                
                if ema_200:
                    por_encima_ema = precio_actual > ema_200
                    idx_ob = -6 
                    
                    # Lógica Clonada de TradingView (Periods = 5, Threshold = 0.5)
                    bullishOB = cierres[idx_ob] < aperturas[idx_ob]
                    
                    upcandles = 0
                    for i in range(-5, 0): 
                        if cierres[i] > aperturas[i]:
                            upcandles += 1
                            
                    absmove = (abs(cierres[idx_ob] - precio_actual) / cierres[idx_ob]) * 100
                    relmove = absmove >= 0.5
                    
                    OB_bull_detectado = bullishOB and (upcandles == 5) and relmove and por_encima_ema
                    
                    if OB_bull_detectado:
                        # Cálculo Dinámico del Stop Loss (Mínimo de la vela del OB que es index 3 en Binance)
                        stop_loss = float(datos[idx_ob][3]) 
                        distancia_sl = precio_actual - stop_loss
                        take_profit = precio_actual + (distancia_sl * 2) # Relación Riesgo/Beneficio 1:2
                        
                        mensaje_alert = (
                            f"🦈 *CLUB MARKETSHARKS ALERTA EN VIVO*\n\n"
                            f"📊 *Par:* BTCUSDT (15m)\n"
                            f"🎯 *Estrategia:* Order Block + EMA 200\n"
                            f"🟢 *Dirección:* COMPRA (Bullish OB Confirmado)\n\n"
                            f"💵 *Precio Entrada:* $ {precio_actual:,.2f} USD\n"
                            f"🛡️ *Stop Loss (SL):* $ {stop_loss:,.2f} USD\n"
                            f"💰 *Take Profit (TP):* $ {take_profit:,.2f} USD\n"
                            f"⚙️ *Apalancamiento:* 10x - 20x (Recomendado)\n\n"
                            f"📈 *Filtro Trend:* Operación por encima de EMA 200 ($ {ema_200:,.2f})"
                        )
                        enviar_senal_telegram(mensaje_alert)
                        time.sleep(900) 
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
