"""Explainable checklist scores for the two existing long setups."""
import hashlib
import json
from .market import parse_time


def entry_score(item, state):
    analysis = item['analysis']
    checks = analysis['conditions']
    as_of = analysis.get('bar_close_time')
    setups = []
    for name in ('顺势突破', '回调转强'):
        factors = [check for check in checks if check['group'] in ('共同条件', '入场量能', name)]
        if not analysis['ready'] or sum(f.get('max_points', 0) for f in factors) != 100:
            continue
        rows = [dict(label=f['label'], evidence=f['evidence'], limit=f['max_points'],
                     points=f['max_points'] if f['met'] else 0) for f in factors]
        setups.append(dict(name=name, total=sum(row['points'] for row in rows), rows=rows))
    setups.sort(key=lambda s: -s['total'])
    total = setups[0]['total'] if setups else None
    if total is None:
        verdict = '资料不足，暂缓评估'
    elif state['mode'] == 'demo':
        verdict = '演示评分'
    elif state['mode'] == 'replay':
        verdict = ('当时周期数据不齐' if not analysis['fresh'] else '当时做多条件齐备' if total == 100
                   else '当时部分条件满足，等待确认' if total >= 60 else '当时条件较少，暂缓开仓')
    elif not analysis['fresh'] or item.get('error'):
        verdict = '历史数据待更新，暂缓开仓'
    elif not state['market']['open']:
        verdict = '收盘复盘，等待下一交易时段'
    elif not (state['connected'] and item['synced'] and item['quote_fresh']):
        verdict = '行情待同步，暂缓开仓'
    elif total == 100 and as_of and 0 <= (parse_time(state['now']) - parse_time(as_of)).total_seconds() <= 120:
        verdict = '做多条件齐备，可评估开仓'
    elif total >= 60:
        verdict = '列入观察，等待新的收盘确认'
    else:
        verdict = '条件较少，暂缓开仓'
    result = dict(total=total, setups=setups, verdict=verdict, as_of=as_of)
    result['snapshot_id'] = hashlib.sha256(json.dumps(result, sort_keys=True).encode()).hexdigest()[:20]
    return result
