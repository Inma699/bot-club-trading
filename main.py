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

# === CONFIGURACIÓN ===
CONFIGURACIONES_MERCADO = [
    {"symbol": "BTCUSDT", "interval": "15m", "nombre": "BTCUSDT (15m)"},
    {"symbol": "SPXUSDT", "interval": "15m", "nombre": "SPXUSDT (15m/1h)", "fallback_intervals": ["1h"]},
]

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


def limpiar_solicitudes_si_es_necesario():
    global SOLICITUDES_MANUALES
    hoy = hora_espana().strftime("%Y-%m-%d")
    for chat_id in list(SOLICITUDES_MANUALES.keys()):
        if SOLICITUDES_MANUALES[chat_id].get("fecha") != hoy:
            del SOLICITUDES_MANUALES[chat_id]


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
            print("✅ Mensaje enviado correctamente")
        else:
            print(f"❌ Error Telegram {response.status_code}")
    except Exception as e:
        print(f"❌ Excepción Telegram: {e}")


def enviar_resumen_diario():
    global ESTADISTICAS
    hoy = time.strftime("%Y-%m-%d")
    ratio = round((ESTADISTICAS['ganadas'] / max(ESTADISTICAS['total_senales'], 1)) * 100, 1)
    resumen = f"📊 *RESUMEN DIARIO CLUB MARKETSHARKS*\n\n📅 Fecha: {hoy}\n🔢 Total señales: {ESTADISTICAS['total_senales']}\n🟢 Compras: {ESTADISTICAS['compras']}\n🔴 Ventas: {ESTADISTICAS['ventas']}\n✅ Ganadas: {ESTADISTICAS['ganadas']}\n❌ Perdidas: {ESTADISTICAS['perdidas']}\n📈 Ratio: {ratio}%"
    enviar_senal_telegram(resumen)
    ESTADISTICAS["ultimo_resumen"] = hoy
    # ====================== FUNCIONES DE DATOS (CORREGIDAS) ======================

def obtener_datos_binance(symbol, interval, limit=210):
    """Prioridad a Binance US para evitar bloqueos"""
    urls = [
        ("https://api.binance.us/api/v3/klines", {}),
        ("https://api.binance.com/api/v3/klines", {}),
    ]
    for base_url, extra in urls:
        try:
            params = {"symbol": symbol, "interval": interval, "limit": limit}
            response = requests.get(base_url, params={**params, **extra}, timeout=12)
            if response.status_code == 200:
                print(f"✅ Datos obtenidos de {base_url} para {symbol}")
                return response.json()
            else:
                print(f"⚠️ {base_url} devolvió {response.status_code} para {symbol} {interval}")
        except Exception as e:
            print(f"⚠️ Error consultando {base_url}: {e}")
    return None


def obtener_datos_binance_futuros(symbol, interval, limit=210):
    urls = [
        ("https://fapi.binance.us/fapi/v1/klines", {}),
        ("https://fapi.binance.com/fapi/v1/klines", {}),
    ]
    params = {"symbol": symbol, "interval": interval, "limit": limit}
    for url, extra in urls:
        try:
            response = requests.get(url, params={**params, **extra}, timeout=12)
            if response.status_code == 200:
                return response.json()
        except Exception as e:
            print(f"⚠️ Error futuros {url}: {e}")
    return None


def obtener_ticker_24h(symbol):
    urls = [
        ("https://api.binance.us/api/v3/ticker/24hr", {"symbol": symbol}),
        ("https://api.binance.com/api/v3/ticker/24hr", {"symbol": symbol}),
    ]
    for url, params in urls:
        try:
            response = requests.get(url, params=params, timeout=10)
            if response.status_code == 200:
                return response.json()
        except:
            pass
    return None


def obtener_funding_rate(symbol):
    urls = [
        ("https://fapi.binance.us/fapi/v1/fundingRate", {"symbol": symbol, "limit": 2}),
        ("https://fapi.binance.com/fapi/v1/fundingRate", {"symbol": symbol, "limit": 2}),
    ]
    for url, params in urls:
        try:
            response = requests.get(url, params=params, timeout=10)
            if response.status_code == 200:
                return response.json()
        except:
            pass
    return None


# ====================== OTRAS FUNCIONES ======================

