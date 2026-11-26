from contextlib import asynccontextmanager
import csv
import io
import os
import re
from pathlib import Path
from typing import Literal
from datetime import date, timedelta
from urllib.parse import urlsplit
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from starlette.middleware.trustedhost import TrustedHostMiddleware
from pydantic import BaseModel, Field, ConfigDict, model_validator
from .store import Store
from .macro import BUBBLE, Macro, analysis_context
from .market_studies import StudyFeed, TIME_LABELS
from .study_journal import StudyJournal,HORIZONS,KINDS
from .engine import Engine
from . import demo
from .advisor import Advisor, AIConfig, ProfileName, snapshot
from . import __version__
from .backtest import Backtests, STRATEGIES
from .market import expected_last_close, now_utc, ET

ROOT = Path(__file__).resolve().parent.parent
DATA = Path(os.environ.get('TRENDDESK_DATA_DIR') or ROOT/'data')

def symbol(value):
    value = value.upper().strip().removeprefix('US.')
    if value.split('.')[0] in ('HK','SH','SZ','SG','JP','MY','CA','AU') and '.' in value:
        raise HTTPException(422,'本工具只支持美股和美股 ETF')
    if not re.fullmatch(r'[A-Z][A-Z0-9.\-]{0,11}',value):
        raise HTTPException(422,'请输入美股代码，例如 AAPL 或 US.NVDA')
    return value

class WatchInput(BaseModel):
    symbol: str

class NewsInput(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True,extra='forbid')
    text: str = Field(min_length=1,max_length=1200)

class SettingsInput(BaseModel):
    model_config = ConfigDict(extra='forbid',allow_inf_nan=False)
    port: int = Field(default=11111,ge=1024,le=65535)
    notifications: bool = False
    volume_multiple: float = Field(default=1.5,ge=1,le=5)
    near_percent: float = Field(default=.5,ge=.1,le=3)

class PositionInput(BaseModel):
    model_config = ConfigDict(extra='forbid',allow_inf_nan=False)
    quantity: float = Field(gt=0,le=100000000)
    cost: float = Field(gt=0,le=10000000)
    stop: float | None = Field(default=None,gt=0,le=10000000)
    target: float | None = Field(default=None,gt=0,le=10000000)

    @model_validator(mode='after')
    def ordered(self):
        if self.stop and self.target and self.stop >= self.target:
            raise ValueError('保护价必须低于目标价')
        return self

class BacktestInput(BaseModel):
    model_config = ConfigDict(extra='forbid',allow_inf_nan=False)
    symbols: list[str] = Field(min_length=1,max_length=20)
    start: date
    end: date
    capital: float = Field(default=100000,ge=100,le=100000000)
    fee_bps: float = Field(default=2.5,ge=0,le=100)
    slippage_bps: float = Field(default=5,ge=0,le=100)
    risk_percent: float = Field(default=1,gt=0,le=5)
    target_r: float = Field(default=2,ge=.5,le=10)
    max_bars: int = Field(default=130,ge=1,le=2600)

    @model_validator(mode='after')
    def valid_range(self):
        latest=expected_last_close('1D',now_utc()).astimezone(ET).date()
        if self.start>self.end or (self.end-self.start).days>365 or self.start<date(2010,1,1) or self.end>latest:
            raise ValueError(f'日期须在 2010 年以后、跨度不超过 365 天，结束日最晚 {latest}')
        self.symbols=list(dict.fromkeys(symbol(s) for s in self.symbols))
        return self

