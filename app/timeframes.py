"""Build research candles from complete regular-session source bars."""
from datetime import timedelta
from itertools import groupby

from .market import ET, MINUTES, TIME_LABELS, bounds, calendar, completed, parse_time

SOURCES = {'1W':'1D', '4h':'60m', '30m':'15m'}


def combine(rows, stamp):
    return {'time':stamp, 'open':rows[0]['open'], 'close':rows[-1]['close'],
            'high':max(b['high'] for b in rows), 'low':min(b['low'] for b in rows),
            'volume':sum(b['volume'] for b in rows)}


def weekly(daily):
    def monday(bar):
        day = parse_time(bar['time']).date()
        return day - timedelta(days=day.weekday())

    result = []
    for start, group in groupby(daily, monday):
        rows = list(group)
        sessions = calendar().sessions_in_range(start,start+timedelta(days=4))
        if [b['time'][:10] for b in rows] == [s.date().isoformat() for s in sessions]:
            result.append(combine(rows, rows[-1]['time']))
    return result


def session_candles(bars, tf):
    step = timedelta(minutes=MINUTES[tf])
    child_step = timedelta(minutes=MINUTES[SOURCES[tf]])

    def bucket(bar):
        stamp = parse_time(bar['time'])
        opening = bounds(stamp.astimezone(ET).date().isoformat())[0]
        return opening + ((stamp-opening)//step)*step

    result = []
    for start, group in groupby(bars, bucket):
        rows = list(group)
        end = min(start+step, bounds(start.astimezone(ET).date().isoformat())[1])
        expected = start
        for row in rows:
            if parse_time(row['time']) != expected: break
            expected += child_step
        else:
            if expected >= end:
                result.append(combine(rows, start.astimezone(ET).isoformat()))
    return result


def derive(tf, bars):
    if tf=='1W': return weekly(bars)
    if tf in SOURCES: return session_candles(bars,tf)
    return bars


def closed_frames(read, now):
    base = {tf:completed(read(tf),tf,now) for tf in TIME_LABELS if tf not in SOURCES}
    return {tf:derive(tf,base[SOURCES.get(tf,tf)]) for tf in TIME_LABELS}
