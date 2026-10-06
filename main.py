import os
import threading
import time
import requests
import ccxt
import numpy as np
import pandas as pd
import psycopg2
import xml.etree.ElementTree as ET
from datetime import datetime
from zoneinfo import ZoneInfo
from flask import Flask
import anthropic

app = Flask(__name__)

@app.route('/')
def home():
    return "Club MarketSharks - Algoritmo Espejo TradingView Activo", 200

# === CLIENTE CCXT COMPARTIDO (BITGET) ===
# Render bloquea Binance (HTTP 451 por restricción geográfica), así que usamos
# la API pública de Bitget vía CCXT como fuente principal de precios/velas.
_EXCHANGE_BITGET = ccxt.bitget({"enableRateLimit": True})

# Mapeo de intervalos usados internamente (formato Binance) al formato CCXT/Bitget.
_MAPA_INTERVALOS_CCXT = {
    "1m": "1m", "3m": "3m", "5m": "5m", "15m": "15m", "30m": "30m",
    "1h": "1h", "2h": "2h", "4h": "4h", "6h": "6h", "12h": "12h", "1d": "1d",
}


def _symbol_spot_ccxt(symbol):
    """Convierte 'BTCUSDT' al formato spot de CCXT: 'BTC/USDT'."""
    symbol = str(symbol).upper()
    if symbol.endswith("USDT"):
        return f"{symbol[:-4]}/USDT"
    return symbol


def _symbol_futuros_ccxt(symbol):
    """Convierte 'BTCUSDT' al formato de perpetuo USDT-M de CCXT: 'BTC/USDT:USDT'."""
    return f"{_symbol_spot_ccxt(symbol)}:USDT"

# === CREDENCIALES DESDE ENVIRONMENT VARIABLES ===
TOKEN_TELEGRAM = os.getenv("TELEGRAM_TOKEN", "").strip()
CHAT_ID_CANAL = os.getenv("TELEGRAM_CHAT_ID", "").strip()

# === INTEGRACIÓN ANTHROPIC (ANÁLISIS MACRO "ESTILO TRUMP") ===
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "").strip()
ANTHROPIC_MODEL = os.getenv("ANTHROPIC_MODEL", "claude-sonnet-5-5").strip()
ANALISIS_TRUMP_ENABLED = os.getenv("ANALISIS_TRUMP_ENABLED", "true").strip().lower() in {"1", "true", "on", "si", "sí"}
# Cliente perezoso: solo se crea si hay clave configurada, para no romper el arranque si falta.
_cliente_anthropic = None
if ANTHROPIC_API_KEY:
    try:
        _cliente_anthropic = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
    except Exception as error:
        print(f"⚠️ No se pudo inicializar el cliente Anthropic: {error}")
        _cliente_anthropic = None
else:
    print("ℹ️ ANTHROPIC_API_KEY no configurada. El análisis macro 'estilo Trump' quedará desactivado.")

# Caché del análisis macro diario para no disparar llamadas a Claude en cada señal.
CACHE_ANALISIS_TRUMP = {"fecha_hora": None, "texto": None}
ANALISIS_TRUMP_TTL_SEGUNDOS = int(os.getenv("ANALISIS_TRUMP_TTL_SEGUNDOS", "3600"))

