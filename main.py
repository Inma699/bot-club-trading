import os
import time
import ccxt
import pandas as pd
import threading
import requests
from datetime import datetime
from flask import Flask

# === MINISERVIDOR WEB PARA EVITAR QUE RENDER SE APAGUE ===
app = Flask(__name__)

@app.route('/')
def home():
    return "🦈 Algoritmo Espejo Bitget Demo + Alertas Telegram - Activo 24/7", 200

# ================== CONFIGURACIÓN ==================
API_KEY = os.getenv('BITGET_API_KEY', 'TU_API_KEY_DEMO')
SECRET = os.getenv('BITGET_API_SECRET', 'TU_SECRET_DEMO')
PASSWORD = os.getenv('BITGET_PASSWORD', 'TU_PASSPHRASE_DEMO')

TOKEN_TELEGRAM = os.getenv("TELEGRAM_TOKEN", "").strip()
CHAT_ID_CANAL = os.getenv("TELEGRAM_CHAT_ID", "").strip()

exchange = ccxt.bitget({
    'apiKey': API_KEY,
    'secret': SECRET,
    'password': PASSWORD,
    'enableRateLimit': True,
    'options': {'defaultType': 'swap'}
})
exchange.set_sandbox_mode(True)

symbol = 'BTC/USDT:USDT'

# === CONFIGURACIÓN DINÁMICA DE RIESGO Y TRAILING STOP ===
margin_per_trade = 2.0      
leverage = 75               
COMISIONES_75X = 9.0        

PROFIT_ACTIVACION_TRAILING = 15.0  
DISTANCIA_PERSECUCION = 5.0        
STOP_LOSS_INICIAL = 15.0           

PRECIO_MAXIMO_ALCANZADO = 0.0

def enviar_alerta_telegram(mensaje):
    if not TOKEN_TELEGRAM or not CHAT_ID_CANAL:
        print(f"⚠️ Telegram Error: Faltan credenciales en Render. TOKEN: '{TOKEN_TELEGRAM[:5] if TOKEN_TELEGRAM else 'VACÍO'}' | CHAT_ID: '{CHAT_ID_CANAL}'")
        return
    try:
        url = f"https://telegram.org{TOKEN_TELEGRAM}/sendMessage"
        payload = {"chat_id": CHAT_ID_CANAL, "text": mensaje, "parse_mode": "Markdown"}
        response = requests.post(url, json=payload, timeout=10)
        
        # Si Telegram rechaza el mensaje, imprimimos la razón exacta
        if response.status_code != 200:
            print(f"❌ Telegram rechazó el mensaje. Código {response.status_code}: {response.text}")
        else:
            print("✉️ Alerta de Telegram enviada con éxito al canal.")
    except Exception as e:
        print(f"⚠️ Error de conexión de red al intentar llamar a Telegram: {e}")

