import os
import asyncio
import requests
import re
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
                noticias_empresa = obtener_noticias_texto_plano(ticker)
                
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
                
                response = client_gemini.models.generate_content(
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
    asyncio.create_task(tarea_escanear_mercado())

@app.get("/")
def ruta_salud():
    """Control de vida del Web Service de Render."""
    return {"status": "online", "tracker": "Regex Plain-Text Blindado", "monitored_tickers": len(WANTED_LIST)}
