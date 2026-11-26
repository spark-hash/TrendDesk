from datetime import datetime, timedelta

from fastapi.testclient import TestClient
import httpx
import pytest

from app.filings import annual_cards
from app.main import create_app
from app.market import ET, completed
from app.market_studies import divergence, ema, intraday, long_term, wilder_rsi, weekly
from app.provider import normalize_bars
from app.store import Store
from app.technicals import geometry, patterns


def test_cross_level_priorities_and_confluence(monkeypatch):
    from app import cross_levels as cross
    now=datetime(2026,11,25,16,0,3,tzinfo=ET)
    monkeypatch.setattr(cross,'expected_last_close',lambda tf,now:now.replace(hour=9,minute=0))
    frames={tf:[dict(time='2026-11-25T15:00:00-05:00',close=100,high=104,low=92)] for tf in ('1M','60m','5m')}
    def level(price,touches):
        return ['支撑 1','',price,'',price,dict(touches=touches,strength='弱' if touches==1 else '强')]
    studies={}
    for tf,price,count in [('1M',90,1),('60m',98,5),('5m',90.05,2)]:
        studies[tf]=({},[level(price,count)])
    zones=cross.ranked_zones(frames,studies,now)
    monthly=next(z for z in zones if z['price']==90)
    hourly=next(z for z in zones if z['price']==98)
    assert monthly['priority']<hourly['priority'] and hourly['near']
    assert monthly['periods']==['月线','5 分钟'] and monthly['high']==90.05


def series(n,step=.1):
    start=datetime(2026,11,25,9,30,tzinfo=ET)
    return [dict(time=(start+timedelta(minutes=i)).isoformat(),open=100+i*step,close=100+i*step,
                 low=99+i*step,high=101+i*step,volume=100) for i in range(n)]


def test_channel_platform_patterns():
    up=series(80)
    assert geometry(up)[0]['channel']['status']=='上升通道'
    assert geometry(series(80,-.1))[0]['channel']['status']=='下降通道'
    flat=series(30,0)
    flat[-1].update(open=102,high=106,close=105)
    cards,lines=geometry(flat)
    assert cards['platform']['status']=='向上突破'
    assert '平台上沿' in [line[0] for line in lines]
    b=series(24,0)
    b[-2].update(open=105,close=99,high=106,low=98)
    b[-1].update(open=100,close=102,high=103,low=99)
    harami=patterns(b,2,[],[])['harami']
    assert harami['status']=='阳线'
    assert harami['overlay']['candles']==[[b[-2]['time'],98,106],[b[-1]['time'],99,103]]
    for idx,h in [(3,105),(9,108),(15,105)]: b[idx]['high']=h
    b[-2]['close']=100
    b[-1]['close']=98
    shape=patterns(b,1,[3,9,15],[])['top3']
    assert shape['status']=='收盘越过颈线'
    assert shape['overlay']['points'][::2]==[[b[i]['time'],b[i]['high']] for i in (3,9,15)]
    assert shape['overlay']['neck'][-1]==[b[-1]['time'],99]
    b[-1]['close']=100
    assert patterns(b,1,[3,9,15],[])['top3']['overlay']['pending']
    assert 'overlay' not in patterns(b,1,[],[])['bottom3']


def test_intraday_warmup_vwap_and_divergence():
    assert ema([1,2,3,4],3)==[None,None,2,3]
    assert wilder_rsi([1]*16)[-1]==50
    assert wilder_rsi(list(range(20)))[-1]==100
    b=series(45)
    for row in b[:-3]: row['time']=row['time'].replace('11-25','11-24')
    cards,rows=intraday(b)
    assert len(rows)==3 and rows[0]['vwap']==pytest.approx(b[-3]['close'])
    assert rows[-1]['dif'] is not None and '预热不足' not in cards['macd']['status']
    b=series(20,0)
    for row in b: row['rsi']=50
    b[8].update(high=105,rsi=80)
    b[15].update(high=107,rsi=70)
    assert divergence(b,'rsi')['status']=='顶背离'
    assert divergence(b[:17],'rsi')['status']!='顶背离'


