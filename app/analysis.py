"""Deterministic, versioned long-only research rules; never executes orders."""
from statistics import mean
from .market import completed, is_current, now_utc, bar_end, parse_time

RULE_VERSION = 'v1.0'

def sma(values, length):
    return mean(values[-length:]) if len(values) >= length else None

def atr(bars, length=14):
    if len(bars) <= length:
        return None
    return mean(max(b['high'] - b['low'], abs(b['high'] - a['close']), abs(b['low'] - a['close']))
                for a, b in zip(bars[-length-1:-1], bars[-length:]))

def trend(bars):
    values = [b['close'] for b in bars]
    ma20, ma50, ma200 = [sma(values, n) for n in (20, 50, 200)]
    result = {'state': 'insufficient', 'label': '数据不足', 'ma20': ma20, 'ma50': ma50, 'ma200': ma200,
              'atr': atr(bars), 'reason': '至少需要 55 根已收盘 K 线'}
    if len(values) < 55:
        return result
    slope = ma50 - sma(values[:-5], 50)
    up = values[-1] > ma20 > ma50 and slope > 0
    down = values[-1] < ma20 < ma50 and slope < 0
    state = 'up' if up else 'down' if down else 'range'
    reason = '价格 > MA20 > MA50，MA50 高于 5 根前' if up else '价格 < MA20 < MA50，MA50 低于 5 根前' if down else '价格、均线排列或均线方向尚未形成一致趋势'
    return dict(result, state=state, label={'up':'上升趋势','down':'下降趋势','range':'震荡 / 过渡'}[state], reason=reason)

def analyze(all_bars, benchmark=None, now=None, settings=None):
    now = now or now_utc()
    bars = {tf: completed(all_bars.get(tf, []), tf, now) for tf in ('1D', '60m', '15m')}
    return analyze_closed(bars, benchmark, now, settings)

