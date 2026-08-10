import time,schedule,pytz,requests;from datetime import datetime;import ccxt,yfinance as yf,pandas as pd,pandas_ta as ta
A={'Cardano':{'t':'c','s':'ADA/USDT'},'Apple':{'t':'s','s':'AAPL'},'BTC':{'t':'c','s':'BTC/USDT'},'DYDX':{'t':'c','s':'DYDX/USDT'},'ETH':{'t':'c','s':'ETH/USDT'},'Facebook':{'t':'s','s':'META'},'Google':{'t':'s','s':'GOOGL'},'SOL':{'t':'c','s':'SOL/USDT'},'XRP':{'t':'c','s':'XRP/USDT'}}
C=10000;R=0.01;T='5m';L=100;ADX_MIN=25;N="JLikh7092q5p5FPTa6EW";F=True
def d(a):
 if a['t']=='c':
  x=ccxt.binance();o=x.fetch_ohlcv(a['s'],T,L);df=pd.DataFrame(o,columns=['t','o','h','l','c','v']);df['t']=pd.to_datetime(df['t'],unit='ms');return df.set_index('t')
 e=datetime.now(pytz.timezone('America/Caracas'));s=e-pd.Timedelta(minutes=L*5);return yf.download(a['s'],start=s,end=e,interval='5m')
def i(df):
 df['r']=ta.rsi(df['c']);m=ta.macd(df['c']);df=pd.concat([df,m],axis=1);b=ta.bbands(df['c']);df=pd.concat([df,b],axis=1);st=ta.stoch(df['h'],df['l'],df['c']);df=pd.concat([df,st],axis=1);df['a']=ta.atr(df['h'],df['l'],df['c']);df['vm']=df['v'].rolling(20).mean();df['r1']=df['h'].rolling(20).max();df['s1']=df['l'].rolling(20).min();adx=ta.adx(df['h'],df['l'],df['c']);df['ad']=adx['ADX_14'];df['e20']=ta.ema(df['c'],20);df['e50']=ta.ema(df['c'],50);return df
def s(df):
 if df['ad'].iloc[-1]<ADX_MIN:return 'N'
 p=df['c'].iloc[-1];e20=df['e20'].iloc[-1];e50=df['e50'].iloc[-1]
 tr='B' if p>e20 and p>e50 else 'S' if p<e20 and p<e50 else 'N'
 sb=0;ss=0
 if df['r'].iloc[-1]<30 and df['c'].iloc[-1]<=df['s1'].iloc[-2]:sb+=1
 if df['c'].iloc[-1]<=df['BBL_20_2.0'].iloc[-1] and df['MACD_12_26_9'].iloc[-1]>df['MACDs_12_26_9'].iloc[-1]:sb+=1
 if df['c'].iloc[-1]>df['r1'].iloc[-2] and df['v'].iloc[-1]>1.5*df['vm'].iloc[-1]:sb+=1
 if df['STOCHk_14_3_3'].iloc[-1]<20 and df['STOCHk_14_3_3'].iloc[-1]>df['STOCHd_14_3_3'].iloc[-1]:sb+=1
 h=df['h'].iloc[-21:-1].max();l=df['l'].iloc[-21:-1].min()
 if df['c'].iloc[-1]<=l+0.236*(h-l) and df['r'].iloc[-1]>30:sb+=1
 bo=abs(df['c'].iloc[-1]-df['o'].iloc[-1]);tot=df['h'].iloc[-1]-df['l'].iloc[-1]
 if tot>0:
  ls=min(df['o'].iloc[-1],df['c'].iloc[-1])-df['l'].iloc[-1]
  if ls>2*bo and bo<0.3*tot:sb+=1
 if df['c'].iloc[-1]>df['ISA_9_26_52'].iloc[-1] and df['c'].iloc[-1]>df['ISB_9_26_52'].iloc[-1]:sb+=1
 if df['r'].iloc[-1]>70 and df['c'].iloc[-1]>=df['r1'].iloc[-2]:ss+=1
 if df['c'].iloc[-1]>=df['BBU_20_2.0'].iloc[-1] and df['MACD_12_26_9'].iloc[-1]<df['MACDs_12_26_9'].iloc[-1]:ss+=1
 if df['c'].iloc[-1]<df['s1'].iloc[-2] and df['v'].iloc[-1]>1.5*df['vm'].iloc[-1]:ss+=1
 if df['STOCHk_14_3_3'].iloc[-1]>80 and df['STOCHk_14_3_3'].iloc[-1]<df['STOCHd_14_3_3'].iloc[-1]:ss+=1
 if df['c'].iloc[-1]>=h-0.236*(h-l) and df['r'].iloc[-1]<70:ss+=1
 us=df['h'].iloc[-1]-max(df['o'].iloc[-1],df['c'].iloc[-1])
 if tot>0 and us>2*bo and bo<0.3*tot:ss+=1
 if df['c'].iloc[-1]<df['ISA_9_26_52'].iloc[-1] and df['c'].iloc[-1]<df['ISB_9_26_52'].iloc[-1]:ss+=1
 if tr=='B':return 'B' if sb>=3 else 'N'
 elif tr=='S':return 'S' if ss>=3 else 'N'
 else:return 'B' if sb>=3 else ('S' if ss>=3 else 'N')
def al(m):requests.post(f"https://notify.run/{N}",json={"text":m})
def ev():
 for n,info in A.items():
  try:
   df=d(info);df=i(df);p=df['c'].iloc[-1];at=df['a'].iloc[-1];sig=s(df)
   if sig!='N':
    now=datetime.now(pytz.UTC);sec=(5-now.minute%5)*60-now.second
    if sec<0:sec=0;t='CALL' if sig=='B' else 'PUT'
    if 230<=sec<=245:al(f"⏰ PREVENTIVA (4 min) | {n} | {t} | Precio: {p:.4f}")
    elif sec<=5:
     sz=(C*R)/(at*1.5);sl=p-at*1.5 if sig=='B' else p+at*1.5;tp=p+at*3 if sig=='B' else p-at*3
     al(f"🔔 CIERRE VELA M5 | {n}\nSEÑAL: {t}\nPRECIO: {p:.4f}\nSL: {sl:.4f} | TP: {tp:.4f}\nTAMAÑO: {sz:.2f}")
     if sig=='B' and p>df['c'].iloc[-2]+at:al(f"📈 TRAILING | {n} | Precio +1 ATR | Nuevo SL: {df['c'].iloc[-2]+at:.4f}")
     elif sig=='S' and p<df['c'].iloc[-2]-at:al(f"📉 TRAILING | {n} | Precio -1 ATR | Nuevo SL: {df['c'].iloc[-2]-at:.4f}")
  except:pass
def j():print(f"⏳ Escaneando {datetime.now().strftime('%H:%M:%S')} UTC-4");ev()
if __name__=="__main__":print("🤖 BOT 9.8 | CALL/PUT | UTC-4");al("🚀 Bot 9.8 conectado");schedule.every(1).minutes.do(j);[time.sleep(1) or schedule.run_pending() for _ in iter(int,1)]
