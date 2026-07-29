from sqlalchemy import Index, UniqueConstraint
from sqlalchemy.dialects import mysql
from sqlalchemy.schema import CreateIndex, CreateTable

from asharelens.storage.models import RunnerJobRow


def test_runner_job_schema_contains_durable_state_fields() -> None:
    columns = RunnerJobRow.__table__.columns

    assert {
        "id",
        "queue",
        "job_type",
        "idempotency_key",
        "status",
        "priority",
        "available_at",
        "attempt",
        "max_attempts",
        "payload",
        "result",
        "leased_by",
        "lease_expires_at",
        "heartbeat_at",
        "last_error",
        "created_at",
        "updated_at",
        "finished_at",
    } <= set(columns.keys())
    assert columns["payload"].nullable is False
    assert columns["result"].nullable is True
    assert columns["lease_expires_at"].nullable is True


def test_runner_job_schema_has_idempotency_and_claim_indexes() -> None:
    constraints = {
        constraint.name: constraint
        for constraint in RunnerJobRow.__table__.constraints
        if constraint.name is not None
    }
    indexes = {index.name: index for index in RunnerJobRow.__table__.indexes}

    assert isinstance(constraints["uq_runner_job_idempotency"], UniqueConstraint)
    assert [column.name for column in constraints["uq_runner_job_idempotency"].columns] == [
        "job_type",
        "idempotency_key",
    ]
    assert isinstance(indexes["ix_runner_job_claim"], Index)
    assert [column.name for column in indexes["ix_runner_job_claim"].columns] == [
        "queue",
        "status",
        "available_at",
        "priority",
        "created_at",
    ]


def test_runner_job_mysql_ddl_uses_innodb_utf8mb4_and_claim_index() -> None:
    table_ddl = str(
        CreateTable(RunnerJobRow.__table__).compile(dialect=mysql.dialect())
    ).upper()
    claim_index = next(
        index
        for index in RunnerJobRow.__table__.indexes
        if index.name == "ix_runner_job_claim"
    )
    index_ddl = str(CreateIndex(claim_index).compile(dialect=mysql.dialect())).upper()

    assert "ENGINE=INNODB" in table_ddl
    assert "CHARSET=UTF8MB4" in table_ddl
    assert "CREATE INDEX IX_RUNNER_JOB_CLAIM" in index_ddl
