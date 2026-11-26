"""Read-only OpenD adapter. Imports no trade context and never unlocks trading."""
import math
import queue
import socket
import time
from datetime import timedelta
from .market import now_utc, ET, parse_time, bounds, MINUTES, month_end

TIMEFRAMES = {'1D':'K_DAY', '60m':'K_60M', '15m':'K_15M'}

def normalize_bars(records, timeframe='1D'):
    output = []
    for r in records:
        try:
            bar = {key:float(r[key]) for key in ('open','high','low','close','volume')}
            if not all(math.isfinite(v) for v in bar.values()) or min(bar[k] for k in ('open','high','low','close')) <= 0 or bar['volume'] < 0:
                continue
            if bar['high'] < max(bar['open'],bar['close'],bar['low']) or bar['low'] > min(bar['open'],bar['close']):
                continue
            stamp = parse_time(r['time_key'])
            # OpenD minute time_key is the bar END, including the short final hour.
            # Internally every intraday bar uses the START of the exchange-aligned bin.
            if timeframe == '1M':
                last = month_end(stamp.year,stamp.month)
                stamp = stamp.replace(day=last.day)
            elif timeframe != '1D':
                session = bounds(stamp.astimezone(ET).date().isoformat())
                if not session or not session[0] < stamp <= session[1]:
                    continue
                minutes = MINUTES[timeframe]
                seconds = (stamp-session[0]).total_seconds()
                slot = max(0,int((seconds-1)//(minutes*60)))
                stamp = (session[0]+timedelta(minutes=slot*minutes)).astimezone(ET)
            bar['time'] = stamp.isoformat()
            output.append(bar)
        except (KeyError, TypeError, ValueError):
            continue
    return output

class MoomooProvider:
    def __init__(self):
        self.ctx = None
        self.messages = queue.Queue(maxsize=10000)
        self.subscribed = set()
        self.subscription_time = {}
        self.remove_attempt = {}
        self.last_request = 0
        self.overflow = False

    def emit(self, message):
        try:
            self.messages.put_nowait(message)
        except queue.Full:
            self.overflow = True

    def connect(self, port):
        # Fast failure before constructing the SDK's automatically reconnecting context.
        with socket.create_connection(('127.0.0.1',port), timeout=1.5):
            pass
        import moomoo as mm
        self.mm = mm
        mm.SysConfig.set_all_thread_daemon(True)
        mm.SysConfig.set_client_info('TrendDeskReadOnly', 100)
        owner = self
        class Quotes(mm.StockQuoteHandlerBase):
            def on_recv_rsp(self, rsp_pb):
                ret, frame = super().on_recv_rsp(rsp_pb)
                if ret == mm.RET_OK:
                    owner.emit(('quote',frame.to_dict('records')))
                return ret, frame
        class Candles(mm.CurKlineHandlerBase):
            def on_recv_rsp(self, rsp_pb):
                ret, frame = super().on_recv_rsp(rsp_pb)
                if ret == mm.RET_OK:
                    # Subscribe defaults to QFQ; reject any differently adjusted push.
                    if getattr(rsp_pb.s2c, 'rehabType', 1) == 1:
                        owner.emit(('bars',frame.to_dict('records')))
                return ret, frame
        self.ctx = mm.OpenQuoteContext(host='127.0.0.1',port=port)
        self.ctx.set_handler(Quotes())
        self.ctx.set_handler(Candles())
        return self.health()

    def health(self):
        ret, data = self.ctx.get_global_state()
        if ret != self.mm.RET_OK or not data.get('qot_logined'):
            raise RuntimeError('OpenD 已连接，但行情服务未登录')
        return {'version':data.get('server_ver'), 'market':data.get('market_us')}

    def subscribe(self, symbol):
        if symbol in self.subscribed:
            return
        mm = self.mm
        ret, data = self.ctx.subscribe(['US.'+symbol], [mm.SubType.QUOTE,mm.SubType.K_DAY,mm.SubType.K_60M,mm.SubType.K_15M], session=mm.Session.RTH)
        if ret != mm.RET_OK:
            raise RuntimeError(str(data)[:300])
        self.subscribed.add(symbol)
        self.subscription_time[symbol] = time.monotonic()

    def unsubscribe(self, symbol):
        now=time.monotonic()
        if now-self.subscription_time.get(symbol,0)<65 or now-self.remove_attempt.get(symbol,0)<15:
            return
        self.remove_attempt[symbol]=now
        mm = self.mm
        ret, _ = self.ctx.unsubscribe(['US.'+symbol], [mm.SubType.QUOTE,mm.SubType.K_DAY,mm.SubType.K_60M,mm.SubType.K_15M])
        if ret == mm.RET_OK:
            self.subscribed.discard(symbol)

    def history(self, symbol, tf, start=None, end=None, cancelled=None):
        mm = self.mm
        start = start or (now_utc().astimezone(ET)-timedelta(days={'1D':500,'60m':170,'15m':35}[tf])).date().isoformat()
        end = end or now_utc().astimezone(ET).date().isoformat()
        result, page = [], None
        for _ in range(20):
            if cancelled and cancelled():
                raise InterruptedError('回测已取消')
            time.sleep(max(0,.6-(time.monotonic()-self.last_request)))
            self.last_request = time.monotonic()
            ktype = (TIMEFRAMES | {'1m':'K_1M','5m':'K_5M','1M':'K_MON'})[tf]
            ret, data, page = self.ctx.request_history_kline('US.'+symbol,start=start,end=end,ktype=getattr(mm.KLType,ktype),
                    autype=mm.AuType.QFQ,max_count=1000,page_req_key=page,session=mm.Session.RTH)
            if ret != mm.RET_OK:
                raise RuntimeError(str(data)[:300])
            result.extend(normalize_bars(data.to_dict('records'),tf))
            if page is None:
                return result
        raise RuntimeError('历史分页超过上限，未将不完整数据用于分析')

    def quota(self):
        ret, data = self.ctx.get_history_kl_quota()
        if ret == self.mm.RET_OK:
            return {'used':int(data[0]),'remaining':int(data[1]),'subscriptions':len(self.subscribed)*4}
        return None

    def close(self):
        if self.ctx:
            self.ctx.close()
        self.ctx = None
        self.subscribed.clear()
        self.subscription_time.clear()
        self.remove_attempt.clear()
        while not self.messages.empty():
            try: self.messages.get_nowait()
            except queue.Empty: break
        self.overflow = False
