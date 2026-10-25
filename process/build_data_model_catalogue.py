from __future__ import annotations

import argparse
import html
import io
import json
from pathlib import Path
from typing import Any

import boto3
import pandas as pd
import pyarrow.parquet as pq
import yaml

BUCKET = "eirepolitic-data"
REGION = "ca-central-1"
PRODUCTION_POINTER = "processed/oireachtas_unified/pointers/production.json"
BATCH_ROOT = "processed/oireachtas_unified/batches"
POLLING_PREFIX = "processed/polling/irish_polling_indicator/latest"
GITHUB_ROOT = "https://github.com/eirepolitic/eirepolitic-data-pipeline/blob/main"

CATEGORY_ORDER = [
    "People & representation",
    "Debates & speeches",
    "Questions",
    "Voting",
    "Legislation",
    "Political metrics",
    "Polling",
    "Other curated data",
]

DATASET_DESCRIPTIONS = {
    "written_question_answer_sections": "One record per official Written Parliamentary Question answer section, preserving the answer text and source-document evidence.",
    "written_question_answer_bridge": "One record per Parliamentary Question linking the question to its observed official Written Answer section and XML match status.",
}

RELATIONSHIPS: dict[str, list[str]] = {
    "silver_houses": ["house_uri → silver_constituencies.house_uri", "house_uri / house_no → silver_member_memberships", "house_uri / house_no → silver_debate_records and silver_divisions"],
    "silver_constituencies": ["constituency_uri → silver_member_constituencies.constituency_uri", "constituency_name is carried onto historical member-vote and gold constituency outputs"],
    "silver_parties": ["party_uri → silver_member_parties.party_uri", "party_name is resolved time-aware for voting/activity outputs"],
    "silver_members": ["member_code → member bridges, silver_speeches.speaker_member_code, silver_member_votes.member_code, silver_questions.asked_by_member_code"],
    "silver_member_memberships": ["membership_id → silver_member_parties, silver_member_constituencies and silver_member_offices", "member_code → silver_members.member_code"],
    "silver_member_parties": ["membership_id → silver_member_memberships.membership_id", "party_uri → silver_parties.party_uri", "member_code → silver_members.member_code"],
    "silver_member_constituencies": ["membership_id → silver_member_memberships.membership_id", "constituency_uri → silver_constituencies.constituency_uri", "member_code → silver_members.member_code"],
    "silver_member_offices": ["membership_id → silver_member_memberships.membership_id", "member_code → silver_members.member_code"],
    "silver_source_files": ["source_file_id is referenced by debates, questions and Bill document/version tables where a source file was downloaded"],
    "silver_debate_records": ["debate_id → silver_debate_sections.debate_id, silver_speeches.debate_id, silver_divisions.debate_id and silver_bill_debates.debate_id"],
    "silver_debate_sections": ["debate_section_id → silver_speeches, silver_questions, silver_divisions and certified context/legislation bridges", "parent_section_id is a self-relationship for section hierarchy"],
    "silver_speeches": ["speaker_member_code → silver_members.member_code when matched", "debate_id / debate_section_id → debate tables", "speech_id → speech_question_context and speech_context"],
    "silver_divisions": ["division_id → silver_division_tallies and silver_member_votes", "debate_id / debate_section_id → debate context where available", "division_id → division_context and vote metric foundations"],
    "silver_division_tallies": ["division_id → silver_divisions.division_id"],
    "silver_member_votes": ["division_id → silver_divisions.division_id", "member_code → silver_members.member_code", "party_name_at_vote and constituency_name_at_vote are time-aware historical attributes"],
    "silver_questions": ["asked_by_member_code → silver_members.member_code", "debate_section_id → silver_debate_sections.debate_section_id when a transcript section is linked", "oral questions feed oral_question_sections and related participant/context foundations", "question_id → written_question_answer_bridge.question_id for written-answer linkage where available"],
    "written_question_answer_bridge": ["question_id → silver_questions.question_id", "debate_section_id → written_question_answer_sections.debate_section_id", "question_xml_match_status preserves whether the XML question identifier was verified rather than hiding uncertain matches"],
    "written_question_answer_sections": ["debate_section_id ← written_question_answer_bridge.debate_section_id", "one answer section can relate to multiple questions when the official source groups answers"],
    "silver_bills": ["bill_id → all silver_bill_* child/bridge tables", "bill_id → bill_debate_sections for certified section-level legislation context"],
    "silver_bill_versions": ["bill_id → silver_bills.bill_id", "source_file_id_* → silver_source_files.source_file_id where downloaded"],
    "silver_bill_stages": ["bill_id → silver_bills.bill_id"],
    "silver_bill_related_docs": ["bill_id → silver_bills.bill_id", "source_file_id_* → silver_source_files.source_file_id where downloaded"],
    "silver_bill_sponsors": ["bill_id → silver_bills.bill_id", "sponsor_uri is source-provided; it is not documented as an enforced member foreign key"],
    "silver_bill_debates": ["bill_id → silver_bills.bill_id", "debate_id → silver_debate_records.debate_id", "debate_section_id → silver_debate_sections.debate_section_id when present"],
    "silver_bill_events": ["bill_id → silver_bills.bill_id"],
    "gold_current_members": ["member_code → silver_members.member_code; party/constituency/office are flattened current attributes"],
    "gold_member_activity_yearly": ["member_code → silver_members.member_code; derived from speech and division/vote activity"],
    "gold_member_activity_monthly": ["member_code → silver_members.member_code; derived from speech and vote activity"],
    "gold_constituency_activity_yearly": ["constituency_name is the reporting grain; derived from member activity attributed to constituencies"],
    "gold_content_fact_pool": ["source_table + source_key point back to the curated fact source; this is a downstream content-selection pool"],
    "daily_activity_components": ["entity_id represents the entity at grain member/party/constituency/national; components are derived from curated speeches, questions and recorded votes"],
    "daily_context_vote_components": ["division_context comes from division_context; collapsing that dimension must reconcile to daily_activity_components voting components"],
    "daily_issue_activity": ["issue_label comes from speech issue classification; entity_id follows the documented grain"],
    "division_party_vote_components": ["division_id → silver_divisions.division_id; party_uri connects to the party identity used at vote time"],
    "context_division_party_vote_components": ["division_id → silver_divisions.division_id and division_context; collapsing context reconciles to division_party_vote_components"],
    "daily_question_dimensions": ["entity_id follows member/party/constituency/national grain; counts silver_questions records, not transcript interventions"],
    "oral_question_sections": ["debate_section_id → silver_debate_sections.debate_section_id; question_ids_json identifies related silver_questions records"],
    "oral_question_exchange_participants": ["debate_section_id → oral_question_sections / silver_debate_sections; member_code → silver_members.member_code when identified"],
    "speech_question_context": ["speech_id → silver_speeches.speech_id; debate_section_id → oral_question_sections when oral-question-related"],
    "bill_debate_sections": ["bill_id → silver_bills.bill_id; debate_section_id → silver_debate_sections.debate_section_id"],
    "speech_context": ["speech_id → silver_speeches.speech_id; linked_entity_id is interpreted according to linked_entity_type"],
    "division_context": ["division_id → silver_divisions.division_id; linked_entity_id is interpreted according to linked_entity_type"],
    "monthly_metric_results": ["entity_id is interpreted by grain; metric_id/metric_version identify the calculation; foundations are recomputed for requested periods rather than summing percentages/ranks"],
    "polls": ["Standalone polling observations; not joined to Oireachtas identifiers by an enforced key"],
    "polling_indicator": ["Standalone modelled polling time series; party columns use source abbreviations and are not enforced foreign keys to silver_parties"],
}

