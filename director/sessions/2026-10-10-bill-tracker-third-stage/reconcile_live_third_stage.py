from __future__ import annotations

import csv
import json
from collections import defaultdict
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any, Mapping

import pandas as pd

from extract.oireachtas.client import OireachtasClient
from instagram.factory.oireachtas_source import load_csv_tables, resolve_validated_production_batch

SESSION = Path("director/sessions/2026-10-10-bill-tracker-third-stage")
SESSION.mkdir(parents=True, exist_ok=True)


def text(v: Any) -> str:
    return "" if v is None else str(v).strip()


def deep_text(value: Any) -> str:
    if isinstance(value, Mapping):
        return " ".join(deep_text(v) for v in value.values())
    if isinstance(value, list):
        return " ".join(deep_text(v) for v in value)
    return text(value)


def first_scalar(value: Any, keys: tuple[str, ...]) -> str:
    if isinstance(value, Mapping):
        for key in keys:
            raw = value.get(key)
            if raw is not None and not isinstance(raw, (dict, list)) and text(raw):
                return text(raw)
        for child in value.values():
            found = first_scalar(child, keys)
            if found:
                return found
    elif isinstance(value, list):
        for child in value:
            found = first_scalar(child, keys)
            if found:
                return found
    return ""


def collect_dates(value: Any) -> list[str]:
    out: set[str] = set()
    if isinstance(value, Mapping):
        for key, child in value.items():
            kl = str(key).lower()
            if ("date" in kl or kl in {"created", "updated"}) and not isinstance(child, (dict, list)):
                s = text(child)
                if len(s) >= 10 and s[:4].isdigit() and s[4] == "-":
                    out.add(s[:10])
            out.update(collect_dates(child))
    elif isinstance(value, list):
        for child in value:
            out.update(collect_dates(child))
    return sorted(out)


def unwrap_bill(item: Mapping[str, Any]) -> Mapping[str, Any]:
    bill = item.get("bill")
    return bill if isinstance(bill, Mapping) else item


def bill_key(no: Any, year: Any) -> str:
    return f"{text(year)}/{text(no)}"


def latest_bill_rows(frame: pd.DataFrame) -> pd.DataFrame:
    if frame.empty:
        return frame
    out = frame.copy()
    if "snapshot_date" in out.columns:
        out = out.sort_values(["bill_id", "snapshot_date"]).drop_duplicates("bill_id", keep="last")
    else:
        out = out.drop_duplicates("bill_id", keep="last")
    return out


def maybe_load(batch, name: str) -> pd.DataFrame:
    try:
        frames, _ = load_csv_tables(batch, [name])
        return frames[name]
    except Exception:
        return pd.DataFrame()


def contains_stage_phrase(value: Any) -> bool:
    s = deep_text(value).casefold()
    return "committee stage" in s or "third stage" in s


def normalize_live(item: Mapping[str, Any]) -> dict[str, Any]:
    bill = unwrap_bill(item)
    most = bill.get("mostRecentStage") if isinstance(bill.get("mostRecentStage"), (Mapping, list)) else {}
    most_text = deep_text(most)
    status = first_scalar(bill, ("status",))
    no = first_scalar(bill, ("billNo", "billNumber"))
    year = first_scalar(bill, ("billYear", "year"))
    title = first_scalar(bill, ("shortTitleEn", "longTitleEn", "showAs", "title"))
    source = first_scalar(bill, ("source", "billSource", "method"))
    uri = first_scalar(bill, ("uri", "billUri", "billId", "id"))
    stage_name = first_scalar(most, ("showAs", "stageName", "stage", "name"))
    stage_outcome = first_scalar(most, ("stageOutcome", "outcome", "status"))
    house = first_scalar(most, ("houseName", "chamberName"))
    if not house:
        # Common Oireachtas shape nests the House under event/house.showAs.
        house = first_scalar(most, ("showAs",)) if "dáil" in most_text.casefold() or "seanad" in most_text.casefold() else ""
    dates = collect_dates(most)
    return {
        "key": bill_key(no, year),
        "bill_no": no,
        "bill_year": year,
        "title": title,
        "bill_uri": uri,
        "bill_source": source,
        "live_status": status,
        "live_stage_name": stage_name,
        "live_stage_outcome": stage_outcome,
        "live_stage_house": house,
        "live_stage_date": max(dates) if dates else "",
        "live_third_stage": contains_stage_phrase(most),
        "most_recent_stage_text": most_text[:1400],
        "most_recent_stage_raw": most,
    }


