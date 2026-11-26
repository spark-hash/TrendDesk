"""Causal regular-session platform replay on completed one-minute candles."""
from datetime import timedelta

from .analysis import atr
from .market import parse_time
from .technicals import card, trend_channel

STAGES = {'formed':'平台确认','first':'初次突破','confirmed':'5 分钟确认','returned':'突破回落'}


def touches(rows, field, edge, tolerance):
    last = -3
    inside = False
    count = 0
    for i, row in enumerate(rows):
        near = abs(row[field]-edge) <= tolerance
        if near and not inside and i-last >= 3:
            last = i
            count += 1
        inside = near
    return count


def candidate(rows):
    top, bottom = max(b['high'] for b in rows), min(b['low'] for b in rows)
    unit = atr(rows)
    if not unit or not 0 < top-bottom <= 4*unit or abs(rows[-1]['close']-rows[0]['close']) > unit:
        return None
    tolerance = min(.4*unit, (top-bottom)*.2)
    highs = touches(rows,'high',top,tolerance)
    lows = touches(rows,'low',bottom,tolerance)
    if min(highs,lows) < 2: return None
    return dict(start=rows[0]['time'], formed=rows[-1]['time'], end=rows[-1]['time'],
                top=top,bottom=bottom,highs=highs,lows=lows)


def marker(stage,box,row,side,first_price=None):
    end = parse_time(row['time'])+timedelta(minutes=1)
    duration = int((end-parse_time(box['start'])).total_seconds()/60)
    direction = '上破' if side==1 else '下破' if side==-1 else ''
    status = ' · '.join(filter(None,[direction,STAGES[stage]]))
    facts = [f"{end:%H:%M} ET 收盘 {row['close']:.2f}，平台 {box['bottom']:.2f}–{box['top']:.2f}。",
             f"从平台起点算起 {duration} 分钟，确认时上沿测试 {box['highs']} 次、下沿 {box['lows']} 次。",
             f"本分钟成交 {row['volume']:,.0f} 股。"]
    if row.get('vwap') is not None:
        facts.append(f"当时 VWAP {row['vwap']:.2f}，收盘与 VWAP 相差 {row['close']-row['vwap']:+.2f}。")
    if stage=='first': facts.append('首次收在固定边界外，等待之后一根完整的 5 分钟 K 线确认。')
    if stage=='confirmed': facts.append('初破后首个完整的 5 分钟时段已收盘，价格仍在同侧边界外。')
    if stage=='returned': facts.append('分钟收盘已回到突破边界内侧或触及原边界。')
    return card('分时平台',status,*facts) | dict(
        stage=stage,time=row['time'],at=end.isoformat(),anchor=box['formed'],side=side,
        top=box['top'],bottom=box['bottom'],price=row['close'],first_price=first_price,
        id='platform_'+end.strftime('%H%M')+'_'+stage)


def replay(rows):
    boxes, events = [], []
    box = previous = None
    segment = search = 0
    side = 0
    first = confirmed = None
    for i,row in enumerate(rows):
        stamp = parse_time(row['time'])
        if previous is None or stamp-previous!=timedelta(minutes=1) or stamp.date()!=previous.date():
            segment = search = i
            box = None
        previous = stamp
        if box is None:
            if i-search+1 < 20: continue
            box = candidate(rows[i-19:i+1])
            if box:
                boxes.append(box)
                events.append(marker('formed',box,row,0))
                side,first,confirmed = 0,None,None
            continue
        box['end'] = row['time']
        price = row['close']
        if not side:
            side = 1 if price>box['top'] else -1 if price<box['bottom'] else 0
            if side:
                first = i
                events.append(marker('first',box,row,side,price))
            continue
        edge = box['top'] if side==1 else box['bottom']
        if side*(price-edge)<=0:
            events.append(marker('returned',box,row,side,rows[first]['close']))
            box = None
            search = i+1 if confirmed is None else confirmed+1
        elif confirmed is None and i-first>=5 and (stamp.minute+1)%5==0:
            confirmed = i
            events.append(marker('confirmed',box,row,side,rows[first]['close']))
        elif confirmed is not None and i-confirmed>=20:
            box = None
            search = confirmed+1

    window = rows[max(segment,len(rows)-60):]
    channel = card('分时趋势通道','样本积累中','需要当日连续 30 根已收盘分钟线。')
    lines = []
    if len(window)>=30:
        channel,lines = trend_channel(window,max(atr(window),window[-1]['close']*.0001))
        channel['title'] = '分时趋势通道'
        if lines:
            upper,lower = lines[0][-1],lines[1][-1]
            fraction = (window[-1]['close']-lower)/(upper-lower) if upper>lower else .5
            position = '靠近下轨' if fraction<1/3 else '靠近上轨' if fraction>2/3 else '位于通道中部'
            channel['facts'].append(f'最新收盘{position}，距下轨占通道宽度的 {fraction:.0%}。')
    platform = card('当前分时平台','观察中','连续 20 分钟，区间宽度 ≤ 4 ATR，净位移 ≤ 1 ATR。两侧均须至少两次独立测试。')
    if box:
        platform = card('当前分时平台',events[-1]['status'],*events[-1]['facts'])
    return {'lines':lines,'boxes':boxes,'events':events,'channel':channel,'platform':platform}
