import os
import threading
import time
import requests
from datetime import datetime
from zoneinfo import ZoneInfo
from flask import Flask

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
    {"symbol": "SPXUSDT", "interval": "15m", "nombre": "SPXUSDT (15m/1h)", "fallback_intervals": ["1h"], "aliases": ["SPXUSDT"]},
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

# === CONTROL DIARIO DE SEÑALES ===
ESTADO_DIARIO = {
    "fecha": None,
    "senales_hoy": 0,
    "senales_automaticas_hoy": 0,
    "senales_manuales_hoy": 0,
    "minimo_senales_alcanzado": False,
    "minimo_senales_automaticas_alcanzado": False,
}

# === CONTROL DE SOLICITUDES MANUALES ===
SOLICITUDES_MANUALES = {}
ADMINS_CANAL = set()


def es_admin_del_canal(chat_id=None):
    if not chat_id:
        return False
    return str(chat_id) in ADMINS_CANAL

# === CONTROL DE SEÑALES AUTOMÁTICAS ===
AUTO_SIGNAL_ENABLED_VALUE = os.getenv("AUTO_SIGNAL_ENABLED", "true")
AUTO_SIGNAL_ENABLED = AUTO_SIGNAL_ENABLED_VALUE.lower() in {"1", "true", "yes", "on"}
AUTO_SIGNAL_COOLDOWN_SECONDS = int(os.getenv("AUTO_SIGNAL_COOLDOWN_SECONDS", "1800"))
ULTIMA_SENAL_AUTOMATICA = None
DETENER_BOT = threading.Event()


@app.route('/stop')
def stop_bot():
    DETENER_BOT.set()
    return "Bot detenido", 200


def puede_enviar_senal_automatica(forzar=False):
    global ULTIMA_SENAL_AUTOMATICA
    if not AUTO_SIGNAL_ENABLED:
        return False
    if forzar:
        return True
    if ULTIMA_SENAL_AUTOMATICA is None:
        return True
    return (time.time() - ULTIMA_SENAL_AUTOMATICA["timestamp"]) >= AUTO_SIGNAL_COOLDOWN_SECONDS


def limpiar_solicitudes_si_es_necesario():
    global SOLICITUDES_MANUALES
    hoy = hora_espana().strftime("%Y-%m-%d")
    for chat_id in list(SOLICITUDES_MANUALES.keys()):
        if SOLICITUDES_MANUALES[chat_id].get("fecha") != hoy:
            del SOLICITUDES_MANUALES[chat_id]


def hora_espana():
    return datetime.now(ZoneInfo("Europe/Madrid"))


def resetear_estado_diario_si_es_necesario():
    global ESTADO_DIARIO
    hoy = hora_espana().strftime("%Y-%m-%d")
    if ESTADO_DIARIO["fecha"] != hoy:
        ESTADO_DIARIO["fecha"] = hoy
        ESTADO_DIARIO["senales_hoy"] = 0
        ESTADO_DIARIO["senales_automaticas_hoy"] = 0
        ESTADO_DIARIO["senales_manuales_hoy"] = 0
        ESTADO_DIARIO["minimo_senales_alcanzado"] = False
        ESTADO_DIARIO["minimo_senales_automaticas_alcanzado"] = False


def evaluar_noticias_alto_impacto(hora_actual):
    """Contexto de riesgo macro; no bloquea la operación, solo ajusta la fuerza requerida."""
    horas_riesgo = {8, 9, 10, 14, 15, 16}
    if hora_actual.hour in horas_riesgo and hora_actual.minute < 30:
        return "alto", "Ventana de riesgo macro detectada"
    return "bajo", "Sin ventana de riesgo detectada"


def evaluar_fuerza_movimiento(cierres, aperturas, altos, bajos):
    if len(cierres) < 3:
        return 0.0, {"cambio_1": 0.0, "cambio_3": 0.0, "rango_3": 0.0}

    cambio_1 = ((cierres[-1] - cierres[-2]) / cierres[-2]) * 100
    cambio_3 = ((cierres[-1] - cierres[-3]) / cierres[-3]) * 100
    rango_3 = ((max(altos[-3:]) - min(bajos[-3:])) / cierres[-1]) * 100
    fuerza = abs(cambio_1) + abs(cambio_3) + rango_3
    return fuerza, {"cambio_1": cambio_1, "cambio_3": cambio_3, "rango_3": rango_3}


