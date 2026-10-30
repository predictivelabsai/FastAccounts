"""Estonian public holidays and standard working time calculations."""
from calendar import monthrange
from datetime import date, timedelta


def easter_sunday(year: int) -> date:
    """Return Easter Sunday using the Anonymous Gregorian computus."""
    a = year % 19
    b, c = divmod(year, 100)
    d, e = divmod(b, 4)
    f = (b + 8) // 25
    g = (b - f + 1) // 3
    h = (19 * a + b - d - g + 15) % 30
    i, k = divmod(c, 4)
    l = (32 + 2 * e + 2 * i - h - k) % 7
    m = (a + 11 * h + 22 * l) // 451
    month = (h + l - 7 * m + 114) // 31
    day = (h + l - 7 * m + 114) % 31 + 1
    return date(year, month, day)


def public_holidays(year: int) -> frozenset[date]:
    easter = easter_sunday(year)
    return frozenset({
        date(year, 1, 1), date(year, 2, 24), easter - timedelta(days=2), easter,
        date(year, 5, 1), easter + timedelta(days=49), date(year, 6, 23),
        date(year, 6, 24), date(year, 8, 20), date(year, 12, 24),
        date(year, 12, 25), date(year, 12, 26),
    })


def is_working_day(day: date) -> bool:
    return day.weekday() < 5 and day not in public_holidays(day.year)


def working_days(year: int, month: int) -> int:
    last_day = monthrange(year, month)[1]
    return sum(is_working_day(date(year, month, day)) for day in range(1, last_day + 1))


def norm_hours(year: int, month: int, hours_per_day: int = 8) -> int:
    """Monthly full-time hours, including TLS § 53 shortened eves."""
    if hours_per_day <= 0:
        raise ValueError('hours_per_day must be positive')
    last_day = monthrange(year, month)[1]
    short_eves = {
        date(year, 2, 23), date(year, 6, 22), date(year, 12, 23), date(year, 12, 31),
    }
    days = [date(year, month, day) for day in range(1, last_day + 1)]
    return working_days(year, month) * hours_per_day - 3 * sum(
        day in short_eves and is_working_day(day) for day in days
    )


def norm_days(year: int, month: int) -> int:
    return working_days(year, month)