def analyze_closed(bars, benchmark=None, now=None, settings=None):
    """Shared rule implementation; caller must supply ONLY candles completed at now."""
    now = now or now_utc()
    settings = settings or {}
    volume_min = settings.get('volume_multiple', 1.5)
    daily, hourly, entry = [bars[t] for t in ('1D', '60m', '15m')]
    trends = {tf: trend(series) for tf, series in bars.items()}
    result = {'trends': trends, 'ready': False, 'fresh': all(is_current(bars[t], t, now) for t in bars),
              'support': None, 'resistance': None, 'trigger': None, 'stop': None, 'distance': None,
              'relative_strength': None, 'signals': [], 'conditions': [], 'rule_version': RULE_VERSION,
              'message': '等待足够的日线、小时线和 15 分钟历史数据', 'bar_time': None}
    if benchmark:
        bench = {b['time'][:10]: b['close'] for b in completed(benchmark, '1D', now)}
        aligned = [(b['close'], bench[b['time'][:10]]) for b in daily if b['time'][:10] in bench]
        if len(aligned) >= 21:
            result['relative_strength'] = ((aligned[-1][0] / aligned[-21][0] - 1) - (aligned[-1][1] / aligned[-21][1] - 1)) * 100
    if len(daily) < 55 or len(hourly) < 55 or len(entry) < 25:
        return result
    # Hourly levels are frozen before the candidate entry candle begins.
    context = [b for b in hourly if bar_end(b, '60m') <= parse_time(entry[-1]['time'])]
    if len(context) < 20:
        return result
    current, previous = entry[-1], entry[-2]
    resistance = max(b['high'] for b in context[-20:])
    support = min(b['low'] for b in context[-20:])
    vol_base = mean(b['volume'] for b in entry[-21:-1])
    vol_ratio = current['volume'] / vol_base if vol_base > 0 else 0
    volatility = atr(entry) or 0
    daily_up = trends['1D']['state'] == 'up'
    hour_trend = trend(context)
    hourly_ok = hour_trend['state'] != 'down'
    volume_ok = vol_ratio >= volume_min
    breakout = previous['close'] <= resistance < current['close']
    # A pullback must visit a frozen hourly MA20 zone and break the prior 3 bars.
    hourly_ma = hour_trend['ma20']
    hourly_atr = atr(context) or 0
    zone_hit = hourly_ma is not None and any(b['low'] <= hourly_ma + hourly_atr * .25 and b['high'] >= hourly_ma - hourly_atr * .25 for b in entry[-7:-1])
    structure_ok = min(b['low'] for b in entry[-7:]) >= support
    local_high = max(b['high'] for b in entry[-4:-1])
    pullback = zone_hit and structure_ok and current['close'] > local_high and current['close'] > (hourly_ma or 0)
    stop = min(b['low'] for b in entry[-7:]) - volatility * .2
    risk = current['close'] - stop
    result.update(ready=True, support=support, resistance=resistance, trigger=resistance, stop=max(0, stop),
                  distance=(resistance / current['close'] - 1) * 100, bar_time=current['time'],
                  volume_ratio=vol_ratio, close=current['close'], target_2r=current['close']+risk*2,
                  message='等待入场条件确认')
    def check(group, label, points, met, evidence):
        return {'group':group, 'label':label, 'met':met, 'evidence':evidence, 'max_points':points}

    day = trends['1D']
    near_limit = settings.get('near_percent', .5)
    extension = current['close'] - resistance
    result['bar_close_time'] = bar_end(current, '15m').isoformat()
    result['conditions'] = [
        check('共同条件', '日线多头排列且 MA50 上行', 25, daily_up,
              f"收盘 {daily[-1]['close']:.2f}，MA20 {day['ma20']:.2f}，MA50 {day['ma50']:.2f}（5 根前 {sma([b['close'] for b in daily[:-5]],50):.2f}）。要求收盘 > MA20 > MA50。"),
        check('共同条件', '信号开始前的小时趋势未转空', 15, hourly_ok,
              f"最近已完成小时线为{hour_trend['label']}，收盘 {context[-1]['close']:.2f}。"),
        check('入场量能', '15 分钟放量确认', 20, volume_ok,
              f"本根 {current['volume']:,.0f} 股，前 20 根均量 {vol_base:,.0f} 股，量比 {vol_ratio:.2f}，要求 ≥ {volume_min:g}。"),
        check('顺势突破', '收盘从区间下方向上突破', 20, breakout,
              f"前收 {previous['close']:.2f}，小时区间上沿 {resistance:.2f}，本根收盘 {current['close']:.2f}。要求前收 ≤ 上沿 < 本收。"),
        check('顺势突破', '收盘位于突破位上方且偏离 ≤ 0.75 ATR', 20, 0 < extension <= volatility*.75,
              f"收盘减上沿 {extension:+.2f}，15 分钟 ATR {volatility:.2f}，允许向上偏离 {volatility*.75:.2f}。"),
        check('回调转强', '前 6 根触及小时 MA20 区域', 10, zone_hit,
              f"均线区域 {hourly_ma-hourly_atr*.25:.2f}–{hourly_ma+hourly_atr*.25:.2f}，按小时 MA20 ± 0.25 ATR 计算。"),
        check('回调转强', '回踩低点守住小时区间', 10, structure_ok,
              f"最近 7 根最低 {min(b['low'] for b in entry[-7:]):.2f}，须 ≥ 区间下沿 {support:.2f}。"),
        check('回调转强', '收盘高于前 3 根高点和小时 MA20', 15, current['close']>max(local_high,hourly_ma),
              f"收盘 {current['close']:.2f}，前 3 根最高 {local_high:.2f}，小时 MA20 {hourly_ma:.2f}。"),
        check('回调转强', '参考保护位低于收盘', 5, risk>0,
              f"参考保护位 {stop:.2f}，每股风险距离 {risk:.2f}。"),
        check('接近突破位', '收盘接近小时区间上沿', 0, 0<=result['distance']<=near_limit,
              f"距上沿 {result['distance']:+.2f}%，提醒范围 0 至 {near_limit:g}%。此观察提醒仅另需满足两项共同条件。"),
    ]
    if not result['fresh']:
        result['message'] = '历史数据尚未补齐，暂停生成新信号'
        return result
    if daily_up and hourly_ok:
        if breakout and volume_ok:
            # Limit extension from the pre-existing level, not a moving threshold.
            if current['close'] - resistance <= volatility * .75:
                result['signals'].append({'kind':'breakout','title':'顺势突破确认', 'detail':f'15 分钟收盘突破 {resistance:.2f}；相对成交量 {vol_ratio:.2f} 倍'})
            else:
                result['message'] = '已偏离突破位，等待回踩'
        if pullback and volume_ok and risk > 0:
            result['signals'].append({'kind':'pullback','title':'回调转强确认','detail':f'回踩小时 MA20 区域后，15 分钟收盘突破 {local_high:.2f}'})
        if 0 <= result['distance'] <= settings.get('near_percent', .5):
            result['signals'].append({'kind':'near','title':'接近突破位','detail':f'距小时区间上沿 {resistance:.2f} 还有 {result["distance"]:.2f}%'})
    if result['signals']:
        result['message'] = result['signals'][0]['title']
    return result
