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
TOKEN_TELEGRAM = os.getenv("TELEGRAM_TOKEN", "").strip()
CHAT_ID_CANAL = os.getenv("TELEGRAM_CHAT_ID", "").strip()

# === CONFIGURACIÓN DE MERCADOS ===
CONFIGURACIONES_MERCADO = [
    {"symbol": "BTCUSDT", "interval": "15m", "nombre": "BTCUSDT (15m)"},
    {"symbol": "SPXCUSDT", "interval": "1h", "nombre": "SPXCUSDT (1h)"},
]

# === ESTADÍSTICAS DIARIAS ===
ESTADISTICAS = {
    "total_senales": 0,
    "compras": 0,
    "ventas": 0,
    "ganadas": 0,
    "perdidas": 0,
    "ultimo_resumen": None,
}

# === SEGUIMIENTO DE OPERACIONES ABIERTAS ===
OPERACIONES_ABIERTAS = []


def enviar_senal_telegram(mensaje):
    if not TOKEN_TELEGRAM or not CHAT_ID_CANAL:
        print("⚠️ Faltan TELEGRAM_TOKEN o TELEGRAM_CHAT_ID en Render")
        return

    url = f"https://api.telegram.org/bot{TOKEN_TELEGRAM}/sendMessage"
    payload = {"chat_id": CHAT_ID_CANAL, "text": mensaje, "parse_mode": "Markdown"}
    try:
        response = requests.post(url, json=payload, timeout=10)
        response.raise_for_status()
        print("✅ Señal enviada a Telegram")
    except Exception as e:
        print(f"⚠️ Error enviando señal a Telegram: {e}")


def obtener_datos_binance(symbol, interval, limit=210):
    url = "https://api.binance.com/api/v3/klines"
    params = {"symbol": symbol, "interval": interval, "limit": limit}
    try:
        response = requests.get(url, params=params, timeout=10)
        if response.status_code == 200:
            return response.json()
        print(f"⚠️ Binance devolvió estado {response.status_code} para {symbol} {interval}: {response.text[:200]}")
    except Exception as e:
        print(f"⚠️ Error consultando Binance para {symbol} {interval}: {e}")
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


def enviar_resumen_diario():
    global ESTADISTICAS
    hoy = time.strftime("%Y-%m-%d")
    ratio = round((ESTADISTICAS['ganadas'] / max(ESTADISTICAS['total_senales'], 1)) * 100, 1)
    resumen = (
        f"📊 *RESUMEN DIARIO CLUB MARKETSHARKS*\n\n"
        f"📅 Fecha: {hoy}\n"
        f"🔢 Total señales: {ESTADISTICAS['total_senales']}\n"
        f"🟢 Compras: {ESTADISTICAS['compras']}\n"
        f"🔴 Ventas: {ESTADISTICAS['ventas']}\n"
        f"✅ Ganadas: {ESTADISTICAS['ganadas']}\n"
        f"❌ Perdidas: {ESTADISTICAS['perdidas']}\n"
        f"📈 Ratio: {ratio}%"
    )
    enviar_senal_telegram(resumen)
    ESTADISTICAS["ultimo_resumen"] = hoy


