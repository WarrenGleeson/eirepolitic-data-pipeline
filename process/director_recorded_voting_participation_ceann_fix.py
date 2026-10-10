#!/usr/bin/env python3
"""Apply the Ceann Comhairle denominator rule to Director voting evidence.

The base audit removes whichever member is identified as physically presiding for
an individual division. This correction also removes an active Ceann Comhairle
from ordinary eligible opportunities throughout the office-holder's tenure,
unless an actual recorded vote exists (casting-vote case).

It rewrites only the Director review evidence produced by the audit. Production
source data is read-only and is not mutated.
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


def main() -> int:
    report_path = OUT_DIR / "report.json"
    report = json.loads(report_path.read_text(encoding="utf-8"))
    batch_id = str(report["production_batch_id"])
    period_start = pd.Timestamp(report["resolved_period"]["start"])
    period_end = pd.Timestamp(report["resolved_period"]["end"])
    excluded_division_ids = set(report["division_counts"].get("excluded_division_ids", []))

    s3 = boto3.client("s3", region_name=os.getenv("AWS_REGION", os.getenv("AWS_DEFAULT_REGION", "ca-central-1")))
    frames = {}
    for name in [
        "silver_divisions",
        "silver_member_votes",
        "silver_member_memberships",
        "silver_member_parties",
        "silver_member_constituencies",
        "silver_member_offices",
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

    # Reapply the existing per-division presiding-member exclusion first.
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

    # Apply the office-holder rule throughout the active Ceann Comhairle tenure.
    offices = frames["silver_member_offices"].copy()
    ceann = offices[offices["office_name"].fillna("").astype(str).str.strip().str.casefold().eq("ceann comhairle")].copy()
    ceann["office_start_dt"] = pd.to_datetime(ceann["office_start"], errors="coerce").dt.normalize()
    ceann["office_end_dt"] = pd.to_datetime(ceann["office_end"], errors="coerce").dt.normalize()
    if ceann.empty:
        raise RuntimeError("No Ceann Comhairle office-holder row found in production evidence")

    office_matches = eligible[["division_id", "member_code", "division_date", "has_recorded_vote"]].merge(
        ceann[["member_code", "office_name", "office_start_dt", "office_end_dt"]],
        on="member_code",
        how="inner",
    )
    active = (
        office_matches["office_start_dt"].notna()
        & (office_matches["division_date"] >= office_matches["office_start_dt"])
        & (office_matches["office_end_dt"].isna() | (office_matches["division_date"] <= office_matches["office_end_dt"]))
    )
    active_ceann_pairs = set(
        zip(
            office_matches.loc[active, "division_id"],
            office_matches.loc[active, "member_code"],
        )
    )
    eligible["is_active_ceann_comhairle"] = [
        (division_id, member_code) in active_ceann_pairs
        for division_id, member_code in zip(eligible["division_id"], eligible["member_code"])
    ]
    excluded_ceann = eligible[eligible["is_active_ceann_comhairle"] & ~eligible["has_recorded_vote"]].copy()
    eligible = eligible[~(eligible["is_active_ceann_comhairle"] & ~eligible["has_recorded_vote"])].copy()

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
    ]].sort_values(["member_name", "member_code"])

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

    td.to_csv(OUT_DIR / "td_participation.csv", index=False)
    party.to_csv(OUT_DIR / "party_participation.csv", index=False)
    constituency.to_csv(OUT_DIR / "constituency_participation.csv", index=False)

    report["audit_version"] = "1.1-ceann-comhairle-office-rule"
    report["presiding_member"]["rule"] = (
        "exclude the identified presiding member from an ordinary eligible opportunity unless that member has a recorded vote; "
        "also exclude an active Ceann Comhairle from ordinary eligible opportunities throughout the office tenure unless an actual recorded vote exists (casting-vote case)"
    )
    report["presiding_member"]["additional_active_ceann_comhairle_opportunities_excluded"] = int(len(excluded_ceann))
    report["presiding_member"]["active_ceann_comhairle_member_codes"] = sorted(set(ceann["member_code"].astype(str)))
    report["reconciliation"].update({
        "member_recorded_participation_opportunities": member_num,
        "member_eligible_division_opportunities": member_den,
        "party_recorded_participation_opportunities": party_num,
        "party_eligible_division_opportunities": party_den,
        "constituency_recorded_participation_opportunities": const_num,
        "constituency_eligible_division_opportunities": const_den,
    })
    report["checks"]["active_ceann_comhairle_excluded_from_ordinary_opportunities"] = not (
        eligible["is_active_ceann_comhairle"] & ~eligible["has_recorded_vote"]
    ).any()
    report["ready_for_content_development"] = all(report["checks"].values())
    report_path.write_text(json.dumps(report, indent=2, sort_keys=True, default=str) + "\n", encoding="utf-8")

    summary_path = OUT_DIR / "summary.md"
    if summary_path.exists():
        summary = summary_path.read_text(encoding="utf-8")
        summary += (
            "\n## Ceann Comhairle office-holder adjustment\n\n"
            f"Active Ceann Comhairle ordinary opportunities additionally removed: **{len(excluded_ceann):,}**. "
            "An actual recorded casting vote would remain eligible.\n"
            f"Corrected eligible TD × division opportunities: **{member_den:,}**.\n"
        )
        summary_path.write_text(summary, encoding="utf-8")

    print(json.dumps({
        "status": "PASS",
        "additional_active_ceann_comhairle_opportunities_excluded": int(len(excluded_ceann)),
        "member_eligible_division_opportunities": member_den,
        "member_recorded_participation_opportunities": member_num,
        "ceann_comhairle_present_in_td_output": bool(td["member_name"].eq("Verona Murphy").any()),
    }, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
