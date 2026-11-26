from datetime import datetime,timedelta
from types import SimpleNamespace

import pytest

from app.intraday_structure import replay
from app.market import ET
from app.market_studies import minute_series
from app.store import Store
from app.study_journal import StudyJournal


def sample(side=1):
    start=datetime(2026,11,25,9,30,tzinfo=ET)
    rows=[]
    for i in range(43):
        price=100 if i<20 or i>=32 else 100+side*(1.5+i/100)
        high=101 if i<20 and i%5==0 else price+.4
        low=99 if i<20 and i%5==2 else price-.4
        rows.append(dict(time=(start+timedelta(minutes=i)).isoformat(),open=price,close=price,
                         high=high,low=low,volume=1000))
    return rows


@pytest.mark.parametrize('side',[1,-1])
def test_frozen_platform_causal_stages_and_rates(tmp_path,side):
    rows=sample(side)
    result=replay(minute_series(rows))
    events=result['events']
    assert [e['stage'] for e in events]==['formed','first','confirmed','returned']
    assert [e['at'][11:16] for e in events]==['09:50','09:51','10:00','10:03']
    assert all(e['top']==101 and e['bottom']==99 for e in events)
    assert events[1]==replay(minute_series(rows[:21]))['events'][-1]
    assert not replay(minute_series(rows[:19]))['events']
    assert not any(e['stage']=='confirmed' for e in replay(minute_series(rows[:25]+rows[26:]))['events'])
    returned_early=rows[:23]+[dict(rows[23],close=100)]
    assert [e['stage'] for e in replay(minute_series(returned_early))['events']][-2:]==['first','returned']
    engine=SimpleNamespace(store=Store(tmp_path/'test.db'),connected=False)
    now=datetime(2026,11,25,16,0,tzinfo=ET)
    StudyJournal(engine,None).scan('AAPL','1m',rows[:24],now)
    journal=StudyJournal(engine,None)
    journal.scan('AAPL','1m',rows,now)
    journal.scan('AAPL','1m',rows,now)
    stats={g['kind']:g for g in journal.report('AAPL','1m',5,'')['platform_comparison']}
    assert stats['minute_first']['mature']==stats['minute_confirmed']['mature']==1
    assert stats['minute_first']['returned']==0 and stats['minute_confirmed']['returned']==1
    assert stats['minute_confirmed']['wait_move']>0
    assert journal.report('AAPL','1m',20,'minute_confirmed')['platform_comparison'][0]['mature']==0


def test_channel_warmup_and_gap_reset():
    rows=sample()
    for i,row in enumerate(rows):
        price=100+i*.1
        row.update(open=price,high=price+.05,low=price-.05,close=price)
    assert replay(rows[:29])['lines']==[]
    assert len(replay(rows[:30])['lines'])==2
    assert replay(rows[:30]+rows[31:])['lines']==[]
