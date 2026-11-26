"""Public US macro releases and market risk indicators, with per-source last-good data."""
import csv
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from io import StringIO
import math
import re
from threading import Lock
from urllib.parse import urlsplit
import xml.etree.ElementTree as XML

import httpx
from .market import ET, calendar, expected_last_close, now_utc
from .bubble import BANDS, breakdown


SERIES = {
    'DGS10': ('10 年期美债收益率', '%', 7),
    'T10Y2Y': ('10 年减 2 年美债利差', '个百分点', 7),
    'CPIAUCSL': ('美国 CPI 同比（季调）', '%', 75),
    'UNRATE': ('美国失业率', '%', 75),
    'VIXCLS': ('VIX 波动率指数', '点', 7),
    'BAMLH0A0HYM2': ('美国高收益债期权调整利差', '个百分点', 7),
}
FEEDS = {
    'fed': ('美联储公告', 'https://www.federalreserve.gov/feeds/press_all.xml', 'federalreserve.gov'),
    'markets': ('MarketWatch 要闻', 'https://feeds.content.dowjones.io/public/rss/mw_topstories', 'marketwatch.com'),
}
RISK = ('VIXCLS', 'BAMLH0A0HYM2')
BUBBLE = 'AIBI'
BUBBLE_TITLE = 'AI 泡沫指数'
BUBBLE_FEED = 'https://aibubblemonitor.com/api/v2/feed'
BUBBLE_BANDS = BANDS


def bubble_index(content, now):
    points = {}
    today = now.astimezone(ET).date()
    for item in XML.fromstring(content).findall('./channel/item'):
        link = (item.findtext('link') or '').strip()
        dated = re.fullmatch(r'https://aibubblemonitor\.com/v2/day/(\d{4}-\d{2}-\d{2})',link)
        title = re.search(r'AI Bubble Index 2\.0 at (\d+(?:\.\d+)?) \(([A-Za-z ]+)\) on ',item.findtext('title') or '')
        if not dated or not title: continue
        day = date.fromisoformat(dated[1])
        score = float(title[1])
        published = parsedate_to_datetime(item.findtext('pubDate') or '')
        if day>today or not published.tzinfo or published>now or not 0<=score<=100: continue
        components = {}
        description = item.findtext('description') or ''
        for field,name in [('Euphoria','市场热度'),('Fragility','脆弱性'),('Demand gauge','需求缺口')]:
            match = re.search(r'\b'+field+r' (\d+(?:\.\d+)?)',description)
            if match and 0<=float(match[1])<=100: components[name]=float(match[1])
        points[dated[1]] = dict(date=dated[1],value=score,source=link,
                                band=BUBBLE_BANDS.get(title[2],title[2]),components=components)
    if not points: raise ValueError('尚无可验证的 AI 泡沫指数读数')
    ordered = [points[key] for key in sorted(points)]
    latest = ordered[-1]
    previous = ordered[-2] if len(ordered)>1 else None
    return dict(latest,code=BUBBLE,title=BUBBLE_TITLE,unit='分',provider='AI Bubble Monitor 2.0',
                previous_date=previous['date'] if previous else None,
                change=round(latest['value']-previous['value'],2) if previous else None,
                history=[{'date':p['date'],'value':p['value']} for p in ordered[-30:]])


def indicator(code, content, today):
    points = {}
    for row in csv.DictReader(StringIO(content)):
        raw = row[code]
        if raw in ('', '.'):
            continue
        day = date.fromisoformat(row['observation_date'])
        value = float(raw)
        if day <= today and math.isfinite(value):
            points[day] = value
    last_observation = max(points, default=None)
    if code == 'CPIAUCSL':
        points = {d:(v/points[d.replace(year=d.year-1)]-1)*100 for d,v in points.items()
                  if d.replace(year=d.year-1) in points and points[d.replace(year=d.year-1)]>0}
    ordered = sorted(points.items())
    if len(ordered)<2:
        raise ValueError('可用历史不足')
    previous_date, previous = ordered[-2]
    day,value = ordered[-1]
    title,unit,_ = SERIES[code]
    result = dict(code=code,title=title,unit=unit,date=day.isoformat(),value=round(value,3),
                  previous_date=previous_date.isoformat(),change=round(value-previous,3),
                  source='https://fred.stlouisfed.org/series/'+code)
    if code=='CPIAUCSL' and last_observation>day:
        result['note']=f"{last_observation:%Y-%m} 缺去年同月指数，显示最近可计算的同比。"
    if code in RISK and len(ordered)>=253:
        baseline = [x for _,x in ordered[-253:-1]]
        result['percentile'] = round(100*(sum(x<value for x in baseline)+.5*baseline.count(value))/252,1)
    return result


def headlines(code, content, now):
    title,_,domain = FEEDS[code]
    root = XML.fromstring(content)
    channel = root.find('channel')
    if channel is None:
        raise ValueError('新闻源格式异常')
    entries={}
    for item in channel.findall('item'):
        url = (item.findtext('link') or '').strip()
        headline = ' '.join((item.findtext('title') or '').split())
        parsed = urlsplit(url)
        host = parsed.hostname or ''
        if not headline or parsed.scheme!='https' or not (host==domain or host.endswith('.'+domain)):
            continue
        try:
            published = parsedate_to_datetime(item.findtext('pubDate') or '')
            if published.tzinfo is None or not now-timedelta(days=30)<=published<=now:
                continue
        except (ValueError, TypeError, OverflowError):
            continue
        entries[url]=dict(title=headline[:320], url=url, source=title,
                          published=published.astimezone(timezone.utc).isoformat())
    return sorted(entries.values(),key=lambda x:x['published'],reverse=True)[:6]


