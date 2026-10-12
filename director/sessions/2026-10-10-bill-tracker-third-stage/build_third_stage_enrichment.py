from __future__ import annotations

import csv
import json
import re
import sys
from collections import defaultdict
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any, Mapping

REPO_ROOT = Path(__file__).resolve().parents[3]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

import pandas as pd

from extract.oireachtas.client import OireachtasClient
from instagram.factory.oireachtas_source import load_csv_tables, resolve_validated_production_batch

SESSION = Path("director/sessions/2026-10-10-bill-tracker-third-stage")
OUT = SESSION / "third_stage_enrichment.json"


def text(v: Any) -> str:
    if v is None or (isinstance(v, float) and pd.isna(v)):
        return ""
    return str(v).strip()


def first_text(m: Mapping[str, Any], *keys: str) -> str:
    for key in keys:
        v = m.get(key)
        if v is not None and not isinstance(v, (dict, list)) and text(v):
            return text(v)
    return ""


def deep_first(value: Any, *keys: str) -> str:
    if isinstance(value, Mapping):
        direct = first_text(value, *keys)
        if direct:
            return direct
        for child in value.values():
            found = deep_first(child, *keys)
            if found:
                return found
    elif isinstance(value, list):
        for child in value:
            found = deep_first(child, *keys)
            if found:
                return found
    return ""


def bill_key(no: Any, year: Any) -> str:
    return f"{text(year)}/{text(no)}"


def latest(frame: pd.DataFrame) -> pd.DataFrame:
    if frame.empty:
        return frame
    if "snapshot_date" in frame.columns and "bill_id" in frame.columns:
        return frame.sort_values(["bill_id", "snapshot_date"]).drop_duplicates("bill_id", keep="last")
    return frame


def maybe_load(batch, name: str) -> pd.DataFrame:
    try:
        frames, _ = load_csv_tables(batch, [name])
        return frames[name]
    except Exception:
        return pd.DataFrame()


def clean_spaces(s: str) -> str:
    return re.sub(r"\s+", " ", s).strip()


def simplify_long_title(short_title: str, long_title: str) -> list[str]:
    if not long_title:
        return [fallback_about(short_title)]
    s = clean_spaces(long_title)
    s = re.sub(r"^An Act\s+", "", s, flags=re.I)
    parts = [p.strip(" .") for p in re.split(r";|\band to\b", s, flags=re.I) if p.strip(" .")]
    out: list[str] = []
    for raw in parts:
        p = raw
        if re.search(r"related matters?$", p, flags=re.I):
            continue
        p = re.sub(r"^to\s+", "", p, flags=re.I)
        p = re.sub(r"^provide for\s+", "sets rules for ", p, flags=re.I)
        p = re.sub(r"^make provision for\s+", "sets rules for ", p, flags=re.I)
        p = re.sub(r"^amend\s+", "changes ", p, flags=re.I)
        p = re.sub(r"^give effect to\s+", "implements ", p, flags=re.I)
        p = re.sub(r"^transpose\s+", "brings Irish law into line with ", p, flags=re.I)
        p = re.sub(r"^establish\s+", "creates ", p, flags=re.I)
        p = clean_spaces(p)
        if not p:
            continue
        p = p[0].upper() + p[1:]
        if len(p) > 180:
            p = p[:177].rsplit(" ", 1)[0] + "…"
        if not p.endswith((".", "?", "!", "…")):
            p += "."
        if p not in out:
            out.append(p)
        if len(out) == 3:
            break
    return out or [fallback_about(short_title)]


def fallback_about(title: str) -> str:
    subject = re.sub(r"\s+Bill\s+\d{4}$", "", title).strip()
    subject = re.sub(r"\s*\(Amendment(?:\s*\([^)]*\))?\)\s*", " ", subject, flags=re.I)
    subject = clean_spaces(subject)
    if "amendment" in title.casefold():
        return f"Changes existing law dealing with {subject.lower()}."
    return f"Deals with {subject.lower()}."


