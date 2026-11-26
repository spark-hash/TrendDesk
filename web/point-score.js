'use strict';
window.pointScores=(()=>{
  const views={};
  const stamp=value=>value?new Intl.DateTimeFormat('zh-CN',{timeZone:'America/New_York',year:'numeric',month:'2-digit',day:'2-digit',hour:'2-digit',minute:'2-digit',hourCycle:'h23'}).format(new Date(value))+' ET':'—';
  function display(v,score){
    v.score=score;v.seq++;
    v.root.querySelector('[data-answer]').textContent='';
    v.root.querySelector('[data-latest]').hidden=!(v.at&&v.latest);
    const result=v.root.querySelector('[data-result]');
    if(!score){result.replaceChildren();return}
    const minute=v.tf==='1m', title=minute?(v.at?'所选分钟':'最新已收盘分钟'):'所选 K 线';
    const details=score.setups.map(s=>'<h4>'+esc(s.name)+' · '+(s.total??'—')+'/100</h4>'+
      s.rows.map(r=>'<div class="entry-factor"><strong>'+(r.points??'—')+'/'+r.limit+'</strong> '+esc(r.label)+'<p>'+esc(r.evidence)+'</p></div>').join('')).join('');
    result.innerHTML='<h3>'+esc(v.symbol)+' · '+title+'开仓评分　'+(score.total??'—')+'/100</h3>'+
      '<p>'+esc(score.verdict)+' · '+stamp(score.cutoff)+'</p><small>'+
      (v.mode==='demo'?'合成演示 · ':'')+(minute?'分钟收盘规则 · 仅用截至该分钟的数据':'按当前参数重算当时的突破和回调条件 · 最近 15 分钟收盘 '+stamp(score.as_of))+
      '</small>'+(details?'<details><summary>逐项得分与依据</summary>'+details+'</details>':'')+
      (score.total!=null&&v.mode==='live'?'<div class="ai-controls"><select aria-label="选点评分 AI 模式"><option value="routine">快速解读</option><option value="deep">深入分析</option></select><button type="button" data-ai>AI 解读此时点</button></div>':'');
  }
  async function pick(name,at){
    const v=views[name];if(v.root.hidden||v.symbol!==selected||v.mode!==mode)return;
    v.at=at;display(v,null);const n=v.seq,result=v.root.querySelector('[data-result]');
    result.textContent='正在读取 '+v.symbol+' '+stamp(at)+' 对应的已收盘行情…';
    try{
      const score=await request('/api/point-score/'+encodeURIComponent(v.symbol)+'?'+new URLSearchParams({tf:v.tf,at,mode:v.mode}),'GET',undefined,90000);
      if(n===v.seq)display(v,score);
    }catch(e){if(n===v.seq)result.textContent=e.message}
  }
  for(const name of ['market','study']){
    const root=$(name+'-point'),v=views[name]={root,seq:0,enabled:false};
    root.addEventListener('click',async e=>{
      const b=e.target.closest('button');if(!b)return;
      if(b.hasAttribute('data-pick')){
        v.enabled=!v.enabled;b.setAttribute('aria-pressed',String(v.enabled));return;
      }
      if(b.hasAttribute('data-latest')){v.at=null;display(v,v.latest);return}
      if(!b.hasAttribute('data-ai')||!v.score||v.symbol!==selected||v.mode!==mode)return;
      const n=v.seq,out=root.querySelector('[data-answer]');
      b.disabled=true;out.textContent='正在解读所选时点…';
      const q=new URLSearchParams({tf:v.tf,at:v.score.at,profile:root.querySelector('select').value,snapshot_id:v.score.snapshot_id||''});
      try{
        const a=await request('/api/ai/point-score/'+encodeURIComponent(v.symbol)+'?'+q,'POST',undefined,210000);
        document.dispatchEvent(new Event('trenddesk-ai-usage'));
        if(n===v.seq)out.textContent=(a.receipt?.returned_model||a.model)+' · '+(a.tokens?.total_tokens??'—')+' tokens\n'+a.text;
      }catch(err){if(n===v.seq)out.textContent=err.message}
      finally{if(n===v.seq)b.disabled=false}
    });
  }
  function sync(name,symbol,tf,visible,latest=null){
    const v=views[name],key=[symbol,tf,mode,visible].join('/');
    v.root.hidden=!visible;
    if(v.key!==key){
      Object.assign(v,{key,symbol,tf,mode,at:null,latest,enabled:false});
      v.root.querySelector('[data-pick]').setAttribute('aria-pressed','false');display(v,latest);
    }else{
      const changed=latest?.as_of!==v.latest?.as_of||latest?.snapshot_id!==v.latest?.snapshot_id;
      v.latest=latest;if(!v.at&&changed)display(v,latest);
    }
  }
  return {sync,pick,enabled:name=>views[name].enabled};
})();
