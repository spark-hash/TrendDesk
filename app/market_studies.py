from math import isfinite
from statistics import mean
from threading import Lock
from time import monotonic
from .analysis import atr, sma
from .market import ET, TIME_LABELS, bar_end, bounds, calendar, completed, expected_last_close, now_utc, parse_time
from .timeframes import weekly, closed_frames
from .provider import MoomooProvider
from .filings import financials
from .technicals import card, geometry, pivots
from .intraday_structure import replay
from .point_score import minute_score
from .cross_levels import ranked_zones

def ema(values,period):
    out=[]
    seed=[]
    current=None
    for v in values:
        if v is not None:
            if current is None:
                seed.append(v)
                if len(seed)==period: current=mean(seed)
            else: current+=(v-current)*2/(period+1)
        out.append(current)
    return out


def wilder_rsi(values,period=14):
    out=[None]*len(values)
    if len(values)<=period: return out
    changes=[b-a for a,b in zip(values,values[1:])]
    gain=mean(max(v,0) for v in changes[:period])
    loss=mean(max(-v,0) for v in changes[:period])
    for i in range(period,len(values)):
        if i>period:
            gain=((period-1)*gain+max(0,changes[i-1]))/period
            loss=((period-1)*loss+max(0,-changes[i-1]))/period
        out[i]=100*gain/(gain+loss) if gain+loss else 50
    return out


def divergence(rows,key):
    for field,sign,label in [('high',1,'顶背离'),('low',-1,'底背离')]:
        indices=pivots(rows,field)
        if len(indices)<2: continue
        a,b=indices[-2:]
        if len(rows)-1-b>15 or b-a<3: continue
        first,last=rows[a],rows[b]
        if first[key] is None or last[key] is None: continue
        if sign*(last[field]-first[field])>0 and sign*(last[key]-first[key])<0:
            return card(('MACD' if key=='dif' else 'RSI')+' 背离',label,
                        f"{first['time'][11:16]} → {last['time'][11:16]} ET，价格 {first[field]:.2f} → {last[field]:.2f}，指标 {first[key]:.3f} → {last[key]:.3f}。") | {'anchor':last['time']}
    return card(('MACD' if key=='dif' else 'RSI')+' 背离','未出现已确认的常规背离' if len(rows)>=7 else '日内拐点数据不足',
                '比较当日最近两个已确认同侧价格拐点对应的指标值，两侧各等 2 根；最新拐点限最近 15 根。')


def minute_series(bars):
    if not bars: return []
    prices=[b['close'] for b in bars]
    fast,slow=ema(prices,12),ema(prices,26)
    dif=[a-b if a is not None and b is not None else None for a,b in zip(fast,slow)]
    signal=ema(dif,9)
    rsi=wilder_rsi(prices)
    day=None
    total=volume=0
    rows=[]
    for i,b in enumerate(bars):
        if b['time'][:10]!=day:
            day=b['time'][:10]
            total=volume=0
        total+=mean((b['high'],b['low'],b['close']))*b['volume']
        volume+=b['volume']
        prev_vol=sum(row['volume'] for row in bars[i-20:i]) if i>=20 else 0
        rows.append(b|{'volume_ratio20':b['volume']*20/prev_vol if prev_vol else None,
                       'vwap':total/volume if volume else None,'dif':dif[i],'dea':signal[i],
                       'hist':dif[i]-signal[i] if signal[i] is not None else None,'rsi':rsi[i]})
    return rows


def intraday(bars):
    if not bars: return {},[]
    rows=[r for r in minute_series(bars) if r['time'][:10]==bars[-1]['time'][:10]]
    volume=sum(r['volume'] for r in rows)
    latest=rows[-1]
    def value(k):
        return '预热不足' if latest[k] is None else f'{latest[k]:.3f}'
    cards={'price':card('分时价格',f'{latest["close"]:.2f}',f'常规时段已收盘分钟线 {len(rows)} 根；当日累计成交量 {volume:,.0f} 股。'),
           'vwap':card('分时 VWAP',value('vwap'),'当日从开盘累计，用分钟典型价 (H+L+C)/3 按成交量加权。'),
           'macd':card('MACD (12,26,9)',f"DIF {value('dif')} · DEA {value('dea')}",f"柱值 DIF−DEA {value('hist')}；EMA 跨交易日预热。"),
           'rsi':card('RSI (14)',value('rsi'),'Wilder 平滑。70 / 30 为观察区间。'),
           'macd_div':divergence(rows,'dif'),'rsi_div':divergence(rows,'rsi')}
    return cards,rows


