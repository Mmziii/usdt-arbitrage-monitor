"""Shared outbound HTTP: per-exchange request budgets, backoff, diagnostics and clock checks.

Nothing here touches an account: public market data only. Every request is recorded so the
Persian diagnostics page can explain *why* a fetch failed instead of a generic error.
"""
import asyncio
import email.utils
import json
import math
import time
from collections import defaultdict, deque
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from typing import Any, Callable, Optional

import httpx

PREVIEW_CHARS = 500

# Documented polite-robot style: `TraderBot/<name>-<version>`. Nobitex asks for this shape
# and its CDN may reject library defaults such as `python-httpx/x.y`.
DEFAULT_AGENT = 'TraderBot/usdt-monitor-3.0 (+read-only; local desktop monitor)'

# Stable reason codes shared by the adapters, the diagnostics page and the tests.
REASONS = (
    'ok', 'http_429', 'http_4xx', 'http_5xx', 'timeout', 'network', 'not_json',
    'shape', 'missing_field', 'unexpected_unit', 'stale_timestamp',
    'timestamp_unreliable', 'empty_book', 'crossed_book', 'unsuccessful_status',
    'symbol_missing', 'blocked', 'budget', 'unknown',
)


class ValidationError(ValueError):
    """A response was received but violates a documented rule.

    ``code`` belongs to :data:`REASONS`; ``detail`` is the raw (English) technical detail,
    which is never shown to the user on its own.
    """

    def __init__(self, code: str = 'shape', detail: str = ''):
        super().__init__(detail or code)
        self.code = code if code in REASONS else 'shape'
        self.detail = detail


class ExchangeError(ValueError):
    """Raised by callers that need an exception instead of a result object."""

    def __init__(self, result: 'HttpResult'):
        super().__init__(result.detail or result.reason)
        self.result = result


class BudgetExhausted(RuntimeError):
    """The per-exchange request budget would have blocked for too long."""


def preview_of(body: bytes, limit: int = PREVIEW_CHARS) -> str:
    """First ``limit`` characters of the raw body, with invalid bytes replaced."""
    if not body:
        return ''
    return body[: limit * 4].decode('utf-8', 'replace')[:limit]


def parse_http_date(value: Optional[str]) -> Optional[float]:
    if not value:
        return None
    try:
        parsed = email.utils.parsedate_to_datetime(value)
    except (TypeError, ValueError):
        return None
    if parsed is None:
        return None
    try:
        return parsed.timestamp()
    except (OverflowError, ValueError):
        return None


class Budget:
    """Rolling-window request budget with concurrency cap and exponential backoff.

    The clock and sleep are injectable so the tests do not wait in real time.
    """

    def __init__(self, name: str, limit: int = 60, window: float = 60.0, concurrency: int = 3,
                 base_backoff: float = 2.0, max_backoff: float = 60.0,
                 clock=time.monotonic, sleep=asyncio.sleep):
        self.name = name
        self.limit = max(1, int(limit))
        self.window = float(window)
        self.concurrency = max(1, int(concurrency))
        self.base_backoff = base_backoff
        self.max_backoff = max_backoff
        self._clock = clock
        self._sleep = sleep
        self._sem = asyncio.Semaphore(self.concurrency)
        self.stamps: deque = deque()
        self.failures = 0
        self.blocked_until = 0.0
        self.total = 0
        self.failed = 0
        self.in_flight = 0

    def _prune(self) -> None:
        now = self._clock()
        while self.stamps and self.stamps[0] <= now - self.window:
            self.stamps.popleft()

    def used(self) -> int:
        self._prune()
        return len(self.stamps)

    @asynccontextmanager
    async def slot(self, max_wait: float = 30.0):
        """Wait for backoff, concurrency and window capacity, then reserve one request."""
        waited = 0.0
        while True:
            wait = max(0.0, self.blocked_until - self._clock())
            self._prune()
            if len(self.stamps) >= self.limit:
                wait = max(wait, self.stamps[0] + self.window - self._clock())
            if wait <= 0:
                break
            waited += wait
            if waited > max_wait:
                raise BudgetExhausted(self.name)
            await self._sleep(wait)
        async with self._sem:
            self._prune()
            self.stamps.append(self._clock())
            self.total += 1
            self.in_flight += 1
            try:
                yield
            finally:
                self.in_flight -= 1

    def success(self) -> None:
        self.failures = 0

    def failure(self, retryable: bool = True) -> float:
        self.failed += 1
        self.failures += 1
        if not retryable:
            return 0.0
        delay = min(self.max_backoff, self.base_backoff ** min(self.failures, 10))
        self.blocked_until = max(self.blocked_until, self._clock() + delay)
        return delay

    def stats(self) -> dict:
        self._prune()
        now = self._clock()
        return {'name': self.name, 'limit': self.limit, 'window_seconds': self.window,
                'used': len(self.stamps), 'remaining': max(0, self.limit - len(self.stamps)),
                'concurrency': self.concurrency, 'in_flight': self.in_flight,
                'total': self.total, 'failed': self.failed, 'consecutive_failures': self.failures,
                'backoff_seconds': round(max(0.0, self.blocked_until - now), 2),
                'backing_off': self.blocked_until > now}


