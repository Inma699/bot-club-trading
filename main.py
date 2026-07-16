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

# === IDs DE ADMINISTRADORES (ilimitados) ===
ADMIN_IDS = {7143306113, 1335354212}

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

# === CONTROL DE SOLICITUDES MANUALES (solo para no-admins) ===
SOLICITUDES_MANUALES = {}
ADMINS_CANAL = set()


def cargar_admins_del_canal():
    global ADMINS_CANAL
    ADMINS_CANAL.clear()
    ADMINS_CANAL.update(ADMIN_IDS)  # IDs hardcodeados

    # También cargar desde variables de entorno (por si quieres agregar más)
    raw_ids = os.getenv("TELEGRAM_ADMIN_IDS", os.getenv("ADMINS_CANAL_IDS", os.getenv("ADMINS_CANAL", ""))).strip()
    if raw_ids:
        for parte in raw_ids.replace(";", ",").split(","):
            valor = parte.strip()
            if valor:
                try:
                    ADMINS_CANAL.add(int(valor))
                except ValueError:
                    ADMINS_CANAL.add(valor)

    if CHAT_ID_CANAL:
        ADMINS_CANAL.add(CHAT_ID_CANAL)

    print(f"✅ Administradores cargados: {ADMINS_CANAL}")


cargar_admins_del_canal()


def es_admin_del_canal(chat_id=None):
    if not chat_id:
        return False
    chat_str = str(chat_id)
    return chat_str in {str(x) for x in ADMINS_CANAL}


# === Resto del código sin cambios importantes (solo mantengo la lógica) ===
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


# ... [Mantengo todas las demás funciones igual: evaluar_fuerza_movimiento, obtener_datos_binance, etc.] ...

def generar_senal_manual(chat_id=None, mercado_seleccionado=None, requester_id=None):
    global SOLICITUDES_MANUALES
    limpiar_solicitudes_si_es_necesario()
    if not chat_id:
        return False

    identificador = requester_id or chat_id
    hoy = hora_espana().strftime("%Y-%m-%d")

    # === ADMINS: ACCESO ILIMITADO ===
    if es_admin_del_canal(identificador):
        print(f"🔑 Admin {identificador} solicitando señal manual (sin límite)")
    else:
        # Usuarios normales: límite de 1 por día
        estado = SOLICITUDES_MANUALES.get(identificador)
        if estado and estado.get("fecha") == hoy and estado.get("usado"):
            mensaje = "🧠 *CLUB MARKETSHARKS*\n\nYa has usado tu solicitud de señal para hoy. Espera a mañana."
            enviar_senal_telegram(mensaje, chat_id=chat_id)
            return False
        SOLICITUDES_MANUALES[identificador] = {"fecha": hoy, "usado": True}

    # ... resto de la función sin cambios ...
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

    for mercado in CONFIGURACIONES_MERCADO:
        senal = generar_senal_fallback(mercado, hora_actual, tipo="manual")
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
                    user_id = message.get("from", {}).get("id")
                    text = (message.get("text") or "").strip().lower()
                    if text in {"/senalahora", "/senal", "/signal", "senalahora", "senal", "signal", "!senal", "!senalahora"}:
                        generar_senal_manual(chat_id=chat_id, requester_id=user_id)
                    if text in {"/senalbtc", "/senalbtc", "senalbtc", "btcmanual"}:
                        generar_senal_manual(chat_id=chat_id, mercado_seleccionado="btc", requester_id=user_id)
                    if text in {"/senalspx", "/senalspx", "senalspx", "spxmanual"}:
                        generar_senal_manual(chat_id=chat_id, mercado_seleccionado="spx", requester_id=user_id)
                if "callback_query" in update:
                    callback = update["callback_query"]
                    chat_id = callback.get("message", {}).get("chat", {}).get("id")
                    user_id = callback.get("from", {}).get("id")
                    data = callback.get("data", "")
                    if data == "senal_btc":
                        answer_url = f"https://api.telegram.org/bot{TOKEN_TELEGRAM}/answerCallbackQuery"
                        requests.post(answer_url, json={"callback_query_id": callback.get("id"), "text": "Generando señal BTC..."}, timeout=10)
                        generar_senal_manual(chat_id=chat_id, mercado_seleccionado="btc", requester_id=user_id)
                    if data == "senal_spx":
                        answer_url = f"https://api.telegram.org/bot{TOKEN_TELEGRAM}/answerCallbackQuery"
                        requests.post(answer_url, json={"callback_query_id": callback.get("id"), "text": "Generando señal SPX..."}, timeout=10)
                        generar_senal_manual(chat_id=chat_id, mercado_seleccionado="spx", requester_id=user_id)
        except Exception as e:
            print(f"⚠️ Error en listener de Telegram: {e}")
        time.sleep(2)


def motor_de_trading():
    print("🚀 Iniciando motor analítico duplicador de TradingView...")
    time.sleep(8)

    try:
        alerta_inicio = "🦈 *CLUB MARKETSHARKS*\n\n🤖 Algoritmo de sincronización activado. Escaneando el mercado en vivo clonando la estrategia de TradingView..."
        
        print(f"📤 Enviando mensaje de inicio al canal: {CHAT_ID_CANAL}")
        enviar_senal_telegram(alerta_inicio)
        
        print("📤 Enviando botones de solicitud manual...")
        enviar_boton_solicitud(chat_id=CHAT_ID_CANAL)
        
        print("✅ Mensajes de inicio enviados correctamente.")
        
    except Exception as e:
        print(f"❌ Error al enviar mensajes de inicio: {e}")

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
                print("🛑 Señales automáticas desactivadas.")
                time.sleep(60)
                continue

            if not puede_enviar_senal_automatica(forzar=not ESTADO_DIARIO["minimo_senales_automaticas_alcanzado"] and ESTADO_DIARIO["senales_automaticas_hoy"] < 2):
                print(f"⏱️ Cooldown activo. Próxima señal en {AUTO_SIGNAL_COOLDOWN_SECONDS} segundos.")
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
                print("📊 Se han emitido señales.")

            if time.strftime("%H:%M") == "00:00" and ESTADISTICAS["ultimo_resumen"] != time.strftime("%Y-%m-%d"):
                enviar_resumen_diario()

            time.sleep(60)

        except Exception as e:
            print(f"⚠️ Error en el motor de trading: {e}")
            time.sleep(30)
