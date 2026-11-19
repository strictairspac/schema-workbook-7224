from fastapi import APIRouter,Depends
from src.config.database import db_session
from src.utils.security import current,writer
from src.schemas.index_trial import TrialInput
from src.services import index_trials as service
from src.services.reports import queue
router=APIRouter()
@router.get('/index-trials')
def listing(db=Depends(db_session),user=Depends(current)):return service.listing(db)
@router.post('/index-trials',status_code=201)
def create(data:TrialInput,db=Depends(db_session),user=Depends(writer)):return service.create(db,data,user,queue)
@router.get('/index-trials/{ident}')
def detail(ident:int,db=Depends(db_session),user=Depends(current)):return service.detail(db,ident)
@router.post('/index-trials/{ident}/retry')
def retry(ident:int,db=Depends(db_session),user=Depends(writer)):return service.retry(db,ident,user,queue)
