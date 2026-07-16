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

# === CREDENCIALES ===
TOKEN_TELEGRAM = os.getenv("TELEGRAM_TOKEN", "").strip()
CHAT_ID_CANAL = os.getenv("TELEGRAM_CHAT_ID", "").strip()

# === ADMINISTRADORES (ILIMITADOS) ===
ADMIN_IDS = {7143306113, 1335354212}

# === CONFIGURACIÓN DE MERCADOS ===
CONFIGURACIONES_MERCADO = [
    {"symbol": "BTCUSDT", "interval": "15m", "nombre": "BTCUSDT (15m)"},
    {"symbol": "SPXUSDT", "interval": "15m", "nombre": "SPXUSDT (15m/1h)", "fallback_intervals": ["1h"]},
]

# === ESTADÍSTICAS Y CONTROLES ===
ESTADISTICAS = {
    "total_senales": 0, "compras": 0, "ventas": 0, "ganadas": 0, "perdidas": 0, "ultimo_resumen": None
}

OPERACIONES_ABIERTAS = []
ESTADO_DIARIO = {
    "fecha": None, "senales_hoy": 0, "senales_automaticas_hoy": 0,
    "senales_manuales_hoy": 0, "minimo_senales_alcanzado": False,
    "minimo_senales_automaticas_alcanzado": False
}

SOLICITUDES_MANUALES = {}
ADMINS_CANAL = set()


def cargar_admins_del_canal():
    global ADMINS_CANAL
    ADMINS_CANAL.clear()
    ADMINS_CANAL.update(ADMIN_IDS)
    raw_ids = os.getenv("TELEGRAM_ADMIN_IDS", "").strip()
    if raw_ids:
        for parte in raw_ids.replace(";", ",").split(","):
            if parte.strip():
                ADMINS_CANAL.add(parte.strip())
    if CHAT_ID_CANAL:
        ADMINS_CANAL.add(CHAT_ID_CANAL)
    print(f"✅ Administradores cargados: {ADMINS_CANAL}")


cargar_admins_del_canal()


def es_admin_del_canal(chat_id=None):
    if not chat_id:
        return False
    return str(chat_id) in {str(x) for x in ADMINS_CANAL}


AUTO_SIGNAL_ENABLED = os.getenv("AUTO_SIGNAL_ENABLED", "true").lower() in {"1", "true", "yes", "on"}
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
    if forzar or ULTIMA_SENAL_AUTOMATICA is None:
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


def enviar_senal_telegram(mensaje, chat_id=None, reply_markup=None):
    target_chat = chat_id or CHAT_ID_CANAL
    if not TOKEN_TELEGRAM or not target_chat:
        print("⚠️ Faltan TELEGRAM_TOKEN o CHAT_ID_CANAL")
        return
    url = f"https://api.telegram.org/bot{TOKEN_TELEGRAM}/sendMessage"
    payload = {"chat_id": target_chat, "text": mensaje, "parse_mode": "Markdown"}
    if reply_markup:
        payload["reply_markup"] = reply_markup
    try:
        response = requests.post(url, json=payload, timeout=10)
        if response.status_code == 200:
            print("✅ Mensaje enviado a Telegram")
        else:
            print(f"❌ Error Telegram {response.status_code}: {response.text[:200]}")
    except Exception as e:
        print(f"❌ Excepción enviando a Telegram: {e}")


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
    
    direccion_texto = "🟢 *Dirección:* COMPRA" if direccion == "COMPRA" else "🔴 *Dirección:* VENTA"
    
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
    if mercado.get("symbol") == "SPXUSDT":
        intervalos = [mercado.get("interval", "15m")] + mercado.get("fallback_intervals", ["1h"])

    for interval in intervalos:
        datos = obtener_datos_binance(mercado["symbol"], interval)
        if not datos:
            continue

        cierres = [float(vela[4]) for vela in datos]
        aperturas = [float(vela[1]) for vela in datos]
        altos = [float(vela[2]) for vela in datos]
        bajos = [float(vela[3]) for vela in datos]
        precio_actual = cierres[-1]
        ema_200 = calcular_ema_tradingview(cierres, 200)
        if not ema_200:
            continue

        fuerzas, _ = evaluar_fuerza_movimiento(cierres, aperturas, altos, bajos)
        cambio_1 = ((cierres[-1] - cierres[-2]) / cierres[-2]) * 100 if len(cierres) >= 2 else 0.0

        if precio_actual > ema_200 and (cambio_1 >= -0.1):
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
        mensaje = construir_mensaje_senal(mercado, direccion, precio_actual, stop_loss, take_profit, ema_200, max(fuerzas, 0.0), motivo, tipo=tipo)
        
        return {
            "mercado": mercado, "direccion": direccion, "precio_actual": precio_actual,
            "stop_loss": stop_loss, "take_profit": take_profit, "ema_200": ema_200,
            "mensaje": mensaje, "apalancamiento": 20 if mercado["symbol"] == "BTCUSDT" else 10
        }
    return None