def evaluar_impulso_fuerte(cierres, aperturas, altos, bajos, volumenes, precio_actual, ema_200):
    if len(cierres) < 5:
        return {"detectado": False, "direccion": "NEUTRAL", "motivo": "Datos insuficientes"}

    cambio_1 = ((cierres[-1] - cierres[-2]) / cierres[-2]) * 100
    cambio_3 = ((cierres[-1] - cierres[-3]) / cierres[-3]) * 100
    volumen_actual = volumenes[-1]
    volumen_promedio = sum(volumenes[-3:]) / max(1, len(volumenes[-3:]))
    spike_volumen = volumen_actual / max(volumen_promedio, 1)
    impulso_alza = cambio_1 >= 0.4 and cambio_3 >= 0.4 and spike_volumen >= 1.4 and precio_actual > ema_200
    impulso_baja = cambio_1 <= -0.4 and cambio_3 <= -0.4 and spike_volumen >= 1.4 and precio_actual < ema_200

    if impulso_alza:
        return {"detectado": True, "direccion": "COMPRA", "motivo": f"Impulso fuerte al alza: cambio_1 {cambio_1:.2f}% | volumen {spike_volumen:.2f}x"}
    if impulso_baja:
        return {"detectado": True, "direccion": "VENTA", "motivo": f"Impulso fuerte a la baja: cambio_1 {cambio_1:.2f}% | volumen {spike_volumen:.2f}x"}
    return {"detectado": False, "direccion": "NEUTRAL", "motivo": "Sin impulso fuerte"}


def obtener_datos_binance(symbol, interval, limit=210):
    urls = [
        ("https://api.binance.com/api/v3/klines", {}),
        ("https://api.binance.us/api/v3/klines", {}),
    ]
    symbols = [symbol]
    if symbol == "SPXUSDT":
        symbols.extend(["SPXUSDT"])
    for candidate_symbol in symbols:
        params = {"symbol": candidate_symbol, "interval": interval, "limit": limit}
        for url, extra_params in urls:
            try:
                response = requests.get(url, params={**params, **extra_params}, timeout=10)
                if response.status_code == 200:
                    return response.json()
                print(f"⚠️ {url} devolvió estado {response.status_code} para {candidate_symbol} {interval}: {response.text[:200]}")
            except Exception as e:
                print(f"⚠️ Error consultando {url} para {candidate_symbol} {interval}: {e}")
    return None


def obtener_datos_binance_futuros(symbol, interval, limit=210):
    urls = [
        ("https://fapi.binance.com/fapi/v1/klines", {}),
        ("https://fstream.binance.com/fapi/v1/klines", {}),
    ]
    params = {"symbol": symbol, "interval": interval, "limit": limit}
    for url, extra_params in urls:
        try:
            response = requests.get(url, params={**params, **extra_params}, timeout=10)
            if response.status_code == 200:
                return response.json()
            print(f"⚠️ {url} devolvió estado {response.status_code} para {symbol} {interval}: {response.text[:200]}")
        except Exception as e:
            print(f"⚠️ Error consultando {url} para {symbol} {interval}: {e}")
    return None


def obtener_ticker_24h(symbol):
    urls = [
        ("https://fapi.binance.com/fapi/v1/ticker/24hr", {"symbol": symbol}),
        ("https://api.binance.us/fapi/v1/ticker/24hr", {"symbol": symbol}),
    ]
    for url, params in urls:
        try:
            response = requests.get(url, params=params, timeout=10)
            if response.status_code == 200:
                return response.json()
        except Exception as e:
            print(f"⚠️ Error consultando ticker 24h en {url}: {e}")
    return None


def obtener_funding_rate(symbol):
    urls = [
        ("https://fapi.binance.com/fapi/v1/fundingRate", {"symbol": symbol, "limit": 2}),
        ("https://fstream.binance.com/fapi/v1/fundingRate", {"symbol": symbol, "limit": 2}),
    ]
    for url, params in urls:
        try:
            response = requests.get(url, params=params, timeout=10)
            if response.status_code == 200:
                return response.json()
        except Exception as e:
            print(f"⚠️ Error consultando funding rate en {url}: {e}")
    return None


