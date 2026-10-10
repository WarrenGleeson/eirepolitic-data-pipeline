#!/usr/bin/env python3
from __future__ import annotations
import io,json,os,sys
from pathlib import Path
import boto3,pandas as pd
ROOT=Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path: sys.path.insert(0,str(ROOT))
from extract.oireachtas.batch import resolve_production_key
from political_metrics.bill_content_snapshot import build_bill_content_snapshot
BUCKET=os.getenv('S3_BUCKET','eirepolitic-data'); s3=boto3.client('s3',region_name=os.getenv('AWS_REGION','ca-central-1'))
KEYS={'bills':'processed/oireachtas_unified/latest/csv/silver_bills.csv','stages':'processed/oireachtas_unified/latest/csv/silver_bill_stages.csv','sponsors':'processed/oireachtas_unified/latest/csv/silver_bill_sponsors.csv','bridge':'processed/oireachtas_unified/latest/metrics/event/bill_debate_sections/csv/bill_debate_sections.csv','speeches':'processed/oireachtas_unified/latest/csv/silver_speeches.csv','divisions':'processed/oireachtas_unified/latest/csv/silver_divisions.csv','member_votes':'processed/oireachtas_unified/latest/csv/silver_member_votes.csv'}
def read(k):
 rk=resolve_production_key(s3,bucket=BUCKET,production_key=k); o=s3.get_object(Bucket=BUCKET,Key=rk); return pd.read_csv(io.BytesIO(o['Body'].read()),dtype=str,keep_default_na=False)
f={n:read(k) for n,k in KEYS.items()}
s=build_bill_content_snapshot(bills=f['bills'],stages=f['stages'],sponsors=f['sponsors'],bill_debate_sections=f['bridge'],speeches=f['speeches'],divisions=f['divisions'],member_votes=f['member_votes'],batch_size=6)
x=s[s['series_bucket'].eq('second_stage')].copy(); x['_last']=pd.to_datetime(x['last_event_date'],errors='coerce')
def keep(r):
 h=str(r.get('current_stage_house_name','')).lower(); dt=r['_last']
 return pd.notna(dt) and ((h in {'34th dáil','34th dail'} and dt>=pd.Timestamp('2024-12-18')) or (h=='27th seanad' and dt>=pd.Timestamp('2025-02-12')))
x=x[x.apply(keep,axis=1)]
ss=f['sponsors']; primary=ss[ss['is_primary'].str.lower().eq('true')].copy()
rows=[]
for _,r in x.iterrows():
 bid=r['bill_id']; pr=primary[primary['bill_id'].eq(bid)]
 if len(pr):
  p=pr.iloc[0]; role=str(p.get('sponsor_role_name','')).strip(); name=str(p.get('sponsor_name','')).strip()
 else: role=name=''
 if role.lower().startswith('minister'):
  rows.append({'bill_id':bid,'title':r['title'],'bill_no':r.get('bill_no',''),'bill_year':r.get('bill_year',''),'introduced_date':r.get('introduced_date',''),'current_stage_date':r.get('current_stage_date',''),'sponsor_role_name':role,'sponsor_name':name})
out={'count':len(rows),'roles':sorted(set(r['sponsor_role_name'] for r in rows)),'rows':sorted(rows,key=lambda z:(z['sponsor_role_name'],z['introduced_date'],z['title']))}
Path('artifacts/minister-sponsors').mkdir(parents=True,exist_ok=True); Path('artifacts/minister-sponsors/summary.json').write_text(json.dumps(out,ensure_ascii=False,indent=2),encoding='utf-8'); print(json.dumps({'count':out['count'],'role_count':len(out['roles']),'roles':out['roles']},ensure_ascii=False,indent=2))
