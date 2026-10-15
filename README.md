# cron-jobs-sandbox

A zero-dependency Python library for parsing standard five-field cron expressions and enumerating their next fire times.

```python
from cron_jobs_sandbox import parse_cron, next_fire_times
from datetime import datetime

expr = parse_cron("*/15 * * * *")
for t in next_fire_times(expr, datetime(2024, 1, 1, 0, 0), count=4):
    print(t)
```

## Why this exists

Standard cron expressions look simple but hide a pile of edge cases: step values, named months and weekdays, the OR semantics between day-of-month and day-of-week, and impossible dates like February 30th. This library exists to give a small, focused, pure-Python implementation that handles those cases correctly without pulling in a heavier scheduling framework.

The trade-off is timezones: all `datetime` objects are naive. Supporting timezones would require either `zoneinfo` (not available on stripped-down container images without system timezone data) or a bundled timezone database, both of which violate the zero-dependency constraint.

## Edge cases you will hit

- **30/31 February is rejected at parse time**, not silently clamped. A schedule like `0 0 30 2 *` can never fire; the library raises `ValueError` rather than rewriting your expression to something you did not write.
- **Day-of-month and day-of-week are OR-ed** when both are restricted (non-wildcard). `0 0 1 * SUN` fires on the 1st of the month *and* on every Sunday.
- **Seconds and microseconds are stripped from the start time.** `next_fire_times` treats the start as the minute boundary for the purposes of comparison, so a start of `00:00:30` will not match `0 * * * *` at `00:00`.
- **Weekdays are Python-idiomatic**: Monday=0, Sunday=6. The cron convention (Sunday=0) is translated internally; callers never need to think about it.

## Exported names

- `parse_cron(expr)` — parse a five-field cron string into a `CronExpression`.
- `CronExpression` — the compiled, immutable expression object. Has a `.matches(dt)` method and a `.raw` attribute.
- `next_fire_times(expr, start, count=1)` — return up to `count` fire times strictly after `start`.
- `CronField` — a single field; exposed for introspection.

## Running the tests

```
PYTHONPATH=src python -m unittest discover -s tests
```
