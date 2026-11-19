#!/usr/bin/env python3 -I
"""Interruption/resume semantics: retry resumes the SAME trial and never re-measures combos already done."""
import json,time,urllib.request,urllib.error,subprocess,os,sys
BASE='http://127.0.0.1:18000'
ENV=os.environ.copy()
ENV.update(DATABASE_URL='mysql+pymysql://schemaworkbook:schemaworkbook_demo_pw@127.0.0.1:13306/schemaworkbook',
           REDIS_URL='redis://127.0.0.1:16379/0',ARTIFACTS_DIR='/tmp/localdb/artifacts')

def call(path,method='GET',token=None,data=None):
    body=json.dumps(data).encode() if data is not None else None
    req=urllib.request.Request(BASE+path,data=body,method=method,
        headers={'Content-Type':'application/json',**({'Authorization':'Bearer '+token} if token else {})})
    try:
        with urllib.request.urlopen(req,timeout=30) as r:return r.status,json.loads(r.read())
    except urllib.error.HTTPError as e:return e.code,json.loads(e.read())

def wait(pred,label,timeout=120):
    end=time.time()+timeout
    while time.time()<end:
        if pred():return
        time.sleep(0.5)
    raise AssertionError('timeout: '+label)

def main():
    code,data=call('/auth/login','POST',None,{'email':'operator@nanlu.test','password':'Demo2026!'});token=data['token']
    code,rels=call('/relations',token=token);rel=next(r for r in rels if r['code']=='NL-1117-A')
    code,rep=call('/reports','POST',token,{'name':'resume-report','relation_id':rel['id']});rid=rep['id']
    wait(lambda:call(f'/reports/{rid}',token=token)[1]['status']=='completed','report')
    rows=[{'values':{'委托号':f'NL-{i:05d}','客户':'南麓大学' if i%2 else '北辰制造','检测项':['拉伸','硬度'][i%2],'方法':'M','结果':str(i)}} for i in range(200)]
    payload={'name':'resume-trial','report_id':rid,'table_name':f'r_{rid}_resume','capacity_bytes':64*1024*1024,
             'sample_rows':rows,
             'queries':[{'label':'q1','sql':f"SELECT * FROM r_{rid}_resume WHERE 客户='南麓大学'"},
                        {'label':'q2','sql':f"SELECT 检测项,COUNT(*) FROM r_{rid}_resume GROUP BY 检测项"}],
             'candidate_indexes':[{'name':'i1','columns':['客户']},{'name':'i2','columns':['检测项']},{'name':'i3','columns':['委托号']}]}
    code,trial=call('/index-trials','POST',token,payload);tid=trial['id'];assert code==201
    def states():
        d=call(f'/index-trials/{tid}',token=token)[1]
        return {c['combo_key'] or '(baseline)':c['status'] for c in d['combos']},d['status']
    # poll densely and kill the worker as soon as baseline plus at least one
    # non-empty combo is done but some combos are still pending
    partial=None
    end=time.time()+60
    while time.time()<end:
        snap,status=states()
        measured=[k for k,v in snap.items() if v=='measured']
        pending=[k for k,v in snap.items() if v in ('pending','running')]
        if '(baseline)' in measured and len(measured)>=2 and pending:
            partial=(snap,status);break
        time.sleep(0.05)
    assert partial,'never observed a partial measurement state'
    snap,_=partial
    done_before={k for k,v in snap.items() if v=='measured'}
    print('measured before kill:',len(done_before),sorted(done_before))
    assert 1<=len(done_before)<8,'worker should have measured baseline plus a partial set'
    subprocess.run(['pkill','-f','src.worker'],check=False)
    time.sleep(2)
    d=call(f'/index-trials/{tid}',token=token)[1]
    assert d['status']=='running','trial should still show running while worker is dead'
    # measured_at timestamps must survive; pending combos must not be counted as done
    measured_at={c['combo_key']:c['measured_at'] for c in d['combos'] if c['status']=='measured'}
    # restart worker, then explicitly call retry endpoint (fresh run_token) to resume the SAME trial
    worker=subprocess.Popen(['/workspace/.venv/bin/python','-m','src.worker'],
        cwd='/workspace/backend',env=ENV,stdout=open('/tmp/localdb/worker-resume.log','a'),stderr=subprocess.STDOUT)
    wait(lambda:os.path.exists('/tmp/worker-heartbeat') and time.time()-os.path.getmtime('/tmp/worker-heartbeat')<5,'worker heartbeat')
    code,retried=call(f'/index-trials/{tid}/retry','POST',token);assert code==200,(code,retried)
    assert retried['id']==tid,'retry must resume the original trial, not create a new one'
    wait(lambda:call(f'/index-trials/{tid}',token=token)[1]['status']=='completed','resumed trial completion')
    d=call(f'/index-trials/{tid}',token=token)[1]
    after={c['combo_key'] or '(baseline)':c['status'] for c in d['combos']}
    # every combo measured exactly once overall; already-measured ones kept their original timestamp
    kept=0
    for c in d['combos']:
        if c['combo_key'] in measured_at and measured_at[c['combo_key']]:
            assert c['measured_at']==measured_at[c['combo_key']],(c['combo_key'],'already-measured combo was re-measured')
            kept+=1
    assert kept==len(measured_at)
    assert all(v=='measured' for v in after.values()),after
    assert len(d['combos'])==8
    # correctness of resumed result
    base=next(c for c in d['combos'] if not c['combo_key'])['measurements']['total_estimated_cost']
    rec=d['result']['recommendation']
    assert rec and rec['total_estimated_cost']<base
    print('resume OK: combos preserved =',kept,'/ total 8; recommendation =',rec['combo_key'],'cost',rec['total_estimated_cost'],'< baseline',base)
    worker.terminate()

if __name__=='__main__':main()
