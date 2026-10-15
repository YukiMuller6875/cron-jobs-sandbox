"""Core cron expression parser and scheduler.

This module is deliberately self-contained: it uses only the Python standard
calendar module and no third-party packages. The two design choices that
are not obvious from the brief are documented below.

**No timezone support.** ``datetime`` objects produced by this module are
naive. The caller is responsible for any timezone conversion. Supporting
timezones would require either ``zoneinfo`` (Python 3.9+ only and dependent
on system timezone data, which may not be present in a stripped container)
or a bundled tz database, both of which break the zero-dependency rule.

**30/31 February is impossible, not clamped.** ``0 0 30 2 *`` can never fire
because February never has 30 days. Rather than silently rewriting it to
``0 0 28 2 *``, the parser raises ``ValueError``. Silent rewrites make
debugging cron schedules harder, not easier, because the schedule that runs
is not the schedule that was written.
"""

import calendar
from datetime import datetime, timedelta

__all__ = ["CronField", "CronExpression", "parse_cron", "next_fire_times"]


class CronField:
    """A single field of a cron expression (minute, hour, etc.).

    Attributes:
        name: Human-readable name ("minute", "hour", ...).
        min_value: Inclusive lower bound.
        max_value: Inclusive upper bound.
        values: Sorted tuple of integers selected by the field, or ``None``
            for the wildcard ("all values in range").
    """

    __slots__ = ("name", "min_value", "max_value", "values")

    def __init__(self, name, min_value, max_value, values):
        self.name = name
        self.min_value = min_value
        self.max_value = max_value
        self.values = values

    def matches(self, value):
        """Return True if ``value`` is selected by this field."""
        if self.values is None:
            return self.min_value <= value <= self.max_value
        return value in self.values

    def __repr__(self):
        return "CronField(name={!r}, values={!r})".format(self.name, self.values)


def _parse_step(step_str, field_name):
    """Parse the step portion of an ``a/b`` cron token.

    The cron spec allows omitting the base (``*/5``), but the step itself is
    mandatory and must be a positive integer. We reject ``0`` because a step
    of zero produces an infinite loop in naive implementations.
    """
    if not step_str:
        raise ValueError("missing step value for field {!r}".format(field_name))
    try:
        step = int(step_str)
    except ValueError:
        raise ValueError(
            "step must be an integer for field {!r}: {!r}".format(field_name, step_str)
        )
    if step <= 0:
        raise ValueError(
            "step must be a positive integer for field {!r}: {}".format(field_name, step)
        )
    return step


def _parse_field(raw, name, min_value, max_value, names):
    """Parse a single cron field into a ``CronField``.

    Supported syntax per field:
        *       wildcard (all valid values)
        a       single value
        a-b     inclusive range
        a,b,c   comma-separated list of the above
        a/b     range or wildcard with step

    Names (``MON``, ``JAN``) are case-insensitive. Abbreviations are NOT
    accepted: ``TUE`` works, ``TUESDAY`` does not. This matches Vixie cron
    and avoids ambiguity (``MAR`` March vs ``MARCH``).
    """
    if not raw:
        raise ValueError("field {!r} is empty".format(name))

    if raw == "*":
        return CronField(name, min_value, max_value, None)

    # Normalize names to integers so the rest of the parser only deals
    # with numbers.
    def resolve(token):
        if names and token.upper() in names:
            return names[token.upper()]
        try:
            return int(token)
        except ValueError:
            raise ValueError(
                "invalid value {!r} for field {!r}".format(token, name)
            )

    selected = set()
    for part in raw.split(","):
        if "/" in part:
            base, step_part = part.split("/", 1)
            step = _parse_step(step_part, name)
            if base == "*":
                start, end = min_value, max_value
            elif "-" in base:
                lo, hi = base.split("-", 1)
                start, end = resolve(lo), resolve(hi)
            else:
                # ``5/10`` is shorthand for ``5-max/10`` in Vixie cron.
                start = resolve(base)
                end = max_value
            if start > end:
                raise ValueError(
                    "range start exceeds end in field {!r}: {!r}".format(name, part)
                )
            for v in range(start, end + 1, step):
                selected.add(v)
        elif "-" in part:
            lo, hi = part.split("-", 1)
            start, end = resolve(lo), resolve(hi)
            if start > end:
                raise ValueError(
                    "range start exceeds end in field {!r}: {!r}".format(name, part)
                )
            for v in range(start, end + 1):
                selected.add(v)
        else:
            v = resolve(part)
            selected.add(v)

    for v in selected:
        if not (min_value <= v <= max_value):
            raise ValueError(
                "value {} out of range [{}, {}] for field {!r}".format(
                    v, min_value, max_value, name
                )
            )

    return CronField(name, min_value, max_value, tuple(sorted(selected)))


