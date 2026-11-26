'use strict';
(() => {
  const field = $('fj-text'), submit = $('fj-submit'), profile = $('fj-profile');
  const status = $('fj-status'), result = $('fj-result'), frame = $('fj-frame');
  function updateDraft() {
    submit.disabled = !field.value.trim();
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
    field.disabled = profile.disabled = submit.disabled = true;
    result.textContent = '';
    status.textContent = '正在解读这条消息…';
    try {
      const answer = await request('/api/news/analysis?profile='+profile.value,'POST',{text:field.value.trim()},200000);
      result.textContent = answer.text;
      status.textContent = [answer.receipt.returned_model || answer.model,
        '请求强度 '+(answer.receipt.requested_effort || '模型默认'),
        '返回强度 '+(answer.receipt.returned_effort || '未返回'),
        (answer.tokens.total_tokens ?? '未返回')+' tokens',answer.cached?'复用上次结果':''].filter(Boolean).join(' · ');
      document.dispatchEvent(new Event('trenddesk-ai-usage'));
    } catch(error) {
      status.textContent = '解读失败 · '+error.message;
    } finally {
      field.disabled = profile.disabled = false;
      submit.disabled = !field.value.trim();
    }
  });
})();
