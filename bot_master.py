import time
import logging
from datetime import datetime, timezone, timedelta
import requests
import pandas as pd
import numpy as np
import yfinance as yf

# =====================================================================
# BLOQUE 1: CONFIGURACIÓN PROFESIONAL M5 (INTACTO)
# =====================================================================

NTFY_TOPIC = "hugo_bot_trading_2026"
NTFY_URL = "https://ntfy.sh/" 

PARES_A_ANALIZAR = ["USDJPY", "USDCAD", "EURUSD", "GBPJPY"]
TEMPORALIDAD = "5m" 
VENCIMIENTO = 5      
FUERZA_MINIMA = 50.0  
CONFIRMACIONES_MINIMAS = 3  
MAX_ALERTAS_DIARIAS = 100   

# --- FILTRO DE HORARIO Y DÍAS (GMT-4, Venezuela) ---
HORA_INICIO = 6   
HORA_FIN = 11     

# Variables de control de estado y bloques
contador_alertas_hoy = 0
dia_actual_registro = None
ultimo_bloque_preventivo = None
ultimo_bloque_oficial = None

# =====================================================================
# BLOQUE 2: SISTEMA DE NOTIFICACIONES (NTFY CONSOLIDADO)
# =====================================================================
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

def enviar_ntfy(mensaje, titulo="Alerta de Trading M5"):
    """Envía una notificación consolidada a NTFY usando JSON."""
    global contador_alertas_hoy
    try:
        if contador_alertas_hoy >= MAX_ALERTAS_DIARIAS:
            logging.warning("⚠️ Límite diario de alertas alcanzado.")
            return False

        # Usamos JSON para evitar problemas con emojis y formatos multilínea
        payload = {
            "topic": NTFY_TOPIC,
            "message": mensaje,
            "title": titulo,
            "priority": 4,  # 4 = Alta prioridad en NTFY
            "tags": ["chart_with_upwards_trend"]
        }
        
        response = requests.post(NTFY_URL, json=payload)
        
        if response.status_code == 429:
            logging.error("❌ Error NTFY: 429 - Límite de tasa excedido temporalmente.")
            return False
            
        response.raise_for_status()
        contador_alertas_hoy += 1
        logging.info(f"✅ NTFY respondió: {response.text}") 
        return True
    except Exception as e:
        logging.error(f"❌ Error crítico en NTFY: {e}")
        return False

