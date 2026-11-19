#!/usr/bin/env python3 -I
"""End-to-end checks for the index-trial feature against a live stack."""
import json,random,time,urllib.request,urllib.error,sys

BASE='http://127.0.0.1:18000'

def call(path,method='GET',token=None,data=None):
    body=json.dumps(data).encode() if data is not None else None
    req=urllib.request.Request(BASE+path,data=body,method=method,
        headers={'Content-Type':'application/json',**({'Authorization':'Bearer '+token} if token else {})})
    try:
        with urllib.request.urlopen(req,timeout=30) as r:return r.status,json.loads(r.read())
    except urllib.error.HTTPError as e:return e.code,json.loads(e.read())

def wait(pred,label,timeout=180):
    deadline=time.time()+timeout
    while time.time()<deadline:
        if pred():return
        time.sleep(0.7)
    raise AssertionError('timeout waiting for '+label)

def login(role):
    code,data=call('/auth/login','POST',None,{'email':f'{role}@nanlu.test','password':'Demo2026!'})
    assert code==200,(code,data);return data['token']

def main():
    op=login('operator');viewer=login('viewer')
    # viewer cannot create trials
    code,_=call('/index-trials','POST',viewer,{'name':'x'})
    assert code==403,'viewer should be rejected'

    # ensure a completed report on NL-1117-A
    code,rels=call('/relations',token=op);assert code==200
    rel=next(r for r in rels if r['code']=='NL-1117-A')
    code,rep=call('/reports','POST',op,{'name':'e2e-report','relation_id':rel['id']});assert code==201,(code,rep)
    rid=rep['id']
    wait(lambda:call(f'/reports/{rid}',token=op)[1]['status']=='completed','report completion')
    report=call(f'/reports/{rid}',token=op)[1]
    assert report['result']['all_3nf'] and report['result']['chase']['lossless']

    random.seed(42)
    customers=['南麓大学','西江质检院','北辰制造','东海实验室']
    items=['拉伸','硬度','冲击','金相','弯曲']
    methods={'拉伸':'GB/T228','硬度':'GB/T231','冲击':'GB/T229','金相':'GB/T13298','弯曲':'GB/T232'}
    rows=[]
    for i in range(300):
        c=random.choice(customers);it=random.choice(items)
        rows.append({'values':{'委托号':f'NL-{i:05d}','客户':c,'检测项':it,'方法':methods[it],'结果':str(random.randint(10,999))}})
    queries=[
        {'label':'按客户查委托','sql':f"SELECT 委托号,检测项 FROM r_{rid}_t WHERE 客户 = '南麓大学' ORDER BY 委托号"},
        {'label':'按检测项统计','sql':f"SELECT 检测项, COUNT(*) AS n FROM r_{rid}_t GROUP BY 检测项 ORDER BY 检测项"},
        {'label':'按委托号精确查','sql':f"SELECT 客户,结果 FROM r_{rid}_t WHERE 委托号 = 'NL-00042'"},
        {'label':'复合条件查询','sql':f"SELECT 委托号,结果 FROM r_{rid}_t WHERE 客户 = '北辰制造' AND 检测项 = '硬度' ORDER BY 委托号"},
    ]
    candidates=[
        {'name':'idx_customer','columns':['客户']},
        {'name':'idx_item','columns':['检测项']},
        {'name':'idx_order_item','columns':['委托号','检测项']},
    ]
    payload={'name':'e2e-trial-generous','report_id':rid,'table_name':f'r_{rid}_t',
             'capacity_bytes':64*1024*1024,'sample_rows':rows,'queries':queries,'candidate_indexes':candidates}
    code,trial=call('/index-trials','POST',op,payload);assert code==201,(code,trial)
    tid=trial['id'];assert len(trial['combos'])==8  # baseline + 2^3-1
    wait(lambda:call(f'/index-trials/{tid}',token=op)[1]['status'] in ('completed','failed'),'trial completion')
    detail=call(f'/index-trials/{tid}',token=op)[1]
    assert detail['status']=='completed',(detail['status'],detail.get('error'))
    combos=detail['combos']
    assert all(c['status']=='measured' for c in combos),[(c['combo_key'],c['status'],c['error']) for c in combos]
    base=next(c for c in combos if c['combo_key']=='')
    base_sigs={q['label']:q['checksum'] for q in base['measurements']['queries']}
    for c in combos:
        m=c['measurements'];assert m['occupancy_bytes']>0
        for q in m['queries']:
            assert q['checksum']==base_sigs[q['label']],(c['combo_key'],q['label'],'result mismatch')
            assert q['plan'] and q['estimated_cost'] is not None
    base_cost=base['measurements']['total_estimated_cost']
    rec=detail['result']['recommendation']
    assert rec is not None,'a cheaper in-capacity combo should be recommended'
    winner=next(c for c in combos if c['id']==rec['combo_id'])
    assert winner['measurements']['total_estimated_cost']==rec['total_estimated_cost']
    assert rec['total_estimated_cost']<base_cost
    assert detail['result']['conclusion']=='recommended'
    print('CASE1 generous trial: recommendation =',rec['combo_key'],
          'cost',rec['total_estimated_cost'],'< baseline',base_cost,
          'occupancy',rec['occupancy_bytes'])

    # tiny capacity -> every non-empty combo rejected -> no available combo
    payload2=dict(payload,name='e2e-trial-tiny',capacity_bytes=1)
    code,trial2=call('/index-trials','POST',op,payload2);assert code==201,(code,trial2)
    t2=trial2['id']
    wait(lambda:call(f'/index-trials/{t2}',token=op)[1]['status'] in ('completed','failed'),'tiny trial')
    d2=call(f'/index-trials/{t2}',token=op)[1]
    assert d2['status']=='completed'
    assert d2['result']['recommendation'] is None and d2['result']['conclusion']=='no_available_combo'
    assert all(c['status']=='skipped' for c in d2['combos'] if c['combo_key'])
    assert all('超过容量' in (c['error'] or '') for c in d2['combos'] if c['combo_key'])
    print('CASE2 tiny capacity: all combos rejected, no_available_combo')

    # validation guards
    bad=dict(payload,name='e2e-bad-sql',queries=[{'label':'x','sql':'DROP TABLE t'}])
    code,err=call('/index-trials','POST',op,bad);assert code==422,(code,err)
    bad=dict(payload,name='e2e-bad-col',candidate_indexes=[{'name':'z','columns':['不存在列']}])
    code,err=call('/index-trials','POST',op,bad);assert code==422,(code,err)
    bad=dict(payload);bad['sample_rows']=[{'values':{'委托号':'A'}}]
    code,err=call('/index-trials','POST',op,bad);assert code==422,(code,err)
    print('CASE3 validation guards: 422 on DDL query / unknown column / ragged rows')

    # restricted play account must block cross-database reads even though the
    # SELECT passes the read-only validator; the trial cannot establish a baseline
    leak=dict(payload,name='e2e-crossdb',
              queries=[{'label':'leak','sql':'SELECT user FROM mysql.user LIMIT 1'}])
    code,trial3=call('/index-trials','POST',op,leak);assert code==201,(code,trial3)
    t3=trial3['id']
    wait(lambda:call(f'/index-trials/{t3}',token=op)[1]['status'] in ('completed','failed'),'crossdb trial')
    d3=call(f'/index-trials/{t3}',token=op)[1]
    assert d3['status']=='failed' and 'denied' in (d3['error'] or '').lower(),(d3['status'],d3.get('error'))
    print('CASE4 cross-database read blocked for restricted play account; trial failed without recommendation')
    print(json.dumps({'report_id':rid,'trial_generous':tid,'trial_tiny':t2,'trial_crossdb':t3},ensure_ascii=False))

if __name__=='__main__':main()