def long_term(daily):
    if len(daily)<220: return {'timing':card('长线入场观察','至少需要 220 根已收盘日线')}
    prices=[b['close'] for b in daily]
    current=prices[-1]
    ma50,ma200=sma(prices,50),sma(prices,200)
    prior200=sma(prices[:-20],200)
    up=current>ma200 and ma50>ma200 and ma200>prior200
    unit=atr(daily[:-1])
    prior50=sma(prices[:-1],50)
    pull=daily[-1]['low']<=prior50+unit*0.5 and daily[-1]['high']>=prior50-unit*0.5 and current>prior50 and current>prices[-2]
    high=max(b['high'] for b in daily[-61:-1])
    return {'ma50':card('50 日均线',f'{ma50:.2f}',f'最新收盘 {current:.2f}。'),
            'ma200':card('200 日均线',f'{ma200:.2f}',f'20 个交易日前 {prior200:.2f}。'),
            'timing':card('长线入场观察','趋势内突破' if up and current>high else '趋势内回踩转强' if up and pull else '趋势成立 · 等待时机' if up else '长期趋势未确认',
            f'趋势要求收盘及 MA50 高于 MA200，且 MA200 高于 20 日前。当前收盘 {current:.2f}。',
            f'回踩区 {prior50-unit*.5:.2f}–{prior50+unit*.5:.2f}，触区后须收于昨日 MA50 上方且高于昨收；另一触发条件为收盘突破此前 60 日高点 {high:.2f}。',
            f'收盘跌破 MA200（{ma200:.2f}）时重评。此为价格筛选规则，未做长线绩效回测。')}


def fundamentals(record):
    if not record.get('equity_valid'): return {'overview':card('基本面','无普通股估值数据','ETF 等标的不适用公司每股盈利指标。')}
    fields=[('pe_ttm_ratio','滚动市盈率','倍'),('pb_ratio','市净率','倍'),('earning_per_share','每股盈利',''),
            ('dividend_ratio_ttm','过去一年股息率','%'),('total_market_val','总市值','')]
    cards={}
    for key,title,suffix in fields:
        v=record.get(key)
        if not isinstance(v,(float,int)) or not isfinite(v): continue
        text=f'{v/1e9:,.2f} 十亿' if key=='total_market_val' else f'{v:,.2f}{suffix}'
        cards[key]=card(title,text,'moomoo 普通股快照，币种及口径依标的披露。')
    pe=record.get('pe_ttm_ratio')
    if 'pe_ttm_ratio' in cards:
        cards['pe_ttm_ratio']['facts'].append('市盈率为零或负时，盈利倍数估值的解释力有限。' if pe<=0 else f'滚动盈利收益率约 {100/pe:.2f}%（市盈率倒数）。')
    cards['overview']=card('基本面概览','盈利倍数可比较' if 'pe_ttm_ratio' in cards and pe>0 else '盈利倍数参考有限',
                           '本页提供当前估值、盈利和分红快照；比较估值需结合同行、增长和现金流。快照时间为行情更新时间。')
    return cards


