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

predicciones = {}
ultima_preventiva_ts = 0
ultima_correccion_ts = 0

def obtener_vela_m5_broker(par):
    simbolo = f"{par}=X"
    url = f"https://query1.finance.yahoo.com/v8/finance/chart/{simbolo}?interval=5m&range=1d"
    try:
        headers = {'User-Agent': 'Mozilla/5.0'}
        r = requests.get(url, timeout=10, headers=headers)
        if r.status_code != 200:
            print(f"Yahoo error {par}: {r.status_code}")
            return None
        data = r.json()
        result = data.get('chart', {}).get('result')
        if not result:
            print(f"Yahoo sin datos para {par}")
            return None
        res = result[0]
        timestamps = res.get('timestamp', [])
        quote = res['indicators']['quote'][0]
        opens = quote.get('open', [])
        highs = quote.get('high', [])
        lows = quote.get('low', [])
        closes = quote.get('close', [])
        volumes = quote.get('volume', [])

        rows = []
        for i in range(len(timestamps)):
            if opens[i] is None or closes[i] is None:
                continue
            rows.append({
                'timestamp': timestamps[i] * 1000,
                'open': float(opens[i]),
                'high': float(highs[i]),
                'low': float(lows[i]),
                'close': float(closes[i]),
                'volume': float(volumes[i]) if volumes[i] else 0
            })
        if not rows:
            return None
        df = pd.DataFrame(rows)
        df['close_time'] = df['timestamp'] + (5 * 60 * 1000)
        return df
    except Exception as e:
        print(f"Error {par}: {e}")
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
            print(f"[{datetime.now(TZ_UTC4).strftime('%H:%M:%S')}] Enviado: {asunto}")
        else:
            print(f"Error Resend: {r.status_code}")
    except Exception as e:
        print(f"Error Resend: {e}")

def calcular_indicadores(df):
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
    return df

def analizar_vela(row):
    rango = row['high'] - row['low']
    if rango <= 0:
        return None
    cuerpo = abs(row['close'] - row['open'])
    prop_cuerpo = cuerpo / rango
    if prop_cuerpo < 0.30:
        return None
    posicion_cierre = (row['close'] - row['low']) / rango

    if row['close'] > row['open']:
        if posicion_cierre < 0.55:
            return None
        puntos = 0
        if row['EMA_9'] > row['EMA_21']: puntos += 1
        if row['RSI'] > 50: puntos += 1
        if row['close'] > row['BB_Mid']: puntos += 1
        if row['MACD'] > row['MACD_Signal']: puntos += 1
        if puntos >= 2:
            return 'COMPRA'
        return None

    if row['close'] < row['open']:
        if posicion_cierre > 0.45:
            return None
        puntos = 0
        if row['EMA_9'] < row['EMA_21']: puntos += 1
        if row['RSI'] < 50: puntos += 1
        if row['close'] < row['BB_Mid']: puntos += 1
        if row['MACD'] < row['MACD_Signal']: puntos += 1
        if puntos >= 2:
            return 'VENTA'
        return None

    return None

def ciclo_principal_247():
    global ultima_preventiva_ts, ultima_correccion_ts
    print(f"[{datetime.now(TZ_UTC4)}] Bot Maestro M5 iniciado 24/7 (Yahoo Finance).")
    while True:
        try:
            ahora = datetime.now(TZ_UTC4)
            minuto = ahora.minute
            ahora_ts = time.time()

            if (minuto % 5 in [3, 8]) and (ahora_ts - ultima_preventiva_ts > 240):
                ultima_preventiva_ts = ahora_ts
                print(f"[{ahora.strftime('%H:%M:%S')}] Analizando velas...")
                señales = 0
                for par in PARES_DIVISAS:
                    df = obtener_vela_m5_broker(par)
                    if df is None:
                        continue
                    df = calcular_indicadores(df)
                    vela = df.iloc[-1]
                    señal = analizar_vela(vela)
                    if señal == 'COMPRA':
                        señales += 1
                        predicciones[par] = 'COMPRA'
                        enviar_alerta_correo(
                            f"🟢 {par} prev 2min",
                            f"🟢 {par} prev 2min - Preparar COMPRA"
                        )
                    elif señal == 'VENTA':
                        señales += 1
                        predicciones[par] = 'VENTA'
                        enviar_alerta_correo(
                            f"🔴 {par} prev 2min",
                            f"🔴 {par} prev 2min - Preparar VENTA"
                        )
                print(f"[{ahora.strftime('%H:%M:%S')}] Señales enviadas: {señales}")

            if (minuto % 5 in [0, 5]) and (ahora_ts - ultima_correccion_ts > 240):
                ultima_correccion_ts = ahora_ts
                now_ms = int(time.time() * 1000)
                print(f"[{ahora.strftime('%H:%M:%S')}] Verificando cierres...")
                for par in list(predicciones.keys()):
                    direccion = predicciones[par]
                    df = obtener_vela_m5_broker(par)
                    if df is None:
                        del predicciones[par]
                        continue
                    df = calcular_indicadores(df)
                    cerradas = df[df['close_time'] < now_ms]
                    if len(cerradas) < 1:
                        del predicciones[par]
                        continue
                    vela_cerrada = cerradas.iloc[-1]
                    señal_cierre = analizar_vela(vela_cerrada)
                    if señal_cierre != direccion:
                        enviar_alerta_correo(
                            f"❌ {par} FALSA",
                            f"❌ {par} FALSA - NO OPERAR"
                        )
                    del predicciones[par]

            time.sleep(10)
        except Exception as e:
            print(f"Error crítico: {e}")
            time.sleep(10)

if __name__ == "__main__":
    ciclo_principal_247()
