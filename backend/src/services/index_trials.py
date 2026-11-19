"""Bounded combinatorial index trials on isolated MySQL/MariaDB schemas.

One trial = one completed report's chosen table, a frozen sample dataset,
read-only queries and candidate indexes. The empty combo is the baseline; every
non-empty subset of candidates is materialised in its own isolated schema with
the same data, replayed, explained and measured.

Resumability: combo rows are claimed by status only. A retry never re-measures
combos already in `measured/skipped`; stale `running` rows and `failed` rows are
returned to `pending`. A fresh run_token on every (re)start makes workers from
an interrupted run release their claim instead of writing stale results.
"""
from itertools import combinations
from datetime import datetime,timezone
import hashlib,json,secrets,time
from fastapi import HTTPException
from sqlalchemy import select,text,create_engine
from src.config.database import engine,Session
from src.config.settings import TRIAL_ADMIN_URL
from src.models.entities import Report,IndexTrial,IndexTrialCombo,Audit
from src.constants.enums import TRIAL_STATES
from src.utils.serialization import record
from .common import save

MAX_CANDIDATES=12
MAX_COMBOS=256
QUEUE_KEY='schemaworkbook:index-queue'

# Privileged engine for isolated schema/account lifecycle; never used by the web app.
admin_engine=create_engine(TRIAL_ADMIN_URL,pool_pre_ping=True)

def combo_key(names):return '|'.join(sorted(names))

def plan_combinations(names):
    names=sorted(names);out=[()]
    for size in range(1,len(names)+1):out.extend(combinations(names,size))
    return out

def listing(db):
    return [record(x) for x in db.scalars(select(IndexTrial).order_by(IndexTrial.id.desc()))]

def detail(db,ident):
    obj=db.get(IndexTrial,ident)
    if not obj:raise HTTPException(404,'试验不存在')
    combos=db.scalars(select(IndexTrialCombo).where(IndexTrialCombo.trial_id==ident).order_by(IndexTrialCombo.id)).all()
    data=record(obj);data['combos']=[record(c) for c in combos]
    return data

def create(db,data,user,queue):
    report=db.get(Report,data.report_id)
    if not report:raise HTTPException(404,'分解报告不存在')
    if report.status!='completed' or not report.result:raise HTTPException(422,'报告尚未完成，无法在报告页发起索引试验')
    payload=data.model_dump()
    columns=list(payload['sample_rows'][0]['values'].keys())
    for item in payload['candidate_indexes']:
        unknown=[c for c in item['columns'] if c not in columns]
        if unknown:raise HTTPException(422,f"候选索引 {item['name']} 引用了样本中不存在的列：{','.join(unknown)}")
    names=[i['name'] for i in payload['candidate_indexes']]
    combos=plan_combinations(names)
    if len(combos)-1>MAX_COMBOS:raise HTTPException(422,f'候选索引组合数 {len(combos)-1} 超过上限 {MAX_COMBOS}')
    snapshot={'columns':columns,**payload}
    trial=IndexTrial(name=payload['name'],report_id=payload['report_id'],status=TRIAL_STATES[0],
                     run_token=secrets.token_hex(16),input_snapshot=snapshot)
    save(db,trial,user,'索引试验入队 '+trial.name)
    for combo in combos:
        db.add(IndexTrialCombo(trial_id=trial.id,combo_key=combo_key(combo),
                               index_specs=[next(i for i in snapshot['candidate_indexes'] if i['name']==n) for n in combo]))
    db.commit()
    try:queue.rpush(QUEUE_KEY,str(trial.id))
    except Exception:
        trial.status='failed';trial.error='队列暂时不可用，请重试恢复';db.commit();raise HTTPException(503,trial.error)
    return detail(db,trial.id)

