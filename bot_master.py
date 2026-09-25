import os
import requests
import time
from datetime import datetime
import pytz
import pandas as pd
import numpy as np

TWELVE_DATA_API_KEY = "f0c27fa81ca04860bb8857c44091ad5b"
RESEND_API_KEY = os.getenv("RESEND_API_KEY")
EMAIL_ORIGEN = "onboarding@resend.dev"
EMAIL_DESTINO = "hugo5764@gmail.com"

TZ_UTC4 = pytz.timezone('America/Caracas')

# 4 pares de Pocket Option
PARES_DIVISAS = ["GBP/JPY", "USD/JPY", "USD/CAD", "EUR/USD"]

HORA_INICIO = 5
HORA_FIN = 12

ultima_preventiva_ts = 0

def obtener_velas(par, intervalo):
    url = "https://api.twelvedata.com/time_series"
    params = {
        "symbol": par,
        "interval": intervalo,
        "outputsize": 100,
        "apikey": TWELVE_DATA_API_KEY,
        "timezone": "America/Caracas"
    }
    try:
        r = requests.get(url, params=params, timeout=10)
        if r.status_code != 200:
            return None
        data = r.json()
        if data.get("status") == "error":
            return None
        values = data.get("values", [])
        if len(values) < 20:
            return None
        rows = []
        for v in reversed(values):
            rows.append({
                'datetime': v['datetime'],
                'open': float(v['open']),
                'high': float(v['high']),
                'low': float(v['low']),
                'close': float(v['close']),
                'volume': float(v.get('volume', 0)) if v.get('volume') else 0
            })
        df = pd.DataFrame(rows)
        df = df[df['open'] != df['close']]
        return df
    except Exception as e:
        print(f"Error {par} {intervalo}: {e}")
        return None

def enviar_alerta_correo(asunto, mensaje):
    try:
        r = requests.post(
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
        if r.status_code == 200:
            print(f"[{datetime.now(TZ_UTC4).strftime('%H:%M:%S')}] OK: {asunto}")
        else:
            print(f"Error Resend: {r.status_code}")
    except Exception as e:
        print(f"Error Resend: {e}")

def calcular_indicadores(df):
    df['EMA_9'] = df['close'].ewm(span=9, adjust=False).mean()
    df['EMA_21'] = df['close'].ewm(span=21, adjust=False).mean()
    df['EMA_50'] = df['close'].ewm(span=50, adjust=False).mean()
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
    df['ROC'] = df['close'].pct_change(periods=3) * 100
    df['Vol_Avg'] = df['volume'].rolling(window=20).mean()
    return df

def tendencia(df):
    df = calcular_indicadores(df)
    ultima = df.iloc[-1]
    if ultima['EMA_9'] > ultima['EMA_21'] > ultima['EMA_50']:
        return 'ALCISTA'
    if ultima['EMA_9'] < ultima['EMA_21'] < ultima['EMA_50']:
        return 'BAJISTA'
    return 'LATERAL'

def analizar_m5(df):
    vela = df.iloc[-1]
    rango = vela['high'] - vela['low']
    if rango <= 0:
        return None

    cuerpo = abs(vela['close'] - vela['open'])
    prop_cuerpo = cuerpo / rango
    mecha_sup = vela['high'] - max(vela['close'], vela['open'])
    mecha_inf = min(vela['close'], vela['open']) - vela['low']
    mecha_total = (mecha_sup + mecha_inf) / rango

    if vela['close'] > vela['open']:
        direccion = 'COMPRA'
    elif vela['close'] < vela['open']:
        direccion = 'VENTA'
    else:
        return None

    if prop_cuerpo < 0.50:
        return None
    if mecha_total > 0.25:
        return None

    posicion_cierre = (vela['close'] - vela['low']) / rango
    if direccion == 'COMPRA' and posicion_cierre < 0.75:
        return None
    if direccion == 'VENTA' and posicion_cierre > 0.25:
        return None

    if pd.isna(vela['ROC']):
        return None
    if direccion == 'COMPRA' and vela['ROC'] < 0.05:
        return None
    if direccion == 'VENTA' and vela['ROC'] > -0.05:
        return None

    return (direccion, prop_cuerpo)

def ciclo_principal_247():
    global ultima_preventiva_ts
    print(f"[{datetime.now(TZ_UTC4)}] Bot Maestro v28 - DOBLE CONFLUENCIA (M5+M15).")
    while True:
        try:
            ahora = datetime.now(TZ_UTC4)
            minuto = ahora.minute
            segundo = ahora.second
            hora_actual = ahora.hour
            dia_semana = ahora.weekday()
            ahora_ts = time.time()
            en_horario = (0 <= dia_semana <= 4) and (HORA_INICIO <= hora_actual < HORA_FIN)

            if (minuto % 5 == 0) and (segundo < 25) and (ahora_ts - ultima_preventiva_ts > 240):
                ultima_preventiva_ts = ahora_ts
                if not en_horario:
                    continue

                print(f"[{ahora.strftime('%H:%M:%S')}] Analizando doble confluencia...")
                señales = 0

                for par in PARES_DIVISAS:
                    # Análisis M5
                    df_m5 = obtener_velas(par, "5min")
                    if df_m5 is None or len(df_m5) < 20:
                        continue
                    df_m5 = calcular_indicadores(df_m5)
                    resultado_m5 = analizar_m5(df_m5)
                    if not resultado_m5:
                        continue
                    direccion_m5, fuerza = resultado_m5

                    # Tendencia M15
                    df_m15 = obtener_velas(par, "15min")
                    if df_m15 is None or len(df_m15) < 20:
                        continue
                    tend_m15 = tendencia(df_m15)

                    # Alineación
                    alineado = False
                    if direccion_m5 == 'COMPRA' and tend_m15 == 'ALCISTA':
                        alineado = True
                    elif direccion_m5 == 'VENTA' and tend_m15 == 'BAJISTA':
                        alineado = True

                    if not alineado:
                        print(f"[{par}] M5={direccion_m5} M15={tend_m15} NO alineado")
                        continue

                    señales += 1
                    par_limpio = par.replace("/", "")
                    emoji = "🟢" if direccion_m5 == "COMPRA" else "🔴"
                    asunto = f"{emoji} {par_limpio} {direccion_m5} | Fuerza {fuerza*100:.0f}% | M5+M15 OK"
                    cuerpo = (
                        f"{emoji} {par} {direccion_m5}\n"
                        f"Fuerza M5: {fuerza*100:.1f}%\n"
                        f"Tendencia M15: {tend_m15}\n"
                        f"Hora: {ahora.strftime('%H:%M:%S')}\n\n"
                        "DOBLE CONFLUENCIA OK\n"
                        "Opera en los proximos 2-3 minutos.\n"
                        "Vencimiento: 5 minutos."
                    )
                    enviar_alerta_correo(asunto, cuerpo)
                    print(f"[{ahora.strftime('%H:%M:%S')}] ALERTA {par} {direccion_m5}")

                print(f"[{ahora.strftime('%H:%M:%S')}] Senales: {señales}")

            time.sleep(10)
        except Exception as e:
            print(f"Error critico: {e}")
            time.sleep(10)

if __name__ == "__main__":
    ciclo_principal_247()
