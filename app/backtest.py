"""Causal 15-minute simulation with independent, equal-sleeve long-only portfolios."""
from bisect import bisect_right
from datetime import date, timedelta
import gzip
import hashlib
import json
import math
from pathlib import Path
import threading
import uuid
from .analysis import analyze_closed, RULE_VERSION
from .market import ET, now_utc, parse_time, calendar, bounds, bar_end
from .provider import MoomooProvider

MODEL_VERSION='bt-1.1'
STRATEGIES={'breakout':'顺势突破','pullback':'回调转强','orb15':'开盘区间突破'}

def orb_warmup_start(start):
    first=calendar().date_to_session(start,direction='next')
    return calendar().session_offset(first,-14).date().isoformat()

def opening_range_signals(minutes, start, end, volume_multiple):
    sessions=[s.date().isoformat() for s in calendar().sessions_in_range(orb_warmup_start(start),end)]
    opening_volumes={}
    signal_days=set()
    signals={}
    eligible={}
    for bar in minutes:
        stamp=bar['time']
        local=parse_time(stamp).astimezone(ET)
        day=local.date().isoformat()
        if day>end: break
        if local.hour==9 and local.minute==30:
            opening_volumes[day]=bar['volume']
            if day<start: continue
            i=bisect_right(sessions,day)-1
            baseline=[opening_volumes.get(s,0) for s in sessions[i-14:i]]
            if len(baseline)==14 and min(baseline)>0 and bar['close']>bar['open']:
                ratio=bar['volume']/(sum(baseline)/14)
                if ratio>=volume_multiple:
                    eligible[day]=(bar['high'],bar['low'],ratio)
        elif day in eligible and day not in signal_days:
            high,low,ratio=eligible[day]
            close=bar_end(bar,'15m')
            if close and close<bounds(day)[1] and bar['close']>high:
                signals[stamp]={'stop':low,'signal_time':close.isoformat(),'signal_price':bar['close'],
                    'detail':f'首根15分钟量比 {ratio:.2f}，收盘突破开盘高点 {high:.2f}'}
                signal_days.add(day)
    return signals

def expected_times(start, end, tf='15m'):
    output=[]
    for day in calendar().sessions_in_range(start,end):
        opening,closing=bounds(day.date().isoformat())
        if tf=='1D':
            output.append(day.date().isoformat())
            continue
        step=timedelta(minutes=15 if tf=='15m' else 60)
        while opening<closing:
            output.append(opening.astimezone(ET).isoformat())
            opening+=step
    return output

def validate_coverage(frames,start,end):
    coverage={}
    for tf in ('1D','60m','15m'):
        expected=set(expected_times(start,end,tf))
        actual={b['time'][:10] if tf=='1D' else parse_time(b['time']).astimezone(ET).isoformat() for b in frames[tf]}
        missing=expected-actual
        coverage[tf]={'expected':len(expected),'actual':len(expected&actual),'missing':len(missing)}
        if missing:
            raise ValueError(f'{tf} 缺少 {len(missing)}/{len(expected)} 根 K 线（首个缺口 {min(missing)}），未纳入回测')
    return coverage

def build_signals(frames, start, end, settings, cancelled=lambda:False):
    """Only prefixes available at each simulated bar close enter shared live rules."""
    daily=sorted((b for b in frames['1D'] if bar_end(b,'1D')),key=lambda b:parse_time(b['time']))
    hourly=sorted((b for b in frames['60m'] if bar_end(b,'60m')),key=lambda b:parse_time(b['time']))
    minutes=sorted(frames['15m'],key=lambda b:parse_time(b['time']))
    daily_ends=[bar_end(b,'1D') for b in daily]
    hourly_ends=[bar_end(b,'60m') for b in hourly]
    signals={kind:{} for kind in STRATEGIES}
    previous={'breakout':False,'pullback':False}
    evaluated=0
    for i,b in enumerate(minutes):
        if i%64==0 and cancelled(): raise InterruptedError('回测已取消')
        close=bar_end(b,'15m')
        if not close: continue
        d=bisect_right(daily_ends,close)
        h=bisect_right(hourly_ends,close)
        snapshot={'1D':daily[max(0,d-220):d], '60m':hourly[max(0,h-80):h], '15m':minutes[max(0,i-60):i+1]}
        # The 3-second live settlement buffer does not alter which closed bars are known.
        result=analyze_closed(snapshot,now=close+timedelta(seconds=3),settings=settings)
        in_range=start<=b['time'][:10]<=end
        if in_range and result['ready'] and result['fresh']: evaluated+=1
        kinds={s['kind'] for s in result['signals']}
        for kind in previous:
            if kind in kinds and not previous[kind] and in_range:
                signals[kind][b['time']]={'stop':result['stop'],'signal_time':close.isoformat(),
                    'signal_price':b['close'],'detail':next(s['detail'] for s in result['signals'] if s['kind']==kind)}
            previous[kind]=kind in kinds
    signals['orb15']=opening_range_signals(minutes,start,end,settings.get('volume_multiple',1.5))
    return signals,evaluated

