'use strict';
function createPriceChart(host,info,scope,getModel){
  let chartGeometry=null,drag=null,chartCount=90,chartOffset=0;
  function drawChart(){
    const model=getModel(),bars=model.bars||[],timeframe=model.tf;
    if(!bars.length){chartGeometry=null;info.textContent='开 —　高 —　低 —　收 —';if(scope==='study'){host.textContent='暂无已收盘 K 线';return}host.innerHTML='<div class="empty-chart"><div class="empty-icon">⌁</div><h3>等待第一组行情</h3><p>启动并登录 Moomoo OpenD 后，历史 K 线会自动同步到这里。</p><button id="empty-demo" class="button">先看看演示界面 ↗</button></div>';$('empty-demo').onclick=toggleMode;return}
    const width=host.clientWidth||700,height=host.clientHeight||330,right=60,left=8,top=12,bottom=28,volumeHeight=48,priceBottom=height-bottom-volumeHeight-15;
    const slots=Math.min(chartCount,bars.length);
    chartOffset=Math.max(-Math.floor(slots*.8),Math.min(chartOffset,bars.length-slots));
    const start=bars.length-chartOffset-slots,visible=bars.slice(start,start+slots);
    const plotWidth=width-left-right,step=plotWidth/slots;
    const average=(index,n)=>index<n-1?null:bars.slice(index-n+1,index+1).reduce((s,b)=>s+b.close,0)/n;
    const av20=visible.map((_,i)=>average(start+i,20)),av50=visible.map((_,i)=>average(start+i,50));
    let lo=Math.min(...visible.map(b=>b.low),...av20.filter(x=>x!=null),...av50.filter(x=>x!=null)),hi=Math.max(...visible.map(b=>b.high),...av20.filter(x=>x!=null),...av50.filter(x=>x!=null));
    const padding=Math.max((hi-lo)*.12,hi*.001);lo-=padding;hi+=padding;
    const y=value=>top+(hi-value)/(hi-lo)*(priceBottom-top),x=i=>left+(i+.5)*step;
    const maxVolume=Math.max(1,...visible.map(b=>b.volume));
    const group=(hint,shape)=>`<g data-chart-tip="${esc(hint)}">${shape}</g>`;
    function curve(path,c,hint,dash='',weight=1.3){
      if(!path)return '';
      return group(hint,`<path d="${path}" stroke="${c}" stroke-width="${weight}" stroke-dasharray="${dash}" fill="none"/><path d="${path}" stroke="transparent" stroke-width="8" fill="none"/>`);
    }
    let svg=`<svg viewBox="0 0 ${width} ${height}" aria-hidden="true"><defs><clipPath id="plot-clip-${scope}"><rect x="${left}" y="${top}" width="${plotWidth}" height="${priceBottom-top}"/></clipPath></defs>`;
    for(let i=0;i<5;i++){
      const value=lo+(hi-lo)*i/4,yy=y(value);
      svg+=group('价格刻度 · '+number(value)+' 美元',`<line x1="${left}" x2="${width-right}" y1="${yy}" y2="${yy}" stroke="#2b332d" stroke-dasharray="2 4"/><text x="${width-right+10}" y="${yy+3}" fill="#849386" font-size="9">${number(value)}</text>`);
    }
    visible.forEach((b,i)=>{
      const xx=x(i),c=b.close>=b.open?'#91d6b0':'#d99986',cw=Math.max(1,step*.62);
      const vol=b.volume/maxVolume*volumeHeight,opacity=b.complete===false?.45:1;
      svg+=group(`影线 · 最高 ${number(b.high)} / 最低 ${number(b.low)} 美元`,`<line x1="${xx}" x2="${xx}" y1="${y(b.high)}" y2="${y(b.low)}" stroke="${c}" opacity="${opacity}"/><line x1="${xx}" x2="${xx}" y1="${y(b.high)}" y2="${y(b.low)}" stroke="transparent" stroke-width="5"/>`);
      svg+=group(`K 线实体 · 开 ${number(b.open)} / 收 ${number(b.close)} 美元${b.complete===false?' · 未收盘':''}`,`<rect x="${xx-cw/2}" y="${Math.min(y(b.open),y(b.close))}" width="${cw}" height="${Math.max(1,Math.abs(y(b.close)-y(b.open)))}" fill="${c}" opacity="${opacity}"/>`);
      svg+=group(`该周期成交量 · ${number(b.volume,0)} 股`,`<rect x="${xx-cw/2}" y="${height-bottom-vol}" width="${cw}" height="${Math.max(1,vol)}" fill="${c}" opacity=".28"/>`);
    });
    for(const [values,c,n] of [[av20,'#d8bc75',20],[av50,'#89afd5',50]]){
      let path='';values.forEach((v,i)=>{if(v!=null)path+=`${path?'L':'M'}${x(i)},${y(v)} `});
      svg+=curve(path,c,`MA${n} · 最近 ${n} 根 K 线的平均收盘价`);
    }
    svg+=`<g clip-path="url(#plot-clip-${scope})">`;
    if(model.showLines && chartOffset<=0){
      const times=new Map(bars.map((b,i)=>[b.time,i-start]));
      for(const [label,t1,v1,t2,v2,level] of model.lines||[]){
        const i=times.get(t1),j=times.get(t2);
        if(!Number.isFinite(i)||!Number.isFinite(j)||j<=i||j<0)continue;
        const channel=label.startsWith('通道'),box=label.startsWith('平台'),support=label.startsWith('支撑');
        const description=channel?'历史价格拟合的趋势边界':box?'历史整理区间的边界':support?'价格曾获得支撑的位置':'价格曾遇到阻力的位置';
        svg+=curve(`M${x(i)} ${y(v1)}L${x(j)} ${y(v2)}`,channel?'#90b7e4':box?'#cb9fdb':support?'#94d8b0':'#e9bd75',`${label} · ${description} · ${number(v1)} → ${number(v2)} 美元${levelHint(level)}`,levelStyle(level).dash,levelStyle(level).width);
      }
      if(!model.lines?.length){
        const a=model.analysis;
        for(const [v,label,c] of [[a?.resistance,'小时阻力','#d8bc75'],[a?.support,'小时支撑','#89afd5']]){
          if(v!=null)svg+=curve(`M${left} ${y(v)}H${x(visible.length-1)}`,c,`${label} · 信号开始前 20 根小时线的区间边界 · 强弱未分级 · ${number(v)} 美元`,'5 6');
        }
      }
    }
    if(model.showCross&&chartOffset<=0)svg+=crossOverlay(model.zones,lo,hi,y,left,x(visible.length-1),'data-chart-tip');
    const timeIndex=new Map(bars.map((b,i)=>[b.time,i-start]));
    for(const [id,shape] of model.patterns||[]){
      const {points=[],neck=[],candles=[],pending}=shape.overlay;
      const color=pending?'#eec27c':'#d6a8fa', hint=shape.title+' · '+shape.status;
      const path=anchors=>anchors.map(([t,p],i)=>(i?'L':'M')+x(timeIndex.get(t))+' '+y(p)).join(' ');
      const onChart=anchors=>anchors.length&&anchors.every(([t])=>timeIndex.has(t));
      svg+='<g data-pattern="'+esc(id)+'">';
      if(onChart(points)){
        svg+=curve(path(points),color,hint,pending?'5 4':'',2.6);
        for(const [t,p] of points)svg+=group(hint+' · 拐点 '+number(p),`<circle cx="${x(timeIndex.get(t))}" cy="${y(p)}" r="3" fill="${color}"/>`);
      }
      if(onChart(neck))svg+=curve(path(neck),color,hint+' · 颈线','9 3 2 3',2);
      if(onChart(candles)){
        const x1=x(timeIndex.get(candles[0][0]))-step*.47,x2=x(timeIndex.get(candles.at(-1)[0]))+step*.47;
        const topY=y(Math.max(...candles.map(p=>p[2])))-3,botY=y(Math.min(...candles.map(p=>p[1])))+3;
        svg+=group(hint,`<rect x="${x1}" y="${topY}" width="${x2-x1}" height="${botY-topY}" stroke="${color}" stroke-width="2" fill="${color}" fill-opacity=".12"/>`);
      }
      svg+='</g>';
    }
    const last=visible.at(-1),priceLabel=`可见末根 K 线${last.complete===false?'暂时价格':'收盘价'} · ${number(last.close)} 美元`;
    svg+=curve(`M${left} ${y(last.close)}H${x(visible.length-1)}`,'#9ab58c',priceLabel,'3 4')+'</g>';
    svg+=group(priceLabel,`<rect x="${width-right+3}" y="${y(last.close)-9}" width="55" height="18" rx="3" fill="#b9df9d"/><text x="${width-right+7}" y="${y(last.close)+3}" fill="#24311f" font-size="9">${number(last.close)}</text>`);
    for(const index of new Set([0,1,2,3,4].map(i=>Math.floor((slots-1)*i/4)))){
      const b=visible[index];if(!b)continue;
      const label=timeframe==='1M'?b.time.slice(0,7):timeframe==='1W'||timeframe==='1D'?b.time.slice(0,10):timeText(b.time);
      svg+=group('周期起点 · '+chartStamp(b.time,getModel().tf)+' ET',`<text x="${x(index)}" y="${height-7}" text-anchor="${index===0?'start':index===slots-1?'end':'middle'}" fill="#7c8d7f" font-size="9">${esc(label)}</text>`);
    }
    svg+='<g data-part="crosshair" pointer-events="none" style="display:none"><line data-part="cross-x" stroke="#96a78e" stroke-dasharray="3 4"/><line data-part="cross-y" stroke="#96a78e" stroke-dasharray="3 4"/></g></svg><output data-part="market-tip" class="chart-tip" hidden></output>';
    host.innerHTML=svg;chartGeometry={left,right,width,height,step,visible,av20,av50};setCandleInfo(last);

  }
  function setCandleInfo(b){info.textContent=`${chartStamp(b.time,getModel().tf)}　开 ${number(b.open)}　高 ${number(b.high)}　低 ${number(b.low)}　收 ${number(b.close)}　量 ${Intl.NumberFormat('en',{notation:'compact',maximumFractionDigits:1}).format(b.volume)}${b.complete===false?' · 未收盘':''}`}
  host.addEventListener('wheel',e=>{if(!chartGeometry)return;e.preventDefault();zoom(e.deltaY>0?10:-10)},{passive:false});
  function scoreMarketPoint(e){
    const g=chartGeometry;if(!g||!getModel().canScore)return;
    const px=e.clientX-host.getBoundingClientRect().left;
    const b=px>=g.left&&px<g.width-g.right?g.visible[Math.floor((px-g.left)/g.step)]:null;
    if(!b||b.complete===false){toast('请选择已收盘的 K 线');return}
    pointScores.pick(scope,b.time);
  }
  host.addEventListener('contextmenu',e=>{if(chartGeometry){e.preventDefault();scoreMarketPoint(e)}});
  host.addEventListener('pointerdown',e=>{if(!chartGeometry||e.button!==0)return;drag={x:e.clientX,y:e.clientY,moved:false,offset:chartOffset};host.setPointerCapture(e.pointerId)});
  host.addEventListener('pointerup',e=>{
    if(drag&&!drag.moved&&Math.hypot(e.clientX-drag.x,e.clientY-drag.y)<5&&window.pointScores?.enabled(scope))scoreMarketPoint(e);
    drag=null;
  });
  host.addEventListener('pointercancel',()=>drag=null);
  host.addEventListener('pointermove',e=>{
    const g=chartGeometry;if(!g)return;
    if(drag){if(Math.hypot(e.clientX-drag.x,e.clientY-drag.y)>=5)drag.moved=true;chartOffset=drag.offset+Math.round((e.clientX-drag.x)/g.step);drawChart();return}
    const host=host,r=host.getBoundingClientRect(),px=e.clientX-r.left,py=e.clientY-r.top;
    const index=Math.floor((px-g.left)/g.step),bar=g.visible[index],tip=host.querySelector('[data-part="market-tip"]');
    const inPlot=px>=g.left&&px<g.width-g.right;
    let hint=e.target.closest('[data-chart-tip]')?.dataset.chartTip||'';
    if(bar){
      setCandleInfo(bar);
      for(const [prefix,values] of [['MA20',g.av20],['MA50',g.av50]])if(hint.startsWith(prefix+' ·'))hint+=' · '+number(values[index])+' 美元';
    }else if(inPlot){
      info.textContent='未来区域 · 尚无 K 线或成交量';
      if(!hint)hint='未来区域 · 尚无行情数据';
    }
    if(tip){
      tip.textContent=hint;tip.hidden=!hint;
      tip.style.left=Math.max(0,Math.min(px+12,r.width-tip.offsetWidth))+'px';
      tip.style.top=Math.max(0,Math.min(py+12,r.height-tip.offsetHeight))+'px';
    }
    const cross=host.querySelector('[data-part="crosshair"]');cross.style.display=inPlot?'':'none';
    for(const [node,attrs] of [[host.querySelector('[data-part="cross-x"]'),{x1:px,x2:px,y1:0,y2:g.height-25}],[host.querySelector('[data-part="cross-y"]'),{x1:g.left,x2:g.width-g.right,y1:py,y2:py}]]){
      for(const [k,v] of Object.entries(attrs))node.setAttribute(k,v);
    }
  });
  host.addEventListener('pointerleave',()=>{
    if(host.querySelector('[data-part="crosshair"]'))host.querySelector('[data-part="crosshair"]').style.display='none';
    if(host.querySelector('[data-part="market-tip"]'))host.querySelector('[data-part="market-tip"]').hidden=true;
    if(chartGeometry)setCandleInfo(chartGeometry.visible.at(-1));
  });
  function reset(){chartCount=90;chartOffset=0;drawChart()}
  function zoom(amount){chartCount=Math.max(25,Math.min(240,chartCount+amount));drawChart()}
  function reveal(overlay){
    const times=[...(overlay.points||[]),...(overlay.neck||[]),...(overlay.candles||[])].map(p=>p[0]);
    const bars=getModel().bars||[],first=bars.findIndex(b=>times.includes(b.time));
    if(first<0)return;
    const slots=Math.min(chartCount,bars.length),start=bars.length-chartOffset-slots;
    const last=bars.findLastIndex(b=>times.includes(b.time));
    if(first<start||last>=start+slots){chartCount=Math.min(240,Math.max(chartCount,last-first+6));chartOffset=Math.max(0,bars.length-last-4)}
  }
  host.addEventListener('dblclick',reset);
  new ResizeObserver(()=>{if(host.clientWidth)drawChart()}).observe(host);
  return {draw:drawChart,reset,zoom,reveal};
}
