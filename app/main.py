"""Employee Attendance & Analytics API for the HROne engineering assignment."""
import json
import os, re, calendar
from datetime import datetime, date, time, timedelta, timezone
from decimal import Decimal, ROUND_HALF_UP
from typing import Optional, Literal

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, Query, Path
from pydantic import BaseModel, ConfigDict, Field, field_validator
from pymongo import MongoClient, ASCENDING, DESCENDING, ReturnDocument
from pymongo.errors import DuplicateKeyError, PyMongoError
from bson import json_util

load_dotenv()  # real environment variables take precedence over .env
IST = timezone(timedelta(hours=5, minutes=30))
UTC = timezone.utc
client = MongoClient(os.getenv("MONGO_URI", "mongodb://localhost:27017"), tz_aware=True, serverSelectionTimeoutMS=2500)
db = client[os.getenv("MONGO_DB", "attendance_db")]
app = FastAPI(title="Employee Attendance & Analytics API", version="2.0.0")
PRESENCE = {"PRESENT", "WFH", "ON_DUTY"}
STATUSES = PRESENCE | {"ABSENT", "LEAVE"}


def now_utc(): return datetime.now(UTC).replace(microsecond=0)
def round_half_up(value, places=2):
    q = Decimal("1") if places == 0 else Decimal("1").scaleb(-places)
    return float(Decimal(str(value)).quantize(q, rounding=ROUND_HALF_UP)) if places else int(Decimal(str(value)).quantize(q, rounding=ROUND_HALF_UP))
def epoch_ms(dt):
    if dt is None: return None
    if dt.tzinfo is None: dt = dt.replace(tzinfo=UTC)
    return int(dt.timestamp() * 1000)
def from_epoch(value, field="timestamp"):
    if value is None: return None
    if isinstance(value, bool) or not isinstance(value, int) or not (100_000_000_000 <= value <= 4_102_444_800_000):
        raise HTTPException(422, f"{field} must be an integer epoch timestamp in milliseconds")
    return datetime.fromtimestamp(value / 1000, UTC).replace(microsecond=0)
def as_utc(dt):
    if dt is None: return None
    return dt.replace(tzinfo=UTC) if dt.tzinfo is None else dt.astimezone(UTC)
def api_doc(doc):
    if not doc: return doc
    d = dict(doc); d.pop("_id", None)
    for key in ("created_at", "punch_in", "punch_out"):
        if key in d and isinstance(d[key], datetime): d[key] = epoch_ms(d[key])
    d.setdefault("history", [])
    d.setdefault("half_day", False)
    for h in d.get("history", []):
        if isinstance(h.get("at"), datetime): h["at"] = epoch_ms(h["at"])
        for change in h.get("changes", {}).values():
            for side in ("from", "to"):
                if isinstance(change.get(side), datetime): change[side] = epoch_ms(change[side])
    return d
def validate_date(s):
    try: return date.fromisoformat(s)
    except Exception: raise HTTPException(422, "date must be YYYY-MM-DD")
def validate_month(s):
    if not re.fullmatch(r"\d{4}-(0[1-9]|1[0-2])", s or ""): raise HTTPException(422, "month must be YYYY-MM")
    y,m=map(int,s.split('-')); return date(y,m,1), date(y,m,calendar.monthrange(y,m)[1])
def ist_local_dt(dt): return as_utc(dt).astimezone(IST)
def shift_boundary(day, hhmm, overnight=False):
    h,m=map(int,hhmm.split(':'))
    d = day + timedelta(days=1) if overnight else day
    return datetime.combine(d, time(h,m), IST).astimezone(UTC)
