import os
import asyncio
import requests
from dotenv import load_dotenv
from telegram import Bot
import google.genai as google_ai
from fastapi import FastAPI

# Cargar variables de entorno del panel de Render
load_dotenv()

# Inicializar FastAPI para mantener Render activo
app = FastAPI(title="Shark Small Cap Scanner Cloud")

# Inicializar clientes de comunicación e IA
bot_telegram = Bot(token=os.getenv("TELEGRAM_TOKEN"))
client_gemini = google_ai.Client(api_key=os.getenv("GEMINI_API_KEY"))

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

def obtener_datos_antibloqueo(ticker):
    """Extrae datos numéricos y noticias usando peticiones HTTP directas bien formateadas."""
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36',
        'Accept': 'application/json'
    }
    
    # 1. Recuperación de precio y estadísticas de volumen (Rutas Web Corregidas)
    url_quote = "https://yahoo.com"
    params_quote = {"symbols": ticker}
    
    precio, market_cap, volumen_actual, volumen_medio = 0, 0, 0, 1
    
    try:
        response = requests.get(url_quote, headers=headers, params=params_quote, timeout=10)
        if response.status_code == 200:
            data = response.json()
            result = data.get("quoteResponse", {}).get("result", [])
            if result:
                res = result[0]
                precio = res.get("regularMarketPrice", 0)
                market_cap = res.get("marketCap", 0)
                volumen_actual = res.get("regularMarketVolume", 0)
                volumen_medio = res.get("averageDailyVolume3Month", 1)
    except Exception as e:
        print(f"⚠️ Alerta en cotización de {ticker}: {e}")

    # 2. Recuperación de prensa mediante el motor de búsqueda estructurado
    url_news = "https://yahoo.com"
    params_news = {"q": ticker, "newsCount": 4}
    titulares = []
    
    try:
        response_news = requests.get(url_news, headers=headers, params=params_news, timeout=10)
        if response_news.status_code == 200:
            data_news = response_news.json()
            news_list = data_news.get("news", [])
            for n in news_list:
                titulares.append(f"- TÍTULO: {n.get('title')} | RESUMEN: {n.get('uuid', 'Análisis de mercado')}")
    except Exception as e:
        print(f"⚠️ Alerta en noticias de {ticker}: {e}")
        
    texto_noticias = "\n".join(titulares) if titulares else "Sin noticias publicadas recientemente."
    
    return {
        "Nombre": ticker,
        "Precio": precio,
        "MarketCap": market_cap,
        "Float": "Estructura Small Cap (Bajo Float)",
        "Volumen_Actual": volumen_actual,
        "Volumen_Medio": volumen_medio,
        "Noticias": texto_noticias
    }

async def tarea_escanear_mercado():
    """Bucle persistente en segundo plano que analiza los 30 tickers en la nube sin cortes."""
    while True:
        print(f"🚀 [NUBE] Iniciando radar de catalizadores para {len(WANTED_LIST)} empresas...")
        
        for ticker in WANTED_LIST:
            try:
                datos = obtener_datos_antibloqueo(ticker)
                
                # Si las APIs devolvieron datos vacíos o no hay prensa, pasamos de largo de forma segura
                if datos["Noticias"] == "Sin noticias publicadas recientemente." or datos["Precio"] == 0:
                    continue
                
                prompt = (
                    f"Actúa como un gestor de fondos de cobertura institucional (Hedge Fund) experto en microcaps y momentum violento.\n"
                    f"Evaluamos la empresa {ticker} con una Capitalización de ${datos['MarketCap']:,}.\n\n"
                    f"Analiza si los siguientes titulares de prensa recientes contienen un CATALIZADOR DE IMPACTO MASIVO "
                    f"capaz de multiplicar el precio por 10 (+1,000%) debido a su baja capitalización de mercado:\n"
                    f"{datos['Noticias']}\n\n"
                    f"¿Qué buscamos?: Aprobaciones FDA, contratos históricos con el Gobierno o la NASA, alianzas comerciales masivas con "
                    f"gigantes Big Tech (Nvidia, Microsoft, Apple) o fusiones corporativas estratégicas de gran valor.\n\n"
                    f"REGLA DE ORO: Si las noticias son análisis ordinarios, movimientos del mercado de rutina, opiniones o reportes comunes, "
                    f"responde ÚNICAMENTE con la palabra: OMITIR.\n\n"
                    f"Si califica para una explosión potencial masiva, redacta una ALERTA CRÍTICA PARA CLUBMSHARKS indicando detalladamente el catalizador, "
                    f"análisis del volumen operativo hoy ({datos['Volumen_Actual']:,} vs {datos['Volumen_Medio']:,}), precio actual (${datos['Precio']}) y plan de acción de entrada rápida en DAS Trader Pro utilizando formato Markdown limpio con emojis."
                )
                
                response = client_gemini.models.generate_content(
                    model="gemini-3.6-flash",
                    contents=prompt,
                )
                
                veredicto = response.text.strip()
                
                if "OMITIR" in veredicto and len(veredicto) < 15:
                    print(f"ℹ️ {ticker}: Sin catalizadores históricos. Omitido.")
                else:
                    print(f"🔥 ¡ALERTA MÁXIMA EN {ticker}! Distribuyendo señal a Telegram...")
                    await enviar_telegram(veredicto)
                
                # Pausa de 5 segundos entre acciones para cumplir los requerimientos de la API de Google
                await asyncio.sleep(5)
                
            except Exception as e:
                print(f"⚠️ Error procesando la empresa {ticker}: {e}")
        
        print("💤 Escáner de 30 tickers completado. Durmiendo 15 minutos en la nube...")
        await asyncio.sleep(900)  # Esperar 15 minutos para la próxima ronda

@app.on_event("startup")
async def inicio_servidor():
    """Ejecuta el bucle de escaneo de forma automática tan pronto como Render activa el servicio."""
    asyncio.create_task(tarea_escanear_mercado())

@app.get("/")
def ruta_salud():
    """Ruta de control web obligatoria para que Render verifique que el bot sigue vivo."""
    return {"status": "online", "club": "ClubMSharks", "monitored_tickers": len(WANTED_LIST)}
