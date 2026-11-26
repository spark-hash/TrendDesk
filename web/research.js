'use strict';
(() => {
  const labels = {breakout:'顺势突破', pullback:'回调转强', near:'接近突破位'};
  let rule='顺势突破', config=null, pending=false, lastAuto='', result=null, problem='';
  let lastSelection='';
  let deepResult=null;
  let catalog=[],catalogVersion=0;
  const effortNames={default:'模型默认',none:'关闭',low:'低',medium:'中',high:'高',xhigh:'极高'};
  function profileEditor(id, choice) {
    const models=config.model_efforts;
    const picker=$(id+'-select'), custom=$(id), strength=$(id+'-effort');
    const choices=[...new Set([...Object.keys(models),...catalog])];
    picker.replaceChildren(...choices.map(model=>new Option(model,model)),new Option('自定义模型…','custom'));
    picker.value=choices.includes(choice.model)?choice.model:'custom';
    custom.value=picker.value==='custom'?choice.model:'';
    function update(effort) {
      const isCustom=picker.value==='custom';
      custom.parentElement.hidden=!isCustom;
      custom.required=isCustom;
      const levels=models[isCustom?custom.value.trim():picker.value]||[];
      strength.replaceChildren(...['default',...levels].map(level=>new Option(effortNames[level],level)));
      strength.value=levels.includes(effort)?effort:'default';
      strength.disabled=!levels.length;
    }
    picker.onchange=()=>update('default');
    custom.oninput=()=>update('default');
    update(choice.effort);
  }
  function readChoice(id) {
    const picker=$(id+'-select').value;
    return {model:picker==='custom'?$(id).value.trim():picker, effort:$(id+'-effort').value};
  }
  function describe(choice) {
    return choice.model+'（'+effortNames[choice.effort]+'）';
  }
  const count=v=>v==null?'未返回':Number(v).toLocaleString('zh-CN');
  async function loadUsage() {
    try {
      const u=await request('/api/ai/usage');
      $('ai-totals').textContent=`本机累计（从启用统计起） · ${count(u.calls||0)} 次有用量回报的调用\n输入 ${count(u.input_tokens||0)} · 输出 ${count(u.output_tokens||0)} · 合计 ${count(u.total_tokens||0)} tokens`;
      const l=u.latest;
      $('ai-limits').textContent=l?`最近响应 · ${l.model} · ${timeText(l.time)} ET\n请求剩余 / 上限：${l.remaining_requests??'未返回'} / ${l.limit_requests??'未返回'}，当时距重置 ${l.reset_requests??'未知'}\nToken 剩余 / 上限：${l.remaining_tokens??'未返回'} / ${l.limit_tokens??'未返回'}，当时距重置 ${l.reset_tokens??'未知'}`:'收到模型响应后显示该模型的限流窗口快照。';
    } catch(e) {$('ai-totals').textContent=e.message;}
  }
  $('ai-usage').ontoggle=()=>{if($('ai-usage').open)void loadUsage();};
  document.addEventListener('trenddesk-ai-usage',()=>{if($('ai-usage').open)void loadUsage();});
  async function loadCatalog() {
    const version=++catalogVersion;
    const info=$('ai-catalog-info'), list=$('ai-model-list');
    if(!config?.configured){info.textContent='请先保存 API Key，然后刷新清单。';return;}
    info.textContent='正在读取当前 Key 的模型…';
    try {
      const data=await request('/api/ai/models','POST');
      if(version!==catalogVersion)return;
      catalog=data.models;
      for(const id of ['ai-model','ai-deep-model'])profileEditor(id,readChoice(id));
      info.textContent=`OpenAI 返回 ${catalog.length} 个模型 ID。列表包含不同用途的模型，行情解读需支持 Responses 文本输出。`;
      list.textContent=catalog.join('\n');
    } catch(e){if(version===catalogVersion){info.textContent=e.message;list.textContent='';}}
  }
  $('ai-list-models').onclick=loadCatalog;
  $('ai-catalog').ontoggle=()=>{if($('ai-catalog').open&&!catalog.length)void loadCatalog();};
  function showReceipt(id, answer) {
    const el=$(id), receipt=answer?.receipt;
    el.hidden=!receipt;
    if(!receipt) return;
    el.querySelector('summary').textContent='调用凭据 · '+(answer.cached?'本地缓存':'本次 API 调用');
    el.querySelector('pre').textContent=[
      '请求模型  '+receipt.requested_model,
      '请求 reasoning.effort  '+(receipt.requested_effort??'未传，由模型使用默认值'),
      'OpenAI 返回模型  '+(receipt.returned_model??'未返回'),
      'OpenAI 返回 reasoning.effort  '+(receipt.returned_effort??'未返回'),
      'OpenAI 请求 ID  '+(receipt.request_id??'未返回')
      ,`该响应 token  输入 ${count(answer.tokens?.input_tokens)} · 输出 ${count(answer.tokens?.output_tokens)}（含推理 ${count(answer.tokens?.reasoning_tokens)}）· 合计 ${count(answer.tokens?.total_tokens)}`
    ].join('\n');
  }
  function facts(analysis, name) {
    return analysis.conditions.filter(c=>c.group==='共同条件' || c.group===name ||
      (name!=='接近突破位' && c.group==='入场量能'));
  }
  function rows(conditions, interactive=false) {
    return conditions.map(c=>`<div class="research-row"><strong class="${c.met?'positive':'muted'}">${c.met?'✓ 满足':'· 未满足'}</strong><div><b>${esc(c.label)}</b><small>${esc(c.evidence)}</small>${interactive?`<button class="text-button" data-condition="${esc(c.label)}" data-group="${esc(c.group)}">AI 解读</button>`:''}</div></div>`).join('');
  }
  let conditionSeq=0;
  $('research-checks').addEventListener('click',async e=>{
    const b=e.target.closest('[data-condition]'), a=current()?.analysis;
    if(!b||mode!=='live'||!a?.bar_close_time)return;
    const seq=++conditionSeq, ticker=selected, stamp=a.bar_close_time;
    const query=new URLSearchParams({label:b.dataset.condition,group:b.dataset.group,as_of:stamp,profile:$('condition-profile').value});
    const output=$('condition-answer');
    output.textContent='正在解读 '+b.dataset.condition+'…';
    try{
      const ans=await request('/api/ai/condition/'+encodeURIComponent(ticker)+'?'+query,'POST',undefined,205000);
      if(seq===conditionSeq && selected===ticker && mode==='live')output.textContent=ans.focus+' · '+ans.as_of+' · '+(ans.receipt.returned_model||ans.model)+' · '+(ans.tokens.total_tokens??'未返回')+' tokens\n'+ans.text;
      document.dispatchEvent(new Event('trenddesk-ai-usage'));
    }catch(error){if(seq===conditionSeq && selected===ticker)output.textContent=error.message;}
  });
  window.conditionEvidence = e => {
    if(!labels[e.kind] || !e.payload?.conditions?.some(c=>c.group)) return '';
    return '<h4>提醒触发时的指标</h4>'+rows(facts(e.payload,labels[e.kind]));
  };
  function draw() {
    const item=current(), a=item?.analysis, live=mode==='live';
    const selection=mode+'/'+selected;
    if(selection!==lastSelection) {
      conditionSeq++;$('condition-answer').textContent='';
      lastSelection=selection; result=null; deepResult=null; problem=''; lastAuto=''; $('ai-auto').checked=false;
      if(a?.signals?.length) rule=labels[a.signals[0].kind]||rule;
    }
    $('research-symbol').textContent=selected+' · 短线信号条件';
    $('research-time').textContent=a?.bar_close_time?'15 分钟收盘 '+timeText(a.bar_close_time)+' ET':'等待已收盘 K 线';
    const active=a?.signals?.map(s=>s.title)||[];
    const context=!live?'演示行情':!state?.connected?'行情已断开':!state.market.open&&!state.market.close_confirmation?'收盘复盘':
      !item?.synced||!a?.fresh?'行情同步中':!item?.quote_fresh?'报价已过期':'常规时段监控';
    $('research-context').textContent=context+' · '+(active.length?'本根满足 '+active.join('、'):'本根暂无完整信号');
    const selectedFacts=a?facts(a,rule):[];
    document.querySelectorAll('#research-tabs button').forEach(b=>b.classList.toggle('active',b.dataset.rule===rule));
    $('research-checks').innerHTML=selectedFacts.length?rows(selectedFacts,live):'<p class="muted">等待可评估的历史数据。</p>';
    const marketOpen=state?.market.open||state?.market.close_confirmation;
    const eligible=live && item && a.ready && a.fresh && (!marketOpen || (item.synced && item.quote_fresh && state.connected));
    $('ai-request').disabled=!config?.configured || !eligible || pending;
    $('ai-deep').disabled=$('ai-request').disabled;
    $('ai-auto').disabled=!live || !config?.configured;
    $('ai-settings').disabled=!live || pending || !config;
    $('research-ai-settings').disabled=$('ai-settings').disabled;
    $('ai-status').textContent=!live?'演示模式':config?
      '盘中 '+describe(config.profiles.routine)+' · 深入 '+describe(config.profiles.deep)+(config.configured?'':' · 请在「AI 接入」填写密钥。'):'正在读取配置…';
    $('ai-request').textContent=pending==='routine'?'正在解读…':'盘中快速解读';
    $('ai-deep').textContent=pending==='deep'?'正在深入分析…':'深入分析当前股票';
    const show=result && live && result.symbol===selected;
    $('ai-meta').textContent=show?`${result.symbol} · ${result.session} · K 线收盘 ${timeText(result.bar_close_time)} ET${result.quote?' · 报价 '+number(result.quote.price)+' @ '+timeText(result.quote.time)+' ET':''} · 生成 ${timeText(result.generated_at)} ET · ${result.model}${result.bar_close_time!==a?.bar_close_time?' · 已有更新 K 线':''}`:'';
    if(show) $('ai-meta').textContent+=' · '+effortNames[result.effort];
    $('ai-output').textContent=[problem,show?result.text:''].filter(Boolean).join('\n\n');
    const deep=live && deepResult?.symbol===selected ? deepResult : null;
    $('ai-deep-meta').textContent=deep?`深入分析 · ${deep.symbol} · ${deep.session} · ${describe(deep)} · K 线收盘 ${timeText(deep.bar_close_time)} ET · 生成 ${timeText(deep.generated_at)} ET${deep.bar_close_time!==a?.bar_close_time?' · 已有更新 K 线':''}`:'';
    $('ai-deep-output').textContent=deep?.text||'';
    showReceipt('ai-receipt',show?result:null);
    showReceipt('ai-deep-receipt',deep);
    const token=selection+'/'+a?.bar_close_time;
    if(eligible && marketOpen && config?.configured && $('ai-auto').checked && !pending && lastAuto!==token) {
      lastAuto=token; void getAdvice();
    }
  }
  async function getAdvice(profile='routine') {
    if(pending || mode!=='live') return;
    const ticker=selected;
    pending=profile; problem=''; draw();
    try {
      const response=await fetch('/api/ai/advice/'+encodeURIComponent(ticker)+'?profile='+profile,{method:'POST',headers:{'X-TrendDesk':'local'},signal:AbortSignal.timeout(195000)});
      const data=await response.json();
      if(!response.ok) throw new Error(data.detail || '请求失败');
      if(selected===ticker && mode==='live') {
        if(profile==='deep') deepResult=data;
        else result=data;
      }
    } catch(e) {
      if(selected===ticker && mode==='live') problem='本次未取得 AI 解读。'+e.message;
    } finally {pending=false; draw();if($('ai-usage').open)void loadUsage();}
  }
  document.querySelectorAll('#research-tabs button').forEach(b=>b.onclick=()=>{rule=b.dataset.rule;draw();});
  $('ai-request').onclick=()=>getAdvice('routine');
  $('ai-deep').onclick=()=>getAdvice('deep');
  $('ai-auto').onchange=draw;
  $('ai-settings').onclick=()=>{
    if(!config.key_storage){
      toast('当前会话仍为旧版。请先运行项目中的 Save-API-Key.cmd，完成加密保存后刷新页面。');
      return;
    }
    $('ai-key-state').textContent=({
      dpapi:'当前密钥已加密保存。',environment:'当前使用环境变量中的密钥。',
      unreadable:'当前 Windows 用户未能解密原密钥，请重新输入。',empty:'尚未保存密钥。'
    })[config.key_storage]||'';
    profileEditor('ai-model',config.profiles.routine);
    profileEditor('ai-deep-model',config.profiles.deep);
    $('ai-key').value='';$('ai-dialog').showModal();
  };
  $('ai-dialog').addEventListener('close',()=>{$('ai-key').value='';});
  $('research-ai-settings').onclick=()=>$('ai-settings').click();
  async function save(clear) {
    const payload={...readChoice('ai-model'),deep:readChoice('ai-deep-model')};
    if(clear || $('ai-key').value.trim()) payload.key=clear?'':$('ai-key').value.trim();
    try {
      config=await request('/api/ai/config','PUT',payload);
      catalogVersion++;catalog=[];$('ai-catalog').open=false;$('ai-model-list').textContent='';
      result=null;deepResult=null;problem='';if(!config.configured) $('ai-auto').checked=false;
      $('ai-dialog').close();draw();
      if(clear) toast('已清除本机密钥');
      else if(config.key_storage==='dpapi') toast('密钥已由 Windows 加密保存');
    } catch(e) { toast(e.message); }
  }
  $('ai-form').onsubmit=e=>{e.preventDefault();void save(false);};
  $('ai-clear').onclick=()=>save(true);
  window.renderResearch=draw;
  request('/api/ai/config').then(value=>{config=value;draw();}).catch(e=>{problem=e.message;draw();});
})();