def calc_late(punch_in, emp, attendance_day):
    local=ist_local_dt(punch_in); day=validate_date(attendance_day)
    sh,sm=map(int,emp['shift_start'].split(':')); eh,em=map(int,emp['shift_end'].split(':'))
    overnight=(eh,em) <= (sh,sm)
    # R1: an early-morning punch on an overnight shift belongs to previous shift day.
    shift_day=day-timedelta(days=1) if overnight and (local.hour,local.minute)<(eh,em) else day
    start=datetime.combine(shift_day,time(sh,sm),IST).astimezone(UTC)
    seconds=(punch_in-start).total_seconds()
    mins=int(seconds//60)
    return mins if seconds > 600 else 0
def calc_overtime(punch_out, emp, attendance_day):
    day=validate_date(attendance_day); sh,sm=map(int,emp['shift_start'].split(':')); eh,em=map(int,emp['shift_end'].split(':'))
    overnight=(eh,em) <= (sh,sm)
    end=shift_boundary(day, emp['shift_end'], overnight)
    mins=int((punch_out-end).total_seconds()//60)
    return mins if mins >= 30 else 0
def derived(emp, day, status, pin, pout):
    if status not in PRESENCE: return {"work_hours":None,"late_minutes":0,"overtime_minutes":0,"half_day":False}
    late=calc_late(pin,emp,day) if pin else 0
    if pout is None: return {"work_hours":None,"late_minutes":late,"overtime_minutes":0,"half_day":False}
    hours=round_half_up((pout-pin).total_seconds()/3600,2)
    return {"work_hours":hours,"late_minutes":late,"overtime_minutes":calc_overtime(pout,emp,day),"half_day":hours < 4.5}

class EmployeeIn(BaseModel):
    model_config=ConfigDict(extra="forbid")
    emp_code:str=Field(pattern=r'^EMP\d{4,6}$')
    name:str=Field(min_length=1,max_length=100)
    email:str=Field(max_length=120,pattern=r'^[^@\s]+@[^@\s]+\.[^@\s]+$')
    department:str=Field(min_length=1,max_length=50)
    shift_start:str='09:30'; shift_end:str='18:30'; joined_on:str
    @field_validator('shift_start','shift_end')
    @classmethod
    def valid_shift(cls,v):
        if not re.fullmatch(r'([01]\d|2[0-3]):[0-5]\d',v): raise ValueError('must be HH:MM')
        return v
    @field_validator('joined_on')
    @classmethod
    def valid_joined(cls,v): date.fromisoformat(v); return v
class PunchInIn(BaseModel):
    model_config=ConfigDict(extra='forbid')
    emp_code:str
    punched_at:Optional[int]=None
    status:Literal['PRESENT','WFH','ON_DUTY']='PRESENT'
class PunchOutIn(BaseModel):
    model_config=ConfigDict(extra='forbid')
    emp_code:str
    punched_at:Optional[int]=None
class RegularizeIn(BaseModel):
    model_config=ConfigDict(extra='forbid')
    status:Optional[Literal['PRESENT','WFH','ON_DUTY','ABSENT','LEAVE']]=None
    punch_in:Optional[int]=None
    punch_out:Optional[int]=None
    reason:str=Field(min_length=5,max_length=200)
    regularized_by:str=Field(min_length=1,max_length=50)

@app.on_event('startup')
def create_indexes():
    db.employees.create_index([('emp_code',ASCENDING)],unique=True,name='uq_employee_code')
    db.employees.create_index([('department',ASCENDING),('emp_code',ASCENDING)],name='department_employee')
    db.employees.create_index([('department',ASCENDING),('joined_on',ASCENDING)],name='department_joined')
    db.employees.create_index([('joined_on',ASCENDING)],name='employee_joined_on')
    db.attendance_logs.create_index([('emp_code',ASCENDING),('date',ASCENDING)],unique=True,name='uq_employee_attendance_day')
    db.attendance_logs.create_index([('date',DESCENDING),('emp_code',ASCENDING)],name='attendance_date_employee')
    db.attendance_logs.create_index([('status',ASCENDING),('date',DESCENDING)],name='attendance_status_date')
    db.attendance_logs.create_index([('date',ASCENDING),('late_minutes',DESCENDING),('emp_code',ASCENDING)],name='attendance_late_date')

@app.get('/health')
def health():
    try: client.admin.command('ping'); return {'status':'ok'}
    except PyMongoError: raise HTTPException(503,'MongoDB unavailable')

@app.post('/employees',status_code=201)
def create_employee(body:EmployeeIn):
    doc=body.model_dump(); doc['created_at']=now_utc()
    try: db.employees.insert_one(doc)
    except DuplicateKeyError: raise HTTPException(409,'emp_code already exists')
    return api_doc(doc)

@app.get('/employees')
def list_employees(department:Optional[str]=None,page:int=Query(1,ge=1),page_size:int=Query(20,ge=1,le=100)):
    q={'department':department} if department else {}
    total=db.employees.count_documents(q)
    items=list(db.employees.find(q,{'_id':0}).sort('emp_code',ASCENDING).skip((page-1)*page_size).limit(page_size))
    return {'items':[api_doc(x) for x in items],'total':total,'page':page,'page_size':page_size}

@app.post('/attendance/punch-in',status_code=201)
def punch_in(body:PunchInIn):
    emp=db.employees.find_one({'emp_code':body.emp_code})
    if not emp: raise HTTPException(404,'employee not found')
    ts=from_epoch(body.punched_at,'punched_at') if body.punched_at is not None else now_utc()
    local=ts.astimezone(IST); day=local.date(); sh,sm=map(int,emp['shift_start'].split(':')); eh,em=map(int,emp['shift_end'].split(':'))
    if (eh,em)<=(sh,sm) and (local.hour,local.minute)<(eh,em): day-=timedelta(days=1)
    day_s=day.isoformat(); fields=derived(emp,day_s,body.status,ts,None)
    doc={'emp_code':body.emp_code,'date':day_s,'status':body.status,'punch_in':ts,'punch_out':None,**fields,'history':[]}
    try: db.attendance_logs.insert_one(doc)
    except DuplicateKeyError: raise HTTPException(409,'already punched in for this date')
    return api_doc(doc)

@app.post('/attendance/punch-out')
def punch_out(body:PunchOutIn):
    emp=db.employees.find_one({'emp_code':body.emp_code})
    if not emp: raise HTTPException(404,'employee not found')
    ts=from_epoch(body.punched_at,'punched_at') if body.punched_at is not None else now_utc()
    local_day=ts.astimezone(IST).date(); candidates=[local_day.isoformat(),(local_day-timedelta(days=1)).isoformat()]
    rec=db.attendance_logs.find_one({'emp_code':body.emp_code,'date':{'$in':candidates},'punch_out':None,'punch_in':{'$ne':None}},sort=[('date',DESCENDING)])
    if not rec: raise HTTPException(404,'open attendance record not found')
    pin=as_utc(rec['punch_in'])
    if ts <= pin: raise HTTPException(422,'punched_at must be after punch_in')
    fields=derived(emp,rec['date'],rec['status'],pin,ts)
    updated=db.attendance_logs.find_one_and_update({'_id':rec['_id'],'punch_out':None},{'$set':{'punch_out':ts,**fields}},return_document=ReturnDocument.AFTER)
    if not updated: raise HTTPException(409,'attendance record was already punched out')
    return api_doc(updated)

@app.get('/attendance')
def list_attendance(emp_code:Optional[str]=None,date_from:Optional[str]=None,date_to:Optional[str]=None,status:Optional[str]=None,page:int=Query(1,ge=1),page_size:int=Query(20,ge=1,le=100)):
    q={}
    if emp_code: q['emp_code']=emp_code
    if date_from or date_to:
        q['date']={}
        if date_from: validate_date(date_from); q['date']['$gte']=date_from
        if date_to: validate_date(date_to); q['date']['$lte']=date_to
    if status:
        if status not in STATUSES: raise HTTPException(422,'invalid status')
        q['status']=status
    total=db.attendance_logs.count_documents(q)
    docs=list(db.attendance_logs.find(q,{'_id':0}).sort([('date',DESCENDING),('emp_code',ASCENDING)]).skip((page-1)*page_size).limit(page_size))
    return {'items':[api_doc(d) for d in docs],'total':total,'page':page,'page_size':page_size}

@app.patch('/attendance/{emp_code}/{date}')
def regularize(emp_code:str,date:str,body:RegularizeIn):
    validate_date(date)
    old=db.attendance_logs.find_one({'emp_code':emp_code,'date':date})
    if not old: raise HTTPException(404,'attendance record not found')
    emp=db.employees.find_one({'emp_code':emp_code})
    if not emp: raise HTTPException(404,'employee not found')
    status=body.status if body.status is not None else old['status']
    pin=from_epoch(body.punch_in,'punch_in') if body.punch_in is not None else as_utc(old.get('punch_in'))
    pout=from_epoch(body.punch_out,'punch_out') if body.punch_out is not None else as_utc(old.get('punch_out'))
    if status in PRESENCE and pin is None: raise HTTPException(422,'presence status requires punch_in')
    if status not in PRESENCE: pin=pout=None
    if pin and pout and pout<=pin: raise HTTPException(422,'punch_out must be after punch_in')
    new={**derived(emp,date,status,pin,pout),'status':status,'punch_in':pin,'punch_out':pout}
    tracked=['status','punch_in','punch_out','work_hours','late_minutes','overtime_minutes','half_day']; changes={}
    for k in tracked:
        before=old.get(k,False if k=='half_day' else 0 if k in ('late_minutes','overtime_minutes') else None)
        after=new.get(k)
        if isinstance(before,datetime): before=as_utc(before)
        if before != after: changes[k]={'from':before,'to':after}
    if changes:
        entry={'at':now_utc(),'by':body.regularized_by,'reason':body.reason,'changes':changes}
        # Atomic $push prevents simultaneous regularizations from overwriting one another.
        updated=db.attendance_logs.find_one_and_update({'_id':old['_id']},{'$set':new,'$push':{'history':entry}},return_document=ReturnDocument.AFTER)
    else: updated=old
    return api_doc(updated)

# Analytics pipelines intentionally perform grouping/joining/ranking in MongoDB.
def month_match(month):
    start,end=validate_month(month); return start.isoformat(),end.isoformat()
def present_expr(): return {'$cond':[{'$in':['$status',list(PRESENCE)]},{'$cond':[{'$eq':['$half_day',True]},0.5,1]},0]}
def present_workday_expr():
    return {'$cond':[{'$and':[{'$in':['$status',list(PRESENCE)]},{'$in':[{'$dayOfWeek':{'$dateFromString':{'dateString':'$date'}}},[2,3,4,5,6]]}]},{'$cond':[{'$eq':[{'$ifNull':['$half_day',False]},True]},0.5,1]},0]}

@app.get('/analytics/employees/{emp_code}/monthly')
def employee_monthly(emp_code:str,month:str):
    start,end=month_match(month)
    emp=db.employees.find_one({'emp_code':emp_code},{'_id':0})
    if not emp: raise HTTPException(404,'employee not found')
    working_rows=list(db.employees.aggregate([
        {'$match': {'emp_code': emp_code, 'joined_on': {'$lte': end}}},
        {'$set': {'period_start': {'$dateFromString': {'dateString': {'$cond': [{'$gt': ['$joined_on', start]}, '$joined_on', start]}}},
                  'period_end': {'$dateFromString': {'dateString': end}}}},
        {'$set': {'day_offsets': {'$range': [0, {'$add': [{'$dateDiff': {'startDate': '$period_start', 'endDate': '$period_end', 'unit': 'day'}}, 1]}]}}},
        {'$set': {'working_days': {'$size': {'$filter': {'input': {'$map': {'input': '$day_offsets', 'as': 'offset', 'in': {'$dateAdd': {'startDate': '$period_start', 'unit': 'day', 'amount': '$$offset'}}}}, 'as': 'day', 'cond': {'$in': [{'$dayOfWeek': '$$day'}, [2, 3, 4, 5, 6]]}}}}}},
        {'$project': {'_id': 0, 'working_days': 1}}
    ]))
    working=working_rows[0]['working_days'] if working_rows else 0
    pipeline=[{'$match':{'emp_code':emp_code,'date':{'$gte':start,'$lte':end}}},{'$group':{'_id':None,'present_days':{'$sum':present_workday_expr()},'leave_days':{'$sum':{'$cond':[{'$eq':['$status','LEAVE']},1,0]}},'late_count':{'$sum':{'$cond':[{'$gt':[{'$ifNull':['$late_minutes',0]},0]},1,0]}},'total_late_minutes':{'$sum':{'$ifNull':['$late_minutes',0]}},'total_overtime_minutes':{'$sum':{'$ifNull':['$overtime_minutes',0]}}}}]
    row=list(db.attendance_logs.aggregate(pipeline)); r=row[0] if row else {}
    return {'emp_code':emp_code,'month':month,'working_days':working,'present_days':round_half_up(r.get('present_days',0),2),'leave_days':r.get('leave_days',0),'late_count':r.get('late_count',0),'total_late_minutes':r.get('total_late_minutes',0),'total_overtime_minutes':r.get('total_overtime_minutes',0),'attendance_pct':round_half_up(100*r.get('present_days',0)/working,2) if working else None}

@app.get('/analytics/departments/summary')
def department_summary(month:str,department:Optional[str]=None):
    start,end=month_match(month)
    emp_match={'joined_on':{'$lte':end}}
    if department: emp_match['department']=department
    pipeline=[{'$match':emp_match},{'$lookup':{'from':'attendance_logs','let':{'code':'$emp_code'},'pipeline':[{'$match':{'$expr':{'$and':[{'$eq':['$emp_code','$$code']},{'$gte':['$date',start]},{'$lte':['$date',end]}]}}},{'$group':{'_id':None,'present_days':{'$sum':present_workday_expr()},'leave_days':{'$sum':{'$cond':[{'$eq':['$status','LEAVE']},1,0]}},'late_count':{'$sum':{'$cond':[{'$gt':[{'$ifNull':['$late_minutes',0]},0]},1,0]}},'total_late_minutes':{'$sum':{'$ifNull':['$late_minutes',0]}},'total_overtime_minutes':{'$sum':{'$ifNull':['$overtime_minutes',0]}},'record_count':{'$sum':1},'hours_sum':{'$sum':{'$cond':[{'$and':[{'$in':['$status',list(PRESENCE)]},{'$ne':['$work_hours',None]}]},'$work_hours',0]}},'hours_count':{'$sum':{'$cond':[{'$and':[{'$in':['$status',list(PRESENCE)]},{'$ne':['$work_hours',None]}]},1,0]}},'leave_count':{'$sum':{'$cond':[{'$eq':['$status','LEAVE']},1,0]}},'on_duty_count':{'$sum':{'$cond':[{'$eq':['$status','ON_DUTY']},1,0]}}}}],'as':'stats'}},{'$unwind':{'path':'$stats','preserveNullAndEmptyArrays':True}},{'$group':{'_id':'$department','headcount':{'$sum':1},'present_days':{'$sum':{'$ifNull':['$stats.present_days',0]}},'leave_count':{'$sum':{'$ifNull':['$stats.leave_count',0]}},'on_duty_count':{'$sum':{'$ifNull':['$stats.on_duty_count',0]}},'late_count':{'$sum':{'$ifNull':['$stats.late_count',0]}},'total_late_minutes':{'$sum':{'$ifNull':['$stats.total_late_minutes',0]}},'total_overtime_minutes':{'$sum':{'$ifNull':['$stats.total_overtime_minutes',0]}},'record_count':{'$sum':{'$ifNull':['$stats.record_count',0]}},'hours_sum':{'$sum':{'$ifNull':['$stats.hours_sum',0]}},'hours_count':{'$sum':{'$ifNull':['$stats.hours_count',0]}}}},{'$project':{'_id':0,'department':'$_id','headcount':1,'present_days':1,'leave_count':1,'on_duty_count':1,'late_count':1,'total_late_minutes':1,'avg_work_hours':{'$cond':[{'$gt':['$hours_count',0]},{'$round':[{'$divide':['$hours_sum','$hours_count']},2]},None]}}},{'$sort':{'department':1}}]
    rows=list(db.employees.aggregate(pipeline))
    rows=[r for r in rows if r.get('headcount',0)>0]
    return {'month':month,'items':rows}

@app.get('/analytics/leaderboard/late')
def late_leaderboard(month:str,limit:int=Query(10,ge=1,le=50),department:Optional[str]=None):
    start,end=month_match(month)
    pipeline=[{'$match':{'date':{'$gte':start,'$lte':end},'late_minutes':{'$gt':0}}},{'$group':{'_id':'$emp_code','total_late_minutes':{'$sum':'$late_minutes'},'late_count':{'$sum':1}}},{'$lookup':{'from':'employees','localField':'_id','foreignField':'emp_code','as':'employee'}},{'$unwind':'$employee'}]
    if department: pipeline.append({'$match':{'employee.department':department}})
    pipeline += [{'$set':{'emp_code':'$_id','name':'$employee.name','department':'$employee.department'}},{'$setWindowFields':{'sortBy':{'total_late_minutes':-1},'output':{'rank':{'$rank':{}}}}},{'$match':{'rank':{'$lte':limit}}},{'$project':{'_id':0,'emp_code':1,'name':1,'department':1,'total_late_minutes':1,'late_count':1,'rank':1}},{'$sort':{'total_late_minutes':-1,'emp_code':1}}]
    return {'month':month,'items':list(db.attendance_logs.aggregate(pipeline))}

@app.get('/analytics/departments/{department}/trend')
def department_trend(department:str,from_:str=Query(...,alias='from'),to:str=Query(...)):
    fd=validate_date(from_); td=validate_date(to)
    if td<fd: raise HTTPException(422,"to must be on or after from")
    if (td-fd).days+1>92: raise HTTPException(422,'date range cannot exceed 92 days')
    if not db.employees.find_one({'department':department}): raise HTTPException(404,'unknown department')
    # Start from a seed date so even a range with zero attendance records gets every day.
    # $documents is supported by MongoDB 6.0+ and is valid as the first stage of db.aggregate.
    pipeline = [
        {'$documents': [{'day': datetime.combine(fd, time.min)}]},
        {'$densify': {'field': 'day', 'range': {'step': 1, 'unit': 'day', 'bounds': [datetime.combine(fd, time.min), datetime.combine(td + timedelta(days=1), time.min)]}}},
        {'$set': {'day_string': {'$dateToString': {'format': '%Y-%m-%d', 'date': '$day'}}}},
        {'$lookup': {
            'from': 'attendance_logs',
            'let': {'day_string': '$day_string'},
            'pipeline': [
                {'$match': {'$expr': {'$eq': ['$date', '$$day_string']}}},
                {'$lookup': {'from': 'employees', 'localField': 'emp_code', 'foreignField': 'emp_code', 'as': 'employee'}},
                {'$unwind': '$employee'},
                {'$match': {'employee.department': department}},
                {'$group': {'_id': None,
                            'present_count': {'$sum': present_expr()},
                            'late_count': {'$sum': {'$cond': [{'$gt': [{'$ifNull': ['$late_minutes', 0]}, 0]}, 1, 0]}}}}
            ],
            'as': 'daily'
        }},
        {'$lookup': {
            'from': 'employees',
            'let': {'day_string': '$day_string'},
            'pipeline': [
                {'$match': {'$expr': {'$and': [{'$eq': ['$department', department]}, {'$lte': ['$joined_on', '$$day_string']}]}}},
                {'$count': 'n'}
            ],
            'as': 'hc'
        }},
        {'$set': {
            'present_count': {'$ifNull': [{'$arrayElemAt': ['$daily.present_count', 0]}, 0]},
            'late_count': {'$ifNull': [{'$arrayElemAt': ['$daily.late_count', 0]}, 0]},
            'headcount': {'$ifNull': [{'$arrayElemAt': ['$hc.n', 0]}, 0]},
            'is_working_day': {'$in': [{'$dayOfWeek': '$day'}, [2, 3, 4, 5, 6]]}
        }},
        {'$set': {'attendance_rate': {'$cond': [
            {'$and': ['$is_working_day', {'$gt': ['$headcount', 0]}]},
            {'$round': [{'$divide': ['$present_count', '$headcount']}, 4]}, None
        ]}}},
        {'$setWindowFields': {'sortBy': {'day': 1}, 'output': {
            'moving_avg_7d': {'$avg': '$attendance_rate', 'window': {'documents': [-6, 0]}}
        }}},
        {'$project': {'_id': 0, 'date': '$day_string', 'is_working_day': 1, 'headcount': 1,
                      'present_count': 1, 'late_count': 1, 'attendance_rate': 1, 'moving_avg_7d': 1}},
        {'$sort': {'date': 1}}
    ]
    return {'department': department, 'from': from_, 'to': to, 'items': list(db.aggregate(pipeline))}

@app.get('/admin/explain/{endpoint}')
def explain_endpoint(endpoint:str,emp_code:Optional[str]=None,month:Optional[str]=None,department:Optional[str]=None,limit:int=Query(10,ge=1,le=50),date_from:Optional[str]=None,date_to:Optional[str]=None,status:Optional[str]=None,from_:Optional[str]=Query(None,alias='from'),to:Optional[str]=None,page:int=Query(1,ge=1),page_size:int=Query(20,ge=1,le=100)):
    allowed={'attendance_list','employee_monthly','department_summary','late_leaderboard','department_trend'}
    if endpoint not in allowed: raise HTTPException(422,'unsupported endpoint')
    if endpoint=='attendance_list':
        q={}
        if emp_code:q['emp_code']=emp_code
        if date_from:q.setdefault('date',{})['$gte']=date_from
        if date_to:q.setdefault('date',{})['$lte']=date_to
        if status:q['status']=status
        command={'find':'attendance_logs','filter':q,'sort':{'date':-1,'emp_code':1},'skip':(page-1)*page_size,'limit':page_size}
        coll='attendance_logs'
    elif endpoint=='employee_monthly':
        if not emp_code or not month: raise HTTPException(422,'emp_code and month are required')
        s,e=month_match(month); pipe=[{'$match':{'emp_code':emp_code,'date':{'$gte':s,'$lte':e}}},{'$group':{'_id':'$emp_code','records':{'$sum':1}}}]; coll='attendance_logs'; command={'aggregate':coll,'pipeline':pipe,'cursor':{}}
    elif endpoint=='department_summary':
        if not month: raise HTTPException(422,'month is required')
        s,e=month_match(month); pipe=[{'$match':{'joined_on':{'$lte':e},**({'department':department} if department else {})}},{'$lookup':{'from':'attendance_logs','localField':'emp_code','foreignField':'emp_code','as':'logs'}},{'$unwind':{'path':'$logs','preserveNullAndEmptyArrays':True}},{'$match':{'$or':[{'logs':None},{'logs.date':{'$gte':s,'$lte':e}}]}}]; coll='employees'; command={'aggregate':coll,'pipeline':pipe,'cursor':{}}
    elif endpoint=='late_leaderboard':
        if not month: raise HTTPException(422,'month is required')
        s,e=month_match(month); pipe=[{'$match':{'date':{'$gte':s,'$lte':e},'late_minutes':{'$gt':0}}},{'$group':{'_id':'$emp_code','total_late_minutes':{'$sum':'$late_minutes'},'late_count':{'$sum':1}}}]; coll='attendance_logs'; command={'aggregate':coll,'pipeline':pipe,'cursor':{}}
    else:
        if not department or not from_ or not to: raise HTTPException(422,'department, from and to are required')
        validate_date(from_);validate_date(to); coll='attendance_logs'; command={'aggregate':coll,'pipeline':[{'$match':{'date':{'$gte':from_,'$lte':to}}}],'cursor':{}}
    try:
        if 'find' in command: result=db.command({'explain':command,'verbosity':'executionStats'})
        else: result=db.command({'explain':command,'verbosity':'executionStats'})
    except PyMongoError as exc: raise HTTPException(500,f'explain failed: {exc.__class__.__name__}')
    serialized = json_util.dumps(
        {
            "endpoint": endpoint,
            "collection": coll,
            "explain": result,
        }
    )
    return json.loads(serialized)
