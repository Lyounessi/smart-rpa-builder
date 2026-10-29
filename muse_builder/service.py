"""Application API: fixed context, spending gate and ledger around one request."""
from dataclasses import dataclass, field
from time import perf_counter

from .budget import reserve, settle
from .client import (CHECK_MAX_OUTPUT_TOKENS, ConnectionCheck, MetaClient,
                     MetaConfiguration, MuseError, token_count)
from .context import request_context, require_current

REJECTED_CODES = {'authentication', 'permission', 'billing', 'model_not_found', 'rate_limited', 'invalid_request'}


@dataclass(frozen=True)
class MuseResponse:
    request_id: str
    model: str
    text: str = field(repr=False)
    duration_seconds: float
    input_tokens: int | None
    output_tokens: int | None
    cached_tokens: int | None


class MuseService:
    def __init__(self, *, client=None):
        self.client = client if client is not None else MetaClient()

    def check_connection(self):
        result = self._perform('connection_check', snapshot=None, max_output_tokens=CHECK_MAX_OUTPUT_TOKENS)
        return ConnectionCheck(model=result.model, duration_seconds=result.duration_seconds, input_tokens=result.input_tokens,
            output_tokens=result.output_tokens, cached_tokens=result.cached_tokens, request_id=result.request_id)

    def review_context(self, snapshot, *, max_output_tokens=1024):
        return self._perform('context_review', snapshot=snapshot, max_output_tokens=max_output_tokens)

    def _perform(self, operation, *, snapshot, max_output_tokens):
        configuration = MetaConfiguration.from_settings()
        instructions = None
        if snapshot is None:
            if operation != 'connection_check':
                raise MuseError('invalid_operation', 'This operation requires a project snapshot.')
            input = 'Reply exactly OK.'
        else:
            require_current(snapshot)
            instructions, input = request_context(snapshot)
        request = reserve(operation, configuration.model, max_output_tokens, snapshot)
        started = perf_counter()
        sent = False
        try:
            if snapshot is not None:
                require_current(snapshot)
            sent = True
            response = self.client.request(input=input, instructions=instructions,
                max_output_tokens=max_output_tokens, configuration=configuration)
        except MuseError as error:
            settle(request.pk, outcome='rejected' if not sent or error.code in REJECTED_CODES else 'uncertain',
                duration=perf_counter() - started, error_code=error.code, rejected=not sent or error.code in REJECTED_CODES)
            raise
        except BaseException as error:
            settle(request.pk, outcome='uncertain', duration=perf_counter() - started, error_code='interrupted')
            if isinstance(error, (KeyboardInterrupt, SystemExit)):
                raise
            raise MuseError('provider', 'Muse request did not finish. Its conservative reservation is retained.') from None
        usage = getattr(response, 'usage', None)
        input_tokens = token_count(getattr(usage, 'input_tokens', None))
        output_tokens = token_count(getattr(usage, 'output_tokens', None))
        cached_tokens = token_count(getattr(getattr(usage, 'input_tokens_details', None), 'cached_tokens', None))
        try:
            text = response.output_text
            valid = response.status == 'completed' and isinstance(text, str) and bool(text.strip())
        except Exception:
            text, valid = '', False
        error = None
        if not valid or (operation == 'connection_check' and text.strip() != 'OK'):
            error = MuseError('unexpected_response', 'Muse returned an incomplete or unexpected response. Usage was recorded; no retry was made.')
        if snapshot is not None:
            try:
                require_current(snapshot)
            except MuseError:
                error = MuseError('stale_specification', 'The project changed during the request. Response discarded; prepare a new snapshot.')
        elapsed = perf_counter() - started
        settle(request.pk, outcome='stale' if error and error.code == 'stale_specification' else 'failed' if error else 'success',
            duration=elapsed, input_tokens=input_tokens, output_tokens=output_tokens, cached_tokens=cached_tokens,
            error_code=error.code if error else '')
        if error:
            raise error
        return MuseResponse(str(request.pk), configuration.model, text, elapsed, input_tokens, output_tokens, cached_tokens)
