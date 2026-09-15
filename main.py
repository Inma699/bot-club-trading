import os
import asyncio
import time
from io import StringIO
import requests
import re
import pandas as pd
from dotenv import load_dotenv
import yfinance as yf
from telegram import Bot, InlineKeyboardButton, InlineKeyboardMarkup, Update
import google.genai as google_ai
from fastapi import FastAPI, Request

# Cargar variables de entorno del panel de Render
load_dotenv()

# Inicializar FastAPI para mantener Render activo
app = FastAPI(title="Shark Small Cap Scanner Cloud")

# Inicializar clientes de comunicación e IA
bot_telegram = Bot(token=os.getenv("TELEGRAM_TOKEN"))
client_gemini = google_ai.Client(api_key=os.getenv("GEMINI_API_KEY"))
telegram_webhook_secret = os.getenv("TELEGRAM_WEBHOOK_SECRET", "")
analisis_en_curso = False

# LISTA MAESTRA: 30 Small Caps de Máxima Volatilidad y Catalizadores
WANTED_LIST = [
    # Inteligencia Artificial y Robótica
    "SOUN", "SERV", "BBAI", "AUST", "RGTI",
    # Aeroespacial, Satélites y Defensa
    "LUNR", "RKLB", "SIDU", "LLAP",
    # Energía, Uranio y Baterías
    "SMR", "AMPX", "ENVX", "OKLO", "LEU",
    # Minería Bitcoin y Criptoactivos
    "MARA", "RIOT", "CLSK", "WULF", "IREN",
    # Biotecnología y Salud (Altos Catalizadores FDA)
    "HIMS", "CRBU", "NTLA", "EDIT", "BEAM",
    # Vehículos Eléctricos y Almacenamiento
    "BLNK", "PLUG", "CHPT", "QS",
    # Otras Microcaps Agresivas por Noticias
    "BURU", "HOLO"
]

async def enviar_telegram(mensaje):
    """Envía las alertas críticas directamente a tu bot de Telegram."""
    try:
        await bot_telegram.send_message(
            chat_id=os.getenv("TELEGRAM_CHAT_ID"), 
            text=mensaje, 
            parse_mode="Markdown"
        )
    except Exception as e:
        print(f"❌ Error al enviar mensaje a Telegram: {e}")

def calcular_metrica_ticker(ticker):
    """Obtiene métricas objetivas para ordenar el universo antes del análisis de IA."""
    try:
        datos = yf.download(ticker, period="3mo", interval="1d", auto_adjust=False, progress=False, threads=False)
        if datos.empty or len(datos) < 20:
            ahora = int(time.time())
            datos = obtener_datos_yahoo_directos(ticker, ahora)
        if datos.empty or len(datos) < 20:
            print(f"⚠️ {ticker}: Yahoo no devolvió al menos 20 sesiones.")
            return None

        if hasattr(datos.columns, "levels"):
            datos.columns = datos.columns.get_level_values(0)
        cierre = datos["Close"].dropna()
        maximo = datos["High"].dropna()
        minimo = datos["Low"].dropna()
        volumen = datos["Volume"].dropna()
        precio = float(cierre.iloc[-1])
        rango_real = (maximo - minimo).abs()
        atr = float(rango_real.rolling(14).mean().iloc[-1])
        if not precio or not atr or atr <= 0:
            return None

        volumen_medio = float(volumen.iloc[-21:-1].mean())
        volumen_relativo = float(volumen.iloc[-1] / volumen_medio) if volumen_medio else 0
        momentum_20d = float((precio / float(cierre.iloc[-21]) - 1) * 100)
        volatilidad = float(atr / precio * 100)
        puntuacion = momentum_20d + min(volumen_relativo, 5) * 2 + min(volatilidad, 20)
        return {
            "ticker": ticker,
            "precio": precio,
            "atr": atr,
            "volumen_relativo": volumen_relativo,
            "momentum_20d": momentum_20d,
            "volatilidad": volatilidad,
            "puntuacion": puntuacion,
        }
    except Exception as error:
        print(f"⚠️ Fallo yfinance en {ticker}: {error}. Probando Yahoo directo.")
        try:
            datos = obtener_datos_yahoo_directos(ticker)
            if not datos.empty and len(datos) >= 20:
                return calcular_metrica_con_datos(ticker, datos)
        except Exception as fallback_error:
            print(f"⚠️ Fallo Yahoo directo en {ticker}: {fallback_error}")
        return None