# === CONFIGURACIÓN DE MERCADOS ===
CONFIGURACIONES_MERCADO = [
    {"symbol": "BTCUSDT", "interval": "15m", "nombre": "BTCUSDT (15m)"},
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

# Hora (Europe/Madrid, formato HH:MM) y control del parte diario automático de "la mente de Trump"
PARTE_TRUMP_HORA = os.getenv("PARTE_TRUMP_HORA", "08:00").strip()
ULTIMO_PARTE_TRUMP_ENVIADO = None

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

# === CONTROL DE SEÑALES AUTOMÁTICAS ===
# Forzar señales automáticas activas por defecto. Se puede alternar via Telegram por admins.
AUTO_SIGNAL_ENABLED = True
AUTO_SIGNAL_COOLDOWN_SECONDS = int(os.getenv("AUTO_SIGNAL_COOLDOWN_SECONDS", "1800"))
ULTIMA_SENAL_AUTOMATICA = None
DETENER_BOT = threading.Event()
BINARIAS_ENABLED = os.getenv("BINARIAS_ENABLED", "true").strip().lower() in {"1", "true", "on", "si", "sí"}
SIMBOLO_BINARIAS = os.getenv("BINARIAS_SYMBOL", "BTC/USDT:USDT")


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


def obtener_noticias_gratis(consulta, max_items=6, idioma="es-419", pais="US"):
    """
    Lee titulares recientes usando el feed RSS público y gratuito de Google News
    (no requiere API key). Devuelve una lista de titulares (str).
    """
    try:
        url = "https://news.google.com/rss/search"
        params = {
            "q": consulta,
            "hl": idioma,
            "gl": pais,
            "ceid": f"{pais}:{idioma.split('-')[0]}",
        }
        respuesta = requests.get(url, params=params, timeout=10, headers={"User-Agent": "Mozilla/5.0"})
        respuesta.raise_for_status()
        raiz = ET.fromstring(respuesta.content)
        titulares = []
        for item in raiz.findall(".//item")[:max_items]:
            titulo = item.findtext("title")
            if titulo:
                titulares.append(titulo.strip())
        return titulares
    except Exception as error:
        print(f"⚠️ No se pudieron obtener noticias para '{consulta}': {error}")
        return []


def recopilar_noticias_macro_diarias():
    """Agrupa titulares del día sobre Trump, Bitcoin y la Fed desde una fuente gratuita."""
    consultas = {
        "Donald Trump economía": "Donald Trump economy OR tariffs OR Federal Reserve",
        "Bitcoin": "Bitcoin price OR crypto market",
        "Reserva Federal": "Federal Reserve interest rates OR Jerome Powell",
    }
    bloque_noticias = {}
    for etiqueta, consulta in consultas.items():
        bloque_noticias[etiqueta] = obtener_noticias_gratis(consulta, max_items=5)
    return bloque_noticias


def generar_analisis_trump_ia(forzar=False):
    """
    Usa la API oficial de Anthropic (Claude) para generar un análisis de sentimiento
    macro de mercado, narrado con la personalidad retórica de Donald Trump, a partir
    de titulares de noticias reales del día sobre Trump, Bitcoin y la Fed.

    Devuelve un texto breve listo para insertar en los mensajes de Telegram.
    Si Anthropic no está configurado o falla, devuelve None (no rompe el flujo del bot).
    """
    global CACHE_ANALISIS_TRUMP

    if not ANALISIS_TRUMP_ENABLED or _cliente_anthropic is None:
        return None

    ahora = time.time()
    cache_valida = (
        CACHE_ANALISIS_TRUMP["fecha_hora"] is not None
        and (ahora - CACHE_ANALISIS_TRUMP["fecha_hora"]) < ANALISIS_TRUMP_TTL_SEGUNDOS
    )
    if cache_valida and not forzar:
        return CACHE_ANALISIS_TRUMP["texto"]

    noticias = recopilar_noticias_macro_diarias()
    resumen_noticias = []
    for etiqueta, titulares in noticias.items():
        if titulares:
            resumen_noticias.append(f"{etiqueta}:\n" + "\n".join(f"- {t}" for t in titulares))
    texto_noticias = "\n\n".join(resumen_noticias) if resumen_noticias else "Sin titulares disponibles hoy."

    dia_semana = hora_espana().strftime("%A")
    prompt = (
        "Eres un analista de mercados que redacta un breve parte macro DIARIO para un canal de trading de BTC/USDT. "
        "Debes narrarlo imitando el ESTILO RETÓRICO de Donald Trump (frases cortas, contundente, mayúsculas ocasionales "
        "para énfasis, superlativos como 'tremendo', 'nadie lo ha visto nunca', 'increíble'), pero el contenido debe ser "
        "un análisis de sentimiento de mercado SERIO y útil, basado ÚNICAMENTE en los titulares reales que te paso abajo. "
        "No inventes declaraciones textuales de Trump ni cites frases como si fueran suyas; es una PARODIA analítica, "
        "no una cita real. Al final añade una conclusión sobre si el sesgo del día es alcista, bajista o neutro para BTC, "
        "y qué día de la semana (de los próximos 7) ves con más probabilidad de un movimiento fuerte, justificando brevemente "
        "por qué (ej. reunión de la Fed, fecha de anuncio, vencimiento de opciones, etc. si aparece en las noticias). "
        f"Hoy es {dia_semana}. Máximo 90 palabras. Responde en español. Incluye SIEMPRE un disclaimer final corto de que "
        "esto no es consejo financiero.\n\n"
        f"TITULARES DE HOY:\n{texto_noticias}"
    )

    try:
        respuesta = _cliente_anthropic.messages.create(
            model=ANTHROPIC_MODEL,
            max_tokens=400,
            messages=[{"role": "user", "content": prompt}],
        )
        texto = "".join(
            bloque.text for bloque in respuesta.content if getattr(bloque, "type", None) == "text"
        ).strip()
        if texto:
            CACHE_ANALISIS_TRUMP["fecha_hora"] = ahora
            CACHE_ANALISIS_TRUMP["texto"] = texto
            return texto
    except Exception as error:
        print(f"⚠️ Error consultando Anthropic/Claude para el análisis macro: {error}")

    return CACHE_ANALISIS_TRUMP["texto"]


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
    """
    Obtiene velas (klines) de mercado SPOT para `symbol` (ej. 'BTCUSDT').

    NOTA: Render bloquea las IPs de Binance con error 451 (restricción geográfica),
    así que usamos Bitget (vía CCXT) como fuente principal, con Kraken como respaldo.
    El formato de salida se mantiene idéntico al de Binance klines:
    [timestamp, open, high, low, close, volume] para máxima compatibilidad con el
    resto del bot (order blocks, EMA, flujo de capital, etc.).
    """
    timeframe = _MAPA_INTERVALOS_CCXT.get(interval, interval)
    par_ccxt = _symbol_spot_ccxt(symbol)
    try:
        velas = _EXCHANGE_BITGET.fetch_ohlcv(par_ccxt, timeframe=timeframe, limit=limit)
        if velas:
            print(f"✅ Velas obtenidas de Bitget (spot) para {symbol} {interval}: {len(velas)}")
            return velas
        print(f"⚠️ Bitget no devolvió velas para {par_ccxt} {interval}")
    except Exception as e:
        print(f"⚠️ Error consultando Bitget (CCXT) para {par_ccxt} {interval}: {e}")

    datos_kraken = obtener_datos_kraken(symbol, interval, limit)
    if datos_kraken:
        print(f"✅ Velas obtenidas de Kraken para {symbol} {interval}: {len(datos_kraken)}")
        return datos_kraken
    return None


def obtener_datos_kraken(symbol, interval, limit=210):
    """Fuente alternativa pública de velas BTC/USD cuando Binance no está disponible."""
    intervalos = {"1m": 1, "5m": 5, "15m": 15, "30m": 30, "1h": 60, "4h": 240, "1d": 1440}
    intervalo = intervalos.get(interval)
    if str(symbol).upper() != "BTCUSDT" or intervalo is None:
        return None

    try:
        response = requests.get(
            "https://api.kraken.com/0/public/OHLC",
            params={"pair": "XBTUSD", "interval": intervalo},
            timeout=12,
        )
        response.raise_for_status()
        payload = response.json()
        if payload.get("error"):
            raise ValueError(", ".join(payload["error"]))

        resultados = payload.get("result", {})
        par = next((clave for clave in resultados if clave != "last"), None)
        if not par:
            return None

        velas = resultados[par]
        velas_cerradas = velas[:-1]
        return [
            [
                int(float(vela[0]) * 1000),
                vela[1],
                vela[2],
                vela[3],
                vela[4],
                vela[6],
            ]
            for vela in velas_cerradas[-limit:]
        ]
    except (requests.RequestException, ValueError, KeyError, TypeError, IndexError) as error:
        print(f"⚠️ Kraken no pudo devolver velas para {symbol} {interval}: {error}")
        return None


def obtener_datos_binance_futuros(symbol, interval, limit=210):
    """
    Obtiene velas (klines) de FUTUROS perpetuos USDT-M para `symbol` (ej. 'BTCUSDT').

    Usa Bitget (vía CCXT) en lugar de Binance Futures, ya que Render bloquea
    las IPs de Binance (HTTP 451). Formato de salida idéntico a Binance klines.
    """
    timeframe = _MAPA_INTERVALOS_CCXT.get(interval, interval)
    par_ccxt = _symbol_futuros_ccxt(symbol)
    try:
        velas = _EXCHANGE_BITGET.fetch_ohlcv(par_ccxt, timeframe=timeframe, limit=limit)
        if velas:
            print(f"✅ Velas de futuros obtenidas de Bitget para {symbol} {interval}: {len(velas)}")
            return velas
        print(f"⚠️ Bitget no devolvió velas de futuros para {par_ccxt} {interval}")
    except Exception as e:
        print(f"⚠️ Error consultando futuros Bitget (CCXT) para {par_ccxt} {interval}: {e}")
    return None


def obtener_ticker_24h(symbol):
    """
    Devuelve un dict compatible con el formato 'ticker 24hr' de Binance
    (claves: priceChangePercent, lastPrice, volume, etc.) pero obtenido desde
    Bitget vía CCXT, ya que Binance Futures está bloqueado en Render (HTTP 451).
    """
    par_ccxt = _symbol_futuros_ccxt(symbol)
    try:
        ticker = _EXCHANGE_BITGET.fetch_ticker(par_ccxt)
        cambio_pct = ticker.get("percentage")
        if cambio_pct is None:
            # Fallback: calcular el % de cambio a partir de open/last si CCXT no lo trae.
            precio_apertura = ticker.get("open")
            precio_actual = ticker.get("last") or ticker.get("close")
            if precio_apertura and precio_actual:
                cambio_pct = ((precio_actual - precio_apertura) / precio_apertura) * 100
            else:
                cambio_pct = 0.0
        return {
            "priceChangePercent": cambio_pct,
            "lastPrice": ticker.get("last"),
            "volume": ticker.get("baseVolume"),
            "highPrice": ticker.get("high"),
            "lowPrice": ticker.get("low"),
        }
    except Exception as e:
        print(f"⚠️ Error consultando ticker 24h en Bitget (CCXT) para {par_ccxt}: {e}")
        return None


def obtener_funding_rate(symbol):
    """
    Devuelve una lista compatible con el formato de Binance fundingRate
    (lista de dicts con clave 'fundingRate'), obtenida desde Bitget vía CCXT.
    """
    par_ccxt = _symbol_futuros_ccxt(symbol)
    try:
        funding = _EXCHANGE_BITGET.fetch_funding_rate(par_ccxt)
        tasa = funding.get("fundingRate")
        if tasa is None:
            return None
        return [{"fundingRate": tasa, "symbol": symbol}]
    except Exception as e:
        print(f"⚠️ Error consultando funding rate en Bitget (CCXT) para {par_ccxt}: {e}")
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

    velas_recientes = datos[-5:]
    nuevas_operaciones = []

    for op in OPERACIONES_ABIERTAS:
        if op["mercado"] != mercado["nombre"]:
            nuevas_operaciones.append((op, None))
            continue

        estado = None
        nivel_alcanzado = None
        precio_nivel = None
        minuto_senal = op.get("creado_en", 0) // 60000
        for vela in velas_recientes:
            if int(vela[0]) // 60000 < minuto_senal:
                continue
            maximo = float(vela[2])
            minimo = float(vela[3])
            if op["tipo"] == "COMPRA":
                toca_sl = minimo <= op["stop_loss"]
                toca_tp = maximo >= op["take_profit"]
            else:
                toca_sl = maximo >= op["stop_loss"]
                toca_tp = minimo <= op["take_profit"]

            if toca_sl or toca_tp:
                # Si ambos niveles aparecen en la misma vela, se cuenta el SL primero.
                estado = "perdida" if toca_sl else "ganada"
                nivel_alcanzado = "Stop Loss (SL)" if toca_sl else "Take Profit (TP)"
                precio_nivel = op["stop_loss"] if toca_sl else op["take_profit"]
                break

        if estado:
            ESTADISTICAS["perdidas" if estado == "perdida" else "ganadas"] += 1
            nuevas_operaciones.append((op, estado, nivel_alcanzado, precio_nivel))
            continue

        precio_actual = cierres[-1]
        if op["tipo"] == "COMPRA":
            ganancia_pct = ((precio_actual - op["entrada"]) / op["entrada"]) * 100
        else:
            ganancia_pct = ((op["entrada"] - precio_actual) / op["entrada"]) * 100
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

    OPERACIONES_ABIERTAS = [op for op, estado, *_ in nuevas_operaciones if estado is None]

    for op, estado, *detalle_cierre in nuevas_operaciones:
        if estado is None:
            continue
        nivel_alcanzado, precio_nivel = detalle_cierre
        mensaje_cierre = (
            f"🧾 *CIERRE DE OPERACIÓN*\n\n"
            f"📊 Par: {op['mercado']}\n"
            f"🔹 Tipo: {op['tipo']}\n"
            f"💵 Entrada: $ {op['entrada']:,.2f}\n"
            f"🛑 Stop: $ {op['stop_loss']:,.2f}\n"
            f"🎯 Take Profit: $ {op['take_profit']:,.2f}\n"
            f"📍 Precio alcanzó: {nivel_alcanzado} ($ {precio_nivel:,.2f})\n"
            f"✅ Resultado: {estado.upper()}"
        )
        enviar_senal_telegram(mensaje_cierre)


def enviar_senal_telegram(mensaje, chat_id=None, reply_markup=None):
    target_chat = chat_id or CHAT_ID_CANAL
    if not TOKEN_TELEGRAM or not target_chat:
        print("⚠️ Faltan TELEGRAM_TOKEN o TELEGRAM_CHAT_ID en Render")
        return

    url = f"https://api.telegram.org/bot{TOKEN_TELEGRAM}/sendMessage"
    # Enviar como texto plano para evitar errores de parseo de entidades
    payload = {"chat_id": target_chat, "text": mensaje}
    if reply_markup:
        payload["reply_markup"] = reply_markup
    try:
        print(f"➡️ Enviando mensaje a Telegram chat={target_chat} payload_len={len(mensaje)}")
        response = requests.post(url, json=payload, timeout=10)
        try:
            response.raise_for_status()
            print(f"✅ Señal enviada a Telegram al chat {target_chat}")
            return True, response.status_code, response.text
        except Exception:
            print(f"⚠️ Telegram devolvió status {response.status_code} al enviar a {target_chat}: {response.text}")
            return False, response.status_code, response.text
    except Exception as e:
        print(f"⚠️ Error enviando señal a Telegram: {e}")
        return False, None, str(e)


def enviar_resumen_diario():
    global ESTADISTICAS
    hoy = time.strftime("%Y-%m-%d")
    ratio = round((ESTADISTICAS['ganadas'] / max(ESTADISTICAS['total_senales'], 1)) * 100, 1)
    analisis_trump = generar_analisis_trump_ia(forzar=True)
    macro_texto = f"\n\n🗣️ *Lectura macro del día (estilo Trump, vía IA):*\n{analisis_trump}" if analisis_trump else ""
    resumen = (
        f"📊 *RESUMEN DIARIO CLUB MARKETSHARKS*\n\n"
        f"📅 Fecha: {hoy}\n"
        f"🔢 Total señales: {ESTADISTICAS['total_senales']}\n"
        f"🟢 Compras: {ESTADISTICAS['compras']}\n"
        f"🔴 Ventas: {ESTADISTICAS['ventas']}\n"
        f"✅ Ganadas: {ESTADISTICAS['ganadas']}\n"
        f"❌ Perdidas: {ESTADISTICAS['perdidas']}\n"
        f"📈 Ratio: {ratio}%"
        f"{macro_texto}"
    )
    enviar_senal_telegram(resumen)
    ESTADISTICAS["ultimo_resumen"] = hoy


def enviar_parte_diario_mente_trump(chat_id=None):
    """
    Envía a Telegram un mensaje dedicado con la 'lectura macro estilo Trump' generada
    por Claude (Anthropic) a partir de noticias reales del día sobre Trump, Bitcoin y la Fed,
    incluyendo su opinión sobre qué día de la semana podría moverse BTC con fuerza.
    """
    analisis_trump = generar_analisis_trump_ia(forzar=True)
    if not analisis_trump:
        mensaje = (
            "🧠 *LA MENTE DE TRUMP SOBRE BTC*\n\n"
            "⚠️ No se pudo generar el análisis macro ahora mismo (falta ANTHROPIC_API_KEY o hubo un error de red). "
            "Inténtalo de nuevo más tarde."
        )
    else:
        mensaje = (
            "🧠 *LA MENTE DE TRUMP SOBRE BTC* 🇺🇸\n\n"
            f"{analisis_trump}\n\n"
            "ℹ️ Generado por IA (Claude/Anthropic) a partir de titulares reales del día. "
            "Es una parodia analítica, NO declaraciones reales de Donald Trump ni asesoramiento financiero."
        )
    enviar_senal_telegram(mensaje, chat_id=chat_id)


def calcular_niveles_senal(direccion, precio, cierres, altos, bajos):
    if len(cierres) < 22:
        return None

    rangos = []
    for indice in range(max(1, len(cierres) - 14), len(cierres)):
        rangos.append(max(
            altos[indice] - bajos[indice],
            abs(altos[indice] - cierres[indice - 1]),
            abs(bajos[indice] - cierres[indice - 1]),
        ))
    atr = sum(rangos) / len(rangos) if rangos else 0
    if atr <= 0:
        return None

    soporte = min(bajos[-21:-1])
    resistencia = max(altos[-21:-1])
    margen_nivel = max(atr * 0.15, precio * 0.0005)
    riesgo_minimo = max(atr * 1.5, precio * 0.0025)
    riesgo_maximo = precio * 0.015

    if direccion == "COMPRA":
        distancia_soporte = precio - soporte + margen_nivel if soporte < precio else 0
        distancia_riesgo = max(riesgo_minimo, distancia_soporte)
        if distancia_riesgo > riesgo_maximo:
            return None
        stop_loss = precio - distancia_riesgo
        take_profit = precio + (distancia_riesgo * 2.05)
        if precio < resistencia < take_profit:
            return None
    else:
        distancia_resistencia = resistencia - precio + margen_nivel if resistencia > precio else 0
        distancia_riesgo = max(riesgo_minimo, distancia_resistencia)
        if distancia_riesgo > riesgo_maximo:
            return None
        stop_loss = precio + distancia_riesgo
        take_profit = precio - (distancia_riesgo * 2.05)
        if take_profit < soporte < precio:
            return None

    return {
        "stop_loss": stop_loss,
        "take_profit": take_profit,
        "soporte": soporte,
        "resistencia": resistencia,
        "ratio_riesgo_beneficio": abs(take_profit - precio) / abs(precio - stop_loss),
    }


def construir_mensaje_senal(mercado, direccion, precio_actual, stop_loss, take_profit, ema_200, fuerza, motivo, flujo_btc=None, liquidaciones=None, tipo="normal", soporte=None, resistencia=None, ratio_riesgo_beneficio=2.0):
    flujo_texto = f"\n⚡ *Flujo de capital:* {flujo_btc['direccion']} ({flujo_btc['confianza']:.2f}) | {flujo_btc['motivo']}" if flujo_btc else ""
    liquidacion_texto = f"\n💥 *Liquidaciones/impulso masivo:* {liquidaciones['intensidad']} | {liquidaciones['motivo']}" if liquidaciones and liquidaciones.get("detectado") else ""
    soporte_texto = f"🧱 *Soporte 20 velas:* $ {soporte:,.2f} USD\n" if soporte is not None else "🧱 *Soporte 20 velas:* no identificado\n"
    resistencia_texto = f"🧱 *Resistencia 20 velas:* $ {resistencia:,.2f} USD\n" if resistencia is not None else "🧱 *Resistencia 20 velas:* no identificada\n"
    prefijo = "🦈 *SEÑAL MANUAL*" if tipo == "manual" else "🦈 *CLUB MARKETSHARKS ALERTA EN VIVO*"
    tipo_texto = "\n⚠️ *Esta señal fue solicitada manualmente por un miembro y no forma parte de la detección automática principal.*" if tipo == "manual" else ""
    if direccion == "COMPRA":
        direccion_texto = "🟢 *Dirección:* COMPRA"
    else:
        direccion_texto = "🔴 *Dirección:* VENTA"

    analisis_trump = generar_analisis_trump_ia()
    macro_texto = f"\n\n🗣️ *Lectura macro (estilo Trump, vía IA):*\n{analisis_trump}" if analisis_trump else ""

    return (
        f"{prefijo}\n\n"
        f"{tipo_texto}\n"
        f"📊 *Par:* {mercado['nombre']}\n"
        f"🎯 *Estrategia:* Order Block + Flujo de capital + EMA 200\n"
        f"{direccion_texto}\n\n"
        f"💵 *Precio Entrada:* $ {precio_actual:,.2f} USD\n"
        f"🛡️ *Stop Loss (SL):* $ {stop_loss:,.2f} USD\n"
        f"💰 *Take Profit (TP):* $ {take_profit:,.2f} USD\n"
        f"📐 *Riesgo/beneficio:* 1:{ratio_riesgo_beneficio:.2f}\n"
        f"{soporte_texto}"
        f"{resistencia_texto}"
        f"⚙️ *Apalancamiento recomendado:* 75x\n\n"
        f"📈 *EMA 200:* $ {ema_200:,.2f} USD\n"
        f"⚡ *Fuerza movimiento:* {fuerza:.2f}% | *Contexto:* {motivo}{flujo_texto}{liquidacion_texto}"
        f"{macro_texto}"
    )


def generar_senal_fallback(mercado, hora_actual, tipo="manual"):
    intervalos = [mercado.get("interval", "15m")]
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
        else:
            direccion = "VENTA"

        niveles = calcular_niveles_senal(direccion, precio_actual, cierres, altos, bajos)
        if not niveles:
            continue
        stop_loss = niveles["stop_loss"]
        take_profit = niveles["take_profit"]

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
            soporte=niveles["soporte"],
            resistencia=niveles["resistencia"],
            ratio_riesgo_beneficio=niveles["ratio_riesgo_beneficio"],
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


def generar_senal_para_mercado(mercado, hora_actual, tipo="auto"):
    intervalos = [mercado.get("interval", "15m")]
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
        elif condicion_venta:
            direccion = "VENTA"
        else:
            continue

        niveles = calcular_niveles_senal(direccion, precio_actual, cierres, altos, bajos)
        if not niveles:
            continue
        stop_loss = niveles["stop_loss"]
        take_profit = niveles["take_profit"]

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
            soporte=niveles["soporte"],
            resistencia=niveles["resistencia"],
            ratio_riesgo_beneficio=niveles["ratio_riesgo_beneficio"],
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
        "creado_en": int(time.time() * 1000),
    })
    if tipo == "auto":
        ULTIMA_SENAL_AUTOMATICA = {"timestamp": time.time(), "mercado": mercado["nombre"], "direccion": direccion}


