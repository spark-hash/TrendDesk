/* Backtest UI uses real historical data only, never the demonstration feed. */
let btJob=null,btPolling=false;
const btFields=['start','end','capital','fee_bps','slippage_bps','risk_percent','target_r','max_bars'];
const btNames={breakout:'顺势突破',pullback:'回调转强',orb15:'开盘区间突破'};
const btColors={breakout:'#bbec91',pullback:'#89afd5',orb15:'#e7b475'};
const btReasons={stop:'保护价',gap_stop:'跳空保护',target:'目标价',time_limit:'持有到期',end_of_sample:'样本结束'};
function setBacktestForm(params){
  for(const field of btFields)$('bt-'+field).value=params[field];
  $('bt-symbols').value=params.symbols.join(', ');
}
$('bt-copy').onclick=()=>{
  if(!btJob)return;
  setBacktestForm(btJob.params);
  toast('已复制股票、日期和回测表单参数；信号阈值使用当前设置。');
};

async function btList(initial=false){
  const data=await request('/api/backtests');
  if(initial){
    setBacktestForm(data.defaults);
    $('bt-end').max=data.defaults.end;$('bt-start').max=data.defaults.end;
  }
  $('bt-history').innerHTML=data.jobs.length?data.jobs.map(j=>`<option value="${esc(j.id)}">${esc(j.params.start)} → ${esc(j.params.end)} · ${j.params.symbols.length} 只 · ${esc(j.model_version||'bt-1.0')} · ${esc(({complete:'完成',running:'运行中',queued:'等待',failed:'失败',cancelled:'已取消',interrupted:'已中断'})[j.status]||j.status)}</option>`).join(''):'<option value="">暂无回测</option>';
  if(btJob)$('bt-history').value=btJob.id;
  if(initial&&data.jobs.length){btJob=await request(`/api/backtests/${data.jobs[0].id}`);btRender();}
  else if(initial)$('bt-status').textContent='选择股票和日期，比较三种策略的历史表现。首次运行需要获取历史 K 线。';
}

function btChart(results,capital,drawdown=false){
  const width=1000,height=drawdown?130:230,left=66,right=20,top=15,bottom=30;
  const series=Object.entries(results);
  let lo=drawdown?0:capital,hi=drawdown?0:capital;
  for(const [,r] of series)for(const p of r.curve){const v=drawdown?-p.drawdown_pct:p.equity;lo=Math.min(lo,v);hi=Math.max(hi,v);}
  if(hi===lo){lo-=drawdown?1:capital*.001;hi+=drawdown?0:capital*.001;}
  const y=v=>top+(hi-v)/(hi-lo)*(height-top-bottom);
  let svg=`<svg viewBox="0 0 ${width} ${height}" role="img" aria-label="${drawdown?'账户回撤曲线':'策略账户净值曲线'}">`;
  for(let i=0;i<4;i++){const v=lo+(hi-lo)*i/3;svg+=`<line x1="${left}" x2="${width-right}" y1="${y(v)}" y2="${y(v)}" stroke="#2b332e"/><text x="${left-10}" y="${y(v)+4}" text-anchor="end" fill="#929f95" font-size="11">${drawdown?v.toFixed(2)+'%':number(v,0)}</text>`;}
  series.forEach(([kind,r])=>{
    const points=r.curve,den=Math.max(points.length-1,1);
    const d=points.map((p,n)=>`${n?'L':'M'}${left+n/den*(width-left-right)},${y(drawdown?-p.drawdown_pct:p.equity)}`).join(' ');
    svg+=`<path d="${d}" fill="none" stroke="${btColors[kind]}" stroke-width="1.8"/>`;
  });
  const first=series[0]?.[1].curve;
  if(first?.length)for(const [p,x,anchor] of [[first[0],left,'start'],[first.at(-1),width-right,'end']])svg+=`<text x="${x}" y="${height-5}" text-anchor="${anchor}" fill="#929f95" font-size="11">${esc(p.time.slice(0,10))}</text>`;
  return svg+'</svg>';
}

