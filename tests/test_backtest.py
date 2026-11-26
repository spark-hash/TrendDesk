from datetime import timedelta
from pathlib import Path
import pytest
from fastapi.testclient import TestClient
from app.backtest import simulate, summary, aggregate, exit_on_bar, expected_times, validate_coverage, build_signals, Backtests
from app.market import bar_end, parse_time
from app.main import create_app
from app.store import Store
from app.backtest import opening_range_signals

PARAMS={'capital':10000,'symbols':['AAPL'],'fee_bps':0,'slippage_bps':0,'risk_percent':1,'target_r':2,'max_bars':130}

def bars(prices):
    return [dict(time=f'2026-11-25T{9+(30+i*15)//60:02d}:{(30+i*15)%60:02d}:00-05:00',
        open=p,close=p,high=p+.1,low=p-.1,volume=1000) for i,p in enumerate(prices)]

def signal(b,stop=95):
    return {b['time']:{'stop':stop,'signal_time':bar_end(b,'15m').isoformat(),'signal_price':b['close'],'detail':'fixture'}}

def test_next_bar_entry_and_cost_accounting():
    candles=bars([100,105,107])
    params=PARAMS|{'fee_bps':10,'slippage_bps':20}
    r=simulate('AAPL',candles,signal(candles[0]),params,10000)
    t=r['trades'][0]
    assert t['entry_time']==candles[1]['time']
    assert t['entry_price']==pytest.approx(105*1.002)
    assert t['exit_price']==pytest.approx(107*.998)
    assert t['reason']=='end_of_sample'
    assert r['final']==pytest.approx(10000+t['pnl'])
    assert t['pnl']==pytest.approx(t['quantity']*(t['exit_price']-t['entry_price'])-t['entry_fee']-t['exit_fee'])
    assert t['quantity']*(t['entry_price']-95)<=100

def test_ambiguous_bar_and_gap_stop():
    pos={'stop':95,'target':110}
    assert exit_on_bar(pos,{'open':100,'high':115,'low':90},0)==(95,'stop')
    assert exit_on_bar(pos,{'open':85,'high':100,'low':80},.01)==(84.15,'gap_stop')
    assert exit_on_bar(pos,{'open':115,'high':120,'low':90},0)==(110,'target')

def test_orb_requires_fourteen_prior_opens_and_confirmation():
    sessions=expected_times('2026-10-30','2026-11-27','1D')[-15:]
    def candle(day,hour,**changes):
        return dict(time=f'{day}T{hour}:00',open=100,high=102,low=98,close=101,volume=100)|changes
    history=[candle(day,'09:30') for day in sessions[:-1]]
    day=sessions[-1]
    opening=candle(day,'09:30',volume=150)
    wick=candle(day,'09:45',high=105,close=102)
    confirmed=candle(day,'10:00',high=105,close=104)
    second=candle(day,'10:15',high=106,close=105)
    def run(series):
        return opening_range_signals(series,day,day,1.5)
    result=run(history+[opening,wick,confirmed,second])
    assert list(result)==[confirmed['time']] and result[confirmed['time']]['stop']==98
    assert not run(history[1:]+[opening,confirmed])
    assert not run(history+[opening|{'volume':149},confirmed])
    assert not run(history+[opening|{'close':99},confirmed])
    # Friday after Thanksgiving closes at 13:00 ET.
    assert not run(history+[opening,candle(day,'12:45',high=105,close=104)])

def test_loss_paths_respect_stop_order_and_early_gap():
    def trade(rows):
        candles=bars([100]*(len(rows)+1))
        for b,row in zip(candles[1:],rows):
            b.update(row)
        return simulate('AAPL',candles,signal(candles[0],90),PARAMS,10000)['trades'][0]
    ambiguous=trade([{'high':106,'low':89}])
    gave_back=trade([{'high':106},{'low':89}])
    gap=trade([{}, {'open':85,'low':83,'high':110}])
    late=trade([{}, {}, {'low':89}])
    assert [t['half_r_path'] for t in [ambiguous,gave_back,gap,late]]==['unknown','yes','no','no']
    m=summary([ambiguous,gave_back,gap,late],[],10000)
    assert (m['early_stops'],m['givebacks'],m['unknown_paths'])==(3,1,1)
    assert m['expectancy_usd']==pytest.approx(sum(t['pnl'] for t in [ambiguous,gave_back,gap,late])/4)

def test_cash_cap_and_fee_can_turn_price_gain_to_loss():
    candles=bars([100,100,100.1])
    params=PARAMS|{'fee_bps':100,'risk_percent':5}
    r=simulate('AAPL',candles,signal(candles[0],99),params,10000)
    t=r['trades'][0]
    assert t['quantity']*100+t['entry_fee']<=10000
    assert t['pnl']<0
    assert summary(r['trades'],r['curve'],10000)['win_rate']==0

