#!/usr/bin/env python3
from __future__ import annotations
import io,json,os
from pathlib import Path
import boto3,pandas as pd
from extract.oireachtas.batch import resolve_production_key
BUCKET=os.getenv('S3_BUCKET','eirepolitic-data'); s3=boto3.client('s3',region_name=os.getenv('AWS_REGION','ca-central-1'))
def read(k):
 rk=resolve_production_key(s3,bucket=BUCKET,production_key=k); o=s3.get_object(Bucket=BUCKET,Key=rk); return pd.read_csv(io.BytesIO(o['Body'].read()),dtype=str,keep_default_na=False)
bills=read('processed/oireachtas_unified/latest/csv/silver_bills.csv'); sponsors=read('processed/oireachtas_unified/latest/csv/silver_bill_sponsors.csv')
titles=['Broadcasting (Amendment) Bill 2026','Anti-Shrinkflation Bill 2026','Defence (Amendment) (No. 2) Bill 2026','Statute Law Revision Bill 2026','Coroners (Amendment) Bill 2026']
out=[]
for t in titles:
 b=bills[bills['title'].eq(t)]
 if not len(b): out.append({'title':t,'error':'not found'}); continue
 bid=b.iloc[0]['bill_id']; ss=sponsors[sponsors['bill_id'].eq(bid)]
 out.append({'title':t,'bill_id':bid,'sponsors':ss.to_dict(orient='records')})
Path('artifacts/sponsor-row-inspect').mkdir(parents=True,exist_ok=True); Path('artifacts/sponsor-row-inspect/sample.json').write_text(json.dumps(out,ensure_ascii=False,indent=2),encoding='utf-8'); print(json.dumps(out,ensure_ascii=False,indent=2))
