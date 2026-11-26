"""Evaluate the existing setup at a chart close and the minute checklist at a single minute close."""
from datetime import timedelta
from functools import lru_cache
import hashlib
import json

from .analysis import analyze
from .entry_score import entry_score
from .market import bar_end, bounds, parse_time
from .provider import MoomooProvider


def candle_score(frames, cutoff, settings):
    # Live rules wait three seconds after a close before accepting that candle.
    analysis = analyze({tf:frames.get(tf, []) for tf in ('1D','60m','15m')},
                       now=cutoff+timedelta(seconds=3),settings=settings)
    score = entry_score({'analysis':analysis}, {'mode':'replay'})
    if not analysis['fresh']:
        score.update(total=None, setups=[], verdict='所选时点缺少已收盘的日线、小时线或 15 分钟线')
    return score


@lru_cache(maxsize=16)
def history_window(code, port, day, fetched_on):
    provider = MoomooProvider()
    try:
        provider.connect(port)
        return {tf:provider.history(code,tf,start=(day-timedelta(days=days)).isoformat(),end=day.isoformat())
                for tf,days in [('1D',180),('60m',35),('15m',10)]}
    finally:
        provider.close()


def minute_score(rows, index):
    b = rows[index]
    end = bar_end(b,'1m')
    start = bounds(b['time'][:10])[0]
    continuous = (parse_time(b['time'])-start).total_seconds() == index*60
    close, vwap, dif, dea, rsi, vol = (b.get(k) for k in ('close','vwap','dif','dea','rsi','volume_ratio20'))
    def points(label, limit, met, evidence):
        return dict(label=label,limit=limit,points=None if met is None else limit if met else 0,evidence=evidence)
    def fmt(n):
        return '缺数据' if n is None else f'{n:.3f}'
    rows_scored = [
        points('收盘站上当日 VWAP',30,close>vwap if vwap is not None and continuous else None,
               f'收盘 {close:.2f}，当日 VWAP {fmt(vwap)}。'+('' if continuous else '当日分钟线不完整。')),
        points('MACD 多头动量',25,dif>dea and dif>0 if dif is not None and dea is not None else None,
               f'DIF {fmt(dif)}，DEA {fmt(dea)}；要求 DIF 高于 DEA 且在零轴上方。'),
        points('RSI 位于做多观察区',15,50<rsi<70 if rsi is not None else None,
               f'RSI(14) {fmt(rsi)}，要求高于 50 且低于 70。'),
        points('分钟放量',20,vol>=1.2 if vol is not None else None,
               f'本分钟 {b["volume"]:,.0f} 股，相对前 20 根常规时段分钟线均量 {fmt(vol)} 倍，门槛 1.2 倍。'),
        points('分钟阳线',10,close>b['open'],f'本分钟开盘 {b["open"]:.2f}，收盘 {close:.2f}。'),
    ]
    total = sum(r['points'] for r in rows_scored) if all(r['points'] is not None for r in rows_scored) else None
    return dict(total=total, as_of=end.isoformat(),snapshot_id=hashlib.sha256(json.dumps([end.isoformat(),rows_scored]).encode()).hexdigest()[:20],
                verdict='数据不足，暂缓评估' if total is None else
                '当时日内做多条件齐备' if total==100 else '当时部分条件满足，等待确认' if total>=60 else '当时条件较少，暂缓开仓',
                setups=[dict(name='日内分钟做多',total=total,rows=rows_scored)])