def actualizar_operaciones_abiertas(cierres, datos, mercado):
    global OPERACIONES_ABIERTAS, ESTADISTICAS

    if not OPERACIONES_ABIERTAS:
        return

    precio_actual = cierres[-1]
    nuevas_operaciones = []

    for op in OPERACIONES_ABIERTAS:
        if op["tipo"] == "COMPRA":
            ganancia_pct = ((precio_actual - op["entrada"]) / op["entrada"]) * 100
            if precio_actual <= op["stop_loss"]:
                ESTADISTICAS["perdidas"] += 1
                nuevas_operaciones.append((op, "perdida"))
            elif precio_actual >= op["take_profit"]:
                ESTADISTICAS["ganadas"] += 1
                nuevas_operaciones.append((op, "ganada"))
            else:
                if ganancia_pct >= 10 and not op.get("aviso_10pct", False):
                    op["aviso_10pct"] = True
                    mensaje_profit = (
                        f"📈 *AVISO DE CIERRE*\n\n"
                        f"📊 Par: {op['mercado']}\n"
                        f"🔹 Tipo: {op['tipo']}\n"
                        f"💹 Beneficio actual: {ganancia_pct:.2f}%\n"
                        f"💡 Se recomienda cerrar la operación si deseas tomar ganancias."
                    )
                    enviar_senal_telegram(mensaje_profit)
                nuevas_operaciones.append((op, None))
        else:
            ganancia_pct = ((op["entrada"] - precio_actual) / op["entrada"]) * 100
            if precio_actual >= op["stop_loss"]:
                ESTADISTICAS["perdidas"] += 1
                nuevas_operaciones.append((op, "perdida"))
            elif precio_actual <= op["take_profit"]:
                ESTADISTICAS["ganadas"] += 1
                nuevas_operaciones.append((op, "ganada"))
            else:
                if ganancia_pct >= 10 and not op.get("aviso_10pct", False):
                    op["aviso_10pct"] = True
                    mensaje_profit = (
                        f"📈 *AVISO DE CIERRE*\n\n"
                        f"📊 Par: {op['mercado']}\n"
                        f"🔹 Tipo: {op['tipo']}\n"
                        f"💹 Beneficio actual: {ganancia_pct:.2f}%\n"
                        f"💡 Se recomienda cerrar la operación si deseas tomar ganancias."
                    )
                    enviar_senal_telegram(mensaje_profit)
                nuevas_operaciones.append((op, None))

    OPERACIONES_ABIERTAS = [op for op, estado in nuevas_operaciones if estado is None]

    for op, estado in nuevas_operaciones:
        if estado is None:
            continue
        mensaje_cierre = (
            f"🧾 *CIERRE DE OPERACIÓN*\n\n"
            f"📊 Par: {op['mercado']}\n"
            f"🔹 Tipo: {op['tipo']}\n"
            f"💵 Entrada: $ {op['entrada']:,.2f}\n"
            f"🛑 Stop: $ {op['stop_loss']:,.2f}\n"
            f"🎯 Take Profit: $ {op['take_profit']:,.2f}\n"
            f"✅ Resultado: {estado.upper()}"
        )
        enviar_senal_telegram(mensaje_cierre)