def obtener_datos_yahoo_directos(ticker, ahora=None):
    """Segundo proveedor usando el endpoint chart de Yahoo, sin el scraper de yfinance."""
    ahora = ahora or int(time.time())
    respuesta = requests.get(
        f"https://query1.finance.yahoo.com/v8/finance/chart/{ticker}",
        params={"period1": ahora - 90 * 86400, "period2": ahora, "interval": "1d", "events": "history"},
        headers={"User-Agent": "Mozilla/5.0"},
        timeout=15,
    )
    try:
        respuesta.raise_for_status()
        resultado = respuesta.json()["chart"]["result"][0]
        cotizaciones = resultado["indicators"]["quote"][0]
        fechas = pd.to_datetime(resultado["timestamp"], unit="s")
        return pd.DataFrame(cotizaciones, index=fechas).dropna(subset=["close", "high", "low", "volume"])
    except (requests.RequestException, ValueError, KeyError, TypeError, IndexError):
        return obtener_datos_stooq(ticker)

def obtener_datos_stooq(ticker):
    """Respaldo CSV para cuando Yahoo bloquea el tráfico del servicio cloud."""
    respuesta = requests.get(
        f"https://stooq.com/q/d/l/?s={ticker.lower()}.us&i=d&d=,",
        headers={"User-Agent": "Mozilla/5.0"},
        timeout=15,
    )
    respuesta.raise_for_status()
    datos = pd.read_csv(StringIO(respuesta.text))
    if datos.empty or "Date" not in datos.columns:
        return pd.DataFrame()
    datos["Date"] = pd.to_datetime(datos["Date"], errors="coerce")
    datos = datos.dropna(subset=["Date"]).set_index("Date")
    return datos.rename(columns={"Close": "close", "High": "high", "Low": "low", "Volume": "volume"})

def calcular_metrica_con_datos(ticker, datos):
    datos = datos.rename(columns={
        "close": "Close", "high": "High", "low": "Low", "volume": "Volume",
        "CLOSE": "Close", "HIGH": "High", "LOW": "Low", "VOLUME": "Volume",
    })
    cierre = datos["Close"].dropna()
    maximo = datos["High"].dropna()
    minimo = datos["Low"].dropna()
    volumen = datos["Volume"].dropna()
    precio = float(cierre.iloc[-1])
    atr = float((maximo - minimo).abs().rolling(14).mean().iloc[-1])
    if not precio or not atr or atr <= 0:
        return None
    volumen_medio = float(volumen.iloc[-21:-1].mean())
    volumen_relativo = float(volumen.iloc[-1] / volumen_medio) if volumen_medio else 0
    momentum_20d = float((precio / float(cierre.iloc[-21]) - 1) * 100)
    volatilidad = float(atr / precio * 100)
    return {
        "ticker": ticker, "precio": precio, "atr": atr,
        "volumen_relativo": volumen_relativo, "momentum_20d": momentum_20d,
        "volatilidad": volatilidad,
        "puntuacion": momentum_20d + min(volumen_relativo, 5) * 2 + min(volatilidad, 20),
    }

def seleccionar_mejor_small_cap():
    """Selecciona la mejor candidata disponible en el universo configurado."""
    metricas = []
    try:
        datos_agrupados = yf.download(
            WANTED_LIST,
            period="3mo",
            interval="1d",
            auto_adjust=False,
            progress=False,
            threads=False,
            group_by="ticker",
        )
        if not datos_agrupados.empty and isinstance(datos_agrupados.columns, pd.MultiIndex):
            primer_nivel = set(datos_agrupados.columns.get_level_values(0))
            nivel_ticker = 0 if any(ticker in primer_nivel for ticker in WANTED_LIST) else 1
            for ticker in WANTED_LIST:
                try:
                    datos_ticker = datos_agrupados.xs(ticker, axis=1, level=nivel_ticker)
                    metrica = calcular_metrica_con_datos(ticker, datos_ticker)
                    if metrica:
                        metricas.append(metrica)
                except (KeyError, IndexError, TypeError, ValueError):
                    continue
    except Exception as error:
        print(f"⚠️ Descarga agrupada no disponible: {error}")

    faltantes = [ticker for ticker in WANTED_LIST if not any(metrica["ticker"] == ticker for metrica in metricas)]
    metricas.extend(calcular_metrica_ticker(ticker) for ticker in faltantes)
    disponibles = [metrica for metrica in metricas if metrica]
    print(f"📊 Datos válidos: {len(disponibles)}/{len(WANTED_LIST)} tickers.")
    return max(disponibles, key=lambda metrica: metrica["puntuacion"]) if disponibles else None

