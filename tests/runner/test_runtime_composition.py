from asharelens.config import RuntimeSettings
from asharelens.runtime import build_executor_registry
from asharelens.storage.database import (
    Base,
    create_database_engine,
    create_session_factory,
)


def test_runtime_registers_daily_and_notification_executors() -> None:
    engine = create_database_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)

    registry = build_executor_registry(
        session_factory=create_session_factory(engine),
        settings=RuntimeSettings(),
    )

    assert callable(registry.resolve("daily.pipeline"))
    assert callable(registry.resolve("notification.deliver"))