def exit_on_bar(position, bar, slip):
    """Gap through stop executes at open; ambiguous high/low ordering chooses stop."""
    if bar['open']<=position['stop']:
        return bar['open']*(1-slip),'gap_stop'
    if bar['open']>=position['target']:
        return position['target']*(1-slip),'target'
    if bar['low']<=position['stop']:
        return position['stop']*(1-slip),'stop'
    if bar['high']>=position['target']:
        return position['target']*(1-slip),'target'
    return None

def simulate(symbol, bars, signals, params, initial):
    cash=initial
    position=None
    pending=None
    trades=[]
    curve=[]
    skipped={'busy':0,'invalid_stop':0,'size':0,'end_of_sample':0}
    fee=params['fee_bps']/10000
    slip=params['slippage_bps']/10000
    risk_pct=params['risk_percent']/100
    for index,b in enumerate(bars):
        stamp=b['time']
        if pending and position is None:
            entry=b['open']*(1+slip)
            risk=entry-pending['stop']
            if risk<=0 or pending['stop']<=0:
                skipped['invalid_stop']+=1
            else:
                # Fractional adjusted shares make split-adjusted price simulation coherent.
                size=min(cash*risk_pct/risk,cash/(entry*(1+fee)))
                size=math.floor(size*1000000)/1000000
                if size<=0:
                    skipped['size']+=1
                else:
                    entry_fee=size*entry*fee
                    cash-=size*entry+entry_fee
                    position=pending|{'entry_time':stamp,'entry_price':entry,'quantity':size,'entry_fee':entry_fee,
                        'target':entry+params['target_r']*risk,'bars':0,'half_r_path':'no',
                        'capital_before':cash+size*entry+entry_fee}
            pending=None
        if position:
            position['bars']+=1
            exit_result=exit_on_bar(position,b,slip)
            if not exit_result and position['bars']>=params['max_bars']:
                exit_result=(b['close']*(1-slip),'time_limit')
            if not exit_result and index==len(bars)-1:
                exit_result=(b['close']*(1-slip),'end_of_sample')
            threshold=position['entry_price']+(position['entry_price']-position['stop'])/2
            reason=exit_result[1] if exit_result else None
            if position['half_r_path']!='yes':
                if b['open']>=threshold or (reason=='target' and position['target']>=threshold):
                    position['half_r_path']='yes'
                elif reason!='gap_stop' and b['high']>=threshold:
                    position['half_r_path']='unknown' if reason=='stop' else 'yes'
            if exit_result:
                price,reason=exit_result
                proceeds=position['quantity']*price
                exit_fee=proceeds*fee
                cash+=proceeds-exit_fee
                pnl=position['quantity']*(price-position['entry_price'])-position['entry_fee']-exit_fee
                trades.append(position|{'symbol':symbol,'exit_time':bar_end(b,'15m').isoformat(),
                    'exit_bar_time':stamp,'exit_price':price,'reason':reason,'exit_fee':exit_fee,
                    'early_stop':reason in ('stop','gap_stop') and position['bars']<=2,
                    'pnl':pnl,'return_pct':pnl/(position['quantity']*position['entry_price']+position['entry_fee'])*100})
                position=None
        if stamp in signals:
            if position:
                skipped['busy']+=1
            elif index==len(bars)-1:
                skipped['end_of_sample']+=1
            else:
                pending=signals[stamp]
        # Liquidation value, including accrued estimated exit fee, sampled each 15m close.
        equity=cash+(position['quantity']*b['close']*(1-fee) if position else 0)
        curve.append({'time':bar_end(b,'15m').isoformat(),'equity':equity})
    return {'symbol':symbol,'initial':initial,'final':cash,'trades':trades,'curve':curve,
            'signal_count':len(signals),'skipped':skipped}