def generar_senal_manual(chat_id=None, mercado_seleccionado=None, requester_id=None):
    global SOLICITUDES_MANUALES
    limpiar_solicitudes_si_es_necesario()
    if not chat_id:
        return False

    identificador = requester_id or chat_id
    hoy = hora_espana().strftime("%Y-%m-%d")

    # Admins tienen acceso ilimitado
    if not es_admin_del_canal(identificador):
        estado = SOLICITUDES_MANUALES.get(identificador)
        if estado and estado.get("fecha") == hoy and estado.get("usado"):
            enviar_senal_telegram("🧠 *CLUB MARKETSHARKS*\n\nYa has usado tu solicitud de señal para hoy.", chat_id=chat_id)
            return False
        SOLICITUDES_MANUALES[identificador] = {"fecha": hoy, "usado": True}

    # Resto de la lógica de generación de señal manual...
    hora_actual = hora_espana()
    mercados = CONFIGURACIONES_MERCADO
    if mercado_seleccionado == "btc":
        mercados = [m for m in CONFIGURACIONES_MERCADO if m["symbol"] == "BTCUSDT"]
    elif mercado_seleccionado == "spx":
        mercados = [m for m in CONFIGURACIONES_MERCADO if m["symbol"] == "SPXUSDT"]

    for mercado in mercados:
        senal = generar_senal_para_mercado(mercado, hora_actual, tipo="manual")
        if not senal:
            senal = generar_senal_fallback(mercado, hora_actual, tipo="manual")
        if senal:
            enviar_senal_y_registrar(senal, chat_id=chat_id, tipo="manual")
            return True

    enviar_senal_telegram("⚠️ No se pudo generar señal en este momento.", chat_id=chat_id)
    return False
    def telegram_listener():
    if not TOKEN_TELEGRAM:
        print("⚠️ TELEGRAM_TOKEN no configurado, listener desactivado.")
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
                    user_id = message.get("from", {}).get("id")
                    text = (message.get("text") or "").strip().lower()
                    if text in {"/senalahora", "/senal", "/signal", "senal", "signal"}:
                        generar_senal_manual(chat_id=chat_id, requester_id=user_id)
                    if text in {"/senalbtc", "senalbtc"}:
                        generar_senal_manual(chat_id=chat_id, mercado_seleccionado="btc", requester_id=user_id)
                    if text in {"/senalspx", "senalspx"}:
                        generar_senal_manual(chat_id=chat_id, mercado_seleccionado="spx", requester_id=user_id)
                if "callback_query" in update:
                    callback = update["callback_query"]
                    chat_id = callback.get("message", {}).get("chat", {}).get("id")
                    user_id = callback.get("from", {}).get("id")
                    data = callback.get("data", "")
                    if data == "senal_btc":
                        generar_senal_manual(chat_id=chat_id, mercado_seleccionado="btc", requester_id=user_id)
                    if data == "senal_spx":
                        generar_senal_manual(chat_id=chat_id, mercado_seleccionado="spx", requester_id=user_id)
        except Exception as e:
            print(f"⚠️ Error en listener: {e}")
        time.sleep(2)


def motor_de_trading():
    print("🚀 Iniciando motor analítico duplicador de TradingView...")
    time.sleep(8)

    try:
        alerta_inicio = "🦈 *CLUB MARKETSHARKS*\n\n🤖 Algoritmo de sincronización activado. Escaneando el mercado en vivo..."
        enviar_senal_telegram(alerta_inicio)
        enviar_boton_solicitud(chat_id=CHAT_ID_CANAL)
        print("✅ Mensaje de inicio y botones enviados.")
    except Exception as e:
        print(f"❌ Error enviando mensaje inicial: {e}")

    while True:
        try:
            if DETENER_BOT.is_set():
                print("🛑 Bot detenido.")
                break

            resetear_estado_diario_si_es_necesario()
            limpiar_solicitudes_si_es_necesario()
            hora_actual = hora_espana()
            senal_enviada = False

            if not AUTO_SIGNAL_ENABLED:
                time.sleep(60)
                continue

            if not puede_enviar_senal_automatica():
                time.sleep(60)
                continue

            for mercado in CONFIGURACIONES_MERCADO:
                if senal_enviada:
                    break
                senal = generar_senal_para_mercado(mercado, hora_actual, tipo="auto")
                if senal and ((senal["direccion"] == "COMPRA" and senal["precio_actual"] > senal["ema_200"]) or
                              (senal["direccion"] == "VENTA" and senal["precio_actual"] < senal["ema_200"])):
                    enviar_senal_y_registrar(senal, tipo="auto")
                    senal_enviada = True

            if not senal_enviada:
                print("🔍 Escaneo completado. Sin novedades relevantes. Reintentando en 60 segundos...")
            time.sleep(60)

        except Exception as e:
            print(f"⚠️ Error en motor: {e}")
            time.sleep(30)


if __name__ == '__main__':
    print("🚀 Bot iniciado en Render")
    hilo_trading = threading.Thread(target=motor_de_trading, daemon=True)
    hilo_trading.start()

    hilo_listener = threading.Thread(target=telegram_listener, daemon=True)
    hilo_listener.start()

    puerto = int(os.getenv("PORT", 10000))
    app.run(host='0.0.0.0', port=puerto)
