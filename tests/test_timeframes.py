from datetime import datetime, timedelta

import pytest

from app.market import ET, bounds, completed, expected_last_close
from app.provider import normalize_bars
from app.study_journal import next_bar
from app.timeframes import session_candles


def source(day, minutes):
    stamp, close = bounds(day)
    bars = []
    while stamp < close:
        price = 10+len(bars)
        bars.append(dict(time=stamp.astimezone(ET).isoformat(),open=price,high=price+2,
                         low=price-1,close=price+1,volume=100))
        stamp += timedelta(minutes=minutes)
    return bars


@pytest.mark.parametrize('day,tf,step,counts', [
    ('2026-11-25','4h',60,[4,3]), ('2026-11-27','4h',60,[4]),
    ('2026-11-25','30m',15,[2]*13), ('2026-11-27','30m',15,[2]*7),
])
def test_regular_session_aggregation(day,tf,step,counts):
    rows = source(day,step)
    candles = session_candles(rows,tf)
    assert [b['volume'] for b in candles] == [100*n for n in counts]
    assert candles[0]['open']==10 and candles[-1]['close']==rows[-1]['close']
    assert candles[-1]['high']==rows[-1]['high'] and candles[0]['low']==9
    assert len(session_candles(rows[1:],tf)) == len(counts)-1
    assert len(session_candles(rows[:-1],tf)) == len(counts)-1
    before_close = bounds(day)[1]-timedelta(seconds=1)
    assert len(session_candles(completed(rows,str(step)+'m',before_close),tf))==len(counts)-1


def test_month_history_and_next_completed_period():
    row = dict(time_key='2026-10-01 00:00:00',open=12,high=14,low=11,close=13,volume=50)
    october = normalize_bars([row],'1M')[0]
    assert october['time']=='2026-10-30T00:00:00-04:00'
    assert next_bar(october['time'],'1M').isoformat()=='2026-11-30T00:00:00-05:00'
    november = normalize_bars([row|{'time_key':'2026-11-02 00:00:00'}],'1M')[0]
    early = datetime(2026,11,30,16,0,2,tzinfo=ET)
    assert completed([october,november],'1M',early)==[october]
    assert expected_last_close('1M',early).date().isoformat()=='2026-10-30'
    assert expected_last_close('1M',early+timedelta(seconds=1)).date().isoformat()=='2026-11-30'
    five = normalize_bars([row|{'time_key':'2026-11-27 13:00:00'}],'5m')[0]
    assert five['time']=='2026-11-27T12:55:00-05:00'
    assert next_bar(five['time'],'5m').isoformat()=='2026-11-30T09:30:00-05:00'
    assert next_bar('2026-11-25T09:30:00-05:00','4h').hour==13