def risk_summary(metrics):
    ranks = [m['percentile'] for m in metrics if m['code'] in RISK and 'percentile' in m and not m['stale']]
    if len(ranks)!=2:
        return '风险情绪数据不足'
    if min(ranks)>=80:
        return '股票波动预期和信用风险溢价均偏高'
    if max(ranks)<=20:
        return '股票波动预期和信用风险溢价均偏低'
    if max(ranks)>=80 and min(ranks)<80:
        return '两个市场的压力信号尚未一致'
    return '两项指标均未进入过去一年的高压力区'


def analysis_context(environment):
    indicators = environment['indicators']
    unavailable = list(environment['unavailable'])
    for item in indicators:
        if item['stale'] and item['title'] not in unavailable:
            unavailable.append(item['title'])
    return {
        'as_of': environment['checked'],
        'sentiment': environment['sentiment'],
        'indicators': [{k:v for k,v in item.items() if k!='history'} for item in indicators if not item['stale']],
        'headlines': [item for item in environment['news'] if not item['cached']][:8],
        'unavailable': unavailable,
    }


class Macro:
    def __init__(self, store):
        self.store=store
        self.lock=Lock()

    def fetch(self, code, now):
        url = BUBBLE_FEED if code==BUBBLE else ('https://fred.stlouisfed.org/graph/fredgraph.csv?id='+code if code in SERIES else FEEDS[code][1])
        response=httpx.get(url,timeout=7,follow_redirects=True)
        response.raise_for_status()
        if code==BUBBLE:
            reading=bubble_index(response.content,now)
            try:
                daily=httpx.get('https://aibubblemonitor.com/api/v2/day/'+reading['date'],timeout=5)
                daily.raise_for_status()
                reading['detail']=breakdown(daily.json(),reading)
            except (httpx.HTTPError,ValueError,KeyError,TypeError,AttributeError):
                reading['detail_unavailable']=True
            return reading
        if code in SERIES:
            return indicator(code,response.text.lstrip('\ufeff'),now.astimezone(ET).date())
        return headlines(code,response.content,now)

    def read(self, refresh=False):
        with self.lock:
            now=now_utc()
            cache=self.store.get('macro_public_v1',{})
            age=(now-datetime.fromisoformat(cache['checked'])).total_seconds() if cache else float('inf')
            if age >= (30 if refresh else 900) or (BUBBLE not in cache.get('values',{}) and BUBBLE not in cache.get('errors',[])):
                values=cache.get('values',{}).copy()
                errors=[]
                with ThreadPoolExecutor(max_workers=9) as pool:
                    pending={k:pool.submit(self.fetch,k,now) for k in (*SERIES,*FEEDS,BUBBLE)}
                    for code,task in pending.items():
                        try:
                            data=task.result()
                            if code==BUBBLE and data['date']<values.get(code,{}).get('data',{}).get('date',''):
                                raise ValueError('上游返回了较旧的指数')
                            if code==BUBBLE and data.get('detail_unavailable'):
                                previous=values.get(code,{}).get('data',{})
                                if previous.get('date')==data['date'] and previous.get('value')==data['value'] and previous.get('detail'):
                                    data['detail']=previous['detail']
                            values[code]={'data':data,'fetched':now.isoformat()}
                        except (httpx.HTTPError,ValueError,KeyError,TypeError,XML.ParseError,OverflowError):
                            errors.append(code)
                cache={'checked':now.isoformat(),'values':values,'errors':errors}
                self.store.set('macro_public_v1',cache)
            return self.present(cache,now)

    @staticmethod
    def present(cache,now):
        today=now.astimezone(ET).date()
        values=cache.get('values',{})
        errors=cache.get('errors',[])
        metrics=[]
        news=[]
        for code,(_,_,max_age) in SERIES.items():
            if code in values:
                item=values[code]['data']
                stale=code in errors or (today-date.fromisoformat(item['date'])).days>max_age
                metrics.append(dict(item,stale=stale))
        for code in FEEDS:
            for item in values.get(code,{}).get('data',[]):
                if datetime.fromisoformat(item['published'])>=now-timedelta(days=30):
                    news.append(dict(item,cached=code in errors))
        names={k:v[0] for k,v in {**SERIES,**FEEDS}.items()}
        names[BUBBLE]=BUBBLE_TITLE
        if BUBBLE in values:
            item=values[BUBBLE]['data']
            last=expected_last_close('1D',now).astimezone(ET).date()
            cutoff=calendar().previous_session(last).date().isoformat()
            metrics.append(dict(item,stale=BUBBLE in errors or item['date']<cutoff))
        return dict(checked=cache.get('checked'), indicators=metrics,
                    sentiment=risk_summary(metrics), news=sorted(news,key=lambda x:x['published'],reverse=True),
                    unavailable=[names[k] for k in errors])
