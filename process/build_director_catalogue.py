#!/usr/bin/env python3
"""Generate the derivable, AUTO-GENERATED sections of director/*.yml from
live GitHub state.

This script owns exactly two things:
  - director/workflows.yml  -> the `inventory` block (id/name/path/state
                                for every GitHub Actions workflow)
  - director/projects.yml   -> the `directory_listing` block (project_id,
                                path, and a few flat fields read out of
                                each instagram/projects/*/project.yml)

Everything else in director/ (refs.yml, references.yml, semantics.md,
capabilities.yml, data_products.yml, visuals.yml, publishing.yml, and the
hand-maintained parts of workflows.yml/projects.yml) is human-reviewed and
this script must never touch it.

Usage:
    python process/build_director_catalogue.py            # regenerate in place
    python process/build_director_catalogue.py --check     # CI drift check;
                                                             # exit 1 if the
                                                             # committed file
                                                             # doesn't match
                                                             # a fresh
                                                             # regeneration

Requires GITHUB_TOKEN (or GH_TOKEN) in the environment with read access to
the repository -- this is set automatically for the standard
`GITHUB_TOKEN` secret in GitHub Actions. Requires PyYAML (already a
dependency of this repository's many project.yml consumers).

Note for anyone running this outside GitHub Actions: this repository's
sandboxed Claude sessions have no authorized direct GitHub API or git-push
credential (see director/refs.yml's Phase 1 notes on the MCP write path).
This script is written to run inside a GitHub Actions job, where the
runner's own GITHUB_TOKEN has normal API read access -- it has not been,
and cannot be, executed end-to-end from within such a session. It has only
been syntax- and YAML-shape-checked locally (see the Phase 2 PR notes).
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
import urllib.error
import urllib.request
from dataclasses import dataclass, field

try:
    import yaml
except ImportError:  # pragma: no cover
    print(
        "PyYAML is required (pip install pyyaml). This repository already "
        "depends on it elsewhere for project.yml parsing.",
        file=sys.stderr,
    )
    raise

REPO_OWNER = "warrengleeson"
REPO_NAME = "eirepolitic-data-pipeline"
API_ROOT = "https://api.github.com"

WORKFLOWS_FILE = "director/workflows.yml"
PROJECTS_FILE = "director/projects.yml"

WORKFLOWS_START = "# AUTO-GENERATED — do not hand-edit below this line until the matching END marker."
WORKFLOWS_END = "# END AUTO-GENERATED"
PROJECTS_START = WORKFLOWS_START
PROJECTS_END = WORKFLOWS_END


def _token() -> str:
    token = os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN")
    if not token:
        raise SystemExit(
            "GITHUB_TOKEN (or GH_TOKEN) must be set. In GitHub Actions this "
            "is the standard ${{ secrets.GITHUB_TOKEN }} passed into env."
        )
    return token


def _api_get(path: str, token: str, params: dict | None = None) -> dict:
    url = f"{API_ROOT}{path}"
    if params:
        from urllib.parse import urlencode

        url = f"{url}?{urlencode(params)}"
    req = urllib.request.Request(
        url,
        headers={
            "Authorization": f"Bearer {token}",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
            "User-Agent": "eirepolitic-director-catalogue-builder",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:  # pragma: no cover
        body = exc.read().decode("utf-8", errors="replace")
        raise SystemExit(f"GitHub API GET {path} failed: {exc.code} {body}") from exc


@dataclass
class Workflow:
    id: int
    name: str
    path: str
    state: str


def fetch_workflows(token: str) -> list[Workflow]:
    workflows: list[Workflow] = []
    page = 1
    while True:
        data = _api_get(
            f"/repos/{REPO_OWNER}/{REPO_NAME}/actions/workflows",
            token,
            params={"per_page": 100, "page": page},
        )
        items = data.get("workflows", [])
        if not items:
            break
        for w in items:
            workflows.append(
                Workflow(id=w["id"], name=w["name"], path=w["path"], state=w["state"])
            )
        if len(items) < 100:
            break
        page += 1
    workflows.sort(key=lambda w: w.path)
    return workflows


@dataclass
class ProjectDir:
    project_id: str
    path: str
    extra: dict = field(default_factory=dict)


def fetch_project_dirs(token: str, ref: str = "main") -> list[ProjectDir]:
    listing = _api_get(
        f"/repos/{REPO_OWNER}/{REPO_NAME}/contents/instagram/projects",
        token,
        params={"ref": ref},
    )
    dirs = [item for item in listing if item.get("type") == "dir"]
    projects: list[ProjectDir] = []
    for d in sorted(dirs, key=lambda x: x["name"]):
        project_id = d["name"]
        project_yml_path = f"instagram/projects/{project_id}/project.yml"
        file_data = _api_get(
            f"/repos/{REPO_OWNER}/{REPO_NAME}/contents/{project_yml_path}",
            token,
            params={"ref": ref},
        )
        import base64

        content = base64.b64decode(file_data["content"]).decode("utf-8")
        parsed = yaml.safe_load(content) or {}
        extra = {}
        if "status" in parsed:
            extra["status_field_in_project_yml"] = parsed["status"]
        period = parsed.get("period") or {}
        cadence = period.get("cadence") or period.get("default")
        if cadence:
            extra["cadence"] = str(cadence)
        if "adapter_module" in parsed:
            extra["adapter_module"] = parsed["adapter_module"]
        projects.append(
            ProjectDir(
                project_id=project_id,
                path=f"instagram/projects/{project_id}/",
                extra=extra,
            )
        )
    return projects


def _yaml_scalar(value: str) -> str:
    needs_quote = bool(re.search(r'[:#"\'{}\[\],&*!|>%@`]', value)) or value != value.strip() or value == ""
    return json.dumps(value) if needs_quote else value


def render_workflows_block(workflows: list[Workflow], generated_at: str) -> str:
    lines = [
        WORKFLOWS_START,
        "inventory:",
        f"  generated_from: GitHub Actions workflows API (all {len(workflows)} workflows in the repo)",
        f'  generated_at_last_hand_sync: "{generated_at}"',
        "  workflows:",
    ]
    for w in workflows:
        lines.append(f"    - id: {w.id}")
        lines.append(f"      name: {_yaml_scalar(w.name)}")
        lines.append(f"      path: {_yaml_scalar(w.path)}")
        lines.append(f"      state: {w.state}")
    lines.append(WORKFLOWS_END)
    return "\n".join(lines) + "\n"


def render_projects_block(projects: list[ProjectDir], generated_at: str) -> str:
    lines = [
        PROJECTS_START,
        "directory_listing:",
        "  generated_from: instagram/projects/*/project.yml on main",
        f'  generated_at_last_hand_sync: "{generated_at}"',
        "  projects:",
    ]
    for p in projects:
        lines.append(f"    - project_id: {p.project_id}")
        lines.append(f"      path: {p.path}")
        for key, value in p.extra.items():
            lines.append(f"      {key}: {_yaml_scalar(str(value))}")
    lines.append(PROJECTS_END)
    return "\n".join(lines) + "\n"


def _replace_block(text: str, new_block: str, start: str, end: str) -> str:
    start_idx = text.index(start)
    end_idx = text.index(end, start_idx) + len(end)
    return text[:start_idx] + new_block.rstrip("\n") + "\n" + text[end_idx + 1 :]


def _extract_block(text: str, start: str, end: str) -> str:
    start_idx = text.index(start)
    end_idx = text.index(end, start_idx) + len(end)
    return text[start_idx:end_idx] + "\n"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--check",
        action="store_true",
        help="Fail if regenerating would change the committed files (CI drift check).",
    )
    parser.add_argument(
        "--generated-at",
        default=None,
        help="Override the generated_at_last_hand_sync date stamp (default: today, UTC).",
    )
    args = parser.parse_args()

    import datetime

    generated_at = args.generated_at or datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%d")

    token = _token()
    workflows = fetch_workflows(token)
    projects = fetch_project_dirs(token)

    new_workflows_block = render_workflows_block(workflows, generated_at)
    new_projects_block = render_projects_block(projects, generated_at)

    exit_code = 0
    for path, new_block, start, end in (
        (WORKFLOWS_FILE, new_workflows_block, WORKFLOWS_START, WORKFLOWS_END),
        (PROJECTS_FILE, new_projects_block, PROJECTS_START, PROJECTS_END),
    ):
        with open(path, "r", encoding="utf-8") as fh:
            current_text = fh.read()

        if args.check:
            current_block = _extract_block(current_text, start, end)
            # Ignore the generated_at_last_hand_sync line for drift purposes --
            # only content drift (workflows added/removed/renamed/state-changed,
            # or projects added/removed/changed) should fail CI, not the date.
            norm = lambda b: re.sub(r'generated_at_last_hand_sync: ".*"', "generated_at_last_hand_sync: DATE", b)
            if norm(current_block) != norm(new_block):
                print(f"DRIFT in {path}: committed AUTO-GENERATED block does not match live GitHub state.")
                print("--- committed ---")
                print(current_block)
                print("--- regenerated ---")
                print(new_block)
                exit_code = 1
            else:
                print(f"OK: {path} AUTO-GENERATED block matches live GitHub state.")
        else:
            updated_text = _replace_block(current_text, new_block, start, end)
            with open(path, "w", encoding="utf-8") as fh:
                fh.write(updated_text)
            print(f"Regenerated {path}.")

    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