def live_bill_map() -> dict[str, Mapping[str, Any]]:
    client = OireachtasClient(timeout_seconds=40, retries=4, sleep_seconds=0.05)
    summary = client.get_json_summary(
        "/legislation",
        params={"bill_status": "Current", "date_start": "1900-01-01", "date_end": date.today().isoformat(), "limit": 200, "lang": "en"},
    )
    if not summary.ok or not summary.payload:
        raise RuntimeError(f"Official legislation query failed: {summary.error or summary.status_code}")
    out: dict[str, Mapping[str, Any]] = {}
    for item in summary.payload.get("results") or []:
        if not isinstance(item, Mapping):
            continue
        bill = item.get("bill") if isinstance(item.get("bill"), Mapping) else item
        key = bill_key(first_text(bill, "billNo", "billNumber"), first_text(bill, "billYear", "year"))
        out[key] = bill
    return out


def collection_rows(bill: Mapping[str, Any], key: str) -> list[Mapping[str, Any]]:
    raw = bill.get(key)
    if not isinstance(raw, list):
        return []
    rows = []
    for x in raw:
        if not isinstance(x, Mapping):
            continue
        inner = x.get(key[:-1]) if key.endswith("s") and isinstance(x.get(key[:-1]), Mapping) else x
        rows.append(inner if isinstance(inner, Mapping) else x)
    return rows


def live_debates(bill: Mapping[str, Any]) -> list[dict[str, str]]:
    rows = []
    for d in collection_rows(bill, "debates"):
        rows.append({
            "date": first_text(d, "date"),
            "label": first_text(d, "showAs", "title", "label"),
            "uri": first_text(d, "uri", "debateUri"),
            "section": first_text(d, "debateSectionId", "sectionId"),
            "chamber": deep_first(d.get("chamber"), "showAs", "name"),
        })
    return rows


def live_versions(bill: Mapping[str, Any]) -> list[dict[str, str]]:
    rows = []
    for v in collection_rows(bill, "versions"):
        rows.append({"date": first_text(v, "date"), "label": first_text(v, "showAs", "title", "label"), "uri": first_text(v, "uri", "versionUri")})
    return rows


def live_related_docs(bill: Mapping[str, Any]) -> list[dict[str, str]]:
    raw = bill.get("relatedDocs") if isinstance(bill.get("relatedDocs"), list) else bill.get("relatedDocuments")
    if not isinstance(raw, list):
        return []
    rows=[]
    for x in raw:
        if not isinstance(x, Mapping): continue
        d=x.get("relatedDoc") if isinstance(x.get("relatedDoc"), Mapping) else x
        rows.append({"date": first_text(d,"date"), "label": first_text(d,"showAs","title","label"), "uri": first_text(d,"uri")})
    return rows


def status_examples(speeches: pd.DataFrame) -> list[dict[str, str]]:
    if speeches.empty or "speech_text" not in speeches.columns:
        return []
    patterns = [
        ("ACCEPTED", re.compile(r"amendment(?: no\. ?\d+)?[^.]{0,100}(?:agreed to|carried)", re.I)),
        ("REJECTED", re.compile(r"amendment(?: no\. ?\d+)?[^.]{0,100}(?:negatived|lost|rejected)", re.I)),
        ("WITHDRAWN", re.compile(r"amendment(?: no\. ?\d+)?[^.]{0,120}withdrawn", re.I)),
        ("COULD NOT PROCEED", re.compile(r"amendment(?: no\. ?\d+)?[^.]{0,140}(?:out of order|not in order)", re.I)),
    ]
    found: list[dict[str,str]]=[]
    seen=set()
    for raw in speeches["speech_text"].fillna("").astype(str):
        clean=clean_spaces(raw)
        for status, rx in patterns:
            m=rx.search(clean)
            if not m: continue
            snippet=clean[max(0,m.start()-70):min(len(clean),m.end()+90)].strip()
            snippet=re.sub(r"^\S*\s*", "", snippet) if len(snippet)>210 else snippet
            snippet=snippet[:240]
            k=(status,snippet.casefold())
            if k in seen: continue
            seen.add(k); found.append({"status":status,"source_snippet":snippet})
            if len(found)>=4: return found
    return found