def enviar_senal_y_registrar(senal, chat_id=None, tipo="auto"):
    enviar_senal_telegram(senal["mensaje"], chat_id=chat_id)
    registrar_senal_emitida(senal["mercado"], senal["direccion"], senal["precio_actual"], senal["stop_loss"], senal["take_profit"], senal["apalancamiento"], tipo=tipo)


def construir_teclado_solicitud():
    estado_auto = "ON" if AUTO_SIGNAL_ENABLED else "OFF"
    estado_binarias = "ON" if BINARIAS_ENABLED else "OFF"
    return {"inline_keyboard": [
        [{"text": "BTC manual", "callback_data": "senal_btc"}],
        [{"text": f"Automáticas: {estado_auto}", "callback_data": "toggle_auto"}],
        [{"text": f"Señales binarias: {estado_binarias}", "callback_data": "toggle_binarias"}],
    ]}


def enviar_boton_solicitud(chat_id=None):
    mensaje = (
        "🦈 *CLUB MARKETSHARKS*\n\n"
        "Elija el mercado para solicitar una señal manual instantánea.\n\n"
        "⚠️ Aviso importante: esta señal manual NO sustituye la estrategia principal del canal.\n"
        "Los administradores del canal pueden pedir más de 1 señal manual al día.\n"
        "Los miembros normales solo pueden solicitar 1 señal manual por día.\n"
        "La señal manual se asume bajo su propio riesgo y no tiene por qué coincidir con la estrategia principal del bot.\n\n"
        "Si el botón no responde, escribe /senalbtc en este chat para pedirla manualmente.\n"
        "Los administradores pueden activar o pausar las señales automáticas y binarias desde los botones."
    )
    enviar_senal_telegram(mensaje, chat_id=chat_id, reply_markup=construir_teclado_solicitud())