# =====================================================================
# BLOQUE 3: ESTRATEGIA TÉCNICA MULTI-INDICADOR (INTACTO)
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
        confirmaciones += 1; estrategias_activas.append("EMA Alcista")
    elif ultima_vela['EMA_9'] < ultima_vela['EMA_21']:
        confirmaciones += 1; estrategias_activas.append("EMA Bajista")
        
    if ultima_vela['RSI'] < 40:
        confirmaciones += 1; estrategias_activas.append("RSI Sobreventa")
    elif ultima_vela['RSI'] > 60:
        confirmaciones += 1; estrategias_activas.append("RSI Sobrecompra")
        
    if ultima_vela['close'] > ultima_vela['EMA_9']:
        confirmaciones += 1; estrategias_activas.append("Precio > EMA9")
    elif ultima_vela['close'] < ultima_vela['EMA_9']:
        confirmaciones += 1; estrategias_activas.append("Precio < EMA9")
        
    if vela_anterior['close'] > vela_anterior['open']:
        confirmaciones += 1; estrategias_activas.append("Momentum Verde")
    elif vela_anterior['close'] < vela_anterior['open']:
        confirmaciones += 1; estrategias_activas.append("Momentum Rojo")

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
# BLOQUE 5: BUCLE PRINCIPAL CON CONSOLIDACIÓN DE SEÑALES
# =====================================================================
def ejecutar_ciclo_trading():
    global dia_actual_registro, contador_alertas_hoy, ultimo_bloque_preventivo, ultimo_bloque_oficial
    
    hora_utc = datetime.now(timezone.utc)
    zona_ve = timezone(timedelta(hours=-4))
    hora_ve = hora_utc.astimezone(zona_ve)
    
    if dia_actual_registro != hora_ve.date():
        dia_actual_registro = hora_ve.date()
        contador_alertas_hoy = 0

    if hora_ve.weekday() > 4:
        logging.info("💤 Fin de semana. Mercado cerrado...")
        time.sleep(3600)
        return

    if not (HORA_INICIO <= hora_ve.hour < HORA_FIN):
        logging.info(f"💤 Fuera de horario ({hora_ve.strftime('%H:%M')} VE). Activo de 06:00 a 11:00.")
        time.sleep(300) 
        return

    minutos = hora_ve.minute
    segundos = hora_ve.second
    
    bloque_id = f"{hora_ve.hour}:{minutos - (minutos % 5)}"
    minutos_en_bloque = minutos % 5

    # --- FASE 1: AVISO PREVENTIVO CONSOLIDADO (Minuto 4) ---
    if minutos_en_bloque == 4 and ultimo_bloque_preventivo != bloque_id:
        ultimo_bloque_preventivo = bloque_id
        logging.info(f"⚠️ Evaluando escaneo preventivo para el bloque {bloque_id}...")
        
        señales_preventivas = []
        for par in PARES_A_ANALIZAR:
            df = obtener_datos_mercado(par)
            if df is not None:
                señal = analizar_par(df, par)
                if señal:
                    señales_preventivas.append(señal)
        
        if señales_preventivas:
            msg = "⚠️ AVISO PREVENTIVO (Faltan 1 min)\n\n"
            for s in señales_preventivas:
                emoji = "🟢" if s['direccion'] == "COMPRA" else "🔴"
                msg += f"{emoji} {s['par']} {s['direccion']} | Fuerza: {s['fuerza']}%\n"
            
            # NUEVO: Log para que veas el mensaje exacto en Railway
            logging.info(f"\n📤 MENSAJE A ENVIAR:\n{msg}")
            
            enviar_ntfy(msg, titulo="Prepararse M5")
            logging.info("🚀 Alerta preventiva consolidada enviada.")
        
        time.sleep(10)
        return

    # --- FASE 2: SEÑAL OFICIAL CONSOLIDADA (Minuto 0) ---
    if minutos_en_bloque == 0 and segundos <= 15 and ultimo_bloque_oficial != bloque_id:
        ultimo_bloque_oficial = bloque_id
        logging.info(f"🔍 Evaluando señal oficial para el bloque {bloque_id}...")
        
        señales_oficiales = []
        for par in PARES_A_ANALIZAR:
            try:
                df = obtener_datos_mercado(par)
                if df is not None:
                    señal = analizar_par(df, par)
                    if señal:
                        señales_oficiales.append(señal)
            except Exception as e:
                logging.error(f"Error analizando {par}: {e}")
        
        if señales_oficiales:
            msg = f"🚀 SEÑALES OFICIALES M5 ({bloque_id})\n\n"
            for s in señales_oficiales:
                emoji = "🟢" if s['direccion'] == "COMPRA" else "🔴"
                msg += f"{emoji} {s['par']} ➔ {s['direccion']}\n"
                msg += f"   💪 Fuerza: {s['fuerza']}% ({s['confirmaciones']})\n"
                msg += f"   💵 Precio: {s['precio']:.5f}\n"
                msg += f"   🧠 Estrategias: {s['estrategias']}\n\n"
            
            msg += f"⏳ Vencimiento: {VENCIMIENTO} min. ¡ENTRA AHORA!"
            
            # NUEVO: Log para que veas el mensaje exacto en Railway
            logging.info(f"\n📤 MENSAJE A ENVIAR:\n{msg}")
            
            if enviar_ntfy(msg, titulo=f"Señales M5 - Bloque {bloque_id}"):
                logging.info("🚀 Alerta oficial consolidada enviada con éxito.")
        
        time.sleep(10)
        return

    time.sleep(5)

if __name__ == "__main__":
    logging.info("🤖 Iniciando Bot v36.9 - Alertas Consolidadas por Bloque M5")
    
    while True:
        try:
            ejecutar_ciclo_trading()
        except KeyboardInterrupt:
            logging.info("Bot detenido por el usuario.")
            break
        except Exception as e:
            logging.error(f"Error en bucle principal: {e}")
            time.sleep(15)