def evaluar_flujo_capital(precio_actual, ema_200, cierres, volumenes, ticker_24h, funding_rate):
    if len(cierres) < 3:
        return {"direccion": "NEUTRAL", "confianza": 0.0, "motivo": "Datos insuficientes"}

    cambio_1 = ((cierres[-1] - cierres[-2]) / cierres[-2]) * 100
    cambio_3 = ((cierres[-1] - cierres[-3]) / cierres[-3]) * 100
    volumen_actual = volumenes[-1]
    volumen_promedio = sum(volumenes[-3:]) / max(1, len(volumenes[-3:]))
    spike_volumen = volumen_actual / max(volumen_promedio, 1)
    cambio_24h = float(ticker_24h.get("priceChangePercent", 0)) if ticker_24h else 0.0
    funding = float(funding_rate[0].get("fundingRate", 0)) if funding_rate and len(funding_rate) > 0 else 0.0

    score_compra = 0.0
    score_venta = 0.0

    if precio_actual > ema_200:
        score_compra += 1.0
    else:
        score_venta += 1.0
    if cambio_1 > 0.15:
        score_compra += 0.8
    elif cambio_1 < -0.15:
        score_venta += 0.8
    if cambio_3 > 0.3:
        score_compra += 0.8
    elif cambio_3 < -0.3:
        score_venta += 0.8
    if spike_volumen > 1.4:
        score_compra += 0.8 if cambio_24h >= 0 else 0.0
        score_venta += 0.8 if cambio_24h < 0 else 0.0
    if funding > 0.0001:
        score_compra += 0.6
    elif funding < -0.0001:
        score_venta += 0.6
    if cambio_24h > 1.0:
        score_compra += 0.6
    elif cambio_24h < -1.0:
        score_venta += 0.6

    if score_compra > score_venta:
        return {"direccion": "COMPRA", "confianza": round(score_compra - score_venta, 2), "motivo": f"Volumen {spike_volumen:.2f}x | funding {funding:.6f} | 24h {cambio_24h:.2f}%"}
    if score_venta > score_compra:
        return {"direccion": "VENTA", "confianza": round(score_venta - score_compra, 2), "motivo": f"Volumen {spike_volumen:.2f}x | funding {funding:.6f} | 24h {cambio_24h:.2f}%"}
    return {"direccion": "NEUTRAL", "confianza": 0.0, "motivo": f"Volumen {spike_volumen:.2f}x | funding {funding:.6f} | 24h {cambio_24h:.2f}%"}


def detectar_liquidaciones_masivas(cierres, volumenes, ticker_24h, funding_rate):
    """Proxy simple de presión de liquidaciones masivas usando impulso + volumen + funding."""
    if len(cierres) < 3:
        return {"detectado": False, "intensidad": "baja", "motivo": "Datos insuficientes"}

    cambio_1 = ((cierres[-1] - cierres[-2]) / cierres[-2]) * 100
    volumen_actual = volumenes[-1]
    volumen_promedio = sum(volumenes[-3:]) / max(1, len(volumenes[-3:]))
    spike_volumen = volumen_actual / max(volumen_promedio, 1)
    cambio_24h = float(ticker_24h.get("priceChangePercent", 0)) if ticker_24h else 0.0
    funding = float(funding_rate[0].get("fundingRate", 0)) if funding_rate and len(funding_rate) > 0 else 0.0

    if abs(cambio_1) >= 1.2 and spike_volumen >= 1.8 and abs(cambio_24h) >= 1.5:
        intensidad = "alta" if abs(cambio_1) >= 2.0 else "media"
        return {"detectado": True, "intensidad": intensidad, "motivo": f"Impulso {cambio_1:.2f}% | volumen {spike_volumen:.2f}x | funding {funding:.6f}"}
    return {"detectado": False, "intensidad": "baja", "motivo": "Sin presión clara de liquidaciones"}


def calcular_ema_tradingview(precios_cierre, periodo=200):
    if len(precios_cierre) < periodo:
        return None
    sma_inicial = sum(precios_cierre[:periodo]) / periodo
    alpha = 2 / (periodo + 1)
    ema = sma_inicial
    for precio in precios_cierre[periodo:]:
        ema = (precio * alpha) + (ema * (1 - alpha))
    return ema


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