def actualizar_teclado_callback(callback):
    mensaje = callback.get("message", {})
    chat_id = mensaje.get("chat", {}).get("id")
    message_id = mensaje.get("message_id")
    if not chat_id or not message_id:
        return
    requests.post(
        f"https://api.telegram.org/bot{TOKEN_TELEGRAM}/editMessageReplyMarkup",
        json={
            "chat_id": chat_id,
            "message_id": message_id,
            "reply_markup": construir_teclado_solicitud(),
        },
        timeout=10,
    )


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
    if mercado_seleccionado == "btc":
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


def calcular_cci_binarias(velas, periodo=14):
    precio_tipico = (velas["high"] + velas["low"] + velas["close"]) / 3
    media = precio_tipico.rolling(window=periodo).mean()
    desviacion = precio_tipico.rolling(window=periodo).apply(
        lambda valores: np.abs(valores - valores.mean()).mean(), raw=True
    ).replace(0, 0.0001)
    return float(((precio_tipico - media) / (0.015 * desviacion)).iloc[-1])


def calcular_rsi_binarias(velas, periodo=14):
    """RSI clásico de Wilder sobre el cierre de las velas sintéticas de 10s, usado como
    filtro adicional de momentum para evitar entradas en zonas de agotamiento (sobrecompra/sobreventa)."""
    cierre = velas["close"]
    delta = cierre.diff()
    ganancia = delta.clip(lower=0)
    perdida = -delta.clip(upper=0)
    media_ganancia = ganancia.ewm(alpha=1 / periodo, min_periods=periodo, adjust=False).mean()
    media_perdida = perdida.ewm(alpha=1 / periodo, min_periods=periodo, adjust=False).mean()
    rs = media_ganancia / media_perdida.replace(0, np.nan)
    rsi = 100 - (100 / (1 + rs))
    valor = rsi.iloc[-1]
    return float(valor) if pd.notna(valor) else 50.0


