"""Deterministic synthetic preview. Never inserted into the live store or alerts."""
import math
import random
from functools import lru_cache
from datetime import timedelta
from .market import now_utc, ET, MINUTES, calendar, market_status, expected_last_close
from .timeframes import SOURCES, derive
from .analysis import analyze

@lru_cache(maxsize=1)
def dataset():
    import pandas as pd
    cal = calendar()
    today = now_utc().astimezone(ET).date()
    last = cal.date_to_session(pd.Timestamp(today)-pd.Timedelta(days=1), direction='previous')
    sessions = cal.sessions_in_range(last-pd.Timedelta(days=540),last)[-330:]
    month_close = expected_last_close('1M').astimezone(ET).date()
    months = {d.strftime('%Y-%m'):d for d in cal.sessions_in_range(last-pd.Timedelta(days=3653),month_close)}
    data = {}
    bases = {'NVDA':145,'AAPL':225,'MSFT':420,'TSLA':310,'AMD':165,'AMZN':215,'META':605,'GOOGL':185,'SPY':590,'QQQ':510}
    for index,(symbol,base) in enumerate(bases.items()):
        rng = random.Random(210+index)
        frames = {}
        for tf in ('1D','60m','15m','5m','1M'):
            times = []
            dates = months.values() if tf=='1M' else sessions if tf=='1D' else sessions[-45 if tf=='60m' else -14:]
            for day in dates:
                opening, closing = cal.session_open(day).to_pydatetime(),cal.session_close(day).to_pydatetime()
                if tf in ('1D','1M'): times.append(opening)
                else:
                    cursor = opening
                    while cursor < closing:
                        times.append(cursor)
                        cursor += timedelta(minutes=MINUTES[tf])
            rows = []
            factor = -.12 if symbol=='TSLA' else .24
            prior = base*(1-factor)
            for i,timestamp in enumerate(times):
                wave = math.sin(i/12)*base*.012 + math.sin(i/3)*base*.003
                close = base*(1-factor+factor*i/len(times))+wave+rng.uniform(-.003,.003)*base
                width = base*(.004 if tf=='1D' else .0018)
                rows.append({'time':timestamp.astimezone(ET).isoformat(),'open':round(prior,2),'close':round(close,2),
                             'high':round(max(prior,close)+rng.uniform(.2,1)*width,2),
                             'low':round(min(prior,close)-rng.uniform(.2,1)*width,2),'volume':rng.randint(900000,2600000)})
                prior=close
            frames[tf]=rows
        for tf,source in SOURCES.items():
            frames[tf]=derive(tf,frames[source])
        data[symbol]=frames
    return data

def state(selected, tf, settings):
    data=dataset()
    selected=selected if selected in data else 'NVDA'
    items=[]
    for symbol,frames in data.items():
        a=analyze(frames,data['SPY']['1D'],settings=settings)
        # Synthetic bars are intentionally labelled; no real freshness claims.
        items.append({'symbol':symbol,'name':{'NVDA':'NVIDIA','AAPL':'Apple','MSFT':'Microsoft','TSLA':'Tesla','AMD':'AMD','AMZN':'Amazon','META':'Meta Platforms','GOOGL':'Alphabet','SPY':'S&P 500 ETF','QQQ':'Nasdaq 100 ETF'}[symbol],
                      'price':frames['1D'][-1]['close'],'change':(frames['1D'][-1]['close']/frames['1D'][-2]['close']-1)*100,
                      'quote_time':None,'quote_fresh':False,'source':'demo','analysis':a,'position':None,'error':None,'synced':False})
    return {'mode':'demo','now':now_utc().isoformat(),'market':market_status(),'connected':False,
            'message':'演示模式 · 所有价格均为合成数据，不产生真实提醒','quota':None,'settings':settings,
            'watchlist':[s for s in data if s not in ('SPY','QQQ')],'items':items,'events':[],
            'selected':selected,'timeframe':tf,'chart':[dict(b,complete=True) for b in data[selected][tf][-240:]]}
