from pydantic import BaseModel,Field,field_validator

class SampleRow(BaseModel):
    values:dict[str,str]=Field(min_length=1,max_length=10)

class QueryInput(BaseModel):
    label:str=Field(min_length=1,max_length=80)
    sql:str=Field(min_length=1,max_length=1000)

class CandidateIndexInput(BaseModel):
    name:str=Field(min_length=1,max_length=60)
    columns:list[str]=Field(min_length=1,max_length=10)

class TrialInput(BaseModel):
    name:str=Field(min_length=2,max_length=120)
    report_id:int=Field(gt=0)
    table_name:str=Field(min_length=1,max_length=60)
    capacity_bytes:int=Field(gt=0,le=10**12)
    sample_rows:list[SampleRow]=Field(min_length=1,max_length=200000)
    queries:list[QueryInput]=Field(min_length=1,max_length=20)
    candidate_indexes:list[CandidateIndexInput]=Field(min_length=1,max_length=12)
    @field_validator('table_name')
    @classmethod
    def table_valid(cls,v):
        v=v.strip()
        if not v.replace('_','').isalnum() or v[0].isdigit():raise ValueError('表名只能含字母数字下划线且不以数字开头')
        return v
    @field_validator('sample_rows')
    @classmethod
    def rows_valid(cls,v):
        keys=[set(r.values.keys()) for r in v]
        if any(k!=keys[0] for k in keys):raise ValueError('每行样本必须包含完全相同的属性列')
        if any(not k or len(k)>10 for k in keys):raise ValueError('样本属性列须为1–10个')
        if any(any(not c.strip() or len(c)>40 for c in r.values.values()) for r in v):raise ValueError('样本值不能为空且长度不超过40')
        return v
    @field_validator('queries')
    @classmethod
    def queries_valid(cls,v):
        labels=[q.label.strip() for q in v]
        if len(set(labels))!=len(labels):raise ValueError('查询标签不能重复')
        for q in v:
            text=q.sql.strip().lower()
            if not text.startswith('select'):raise ValueError('常用查询必须是只读 SELECT 语句')
            if any(w in text for w in ('insert','update','delete','drop','alter','create','truncate',';')):
                raise ValueError('查询只允许单条只读 SELECT，禁止 DDL/DML 与分号')
        return v
    @field_validator('candidate_indexes')
    @classmethod
    def indexes_valid(cls,v):
        names=[i.name.strip() for i in v]
        if len(set(names))!=len(names):raise ValueError('候选索引名称不能重复')
        for item in v:
            if len(set(item.columns))!=len(item.columns):raise ValueError('同一索引内列不能重复')
        return v