def actualizar_contexto_binarias(exchange_binarias):
    columnas = ["timestamp", "open", "high", "low", "close", "volume"]
    barras_1m = exchange_binarias.fetch_ohlcv(SIMBOLO_BINARIAS, timeframe="1m", limit=100)
    barras_5m = exchange_binarias.fetch_ohlcv(SIMBOLO_BINARIAS, timeframe="5m", limit=30)
    if len(barras_1m) < 50 or len(barras_5m) < 25:
        raise ValueError("Bitget devolvió pocas velas para calcular el contexto")

    velas_1m = pd.DataFrame(barras_1m, columns=columnas)
    bloque = velas_1m["close"].iloc[-50:].values
    x = np.arange(50)
    coeficientes = np.polyfit(x, bloque, 1)
    centro = float(coeficientes[0] * 49 + coeficientes[1])
    desviacion = float(velas_1m["close"].iloc[-50:].std())
    rango_real_1m = pd.concat([
        velas_1m["high"] - velas_1m["low"],
        (velas_1m["high"] - velas_1m["close"].shift()).abs(),
        (velas_1m["low"] - velas_1m["close"].shift()).abs(),
    ], axis=1).max(axis=1)
    atr_macro = float(rango_real_1m.rolling(14).mean().iloc[-1])

    velas_5m = pd.DataFrame(barras_5m, columns=columnas)
    ema9 = velas_5m["close"].ewm(span=9, adjust=False).mean().iloc[-1]
    ema21 = velas_5m["close"].ewm(span=21, adjust=False).mean().iloc[-1]
    tendencia = "ALCISTA" if ema9 > ema21 else "BAJISTA" if ema9 < ema21 else "NEUTRO"

    cerradas = velas_5m.iloc[:-1]
    movimiento_alcista = cerradas["high"].diff()
    movimiento_bajista = -cerradas["low"].diff()
    dm_positivo = movimiento_alcista.where(
        (movimiento_alcista > movimiento_bajista) & (movimiento_alcista > 0), 0.0
    )
    dm_negativo = movimiento_bajista.where(
        (movimiento_bajista > movimiento_alcista) & (movimiento_bajista > 0), 0.0
    )
    cierre_previo = cerradas["close"].shift()
    rango_real = pd.concat([
        cerradas["high"] - cerradas["low"],
        (cerradas["high"] - cierre_previo).abs(),
        (cerradas["low"] - cierre_previo).abs(),
    ], axis=1).max(axis=1)
    atr_5m = rango_real.ewm(alpha=1 / 14, min_periods=14, adjust=False).mean()
    di_positivo = 100 * dm_positivo.ewm(alpha=1 / 14, min_periods=14, adjust=False).mean() / atr_5m
    di_negativo = 100 * dm_negativo.ewm(alpha=1 / 14, min_periods=14, adjust=False).mean() / atr_5m
    denominador = (di_positivo + di_negativo).replace(0, np.nan)
    dx = (100 * (di_positivo - di_negativo).abs() / denominador).fillna(0)
    adx = float(dx.ewm(alpha=1 / 14, min_periods=14, adjust=False).mean().iloc[-1])
    volumen_referencia = cerradas["volume"].iloc[-21:-1].mean()
    ratio_volumen = float(cerradas["volume"].iloc[-1] / volumen_referencia) if volumen_referencia > 0 else 0.0

    precio_referencia = float(velas_1m["close"].iloc[-1])
    atr_porcentual = (atr_macro / precio_referencia * 100) if precio_referencia > 0 else 0.0

    return {
        "techo": centro + desviacion * 2.0,
        "piso": centro - desviacion * 2.0,
        "centro": centro,
        "atr": atr_macro,
        "atr_pct": atr_porcentual,
        "tendencia": tendencia,
        "adx": adx if np.isfinite(adx) else 0.0,
        "ratio_volumen": ratio_volumen,
    }


