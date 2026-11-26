from datetime import datetime, timedelta, timezone
import pytest
from fastapi.testclient import TestClient
from app.market import ET, bounds, market_status, completed, expected_last_close, is_current
from app.analysis import analyze, trend
from app.provider import normalize_bars
from app.store import Store
from app.engine import Engine
from app.main import create_app

def et(value): return datetime.fromisoformat(value).replace(tzinfo=ET)
def bar(time, close=100, **kwargs):
    return {'time':time,'open':close-.1,'high':close+.3,'low':close-.3,'close':close,'volume':1000,**kwargs}

def test_holiday_early_close_and_dst():
    assert not market_status(et('2026-11-26T12:00:00'))['open']
    assert market_status(et('2026-11-27T12:59:00'))['open']
    assert not market_status(et('2026-11-27T13:00:00'))['open']
    assert market_status(et('2026-11-27T13:00:04'))['close_confirmation']
    assert not market_status(et('2026-11-27T13:02:01'))['close_confirmation']
    assert bounds('2026-07-06')[0].hour==13
    assert bounds('2026-11-30')[0].hour==14

def test_candles_must_close_and_exclude_premarket():
    bars=[bar('2026-11-25T08:00:00-05:00'),bar('2026-11-25T09:30:00-05:00'),bar('2026-11-25T09:45:00-05:00')]
    assert completed(bars,'15m',et('2026-11-25T09:45:02'))==[]
    assert completed(bars,'15m',et('2026-11-25T09:45:03'))==[bars[1]]
    assert len(completed(bars,'15m',et('2026-11-25T10:00:04')))==2

def test_short_final_hour_closes_at_session_close():
    b=bar('2026-11-27T12:30:00-05:00')
    assert completed([b],'60m',et('2026-11-27T13:00:04'))==[b]
    assert expected_last_close('60m',et('2026-11-27T13:01:00'))==et('2026-11-27T13:00:00')

def test_daily_not_complete_before_market_close():
    b=bar('2026-11-25T00:00:00-05:00')
    assert not completed([b],'1D',et('2026-11-25T15:59:00'))
    assert completed([b],'1D',et('2026-11-25T16:00:04'))
    assert is_current([b],'1D',et('2026-11-26T13:00:00'))

def test_normalizer_rejects_bad_prices_and_nan():
    def record(**changes): return {'time_key':'2026-11-25 10:00:00','open':100,'high':102,'low':99,'close':101,'volume':2000}|changes
    result=normalize_bars([record(),record(close=float('nan')),record(low=105),record(volume=-1),record(close=0)])
    assert len(result)==1
    assert result[0]['time'].endswith('-05:00')

def test_moomoo_end_timestamps_are_normalized():
    record={'time_key':'2026-11-25 10:30:00','open':100,'high':102,'low':99,'close':101,'volume':2000}
    first=normalize_bars([record],'60m')[0]
    assert first['time']=='2026-11-25T09:30:00-05:00'
    last=normalize_bars([record|{'time_key':'2026-11-25 16:00:00'}],'60m')[0]
    assert last['time']=='2026-11-25T15:30:00-05:00'
    early=normalize_bars([record|{'time_key':'2026-11-27 13:00:00'}],'60m')[0]
    assert early['time']=='2026-11-27T12:30:00-05:00'
    assert normalize_bars([record|{'time_key':'2026-11-25 09:45:00'}],'15m')[0]['time']=='2026-11-25T09:30:00-05:00'

def test_breakout_signal_uses_prior_levels_and_current_history():
    import pandas as pd
    from app.market import calendar
    cal=calendar()
    days=cal.sessions_in_range('2026-08-01','2026-11-24')[-60:]
    daily=[bar(d.date().isoformat()+'T00:00:00-05:00',80+i*.3) for i,d in enumerate(days)]
    hourly=[]
    for day in cal.sessions_in_range('2026-11-10','2026-11-24'):
        start,end=bounds(day.date().isoformat())
        while start<end:
            hourly.append(bar(start.astimezone(ET).isoformat(),99.5))
            start+=timedelta(hours=1)
    hourly.append(bar('2026-11-25T09:30:00-05:00',99.5))
    minutes=[]
    for day in ('2026-11-24','2026-11-25'):
        start,end=bounds(day)
        end=min(end,et('2026-11-25T10:45:00'))
        while start<end:
            minutes.append(bar(start.astimezone(ET).isoformat(),99.5))
            start+=timedelta(minutes=15)
    minutes[-1]=bar(minutes[-1]['time'],99.95,volume=2000)
    series={'1D':daily,'60m':hourly,'15m':minutes}
    result=analyze(series,now=et('2026-11-25T10:45:04'))
    assert result['fresh']
    assert 'breakout' in [s['kind'] for s in result['signals']]
    assert result['resistance']==99.8
    assert all(c['met'] and c['evidence'] for c in result['conditions']
               if c['group'] in ('顺势突破','共同条件','入场量能'))
    assert datetime.fromisoformat(result['bar_close_time']) == et('2026-11-25T10:45:00')
    from app.entry_score import entry_score
    item = dict(analysis=result, synced=True, quote_fresh=True)
    live = dict(mode='live', market={'open':True}, connected=True, now='2026-11-25T10:45:04-05:00')
    score = entry_score(item, live)
    assert score['total'] == 100 and '可评估开仓' in score['verdict']
    from app.point_score import candle_score
    point=et('2026-11-25T10:45:00')
    historical=candle_score(series,point,{})
    assert historical['total']==100
    extra={tf:[*rows,bar('2026-11-25T12:30:00-05:00',80,volume=99999)] for tf,rows in series.items()}
    assert candle_score(extra,point,{})==historical
    for setup in score['setups']:
        assert sum(r['limit'] for r in setup['rows']) == 100
        assert sum(r['points'] for r in setup['rows']) == setup['total']
        assert all(r['evidence'] for r in setup['rows'])
    assert '暂缓' in entry_score(dict(item, quote_fresh=False), live)['verdict']
    assert '收盘复盘' in entry_score(item, dict(live, market={'open':False}))['verdict']
    assert '等待' in entry_score(item, dict(live, now='2026-11-25T10:50:00-05:00'))['verdict']
    # Unfinished next bar must not affect the trigger, even with an extreme high.
    series['15m'].append(bar('2026-11-25T10:45:00-05:00',200))
    assert analyze(series,now=et('2026-11-25T10:45:04'))==result

