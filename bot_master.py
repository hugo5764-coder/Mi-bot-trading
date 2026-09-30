import time
import logging
from datetime import datetime, timezone, timedelta
import requests
import pandas as pd
import numpy as np
import yfinance as yf

# =====================================================================
# BLOQUE 1: CONFIGURACIÓN PROFESIONAL M5
# =====================================================================

NTFY_TOPIC = "hugo_bot_trading_2026"
NTFY_URL = f"https://ntfy.sh/{NTFY_TOPIC}"

PARES_A_ANALIZAR = ["USDJPY", "USDCAD", "EURUSD", "GBPJPY"]
TEMPORALIDAD = "5m" 
VENCIMIENTO = 5      
FUERZA_MINIMA = 50.0  
CONFIRMACIONES_MINIMAS = 3  
MAX_ALERTAS_DIARIAS = 15    

# --- FILTRO DE HORARIO Y DÍAS (GMT-4, Venezuela) ---
HORA_INICIO = 6   
HORA_FIN = 11     

# Variables de control de estado y memoria de velas
contador_alertas_hoy = 0
dia_actual_registro = None
ultimas_velas_oficiales = {par: None for par in PARES_A_ANALIZAR}
ultimas_velas_preventivas = {par: None for par in PARES_A_ANALIZAR}

# =====================================================================
# BLOQUE 2: SISTEMA DE NOTIFICACIONES (NTFY)
# =====================================================================
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

def enviar_ntfy(mensaje, titulo="Alerta de Trading M5"):
    """Envía notificación push a NTFY de forma segura."""
    global contador_alertas_hoy
    try:
        if contador_alertas_hoy >= MAX_ALERTAS_DIARIAS:
            logging.warning("⚠️ Límite diario de 15 alertas alcanzado. Pausando envíos por hoy.")
            return False

        headers = {
            "Title": titulo,
            "Priority": "high",
            "Tags": "chart_with_upwards_trend"
        }
        response = requests.post(NTFY_URL, data=mensaje.encode(encoding='utf-8'), headers=headers)
        
        if response.status_code == 429:
            logging.error("❌ Error NTFY: 429 - Cuota diaria agotada. Abortando señal.")
            return False
            
        response.raise_for_status()
        contador_alertas_hoy += 1
        return True
    except Exception as e:
        logging.error(f"❌ Error crítico en NTFY: {e}")
        return False

# =====================================================================
# BLOQUE 3: ESTRATEGIA TÉCNICA MULTI-INDICADOR
# =====================================================================

def calcular_indicadores(df):
    df['EMA_9'] = df['close'].ewm(span=9, adjust=False).mean()
    df['EMA_21'] = df['close'].ewm(span=21, adjust=False).mean()
    
    delta = df['close'].diff()
    gain = (delta.where(delta > 0, 0)).rolling(window=14).mean()
    loss = (-delta.where(delta < 0, 0)).rolling(window=14).mean()
    rs = gain / loss
    df['RSI'] = 100 - (100 / (1 + rs))
    return df

def analizar_par(df, par):
    if len(df) < 30:
        return None

    df = calcular_indicadores(df)
    ultima_vela = df.iloc[-1]
    vela_anterior = df.iloc[-2]
    
    confirmaciones = 0
    estrategias_activas = []
    
    if ultima_vela['EMA_9'] > ultima_vela['EMA_21']:
        confirmaciones += 1; estrategias_activas.append("Tendencia Alcista (EMA)")
    elif ultima_vela['EMA_9'] < ultima_vela['EMA_21']:
        confirmaciones += 1; estrategias_activas.append("Tendencia Bajista (EMA)")
        
    if ultima_vela['RSI'] < 40:
        confirmaciones += 1; estrategias_activas.append("RSI en Sobreventa")
    elif ultima_vela['RSI'] > 60:
        confirmaciones += 1; estrategias_activas.append("RSI en Sobrecompra")
        
    if ultima_vela['close'] > ultima_vela['EMA_9']:
        confirmaciones += 1; estrategias_activas.append("Precio sobre EMA9")
    elif ultima_vela['close'] < ultima_vela['EMA_9']:
        confirmaciones += 1; estrategias_activas.append("Precio bajo EMA9")
        
    if vela_anterior['close'] > vela_anterior['open']:
        confirmaciones += 1; estrategias_activas.append("Momentum Verde Previo")
    elif vela_anterior['close'] < vela_anterior['open']:
        confirmaciones += 1; estrategias_activas.append("Momentum Rojo Previo")

    if ultima_vela['EMA_9'] > ultima_vela['EMA_21'] and ultima_vela['close'] > ultima_vela['EMA_9']:
        direccion = "COMPRA"
    elif ultima_vela['EMA_9'] < ultima_vela['EMA_21'] and ultima_vela['close'] < ultima_vela['EMA_9']:
        direccion = "VENTA"
    else:
        return None 

    fuerza = 50.0
    if confirmaciones >= 3:
        fuerza += (confirmaciones * 12.5)

    if fuerza >= FUERZA_MINIMA and confirmaciones >= CONFIRMACIONES_MINIMAS:
        return {
            "par": par,
            "timestamp": df.index[-1],
            "direccion": direccion,
            "fuerza": min(round(fuerza, 1), 100.0),
            "confirmaciones": f"{confirmaciones}/4",
            "precio": ultima_vela['close'],
            "estrategias": ", ".join(estrategias_activas)
        }
    return None