def retry(db,ident,user,queue):
    trial=db.get(IndexTrial,ident)
    if not trial:raise HTTPException(404,'试验不存在')
    if trial.status=='completed':raise HTTPException(409,'试验已完成，结果已冻结，不可重试')
    # A new run_token invalidates any still-alive stale worker's pending writes,
    # so recovery is safe even while a previous run is marked `running`.
    trial.run_token=secrets.token_hex(16);trial.status='queued';trial.error=None;trial.result=None
    reset=0
    for c in db.scalars(select(IndexTrialCombo).where(IndexTrialCombo.trial_id==ident)).all():
        if c.status in ('pending','running','failed'):
            c.status='pending';c.measurements=None;c.error=None;c.measured_at=None;reset+=1
    db.add(Audit(actor=user.email,action=f'恢复索引试验 {trial.name}（重测 {reset} 个组合，已测组合不重复计入）'));db.commit()
    try:queue.rpush(QUEUE_KEY,str(trial.id))
    except Exception:
        trial.status='failed';trial.error='队列暂时不可用，请稍后重试';db.commit();raise HTTPException(503,trial.error)
    return detail(db,trial.id)

# ---------------- worker side ----------------

def _ident(name):return '`'+str(name).replace('`','``')+'`'

def _exec(conn,sql,params=None):return conn.execute(text(sql),params or {})

def _schema_engine(schema):
    # Same restricted trial_admin account, but defaulted to one isolated schema so
    # that user queries with unqualified table names resolve there. Grants still
    # deny any access outside trial% schemas.
    return create_engine(admin_engine.url.set(database=schema),pool_pre_ping=True)

def _checksum(rows):
    h=hashlib.sha256()
    for r in sorted(rows):h.update(json.dumps(r,ensure_ascii=False).encode())
    return h.hexdigest()

def _query_total_cost(parsed):
    """The top-level query_block.query_cost is the authoritative plan total."""
    if not isinstance(parsed,dict):return None
    block=parsed.get('query_block')
    if isinstance(block,dict):
        info=block.get('cost_info') or {}
        try:return round(float(info['query_cost']),6)
        except (KeyError,TypeError,ValueError):pass
    found=[];_collect_cost(parsed,found)
    return round(max(found),6) if found else None

def _collect_cost(node,found):
    if isinstance(node,dict):
        for k,v in node.items():
            if k in ('query_cost','cost'):
                try:found.append(float(v))
                except (TypeError,ValueError):pass
            else:_collect_cost(v,found)
    elif isinstance(node,list):
        for v in node:_collect_cost(v,found)

def _explain(conn,query_sql):
    sql=query_sql.strip().rstrip(';')
    classic=[dict(r) for r in conn.execute(text('EXPLAIN '+sql)).mappings().all()]
    json_text=conn.execute(text('EXPLAIN FORMAT=JSON '+sql)).scalar()
    try:
        parsed=json.loads(json_text) if json_text else None
        total=_query_total_cost(parsed)
    except (ValueError,TypeError):
        parsed,total=json_text,None
    return {'plan':classic,'plan_json':parsed,'estimated_cost':total}

def _measure(conn,schema,table_name,snapshot,specs):
    qualified=f'{_ident(schema)}.{_ident(table_name)}'
    for spec in specs:
        cols=','.join(_ident(c) for c in spec['columns'])
        _exec(conn,f"CREATE INDEX {_ident(spec['name'])} ON {qualified} ({cols})")
    _exec(conn,f'ANALYZE TABLE {qualified}')
    # Replay runs on the restricted trial_admin connection, whose grants only
    # cover trial% schemas: a crafted query against other databases is denied
    # (1142), and read-only validation already blocks DDL/DML.
    queries=[]
    for q in snapshot['queries']:
        exp=_explain(conn,q['sql'])
        rows=conn.execute(text(q['sql'].strip().rstrip(';'))).all()
        sig=[tuple('' if v is None else str(v) for v in r) for r in rows]
        queries.append({'label':q['label'],'sql':q['sql'],**exp,
                        'row_count':len(sig),'checksum':_checksum(sig)})
    est=conn.execute(text(
        'SELECT COALESCE(DATA_LENGTH,0)+COALESCE(INDEX_LENGTH,0) AS bytes '
        'FROM information_schema.TABLES WHERE TABLE_SCHEMA=:s AND TABLE_NAME=:t'),
        {'s':schema,'t':table_name}).mappings().first()
    return {'indexes':[s['name'] for s in specs],'occupancy_bytes':int(est['bytes']),'queries':queries}

