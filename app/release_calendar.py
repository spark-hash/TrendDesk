"""Upcoming national releases from the BLS and BEA public calendars."""
import re
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from threading import Lock

import httpx
from .market import ET, now_utc

FEEDS = {
    'BLS': 'https://www.bls.gov/schedule/news_release/bls.ics',
    'BEA': 'https://www.bea.gov/news/schedule/ics/online-calendar-subscription.ics',
}
PAGES = {'BLS':'https://www.bls.gov/schedule/', 'BEA':'https://www.bea.gov/news/schedule'}
TITLES = [('consumer price index','消费者价格指数 CPI'), ('employment situation','就业报告与失业率'),
          ('producer price index','生产者价格指数 PPI'), ('job openings','职位空缺 JOLTS'),
          ('personal income and outlays','个人收入与支出（含 PCE 物价）'),
          ('gross domestic product','国内生产总值 GDP'), ('gdp (','国内生产总值 GDP'),
          ('u.s. international trade in goods','美国国际贸易')]
# Published schedule checked on Nov 26, used only until the first successful feed refresh.
SEED = {'BLS':[('2026-12-01T10:00','Job Openings and Labor Turnover Survey for October 2026'),
               ('2026-12-04T08:30','Employment Situation for November 2026'),
               ('2026-12-10T08:30','Consumer Price Index for November 2026'),
               ('2026-12-15T08:30','Producer Price Index for November 2026')],
        'BEA':[('2026-12-08T08:30','U.S. International Trade in Goods and Services, October 2026'),
               ('2026-12-23T08:30','GDP (Third Estimate), 3rd Quarter 2026'),
               ('2026-12-23T08:30','Personal Income and Outlays, November 2026')]}


def importance(title):
    if title.startswith(('消费者价格指数','就业报告','个人收入与支出','国内生产总值')):
        return '高'
    if title.startswith(('生产者价格指数','职位空缺')):
        return '中'
    return '一般'


def event(source, at, title):
    label = next((zh for prefix,zh in TITLES if title.lower().startswith(prefix)), None)
    if label:
        return dict(source=source, at=at.astimezone(ET).isoformat(), title=label, detail=title, url=PAGES[source])


def parse_feed(source, text):
    if 'BEGIN:VCALENDAR' not in text:
        raise ValueError('Missing calendar')
    rows = {}
    for block in re.findall(r'BEGIN:VEVENT(.*?)END:VEVENT',re.sub(r'\r?\n[ \t]', '', text), re.S):
        fields = {}
        for line in block.splitlines():
            key, sep, value = line.partition(':')
            if sep:
                fields[key.split(';')[0]] = value.strip()
        if fields.get('STATUS') == 'CANCELLED':
            continue
        raw = fields.get('DTSTART','')
        if not re.fullmatch(r'\d{8}T\d{6}Z?',raw):
            continue
        at = datetime.strptime(raw.rstrip('Z'),'%Y%m%dT%H%M%S').replace(tzinfo=timezone.utc if raw.endswith('Z') else ET)
        title = fields.get('SUMMARY','').replace(r'\,',',')
        item = event(source,at,title)
        if item:
            rows[(item['at'],title)] = item
    if not rows:
        raise ValueError('No recognized releases')
    return list(rows.values())


class ReleaseCalendar:
    def __init__(self, store):
        self.store = store
        self.lock = Lock()

    def fetch(self, source):
        response = httpx.get(FEEDS[source],timeout=8,follow_redirects=True)
        response.raise_for_status()
        return parse_feed(source,response.text)

    def read(self, refresh=False):
        with self.lock:
            now = now_utc()
            cache = self.store.get('release_calendar_v1',{})
            if not cache or (now-datetime.fromisoformat(cache['checked'])).total_seconds() >= (30 if refresh else 3600):
                data = cache.get('sources',{}).copy()
                errors = []
                with ThreadPoolExecutor(max_workers=2) as pool:
                    tasks = {s:pool.submit(self.fetch,s) for s in FEEDS}
                    for source,task in tasks.items():
                        try:
                            data[source] = dict(events=task.result(), updated=now.isoformat())
                        except (ValueError,httpx.HTTPError):
                            errors.append(source)
                            if source not in data:
                                rows = [event(source,datetime.fromisoformat(at).replace(tzinfo=ET),title) for at,title in SEED[source]]
                                data[source] = dict(events=rows,updated='2026-11-26')
                cache = dict(checked=now.isoformat(),sources=data,errors=errors)
                self.store.set('release_calendar_v1',cache)
            today = now.astimezone(ET).date()
            end = today + timedelta(days=45)
            events = [dict(e,cached=s in cache['errors'],updated=v['updated'],importance=importance(e['title'])) for s,v in cache['sources'].items()
                      for e in v['events'] if today.isoformat() <= e['at'][:10] <= end.isoformat()]
            return dict(events=sorted(events,key=lambda e:e['at']),checked=cache['checked'],errors=cache['errors'])