async def generar_analisis_bajo_demanda():
    metrica = await asyncio.to_thread(seleccionar_mejor_small_cap)
    if not metrica:
        return "No hay datos de mercado disponibles ahora. Inténtalo de nuevo en unos minutos."

    entrada = metrica["precio"]
    atr = metrica["atr"]
    stop_loss = max(0.01, entrada - 1.5 * atr)
    take_profit_1 = entrada + 2 * atr
    take_profit_2 = entrada + 3 * atr
    noticias = await asyncio.to_thread(obtener_noticias_texto_plano, metrica["ticker"])
    prompt = (
        "Analiza de forma prudente esta small cap para trading intradía o swing. "
        "No prometas rentabilidad ni uses lenguaje de certeza. Resume catalizadores, riesgos, "
        "liquidez y qué invalidaría la operación.\n"
        f"Ticker: {metrica['ticker']}\nPrecio actual aproximado: {entrada:.4f}\n"
        f"Noticias: {noticias}\n"
        "Devuelve un resumen breve en español, sin inventar datos."
    )
    try:
        respuesta = await asyncio.to_thread(
            client_gemini.models.generate_content,
            model="gemini-3.6-flash",
            contents=prompt,
        )
        contexto = respuesta.text.strip()
    except Exception as error:
        print(f"⚠️ Error generando análisis bajo demanda: {error}")
        contexto = "No se pudo obtener el contexto de noticias/IA; revisa los datos antes de operar."

    return (
        "📊 MEJOR CANDIDATA DEL MOMENTO\n\n"
        f"🔹 Ticker: {metrica['ticker']}\n"
        f"💵 Precio referencia: ${entrada:.4f}\n"
        f"🎯 TP1 (2 ATR): ${take_profit_1:.4f}\n"
        f"🎯 TP2 (3 ATR): ${take_profit_2:.4f}\n"
        f"🛑 SL (1,5 ATR): ${stop_loss:.4f}\n"
        f"📈 Momentum 20 días: {metrica['momentum_20d']:+.2f}%\n"
        f"📦 Volumen relativo: {metrica['volumen_relativo']:.2f}x\n"
        f"🌊 Volatilidad ATR: {metrica['volatilidad']:.2f}%\n\n"
        f"🧠 CONTEXTO\n{contexto}\n\n"
        "⚠️ Niveles orientativos calculados con ATR, no son recomendación financiera. "
        "Comprueba cotización, spread, volumen y disponibilidad del ticker en Interactive Brokers antes de enviar una orden."
    )

async def publicar_menu_telegram():
    chat_id = os.getenv("TELEGRAM_CHAT_ID")
    if not chat_id:
        print("⚠️ TELEGRAM_CHAT_ID no está configurado; no se publicará el botón.")
        return
    teclado = InlineKeyboardMarkup([[InlineKeyboardButton(
        "🔎 Solicitar mejor small cap del momento", callback_data="mejor_small_cap"
    )]])
    try:
        await bot_telegram.send_message(
            chat_id=chat_id,
            text="Pulsa el botón para analizar la small cap con mejor combinación de momentum y actividad.",
            reply_markup=teclado,
        )
    except Exception as error:
        print(f"❌ Error publicando el botón de Telegram: {error}")

async def procesar_webhook_telegram(request: Request):
    global analisis_en_curso
    if telegram_webhook_secret and request.headers.get("X-Telegram-Bot-Api-Secret-Token") != telegram_webhook_secret:
        return {"ok": False}
    update = Update.de_json(await request.json(), bot_telegram)
    if not update.callback_query or update.callback_query.data != "mejor_small_cap":
        return {"ok": True}
    await update.callback_query.answer("Analizando el mercado...")
    if analisis_en_curso:
        await update.callback_query.message.reply_text("⏳ Ya hay un análisis en curso. Espera unos segundos.")
        return {"ok": True}
    analisis_en_curso = True
    asyncio.create_task(enviar_analisis_bajo_demanda(update.callback_query.message))
    return {"ok": True}

async def enviar_analisis_bajo_demanda(mensaje):
    try:
        await mensaje.reply_text("⏳ Analizando las candidatas disponibles...")
        await mensaje.reply_text(await generar_analisis_bajo_demanda())
    except Exception as error:
        print(f"❌ Error enviando análisis solicitado: {error}")
        await mensaje.reply_text("❌ No se pudo completar el análisis. Revisa los logs de Render.")
    finally:
        global analisis_en_curso
        analisis_en_curso = False

def obtener_noticias_texto_plano(ticker):
    """Extrae las noticias usando expresiones regulares sobre el texto plano, evitando errores de XML."""
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36'
    }
    
    url_base = "https://yahoo.com"
    parametros = {"s": str(ticker).strip().upper()}
    titulares = []
    
    try:
        response = requests.get(url_base, headers=headers, params=parametros, timeout=12)
        if response.status_code == 200:
            texto = response.text
            # Buscamos las etiquetas <title> dentro del texto sin usar un lector estricto de XML
            matches = re.findall(r'<title>(.*?)</title>', texto)
            
            # El primer match suele ser el título del feed global (ej: "Yahoo Finance: SOUN"), lo saltamos
            for title in matches[1:5]:
                # Limpieza rápida de etiquetas basura si las hubiera
                title_limpio = re.sub(r'<!\[CDATA\[(.*?)\]\]>', r'\1', title)
                titulares.append(f"- TÍTULO: {title_limpio}")
                
    except Exception as e:
        print(f"⚠️ Error de lectura de texto en {ticker}: {e}")
        
    texto_noticias = "\n".join(titulares) if titulares else "Sin noticias publicadas recientemente."
    return texto_noticias