def enviar_senal_telegram(mensaje, chat_id=None, reply_markup=None):
    target_chat = chat_id or CHAT_ID_CANAL
    if not TOKEN_TELEGRAM or not target_chat:
        print("⚠️ Faltan TELEGRAM_TOKEN o TELEGRAM_CHAT_ID en Render")
        return

    url = f"https://api.telegram.org/bot{TOKEN_TELEGRAM}/sendMessage"
    payload = {"chat_id": target_chat, "text": mensaje, "parse_mode": "Markdown"}
    if reply_markup:
        payload["reply_markup"] = reply_markup
    try:
        response = requests.post(url, json=payload, timeout=10)
        response.raise_for_status()
        print("✅ Señal enviada a Telegram")
    except Exception as e:
        print(f"⚠️ Error enviando señal a Telegram: {e}")


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


def construir_mensaje_senal(mercado, direccion, precio_actual, stop_loss, take_profit, ema_200, fuerza, motivo, flujo_btc=None, liquidaciones=None, tipo="normal"):
    flujo_texto = f"\n⚡ *Flujo de capital:* {flujo_btc['direccion']} ({flujo_btc['confianza']:.2f}) | {flujo_btc['motivo']}" if flujo_btc else ""
    liquidacion_texto = f"\n💥 *Liquidaciones/impulso masivo:* {liquidaciones['intensidad']} | {liquidaciones['motivo']}" if liquidaciones and liquidaciones.get("detectado") else ""
    prefijo = "🦈 *SEÑAL MANUAL*" if tipo == "manual" else "🦈 *CLUB MARKETSHARKS ALERTA EN VIVO*"
    tipo_texto = "\n⚠️ *Esta señal fue solicitada manualmente por un miembro y no forma parte de la detección automática principal.*" if tipo == "manual" else ""
    if direccion == "COMPRA":
        direccion_texto = "🟢 *Dirección:* COMPRA"
    else:
        direccion_texto = "🔴 *Dirección:* VENTA"
    return (
        f"{prefijo}\n\n"
        f"{tipo_texto}\n"
        f"📊 *Par:* {mercado['nombre']}\n"
        f"🎯 *Estrategia:* Order Block + Flujo de capital + EMA 200\n"
        f"{direccion_texto}\n\n"
        f"💵 *Precio Entrada:* $ {precio_actual:,.2f} USD\n"
        f"🛡️ *Stop Loss (SL):* $ {stop_loss:,.2f} USD\n"
        f"💰 *Take Profit (TP):* $ {take_profit:,.2f} USD\n"
        f"⚙️ *Apalancamiento recomendado:* {20 if mercado['symbol'] == 'BTCUSDT' else 10}x\n\n"
        f"📈 *EMA 200:* $ {ema_200:,.2f} USD\n"
        f"⚡ *Fuerza movimiento:* {fuerza:.2f}% | *Contexto:* {motivo}{flujo_texto}{liquidacion_texto}"
    )


