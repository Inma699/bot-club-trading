import os
import threading
import time
import requests
import psycopg2
from datetime import datetime
from zoneinfo import ZoneInfo
from flask import Flask
from telegram import Update, ContextTypes

app = Flask(__name__)

BOT_TELEGRAM_URL = "https://t.me/ClubMSharks_bot"

@app.route('/')
def home():
    return """
    <!doctype html>
    <html lang="es">
    <head>
        <meta charset="utf-8">
        <title>Club MarketSharks</title>
        <style>
            body { font-family: Arial, sans-serif; background: #07111f; color: white; display: flex; align-items: center; justify-content: center; min-height: 100vh; margin: 0; }
            .container { text-align: center; padding: 40px; }
            h1 { margin-bottom: 16px; }
            .btn {
                display: inline-block; text-decoration: none; background: linear-gradient(135deg, #3b82f6, #8b5cf6); color: white;
                padding: 14px 28px; border-radius: 999px; font-weight: bold; font-size: 1.1rem; box-shadow: 0 10px 30px rgba(59,130,246,.35);
            }
        </style>
    </head>
    <body>
        <div class="container">
            <h1>Club MarketSharks</h1>
            <p>Algoritmo Espejo TradingView Activo</p>
            <a class="btn" href="https://t.me/ClubMSharks_bot" target="_blank" rel="noopener noreferrer">Join Us Now</a>
        </div>
    </body>
    </html>
    """, 200

# === CREDENCIALES DESDE ENVIRONMENT VARIABLES ===
TOKEN_TELEGRAM = os.getenv("TELEGRAM_TOKEN", "").strip()
CHAT_ID_CANAL = os.getenv("TELEGRAM_CHAT_ID", "").strip()
DATABASE_URL = os.getenv("DATABASE_URL", "").strip()

