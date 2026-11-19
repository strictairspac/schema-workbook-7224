import os,traceback,json,logging
from pathlib import Path
from src.config.database import Session
from src.models.entities import Report
from src.services.reports import queue
from src.services.normalization import analyze
from src.services import index_trials

ARTIFACT_DIR=Path(os.getenv('ARTIFACTS_DIR','/artifacts'))

def handle_report(ident):
    try:
        with Session() as db:
            obj=db.get(Report,ident);obj.status='running';db.commit();snapshot=obj.input_snapshot
        result=analyze(snapshot['relation']['attributes'],snapshot['dependencies'])
        with Session() as db:
            obj=db.get(Report,ident);obj.result=result;obj.status='completed';db.commit()
        try:
            ARTIFACT_DIR.mkdir(parents=True,exist_ok=True)
            (ARTIFACT_DIR/f'report-{ident}.json').write_text(json.dumps(result,ensure_ascii=False,indent=2))
        except OSError:
            logging.exception('artifact write failed for report %s; database result retained',ident)
    except Exception as e:
        traceback.print_exc()
        with Session() as db:
            obj=db.get(Report,ident)
            if obj:obj.status='failed';obj.error=str(e);db.commit()

while True:
    Path('/tmp/worker-heartbeat').touch()
    item=queue.blpop(['schemaworkbook:queue',index_trials.QUEUE_KEY],timeout=2)
    if not item:continue
    key,payload=item
    ident=int(payload)
    if key=='schemaworkbook:queue':handle_report(ident)
    else:
        try:index_trials.run_trial(ident)
        except Exception:traceback.print_exc()
