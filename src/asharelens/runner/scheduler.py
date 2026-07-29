"""Persistent local-time schedules that enqueue idempotent durable jobs."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta
from typing import Any
from uuid import uuid4
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from sqlalchemy import select
from sqlalchemy.orm import Session

from asharelens.runner.job_repository import JobRepository
from asharelens.runner.models import JobSnapshot
from asharelens.storage.models import RunnerScheduleRow


class ScheduleNotFound(LookupError):
    """Raised when a persistent schedule ID does not exist."""


class ScheduleConflict(ValueError):
    """A schedule name already exists with different immutable configuration."""


@dataclass(frozen=True, slots=True)
class ScheduleSnapshot:
    """Immutable view of one daily schedule."""

    id: str
    name: str
    job_type: str
    queue: str
    payload: dict[str, Any]
    timezone: str
    local_time: time
    weekdays: tuple[int, ...]
    enabled: bool
    priority: int
    max_attempts: int
    catch_up_limit: int
    next_fire_at: datetime
    last_enqueued_for: datetime | None


@dataclass(frozen=True, slots=True)
class ScheduleTick:
    """Jobs emitted by one transactional Scheduler scan."""

    enqueued: tuple[JobSnapshot, ...]


class DailyScheduleCalculator:
    """Translate local daily rules into naive UTC persistence values."""

    def next_after(
        self,
        *,
        after: datetime,
        local_time: time,
        weekdays: tuple[int, ...],
        timezone: str,
    ) -> datetime:
        """Return the first matching fire strictly after a UTC instant."""

        zone = _load_zone(timezone)
        after_utc = _aware_utc(after)
        local_after = after_utc.astimezone(zone)
        for offset in range(8):
            local_date = local_after.date() + timedelta(days=offset)
            if local_date.weekday() not in weekdays:
                continue
            candidate = datetime.combine(local_date, local_time, tzinfo=zone)
            if candidate > local_after:
                return candidate.astimezone(UTC).replace(tzinfo=None)
        raise ValueError("weekdays must contain at least one valid weekday")

    def recent_due(
        self,
        *,
        not_before: datetime,
        through: datetime,
        local_time: time,
        weekdays: tuple[int, ...],
        timezone: str,
        limit: int,
    ) -> tuple[datetime, ...]:
        """Return at most the most recent `limit` due fire instants."""

        zone = _load_zone(timezone)
        lower = _aware_utc(not_before)
        upper = _aware_utc(through)
        if lower > upper:
            return ()

        cursor: date = upper.astimezone(zone).date()
        earliest_date = lower.astimezone(zone).date()
        recent: list[datetime] = []
        while cursor >= earliest_date and len(recent) < limit:
            if cursor.weekday() in weekdays:
                candidate = datetime.combine(cursor, local_time, tzinfo=zone).astimezone(
                    UTC
                )
                if lower <= candidate <= upper:
                    recent.append(candidate.replace(tzinfo=None))
            cursor -= timedelta(days=1)
        return tuple(sorted(recent))


class PersistentScheduler:
    """Store daily schedules and enqueue bounded catch-up tasks."""

    def __init__(
        self,
        session: Session,
        *,
        calculator: DailyScheduleCalculator | None = None,
    ) -> None:
        self._session = session
        self._calculator = calculator or DailyScheduleCalculator()

    def create_daily(
        self,
        *,
        name: str,
        job_type: str,
        local_time: time,
        weekdays: tuple[int, ...],
        payload: dict[str, Any],
        now: datetime,
        timezone: str = "Asia/Shanghai",
        queue: str = "default",
        enabled: bool = True,
        priority: int = 0,
        max_attempts: int = 3,
        catch_up_limit: int = 1,
    ) -> ScheduleSnapshot:
        """Persist a daily rule with its first future UTC fire time."""

        if not name or not job_type or not queue:
            raise ValueError("name, job_type and queue must not be empty")
        normalized_weekdays = _validate_weekdays(weekdays)
        if max_attempts <= 0 or catch_up_limit <= 0:
            raise ValueError("max_attempts and catch_up_limit must be positive")
        current = _naive_utc(now)
        next_fire = self._calculator.next_after(
            after=current,
            local_time=local_time,
            weekdays=normalized_weekdays,
            timezone=timezone,
        )
        row = RunnerScheduleRow(
            id=str(uuid4()),
            name=name,
            job_type=job_type,
            queue=queue,
            payload=dict(payload),
            timezone=timezone,
            local_time=local_time,
            weekdays=list(normalized_weekdays),
            enabled=enabled,
            priority=priority,
            max_attempts=max_attempts,
            catch_up_limit=catch_up_limit,
            next_fire_at=next_fire,
            last_enqueued_for=None,
            created_at=current,
            updated_at=current,
        )
        self._session.add(row)
        self._session.flush()
        return _snapshot(row)

    def ensure_daily(
        self,
        *,
        name: str,
        job_type: str,
        local_time: time,
        weekdays: tuple[int, ...],
        payload: dict[str, Any],
        now: datetime,
        timezone: str = "Asia/Shanghai",
        queue: str = "default",
        enabled: bool = True,
        priority: int = 0,
        max_attempts: int = 3,
        catch_up_limit: int = 1,
    ) -> ScheduleSnapshot:
        """Create one daily rule or return its identical existing definition."""

        row = self._session.scalar(
            select(RunnerScheduleRow).where(RunnerScheduleRow.name == name)
        )
        if row is None:
            return self.create_daily(
                name=name,
                job_type=job_type,
                local_time=local_time,
                weekdays=weekdays,
                payload=payload,
                now=now,
                timezone=timezone,
                queue=queue,
                enabled=enabled,
                priority=priority,
                max_attempts=max_attempts,
                catch_up_limit=catch_up_limit,
            )
        expected = {
            "catch_up_limit": catch_up_limit,
            "enabled": enabled,
            "job_type": job_type,
            "local_time": local_time,
            "max_attempts": max_attempts,
            "payload": payload,
            "priority": priority,
            "queue": queue,
            "timezone": timezone,
            "weekdays": list(_validate_weekdays(weekdays)),
        }
        actual = {
            "catch_up_limit": row.catch_up_limit,
            "enabled": row.enabled,
            "job_type": row.job_type,
            "local_time": row.local_time,
            "max_attempts": row.max_attempts,
            "payload": row.payload,
            "priority": row.priority,
            "queue": row.queue,
            "timezone": row.timezone,
            "weekdays": row.weekdays,
        }
        if actual != expected:
            raise ScheduleConflict(
                f"schedule {name!r} already exists with different configuration"
            )
        return _snapshot(row)

    def run_due(
        self,
        *,
        now: datetime,
        max_schedules: int = 100,
    ) -> ScheduleTick:
        """Lock due schedules, emit bounded jobs and advance past `now`."""

        if max_schedules <= 0:
            raise ValueError("max_schedules must be positive")
        current = _naive_utc(now)
        statement = (
            select(RunnerScheduleRow)
            .where(
                RunnerScheduleRow.enabled.is_(True),
                RunnerScheduleRow.next_fire_at <= current,
            )
            .order_by(RunnerScheduleRow.next_fire_at, RunnerScheduleRow.id)
            .limit(max_schedules)
            .with_for_update(skip_locked=True)
        )
        rows = tuple(self._session.scalars(statement))
        jobs: list[JobSnapshot] = []
        repository = JobRepository(self._session)
        for row in rows:
            weekdays = tuple(row.weekdays)
            fires = self._calculator.recent_due(
                not_before=row.next_fire_at,
                through=current,
                local_time=row.local_time,
                weekdays=weekdays,
                timezone=row.timezone,
                limit=row.catch_up_limit,
            )
            for fire in fires:
                fire_label = f"{fire.isoformat()}Z"
                jobs.append(
                    repository.enqueue(
                        job_type=row.job_type,
                        idempotency_key=f"schedule:{row.id}:{fire_label}",
                        payload={
                            "input": dict(row.payload),
                            "schedule": {
                                "id": row.id,
                                "planned_fire_at": fire_label,
                            },
                        },
                        queue=row.queue,
                        priority=row.priority,
                        max_attempts=row.max_attempts,
                        now=current,
                    )
                )
            if fires:
                row.last_enqueued_for = fires[-1]
            row.next_fire_at = self._calculator.next_after(
                after=current,
                local_time=row.local_time,
                weekdays=weekdays,
                timezone=row.timezone,
            )
            row.updated_at = current
        self._session.flush()
        return ScheduleTick(enqueued=tuple(jobs))

    def set_enabled(
        self,
        schedule_id: str,
        *,
        enabled: bool,
        now: datetime,
    ) -> ScheduleSnapshot:
        """Enable or disable one persistent rule."""

        row = self._get_row(schedule_id)
        row.enabled = enabled
        row.updated_at = _naive_utc(now)
        self._session.flush()
        return _snapshot(row)

    def get(self, schedule_id: str) -> ScheduleSnapshot:
        """Return an immutable schedule snapshot."""

        return _snapshot(self._get_row(schedule_id))

    def _get_row(self, schedule_id: str) -> RunnerScheduleRow:
        row = self._session.get(RunnerScheduleRow, schedule_id)
        if row is None:
            raise ScheduleNotFound(schedule_id)
        return row


def _snapshot(row: RunnerScheduleRow) -> ScheduleSnapshot:
    return ScheduleSnapshot(
        id=row.id,
        name=row.name,
        job_type=row.job_type,
        queue=row.queue,
        payload=dict(row.payload),
        timezone=row.timezone,
        local_time=row.local_time,
        weekdays=tuple(row.weekdays),
        enabled=row.enabled,
        priority=row.priority,
        max_attempts=row.max_attempts,
        catch_up_limit=row.catch_up_limit,
        next_fire_at=row.next_fire_at,
        last_enqueued_for=row.last_enqueued_for,
    )


def _validate_weekdays(weekdays: tuple[int, ...]) -> tuple[int, ...]:
    normalized = tuple(sorted(set(weekdays)))
    if not normalized or any(day < 0 or day > 6 for day in normalized):
        raise ValueError("weekdays must contain integers from 0 through 6")
    return normalized


def _load_zone(name: str) -> ZoneInfo:
    try:
        return ZoneInfo(name)
    except ZoneInfoNotFoundError:
        raise ValueError(f"unknown timezone: {name}") from None


def _aware_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def _naive_utc(value: datetime) -> datetime:
    return _aware_utc(value).replace(tzinfo=None)