# === BUCLE DE TRADING EN TIEMPO REAL ===
def motor_de_trading():
    print("🚀 Iniciando motor analítico duplicador de TradingView...")
    time.sleep(5)

    alerta_inicio = "🦈 *CLUB MARKETSHARKS*\n\n🤖 Algoritmo de sincronización activado. Escaneando el mercado en vivo clonando la estrategia de TradingView para compra y venta..."
    enviar_senal_telegram(alerta_inicio)

    while True:
        try:
            senal_enviada = False

            for mercado in CONFIGURACIONES_MERCADO:
                datos = obtener_datos_binance(mercado["symbol"], mercado["interval"])
                if not datos:
                    continue

                # Estructura de Binance: [1]=Open, [2]=High, [3]=Low, [4]=Close
                aperturas = [float(vela[1]) for vela in datos]
                altos = [float(vela[2]) for vela in datos]
                bajos = [float(vela[3]) for vela in datos]
                cierres = [float(vela[4]) for vela in datos]

                precio_actual = cierres[-1]
                actualizar_operaciones_abiertas(cierres, datos, mercado)
                ema_200 = calcular_ema_tradingview(cierres, 200)

                if not ema_200:
                    continue

                idx_ob = -6
                vela_ob = datos[idx_ob]
                apertura_ob = float(vela_ob[1])
                cierre_ob = float(vela_ob[4])
                low_ob = float(vela_ob[3])
                high_ob = float(vela_ob[2])

                # 1. Order Block: vela origen roja para compra y verde para venta
                bullish_ob = cierre_ob < apertura_ob
                bearish_ob = cierre_ob > apertura_ob

                # 2. Las siguientes 5 velas deben ser consecutivamente alcistas o bajistas
                ultimas_5 = list(range(-5, 0))
                bullish_sequence = all(cierres[i] > aperturas[i] for i in ultimas_5)
                bearish_sequence = all(cierres[i] < aperturas[i] for i in ultimas_5)

                # 3. Movimiento mínimo del 0.5%
                absmove = (abs(cierre_ob - precio_actual) / cierre_ob) * 100
                relmove = absmove >= 0.5

                if bullish_ob and bullish_sequence and relmove and precio_actual > ema_200:
                    stop_loss = low_ob
                    if stop_loss >= precio_actual or (precio_actual - stop_loss) > 600:
                        stop_loss = precio_actual - 200.00

                    distancia_riesgo = precio_actual - stop_loss
                    take_profit = precio_actual + (distancia_riesgo * 2)

                    apalancamiento_recomendado = 10 if mercado["symbol"] == "SPXCUSDT" else 20
                    mensaje_alert = (
                        f"🦈 *CLUB MARKETSHARKS ALERTA EN VIVO*\n\n"
                        f"📊 *Par:* {mercado['nombre']}\n"
                        f"🎯 *Estrategia:* Order Block + EMA 200\n"
                        f"🟢 *Dirección:* COMPRA (Bullish OB Confirmado)\n\n"
                        f"💵 *Precio Entrada:* $ {precio_actual:,.2f} USD\n"
                        f"🛡️ *Stop Loss (SL):* $ {stop_loss:,.2f} USD\n"
                        f"💰 *Take Profit (TP):* $ {take_profit:,.2f} USD\n"
                        f"⚙️ *Apalancamiento recomendado:* {apalancamiento_recomendado}x\n\n"
                        f"📈 *Filtro Trend:* Operación por encima de EMA 200 ($ {ema_200:,.2f})"
                    )
                    ESTADISTICAS["total_senales"] += 1
                    ESTADISTICAS["compras"] += 1
                    OPERACIONES_ABIERTAS.append({
                        "mercado": mercado["nombre"],
                        "tipo": "COMPRA",
                        "entrada": precio_actual,
                        "stop_loss": stop_loss,
                        "take_profit": take_profit,
                        "apalancamiento": 10 if mercado["symbol"] == "SPXCUSDT" else 20,
                        "aviso_10pct": False,
                    })
                    enviar_senal_telegram(mensaje_alert)
                    senal_enviada = True
                    time.sleep(2)

                elif bearish_ob and bearish_sequence and relmove and precio_actual < ema_200:
                    stop_loss = high_ob
                    if stop_loss <= precio_actual or (stop_loss - precio_actual) > 600:
                        stop_loss = precio_actual + 200.00

                    distancia_riesgo = stop_loss - precio_actual
                    take_profit = precio_actual - (distancia_riesgo * 2)

                    apalancamiento_recomendado = 10 if mercado["symbol"] == "SPXCUSDT" else 20
                    mensaje_alert = (
                        f"🦈 *CLUB MARKETSHARKS ALERTA EN VIVO*\n\n"
                        f"📊 *Par:* {mercado['nombre']}\n"
                        f"🎯 *Estrategia:* Order Block + EMA 200\n"
                        f"🔴 *Dirección:* VENTA (Bearish OB Confirmado)\n\n"
                        f"💵 *Precio Entrada:* $ {precio_actual:,.2f} USD\n"
                        f"🛡️ *Stop Loss (SL):* $ {stop_loss:,.2f} USD\n"
                        f"💰 *Take Profit (TP):* $ {take_profit:,.2f} USD\n"
                        f"⚙️ *Apalancamiento recomendado:* {apalancamiento_recomendado}x\n\n"
                        f"📈 *Filtro Trend:* Operación por debajo de EMA 200 ($ {ema_200:,.2f})"
                    )
                    ESTADISTICAS["total_senales"] += 1
                    ESTADISTICAS["ventas"] += 1
                    OPERACIONES_ABIERTAS.append({
                        "mercado": mercado["nombre"],
                        "tipo": "VENTA",
                        "entrada": precio_actual,
                        "stop_loss": stop_loss,
                        "take_profit": take_profit,
                        "apalancamiento": 10 if mercado["symbol"] == "SPXCUSDT" else 20,
                        "aviso_10pct": False,
                    })
                    enviar_senal_telegram(mensaje_alert)
                    senal_enviada = True
                    time.sleep(2)

            if not senal_enviada:
                print("🔍 Escaneo completado. Sin novedades en los Order Blocks. Reintentando en 60 segundos...")
            else:
                print("📊 Se han emitido señales. Se enviará un resumen diario al cierre del día.")

            # Envío diario de resumen a las 00:00 hora local
            if time.strftime("%H:%M") == "00:00" and ESTADISTICAS["ultimo_resumen"] != time.strftime("%Y-%m-%d"):
                enviar_resumen_diario()

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
