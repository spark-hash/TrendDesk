"""NYSE session clock. All bar timestamps are interpreted in America/New_York."""
from datetime import datetime, timedelta, timezone
from functools import lru_cache
from zoneinfo import ZoneInfo
from calendar import monthrange
import exchange_calendars as xcals
import pandas as pd

ET = ZoneInfo('America/New_York')
UTC = timezone.utc
MINUTES = {'1m':1, '5m':5, '15m':15, '30m':30, '60m':60, '4h':240}
TIME_LABELS = {'1M':'月线','1W':'周线','1D':'日线','4h':'4 小时','60m':'1 小时',
               '30m':'30 分钟','15m':'15 分钟','5m':'5 分钟'}

@lru_cache(maxsize=512)
def month_end(year, month):
    last = pd.Timestamp(year=year, month=month, day=monthrange(year,month)[1])
    return calendar().date_to_session(last, direction='previous').date()

@lru_cache(maxsize=1)
def calendar():
    return xcals.get_calendar('XNYS', start='2000-01-01', end='2040-12-31')

def now_utc():
    return datetime.now(UTC)

def parse_time(value):
    dt = datetime.fromisoformat(str(value))
    return dt.replace(tzinfo=ET) if dt.tzinfo is None else dt

@lru_cache(maxsize=4096)
def bounds(day):
    cal = calendar()
    label = pd.Timestamp(day)
    if not cal.is_session(label):
        return None
    return cal.session_open(label).to_pydatetime(), cal.session_close(label).to_pydatetime()

def market_status(now=None):
    now = now or now_utc()
    local = now.astimezone(ET)
    session = bounds(local.date().isoformat())
    active = bool(session and session[0] <= now < session[1])
    confirming = bool(session and session[1] <= now <= session[1]+timedelta(seconds=120))
    cal = calendar()
    day = pd.Timestamp(local.date())
    if session and now < session[0]:
        next_open = session[0]
    else:
        label = cal.date_to_session(day + pd.Timedelta(days=1), direction='next')
        next_open = cal.session_open(label).to_pydatetime()
    return {'open': active, 'close_confirmation':confirming, 'label': '常规交易时段' if active else '收盘确认窗口' if confirming else ('休市' if not session else '盘前 / 盘后'),
            'et': local.isoformat(), 'next_open': next_open.isoformat(),
            'close': session[1].isoformat() if session else None}

def bar_end(bar, timeframe):
    start = parse_time(bar['time'])
    session = bounds(start.astimezone(ET).date().isoformat())
    if not session:
        return None
    if timeframe in ('1D','1W','1M'):
        return session[1]
    if not session[0] <= start < session[1]:
        return None
    return min(start + timedelta(minutes=MINUTES[timeframe]), session[1])

def completed(bars, timeframe, now=None):
    now = now or now_utc()
    return [b for b in bars if (end := bar_end(b, timeframe)) and end + timedelta(seconds=3) <= now]

def expected_last_close(timeframe, now=None):
    now = now or now_utc()
    local = now.astimezone(ET)
    cal = calendar()
    day = pd.Timestamp(local.date())
    session = bounds(local.date().isoformat())
    if timeframe in ('1M','1W'):
        last_day = expected_last_close('1D', now).astimezone(ET).date()
        if timeframe=='1M':
            end = month_end(last_day.year,last_day.month)
            if end>last_day:
                previous = last_day.replace(day=1)-timedelta(days=1)
                end = month_end(previous.year,previous.month)
        else:
            friday = last_day+timedelta(days=4-last_day.weekday())
            end = cal.date_to_session(friday,direction='previous').date()
            if end>last_day: end=cal.date_to_session(friday-timedelta(days=7), direction='previous').date()
        return bounds(end.isoformat())[1]
    if timeframe == '1D' or not session or now < session[0]:
        label = cal.date_to_session(day, direction='previous')
        if cal.session_close(label).to_pydatetime() + timedelta(seconds=3) > now:
            label = cal.previous_session(label)
        return cal.session_close(label).to_pydatetime()
    minutes = MINUTES[timeframe]
    count = int((min(now - timedelta(seconds=3), session[1]) - session[0]).total_seconds() // (minutes * 60))
    if now >= session[1] + timedelta(seconds=3):
        return session[1]
    if count < 1:
        label = cal.previous_session(day)
        return cal.session_close(label).to_pydatetime()
    return session[0] + timedelta(minutes=count * minutes)

def is_current(bars, timeframe, now=None):
    if not bars:
        return False
    end = bar_end(bars[-1], timeframe)
    return end is not None and end >= expected_last_close(timeframe, now)