# Process-wide budget registry: the classic dashboard and the new scanner share the same
# limits, so two loops can never add up beyond an exchange's documented allowance.
_BUDGETS: dict[str, Budget] = {}
BUDGET_DEFAULTS = {
    'wallex': dict(limit=60, concurrency=3),
    'nobitex': dict(limit=120, concurrency=4),
    'nobitex:stats': dict(limit=15, concurrency=2),
    'wallex:stats': dict(limit=60, concurrency=3),
    'bitunix': dict(limit=60, concurrency=3),
}


def budget(name: str, **overrides) -> Budget:
    if name not in _BUDGETS:
        options = {**BUDGET_DEFAULTS.get(name, dict(limit=60, concurrency=3)), **overrides}
        _BUDGETS[name] = Budget(name, **options)
    elif overrides:
        for key, value in overrides.items():
            if key in ('limit', 'concurrency', 'window'):
                setattr(_BUDGETS[name], key, value)
    return _BUDGETS[name]


def budgets() -> dict:
    return dict(_BUDGETS)


def reset_budgets() -> None:
    """Test helper: forget every process-wide budget."""
    _BUDGETS.clear()


@dataclass
class Endpoint:
    """A documented public endpoint. Adapters list them primary-first."""
    id: str
    url: str
    kind: str = 'json'          # 'json' | 'depth' | 'best'
    quality: str = 'depth'      # 'depth' | 'best_only' | 'last_price'
    note: str = ''


@dataclass
class Attempt:
    exchange: str
    endpoint: str
    url: str
    at: float
    status: Optional[int]
    elapsed_ms: float
    json_ok: bool
    reason: str
    detail: str
    preview: str
    skew: Optional[float]
    attempt: int
    quality: str = 'depth'

    def public(self) -> dict:
        return {'exchange': self.exchange, 'endpoint': self.endpoint, 'url': self.url,
                'at': self.at, 'status': self.status, 'elapsed_ms': round(self.elapsed_ms, 1),
                'json_ok': self.json_ok, 'reason': self.reason, 'detail': self.detail,
                'preview': self.preview, 'skew_seconds': None if self.skew is None else round(self.skew, 1),
                'attempt': self.attempt, 'quality': self.quality}


@dataclass
class HttpResult:
    ok: bool
    data: Any = None
    reason: str = 'ok'
    detail: str = ''
    status: Optional[int] = None
    elapsed_ms: float = 0.0
    url: str = ''
    endpoint: str = ''
    preview: str = ''
    attempts: int = 1
    skew: Optional[float] = None
    quality: str = 'depth'

    def raise_for_status(self) -> Any:
        if not self.ok:
            raise ExchangeError(self)
        return self.data