TRANSFORM_NOTES: dict[str, str] = {
    "silver_speeches": "Parsed into atomic interventions from debate XML; speaker matching is retained with method/confidence, text is hashed, and word/character counts are calculated.",
    "silver_debate_sections": "Parsed from Oireachtas debate metadata/XML into deterministic section identifiers and parent/ordering structure.",
    "silver_member_votes": "Exploded from division membership payloads to one member-vote row; party and constituency are recorded as historical attributes at vote time.",
    "silver_questions": "Normalizes Oireachtas question records and source-document references; oral-question transcript participation is modelled separately and must not be read as question-taking attribution.",
    "written_question_answer_sections": "Structurally extracts official Akoma Ntoso Written Answers XML at answer-section grain, preserving grouped answers, referrals/direct replies, embedded-table counts, source URLs and document/section hashes. No AI classification is used.",
    "written_question_answer_bridge": "Builds a deterministic question-to-answer-section relationship and keeps XML question-ID verification status in a separate field so uncertain source matches remain visible.",
    "bill_debate_sections": "Certified exact Bill-to-section bridge. Debate-wide co-occurrence, conflicting source records and multi-Bill section anomalies are excluded.",
    "speech_context": "Assigns exactly one top-level context per speech using deterministic precedence across certified question, legislation and heading evidence; `other` is the explicit fallback.",
    "division_context": "Assigns one deterministic context per division using certified Bill relationships and section-level speech context without multiplying vote rows.",
    "oral_question_exchange_participants": "Captures observed transcript participation only. It deliberately does not infer who formally took a submitted question.",
    "daily_context_vote_components": "Adds certified division context while preserving the existing vote numerator/eligible-member denominator rules.",
    "context_division_party_vote_components": "Adds certified division context while preserving party-at-vote attribution and reconciliation to the non-context foundation.",
    "polls": "Validates the exact upstream schema, strict dates and sample sizes; preserves historical negative source values as quality flags; converts numeric party fields while retaining source provenance.",
    "polling_indicator": "Validates exact source schema, unique (date, cycle), complete lower/estimate/upper intervals and 0–1 bounds; duplicate calendar dates at cycle boundaries are quality-flagged, not removed.",
}