async def tarea_escanear_mercado():
    """Bucle de escaneo continuo en la nube basado en extracción segura por texto plano."""
    while True:
        print(f"🚀 [NUBE ESPAÑA] Radar robusto activado para {len(WANTED_LIST)} empresas...")
        
        for ticker in WANTED_LIST:
            try:
                print(f"📡 Buscando prensa para {ticker}...")
                noticias_empresa = await asyncio.to_thread(obtener_noticias_texto_plano, ticker)
                
                if noticias_empresa == "Sin noticias publicadas recientemente.":
                    continue
                
                prompt = (
                    f"Actúa como un gestor de fondos de cobertura institucional (Hedge Fund) experto en microcaps y momentum violento.\n"
                    f"Evaluamos la empresa {ticker}.\n\n"
                    f"Analiza si los siguientes titulares de prensa contienen un CATALIZADOR DE IMPACTO MASIVO "
                    f"capaz de multiplicar el precio por 10 (+1,000%) debido a su baja capitalización de mercado:\n"
                    f"{noticias_empresa}\n\n"
                    f"¿Qué buscamos de forma estricta?: Aprobaciones regulatorias FDA, contratos millonarios con gobiernos o agencias "
                    f"espaciales, alianzas de desarrollo masivo con gigantes Big Tech (Nvidia, Microsoft, Apple) o adquisiciones directas.\n\n"
                    f"REGLA DE ORO: Si las noticias son análisis ordinarios, movimientos diarios comunes, resúmenes semanales de rutina o blogs de opinión, "
                    f"responde ÚNICAMENTE con la palabra: OMITIR.\n\n"
                    f"Si califica para una explosión potencial masiva, redacta una ALERTA CRÍTICA PARA CLUBMSHARKS indicando de forma detallada el catalizador, "
                    f"los puntos clave del informe y un plan de acción sugerido para ejecutar entradas de momentum en tu terminal DAS Trader Pro. Usa formato Markdown limpio con emojis."
                )
                
                response = await asyncio.to_thread(
                    client_gemini.models.generate_content,
                    model="gemini-3.6-flash",
                    contents=prompt,
                )
                
                veredicto = response.text.strip()
                
                if "OMITIR" in veredicto and len(veredicto) < 15:
                    print(f"ℹ️ {ticker}: Evaluado. Sin catalizadores extremos de grado +1,000%.")
                else:
                    print(f"🔥 ¡CATALIZADOR DE ALTO IMPACTO EN {ticker}! Distribuyendo señal a Telegram...")
                    await enviar_telegram(veredicto)
                
                # Pausa reglamentaria para proteger las llamadas gratuitas de Gemini
                await asyncio.sleep(6)
                
            except Exception as e:
                print(f"⚠️ Error procesando la consulta en {ticker}: {e}")
        
        print("💤 Ronda de 30 tickers completada sin errores. Durmiendo 15 minutos en la nube...")
        await asyncio.sleep(900)

@app.on_event("startup")
async def inicio_servidor():
    """Lanza la tarea en segundo plano al arrancar la app web."""
    url_render = os.getenv("RENDER_EXTERNAL_URL")
    if url_render:
        try:
            webhook_url = f"{url_render.rstrip('/')}/telegram/webhook"
            opciones_webhook = {"url": webhook_url}
            if telegram_webhook_secret:
                opciones_webhook["secret_token"] = telegram_webhook_secret
            await bot_telegram.set_webhook(**opciones_webhook)
            await publicar_menu_telegram()
            print(f"✅ Webhook de Telegram activo en {webhook_url}")
        except Exception as error:
            print(f"❌ No se pudo configurar el webhook de Telegram: {error}")
    else:
        print("⚠️ RENDER_EXTERNAL_URL no está configurada; el botón no recibirá clics.")
    asyncio.create_task(tarea_escanear_mercado())

@app.api_route("/", methods=["GET", "HEAD"])
def ruta_salud():
    """Ruta web de verificación obligatoria adaptada para evitar alertas en Render."""
    return {"status": "online", "tracker": "Regex Plain-Text Blindado", "monitored_tickers": len(WANTED_LIST)}

@app.post("/telegram/webhook")
async def telegram_webhook(request: Request):
    return await procesar_webhook_telegram(request)