def generar_senal_para_mercado(mercado, hora_actual, tipo="auto"):
    intervalos = [mercado.get("interval", "15m")]
    if mercado.get("symbol") == "SPXUSDT":
        intervalos = [mercado.get("interval", "15m")] + mercado.get("fallback_intervals", ["1h"])

    for interval in intervalos:
        datos = obtener_datos_binance(mercado["symbol"], interval)
        if not datos:
            continue

        aperturas = [float(vela[1]) for vela in datos]
        altos = [float(vela[2]) for vela in datos]
        bajos = [float(vela[3]) for vela in datos]
        cierres = [float(vela[4]) for vela in datos]
        volumenes = [float(vela[5]) for vela in datos]
        precio_actual = cierres[-1]
        ema_200 = calcular_ema_tradingview(cierres, 200)
        if not ema_200:
            continue

        idx_ob = -6
        vela_ob = datos[idx_ob]
        apertura_ob = float(vela_ob[1])
        cierre_ob = float(vela_ob[4])
        low_ob = float(vela_ob[3])
        high_ob = float(vela_ob[2])

        fuerza, detalle = evaluar_fuerza_movimiento(cierres, aperturas, altos, bajos)
        impulso_fuerte = evaluar_impulso_fuerte(cierres, aperturas, altos, bajos, volumenes, precio_actual, ema_200)
        nivel_noticias, motivo = evaluar_noticias_alto_impacto(hora_actual)
        umbral_fuerza = 1.6 if nivel_noticias == "alto" else 0.8

        flujo_btc = None
        liquidaciones = None
        if mercado["symbol"] == "BTCUSDT":
            datos_futuros = obtener_datos_binance_futuros(mercado["symbol"], interval, 210)
            ticker_24h = obtener_ticker_24h(mercado["symbol"])
            funding_rate = obtener_funding_rate(mercado["symbol"])
            if datos_futuros:
                cierres_futuros = [float(vela[4]) for vela in datos_futuros]
                volumenes_futuros = [float(vela[5]) for vela in datos_futuros]
                flujo_btc = evaluar_flujo_capital(precio_actual, ema_200, cierres_futuros, volumenes_futuros, ticker_24h, funding_rate)
                liquidaciones = detectar_liquidaciones_masivas(cierres_futuros, volumenes_futuros, ticker_24h, funding_rate)

        bullish_ob = cierre_ob < apertura_ob
        bearish_ob = cierre_ob > apertura_ob
        ultimas_5 = list(range(-5, 0))
        bullish_sequence = all(cierres[i] > aperturas[i] for i in ultimas_5)
        bearish_sequence = all(cierres[i] < aperturas[i] for i in ultimas_5)
        absmove = (abs(cierre_ob - precio_actual) / cierre_ob) * 100
        relmove = absmove >= 0.5

        condicion_compra = (
            (bullish_ob and bullish_sequence and relmove and precio_actual > ema_200 and fuerza >= umbral_fuerza)
            or (precio_actual > ema_200 and flujo_btc and flujo_btc["direccion"] == "COMPRA" and flujo_btc["confianza"] >= 1.5)
            or (impulso_fuerte["detectado"] and impulso_fuerte["direccion"] == "COMPRA")
        )
        condicion_venta = (
            (bearish_ob and bearish_sequence and relmove and precio_actual < ema_200 and fuerza >= umbral_fuerza)
            or (precio_actual < ema_200 and flujo_btc and flujo_btc["direccion"] == "VENTA" and flujo_btc["confianza"] >= 1.5)
            or (impulso_fuerte["detectado"] and impulso_fuerte["direccion"] == "VENTA")
        )

        if condicion_compra:
            direccion = "COMPRA"
            stop_loss = low_ob if low_ob < precio_actual else precio_actual - 200.0
            distancia_riesgo = precio_actual - stop_loss
            take_profit = precio_actual + (distancia_riesgo * 2)
        elif condicion_venta:
            direccion = "VENTA"
            stop_loss = high_ob if high_ob > precio_actual else precio_actual + 200.0
            distancia_riesgo = stop_loss - precio_actual
            take_profit = precio_actual - (distancia_riesgo * 2)
        else:
            continue

        mensaje = construir_mensaje_senal(
            mercado=mercado,
            direccion=direccion,
            precio_actual=precio_actual,
            stop_loss=stop_loss,
            take_profit=take_profit,
            ema_200=ema_200,
            fuerza=fuerza,
            motivo=motivo,
            flujo_btc=flujo_btc,
            liquidaciones=liquidaciones,
            tipo=tipo,
        )
        return {
            "mercado": mercado,
            "direccion": direccion,
            "precio_actual": precio_actual,
            "stop_loss": stop_loss,
            "take_profit": take_profit,
            "ema_200": ema_200,
            "mensaje": mensaje,
            "apalancamiento": 20 if mercado["symbol"] == "BTCUSDT" else 10,
            "interval": interval,
        }
    return None


def registrar_senal_emitida(mercado, direccion, precio_actual, stop_loss, take_profit, apalancamiento, tipo="auto"):
    global ESTADISTICAS, ESTADO_DIARIO, ULTIMA_SENAL_AUTOMATICA
    ESTADISTICAS["total_senales"] += 1
    if direccion == "COMPRA":
        ESTADISTICAS["compras"] += 1
    else:
        ESTADISTICAS["ventas"] += 1
    ESTADO_DIARIO["senales_hoy"] += 1
    if tipo == "auto":
        ESTADO_DIARIO["senales_automaticas_hoy"] += 1
        if ESTADO_DIARIO["senales_automaticas_hoy"] >= 2:
            ESTADO_DIARIO["minimo_senales_automaticas_alcanzado"] = True
            ESTADO_DIARIO["minimo_senales_alcanzado"] = True
    else:
        ESTADO_DIARIO["senales_manuales_hoy"] += 1
    OPERACIONES_ABIERTAS.append({
        "mercado": mercado["nombre"],
        "tipo": direccion,
        "entrada": precio_actual,
        "stop_loss": stop_loss,
        "take_profit": take_profit,
        "apalancamiento": apalancamiento,
        "aviso_10pct": False,
    })
    if tipo == "auto":
        ULTIMA_SENAL_AUTOMATICA = {"timestamp": time.time(), "mercado": mercado["nombre"], "direccion": direccion}


