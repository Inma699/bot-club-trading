import time
import smtplib
from email.mime.text import MIMEText
import pandas as pd
import pandas_ta as ta
import ccxt

# === CONFIGURACIÓN DE TU INFRAESTRUCTURA ===
# ⚠️ COPIA TU DIRECCIÓN DE EMAIL DE PIPEDREAM Y PÉGALA AQUÍ ABAJO (Mantén las comillas "")
EMAIL_DESTINO_PIPEDREAM = "emegsbbozraerrs@upload.pipedream.net"

SYMBOL = "BTC/USDT:USDT" # Par BTCUSDTPERP en Bitget
TIMEFRAME = "15m"

# Conexión pública a Bitget para leer las velas históricas en tiempo real
exchange = ccxt.bitget()

def buscar_order_blocks():
    try:
        # 1. Extraemos las últimas 300 velas de 15 minutos de Bitget
        bars = exchange.fetch_ohlcv(SYMBOL, timeframe=TIMEFRAME, limit=300)
        df = pd.DataFrame(bars, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
        
        # 2. Calculamos tu pilar sagrado: EMA 200
        df['ema_200'] = ta.ema(df['close'], length=200)
        
        # 3. Lógica matemática del indicador Order Block de wugamlo (Periods = 5)
        periods = 5
        ob_period = periods + 1
        
        # Analizamos la vela clave del pasado reciente (Fila -ob_period)
        row_ob = df.iloc[-ob_period]
        close_ob = row_ob['close']
        open_ob = row_ob['open']
        high_ob = row_ob['high']
        low_ob = row_ob['low']
        
        # Verificar si las siguientes 5 velas son del mismo color seguidas
        ultimas_velas = df.iloc[-periods:]
        todas_verdes = all(ultimas_velas['close'] > ultimas_velas['open'])
        todas_rojas = all(ultimas_velas['close'] < ultimas_velas['open'])
        
        precio_actual = df.iloc[-1]['close']
        ema_actual = df.iloc[-1]['ema_200']
        
        # === GATILLOS DE ALERTA CONECTADOS A TU FILTRO MACRO ===
        if (close_ob < open_ob) and todas_verdes and (precio_actual > ema_actual):
            enviar_alerta_email(action="BUY", position="1")
            
        elif (close_ob > open_ob) and todas_rojas and (precio_actual < ema_actual):
            enviar_alerta_email(action="SELL", position="-1")
        else:
            print("Escaneo finalizado: No hay patrones de Order Block válidos en esta vela.")
            
    except Exception as e:
        print(f"Error escaneando Bitget: {e}")

def enviar_alerta_email(action, position):
    mensaje_oficial = (
        f"New Señal BTCUSDT Order Block Finder + EMA 200 Estrategia (DARK, 5, 0, 200): "
        f"orden {action} @ 1 efectuada en BTCUSDTPERP. La nueva posición estratégica es {position}"
    )
    
    msg = MIMEText(mensaje_oficial)
    msg['Subject'] = 'New Señal BTCUSDT'
    msg['From'] = 'bot@clubtrading.com'
    msg['To'] = EMAIL_DESTINO_PIPEDREAM
    
    try:
        with smtplib.SMTP('localhost') as server:
            server.sendmail(msg['From'], [msg['To']], msg.as_string())
        print(f"🐋 ¡Email oficial enviado con éxito a tu Pipedream!")
    except Exception as e:
        print(f"Señal generada: {mensaje_oficial}. (Configurando envío de respaldo: {e})")

# Ejecución única para el sistema Cron de Render (Sin bucle While)
print("🚀 Iniciando radar rápido de Bitget...")
buscar_order_blocks()