def get_market_data():
    bars = exchange.fetch_ohlcv(symbol, timeframe='5m', limit=100)
    df = pd.DataFrame(bars, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
    df['timestamp'] = pd.to_datetime(df['timestamp'], unit='ms')
    return df

def analizar_estrategia_institucional(df):
    if len(df) < 5:
        return None
    velas = df.tail(5).to_dict('records')
    v_actual = velas[-1]
    v_previa = velas[-2]
    maximo_reciente = max([v['high'] for v in velas[:-1]])
    minimo_reciente = min([v['low'] for v in velas[:-1]])
    volumen_promedio = df['volume'].tail(20).mean()
    volumen_alto = v_actual['volume'] > (volumen_promedio * 1.5)

    if v_actual['low'] <= minimo_reciente and v_actual['close'] > v_previa['close'] and volumen_alto:
        return "COMPRA"
    elif v_actual['high'] >= maximo_reciente and v_actual['close'] < v_previa['close'] and volumen_alto:
        return "VENTA"
    return None

def get_current_position():
    try:
        positions = exchange.fetch_positions([symbol])
        for p in positions:
            if p.get('contracts') is not None and float(p.get('contracts', 0)) > 0:
                return p
        return None
    except:
        return None

def motor_de_trading_bitget():
    global PRECIO_MAXIMO_ALCANZADO
    # Usamos flush=True para que Render imprima el log sin retrasos
    print("🦈 Bot Avanzado - Esperando estabilización de red de Render...", flush=True)
    
    time.sleep(10)
    
    print("🚀 Lanzando alertas a Telegram...", flush=True)
    enviar_alerta_telegram("🤖 *¡CLUB MARKETSHARKS ACTIVADO!*\n\nAlgoritmo Espejo Bitget operativo en Render 24/7.\nEscaneando Order Blocks y Liquidaciones en vivo...")

    try:
        exchange.set_margin_mode('isolated', symbol)
        exchange.set_leverage(leverage, symbol)
        print("✅ Configuración inicial de Bitget Demo completada.", flush=True)
    except Exception as e:
        print(f"⚠️ Nota de configuración inicial: {e}", flush=True)

    while True:
        try:
            df = get_market_data()
            price = df['close'].iloc[-1]
            timestamp = datetime.now().strftime('%H:%M:%S')
            
            poder_compra = margin_per_trade * leverage
            trade_amount = round(poder_compra / price, 4)
            position = get_current_position()
            
            if position is None:
                PRECIO_MAXIMO_ALCANZADO = 0.0
                # Cambiamos el end='\r' por un print limpio con flush para que se vea en Render obligatoriamente
                print(f"🔍 [{timestamp}] Escaneando estructuras... BTC: {price:,.1f} USDT", flush=True)
                direccion_estrategia = analizar_estrategia_institucional(df)
                
                if direccion_estrategia == "COMPRA":
                    print(f"\n⚡ [{timestamp}] ¡ORDER BLOCK ALCISTA! Intentando LONG.", flush=True)
                    params_bitget = {
                        'symbol': 'BTCUSDT', 'productType': 'USDT-FUTURES', 'marginMode': 'isolated',
                        'marginCoin': 'USDT', 'side': 'buy', 'tradeSide': 'open', 'orderType': 'market', 'size': str(trade_amount)
                    }
                    exchange.privateMixPostV2MixOrderPlaceOrder(params_bitget)
                    enviar_alerta_telegram(f"🟢 *LONG ABIERTO*\n📈 Entrada: {price:,.1f} USDT\n💰 Margen: {margin_per_trade} USDT")
                    time.sleep(5)
                    
                elif direccion_estrategia == "VENTA":
                    print(f"\n⚡ [{timestamp}] ¡ORDER BLOCK BAJISTA! Intentando SHORT.", flush=True)
                    params_bitget = {
                        'symbol': 'BTCUSDT', 'productType': 'USDT-FUTURES', 'marginMode': 'isolated',
                        'marginCoin': 'USDT', 'side': 'sell', 'tradeSide': 'open', 'orderType': 'market', 'size': str(trade_amount)
                    }
                    exchange.privateMixPostV2MixOrderPlaceOrder(params_bitget)
                    enviar_alerta_telegram(f"🔴 *SHORT ABIERTO*\n📉 Entrada: {price:,.1f} USDT\n💰 Margen: {margin_per_trade} USDT")
                    time.sleep(5)

            else:
                side = position['side']
                entry = float(position['entryPrice'])
                contracts = float(position['contracts'])
                
                profit_bruto = ((price - entry) / entry * 100) * leverage
                if side == 'short':
                    profit_bruto = -profit_bruto
                    
                if PRECIO_MAXIMO_ALCANZADO == 0.0:
                    PRECIO_MAXIMO_ALCANZADO = profit_bruto
                elif profit_bruto > PRECIO_MAXIMO_ALCANZADO:
                    PRECIO_MAXIMO_ALCANZADO = profit_bruto
                    
                trailing_activo = "SÍ" if PRECIO_MAXIMO_ALCANZADO >= PROFIT_ACTIVACION_TRAILING else "NO"
                print(f"📊 [{timestamp}] {side.upper()} | Bruto: {profit_bruto:.1f}% | Máx: {PRECIO_MAXIMO_ALCANZADO:.1f}% | Trailing: {trailing_activo}", flush=True)
                
                ejecutar_cierre = False
                motivo_cierre = ""
                
                if profit_bruto <= -STOP_LOSS_INICIAL:
                    ejecutar_cierre = True
                    motivo_cierre = "Stop Loss de seguridad alcanzado"
                elif PRECIO_MAXIMO_ALCANZADO >= PROFIT_ACTIVACION_TRAILING:
                    if profit_bruto <= (PRECIO_MAXIMO_ALCANZADO - DISTANCIA_PERSECUCION):
                        if profit_bruto > COMISIONES_75X:
                            ejecutar_cierre = True
                            motivo_cierre = "Trailing Stop ejecutado"
                
                if ejecutar_cierre:
                    close_side = 'sell' if side == 'long' else 'buy'
                    params_close = {
                        'symbol': 'BTCUSDT', 'productType': 'USDT-FUTURES', 'marginMode': 'isolated',
                        'marginCoin': 'USDT', 'side': close_side, 'tradeSide': 'close', 'orderType': 'market', 'size': str(contracts)
                    }
                    exchange.privateMixPostV2MixOrderPlaceOrder(params_close)
                    
                    profit_neto_porcentaje = profit_bruto - COMISIONES_75X
                    dinero_neto = margin_per_trade * (profit_neto_porcentaje / 100)
                    
                    msg_cierre = (
                        f"🏁 *POSICIÓN CERRADA EN BITGET*\n\n"
                        f"📋 Motivo: {motivo_cierre}\n"
                        f"📊 Rendimiento Bruto: {profit_bruto:.2f}%\n"
                        f"📈 Rendimiento Neto: {profit_neto_porcentaje:.2f}%\n"
                        f"💰 *RESULTADO NETO:* `{dinero_neto:+.4f} USDT`"
                    )
                    enviar_alerta_telegram(msg_cierre)
                    time.sleep(10)
                    
            time.sleep(10)
        except Exception as e:
            print(f"\n❌ Error en bucle: {e}", flush=True)
            time.sleep(15)

if __name__ == '__main__':
    hilo_bot = threading.Thread(target=motor_de_trading_bitget)
    hilo_bot.daemon = True
    hilo_bot.start()
    
    puerto = int(os.getenv("PORT", 10000))
    app.run(host='0.0.0.0', port=puerto)
