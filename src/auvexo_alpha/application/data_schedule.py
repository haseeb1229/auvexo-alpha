"""Canonical bounded public-data reliability schedule; no execution authority."""

from datetime import UTC, date, datetime, time, timedelta

SCHEDULE_ID = "public-data-2300-pkt-v1"
FIRST_SCHEDULED_DAY = date(2026, 10, 18)
WINDOW_START_UTC = time(18, tzinfo=UTC)
WINDOW_DURATION = timedelta(minutes=12)
WARMUP_LEAD = timedelta(minutes=3)
START_TOLERANCE = timedelta(minutes=4)
SCHEDULE_DESCRIPTION = (
    "22:57 Asia/Karachi warmup (17:57 UTC); 23:00-23:12 Asia/Karachi collection (18:00-18:12 UTC)"
)


def qualification_window(day: date) -> tuple[datetime, datetime]:
    start = datetime.combine(day, WINDOW_START_UTC)
    return start, start + WINDOW_DURATION


def target_window(now: datetime) -> datetime:
    if now.tzinfo is None or now.utcoffset() is None:
        raise ValueError("NAIVE_SCHEDULE_TIME")
    now = now.astimezone(UTC)
    target, _ = qualification_window(now.date())
    # Never roll a late invocation forward or turn it into catch-up collection.
    if now.date() < FIRST_SCHEDULED_DAY or not timedelta(0) < target - now <= START_TOLERANCE:
        raise ValueError("OUTSIDE_PREWINDOW_START")
    return target
