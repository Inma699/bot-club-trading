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

# Credenciales de Telegram ya existentes en tu Render
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
margin_per_trade = 2.0      # Inversión fija: 2 USDT de margen
leverage = 75               # Apalancamiento sincronizado
COMISIONES_75X = 9.0        # Impacto estimado de comisiones en la pantalla (~9%)

PROFIT_ACTIVACION_TRAILING = 15.0  # Trailing se activa a +15%
DISTANCIA_PERSECUCION = 5.0        # Distancia de persecución (5%)
STOP_LOSS_INICIAL = 15.0           # Stop loss inicial de seguridad (15%)

# Memoria del Trailing
PRECIO_MAXIMO_ALCANZADO = 0.0

# === FUNCIÓN EXCLUSIVA DE ALERTAS PARA TU TELEGRAM ===
def enviar_alerta_telegram(mensaje):
    """ Envía notificaciones de texto con formato Markdown a tu canal """
    if not TOKEN_TELEGRAM or not CHAT_ID_CANAL:
        print("⚠️ Telegram: Faltan el TOKEN o CHAT_ID en Render. Alerta omitida.")
        return
    try:
        url = f"https://telegram.org{TOKEN_TELEGRAM}/sendMessage"
        payload = {
            "chat_id": CHAT_ID_CANAL,
            "text": mensaje,
            "parse_mode": "Markdown"
        }
        requests.post(url, json=payload, timeout=10)
    except Exception as e:
        print(f"⚠️ Error al enviar mensaje a Telegram: {e}")

