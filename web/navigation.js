'use strict';
(() => {
  const routes=new Map([
    ['market',['market','行情看板']],
    ['studies',['stock','个股研究','structure']],
    ['intraday',['stock','个股研究','intraday']],
    ['fundamental',['stock','个股研究','fundamental']],
    ['longterm',['stock','个股研究','longterm']],
    ['research',['stock','个股研究']],
    ['macro-section',['news','宏观与新闻']],
    ['macro-bubble',['news','宏观与新闻']],
    ['financialjuice',['news','宏观与新闻']],
    ['events-section',['events','信号与回测']],
    ['study-journal',['events','信号与回测']],
    ['backtest-section',['events','信号与回测']]
  ]);
  function setCurrent(link,active){
    if(active)link.setAttribute('aria-current','page');
    else link.removeAttribute('aria-current');
  }
  function syncTickerControl(){
    const id=location.hash.slice(1);
    $('ticker-control').hidden=routes.get(id)?.[0]!=='stock' &&
      !(id==='events-section' && $('event-filter').value==='selected') &&
      !(id==='study-journal' && $('journal-scope').value==='current');
  }
  function show(){
    const target=location.hash.slice(1);
    const id=routes.has(target)?target:'market';
    const [area,title,study]=routes.get(id);
    const view=study?'studies':id==='macro-bubble'?'macro-section':id;
    for(const el of document.querySelectorAll('[data-view]'))el.hidden=el.dataset.view!==view;
    $('view-tools').hidden=!['stock','news','events'].includes(area);
    syncTickerControl();
    $('stock-links').hidden=area!=='stock';
    $('news-links').hidden=area!=='news';
    $('journal-links').hidden=area!=='events';
    for(const link of document.querySelectorAll('.primary-nav a'))setCurrent(link,link.dataset.area===area);
    for(const link of document.querySelectorAll('#view-tools nav a'))setCurrent(link,link.hash==='#'+id);
    const subsection=document.querySelector('#view-tools nav a[aria-current]')?.textContent;
    $('view-area').textContent=subsection?title:'美股趋势工作台';
    $('view-title').textContent=subsection||title;
    document.title=[subsection,title,'TrendDesk'].filter(Boolean).join(' · ');
    if(study)window.openStudySection(study);
    if(view==='macro-section')window.openMacro(id==='macro-bubble'?'bubble':'all');
    if(id==='study-journal')window.openJournal();
    if(id==='backtest-section')window.openBacktests();
    if(id==='financialjuice'&&!$('fj-frame').hasAttribute('src'))$('fj-frame').src=$('fj-frame').dataset.src;
    if(id==='market'&&state)drawChart();
    window.scrollTo(0,0);
  }
  let optionsKey='';
  window.syncNavSymbol=()=>{
    if(!state)return;
    const stocks=[...new Set([...state.watchlist,'SPY','QQQ',selected])];
    const signature=stocks.join(',');
    if(signature!==optionsKey){
      $('view-symbol').replaceChildren(...stocks.map(s=>new Option(s,s)));
      optionsKey=signature;
    }
    $('view-symbol').value=selected;
  };
  $('view-symbol').onchange=e=>{
    selectSymbol(e.target.value);
    window.syncJournal();
  };
  $('event-filter').addEventListener('change',syncTickerControl);
  $('journal-scope').addEventListener('change',syncTickerControl);
  window.addEventListener('hashchange',show);
  show();
  window.syncNavSymbol();
})();
