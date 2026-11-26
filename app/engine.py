import logging
import queue
import threading
import time
from datetime import timedelta
from .analysis import analyze
from .technicals import geometry
from .market import now_utc, ET, market_status, parse_time, bar_end, completed, expected_last_close
from .timeframes import SOURCES, derive
from .provider import MoomooProvider, normalize_bars, TIMEFRAMES
from .notifications import notify

log = logging.getLogger(__name__)

class Engine:
    def __init__(self, store):
        self.store = store
        self.provider = MoomooProvider()
        self.lock = threading.RLock()
        self.stop = threading.Event()
        self.reconnect = threading.Event()
        self.connected = False
        self.message = '正在连接本机 OpenD…'
        self.quota = None
        self.quotes = {}
        self.errors = {}
        self.loaded = {}
        self.retry = {}
        self.thread = None
        self.analyses = {}
        self.last_eval = 0
        self.last_sync = {}
        self.history_thread = None
        self.history_errors = {}

    def start(self):
        self.thread = threading.Thread(target=self.run, daemon=True, name='market-worker')
        self.thread.start()
        self.history_thread = threading.Thread(target=self.sync_research_history, daemon=True, name='research-history')
        self.history_thread.start()

    def close(self):
        self.stop.set()
        if self.thread: self.thread.join(timeout=3)
        if self.history_thread: self.history_thread.join(timeout=3)

    def sync_research_history(self):
        # These two histories are independent of the subscriptions that drive trade alerts.
        ready, retry = {}, {}
        while not self.stop.is_set():
            now = now_utc()
            port = self.store.settings()['port']
            versions = {'5m':expected_last_close('5m',now), '1M':expected_last_close('1D',now)}
            client = MoomooProvider()
            try:
                for code in self.symbols():
                    for tf, version in versions.items():
                        if self.stop.is_set(): return
                        key = (port,code,tf)
                        if not self.connected or ready.get(key)==version or time.monotonic()<retry.get(key,0):
                            continue
                        try:
                            if not client.ctx: client.connect(port)
                            end = expected_last_close(tf,now).astimezone(ET).date()
                            start = end-timedelta(days=7305 if tf=='1M' else 14)
                            bars = client.history(code,tf,start=start.isoformat(),end=end.isoformat(),cancelled=self.stop.is_set)
                            bars = completed(bars,tf,now)
                            if not bars: raise ValueError('暂无已收盘行情')
                            self.store.put_bars(code,tf,bars,replace=True)
                            if bar_end(bars[-1],tf)<expected_last_close(tf,now):
                                raise ValueError('最新已收盘行情尚未到达')
                            ready[key] = version
                            self.history_errors.pop((code,tf),None)
                        except Exception as exc:
                            self.history_errors[code,tf] = str(exc)[:180]
                            retry[key] = time.monotonic()+60
            finally:
                client.close()
            self.stop.wait(8)

    def symbols(self):
        return list(dict.fromkeys(['SPY','QQQ']+self.store.watchlist()+list(self.store.positions())))

    def run(self):
        health_at = 0
        while not self.stop.is_set():
            try:
                if self.reconnect.is_set():
                    self.provider.close()
                    self.connected = False
                    self.loaded.clear()
                    self.quotes.clear()
                    self.retry.clear()
                    self.reconnect.clear()
                if not self.connected:
                    self.provider.connect(self.store.settings()['port'])
                    self.connected = True
                    self.message = '已连接 moomoo · 正在同步历史行情'
                    self.loaded.clear()
                    self.retry.clear()
                now = now_utc()
                session_day = now.astimezone(ET).date().isoformat()
                if time.monotonic() - health_at > 15:
                    self.provider.health()
                    self.quota = self.provider.quota()
                    health_at = time.monotonic()
                wanted = self.symbols()
                for symbol in self.provider.subscribed - set(wanted):
                    self.provider.unsubscribe(symbol)
                pending = [s for s in wanted if self.loaded.get(s) != session_day and time.monotonic() >= self.retry.get(s,0)]
                if pending:
                    symbol = pending[0]
                    self.message = f'正在同步 {symbol} 的历史 K 线…'
                    try:
                        self.provider.subscribe(symbol)
                        frames = {tf:self.provider.history(symbol,tf) for tf in TIMEFRAMES}
                        if any(not bars for bars in frames.values()):
                            raise RuntimeError('该代码没有足够的美股 K 线数据')
                        with self.lock:
                            for tf, bars in frames.items():
                                self.store.put_bars(symbol,tf,bars,replace=True)
                            self.loaded[symbol] = session_day
                            self.last_sync[symbol] = time.monotonic()
                            self.errors.pop(symbol,None)
                    except Exception as exc:
                        self.errors[symbol] = str(exc)[:300]
                        self.retry[symbol] = time.monotonic()+120
                self.drain()
                if self.provider.overflow:
                    raise RuntimeError('推送积压，正在重连并补齐行情')
                if not pending:
                    self.message = '行情服务已连接 · 仅监控常规交易时段'
                if time.monotonic()-self.last_eval > 3:
                    self.evaluate()
                    self.last_eval = time.monotonic()
                self.stop.wait(.5)
            except Exception as exc:
                self.connected = False
                self.message = ('OpenD 未连接：请启动并登录 Moomoo OpenD，确认端口 ' + str(self.store.settings()['port'])) if isinstance(exc, OSError) else str(exc)[:300]
                try: self.provider.close()
                except Exception: pass
                self.quotes.clear()
                self.loaded.clear()
                self.evaluate()
                self.stop.wait(5)
        self.provider.close()

    def drain(self):
        for _ in range(2000):
            try: kind, records = self.provider.messages.get_nowait()
            except queue.Empty: break
            with self.lock:
                for record in records:
                    symbol = record['code'].removeprefix('US.')
                    if kind == 'bars':
                        tf = next((k for k,v in TIMEFRAMES.items() if v == record['k_type']),None)
                        if tf and symbol in self.loaded:
                            self.store.put_bars(symbol,tf,normalize_bars([record],tf))
                    else:
                        try:
                            stamp = parse_time(str(record['data_date'])+' '+str(record['data_time']))
                            price = float(record['last_price'])
                            prev = float(record.get('prev_close_price') or 0)
                            if price <= 0: continue
                            self.quotes[symbol] = {'price':price, 'time':stamp.isoformat(), 'name':record.get('name',symbol),
                                                   'change':(price/prev-1)*100 if prev > 0 else None}
                        except (ValueError,TypeError): pass

    def get_bars(self, symbol):
        return {tf:self.store.bars(symbol,tf) for tf in TIMEFRAMES}

    def quote_fresh(self, quote, now):
        if not quote: return False
        age = (now-parse_time(quote['time'])).total_seconds()
        return -5 <= age <= 120

    def emit(self, symbol, signal, price, stamp, analysis, dedupe):
        created = self.store.event(symbol,signal,price,stamp,analysis,dedupe)
        if created and self.store.settings()['notifications']:
            try: notify(symbol+' · '+signal['title'],signal['detail'])
            except Exception: log.exception('Desktop notification failed')

    def evaluate(self):
        now = now_utc()
        market = market_status(now)
        benchmark = self.store.bars('SPY','1D')
        positions = self.store.positions()
        settings = self.store.settings()
        with self.lock:
            for symbol in self.symbols():
                analysis = analyze(self.get_bars(symbol),benchmark,now,settings)
                self.analyses[symbol] = analysis
                if self.connected and symbol in self.loaded and not analysis['fresh'] and time.monotonic()-self.last_sync.get(symbol,0)>90:
                    self.loaded.pop(symbol,None)
                quote = self.quotes.get(symbol)
                active = self.connected and (market['open'] or market['close_confirmation']) and self.quote_fresh(quote,now)
                if not active:
                    continue
                if symbol in self.loaded and analysis['ready'] and analysis['fresh']:
                    # No retrospective alerts on reconnect: only a candle closed in the last 2 minutes.
                    recent = self.store.bars(symbol,'15m')
                    candidate = next((b for b in reversed(recent) if b['time']==analysis['bar_time']),None)
                    timely = candidate and 0 <= (now-bar_end(candidate,'15m')).total_seconds() <= 120
                    kinds = {s['kind'] for s in analysis['signals']}
                    for kind in ('near','breakout','pullback'):
                        key = f'{symbol}:entry:{kind}'
                        if kind not in kinds:
                            self.store.event(symbol,{},0,'',{},key,reset=True)
                        elif timely and self.store.latch(key) is None:
                            signal = next(s for s in analysis['signals'] if s['kind']==kind)
                            self.emit(symbol,signal,analysis['close'],'active',analysis,key)
                pos = positions.get(symbol)
                if pos:
                    for kind, level, reached in [('stop',pos.get('stop'),lambda p,x:p<=x),('target',pos.get('target'),lambda p,x:p>=x)]:
                        if level and reached(quote['price'],level):
                            signal = {'kind':kind,'title':'保护价触发' if kind=='stop' else '目标价到达',
                                      'detail':f'最新报价 {quote["price"]:.2f}，计划价位 {level:.2f}；请检查持仓'}
                            self.emit(symbol,signal,quote['price'],'active',{'quote_time':quote['time'],'position':pos},f'{symbol}:risk:{kind}')

    def state(self, selected=None, tf='1D'):
        now = now_utc()
        positions = self.store.positions()
        with self.lock:
            items = []
            for symbol in self.symbols():
                analysis = self.analyses.get(symbol) or analyze(self.get_bars(symbol),now=now)
                quote = self.quotes.get(symbol)
                daily = self.store.bars(symbol,'1D')
                price = quote['price'] if quote else daily[-1]['close'] if daily else None
                items.append({'symbol':symbol,'name':quote.get('name',symbol) if quote else symbol,
                              'price':price,'change':quote.get('change') if quote else None,
                              'quote_time':quote.get('time') if quote else None,
                              'quote_fresh':self.connected and self.quote_fresh(quote,now),
                              'source':'moomoo' if quote else 'cache' if daily else 'none',
                              'analysis':analysis,'position':positions.get(symbol),'error':self.errors.get(symbol),
                              'synced':self.loaded.get(symbol)==now.astimezone(ET).date().isoformat(),
                              'bar_times':{period:(series[-1]['time'] if (series:=self.store.bars(symbol,period)) else None) for period in TIMEFRAMES}})
            selected = selected or (self.store.watchlist() or ['SPY'])[0]
            source = SOURCES.get(tf,tf)
            bars = self.store.bars(selected,source)
            chart = (derive(tf,completed(bars,source,now)) if tf in SOURCES else bars)[-240:]
            for bar in chart:
                end = bar_end(bar,tf)
                bar['complete'] = bool(end and end.timestamp()+3 <= now.timestamp())
            _,lines=geometry([bar for bar in chart if bar['complete']])
            return {'mode':'live','now':now.isoformat(),'market':market_status(now),'connected':self.connected,'structure_lines':lines,
                    'message':self.message,'quota':self.quota,'settings':self.store.settings(),
                    'watchlist':self.store.watchlist(),'items':items,'events':self.store.events(),
                    'selected':selected,'timeframe':tf,'chart':chart,'chart_error':self.history_errors.get((selected,tf))}
