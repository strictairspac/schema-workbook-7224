// Minimal DOM stub to smoke-render the trial pages under Node (no browser).
globalThis.localStorage = {
  store: {},
  getItem(k) { return this.store[k] ?? null; },
  setItem(k, v) { this.store[k] = String(v); },
  removeItem(k) { delete this.store[k]; },
};
const base = '/workspace/frontend/src/';
const { trialCreateSection, trialsListPage, trialDetailPage } = await import(base + 'pages/trials.js');
const { evidencePage } = await import(base + 'pages/evidence.js');

const plan = (type, key, cost, extra) => ({
  label: 'q',
  plan: [{ table: 't', type, key, rows: 100, Extra: extra }],
  plan_json: { query_block: { cost_info: { query_cost: String(cost) } } },
  estimated_cost: cost,
  row_count: 100,
  sql: 'SELECT 1',
});
const measurement = (cost, occ) => ({
  queries: [plan(cost < 40 ? 'ref' : 'ALL', cost < 40 ? 'ia' : null, cost, cost < 40 ? '' : 'Using where')],
  occupancy_bytes: occ,
  total_estimated_cost: cost,
  result_mismatches: [],
});

const report = {
  id: 3, name: 'r', status: 'completed', created_at: '2026-11-19T00:00:00+00:00',
  result: {
    all_3nf: true, chase: { lossless: true, witness_rows: [1], steps: [] }, dependency_preserved: true,
    candidate_keys: [['委托号', '检测项']], decomposition: [['委托号', '客户']], searched_subsets: 4,
    closure_proofs: [], normal_form_checks: [], added_key_relation: null, method: 'm', checksum: 'abc',
  },
};
const trial = {
  id: 9, name: 't', report_id: 3, status: 'completed', created_at: '2026-11-19T00:00:00+00:00',
  input_snapshot: { sample_rows: [1, 2], capacity_bytes: 67108864, candidate_indexes: [1, 2, 3] },
  result: {
    baseline: {}, recommendation: { combo_key: ['ia', 'ib'], total_estimated_cost: 10.75, baseline_total_estimated_cost: 40.5, occupancy_bytes: 65536 },
    combo_count: 4, eligible_count: 1, conclusion: 'recommended', rejected: [],
  },
  combos: [
    { combo_key: '', index_specs: [], status: 'measured', error: null, measurements: measurement(40.5, 49152) },
    { combo_key: 'ia', index_specs: [{ name: 'ia' }], status: 'measured', error: null, measurements: measurement(10.75, 65536) },
    { combo_key: 'ib', index_specs: [{ name: 'ib' }], status: 'skipped', error: '实测占用 999 字节超过容量 1，拒绝推荐', measurements: { queries: [], occupancy_bytes: 999, total_estimated_cost: 5, result_mismatches: [] } },
  ],
};

function assert(cond, msg) { if (!cond) { console.error('FAIL:', msg); process.exit(1); } }

let html = trialCreateSection(report, [trial]);
for (const needle of ['索引选型试验', '委托样本', '常用查询', '候选索引', 'trial-form', '回看计划与占用']) {
  assert(html.includes(needle), 'create section missing ' + needle);
}
assert(trialsListPage([trial]).includes('推荐：ia + ib'), 'list page recommendation missing');
let detail = trialDetailPage(trial);
for (const needle of ['推荐组合：ia + ib', '10.75', '基线 40.5', '实测占用', 'plan-details', '执行计划', '已拒绝']) {
  assert(detail.includes(needle), 'detail missing ' + needle);
}
const none = JSON.parse(JSON.stringify(trial));
none.result.recommendation = null; none.result.conclusion = 'no_available_combo';
assert(trialDetailPage(none).includes('无可用组合'), 'no-combo branch missing');
assert(evidencePage(report, [trial]).includes('索引选型试验'), 'evidence page should embed trial entry');
const running = JSON.parse(JSON.stringify(trial));
running.status = 'running'; running.result = null;
assert(trialDetailPage(running).includes('实测进行中'), 'running branch missing');
console.log('FRONTEND SMOKE OK: all trial page branches render');