def enviar_alerta_binaria(mensaje):
    if BINARIAS_ENABLED:
        threading.Thread(target=enviar_senal_telegram, args=(mensaje,), daemon=True).start()


def motor_senales_binarias():
    print(f"📡 Motor de señales binarias iniciado para {SIMBOLO_BINARIAS}.")
    exchange_binarias = _EXCHANGE_BITGET
    contexto = None
    ultimo_intento_contexto = 0.0
    ultima_actualizacion_contexto = 0.0
    historial_velas = []
    precios_ventana = []
    inicio_ventana = time.time()
    ultima_direccion = None
    ultima_ruptura = None

    while not DETENER_BOT.is_set():
        if not BINARIAS_ENABLED:
            historial_velas.clear()
            precios_ventana.clear()
            inicio_ventana = time.time()
            ultima_direccion = None
            ultima_ruptura = None
            time.sleep(1)
            continue

        try:
            ahora = time.time()
            if ahora - ultimo_intento_contexto >= 20:
                ultimo_intento_contexto = ahora
                try:
                    contexto = actualizar_contexto_binarias(exchange_binarias)
                    ultima_actualizacion_contexto = time.time()
                except Exception as error:
                    print(f"⚠️ No se pudo actualizar el contexto binario ({type(error).__name__}).")

            if not contexto or ahora - ultima_actualizacion_contexto > 40:
                time.sleep(2)
                continue

            ticker = exchange_binarias.fetch_ticker(SIMBOLO_BINARIAS)
            precio = float(ticker["last"])
            precios_ventana.append(precio)
            tiempo_ventana = time.time() - inicio_ventana
            if tiempo_ventana < 10:
                time.sleep(2)
                continue

            cierre = precios_ventana[-1]
            vela = {"high": max(precios_ventana), "low": min(precios_ventana), "close": cierre}
            historial_velas.append(vela)
            if len(historial_velas) > 50:
                historial_velas.pop(0)
            precios_ventana = []
            inicio_ventana = time.time()

            if len(historial_velas) < 15:
                continue

            velas_10s = pd.DataFrame(historial_velas)
            ema5 = velas_10s["close"].ewm(span=5, adjust=False).mean()
            ema13 = velas_10s["close"].ewm(span=13, adjust=False).mean()
            cci = calcular_cci_binarias(velas_10s)
            rsi = calcular_rsi_binarias(velas_10s)
            hora = hora_espana().strftime("%H:%M:%S")
            techo = contexto["techo"]
            piso = contexto["piso"]
            centro = contexto["centro"]
            adx = contexto["adx"]
            ratio_volumen = contexto["ratio_volumen"]
            atr = contexto["atr"]
            # ATR normalizado (% del precio) en vez de ATR absoluto en USD: así los umbrales de
            # expiración siguen siendo válidos aunque BTC cotice muy por encima o por debajo del
            # rango histórico de referencia (la volatilidad absoluta escala con el precio).
            atr_pct = contexto.get("atr_pct", 0.0)

            if atr_pct > 0.12:
                expiracion = "1 MINUTO"
            elif atr_pct > 0.07:
                expiracion = "2 MINUTOS"
            else:
                expiracion = "5 MINUTOS"

            # Filtro de momentum con RSI: evita abrir rupturas cuando el activo ya está
            # agotado (sobrecompra >75 para LONG, sobreventa <25 para SHORT), reduciendo
            # falsas señales en reversiones inminentes.
            rsi_valido_largo = rsi < 75
            rsi_valido_corto = rsi > 25

            ruptura_alcista = (
                cierre > techo and contexto["tendencia"] == "ALCISTA" and adx >= 25
                and ratio_volumen >= 1.3 and cci > 0 and rsi_valido_largo
            )
            ruptura_bajista = (
                cierre < piso and contexto["tendencia"] == "BAJISTA" and adx >= 25
                and ratio_volumen >= 1.3 and cci < 0 and rsi_valido_corto
            )
            duracion = "30-60 min" if adx >= 45 else "20-40 min" if adx >= 35 else "10-30 min"

            if not (piso <= cierre <= techo):
                if ruptura_alcista and ultima_ruptura != "LONG":
                    ultima_ruptura = "LONG"
                    enviar_alerta_binaria(
                        f"🚀 RUPTURA ALCISTA FUERTE | LONG\nSímbolo: {SIMBOLO_BINARIAS}\n"
                        f"Precio: {cierre:,.1f}\nHora: {hora}\nExpiración: {expiracion}\n"
                        f"ADX 5m: {adx:.1f} | Volumen: {ratio_volumen:.1f}x | RSI: {rsi:.1f}\n"
                        f"Duración orientativa: {duracion} (no garantizada)"
                    )
                elif ruptura_bajista and ultima_ruptura != "SHORT":
                    ultima_ruptura = "SHORT"
                    enviar_alerta_binaria(
                        f"🔻 RUPTURA BAJISTA FUERTE | SHORT\nSímbolo: {SIMBOLO_BINARIAS}\n"
                        f"Precio: {cierre:,.1f}\nHora: {hora}\nExpiración: {expiracion}\n"
                        f"ADX 5m: {adx:.1f} | Volumen: {ratio_volumen:.1f}x | RSI: {rsi:.1f}\n"
                        f"Duración orientativa: {duracion} (no garantizada)"
                    )
            else:
                ultima_ruptura = None

            ema5_actual, ema13_actual = ema5.iloc[-1], ema13.iloc[-1]
            ema5_previa, ema13_previa = ema5.iloc[-2], ema13.iloc[-2]
            if ema5_actual > ema13_actual and ema5_previa <= ema13_previa and ultima_direccion != "COMPRA":
                ultima_direccion = "COMPRA"
                if (
                    cierre <= centro and atr >= 35 and contexto["tendencia"] == "ALCISTA"
                    and cci > 0 and rsi_valido_largo and rsi >= 50
                ):
                    situacion = "RUPTURA ALCISTA" if cierre > techo else "REBOTE EN PISO"
                    enviar_alerta_binaria(
                        f"🚀 LONG CONFIRMADO\nSímbolo: {SIMBOLO_BINARIAS}\nPrecio: {cierre:,.1f}\n"
                        f"Hora: {hora}\nContexto: {situacion}\nRSI: {rsi:.1f}\nExpiración: {expiracion}"
                    )
            elif ema5_actual < ema13_actual and ema5_previa >= ema13_previa and ultima_direccion != "VENTA":
                ultima_direccion = "VENTA"
                if (
                    cierre >= centro and atr >= 35 and contexto["tendencia"] == "BAJISTA"
                    and cci < 0 and rsi_valido_corto and rsi <= 50
                ):
                    situacion = "RUPTURA BAJISTA" if cierre < piso else "REBOTE EN TECHO"
                    enviar_alerta_binaria(
                        f"🔻 SHORT CONFIRMADO\nSímbolo: {SIMBOLO_BINARIAS}\nPrecio: {cierre:,.1f}\n"
                        f"Hora: {hora}\nContexto: {situacion}\nRSI: {rsi:.1f}\nExpiración: {expiracion}"
                    )
            elif abs(ema5_actual - ema13_actual) > 2.0:
                ultima_direccion = None

        except Exception as error:
            print(f"⚠️ Error en motor de señales binarias ({type(error).__name__}).")
            time.sleep(2)


