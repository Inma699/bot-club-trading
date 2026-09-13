import os
import asyncio
import yfinance as yf
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

# LISTA EXPANDIDA: 30 Small Caps de Máxima Volatilidad y Catalizadores
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

def obtener_datos_e_historico_noticias(ticker):
    """Extrae datos camuflándose como navegador para evitar bloqueos en la nube."""
    accion = yf.Ticker(ticker)
    
    # Cabecera de agente de usuario para simular Google Chrome real
    yf.utils.requests_session.headers.update({
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
    })
    
    # Capturar noticias del ticker de forma directa
    noticias = accion.news
    titulares = []
    if noticias:
        for n in noticias[:4]:
            titulares.append(f"- TÍTULO: {n.get('title')} | RESUMEN: {n.get('snippet', 'Sin resumen')}")
    
    texto_noticias = "\n".join(titulares) if titulares else "Sin noticias publicadas recientemente."
    
    # Extraer métricas financieras con sistema de contingencia contra bloqueos de IP
    try:
        info_rapida = accion.fast_info
        precio = info_rapida.get("last_price", 0)
        market_cap = info_rapida.get("market_cap", 0)
        volumen_actual = info_rapida.get("last_volume", 0)
        volumen_medio = info_rapida.get("three_month_average_volume", 1)
    except:
        info_lenta = accion.info
        precio = info_lenta.get("currentPrice", 0)
        market_cap = info_lenta.get("marketCap", 0)
        volumen_actual = info_lenta.get("volume", 0)
        volumen_medio = info_lenta.get("averageVolume", 1)
    
    return {
        "Nombre": ticker,
        "Precio": precio,
        "MarketCap": market_cap,
        "Float": "Bajo (Estructura Small Cap)",
        "Volumen_Actual": volumen_actual,
        "Volumen_Medio": volumen_medio,
        "Noticias": texto_noticias
    }

async def tarea_escanear_mercado():
    """Bucle persistente en segundo plano que analiza los 30 tickers en Render."""
    while True:
        print(f"🚀 [NUBE] Iniciando radar de catalizadores para {len(WANTED_LIST)} empresas...")
        
        for ticker in WANTED_LIST:
            try:
                datos = obtener_datos_e_historico_noticias(ticker)
                
                # Si no hay prensa que evaluar, saltamos inmediatamente para ahorrar cuota
                if datos["Noticias"] == "Sin noticias publicadas recientemente.":
                    continue
                
                prompt = (
                    f"Actúa como un gestor de fondos de cobertura institucional (Hedge Fund) experto en microcaps y momentum violento.\n"
                    f"Evaluamos la empresa {ticker} con una Capitalización de ${datos['MarketCap']:,}.\n\n"
                    f"Analiza si los siguientes titulares de prensa recientes contienen un CATALIZADOR DE IMPACTO MASIVO "
                    f"capaz de multiplicar el precio por 10 (+1,000%) debido a su baja capitalización de mercado:\n"
                    f"{datos['Noticias']}\n\n"
                    f"¿Qué buscamos?: Aprobaciones FDA, contratos históricos con el Gobierno/NASA, alianzas comerciales masivas con "
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
                
                # Pausa de 6 segundos entre acciones. Evita que Google nos aplique un ban por velocidad en el plan gratuito
                await asyncio.sleep(6)
                
            except Exception as e:
                print(f"⚠️ Error procesando la empresa {ticker}: {e}")
        
        print("💤 Escáner de 30 tickers completado. Durmiendo 15 minutos en la nube...")
        await asyncio.sleep(900)  # 900 segundos = Esperar 15 minutos para la próxima ronda

@app.on_event("startup")
async def inicio_servidor():
    """Ejecuta el bucle de escaneo de forma automática tan pronto como Render activa el servicio."""
    asyncio.create_task(tarea_escanear_mercado())

@app.get("/")
def ruta_salud():
    """Ruta de control web obligatoria para que Render verifique que el bot no se ha congelado."""
    return {"status": "online", "club": "ClubMSharks", "monitored_tickers": len(WANTED_LIST)}
