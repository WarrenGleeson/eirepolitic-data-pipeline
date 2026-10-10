#!/usr/bin/env python3
from __future__ import annotations
import io, json, os, urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path
import boto3, pandas as pd
from extract.oireachtas.batch import resolve_production_key

BUCKET=os.getenv('S3_BUCKET','eirepolitic-data')
s3=boto3.client('s3',region_name=os.getenv('AWS_REGION','ca-central-1'))

def read_csv(key):
    real=resolve_production_key(s3,bucket=BUCKET,production_key=key)
    obj=s3.get_object(Bucket=BUCKET,Key=real)
    return pd.read_csv(io.BytesIO(obj['Body'].read()),dtype=str,keep_default_na=False)

bills=read_csv('processed/oireachtas_unified/latest/csv/silver_bills.csv')
manifest_url='https://raw.githubusercontent.com/eirepolitic/Eirepolitic-data-pipeline/previews/bill-tracker-second-stage-all/manifest.json'
with urllib.request.urlopen(manifest_url,timeout=30) as r:
    manifest=json.loads(r.read().decode('utf-8'))

house_by_title={str(r['title']):str(r.get('current_stage_house_name','')) for _,r in bills.iterrows()}
missing=[t for p in manifest['posts'] for t in p['bills'] if t not in house_by_title]
if missing:
    raise SystemExit(f'missing house for titles: {missing}')

start=datetime(2026,10,12,8,0,tzinfo=timezone.utc)
rows=[]
for i,p in enumerate(manifest['posts']):
    day=i//2
    hour=8 if i%2==0 else 12
    scheduled=start.replace(hour=hour)+timedelta(days=day)
    houses=[house_by_title[t] for t in p['bills']]
    norm=['seanad' if 'seanad' in h.lower() else 'dáil' for h in houses]
    if all(h=='seanad' for h in norm):
        house_tag='#SeanadÉireann'; house_mix='Seanad-only'
    elif all(h=='dáil' for h in norm):
        house_tag='#DáilÉireann'; house_mix='Dáil-only'
    else:
        house_tag='#DáilÉireann'; house_mix='Mixed Dáil/Seanad'
    tags=['#EirePolitic','#Oireachtas','#IrishPolitics','#Legislation',house_tag]

    if p['post']==1:
        intro=("We’re continuing our Bills of the Current Session series with four Bills currently at Second Stage. "
               "This is where the Dáil or Seanad considers the Bill’s main purpose and whether it should continue through the legislative process.")
    elif p['post']==manifest['post_count']:
        intro=("This final post in our Second Stage series covers the remaining four Bills currently at this stage. "
               "Second Stage is where the Dáil or Seanad considers a Bill’s main purpose and whether it should continue through the legislative process.")
    else:
        intro=("Continuing our look at Bills currently at Second Stage, these next four Bills are at the point where the Dáil or Seanad considers "
               "the Bill’s main purpose and whether it should continue through the legislative process.")

    bullet='\n'.join('• '+t for t in p['bills'])
    caption=(intro+'\n\nThis post covers:\n\n'+bullet+
             '\n\nSwipe through to see what each Bill would do, who brought it forward, how long it has been at Second Stage, and the latest recorded activity.'+
             '\n\n'+' '.join(tags))
    rows.append({
        'post':p['post'],
        'scheduled_at_utc':scheduled.isoformat().replace('+00:00','Z'),
        'house_mix':house_mix,
        'houses':houses,
        'bills':p['bills'],
        'hashtags':tags,
        'caption':caption,
    })

out={'strategy':{'start_utc':'2026-10-12T08:00:00Z','cadence':'2 posts/day at 08:00 and 12:00 UTC; final day 1 post','post_count':27,'posting_days':14},'posts':rows}
Path('artifacts/second-stage-schedule-plan').mkdir(parents=True,exist_ok=True)
Path('artifacts/second-stage-schedule-plan/plan.json').write_text(json.dumps(out,ensure_ascii=False,indent=2),encoding='utf-8')
md=['# Second Stage Bill Tracker — proposed schedule and captions','',f"Start: {out['strategy']['start_utc']}",f"Cadence: {out['strategy']['cadence']}",'']
for r in rows:
    md += [f"## Post {r['post']} — {r['scheduled_at_utc']} — {r['house_mix']}",'',r['caption'],'']
Path('artifacts/second-stage-schedule-plan/plan.md').write_text('\n'.join(md),encoding='utf-8')
print(json.dumps({'post_count':len(rows),'house_mix_counts':pd.Series([r['house_mix'] for r in rows]).value_counts().to_dict(),'first':rows[0],'last':rows[-1]},ensure_ascii=False,indent=2))
