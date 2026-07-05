import os
import threading
import time
from flask import Flask
import requests

# === CONFIGURACIÓN DEL SERVIDOR WEB PARA RENDER ===
app = Flask(__name__)

@app.route('/')
def home():
    return "Club MarketSharks - Analizador de Mercados en Vivo", 200

# === CREDENCIALES DESDE ENVIRONMENT VARIABLES ===
TOKEN_TELEGRAM = os.getenv("TELEGRAM_TOKEN")
CHAT_ID_CANAL = os.getenv("TELEGRAM_CHAT_ID")

def enviar_senal_telegram(mensaje):
    """Envía la alerta de forma síncrona y directa por protocolo HTTP POST"""
    if not TOKEN_TELEGRAM or not CHAT_ID_CANAL:
        print("❌ Error: Faltan las variables secretas en el panel de Render.")
        return
        
    url = f"https://api.telegram.org/bot{TOKEN_TELEGRAM}/sendMessage"
    payload = {
        "chat_id": CHAT_ID_CANAL,
        "text": mensaje,
        "parse_mode": "Markdown"
    }
    try:
        response = requests.post(url, json=payload, timeout=10)
        if response.status_code == 200:
            print("📢 ¡Señal enviada a Telegram con éxito!")
        else:
            print(f"❌ API Telegram rechazó el envío: {response.text}")
    except Exception as e:
        print(f"⚠️ Error de red al conectar con Telegram: {e}")

def obtener_datos_binance():
    """Conecta en tiempo real con la API pública de Binance para extraer las últimas 210 velas"""
    url = "https://binance.com"
    params = {
        "symbol": "BTCUSDT",
        "interval": "15m",  
        "limit": 210        
    }
    try:
        response = requests.get(url, params=params, timeout=10)
        if response.status_code == 200:
            return response.json()
    except Exception as e:
        print(f"⚠️ Error al conectar con la API de Binance: {e}")
    return None

def calcular_ema(precios_cierre, periodo=200):
    """Calcula matemáticamente la EMA 200 exacta sobre la lista de precios"""
    if len(precios_cierre) < periodo:
        return None
    k = 2 / (periodo + 1)
    ema = precios_cierre[0]
    for precio in precios_cierre[1:]:
        ema = (precio * k) + (ema * (1 - k))
    return ema

# === BUCLE DE MONITOREO EN TIEMPO REAL (ESCANEO CADA 60 SEGUNDOS) ===
def motor_de_trading():
    print("🚀 Motor analítico real conectado a Binance... Analizando mercado.")
    
    # Pausa de seguridad de 5 segundos para que Flask levante el puerto 10000 en Render
    time.sleep(5)
    
    # Alerta de confirmación inmediata al arrancar el búnker de Python
    alerta_inicio = "🦈 *CLUB MARKETSHARKS*\n\n🤖 El algoritmo se ha conectado con éxito al mercado en vivo. Escaneando BTCUSDT en intervalos de 15 minutos de forma automática..."
    enviar_senal_telegram(alerta_inicio)
    
    while True:
        try:
            datos = obtener_datos_binance()
            if datos:
                # El índice [4] dentro de los datos de Binance corresponde exactamente al precio de Cierre (Close)
                cierres = [float(vela[4]) for vela in datos]
                precio_actual = cierres[-1]
                
                # Calculamos la EMA 200 macro
                ema_200 = calcular_ema(cierres, 200)
                
                if ema_200:
                    por_encima_ema = precio_actual > ema_200
                    
                    # Identificación del bloque de órdenes (Vela de ruptura reciente)
                    absmove = ((abs(cierres[-5] - precio_actual)) / cierres[-5]) * 100
                    
                    if absmove > 0.5 and por_encima_ema:
                        # === CÁLCULO AUTOMÁTICO DE GESTIÓN DE RIESGO INSTITUCIONAL ===
                        # Calculamos el Stop Loss dinámico usando el mínimo de la vela del Order Block (vela -6)
                        vela_ob = datos[-6]
                        stop_loss = float(vela_ob[3]) # Índice 3 es el Low (Mínimo) en Binance
                        
                        # Control de seguridad: Si el mínimo está muy lejos, usamos un margen estándar de $150
                        if (precio_actual - stop_loss) > 500 or stop_loss >= precio_actual:
                            stop_loss = precio_actual - 150.00
                            
                        # El Take Profit busca el doble de beneficio que lo que arriesga el Stop Loss (Ratio 1:2)
                        distancia_riesgo = precio_actual - stop_loss
                        take_profit = precio_actual + (distancia_riesgo * 2)
                        
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
                        time.sleep(900)  # Si hay señal, espera 15 min a que cierre la vela
                        continue

            print("🔍 Escaneo completado. Mercado estable. Próximo análisis en 60 segundos...")
            time.sleep(60)  
            
        except Exception as e:
            print(f"⚠️ Error en el bucle de trading: {e}")
            time.sleep(30)

if __name__ == '__main__':
    hilo_trading = threading.Thread(target=motor_de_trading)
    hilo_trading.daemon = True
    hilo_trading.start()
    
    puerto = int(os.getenv("PORT", 10000))
    app.run(host='0.0.0.0', port=puerto)
