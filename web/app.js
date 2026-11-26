'use strict';
const $=id=>document.getElementById(id);
const esc=value=>String(value??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const number=(value,digits=2)=>value==null||!Number.isFinite(Number(value))?'—':Number(value).toLocaleString('en-US',{minimumFractionDigits:digits,maximumFractionDigits:digits});
const pct=value=>value==null?'—':`${value>=0?'+':''}${number(value)}%`;
const color=value=>value==null?'muted':value>=0?'positive':'negative';
const trendColor=state=>state==='up'?'positive':state==='down'?'negative':'muted';
let selected=localStorage.getItem('td-selected')||'NVDA',timeframe='1D',mode='live',state=null,loading=false,lastSignature='',chartCount=90,chartOffset=0;
let chartGeometry=null,drag=null,toastTimer=null;

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
  }catch(error){$('status-text').textContent='本地后台连接中断：'+error.message;$('status-banner').className='status-banner';$('connection-label').textContent='后台离线';$('connection-button').classList.remove('connected');$('monitor-status').textContent='后台离线 · 监控已暂停';$('data-warning').textContent='后台离线，屏幕上的价格和分析仅供历史查看。';$('chart-source').textContent='缓存画面 · 后台离线';}
  finally{loading=false;if(requested.selected!==selected||requested.timeframe!==timeframe||requested.mode!==mode)refresh()}
}
function selectSymbol(symbol){selected=symbol;localStorage.setItem('td-selected',selected);chartOffset=0;lastSignature='';refresh()}
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
  renderWatchlist();renderStock();renderEvents();window.renderResearch?.();window.syncStudies?.();window.syncNavSymbol?.();window.syncJournal?.();
  const q=state.quota;$('quota-label').textContent=q?`历史额度 ${q.used} / ${q.used+q.remaining} · 本连接订阅 ${q.subscriptions}`:'实时数据由 moomoo OpenD 提供';
  $('export').hidden=demo;
}
function renderWatchlist(){
  const query=$('search').value.trim().toUpperCase();
  let items=state.items.filter(x=>state.watchlist.includes(x.symbol)&&(x.symbol.includes(query)||x.name.toUpperCase().includes(query)));
  const sort=$('sort').value;
  if(sort==='distance')items.sort((a,b)=>Math.abs(a.analysis.distance??999)-Math.abs(b.analysis.distance??999));
  if(sort==='strength')items.sort((a,b)=>(b.analysis.relative_strength??-999)-(a.analysis.relative_strength??-999));
  $('watchlist').innerHTML=items.length?items.map(item=>`<button class="watch-row ${item.symbol===selected?'selected':''}" data-symbol="${esc(item.symbol)}" title="${esc(item.error||item.analysis.message)}"><span class="stock-monogram">${esc(item.symbol.slice(0,2))}</span><span class="watch-left"><strong>${esc(item.symbol)}</strong><small class="${trendColor(item.analysis.trends['1D'].state)}">${item.error?'数据获取失败':esc(item.analysis.trends['1D'].label)}</small></span><span class="watch-right"><strong>${number(item.price)}</strong><small class="${color(item.change)}">${pct(item.change)}</small></span></button>`).join(''):'<div class="empty-events"><p>没有匹配的股票</p></div>';
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
  const signature=JSON.stringify([selected,timeframe,mode,state.chart]);
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

function drawChart(){
  const host=$('chart'),bars=state?.chart||[];
  if(!bars.length){chartGeometry=null;$('chart-info').textContent='开 —　高 —　低 —　收 —';host.innerHTML='<div class="empty-chart"><div class="empty-icon">⌁</div><h3>等待第一组行情</h3><p>启动并登录 Moomoo OpenD 后，历史 K 线会自动同步到这里。</p><button id="empty-demo" class="button">先看看演示界面 ↗</button></div>';$('empty-demo').onclick=toggleMode;return}
  const width=host.clientWidth||700,height=host.clientHeight||330,right=60,left=8,top=12,bottom=28,volumeHeight=48,priceBottom=height-bottom-volumeHeight-15;
  chartOffset=Math.max(0,Math.min(chartOffset,Math.max(0,bars.length-25)));
  const end=bars.length-chartOffset,start=Math.max(0,end-chartCount),visible=bars.slice(start,end);
  if(!visible.length)return;
  const plotWidth=width-left-right,step=plotWidth/visible.length;
  const average=(index,n)=>index<n-1?null:bars.slice(index-n+1,index+1).reduce((s,b)=>s+b.close,0)/n;
  const av20=visible.map((_,i)=>average(start+i,20)),av50=visible.map((_,i)=>average(start+i,50));
  let lo=Math.min(...visible.map(b=>b.low),...av20.filter(x=>x!=null),...av50.filter(x=>x!=null)),hi=Math.max(...visible.map(b=>b.high),...av20.filter(x=>x!=null),...av50.filter(x=>x!=null));
  const padding=Math.max((hi-lo)*.12,hi*.001);lo-=padding;hi+=padding;
  const y=value=>top+(hi-value)/(hi-lo)*(priceBottom-top),x=i=>left+(i+.5)*step;
  const maxVolume=Math.max(1,...visible.map(b=>b.volume));
  let svg=`<svg viewBox="0 0 ${width} ${height}" xmlns="http://www.w3.org/2000/svg" aria-hidden="true"><defs><clipPath id="plot-clip"><rect x="${left}" y="0" width="${plotWidth}" height="${height}"/></clipPath></defs>`;
  for(let i=0;i<5;i++){const value=lo+(hi-lo)*i/4,yy=y(value);svg+=`<line x1="${left}" x2="${width-right}" y1="${yy}" y2="${yy}" stroke="#2b332d" stroke-dasharray="2 4"/><text x="${width-right+10}" y="${yy+3}" fill="#849386" font-size="9" font-family="Segoe UI, sans-serif">${number(value)}</text>`}
  svg+='<g clip-path="url(#plot-clip)">';
  visible.forEach((b,i)=>{const xx=x(i),c=b.close>=b.open?'#91d6b0':'#d99986',cw=Math.max(1,step*.62);svg+=`<line x1="${xx}" x2="${xx}" y1="${y(b.high)}" y2="${y(b.low)}" stroke="${c}" opacity="${b.complete===false?.45:1}"/><rect x="${xx-cw/2}" y="${Math.min(y(b.open),y(b.close))}" width="${cw}" height="${Math.max(1,Math.abs(y(b.close)-y(b.open)))}" fill="${c}" opacity="${b.complete===false?.45:1}"/><rect x="${xx-cw/2}" y="${height-bottom-b.volume/maxVolume*volumeHeight}" width="${cw}" height="${b.volume/maxVolume*volumeHeight}" fill="${c}" opacity=".24"/>`});
  for(const [values,c] of [[av20,'#d8bc75'],[av50,'#89afd5']]){let path='';values.forEach((v,i)=>{if(v!=null)path+=`${path?'L':'M'}${x(i)},${y(v)} `});svg+=`<path d="${path}" stroke="${c}" stroke-width="1.3" fill="none"/>`}
  const a=current()?.analysis;
  if($('market-lines').checked && chartOffset===0 && state.structure_lines?.length){
    const times=new Map(bars.map((b,i)=>[b.time,i-start]));
    for(const [label,t1,v1,t2,v2] of state.structure_lines){
      const c=label.startsWith('通道')?'#90b7e4':label.startsWith('平台')?'#cb9fdb':label.startsWith('支撑')?'#94d8b0':'#e9bd75';
      const i=times.get(t1),j=times.get(t2);
      if(j<=i||j<0||v2<lo||v2>hi)continue;
      const from=Math.max(i,0),v=v1+(from-i)*(v2-v1)/(j-i);
      svg+=`<path d="M${x(from)} ${y(v)} L${x(j)} ${y(v2)}" stroke="${c}" stroke-dasharray="5 4" fill="none"><title>${esc(label)} ${number(v2)}</title></path>`;
    }
  }else if($('market-lines').checked&&chartOffset===0&&a){for(const [level,label,c] of [[a.resistance,'小时阻力','#d8bc75'],[a.support,'小时支撑','#89afd5']]){if(level!=null&&level>lo&&level<hi)svg+=`<line x1="${left}" x2="${width-right}" y1="${y(level)}" y2="${y(level)}" stroke="${c}" stroke-dasharray="5 6" opacity=".55"/><text x="${left+8}" y="${y(level)-5}" fill="${c}" font-size="9">${label} ${number(level)}</text>`}}
  const last=visible.at(-1);svg+=`<line x1="${left}" x2="${width-right}" y1="${y(last.close)}" y2="${y(last.close)}" stroke="#9ab58c" stroke-dasharray="3 4" opacity=".6"/></g>`;
  svg+=`<rect x="${width-right+3}" y="${y(last.close)-9}" width="55" height="18" rx="3" fill="#b9df9d"/><text x="${width-right+7}" y="${y(last.close)+3}" fill="#24311f" font-size="9">${number(last.close)}</text>`;
  for(let i=0;i<5;i++){const index=Math.floor((visible.length-1)*i/4),b=visible[index],date=new Date(b.time);const label=new Intl.DateTimeFormat('en-US',{timeZone:'America/New_York',...(timeframe==='1M'?{year:'numeric',month:'short'}:!timeframe.endsWith('m')&&timeframe!=='4h'?{month:'short',day:'numeric'}:{month:'numeric',day:'numeric',hour:'2-digit',minute:'2-digit',hourCycle:'h23'})}).format(date);svg+=`<text x="${x(index)}" y="${height-7}" text-anchor="${i===0?'start':i===4?'end':'middle'}" fill="#7c8d7f" font-size="9">${esc(label)}</text>`}
  svg+='<g id="crosshair" style="display:none"><line id="cross-x" stroke="#96a78e" stroke-dasharray="3 4"/><line id="cross-y" stroke="#96a78e" stroke-dasharray="3 4"/></g></svg>';
  host.innerHTML=svg;chartGeometry={left,right,width,height,step,visible,start};setCandleInfo(last);
}
function chartStamp(value){return timeframe==='1M'&&value?value.slice(0,7):timeText(value)}
function periodNote(tf){
  if(tf==='4h')return ' · 09:30 ET 起算，末根截至当日收市';
  if(tf==='1M')return ' · 截至最近完整交易月';
  return '';
}
function setCandleInfo(b){$('chart-info').textContent=`${chartStamp(b.time)}　开 ${number(b.open)}　高 ${number(b.high)}　低 ${number(b.low)}　收 ${number(b.close)}　量 ${Intl.NumberFormat('en',{notation:'compact',maximumFractionDigits:1}).format(b.volume)}${b.complete===false?' · 未收盘':''}`}
$('chart').addEventListener('wheel',e=>{if(!chartGeometry)return;e.preventDefault();chartCount=Math.max(25,Math.min(240,chartCount+(e.deltaY>0?10:-10)));drawChart()},{passive:false});
$('chart').addEventListener('pointerdown',e=>{if(!chartGeometry)return;drag={x:e.clientX,offset:chartOffset};$('chart').setPointerCapture(e.pointerId)});
$('chart').addEventListener('pointerup',()=>drag=null);
$('chart').addEventListener('pointercancel',()=>drag=null);
$('chart').addEventListener('pointermove',e=>{if(!chartGeometry)return;const g=chartGeometry;if(drag){chartOffset=drag.offset+Math.round((e.clientX-drag.x)/g.step);drawChart();return}const r=$('chart').getBoundingClientRect(),px=e.clientX-r.left,py=e.clientY-r.top,index=Math.max(0,Math.min(g.visible.length-1,Math.floor((px-g.left)/g.step)));setCandleInfo(g.visible[index]);const cross=$('crosshair');if(!cross)return;cross.style.display='';$('cross-x').setAttribute('x1',px);$('cross-x').setAttribute('x2',px);$('cross-x').setAttribute('y1',0);$('cross-x').setAttribute('y2',g.height-25);$('cross-y').setAttribute('x1',0);$('cross-y').setAttribute('x2',g.width-g.right);$('cross-y').setAttribute('y1',py);$('cross-y').setAttribute('y2',py)});
$('chart').addEventListener('pointerleave',()=>{if($('crosshair'))$('crosshair').style.display='none'});
new ResizeObserver(()=>{if(state)drawChart()}).observe($('chart'));
function toggleMode(){mode=mode==='live'?'demo':'live';chartOffset=0;lastSignature='';refresh()}
$('mode-toggle').onclick=toggleMode;
function bindLayer(id,onChange){
  const input=$(id);
  input.checked=localStorage.getItem('td-layer-'+id)!=='off';
  input.addEventListener('change',()=>{localStorage.setItem('td-layer-'+id,input.checked?'on':'off');onChange();});
}
bindLayer('market-lines',drawChart);
$('chart-reset').onclick=()=>{chartCount=90;chartOffset=0;drawChart()};
document.querySelectorAll('[data-tf]').forEach(b=>b.onclick=()=>{timeframe=b.dataset.tf;chartOffset=0;lastSignature='';refresh()});
document.querySelector('.stock-actions a[href="#studies"]').addEventListener('click',()=>{$('study-tf').value=timeframe;});
document.querySelectorAll('.market-card').forEach(b=>b.onclick=()=>selectSymbol(b.dataset.symbol));
$('search').oninput=()=>state&&renderWatchlist();$('sort').onchange=()=>state&&renderWatchlist();$('event-filter').onchange=()=>state&&renderEvents();
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