def enviar_senal_y_registrar(senal, chat_id=None, tipo="auto"):
    enviar_senal_telegram(senal["mensaje"], chat_id=chat_id)
    registrar_senal_emitida(senal["mercado"], senal["direccion"], senal["precio_actual"], senal["stop_loss"], senal["take_profit"], senal["apalancamiento"], tipo=tipo)


def enviar_boton_solicitud(chat_id=None):
    markup = {"inline_keyboard": [
        [{"text": "BTC manual", "callback_data": "senal_btc"}],
        [{"text": "SPX manual", "callback_data": "senal_spx"}],
    ]}
    mensaje = (
        "🦈 *CLUB MARKETSHARKS*\n\n"
        "Elija el mercado para solicitar una señal manual instantánea.\n\n"
        "⚠️ Aviso importante: esta señal manual NO sustituye la estrategia principal del canal.\n"
        "Los administradores del canal pueden pedir más de 1 señal manual al día.\n"
        "Los miembros normales solo pueden solicitar 1 señal manual por día.\n"
        "La señal manual se asume bajo su propio riesgo y no tiene por qué coincidir con la estrategia principal del bot.\n\n"
        "Si el botón no responde, escribe /senalbtc o /senalspx en este chat para pedirla manualmente."
    )
    enviar_senal_telegram(mensaje, chat_id=chat_id, reply_markup=markup)


def generar_senal_manual(chat_id=None, mercado_seleccionado=None):
    global SOLICITUDES_MANUALES
    limpiar_solicitudes_si_es_necesario()
    if not chat_id:
        return False

    hoy = hora_espana().strftime("%Y-%m-%d")
    if not es_admin_del_canal(chat_id):
        estado = SOLICITUDES_MANUALES.get(chat_id)
        if estado and estado.get("fecha") == hoy and estado.get("usado"):
            mensaje = "🧠 *CLUB MARKETSHARKS*\n\nYa has usado tu solicitud de señal para hoy. Espera a mañana o vuelve a intentarlo más tarde."
            enviar_senal_telegram(mensaje, chat_id=chat_id)
            return False
        SOLICITUDES_MANUALES[chat_id] = {"fecha": hoy, "usado": True}

    mensaje_espera = "🧠 *CLUB MARKETSHARKS*\n\nEl bot está estudiando la mejor señal para ti. Recibirás la señal en 1 minuto."
    enviar_senal_telegram(mensaje_espera, chat_id=chat_id)

    time.sleep(60)

    hora_actual = hora_espana()
    mercados = CONFIGURACIONES_MERCADO
    if mercado_seleccionado == "btc":
        mercados = [m for m in CONFIGURACIONES_MERCADO if m["symbol"] == "BTCUSDT"]
    elif mercado_seleccionado == "spx":
        mercados = [m for m in CONFIGURACIONES_MERCADO if m["symbol"] == "SPXUSDT"]

    for mercado in mercados:
        senal = generar_senal_para_mercado(mercado, hora_actual, tipo="manual")
        if senal:
            enviar_senal_y_registrar(senal, chat_id=chat_id, tipo="manual")
            return True
    mensaje_error = "⚠️ *CLUB MARKETSHARKS*\n\nNo se pudo generar una señal en este momento. Inténtalo de nuevo más tarde."
    enviar_senal_telegram(mensaje_error, chat_id=chat_id)
    return False


