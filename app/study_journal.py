"""Record transitions from closed-bar prefixes and score completed forward windows."""
import json
import logging
import threading
from datetime import timedelta
from functools import lru_cache
from .market import ET, MINUTES, bar_end, bounds, calendar, expected_last_close, now_utc, parse_time, month_end
from .market_studies import long_term, minute_series, divergence
from .timeframes import closed_frames
from .technicals import geometry
from .intraday_structure import replay, STAGES
from .notifications import notify

HORIZONS=(1,5,20)
KINDS={'channel':'通道','platform':'平台','top2':'双顶','bottom2':'双底','top3':'头肩顶','bottom3':'头肩底',
       'harami':'孕线','engulf':'吞没','inside':'内包线','doji':'十字星',
       'macd_div':'MACD 背离','rsi_div':'RSI 背离','timing':'长线时机',
       **{'minute_'+k:'分时'+v for k,v in STAGES.items()}}
ACTIVE={'上升通道','下降通道','向上突破','向下跌破','收盘越过颈线','阳线','阴线','出现',
        '顶背离','底背离','趋势内突破','趋势内回踩转强'}
log=logging.getLogger(__name__)


@lru_cache(maxsize=32000)
def next_bar(stamp,tf):
    local=parse_time(stamp).astimezone(ET)
    day=local.date().isoformat()
    cal=calendar()
    if tf=='1M':
        following=local.date().replace(day=28)+timedelta(days=4)
        end=month_end(following.year,following.month)
        return local.replace(year=end.year,month=end.month,day=end.day)
    if tf=='1W':
        monday=local.date()+timedelta(days=7-local.weekday())
        end=cal.sessions_in_range(monday,monday+timedelta(days=4))[-1].date()
        return local.replace(year=end.year,month=end.month,day=end.day)
    if tf=='1D':
        date=cal.next_session(day).date()
        return local.replace(year=date.year,month=date.month,day=date.day)
    step=MINUTES[tf]
    following=local+timedelta(minutes=step)
    if following<bounds(day)[1]: return following
    return bounds(cal.next_session(day).date().isoformat())[0].astimezone(ET)


def observations_at(rows,i,tf):
    if tf=='1m':
        start=i
        while start>0 and rows[start-1]['time'][:10]==rows[i]['time'][:10]: start-=1
        day=rows[start:i+1]
        cards={k:divergence(day,field) for k,field in [('macd_div','dif'),('rsi_div','rsi')]}
    else:
        cards=geometry(rows[max(0,i-119):i+1])[0]
        if tf=='1D': cards.update(long_term(rows[max(0,i-219):i+1]))
    return {k:v for k,v in cards.items() if k in KINDS and v['status'] in ACTIVE}


