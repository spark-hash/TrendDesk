'use strict';
const $=id=>document.getElementById(id);
const esc=value=>String(value??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const number=(value,digits=2)=>value==null||!Number.isFinite(Number(value))?'—':Number(value).toLocaleString('en-US',{minimumFractionDigits:digits,maximumFractionDigits:digits});
const pct=value=>value==null?'—':`${value>=0?'+':''}${number(value)}%`;
const color=value=>value==null?'muted':value>=0?'positive':'negative';
const trendColor=state=>state==='up'?'positive':state==='down'?'negative':'muted';
let selected=localStorage.getItem('td-selected')||'NVDA',timeframe='1D',mode='live',state=null,loading=false,lastSignature='';
let toastTimer=null;

async function request(path,method='GET',data,timeout=15000){
  const response=await fetch(path,{method,headers:method==='GET'?{}:{'Content-Type':'application/json','X-TrendDesk':'local'},body:data===undefined?undefined:JSON.stringify(data),signal:AbortSignal.timeout(timeout)});
  if(!response.ok){let body;try{body=await response.json()}catch{body={detail:response.statusText}};throw new Error(Array.isArray(body.detail)?body.detail.map(x=>x.msg).join('；'):body.detail||'请求失败')}
  return response.json();
}
function toast(message){$('toast').textContent=message;$('toast').classList.add('show');clearTimeout(toastTimer);toastTimer=setTimeout(()=>$('toast').classList.remove('show'),5000)}
function current(){return state?.items.find(item=>item.symbol===selected)}
function liveOnly(){if(mode==='demo'){toast('请先退出演示模式，再修改自选、持仓或设置。');return false}return true}
async function refresh(){
  if(loading)return;loading=true;
  const requested={selected,timeframe,mode};
  try{
    const next=await request(`/api/state?selected=${encodeURIComponent(selected)}&timeframe=${timeframe}&mode=${mode}`);
    if(requested.selected!==selected||requested.timeframe!==timeframe||requested.mode!==mode)return;
    state=next;selected=next.selected;render();
  }catch(error){entryContext='';entryGeneration++;$('entry-summary').textContent='后台离线，暂停开仓评估';$('entry-factors').textContent='等待恢复行情';$('entry-answer').textContent='';$('entry-analyze').disabled=true;$('status-text').textContent='本地后台连接中断：'+error.message;$('status-banner').className='status-banner';$('connection-label').textContent='后台离线';$('connection-button').classList.remove('connected');$('monitor-status').textContent='后台离线 · 监控已暂停';$('data-warning').textContent='后台离线，屏幕上的价格和分析仅供历史查看。';$('chart-source').textContent='缓存画面 · 后台离线';}
  finally{loading=false;if(requested.selected!==selected||requested.timeframe!==timeframe||requested.mode!==mode)refresh()}
}
function selectSymbol(symbol){selected=symbol;localStorage.setItem('td-selected',selected);marketChart.reset();lastSignature='';refresh()}
function render(){
  const demo=mode==='demo';
  $('status-text').textContent=state.message;
  $('status-banner').className='status-banner'+(demo?' demo':state.connected?' healthy':'');
  $('connection-label').textContent=demo?'演示预览':state.connected?'OpenD 已连接':'OpenD 未连接';
  $('connection-button').classList.toggle('connected',state.connected&&!demo);
  $('mode-toggle').textContent=demo?'退出演示':'查看演示';$('reconnect').hidden=demo;
  $('market-label').textContent=`${state.market.label} · 下一开盘 ${timeText(state.market.next_open,'Asia/Singapore')} SGT`;
  $('clock').textContent=timeText(state.now,'America/New_York')+' ET';
  $('watch-count').textContent=state.watchlist.length;
  $('monitor-count').innerHTML=`${state.watchlist.length}<small> / 50 自选股</small>`;
  const fresh=state.items.filter(x=>x.quote_fresh&&state.watchlist.includes(x.symbol)).length;
  $('monitor-status').textContent=demo?'合成数据 · 不产生提醒':!state.connected?'监控暂停 · 等待 OpenD':state.market.open||state.market.close_confirmation?`${fresh} 只报价新鲜 · 收盘确认入场`:'休市期间不生成新提醒';
  for(const symbol of ['SPY','QQQ']){
    const item=state.items.find(x=>x.symbol===symbol),t=item?.analysis.trends['1D'];
    $(`benchmark-${symbol.toLowerCase()}`).innerHTML=`<div class="market-top"><strong>${symbol}</strong><span>${symbol==='SPY'?'S&P 500 ETF':'NASDAQ 100 ETF'}</span></div><div class="market-bottom"><strong>${number(item?.price)}</strong><span class="${color(item?.change)}">${pct(item?.change)}</span></div><div class="market-caption">${demo?'演示 · ':''}${esc(t?.label||'等待数据')}</div>`;
  }
  renderWatchlist();renderStock();window.pointScores?.sync("market",state.selected,state.timeframe,!!state.chart?.length);renderEntryScore();renderEvents();window.renderResearch?.();window.syncStudies?.();window.syncNavSymbol?.();window.syncJournal?.();
  const q=state.quota;$('quota-label').textContent=q?`历史额度 ${q.used} / ${q.used+q.remaining} · 本连接订阅 ${q.subscriptions}`:'实时数据由 moomoo OpenD 提供';
  $('export').hidden=demo;
}
let entryContext='',entryGeneration=0;
function renderEntryScore(){
  const item=current(),score=item?.entry_score;
  const context=[selected,mode,score?.snapshot_id].join('/');
  if(context===entryContext)return;
  entryContext=context;entryGeneration++;
  $('entry-panel').hidden=!item;
  $('entry-answer').textContent='';
  $('entry-analyze').disabled=mode!=='live'||score?.total==null;
  if(!score)return;
  $('entry-summary').innerHTML=`<strong>${score.total??'—'}<small> / 100</small></strong><b>${esc(score.verdict)}</b><p>${esc(score.setups[0]?.name||'等待历史 K 线')}${score.as_of?' · '+timeText(score.as_of)+' ET 收盘':''}</p>`;
  $('entry-factors').innerHTML=score.setups.length?'<p>分别评估两种入场形态，取较高分。满足一项得该项全部分值；分数表示条件符合程度。</p>'+score.setups.map(setup=>`<h4>${esc(setup.name)} · ${setup.total}/100</h4>`+setup.rows.map(r=>`<div class="entry-factor"><strong>${r.points}/${r.limit}</strong><span>${esc(r.label)}</span><p>${esc(r.evidence)}</p></div>`).join('')).join(''):'需要已收盘的日线、小时线与 15 分钟线达到计算窗口。';
}
$('entry-analyze').onclick=async()=>{
  const item=current(),score=item?.entry_score;
  if(mode!=='live'||score?.total==null||state.selected!==selected)return;
  const n=++entryGeneration;
  $('entry-analyze').disabled=true;
  $('entry-answer').textContent='正在解读 '+selected+' 的开仓评分…';
  const query=new URLSearchParams({profile:$('entry-profile').value,snapshot_id:score.snapshot_id});
  try{
    const a=await request('/api/ai/entry-score/'+encodeURIComponent(selected)+'?'+query,'POST',undefined,210000);
    document.dispatchEvent(new Event('trenddesk-ai-usage'));
    if(n===entryGeneration&&selected===item.symbol)$('entry-answer').textContent=(a.receipt?.returned_model||a.model)+' · '+(a.tokens?.total_tokens??'—')+' tokens\n'+a.text;
  }catch(err){if(n===entryGeneration)$('entry-answer').textContent=err.message}
  finally{if(n===entryGeneration)$('entry-analyze').disabled=false}
};
let draggingSymbol=null,savingOrder=false;
const list=$('watchlist');
list.addEventListener('dragstart',e=>{
  const row=e.target.closest('[draggable="true"]');if(!row)return;
  draggingSymbol=row.dataset.symbol;e.dataTransfer.effectAllowed='move';e.dataTransfer.setData('text/plain',draggingSymbol);
});
function markDrop(e){
  if(!draggingSymbol)return null;
  const row=e.target.closest('[data-symbol]');
  for(const old of list.querySelectorAll('[data-drop]'))delete old.dataset.drop;
  if(!row||row.dataset.symbol===draggingSymbol)return null;
  e.preventDefault();const bounds=row.getBoundingClientRect();
  row.dataset.drop=e.clientY>=bounds.top+bounds.height/2?'after':'before';
  return row;
}
list.addEventListener('dragover',markDrop);
list.addEventListener('drop',async e=>{
  const row=markDrop(e);if(!row)return;
  const move={symbol:draggingSymbol,anchor:row.dataset.symbol,after:row.dataset.drop==='after'};
  savingOrder=true;draggingSymbol=null;
  try{state.watchlist=await request('/api/watchlist/order','PUT',move)}catch(err){toast(err.message)}
  finally{savingOrder=false;renderWatchlist();refresh()}
});
list.addEventListener('dragend',()=>{draggingSymbol=null;if(!savingOrder)renderWatchlist()});
function renderWatchlist(){
  if(draggingSymbol||savingOrder)return;
  const query=$('search').value.trim().toUpperCase();
  let items=state.items.filter(x=>state.watchlist.includes(x.symbol)&&(x.symbol.includes(query)||x.name.toUpperCase().includes(query)));
  const sort=$('sort').value;
  const manual=sort==='default'&&mode==='live';
  if(sort==='default')items.sort((a,b)=>state.watchlist.indexOf(a.symbol)-state.watchlist.indexOf(b.symbol));
  if(sort==='distance')items.sort((a,b)=>Math.abs(a.analysis.distance??999)-Math.abs(b.analysis.distance??999));
  if(sort==='strength')items.sort((a,b)=>(b.analysis.relative_strength??-999)-(a.analysis.relative_strength??-999));
  $('watchlist').innerHTML=items.length?items.map(item=>`<button class="watch-row ${item.symbol===selected?'selected':''}" draggable="${manual}" data-symbol="${esc(item.symbol)}" title="${esc(item.error||item.analysis.message)}"><span class="stock-monogram" title="${manual?'按住并拖动以调整顺序':esc(item.symbol)}">${manual?'⠿':esc(item.symbol.slice(0,2))}</span><span class="watch-left"><strong>${esc(item.symbol)}</strong><small class="${trendColor(item.analysis.trends['1D'].state)}">${item.error?'数据获取失败':esc(item.analysis.trends['1D'].label)} · ${item.entry_score?.total==null?'待评分':item.entry_score.total+' 分'}</small></span><span class="watch-right"><strong>${number(item.price)}</strong><small class="${color(item.change)}">${pct(item.change)}</small></span></button>`).join(''):'<div class="empty-events"><p>没有匹配的股票</p></div>';
  $('watchlist').querySelectorAll('[data-symbol]').forEach(el=>el.onclick=()=>selectSymbol(el.dataset.symbol));
}
function renderStock(){
  const item=current();if(!item){$('remove-watch').hidden=true;$('stock-symbol').textContent=selected;$('stock-name').textContent='请先添加到自选股';$('stock-price').textContent='—';$('chart').innerHTML='<div class="empty-chart"><h3>该代码尚未加入自选</h3><p>点击自选股列表中的 ＋，添加后开始同步。</p></div>';return}
  const a=item.analysis;
  $('stock-symbol').innerHTML=`${esc(selected)} <span>US EQUITY</span>`;
  $('stock-name').textContent=item.name;
  $('stock-price').textContent=number(item.price);
  $('stock-change').className=color(item.change);$('stock-change').textContent=mode==='demo'?`${pct(item.change)} · 演示`:item.change!=null?`${pct(item.change)} · ${timeText(item.quote_time)} ET`:'历史收盘 / 暂无报价';
  $('setup-title').textContent=a.ready?a.message:'等待足够的历史数据';
  $('setup-reason').textContent=a.trends['1D'].reason;
  $('data-warning').textContent=mode==='demo'?'合成演示数据，仅展示功能和布局。':item.error||(!state.connected?'OpenD 未连接，暂停新信号。':!item.synced?'正在同步历史数据，暂停新信号。':!state.market.open&&!state.market.close_confirmation?'当前休市，显示最近分析，不产生新提醒。':!item.quote_fresh?'报价已过期，暂停新信号。':!a.fresh?'部分周期 K 线尚未更新，暂停入场信号。':'已收盘 K 线确认 · 行情新鲜');
  $('levels').innerHTML=[['突破参考位',number(a.trigger),'emphasis'],['小时支撑',number(a.support),''],['参考保护位',number(a.stop),''],['参考 2R 目标',number(a.target_2r),''],['20 日相对 SPY',a.relative_strength==null?'—':`${number(a.relative_strength)} 个百分点`,'']].map(([name,value,cls])=>`<div class="level-row ${cls}"><span>${name}</span><strong>${value}</strong></div>`).join('');
  $('conditions').innerHTML=(a.signals.length?a.signals.map(s=>`<p>${esc(s.detail)}</p>`).join(''):'<p class="muted">本根尚无已确认信号。</p>')+'<a class="text-button" href="#research">查看短线条件与 AI 解读 ↗</a>';
  $('trend-strip').innerHTML=Object.entries(a.trends).map(([tf,t])=>`<div class="trend-item" title="${esc(t.reason)}"><span>${{'1D':'日线 · 主要趋势','60m':'小时线 · 走势结构','15m':'15 分钟 · 触发周期'}[tf]}</span><strong class="${trendColor(t.state)}"><i class="dot"></i>${esc(t.label)}</strong></div>`).join('');
  const p=item.position;
  $('position-info').innerHTML=p?`${number(p.quantity,3)} 股 · 成本 $${number(p.cost)}<br>保护 $${number(p.stop)} / 目标 $${number(p.target)}<br><span class="${color(item.price==null?null:(item.price-p.cost)*p.quantity)}">浮动盈亏 $${number(item.price==null?null:(item.price-p.cost)*p.quantity)}</span>`:'录入持仓，启用保护价和目标价提醒。';
  $('remove-watch').hidden=mode!=='live'||!state.watchlist.includes(selected);

  $('chart-source').textContent=mode==='demo'?'合成演示 · 前复权样式':`moomoo · 前复权 · 常规时段 · 最新 K 线 ${chartStamp(state.chart.at(-1)?.time)}${periodNote(timeframe)}${!state.connected?' · 缓存':''}${state.chart_error?' · '+state.chart_error:''}`;
  document.querySelectorAll('[data-tf]').forEach(b=>b.classList.toggle('active',b.dataset.tf===timeframe));
  const signature=JSON.stringify([selected,timeframe,mode,state.chart,state.cross_levels]);
  if(signature!==lastSignature){lastSignature=signature;drawChart()}
}
function timeText(value,zone='America/New_York'){
  if(!value)return '—';return new Intl.DateTimeFormat('zh-CN',{timeZone:zone,month:'2-digit',day:'2-digit',hour:'2-digit',minute:'2-digit',hourCycle:'h23'}).format(new Date(value));
}
function renderEvents(){
  let events=state.events;
  if($('event-filter').value==='selected')events=events.filter(e=>e.symbol===selected);
  if($('event-filter').value==='risk')events=events.filter(e=>['stop','target'].includes(e.kind));
  $('event-count').textContent=events.length;
  $('events').innerHTML=events.length?`<table class="events-table"><thead><tr><th>时间 · 美东</th><th>股票</th><th>信号</th><th>触发价</th><th class="detail-col">触发依据</th></tr></thead><tbody>${events.map(e=>`<tr data-id="${e.id}" tabindex="0"><td>${timeText(e.created)} ${!e.seen?'<span class="positive">●</span>':''}</td><td><strong>${esc(e.symbol)}</strong></td><td><span class="event-kind ${['stop','target'].includes(e.kind)?'risk':''}">${esc(e.title)}</span></td><td>${number(e.price)}</td><td class="detail-col">${esc(e.detail)}</td></tr>`).join('')}</tbody></table>`:`<div class="empty-events"><span>◷</span><div><p>${mode==='demo'?'演示模式不会产生或保存交易提醒':'最近 100 条提醒中没有匹配记录'}</p><small>记录会保留触发时间、价格和依据。</small></div></div>`;
  $('events').querySelectorAll('[data-id]').forEach(row=>{
    const open=()=>{const e=state.events.find(x=>x.id===Number(row.dataset.id));$('event-detail').innerHTML=`<h3>${esc(e.symbol)} · ${esc(e.title)}</h3><p>${esc(e.detail)}</p><p>触发价 $${number(e.price)}<br>美东 ${timeText(e.created)} / 新加坡 ${timeText(e.created,'Asia/Singapore')}</p>${window.conditionEvidence?.(e)||''}<details><summary>触发时的完整记录</summary><pre>${esc(JSON.stringify(e.payload,null,2))}</pre></details>`;const link=$('event-study');link.hidden=!state.items.some(item=>item.symbol===e.symbol);link.textContent='查看 '+e.symbol+' 当前信号条件 ↗';link.onclick=()=>{$('event-dialog').close();selectSymbol(e.symbol);};$('event-dialog').showModal()};row.onclick=open;row.onkeydown=e=>{if(e.key==='Enter')open()};
  });
}

function levelStyle(level){
  if(level?.strength==='强')return {width:2.8,dash:'none'};
  if(level?.strength==='中')return {width:1.9,dash:'8 4'};
  if(level?.strength==='弱')return {width:1,dash:'2 4'};
  return {width:1.3,dash:'5 4'};
}
function levelHint(level){
  return level?' · '+level.strength+' · '+level.touches+' 次独立测试':'';
}
function crossOverlay(zones,lo,hi,y,left,right,tipAttr){
  const visible=(zones||[]).filter(z=>z.price>=lo&&z.price<=hi);
  const lines=[];
  for(const side of ['支撑','阻力']){
    const group=visible.filter(z=>z.side===side);
    const nearest=[...group].sort((a,b)=>Math.abs(a.distance)-Math.abs(b.distance)).slice(0,2);
    lines.push(...new Set([...group.slice(0,4),...nearest]));
  }
  const labels=[];
  return lines.map(z=>{
    const yy=y(z.price),c=z.side==='支撑'?'#6fe3b3':'#ffab74';
    const label=z.tf+' '+z.side+' '+number(z.price);
    const tip=label+' · 当前跨周期参考区 '+number(z.low)+'–'+number(z.high)+' · '+z.strength+(z.touches?' · 该周期独立测试 '+z.touches+' 次':'')+' · 涉及 '+z.periods.join('、')+' · 距参考收盘 '+pct(z.distance)+' · 更新 '+timeText(z.as_of)+' ET';
    const show=labels.every(other=>Math.abs(other-yy)>13);if(show)labels.push(yy);
    return `<g ${tipAttr}="${esc(tip)}"><path d="M${left} ${yy}H${right}" stroke="${c}" stroke-width="${1+z.rank*.22}" stroke-dasharray="10 3 2 3" fill="none"/><path d="M${left} ${yy}H${right}" stroke="transparent" stroke-width="7" fill="none"/>${show?'<text x="'+(right-4)+'" y="'+(yy-3)+'" text-anchor="end" style="fill:'+c+';font-size:9px">'+esc(label)+'</text>':''}</g>`;
  }).join('');
}
const marketChart=createPriceChart($('chart'),$('chart-info'),'market',()=>({
  bars:state?.chart,tf:timeframe,lines:state?.structure_lines,zones:state?.cross_levels,analysis:current()?.analysis,
  showLines:$('market-lines').checked,showCross:$('market-cross').checked,
  canScore:state?.selected===selected&&state?.timeframe===timeframe&&state?.mode===mode
}));
function drawChart(){marketChart.draw()}
function chartStamp(value,tf=timeframe){return tf==='1M'&&value?value.slice(0,7):timeText(value)}
function periodNote(tf){
  if(tf==='4h')return ' · 09:30 ET 起算，末根截至当日收市';
  if(tf==='1M')return ' · 截至最近完整交易月';
  return '';
}
function toggleMode(){mode=mode==='live'?'demo':'live';marketChart.reset();lastSignature='';refresh()}
$('mode-toggle').onclick=toggleMode;
function bindLayer(id,onChange){
  const input=$(id);
  input.checked=localStorage.getItem('td-layer-'+id)!=='off';
  input.addEventListener('change',()=>{localStorage.setItem('td-layer-'+id,input.checked?'on':'off');onChange();});
}
bindLayer('market-lines',drawChart);bindLayer('market-cross',drawChart);
$('chart-reset').onclick=marketChart.reset;
document.querySelectorAll('[data-tf]').forEach(b=>b.onclick=()=>{timeframe=b.dataset.tf;marketChart.reset();lastSignature='';refresh()});
document.querySelector('.stock-actions a[href="#studies"]').addEventListener('click',()=>{window.setStudyPeriod(timeframe);});
document.querySelectorAll('.market-card').forEach(b=>b.onclick=()=>selectSymbol(b.dataset.symbol));
$('search').oninput=()=>state&&renderWatchlist();$('sort').onchange=()=>state&&renderWatchlist();$('event-filter').onchange=()=>state&&renderEvents();
$('about-button').onclick=async()=>{
  const version=$('about-version');
  version.textContent='正在读取…';
  $('about-dialog').showModal();
  try{
    const health=await request('/api/health','GET',undefined,5000);
    version.textContent=health.version?'v'+health.version:'服务未返回版本号';
  }catch{version.textContent='无法连接本地服务，请重新打开「关于」重试'}
};
document.querySelectorAll('.close-dialog').forEach(b=>b.onclick=()=>b.closest('dialog').close());
document.querySelectorAll('dialog').forEach(d=>d.addEventListener('click',e=>{if(e.target===d){const r=d.getBoundingClientRect();if(e.clientX<r.left||e.clientX>r.right||e.clientY<r.top||e.clientY>r.bottom)d.close()}}));
$('add-button').onclick=()=>{if(liveOnly()){$('add-dialog').showModal();$('new-symbol').focus()}};
$('add-form').onsubmit=async e=>{e.preventDefault();try{const data=await request('/api/watchlist','POST',{symbol:$('new-symbol').value});$('add-dialog').close();$('new-symbol').value='';selected=data.symbol;toast('已添加，等待 moomoo 同步');refresh()}catch(error){toast(error.message)}};
function openSettings(){if(!state||!liveOnly())return;const s=state.settings;$('setting-port').value=s.port;$('setting-volume').value=s.volume_multiple;$('setting-near').value=s.near_percent;$('setting-notifications').checked=s.notifications;$('settings-dialog').showModal()}
$('settings-button').onclick=openSettings;$('connection-button').onclick=openSettings;
$('settings-form').onsubmit=async e=>{e.preventDefault();try{await request('/api/settings','PUT',{port:Number($('setting-port').value),volume_multiple:Number($('setting-volume').value),near_percent:Number($('setting-near').value),notifications:$('setting-notifications').checked});$('settings-dialog').close();toast('设置已保存');refresh()}catch(error){toast(error.message)}};
$('reconnect').onclick=async()=>{try{await request('/api/reconnect','POST',{});toast('正在重连并重新同步历史数据');refresh()}catch(e){toast(e.message)}};
$('rules-button').onclick=()=>$('rules-dialog').showModal();
$('remove-watch')?.addEventListener('click',async()=>{try{await request('/api/watchlist/'+encodeURIComponent(selected),'DELETE');toast('已从自选移除');selectSymbol(state.watchlist.find(s=>s!==selected)||'SPY')}catch(e){toast(e.message)}});
$('position-button').onclick=()=>{if(!liveOnly()||!current())return;const p=current().position||{};$('position-title').textContent=selected+' · 持仓计划';for(const key of ['quantity','cost','stop','target'])$('position-'+key).value=p[key]??'';$('delete-position').hidden=!current().position;$('position-dialog').showModal()};
$('position-form').onsubmit=async e=>{e.preventDefault();const data={};for(const key of ['quantity','cost','stop','target'])data[key]=$('position-'+key).value?Number($('position-'+key).value):null;try{await request('/api/positions/'+encodeURIComponent(selected),'PUT',data);$('position-dialog').close();toast('持仓计划已保存');refresh()}catch(error){toast(error.message)}};
$('delete-position').onclick=async()=>{try{await request('/api/positions/'+encodeURIComponent(selected),'DELETE');$('position-dialog').close();toast('已移除持仓记录');refresh()}catch(e){toast(e.message)}};
$('ack-events').onclick=async()=>{if(!liveOnly())return;try{await request('/api/events/ack','POST',{});refresh()}catch(e){toast(e.message)}};
refresh();setInterval(refresh,4000);