def _fresh_schema(conn,prefix):
    name=f'{prefix}_{int(time.time()*1000)}_{secrets.token_hex(4)}'
    _exec(conn,f'CREATE DATABASE {_ident(name)} CHARACTER SET utf8mb4')
    return name

def _build_table(conn,schema,table_name,columns,rows):
    ddl=f"CREATE TABLE {_ident(schema)}.{_ident(table_name)} ("+','.join(
        f'{_ident(c)} VARCHAR(255) NOT NULL' for c in columns)+') ENGINE=InnoDB'
    _exec(conn,ddl)
    if rows:
        cols=','.join(_ident(c) for c in columns)
        sql=f'INSERT INTO {_ident(schema)}.{_ident(table_name)} ({cols}) VALUES ('+','.join(f':{c}' for c in columns)+')'
        conn.execute(text(sql),[r['values'] for r in rows])

def run_trial(trial_id):
    """Idempotent and resumable; safe to invoke again after interruption."""
    with Session() as db:
        trial=db.get(IndexTrial,trial_id)
        if not trial or trial.status=='completed':return
        token=trial.run_token;trial.status='running';trial.error=None;db.commit()
        snapshot=trial.input_snapshot
    try:_measure_all(trial_id,token,snapshot)
    except Exception as exc:
        import traceback;traceback.print_exc()
        with Session() as db:
            obj=db.get(IndexTrial,trial_id)
            if obj and obj.run_token==token:obj.status='failed';obj.error=str(exc);db.commit()

def _measure_all(trial_id,token,snapshot):
    prefix=f'trial_{trial_id}'
    table_name=snapshot['table_name']
    baseline_schema=None
    try:
        with admin_engine.connect() as admin:
            for old in admin.execute(text(
                    "SELECT SCHEMA_NAME FROM information_schema.SCHEMATA WHERE SCHEMA_NAME LIKE :p"),
                    {'p':prefix+'_%'}).scalars().all():
                _exec(admin,f'DROP DATABASE IF EXISTS {_ident(old)}')
            admin.commit()
        # Reuse an already-measured baseline: the input snapshot is frozen, so a
        # resumed run never repeats work that was measured before interruption.
        with Session() as db:
            base_row=db.scalar(select(IndexTrialCombo).where(
                IndexTrialCombo.trial_id==trial_id,IndexTrialCombo.combo_key==''))
            stored_baseline=base_row.measurements if base_row and base_row.status=='measured' and base_row.measurements else None
        if stored_baseline:
            baseline=stored_baseline
        else:
            with admin_engine.connect() as admin:
                baseline_schema=_fresh_schema(admin,prefix);admin.commit()
                _build_table(admin,baseline_schema,table_name,snapshot['columns'],snapshot['sample_rows']);admin.commit()
            base_engine=_schema_engine(baseline_schema)
            try:
                with base_engine.connect() as conn:
                    baseline=_measure(conn,baseline_schema,table_name,snapshot,[]);conn.commit()
            finally:base_engine.dispose()
        baseline_sig={q['label']:q['checksum'] for q in baseline['queries']}
        baseline_cost=round(sum((q['estimated_cost'] or 0) for q in baseline['queries']),6)
        baseline['total_estimated_cost']=baseline_cost
        if not stored_baseline:
            with Session() as db:
                base=db.scalar(select(IndexTrialCombo).where(
                    IndexTrialCombo.trial_id==trial_id,IndexTrialCombo.combo_key==''))
                base.status='measured';base.measurements=baseline;base.measured_at=datetime.now(timezone.utc)
                if db.get(IndexTrial,trial_id).run_token!=token:return
                db.commit()
        with Session() as db:
            pending_ids=[r.id for r in db.scalars(select(IndexTrialCombo).where(
                IndexTrialCombo.trial_id==trial_id,IndexTrialCombo.status=='pending').order_by(IndexTrialCombo.id)).all()]
        capacity=snapshot['capacity_bytes']
        for cid in pending_ids:
            with Session() as db:
                combo=db.get(IndexTrialCombo,cid)
                if not combo or combo.status!='pending' or db.get(IndexTrial,trial_id).run_token!=token:continue
                combo.status='running';db.commit();specs=list(combo.index_specs)
            schema=None
            try:
                with admin_engine.connect() as admin:
                    schema=_fresh_schema(admin,prefix);admin.commit()
                    _build_table(admin,schema,table_name,snapshot['columns'],snapshot['sample_rows']);admin.commit()
                se=_schema_engine(schema)
                try:
                    with se.connect() as conn:
                        measurement=_measure(conn,schema,table_name,snapshot,specs);conn.commit()
                finally:se.dispose()
                mismatched=[q['label'] for q in measurement['queries'] if q['checksum']!=baseline_sig.get(q['label'])]
                over=measurement['occupancy_bytes']>capacity
                total=round(sum((q['estimated_cost'] or 0) for q in measurement['queries']),6)
                measurement.update(total_estimated_cost=total,baseline_total_estimated_cost=baseline_cost,
                                   capacity_bytes=capacity,within_capacity=not over,result_mismatches=mismatched)
                with Session() as db:
                    combo=db.get(IndexTrialCombo,cid)
                    if db.get(IndexTrial,trial_id).run_token!=token:continue
                    combo.measurements=measurement;combo.measured_at=datetime.now(timezone.utc)
                    if over:combo.status,combo.error='skipped',f"实测占用 {measurement['occupancy_bytes']} 字节超过容量 {capacity}，拒绝推荐"
                    elif mismatched:combo.status,combo.error='skipped','查询结果与基线不一致，拒绝推荐'
                    else:combo.status,combo.error='measured',None
                    db.commit()
            except Exception:
                import traceback;traceback.print_exc()
                with Session() as db:
                    combo=db.get(IndexTrialCombo,cid)
                    if combo and combo.status=='running' and db.get(IndexTrial,trial_id).run_token==token:
                        combo.status='failed';combo.error=traceback.format_exc()[-500:];db.commit()
            finally:
                if schema:
                    with admin_engine.connect() as cleanup:
                        _exec(cleanup,f'DROP DATABASE IF EXISTS {_ident(schema)}');cleanup.commit()
        _finalize(trial_id,token,baseline)
    finally:
        if baseline_schema:
            with admin_engine.connect() as cleanup:
                _exec(cleanup,f'DROP DATABASE IF EXISTS {_ident(baseline_schema)}');cleanup.commit()