def telegram_listener():
    global AUTO_SIGNAL_ENABLED, BINARIAS_ENABLED
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
                    if text in {"/trump", "/mentetrump", "/trumpmind", "trump", "mentetrump"}:
                        enviar_parte_diario_mente_trump(chat_id=chat_id)
                if "callback_query" in update:
                    callback = update["callback_query"]
                    chat_id = callback.get("message", {}).get("chat", {}).get("id")
                    user_id = callback.get("from", {}).get("id")
                    data = callback.get("data", "")
                    if data == "senal_btc":
                        answer_url = f"https://api.telegram.org/bot{TOKEN_TELEGRAM}/answerCallbackQuery"
                        requests.post(answer_url, json={"callback_query_id": callback.get("id"), "text": "Generando señal BTC..."}, timeout=10)
                        generar_senal_manual(chat_id=chat_id, mercado_seleccionado="btc", requester_id=user_id)
                    elif data in {"toggle_auto", "toggle_binarias"}:
                        if not es_admin_del_canal(user_id):
                            answer_url = f"https://api.telegram.org/bot{TOKEN_TELEGRAM}/answerCallbackQuery"
                            requests.post(answer_url, json={"callback_query_id": callback.get("id"), "text": "Solo administradores pueden cambiar estos estados."}, timeout=10)
                        else:
                            if data == "toggle_auto":
                                AUTO_SIGNAL_ENABLED = not AUTO_SIGNAL_ENABLED
                                estado = "ON" if AUTO_SIGNAL_ENABLED else "OFF"
                                detalle = f"Señales automáticas ahora {estado}."
                            else:
                                BINARIAS_ENABLED = not BINARIAS_ENABLED
                                estado = "ON" if BINARIAS_ENABLED else "OFF"
                                detalle = f"Señales binarias ahora {estado}."
                            requests.post(
                                f"https://api.telegram.org/bot{TOKEN_TELEGRAM}/answerCallbackQuery",
                                json={"callback_query_id": callback.get("id"), "text": detalle},
                                timeout=10,
                            )
                            actualizar_teclado_callback(callback)
                            enviar_senal_telegram(f"⚙️ {detalle} (admin {user_id}).", chat_id=CHAT_ID_CANAL)
        except Exception as e:
            print(f"⚠️ Error en listener de Telegram: {e}")
        time.sleep(2)


