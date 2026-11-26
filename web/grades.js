'use strict';
// Positive values use green. Each badge names the dimension being assessed.
function grade(level,label,reason){
  return {level,label,reason};
}
function gradeBadge(g){
  return '<span class="grade" data-grade="'+g.level+'" title="'+esc(g.reason)+'">'+esc(g.label)+'</span>';
}
function direction(level,reason){
  return grade(level,['强空','偏空','略偏空','中性','略偏多','偏多','强多'][level+3],reason);
}
function studyGrade(id,metric,data,section){
  const s=metric.status, minute=data.minutes?.at(-1);
  if(/不足|暂无|未出现|未识别|未确认|未形成|观察中/.test(s))return grade(0,'待确认',s);
  if(section==='intraday'&&minute){
    if(['price','vwap'].includes(id)&&Number.isFinite(minute.vwap)){
      return direction(Math.sign(minute.close-minute.vwap),'分钟收盘价与当日 VWAP 比较');
    }
    if(id==='macd'&&Number.isFinite(minute.hist)){
      const sign=Math.sign(minute.hist);
      return direction(sign*(Math.sign(minute.dif)===sign?2:1),'DIF 与 DEA 的差值决定方向；DIF 同处零轴相应一侧时加深一级');
    }
    if(id==='rsi'&&Number.isFinite(minute.rsi)){
      const n=minute.rsi;
      return grade(n>=70?2:n>55?1:n<=30?-2:n<45?-1:0,
        n>=70?'强动量 · 超买区':n>55?'动量偏多':n<=30?'弱动量 · 超卖区':n<45?'动量偏空':'动量中性','RSI 以 45–55 为中性区，70 / 30 为动量极值观察线');
    }
  }
  if(s.includes('突破回落'))return grade(0,'突破失效',s);
  if(s.includes('收盘越过颈线'))return direction(id.startsWith('bottom')?3:-3,s+' · '+metric.title);
  if(s.includes('候选'))return grade(0,'待确认',s);
  if(/上升通道|趋势内突破|趋势内回踩转强|向上突破/.test(s))return direction(2,s);
  if(/下降通道|向下跌破/.test(s))return direction(-2,s);
  if(/^[上下]破/.test(s))return direction((s.startsWith('上')?1:-1)*(s.includes('5 分钟确认')?3:1),s);
  if(/底背离|阳线|趋势成立/.test(s))return direction(1,s);
  if(/顶背离|阴线/.test(s))return direction(-1,s);
  if(/^ma\d+$/.test(id)&&Number.isFinite(data.candles?.at(-1)?.close)&&section==='structure'){
    const average=Number(s);
    if(Number.isFinite(average))return direction(Math.sign(data.candles.at(-1).close-average),'最新已收盘价格与该周期均线比较');
  }
  return grade(0,'中性观察','此读数本身没有给出明确的多空方向');
}
function macroGrade(m){
  if(m.stale)return grade(0,'待更新','数据源滞后或使用缓存');
  if(Number.isFinite(m.percentile)){
    const p=m.percentile,n=p>=95?-3:p>=80?-2:p<=5?3:p<=20?2:0;
    return grade(n,n<0?'高压力':n>0?'低压力':'压力正常','相对过去一年的百分位；20 / 80 为低高分界，5 / 95 为极值');
  }
  if(!Number.isFinite(m.change))return grade(0,'待比较','缺少上一期数据');
  if(m.code==='T10Y2Y')return grade(m.value<0?-1:0,m.value<0?'曲线倒挂':'正斜率','10 年减 2 年收益率；倒挂标记期限结构压力');
  const name={CPIAUCSL:'通胀',UNRATE:'就业压力',DGS10:'长债利率'}[m.code];
  if(!name)return grade(0,'中性观察','暂无方向规则');
  return grade(-Math.sign(m.change),name+(m.change>0?'上行':m.change<0?'下行':'持平'),'与上一期比较；颜色表示此项压力变化');
}
function headlineGrade(title){
  const up=title.match(/\b(rall(?:y|ies|ied)|surge[sd]?|soar[sed]*|record highs?|rebounds?|gains?|bullish)\b/gi)||[];
  const down=title.match(/\b(crash(?:es|ed)?|plunges?|sell[ -]?offs?|rout|tumbles?|slumps?|bearish)\b/gi)||[];
  if(/\?|\b(not|never|avoid|avert|deny|denies)\b/i.test(title)||Boolean(up.length)===Boolean(down.length))
    return grade(0,'方向未明','标题词义混合、带疑问或未命中方向词');
  const hits=up.length?up:down,level=Math.min(2,new Set(hits.map(s=>s.toLowerCase())).size);
  return grade(up.length?level:-level,up.length?'标题偏多':'标题偏空','标题措辞：'+hits.join('、'));
}
function bubbleGrade(band,stale=false){
  if(stale)return grade(0,'待更新','该读数已标记缓存或滞后');
  return grade(({'低位':2,'正常':0,'偏高':-1,'高位':-2,'极高':-3})[band]??0,band||'未分级','按发布方的泡沫压力等级着色');
}
