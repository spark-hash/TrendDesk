'use strict';
(() => {
  const sections={structure:'多周期技术',intraday:'日内专区',fundamental:'基本面',longterm:'长线时机'};
  const colors=['#94d8b0','#e9bd75','#90b7e4','#cb9fdb'];
  let section='structure', data=null, key='', generation=0, pending=false, last=0, visible=false;
  let aiSeq=0, aiBusy=false, aiText='';
  let period='1D',windowSize=null,firstSlot=null,pan=null;
  const selectedPatterns=new Set();
  const priceChart=createPriceChart($('study-candles'),$('study-price-info'),'study',()=>({
    bars:data?.candles,tf:period,lines:data?.lines,zones:data?.cross_levels,
    canScore:mode==='live'&&data?.symbol===selected&&data?.tf===period,
    showLines:$('technical-lines').checked,showCross:$('study-cross').checked,
    patterns:Object.entries(data?.sections.structure||{}).filter(([id,v])=>selectedPatterns.has(id)&&v.overlay)
  }));
  function viewport(total){
    const count=Math.min(total,windowSize??(section==='structure'?80:total));
    const maxStart=total-Math.max(1,Math.ceil(count*.2));
    return {count,start:Math.max(0,Math.min(maxStart,firstSlot??total-count))};
  }
  function resetView(){windowSize=null;firstSlot=null;pan=null}
  function zoom(total,factor,anchor=.5){
    const old=viewport(total);
    windowSize=Math.min(total,Math.max(Math.min(12,total),Math.round(old.count*factor)));
    firstSlot=Math.round(old.start+(old.count-windowSize)*Math.max(0,Math.min(1,anchor)));
    render();
  }
  const fieldMeaning={close:'分钟收盘价（美元）',vwap:'当日累计成交量加权均价（美元）',volume:'该分钟成交股数',
    dif:'MACD 快慢指数均线之差',dea:'DIF 的信号均线',hist:'MACD 柱 · DIF 与 DEA 的差值',rsi:'14 周期 RSI · 涨跌动量，范围 0–100'};
  const context=()=>[mode,selected,section,period].join('/');
  function resetAI(){
    aiSeq++; aiBusy=false; aiText=''; $('study-answer').textContent='';
  }
  function metricButton(id,label){
    return '<button class="text-button" data-study-ai="'+esc(id)+'"'+(aiBusy?' disabled':'')+'>'+esc(label)+'</button>';
  }
  function plot(rows,fields,{lines=[],boxes=[],events=[],title,range=null,minute=false}){
    if(!rows.length)return '';
    const W=Math.max(160,$('study-chart').clientWidth),H=fields[0]==='close'?210:94,L=10,R=68,T=10,B=20;
    const minuteOf=time=>Number(time.slice(11,13))*60+Number(time.slice(14,16));
    const axis=rows.map((b,i)=>minute?minuteOf(b.time)-570:i);
    const units=Math.max(1,axis.at(-1)+1),{count,start}=viewport(units);
    const dx=(W-L-R)/count,indices=new Map(rows.map((b,i)=>[b.time,i]));
    const visible=axis.map((slot,i)=>slot>=start&&slot<start+count?i:-1).filter(i=>i>=0);
    const values=visible.flatMap(i=>fields.map(k=>rows[i][k]).filter(Number.isFinite));
    for(const [,t1,a,t2,b] of lines){
      const l=axis[indices.get(t1)],r=axis[indices.get(t2)];
      if(!(r>l)||r<start||l>=start+count)continue;
      for(const slot of [Math.max(l,start),Math.min(r,start+count-1)])values.push(a+(b-a)*(slot-l)/(r-l));
    }
    for(const box of boxes)if(axis[indices.get(box.end)]>=start&&axis[indices.get(box.start)]<start+count)values.push(box.bottom,box.top);
    if(!values.length&&!range)values.push(...rows.flatMap(b=>fields.map(k=>b[k]).filter(Number.isFinite)));
    if(!values.length&&!range)return '';
    if(fields.includes('hist'))values.push(0);
    const low=range?range[0]:Math.min(...values),high=range?range[1]:Math.max(...values);
    const span=high-low||Math.max(0.01,Math.abs(low)*0.002);
    const x=i=>L+(axis[i]+0.5-start)*dx,y=v=>T+(high-v)/span*(H-B-T);
    let svg='<svg viewBox="0 0 '+W+' '+H+'" role="img" aria-label="'+esc(title)+'">';
    for(const v of [low,(low+high)/2,high]){
      const tick=number(v,fields[0]==='dif'?3:2);
      svg+='<g data-plot-hint="纵轴刻度 · '+tick+'"><line x1="'+L+'" x2="'+(W-R)+'" y1="'+y(v)+'" y2="'+y(v)+'" stroke="#303c39"/><text x="'+(W-R+5)+'" y="'+(y(v)+4)+'">'+tick+'</text></g>';
    }
    svg+='<svg x="'+L+'" width="'+(W-R-L)+'" height="'+H+'" viewBox="'+L+' 0 '+(W-R-L)+' '+H+'" overflow="hidden">';
    for(const box of boxes){
      const x1=x(indices.get(box.start)),x2=x(indices.get(box.end)),confirm=x(indices.get(box.formed));
      const when=new Date(Date.parse(box.formed)+60000).toLocaleTimeString('en-GB',{timeZone:'America/New_York',hour:'2-digit',minute:'2-digit'});
      const label='平台于 '+when+' ET 首次确认 · '+number(box.bottom)+'–'+number(box.top)+' · 上沿 '+box.highs+' 次 / 下沿 '+box.lows+' 次';
      svg+='<g data-plot-hint="'+esc(label)+'"><rect x="'+x1+'" y="'+y(box.top)+'" width="'+(x2-x1)+'" height="'+(y(box.bottom)-y(box.top))+'" fill="#cb9fdb" fill-opacity=".13" stroke="#cb9fdb" stroke-opacity=".6"/><path d="M'+confirm+' '+y(box.top)+'V'+y(box.bottom)+'" stroke="#cb9fdb" stroke-dasharray="2 2"/></g>';
    }
    fields.forEach((k,j)=>{
      if(k==='hist'||k==='volume'){
        for(const i of visible){
          const b=rows[i];
          if(!Number.isFinite(b[k]))continue;
          svg+='<rect data-plot-hint="'+fieldMeaning[k]+'" x="'+(x(i)-dx*.35)+'" y="'+Math.min(y(0),y(b[k]))+'" width="'+Math.max(.7,dx*.7)+'" height="'+Math.max(.6,Math.abs(y(0)-y(b[k])))+'" fill="'+(k==='volume'?colors[2]:b[k]>=0?colors[0]:'#df998b')+'" opacity=".5"/>';
        }
        return;
      }
      let path='',prev=-2;
      visible.forEach(i=>{
        const b=rows[i];if(!Number.isFinite(b[k]))return;
        path+=(axis[i]===prev+1?'L':'M')+x(i)+' '+y(b[k])+' ';prev=axis[i];
      });
      svg+='<g data-plot-hint="'+fieldMeaning[k]+'"><path d="'+path+'" stroke="'+colors[j]+'" stroke-width="1.8" fill="none"/><path d="'+path+'" stroke="transparent" stroke-width="8" fill="none"/></g>';
    });
    for(const [name,t1,v1,t2,v2,level] of lines){
      if(!indices.has(t1)||!indices.has(t2))continue;
      const col=name.startsWith('通道')?colors[2]:name.startsWith('平台')?colors[3]:name.startsWith('支撑')?colors[0]:colors[1];
      const hint=name+' · 最新窗口拟合或测算 · 起点 '+number(v1)+' / 终点 '+number(v2)+levelHint(level);
      const path='M'+x(indices.get(t1))+' '+y(v1)+'L'+x(indices.get(t2))+' '+y(v2);
      svg+='<g data-plot-hint="'+esc(hint)+'"><path fill="none" stroke="'+col+'" stroke-width="'+levelStyle(level).width+'" stroke-dasharray="'+levelStyle(level).dash+'"  d="'+path+'"/><path fill="none" stroke="transparent" stroke-width="9" d="'+path+'"/></g>';
    }
    if((fields[0]==='close')&&$('study-cross').checked&&visible.includes(rows.length-1)){
      svg+=crossOverlay(data.cross_levels,low,high,y,L,x(rows.length-1),'data-plot-hint');
    }
    const markColors={formed:'#cb9fdb',first:'#e9bd75',confirmed:'#94d8b0',returned:'#df998b'};
    for(const event of events){
      const label=esc(event.at.slice(11,16)+' ET · '+event.status);
      svg+='<circle data-plot-event="'+esc(event.id)+'" tabindex="0" aria-label="'+label+'" cx="'+x(indices.get(event.time))+'" cy="'+y(event.price)+'" r="4" fill="'+markColors[event.stage]+'" stroke="#18201e"><title>'+label+'</title></circle>';
    }
    for(const i of new Set([visible[0],visible[Math.floor(visible.length/2)],visible.at(-1)].filter(Number.isInteger))){
      const dt=rows[i].time;
      const label=minute?new Date(Date.parse(dt)+60000).toLocaleTimeString('en-GB',{timeZone:'America/New_York',hour:'2-digit',minute:'2-digit'}):data?.tf==='1M'?dt.slice(0,7):dt.slice(5,10)+(data?.tf?.endsWith('m')||data?.tf==='4h'?' '+dt.slice(11,16):'');
      svg+='<text data-plot-hint="时间刻度 · '+esc(label)+' ET" x="'+x(i)+'" y="'+(H-2)+'" text-anchor="'+(i===visible[0]?'start':i===visible.at(-1)?'end':'middle')+'">'+esc(label)+'</text>';
    }
    return '<figure data-units="'+units+'" data-fields="'+fields.join(',')+'"><figcaption>'+esc(title)+'</figcaption>'+svg+'</svg></svg><output class="chart-tip" hidden></output></figure>';
  }
  function render(){
    const minute=section==='intraday', rows=minute?data?.minutes:data?.candles;
    pointScores.sync('study',selected,minute?'1m':period,mode==='live'&&['structure','intraday'].includes(section)&&!!rows?.length,
      minute&&data?.minute_score?{...data.minute_score,at:rows.at(-1).time,cutoff:data.minute_score.as_of}:null);
    const expanded=$('study-inactive')?.open;
    $('study-heading').textContent=selected+' · 个股研究';
    $('study-journal-link').hidden=section==='fundamental'||mode!=='live';
    $('study-tf-label').hidden=section!=='structure';
    for(const b of $('study-periods').children){b.classList.toggle('active',b.dataset.period===period);b.setAttribute('aria-pressed',String(b.dataset.period===period))}
    $('plot-tools').hidden=!(mode==='live' && (section==='structure'?data?.candles?.length:section==='intraday'&&data?.minutes?.length));
    $('study-price').hidden=section!=='structure'||mode!=='live'||!data?.candles?.length;
    $('study-chart').innerHTML=''; $('study-cards').innerHTML=''; $('study-section-action').innerHTML='';
    $('minute-events').replaceChildren();
    $('study-layers').hidden=mode!=='live'||!['structure','intraday'].includes(section);
    for(const input of $('study-layers').querySelectorAll('input'))
      input.parentElement.hidden=input.id==='study-cross'?false:input.id==='technical-lines'?section!=='structure':section!=='intraday';
    $('study-answer').textContent=aiText;
    if(mode!=='live'){ $('study-status').textContent='切换到实时工作台可查看真实数据研究。';return; }
    if(!data){$('study-status').textContent='正在读取行情与研究数据…';return;}
    const items=data.sections[section], stamp=data.times[section];
    const labels={structure:'已收盘 K 线',intraday:'常规时段 · 1 分钟',fundamental:'moomoo 估值快照',longterm:'日线收盘观察'};
    let status=labels[section]+(stamp?' · '+stamp.slice(0,16).replace('T',' ')+' ET':' · 暂无数据');
    if(section==='intraday' && stamp){
      status+=stamp<data.expected_minute?' · 分钟行情滞后':' · 最近已完成分钟';
      if(data.minute_gaps)status+=' · 缺失 '+data.minute_gaps+' 根分钟线，指标可能失真';
    }
    if(section==='longterm' && stamp && stamp<data.expected_daily)status+=' · 日线滞后';
    if(data.errors[section])status+=' · '+data.errors[section];
    if(section==='structure')status+=periodNote(data.tf);
    $('study-status').textContent=status;
    if(section==='structure'){
      priceChart.draw();
    }else if(section==='intraday'){
      const rows=data.minutes;
      const overlay=data.intraday_overlay||{lines:[],boxes:[],events:[]};
      const legend=['绿线价格','金线 VWAP'];
      if($('minute-channel').checked&&overlay.lines.length)legend.push('蓝色趋势通道');
      if($('minute-boxes').checked&&overlay.boxes.length)legend.push('紫色平台');
      if($('minute-marks').checked&&overlay.events.length)legend.push('标记：紫色形成、金色初破、绿色确认、红色回落');
      $('study-chart').innerHTML=plot(rows,['close','vwap'],{title:'分时 · '+legend.join(' / '),minute:true,
        lines:$('minute-channel').checked?overlay.lines:[],boxes:$('minute-boxes').checked?overlay.boxes:[],
        events:$('minute-marks').checked?overlay.events:[]})
        +plot(rows,['volume'],{range:[0,Math.max(1,...rows.map(b=>b.volume))],title:'每分钟成交量 · 股',minute:true})
        +plot(rows,['dif','dea','hist'],{title:'MACD · 绿线 DIF / 金线 DEA / 柱为差值',minute:true})
        +plot(rows,['rsi'],{range:[0,100],title:'RSI (14)',minute:true});
      if(overlay.events.length){
        const latest=overlay.events.at(-1);
        const events=overlay.events.slice().reverse().map(e=>'<li>'+esc(e.at.slice(11,16)+' ET · '+e.status+' · '+number(e.price))+
          metricButton(e.id,'AI 解读')+'</li>').join('');
        $('minute-events').innerHTML='<details><summary>'+esc('最近提醒 '+latest.at.slice(11,16)+' ET · '+latest.status+'（当日 '+overlay.events.length+' 条）')+'</summary><ol>'+events+'</ol></details>';
      }
    }
    if(!Object.keys(items).length)return;
    $('study-section-action').innerHTML=metricButton('all','AI 解读整个'+sections[section]+' ↗');
    const card=([id,v])=>
      '<article'+(v.overlay?' data-shape="'+esc(id)+'"':'')+'><div class="rule-heading"><h4>'+esc(v.title)+'</h4>'+metricButton(id,'AI 解读')+'</div><strong>'+esc(v.status)+'</strong> '+gradeBadge(studyGrade(id,v,data,section))+
      (v.overlay?'<button type="button" class="pattern-toggle" aria-pressed="'+selectedPatterns.has(id)+'">'+(selectedPatterns.has(id)?'隐藏形态':'在图上显示')+'</button>':'')+v.facts.map(f=>'<p>'+esc(f)+'</p>').join('')+(v.url?'<a class="text-button" href="'+esc(v.url)+'" target="_blank" rel="noreferrer">查看 SEC 原始披露 ↗</a>':'')+'</article>';
    const entries=Object.entries(items);
    if(section!=='structure'){$('study-cards').innerHTML=entries.map(card).join('');return;}
    const patterns=new Set(['top2','bottom2','top3','bottom3','harami','engulf','inside','doji']);
    const indicators=new Set(['ma20','ma50','ma200','volume','atr']);
    const shapes=entries.filter(([id])=>patterns.has(id));
    const inactive=([,v])=>['未出现','未识别'].includes(v.status);
    const blocks=[
      ['通道、平台与关键位',entries.filter(([id])=>!patterns.has(id)&&!indicators.has(id))],
      ['已出现和待确认的形态',shapes.filter(row=>!inactive(row))],
      ['均线、波幅与成交量',entries.filter(([id])=>indicators.has(id))]
    ];
    let html=blocks.filter(([,rows])=>rows.length).map(([heading,rows])=>'<h3 class="study-group">'+heading+'</h3>'+rows.map(card).join('')).join('');
    const other=shapes.filter(inactive);
    if(other.length)html+='<details id="study-inactive"'+(expanded?' open':'')+'><summary>未触发的形态（'+other.length+'）</summary><div>'+other.map(card).join('')+'</div></details>';
    $('study-cards').innerHTML=html;
  }
  async function sync(force=false){
    const next=context();
    if(key!==next){key=next;selectedPatterns.clear();data=null;priceChart.reset();resetView();generation++;pending=false;last=0;resetAI();render();}
    if(mode!=='live'||(!visible&&!force)||pending||(!force&&Date.now()-last<60000))return;
    pending=true;
    const g=generation;
    try{
      const response=await request('/api/studies/'+encodeURIComponent(selected)+'?tf='+period+'&section='+section,'GET',undefined,45000);
      if(g===generation){if(data?.times[section]!==response.times[section])resetAI();data=response;render();}
    }catch(e){if(g===generation){data=null;render();$('study-status').textContent='研究更新失败 · '+e.message;}}
    finally{if(g===generation){last=Date.now();pending=false;}}
  }
  window.openStudySection=name=>{
    if(section!==name){section=name;resetAI();}
    sync();
  };
  window.setStudyPeriod=tf=>{period=tf};
  $('study-periods').onclick=e=>{const b=e.target.closest('[data-period]');if(b&&period!==b.dataset.period){period=b.dataset.period;sync(true)}};
  $('study-journal-link').addEventListener('click',()=>{
    $('journal-scope').value='current';
    $('journal-kind').value=section==='longterm'?'timing':'';
    $('journal-tf').value=section==='intraday'?'1m':section==='longterm'?'1D':period;
  });
  $('study-refresh').onclick=()=>sync(true);
  for(const input of $('study-layers').querySelectorAll('input'))bindLayer(input.id,render);
  const plotWidth=svg=>svg.viewBox.baseVal.width-78;
  function showHint(e){
    const figure=e.target.closest('figure');
    if(!figure||!data)return;
    const svg=figure.querySelector('svg'), tip=figure.querySelector('output');
    const target=e.target.closest('[data-plot-event]');
    const event=target&&data.intraday_overlay?.events.find(v=>v.id===target.dataset.plotEvent);
    const rect=figure.getBoundingClientRect();
    const point=target&&e.type==='focusin'?target.getBoundingClientRect():null;
    const clientX=point?point.left+point.width/2:e.clientX;
    const clientY=point?point.top+point.height/2:e.clientY;
    const coords=new DOMPoint(clientX,clientY).matrixTransform(svg.getScreenCTM().inverse());
    const rows=section==='intraday'?data.minutes:data.candles;
    const minute=t=>Number(t.slice(11,13))*60+Number(t.slice(14,16))-570;
    const count=section==='intraday'?minute(rows.at(-1).time)+1:rows.length;
    const slot=Math.floor((coords.x-10)*viewport(count).count/plotWidth(svg))+viewport(count).start;
    const row=section==='intraday'?rows.find(b=>minute(b.time)===slot):rows[slot];
    const hint=e.target.closest('[data-plot-hint]')?.dataset.plotHint;
    if(!row&&!event&&!hint&&(coords.x<10||coords.x>svg.viewBox.baseVal.width-68)){tip.hidden=true;return;}
    if(event)tip.textContent=event.status+'\n'+event.facts.join('\n');
    else if(!row)tip.textContent=hint||(slot>=count?'未来区域 · 尚无行情数据':'此时段缺少行情');
    else{
      const names={close:'收',vwap:'VWAP',volume:'量',dif:'DIF',dea:'DEA',hist:'柱',rsi:'RSI',open:'开',high:'高',low:'低'};
      const fields=figure.dataset.fields?figure.dataset.fields.split(','):['open','high','low','close'];
      const time=section==='intraday'?new Date(Date.parse(row.time)+60000).toLocaleTimeString('en-GB',{timeZone:'America/New_York',hour:'2-digit',minute:'2-digit'})+' ET 收盘':row.time.slice(0,16).replace('T',' ')+' ET';
      tip.textContent=[time,fields.map(k=>names[k]+' '+number(row[k],k==='volume'?0:2)).join(' · '),hint].filter(Boolean).join('\n');
    }
    tip.hidden=false;
    tip.style.left=Math.max(0,Math.min(clientX-rect.left+9,rect.width-tip.offsetWidth))+'px';
    tip.style.top=Math.max(0,clientY-rect.top-tip.offsetHeight-7)+'px';
  }
  const charts=$('study-chart');
  let plotWidthSeen=0;
  new ResizeObserver(([entry])=>{
    const width=entry.contentRect.width;
    if(width===plotWidthSeen)return;
    plotWidthSeen=width;
    if(width&&section==='intraday'&&data)render();
  }).observe(charts);
  charts.addEventListener('focusin',showHint);
  charts.addEventListener('pointerdown',e=>{
    const figure=e.target.closest('figure');
    if(!figure||e.button!==0||!e.target.closest('svg'))return;
    const svg=figure.querySelector('svg'),units=Number(figure.dataset.units);
    const view=viewport(units);pan={x:e.clientX,y:e.clientY,at:pointAt(e),moved:false,start:view.start,units,count:view.count,step:svg.getScreenCTM().a*plotWidth(svg)/view.count};
    charts.setPointerCapture(e.pointerId);showHint(e);
  });
  charts.addEventListener('pointermove',e=>{
    if(!pan){showHint(e);return}
    if(Math.hypot(pan.x-e.clientX,pan.y-e.clientY)>=5)pan.moved=true;
    const next=Math.max(0,Math.min(pan.units-Math.max(1,Math.ceil(pan.count*.2)),pan.start+Math.round((pan.x-e.clientX)/pan.step)));
    if(next!==firstSlot){firstSlot=next;render()}
  });
  function pointAt(e){
    const figure=e.target.closest('figure');if(!figure||!data||!e.target.closest('svg'))return null;
    const svg=figure.querySelector('svg'),p=new DOMPoint(e.clientX,e.clientY).matrixTransform(svg.getScreenCTM().inverse());
    if(p.x<10||p.x>=svg.viewBox.baseVal.width-68)return null;
    const view=viewport(Number(figure.dataset.units)),slot=view.start+Math.floor((p.x-10)*view.count/plotWidth(svg));
    if(section==='structure')return data.candles[slot]?.time;
    return data.minutes.find(b=>Number(b.time.slice(11,13))*60+Number(b.time.slice(14,16))-570===slot)?.time;
  }
  function pick(time){
    if(time)pointScores.pick('study',time);else toast('该位置没有已收盘行情');
  }
  charts.addEventListener('contextmenu',e=>{if(e.target.closest('svg')){e.preventDefault();pick(pointAt(e))}});
  charts.addEventListener('pointerup',e=>{
    if(pan&&!pan.moved&&Math.hypot(pan.x-e.clientX,pan.y-e.clientY)<5&&pointScores.enabled('study'))pick(pan.at);
  });
  charts.addEventListener('lostpointercapture',()=>pan=null);
  charts.addEventListener('dblclick',()=>{resetView();render()});
  charts.addEventListener('wheel',e=>{
    const f=e.target.closest('figure');if(!f)return;e.preventDefault();
    const svg=f.querySelector('svg'),point=new DOMPoint(e.clientX,e.clientY).matrixTransform(svg.getScreenCTM().inverse());
    zoom(Number(f.dataset.units),e.deltaY<0?.8:1.25,(point.x-10)/plotWidth(svg));
  },{passive:false});
  $('plot-tools').onclick=e=>{
    const action=e.target.closest('[data-zoom]')?.dataset.zoom,f=charts.querySelector('figure');
    if(section==='structure'&&action){if(action==='reset')priceChart.reset();else priceChart.zoom(action==='in'?-10:10);return}
    if(!action||!f)return;
    if(action==='reset'){resetView();render()}else zoom(Number(f.dataset.units),action==='in'?.8:1.25);
  };
  function clearTips(){for(const tip of charts.querySelectorAll('output'))tip.hidden=true;}
  charts.addEventListener('pointerout',e=>{if(e.target.closest('figure')!==e.relatedTarget?.closest?.('figure'))clearTips();});
  charts.addEventListener('focusout',clearTips);
  $('study-cards').addEventListener('click',e=>{
    const row=e.target.closest('[data-shape]');
    if(!row||e.target.closest('[data-study-ai],a'))return;
    const id=row.dataset.shape,button=row.querySelector('.pattern-toggle'),shape=data?.sections.structure?.[id];
    if(!shape?.overlay)return;
    if(selectedPatterns.has(id))selectedPatterns.delete(id);
    else{selectedPatterns.add(id);priceChart.reveal(shape.overlay)}
    button.setAttribute('aria-pressed',String(selectedPatterns.has(id)));
    button.textContent=selectedPatterns.has(id)?'隐藏形态':'在图上显示';
    priceChart.draw();
  });
  $('studies').addEventListener('click',async e=>{
    const button=e.target.closest('[data-study-ai]');
    if(!button||aiBusy||!data||key!==context())return;
    const id=button.dataset.studyAi, n=++aiSeq;
    const event=data.intraday_overlay?.events.find(v=>v.id===id);
    const label=id==='all'?sections[section]:event?event.at.slice(11,16)+' ET · '+event.status:data.sections[section][id].title;
    const query=new URLSearchParams({section,focus:id,tf:data.tf,profile:$('study-profile').value,as_of:data.times[section]||''});
    aiBusy=true;aiText='正在解读 '+label+'…';render();
    $('study-answer').scrollIntoView({block:'nearest'});
    try{
      const a=await request('/api/studies/'+encodeURIComponent(data.symbol)+'/analysis?'+query,'POST',undefined,210000);
      document.dispatchEvent(new Event('trenddesk-ai-usage'));
      if(n===aiSeq)aiText=label+' · '+a.symbol+' · '+a.as_of+' · '+(a.receipt.returned_model||a.model)+' · 强度 '+(a.receipt.returned_effort||a.receipt.requested_effort||'模型默认')+' · '+(a.tokens.total_tokens??'未返回')+' tokens\n\n'+a.text;
    }catch(err){if(n===aiSeq)aiText=label+' · '+err.message;}
    finally{if(n===aiSeq){aiBusy=false;render();}}
  });
  new IntersectionObserver(entries=>{visible=entries[0].isIntersecting;if(visible)sync();}).observe($('studies'));
  window.syncStudies=()=>sync();
})();
