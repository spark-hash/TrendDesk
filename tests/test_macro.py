from datetime import date, datetime, timezone
import httpx
import json
import pytest
from fastapi.testclient import TestClient
from app.macro import Macro, analysis_context, bubble_index, indicator, headlines, risk_summary
from app.bubble import breakdown


def test_bubble_detail_uses_one_vintage_and_distinguishes_levels_from_change():
    reading={'date':'2026-11-25','value':63}
    raw={'seriesId':'aibi-2.0','date':reading['date'],'headline':{'value':63,'rank':45,'rankSince':'2019-01-01'},
         'euphoria':{'value':60.8,'band':'Low','rank':28,'rankSince':'2019-01-01'},
         'fragility':{'value':72.8,'band':'High','rank':86,'rankSince':'2019-01-01'},
         'pillars':{'valuation':{'score':50.9,'weight':20},'capex':{'score':99.6,'weight':20}},
         'attribution':[{'pillar':'valuation','points':-.24}],
         'indicators':[{'id':'capex.capex_ocf','value':.95,'asOf':'2026-10-30'},
                       {'id':'valuation.basket_pe','value':19,'asOf':'2026-11-26'}]}
    detail=breakdown(raw,reading)
    assert detail['rank']==45 and '脆弱性' in detail['summary']
    assert len(detail['pillars'])==7
    assert detail['pillars'][0]['contribution']==-.24 and detail['pillars'][2]['contribution'] is None
    assert detail['pillars'][1]['value'] is None
    assert len(detail['evidence'])==1 and detail['evidence'][0]['value']==95
    for changed in [{'date':'2026-11-24'},{'seriesId':'other'},{'headline':{'value':62}}]:
        with pytest.raises(ValueError): breakdown(raw|changed,reading)


def test_bubble_feed_orders_dates_and_keeps_axes_separate():
    def item(day, score, band='Normal'):
        return (f'<item><title>Band change: AI Bubble Index 2.0 at {score} ({band}) on Nov {day}, 2026</title>'
                f'<link>https://aibubblemonitor.com/v2/day/2026-11-{day}</link>'
                f'<pubDate>{day} Nov 2026 22:00:00 GMT</pubDate>'
                '<description>Euphoria 60.8, Fragility 72.8, Demand gauge 41.7, core series 77.2.</description></item>')
    feed='<rss><channel>'+item(25,63)+item(26,90)+item(24,63.5)+'</channel></rss>'
    now=datetime(2026,11,26,12,tzinfo=timezone.utc)
    reading=bubble_index(feed,now)
    assert reading['date']=='2026-11-25' and reading['value']==63 and reading['change']==-.5
    assert reading['band']=='正常' and reading['components']=={'市场热度':60.8,'脆弱性':72.8,'需求缺口':41.7}
    assert [p['date'] for p in reading['history']]==['2026-11-24','2026-11-25']
    cache={'checked':now.isoformat(),'values':{'AIBI':{'data':reading}}}
    fresh=analysis_context(Macro.present(cache,now))['indicators'][0]
    assert fresh['value']==63 and 'history' not in fresh
    cached=Macro.present(cache|{'errors':['AIBI']},now)
    assert cached['indicators'][0]['stale'] and not analysis_context(cached)['indicators']
    assert Macro.present(cache,datetime(2026,12,2,tzinfo=timezone.utc))['indicators'][0]['stale']


def test_cpi_uses_same_month_last_year_and_excludes_future():
    csv='observation_date,CPIAUCSL\n2024-09-01,90\n2024-10-01,100\n2025-09-01,99\n2025-10-01,102\n2026-10-01,999'
    item=indicator('CPIAUCSL',csv,date(2025,11,1))
    assert item['value']==2 and item['change']==-8 and item['date']=='2025-10-01'


def test_risk_requires_two_fresh_sources():
    a={'code':'VIXCLS','percentile':88,'stale':False}
    b={'code':'BAMLH0A0HYM2','percentile':82,'stale':False}
    assert '均偏高' in risk_summary([a,b])
    assert '尚未一致' in risk_summary([a,b|{'percentile':45}])
    assert '不足' in risk_summary([a,b|{'stale':True}])


def test_news_only_recent_original_source():
    now=datetime(2026,11,26,tzinfo=timezone.utc)
    item='<item><title>Policy update</title><link>https://www.federalreserve.gov/release</link><pubDate>Wed, 25 Nov 2026 12:00:00 GMT</pubDate></item>'
    feed='<rss><channel>'+item+item.replace('www.federalreserve.gov','other.example')+item.replace('2026','2025')+'</channel></rss>'
    assert len(headlines('fed',feed,now))==1


def test_failed_refresh_retains_previous_observation(tmp_path,monkeypatch):
    from app.store import Store
    from app import macro
    now=datetime(2026,11,26,tzinfo=timezone.utc)
    monkeypatch.setattr(macro,'now_utc',lambda:now)
    store=Store(tmp_path/'macro.db')
    old='2026-11-25T00:00:00+00:00'
    store.set('macro_public_v1',{'checked':old,'values':{'DGS10':{'data':{'code':'DGS10','date':'2026-11-24','value':4},'fetched':old}},'errors':[]})
    env=Macro(store)
    def fail(code,now): raise httpx.ConnectError('offline')
    monkeypatch.setattr(env,'fetch',fail)
    result=env.read()
    assert result['indicators'][0]['value']==4 and result['indicators'][0]['stale']
    assert len(result['unavailable'])==9 and 'AI 泡沫指数' in result['unavailable']


