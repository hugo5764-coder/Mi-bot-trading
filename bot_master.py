import time
import logging
from datetime import datetime, timezone, timedelta
import requests
import pandas as pd
import numpy as np

# =====================================================================
# BLOQUE 1: CONFIGURACIÓN (Edita esto según tus necesidades)
# =====================================================================

# --- CONFIGURACIÓN DE NTFY (App Android) ---
NTFY_TOPIC = "hugo_bot_trading_2026" # Asegúrate de que este sea el topic que pusiste en la app
NTFY_URL = f"https://ntfy.sh/{NTFY_TOPIC}"

# --- CONFIGURACIÓN DE TRADING ---
PARES_A_ANALIZAR = ["USDJPY", "USDCAD", "EURUSD", "GBPJPY"]
TEMPORALIDAD = "15m" 
VENCIMIENTO = 15      
FUERZA_MINIMA = 65.0  
CONFIRMACIONES_MINIMAS = 4 

# --- FILTRO DE HORARIO (GMT-4, Venezuela) ---
HORA_INICIO = 8   
HORA_FIN = 17     

# =====================================================================
# BLOQUE 2: SISTEMA DE NOTIFICACIONES (Solo NTFY)
# =====================================================================
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

def enviar_ntfy(mensaje):
    """Envía notificación push a NTFY. Si falla (429), aborta la señal."""
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
    
    # 1. Evaluar Indicadores (5 posibles confirmaciones)
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

    # 2. Determinar dirección
    if "EMA_ALCISTA" in señales and "PRECIO_SOBRE_EMA9" in señales:
        direccion = "COMPRA"
    elif "EMA_BAJISTA" in señales and "PRECIO_BAJO_EMA9" in señales:
        direccion = "VENTA"
    else:
        return None 

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

    # 4. FILTRO ANTI-TRAMPAS (Fakeout)
    if direccion == "VENTA" and ultima_vela['close'] > ultima_vela['open']:
        logging.info(f"🚫 {par}: Señal VENTA abortada. Vela actual verde (Falso positivo).")
        return None
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
# BLOQUE 4: OBTENCIÓN DE DATOS (AQUÍ DEBES CONECTAR TU API REAL)
# =====================================================================
def obtener_datos_mercado(par):
    """
    ⚠️ REEMPLAZAR CON API REAL (TwelveData, Polygon, etc.)
    Simulación para que el bot no crashee.
    """
    fechas = pd.date_range(end=datetime.now(timezone.utc), periods=50, freq='15min')
    precios = np.random.normal(150, 2, 50).cumsum() + 1000
    df = pd.DataFrame({'close': precios, 'open': precios - np.random.normal(0, 0.5, 50)})
    df['high'] = df[['open', 'close']].max(axis=1) + 0.5
    df['low'] = df[['open', 'close']].min(axis=1) - 0.5
    return df

# =====================================================================
# BLOQUE 5: BUCLE PRINCIPAL (Sincronizado con el reloj)
# =====================================================================
def escanear_mercado():
    # Calcular hora actual en Venezuela (GMT-4) correctamente
    hora_utc = datetime.now(timezone.utc)
    zona_ve = timezone(timedelta(hours=-4))
    hora_ve = hora_utc.astimezone(zona_ve)
    
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
                emoji = "🟢" if señal['direccion'] == "COMPRA" else "🔴"
                mensaje = (
                    f"{emoji} {señal['par']} {señal['direccion']} | Fuerza {señal['fuerza']}%\n\n"
                    f"📊 Confirmaciones: {señal['confirmaciones']}\n"
                    f"⏳ Vencimiento: {VENCIMIENTO} min\n"
                    f"💵 Precio entrada: {señal['precio']:.5f}\n\n"
                    f"👉 ENTRA AHORA ({'CALL' if señal['direccion'] == 'COMPRA' else 'PUT'})"
                )
                
                if enviar_ntfy(mensaje):
                    logging.info(f"🚀 Señal enviada: {par} {señal['direccion']}")
                else:
                    logging.warning(f"⚠️ Señal abortada para {par} por fallo en NTFY.")
                
        except Exception as e:
            logging.error(f"Error analizando {par}: {e}")

def esperar_proxima_vela():
    """Calcula los segundos exactos para despertar en el próximo minuto 00, 15, 30 o 45."""
    ahora = datetime.now(timezone.utc).astimezone(timezone(timedelta(hours=-4)))
    minutos = ahora.minute
    segundos = ahora.second
    
    # Calcular cuántos minutos faltan para el próximo bloque de 15 min
    minutos_faltantes = (15 - (minutos % 15)) % 15
    if minutos_faltantes == 0 and segundos == 0:
        return 0 # Ya estamos en el momento exacto
    
    segundos_totales = (minutos_faltantes * 60) - segundos
    if segundos_totales <= 0:
        segundos_totales += 900 # Si ya pasó, esperar al siguiente ciclo
        
    logging.info(f"⏳ Esperando {segundos_totales} segundos para la próxima vela M15...")
    time.sleep(segundos_totales)

if __name__ == "__main__":
    logging.info("🤖 Iniciando Bot de Trading v36.1 - Sincronizado")
    
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
