#!/usr/bin/env python3
"""Apply the Ceann Comhairle denominator rule to Director voting evidence.

The base audit removes whichever member is identified as physically presiding for
an individual division. For this Director review period, Verona Murphy is the
validated Ceann Comhairle office-holder. This correction removes her from ordinary
eligible opportunities across the resolved period unless an actual recorded vote
exists (casting-vote case).

It rewrites only Director review evidence. Production source data remains read-only.
"""
from __future__ import annotations

import json
import os
from pathlib import Path

import boto3
import pandas as pd

from political_metrics.calculators.votes import (
    constituency_vote_participation,
    eligible_division_pairs,
    member_vote_participation,
    party_vote_metrics,
)
from process.director_recorded_voting_participation_audit import (
    BUCKET,
    TABLE_KEYS,
    _clean,
    _named,
    _read_batch_csv,
)

OUT_DIR = Path(os.getenv("DIRECTOR_VOTE_AUDIT_DIR", "artifacts/director-recorded-voting-participation"))
CEANN_COMHAIRLE_MEMBER_CODE = "Verona-Murphy.D.2020-02-08"
CEANN_COMHAIRLE_NAME = "Verona Murphy"


def main() -> int:
    report_path = OUT_DIR / "report.json"
    report = json.loads(report_path.read_text(encoding="utf-8"))
    batch_id = str(report["production_batch_id"])
    period_start = pd.Timestamp(report["resolved_period"]["start"])
    period_end = pd.Timestamp(report["resolved_period"]["end"])
    excluded_division_ids = set(report["division_counts"].get("excluded_division_ids", []))

    # Require the base audit itself to have identified the expected office-holder.
    office_rows = report.get("presiding_member", {}).get("identified_ceann_comhairle_office_rows", [])
    matching_office_rows = [
        row for row in office_rows
        if str(row.get("member_code") or "") == CEANN_COMHAIRLE_MEMBER_CODE
        and str(row.get("office_name") or "").strip().casefold() == "ceann comhairle"
    ]
    if not matching_office_rows:
        raise RuntimeError(
            f"Base audit did not identify {CEANN_COMHAIRLE_NAME} ({CEANN_COMHAIRLE_MEMBER_CODE}) as Ceann Comhairle"
        )

    s3 = boto3.client("s3", region_name=os.getenv("AWS_REGION", os.getenv("AWS_DEFAULT_REGION", "ca-central-1")))
    frames = {}
    for name in [
        "silver_divisions",
        "silver_member_votes",
        "silver_member_memberships",
        "silver_member_parties",
        "silver_member_constituencies",
        "silver_members",
    ]:
        frames[name], _ = _read_batch_csv(s3, batch_id=batch_id, logical_key=TABLE_KEYS[name])
        frames[name] = _clean(frames[name])

    divisions = frames["silver_divisions"].copy()
    divisions = divisions[divisions["chamber"].str.lower().eq("dail")].copy()
    divisions["division_date_dt"] = pd.to_datetime(divisions["division_date"], errors="coerce").dt.normalize()
    divisions = divisions[
        divisions["division_date_dt"].between(period_start, period_end, inclusive="both")
        & ~divisions["division_id"].isin(excluded_division_ids)
    ].copy()
    division_ids = set(divisions["division_id"])

    memberships = frames["silver_member_memberships"]
    memberships = memberships[memberships["chamber"].str.lower().eq("dail")].copy()
    votes = frames["silver_member_votes"]
    votes = votes[votes["division_id"].isin(division_ids)].copy()
    votes["division_date"] = pd.to_datetime(votes["division_date"], errors="coerce").dt.normalize()

    eligible = eligible_division_pairs(memberships, divisions[["division_id", "division_date"]])
    eligible["division_date"] = pd.to_datetime(eligible["division_date"], errors="coerce").dt.normalize()

    # Reapply the existing per-division presiding-member exclusion.
    presiding = pd.read_csv(OUT_DIR / "presiding_member_evidence.csv", dtype=str, keep_default_na=False)
    eligible = eligible.merge(
        presiding[["division_id", "presiding_member_code"]],
        on="division_id",
        how="left",
        validate="many_to_one",
    )
    vote_pairs = set(zip(votes["division_id"], votes["member_code"]))
    eligible["has_recorded_vote"] = [
        (division_id, member_code) in vote_pairs
        for division_id, member_code in zip(eligible["division_id"], eligible["member_code"])
    ]
    eligible["is_presiding_member"] = eligible["member_code"].eq(eligible["presiding_member_code"])
    eligible = eligible[~(eligible["is_presiding_member"] & ~eligible["has_recorded_vote"])].copy()

    # During this resolved review period, exclude the Ceann Comhairle from ordinary
    # division opportunities even when another member physically presided.
    eligible["is_ceann_comhairle"] = eligible["member_code"].eq(CEANN_COMHAIRLE_MEMBER_CODE)
    excluded_ceann = eligible[eligible["is_ceann_comhairle"] & ~eligible["has_recorded_vote"]].copy()
    eligible = eligible[~(eligible["is_ceann_comhairle"] & ~eligible["has_recorded_vote"])].copy()

    remaining_ordinary = eligible[eligible["is_ceann_comhairle"] & ~eligible["has_recorded_vote"]]
    if not remaining_ordinary.empty:
        raise RuntimeError("Ceann Comhairle ordinary opportunities remain after correction")

    member_parties = frames["silver_member_parties"]
    member_constituencies = frames["silver_member_constituencies"]
    members = frames["silver_members"]

    td = member_vote_participation(votes, eligible)
    td = td.rename(columns={
        "eligible_division_count": "eligible_division_opportunities",
        "votes_cast_count": "recorded_participation_opportunities",
    })
    td = _named(td, members)
    td["recorded_participation_pct"] = (td["vote_participation_pct"].astype(float) * 100).round(1)
    td = td[[
        "member_name", "member_code", "recorded_participation_opportunities",
        "eligible_division_opportunities", "recorded_participation_pct",
    ]]
    # Safeguard: the Ceann Comhairle is N/A for this TD comparison, not a 0% row.
    td = td[td["member_code"].ne(CEANN_COMHAIRLE_MEMBER_CODE)].sort_values(["member_name", "member_code"])

    party = party_vote_metrics(votes, eligible, member_parties)
    party_names = member_parties[["party_uri", "party_name"]].dropna().drop_duplicates("party_uri", keep="last")
    party = party.merge(party_names, on="party_uri", how="left")
    party["recorded_participation_pct"] = (party["vote_participation_pct"].astype(float) * 100).round(1)
    party = party[[
        "party_name", "party_uri", "recorded_member_votes", "eligible_member_divisions", "recorded_participation_pct",
    ]].rename(columns={
        "recorded_member_votes": "recorded_participation_opportunities",
        "eligible_member_divisions": "eligible_division_opportunities",
    }).sort_values(["party_name", "party_uri"])

    constituency = constituency_vote_participation(votes, eligible, member_constituencies)
    const_names = member_constituencies[["constituency_uri", "constituency_name"]].dropna().drop_duplicates("constituency_uri", keep="last")
    constituency = constituency.merge(const_names, on="constituency_uri", how="left")
    constituency["recorded_participation_pct"] = (constituency["vote_participation_pct"].astype(float) * 100).round(1)
    constituency = constituency[[
        "constituency_name", "constituency_uri", "recorded_member_votes", "eligible_member_divisions", "recorded_participation_pct",
    ]].rename(columns={
        "recorded_member_votes": "recorded_participation_opportunities",
        "eligible_member_divisions": "eligible_division_opportunities",
    }).sort_values(["constituency_name", "constituency_uri"])

    member_num = int(td["recorded_participation_opportunities"].sum())
    member_den = int(td["eligible_division_opportunities"].sum())
    party_num = int(party["recorded_participation_opportunities"].sum())
    party_den = int(party["eligible_division_opportunities"].sum())
    const_num = int(constituency["recorded_participation_opportunities"].sum())
    const_den = int(constituency["eligible_division_opportunities"].sum())

    if not (member_num == party_num == const_num and member_den == party_den == const_den):
        raise RuntimeError("Ceann Comhairle correction broke member/party/constituency reconciliation")
    if td["member_code"].eq(CEANN_COMHAIRLE_MEMBER_CODE).any():
        raise RuntimeError("Ceann Comhairle still present in TD comparison output")

    td.to_csv(OUT_DIR / "td_participation.csv", index=False)
    party.to_csv(OUT_DIR / "party_participation.csv", index=False)
    constituency.to_csv(OUT_DIR / "constituency_participation.csv", index=False)

    report["audit_version"] = "1.1-ceann-comhairle-period-rule"
    report["presiding_member"]["rule"] = (
        "exclude the identified presiding member from an ordinary eligible opportunity unless that member has a recorded vote; "
        "for this resolved period also exclude the validated Ceann Comhairle from ordinary eligible opportunities unless an actual recorded vote exists (casting-vote case)"
    )
    report["presiding_member"]["additional_ceann_comhairle_opportunities_excluded"] = int(len(excluded_ceann))
    report["presiding_member"]["ceann_comhairle_member_code"] = CEANN_COMHAIRLE_MEMBER_CODE
    report["presiding_member"]["ceann_comhairle_member_name"] = CEANN_COMHAIRLE_NAME
    report["reconciliation"].update({
        "member_recorded_participation_opportunities": member_num,
        "member_eligible_division_opportunities": member_den,
        "party_recorded_participation_opportunities": party_num,
        "party_eligible_division_opportunities": party_den,
        "constituency_recorded_participation_opportunities": const_num,
        "constituency_eligible_division_opportunities": const_den,
    })
    report["checks"]["ceann_comhairle_excluded_from_td_comparison"] = True
    report["checks"]["ceann_comhairle_excluded_from_ordinary_opportunities"] = True
    report["ready_for_content_development"] = all(report["checks"].values())
    report_path.write_text(json.dumps(report, indent=2, sort_keys=True, default=str) + "\n", encoding="utf-8")

    summary_path = OUT_DIR / "summary.md"
    if summary_path.exists():
        summary = summary_path.read_text(encoding="utf-8")
        summary += (
            "\n## Ceann Comhairle adjustment\n\n"
            f"{CEANN_COMHAIRLE_NAME} is excluded from the TD comparison for this resolved period. "
            f"Additional ordinary opportunities removed after the per-division presiding rule: **{len(excluded_ceann):,}**. "
            "An actual recorded casting vote would remain eligible.\n"
            f"Corrected eligible TD × division opportunities: **{member_den:,}**.\n"
        )
        summary_path.write_text(summary, encoding="utf-8")

    print(json.dumps({
        "status": "PASS",
        "additional_ceann_comhairle_opportunities_excluded": int(len(excluded_ceann)),
        "member_eligible_division_opportunities": member_den,
        "member_recorded_participation_opportunities": member_num,
        "ceann_comhairle_present_in_td_output": False,
    }, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
