'use strict';
(() => {
  const origin = location.ancestorOrigins[0];
  if (!['http://127.0.0.1:8765','http://localhost:8765'].includes(origin)) return;
  const button = document.createElement('button');
  button.type = 'button';
  button.textContent = 'AI 解读';
  button.style.cssText = 'position:fixed;z-index:2147483647;border:1px solid #85bda9;border-radius:6px;padding:5px 10px;background:#143a32;color:white;cursor:pointer;font:600 13px sans-serif';
  button.hidden = true;
  document.body.append(button);
  function update() {
    const selection = window.getSelection();
    button.hidden = !selection?.rangeCount || selection.isCollapsed;
    if (button.hidden) return;
    const rect = selection.getRangeAt(0).getBoundingClientRect();
    button.style.left = Math.max(2,Math.min(innerWidth-button.offsetWidth-4,rect.left))+'px';
    button.style.top = (rect.bottom+button.offsetHeight+5<innerHeight ? rect.bottom+4 : Math.max(2,rect.top-button.offsetHeight-4))+'px';
  }
  document.addEventListener('selectionchange',update);
  document.addEventListener('scroll',update,true);
  button.addEventListener('mousedown',event=>event.preventDefault());
  button.addEventListener('click',event=>{
    if (!event.isTrusted) return;
    const text = window.getSelection()?.toString().trim();
    if (text) window.parent.postMessage({type:'trenddesk-news-selection',text:text.slice(0,1200)},origin);
    button.hidden = true;
  });
})();
