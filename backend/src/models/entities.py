from sqlalchemy import Column,Integer,String,JSON,DateTime,ForeignKey,Text
from datetime import datetime,timezone
from src.config.database import Base
class User(Base):
    __tablename__='users'
    id=Column(Integer,primary_key=True);email=Column(String(120),unique=True,nullable=False);password=Column(String(300),nullable=False);role=Column(String(20),nullable=False)
class Relation(Base):
    __tablename__='relations'
    id=Column(Integer,primary_key=True);code=Column(String(80),unique=True,nullable=False);title=Column(String(160),nullable=False);attributes=Column(JSON,nullable=False);note=Column(String(300),default='')
class Dependency(Base):
    __tablename__='dependencies'
    id=Column(Integer,primary_key=True);relation_id=Column(Integer,ForeignKey('relations.id'),nullable=False);lhs=Column(JSON,nullable=False);rhs=Column(JSON,nullable=False);note=Column(String(300),default='')
class Report(Base):
    __tablename__='reports'
    id=Column(Integer,primary_key=True);name=Column(String(120),nullable=False);relation_id=Column(Integer,ForeignKey('relations.id'),nullable=False)
    status=Column(String(20),nullable=False,default='queued');input_snapshot=Column(JSON,nullable=False);result=Column(JSON,nullable=True);error=Column(Text,nullable=True)
    created_at=Column(DateTime(timezone=True),default=lambda:datetime.now(timezone.utc))
class IndexTrial(Base):
    __tablename__='index_trials'
    id=Column(Integer,primary_key=True);name=Column(String(120),nullable=False);report_id=Column(Integer,ForeignKey('reports.id'),nullable=False)
    status=Column(String(20),nullable=False,default='queued');run_token=Column(String(40),nullable=False)
    input_snapshot=Column(JSON,nullable=False);result=Column(JSON,nullable=True);error=Column(Text,nullable=True)
    created_at=Column(DateTime(timezone=True),default=lambda:datetime.now(timezone.utc))
class IndexTrialCombo(Base):
    __tablename__='index_trial_combos'
    id=Column(Integer,primary_key=True);trial_id=Column(Integer,ForeignKey('index_trials.id'),nullable=False)
    combo_key=Column(String(200),nullable=False);index_specs=Column(JSON,nullable=False)
    status=Column(String(20),nullable=False,default='pending');measurements=Column(JSON,nullable=True);error=Column(Text,nullable=True)
    measured_at=Column(DateTime(timezone=True),nullable=True)
class Audit(Base):
    __tablename__='audit_logs'
    id=Column(Integer,primary_key=True);actor=Column(String(120),nullable=False);action=Column(String(160),nullable=False);created_at=Column(DateTime(timezone=True),default=lambda:datetime.now(timezone.utc))