# =====================================================================
# BLOQUE 4: OBTENCIÓN DE DATOS (YAHOO FINANCE M5)
# =====================================================================
def obtener_datos_mercado(par):
    try:
        ticker = f"{par}=X"
        df = yf.download(ticker, period="2d", interval="5m", progress=False)
        
        if df.empty:
            return None
            
        if isinstance(df.columns, pd.MultiIndex):
            df.columns = df.columns.get_level_values(0)
            
        df = df.rename(columns={'Close': 'close', 'Open': 'open', 'High': 'high', 'Low': 'low'})
        return df
    except Exception as e:
        logging.error(f"❌ Error descargando {par}: {e}")
        return None

# =====================================================================
# BLOQUE 5: BUCLE PRINCIPAL CON CONTROL DE DUPLICADOS POR VELA
# =====================================================================
def ejecutar_ciclo_trading():
    global dia_actual_registro, contador_alertas_hoy, ultimas_velas_oficiales, ultimas_velas_preventivas
    
    hora_utc = datetime.now(timezone.utc)
    zona_ve = timezone(timedelta(hours=-4))
    hora_ve = hora_utc.astimezone(zona_ve)
    
    if dia_actual_registro != hora_ve.date():
        dia_actual_registro = hora_ve.date()
        contador_alertas_hoy = 0

    if hora_ve.weekday() > 4:
        logging.info("💤 Fin de semana. El mercado de divisas está cerrado...")
        time.sleep(3600)
        return

    if not (HORA_INICIO <= hora_ve.hour < HORA_FIN):
        logging.info(f"💤 Fuera de horario ({hora_ve.strftime('%H:%M')} VE). Activo de 06:00 a 11:00.")
        time.sleep(300) 
        return

    minutos = hora_ve.minute
    segundos = hora_ve.second
    
    minutos_en_bloque = minutos % 5
    segundos_en_bloque = (minutos_en_bloque * 60) + segundos
    
    # --- FASE 1: ALERTA PREVENTIVA (Minuto 4 del bloque M5) ---
    if 235 <= segundos_en_bloque <= 245:
        logging.info("⚠️️ Ejecutando escaneo preventivo (1 min para cierre de vela M5)...")
        for par in PARES_A_ANALIZAR:
            df = obtener_datos_mercado(par)
            if df is not None:
                señal = analizar_par(df, par)
                if señal:
                    # Evitar repetir la alerta preventiva para la misma vela exacta
                    if ultimas_velas_preventivas[par] == señal['timestamp']:
                        continue
                    
                    ultimas_velas_preventivas[par] = señal['timestamp']
                    emoji = "🟢" if señal['direccion'] == "COMPRA" else "🔴"
                    msg_prev = (
                        f"⚠️ PREPARATE (1 MIN) -> {emoji} {señal['par']} {señal['direccion']}\n"
                        f"💪 Fuerza: {señal['fuerza']}% | Conf: {señal['confirmaciones']}\n"
                        f"💵 Precio est: {señal['precio']:.5f}\n\n"
                        f"⏱️ Prepárate en tu broker para M5."
                    )
                    enviar_ntfy(msg_prev, titulo="Aviso Preventivo M5")
        
        time.sleep(15)
        return

    # --- FASE 2: SEÑAL OFICIAL (Al cierre exacto de la vela) ---
    logging.info(f"🔍 Escaneando mercado al cierre de vela M5...")
    for par in PARES_A_ANALIZAR:
        try:
            df = obtener_datos_mercado(par)
            if df is None:
                continue
                
            señal = analizar_par(df, par)
            
            if señal:
                # Evitar repetir la alerta oficial para la misma vela exacta
                if ultimas_velas_oficiales[par] == señal['timestamp']:
                    continue
                
                ultimas_velas_oficiales[par] = señal['timestamp']
                emoji = "🟢" if señal['direccion'] == "COMPRA" else "🔴"
                mensaje = (
                    f"{emoji} {señal['par']} {señal['direccion']} | Fuerza {señal['fuerza']}%\n\n"
                    f"📊 Confirmaciones: {señal['confirmaciones']}\n"
                    f"🧠 Estrategias: {señal['estrategias']}\n"
                    f"⏳ Vencimiento: {VENCIMIENTO} min (M5)\n"
                    f"💵 Precio entrada: {señal['precio']:.5f}\n\n"
                    f"👉 ENTRA AHORA ({'CALL' if señal['direccion'] == 'COMPRA' else 'PUT'})"
                )
                
                if enviar_ntfy(mensaje, titulo=f"Señal Oficial M5 ({contador_alertas_hoy+1}/15)"):
                    logging.info(f"🚀 Alerta oficial enviada: {par} {señal['direccion']}")
                
        except Exception as e:
            logging.error(f"Error analizando {par}: {e}")

    time.sleep(30)

if __name__ == "__main__":
    logging.info("🤖 Iniciando Bot v36.6 - M5 con Control Anti-Spam por Vela")
    
    while True:
        try:
            ejecutar_ciclo_trading()
        except KeyboardInterrupt:
            logging.info("Bot detenido por el usuario.")
            break
        except Exception as e:
            logging.error(f"Error en bucle principal: {e}")
            time.sleep(60)