def _finalize(trial_id,token,baseline):
    with Session() as db:
        trial=db.get(IndexTrial,trial_id)
        if not trial or trial.run_token!=token:return
        combos=db.scalars(select(IndexTrialCombo).where(IndexTrialCombo.trial_id==trial_id)).all()
        if any(c.status in ('pending','running') for c in combos):return
        baseline_cost=baseline['total_estimated_cost']
        eligible=[]
        for c in combos:
            if not c.combo_key or c.status!='measured' or not c.measurements:continue
            m=c.measurements
            if m.get('result_mismatches') or not m.get('within_capacity'):continue
            if m['total_estimated_cost']>=baseline_cost:continue
            eligible.append((m['total_estimated_cost'],c.combo_key,c.id,m['occupancy_bytes']))
        eligible.sort(key=lambda x:(x[0],x[1]))
        recommendation=None
        if eligible:
            cost,key,cid,occ=eligible[0]
            recommendation={'combo_id':cid,'combo_key':key.split('|'),
                            'total_estimated_cost':cost,'baseline_total_estimated_cost':baseline_cost,
                            'occupancy_bytes':occ,
                            'reason':'容量内、回放结果与无候选索引基线一致，执行计划查询总估算成本低于基线且为全部合规组合中最低'}
        rejected=[{'combo_key':c.combo_key.split('|'),'status':c.status,'error':c.error}
                  for c in combos if c.combo_key and c.status in ('skipped','failed')]
        trial.status='completed'
        trial.result={'baseline':baseline,'recommendation':recommendation,'rejected':rejected,
                      'combo_count':len(combos),'eligible_count':len(eligible),
                      'conclusion':'recommended' if recommendation else 'no_available_combo'}
        db.add(Audit(actor='worker',action=('索引试验给出推荐 ' if recommendation else '索引试验无可用组合 ')+trial.name))
        db.commit()