# === CONFIGURACIÓN DE MERCADOS ===
CONFIGURACIONES_MERCADO = [
    {"symbol": "BTCUSDT", "interval": "15m", "nombre": "BTCUSDT (15m)"},
    {"symbol": "SPCXUSDT", "interval": "15m", "nombre": "SPCXUSDT (Bitget 15m/1h)", "fallback_intervals": ["1h"], "aliases": ["SPCXUSDT"]},
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


def cargar_admins_del_canal():
    global ADMINS_CANAL
    raw_ids = os.getenv("TELEGRAM_ADMIN_IDS", os.getenv("ADMINS_CANAL_IDS", os.getenv("ADMINS_CANAL", ""))).strip()
    ids = set()
    if raw_ids:
        for parte in raw_ids.replace(";", ",").split(","):
            valor = parte.strip()
            if valor:
                ids.add(valor)
    if CHAT_ID_CANAL:
        ids.add(CHAT_ID_CANAL)
    ADMINS_CANAL = {str(item) for item in ids}


cargar_admins_del_canal()
# Añadir admin fijo para Inma (@Diamond_DeltaHz) — permisos ilimitados de señales manuales
ADMINS_CANAL.add("1335354212")


def es_admin_del_canal(chat_id=None):
    if not chat_id:
        return False
    return str(chat_id) in ADMINS_CANAL


def get_db_connection():
    if not DATABASE_URL:
        return None
    try:
        conn = psycopg2.connect(DATABASE_URL)
        conn.autocommit = True
        return conn
    except Exception as e:
        print(f"❌ Error conectando a PostgreSQL: {e}")
        return None


def guardar_usuario_db(user_id):
    user_id = int(user_id)
    conn = get_db_connection()
    if not conn:
        return False
    try:
        with conn.cursor() as cur:
            cur.execute("""
                CREATE TABLE IF NOT EXISTS telegram_users (
                    user_id BIGINT PRIMARY KEY,
                    created_at TIMESTAMPTZ DEFAULT NOW()
                );
            """)
            cur.execute("""
                INSERT INTO telegram_users (user_id)
                VALUES (%s)
                ON CONFLICT (user_id) DO NOTHING;
            """, (user_id,))
        return True
    except Exception as e:
        print(f"❌ Error guardando usuario en DB: {e}")
        return False
    finally:
        conn.close()


def obtener_ids_telegram_db():
    conn = get_db_connection()
    if not conn:
        return []
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT user_id FROM telegram_users ORDER BY created_at ASC;")
            return [str(row[0]) for row in cur.fetchall()]
    except Exception as e:
        print(f"❌ Error leyendo usuarios de DB: {e}")
        return []
    finally:
        conn.close()


def enviar_senal_a_canal_y_usuarios(mensaje):
    # 1) Canal principal
    enviar_senal_telegram(mensaje, chat_id=TELEGRAM_CHAT_ID)

    # 2) Privados de la base de datos
    for user_id in obtener_ids_telegram_db():
        try:
            enviar_senal_telegram(mensaje, chat_id=user_id)
        except Exception:
            pass


def enviar_senal_telegram(mensaje, chat_id=None):
    target_chat = chat_id or TELEGRAM_CHAT_ID
    if not TOKEN_TELEGRAM or not target_chat:
        return

    url = f"https://api.telegram.org/bot{TOKEN_TELEGRAM}/sendMessage"
    payload = {"chat_id": target_chat, "text": mensaje}

    try:
        response = requests.post(url, json=payload, timeout=10)
        response.raise_for_status()
    except Exception as e:
        print(f"⚠️ Error enviando a {target_chat}: {e}")


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


def generar_senal_fallback(mercado, hora_actual, tipo="manual"):
    intervalos = [mercado.get("interval", "15m")]
    if mercado.get("symbol") == "SPCXUSDT":
        intervalos = [mercado.get("interval", "15m")] + mercado.get("fallback_intervals", ["1h"]) 

    for interval in intervalos:
        datos = obtener_datos_binance(mercado["symbol"], interval)
        if not datos:
            continue

        cierres = [float(vela[4]) for vela in datos]
        aperturas = [float(vela[1]) for vela in datos]
        altos = [float(vela[2]) for vela in datos]
        bajos = [float(vela[3]) for vela in datos]
        volumenes = [float(vela[5]) for vela in datos]
        precio_actual = cierres[-1]
        ema_200 = calcular_ema_tradingview(cierres, 200)
        if not ema_200:
            continue

        fuerzas, detalle = evaluar_fuerza_movimiento(cierres, aperturas, altos, bajos)
        cambio_1 = ((cierres[-1] - cierres[-2]) / cierres[-2]) * 100 if len(cierres) >= 2 else 0.0
        cambio_3 = ((cierres[-1] - cierres[-3]) / cierres[-3]) * 100 if len(cierres) >= 3 else 0.0

        if precio_actual > ema_200 and (cambio_1 >= -0.1 or cambio_3 >= -0.2):
            direccion = "COMPRA"
            stop_loss = min(bajos[-3:]) if len(bajos) >= 3 else precio_actual - 1.0
            distancia_riesgo = max(precio_actual - stop_loss, 1.0)
            take_profit = precio_actual + (distancia_riesgo * 2)
        else:
            direccion = "VENTA"
            stop_loss = max(altos[-3:]) if len(altos) >= 3 else precio_actual + 1.0
            distancia_riesgo = max(stop_loss - precio_actual, 1.0)
            take_profit = precio_actual - (distancia_riesgo * 2)

        motivo = f"Señal manual de respaldo | cambio_1 {cambio_1:.2f}% | EMA 200 {ema_200:.2f}"
        mensaje = construir_mensaje_senal(
            mercado=mercado,
            direccion=direccion,
            precio_actual=precio_actual,
            stop_loss=stop_loss,
            take_profit=take_profit,
            ema_200=ema_200,
            fuerza=max(fuerzas, 0.0),
            motivo=motivo,
            flujo_btc=None,
            liquidaciones=None,
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

    if mercado["symbol"] == "SPCXUSDT":
        precio_directo = obtener_precio_spcx()
        if precio_directo is not None:
            stop_loss = max(precio_directo * 0.98, precio_directo - 1.0)
            distancia_riesgo = max(precio_directo - stop_loss, 1.0)
            take_profit = precio_directo + (distancia_riesgo * 2)
            motivo = "Señal manual de respaldo para SPCX usando precio directo de Bitget/alternativa externa."
            mensaje = construir_mensaje_senal(
                mercado=mercado,
                direccion="COMPRA",
                precio_actual=precio_directo,
                stop_loss=stop_loss,
                take_profit=take_profit,
                ema_200=precio_directo,
                fuerza=0.0,
                motivo=motivo,
                flujo_btc=None,
                liquidaciones=None,
                tipo=tipo,
            )
            return {
                "mercado": mercado,
                "direccion": "COMPRA",
                "precio_actual": precio_directo,
                "stop_loss": stop_loss,
                "take_profit": take_profit,
                "ema_200": precio_directo,
                "mensaje": mensaje,
                "apalancamiento": 10,
                "interval": mercado.get("interval", "15m"),
            }

    return None


def generar_senal_para_mercado(mercado, hora_actual, tipo="auto"):
    intervalos = [mercado.get("interval", "15m")]
    if mercado.get("symbol") == "SPCXUSDT":
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
    enviar_senal_a_usuarios_db(senal["mensaje"])
    registrar_senal_emitida(senal["mercado"], senal["direccion"], senal["precio_actual"], senal["stop_loss"], senal["take_profit"], senal["apalancamiento"], tipo=tipo)


def enviar_boton_solicitud(chat_id=None):
    estado_auto = "ON" if AUTO_SIGNAL_ENABLED else "OFF"
    markup = {"inline_keyboard": [
        [{"text": "BTC manual", "callback_data": "senal_btc"}],
        [{"text": "SPCX manual", "callback_data": "senal_spcx"}],
        [{"text": f"Automáticas: {estado_auto}", "callback_data": "toggle_auto"}],
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


def generar_senal_manual(chat_id=None, mercado_seleccionado=None, requester_id=None):
    global SOLICITUDES_MANUALES
    limpiar_solicitudes_si_es_necesario()
    if not chat_id:
        return False
    hoy = hora_espana().strftime("%Y-%m-%d")
    identificador = requester_id or chat_id
    print(f"📨 Solicitud manual recibida. chat_id={chat_id} requester_id={requester_id} identificador={identificador}")

    # confirmar recepción al solicitante (si conocemos requester_id)
    if requester_id:
        ok, status, text = enviar_senal_telegram("📨 Recibida tu solicitud, generando señal...", chat_id=requester_id)
        if not ok and status == 403:
            print(f"⚠️ No se puede DM al requester {requester_id} (403). Notificando en canal.")
            enviar_senal_telegram(f"⚠️ No pude enviar DM al solicitante (ID {requester_id}). La señal se publicará en este canal.", chat_id=chat_id)

    if not es_admin_del_canal(identificador):
        estado = SOLICITUDES_MANUALES.get(identificador)
        if estado and estado.get("fecha") == hoy and estado.get("usado"):
            mensaje = "🧠 *CLUB MARKETSHARKS*\n\nYa has usado tu solicitud de señal para hoy. Espera a mañana o vuelve a intentarlo más tarde."
            enviar_senal_telegram(mensaje, chat_id=chat_id)
            if requester_id:
                ok2, status2, _ = enviar_senal_telegram("⚠️ Tu solicitud fue rechazada: ya usaste la de hoy.", chat_id=requester_id)
                if not ok2 and status2 == 403:
                    enviar_senal_telegram(f"⚠️ No pude enviar DM al solicitante (ID {requester_id}) sobre la limitación diaria.", chat_id=chat_id)
            return False
        SOLICITUDES_MANUALES[identificador] = {"fecha": hoy, "usado": True}

    hora_actual = hora_espana()
    mercados = CONFIGURACIONES_MERCADO
    if mercado_seleccionado == "btc":
        mercados = [m for m in CONFIGURACIONES_MERCADO if m["symbol"] == "BTCUSDT"]
    elif mercado_seleccionado in {"spx", "spcx"}:
        mercados = [m for m in CONFIGURACIONES_MERCADO if m["symbol"] == "SPCXUSDT"]

    for mercado in mercados:
        senal = generar_senal_para_mercado(mercado, hora_actual, tipo="manual")
        if not senal:
            senal = generar_senal_fallback(mercado, hora_actual, tipo="manual")
        if senal:
            enviar_senal_y_registrar(senal, chat_id=chat_id, tipo="manual")
            print(f"✅ Señal generada y enviada. destino_chat={chat_id} remitente={requester_id}")
            if requester_id:
                ok3, status3, _ = enviar_senal_telegram("✅ Señal generada y enviada. Comprueba el chat donde la solicitaste.", chat_id=requester_id)
                if not ok3 and status3 == 403:
                    enviar_senal_telegram(f"⚠️ No pude enviar DM al solicitante (ID {requester_id}); la señal fue publicada en este canal.", chat_id=chat_id)
            return True

    # Si se solicitó un mercado específico, no probamos otros mercados distintos.
    if mercado_seleccionado in {"btc", "spx", "spcx"}:
        mensaje_error = (
            "⚠️ *CLUB MARKETSHARKS*\n\n"
            "No se pudo generar una señal para el mercado solicitado en este momento. Inténtalo de nuevo más tarde."
        )
        enviar_senal_telegram(mensaje_error, chat_id=chat_id)
        return False

    for mercado in CONFIGURACIONES_MERCADO:
        senal = generar_senal_fallback(mercado, hora_actual, tipo="manual")
        if senal:
            enviar_senal_y_registrar(senal, chat_id=chat_id, tipo="manual")
            print(f"✅ Señal fallback generada y enviada. destino_chat={chat_id} remitente={requester_id}")
            if requester_id:
                ok4, status4, _ = enviar_senal_telegram("✅ Señal de respaldo generada y enviada. Comprueba el chat donde la solicitaste.", chat_id=requester_id)
                if not ok4 and status4 == 403:
                    enviar_senal_telegram(f"⚠️ No pude enviar DM al solicitante (ID {requester_id}); la señal de respaldo fue publicada en este canal.", chat_id=chat_id)
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
                    user = message.get("from", {})
                    user_id = user.get("id")
                    username = user.get("username")
                    first_name = user.get("first_name")
                    text = (message.get("text") or "").strip().lower()

                    if text == "/start":
                        guardar_usuario_db(user_id)
                        welcome = (
                            "🦈 ¡Bienvenido a Club MarketSharks!\n\n"
                            "Tu registro quedó guardado y ya recibirás las señales por chat privado.\n\n"
                            "Pulsa el botón o escribe /senalbtc o /senalspx para pedir una señal manual."
                        )
                        enviar_senal_telegram(welcome, chat_id=user_id)

                    if text in {"/senalahora", "/senal", "/signal", "senalahora", "senal", "signal", "!senal", "!senalahora"}:
                        generar_senal_manual(chat_id=chat_id, requester_id=user_id)
                    if text in {"/senalbtc", "/senalbtc", "senalbtc", "btcmanual"}:
                        generar_senal_manual(chat_id=chat_id, mercado_seleccionado="btc", requester_id=user_id)
                    if text in {"/senalspx", "/senalspcx", "senalspx", "senalspcx", "spxmanual", "spcxmanual"}:
                        generar_senal_manual(chat_id=chat_id, mercado_seleccionado="spcx", requester_id=user_id)
                if "callback_query" in update:
                    callback = update["callback_query"]
                    chat_id = callback.get("message", {}).get("chat", {}).get("id")
                    user_id = callback.get("from", {}).get("id")
                    data = callback.get("data", "")
                    if data == "senal_btc":
                        answer_url = f"https://api.telegram.org/bot{TOKEN_TELEGRAM}/answerCallbackQuery"
                        requests.post(answer_url, json={"callback_query_id": callback.get("id"), "text": "Generando señal BTC..."}, timeout=10)
                        generar_senal_manual(chat_id=chat_id, mercado_seleccionado="btc", requester_id=user_id)
                    if data == "senal_spcx":
                        answer_url = f"https://api.telegram.org/bot{TOKEN_TELEGRAM}/answerCallbackQuery"
                        requests.post(answer_url, json={"callback_query_id": callback.get("id"), "text": "Generando señal SPCX..."}, timeout=10)
                        generar_senal_manual(chat_id=chat_id, mercado_seleccionado="spcx", requester_id=user_id)
                    if data == "toggle_auto":
                        # Solo admins pueden togglear
                        if not es_admin_del_canal(user_id):
                            answer_url = f"https://api.telegram.org/bot{TOKEN_TELEGRAM}/answerCallbackQuery"
                            requests.post(answer_url, json={"callback_query_id": callback.get("id"), "text": "Solo administradores pueden cambiar el estado de automáticas."}, timeout=10)
                        else:
                            # Alternar
                            global AUTO_SIGNAL_ENABLED
                            AUTO_SIGNAL_ENABLED = not AUTO_SIGNAL_ENABLED
                            nuevo_estado = "activadas" if AUTO_SIGNAL_ENABLED else "desactivadas"
                            requests.post(f"https://api.telegram.org/bot{TOKEN_TELEGRAM}/answerCallbackQuery", json={"callback_query_id": callback.get("id"), "text": f"Automáticas {nuevo_estado}."}, timeout=10)
                            enviar_senal_telegram(f"⚙️ Señales automáticas ahora *{nuevo_estado}* por petición del admin {user_id}.", chat_id=CHAT_ID_CANAL)
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
                    # Intentar fallback automático cuando el análisis principal no devuelve señal
                    print(f"ℹ️ No se generó señal principal para {mercado['symbol']}. Intentando fallback automático...")
                    senal = generar_senal_fallback(mercado, hora_actual, tipo="auto")
                    if senal:
                        print(f"ℹ️ Se generó señal de fallback automático para {mercado['symbol']}")
                    else:
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