def summary(trades, curve, initial):
    wins=sum(t['pnl']>0 for t in trades)
    losses=sum(t['pnl']<0 for t in trades)
    profit=sum(t['pnl'] for t in trades if t['pnl']>0)
    loss=-sum(t['pnl'] for t in trades if t['pnl']<0)
    peak=initial
    drawdown=0
    for point in curve:
        peak=max(peak,point['equity'])
        point['drawdown_pct']=(peak-point['equity'])/peak*100
        drawdown=max(drawdown,point['drawdown_pct'])
    final=curve[-1]['equity'] if curve else initial
    return {'trades':len(trades),'wins':wins,'losses':losses,'breakeven':len(trades)-wins-losses,
        'win_rate':wins/len(trades)*100 if trades else None,'net_pnl':final-initial,
        'expectancy_usd':(profit-loss)/len(trades) if trades else None,
        'early_stops':sum(t['early_stop'] for t in trades),
        'givebacks':sum(t['pnl']<0 and t['half_r_path']=='yes' for t in trades),
        'unknown_paths':sum(t['pnl']<0 and t['half_r_path']=='unknown' for t in trades),
        'return_pct':(final/initial-1)*100,'max_drawdown_pct':drawdown,'final_equity':final,
        'profit_factor':profit/loss if loss else None,'gross_profit':profit,'gross_loss':loss,
        'avg_trade_pct':sum(t['return_pct'] for t in trades)/len(trades) if trades else None,
        'fees':sum(t['entry_fee']+t['exit_fee'] for t in trades),
        'forced_exits':sum(t['reason']=='end_of_sample' for t in trades)}

def aggregate(results, params, timeline):
    initial=params['capital']
    sleeve=initial/len(params['symbols'])
    idle=initial-sleeve*len(results)
    by_time=[{p['time']:p['equity'] for p in r['curve']} for r in results]
    curve=[{'time':t,'equity':idle+sum(c[t] for c in by_time)} for t in timeline]
    trades=sorted([t for r in results for t in r['trades']],key=lambda t:t['entry_time'])
    metrics=summary(trades,curve,initial)
    per_symbol=[{'symbol':r['symbol'],'signals':r['signal_count'],'skipped':r['skipped'],
                 **summary(r['trades'],r['curve'],sleeve)} for r in results]
    return {'metrics':metrics,'curve':curve,'trades':trades,'per_symbol':per_symbol,
        'signals':sum(r['signal_count'] for r in results),'skipped':{k:sum(r['skipped'][k] for r in results) for k in ('busy','invalid_stop','size','end_of_sample')}}

