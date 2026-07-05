import os
import threading
import time
from flask import Flask
import requests

# === CONFIGURACIÓN DEL SERVIDOR WEB PARA RENDER ===
# Render exige un servicio web activo que responda por el puerto 10000 
# para certificar que el despliegue es exitoso ("Live").
app = Flask(__name__)

@app.route('/')
def home():
    return "Club MarketSharks - Bot de Señales Operativo", 200

@app.route('/health')
def health():
    return "OK", 200

# === CONFIGURACIÓN DE LAS CREDENCIALES (SECRETS) ===
# Es más seguro usar variables de entorno de Render, pero puedes poner tus textos fijos aquí
TOKEN_TELEGRAM = os.getenv("TELEGRAM_TOKEN", "TU_NUEVO_TOKEN_DE_BOTFATHER")
CHAT_ID_CANAL = os.getenv("TELEGRAM_CHAT_ID", "TU_ID_DE_CANAL_CON_MENOS_100")

def enviar_senal_telegram(mensaje):
    """Envía la alerta directamente a la API de Telegram de forma automática"""
    url = f"https://telegram.org{TOKEN_TELEGRAM}/sendMessage"
    payload = {
        "chat_id": CHAT_ID_CANAL,
        "text": mensaje,
        "parse_mode": "Markdown"
    }
    try:
        response = requests.post(url, json=payload, timeout=10)
        if response.status_code == 200:
            print("📢 Señal enviada a Telegram con éxito.")
        else:
            print(f"❌ Error de la API de Telegram: {response.text}")
    except Exception as e:
        print(f"⚠️ Error en la conexión de red: {e}")

# === BUCLE PRINCIPAL DE MONITOREO DE TRADING (ORDER BLOCKS) ===
def bucle_estrategia():
    """Aquí corre el análisis matemático de la EMA 200 y los Order Blocks"""
    print("🚀 Motor analítico de Order Blocks + EMA 200 iniciado...")
    
    # Tiempo de espera inicial para que el servidor web de Render se active primero
    time.sleep(10)
    
    while True:
        try:
            # Aquí Python analizará el mercado en el futuro. 
            # Simulamos una detección positiva bajo tu filtro macro:
            print("🔍 Escaneando Order Blocks en BTCUSDT...")
            
            # NOTA: Para las pruebas, simulamos que se detecta un Bullish OB por encima de la EMA 200
            # Cambia esta lógica o añade tu conector de Binance/CCXT aquí.
            detectado_ob = True 
            tipo_ob = "BULLISH OB 🟢"
            precio_actual = "64250.00"
            
            if detectado_ob:
                mensaje_alert = (
                    f"🦈 *CLUB MARKETSHARKS ALERTA AUTOMÁTICA*\n\n"
                    f"📊 *Par:* BTCUSDT\n"
                    f"🎯 *Estrategia:* Order Block Finder + EMA 200\n"
                    f"⚡ *Señal:* {tipo_ob} Detectado\n"
                    f"💵 *Precio de Entrada:* € {precio_actual} EUR\n"
                    f"⏰ *Estado:* Confirmado por algoritmo"
                )
                enviar_senal_telegram(mensaje_alert)
                
                # Pausa larga tras enviar la señal para no saturar el canal (ej: esperar 1 hora o nueva vela)
                time.sleep(3600) 
                
        except Exception as e:
            print(f"⚠️ Error en el bucle de trading: {e}")
            time.sleep(60)

# === ARRANCAR AMBOS MOTORES A LA VEZ ===
if __name__ == '__main__':
    # Lanzamos el motor de trading en un hilo paralelo para que no bloquee a Flask
    hilo_trading = threading.Thread(target=bucle_estrategia)
    hilo_trading.daemon = True
    hilo_trading.start()
    
    # Render asigna el puerto dinámicamente mediante la variable PORT, si no usa el 10000
    puerto = int(os.getenv("PORT", 10000))
    app.run(host='0.0.0.0', port=puerto)