def test_macro_analysis_uses_selected_profile_and_fresh_evidence(tmp_path, monkeypatch):
    from app.main import create_app
    from app.store import Store

    store = Store(tmp_path/'analysis.db')
    monkeypatch.delenv('OPENAI_API_KEY', raising=False)
    headers = {'X-TrendDesk':'local'}
    url = '/api/macro/analysis?profile=deep'
    environment = {
        'checked':'2026-11-26T10:00:00+00:00', 'sentiment':'风险情绪数据不足',
        'indicators':[{'title':'过期指标','value':98765,'stale':True}],
        'news':[{'title':'缓存标题','cached':True}], 'unavailable':[],
    }
    monkeypatch.setattr(Macro, 'read', lambda self: environment)
    calls = []
    def respond(url, **kwargs):
        payload = kwargs['json']
        calls.append(payload)
        return httpx.Response(200, request=httpx.Request('POST',url), json={
            'status':'completed', 'model':payload['model'], 'reasoning':payload.get('reasoning'),
            'usage':{'total_tokens':17},
            'output':[{'type':'message','content':[{'type':'output_text','text':'观察信用利差变化。'}]}],
        })
    monkeypatch.setattr(httpx,'post',respond)
    with TestClient(create_app(store,run_worker=False)) as client:
        assert 'API Key' in client.post(url,headers=headers).json()['detail']
        monkeypatch.setenv('OPENAI_API_KEY','test-only')
    with TestClient(create_app(store,run_worker=False)) as client:
        assert client.post(url,headers=headers).status_code==409
        assert not calls
        environment['news'].append({'title':'政策更新','cached':False})
        answer=client.post(url,headers=headers).json()
        assert answer['profile']=='deep' and answer['as_of']==environment['checked']
        assert answer['tokens']['total_tokens']==17 and answer['receipt']['returned_effort']=='high'
        content=json.loads(calls[0]['input'])
        assert content['unavailable']==['过期指标'] and not content['indicators']
        assert 'symbol' not in content and [n['title'] for n in content['headlines']]==['政策更新']
        assert '宏观快照' in calls[0]['instructions']
        assert client.post(url,headers=headers).json()['cached'] and len(calls)==1
        quick=client.post('/api/macro/analysis',headers=headers).json()
        assert quick['profile']=='routine' and not quick['cached'] and len(calls)==2
        assert client.get('/api/ai/usage').json()['total_tokens']==34

        news_url='/api/news/analysis?profile=deep'
        assert client.post(news_url,headers=headers,json={'text':'  '}).status_code==422
        assert client.post(news_url,json={'text':'market news'}).status_code==403
        story=client.post(news_url,headers=headers,json={'text':'  Example headline  '}).json()
        assert story['profile']=='deep' and story['receipt']['returned_effort']=='high'
        assert json.loads(calls[-1]['input'])=={'excerpt':'Example headline'}
        assert '单条消息' in calls[-1]['instructions']
        assert client.post(news_url,headers=headers,json={'text':'Example headline'}).json()['cached']
        assert client.get('/api/ai/usage').json()['total_tokens']==51
        assert client.post(url+'&focus=bubble',headers=headers).status_code==409
        environment['indicators'].append({'code':'AIBI','title':'AI 泡沫指数','value':63,'stale':False})
        assert client.post(url+'&focus=bubble',headers=headers).status_code==200
        focused=json.loads(calls[-1]['input'])
        assert [m['code'] for m in focused['indicators']]==['AIBI'] and not focused['headlines']

def test_news_translation_has_its_own_prompt_and_cache(tmp_path,monkeypatch):
    from app.main import create_app
    from app.store import Store
    monkeypatch.setenv('OPENAI_API_KEY','test-only')
    prompts=[]
    def reply(url,**kwargs):
        payload=kwargs['json']
        prompts.append(payload['instructions'])
        return httpx.Response(200,request=httpx.Request('POST',url),json={
            'status':'completed','model':payload['model'],'usage':{'total_tokens':8},
            'output':[{'type':'message','content':[{'type':'output_text','text':'利率维持在 4%。'}]}]})
    monkeypatch.setattr(httpx,'post',reply)
    with TestClient(create_app(Store(tmp_path/'translate.db'),run_worker=False),headers={'X-TrendDesk':'local'}) as client:
        body={'text':'Rates stay at 4%.'}
        for route in ('translate','analysis','translate'):
            response=client.post('/api/news/'+route,json=body)
            assert response.status_code==200 and response.json()['text']
        assert response.json()['cached']
    assert len(prompts)==2 and '只输出译文' in prompts[0] and '只输出译文' not in prompts[1]


def test_headline_research_requires_search_and_clickable_evidence(tmp_path,monkeypatch):
    from app.main import create_app
    from app.store import Store
    monkeypatch.setenv('OPENAI_API_KEY','test-only')
    note={'type':'url_citation','url':'https://www.federalreserve.gov/','title':'Fed','end_index':2}
    part={'type':'output_text','text':'公告内容','annotations':[note]}
    output=[{'type':'message','content':[part]}]
    def reply(url,**kwargs):
        payload=kwargs['json']
        assert payload['tools']==[{'type':'web_search'}] and payload['tool_choice']=='required'
        assert json.loads(payload['input'])['source']=='美联储公告'
        return httpx.Response(200,request=httpx.Request('POST',url),json={
            'status':'completed','model':payload['model'],'output':output})
    monkeypatch.setattr(httpx,'post',reply)
    with TestClient(create_app(Store(tmp_path/'search.db'),run_worker=False),headers={'X-TrendDesk':'local'}) as client:
        def run(): return client.post('/api/news/research',json={'text':'Fed announcement','source':'美联储公告'})
        assert run().status_code==502
        output.insert(0,{'type':'web_search_call','status':'completed'})
        assert run().json()['passages'][0]['citations']==[{'url':note['url'],'title':'Fed','after':2}]
        note['url']='javascript:void(0)'
        assert run().status_code==502