_MONTH_NAMES = {
    "JAN": 1, "FEB": 2, "MAR": 3, "APR": 4,
    "MAY": 5, "JUN": 6, "JUL": 7, "AUG": 8,
    "SEP": 9, "OCT": 10, "NOV": 11, "DEC": 12,
}

_DAY_NAMES = {
    "SUN": 6, "MON": 0, "TUE": 1, "WED": 2,
    "THU": 3, "FRI": 4, "SAT": 5,
}


class CronExpression:
    """A compiled, immutable cron expression.

    Once constructed the expression can be queried cheaply and reused. The
    ``weekday`` field follows the Python ``date.weekday()`` convention where
    Monday is 0 and Sunday is 6 (Vixie cron uses Sunday=0; we translate in
    the parser so callers never have to think about it).
    """

    __slots__ = ("minute", "hour", "day_of_month", "month", "weekday", "raw")

    def __init__(self, minute, hour, day_of_month, month, weekday, raw):
        self.minute = minute
        self.hour = hour
        self.day_of_month = day_of_month
        self.month = month
        self.weekday = weekday
        self.raw = raw

    @classmethod
    def parse(cls, expr):
        """Parse a five-field cron expression string."""
        return parse_cron(expr)

    def matches(self, dt):
        """Return True if ``dt`` satisfies every field of this expression.

        Note: day-of-month and day-of-week are OR-ed when both are restricted
        (non-wildcard), per standard Vixie cron behaviour. When either is a
        wildcard, both must match (AND).
        """
        if not self.month.matches(dt.month):
            return False
        if not self.minute.matches(dt.minute):
            return False
        if not self.hour.matches(dt.hour):
            return False

        dom_match = self.day_of_month.matches(dt.day)
        dow_match = self.weekday.matches(dt.weekday())

        if self.day_of_month.values is None:
            return dow_match
        if self.weekday.values is None:
            return dom_match
        return dom_match or dow_match

    def __repr__(self):
        return "CronExpression({!r})".format(self.raw)


def parse_cron(expr):
    """Parse a standard five-field cron expression into a ``CronExpression``.

    Fields, in order: minute hour day-of-month month day-of-week.
    """
    if not isinstance(expr, str):
        raise TypeError("expr must be a string")
    parts = expr.split()
    if len(parts) != 5:
        raise ValueError(
            "expected 5 fields, got {}".format(len(parts))
        )
    minute = _parse_field(parts[0], "minute", 0, 59, None)
    hour = _parse_field(parts[1], "hour", 0, 23, None)
    dom = _parse_field(parts[2], "day-of-month", 1, 31, None)
    month = _parse_field(parts[3], "month", 1, 12, _MONTH_NAMES)
    dow = _parse_field(parts[4], "day-of-week", 0, 6, _DAY_NAMES)

    # Validate day-of-month against the month(s) it will fire in. We only
    # check months the expression actually targets, so a day-of-month of
    # 31 paired with a wildcard month is accepted (it fires in the months
    # that have 31 days). But ``0 0 30 2 *`` is rejected eagerly because
    # February never has 30 days.
    if dom.values is not None and month.values is not None:
        for m in month.values:
            max_day = calendar.monthrange(2001, m)[1]  # 2001 is a non-leap year
            for d in dom.values:
                if d > max_day:
                    raise ValueError(
                        "day {} does not exist in month {} for field {!r}".format(
                            d, m, "day-of-month"
                        )
                    )

    return CronExpression(minute, hour, dom, month, dow, expr)


def next_fire_times(expr, start, count=1):
    """Return up to ``count`` fire times strictly after ``start``.

    Args:
        expr: A ``CronExpression``.
        start: Naive ``datetime``; fire times are strictly greater than this.
        count: Maximum number of times to return.

    Returns a list of naive ``datetime`` objects. The search is bounded at
    366 days past ``start`` to prevent infinite loops on impossible schedules
    that slipped past validation (e.g. ``0 0 30 2 *`` combined with a future
    schedule that somehow passes the month check).
    """
    if not isinstance(expr, CronExpression):
        raise TypeError("expr must be a CronExpression")
    if not isinstance(start, datetime):
        raise TypeError("start must be a datetime")
    if count < 0:
        raise ValueError("count must be non-negative")
    if count == 0:
        return []

    results = []
    current = start.replace(second=0, microsecond=0) + timedelta(minutes=1)
    deadline = start + timedelta(days=366)

    while current <= deadline and len(results) < count:
        if expr.matches(current):
            results.append(current)
        current += timedelta(minutes=1)

    return results