def motor_de_trading():
    print("🚀 Iniciando motor analítico duplicador de TradingView...")
    print(f"📊 Señales binarias: {'ON' if BINARIAS_ENABLED else 'OFF'}.")
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

            for mercado in CONFIGURACIONES_MERCADO:
                if not any(op["mercado"] == mercado["nombre"] for op in OPERACIONES_ABIERTAS):
                    continue
                datos_seguimiento = obtener_datos_binance(mercado["symbol"], "1m", limit=5)
                if datos_seguimiento:
                    cierres_seguimiento = [float(vela[4]) for vela in datos_seguimiento]
                    actualizar_operaciones_abiertas(cierres_seguimiento, datos_seguimiento, mercado)

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

            global ULTIMO_PARTE_TRUMP_ENVIADO
            hoy_str = hora_actual.strftime("%Y-%m-%d")
            if hora_actual.strftime("%H:%M") == PARTE_TRUMP_HORA and ULTIMO_PARTE_TRUMP_ENVIADO != hoy_str:
                try:
                    enviar_parte_diario_mente_trump(chat_id=CHAT_ID_CANAL)
                    ULTIMO_PARTE_TRUMP_ENVIADO = hoy_str
                except Exception as error:
                    print(f"⚠️ No se pudo enviar el parte diario de 'la mente de Trump': {error}")

            time.sleep(60)
        except Exception as e:
            print(f"⚠️ Error en el motor de trading: {e}")
            time.sleep(30)


if __name__ == '__main__':
    hilo_trading = threading.Thread(target=motor_de_trading)
    hilo_trading.daemon = True
    hilo_trading.start()

    hilo_binarias = threading.Thread(target=motor_senales_binarias)
    hilo_binarias.daemon = True
    hilo_binarias.start()

    hilo_listener = threading.Thread(target=telegram_listener)
    hilo_listener.daemon = True
    hilo_listener.start()

    puerto = int(os.getenv("PORT", 10000))
    app.run(host='0.0.0.0', port=puerto)
