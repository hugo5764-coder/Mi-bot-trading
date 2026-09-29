import os
import requests
import time
from datetime import datetime
import pytz
import pandas as pd
import numpy as np

TWELVE_DATA_API_KEY = "f0c27fa81ca04860bb8857c44091ad5b"
NTFY_TOPIC = "hugo-bot-trading-2026"

TZ_UTC4 = pytz.timezone('America/Caracas')

PARES_DIVISAS = ["GBP/JPY", "USD/JPY", "USD/CAD", "EUR/USD"]

HORA_INICIO = 6
HORA_FIN = 11

ultimo_envio_ts = 0

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
        return df
    except Exception as e:
        print(f"Error {par} {intervalo}: {e}")
        return None

def enviar_alerta_ntfy(asunto, mensaje):
    """Envía notificación push instantánea por ntfy"""
    try:
        r = requests.post(
            f"https://ntfy.sh/{NTFY_TOPIC}",
            data=mensaje.encode('utf-8'),
            headers={
                "Title": asunto,
                "Priority": "urgent",
                "Tags": "rotating_light,chart_with_upwards_trend"
            },
            timeout=10
        )
        if r.status_code == 200:
            print(f"[{datetime.now(TZ_UTC4).strftime('%H:%M:%S')}] NTFY OK: {asunto}")
        else:
            print(f"Error NTFY: {r.status_code}")
    except Exception as e:
        print(f"Error NTFY: {e}")

def calcular_indicadores(df):
    df['EMA_9'] = df['close'].ewm(span=9, adjust=False).mean()
    df['EMA_21'] = df['close'].ewm(span=21, adjust=False).mean()
    df['EMA_50'] = df['close'].ewm(span=50, adjust=False).mean()
    delta = df['close'].diff()
    gain = (delta.where(delta > 0, 0)).rolling(window=14).mean()
    loss = (-delta.where(delta < 0, 0)).rolling(window=14).mean()
    rs = gain / loss
    df['RSI'] = 100 - (100 / (1 + rs))
    exp1 = df['close'].ewm(span=12, adjust=False).mean()
    exp2 = df['close'].ewm(span=26, adjust=False).mean()
    df['MACD'] = exp1 - exp2
    df['MACD_Signal'] = df['MACD'].ewm(span=9, adjust=False).mean()
    df['MACD_Hist'] = df['MACD'] - df['MACD_Signal']
    return df

def tendencia(df):
    df = calcular_indicadores(df)
    u = df.iloc[-1]
    if u['EMA_9'] > u['EMA_21']:
        return 'ALCISTA'
    if u['EMA_9'] < u['EMA_21']:
        return 'BAJISTA'
    return 'LATERAL'

def analizar_vela_en_formacion(df_m5):
    vela = df_m5.iloc[-1]
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

    confirmaciones = 0
    if prop_cuerpo >= 0.40: confirmaciones += 1
    if mecha_total <= 0.30: confirmaciones += 1

    posicion_cierre = (vela['close'] - vela['low']) / rango
    if direccion == 'COMPRA' and posicion_cierre >= 0.68: confirmaciones += 1
    elif direccion == 'VENTA' and posicion_cierre <= 0.32: confirmaciones += 1

    if not pd.isna(vela['RSI']):
        if direccion == 'COMPRA' and 50 < vela['RSI'] < 82: confirmaciones += 1
        elif direccion == 'VENTA' and 18 < vela['RSI'] < 50: confirmaciones += 1

    if not pd.isna(vela['MACD_Hist']):
        if direccion == 'COMPRA' and vela['MACD_Hist'] > 0: confirmaciones += 1
        elif direccion == 'VENTA' and vela['MACD_Hist'] < 0: confirmaciones += 1

    if confirmaciones >= 3:
        return (direccion, prop_cuerpo, confirmaciones)
    return None

def ciclo_principal_247():
    global ultimo_envio_ts
    print(f"[{datetime.now(TZ_UTC4)}] Bot v34 - NTFY INSTANTANEO (6AM a 11AM).")
    while True:
        try:
            ahora = datetime.now(TZ_UTC4)
            minuto = ahora.minute
            segundo = ahora.second
            hora_actual = ahora.hour
            dia_semana = ahora.weekday()
            ahora_ts = time.time()
            en_horario = (0 <= dia_semana <= 4) and (HORA_INICIO <= hora_actual < HORA_FIN)

            minutos_analisis = [3, 18, 33, 48]

            if (minuto in minutos_analisis) and (segundo < 20) and (ahora_ts - ultimo_envio_ts > 800):
                ultimo_envio_ts = ahora_ts
                if not en_horario:
                    continue

                print(f"[{ahora.strftime('%H:%M:%S')}] Analizando 4 pares...")
                candidatos = []

                for par in PARES_DIVISAS:
                    df_m5 = obtener_velas(par, "5min")
                    if df_m5 is None or len(df_m5) < 20:
                        continue
                    df_m5 = calcular_indicadores(df_m5)
                    resultado = analizar_vela_en_formacion(df_m5)
                    if not resultado:
                        continue
                    direccion, fuerza, conf = resultado

                    df_m15 = obtener_velas(par, "15min")
                    if df_m15 is None or len(df_m15) < 20:
                        continue
                    tend_m15 = tendencia(df_m15)

                    alineado = False
                    if direccion == 'COMPRA' and tend_m15 == 'ALCISTA':
                        alineado = True
                    elif direccion == 'VENTA' and tend_m15 == 'BAJISTA':
                        alineado = True

                    if not alineado:
                        continue

                    candidatos.append((par, direccion, fuerza, conf, tend_m15))

                if candidatos:
                    candidatos.sort(key=lambda x: x[2], reverse=True)
                    par, direccion, fuerza, conf, tend_m15 = candidatos[0]

                    par_limpio = par.replace("/", "")
                    emoji = "🟢" if direccion == "COMPRA" else "🔴"
                    asunto = f"{emoji} {par_limpio} {direccion} | Fuerza {fuerza*100:.0f}%"
                    cuerpo = (
                        f"{emoji} {par} {direccion}\n"
                        f"Fuerza: {fuerza*100:.1f}%\n"
                        f"Confirmaciones: {conf}/5\n"
                        f"M15: {tend_m15}\n"
                        f"Hora: {ahora.strftime('%H:%M:%S')}\n\n"
                        f"ENTRA AHORA (CALL si es COMPRA, PUT si es VENTA)\n"
                        f"Vencimiento: 5 min"
                    )
                    enviar_alerta_ntfy(asunto, cuerpo)
                    print(f"[{ahora.strftime('%H:%M:%S')}] ENVIADO: {par} {direccion}")
                else:
                    print(f"[{ahora.strftime('%H:%M:%S')}] Sin candidatos.")

            time.sleep(5)
        except Exception as e:
            print(f"Error critico: {e}")
            time.sleep(5)

if __name__ == "__main__":
    ciclo_principal_247()
