import os
import requests
import time
from datetime import datetime
import pytz
import pandas as pd
import numpy as np

RESEND_API_KEY = os.getenv("RESEND_API_KEY") 
EMAIL_ORIGEN = "onboarding@resend.dev" 
EMAIL_DESTINO = "hugo5764@gmail.com"

TZ_UTC4 = pytz.timezone('America/Caracas')

PARES_DIVISAS = [
    "EURUSD", "GBPUSD", "USDJPY", "AUDUSD", "USDCAD",
    "NZDUSD", "EURGBP", "EURJPY", "GBPJPY", "AUDJPY"
]

cooldown_pares = {par: 0 for par in PARES_DIVISAS}

def enviar_alerta_correo(asunto, mensaje):
    try:
        response = requests.post(
            "https://api.resend.com/emails",
            headers={
                "Authorization": f"Bearer {RESEND_API_KEY}",
                "Content-Type": "application/json",
            },
            json={
                "from": EMAIL_ORIGEN,
                "to": [EMAIL_DESTINO],
                "subject": asunto,
                "text": mensaje,
            },
        )
        if response.status_code == 200:
            print(f"[{datetime.now(TZ_UTC4).strftime('%H:%M:%S')}] Alerta enviada a {EMAIL_DESTINO}")
        else:
            print(f"Error al enviar con Resend: {response.status_code} - {response.text}")
    except Exception as e:
        print(f"Error de conexión con Resend: {e}")

def calcular_cinco_estrategias(df):
    df['EMA_9'] = df['close'].ewm(span=9, adjust=False).mean()
    df['EMA_21'] = df['close'].ewm(span=21, adjust=False).mean()
    delta = df['close'].diff()
    gain = (delta.where(delta > 0, 0)).rolling(window=14).mean()
    loss = (-delta.where(delta < 0, 0)).rolling(window=14).mean()
    rs = gain / loss
    df['RSI'] = 100 - (100 / (1 + rs))
    df['BB_Mid'] = df['close'].rolling(window=20).mean()
    df['BB_Std'] = df['close'].rolling(window=20).std()
    df['BB_Upper'] = df['BB_Mid'] + (df['BB_Std'] * 2)
    df['BB_Lower'] = df['BB_Mid'] - (df['BB_Std'] * 2)
    exp1 = df['close'].ewm(span=12, adjust=False).mean()
    exp2 = df['close'].ewm(span=26, adjust=False).mean()
    df['MACD'] = exp1 - exp2
    df['MACD_Signal'] = df['MACD'].ewm(span=9, adjust=False).mean()
    df['Cuerpo'] = abs(df['close'] - df['open'])
    df['Rango_Total'] = (df['high'] - df['low']).replace(0, 0.00001)
    df['Proporcion_Cuerpo'] = df['Cuerpo'] / df['Rango_Total']
    return df

def evaluar_vela_m5(df):
    ultima = df.iloc[-1]
    if ultima['Proporcion_Cuerpo'] < 0.80:
        return 'SENAL_FALSA'
    alcista = (
        (ultima['close'] > ultima['open']) and
        (ultima['EMA_9'] > ultima['EMA_21']) and
        (ultima['RSI'] > 55) and
        (ultima['close'] > ultima['BB_Mid']) and
        (ultima['MACD'] > ultima['MACD_Signal']) and
        (ultima['MACD'] > 0)
    )
    bajista = (
        (ultima['close'] < ultima['open']) and
        (ultima['EMA_9'] < ultima['EMA_21']) and
        (ultima['RSI'] < 45) and
        (ultima['close'] < ultima['BB_Mid']) and
        (ultima['MACD'] < ultima['MACD_Signal']) and
        (ultima['MACD'] < 0)
    )
    if alcista or bajista:
        return 'VALIDA'
    else:
        return 'SENAL_FALSA'

def ciclo_principal_247():
    print(f"[{datetime.now(TZ_UTC4)}] Bot Maestro M5 iniciado 24/7.")
    while True:
        try:
            ahora = datetime.now(TZ_UTC4)
            minuto_actual = ahora.minute
            if minuto_actual % 5 == 1:
                for par in PARES_DIVISAS:
                    if time.time() - cooldown_pares[par] < 900:
                        continue
                    resultado = 'VALIDA' 
                    if resultado == 'SENAL_FALSA':
                        asunto = f"⚠️ ALERTA DE INVALIDACIÓN: {par} (M5)"
                        cuerpo = (
                            f"Par: {par}\n"
                            f"Hora UTC-4: {ahora.strftime('%Y-%m-%d %H:%M:%S')}\n"
                            "Motivo: La vela M5 presentó indecisión o fallo en la confluencia.\n"
                            "ACCIÓN: Descartar operación."
                        )
                        enviar_alerta_correo(asunto, cuerpo)
                        cooldown_pares[par] = time.time()
                time.sleep(240)
            time.sleep(15)
        except Exception as e:
            print(f"Error critico: {e}. Reinciando...")
            time.sleep(10)

if __name__ == "__main__":
    ciclo_principal_247()
