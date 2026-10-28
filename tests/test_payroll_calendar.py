from datetime import date

import pytest

from payroll_calendar import easter_sunday, is_working_day, norm_days, norm_hours, public_holidays


def test_gregorian_easter_and_estonian_holidays():
    assert easter_sunday(2026) == date(2026, 4, 5)
    holidays = public_holidays(2026)
    assert date(2026, 4, 3) in holidays
    assert date(2026, 4, 5) in holidays
    assert not is_working_day(date(2026, 2, 24))


@pytest.mark.parametrize(('month', 'days', 'hours'), [
    (2, 19, 149), (6, 20, 157), (10, 22, 176), (12, 21, 162),
])
def test_2026_working_time_norms(month, days, hours):
    assert norm_days(2026, month) == days
    assert norm_hours(2026, month) == hours


def test_non_working_preholiday_does_not_create_short_day():
    # 1 January 2027 is Friday, so 31 December 2026 is the shortened working eve.
    assert norm_hours(2026, 12) == 162
