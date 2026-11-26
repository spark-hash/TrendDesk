'use strict';
function newsResearchHtml(answer){
  const sources=new Map();
  const content=answer.passages.map(part=>{
    const chars=Array.from(part.text);let cursor=0,html='';
    for(const cite of part.citations.slice().sort((a,b)=>a.after-b.after)){
      if(!/^https?:\/\//i.test(cite.url))continue;
      if(!sources.has(cite.url))sources.set(cite.url,{n:sources.size+1,title:cite.title});
      html+=esc(chars.slice(cursor,cite.after).join(''))+' <a class="news-cite" href="'+esc(cite.url)+'" target="_blank" rel="noreferrer" title="'+esc(cite.title)+'">['+sources.get(cite.url).n+']</a>';
      cursor=cite.after;
    }
    return '<p>'+html+esc(chars.slice(cursor).join(''))+'</p>';
  }).join('');
  const links=Array.from(sources,([url,s])=>'<a href="'+esc(url)+'" target="_blank" rel="noreferrer">['+s.n+'] '+esc(s.title)+' ↗</a>').join('');
  return content+'<div class="news-sources">'+links+'</div><small>'+esc(answer.receipt?.returned_model||answer.model)+' · '+esc(timeText(answer.generated_at))+' ET · '+esc(answer.tokens?.total_tokens??'—')+' tokens</small>';
}
(() => {
  const field = $('fj-text'), submit = $('fj-submit'), profile = $('fj-profile');
  const status = $('fj-status'), result = $('fj-result'), frame = $('fj-frame');
  const translate=$('fj-translate'),research=$('fj-research');
  function updateDraft() {
    research.disabled = translate.disabled = submit.disabled = !field.value.trim();
    status.textContent = '';
    result.textContent = '';
  }
  field.addEventListener('input',updateDraft);
  window.addEventListener('message',event=>{
    if (event.origin !== 'https://feed.financialjuice.com' || event.source !== frame.contentWindow) return;
    const data = event.data;
    if (data?.type !== 'trenddesk-news-selection' || typeof data.text !== 'string' || field.disabled) return;
    field.value = data.text.trim().slice(0,1200);
    updateDraft();
    field.focus();
  });
  $('fj-form').addEventListener('submit',async event=>{
    event.preventDefault();
    if (submit.disabled || !field.value.trim()) return;
    const translating=event.submitter===translate,searching=event.submitter===research;
    field.disabled = profile.disabled = research.disabled = translate.disabled = submit.disabled = true;
    result.textContent = '';
    status.textContent = translating?'正在翻译原文…':searching?'正在联网查找原文与相关报道…':'正在解读这条消息…';
    try {
      const payload={text:field.value.trim()};if(searching)payload.source='FinancialJuice';
      const answer = await request('/api/news/'+(translating?'translate':searching?'research':'analysis')+'?profile='+profile.value,'POST',payload,200000);
      if(searching)result.innerHTML=newsResearchHtml(answer);else result.textContent=answer.text;
      status.textContent = [answer.receipt.returned_model || answer.model,
        '请求强度 '+(answer.receipt.requested_effort || '模型默认'),
        '返回强度 '+(answer.receipt.returned_effort || '未返回'),
        (answer.tokens.total_tokens ?? '未返回')+' tokens',answer.cached?'复用上次结果':''].filter(Boolean).join(' · ');
      document.dispatchEvent(new Event('trenddesk-ai-usage'));
    } catch(error) {
      status.textContent = (translating?'翻译失败':'解读失败')+' · '+error.message;
    } finally {
      field.disabled = profile.disabled = false;
      research.disabled = translate.disabled = submit.disabled = !field.value.trim();
    }
  });
})();
