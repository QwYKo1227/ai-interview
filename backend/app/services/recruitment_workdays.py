"""Mainland China workdays, including official weekend make-up days."""
from datetime import timedelta, timezone

from chinese_calendar import is_workday

COMPANY_TZ = timezone(timedelta(hours=8))


def add_workdays(start, days):
    current = start.astimezone(COMPANY_TZ)
    for _ in range(days):
        current += timedelta(days=1)
        while not is_workday(current.date()):
            current += timedelta(days=1)
    return current.astimezone(timezone.utc)
