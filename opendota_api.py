"""OpenDota HTTP client shared by every module, with the free tier's rate limits."""

import collections
import datetime
import threading
import time

import requests

OPENDOTA_API_URL = "https://api.opendota.com/api"

# Free tier, no API key: 60 calls per minute and 3000 per day.
MAX_CALLS_PER_MINUTE = 60
MAX_CALLS_PER_DAY = 3000


class OpenDotaDailyLimitError(RuntimeError):
    """Raised when the daily call budget is spent."""


class _RateLimiter:
    """Sliding one-minute window plus a daily counter reset at UTC midnight.

    Shared by all sessions of the process. OpenDota counts per IP, so the
    remaining-calls headers it returns also lower the local budget.
    """

    def __init__(self, per_minute, per_day):
        self.per_minute = per_minute
        self.per_day = per_day
        self._lock = threading.Lock()
        self._calls = collections.deque()
        self._day = None
        self._day_count = 0

    def _roll_day(self):
        today = datetime.datetime.now(datetime.timezone.utc).date()
        if self._day != today:
            self._day = today
            self._day_count = 0

    def acquire(self):
        with self._lock:
            self._roll_day()
            if self._day_count >= self.per_day:
                raise OpenDotaDailyLimitError("OpenDota daily call limit reached")
            while True:
                now = time.monotonic()
                while self._calls and now - self._calls[0] >= 60:
                    self._calls.popleft()
                if len(self._calls) < self.per_minute:
                    break
                time.sleep(60 - (now - self._calls[0]))
            self._calls.append(time.monotonic())
            self._day_count += 1

    def update_from_headers(self, headers):
        with self._lock:
            self._roll_day()
            day_left = headers.get("X-Rate-Limit-Remaining-Day")
            if day_left is not None and day_left.isdigit():
                self._day_count = max(self._day_count, self.per_day - int(day_left))
            minute_left = headers.get("X-Rate-Limit-Remaining-Minute")
            if minute_left is not None and minute_left.isdigit():
                now = time.monotonic()
                while len(self._calls) < self.per_minute - int(minute_left):
                    self._calls.append(now)


_limiter = _RateLimiter(MAX_CALLS_PER_MINUTE, MAX_CALLS_PER_DAY)


def opendota_get(path, params=None, timeout=30, session=None):
    """GET an OpenDota endpoint (`path` like "/players/123/matches") within the rate limits."""
    _limiter.acquire()
    r = (session or requests).get(f"{OPENDOTA_API_URL}{path}", params=params, timeout=timeout)
    _limiter.update_from_headers(r.headers)
    return r