function btRender(){
  const j=btJob;if(!j)return;
  const active=['queued','running'].includes(j.status);
  $('bt-copy').disabled=active;
  $('bt-run').disabled=active;$('bt-cancel').hidden=!active;$('bt-history').disabled=active;
  $('bt-progress').hidden=!active;$('bt-progress').value=j.progress;
  $('bt-status').textContent=j.message+(active?` · ${j.progress}%`:'');
  let html=Object.keys(j.errors).length?`<div class="bt-errors">${Object.entries(j.errors).map(([s,e])=>`<p><strong>${esc(s)}</strong> · ${esc(e)}</p>`).join('')}</div>`:'';
  if(j.status!=='complete'){$('bt-results').innerHTML=html;return;}
  const p=j.params;
  html+=`<div class="bt-caption"><span>${esc(p.start)} — ${esc(p.end)} · ${Object.keys(j.coverage).length}/${p.symbols.length} 只完整数据 · ${esc(j.rule_version)} / ${esc(j.model_version)}<br><span class="muted">${esc(p.symbols.join(' / '))} · 每策略 $${number(p.capital,0)} · 每边费用 ${p.fee_bps} bps + 滑点 ${p.slippage_bps} bps · 风险 ${p.risk_percent}% · ${p.target_r}R · 最多 ${p.max_bars} 根 · 量比 ${p.settings.volume_multiple}</span></span><a class="text-button" href="/api/backtests/${encodeURIComponent(j.id)}/export">导出全部交易 CSV ↗</a></div><div class="bt-cards">`;
  for(const [kind,r] of Object.entries(j.results)){
    const m=r.metrics;
    html+=`<article class="bt-card ${kind}"><div class="bt-card-title"><h3>${btNames[kind]}</h3><span class="muted">${m.trades} 笔交易 / ${r.signals} 次信号</span></div><div class="bt-metrics"><div><span>扣费后收益率</span><strong class="${color(m.return_pct)}">${pct(m.return_pct)}</strong></div><div><span>胜率</span><strong>${m.win_rate==null?'—':number(m.win_rate)+'%'}</strong></div><div><span>最大回撤</span><strong class="negative">${number(m.max_drawdown_pct)}%</strong></div></div><div class="bt-card-foot"><span>净盈亏 <b class="${color(m.net_pnl)}">$${number(m.net_pnl)}</b></span><span>${m.wins} 胜 / ${m.losses} 负 / ${m.breakeven} 平</span><span>手续费 $${number(m.fees)}</span></div><p class="muted small">${m.trades<30?'样本较少，胜率仍不稳定。':'当前样本的描述统计，未做样本外验证。'}样本结束强平 ${m.forced_exits} 笔；因持仓占用跳过 ${r.skipped.busy} 次。</p></article>`;
  }
  html+='</div>';
  if(j.results.breakout?.metrics.early_stops!=null){
    html+='<div class="bt-detail"><h4>亏损路径与净期望</h4><div class="bt-table-wrap"><table><thead><tr><th>策略</th><th>前两根止损 / 全部交易</th><th>曾达 +0.5R / 亏损交易</th><th>顺序未知 / 亏损交易</th><th>每笔净期望 USD</th></tr></thead><tbody>';
    const fraction=(n,d)=>d?`${n} / ${d}（${number(100*n/d,1)}%）`:'—';
    for(const [kind,{metrics:m}] of Object.entries(j.results)){
      html+=`<tr><td>${btNames[kind]}</td><td>${fraction(m.early_stops,m.trades)}</td><td>${fraction(m.givebacks,m.losses)}</td><td>${fraction(m.unknown_paths,m.losses)}</td><td>${m.expectancy_usd==null?'—':number(m.expectancy_usd)}</td></tr>`;
    }
    html+='</tbody></table></div><p class="muted small">前两根按交易时段计。+0.5R 按买入价到初始保护价的距离计算；若止损当根才首次触及门槛且先后不明，单列为未知。两类统计可重叠。</p></div>';
  }
  const legend=Object.keys(j.results).map(k=>`<i class="bt-key" style="background:${btColors[k]}"></i>${btNames[k]}`).join('　');
  html+='<div class="bt-chart"><div class="bt-chart-heading"><h4>账户净值 · USD</h4><span>'+legend+'</span></div>'+btChart(j.results,p.capital)+'<h4 class="muted">距历史峰值的回撤</h4>'+btChart(j.results,p.capital,true)+'</div>';
  html+='<details class="bt-detail" open><summary>逐股表现</summary><div class="bt-table-wrap"><table><thead><tr><th>股票</th><th>策略</th><th>交易数</th><th>胜率</th><th>净盈亏 USD</th><th>资金份额收益</th><th>最大回撤</th></tr></thead><tbody>';
  for(const [kind,r] of Object.entries(j.results))for(const s of r.per_symbol)html+=`<tr><td>${esc(s.symbol)}</td><td>${btNames[kind]}</td><td>${s.trades}</td><td>${s.win_rate==null?'—':number(s.win_rate)+'%'}</td><td class="${color(s.net_pnl)}">${number(s.net_pnl)}</td><td class="${color(s.return_pct)}">${pct(s.return_pct)}</td><td>${number(s.max_drawdown_pct)}%</td></tr>`;
  html+='</tbody></table></div></details><details class="bt-detail"><summary>交易明细（最近 100 笔；CSV 包含全部）</summary><div class="bt-table-wrap"><table><thead><tr><th>股票 / 策略</th><th>入场（美东）</th><th>退出 K 线（美东）</th><th>买入 → 卖出</th><th>净盈亏 USD</th><th>退出原因</th><th>前两根止损</th><th>曾达 +0.5R</th></tr></thead><tbody>';
  const trades=Object.entries(j.results).flatMap(([kind,r])=>r.trades.map(t=>({...t,kind}))).sort((a,b)=>b.entry_time.localeCompare(a.entry_time)).slice(0,100);
  for(const t of trades)html+=`<tr><td>${esc(t.symbol)} / ${btNames[t.kind]}</td><td>${esc(t.entry_time.slice(0,16).replace('T',' '))}</td><td>${esc(t.exit_time.slice(0,16).replace('T',' '))}</td><td>${number(t.entry_price)} → ${number(t.exit_price)}</td><td class="${color(t.pnl)}">${number(t.pnl)}</td><td>${btReasons[t.reason]}</td><td>${t.early_stop==null?'—':t.early_stop?'是':'否'}</td><td>${({yes:'是',no:'否',unknown:'顺序未知'})[t.half_r_path]||'—'}</td></tr>`;
  if(!trades.length)html+='<tr><td colspan="8">此范围没有满足条件并成交的信号。</td></tr>';
  html+='</tbody></table></div></details><details class="bt-detail"><summary>历史数据覆盖</summary><div class="bt-table-wrap"><table><thead><tr><th>股票</th><th>日线</th><th>小时线</th><th>15 分钟线</th><th>可评估时点</th><th>数据来源</th></tr></thead><tbody>';
  for(const [s,c] of Object.entries(j.coverage))html+=`<tr><td>${esc(s)}</td>${['1D','60m','15m'].map(tf=>`<td>${c.frames[tf].actual} / ${c.frames[tf].expected}</td>`).join('')}<td>${c.evaluated_bars}</td><td>${c.source==='cache'?'本地 moomoo 历史缓存':'moomoo API'}</td></tr>`;
  html+='</tbody></table></div></details>';$('bt-results').innerHTML=html;
}