def production_metrics(batch) -> tuple[dict[str, dict[str, Any]], dict[str, Any]]:
    bills = latest_bill_rows(maybe_load(batch, "silver_bills"))
    stages = maybe_load(batch, "silver_bill_stages")
    bill_debates = maybe_load(batch, "silver_bill_debates")
    divisions = maybe_load(batch, "silver_divisions")
    related = maybe_load(batch, "silver_bill_related_docs")
    versions = maybe_load(batch, "silver_bill_versions")

    by_bill_id: dict[str, dict[str, Any]] = {}
    key_to_id: dict[str, str] = {}
    if not bills.empty:
        for _, r in bills.iterrows():
            k = bill_key(r.get("bill_no"), r.get("bill_year"))
            bid = text(r.get("bill_id"))
            key_to_id[k] = bid
            by_bill_id[bid] = {
                "production_bill_id": bid,
                "production_title": text(r.get("title") or r.get("short_title")),
                "production_status": text(r.get("status")),
                "production_last_event_date": text(r.get("last_event_date")),
            }

    current_committee_ids: set[str] = set()
    if not stages.empty:
        s = stages.copy()
        mask = s.get("stage_name", pd.Series(index=s.index, dtype=str)).fillna("").astype(str).str.strip().eq("Committee Stage")
        if "stage_outcome" in s.columns:
            mask &= s["stage_outcome"].fillna("").astype(str).str.strip().str.casefold().eq("current")
        current_committee_ids = set(s.loc[mask, "bill_id"].astype(str)) if "bill_id" in s.columns else set()

    # Pre-index debate rows and division linkage.
    debate_rows_by_bill: dict[str, pd.DataFrame] = {}
    pairs_by_bill: dict[str, set[tuple[str, str]]] = defaultdict(set)
    if not bill_debates.empty and "bill_id" in bill_debates.columns:
        for bid, grp in bill_debates.groupby(bill_debates["bill_id"].astype(str)):
            debate_rows_by_bill[bid] = grp
            for _, r in grp.iterrows():
                pairs_by_bill[bid].add((text(r.get("debate_id")), text(r.get("debate_section_id"))))

    div_count_by_bill: dict[str, int] = defaultdict(int)
    if not divisions.empty and "debate_id" in divisions.columns:
        for bid, pairs in pairs_by_bill.items():
            if not pairs:
                continue
            def linked(r):
                p = (text(r.get("debate_id")), text(r.get("debate_section_id")))
                if p in pairs:
                    return True
                return any(p[0] and p[0] == x[0] for x in pairs)
            div_count_by_bill[bid] = int(divisions.apply(linked, axis=1).sum())

    def docs_metric(frame: pd.DataFrame, bid: str, needle: str) -> int:
        if frame.empty or "bill_id" not in frame.columns:
            return 0
        grp = frame[frame["bill_id"].astype(str).eq(bid)]
        if grp.empty:
            return 0
        return int(grp.apply(lambda r: needle in " ".join(text(x).casefold() for x in r.values), axis=1).sum())

    metrics_by_key: dict[str, dict[str, Any]] = {}
    for k, bid in key_to_id.items():
        grp = debate_rows_by_bill.get(bid, pd.DataFrame())
        committee_debates = 0
        if not grp.empty:
            committee_debates = int(grp.apply(lambda r: contains_stage_phrase({c: r.get(c) for c in grp.columns}), axis=1).sum())
        metrics_by_key[k] = {
            **by_bill_id.get(bid, {}),
            "production_current_committee": bid in current_committee_ids,
            "production_bill_debate_rows": int(len(grp)),
            "production_committee_debate_rows": committee_debates,
            "production_linked_division_rows": int(div_count_by_bill.get(bid, 0)),
            "production_amendment_doc_rows": docs_metric(related, bid, "amend"),
            "production_amended_version_rows": docs_metric(versions, bid, "amend"),
        }

    meta = {
        "table_rows": {
            "silver_bills": int(len(bills)),
            "silver_bill_stages": int(len(stages)),
            "silver_bill_debates": int(len(bill_debates)),
            "silver_divisions": int(len(divisions)),
            "silver_bill_related_docs": int(len(related)),
            "silver_bill_versions": int(len(versions)),
        },
        "production_current_committee_count": len(current_committee_ids),
    }
    return metrics_by_key, meta


