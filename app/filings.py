"""Annual US GAAP observations from SEC companyfacts (USD, matching fiscal periods)."""
from datetime import date, datetime, timedelta
import httpx
from .technicals import card

CIKS={'AAPL':320193,'NVDA':1045810,'MSFT':789019,'TSLA':1318605,
      'AMD':2488,'AMZN':1018724,'META':1326801,'GOOGL':1652044,'GOOG':1652044}
HEADERS={'User-Agent':'TrendDesk personal research (local desktop)','Accept':'application/json'}
TAGS={'revenue':['RevenueFromContractWithCustomerExcludingAssessedTax','Revenues','SalesRevenueNet'],
      'profit':['NetIncomeLoss'],'cash':['NetCashProvidedByUsedInOperatingActivities']}


def annual_cards(data,today):
    gaap=data.get('facts',{}).get('us-gaap',{})
    values={}
    for metric,tags in TAGS.items():
        periods={}
        for tag in tags:
            rows=gaap.get(tag,{}).get('units',{}).get('USD',[])
            for row in rows:
                if row.get('form') not in ('10-K','10-K/A') or not row.get('start') or row['filed']>today: continue
                duration=(date.fromisoformat(row['end'])-date.fromisoformat(row['start'])).days
                if not 350<=duration<=380 or row['end']>today: continue
                period=(row['start'],row['end'])
                if period not in periods or row['filed']>periods[period]['filed']:
                    periods[period]=row
        values[metric]=periods
    if not values['revenue']: return {}
    periods=sorted(values['revenue'],key=lambda p:p[1])
    latest=periods[-1]
    row=values['revenue'][latest]
    revenue=row['val']
    def basis(entry):
        return f"财年 {entry['start']} 至 {entry['end']}，10-K 披露 {entry['filed']} · SEC EDGAR。"
    cards={'revenue':card('年度营收',f'{revenue/1e9:,.2f} 十亿美元',basis(row))}
    if len(periods)>1:
        prev=values['revenue'][periods[-2]]
        if prev['val']>0 and 350<=(date.fromisoformat(row['end'])-date.fromisoformat(prev['end'])).days<=380:
            cards['growth']=card('年度营收同比',f"{(revenue/prev['val']-1)*100:+.2f}%",basis(row),f"上一财年营收 {prev['val']/1e9:,.2f} 十亿美元。")
    profit=values['profit'].get(latest)
    if profit and revenue>0:
        cards['margin']=card('年度净利率',f"{profit['val']/revenue*100:.2f}%",basis(profit),'使用同一财年的净利润 / 营收。')
    cash=values['cash'].get(latest)
    if cash:
        cards['cashflow']=card('经营现金流',f"{cash['val']/1e9:,.2f} 十亿美元",basis(cash))
    for key,item in cards.items():
        source={'margin':profit,'cashflow':cash}.get(key,row)
        if source.get('accn') and data.get('cik'):
            accn=source['accn']
            item['url']=f"https://www.sec.gov/Archives/edgar/data/{int(data['cik'])}/{accn.replace('-','')}/{accn}-index.htm"
    return cards


def financials(store,code,now):
    if code in ('SPY','QQQ'): return {},None
    key='sec_financials_v2_'+code
    cached=store.get(key,{})
    if cached and datetime.fromisoformat(cached['next'])>now:
        return cached['cards'],cached.get('note')
    cards=cached.get('cards',{})
    try:
        cik=CIKS.get(code)
        if not cik:
            tickers=store.get('sec_ticker_lookup',{})
            if not tickers or datetime.fromisoformat(tickers['expires'])<=now:
                response=httpx.get('https://www.sec.gov/files/company_tickers.json',headers=HEADERS,timeout=5)
                response.raise_for_status()
                tickers={'items':{r['ticker']:r['cik_str'] for r in response.json().values()},'expires':(now+timedelta(days=7)).isoformat()}
                store.set('sec_ticker_lookup',tickers)
            cik=tickers['items'][code.replace('.','-')]
        response=httpx.get(f'https://data.sec.gov/api/xbrl/companyfacts/CIK{int(cik):010d}.json',headers=HEADERS,timeout=8)
        response.raise_for_status()
        cards=annual_cards(response.json(),now.date().isoformat())
        note=None if cards else '暂无可比的美元 US GAAP 年报'
        delay=timedelta(hours=12)
    except (httpx.HTTPError,ValueError,KeyError,TypeError):
        note='SEC 暂未提供可用年报'+('，显示已缓存财年' if cards else '')
        delay=timedelta(minutes=15)
    store.set(key,{'cards':cards,'note':note,'next':(now+delay).isoformat()})
    return cards,note