class StudyJournal:
    def __init__(self,engine,studies):
        self.engine=engine
        self.store=engine.store
        self.studies=studies
        self.stop=threading.Event()
        self.thread=None
        self.note='准备研究复盘'
        self.seen={}

    def start(self):
        self.thread=threading.Thread(target=self.run,daemon=True,name='study-journal')
        self.thread.start()

    def close(self):
        self.stop.set()
        if self.thread: self.thread.join(timeout=4)

    def scan(self,symbol,tf,rows,now):
        if not rows: return
        stream=(symbol,tf)
        last=rows[-1]['time']
        if self.seen.get(stream)==last: return
        version='v2' if tf=='1m' else 'v1'
        key=f'study_journal_{version}_{symbol}_{tf}'
        cursor=self.store.get(key,{})
        if cursor.get('bar','')>=last:
            self.seen[stream]=last
            return
        events=[]
        stamps=[r['time'] for r in rows]
        segments=[0]
        for i in range(1,len(rows)):
            if next_bar(stamps[i-1],tf)!=parse_time(stamps[i]): segments.append(i)
        ends=segments[1:]+[len(rows)]
        # Limit initial replay; process all available new bars after a saved checkpoint.
        initial=max(0,len(rows)-(390 if tf=='1m' else 60))
        recorded=now.isoformat()
        active=cursor.get('active',{})
        enriched=minute_series(rows) if tf=='1m' else rows
        notifications=[]
        for lo,hi in zip(segments,ends):
            if cursor and stamps[hi-1]<=cursor['bar']: continue
            run=enriched[lo:hi]
            markers={e['time']:e for e in replay(run)['events']} if tf=='1m' else {}
            start=next((i for i,b in enumerate(run) if b['time']>cursor['bar']),len(run)) if cursor else max(0,initial-lo)
            if start>=len(run): continue
            if not cursor or (start==0 and next_bar(cursor['bar'],tf)!=parse_time(run[0]['time'])):
                prev=observations_at(run,start-1,tf) if start else {}
                active={k:v.get('anchor',v['status']) for k,v in prev.items()}
            for i in range(start,len(run)):
                if self.stop.is_set(): return
                b=run[i]
                current=observations_at(run,i,tf)
                marker=markers.get(b['time'])
                if marker: current['minute_'+marker['stage']]=marker
                state={}
                for k,v in current.items():
                    token=v.get('anchor',v['status'])
                    state[k]=token
                    if active.get(k)==token: continue
                    stamp=b['time']
                    confirmation=bar_end(b,tf).astimezone(ET).isoformat()
                    episode=v.get('anchor',stamp)+'/'+v['status']
                    events.append((symbol,tf,k,episode,stamp,confirmation,recorded,b['close'],json.dumps(v,ensure_ascii=False)))
                    if marker is v and cursor and 0 <= (now-parse_time(confirmation)).total_seconds()<=90:
                        notifications.append(v)
                active=state
        indices={stamp:i for i,stamp in enumerate(stamps)}
        segment_end={i:hi for lo,hi in zip(segments,ends) for i in range(lo,hi)}
        with self.store.lock,self.store.db as db:
            db.executemany('INSERT OR IGNORE INTO study_observations(symbol,tf,kind,episode,bar_time,confirmed,recorded,price,evidence) VALUES(?,?,?,?,?,?,?,?,?)',events)
            pending=db.execute('''SELECT id,bar_time,kind,evidence FROM study_observations o WHERE symbol=? AND tf=? AND bar_time>=?
                AND NOT EXISTS(SELECT 1 FROM study_outcomes r WHERE r.observation=o.id AND r.horizon=20)''',(symbol,tf,stamps[0])).fetchall()
            outcomes=[]
            returns=[]
            for obs in pending:
                i=indices.get(obs['bar_time'])
                if i is None: continue
                base=rows[i]['close']
                for n in HORIZONS:
                    if i+n>=segment_end[i]: continue
                    if tf=='1m' and stamps[i][:10]!=stamps[i+n][:10]: continue
                    future=rows[i+1:i+n+1]
                    if obs['kind'] in ('minute_first','minute_confirmed'):
                        event=json.loads(obs['evidence'])
                        edge=event['top'] if event['side']==1 else event['bottom']
                        returned=any(event['side']*(bar['close']-edge)<=0 for bar in future)
                        returns.append((obs['id'],n,int(returned)))
                    outcomes.append((obs['id'],n,100*(future[-1]['close']/base-1),
                                     max(0,100*(1-min(b['low'] for b in future)/base))))
            db.executemany('INSERT OR IGNORE INTO study_outcomes VALUES(?,?,?,?)',outcomes)
            db.executemany('INSERT OR IGNORE INTO platform_returns VALUES(?,?,?)',returns)
            db.execute('INSERT OR REPLACE INTO kv VALUES(?,?)',(key,json.dumps({'bar':last,'active':active})))
        self.seen[stream]=last
        if notifications and self.engine.connected and self.store.settings()['notifications']:
            for event in notifications:
                try: notify(symbol+' · '+event['status'],event['facts'][0])
                except Exception: log.exception('Platform notification failed')

    def run(self):
        last_minute={}
        while not self.stop.is_set():
            errors=[]
            now=now_utc()
            for code in self.store.watchlist():
                if self.stop.is_set(): return
                try:
                    frames=closed_frames(lambda tf:self.store.bars(code,tf),now)
                    for tf,series in frames.items():
                        if self.stop.is_set(): return
                        self.scan(code,tf,series,now)
                    bucket=expected_last_close('1m' if self.store.settings()['notifications'] else '15m',now)
                    if self.engine.connected and last_minute.get(code)!=bucket:
                        minute=self.studies.external(code,now,'intraday')
                        if minute['errors'] or not minute['minute']:
                            errors.append(code+' 分钟线未就绪')
                        else:
                            self.scan(code,'1m',minute['minute'],now)
                            if bar_end(minute['minute'][-1],'1m')>=bucket: last_minute[code]=bucket
                except Exception as exc:
                    errors.append(code+' 复盘更新失败')
                    log.exception('Study journal update failed for %s',code)
            self.note=f"最近复核 {now_utc().astimezone(ET):%m-%d %H:%M} ET"
            if not self.engine.connected: errors.append('OpenD 离线，分钟线暂停更新')
            if errors: self.note+=' · '+' · '.join(errors)
            self.stop.wait(50)

    def report(self,symbol,tf,horizon,kind):
        filters=[]
        params=[]
        for field,value in [('o.symbol',symbol),('o.tf',tf),('o.kind',kind)]:
            if value:
                filters.append(field+'=?')
                params.append(value)
        where=' WHERE '+' AND '.join(filters) if filters else ''
        join=' FROM study_observations o LEFT JOIN study_outcomes r ON r.observation=o.id AND r.horizon=?'+where
        with self.store.lock:
            comparison=[]
            if tf in ('','1m') and kind in ('','minute_first','minute_confirmed'):
                clause=' AND ' if where else ' WHERE '
                sql="""SELECT o.kind, json_extract(o.evidence,'$.side') side,count(*) total,
                       count(p.reentered) mature,sum(p.reentered) returned,
                       avg((o.price/json_extract(o.evidence,'$.first_price')-1)*100*json_extract(o.evidence,'$.side')) wait_move
                       FROM study_observations o LEFT JOIN platform_returns p ON p.observation=o.id AND p.horizon=?"""
                comparison=self.store.db.execute(sql+where+clause+
                    "o.kind IN ('minute_first','minute_confirmed') GROUP BY o.kind,side ORDER BY side DESC,o.kind DESC",
                    [horizon,*params]).fetchall()
            groups=self.store.db.execute('SELECT o.kind,o.tf,json_extract(o.evidence,\'$.status\') status,count(*) total,count(r.observation) mature,avg(r.return_pct) mean_return,avg(r.mae_pct) mean_mae,max(r.mae_pct) worst_mae'+join+' GROUP BY o.kind,o.tf,status ORDER BY mature DESC',[horizon,*params]).fetchall()
            rows=self.store.db.execute('SELECT o.symbol,o.tf,o.kind,o.confirmed,o.recorded,o.evidence,o.price,r.return_pct,r.mae_pct'+join+' ORDER BY o.confirmed DESC,o.id DESC LIMIT 100',[horizon,*params]).fetchall()
        return {'groups':[dict(r) for r in groups],'latest':[dict(r)|{'evidence':json.loads(r['evidence'])} for r in rows],
                'platform_comparison':[dict(r) for r in comparison],'status':self.note,'kinds':KINDS}
