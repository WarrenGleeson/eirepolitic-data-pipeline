from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Protocol

from botocore.exceptions import ClientError

from publishing.models import PublicationSchedule


class SchedulerError(RuntimeError):
    pass


class SchedulerConflict(SchedulerError):
    pass


@dataclass(frozen=True)
class SchedulerTarget:
    lambda_arn: str
    role_arn: str
    dlq_arn: str


class PublicationScheduler(Protocol):
    def create(self, schedule: PublicationSchedule) -> str: ...
    def verify(self, schedule: PublicationSchedule) -> bool: ...
    def cancel(self, schedule: PublicationSchedule) -> None: ...


class EventBridgePublicationScheduler:
    """Adapter for one-time EventBridge Scheduler jobs.

    The job contains only publication identity/version. Approved content and
    credentials remain outside Scheduler.
    """

    def __init__(self, client: Any, target: SchedulerTarget, *, group_name: str = "eirepolitic-instagram") -> None:
        self.client = client
        self.target = target
        self.group_name = group_name

    @staticmethod
    def schedule_name(schedule: PublicationSchedule) -> str:
        safe_id = "".join(ch if ch.isalnum() or ch in "-_" else "-" for ch in schedule.publication_id)
        return f"instagram-{safe_id}-v{schedule.publication_version}"

    @staticmethod
    def payload(schedule: PublicationSchedule) -> str:
        return json.dumps(
            {
                "publication_id": schedule.publication_id,
                "expected_version": int(schedule.publication_version),
            },
            separators=(",", ":"),
            sort_keys=True,
        )

    @staticmethod
    def expression(schedule: PublicationSchedule) -> str:
        value = datetime.fromisoformat(schedule.scheduled_at_utc.replace("Z", "+00:00")).astimezone(timezone.utc)
        return f"at({value.strftime('%Y-%m-%dT%H:%M:%S')})"

    def _target(self, schedule: PublicationSchedule) -> dict[str, Any]:
        return {
            "Arn": self.target.lambda_arn,
            "RoleArn": self.target.role_arn,
            "Input": self.payload(schedule),
            "DeadLetterConfig": {"Arn": self.target.dlq_arn},
            "RetryPolicy": {
                "MaximumEventAgeInSeconds": 3600,
                "MaximumRetryAttempts": 3,
            },
        }

    def create(self, schedule: PublicationSchedule) -> str:
        if schedule.status != "scheduled":
            raise SchedulerError("only an active scheduled publication can create an EventBridge job")
        name = self.schedule_name(schedule)
        try:
            self.client.create_schedule(
                Name=name,
                GroupName=self.group_name,
                ScheduleExpression=self.expression(schedule),
                FlexibleTimeWindow={"Mode": "OFF"},
                ActionAfterCompletion="DELETE",
                Target=self._target(schedule),
                Description=f"Eirepolitic Instagram publication {schedule.publication_id} v{schedule.publication_version}",
            )
        except ClientError as exc:
            if exc.response.get("Error", {}).get("Code") == "ConflictException":
                raise SchedulerConflict(f"schedule already exists: {name}") from exc
            raise
        return name

    def verify(self, schedule: PublicationSchedule) -> bool:
        try:
            response = self.client.get_schedule(Name=self.schedule_name(schedule), GroupName=self.group_name)
        except ClientError as exc:
            if exc.response.get("Error", {}).get("Code") == "ResourceNotFoundException":
                return False
            raise
        target = response.get("Target", {})
        return (
            response.get("ScheduleExpression") == self.expression(schedule)
            and response.get("FlexibleTimeWindow") == {"Mode": "OFF"}
            and target.get("Arn") == self.target.lambda_arn
            and target.get("Input") == self.payload(schedule)
        )

    def cancel(self, schedule: PublicationSchedule) -> None:
        try:
            self.client.delete_schedule(Name=self.schedule_name(schedule), GroupName=self.group_name)
        except ClientError as exc:
            if exc.response.get("Error", {}).get("Code") == "ResourceNotFoundException":
                return
            raise
