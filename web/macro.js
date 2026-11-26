'use strict';
(() => {
  let loading=false;
  let checked=null, pane='all', pending='', received=0;
  const answers={}, problems={};
  function showAnswerStatus(){
    const answer=answers[pane];
    $('macro-ai-output').textContent=answer?.text||'';
    if(!answer){
      $('macro-ai-status').textContent=problems[pane]||(pending===pane?'正在解读…':
        pane==='bubble'?'按所选模式解读本期指数及风险来源。':'按所选模式解读宏观指标与新闻。');
      return;
    }
    const receipt=answer.receipt;
    const mode=answer.profile==='deep'?'深入分析':'快速解读';
    const usage=answer.tokens.total_tokens?.toLocaleString('zh-CN')??'未返回';
    const parts=[mode,'数据检查于 '+timeText(answer.as_of)+' ET','返回模型 '+(receipt.returned_model??'未返回'),
      '请求强度 '+(receipt.requested_effort??'模型默认'),'返回强度 '+(receipt.returned_effort??'未返回'),usage+' tokens'];
    if(answer.cached)parts.push('复用上次解读');
    if(checked && checked>answer.as_of)parts.push('数据已重新检查，可再次分析');
    $('macro-ai-status').textContent=parts.join(' · ');
  }
  const pctChange=m=>m.change===0?'持平':(m.change>0?'上升 ':'下降 ')+number(Math.abs(m.change),2)+(m.code==='VIXCLS'?' 点':' 个百分点');
  const signed=(v,d=1)=>(v>0?'+':'')+number(v,d);
  function explainBubble(m){
    const d=m.detail;
    if(!d)return '<p class="muted small">当期七项明细暂未取得，可通过当日原文核对总分。</p>';
    const axes=d.axes.map(a=>'<div><b>'+esc(a.name)+' · '+number(a.value,1)+' · '+esc(a.band)+'</b><p>'+
      esc(a.meaning)+'</p>'+(a.rank!=null&&a.since?'<small>'+esc(a.since.slice(0,4))+' 年以来第 '+number(a.rank,0)+' 百分位</small>':'')+'</div>').join('');
    const drivers=d.pillars.filter(p=>p.contribution!=null).sort((a,b)=>Math.abs(b.contribution)-Math.abs(a.contribution));
    const moves=drivers.slice(0,3).map(p=>esc(p.name)+' '+signed(p.contribution,2)+' 分').join('，');
    const rows=d.pillars.map(p=>'<tr><th scope="row">'+esc(p.name)+'</th><td>'+number(p.weight,0)+(p.weight==null?'':'%')+'</td><td>'+
      number(p.value,1)+'</td><td>'+esc(p.meaning)+'</td></tr>').join('');
    const obs=d.evidence.map(e=>'<li><span>'+esc(e.label)+'</span> <b>'+number(e.value,Number.isInteger(e.value)?0:2)+' '+esc(e.unit)+
      '</b> <small class="muted">'+esc(e.date)+'</small></li>').join('');
    const levels=d.pillars.filter(p=>p.value!=null).sort((a,b)=>b.value-a.value);
    let contrast='';
    if(levels.length>1){
      const highest=levels[0],lowest=levels.at(-1);
      contrast='<p>分项读数范围从'+esc(lowest.name)+'的 '+number(lowest.value,1)+' 分，到'+esc(highest.name)+'的 '+number(highest.value,1)+' 分。</p>';
    }
    return (m.detail_unavailable?'<p class="muted small">分项刷新失败，以下为同一观测日的已保存明细。</p>':'')+
      '<p class="bubble-summary">'+esc(d.summary)+'</p><div class="bubble-axes">'+axes+'</div>'+
      '<h4>总分由哪些因素构成？</h4>'+contrast+(moves?'<p>较上期，发布方列出的主要贡献为'+moves+'。正值推高总分，负值拉低总分。</p>':'')+
      '<details><summary>查看七项分数、权重和含义</summary><div class="bubble-table"><table><thead><tr><th>因素</th><th>权重</th><th>分数</th><th>衡量的问题</th></tr></thead><tbody>'+rows+'</tbody></table></div></details>'+
      (obs?'<details><summary>查看底层观测与数据日期（'+d.evidence.length+' 项）</summary><ul>'+obs+'</ul></details>':'')+
      '<p class="muted small">发布方的历史回放用于辨识过热环境。要把它用作交易条件，还需验证高分后不同持有期的回撤和误报率。<a href="https://aibubblemonitor.com/v2/backtest" target="_blank" rel="noreferrer">查看验证范围 ↗</a></p>';
  }
  function renderBubble(m){
    const host=$('bubble-reading');
    if(!m){host.textContent='暂无可用读数，可点击「刷新数据」重试。';return;}
    const history=m.history||[];
    const change=m.change==null?'':m.change===0?'较上期持平':'较上期'+(m.change>0?'上升 ':'下降 ')+number(Math.abs(m.change),1)+' 分';
    const components=Object.entries(m.components).map(([name,value])=>
      '<span>'+esc(name)+' <b>'+number(value,1)+'</b></span>').join('');
    let chart='';
    if(history.length>1){
      const scores=history.map(p=>p.value), low=Math.max(0,Math.floor(Math.min(...scores))-1), high=Math.min(100,Math.ceil(Math.max(...scores))+1);
      const xs=i=>32+282*i/(history.length-1), ys=v=>5+47*(high-v)/(high-low);
      const path=history.map((p,i)=>xs(i)+','+ys(p.value)).join(' ');
      const dots=history.map((p,i)=>'<circle cx="'+xs(i)+'" cy="'+ys(p.value)+'" r="4" fill="transparent"><title>'+esc(p.date)+' · '+number(p.value,1)+' 分</title></circle>').join('');
      chart='<figure><figcaption>最近 '+history.length+' 期 · '+esc(history[0].date)+' 至 '+esc(m.date)+'</figcaption>'+
        '<svg viewBox="0 0 320 58" role="img" aria-label="AI 泡沫指数近期走势"><text x="2" y="11">'+high+'</text><text x="2" y="54">'+low+'</text>'+
        '<polyline fill="none" stroke="currentColor" stroke-width="2" points="'+path+'"/>'+dots+'</svg></figure>';
    }
    const rank=m.detail?.rank, since=m.detail?.since;
    const trend=[5,20].filter(n=>history.length>n).map(n=>n+' 期 '+signed(m.value-history.at(-1-n).value)+' 分').join(' · ');
    host.innerHTML='<div class="bubble-layout"><div><strong>'+number(m.value,1)+' <small>/ 100 · '+esc(m.band)+'</small></strong>'+
      (rank!=null&&since?'<p>'+esc(since.slice(0,4))+' 年以来第 '+number(rank,0)+' 百分位</p>':'')+
      '<p>'+esc([change,trend].filter(Boolean).join(' · '))+'</p><a class="text-button" href="'+esc(m.source)+'" target="_blank" rel="noreferrer">'+esc(m.provider)+' · '+esc(m.date)+' ↗</a>'+
      (m.detail?.reconstructed?'<small> 历史重建</small>':'')+
      (m.stale?'<p class="data-warning">缓存或发布滞后，AI 解读暂不引用该读数。</p>':'')+'</div>'+chart+'</div>'+
      (!m.detail?.axes.length?'<div class="bubble-components">'+components+'</div>':'')+explainBubble(m);
  }
  function render(data) {
    checked=data.checked;
    showAnswerStatus();
    $('macro-status').textContent='公开市场数据 · 最近检查 '+timeText(data.checked)+' ET'+
      (data.unavailable.length?' · 获取失败：'+data.unavailable.join('、')+'。已有记录会标记为缓存。':' · 各指标按来源发布频率更新');
    $('macro-sentiment').textContent=data.sentiment;
    const bubble=data.indicators.find(m=>m.code==='AIBI');
    renderBubble(bubble);
    $('bubble-shortcut').textContent=bubble?'AI 泡沫指数 · '+number(bubble.value,1)+' / 100 · '+bubble.band+' · '+bubble.date+(bubble.stale?' · 缓存或滞后':'')+' ↗':'查看 AI 泡沫指数 ↗';
    const ranked=data.indicators.filter(m=>m.code!=='AIBI').sort((a,b)=>Number(b.percentile!=null)-Number(a.percentile!=null));
    $('macro-cards').innerHTML=ranked.map(m=>{
      const monthly=['CPIAUCSL','UNRATE'].includes(m.code);
      const date=monthly?m.date.slice(0,7):m.date;
      return `<article><a href="${esc(m.source)}" target="_blank" rel="noreferrer">${esc(m.title)} ↗</a><strong>${number(m.value)}<small> ${esc(m.unit)}</small></strong><div>较上期${pctChange(m)}</div>${m.percentile!=null?`<div>过去一年 · 第 ${number(m.percentile,1)} 百分位</div>`:''}<small class="muted">${esc(date)} · FRED${m.stale?' · 缓存或观测滞后':''}</small>${m.note?`<div>${esc(m.note)}</div>`:''}</article>`;
    }).join('')||'<p class="muted">暂无宏观观测，请稍后刷新。</p>';
    $('macro-news').innerHTML=['美联储公告','MarketWatch 要闻'].map(source=>{
      const items=data.news.filter(n=>n.source===source);
      return `<div><h4>${esc(source)}</h4>${items.length?items.slice(0,4).map(n=>`<a href="${esc(n.url)}" target="_blank" rel="noreferrer"><small class="muted">${esc(timeText(n.published))} ET${n.cached?' · 缓存':''}</small><span>${esc(n.title)} ↗</span></a>`).join(''):'<p class="muted">近 30 天暂无可显示条目。</p>'}</div>`;
    }).join('');
  }
  async function refresh(manual=false) {
    if(loading) return;
    loading=true;$('macro-refresh').disabled=true;
    try {
      render(await request(manual?'/api/macro/refresh':'/api/macro',manual?'POST':'GET'));
      received=Date.now();
    } catch(e) {$('macro-status').textContent='宏观环境更新失败 · '+e.message;}
    finally {loading=false;$('macro-refresh').disabled=false;}
  }
  $('macro-refresh').onclick=()=>refresh(true);
  async function analyze(focus){
    const button=$('macro-analyze'), profile=$('macro-profile');
    if(button.disabled)return;
    button.disabled=true;
    $('bubble-analyze').disabled=true;
    profile.disabled=true;
    pending=focus;
    delete answers[focus];
    delete problems[focus];
    showAnswerStatus();
    try {
      answers[focus]=await request('/api/macro/analysis?focus='+focus+'&profile='+profile.value,'POST',undefined,210000);
      document.dispatchEvent(new Event('trenddesk-ai-usage'));
    } catch(e){
      problems[focus]='解读失败 · '+e.message;
    } finally {
      button.disabled=false;
      $('bubble-analyze').disabled=false;
      profile.disabled=false;
      pending='';
      showAnswerStatus();
    }
  }
  $('macro-analyze').onclick=()=>analyze('all');
  $('bubble-analyze').onclick=()=>analyze('bubble');
  window.openMacro=(focus='all')=>{
    pane=focus;
    for(const el of document.querySelectorAll('[data-macro-pane]'))el.hidden=el.dataset.macroPane!==focus;
    $('macro-heading').textContent=focus==='bubble'?'当期指数':'美股宏观环境';
    $('macro-ai-heading').textContent=focus==='bubble'?'指数 AI 解读':'宏观 AI 解读';
    $('macro-analyze').hidden=focus==='bubble';
    $('bubble-analyze').hidden=focus!=='bubble';
    showAnswerStatus();
    if(Date.now()-received>=900000)refresh();
  };
  setInterval(()=>{if(!document.hidden&&!$('macro-section').hidden)refresh();},900000);
})();
