'use strict';
(() => {
  const panel=$('study-journal');
  const periods={'1M':'月线','4h':'4 小时','30m':'30 分钟','5m':'5 分钟','1m':'1 分钟','15m':'15 分钟','60m':'1 小时','1D':'日线','1W':'周线'};
  const eastern=new Intl.DateTimeFormat('sv-SE',{timeZone:'America/New_York',dateStyle:'short',timeStyle:'medium'});
  const date=value=>eastern.format(new Date(value));
  const decline=value=>value==null?'—':number(value)+'%';
  let generation=0, lastKey='';

  function table(headings,rows){
    return '<table><thead><tr>'+headings.map(h=>'<th scope="col">'+h+'</th>').join('')+
      '</tr></thead><tbody>'+rows.map(cells=>'<tr>'+cells.map(c=>'<td>'+c+'</td>').join('')+'</tr>').join('')+
      '</tbody></table>';
  }
  function query(){
    return new URLSearchParams({code:$('journal-scope').value==='current'?selected:'',
      tf:$('journal-tf').value,kind:$('journal-kind').value,horizon:$('journal-horizon').value}).toString();
  }
  function evidence(row){
    const facts=row.evidence.facts.map(f=>'<p>'+esc(f)+'</p>').join('');
    return '<details><summary>'+esc(row.evidence.title)+' · '+esc(row.evidence.status)+'</summary>'+
      facts+'<p>实际写入 '+esc(date(row.recorded))+' ET</p></details>';
  }
  async function load(){
    if(panel.hidden)return;
    const id=++generation, key=query(), changed=key!==lastKey;
    lastKey=key;
    if(changed){$('journal-groups').replaceChildren();$('journal-samples').replaceChildren();$('platform-comparison').replaceChildren();}
    $('journal-status').textContent='正在读取本机研究记录…';
    try{
      const data=await request('/api/study-journal?'+key);
      if(id!==generation||panel.hidden||key!==query())return;
      const kinds=$('journal-kind');
      if(kinds.options.length<=2)
        for(const [value,name] of Object.entries(data.kinds)){
          if(value!=='timing')kinds.add(new Option(name,value));
        }
      const total=data.groups.reduce((sum,g)=>sum+g.total,0);
      const mature=data.groups.reduce((sum,g)=>sum+g.mature,0);
      const stages=data.platform_comparison||[];
      $('platform-comparison').innerHTML=stages.length?'<h3>分时突破回落率</h3><p class="muted small">从各阶段收盘起算。观察窗口内，任一分钟收盘触及或越回原边界即计一次回落。等待期间变动按突破方向折算，以进入确认阶段的样本计算。</p><div class="bt-table-wrap">'+
        table(['方向','阶段','回落 / 走满窗口','回落率','等待确认期间平均变动'],stages.map(s=>[
          s.side===1?'上破':'下破',esc(data.kinds[s.kind]),(s.returned||0)+' / '+s.mature,
          s.mature?number(100*s.returned/s.mature,1)+'%':'—',s.kind==='minute_confirmed'?pct(s.wait_move):'—']))+'</div>':'';
      $('journal-status').textContent='真实行情 · '+total+' 条确认记录 · '+mature+' 条已走满窗口 · '+data.status;
      $('journal-groups').innerHTML=total?table(['指标 / 状态','周期','已走满 / 总数','平均涨跌','平均最大下探','最深下探'],
        data.groups.map(g=>[esc(data.kinds[g.kind])+' · '+esc(g.status),periods[g.tf],g.mature+' / '+g.total,
          pct(g.mean_return),decline(g.mean_mae),decline(g.worst_mae)])):'当前筛选条件下暂无记录。';
      $('journal-samples').innerHTML=data.latest.length?table(['确认时间 ET','股票','周期','信号与依据','确认价','窗口涨跌','最大下探'],
        data.latest.map(r=>[esc(date(r.confirmed)),esc(r.symbol),periods[r.tf],evidence(r),number(r.price),
          r.return_pct==null?'未走满或缺数据':pct(r.return_pct),decline(r.mae_pct)])):'';
    }catch(error){
      if(id===generation)$('journal-status').textContent='读取失败 · '+error.message;
    }
  }
  for(const name of ['scope','tf','kind','horizon'])$('journal-'+name).addEventListener('change',load);
  $('journal-refresh').addEventListener('click',load);
  window.openJournal=load;
  window.syncJournal=()=>{if(!panel.hidden && lastKey!==query())load();};
})();
