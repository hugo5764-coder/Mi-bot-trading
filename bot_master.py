import time
import logging
from datetime import datetime, timezone, timedelta
import requests
import pandas as pd
import numpy as np
import yfinance as yf

# =====================================================================
# BLOQUE 1: CONFIGURACIÓN
# =====================================================================

NTFY_TOPIC = "hugo_bot_trading_2026"
NTFY_URL = f"https://ntfy.sh/{NTFY_TOPIC}"

PARES_A_ANALIZAR = ["USDJPY", "USDCAD", "EURUSD", "GBPJPY"]
TEMPORALIDAD = "15m" 
VENCIMIENTO = 15      
FUERZA_MINIMA = 65.0  
CONFIRMACIONES_MINIMAS = 4 

# --- FILTRO DE HORARIO CORREGIDO (GMT-4, Venezuela) ---
HORA_INICIO = 6   
HORA_FIN = 11     

# =====================================================================
# BLOQUE 2: SISTEMA DE NOTIFICACIONES (NTFY)
# =====================================================================
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

def enviar_ntfy(mensaje):
    """Envía notificación push a NTFY sin errores de codificación en headers."""
    try:
        headers = {
            "Title": "Alerta de Senal de Trading",
            "Priority": "high",
            "Tags": "chart_with_upwards_trend"
        }
        response = requests.post(NTFY_URL, data=mensaje.encode(encoding='utf-8'), headers=headers)
        
        if response.status_code == 429:
            logging.error("❌ Error NTFY: 429 - Cuota diaria agotada. Abortando señal.")
            return False
        response.raise_for_status()
        return True
    except Exception as e:
        logging.error(f"❌ Error crítico en NTFY: {e}")
        return False

# =====================================================================
# BLOQUE 3: ESTRATEGIA Y ANÁLISIS TÉCNICO
# =====================================================================

def calcular_indicadores(df):
    """Calcula EMA de 9, EMA de 21 y RSI de 14."""
    df['EMA_9'] = df['close'].ewm(span=9, adjust=False).mean()
    df['EMA_21'] = df['close'].ewm(span=21, adjust=False).mean()
    
    delta = df['close'].diff()
    gain = (delta.where(delta > 0, 0)).rolling(window=14).mean()
    loss = (-delta.where(delta < 0, 0)).rolling(window=14).mean()
    rs = gain / loss
    df['RSI'] = 100 - (100 / (1 + rs))
    return df

def analizar_par(df, par):
    """Analiza el par y devuelve una señal si cumple con los filtros estrictos."""
    if len(df) < 30:
        return None

    df = calcular_indicadores(df)
    ultima_vela = df.iloc[-1]
    vela_anterior = df.iloc[-2]
    
    confirmaciones = 0
    señales = []
    
    if ultima_vela['EMA_9'] > ultima_vela['EMA_21']:
        confirmaciones += 1; señales.append("EMA_ALCISTA")
    elif ultima_vela['EMA_9'] < ultima_vela['EMA_21']:
        confirmaciones += 1; señales.append("EMA_BAJISTA")
        
    if ultima_vela['RSI'] < 35:
        confirmaciones += 1; señales.append("RSI_SOBREVENTA")
    elif ultima_vela['RSI'] > 65:
        confirmaciones += 1; señales.append("RSI_SOBRECOMPRA")
        
    if ultima_vela['close'] > ultima_vela['EMA_9']:
        confirmaciones += 1; señales.append("PRECIO_SOBRE_EMA9")
    elif ultima_vela['close'] < ultima_vela['EMA_9']:
        confirmaciones += 1; señales.append("PRECIO_BAJO_EMA9")
        
    if vela_anterior['close'] > vela_anterior['open']:
        confirmaciones += 1; señales.append("VELA_ANTERIOR_VERDE")
    elif vela_anterior['close'] < vela_anterior['open']:
        confirmaciones += 1; señales.append("VELA_ANTERIOR_ROJA")

    if "EMA_ALCISTA" in señales and "PRECIO_SOBRE_EMA9" in señales:
        direccion = "COMPRA"
    elif "EMA_BAJISTA" in señales and "PRECIO_BAJO_EMA9" in señales:
        direccion = "VENTA"
    else:
        return None 

    fuerza = 50.0
    if direccion == "COMPRA":
        if ultima_vela['RSI'] < 40: fuerza += 20
        if ultima_vela['EMA_9'] > ultima_vela['EMA_21']: fuerza += 20
        if vela_anterior['close'] > vela_anterior['open']: fuerza += 10
    else:
        if ultima_vela['RSI'] > 60: fuerza += 20
        if ultima_vela['EMA_9'] < ultima_vela['EMA_21']: fuerza += 20
        if vela_anterior['close'] < vela_anterior['open']: fuerza += 10

    if direccion == "VENTA" and ultima_vela['close'] > ultima_vela['open']:
        return None
    if direccion == "COMPRA" and ultima_vela['close'] < ultima_vela['open']:
        return None

    if fuerza >= FUERZA_MINIMA and confirmaciones >= CONFIRMACIONES_MINIMAS:
        return {
            "par": par,
            "direccion": direccion,
            "fuerza": round(fuerza, 1),
            "confirmaciones": f"{confirmaciones}/5",
            "precio": ultima_vela['close']
        }
    return None