def test_trend_and_insufficient_data():
    assert trend([bar('x',i+100) for i in range(60)])['state']=='up'
    assert trend([bar('x',200-i) for i in range(60)])['state']=='down'
    assert trend([bar('x')]*54)['state']=='insufficient'

def test_analysis_ignores_future_candles():
    from app.demo import dataset
    series={tf:list(rows) for tf,rows in dataset()['NVDA'].items()}
    cutoff=et('2026-11-25T16:01:00')
    before=analyze(series,now=cutoff)
    for tf in series: series[tf].append(bar('2030-01-02T10:00:00-05:00',1000000))
    after=analyze(series,now=cutoff)
    assert before==after

def test_event_persistence_and_episode_reset(tmp_path):
    path=tmp_path/'db.sqlite'
    store=Store(path)
    signal={'kind':'breakout','title':'突破','detail':'说明'}
    assert store.event('AAPL',signal,100,'active',{},'AAPL:entry:breakout')
    second=Store(path)
    assert not second.event('AAPL',signal,101,'active',{},'AAPL:entry:breakout')
    second.event('AAPL',{},0,'',{},'AAPL:entry:breakout',reset=True)
    assert second.event('AAPL',signal,102,'active',{},'AAPL:entry:breakout')
    assert len(second.events())==2
    second.acknowledge()
    assert all(e['seen'] for e in second.events())

def test_risk_alert_requires_open_market_and_fresh_quote(tmp_path,monkeypatch):
    import app.engine as engine_module
    now=et('2026-11-25T10:00:30')
    monkeypatch.setattr(engine_module,'now_utc',lambda:now)
    store=Store(tmp_path/'db.sqlite')
    store.position('NVDA',{'quantity':2,'cost':100,'stop':95,'target':120})
    engine=Engine(store)
    engine.connected=True
    engine.loaded['NVDA']='2026-11-25'
    engine.quotes['NVDA']={'price':94,'time':(now-timedelta(minutes=3)).isoformat()}
    engine.evaluate()
    assert not store.events()
    engine.quotes['NVDA']['time']=now.isoformat()
    engine.evaluate();engine.evaluate()
    assert len(store.events())==1
    assert store.events()[0]['kind']=='stop'
    store.position('NVDA',{'quantity':2,'cost':100,'stop':95,'target':120})
    now=et('2026-11-26T10:00:30')
    engine.quotes['NVDA']['time']=now.isoformat()
    engine.evaluate()
    assert len(store.events())==1

@pytest.fixture
def client(tmp_path):
    store=Store(tmp_path/'db.sqlite')
    with TestClient(create_app(store,run_worker=False)) as client:
        yield client,store

def test_api_mutation_validation_and_roundtrip(client):
    c,store=client
    headers={'X-TrendDesk':'local'}
    assert c.post('/api/watchlist',json={'symbol':'IBM'}).status_code==403
    assert c.post('/api/watchlist',headers=headers|{'Origin':'https://evil.example'},json={'symbol':'IBM'}).status_code==403
    assert c.post('/api/watchlist',headers=headers,json={'symbol':'HK.00700'}).status_code==422
    assert c.post('/api/watchlist',headers=headers,json={'symbol':'<script>'}).status_code==422
    assert c.post('/api/watchlist',headers=headers,json={'symbol':'US.IBM'}).json()['symbol']=='IBM'
    assert c.put('/api/positions/IBM',headers=headers,json={'quantity':2,'cost':100,'stop':90,'target':120}).status_code==200
    assert c.put('/api/positions/IBM',headers=headers,json={'quantity':2,'cost':100,'stop':130,'target':120}).status_code==422
    assert store.positions()['IBM']['stop']==90
    assert c.delete('/api/watchlist/IBM',headers=headers).status_code==400
    assert c.delete('/api/positions/IBM',headers=headers).status_code==200
    assert c.delete('/api/watchlist/IBM',headers=headers).status_code==200
    assert c.get('/api/state?mode=live&selected=IBM').json()['mode']=='live'
    before=store.events()
    preview=c.get('/api/state?mode=demo&selected=NVDA').json()
    assert preview['mode']=='demo' and len(preview['chart'])>0
    assert store.events()==before
    assert c.get('/api/events/export').status_code==200
    assert c.get('/',headers={'Host':'evil.example'}).status_code==400
