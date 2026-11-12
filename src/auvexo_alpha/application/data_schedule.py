"""Canonical bounded public-data reliability schedule; no execution authority."""

from datetime import UTC, date, datetime, time, timedelta

SCHEDULE_ID = "public-data-2300-pkt-v1"
FIRST_SCHEDULED_DAY = date(2026, 10, 18)
WINDOW_START_UTC = time(18, tzinfo=UTC)
WINDOW_DURATION = timedelta(minutes=12)
WARMUP_LEAD = timedelta(minutes=3)
START_TOLERANCE = timedelta(minutes=4)
# Warm-up only: time allowed for backlog polls inside the wrapper's 150-second child deadline.
CATCHUP_BUDGET = timedelta(seconds=90)
# No backlog poll may start this close to, or inside, the qualifying window.
CATCHUP_GUARD = timedelta(seconds=30)
SCHEDULE_DESCRIPTION = (
    "22:57 Asia/Karachi warmup (17:57 UTC); 23:00-23:12 Asia/Karachi collection (18:00-18:12 UTC)"
)


def schedule_time(now: datetime) -> datetime:
    if now.tzinfo is None or now.utcoffset() is None:
        raise ValueError("NAIVE_SCHEDULE_TIME")
    return now.astimezone(UTC)


def qualification_window(day: date) -> tuple[datetime, datetime]:
    start = datetime.combine(day, WINDOW_START_UTC)
    return start, start + WINDOW_DURATION


def prewindow(day: date) -> tuple[datetime, datetime]:
    """Half-open [earliest permitted wrapper start, window start) for one calendar day."""
    target, _ = qualification_window(day)
    return target - START_TOLERANCE, target


def target_window(now: datetime) -> datetime:
    now = schedule_time(now)
    earliest, target = prewindow(now.date())
    # Never roll a late invocation forward or turn it into catch-up collection.
    if now.date() < FIRST_SCHEDULED_DAY or not earliest <= now < target:
        raise ValueError("OUTSIDE_PREWINDOW_START")
    return target


def catchup_permitted(now: datetime) -> bool:
    """Warm-up backlog polls may start only clear of that day's qualifying window."""
    now = schedule_time(now)
    start, end = qualification_window(now.date())
    return not start - CATCHUP_GUARD <= now < end
