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
    simbolo_binance = par.replace("USD", "USDT")
    url = f"https://api.binance.com/api/v3/klines?symbol={simbolo_binance}&interval=5m&limit=100"
    try:
        r = requests.get(url, timeout=10)
        if r.status_code == 200:
            datos = r.json()
            df = pd.DataFrame(datos, columns=[
                'timestamp', 'open', 'high', 'low', 'close', 'volume',
                'close_time', 'quote_asset_volume', 'number_of_trades',
                'taker_buy_base', 'taker_buy_quote', 'ignore'
            ])
            for c in ['open', 'high', 'low', 'close', 'volume']:
                df[c] = df[c].astype(float)
            df['timestamp'] = df['timestamp'].astype(np.int64)
            df['close_time'] = df['close_time'].astype(np.int64)
            return df
        return None
    except Exception as e:
        print(f"Error: {e}")
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
            print(f"Error Resend: {r.status_code} - {r.text}")
    except Exception as e:
        print(f"Error conexión Resend: {e}")

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
    """Devuelve 'COMPRA', 'VENTA' o None"""
    rango = row['high'] - row['low']
    if rango <= 0:
        return None
    cuerpo = abs(row['close'] - row['open'])
    prop_cuerpo = cuerpo / rango
    
    # Cuerpo mínimo 40%
    if prop_cuerpo < 0.40:
        return None
    
    posicion_cierre = (row['close'] - row['low']) / rango
    
    # VELA VERDE
    if row['close'] > row['open']:
        if posicion_cierre < 0.60:
            return None
        puntos = 0
        if row['EMA_9'] > row['EMA_21']: puntos += 1
        if row['RSI'] > 50: puntos += 1
        if row['close'] > row['BB_Mid']: puntos += 1
        if row['MACD'] > row['MACD_Signal']: puntos += 1
        if puntos >= 2:
            return 'COMPRA'
        return None
    
    # VELA ROJA
    if row['close'] < row['open']:
        if posicion_cierre > 0.40:
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
    print(f"[{datetime.now(TZ_UTC4)}] Bot Maestro M5 iniciado 24/7.")
    while True:
        try:
            ahora = datetime.now(TZ_UTC4)
            minuto = ahora.minute
            ahora_ts = time.time()

            # PREVENTIVA: 2 min antes del cierre (minuto 3 u 8)
            if (minuto % 5 in [3, 8]) and (ahora_ts - ultima_preventiva_ts > 240):
                ultima_preventiva_ts = ahora_ts
                print(f"[{ahora.strftime('%H:%M:%S')}] Analizando velas en formación...")
                señales = 0
                for par in PARES_DIVISAS:
                    df = obtener_vela_m5_broker(par)
                    if df is None:
                        continue
                    df = calcular_indicadores(df)
                    vela_actual = df.iloc[-1]
                    señal = analizar_vela(vela_actual)

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

            # CORRECCIÓN: al cierre exacto (minuto 0 o 5)
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
