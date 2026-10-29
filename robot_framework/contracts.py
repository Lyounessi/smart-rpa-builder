from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any


class Outcome(StrEnum):
    OK = 'OK'
    NOK = 'NOK'
    ERROR = 'ERROR'


class RunState(StrEnum):
    QUEUED = 'queued'
    RUNNING = 'running'
    COMPLETED = 'completed'
    FAILED = 'failed'
    CANCELLED = 'cancelled'


@dataclass(frozen=True)
class RunOptions:
    record_screen: bool = False
    stop_on_nok: bool = False
    stop_on_error: bool = True
    action_timeout_ms: int = 10000
    email_timeout_seconds: float = 15

    def __post_init__(self):
        if not 1 <= self.action_timeout_ms <= 120000:
            raise ValueError('Action timeout must be between 1 and 120000 ms.')
        if not 0 < self.email_timeout_seconds <= 120:
            raise ValueError('Email timeout must be greater than zero and at most 120 seconds.')


@dataclass(frozen=True)
class InputRow:
    reference: str
    values: dict[str, Any]


@dataclass
class RowResult:
    reference: str
    status: Outcome
    message: str = ''
    failed_step: str | None = None
    evidence: list[str] = field(default_factory=list)
    business_completed: bool = False
    outputs: dict[str, str] = field(default_factory=dict)


@dataclass
class RunResult:
    state: RunState = RunState.QUEUED
    rows: list[RowResult] = field(default_factory=list)
    message: str = ''
    cleanup_errors: list[str] = field(default_factory=list)
    artifacts: list[str] = field(default_factory=list)
    unprocessed: list[str] = field(default_factory=list)
    primary_error: BaseException | None = field(default=None, repr=False)


class BusinessRejection(Exception):
    """Use a fixed diagnostic code, never input values or secrets."""


class ExecutionCancelled(Exception):
    pass


class TechnicalError(Exception):
    pass


@dataclass(frozen=True)
class Progress:
    kind: str
    row: str | None = None
    step: str | None = None
    result: RowResult | None = None
    summary: RunResult | None = None
    action_status: str | None = None
