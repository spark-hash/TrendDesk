"""Descriptive studies calculated on closed, regular-session bars."""
from statistics import mean
from .analysis import atr, sma


def card(title, status, *facts):
    return {'title': title, 'status': status, 'facts': list(facts)}


def pivots(bars, key, radius=2):
    compare = max if key == 'high' else min
    result = []
    for i in range(radius, len(bars)-radius):
        prices = [b[key] for b in bars[i-radius:i+radius+1]]
        if bars[i][key] == compare(prices) and prices.count(bars[i][key]) == 1:
            result.append(i)
    return result


def trend_channel(bars,unit):
    window = bars[-60:]
    n = len(window)
    mid = (n-1)/2
    centers = [b['close'] for b in window]
    avg = mean(centers)
    slope = sum((i-mid)*(v-avg) for i,v in enumerate(centers))/sum((i-mid)**2 for i in range(n))
    fitted = [avg+slope*(i-mid) for i in range(n)]
    upper = max(b['high']-v for b,v in zip(window,fitted))
    lower = min(b['low']-v for b,v in zip(window,fitted))
    variance = sum((v-avg)**2 for v in centers)
    r2 = 1-sum((a-b)**2 for a,b in zip(centers,fitted))/variance if variance else 0
    change = slope*(n-1)
    direction = ('上升通道' if change>0 else '下降通道') if abs(change)>=unit and r2>=0.35 else '方向未确认'
    channel = card('趋势通道',direction,f'最近 {n} 根收盘线性拟合，R² {r2:.2f}；方向门槛 0.35 且位移至少 1 ATR。',
                            f'上下轨包络该窗口高低点，当前下轨 {fitted[-1]+lower:.2f}，上轨 {fitted[-1]+upper:.2f}。')
    lines = []
    if direction!='方向未确认':
        for name,offset in [('通道上轨',upper),('通道下轨',lower)]:
            lines.append([name,window[0]['time'],fitted[0]+offset,window[-1]['time'],fitted[-1]+offset])
    return channel,lines


def geometry(bars):
    cards, lines = {}, []
    if len(bars) < 21:
        return {'structure': card('价格结构','至少需要 21 根已收盘 K 线')}, lines
    closes=[b['close'] for b in bars]
    for period in (20,50,200):
        level=sma(closes,period)
        cards['ma'+str(period)]=card(f'MA{period}',f'{level:.2f}' if level is not None else '预热不足',
            f'当前周期最近 {period} 根的收盘均价。')
    cards['atr']=card('ATR (14)',f'{atr(bars):.2f}','最近 14 根真实波幅的算术均值。')
    vol=mean(b['volume'] for b in bars[-21:-1])
    cards['volume']=card('成交量比',f"{bars[-1]['volume']/vol:.2f} 倍" if vol else '缺少有效基准','本根成交量 / 前 20 根平均成交量。')
    bars = bars[-120:]
    last = bars[-1]['close']
    unit = max(atr(bars), last*0.0001)
    cards['channel'],lines = trend_channel(bars,unit)
    high_p,low_p = pivots(bars,'high'),pivots(bars,'low')
    zones = []
    for i,price in sorted([(i,bars[i]['low']) for i in low_p]+[(i,bars[i]['high']) for i in high_p]):
        near = [z for z in zones if abs(mean(z['prices'])-price)<=0.4*unit and
                max(max(z['prices']),price)-min(min(z['prices']),price)<=0.8*unit]
        zone = min(near,key=lambda z:abs(mean(z['prices'])-price)) if near else None
        if zone is None:
            zones.append({'prices':[price],'last':i,'touches':1})
        elif i-zone['last']>=3:
            zone['prices'].append(price)
            zone['touches']+=1
            zone['last']=i
    for key,title in [('support','支撑'),('resistance','阻力')]:
        candidates = [z for z in zones if (mean(z['prices'])<last if key=='support' else mean(z['prices'])>last)]
        candidates.sort(key=lambda z:abs(mean(z['prices'])-last))
        for rank,z in enumerate(candidates[:2],1):
            price = mean(z['prices'])
            strength = '强' if z['touches']>=3 else '中' if z['touches']==2 else '弱'
            name = f'{title} {rank}'
            cards[f'{key}{rank}'] = card(name,f'{price:.2f} · {strength}',f"独立测试 {z['touches']} 次，最近测试 {bars[z['last']]['time'][:16]} ET。",
                '两侧各 2 根确认拐点；0.4 ATR 内聚类，触点至少相隔 3 根。强弱按测试次数分级。')
            lines.append([name,bars[0]['time'],price,bars[-1]['time'],price])
        if not candidates: cards[key]=card(title,'当前价格一侧没有已确认的拐点区域')
    base = bars[-21:-1]
    top,bottom=max(b['high'] for b in base),min(b['low'] for b in base)
    base_atr=atr(bars[:-1])
    flat = top-bottom<=4*base_atr and abs(base[-1]['close']-base[0]['close'])<=base_atr
    status = '向上突破' if last>top else '向下跌破' if last<bottom else '平台内'
    cards['platform']=card('整理平台',status if flat else '未形成',f'前 20 根区间 {bottom:.2f}–{top:.2f}，中位 {((bottom+top)/2):.2f}。',
                           '区间宽度不超过 4 ATR，首尾收盘位移不超过 1 ATR；用最新收盘判断突破。')
    if flat:
        for name,value in [('平台上沿',top),('平台下沿',bottom)]:
            lines.append([name,base[0]['time'],value,bars[-1]['time'],value])
    cards.update(patterns(bars,unit,high_p,low_p))
    return cards,lines