def _get_json(s3: Any, key: str) -> dict[str, Any]:
    obj = s3.get_object(Bucket=BUCKET, Key=key)
    return json.loads(obj["Body"].read().decode("utf-8"))


def _object_exists(s3: Any, key: str) -> bool:
    try:
        s3.head_object(Bucket=BUCKET, Key=key)
        return True
    except Exception:
        return False


def _list_keys(s3: Any, prefix: str) -> list[str]:
    keys: list[str] = []
    paginator = s3.get_paginator("list_objects_v2")
    for page in paginator.paginate(Bucket=BUCKET, Prefix=prefix):
        keys.extend(str(item["Key"]) for item in page.get("Contents", []))
    return keys


def _read_parquet(s3: Any, key: str) -> pd.DataFrame:
    obj = s3.get_object(Bucket=BUCKET, Key=key)
    return pq.read_table(io.BytesIO(obj["Body"].read())).to_pandas()


def _load_yaml(path: str) -> dict[str, Any]:
    return yaml.safe_load(Path(path).read_text(encoding="utf-8")) or {}


def _sample_rows(frame: pd.DataFrame, n: int = 10) -> pd.DataFrame:
    if len(frame) <= n:
        return frame.copy()
    # Even spacing is deterministic and gives a more representative visual sample than head(10).
    positions = [round(i * (len(frame) - 1) / (n - 1)) for i in range(n)]
    return frame.iloc[positions].copy()


def _dtype_name(series: pd.Series) -> str:
    return str(series.dtype)


def _display(value: Any) -> str:
    if value is None:
        return "NULL"
    try:
        if pd.isna(value):
            return "NULL"
    except Exception:
        pass
    if isinstance(value, (dict, list, tuple)):
        return json.dumps(value, ensure_ascii=False, sort_keys=True)
    text = str(value)
    return text if text else "BLANK"


def _category(name: str) -> str:
    if name.startswith(("silver_member", "silver_houses", "silver_constituencies", "silver_parties", "gold_current_members")):
        return "People & representation"
    if name.startswith(("silver_debate", "silver_speeches")) or name in {"speech_question_context", "speech_context", "daily_issue_activity"}:
        return "Debates & speeches"
    if "question" in name:
        return "Questions"
    if name.startswith("silver_division") or name == "silver_member_votes" or "vote" in name or name == "division_context":
        return "Voting"
    if name.startswith("silver_bill") or name == "bill_debate_sections":
        return "Legislation"
    if name in {"polls", "polling_indicator"}:
        return "Polling"
    if name.startswith("gold_") or name in {"daily_activity_components", "monthly_metric_results"}:
        return "Political metrics"
    return "Other curated data"