def classify(row: Mapping[str, Any]) -> str:
    divs = int(row.get("production_linked_division_rows") or 0)
    amendment_docs = int(row.get("production_amendment_doc_rows") or 0)
    amended_versions = int(row.get("production_amended_version_rows") or 0)
    committee_debates = int(row.get("production_committee_debate_rows") or 0)
    all_debates = int(row.get("production_bill_debate_rows") or 0)
    if divs > 0 or amendment_docs >= 2 or amended_versions >= 1 or committee_debates >= 2:
        return "complex"
    if amendment_docs == 1 or committee_debates == 1 or all_debates >= 2:
        return "substantive"
    return "light"


def make_groups(rows: list[dict[str, Any]], size: int = 4) -> list[dict[str, Any]]:
    # Keep the overall order recent-first, but spread complex Bills so one post is not overloaded.
    ranked = sorted(rows, key=lambda r: (r.get("live_stage_date") or "0000-00-00", r.get("bill_year") or "", int(r.get("bill_no") or 0)), reverse=True)
    total_groups = (len(ranked) + size - 1) // size
    buckets: list[list[dict[str, Any]]] = [[] for _ in range(total_groups)]
    complex_rows = [r for r in ranked if r["complexity"] == "complex"]
    other_rows = [r for r in ranked if r["complexity"] != "complex"]
    for i, row in enumerate(complex_rows):
        buckets[i % total_groups].append(row)
    cursor = 0
    for row in other_rows:
        checked = 0
        while checked < total_groups and len(buckets[cursor % total_groups]) >= size:
            cursor += 1; checked += 1
        if checked >= total_groups:
            break
        buckets[cursor % total_groups].append(row)
        cursor += 1
    groups = []
    for idx, bucket in enumerate(buckets, start=1):
        bucket.sort(key=lambda r: (r.get("live_stage_date") or "0000-00-00", r.get("bill_year") or "", int(r.get("bill_no") or 0)), reverse=True)
        groups.append({
            "post": idx,
            "bill_count": len(bucket),
            "expected_bill_slides_min": len(bucket),
            "complex_bill_count": sum(1 for r in bucket if r["complexity"] == "complex"),
            "bills": [{k: r.get(k) for k in ("key", "title", "live_stage_date", "live_stage_house", "complexity")} for r in bucket],
        })
    return groups


