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

# SOLO 2 PARES para reducir consumo
PARES_DIVISAS = ["GBP/JPY", "USD/JPY"]

HORA_INICIO = 5
HORA_FIN = 12

predicciones = {}
ultima_preventiva_ts = 0

def obtener_vela_m5_broker(par):
    url = "https://api.twelvedata.com/time_series"
    params = {
        "symbol": par,
        "interval": "5min",
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
        if len(values) < 5:
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
    high_low = df['high'] - df['low']
    high_close = abs(df['high'] - df['close'].shift())
    low_close = abs(df['low'] - df['close'].shift())
    tr = pd.concat([high_low, high_close, low_close], axis=1).max(axis=1)
    up = df['high'].diff()
    down = -df['low'].diff()
    plus_dm = np.where((up > down) & (up > 0), up, 0.0)
    minus_dm = np.where((down > up) & (down > 0), down, 0.0)
    tr_smooth = tr.rolling(window=14).sum()
    plus_di = 100 * pd.Series(plus_dm).rolling(window=14).sum() / tr_smooth
    minus_di = 100 * pd.Series(minus_dm).rolling(window=14).sum() / tr_smooth
    dx = 100 * abs(plus_di - minus_di) / (plus_di + minus_di)
    df['ADX'] = dx.rolling(window=14).mean()
    return df

def analizar_vela(df, idx):
    vela = df.iloc[idx]
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

    # FILTROS ESTRICTOS para más calidad
    if prop_cuerpo < 0.50:
        return None
    if mecha_total > 0.28:
        return None

    posicion_cierre = (vela['close'] - vela['low']) / rango
    if direccion == 'COMPRA' and posicion_cierre < 0.72:
        return None
    if direccion == 'VENTA' and posicion_cierre > 0.28:
        return None

    puntos = 0
    if prop_cuerpo >= 0.60:
        puntos += 2
    elif prop_cuerpo >= 0.50:
        puntos += 1
    if mecha_sup / rango <= 0.14:
        puntos += 1
    if mecha_inf / rango <= 0.14:
        puntos += 1
    if direccion == 'COMPRA' and vela['EMA_9'] > vela['EMA_21']:
        puntos += 1
    if direccion == 'VENTA' and vela['EMA_9'] < vela['EMA_21']:
        puntos += 1
    if direccion == 'COMPRA' and 55 < vela['RSI'] < 80:
        puntos += 1
    if direccion == 'VENTA' and 20 < vela['RSI'] < 45:
        puntos += 1
    if direccion == 'COMPRA' and vela['close'] > vela['BB_Mid']:
        puntos += 1
    if direccion == 'VENTA' and vela['close'] < vela['BB_Mid']:
        puntos += 1
    if direccion == 'COMPRA' and vela['MACD'] > vela['MACD_Signal']:
        puntos += 1
    if direccion == 'VENTA' and vela['MACD'] < vela['MACD_Signal']:
        puntos += 1
    if not pd.isna(vela['ADX']) and vela['ADX'] >= 22:
        puntos += 1

    if puntos >= 8:  # Subí de 7 a 8 para más calidad
        return (direccion, prop_cuerpo, puntos)
    return None

def ciclo_principal_247():
    global ultima_preventiva_ts
    print(f"[{datetime.now(TZ_UTC4)}] Bot Maestro M5 iniciado (v25 - 2 PARES + CALIDAD ALTA).")
    while True:
        try:
            ahora = datetime.now(TZ_UTC4)
            minuto = ahora.minute
            segundo = ahora.second
            hora_actual = ahora.hour
            dia_semana = ahora.weekday()
            ahora_ts = time.time()
            en_horario = (0 <= dia_semana <= 4) and (HORA_INICIO <= hora_actual < HORA_FIN)

            # Analisis cada 5 min en minuto 0
            if (minuto % 5 == 0) and (segundo < 30) and (ahora_ts - ultima_preventiva_ts > 240):
                ultima_preventiva_ts = ahora_ts
                predicciones.clear()  # Limpiar predicciones viejas

                if not en_horario:
                    continue

                print(f"[{ahora.strftime('%H:%M:%S')}] Analizando velas CERRADAS...")
                candidatos = []
                for par in PARES_DIVISAS:
                    df = obtener_vela_m5_broker(par)
                    if df is None or len(df) < 5:
                        continue
                    df = calcular_indicadores(df)
                    resultado = analizar_vela(df, len(df) - 1)
                    if resultado:
                        candidatos.append((par, resultado[0], resultado[1], resultado[2]))
                        print(f"[CANDIDATO] {par}: {resultado[0]} {resultado[2]}/10")

                if candidatos:
                    candidatos.sort(key=lambda x: x[3], reverse=True)
                    par, direccion, fuerza, pts = candidatos[0]
                    par_limpio = par.replace("/", "")
                    predicciones[par] = direccion
                    emoji = "🟢" if direccion == "COMPRA" else "🔴"
                    asunto = f"{emoji} {par_limpio} {direccion} | {pts}/10 pts"
                    cuerpo = (
                        f"{emoji} {par} {direccion}\n"
                        f"Puntaje: {pts}/10\n"
                        f"Fuerza: {fuerza*100:.1f}%\n"
                        f"Hora: {ahora.strftime('%H:%M:%S')}"
                    )
                    enviar_alerta_correo(asunto, cuerpo)
                else:
                    print(f"[{ahora.strftime('%H:%M:%S')}] Sin candidatos.")

            # Verificación 2 min después (minuto 2)
            if (minuto % 5 == 2) and (segundo < 30):
                if not en_horario or not predicciones:
                    continue
                print(f"[{ahora.strftime('%H:%M:%S')}] Confirmando vela...")
                for par in list(predicciones.keys()):
                    direccion = predicciones[par]
                    df = obtener_vela_m5_broker(par)
                    if df is None or len(df) < 5:
                        continue
                    df = calcular_indicadores(df)
                    resultado = analizar_vela(df, len(df) - 1)
                    if not resultado or resultado[0] != direccion:
                        par_limpio = par.replace("/", "")
                        asunto = f"❌ {par_limpio} FALSA | NO OPERAR"
                        cuerpo = (
                            f"❌ {par} FALSA\n"
                            f"Hora: {ahora.strftime('%H:%M:%S')}\n"
                            "La nueva vela NO confirma. NO OPERAR."
                        )
                        enviar_alerta_correo(asunto, cuerpo)
                    predicciones.clear()

            time.sleep(10)
        except Exception as e:
            print(f"Error crítico: {e}")
            time.sleep(10)

if __name__ == "__main__":
    ciclo_principal_247()