class Backtests:
    def __init__(self, store, directory):
        self.store=store
        self.directory=Path(directory)
        self.directory.mkdir(parents=True,exist_ok=True)
        self.lock=threading.Lock()
        self.cancelled=threading.Event()
        self.thread=None
        self.active=None
        for job in store.backtests(100):
            if job['status'] in ('running','queued'):
                job.update(status='interrupted',message='后台已重启，请重新运行此回测')
                store.save_backtest(job)

    def start(self, params):
        with self.lock:
            if self.thread and self.thread.is_alive():
                raise ValueError('已有回测正在运行，请等待或取消')
            uid=now_utc().strftime('%Y%m%d%H%M%S')+'-'+uuid.uuid4().hex[:8]
            job={'id':uid,'status':'queued','message':'准备历史数据','progress':0,'created':now_utc().isoformat(),
                 'params':params,'results':{},'coverage':{},'errors':{},'rule_version':RULE_VERSION,'model_version':MODEL_VERSION}
            self.store.save_backtest(job)
            self.cancelled.clear()
            self.active=uid
            self.thread=threading.Thread(target=self.run,args=(job,),daemon=True,name='backtest-worker')
            self.thread.start()
            return job

    def close(self): self.cancelled.set()

    def history(self,provider,symbol,params):
        # Separate immutable daily cache; never overwrite the live engine's QFQ window.
        key=json.dumps([symbol,params['start'],params['end'],now_utc().astimezone(ET).date().isoformat(),'QFQ-RTH-start-v2'])
        path=self.directory/(hashlib.sha256(key.encode()).hexdigest()+'.json.gz')
        first=orb_warmup_start(params['start'])
        if path.exists():
            with gzip.open(path,'rt',encoding='utf-8') as f: frames=json.load(f)
            oldest=frames['15m'][0]['time'][:10]
            if oldest<=first: return frames,'cache'
            if not provider.ctx: provider.connect(params['port'])
            until=(date.fromisoformat(oldest)-timedelta(days=1)).isoformat()
            prefix=provider.history(symbol,'15m',start=first,end=until,cancelled=self.cancelled.is_set)
            frames['15m']=prefix+frames['15m']
        else:
            if not provider.ctx: provider.connect(params['port'])
            frames={}
            for tf,warmup in [('1D',400),('60m',90),('15m',14)]:
                begin=first if tf=='15m' else (date.fromisoformat(params['start'])-timedelta(days=warmup)).isoformat()
                frames[tf]=provider.history(symbol,tf,start=begin,end=params['end'],cancelled=self.cancelled.is_set)
                if not frames[tf]: raise ValueError(f'{tf} 没有历史数据')
        temporary=path.with_suffix('.tmp')
        with gzip.open(temporary,'wt',encoding='utf-8') as f: json.dump(frames,f,allow_nan=False)
        temporary.replace(path)
        return frames,'moomoo'

    def run(self,job):
        params=job['params']
        provider=MoomooProvider()
        results={kind:[] for kind in STRATEGIES}
        try:
            job['status']='running'
            timeline=[bar_end({'time':t},'15m').isoformat() for t in expected_times(params['start'],params['end'])]
            if not timeline: raise ValueError('所选范围没有交易日')
            for i,symbol in enumerate(params['symbols']):
                if self.cancelled.is_set(): raise InterruptedError('回测已取消')
                job.update(message=f'{symbol} · 获取历史数据 ({i+1}/{len(params["symbols"])})',progress=round(i/len(params['symbols'])*100))
                self.store.save_backtest(job)
                try:
                    frames,source=self.history(provider,symbol,params)
                    coverage=validate_coverage(frames,params['start'],params['end'])
                    job.update(message=f'{symbol} · 逐根计算信号与模拟成交')
                    self.store.save_backtest(job)
                    signals,evaluated=build_signals(frames,params['start'],params['end'],params['settings'],self.cancelled.is_set)
                    if evaluated==0: raise ValueError('预热历史不足，没有可评估的信号时点')
                    bars=[b for b in frames['15m'] if params['start']<=b['time'][:10]<=params['end']]
                    for kind in STRATEGIES:
                        results[kind].append(simulate(symbol,bars,signals[kind],params,params['capital']/len(params['symbols'])))
                    job['coverage'][symbol]={'frames':coverage,'source':source,'evaluated_bars':evaluated,
                        'first':bars[0]['time'],'last':bars[-1]['time']}
                except InterruptedError: raise
                except Exception as exc:
                    job['errors'][symbol]=str(exc)[:400]
                self.store.save_backtest(job)
            if self.cancelled.is_set(): raise InterruptedError('回测已取消')
            if not any(results.values()): raise ValueError('没有可回测的完整数据，请查看各标的错误')
            job['results']={kind:aggregate(values,params,timeline) for kind,values in results.items()}
            job.update(status='complete',progress=100,message='回测完成' if not job['errors'] else '部分标的完成；失败标的资金按现金保留',finished=now_utc().isoformat())
        except InterruptedError:
            job.update(status='cancelled',message='回测已取消；不发布部分计算的绩效')
        except Exception as exc:
            job.update(status='failed',message=str(exc)[:400])
        finally:
            try: provider.close()
            except Exception: pass
            self.store.save_backtest(job)
