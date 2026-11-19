import {table} from '../components/common/table.js';
import {badge,comboBadge} from '../components/common/badge.js';
import {esc,date} from '../utils/html.js';
import {session} from '../hooks/session.js';

const readOnly=session.user?.role==='viewer';

export function trialCreateSection(report,trials){
  const mine=trials.filter(t=>t.report_id===report.id);
  const defaultTable=('r_'+report.id+'_sample').replace(/[^a-zA-Z0-9_]/g,'_');
  return `<div class="trial-block">
  <div class="section-top"><h2>索引选型试验</h2><span>SAME DATA / REAL INDEX / EXPLAIN</span></div>
  <p class="help">在本报告冻结的拆解结果上，录入委托样本、常用只读查询与候选索引。系统将用同一批数据为每个候选组合建立独立隔离的实测库，回放查询并核对结果一致性，按执行计划总估算成本择优；实测占用超容量或结果不一致的组合直接拒绝。</p>
  ${mine.length?table(['试验 / 时间','状态','结论','详情'],mine.map(t=>[
    `<strong>${esc(t.name)}</strong><small>${date(t.created_at)}</small>`,badge(t.status),
    t.result?(t.result.recommendation?`推荐：${esc(t.result.recommendation.combo_key.join(' + ')||'—')}`:'无可用组合'):'—',
    `<a href="#trials/${t.id}">回看计划与占用 →</a>`])):''}
  <form id="trial-form" class="trial-form">
    <div class="fields">
      <label>试验名称<input name="name" value="trial-report-${report.id}-${new Date().toISOString().slice(0,10)}" required></label>
      <label>实测表名（隔离库内）<input name="table_name" value="${esc(defaultTable)}" required></label>
      <label>容量上限（MB，实测占用超过即拒绝）<input name="capacity_mb" type="number" min="1" step="1" value="64" required></label>
    </div>
    <label>委托样本（CSV，首行表头为属性列，后续每行一条样本）
      <textarea name="sample_csv" rows="7" placeholder="委托号,客户,检测项&#10;NL-001,南麓大学,拉伸&#10;NL-002,南麓大学,硬度" required></textarea></label>
    <div class="row-editor">
      <div class="row-editor-head"><b>常用查询（只读 SELECT，按顺序回放）</b><button type="button" class="small" data-add="query" ${readOnly?'disabled':''}>+ 查询</button></div>
      <div id="query-rows"></div>
    </div>
    <div class="row-editor">
      <div class="row-editor-head"><b>候选索引</b><button type="button" class="small" data-add="index" ${readOnly?'disabled':''}>+ 候选索引</button></div>
      <div id="index-rows"></div>
    </div>
    <button class="primary" ${readOnly?'disabled':''}>建库实测全部组合 ↗</button>
    <p class="help">最多 12 个候选索引（至多 256 个非空组合）。中断后可在试验详情页恢复原试验，已测组合不会重复计入。</p>
  </form></div>`;
}

export function trialsListPage(items){
  if(!items.length)return '<div class="empty">还没有索引试验。请打开一份已完成的分解报告，在报告页面录入委托样本、常用查询和候选索引。</div>';
  return `<div class="section-top"><h2>索引试验记录</h2><span>${items.length} 件 / ISOLATED MEASUREMENT</span></div>`+
    table(['试验 / 时间','状态','结论','详情'],items.map(t=>[
      `<strong>${esc(t.name)}</strong><small>${date(t.created_at)}</small>`,badge(t.status),
      t.result?(t.result.recommendation?`推荐：${esc(t.result.recommendation.combo_key.join(' + '))}（估算成本 ${t.result.recommendation.total_estimated_cost} vs 基线 ${t.result.recommendation.baseline_total_estimated_cost}）`:'无可用组合'):'—',
      `<a href="#trials/${t.id}">回看 →</a>`]));
}

