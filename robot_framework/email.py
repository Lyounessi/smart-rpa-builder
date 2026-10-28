"""Plain-text email contract. Provider implementations live outside the core."""
from dataclasses import dataclass, field
from email.headerregistry import Address
from enum import StrEnum
import re
from typing import Protocol

from .contracts import ExecutionCancelled, TechnicalError

TOKEN = re.compile(r'{{\s*([a-z][a-z0-9_]*)\s*}}')
ACCOUNT = re.compile(r'[a-zA-Z][a-zA-Z0-9_-]{0,99}')


def referenced_fields(template):
    if not isinstance(template, str):
        raise ValueError('Email templates must be plain text.')
    fields = set(TOKEN.findall(template))
    remainder = TOKEN.sub('', template)
    if '{{' in remainder or '}}' in remainder or '{%' in remainder or '{#' in remainder:
        raise ValueError('Only simple {{input_key}} substitution is supported.')
    return fields


def substitute(template, inputs):
    fields = referenced_fields(template)
    if not fields.issubset(inputs):
        raise ValueError('Email references an unavailable input field.')
    # One pass only: inserted values are never interpreted as templates.
    return TOKEN.sub(lambda match: str(inputs[match.group(1)]), template)


class EmailStatus(StrEnum):
    ACCEPTED = 'accepted'
    SIMULATED = 'simulated'
    FAILED = 'failed'
    UNCERTAIN = 'uncertain'


class EmailFailure(TechnicalError):
    def __init__(self, status=EmailStatus.UNCERTAIN):
        self.status = EmailStatus(status)
        if self.status not in {EmailStatus.FAILED, EmailStatus.UNCERTAIN}:
            raise ValueError('Invalid email failure status.')
        super().__init__('Email failed.' if self.status == EmailStatus.FAILED else 'Email delivery is uncertain.')


@dataclass(frozen=True)
class EmailMessage:
    account: str
    to: tuple[str, ...] = field(repr=False)
    subject: str = field(repr=False)
    body: str = field(repr=False)


class EmailAdapter(Protocol):
    def send(self, message: EmailMessage, *, timeout_seconds: float) -> EmailStatus:
        """Resolve account/secret references internally; enforce a bounded I/O deadline.

        ACCEPTED means provider acceptance, never proof of inbox delivery. Never retry
        internally. Report UNCERTAIN if submission might have succeeded.
        """
        ...


class UnconfiguredEmail:
    def send(self, message, *, timeout_seconds):
        raise EmailFailure(EmailStatus.FAILED)


@dataclass(frozen=True)
class EmailStep:
    step_id: str
    account: str
    to: str = field(repr=False)
    subject: str = field(repr=False)
    body: str = field(repr=False)

    def validate(self, input_fields):
        if not re.fullmatch(r'[a-zA-Z0-9_-]{1,200}', self.step_id) or not ACCOUNT.fullmatch(self.account):
            raise ValueError('Invalid email step or account reference.')
        fields = set().union(*(referenced_fields(value) for value in (self.to, self.subject, self.body)))
        if not fields.issubset(input_fields):
            raise ValueError('Email references an undefined workflow input.')

    def render(self, inputs):
        self.validate(inputs.keys())
        return make_message(self.account, *(substitute(value, inputs) for value in (self.to, self.subject, self.body)))


def make_message(account, to, subject, body):
    if not isinstance(account, str) or not ACCOUNT.fullmatch(account):
        raise ValueError('Use an email account reference.')
    if not isinstance(subject, str) or not isinstance(body, str) or '\r' in subject or '\n' in subject:
        raise ValueError('Use a plain-text body and a single-line subject.')
    recipients = to.split(',') if isinstance(to, str) else to
    if not isinstance(recipients, (list, tuple)) or not 1 <= len(recipients) <= 100:
        raise ValueError('Provide 1 to 100 plain recipient addresses.')
    addresses = []
    for value in recipients:
        try:
            if not isinstance(value, str) or '\r' in value or '\n' in value:
                raise ValueError()
            value = value.strip()
            parsed = Address(addr_spec=value)
            if not parsed.username or not parsed.domain or parsed.addr_spec != value:
                raise ValueError()
        except Exception:
            raise ValueError('Invalid email recipient address.') from None
        addresses.append(value)
    return EmailMessage(account, tuple(addresses), subject, body)


class EmailService:
    def __init__(self, ctx, adapter, timeout_seconds):
        self.ctx, self.adapter, self.timeout_seconds = ctx, adapter, timeout_seconds

    def send_step(self, specification, inputs):
        message = specification.render(inputs)
        with self.ctx.step(specification.step_id):
            return self.send(account=message.account, to=message.to, subject=message.subject, body=message.body)

    def send(self, *, account, to, subject, body):
        self.ctx.checkpoint()
        if self.ctx.row is None or self.ctx.active_step is None:
            raise ValueError('Send email inside a named row step.')
        self.ctx.emit('email_started', step=self.ctx.active_step, action_status='started')
        try:
            message = make_message(account, to, subject, body)
        except ValueError:
            self.ctx.emit('email_finished', step=self.ctx.active_step, action_status=EmailStatus.FAILED)
            raise EmailFailure(EmailStatus.FAILED) from None
        try:
            status = EmailStatus(self.adapter.send(message, timeout_seconds=self.timeout_seconds))
        except EmailFailure as error:
            status = error.status
        except BaseException as error:
            self.ctx.emit('email_finished', step=self.ctx.active_step, action_status=EmailStatus.UNCERTAIN)
            if isinstance(error, (ExecutionCancelled, KeyboardInterrupt, SystemExit)):
                raise
            raise EmailFailure(EmailStatus.UNCERTAIN) from None
        self.ctx.emit('email_finished', step=self.ctx.active_step, action_status=status)
        if status in {EmailStatus.FAILED, EmailStatus.UNCERTAIN}:
            raise EmailFailure(status)
        return status
