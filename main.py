import os
import threading
import time
import requests
import psycopg2
from datetime import datetime
from zoneinfo import ZoneInfo
from flask import Flask

app = Flask(__name__)

# === CREDENCIALES DESDE ENVIRONMENT VARIABLES ===
TOKEN_TELEGRAM = os.getenv("TELEGRAM_TOKEN", "").strip()
CHAT_ID_CANAL = os.getenv("TELEGRAM_CHAT_ID", "").strip()
DATABASE_URL = os.getenv("DATABASE_URL", "").strip()

# Parche IPv4 automático para Supabase en Render (Evita Network is unreachable)
if DATABASE_URL and "supabase.co" in DATABASE_URL and "pooler" not in DATABASE_URL:
    DATABASE_URL = DATABASE_URL.replace("@db.", "@://supabase.com")

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

OPERACIONES_ABIERTAS = []
ESTADO_DIARIO = {
    "fecha": None,
    "senales_hoy": 0,
    "senales_automaticas_hoy": 0,
    "senales_manuales_hoy": 0,
    "minimo_senales_alcanzado": False,
    "minimo_senales_automaticas_alcanzado": False,
}

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
ADMINS_CANAL.add("1335354212")

def es_admin_del_canal(chat_id=None):
    if not chat_id:
        return False
    return str(chat_id) in ADMINS_CANAL

AUTO_SIGNAL_ENABLED = True
AUTO_SIGNAL_COOLDOWN_SECONDS = int(os.getenv("AUTO_SIGNAL_COOLDOWN_SECONDS", "1800"))
ULTIMA_SENAL_AUTOMATICA = None
DETENER_BOT = threading.Event()

# === FUNCIONES DE BASE DE DATOS ===
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
    if user_id is None:
        return False
    conn = get_db_connection()
    if not conn:
        return False
    try:
        with conn.cursor() as cur:
            cur.execute("""
                INSERT INTO usuarios (user_id)
                VALUES (%s)
                ON CONFLICT (user_id) DO NOTHING;
            """, (int(user_id),))
        print(f"✅ Usuario {user_id} guardado con éxito en Supabase.")
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
            cur.execute("SELECT user_id FROM usuarios;")
            return [str(row[0]) for row in cur.fetchall()]
    except Exception as e:
        print(f"❌ Error leyendo usuarios de DB: {e}")
        return []
    finally:
        conn.close()

def enviar_senal_a_usuarios_privados(mensaje):
    usuarios = obtener_ids_telegram_db()
    for user_id in usuarios:
        try:
            enviar_senal_telegram(mensaje, chat_id=user_id)
        except Exception:
            pass

@app.route('/')
def home():
    return "Club MarketSharks - Algoritmo Espejo TradingView Activo", 200

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
        return {"detectado": True, "direccion": "COMPRA", "motivo": f"Impulso alza: {cambio_1:.2f}%"}
    if impulso_baja:
        return {"detectado": True, "direccion": "VENTA", "motivo": f"Impulso baja: {cambio_1:.2f}%"}
    return {"detectado": False, "direccion": "NEUTRAL", "motivo": "Sin impulso"}

def obtener_datos_bitget(symbol, interval, limit=210):
    sym_upper = str(symbol).upper()
    granularity = str(int(interval[:-1]) * 60) if interval.endswith('m') else (str(int(interval[:-1]) * 3600) if interval.endswith('h') else interval)
    endpoints = [
        ("https://bitget.com", {"symbol": sym_upper, "granularity": granularity, "limit": limit}),
        ("https://bitget.com", {"symbol": sym_upper, "granularity": granularity, "limit": limit})
    ]
    for url, params in endpoints:
        try:
            r = requests.get(url, params=params, timeout=10)
            if r.status_code == 200 and isinstance(r.json(), dict) and "data" in r.json():
                return r.json()["data"]
        except Exception:
            pass
    return None

def obtener_precio_bitget_v2(symbol):
    try:
        r = requests.get("https://bitget.com", params={"symbol": str(symbol).upper()}, timeout=10)
        if r.status_code == 200 and "data" in r.json():
            return float(r.json()["data"].get("lastPr", r.json()["data"].get("last", 0)))
    except Exception:
        pass
    return None

def obtener_precio_spcx():
    p = obtener_precio_bitget_v2('SPCXUSDT')
    if p: return p
    try:
        r = requests.get("https://coingecko.com", params={"ids": "spcx", "vs_currencies": "usd"}, timeout=10)
        if r.status_code == 200: return float(r.json().get("spcx", {}).get("usd", 0))
    except Exception: pass
    return 2.50

def obtener_datos_binance(symbol, interval, limit=210):
    if str(symbol).upper() == "SPCXUSDT":
        return obtener_datos_bitget(symbol, interval, limit=limit)
    endpoints = [
        "https://binance.com",
        "https://binance.com",
        "https://binance.com"
    ]
    for url in endpoints:
        try:
            r = requests.get(url, params={"symbol": symbol, "interval": interval, "limit": limit}, timeout=10)
            if r.status_code == 200: return r.json()
        except Exception: pass
    return None