function planBlock(q){
  const rows=(q.plan||[]).map(p=>`<tr><td>${esc(p.table??'')}</td><td>${esc(p.type??'')}</td><td>${esc(p.key??'')}</td><td>${esc(p.rows??'')}</td><td>${esc(p.Extra??'')}</td></tr>`).join('');
  return `<details class="plan-details"><summary>${esc(q.label)} · 成本 ${q.estimated_cost??'—'} · 行数 ${q.row_count}</summary>
    <div class="table-wrap"><table><thead><tr><th>表</th><th>访问类型</th><th>键</th><th>估算行</th><th>Extra</th></tr></thead><tbody>${rows}</tbody></table></div>
    <pre class="plan-json">${esc(JSON.stringify(q.plan_json,null,1))}</pre>
    <code class="sql">${esc(q.sql)}</code></details>`;
}

export function trialDetailPage(trial){
  if(!trial)return '<div class="empty">试验不存在或已被删除。</div>';
  const snap=trial.input_snapshot,res=trial.result;
  const head=`<div class="evidence-top"><div><span class="eyebrow">INDEX TRIAL / #${trial.id} / REPORT #${trial.report_id}</span>
    <h2>${esc(trial.name)} ${badge(trial.status)}</h2><p>${date(trial.created_at)} · 样本 ${snap.sample_rows.length} 行 · 容量上限 ${snap.capacity_bytes} 字节 · 候选索引 ${snap.candidate_indexes.length} 个</p></div>
    ${trial.status==='failed'&&!readOnly?`<button id="trial-retry" data-id="${trial.id}">恢复原试验 ↻</button>`:''}</div>`;
  const err=trial.error?`<div class="error">${esc(trial.error)}。可恢复原试验，已测组合不重复计入。</div>`:'';
  const verdict=res? (res.recommendation?
    `<div class="verdict"><div class="verdict-icon">✓</div><div><span class="eyebrow">RECOMMENDED COMBO</span><h2>推荐组合：${esc(res.recommendation.combo_key.join(' + '))}</h2>
      <p>总估算成本 ${res.recommendation.total_estimated_cost}（基线 ${res.recommendation.baseline_total_estimated_cost}，只推荐比基线省的组合）· 实测占用 ${res.recommendation.occupancy_bytes} 字节</p></div></div>`:
    `<div class="verdict"><div class="verdict-icon">!</div><div><span class="eyebrow">NO AVAILABLE COMBO</span><h2>无可用组合</h2>
      <p>所有非空组合要么超容量、结果与基线不一致，要么成本不低于基线。保留无候选索引基线。</p></div></div>`):
    `<div class="notice">实测进行中，每 1.5 秒刷新。每个组合使用独立隔离库，互不影响；中断后可恢复，已测组合不会重复测量。</div>`;
  const comboRows=trial.combos.map(c=>{
    const m=c.measurements;
    const cost=m?m.total_estimated_cost??(m.queries?m.queries.reduce((s,q)=>s+(q.estimated_cost||0),0):'—'):'—';
    const base=m?m.baseline_total_estimated_cost:'—';
    const occ=m?m.occupancy_bytes:'—';
    const mismatch=m&&m.result_mismatches&&m.result_mismatches.length?esc('结果不一致：'+m.result_mismatches.join('，')):'';
    return [`<strong>${c.combo_key?esc(c.combo_key.split('|').join(' + ')):'<em>基线（无候选索引）</em>'}</strong><small>${esc(c.index_specs.map(i=>i.name).join(', '))}</small>`,
      comboBadge(c.status),`${cost}`, `${base}`, `${occ}`,
      `<small>${m?esc(mismatch||c.error||''):esc(c.error||'')}</small>`];
  });
  const plans=`<div class="section-top"><h2>组合实测明细</h2><span>执行计划与占用可回看</span></div>`+
    table(['组合','状态','查询总估算成本','基线总成本','实测占用(字节)','拒绝原因'],comboRows)+
    trial.combos.filter(c=>c.measurements).map(c=>`<div class="combo-plans"><h3>${c.combo_key?esc(c.combo_key.split('|').join(' + ')):'基线（无候选索引）'} ${comboBadge(c.status)}</h3>
      ${c.measurements.queries.map(planBlock).join('')}</div>`).join('');
  return head+err+verdict+plans;
}