# =====================================================================
# BLOQUE 4: OBTENCIÓN DE DATOS REALES (YAHOO FINANCE)
# =====================================================================
def obtener_datos_mercado(par):
    """Obtiene datos reales de Yahoo Finance para el par en M15."""
    try:
        ticker = f"{par}=X"
        df = yf.download(ticker, period="5d", interval="15m", progress=False)
        
        if df.empty:
            logging.warning(f"⚠️ Yahoo Finance no devolvió datos para {par}")
            return None
            
        if isinstance(df.columns, pd.MultiIndex):
            df.columns = df.columns.get_level_values(0)
            
        df = df.rename(columns={'Close': 'close', 'Open': 'open', 'High': 'high', 'Low': 'low'})
        return df
    except Exception as e:
        logging.error(f"❌ Error descargando datos de Yahoo Finance para {par}: {e}")
        return None

# =====================================================================
# BLOQUE 5: BUCLE PRINCIPAL
# =====================================================================
def escanear_mercado():
    hora_utc = datetime.now(timezone.utc)
    zona_ve = timezone(timedelta(hours=-4))
    hora_ve = hora_utc.astimezone(zona_ve)
    
    if not (HORA_INICIO <= hora_ve.hour < HORA_FIN):
        logging.info(f"💤 Fuera de horario de trading ({hora_ve.strftime('%H:%M')} - Activo de 06:00 a 11:00).")
        time.sleep(300) 
        return

    logging.info("🔍 Analizando pares con datos reales...")
    for par in PARES_A_ANALIZAR:
        try:
            df = obtener_datos_mercado(par)
            if df is None:
                continue
                
            señal = analizar_par(df, par)
            
            if señal:
                emoji = "🟢" if señal['direccion'] == "COMPRA" else "🔴"
                mensaje = (
                    f"{emoji} {señal['par']} {señal['direccion']} | Fuerza {señal['fuerza']}%\n\n"
                    f"📊 Confirmaciones: {señal['confirmaciones']}\n"
                    f"⏳ Vencimiento: {VENCIMIENTO} min\n"
                    f"💵 Precio entrada: {señal['precio']:.5f}\n\n"
                    f"👉 ENTRA AHORA ({'CALL' if señal['direccion'] == 'COMPRA' else 'PUT'})"
                )
                
                if enviar_ntfy(mensaje):
                    logging.info(f"🚀 Señal real enviada: {par} {señal['direccion']}")
                else:
                    logging.warning(f"⚠️ Señal abortada para {par} por fallo en NTFY.")
                
        except Exception as e:
            logging.error(f"Error analizando {par}: {e}")

def esperar_proxima_vela():
    ahora = datetime.now(timezone.utc).astimezone(timezone(timedelta(hours=-4)))
    minutos = ahora.minute
    segundos = ahora.second
    
    minutos_faltantes = (15 - (minutos % 15)) % 15
    if minutos_faltantes == 0 and segundos == 0:
        return 
    
    segundos_totales = (minutos_faltantes * 60) - segundos
    if segundos_totales <= 0:
        segundos_totales += 900 
        
    logging.info(f"⏳ Esperando {segundos_totales} segundos para la próxima vela M15...")
    time.sleep(segundos_totales)

if __name__ == "__main__":
    logging.info("🤖 Iniciando Bot de Trading v36.3 - Horario 6-11 AM y Yahoo Finance")
    
    while True:
        try:
            escanear_mercado()
            esperar_proxima_vela()
        except KeyboardInterrupt:
            logging.info("Bot detenido por el usuario.")
            break
        except Exception as e:
            logging.error(f"Error en el bucle principal: {e}")
            time.sleep(60)