class StudyFeed:
    def __init__(self,engine):
        self.engine=engine
        self.guard=Lock()
        self.locks={}
        self.cache={}
        self.level_cache={}

    def cross_levels(self,code,now):
        with self.guard:
            saved=self.level_cache.get(code)
            if saved and monotonic()<saved[0]: return saved[1]
        frames=closed_frames(lambda t:self.engine.store.bars(code,t),now)
        zones=ranked_zones(frames,{tf:geometry(rows) for tf,rows in frames.items()},now)
        with self.guard:
            if len(self.level_cache)>=64: self.level_cache.clear()
            self.level_cache[code]=(monotonic()+30,zones)
        return zones

    def external(self,code,now,section):
        port=self.engine.store.settings()['port']
        key=(code,port,section)
        minute=section=='intraday'
        version=expected_last_close('1m',now) if minute else None
        with self.guard:
            lock=self.locks.setdefault(key,Lock())
        with lock:
            saved=self.cache.get(key)
            if saved and saved[0]==version and monotonic()<saved[1]:
                return saved[2]
            client=MoomooProvider()
            data={'minute':[],'fund':{},'errors':{}}
            try:
                client.connect(port)
                if minute:
                    day=version.astimezone(ET).date().isoformat()
                    previous=calendar().previous_session(day).date().isoformat()
                    bars=client.history(code,'1m',start=previous,end=day)
                    data['minute']=completed(bars,'1m',now)
                else:
                    ret,frame=client.ctx.get_market_snapshot(['US.'+code])
                    if ret!=client.mm.RET_OK: raise ValueError(str(frame))
                    row=frame.to_dict('records')[0]
                    data['fund']=fundamentals(row)
                    data['fund_time']=str(row.get('update_time') or now.astimezone(ET).isoformat())
            except Exception as exc: data['errors'][section]=str(exc)[:180]
            finally: client.close()
            if not minute:
                annual,note=financials(self.engine.store,code,now)
                data['fund'].update(annual)
                if annual and not data.get('fund_time'):
                    data['fund_time']=now.astimezone(ET).date().isoformat()
                if note:
                    data['errors'][section]=' · '.join(filter(None,[data['errors'].get(section),note]))
            ttl=30 if data['errors'] else 300 if minute else 900
            self.cache[key]=(version,monotonic()+ttl,data)
            return data

    def read(self,code,tf,section='all'):
        now=now_utc()
        result={'symbol':code,'tf':tf,'sections':{},'times':{},'errors':{},'candles':[],'lines':[],
                'minutes':[],'minute_gaps':0,'expected_minute':expected_last_close('1m',now).astimezone(ET).isoformat(),
                'expected_daily':expected_last_close('1D',now).astimezone(ET).isoformat()}
        def stamp(bars,period):
            if bars: return bar_end(bars[-1],period).astimezone(ET).isoformat()
        if section in ('structure','longterm','all'):
            if section!='structure':
                daily=completed(self.engine.store.bars(code,'1D'),'1D',now)
                result['sections']['longterm']=long_term(daily)
                result['times']['longterm']=stamp(daily,'1D')
            if section!='longterm':
                self.structure(result,code,tf,now)
        if section in ('intraday','all'):
            if section=='intraday': result['cross_levels']=self.cross_levels(code,now)
            ext=self.external(code,now,'intraday')
            intr,points=intraday(ext['minute'])
            overlay=replay(points)
            if points:
                intr.update(channel=overlay.pop('channel'),platform=overlay.pop('platform'))
                if overlay['events']:
                    recent=overlay['events'][-1]
                    intr['platform_latest']=card('最近一次平台提醒',recent['status'],*recent['facts'])
            result['intraday_overlay']=overlay
            result['sections']['intraday']=intr
            result['times']['intraday']=stamp(ext['minute'],'1m')
            result['minutes']=points
            result['errors'].update(ext['errors'])
            if points:
                final=parse_time(points[-1]['time'])
                result['minute_score']=minute_score(points,len(points)-1)
                count=int((final-bounds(points[-1]['time'][:10])[0]).total_seconds()//60)+1
                result['minute_gaps']=max(0,count-len({b['time'] for b in points}))
        if section in ('fundamental','all'):
            ext=self.external(code,now,'fundamental')
            result['sections']['fundamental']=ext['fund']
            result['times']['fundamental']=ext.get('fund_time')
            result['errors'].update(ext['errors'])
        return result

    def structure(self,result,code,tf,now):
        frames=closed_frames(lambda t:self.engine.store.bars(code,t),now)
        bars=frames[tf]
        studies={t:geometry(rows) for t,rows in frames.items()}
        structure,lines=studies[tf]
        zones=ranked_zones(frames,studies,now)
        result['cross_levels']=zones
        levels=[f"{z['side']} #{z['priority']} · {z['low']:.2f}–{z['high']:.2f} · {z['tf']} {z['strength']} · 距收盘 {z['distance']:+.2f}% · {'、'.join(z['periods'])}"
                for z in zones if z['priority']<=3 or z['near']]
        structure={'levels':card('跨周期关键位','周期优先 · 另列最近两档',
            '先按最高周期，再按重合周期数、该周期独立测试次数、距现价远近排序。',*levels),**structure}
        result.update(candles=bars[-300:],lines=lines)
        result['sections']['structure']=structure
        result['times']['structure']=bar_end(bars[-1],tf).astimezone(ET).isoformat() if bars else None
        if not bars or bar_end(bars[-1],tf)<expected_last_close(tf,now):
            result['errors']['structure']=getattr(self.engine,'history_errors',{}).get((code,tf),'等待最新已收盘行情')