def compact_divisions(divs: pd.DataFrame, tallies: pd.DataFrame) -> list[dict[str, Any]]:
    if divs.empty:
        return []
    out=[]
    for _, r in divs.head(3).iterrows():
        did=text(r.get("division_id"))
        tally_rows=tallies[tallies.get("division_id", pd.Series(index=tallies.index,dtype=str)).astype(str).eq(did)] if not tallies.empty and "division_id" in tallies.columns else pd.DataFrame()
        tally_text=[]
        for _, tr in tally_rows.iterrows():
            label=text(tr.get("tally_type") or tr.get("vote_option") or tr.get("label"))
            count=text(tr.get("count") or tr.get("tally_count") or tr.get("value"))
            if label and count: tally_text.append(f"{label} {count}")
        out.append({
            "date": text(r.get("division_date")),
            "subject": text(r.get("subject")),
            "outcome": text(r.get("outcome")),
            "tally": ", ".join(tally_text[:4]),
        })
    return out


def main() -> None:
    batch=resolve_validated_production_batch()
    tables={name:maybe_load(batch,name) for name in ["silver_bills","silver_bill_debates","silver_bill_versions","silver_bill_related_docs","silver_divisions","silver_division_tallies","silver_speeches"]}
    bills=latest(tables["silver_bills"])
    bill_id_by_key={bill_key(r.get("bill_no"),r.get("bill_year")):text(r.get("bill_id")) for _,r in bills.iterrows()}
    live=live_bill_map()

    inv={}
    with (SESSION/"live_third_stage_inventory.csv").open("r",encoding="utf-8",newline="") as fh:
        for row in csv.DictReader(fh): inv[row["key"]]=row

    out={"verified_at_utc":datetime.now(timezone.utc).isoformat(),"source_batch_id":batch.batch_id,"bills":{}}
    for key,row in inv.items():
        lb=live.get(key,{})
        bid=bill_id_by_key.get(key,"")
        title=row.get("title") or first_text(lb,"shortTitleEn","showAs","title")
        long_title=first_text(lb,"longTitleEn")
        debates=live_debates(lb)
        versions=live_versions(lb)
        docs=live_related_docs(lb)

        prod_deb=tables["silver_bill_debates"]
        bdeb=prod_deb[prod_deb["bill_id"].astype(str).eq(bid)] if bid and not prod_deb.empty and "bill_id" in prod_deb.columns else pd.DataFrame()
        debate_ids=set(bdeb["debate_id"].dropna().astype(str)) if not bdeb.empty and "debate_id" in bdeb.columns else set()
        debate_sections=set(bdeb["debate_section_id"].dropna().astype(str)) if not bdeb.empty and "debate_section_id" in bdeb.columns else set()

        divs=tables["silver_divisions"]
        if not divs.empty and debate_ids:
            mask=divs["debate_id"].fillna("").astype(str).isin(debate_ids) if "debate_id" in divs.columns else pd.Series(False,index=divs.index)
            if "debate_section_id" in divs.columns and debate_sections:
                mask |= divs["debate_section_id"].fillna("").astype(str).isin(debate_sections)
            bdiv=divs[mask]
        else: bdiv=pd.DataFrame()

        speeches=tables["silver_speeches"]
        if not speeches.empty and debate_ids and "debate_id" in speeches.columns:
            bsp=speeches[speeches["debate_id"].fillna("").astype(str).isin(debate_ids)]
        else: bsp=pd.DataFrame()

        amended_versions=[v for v in versions if "amend" in v["label"].casefold()]
        amendment_docs=[d for d in docs if "amend" in d["label"].casefold()]
        committee_debates=[d for d in debates if "committee stage" in d["label"].casefold() or "third stage" in d["label"].casefold()]
        if not committee_debates and debates:
            stage_date=row.get("live_stage_date") or ""
            committee_debates=[d for d in debates if d.get("date")==stage_date]

        examples=status_examples(bsp)
        divisions=compact_divisions(bdiv,tables["silver_division_tallies"])
        complex_evidence=bool(amended_versions or amendment_docs or divisions or examples)

        stage_points=[]
        if committee_debates:
            dates=sorted({d["date"] for d in committee_debates if d["date"]})
            if dates: stage_points.append(f"The detailed review is recorded on {', '.join(dates[:2])}.")
            else: stage_points.append("The official record includes a detailed Third Stage debate.")
        else:
            stage_points.append(f"The official record lists the Bill at Third Stage from {row.get('live_stage_date') or 'its latest recorded date'}.")
        if amendment_docs:
            stage_points.append("An official list of proposed wording changes is published for this Bill.")
        if amended_versions:
            stage_points.append("An updated version of the Bill was published after changes were made.")
        if divisions:
            stage_points.append(f"The record includes {len(divisions)} linked recorded vote{'s' if len(divisions)!=1 else ''}.")
        if len(stage_points)<2:
            stage_points.append("The next useful update is whether proposed wording changes are accepted or rejected.")

        result="Detailed review is still the current stage."
        if amended_versions:
            result="The Bill has an updated version containing changes made during its detailed review."
        elif examples:
            cats=[]
            for ex in examples:
                if ex["status"] not in cats: cats.append(ex["status"])
            result="The official debate record shows proposed changes were " + ", ".join(c.lower() for c in cats[:3]) + "."
        elif committee_debates:
            result="The detailed review has a published debate record, but no updated amended version was identified in this source snapshot."

        out["bills"][key]={
            "key":key,"title":title,"bill_no":row.get("bill_no"),"bill_year":row.get("bill_year"),"stage_date":row.get("live_stage_date"),"complexity":row.get("complexity"),
            "about_points":simplify_long_title(title,long_title),
            "stage_points":stage_points[:4],
            "result":result,
            "committee_debates":committee_debates[:5],
            "amendment_documents":amendment_docs[:5],
            "amended_versions":amended_versions[:5],
            "change_outcomes":examples,
            "divisions":divisions,
            "extra_slide":complex_evidence,
            "source_note":"Official Oireachtas legislation record plus validated production debate/division tables.",
        }

    # Preserve the separately verified Broadcasting example where production omitted live Committee Stage details.
    b=out["bills"].get("2026/54")
    if b:
        b["stage_points"]=["TDs went through the Bill section by section on 22 September.","Proposed changes were accepted, withdrawn, rejected and ruled out.","The Bill moved forward with changed wording."]
        b["result"]="The Bill moved forward with changes made during Third Stage."
        b["change_outcomes"]=[
            {"status":"ACCEPTED","plain":"A Government proposal changing levy rules in section 13 was accepted."},
            {"status":"WITHDRAWN","plain":"A proposal about support for local music was discussed and then withdrawn."},
            {"status":"COULD NOT PROCEED","plain":"One proposed change could not be considered because it would create a new cost for the State."},
        ]
        b["divisions"]=[{"date":"2026-09-22","subject":"One proposed change","outcome":"Lost","tally":"4 Tá, 5 Níl","plain":"The committee voted 5 to 4 against one proposed change. This was not a vote on the Bill as a whole."}]
        b["extra_slide"]=True

    OUT.write_text(json.dumps(out,indent=2,ensure_ascii=False,default=str),encoding="utf-8")
    print(json.dumps({"bills":len(out["bills"]),"extra_slides":sum(1 for x in out["bills"].values() if x["extra_slide"]),"batch":batch.batch_id},indent=2))


if __name__=="__main__":
    main()