def evaluar_fuerza_movimiento(cierres, aperturas, altos, bajos):
    if len(cierres) < 3:
        return 0.0, {"cambio_1": 0.0, "cambio_3": 0.0, "rango_3": 0.0}
    cambio_1 = ((cierres[-1] - cierres[-2]) / cierres[-2]) * 100
    cambio_3 = ((cierres[-1] - cierres[-3]) / cierres[-3]) * 100
    rango_3 = ((max(altos[-3:]) - min(bajos[-3:])) / cierres[-1]) * 100
    fuerza = abs(cambio_1) + abs(cambio_3) + rango_3
    return fuerza, {"cambio_1": cambio_1, "cambio_3": cambio_3, "rango_3": rango_3}


def calcular_ema_tradingview(precios_cierre, periodo=200):
    if len(precios_cierre) < periodo:
        return None
    sma_inicial = sum(precios_cierre[:periodo]) / periodo
    alpha = 2 / (periodo + 1)
    ema = sma_inicial
    for precio in precios_cierre[periodo:]:
        ema = (precio * alpha) + (ema * (1 - alpha))
    return ema
    # ====================== FUNCIONES DE DATOS (CORREGIDAS) ======================

def obtener_datos_binance(symbol, interval, limit=210):
    """Prioridad a Binance US para evitar bloqueos"""
    urls = [
        ("https://api.binance.us/api/v3/klines", {}),
        ("https://api.binance.com/api/v3/klines", {}),
    ]
    for base_url, extra in urls:
        try:
            params = {"symbol": symbol, "interval": interval, "limit": limit}
            response = requests.get(base_url, params={**params, **extra}, timeout=12)
            if response.status_code == 200:
                print(f"✅ Datos obtenidos de {base_url} para {symbol}")
                return response.json()
            else:
                print(f"⚠️ {base_url} devolvió {response.status_code} para {symbol} {interval}")
        except Exception as e:
            print(f"⚠️ Error consultando {base_url}: {e}")
    return None


def obtener_datos_binance_futuros(symbol, interval, limit=210):
    urls = [
        ("https://fapi.binance.us/fapi/v1/klines", {}),
        ("https://fapi.binance.com/fapi/v1/klines", {}),
    ]
    params = {"symbol": symbol, "interval": interval, "limit": limit}
    for url, extra in urls:
        try:
            response = requests.get(url, params={**params, **extra}, timeout=12)
            if response.status_code == 200:
                return response.json()
        except Exception as e:
            print(f"⚠️ Error futuros {url}: {e}")
    return None


def obtener_ticker_24h(symbol):
    urls = [
        ("https://api.binance.us/api/v3/ticker/24hr", {"symbol": symbol}),
        ("https://api.binance.com/api/v3/ticker/24hr", {"symbol": symbol}),
    ]
    for url, params in urls:
        try:
            response = requests.get(url, params=params, timeout=10)
            if response.status_code == 200:
                return response.json()
        except:
            pass
    return None


def obtener_funding_rate(symbol):
    urls = [
        ("https://fapi.binance.us/fapi/v1/fundingRate", {"symbol": symbol, "limit": 2}),
        ("https://fapi.binance.com/fapi/v1/fundingRate", {"symbol": symbol, "limit": 2}),
    ]
    for url, params in urls:
        try:
            response = requests.get(url, params=params, timeout=10)
            if response.status_code == 200:
                return response.json()
        except:
            pass
    return None


# ====================== OTRAS FUNCIONES ======================

def evaluar_fuerza_movimiento(cierres, aperturas, altos, bajos):
    if len(cierres) < 3:
        return 0.0, {"cambio_1": 0.0, "cambio_3": 0.0, "rango_3": 0.0}
    cambio_1 = ((cierres[-1] - cierres[-2]) / cierres[-2]) * 100
    cambio_3 = ((cierres[-1] - cierres[-3]) / cierres[-3]) * 100
    rango_3 = ((max(altos[-3:]) - min(bajos[-3:])) / cierres[-1]) * 100
    fuerza = abs(cambio_1) + abs(cambio_3) + rango_3
    return fuerza, {"cambio_1": cambio_1, "cambio_3": cambio_3, "rango_3": rango_3}


