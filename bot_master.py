import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
import time
from datetime import datetime
import pytz
import pandas as pd
import numpy as np

# --- CONFIGURACIÓN GENERAL ---
EMAIL_DESTINO = "hugo5764@gmail.com"
EMAIL_ORIGEN = "tu_correo@gmail.com"  # Reemplaza con tu correo remitente de Gmail
EMAIL_PASSWORD = "tu_contraseña_de_aplicacion"  # Contraseña de aplicación de 16 dígitos de Google

TZ_UTC4 = pytz.timezone('America/Caracas')

# 10 Pares de divisas oficiales principales
PARES_DIVISAS = [
    "EURUSD", "GBPUSD", "USDJPY", "AUDUSD", "USDCAD", 
    "NZDUSD", "EURGBP", "EURJPY", "GBPJPY", "AUDJPY"
]

# Control de Cooldown (Anti-spam por par)
cooldown_pares = {par: 0 for par in PARES_DIVISAS}

def enviar_alerta_correo(asunto, mensaje):
    """Envía correo con sistema de reintentos para garantizar entrega 24/7"""
    intentos = 3
    for intento in range(intentos):
        try:
            msg = MIMEMultipart()
            msg['From'] = EMAIL_ORIGEN
            msg['To'] = EMAIL_DESTINO
            msg['Subject'] = asunto
            msg.attach(MIMEText(mensaje, 'plain'))

            server = smtplib.SMTP('smtp.gmail.com', 587, timeout=10)
            server.starttls()
            server.login(EMAIL_ORIGEN, EMAIL_PASSWORD)
            server.sendmail(EMAIL_ORIGEN, EMAIL_DESTINO, msg.as_string())
            server.quit()
            print(f"[{datetime.now(TZ_UTC4).strftime('%H:%M:%S')}] Alerta enviada a {EMAIL_DESTINO}")
            return
        except Exception as e:
            print(f"Intento {intento+1} fallido al enviar correo: {e}")
            time.sleep(5)

def calcular_cinco_estrategias(df):
    """Evalúa las 5 estrategias principales del mercado"""
    # 1. EMA Trend (9 y 21)
    df['EMA_9'] = df['close'].ewm(span=9, adjust=False).mean()
    df['EMA_21'] = df['close'].ewm(span=21, adjust=False).mean()
    
    # 2. RSI Dinámico (14)
    delta = df['close'].diff()
    gain = (delta.where(delta > 0, 0)).rolling(window=14).mean()
    loss = (-delta.where(delta < 0, 0)).rolling(window=14).mean()
    rs = gain / loss
    df['RSI'] = 100 - (100 / (1 + rs))
    
    # 3. Bandas de Bollinger (20, 2)
    df['BB_Mid'] = df['close'].rolling(window=20).mean()
    df['BB_Std'] = df['close'].rolling(window=20).std()
    df['BB_Upper'] = df['BB_Mid'] + (df['BB_Std'] * 2)
    df['BB_Lower'] = df['BB_Mid'] - (df['BB_Std'] * 2)
    
    # 4. MACD (12, 26, 9)
    exp1 = df['close'].ewm(span=12, adjust=False).mean()
    exp2 = df['close'].ewm(span=26, adjust=False).mean()
    df['MACD'] = exp1 - exp2
    df['MACD_Signal'] = df['MACD'].ewm(span=9, adjust=False).mean()
    
    # 5. Price Action: Vela limpia (Cuerpo vs Rango total)
    df['Cuerpo'] = abs(df['close'] - df['open'])
    df['Rango_Total'] = (df['high'] - df['low']).replace(0, 0.00001)
    df['Proporcion_Cuerpo'] = df['Cuerpo'] / df['Rango_Total']
    
    return df

def evaluar_vela_m5(df):
    """
    Condición 'Cero dudas': La vela arranca fuerte y limpia (cuerpo >= 80% del rango).
    Retorna VALIDA (silencio) o SENAL_FALSA (envía alerta de correo).
    """
    ultima = df.iloc[-1]
    
    # Filtro de arranque inmediato sin indecisión
    if ultima['Proporcion_Cuerpo'] < 0.80:
        return 'SENAL_FALSA' # Mechas largas o indecisión al inicio
    
    # Confluencia alcista pura
    alcista = (
        (ultima['close'] > ultima['open']) and
        (ultima['EMA_9'] > ultima['EMA_21']) and
        (ultima['RSI'] > 55) and
        (ultima['close'] > ultima['BB_Mid']) and
        (ultima['MACD'] > ultima['MACD_Signal']) and
        (ultima['MACD'] > 0)
    )
    
    # Confluencia bajista pura
    bajista = (
        (ultima['close'] < ultima['open']) and
        (ultima['EMA_9'] < ultima['EMA_21']) and
        (ultima['RSI'] < 45) and
        (ultima['close'] < ultima['BB_Mid']) and
        (ultima['MACD'] < ultima['MACD_Signal']) and
        (ultima['MACD'] < 0)
    )
    
    if alcista or bajista:
        return 'VALIDA' # Señal limpia: Operación en silencio absoluto
    else:
        return 'SENAL_FALSA' # Falla en confluencia: Dispara alerta de invalidación

def ciclo_principal_247():
    print(f"[{datetime.now(TZ_UTC4)}] Bot Maestro M5 iniciado 24/7 para los 10 pares.")
    
    while True:
        try:
            ahora = datetime.now(TZ_UTC4)
            minuto_actual = ahora.minute
            
            # Sincronizar en los primeros minutos de cada vela M5 (ej: minuto 1, 6, 11...)
            if minuto_actual % 5 == 1:
                for par in PARES_DIVISAS:
                    # Control de Cooldown de 15 minutos por par para evitar saturación
                    if time.time() - cooldown_pares[par] < 900:
                        continue
                    
                    # --- AQUÍ CONECTAS LA DATA REAL DE TU BRÓKER PARA CADA PAR ---
                    # df = obtener_vela_m5_broker(par)
                    # df = calcular_cinco_estrategias(df)
                    # resultado = evaluar_vela_m5(df)
                    
                    resultado = 'VALIDA' # Simulación por defecto
                    
                    if resultado == 'SENAL_FALSA':
                        asunto = f"⚠️ ALERTA DE INVALIDACIÓN: {par} (M5)"
                        cuerpo = (
                            f"Par: {par}\n"
                            f"Hora UTC-4: {ahora.strftime('%Y-%m-%d %H:%M:%S')}\n"
                            "Motivo: La vela M5 presentó indecisión o fallo en la confluencia de las 5 estrategias.\n"
                            "ACCIÓN: Descartar operación."
                        )
                        enviar_alerta_correo(asunto, cuerpo)
                        cooldown_pares[par] = time.time()
                
                time.sleep(240)
            
            time.sleep(15)
            
        except Exception as e:
            print(f"Error crítico en el bucle 24/7: {e}. Reiniciando ciclo en 10 segundos...")
            time.sleep(10)

if __name__ == "__main__":
    ciclo_principal_247()