def test_point_score_uses_only_known_minutes_and_marks_missing_volume():
    from app.point_score import minute_score
    bars=series(70)
    _,rows=intraday(bars)
    before=minute_score(rows,40)
    assert datetime.fromisoformat(before['as_of']) == datetime(2026,11,25,10,11,tzinfo=ET)
    assert before['total'] is not None
    assert sum(r['points'] for r in before['setups'][0]['rows'])==before['total']
    for b in bars[41:]:
        b.update(close=500,high=501,volume=9999999)
    assert minute_score(intraday(bars)[1],40)==before
    assert minute_score(rows,0)['total'] is None
    assert minute_score(rows[1:],39)['total'] is None


def test_key_level_lines_carry_the_card_strength():
    bars=series(60,0)
    for i in (8,20,32): bars[i]['low']=97
    bars[12]['high']=105
    cards,lines=geometry(bars)
    for prefix,key,count,expected in [('支撑','support1',3,'强'),('阻力','resistance1',1,'弱')]:
        line=next(line for line in lines if line[0]==prefix+' 1')
        assert line[5]==dict(strength=expected,touches=count)
        assert expected in cards[key]['status']


def test_closed_minutes_week_holiday_and_long_window():
    b=dict(open=100,high=101,low=99,close=100,volume=7,time_key='2026-11-25 09:31:00')
    normalized=normalize_bars([b],'1m')
    assert normalized[0]['time'][11:16]=='09:30'
    assert not completed(normalized,'1m',datetime(2026,11,25,9,31,2,tzinfo=ET))
    days=series(4)
    for row,day in zip(days,[23,24,25,27]): row['time']=f'2026-11-{day}T00:00:00-05:00'
    assert weekly(days[:-1])==[]
    assert weekly(days)[0]['volume']==400
    assert '长期趋势未确认' in long_term(series(230,-.05))['timing']['status']


def test_fiscal_yoy_aligns_periods_and_excludes_future():
    def row(year,val):
        return dict(form='10-K',start=f'{year}-01-01',end=f'{year}-12-31',filed=f'{year+1}-02-01',val=val)
    data={'facts':{'us-gaap':{'Revenues':{'units':{'USD':[row(2023,100),row(2024,120),row(2025,140)]}},
                               'NetIncomeLoss':{'units':{'USD':[row(2024,24)]}}}}}
    cards=annual_cards(data,'2025-12-31')
    assert cards['growth']['status']=='+20.00%' and cards['margin']['status']=='20.00%'


def test_focused_ai_uses_server_evidence_and_rejects_stale_view(tmp_path,monkeypatch):
    monkeypatch.setenv('OPENAI_API_KEY','test-only')
    sample={'symbol':'AAPL','sections':{'intraday':{'rsi':{'status':'55'},'macd':{'status':'other'}}},
            'times':{'intraday':'snapshot'},'expected_minute':'snapshot','minute_gaps':0,'errors':{},
            'intraday_overlay':{'events':[{'id':'platform_1013_first','at':'10:13 ET',
                                           'facts':['触发时的固定上沿 212.50']}]}}
    monkeypatch.setattr('app.market_studies.StudyFeed.read',lambda self,code,tf,section:sample)
    bodies=[]
    def respond(url,**kwargs):
        bodies.append(kwargs['json'])
        return httpx.Response(200,request=httpx.Request('POST',url),json={'status':'completed','model':'test',
            'usage':{'total_tokens':11},'output':[{'type':'message','content':[{'type':'output_text','text':'测试'}]}]})
    monkeypatch.setattr(httpx,'post',respond)
    with TestClient(create_app(Store(tmp_path/'research.db'),run_worker=False)) as client:
        url='/api/studies/AAPL/analysis?section=intraday&focus=rsi&profile=deep'
        headers={'X-TrendDesk':'local'}
        assert client.post(url+'&as_of=outdated',headers=headers).status_code==409
        out=client.post(url+'&as_of=snapshot',headers=headers).json()
        assert out['focus']=='rsi' and out['tokens']['total_tokens']==11 and len(bodies)==1
        assert 'other' not in bodies[0]['input'] and '55' in bodies[0]['input']
        event=client.post(url.replace('focus=rsi','focus=platform_1013_first')+'&as_of=snapshot',headers=headers)
        assert event.json()['as_of']=='10:13 ET' and '212.50' in bodies[-1]['input']
        assert 'other' not in bodies[-1]['input']