def _source_text(name: str, meta: dict[str, Any]) -> str:
    if name in {"polls", "polling_indicator"}:
        source_file = "data_polls.csv" if name == "polls" else "data_pollingindicator.csv"
        return f"Irish Polling Indicator (IPI) GitHub dataset, `{source_file}`. Reuse/licence status is recorded by the ingestion as unconfirmed."
    if name in {"written_question_answer_sections", "written_question_answer_bridge"}:
        return "Official Houses of the Oireachtas Akoma Ntoso Written Answers XML. Historical/incremental extraction may use the daily main.xml while preserving each section's official source URL."
    if meta.get("kind") == "metric":
        return "Derived inside the EirePolitic political-metrics pipeline from the promoted Oireachtas batch; exact source semantics are defined in `configs/political_metrics/materialization.yml`."
    endpoint = meta.get("endpoint")
    if endpoint:
        return f"Houses of the Oireachtas API `{endpoint}` plus linked XML/PDF resources where the builder requires them."
    if name in {"silver_debate_sections", "silver_speeches"}:
        return "Houses of the Oireachtas debate records and downloaded debate XML."
    if name.startswith("gold_"):
        return "Derived from EirePolitic curated Oireachtas silver tables in the same promoted batch."
    return "EirePolitic promoted Oireachtas batch; see the linked implementation/configuration evidence."


def _transform_text(name: str, meta: dict[str, Any]) -> str:
    if name in TRANSFORM_NOTES:
        return TRANSFORM_NOTES[name]
    if name.startswith("silver_member_"):
        return "Normalizes nested member-history payloads into a time-aware bridge with deterministic IDs, current flags and snapshot metadata."
    if name in {"silver_members", "silver_houses", "silver_constituencies", "silver_parties"}:
        return "Normalizes source identifiers/names and validity fields into a stable dimension; source hashes and snapshot metadata support reproducibility and change detection."
    if name.startswith("silver_division"):
        return "Normalizes Oireachtas division payloads into stable event/tally records with source hashes or snapshot metadata as applicable."
    if name.startswith("silver_bill"):
        return "Normalizes legislation payloads into one stable Bill entity plus child/bridge records for versions, stages, documents, sponsors, debates and events."
    if name.startswith("gold_"):
        return "Deterministic downstream aggregation/flattening from curated silver tables; designed for analysis rather than source-system fidelity."
    if meta.get("kind") == "metric":
        return str(meta.get("description") or "Deterministic metric materialization from promoted curated data.")
    return "Normalized and quality-checked by the repository implementation before publication."


def _notes(name: str, meta: dict[str, Any], rows: int) -> str:
    notes: list[str] = []
    if rows < 10:
        notes.append(f"The current dataset contains only {rows} rows, so the example shows every available row rather than inventing rows.")
    if name == "silver_member_votes":
        notes.append("A missing vote row must not be interpreted as an abstention; eligibility/denominator logic lives in the metric foundations.")
    if name == "silver_questions":
        notes.append("Question records and transcript speech interventions are different grains.")
    if name == "written_question_answer_sections":
        notes.append("Answers are not copied onto every question row. Grouped answers, referrals, missing replies and embedded tables remain explicit source features.")
    if name == "written_question_answer_bridge":
        notes.append("The bridge preserves XML match status separately from the section relationship; do not treat every relationship as an independently verified XML question identifier.")
    if name in {"polls", "polling_indicator"}:
        notes.append("This is a separate polling production family, not part of the atomic Oireachtas batch pointer.")
    status = meta.get("status")
    if status and status != "confirmed":
        notes.append(f"Registry status: {status}.")
    return " ".join(notes) or "No additional interpretation caveat is recorded beyond the source and transformation rules above."


def _table_html(frame: pd.DataFrame) -> str:
    headers = "".join(f"<th>{html.escape(str(c))}</th>" for c in frame.columns)
    body_rows = []
    for _, row in frame.iterrows():
        cells = "".join(f'<td><div class="cell">{html.escape(_display(row[c]))}</div></td>' for c in frame.columns)
        body_rows.append(f"<tr>{cells}</tr>")
    return f'<div class="table-wrap" tabindex="0"><table><thead><tr>{headers}</tr></thead><tbody>{"".join(body_rows)}</tbody></table></div>'


def _schema_html(frame: pd.DataFrame) -> str:
    rows = "".join(
        f"<tr><td><code>{html.escape(str(c))}</code></td><td>{html.escape(_dtype_name(frame[c]))}</td></tr>"
        for c in frame.columns
    )
    return f'<div class="schema-wrap"><table class="schema"><thead><tr><th>Column</th><th>Observed type</th></tr></thead><tbody>{rows}</tbody></table></div>'


