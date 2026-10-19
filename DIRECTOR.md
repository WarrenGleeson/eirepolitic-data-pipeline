# eirepolitic-data-pipeline Director Pack

## System

`eirepolitic-data-pipeline` is the active data and publishing pipeline for EirePolitic. It handles ingestion, processing, scheduling, and downstream publishing workflows.

## Existing capabilities

- Production data ingestion and processing workflows.
- AWS-backed storage and runtime components.
- Instagram publishing schedules managed through AWS services.
- Existing repository-specific agent guidance under `director/`.
- GitHub Actions workflows for operational automation.

## Operating workflows

Use the existing repository guidance and workflows rather than creating parallel mechanisms.

Primary references:

- Agent knowledge layer: `director/README.md`
- Operational workflows: `.github/workflows/`
- Human/project overview: `README.md`
- Additional documentation: `docs/`

## Readiness

Production-sensitive and actively maintained. Verify current GitHub Actions, AWS state, and external publishing state before changing operational behavior.

## Authoritative state

- Durable project knowledge and operating guidance: repository documentation, especially `director/` and `docs/`.
- Repository and workflow state: live GitHub.
- AWS runtime/configuration: live AWS environment.
- Instagram publishing schedules: AWS DynamoDB and EventBridge Scheduler.

If documentation and live state conflict, verify whether the docs are stale or the live system has drifted before changing architecture.

## Documentation pointers

- Human entry point: `README.md`
- Agent-specific guidance: `director/README.md`
- Additional docs: `docs/`
- Workflows: `.github/workflows/`

## Do not rebuild

- Do not replace or duplicate the existing `director/` knowledge layer.
- Do not rename AWS resources merely to match the GitHub account migration.
- Do not move Instagram scheduling into GitHub; it remains managed through AWS DynamoDB and EventBridge Scheduler.
- Reuse existing workflows and infrastructure before adding alternatives.

## Operational warnings

- This is a production-sensitive repository.
- Existing AWS resources containing `eirepolitic` in their names are intentionally unchanged.
- Do not change credentials, deployment/runtime resources, schedules, publishing integrations, or production behavior as part of repository standardization.
- Never commit secret values.

## Standard deviations

The repository keeps its richer agent knowledge under `director/`. Root `DIRECTOR.md` is the V1 entry point and points to that existing canonical layer rather than duplicating it.

## Continuation

- Outstanding work: continue normal migration cleanup and pipeline development without changing runtime resource names solely for account consistency.
- Next safe action: inspect the relevant `director/` guidance and live operational state before making implementation changes.
