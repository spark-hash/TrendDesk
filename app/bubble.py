"""Interpret the publisher's dated AIBI 2.0 snapshot without reweighting the score."""
from datetime import date
from math import isfinite

BANDS = {'Low':'低位','Normal':'正常','Elevated':'偏高','High':'高位','Extreme':'极高'}
AXES = {
    'euphoria': ('市场热度','估值、价格和仓位共同反映追涨程度。'),
    'fragility': ('脆弱性','观察资本开支和杠杆是否使市场更容易受到冲击。'),
    'demand': ('需求缺口','用开发工具下载增速代理需求。高分表示需求支撑偏弱。'),
    'core': ('长期核心','仅用互联网泡沫前已有的指标，与更长的市场历史比较。'),
}
PILLARS = {
    'valuation': ('估值与集中度','估值倍数和市值集中度是否处于历史高位？'),
    'dynamics': ('价格动量','AI 股票是否持续跑赢大盘，价格上涨是否加速？'),
    'capex': ('资本开支压力','云厂商为扩建基础设施动用了多少经营现金流？'),
    'credit': ('信用与融资','企业借款利差和融资压力是否上升？'),
    'leverage': ('杠杆与仓位','投资者是否大量借钱买股，科技股仓位是否拥挤？'),
    'demand': ('需求验证','开发工具的使用增速能否为投入扩张提供佐证？'),
    'narrative': ('舆论关注度','AI 在公共阅读和开发者讨论中的占比是否异常高？'),
}
# Selected raw inputs whose units can be displayed unambiguously.
EVIDENCE = {
    'valuation.basket_pe':('AI 股票篮子滚动市盈率',1,'倍'),
    'valuation.basket_ps':('AI 股票篮子市销率',1,'倍'),
    'dynamics.ai_runup':('AI 股票近两年相对大盘的涨幅差',100,'个百分点'),
    'capex.capex_ocf':('大型云厂商资本开支 / 经营现金流',100,'%'),
    'capex.negative_fcf':('资本开支超过经营现金流的云厂商',1,'家'),
    'credit.ebp':('超额债券风险溢价',1,'个百分点'),
    'lev.nq_asset_managers':('资管机构纳指期货净多头 / 未平仓量',100,'%'),
    'demand.npm_growth':('npm 开发工具相对下载增速（历史评分）',None,'分'),
    'narrative.hacker_news':('AI 话题在 Hacker News 热门讨论中的占比',100,'%'),
}


def numeric(value, low=None, high=None):
    return (type(value) in (float,int) and isfinite(value)
            and (low is None or value>=low) and (high is None or value<=high))


def public_date(value, as_of):
    try:
        return date.fromisoformat(value)<=date.fromisoformat(as_of)
    except (TypeError,ValueError):
        return False


def breakdown(data, reading):
    day=reading['date']
    if not isinstance(data,dict) or data.get('seriesId')!='aibi-2.0' or data.get('date')!=day:
        raise ValueError('指数版本或日期不匹配')
    head=data.get('headline') or {}
    if not numeric(head.get('value'),0,100) or abs(head['value']-reading['value'])>.051:
        raise ValueError('总分与当日发布记录不符')
    axes=[]
    for key,(name,meaning) in AXES.items():
        axis=data.get(key) or {}
        if numeric(axis.get('value'),0,100) and axis.get('band') in BANDS:
            axes.append(dict(name=name,value=axis['value'],band=BANDS[axis['band']],meaning=meaning,
                             rank=axis.get('rank') if numeric(axis.get('rank'),0,100) else None,
                             since=axis.get('rankSince') if public_date(axis.get('rankSince'),day) else None))
    contributions={a['pillar']:a['points'] for a in data.get('attribution',[])
                   if isinstance(a,dict) and a.get('pillar') in PILLARS and numeric(a.get('points'),-100,100)}
    pillars=[]
    for key,(name,meaning) in PILLARS.items():
        p=(data.get('pillars') or {}).get(key) or {}
        value=p.get('score')
        weight=p.get('weight')
        pillars.append(dict(name=name,meaning=meaning,value=value if numeric(value,0,100) else None,
                            weight=weight if numeric(weight,0,100) else None,contribution=contributions.get(key)))
    evidence=[]
    for item in data.get('indicators',[]):
        if not isinstance(item,dict) or item.get('id') not in EVIDENCE or not public_date(item.get('asOf'),day):
            continue
        label,factor,unit=EVIDENCE[item['id']]
        value=item.get('score') if factor is None else item.get('value')
        if numeric(value):
            evidence.append(dict(label=label,value=round(value*(factor or 1),2),unit=unit,date=item['asOf']))
    levels={axis['name']:axis['band'] for axis in axes}
    summary='。'.join(f'{name}处于{levels[name]}区间' for name in ('市场热度','脆弱性','需求缺口') if name in levels)
    if levels.get('脆弱性') in ('高位','极高') and levels.get('市场热度') in ('低位','正常'):
        summary='市场追涨热度有限，但资本开支、融资与杠杆构成的脆弱性指标处于高位。'
        summary+='若信用利差也开始走阔，说明压力有从投入或仓位扩散到融资市场的迹象。'
    elif summary:
        summary+='。'
    return dict(axes=axes,pillars=pillars,evidence=evidence,summary=summary,
                rank=head.get('rank') if numeric(head.get('rank'),0,100) else None,
                since=head.get('rankSince') if public_date(head.get('rankSince'),day) else None,
                reconstructed=data.get('reconstructed') is True)
