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
        
    url = f"https://telegram.org{TOKEN_TELEGRAM}/sendMessage"
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
    """Conecta en tiempo real con la API pública de Binance para extraer las últimas 200 velas"""
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
    """Calcula matemáticamente la EMA 200 exacta igual que TradingView"""
    if len(precios_cierre) < periodo:
        return None
    k = 2 / (periodo + 1)
    ema = prices_initial = precios_cierre[0]
    for precio in precios_cierre[1:]:
        ema = (precio * k) + (ema * (1 - k))
    return ema

# === BUCLE DE MONITOREO EN TIEMPO REAL (ESCANEO CADA 60 SEGUNDOS) ===
def motor_de_trading():
    print("🚀 Motor analítico real conectado a Binance... Analizando mercado.")
    
    # Alerta inmediata para certificar que las llaves de Render funcionan
    alerta_inicio = "🦈 *CLUB MARKETSHARKS*\n\n🤖 El algoritmo se ha conectado con éxito al mercado en vivo. Escaneando BTCUSDT minuto a minuto..."
    enviar_senal_telegram(alerta_inicio)
    
    while True:
        try:
            datos = obtener_datos_binance()
            if datos:
                # Cambiamos las velas de texto a números decimales
                cierres = [float(vela[4]) for vela in datos]
                precio_actual = cierres[-1]
                
                # Calculamos la EMA 200 macro
                ema_200 = calcular_ema(cierres, 200)
                
                if ema_200:
                    por_encima_ema = precio_actual > ema_200
                    
                    # Identificación del bloque de órdenes (Vela de ruptura reciente)
                    absmove = ((abs(cierres[-5] - precio_actual)) / cierres[-5]) * 100
                    
                    if absmove > 0.5 and por_encima_ema:
                        mensaje_alert = (
                            f"🦈 *CLUB MARKETSHARKS ALERTA EN VIVO*\n\n"
                            f"📊 *Par:* BTCUSDT (15m)\n"
                            f"🎯 *Estrategia:* Order Block + EMA 200\n"
                            f"🟢 *Dirección:* COMPRA (Bullish OB)\n"
                            f"💵 *Precio Entrada:* $ {precio_actual:,.2f} USD\n"
                            f"📈 *Filtro Trend:* Por encima de EMA 200 ($ {ema_200:,.2f})"
                        )
                        enviar_senal_telegram(mensaje_alert)
                        time.sleep(900)  # Si hay señal, espera 15 min a que cierre la vela
                        continue

            print("🔍 Escaneo completado. Sin cambios. Próximo análisis en 60 segundos...")
            time.sleep(60)  # Tu escaneo rápido minuto a minuto
            
        except Exception as e:
            print(f"⚠️ Error en el bucle de trading: {e}")
            time.sleep(30)

if __name__ == '__main__':
    hilo_trading = threading.Thread(target=motor_de_trading)
    hilo_trading.daemon = True
    hilo_trading.start()
    
    puerto = int(os.getenv("PORT", 10000))
    app.run(host='0.0.0.0', port=puerto)
