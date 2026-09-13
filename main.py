import os
import asyncio
import yfinance as yf
from dotenv import load_dotenv
from telegram import Bot
import google.genai as google_ai
from fastapi import FastAPI, BackgroundTasks

# Cargar variables de entorno
load_dotenv()

# Inicializar FastAPI para mantener Render activo
app = FastAPI(title="Shark Small Cap Scanner Cloud")

# Inicializar clientes
bot_telegram = Bot(token=os.getenv("TELEGRAM_TOKEN"))
client_gemini = google_ai.Client(api_key=os.getenv("GEMINI_API_KEY"))

WANTED_LIST = ["LUNR", "SERV", "SOUN", "SMR", "AMPX", "ENVX", "MARA", "HIMS", "BURU"]

async def enviar_telegram(mensaje):
    try:
        await bot_telegram.send_message(
            chat_id=os.getenv("TELEGRAM_CHAT_ID"), 
            text=mensaje, 
            parse_mode="Markdown"
        )
    except Exception as e:
        print(f"❌ Error Telegram: {e}")

def obtener_datos_e_historico_noticias(ticker):
    accion = yf.Ticker(ticker)
    noticias = accion.news
    titulares = []
    if noticias:
        for n in noticias[:5]:
            titulares.append(f"- TÍTULO: {n.get('title')} | RESUMEN: {n.get('snippet', 'Sin resumen')}")
    
    texto_noticias = "\n".join(titulares) if titulares else "Sin noticias publicadas recientemente."
    info = accion.info
    
    return {
        "Nombre": info.get("longName", "Desconocido"),
        "Precio": info.get("currentPrice", 0),
        "MarketCap": info.get("marketCap", 0) or 0,
        "Float": info.get("floatShares", 0) or "Bajo",
        "Volumen_Actual": info.get("volume", 0) or 0,
        "Volumen_Medio": info.get("averageVolume", 1) or 1,
        "Noticias": texto_noticias
    }

async def tarea_escanear_mercado():
    """Bucle infinito que se ejecuta en segundo plano en la nube."""
    while True:
        print("🚀 [NUBE] Iniciando radar de catalizadores masivos (+1,000%)...")
        for ticker in WANTED_LIST:
            try:
                datos = obtener_datos_e_historico_noticias(ticker)
                if datos["Noticias"] == "Sin noticias publicadas recientemente.":
                    continue
                
                prompt = (
                    f"Actúa como un gestor de fondos de cobertura institucional (Hedge Fund) experto en microcaps y momentum violento.\n"
                    f"Evaluamos la empresa {ticker} ({datos['Nombre']}) con una Capitalización de ${datos['MarketCap']:,}.\n\n"
                    f"Analiza si los siguientes titulares contienen un CATALIZADOR DE IMPACTO MASIVO capaz de multiplicar el precio por 10 (+1,000%):\n"
                    f"{datos['Noticias']}\n\n"
                    f"REGLA DE ORO: Si las noticias son ordinarias o comunes, responde ÚNICAMENTE con la palabra: OMITIR.\n\n"
                    f"Si califica para una explosión masiva, redacta una ALERTA CRÍTICA PARA CLUBMSHARKS destacando el catalizador, "
                    f"análisis de volumen, precio actual (${datos['Precio']}) y plan de acción en DAS Trader Pro usando Markdown."
                )
                
                response = client_gemini.models.generate_content(
                    model="gemini-3.6-flash",
                    contents=prompt,
                )
                
                veredicto = response.text.strip()
                if "OMITIR" in veredicto and len(veredicto) < 15:
                    print(f"ℹ️ {ticker}: Omitido.")
                else:
                    print(f"🔥 ¡CATALIZADOR ENCONTRADO EN {ticker}! Enviando...")
                    await enviar_telegram(veredicto)
                
                await asyncio.sleep(5)  # Respetar Rate Limits del plan gratuito
                
            except Exception as e:
                print(f"⚠️ Error en {ticker}: {e}")
        
        print("💤 Escáner completado. Durmiendo 15 minutos...")
        await asyncio.sleep(900)  # 900 segundos = 15 minutos

@app.on_event("startup")
async def inicio_servidor():
    """Lanza de forma automática el bot en segundo plano en cuanto Render enciende el servicio."""
    asyncio.create_task(tarea_escanear_mercado())

@app.get("/")
def ruta_salud():
    """Ruta web obligatoria para que Render sepa que la aplicación sigue viva."""
    return {"status": "online", "bot": "ClubMSharks Scanner Activo"}
