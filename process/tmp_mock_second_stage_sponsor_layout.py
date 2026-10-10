#!/usr/bin/env python3
from __future__ import annotations
from pathlib import Path
from PIL import Image, ImageDraw
import process.tmp_render_all_second_stage_posts as r

OUT=Path('artifacts/second-stage-sponsor-mock'); OUT.mkdir(parents=True,exist_ok=True)
TITLE='Broadcasting (Amendment) Bill 2026'
ASSET_DIR=Path('instagram/templates/assets')
MINISTER_NAME='Patrick O’Donovan TD'
MINISTER_ROLE='Minister for Culture, Communications and Sport'

rows,_=r.load_rows()
row=next((x for x in rows if x['title']==TITLE),None)
if row is None: raise SystemExit(f'Bill not found: {TITLE}')
texts=r.SPECIAL[TITLE]


def _is_gold(px):
    rr,gg,bb,aa=px
    if aa == 0:
        return False
    return rr > 150 and gg > 105 and bb < 155 and (rr - bb) > 55 and (gg - bb) > 20


def clean_corner(path: Path) -> Image.Image:
    src=Image.open(path).convert('RGBA')
    out=src.copy()
    p=out.load()
    for y in range(out.height):
        for x in range(out.width):
            if _is_gold(p[x,y]):
                p[x,y]=(15,47,36,255)
    return out


def clean_base_slide() -> Image.Image:
    im=Image.new('RGB',(r.W,r.H),r.BG)
    placements=[
        ('corner_tl.png',(0,0)),('corner_tr.png',(925,0)),
        ('corner_bl.png',(0,1195)),('corner_br.png',(925,1195)),
    ]
    for name,pos in placements:
        c=clean_corner(ASSET_DIR/name).resize((155,155),Image.Resampling.LANCZOS)
        im.paste(c,pos,c)
    return im


im=clean_base_slide(); d=ImageDraw.Draw(im)

# Title: exactly one centred gold underline.
f=r.fit(d,TITLE,900,95,34,22,3,True)
lines=r.wrap_text_px(d,TITLE,f,900)
cur=48
for ln in lines:
    d.text((r.W//2,cur),ln,font=f,fill=r.TEXT,anchor='ma')
    bb=d.textbbox((r.W//2,cur),ln,font=f,anchor='ma')
    cur=bb[3]+3
line_y=max(128,cur+5)
d.rectangle((190,line_y,890,line_y+4),fill=r.ACCENT)

# Supporting metadata recentered beneath the single rule.
ry=line_y+17
meta=f"Bill No. {row.get('bill_no','')} of {row.get('bill_year','')} · {row.get('origin_house_name','')}"
mf=r.fit(d,meta,900,38,18,14,2)
r.draw_block(d,meta,(90,ry,990,ry+40),mf,fill=r.MUTED,center=True)

labels=['WHAT THE BILL COVERS','PRACTICAL EFFECT','SPONSOR / CONTEXT','SECOND STAGE RECORD']
top=ry+48
bh=282
gap=20
boxes=[
    (58,top,518,top+bh),(562,top,1022,top+bh),
    (58,top+bh+gap,518,top+2*bh+gap),(562,top+bh+gap,1022,top+2*bh+gap),
]
shared=14
for s in range(24,13,-1):
    ff=r.font(s)
    if all(r.lines_h(d,r.wrap_text_px(d,txt,ff,408),ff,4)<=190 for txt in texts):
        shared=s
        break
bf=r.font(shared)
for box,label,txt in zip(boxes,labels,texts):
    r.panel(d,box)
    d.text((box[0]+22,box[1]+20),label,font=r.font(16,True),fill=r.ACCENT,anchor='la')
    r.draw_block(d,txt,(box[0]+22,box[1]+58,box[2]-22,box[3]-18),bf)

# Tighter, fuller status box.
sy=boxes[2][3]+22
status_bottom=1038
r.panel(d,(58,sy,1022,status_bottom),outline=r.ACCENT,fill=r.BG,w=3)
d.text((r.W//2,sy+20),'SECOND STAGE STATUS',font=r.font(18,True),fill=r.ACCENT,anchor='ma')
headline='AT SECOND STAGE FOR 4 MONTHS'
d.text((r.W//2,sy+55),headline,font=r.font(27,True),fill=r.TEXT,anchor='ma')
status=[
    'Reached Second Stage: 10 June 2026',
    'Last activity: The Bill was discussed in the Dáil on 10 June 2026.',
    'It has remained at Second Stage since that discussion.',
]
y=sy+90
sf=r.font(19)
for line in status:
    for sub in r.wrap_text_px(d,line,sf,850):
        d.text((r.W//2,y),sub,font=sf,fill=r.TEXT,anchor='ma')
        bb=d.textbbox((r.W//2,y),sub,font=sf,anchor='ma')
        y=bb[3]+4
    y+=2

# Prominent sponsor box: person first, office title second.
s_top=1056
s_bottom=1206
r.panel(d,(58,s_top,1022,s_bottom),outline=r.OUTLINE,fill=r.PANEL,w=2)
d.text((86,s_top+20),'BROUGHT BY',font=r.font(17,True),fill=r.ACCENT,anchor='la')
name_font=r.fit(d,MINISTER_NAME,760,38,28,21,1,True)
d.text((86,s_top+55),MINISTER_NAME,font=name_font,fill=r.TEXT,anchor='la')
role_font=r.fit(d,MINISTER_ROLE,760,34,20,15,2,False)
r.draw_block(d,MINISTER_ROLE,(86,s_top+88,880,s_top+126),role_font,fill=r.MUTED,center=False)
d.text((994,s_bottom-25),'Government Bill',font=r.font(16,True),fill=r.MUTED,anchor='ra')

# Footer: exactly one centred gold rule.
footer_y=1253
d.rectangle((190,footer_y,890,footer_y+4),fill=r.ACCENT)
d.text((64,1278),f"Source: Houses of the Oireachtas · {row.get('bill_id','')}",font=r.font(12),fill=r.MUTED,anchor='la')
d.text((1016,1278),'Second Stage · Sponsor layout mock',font=r.font(12,True),fill=r.MUTED,anchor='ra')

im.save(OUT/'broadcasting-sponsor-mock.png')
print(OUT/'broadcasting-sponsor-mock.png')
