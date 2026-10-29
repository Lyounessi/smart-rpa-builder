"""Small Meta Model API boundary. Never return SDK errors or credentials to callers."""
from dataclasses import dataclass, field
import math
import re
from time import perf_counter

import httpx
from django.conf import settings
from openai import (APIConnectionError, APIError, APIStatusError, APITimeoutError,
                    AuthenticationError, OpenAI, PermissionDeniedError, RateLimitError)

META_BASE_URL = 'https://api.meta.ai/v1'
CHECK_MAX_OUTPUT_TOKENS = 128


class MuseError(Exception):
    def __init__(self, code, message):
        self.code, self.message = code, message
        super().__init__(message)


@dataclass(frozen=True)
class MetaConfiguration:
    api_key: str = field(repr=False)
    model: str = 'muse-spark-1.3'
    timeout_seconds: float = 45

    @classmethod
    def from_settings(cls):
        key = settings.MUSE_APIKEY
        if not isinstance(key, str) or not key.strip():
            raise MuseError('missing_key', 'Muse is not configured. Set MUSE_APIKEY in your local .env or process environment.')
        if any(character.isspace() for character in key):
            raise MuseError('invalid_configuration', 'MUSE_APIKEY must not contain whitespace. Check the local configuration.')
        model = settings.META_MODEL
        if not isinstance(model, str) or not re.fullmatch(r'[a-zA-Z0-9][a-zA-Z0-9_.-]{0,99}', model):
            raise MuseError('invalid_configuration', 'META_MODEL must contain a valid model identifier.')
        try:
            timeout = float(settings.META_TIMEOUT_SECONDS)
            if not math.isfinite(timeout) or not 1 <= timeout <= 120:
                raise ValueError()
        except (TypeError, ValueError):
            raise MuseError('invalid_configuration', 'META_TIMEOUT_SECONDS must be between 1 and 120.') from None
        return cls(api_key=key, model=model, timeout_seconds=timeout)


@dataclass(frozen=True)
class ConnectionCheck:
    model: str
    duration_seconds: float
    input_tokens: int | None
    output_tokens: int | None
    cached_tokens: int | None


def token_count(value):
    return value if isinstance(value, int) and not isinstance(value, bool) and value >= 0 else None


class MetaClient:
    def __init__(self, *, client_factory=None):
        self.client_factory = client_factory if client_factory is not None else OpenAI

    def check_connection(self):
        configuration = MetaConfiguration.from_settings()
        timeout = httpx.Timeout(configuration.timeout_seconds, connect=min(10, configuration.timeout_seconds),
            write=min(10, configuration.timeout_seconds), pool=min(5, configuration.timeout_seconds))
        started = perf_counter()
        # Never follow a redirect to a caller-controlled endpoint. No base-URL override.
        try:
            with httpx.Client(timeout=timeout, follow_redirects=False) as transport:
                with self.client_factory(api_key=configuration.api_key, base_url=META_BASE_URL,
                        max_retries=0, timeout=timeout, http_client=transport) as client:
                    response = client.responses.create(
                        model=configuration.model, input='Reply exactly OK.',
                        max_output_tokens=CHECK_MAX_OUTPUT_TOKENS,
                        reasoning={'effort':'minimal'}, store=False, tools=[],
                    )
        except AuthenticationError:
            raise MuseError('authentication', 'Meta rejected the API key. Check MUSE_APIKEY and account access.') from None
        except PermissionDeniedError:
            raise MuseError('permission', 'Meta denied access. Check model and account permissions.') from None
        except RateLimitError:
            raise MuseError('rate_limited', 'Meta rate limit reached. No automatic retry was made; try again later.') from None
        except APITimeoutError:
            raise MuseError('timeout', 'Meta request timed out. Delivery or billing may be uncertain; no automatic retry was made.') from None
        except APIConnectionError:
            raise MuseError('connection', 'Could not reach Meta. Check network connectivity; no automatic retry was made.') from None
        except APIStatusError as error:
            code, message = {
                400: ('invalid_request', 'Meta rejected the connection-check parameters. Check model compatibility.'),
                402: ('billing', 'Meta reports a billing or credit issue. Check the provider dashboard.'),
                404: ('model_not_found', 'Meta model or API endpoint was not found. Check META_MODEL and model access.'),
            }.get(error.status_code, ('provider', 'Meta returned a provider error. No automatic retry was made.'))
            raise MuseError(code, message) from None
        except APIError:
            raise MuseError('provider', 'Meta returned an unreadable API response. No automatic retry was made.') from None
        except Exception:
            raise MuseError('client', 'The Meta connection check could not complete. Check the local SDK and configuration.') from None
        try:
            confirmed = response.status == 'completed' and response.output_text.strip() == 'OK'
            usage = response.usage
            details = getattr(usage, 'input_tokens_details', None)
        except Exception:
            confirmed, usage, details = False, None, None
        if not confirmed:
            raise MuseError('unexpected_response', 'Meta responded, but the bounded connection check did not return the expected confirmation. No retry was made.')
        return ConnectionCheck(model=configuration.model, duration_seconds=perf_counter() - started,
            input_tokens=token_count(getattr(usage, 'input_tokens', None)),
            output_tokens=token_count(getattr(usage, 'output_tokens', None)),
            cached_tokens=token_count(getattr(details, 'cached_tokens', None)))