def get_market_data():
    bars = exchange.fetch_ohlcv(symbol, timeframe='5m', limit=100)
    df = pd.DataFrame(bars, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
    df['timestamp'] = pd.to_datetime(df['timestamp'], unit='ms')
    return df

def analizar_estrategia_institucional(df):
    if len(df) < 5:
        return None
    velas = df.tail(5).to_dict('records')
    v_actual = candles = velas[-1]
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

# === EL MOTOR DE TRADING CORRIENDO EN UN HILO ASÍNCRONO ===
def motor_de_trading_bitget():
    global PRECIO_MAXIMO_ALCANZADO
    print("🦈 Bot Avanzado - Inicializando bucle con alertas de Telegram...")
    
    # Mensaje de arranque en tu canal
    enviar_alerta_telegram("🦈 *CLUB MARKETSHARKS*\n\n🤖 ¡Algoritmo Espejo Bitget Activado en Render 24/7!\nEscaneando estructuras institucionales y zonas de liquidación...")

    try:
        exchange.set_margin_mode('isolated', symbol)
        exchange.set_leverage(leverage, symbol)
    except Exception as e:
        print(f"⚠️ Nota de configuración inicial: {e}")

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
                print(f"🔍 [{timestamp}] Escaneando estructuras institucionales... BTC: {price:,.1f} USDT", end="\r")
                direccion_estrategia = analizar_estrategia_institucional(df)
                
                if direccion_estrategia == "COMPRA":
                    print(f"\n⚡ [{timestamp}] ¡ORDER BLOCK ALCISTA! Intentando LONG.")
                    params_bitget = {
                        'symbol': 'BTCUSDT', 'productType': 'USDT-FUTURES', 'marginMode': 'isolated',
                        'marginCoin': 'USDT', 'side': 'buy', 'tradeSide': 'open', 'orderType': 'market', 'size': str(trade_amount)
                    }
                    orden = exchange.privateMixPostV2MixOrderPlaceOrder(params_bitget)
                    
                    # Alerta a Telegram de Apertura
                    msg_compra = f"🟢 *NUEVA OPERACIÓN ESPEJO*\n\n🦈 *Tipo:* LONG (COMPRA)\n📈 *Precio Entrada:* {price:,.1f} USDT\n💰 *Margen:* {margin_per_trade} USDT\n🚀 *Apalancamiento:* {leverage}x\n📊 *Tamaño:* {trade_amount} BTC\n\n_El bot ha abierto la posición en Bitget Demo de forma automática._"
                    enviar_alerta_telegram(msg_compra)
                    time.sleep(5)
                    
                elif direccion_estrategia == "VENTA":
                    print(f"\n⚡ [{timestamp}] ¡ORDER BLOCK BAJISTA! Intentando SHORT.")
                    params_bitget = {
                        'symbol': 'BTCUSDT', 'productType': 'USDT-FUTURES', 'marginMode': 'isolated',
                        'marginCoin': 'USDT', 'side': 'sell', 'tradeSide': 'open', 'orderType': 'market', 'size': str(trade_amount)
                    }
                    orden = exchange.privateMixPostV2MixOrderPlaceOrder(params_bitget)
                    
                    # Alerta a Telegram de Apertura
                    msg_venta = f"🔴 *NUEVA OPERACIÓN ESPEJO*\n\n🦈 *Tipo:* SHORT (VENTA)\n📉 *Precio Entrada:* {price:,.1f} USDT\n💰 *Margen:* {margin_per_trade} USDT\n🚀 *Apalancamiento:* {leverage}x\n📊 *Tamaño:* {trade_amount} BTC\n\n_El bot ha abierto la posición en Bitget Demo de forma automática._"
                    enviar_alerta_telegram(msg_venta)
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
                print(f"📊 [{timestamp}] {side.upper()} | Bruto: {profit_bruto:.1f}% | Máx: {PRECIO_MAXIMO_ALCANZADO:.1f}% | Trailing: {trailing_activo}", end="\r")
                
                ejecutar_cierre = False
                motivo_cierre = ""
                tipo_resultado = ""
                
                if profit_bruto <= -STOP_LOSS_INICIAL:
                    ejecutar_cierre = True
                    motivo_cierre = "🛑 Stop Loss Inicial de seguridad alcanzado."
                    tipo_resultado = "LOSS"
                elif PRECIO_MAXIMO_ALCANZADO >= PROFIT_ACTIVACION_TRAILING:
                    if profit_bruto <= (PRECIO_MAXIMO_ALCANZADO - DISTANCIA_PERSECUCION):
                        if profit_bruto > COMISIONES_75X:
                            ejecutar_cierre = True
                            motivo_cierre = f"🎯 Trailing Stop disparado tras retroceder un {DISTANCIA_PERSECUCION}% desde el máximo."
                            tipo_resultado = "PROFIT"
                
                if ejecutar_cierre:
                    print(f"\n\n🚨 [{timestamp}] DISPARANDO ORDEN ESPEJO DE SALIDA: {motivo_cierre}")
                    close_side = 'sell' if side == 'long' else 'buy'
                    params_close = {
                        'symbol': 'BTCUSDT', 'productType': 'USDT-FUTURES', 'marginMode': 'isolated',
                        'marginCoin': 'USDT', 'side': close_side, 'tradeSide': 'close', 'orderType': 'market', 'size': str(contracts)
                    }
                    exchange.privateMixPostV2MixOrderPlaceOrder(params_close)
                    
                    # CALCULO DE DINERO GANADO/PERDIDO REAL NETO
                    # Ganancia neta % = Bruto % - 9% de comisiones
                    profit_neto_porcentaje = profit_bruto - COMISIONES_75X
                    dinero_neto = margin_per_trade * (profit_neto_porcentaje / 100)
                    
                    icono = "🏁" if tipo_resultado == "PROFIT" else "❌"
                    color_texto = "🔥 ¡Beneficio Consolidado!" if dinero_neto > 0 else "📉 Pérdida registrada"
                    
                    # Alerta a Telegram de Cierre con cálculo de dinero
                    msg_cierre = f"{icono} *OPERACIÓN CERRADA EN BITGET*\n\n" \
                                 f"🦈 *Dirección:* {side.upper()}\n" \
                                 f"📋 *Motivo:* {motivo_cierre}\n" \
                                 f"🏁 *Precio de Cierre:* {price:,.1f} USDT\n" \
                                 f"📊 *Rendimiento Bruto:* {profit_bruto:.2f}%\n" \