def test_drawdown_includes_open_position_and_idle_allocations():
    candles=bars([100,100,96,101])
    params=PARAMS|{'symbols':['AAPL','MSFT']}
    r=simulate('AAPL',candles,signal(candles[0],90),params,5000)
    result=aggregate([r],params,[p['time'] for p in r['curve']])
    assert result['metrics']['max_drawdown_pct']==pytest.approx(.2)
    assert result['metrics']['return_pct']==pytest.approx(.05)
    assert result['curve'][2]['equity']==9980

def test_no_trades_and_end_of_sample_signal():
    candles=bars([100,101])
    r=simulate('AAPL',candles,signal(candles[-1]),PARAMS,10000)
    assert not r['trades'] and r['skipped']['end_of_sample']==1
    m=summary(r['trades'],r['curve'],10000)
    assert m['win_rate'] is None and m['return_pct']==m['max_drawdown_pct']==0

def test_timeout_and_non_overlapping_positions():
    candles=bars([100,100,100,100])
    signals=signal(candles[0])|signal(candles[1])
    r=simulate('AAPL',candles,signals,PARAMS|{'max_bars':2},10000)
    assert len(r['trades'])==1 and r['skipped']['busy']==1
    assert r['trades'][0]['reason']=='time_limit'
    assert r['trades'][0]['bars']==2

def test_coverage_early_close_and_missing_data():
    assert len(expected_times('2026-11-26','2026-11-27'))==14
    frames={tf:[{'time':s+'T00:00:00-05:00' if tf=='1D' else s} for s in expected_times('2026-11-25','2026-11-25',tf)] for tf in ('1D','60m','15m')}
    assert validate_coverage(frames,'2026-11-25','2026-11-25')['15m']['actual']==26
    frames['15m'].pop(2)
    with pytest.raises(ValueError,match='15m'):validate_coverage(frames,'2026-11-25','2026-11-25')

def test_multi_timeframe_prefixes_never_see_future(monkeypatch):
    import app.backtest as bt
    frames={tf:[dict(time=s+'T00:00:00-05:00' if tf=='1D' else s,open=100,close=100,low=99,high=101,volume=1000) for s in expected_times('2026-11-23','2026-11-25',tf)] for tf in ('1D','60m','15m')}
    checked=[]
    def rule(snapshot,now,settings):
        close=now-timedelta(seconds=3)
        assert all(bar_end(b,tf)<=close for tf,series in snapshot.items() for b in series)
        if snapshot['1D'] and close<parse_time('2026-11-25T16:00:00-05:00'):
            assert snapshot['1D'][-1]['time'][:10]<'2026-11-25'
        checked.append(close)
        active=close.minute==0
        return {'ready':True,'fresh':True,'stop':95,'signals':[{'kind':'breakout','detail':'test'}] if active else []}
    monkeypatch.setattr(bt,'analyze_closed',rule)
    full,count=build_signals(frames,'2026-11-23','2026-11-25',{})
    prefix={tf:[b for b in series if b['time'][:10]<'2026-11-25'] for tf,series in frames.items()}
    earlier,_=build_signals(prefix,'2026-11-23','2026-11-24',{})
    assert earlier['breakout']=={t:s for t,s in full['breakout'].items() if t[:10]<'2026-11-25'}
    assert checked and count==78
    with pytest.raises(InterruptedError):build_signals(frames,'2026-11-23','2026-11-25',{},lambda:True)

def test_backtest_api_validation_persistence_and_export(tmp_path,monkeypatch):
    store=Store(tmp_path/'test.db')
    app=create_app(store,run_worker=False)
    manager=app.state.backtests
    monkeypatch.setattr(manager,'start',lambda p:{'id':'test','params':p,'status':'queued'})
    with TestClient(app) as client:
        defaults=client.get('/api/backtests').json()['defaults']
        assert client.post('/api/backtests',json=defaults).status_code==403
        headers={'X-TrendDesk':'local'}
        assert client.post('/api/backtests',json=defaults|{'start':'2020-01-01'},headers=headers).status_code==422
        assert client.post('/api/backtests',json=defaults|{'symbols':['HK.00700']},headers=headers).status_code==422
        assert client.post('/api/backtests',json=defaults|{'symbols':[]},headers=headers).status_code==422
        response=client.post('/api/backtests',json=defaults|{'symbols':['aapl','US.AAPL']},headers=headers)
        assert response.status_code==202 and response.json()['params']['symbols']==['AAPL']
        store.save_backtest({'id':'saved','status':'complete','results':{},'params':defaults,'coverage':{}})
        assert client.get('/api/backtests/saved').json()['status']=='complete'
        assert 'text/csv' in client.get('/api/backtests/saved/export').headers['content-type']
        assert client.get('/api/backtests/absent').status_code==404
    store.save_backtest({'id':'interrupted','status':'running'})
    Backtests(store,tmp_path/'cache')
    assert store.backtest('interrupted')['status']=='interrupted'