def patterns(bars,unit,highs,lows):
    cards={}
    a,b=bars[-2:]
    for key,name,indices,field,sign in [('top','顶',highs,'high',1),('bottom','底',lows,'low',-1)]:
        # Invert bottoms so both shapes have peaks and intervening troughs.
        peaks=[sign*x[field] for x in bars]
        troughs=[sign*x['low' if sign==1 else 'high'] for x in bars]
        for count,title in [(2,'双'+name),(3,'头肩'+name)]:
            label='未识别'
            evidence=['比较最近已确认的摆动点；同侧峰谷容差 1 ATR，颈线深度至少 1 ATR。']
            ids=indices[-count:]
            if len(ids)==count and len(bars)-1-ids[-1]<=20 and all(y-x>=3 for x,y in zip(ids,ids[1:])):
                neck_ids=[min(range(x+1,y),key=troughs.__getitem__) for x,y in zip(ids,ids[1:])]
                shoulder=min(peaks[ids[0]],peaks[ids[-1]])
                shape=(abs(peaks[ids[0]]-peaks[ids[-1]])<=unit and shoulder-max(troughs[i] for i in neck_ids)>=unit)
                if count==3: shape &= peaks[ids[1]]>=max(peaks[ids[0]],peaks[ids[-1]])+unit*0.6
                slope=(troughs[neck_ids[-1]]-troughs[neck_ids[0]])/(neck_ids[-1]-neck_ids[0]) if count==3 else 0
                neck=troughs[neck_ids[-1]]+slope*(len(bars)-1-neck_ids[-1])
                if shape and max(sign*x['close'] for x in bars[ids[-1]+1:])<=max(peaks[i] for i in ids)+unit*0.25:
                    label='收盘越过颈线' if sign*b['close']<neck else '候选 · 待颈线确认'
                    evidence=[f'拐点价格 '+ ' / '.join(f'{bars[i][field]:.2f}' for i in ids),
                              f'当前颈线 {sign*neck:.2f}，最近拐点 {bars[ids[-1]]["time"][:16]} ET。']
            cards[key+str(count)]=card(title,label,*evidence)
            if label=='收盘越过颈线':
                cards[key+str(count)]['anchor']=bars[ids[-1]]['time']
    ao,ac,bo,bc=a['open'],a['close'],b['open'],b['close']
    prev,body=abs(ac-ao),abs(bc-bo)
    inside=min(ao,ac)<min(bo,bc) and max(bo,bc)<max(ao,ac)
    opposite=(ac-ao)*(bc-bo)<0
    engulf=min(bo,bc)<=min(ao,ac) and max(bo,bc)>=max(ao,ac) and body>prev
    spread=b['high']-b['low']
    for key,title,active,rule in [
        ('harami','孕线',inside and opposite and prev>=0.5*unit,'前一根实体至少 0.5 ATR，当前反色实体完全落在前实体内'),
        ('engulf','吞没',opposite and engulf,'当前反色实体覆盖前一根实体'),
        ('inside','内包线',b['high']<a['high'] and b['low']>a['low'],'本根高低点都在前一根高低区间内'),
        ('doji','十字星',spread>0 and body<=0.1*spread,'实体不超过本根振幅的 10%')]:
        label=('阳线' if bc>bo else '阴线') if active and key in ('harami','engulf') else '出现' if active else '未出现'
        cards[key]=card(title,label,rule,f'前根开收 {ao:.2f} / {ac:.2f}；本根开高低收 {bo:.2f} / {b["high"]:.2f} / {b["low"]:.2f} / {bc:.2f}。')
    return cards