def _impl_links(name: str, meta: dict[str, Any]) -> str:
    links: list[tuple[str, str]] = []
    if name in {"polls", "polling_indicator"}:
        links.append(("polling ingestion", f"{GITHUB_ROOT}/extract/polling/ipi.py"))
    elif name in {"written_question_answer_sections", "written_question_answer_bridge"}:
        links.append(("Written PQ answer contract", f"{GITHUB_ROOT}/configs/political_metrics/written_question_answers.yml"))
        links.append(("Written PQ deployment", f"{GITHUB_ROOT}/.github/workflows/written_pq_answer_foundation_deploy.yml"))
    elif meta.get("kind") == "metric":
        links.append(("metric contract", f"{GITHUB_ROOT}/configs/political_metrics/materialization.yml"))
        links.append(("metric pipeline", f"{GITHUB_ROOT}/political_metrics"))
    else:
        links.append(("table registry", f"{GITHUB_ROOT}/configs/oireachtas/tables.yml"))
        links.append(("Oireachtas pipeline", f"{GITHUB_ROOT}/extract/oireachtas"))
    return " · ".join(f'<a href="{html.escape(url, quote=True)}" target="_blank" rel="noopener noreferrer">{html.escape(label)}</a>' for label, url in links)


def _discover(s3: Any) -> tuple[str, list[dict[str, Any]]]:
    pointer = _get_json(s3, PRODUCTION_POINTER)
    if pointer.get("mode") != "batch":
        raise RuntimeError(f"Expected batch production pointer, got {pointer.get('mode')!r}")
    batch_id = str(pointer["batch_id"])
    base = f"{BATCH_ROOT}/{batch_id}"
    discovered: list[dict[str, Any]] = []

    for key in _list_keys(s3, f"{base}/tables/"):
        parts = key.split("/")
        if len(parts) >= 8 and parts[-2] == "parquet" and key.endswith(".parquet"):
            discovered.append({"name": parts[-3], "key": key, "kind": "table"})

    for key in _list_keys(s3, f"{base}/metrics/"):
        parts = key.split("/")
        if len(parts) >= 9 and parts[-2] == "parquet" and key.endswith(".parquet"):
            discovered.append({"name": parts[-3], "key": key, "kind": "metric", "metric_cadence": parts[-5]})

    polling_manifest = f"{POLLING_PREFIX}/manifest.json"
    if _object_exists(s3, polling_manifest):
        for name in ("polls", "polling_indicator"):
            key = f"{POLLING_PREFIX}/parquet/{name}.parquet"
            if _object_exists(s3, key):
                discovered.append({"name": name, "key": key, "kind": "polling"})

    # One physical parquet per logical dataset is required for the catalogue.
    unique: dict[str, dict[str, Any]] = {}
    for item in discovered:
        unique[item["name"]] = item
    return batch_id, sorted(unique.values(), key=lambda item: item["name"])