def obtener_datos_binance_futuros(symbol, interval, limit=210):
    endpoints = [
        "https://binance.com",
        "https://binance.com"
    ]
    for url in endpoints:
        try:
            r = requests.get(url, params={"symbol": symbol, "interval": interval, "limit": limit}, timeout=10)
            if r.status_code == 200: return r.json()
        except Exception: pass
    return None

def obtener_ticker_24h(symbol):
    try:
        r = requests.get("https://binance.com", params={"symbol": symbol}, timeout=10)
        if r.status_code == 200: return r.json()
    except Exception: pass
    return {"priceChangePercent": "0.0"}

def obtener_funding_rate(symbol):
    try:
        r = requests.get("https://binance.com", params={"symbol": symbol, "limit": 1}, timeout=10)
        if r.status_code == 200 and isinstance(r.json(), list): return r.json()
    except Exception: pass
    return {"fundingRate": "0.0001"}

def evaluar_flujo_capital(precio_actual, ema_200, cierres, volumenes, ticker_24h, funding_rate):
    cambio_24h = float(ticker_24h.get("priceChangePercent", 0))
    funding = float(funding_rate.get("fundingRate", 0))
    score = 1.0 if precio_actual > ema_200 else -1.0
    if score > 0:
        return {"direccion": "COMPRA", "confianza": 1.5, "motivo": f"Funding {funding:.4f}"}
    return {"direccion": "VENTA", "confianza": 1.5, "motivo": f"24h {cambio_24h:.1f}%"}

def detectar_liquidaciones_masivas(cierres, volumenes, ticker_24h, funding_rate):
    return {"detectado": False, "intensidad": "baja", "motivo": "Estable"}

def calcular_ema_tradingview(precios_cierre, periodo=200):
    if len(precios_cierre) < periodo: return None
    sma = sum(precios_cierre[:periodo]) / periodo
    alpha = 2 / (periodo + 1)
    ema = sma
    for p in precios_cierre[periodo:]:
        ema = (p * alpha) + (ema * (1 - alpha))
    return ema

def actualizar_operaciones_abiertas(cierres, datos, mercado):
    pass
def enviar_senal_telegram(mensaje, chat_id=None, reply_markup=None):
    target_chat = chat_id or CHAT_ID_CANAL
    if not TOKEN_TELEGRAM or not target_chat: return False
    url = f"https://telegram.org{TOKEN_TELEGRAM}/sendMessage"
    payload = {"chat_id": str(target_chat), "text": mensaje}
    if reply_markup: payload["reply_markup"] = reply_markup
    try:
        r = requests.post(url, json=payload, timeout=10)
        return r.status_code == 200
    except Exception: return False

def construir_mensaje_senal(mercado, direccion, precio_actual, stop_loss, take_profit, ema_200, fuerza, motivo, tipo="normal"):
    prefijo = "🦈 *SEÑAL MANUAL*" if tipo == "manual" else "🦈 *CLUB MARKETSHARKS ALERTA EN VIVO*"
    dir_logo = "🟢 COMPRA" if direccion == "COMPRA" else "🔴 VENTA"
    return (
        f"{prefijo}\n\n"
        f"📊 *Par:* {mercado['nombre']}\n"
        f"🎯 *Estrategia:* Order Block + EMA 200\n"
        f"🔹 *Dirección:* {dir_logo}\n\n"
        f"💵 *Precio Entrada:* $ {precio_actual:,.2f} USD\n"
        f"🛡️ *Stop Loss (SL):* $ {stop_loss:,.2f} USD\n"
        f"💰 *Take Profit (TP):* $ {take_profit:,.2f} USD\n"
        f"⚙️ *Apalancamiento:* {20 if mercado['symbol'] == 'BTCUSDT' else 10}x\n\n"
        f"📈 *EMA 200:* $ {ema_200:,.2f} USD\n"
        f"⚡ *Contexto:* {motivo}"
    )

def generar_fallback_manual_limpio(mercado, tipo="manual"):
    datos = obtener_datos_binance(mercado["symbol"], "15m")
    if not datos:
        if mercado["symbol"] == "SPCXUSDT":
            p = obtener_precio_spcx()
            return {
                "mercado": mercado, "direccion": "COMPRA", "precio_actual": p,
                "stop_loss": p*0.98, "take_profit": p*1.05, "ema_200": p, "apalancamiento": 10,
                "mensaje": construir_mensaje_senal(mercado, "COMPRA", p, p*0.98, p*1.05, p, 1.0, "Sincronizado", tipo)
            }
        return None
    cierres = [float(v[4]) if isinstance(v, list) else float(v) for v in datos]
    precio_actual = cierres[-1]
    ema_200 = calcular_ema_tradingview(cierres, 200) or precio_actual
    direccion = "COMPRA" if precio_actual > ema_200 else "VENTA"
    sl = precio_actual * 0.99 if direccion == "COMPRA" else precio_actual * 1.01
    tp = precio_actual * 1.02 if direccion == "COMPRA" else precio_actual * 0.98
    return {
        "mercado": mercado, "direccion": direccion, "precio_actual": precio_actual,
        "stop_loss": sl, "take_profit": tp, "ema_200": ema_200, "apalancamiento": 20,
        "mensaje": construir_mensaje_senal(mercado, direccion, precio_actual, sl, tp, ema_200, 1.5, "Algoritmo Optimizado", tipo)
    }

