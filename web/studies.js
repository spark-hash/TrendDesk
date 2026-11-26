'use strict';
(() => {
  const sections={structure:'多周期技术',intraday:'日内专区',fundamental:'基本面',longterm:'长线时机'};
  const colors=['#94d8b0','#e9bd75','#90b7e4','#cb9fdb'];
  let section='structure', data=null, key='', generation=0, pending=false, last=0, visible=false;
  let aiSeq=0, aiBusy=false, aiText='';
  const context=()=>[mode,selected,section,$('study-tf').value].join('/');
  function resetAI(){
    aiSeq++; aiBusy=false; aiText=''; $('study-answer').textContent='';
  }
  function metricButton(id,label){
    return '<button class="text-button" data-study-ai="'+esc(id)+'"'+(aiBusy?' disabled':'')+'>'+esc(label)+'</button>';
  }
  function plot(rows,fields,{candles=false,lines=[],boxes=[],events=[],title,range=null,minute=false}){
    if(!rows.length)return '';
    const W=900,H=candles||fields[0]==='close'?210:94,L=10,R=68,T=10,B=20;
    const values=rows.flatMap(b=>candles?[b.low,b.high]:fields.map(k=>b[k]).filter(Number.isFinite));
    values.push(...lines.flatMap(line=>[line[2],line[4]]));
    values.push(...boxes.flatMap(box=>[box.top,box.bottom]));
    if(!values.length)return '';
    const low=range?range[0]:Math.min(...values),high=range?range[1]:Math.max(...values);
    const span=high-low||Math.max(0.01,Math.abs(low)*0.002);
    const minuteOf=time=>Number(time.slice(11,13))*60+Number(time.slice(14,16));
    const axis=rows.map((b,i)=>minute?minuteOf(b.time)-570:i);
    const units=Math.max(1,axis.at(-1)+1);
    const dx=(W-L-R)/units;
    const x=i=>L+(axis[i]+0.5)*dx,y=v=>T+(high-v)/span*(H-B-T);
    const indices=new Map(rows.map((b,i)=>[b.time,i]));
    let svg='<svg viewBox="0 0 '+W+' '+H+'" role="img" aria-label="'+esc(title)+'">';
    for(const box of boxes){
      const x1=x(indices.get(box.start)),x2=x(indices.get(box.end)),confirm=x(indices.get(box.formed));
      const when=new Date(Date.parse(box.formed)+60000).toLocaleTimeString('en-GB',{timeZone:'America/New_York',hour:'2-digit',minute:'2-digit'});
      const label='平台于 '+when+' ET 首次确认 · '+number(box.bottom)+'–'+number(box.top)+' · 上沿 '+box.highs+' 次 / 下沿 '+box.lows+' 次';
      svg+='<g data-plot-hint="'+esc(label)+'"><rect x="'+x1+'" y="'+y(box.top)+'" width="'+(x2-x1)+'" height="'+(y(box.bottom)-y(box.top))+'" fill="#cb9fdb" fill-opacity=".13" stroke="#cb9fdb" stroke-opacity=".6"/><path d="M'+confirm+' '+y(box.top)+'V'+y(box.bottom)+'" stroke="#cb9fdb" stroke-dasharray="2 2"/></g>';
    }
    for(const v of [low,(low+high)/2,high]){
      svg+='<line x1="'+L+'" x2="'+(W-R)+'" y1="'+y(v)+'" y2="'+y(v)+'" stroke="#303c39"/><text x="'+(W-R+5)+'" y="'+(y(v)+4)+'">'+number(v,fields[0]==='dif'?3:2)+'</text>';
    }
    if(candles)rows.forEach((b,i)=>{
      const c=b.close>=b.open?colors[0]:'#df998b';
      svg+='<path stroke="'+c+'" d="M'+x(i)+' '+y(b.low)+'V'+y(b.high)+'"/><rect fill="'+c+'" x="'+(x(i)-dx*.31)+'" y="'+Math.min(y(b.open),y(b.close))+'" width="'+dx*.62+'" height="'+Math.max(.8,Math.abs(y(b.open)-y(b.close)))+'"/>';
    });
    fields.forEach((k,j)=>{
      if(k==='hist'||k==='volume'){
        for(const [i,b] of rows.entries()){
          if(!Number.isFinite(b[k]))continue;
          svg+='<rect x="'+(x(i)-dx*.35)+'" y="'+Math.min(y(0),y(b[k]))+'" width="'+Math.max(.7,dx*.7)+'" height="'+Math.max(.6,Math.abs(y(0)-y(b[k])))+'" fill="'+(k==='volume'?colors[2]:b[k]>=0?colors[0]:'#df998b')+'" opacity=".5"/>';
        }
        return;
      }
      let path='',prev=-2;
      rows.forEach((b,i)=>{
        if(!Number.isFinite(b[k]))return;
        path+=(axis[i]===prev+1?'L':'M')+x(i)+' '+y(b[k])+' ';prev=axis[i];
      });
      svg+='<path d="'+path+'" stroke="'+colors[j]+'" stroke-width="1.8" fill="none"/>';
    });
    for(const [name,t1,v1,t2,v2] of lines){
      if(!indices.has(t1)||!indices.has(t2))continue;
      const col=name.startsWith('通道')?colors[2]:name.startsWith('平台')?colors[3]:name.startsWith('支撑')?colors[0]:colors[1];
      const hint=name+' · 最新窗口拟合或测算 · 起点 '+number(v1)+' / 终点 '+number(v2);
      const path='M'+x(indices.get(t1))+' '+y(v1)+'L'+x(indices.get(t2))+' '+y(v2);
      svg+='<g data-plot-hint="'+esc(hint)+'"><path fill="none" stroke="'+col+'" stroke-dasharray="6 4" d="'+path+'"/><path fill="none" stroke="transparent" stroke-width="9" d="'+path+'"/></g>';
    }
    const markColors={formed:'#cb9fdb',first:'#e9bd75',confirmed:'#94d8b0',returned:'#df998b'};
    for(const event of events){
      const label=esc(event.at.slice(11,16)+' ET · '+event.status);
      svg+='<circle data-plot-event="'+esc(event.id)+'" tabindex="0" aria-label="'+label+'" cx="'+x(indices.get(event.time))+'" cy="'+y(event.price)+'" r="4" fill="'+markColors[event.stage]+'" stroke="#18201e"><title>'+label+'</title></circle>';
    }
    for(const i of [...new Set([0,Math.floor(rows.length/2),rows.length-1])]){
      const dt=rows[i].time;
      const label=minute?new Date(Date.parse(dt)+60000).toLocaleTimeString('en-GB',{timeZone:'America/New_York',hour:'2-digit',minute:'2-digit'}):data?.tf==='1M'?dt.slice(0,7):dt.slice(5,10)+(data?.tf?.endsWith('m')||data?.tf==='4h'?' '+dt.slice(11,16):'');
      svg+='<text x="'+x(i)+'" y="'+(H-2)+'" text-anchor="'+(i===0?'start':i===rows.length-1?'end':'middle')+'">'+esc(label)+'</text>';
    }
    return '<figure data-fields="'+fields.join(',')+'"><figcaption>'+esc(title)+'</figcaption>'+svg+'</svg><output class="chart-tip" hidden></output></figure>';
  }
  function render(){
    const expanded=$('study-inactive')?.open;
    $('study-heading').textContent=selected+' · 个股研究';
    $('study-journal-link').hidden=section==='fundamental'||mode!=='live';
    $('study-tf-label').hidden=section!=='structure';
    $('study-chart').innerHTML=''; $('study-cards').innerHTML=''; $('study-section-action').innerHTML='';
    $('minute-events').replaceChildren();
    $('study-layers').hidden=mode!=='live'||!['structure','intraday'].includes(section);
    for(const input of $('study-layers').querySelectorAll('input'))
      input.parentElement.hidden=input.id==='technical-lines'?section!=='structure':section!=='intraday';
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
      $('study-chart').innerHTML=plot(data.candles,[],{candles:true,lines:$('technical-lines').checked?data.lines:[],title:'价格结构 · 蓝色通道 / 绿色支撑 / 金色阻力 / 紫色平台'});
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
      '<article><div class="rule-heading"><h4>'+esc(v.title)+'</h4>'+metricButton(id,'AI 解读')+'</div><strong>'+esc(v.status)+'</strong>'+
      v.facts.map(f=>'<p>'+esc(f)+'</p>').join('')+(v.url?'<a class="text-button" href="'+esc(v.url)+'" target="_blank" rel="noreferrer">查看 SEC 原始披露 ↗</a>':'')+'</article>';
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
    if(key!==next){key=next;generation++;pending=false;data=null;last=0;resetAI();render();}
    if(mode!=='live'||(!visible&&!force)||pending||(!force&&Date.now()-last<60000))return;
    pending=true;
    const g=generation;
    try{
      const response=await request('/api/studies/'+encodeURIComponent(selected)+'?tf='+$('study-tf').value+'&section='+section,'GET',undefined,45000);
      if(g===generation){if(data?.times[section]!==response.times[section])resetAI();data=response;render();}
    }catch(e){if(g===generation){data=null;render();$('study-status').textContent='研究更新失败 · '+e.message;}}
    finally{if(g===generation){last=Date.now();pending=false;}}
  }
  window.openStudySection=name=>{
    if(section!==name){section=name;resetAI();}
    sync();
  };
  $('study-tf').onchange=()=>sync(true);
  $('study-journal-link').addEventListener('click',()=>{
    $('journal-scope').value='current';
    $('journal-kind').value=section==='longterm'?'timing':'';
    $('journal-tf').value=section==='intraday'?'1m':section==='longterm'?'1D':$('study-tf').value;
  });
  $('study-refresh').onclick=()=>sync(true);
  for(const input of $('study-layers').querySelectorAll('input'))bindLayer(input.id,render);
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
    const slot=Math.floor((coords.x-10)*count/(900-68-10));
    const row=section==='intraday'?rows.find(b=>minute(b.time)===slot):rows[slot];
    const hint=e.target.closest('[data-plot-hint]')?.dataset.plotHint;
    if(!row&&!event){tip.hidden=true;return;}
    if(event)tip.textContent=event.status+'\n'+event.facts.join('\n');
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
  for(const name of ['pointermove','pointerdown','focusin'])charts.addEventListener(name,showHint);
  function clearTips(){for(const tip of charts.querySelectorAll('output'))tip.hidden=true;}
  charts.addEventListener('pointerout',e=>{if(e.target.closest('figure')!==e.relatedTarget?.closest?.('figure'))clearTips();});
  charts.addEventListener('focusout',clearTips);
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
