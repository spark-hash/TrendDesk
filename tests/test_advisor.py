from types import SimpleNamespace
import threading
import httpx
import pytest
from fastapi import HTTPException
from app import advisor


def test_response_cache_errors_and_secrets(monkeypatch):
    monkeypatch.delenv('OPENAI_API_KEY', raising=False)
    api = advisor.Advisor()
    market = dict(symbol='AMD', session='收盘复盘', bar_close_time='2026-11-25T16:00:00-05:00', quote=None)
    with pytest.raises(HTTPException, match='配置|填写'):
        api.advise(market)
    status = api.configure(advisor.AIConfig(model='test-model',key='test-only'))
    assert status['configured'] and status['model']=='test-model' and 'test-only' not in str(status)
    calls = []
    def respond(url, json, headers, timeout):
        calls.append(json)
        assert headers['Authorization']=='Bearer test-only' and 'test-only' not in str(json)
        return httpx.Response(200,request=httpx.Request('POST',url),headers={'x-request-id':f'req-{len(calls)}','x-ratelimit-remaining-tokens':'990'},
                              json={'model':json['model']+'-snapshot','reasoning':json.get('reasoning'),
                                    'usage':{'total_tokens':10,'input_tokens':6,'output_tokens':4,
                                             'output_tokens_details':{'reasoning_tokens':2}},
                                    'status':'completed','output':[
            {'type':'message','content':[{'type':'output_text','text':'观察量能'}]}]})
    monkeypatch.setattr(httpx,'post',respond)
    quick=api.advise(market)
    assert quick['text']=='观察量能' and not quick['cached']
    assert quick['receipt']==dict(requested_model='test-model',requested_effort=None,
                                  returned_model='test-model-snapshot',returned_effort=None,request_id='req-1')
    assert api.advise(market)['model']=='test-model' and len(calls)==1
    assert 'reasoning' not in calls[0]
    deep=api.advise(market,'deep')
    assert deep['profile']=='deep' and deep['receipt']['returned_effort']=='high'
    assert deep['receipt']['request_id']=='req-2'
    assert calls[1]['model']=='gpt-5.4' and calls[1]['reasoning']=={'effort':'high'}
    assert api.advise(market)['profile']=='routine' and len(calls)==2
    assert api.advise(market)['cached'] and api.advise(market)['receipt']==quick['receipt']
    assert api.usage['total_tokens']==20 and api.usage['reasoning_tokens']==4
    assert api.usage['latest']['remaining_tokens']=='990'
    monkeypatch.setattr(httpx,'get',lambda url,**kw:httpx.Response(200,request=httpx.Request('GET',url),
                        json={'data':[{'id':'z-custom'},{'id':'a-audio'},{'id':'a-audio'}]}))
    assert api.models()=={'models':['a-audio','z-custom']}
    with pytest.raises(ValueError):
        advisor.AIConfig(model='gpt-4.1-mini',effort='high')
    api.configure(advisor.AIConfig(model='other'))
    monkeypatch.setattr(httpx,'post',lambda url,**kw:httpx.Response(401,request=httpx.Request('POST',url)))
    with pytest.raises(HTTPException,match='密钥未通过验证'):
        api.advise(market)


def test_snapshot_blocks_stale_quotes_and_omits_private_fields(monkeypatch):
    from datetime import datetime, timezone
    now=datetime(2026,11,25,16,tzinfo=timezone.utc)
    quote=dict(price=100,time=now.isoformat(),name='ignored')
    engine=SimpleNamespace(lock=threading.Lock(),symbols=lambda:['AMD'],get_bars=lambda s:{},
                           store=SimpleNamespace(settings=lambda:{}),connected=True,
                           loaded={'AMD':'2026-11-25'},quotes={'AMD':quote},quote_fresh=lambda *args:False)
    a=dict(ready=True,fresh=True,bar_close_time=now.isoformat(),close=100,conditions=[],signals=[],
           support=95,resistance=105,stop=95,target_2r=110,position={'cost':99})
    monkeypatch.setattr(advisor,'now_utc',lambda:now)
    monkeypatch.setattr(advisor,'analyze',lambda *args,**kw:a)
    with pytest.raises(HTTPException,match='实时报价'):
        advisor.snapshot(engine,'AMD')
    engine.quote_fresh=lambda *args:True
    result=advisor.snapshot(engine,'AMD')
    assert result['quote']==dict(price=100,time=now.isoformat()) and 'position' not in result
    monkeypatch.setattr(advisor,'market_status',lambda t:dict(open=False,close_confirmation=False))
    result=advisor.snapshot(engine,'AMD')
    assert result['session']=='收盘复盘' and result['quote'] is None