class Monitor:
    """Bounded, in-memory diagnostics store. Never written to disk, no secrets stored."""

    def __init__(self, limit: int = 40, clock=time.time):
        self.limit = limit
        self.clock = clock
        self.logs: dict[str, deque] = defaultdict(lambda: deque(maxlen=limit))
        self.clock_state: dict[str, dict] = {}
        self.endpoints: dict[str, dict] = defaultdict(dict)
        self.last_success: dict[str, float] = {}
        self.last_failure: dict[str, Attempt] = {}

    def record(self, attempt: Attempt) -> None:
        self.logs[attempt.exchange].append(attempt)
        if attempt.reason == 'ok':
            self.last_success[attempt.exchange] = attempt.at
            self.last_failure.pop(attempt.exchange, None)
        else:
            self.last_failure[attempt.exchange] = attempt

    def use_endpoint(self, exchange: str, kind: str, endpoint_id: str) -> None:
        self.endpoints[exchange][kind] = endpoint_id

    def note_skew(self, exchange: str, skew: Optional[float]) -> None:
        if skew is None or not math.isfinite(skew):
            return
        state = self.clock_state.setdefault(exchange, {})
        state['skew_seconds'] = skew
        state['checked_at'] = self.clock()
        state['samples'] = int(state.get('samples', 0)) + 1

    def log(self, exchange: Optional[str] = None, limit: int = 25) -> list:
        entries = self.logs[exchange] if exchange else [
            item for queue in self.logs.values() for item in queue]
        ordered = sorted(entries, key=lambda item: item.at, reverse=True)
        return [item.public() for item in ordered[:limit]]

    def reset(self) -> None:
        self.logs.clear()
        self.clock_state.clear()
        self.endpoints.clear()
        self.last_success.clear()
        self.last_failure.clear()


def _classify_status(status: int) -> str:
    if status == 429:
        return 'http_429'
    if status in (401, 403, 451):
        return 'blocked'
    if status >= 500:
        return 'http_5xx'
    if status >= 400:
        return 'http_4xx'
    return 'unknown'