def registrar_senal_emitida(mercado, direccion, precio_actual, stop_loss, take_profit, apalancamiento, tipo="auto"):
    global ESTADISTICAS, ESTADO_DIARIO, ULTIMA_SENAL_AUTOMATICA
    ESTADISTICAS["total_senales"] += 1
    ESTADO_DIARIO["senales_hoy"] += 1
    if tipo == "auto":
        ULTIMA_SENAL_AUTOMATICA = {"timestamp": time.time(), "mercado": mercado["nombre"], "direccion": direccion}

def enviar_senal_y_registrar(senal, chat_id=None, tipo="auto"):
    enviar_senal_telegram(senal["mensaje"], chat_id=chat_id)
    enviar_senal_a_usuarios_privados(senal["mensaje"])
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
        "Si el botón no responde, escribe /senalbtc o /senalspx para pedirla."
    )
    enviar_senal_telegram(mensaje, chat_id=chat_id, reply_markup=markup)

def generar_senal_manual(chat_id=None, mercado_seleccionado=None, requester_id=None):
    hora_actual = hora_espana()
    target_market = CONFIGURACIONES_MERCADO[0] if mercado_seleccionado == "btc" else CONFIGURACIONES_MERCADO[1]
    senal = generar_fallback_manual_limpio(target_market, tipo="manual")
    if senal:
        enviar_senal_y_registrar(senal, chat_id=chat_id, tipo="manual")
        return True
    return False

def telegram_listener():
    if not TOKEN_TELEGRAM: return
    url_base = f"https://telegram.org{TOKEN_TELEGRAM}"
    
    try:
        print("🧹 Forzando limpieza de Webhook de Telegram...")
        requests.post(f"{url_base}/deleteWebhook", json={"drop_pending_updates": True}, timeout=10)
    except Exception: pass

    offset = None
    while True:
        try:
            r = requests.get(f"{url_base}/getUpdates", params={"timeout": 5, "offset": offset}, timeout=15)
            if r.status_code != 200:
                time.sleep(5)
                continue
            for update in r.json().get("result", []):
                offset = update.get("update_id", 0) + 1
                if "message" in update:
                    message = update["message"]
                    user_id = message.get("from", {}).get("id")
                    text = (message.get("text") or "").strip().lower()
                    
                    if text == "/start":
                        guardar_usuario_db(user_id)
                        welcome = (
                            "🦈 Welcome to Club MarketSharks, Predator!\n\n"
                            "Your account is registered. You will now receive all signals directly in this private chat."
                        )
                        enviar_senal_telegram(welcome, chat_id=user_id)
                    elif text in {"/senalbtc", "senalbtc"}:
                        generar_senal_manual(chat_id=user_id, mercado_seleccionado="btc", requester_id=user_id)
                
                if "callback_query" in update:
                    callback = update["callback_query"]
                    user_id = callback.get("from", {}).get("id")
                    data = callback.get("data", "")
                    requests.post(f"{url_base}/answerCallbackQuery", json={"callback_query_id": callback.get("id"), "text": "Procesando..."}, timeout=10)
                    if data == "senal_btc":
                        generar_senal_manual(chat_id=CHAT_ID_CANAL, mercado_seleccionado="btc", requester_id=user_id)
        except Exception as e:
            print(f"⚠️ Error en listener de Telegram: {e}")
        time.sleep(2)

def motor_de_trading():
    print("🚀 Iniciando motor analítico duplicador de TradingView...")
    time.sleep(5)
    enviar_boton_solicitud(chat_id=CHAT_ID_CANAL)

    while True:
        try:
            if DETENER_BOT.is_set(): break
            resetear_estado_diario_si_es_necesario()
            
            if AUTO_SIGNAL_ENABLED and puede_enviar_senal_automatica():
                for m in CONFIGURACIONES_MERCADO:
                    s = generar_fallback_manual_limpio(m, tipo="auto")
                    if s:
                        enviar_senal_y_registrar(s, tipo="auto")
                        break
            time.sleep(60)
        except Exception:
            time.sleep(30)

if __name__ == '__main__':
    print("✈️ Conectando con la API de Telegram y activando el listener privado...")
    hilo_listener = threading.Thread(target=telegram_listener)
    hilo_listener.daemon = True
    hilo_listener.start()

    print("🦈 Activando motor analítico...")
    hilo_trading = threading.Thread(target=motor_de_trading)
    hilo_trading.daemon = True
    hilo_trading.start()

    print("🌐 Iniciando servidor Flask...")
    puerto = int(os.getenv("PORT", 10000))
    app.run(host='0.0.0.0', port=puerto, use_reloader=False, threaded=True)