def telegram_listener():
    if not TOKEN_TELEGRAM:
        return
    offset = None
    while True:
        try:
            url = f"https://api.telegram.org/bot{TOKEN_TELEGRAM}/getUpdates"
            params = {"timeout": 5}
            if offset is not None:
                params["offset"] = offset
            response = requests.get(url, params=params, timeout=15)
            if response.status_code != 200:
                time.sleep(5)
                continue
            updates = response.json().get("result", [])
            for update in updates:
                offset = update.get("update_id", 0) + 1
                if "message" in update:
                    message = update["message"]
                    chat_id = message.get("chat", {}).get("id")
                    text = (message.get("text") or "").strip().lower()
                    if text in {"/senalahora", "/senal", "/signal", "senalahora", "senal", "signal", "!senal", "!senalahora"}:
                        generar_senal_manual(chat_id=chat_id)
                    if text in {"/senalbtc", "/senalbtc", "senalbtc", "btcmanual"}:
                        generar_senal_manual(chat_id=chat_id, mercado_seleccionado="btc")
                    if text in {"/senalspx", "/senalspx", "senalspx", "spxmanual"}:
                        generar_senal_manual(chat_id=chat_id, mercado_seleccionado="spx")
                if "callback_query" in update:
                    callback = update["callback_query"]
                    chat_id = callback.get("message", {}).get("chat", {}).get("id")
                    data = callback.get("data", "")
                    if data == "senal_btc":
                        answer_url = f"https://api.telegram.org/bot{TOKEN_TELEGRAM}/answerCallbackQuery"
                        requests.post(answer_url, json={"callback_query_id": callback.get("id"), "text": "Generando señal BTC..."}, timeout=10)
                        generar_senal_manual(chat_id=chat_id, mercado_seleccionado="btc")
                    if data == "senal_spx":
                        answer_url = f"https://api.telegram.org/bot{TOKEN_TELEGRAM}/answerCallbackQuery"
                        requests.post(answer_url, json={"callback_query_id": callback.get("id"), "text": "Generando señal SPX..."}, timeout=10)
                        generar_senal_manual(chat_id=chat_id, mercado_seleccionado="spx")
        except Exception as e:
            print(f"⚠️ Error en listener de Telegram: {e}")
        time.sleep(2)


def motor_de_trading():
    print("🚀 Iniciando motor analítico duplicador de TradingView...")
    time.sleep(5)

    alerta_inicio = "🦈 *CLUB MARKETSHARKS*\n\n🤖 Algoritmo de sincronización activado. Escaneando el mercado en vivo clonando la estrategia de TradingView para compra y venta..."
    enviar_senal_telegram(alerta_inicio)
    enviar_boton_solicitud(chat_id=CHAT_ID_CANAL)

    while True:
        try:
            if DETENER_BOT.is_set():
                print("🛑 Bot detenido por petición externa.")
                break

            resetear_estado_diario_si_es_necesario()
            limpiar_solicitudes_si_es_necesario()
            hora_actual = hora_espana()
            senal_enviada = False

            if not AUTO_SIGNAL_ENABLED:
                print("🛑 Señales automáticas desactivadas. Solo se atenderán solicitudes manuales.")
                time.sleep(60)
                continue

            if not puede_enviar_senal_automatica(forzar=not ESTADO_DIARIO["minimo_senales_automaticas_alcanzado"] and ESTADO_DIARIO["senales_automaticas_hoy"] < 2):
                print(f"⏱️ Cooldown activo. Próxima señal automática en {AUTO_SIGNAL_COOLDOWN_SECONDS} segundos.")
                time.sleep(60)
                continue

            for mercado in CONFIGURACIONES_MERCADO:
                if senal_enviada:
                    break
                senal = generar_senal_para_mercado(mercado, hora_actual, tipo="auto")
                if not senal:
                    continue

                if senal["direccion"] == "COMPRA" and senal["precio_actual"] > senal["ema_200"]:
                    enviar_senal_y_registrar(senal, tipo="auto")
                    senal_enviada = True
                    time.sleep(2)
                elif senal["direccion"] == "VENTA" and senal["precio_actual"] < senal["ema_200"]:
                    enviar_senal_y_registrar(senal, tipo="auto")
                    senal_enviada = True
                    time.sleep(2)

            if not ESTADO_DIARIO["minimo_senales_automaticas_alcanzado"] and hora_actual.hour >= 14:
                for mercado in CONFIGURACIONES_MERCADO:
                    if ESTADO_DIARIO["senales_automaticas_hoy"] >= 2:
                        break
                    senal = generar_senal_para_mercado(mercado, hora_actual, tipo="auto")
                    if senal:
                        enviar_senal_y_registrar(senal, tipo="auto")
                        senal_enviada = True
                        time.sleep(2)

            if not senal_enviada:
                print("🔍 Escaneo completado. Sin novedades relevantes. Reintentando en 60 segundos...")
            else:
                print("📊 Se han emitido señales. Se enviará un resumen diario al cierre del día.")

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

    hilo_listener = threading.Thread(target=telegram_listener)
    hilo_listener.daemon = True
    hilo_listener.start()

    puerto = int(os.getenv("PORT", 10000))
    app.run(host='0.0.0.0', port=puerto)
