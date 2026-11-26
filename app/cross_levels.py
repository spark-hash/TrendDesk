"""Rank current structural zones by timeframe first, with proximity kept separately."""
from .analysis import atr
from .market import TIME_LABELS, bar_end, expected_last_close

PERIODS=('5m','15m','30m','60m','4h','1D','1W','1M')


def ranked_zones(frames, studies, now):
    available=[tf for tf in PERIODS if frames.get(tf)]
    if not available: return []
    # Use the most recent close, preferring the finest timeframe for ties.
    latest=max(available,key=lambda tf:bar_end(frames[tf][-1],tf))
    price=frames[latest][-1]['close']
    tolerance=max(price*.0012,min(price*.006,(atr(frames.get('1D',[])) or price*.01)*.15))
    points=[]
    for rank,tf in enumerate(PERIODS):
        if tf not in available: continue
        end=bar_end(frames[tf][-1],tf)
        if end<expected_last_close(tf,now): continue
        if tf in ('1D','1W','1M'):
            bar=frames[tf][-1]
            for field,label in [('high','最高'),('low','最低')]:
                points.append(dict(price=bar[field],tf=tf,rank=rank,name='最近已收盘周期'+label,
                                   strength='周期'+label,touches=0,as_of=end.isoformat()))
        for name,_,value,_,_,*metadata in studies[tf][1]:
            if not metadata and not name.startswith('平台'): continue
            meta=metadata[0] if metadata else {}
            points.append(dict(price=value,tf=tf,rank=rank,name=name,strength=meta.get('strength','平台边界'),
                               touches=meta.get('touches',0),as_of=end.isoformat()))
    result=[]
    for side in ('支撑','阻力'):
        candidates=sorted((p for p in points if (p['price']<=price)==(side=='支撑')),key=lambda p:p['price'])
        groups=[]
        for p in candidates:
            if not groups or p['price']-groups[-1][0]['price']>tolerance: groups.append([])
            groups[-1].append(p)
        ranked=[]
        for group in groups:
            lead=max(group,key=lambda p:(p['rank'],p['touches'],p['strength']=='平台边界'))
            periods=sorted({p['tf'] for p in group},key=PERIODS.index,reverse=True)
            first,last=group[0]['price'],group[-1]['price']
            ranked.append(dict(side=side,low=first,high=last,price=lead['price'],tf=TIME_LABELS[lead['tf']],
                strength=lead['strength'],touches=lead['touches'],rank=lead['rank'],as_of=lead['as_of'],
                periods=[TIME_LABELS[t] for t in periods],distance=(lead['price']/price-1)*100))
        ranked.sort(key=lambda z:(-z['rank'],-len(z['periods']),-z['touches'],abs(z['distance'])))
        nearest=sorted(ranked,key=lambda z:abs(z['distance']))[:2]
        for i,z in enumerate(ranked):
            z['priority']=i+1
            z['near']=z in nearest
        result.extend(ranked)
    return result