def main() -> None:
    verified_at = datetime.now(timezone.utc).isoformat()
    batch = resolve_validated_production_batch()
    prod, prod_meta = production_metrics(batch)

    client = OireachtasClient(timeout_seconds=40, retries=4, sleep_seconds=0.05)
    live_summary = client.get_json_summary(
        "/legislation",
        params={"bill_status": "Current", "date_start": "1900-01-01", "date_end": date.today().isoformat(), "limit": 200, "lang": "en"},
    )
    if not live_summary.ok or not live_summary.payload:
        raise RuntimeError(f"Live Oireachtas legislation query failed: {live_summary.error or live_summary.status_code}")
    results = live_summary.payload.get("results") or []
    live_all = [normalize_live(item) for item in results if isinstance(item, Mapping)]
    live_third = [r for r in live_all if r["live_third_stage"] and r["live_status"].casefold() == "current"]

    rows: list[dict[str, Any]] = []
    for live in live_third:
        merged = {**live, **prod.get(live["key"], {})}
        merged["production_present"] = live["key"] in prod
        merged["production_live_discrepancy"] = not bool(merged.get("production_current_committee"))
        merged["complexity"] = classify(merged)
        rows.append(merged)

    live_keys = {r["key"] for r in rows}
    production_current_keys = {k for k, v in prod.items() if v.get("production_current_committee")}
    prod_only = sorted(production_current_keys - live_keys)
    live_only = sorted(live_keys - production_current_keys)

    # Force known high-complexity Broadcasting treatment if live and production metrics are stale.
    for r in rows:
        if r["key"] == "2026/54":
            r["complexity"] = "complex"
            r["complexity_note"] = "Live Committee Stage record already verified separately: amended Bill plus amendment division."

    groups = make_groups(rows, 4)
    counts = defaultdict(int)
    for r in rows:
        counts[r["complexity"]] += 1

    payload = {
        "verified_at_utc": verified_at,
        "official_source": "https://api.oireachtas.ie/v1/legislation",
        "source_batch_id": batch.batch_id,
        "source_pointer": batch.pointer,
        "live_api_pagination": live_summary.pagination,
        "live_current_bill_count": len(live_all),
        "live_third_stage_count": len(rows),
        "production_current_committee_count": prod_meta["production_current_committee_count"],
        "production_only_current_committee_keys": prod_only,
        "live_only_third_stage_keys": live_only,
        "complexity_counts": dict(counts),
        "recommended_bills_per_post": 4,
        "recommended_post_count": len(groups),
        "production_table_rows": prod_meta["table_rows"],
        "live_inventory": sorted(rows, key=lambda r: (r.get("live_stage_date") or "", r.get("bill_year") or "", int(r.get("bill_no") or 0)), reverse=True),
        "groups": groups,
        "sample_raw_most_recent_stage": {r["key"]: r["most_recent_stage_raw"] for r in rows[:3]},
    }

    json_path = SESSION / "live_third_stage_reconciliation.json"
    json_path.write_text(json.dumps(payload, indent=2, ensure_ascii=False, default=str), encoding="utf-8")

    csv_path = SESSION / "live_third_stage_inventory.csv"
    fields = [
        "key", "bill_no", "bill_year", "title", "live_status", "live_stage_name", "live_stage_outcome", "live_stage_house", "live_stage_date",
        "complexity", "production_present", "production_current_committee", "production_bill_debate_rows", "production_committee_debate_rows",
        "production_linked_division_rows", "production_amendment_doc_rows", "production_amended_version_rows", "production_live_discrepancy",
    ]
    with csv_path.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=fields)
        writer.writeheader()
        for r in payload["live_inventory"]:
            writer.writerow({k: r.get(k, "") for k in fields})

    lines = [
        "# Live Third Stage reconciliation",
        "",
        f"- Verified: {verified_at}",
        f"- Validated production batch: `{batch.batch_id}`",
        f"- Live Current Bills returned by official API: **{len(live_all)}**",
        f"- Live Bills whose most recent stage is Third/Committee Stage: **{len(rows)}**",
        f"- Production Current Committee Stage rows: **{prod_meta['production_current_committee_count']}**",
        f"- Live Third Stage Bills absent from production Current Committee inventory: **{len(live_only)}**",
        f"- Production Current Committee Bills no longer live Third Stage: **{len(prod_only)}**",
        f"- Complexity: complex {counts['complex']}, substantive {counts['substantive']}, light {counts['light']}",
        f"- Recommended grouping: **{len(groups)} posts**, normally 4 Bills per post.",
        "",
        "## Live-only Third Stage keys",
        "",
        ", ".join(live_only) if live_only else "None",
        "",
        "## Production-only Third Stage keys",
        "",
        ", ".join(prod_only) if prod_only else "None",
        "",
        "## Proposed posts",
        "",
    ]
    for g in groups:
        bills_text = "; ".join(f"{b['title']} ({b['key']}, {b['complexity']})" for b in g["bills"])
        lines.append(f"- **Post {g['post']}** ({g['bill_count']} Bills): {bills_text}")
    (SESSION / "live_third_stage_reconciliation.md").write_text("\n".join(lines) + "\n", encoding="utf-8")

    print(json.dumps({
        "batch": batch.batch_id,
        "live_current": len(live_all),
        "live_third_stage": len(rows),
        "production_current_committee": prod_meta["production_current_committee_count"],
        "live_only": len(live_only),
        "production_only": len(prod_only),
        "complexity": dict(counts),
        "posts": len(groups),
    }, indent=2))


if __name__ == "__main__":
    main()