$('bt-form').onsubmit=async event=>{
  event.preventDefault();if(!liveOnly())return;
  const params={symbols:$('bt-symbols').value.toUpperCase().split(/[,，\s]+/).filter(Boolean)};
  for(const f of btFields)params[f]=['start','end'].includes(f)?$(`bt-${f}`).value:Number($(`bt-${f}`).value);
  $('bt-run').disabled=true;
  try{btJob=await request('/api/backtests','POST',params);btRender();await btList();}catch(e){toast(e.message);$('bt-run').disabled=false;}
};
$('bt-cancel').onclick=async()=>{try{await request(`/api/backtests/${btJob.id}/cancel`,'POST');$('bt-status').textContent='正在取消，等待当前数据请求结束…';}catch(e){toast(e.message);}};
$('bt-history').onchange=async()=>{if(!$('bt-history').value)return;try{btJob=await request(`/api/backtests/${$('bt-history').value}`);btRender();}catch(e){toast(e.message);}};
setInterval(async()=>{
  if(btPolling||!btJob||!['queued','running'].includes(btJob.status))return;
  btPolling=true;
  try{btJob=await request(`/api/backtests/${btJob.id}`);btRender();if(!['queued','running'].includes(btJob.status))await btList();}
  catch(e){$('bt-status').textContent='读取进度失败，将自动重试：'+e.message;}
  finally{btPolling=false;}
},2500);
let btStarted=false;
window.openBacktests=async()=>{
  if(btStarted)return;
  btStarted=true;
  try{await btList(true);}
  catch(e){btStarted=false;$('bt-status').textContent='无法读取回测记录：'+e.message;}
};
