#!/usr/bin/env python3
import json
from pathlib import Path
import process.tmp_render_all_second_stage_posts as r

TITLE='Broadcasting (Amendment) Bill 2026'
rows,_=r.load_rows()
row=next((x for x in rows if x['title']==TITLE),None)
if row is None:
    raise SystemExit('bill not found')
keys=['bill_id','title','bill_no','bill_year','origin_house_name','current_stage_house_name','primary_sponsor_name','primary_sponsor_role_name','primary_sponsor_type']
out={k:row.get(k,'') for k in keys}
Path('artifacts/sponsor-inspect').mkdir(parents=True,exist_ok=True)
Path('artifacts/sponsor-inspect/broadcasting.json').write_text(json.dumps(out,ensure_ascii=False,indent=2),encoding='utf-8')
print(json.dumps(out,ensure_ascii=False,indent=2))
