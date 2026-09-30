import time
import logging
from datetime import datetime, timedelta
import requests
import pandas as pd
import numpy as np

# =====================================================================
# BLOQUE 1: CONFIGURACIÓN (Edita esto según tus necesidades)
# =====================================================================

# --- CONFIGURACIÓN DE NTFY (App Android) ---
# CAMBIA ESTO por un nombre único, inventado por ti. Ej: "hugo_bot_2026_xyz"
NTFY_TOPIC = "hugo_bot_trading_2026" 
NTFY_URL = f"https://ntfy.sh/{NTFY_TOPIC}"

# --- CONFIGURACIÓN DE TRADING ---
PARES_A_ANALIZAR = ["USDJPY", "USDCAD", "EURUSD", "GBPJPY"]
TEMPORALIDAD = "15m" # Análisis en velas de 15 minutos
VENCIMIENTO = 15      # CORREGIDO: Vencimiento de 15 min para que coincida con M15
FUERZA_MINIMA = 65.0  # Ignorar señales con fuerza menor al 65%
CONFIRMACIONES_MINIMAS = 4 # Exigir 4/5 o 5/5

# --- FILTRO DE HORARIO (GMT-4, Venezuela) ---
# Evitar horas muertas (ej. 5:00 AM a 7:30 AM)
HORA_INICIO = 8   # 8:00 AM
HORA_FIN = 17     # 5:00 PM

# =====================================================================
# BLOQUE 2: SISTEMA DE NOTIFICACIONES (Solo NTFY)
# =====================================================================
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

