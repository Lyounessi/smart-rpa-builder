"""Atomic local spending reservations. Unknown usage is never treated as free."""
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation, ROUND_CEILING

from django.conf import settings
from django.db import IntegrityError, OperationalError, transaction
from django.utils import timezone
from .client import MuseError
from .models import MuseBudget, MuseRequest

# Standard Muse Spark 1.3 context limit; requests have no hosted tools/loops.
CONTEXT_WINDOW = 1_048_576
MILLION = Decimal(1_000_000)
UNIT = Decimal('0.00000001')
OPERATIONS = {'connection_check', 'context_review', 'clarification', 'generation', 'repair'}


def money(value):
    return value.quantize(UNIT, rounding=ROUND_CEILING)


def decimal_setting(name, maximum):
    try:
        value = Decimal(str(getattr(settings, name)))
        if not value.is_finite() or value < 0 or value > maximum:
            raise InvalidOperation()
        return value
    except (InvalidOperation, ValueError, TypeError):
        raise MuseError('invalid_budget_configuration', f'Invalid {name} configuration.') from None


@dataclass(frozen=True)
class SpendingPolicy:
    limit: Decimal
    input_rate: Decimal
    cached_rate: Decimal
    output_rate: Decimal
    output_cap: int

    @classmethod
    def load(cls, model):
        if model != settings.META_PRICE_MODEL or model != 'muse-spark-1.3':
            raise MuseError('unpriced_model', 'No verified context limit and pricing profile is configured for this model.')
        try:
            cap = int(settings.MUSE_MAX_OUTPUT_TOKENS)
            if not 16 <= cap <= 16384:
                raise ValueError()
        except (TypeError, ValueError):
            raise MuseError('invalid_budget_configuration', 'MUSE_MAX_OUTPUT_TOKENS must be between 16 and 16384.') from None
        policy = cls(decimal_setting('MUSE_BUDGET_USD', Decimal(150)),
            decimal_setting('META_INPUT_USD_PER_MILLION', Decimal(1000)),
            decimal_setting('META_CACHED_USD_PER_MILLION', Decimal(1000)),
            decimal_setting('META_OUTPUT_USD_PER_MILLION', Decimal(1000)), cap)
        if policy.input_rate <= 0 or policy.output_rate <= 0 or policy.cached_rate > policy.input_rate:
            raise MuseError('invalid_budget_configuration', 'Configure positive input/output prices and a cached rate no greater than input.')
        return policy

    def pricing(self):
        return {'input':str(self.input_rate), 'cached':str(self.cached_rate), 'output':str(self.output_rate),
                'unit':'USD per million tokens', 'context_window':CONTEXT_WINDOW}

    def reservation(self, output_tokens):
        # Reserve a complete model-window input at uncached price plus capped output.
        # Deliberately over-reserves; image tokenization is not inferred from bytes.
        return money((CONTEXT_WINDOW * self.input_rate + output_tokens * self.output_rate) / MILLION)


def reserve(operation, model, max_output_tokens, snapshot=None, build_operation=None):
    policy = SpendingPolicy.load(model)
    if operation not in OPERATIONS or not isinstance(max_output_tokens, int) or isinstance(max_output_tokens, bool) or not 16 <= max_output_tokens <= policy.output_cap:
        raise MuseError('request_limit', 'Unsupported operation or output-token limit.')
    amount = policy.reservation(max_output_tokens)
    try:
        with transaction.atomic():
            budget, _ = MuseBudget.objects.get_or_create(pk=1)
            budget = MuseBudget.objects.select_for_update().get(pk=budget.pk)
            if MuseRequest.objects.filter(active_slot='local').exists():
                raise MuseError('operation_active', 'Another Muse operation is active. Wait for it to finish.')
            # Conditional write provides an atomic guard on SQLite too.
            updated = MuseBudget.objects.filter(pk=1, committed_usd=budget.committed_usd, committed_usd__lte=policy.limit - amount).update(
                committed_usd=budget.committed_usd + amount)
            if updated != 1:
                raise MuseError('budget_exhausted', 'The local spending limit cannot cover this conservative request reservation.')
            return MuseRequest.objects.create(snapshot=snapshot, operation=operation, model=model,
                max_output_tokens=max_output_tokens, reserved_usd=amount, accounted_usd=amount, pricing=policy.pricing(), build_operation=build_operation)
    except (IntegrityError, OperationalError):
        raise MuseError('operation_active', 'Muse reservation is busy. No request was sent; try again later.') from None


@transaction.atomic
def settle(request_id, *, outcome, duration, input_tokens=None, output_tokens=None, cached_tokens=None, error_code='', rejected=False):
    budget = MuseBudget.objects.select_for_update().get(pk=1)
    request = MuseRequest.objects.select_for_update().get(pk=request_id)
    if request.active_slot is None:
        raise MuseError('request_finalized', 'This Muse request was already finalized.')
    valid_count = lambda value: isinstance(value, int) and not isinstance(value, bool) and value >= 0
    known = valid_count(input_tokens) and valid_count(output_tokens) and (cached_tokens is None or valid_count(cached_tokens) and cached_tokens <= input_tokens)
    estimate = None
    if rejected:
        accounted = Decimal(0)
    elif known:
        rates = request.pricing
        cached = cached_tokens or 0
        estimate = money(((input_tokens - cached) * Decimal(rates['input']) + cached * Decimal(rates['cached']) +
                         output_tokens * Decimal(rates['output'])) / MILLION)
        accounted = estimate
    else:
        accounted = request.reserved_usd
    budget.committed_usd += accounted - request.accounted_usd
    budget.save(update_fields=['committed_usd'])
    request.finished_at, request.duration_seconds = timezone.now(), duration
    request.outcome, request.error_code, request.active_slot = outcome, error_code, None
    request.input_tokens, request.output_tokens, request.cached_tokens = input_tokens, output_tokens, cached_tokens
    request.usage_known, request.estimated_cost_usd, request.accounted_usd = known, estimate, accounted
    request.save()
    return request


def close_abandoned(request_id):
    # Caller must first establish that the owning worker has stopped. Never release
    # the monetary reservation just because a worker/request disappeared.
    return settle(request_id, outcome='uncertain', duration=None, error_code='abandoned_worker')