class Gateway:
    """Thin httpx wrapper that records every attempt and applies the shared budgets."""

    def __init__(self, monitor: Optional[Monitor] = None, user_agent: Optional[str] = None,
                 proxy: Optional[str] = None, timeout: float = 8.0,
                 max_attempts: int = 3, max_wait: float = 6.0,
                 exchange_agents: Optional[dict] = None):
        self.monitor = monitor or Monitor()
        self.user_agent = user_agent or DEFAULT_AGENT
        self.proxy = proxy
        self.timeout = timeout
        self.max_attempts = max_attempts
        self.max_wait = max_wait
        # Per-exchange overrides. Nobitex documents a bot style User-Agent and its CDN
        # rejects some default HTTP clients, so this is configurable in the settings page.
        self.exchange_agents = {name: agent for name, agent in (exchange_agents or {}).items()
                                if agent}

    def configure(self, user_agent: Optional[str] = None, proxy: Optional[str] = None,
                  timeout: Optional[float] = None,
                  exchange_agents: Optional[dict] = None) -> None:
        if user_agent is not None:
            self.user_agent = user_agent
        self.proxy = proxy
        if timeout is not None:
            self.timeout = timeout
        if exchange_agents is not None:
            self.exchange_agents = {name: agent for name, agent in exchange_agents.items()
                                    if agent}

    def agent_for(self, exchange: Optional[str] = None) -> str:
        if exchange and self.exchange_agents.get(exchange):
            return self.exchange_agents[exchange]
        return self.user_agent

    def headers_for(self, exchange: Optional[str] = None) -> dict:
        agent = self.agent_for(exchange)
        headers = {'User-Agent': agent, 'Accept': 'application/json'}
        if agent.startswith('TraderBot/'):
            # Polite bots identify themselves and where the project lives.
            headers['From'] = 'local-read-only-monitor'
        return headers

    @property
    def headers(self) -> dict:
        return self.headers_for(None)

    def make_client(self) -> httpx.AsyncClient:
        options = dict(timeout=httpx.Timeout(self.timeout), headers=self.headers,
                       follow_redirects=True)
        if self.proxy:
            options['proxy'] = self.proxy
        return httpx.AsyncClient(**options)

    async def fetch(self, client, exchange: str, endpoint: Endpoint,
                    parser: Optional[Callable[[Any], Any]] = None,
                    budget_name: Optional[str] = None,
                    max_attempts: Optional[int] = None) -> HttpResult:
        """Fetch one endpoint and optionally validate/parse it.

        HTTP-level failures (429/5xx/timeouts/network) are retried with exponential
        backoff. A response that arrives but violates a documented rule is *not* retried:
        the caller moves on to its documented alternative endpoint.
        """
        attempts = max_attempts or self.max_attempts
        result = HttpResult(ok=False, url=endpoint.url, endpoint=endpoint.id,
                            quality=endpoint.quality)
        for attempt in range(1, attempts + 1):
            result.attempts = attempt
            started = time.monotonic()
            response = None
            try:
                async with budget(budget_name or exchange).slot(max_wait=self.max_wait):
                    response = await client.get(endpoint.url, timeout=self.timeout,
                                                headers=self.headers_for(exchange))
            except BudgetExhausted as exc:
                result.reason, result.detail = 'budget', str(exc)
                self._record(exchange, endpoint, result, None, 0.0, False, 'budget', 'request budget')
                return result
            except httpx.TimeoutException:
                result.reason, result.detail = 'timeout', 'timeout'
                self._record(exchange, endpoint, result, None, 0.0, False, 'timeout', 'timeout')
                budget(budget_name or exchange).failure()
                if attempt < attempts:
                    await asyncio.sleep(min(4.0, 0.5 * 2 ** attempt))
                    continue
                return result
            except (httpx.NetworkError, httpx.HTTPError, OSError) as exc:
                result.reason, result.detail = 'network', f'{type(exc).__name__}: {exc}'
                self._record(exchange, endpoint, result, None, 0.0, False, 'network', str(exc))
                budget(budget_name or exchange).failure()
                if attempt < attempts:
                    await asyncio.sleep(min(4.0, 0.5 * 2 ** attempt))
                    continue
                return result

            elapsed = (time.monotonic() - started) * 1000
            result.status = response.status_code
            result.elapsed_ms = elapsed
            skew = None
            server = parse_http_date(response.headers.get('date'))
            if server is not None:
                skew = server - self.monitor.clock()
                self.monitor.note_skew(exchange, skew)
            result.skew = skew
            body = response.content or b''
            result.preview = preview_of(body)

            if response.status_code >= 400:
                reason = _classify_status(response.status_code)
                result.reason, result.detail = reason, f'HTTP {response.status_code}'
                self._record(exchange, endpoint, result, response.status_code, elapsed, False,
                             reason, f'HTTP {response.status_code}')
                retryable = reason in ('http_429', 'http_5xx')
                budget(budget_name or exchange).failure(retryable)
                if retryable and attempt < attempts:
                    await asyncio.sleep(min(4.0, 0.5 * 2 ** attempt))
                    continue
                return result

            try:
                data = json.loads(body.decode('utf-8'))
            except (UnicodeDecodeError, json.JSONDecodeError) as exc:
                result.reason, result.detail = 'not_json', f'{type(exc).__name__}: {exc}'
                self._record(exchange, endpoint, result, response.status_code, elapsed, False,
                             'not_json', result.detail)
                budget(budget_name or exchange).failure(retryable=False)
                return result

            result.data = data
            if parser is not None:
                try:
                    result.data = parser(data)
                except ValidationError as exc:
                    result.ok = False
                    result.reason, result.detail = exc.code, exc.detail
                    self._record(exchange, endpoint, result, response.status_code, elapsed, True,
                                 exc.code, exc.detail)
                    budget(budget_name or exchange).success()
                    return result
                except (KeyError, IndexError, TypeError, AttributeError, ValueError) as exc:
                    result.ok = False
                    result.reason = 'shape'
                    result.detail = f'{type(exc).__name__}: {exc}'
                    self._record(exchange, endpoint, result, response.status_code, elapsed, True,
                                 'shape', result.detail)
                    budget(budget_name or exchange).success()
                    return result
            result.ok = True
            result.reason = 'ok'
            self.monitor.use_endpoint(exchange, endpoint.kind, endpoint.id)
            self._record(exchange, endpoint, result, response.status_code, elapsed, True, 'ok', '')
            budget(budget_name or exchange).success()
            return result
        return result

    def _record(self, exchange: str, endpoint: Endpoint, result: HttpResult,
                status: Optional[int], elapsed: float, json_ok: bool,
                reason: str, detail: str) -> None:
        self.monitor.record(Attempt(exchange=exchange, endpoint=endpoint.id, url=endpoint.url,
                                    at=self.monitor.clock(), status=status,
                                    elapsed_ms=elapsed, json_ok=json_ok, reason=reason,
                                    detail=detail[:300], preview=result.preview,
                                    skew=result.skew, attempt=result.attempts,
                                    quality=endpoint.quality))