def enviar_ntfy(mensaje):
    """
    Envía notificación push a NTFY. 
    Si falla (Error 429), retorna False y aborta la señal para evitar 'señales fantasma'.
    """
    try:
        headers = {
            "Title": "🚨 Señal de Trading",
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
    # EMAs
    df['EMA_9'] = df['close'].ewm(span=9, adjust=False).mean()
    df['EMA_21'] = df['close'].ewm(span=21, adjust=False).mean()
    
    # RSI
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
    
    # 1. Evaluar Indicadores (5 posibles confirmaciones)
    # EMA Cross
    if ultima_vela['EMA_9'] > ultima_vela['EMA_21']:
        confirmaciones += 1; señales.append("EMA_ALCISTA")
    elif ultima_vela['EMA_9'] < ultima_vela['EMA_21']:
        confirmaciones += 1; señales.append("EMA_BAJISTA")
        
    # RSI
    if ultima_vela['RSI'] < 35: # Sobreventa
        confirmaciones += 1; señales.append("RSI_SOBREVENTA")
    elif ultima_vela['RSI'] > 65: # Sobrecompra
        confirmaciones += 1; señales.append("RSI_SOBRECOMPRA")
        
    # Precio vs EMAs
    if ultima_vela['close'] > ultima_vela['EMA_9']:
        confirmaciones += 1; señales.append("PRECIO_SOBRE_EMA9")
    elif ultima_vela['close'] < ultima_vela['EMA_9']:
        confirmaciones += 1; señales.append("PRECIO_BAJO_EMA9")
        
    # Vela anterior (Momentum)
    if vela_anterior['close'] > vela_anterior['open']:
        confirmaciones += 1; señales.append("VELA_ANTERIOR_VERDE")
    elif vela_anterior['close'] < vela_anterior['open']:
        confirmaciones += 1; señales.append("VELA_ANTERIOR_ROJA")

    # 2. Determinar dirección
    if "EMA_ALCISTA" in señales and "PRECIO_SOBRE_EMA9" in señales:
        direccion = "COMPRA"
    elif "EMA_BAJISTA" in señales and "PRECIO_BAJO_EMA9" in señales:
        direccion = "VENTA"
    else:
        return None # Señal mixta, no operar

    # 3. Calcular Fuerza (0-100%)
    fuerza = 50.0
    if direccion == "COMPRA":
        if ultima_vela['RSI'] < 40: fuerza += 20
        if ultima_vela['EMA_9'] > ultima_vela['EMA_21']: fuerza += 20
        if vela_anterior['close'] > vela_anterior['open']: fuerza += 10
    else:
        if ultima_vela['RSI'] > 60: fuerza += 20
        if ultima_vela['EMA_9'] < ultima_vela['EMA_21']: fuerza += 20
        if vela_anterior['close'] < vela_anterior['open']: fuerza += 10

    # 4. FILTRO ANTI-TRAMPAS (Fakeout) - ¡Esto te salvó hoy!
    # Si la señal es VENTA, pero la vela actual (la que se está formando) está verde, ABORTAR.
    if direccion == "VENTA" and ultima_vela['close'] > ultima_vela['open']:
        logging.info(f"🚫 {par}: Señal VENTA abortada. Vela actual verde (Falso positivo).")
        return None
    # Si la señal es COMPRA, pero la vela actual está roja, ABORTAR.
    if direccion == "COMPRA" and ultima_vela['close'] < ultima_vela['open']:
        logging.info(f"🚫 {par}: Señal COMPRA abortada. Vela actual roja (Falso positivo).")
        return None

    # 5. Aplicar filtros de calidad
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
# BLOQUE 4: OBTENCIÓN DE DATOS (REEMPLAZAR CON API REAL)
# =====================================================================
def obtener_datos_mercado(par):
    """
    ⚠️ ATENCIÓN: Aquí debes conectar tu API de datos real (TwelveData, Polygon, etc.)
    Actualmente genera datos aleatorios para que el bot no crashee en Railway.
    """
    # --- SIMULACIÓN (Borrar cuando tengas API real) ---
    fechas = pd.date_range(end=datetime.now(), periods=50, freq='15min')
    precios = np.random.normal(150, 2, 50).cumsum() + 1000
    df = pd.DataFrame({'close': precios, 'open': precios - np.random.normal(0, 0.5, 50)})
    df['high'] = df[['open', 'close']].max(axis=1) + 0.5
    df['low'] = df[['open', 'close']].min(axis=1) - 0.5
    return df

# =====================================================================
# BLOQUE 5: BUCLE PRINCIPAL (El cerebro del bot)
# =====================================================================
def escanear_mercado():
    # Calcular hora actual en Venezuela (GMT-4)
    hora_utc = datetime.utcnow()
    hora_ve = hora_utc - timedelta(hours=4)
    
    # Filtro de Horario
    if not (HORA_INICIO <= hora_ve.hour < HORA_FIN):
        logging.info(f"💤 Fuera de horario de trading ({hora_ve.strftime('%H:%M')}). Esperando...")
        return

    logging.info("🔍 Analizando pares...")
    for par in PARES_A_ANALIZAR:
        try:
            df = obtener_datos_mercado(par)
            señal = analizar_par(df, par)
            
            if señal:
                # Construir mensaje de alerta
                emoji = "🟢" if señal['direccion'] == "COMPRA" else "🔴"
                mensaje = (
                    f"{emoji} {señal['par']} {señal['direccion']} | Fuerza {señal['fuerza']}%\n\n"
                    f"📊 Confirmaciones: {señal['confirmaciones']}\n"
                    f"⏳ Vencimiento: {VENCIMIENTO} min\n"
                    f"💵 Precio entrada: {señal['precio']:.5f}\n\n"
                    f"👉 ENTRA AHORA ({'CALL' if señal['direccion'] == 'COMPRA' else 'PUT'})"
                )
                
                # Enviar alerta (Si NTFY falla, NO se envía nada)
                if enviar_ntfy(mensaje):
                    logging.info(f"🚀 Señal enviada: {par} {señal['direccion']}")
                else:
                    logging.warning(f"⚠️ Señal abortada para {par} por fallo en NTFY.")
                
        except Exception as e:
            logging.error(f"Error analizando {par}: {e}")

if __name__ == "__main__":
    logging.info("🤖 Iniciando Bot de Trading v36 - Solo NTFY")
    
    # Bucle infinito controlado
    while True:
        try:
            # Escanear mercado
            escanear_mercado()
            
            # Esperar 15 minutos (900 segundos) para la próxima vela de M15
            logging.info("⏳ Esperando 15 minutos para la próxima vela...")
            time.sleep(900) 
            
        except KeyboardInterrupt:
            logging.info("Bot detenido por el usuario.")
            break
        except Exception as e:
            logging.error(f"Error en el bucle principal: {e}")
            time.sleep(60) # Esperar 1 minuto si hay error antes de reintentar
