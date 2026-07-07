import os
import threading
import time
from flask import Flask
import requests

app = Flask(__name__)

@app.route('/')
def home():
    return "Club MarketSharks - Algoritmo Espejo TradingView Activo", 200

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
    """Calcula la EMA usando el método de suavizado exacto de TradingView (SMA inicial + Alpha)"""
    if len(precios_cierre) < periodo:
        return None
    sma_inicial = sum(precios_cierre[:periodo]) / periodo
    alpha = 2 / (periodo + 1)
    ema = sma_inicial
    for precio in precios_cierre[periodo:]:
        ema = (precio * alpha) + (ema * (1 - alpha))
    return ema

# === BUCLE DE TRADING EN TIEMPO REAL ===
def motor_de_trading():
    print("🚀 Iniciando motor analítico duplicador de TradingView...")
    time.sleep(5)
    
    # Alerta inmediata de inicio para confirmar que Render y Telegram están conectados
    alerta_inicio = "🦈 *CLUB MARKETSHARKS*\n\n🤖 Algoritmo de sincronización activado. Escaneando el mercado en vivo clonando la estrategia de TradingView..."
    enviar_senal_telegram(alerta_inicio)
    
    while True:
        try:
            datos = obtener_datos_binance()
            if datos:
                # Estructura de Binance: [1]=Open, [2]=High, [3]=Low, [4]=Close
                aperturas = [float(vela[1]) for vela in datos]
                altos     = [float(vela[2]) for vela in datos]
                bajos     = [float(vela[3]) for vela in datos]
                cierres   = [float(vela[4]) for vela in datos]
                
                precio_actual = cierres[-1]
                ema_200 = calcular_ema_tradingview(cierres, 200)
                
                if ema_200:
                    por_encima_ema = precio_actual > ema_200
                    
                    # En tu Pine Script: ob_period = periods + 1 (5 + 1 = 6 velas hacia atrás)
                    # Analizamos la vela origen del bloque de órdenes
                    idx_ob = -6 
                    
                    # 1. Bullish Order Block Identification (La vela origen debe ser roja)
                    bullishOB = cierres[idx_ob] < aperturas[idx_ob]
                    
                    # 2. Las siguientes 5 velas deben ser alcistas (verdes) consecutivas
                    upcandles = 0
                    for i in range(-5, 0): # Revisa las posiciones -5, -4, -3, -2, -1
                        if cierres[i] > aperturas[i]:
                            upcandles += 1
                    
                    # 3. Movimiento de porcentaje mínimo (Threshold = 0.5%)
                    absmove = (abs(cierres[idx_ob] - precio_actual) / cierres[idx_ob]) * 100
                    relmove = absmove >= 0.5
                    
                    # === DISPARO DEL GATILLO DE COMPRA ===
                    if bullishOB and (upcandles == 5) and relmove and por_encima_ema:
                        # Sacamos el mínimo de la vela del bloque de órdenes (Índice 3 en Binance es el Low)
                        stop_loss = float(datos[idx_ob][3])
                        
                        # Margen de seguridad si el stop queda demasiado ajustado
                        if stop_loss >= precio_actual or (precio_actual - stop_loss) > 600:
                            stop_loss = precio_actual - 200.00
                            
                        distancia_riesgo = precio_actual - stop_loss
                        take_profit = precio_actual + (distancia_riesgo * 2) # Ratio 1:2
                        
                        mensaje_alert = (
                            f"🦈 *CLUB MARKETSHARKS ALERTA EN VIVO*\n\n"
                            f"📊 *Par:* BTCUSDT (15m)\n"
                            f"🎯 *Estrategia:* Order Block + EMA 200\n"
                            f"🟢 *Dirección:* COMPRA (Bullish OB Confirmado)\n\n"
                            f"💵 *Precio Entrada:* $ {precio_actual:,.2f} USD\n"
                            f"🛡️ *Stop Loss (SL):* $ {stop_loss:,.2f} USD\n"
                            f"💰 *Take Profit (TP):* $ {take_profit:,.2f} USD\n"
                            f"⚙️ *Apalancamiento:* 50x (Mínimo recomendado)\n\n"
                            f"📈 *Filtro Trend:* Operación por encima de EMA 200 ($ {ema_200:,.2f})"
                        )
                        enviar_senal_telegram(mensaje_alert)
                        time.sleep(900)  # Pausa de 15 minutos para que cierre la vela actual y no repita la señal
                        continue

            print("🔍 Escaneo completado. Sin novedades en los Order Blocks. Reintentando en 60 segundos...")
            time.sleep(60)  
            
        except Exception as e:
            print(f"⚠️ Error en el motor de trading: {e}")
            time.sleep(30)

if __name__ == '__main__':
    hilo_trading = threading.Thread(target=motor_de_trading)
    hilo_trading.daemon = True
    hilo_trading.start()
    
    puerto = int(os.getenv("PORT", 10000))
    app.run(host='0.0.0.0', port=puerto)