def calcular_ema_tradingview(precios_cierre, periodo=200):
    if len(precios_cierre) < periodo:
        return None
    sma_inicial = sum(precios_cierre[:periodo]) / periodo
    alpha = 2 / (periodo + 1)
    ema = sma_inicial
    for precio in precios_cierre[periodo:]:
        ema = (precio * alpha) + (ema * (1 - alpha))
    return ema
    def construir_mensaje_senal(mercado, direccion, precio_actual, stop_loss, take_profit, ema_200, fuerza, motivo, flujo_btc=None, liquidaciones=None, tipo="normal"):
    flujo_texto = f"\n⚡ *Flujo de capital:* {flujo_btc['direccion']} ({flujo_btc['confianza']:.2f}) | {flujo_btc['motivo']}" if flujo_btc else ""
    liquidacion_texto = f"\n💥 *Liquidaciones:* {liquidaciones['intensidad']} | {liquidaciones['motivo']}" if liquidaciones and liquidaciones.get("detectado") else ""
    prefijo = "🦈 *SEÑAL MANUAL*" if tipo == "manual" else "🦈 *CLUB MARKETSHARKS ALERTA EN VIVO*"
    direccion_texto = "🟢 *Dirección:* COMPRA" if direccion == "COMPRA" else "🔴 *Dirección:* VENTA"
    
    return f"{prefijo}\n\n{direccion_texto}\n📊 *Par:* {mercado['nombre']}\n💵 *Entrada:* ${precio_actual:,.2f}\n🛡️ *SL:* ${stop_loss:,.2f}\n💰 *TP:* ${take_profit:,.2f}\n📈 *EMA 200:* ${ema_200:,.2f}\n⚡ Fuerza: {fuerza:.2f}%{flujo_texto}{liquidacion_texto}"


def enviar_boton_solicitud(chat_id=None):
    markup = {"inline_keyboard": [
        [{"text": "BTC manual", "callback_data": "senal_btc"}],
        [{"text": "SPX manual", "callback_data": "senal_spx"}],
    ]}
    mensaje = "🦈 *CLUB MARKETSHARKS*\n\nPulsa un botón para solicitar señal manual."
    enviar_senal_telegram(mensaje, chat_id=chat_id, reply_markup=markup)


def generar_senal_manual(chat_id=None, mercado_seleccionado=None, requester_id=None):
    global SOLICITUDES_MANUALES
    limpiar_solicitudes_si_es_necesario()
    if not chat_id:
        return False

    identificador = requester_id or chat_id
    hoy = hora_espana().strftime("%Y-%m-%d")

    if not es_admin_del_canal(identificador):
        if SOLICITUDES_MANUALES.get(identificador, {}).get("fecha") == hoy and SOLICITUDES_MANUALES.get(identificador, {}).get("usado"):
            enviar_senal_telegram("Ya usaste tu señal manual hoy.", chat_id)
            return False
        SOLICITUDES_MANUALES[identificador] = {"fecha": hoy, "usado": True}

    # Lógica simplificada para prueba
    print(f"🔄 Generando señal manual para {identificador}")
    enviar_senal_telegram("🦈 Señal manual solicitada. Generando...", chat_id=chat_id)
    return True


def telegram_listener():
    if not TOKEN_TELEGRAM:
        return
    offset = None
    while True:
        try:
            url = f"https://api.telegram.org/bot{TOKEN_TELEGRAM}/getUpdates"
            params = {"timeout": 5}
            if offset:
                params["offset"] = offset
            resp = requests.get(url, params=params, timeout=10)
            if resp.status_code == 200:
                for update in resp.json().get("result", []):
                    offset = update.get("update_id", 0) + 1
                    # (Lógica básica de comandos)
        except:
            pass
        time.sleep(3)


def motor_de_trading():
    print("🚀 Motor iniciado")
    time.sleep(5)
    enviar_senal_telegram("🦈 *CLUB MARKETSHARKS* Bot reiniciado correctamente.")
    enviar_boton_solicitud(CHAT_ID_CANAL)

    while True:
        print("🔄 Escaneando mercado...")
        time.sleep(60)


if __name__ == '__main__':
    print("🚀 Iniciando bot completo...")
    threading.Thread(target=motor_de_trading, daemon=True).start()
    threading.Thread(target=telegram_listener, daemon=True).start()
    
    port = int(os.getenv("PORT", 10000))
    app.run(host='0.0.0.0', port=port)
