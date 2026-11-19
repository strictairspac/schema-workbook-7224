#!/usr/bin/env python3 -I
"""Concurrent trials must use fully isolated data/index schemas and finish independently."""
import json,time,urllib.request,urllib.error
BASE='http://127.0.0.1:18000'

def call(path,method='GET',token=None,data=None):
    body=json.dumps(data).encode() if data is not None else None
    req=urllib.request.Request(BASE+path,data=body,method=method,
        headers={'Content-Type':'application/json',**({'Authorization':'Bearer '+token} if token else {})})
    try:
        with urllib.request.urlopen(req,timeout=30) as r:return r.status,json.loads(r.read())
    except urllib.error.HTTPError as e:return e.code,json.loads(e.read())

def wait(pred,label,timeout=180):
    end=time.time()+timeout
    while time.time()<end:
        if pred():return
        time.sleep(0.5)
    raise AssertionError('timeout: '+label)

def main():
    token=call('/auth/login','POST',None,{'email':'operator@nanlu.test','password':'Demo2026!'})[1]['token']
    rel=next(r for r in call('/relations',token=token)[1] if r['code']=='NL-1117-A')
    rid=call('/reports','POST',token,{'name':'concurrent-report','relation_id':rel['id']})[1]['id']
    wait(lambda:call(f'/reports/{rid}',token=token)[1]['status']=='completed','report')
    def payload(name,cap,table):
        rows=[{'values':{'委托号':f'NL-{i:05d}','客户':'南麓大学' if i%3 else '北辰制造','检测项':['拉伸','硬度'][i%2],'方法':'M','结果':str(i)}} for i in range(150)]
        return {'name':name,'report_id':rid,'table_name':table,'capacity_bytes':cap,'sample_rows':rows,
                'queries':[{'label':'q','sql':f"SELECT 委托号 FROM {table} WHERE 客户='南麓大学'"}],
                'candidate_indexes':[{'name':'ia','columns':['客户']},{'name':'ib','columns':['检测项']}]}
    # two trials queued back-to-back; a generous and a tight-capacity one, different table names
    t1=call('/index-trials','POST',token,payload('concurrent-a',64*1024*1024,'tbl_conc_a'))[1]['id']
    t2=call('/index-trials','POST',token,payload('concurrent-b',1,'tbl_conc_b'))[1]['id']
    wait(lambda:all(call(f'/index-trials/{t}',token=token)[1]['status']=='completed' for t in (t1,t2)),'both trials')
    d1=call(f'/index-trials/{t1}',token=token)[1];d2=call(f'/index-trials/{t2}',token=token)[1]
    # independent conclusions: first has a cheaper in-capacity recommendation, second has none
    assert d1['result']['conclusion']=='recommended',d1['result']
    assert d2['result']['conclusion']=='no_available_combo',d2['result']
    # isolation: each trial only ever references its own table in its frozen queries/plans
    for d,tid,table in ((d1,t1,'tbl_conc_a'),(d2,t2,'tbl_conc_b')):
        for c in d['combos']:
            assert c['measurements']
            for q in c['measurements']['queries']:
                assert table in q['sql']
                # the executed plan must name this trial's table, never the other trial's
                blob=json.dumps(q['plan_json'],ensure_ascii=False)
                assert f'"table_name": "{table}"' in blob
                other='tbl_conc_b' if table=='tbl_conc_a' else 'tbl_conc_a'
                assert other not in blob
    # schema names are unique per trial prefix; nothing of trial t1 leaks into t2 combos
    keys1={c['combo_key'] for c in d1['combos']};keys2={c['combo_key'] for c in d2['combos']}
    assert keys1==keys2=={'','ia','ib','ia|ib'}
    assert d1['result']['recommendation']['combo_key']!=d2['result'].get('recommendation')
    print('concurrency OK: trial',t1,'recommended',d1['result']['recommendation']['combo_key'],
          '; trial',t2,'no_available_combo; isolated tables tbl_conc_a / tbl_conc_b')

if __name__=='__main__':main()