def create_app(store=None, run_worker=True):
    store = store or Store(DATA/'trenddesk.db')
    engine = Engine(store)
    studies = StudyFeed(engine)
    journal = StudyJournal(engine,studies)
    advisor = Advisor(store)
    macro = Macro(store)
    backtests = Backtests(store,DATA/'backtests')
    @asynccontextmanager
    async def lifespan(app):
        if run_worker:
            engine.start()
            journal.start()
        try:
            yield
        finally:
            journal.close()
            engine.close()
            backtests.close()
    app = FastAPI(title='TrendDesk Local',lifespan=lifespan,docs_url=None,redoc_url=None)
    app.state.engine = engine
    app.state.backtests = backtests
    app.add_middleware(TrustedHostMiddleware,allowed_hosts=['127.0.0.1','localhost']+([] if run_worker else ['testserver']))

    @app.middleware('http')
    async def local_requests(request: Request, call_next):
        origin = request.headers.get('origin')
        if origin and (urlsplit(origin).netloc != request.headers.get('host') or urlsplit(origin).scheme != 'http'):
            return JSONResponse({'detail':'仅允许本地同源请求'},status_code=403)
        if request.method in ('POST','PUT','DELETE','PATCH') and request.headers.get('x-trenddesk') != 'local':
            return JSONResponse({'detail':'缺少本地客户端标识'},status_code=403)
        response=await call_next(request)
        response.headers['X-Content-Type-Options']='nosniff'
        response.headers['X-Frame-Options']='DENY'
        response.headers['Content-Security-Policy']="default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data:; connect-src 'self'; frame-src https://feed.financialjuice.com/widgets/headlines.aspx; frame-ancestors 'none'"
        if request.url.path.startswith('/api'):
            response.headers['Cache-Control']='no-store'
        return response

    @app.get('/')
    def index(): return FileResponse(ROOT/'web'/'index.html')

    @app.get('/api/health')
    def health(): return {'app':'trenddesk','version':__version__,'pid':os.getpid()}

    @app.get('/api/backtests')
    def backtest_list():
        end=expected_last_close('1D',now_utc()).astimezone(ET).date()
        jobs=[{k:v for k,v in j.items() if k not in ('results','coverage')} for j in store.backtests(20)]
        return {'jobs':jobs,'defaults':{'symbols':store.watchlist()[:20],'start':str(end-timedelta(days=180)),
            'end':str(end),'capital':100000,'fee_bps':2.5,'slippage_bps':5,'risk_percent':1,'target_r':2,'max_bars':130}}

    @app.get('/api/ai/config')
    def ai_config():
        return advisor.status()

    @app.get('/api/macro')
    def macro_environment():
        return macro.read()

    @app.post('/api/macro/refresh')
    def macro_refresh():
        return macro.read(refresh=True)

    @app.post('/api/macro/analysis')
    def macro_analysis(profile: ProfileName = 'routine', focus: Literal['all','bubble']='all'):
        if not advisor.status()['configured']:
            raise HTTPException(409, '请先在「AI 接入」中保存 API Key')
        context = analysis_context(macro.read())
        if focus=='bubble':
            index=next((m for m in context['indicators'] if m.get('code')==BUBBLE),None)
            if not index: raise HTTPException(409,'暂无新鲜的 AI 泡沫指数，请刷新宏观数据')
            context={'focus':'bubble','as_of':context['as_of'],'indicators':[index],'headlines':[]}
        if not context['indicators'] and not context['headlines']:
            raise HTTPException(409, '暂无可用的宏观指标或新闻，请先刷新数据')
        return advisor.advise(context, profile, scope='macro')

    @app.post('/api/news/analysis')
    def news_analysis(value: NewsInput, profile: ProfileName = 'routine'):
        return advisor.advise({'excerpt':value.text}, profile, scope='news')

    @app.get('/api/studies/{code}')
    def stock_studies(code: str, tf: str='1D', section: str='all'):
        code=symbol(code)
        if tf not in TIME_LABELS: raise HTTPException(422,'不支持的研究周期')
        if code not in engine.symbols(): raise HTTPException(404,'请先将股票加入自选')
        if section not in ('all','structure','intraday','fundamental','longterm'): raise HTTPException(422,'未知研究栏目')
        return studies.read(code,tf,section)

    @app.get('/api/study-journal')
    def study_journal(code: str='', tf: str='', horizon: int=5, kind: str=''):
        if tf not in ('','1m',*TIME_LABELS) or horizon not in HORIZONS or (kind and kind not in KINDS):
            raise HTTPException(422,'不支持的复盘筛选条件')
        return journal.report(symbol(code) if code else '',tf,horizon,kind)

    @app.post('/api/studies/{code}/analysis')
    def study_analysis(code: str, section: str, focus: str='all', tf: str='1D', profile: ProfileName='routine', as_of: str=''):
        if not advisor.status()['configured']: raise HTTPException(409,'请先在 AI 接入中保存 Key')
        data=stock_studies(code,tf,section)
        items=data['sections'].get(section)
        if not items or not data['times'][section]: raise HTTPException(409,'该板块暂无可解读数据')
        if section=='intraday' and focus.startswith('platform_') and focus not in items:
            for event in data.get('intraday_overlay',{}).get('events',[]):
                if event['id']==focus:
                    items={focus:event}
                    break
        if focus!='all' and focus not in items: raise HTTPException(422,'指标已变化，请刷新')
        stamp=data['times'][section]
        if as_of and stamp!=as_of: raise HTTPException(409,'源数据已更新，请刷新研究面板后解读')
        period={'structure':TIME_LABELS[tf],'intraday':'常规时段 1 分钟','fundamental':'行情估值快照','longterm':'日线'}[section]
        context={'symbol':data['symbol'],'section':section,'focus':focus,'period':period,'as_of':stamp,
            'evidence':items if focus=='all' else {focus:items[focus]},'source_status':data['errors'].get(section)}
        if section=='intraday':
            context.update(expected_minute=data['expected_minute'],missing_minutes=data['minute_gaps'])
            if focus in items and items[focus].get('at'):
                context['as_of']=items[focus]['at']
        if section=='longterm':
            context.update(expected_daily=data['expected_daily'])
            if focus in ('timing','all'):
                fund=studies.read(data['symbol'],tf,'fundamental')
                context.update(fundamentals=fund['sections']['fundamental'],fundamental_as_of=fund['times']['fundamental'],
                               financial_source_status=fund['errors'].get('fundamental'))
        return advisor.advise(context,profile,scope='study')

    @app.post('/api/ai/models')
    def ai_models():
        return advisor.models()

    @app.get('/api/ai/usage')
    def ai_usage():
        return advisor.usage

    @app.put('/api/ai/config')
    def ai_configure(value: AIConfig):
        return advisor.configure(value)

    @app.post('/api/ai/advice/{code}')
    def ai_advice(code: str, profile: ProfileName = 'routine'):
        if not advisor.status()['configured']:
            raise HTTPException(409,'请先配置 OpenAI API Key')
        code = symbol(code)
        if profile == 'deep':
            environment = macro.read()
            market = snapshot(engine, code)
            market['macro'] = analysis_context(environment)
            research=studies.read(code,'1D')
            market['studies']={k:research[k] for k in ('times','sections','errors','minute_gaps','expected_minute','expected_daily')}
        else:
            market = snapshot(engine, code)
        return advisor.advise(market, profile)

    @app.post('/api/ai/condition/{code}')
    def condition_analysis(code: str, label: str, group: str, as_of: str, profile: ProfileName='routine'):
        if not advisor.status()['configured']: raise HTTPException(409,'请先保存 AI Key')
        market=snapshot(engine,symbol(code))
        if market['bar_close_time']!=as_of: raise HTTPException(409,'条件数据已更新，请重试')
        item=next((c for c in market['conditions'] if c['label']==label and c['group']==group),None)
        if not item: raise HTTPException(422,'没有找到该项条件')
        return advisor.advise({'symbol':market['symbol'],'period':'15 分钟信号及其上级周期条件','as_of':as_of,
            'section':group,'focus':label,'session':market['session'],'evidence':item},profile,scope='study')

    @app.post('/api/backtests',status_code=202)
    def backtest_start(value: BacktestInput):
        params=value.model_dump(mode='json')|{'settings':store.settings(),'port':store.settings()['port']}
        try: return backtests.start(params)
        except ValueError as exc: raise HTTPException(409,str(exc))

    @app.get('/api/backtests/{job_id}')
    def backtest_get(job_id: str):
        job=store.backtest(job_id)
        if not job: raise HTTPException(404,'未找到回测')
        return job

    @app.post('/api/backtests/{job_id}/cancel')
    def backtest_cancel(job_id: str):
        job=backtest_get(job_id)
        if job['status'] in ('queued','running') and backtests.active==job_id: backtests.cancelled.set()
        return {'ok':True}

    @app.get('/api/backtests/{job_id}/export')
    def backtest_export(job_id: str):
        job=backtest_get(job_id)
        buffer=io.StringIO()
        writer=csv.writer(buffer)
        writer.writerow(['策略','股票','信号时间','入场时间','退出K线结束时间','入场价','退出价','数量','净盈亏USD','交易收益%','手续费USD','退出原因','前两根止损','持仓曾达+0.5R'])
        for kind,result in job['results'].items():
            for t in result['trades']:
                writer.writerow([STRATEGIES[kind],t['symbol'],t['signal_time'],t['entry_time'],t['exit_time'],t['entry_price'],t['exit_price'],t['quantity'],t['pnl'],t['return_pct'],t['entry_fee']+t['exit_fee'],t['reason'],t.get('early_stop',''),t.get('half_r_path','')])
        return Response('\ufeff'+buffer.getvalue(),media_type='text/csv; charset=utf-8',headers={'Content-Disposition':'attachment; filename="trenddesk-backtest.csv"'})

    @app.get('/api/state')
    def state(selected: str='NVDA',timeframe: str='1D',mode: str='live'):
        selected=symbol(selected)
        if timeframe not in TIME_LABELS or mode not in ('live','demo'):
            raise HTTPException(422,'不支持的周期或模式')
        return demo.state(selected,timeframe,store.settings()) if mode=='demo' else engine.state(selected,timeframe)

    @app.post('/api/watchlist')
    def add_watch(value: WatchInput):
        s=symbol(value.symbol)
        if len(store.watchlist())>=50 and s not in store.watchlist():
            raise HTTPException(400,'第一版最多监控 50 只自选股')
        store.add(s)
        return {'symbol':s}

    @app.delete('/api/watchlist/{code}')
    def remove_watch(code: str):
        s=symbol(code)
        if s in store.positions():
            raise HTTPException(400,'该股票仍有持仓计划，请先移除持仓记录再移出自选')
        store.remove(s)
        return {'ok':True}

    @app.put('/api/settings')
    def settings(value: SettingsInput):
        old=store.settings()
        store.set('settings',value.model_dump())
        if old['port']!=value.port: engine.reconnect.set()
        return value

    @app.post('/api/reconnect')
    def reconnect():
        engine.reconnect.set()
        return {'ok':True}

    @app.put('/api/positions/{code}')
    def position(code: str,value: PositionInput):
        s=symbol(code)
        if s not in store.watchlist() and s not in ('SPY','QQQ'):
            raise HTTPException(400,'请先把该股票加入自选')
        store.position(s,value.model_dump())
        return {'ok':True}

    @app.delete('/api/positions/{code}')
    def remove_position(code: str):
        store.position(symbol(code),None)
        return {'ok':True}

    @app.post('/api/events/ack')
    def acknowledge():
        store.acknowledge()
        return {'ok':True}

    @app.get('/api/events/export')
    def export():
        buffer=io.StringIO()
        writer=csv.writer(buffer)
        writer.writerow(['时间 UTC','股票','类型','原因','触发价','K线时间'])
        for e in store.events(10000):
            values=[e['created'],e['symbol'],e['title'],e['detail'],e['price'],e['bar_time']]
            writer.writerow(["'"+v if isinstance(v,str) and v.startswith(('=','+','-','@')) else v for v in values])
        return Response('\ufeff'+buffer.getvalue(),media_type='text/csv; charset=utf-8',headers={'Content-Disposition':'attachment; filename="trenddesk-signals.csv"'})

    app.mount('/static',StaticFiles(directory=ROOT/'web'),name='static')
    return app

app = create_app()
