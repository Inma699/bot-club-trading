import os
import time
import requests
import pandas as pd
import ccxt

# === CONFIGURACIÓN DE SEGURIDAD PARA TELEGRAM ===
TOKEN_TELEGRAM = os.environ.get("TELEGRAM_TOKEN")
ID_CHAT_CANAL  = os.environ.get("TELEGRAM_CHAT_ID")

SYMBOL = "BTC/USDT:USDT" # Par BTCUSDTPERP en Bitget
TIMEFRAME = "15m"

exchange = ccxt.bitget()

def buscar_order_blocks():
    try:
        bars = exchange.fetch_ohlcv(SYMBOL, timeframe=TIMEFRAME, limit=300)
        df = pd.DataFrame(bars, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
        
        # === CÁLCULO MATEMÁTICO NATIVO DE TU EMA 200 (SIN LIBRERÍAS EXTENSIÓN) ===
        df['ema_200'] = df['close'].ewm(span=200, adjust=False).mean()
        
        periods = 5
        ob_period = periods + 1
        row_ob = df.iloc[-ob_period]
        close_ob = row_ob['close']
        open_ob = row_ob['open']
        
        ultimas_velas = df.iloc[-periods:]
        todas_verdes = all(ultimas_velas['close'] > ultimas_velas['open'])
        todas_rojas = all(ultimas_velas['close'] < ultimas_velas['open'])
        
        precio_actual = df.iloc[-1]['close']
        ema_actual = df.iloc[-1]['ema_200']
        
        if (close_ob < open_ob) and todas_verdes and (precio_actual > ema_actual):
            enviar_alerta_telegram(action="LONG 📈", pnl="35%", sl="17.5%")
        elif (close_ob > open_ob) and todas_rojas and (precio_actual < ema_actual):
            enviar_alerta_telegram(action="SHORT 💥", pnl="35%", sl="17.5%")
        else:
            print("Escaneo Bitget OK: Sin señales de Order Blocks.")
            
    except Exception as e:
        print(f"Error escaneando Bitget: {e}")

def enviar_alerta_telegram(action, pnl, sl):
    mensaje_oficial = (
        f"🐋 *¡ALERTA CLUB TRADING - MOVIMIENTO DE BALLENAS!* 🐋\n\n"
        f"👉 *Par:* BTCUSDTPERP (Futuros Bitget)\n"
        f"🚀 *Operación:* {action} (Confirmado por Order Block & EMA 200)\n\n"
        f"🎯 *TARGET ACONSEJADO:* +{pnl} PNL\n"
        f"🛑 *STOP LOSS PROTEGIDO:* -{sl} PNL\n\n"
        f"¡Revisa tu app de Bitget y asegura tu posición! 💥"
    )
    
    url = f"https://telegram.org{TOKEN_TELEGRAM}/sendMessage"
    payload = {
        "chat_id": ID_CHAT_CANAL,
        "text": mensaje_oficial,
        "parse_mode": "Markdown"
    }
    
    try:
        response = requests.post(url, json=payload)
        if response.status_code == 200:
            print(f"🐋 ¡Alerta oficial publicada con éxito en tu canal de Telegram!")
            time.sleep(1200)
    except Exception as e:
        print(f"Error enviando mensaje a Telegram: {e}")
        time.sleep(1200)

print("🚀 Bot Club encendido en la nube... Escaneando Bitget y conectado a Telegram 24/7")
while True:
    buscar_order_blocks()
    time.sleep(60)