def build(output: Path) -> dict[str, Any]:
    s3 = boto3.client("s3", region_name=REGION)
    registry = _load_yaml("configs/oireachtas/tables.yml").get("tables", {})
    materialization = _load_yaml("configs/political_metrics/materialization.yml")
    written_answers = _load_yaml("configs/political_metrics/written_question_answers.yml")
    metric_meta = {}
    metric_meta.update(materialization.get("foundation_datasets", {}))
    metric_meta.update(materialization.get("result_datasets", {}))
    metric_meta.update(written_answers.get("foundation_datasets", {}))

    batch_id, discovered = _discover(s3)
    production: list[dict[str, Any]] = []
    supporting: list[dict[str, Any]] = []
    experimental: list[dict[str, Any]] = []

    for item in discovered:
        name = item["name"]
        reg = dict(registry.get(name) or {})
        metric = dict(metric_meta.get(name) or {})
        meta = {**reg, **metric, **item}
        if item["kind"] == "metric":
            meta["kind"] = "metric"
            meta.setdefault("status", "confirmed")
            meta.setdefault("cadence", item.get("metric_cadence"))
            meta.setdefault("primary_key", metric.get("primary_key", []))
        elif item["kind"] == "polling":
            meta["status"] = "confirmed"
            meta["cadence"] = "upstream-change driven"
            meta["primary_key"] = ["source_row_number"] if name == "polls" else ["date", "cycle"]
            meta["description"] = "Individual Irish opinion polls." if name == "polls" else "Modelled Irish party-support estimates and uncertainty intervals."

        if name.startswith("control_"):
            supporting.append(meta)
            continue
        if reg and reg.get("status") not in {None, "confirmed"}:
            experimental.append(meta)
            continue

        frame = _read_parquet(s3, item["key"])
        if frame.columns.duplicated().any():
            raise RuntimeError(f"{name}: duplicate column names")
        sample = _sample_rows(frame, 10)
        if list(sample.columns) != list(frame.columns):
            raise RuntimeError(f"{name}: sample does not preserve every column")
        meta["frame"] = frame
        meta["sample"] = sample
        meta["row_count"] = len(frame)
        meta["column_count"] = len(frame.columns)
        production.append(meta)

    # Registry-only non-production entries are surfaced separately so readers can distinguish them.
    discovered_names = {item["name"] for item in discovered}
    for name, reg in registry.items():
        if name in discovered_names:
            continue
        record = {"name": name, **reg}
        if name.startswith("control_"):
            supporting.append(record)
        elif reg.get("status") in {"in_progress", "planned", "deprecated"}:
            experimental.append(record)

    production.sort(key=lambda m: (CATEGORY_ORDER.index(_category(m["name"])) if _category(m["name"]) in CATEGORY_ORDER else 99, m["name"]))

    index_rows = []
    sections = []
    for meta in production:
        name = meta["name"]
        frame = meta["frame"]
        sample = meta["sample"]
        anchor = name.replace("_", "-")
        grain = ", ".join(meta.get("primary_key") or []) or "See columns / implementation"
        desc = str(meta.get("description") or DATASET_DESCRIPTIONS.get(name) or "Current promoted EirePolitic dataset.")
        index_rows.append(
            f'<tr><td><a href="#{anchor}"><code>{html.escape(name)}</code></a></td><td>{html.escape(_category(name))}</td><td>{html.escape(desc)}</td><td><code>{html.escape(grain)}</code></td><td>{len(frame):,}</td></tr>'
        )
        rel = RELATIONSHIPS.get(name, ["No enforced foreign-key relationship is declared here; use shared identifiers only where the pipeline contract supports the join."])
        rel_html = "".join(f"<li>{html.escape(x)}</li>" for x in rel)
        logical_location = meta["key"]
        if meta.get("kind") == "table":
            logical_location = f"processed/oireachtas_unified/latest/parquet/{name}.parquet (resolved through production batch {batch_id})"
        elif meta.get("kind") == "metric":
            logical_location = f"current batch metric object: {meta['key']}"
        section = f'''
<section class="dataset" id="{anchor}">
  <div class="section-head">
    <div><span class="eyebrow">{html.escape(_category(name))}</span><h2><code>{html.escape(name)}</code></h2><p>{html.escape(desc)}</p></div>
    <a class="back" href="#top">Back to index ↑</a>
  </div>
  <div class="facts">
    <div><strong>What it is</strong><span>One row is identified by <code>{html.escape(grain)}</code>. Current snapshot: {len(frame):,} rows × {len(frame.columns)} columns.</span></div>
    <div><strong>Source</strong><span>{html.escape(_source_text(name, meta))}</span></div>
    <div><strong>Transformations</strong><span>{html.escape(_transform_text(name, meta))}</span></div>
    <div><strong>Relationships</strong><ul>{rel_html}</ul></div>
    <div><strong>Important notes</strong><span>{html.escape(_notes(name, meta, len(frame)))}</span></div>
    <div><strong>Physical location</strong><span><code>{html.escape(logical_location)}</code></span></div>
    <div><strong>Update cadence</strong><span>{html.escape(str(meta.get('cadence') or 'Not explicitly declared'))}</span></div>
    <div><strong>Implementation evidence</strong><span>{_impl_links(name, meta)}</span></div>
  </div>
  <details class="schema-details"><summary>Schema ({len(frame.columns)} columns)</summary>{_schema_html(frame)}</details>
  <h3>Example data</h3>
  <p class="sample-note">{len(sample)} real rows from the current dataset. Every current column is shown. <strong>NULL</strong> means a missing value; <strong>BLANK</strong> means an empty string.</p>
  {_table_html(sample)}
</section>'''
        sections.append(section)

    groups: dict[str, list[str]] = {cat: [] for cat in CATEGORY_ORDER}
    for meta in production:
        groups.setdefault(_category(meta["name"]), []).append(meta["name"])
    group_cards = "".join(
        f'<div class="group-card"><h3>{html.escape(cat)}</h3><p>{len(names)} dataset{"s" if len(names) != 1 else ""}</p><div>{"".join(f"<a href=\"#{n.replace(chr(95), chr(45))}\"><code>{html.escape(n)}</code></a>" for n in names)}</div></div>'
        for cat, names in groups.items() if names
    )

    relation_rows = []
    for left, rels in RELATIONSHIPS.items():
        if left not in {m["name"] for m in production}:
            continue
        relation_rows.append(f'<tr><td><code>{html.escape(left)}</code></td><td>{"<br>".join(html.escape(r) for r in rels)}</td></tr>')

    supporting_rows = "".join(
        f'<tr><td><code>{html.escape(str(m.get("name")))}</code></td><td>{html.escape(str(m.get("status") or "current supporting"))}</td><td>{html.escape(str(m.get("description") or "Supporting/control dataset."))}</td></tr>'
        for m in sorted(supporting, key=lambda x: str(x.get("name")))
    ) or '<tr><td colspan="3">None detected.</td></tr>'
    experimental_rows = "".join(
        f'<tr><td><code>{html.escape(str(m.get("name")))}</code></td><td>{html.escape(str(m.get("status") or "not promoted"))}</td><td>{html.escape(str(m.get("description") or "Not part of the current usable production catalogue."))}</td></tr>'
        for m in sorted(experimental, key=lambda x: str(x.get("name")))
    ) or '<tr><td colspan="3">None detected.</td></tr>'

    page = f'''<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>EirePolitic · Irish politics data model</title>
<style>
:root{{--bg:#0b2119;--panel:#12352a;--panel2:#173d31;--text:#f4ead7;--muted:#cbbf9f;--line:#315448;--accent:#d8b45f;--code:#e9dcae}}
*{{box-sizing:border-box}}html{{scroll-behavior:smooth}}body{{margin:0;font-family:Arial,Helvetica,sans-serif;background:var(--bg);color:var(--text);line-height:1.55}}a{{color:var(--accent)}}code{{color:var(--code);font-family:ui-monospace,SFMono-Regular,Menlo,Consolas,monospace}}main{{max-width:1680px;margin:0 auto;padding:28px}}h1{{font-size:clamp(30px,5vw,58px);line-height:1.05;margin:8px 0 12px}}h2{{font-size:clamp(22px,3vw,34px);margin:4px 0 8px}}h3{{margin:18px 0 8px}}p{{margin:6px 0 12px}}.hero,.overview,.dataset,.appendix{{background:var(--panel);border:1px solid var(--line);border-radius:18px;padding:20px;margin-bottom:22px}}.hero p{{max-width:980px;color:var(--muted);font-size:17px}}.badges{{display:flex;gap:8px;flex-wrap:wrap;margin-top:14px}}.badge,.eyebrow{{font-size:12px;border:1px solid var(--line);border-radius:999px;padding:4px 8px;color:var(--muted)}}.grid{{display:grid;grid-template-columns:repeat(auto-fit,minmax(250px,1fr));gap:12px}}.group-card{{background:var(--panel2);border:1px solid var(--line);border-radius:14px;padding:14px}}.group-card h3{{margin-top:0}}.group-card a{{display:block;margin:5px 0}}.table-wrap,.schema-wrap{{overflow:auto;max-width:100%;border:1px solid var(--line);border-radius:12px;background:#0e2a21}}table{{border-collapse:separate;border-spacing:0;width:max-content;min-width:100%;font-size:13px}}th,td{{padding:8px 10px;border-right:1px solid var(--line);border-bottom:1px solid var(--line);vertical-align:top;text-align:left}}th{{position:sticky;top:0;background:#1a4537;color:var(--text);z-index:2;white-space:nowrap}}th:first-child,td:first-child{{position:sticky;left:0;background:#16382e;z-index:1}}th:first-child{{z-index:3;background:#1a4537}}.cell{{max-width:520px;max-height:180px;overflow:auto;white-space:pre-wrap;word-break:break-word}}.schema{{width:100%}}.schema td:first-child,.schema th:first-child{{position:static}}.section-head{{display:flex;justify-content:space-between;gap:18px;align-items:flex-start}}.back{{white-space:nowrap;font-size:13px}}.facts{{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:10px;margin:16px 0}}.facts>div{{background:var(--panel2);border:1px solid var(--line);border-radius:12px;padding:12px}}.facts strong{{display:block;color:var(--accent);font-size:12px;text-transform:uppercase;letter-spacing:.04em;margin-bottom:5px}}.facts span,.facts ul{{margin:0;color:var(--text)}}.facts ul{{padding-left:18px}}.sample-note,.muted{{color:var(--muted)}}details{{margin:10px 0 16px}}summary{{cursor:pointer;color:var(--accent)}}.index table{{width:100%}}.index td:first-child,.index th:first-child{{position:static}}.appendix table{{width:100%}}.appendix td:first-child,.appendix th:first-child{{position:static}}@media(max-width:800px){{main{{padding:14px}}.facts{{grid-template-columns:1fr}}.section-head{{display:block}}.back{{display:inline-block;margin-top:8px}}}}
</style></head><body><main id="top">
<section class="hero"><span class="eyebrow">EirePolitic data catalogue</span><h1>Irish politics data model</h1><p>This page shows the political datasets that are actually present in the current EirePolitic production stores. The Oireachtas datasets are resolved from the atomic production batch pointer; polling is inspected from its independently published latest manifest. The examples below are real rows read at documentation-build time.</p><div class="badges"><span class="badge">Production batch: {html.escape(batch_id)}</span><span class="badge">{len(production)} usable datasets documented</span><span class="badge">10-row full-column samples where ≥10 rows exist</span></div></section>
<section class="overview"><h2>Data-model overview</h2><p class="muted">The model starts with people/representation and source parliamentary records, then adds normalized debates, questions, votes and legislation, followed by deterministic analytical foundations. Polling is a separate source family.</p><div class="grid">{group_cards}</div></section>
<section class="overview"><h2>Table relationship overview</h2><p class="muted">These are explicit identifiers or documented deterministic/recommended joins. They are not presented as database-enforced foreign keys.</p><div class="table-wrap"><table><thead><tr><th>Dataset</th><th>How it connects</th></tr></thead><tbody>{''.join(relation_rows)}</tbody></table></div></section>
<section class="overview index"><h2>Table index</h2><div class="table-wrap"><table><thead><tr><th>Dataset</th><th>Group</th><th>Purpose</th><th>Primary/natural key</th><th>Rows</th></tr></thead><tbody>{''.join(index_rows)}</tbody></table></div></section>
{''.join(sections)}
<section class="appendix"><h2>Supporting / operational datasets</h2><p class="muted">These exist to run/audit the pipeline, rather than being the primary political-analysis model.</p><div class="table-wrap"><table><thead><tr><th>Dataset</th><th>Status</th><th>Purpose</th></tr></thead><tbody>{supporting_rows}</tbody></table></div></section>
<section class="appendix"><h2>Experimental, in-progress or not currently promoted</h2><p class="muted">These are deliberately separated from the current usable catalogue so prototypes are not mistaken for production tables. No elections dataset was discovered in the repository/current production stores during this build.</p><div class="table-wrap"><table><thead><tr><th>Dataset</th><th>Status</th><th>Purpose</th></tr></thead><tbody>{experimental_rows}</tbody></table></div></section>
<section class="appendix"><h2>How to refresh this page</h2><p>Run the <code>Data model documentation</code> GitHub Actions workflow. It reads production data only, regenerates this page and republishes the browser preview. No production schema or ingestion write is performed.</p></section>
</main></body></html>'''

    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(page, encoding="utf-8")
    manifest = {
        "batch_id": batch_id,
        "production_dataset_count": len(production),
        "datasets": [
            {"name": m["name"], "rows": m["row_count"], "columns": list(m["frame"].columns), "sample_rows": len(m["sample"]), "s3_key": m["key"]}
            for m in production
        ],
        "supporting": [m.get("name") for m in supporting],
        "experimental_or_not_promoted": [m.get("name") for m in experimental],
    }
    manifest_path = output.with_name("catalogue_manifest.json")
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2, default=str) + "\n", encoding="utf-8")
    return manifest


def main() -> None:
    parser = argparse.ArgumentParser(description="Build the EirePolitic production data-model catalogue from live read-only data")
    parser.add_argument("--output", default="generated_docs/data-model/index.html")
    args = parser.parse_args()
    manifest = build(Path(args.output))
    print(json.dumps({"status": "ok", "production_dataset_count": manifest["production_dataset_count"], "batch_id": manifest["batch_id"]}, indent=2))


if __name__ == "__main__":
    main()
