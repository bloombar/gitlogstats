"""
Unit tests for gitlogstats.dates: reading -s/-e values, with and without a
time of day, as the moments that begin and end the date range (FILT-1, FILT-9).
"""

import datetime

import pytest

from gitlogstats.dates import range_end, range_start

D = datetime.datetime


@pytest.mark.parametrize(
    "value, expected",
    [
        ("03/01/2024", D(2024, 3, 1, 0, 0, 0)),
        ("03/01/2024 17:05", D(2024, 3, 1, 17, 5, 0)),
        ("03/01/2024 17:05:30", D(2024, 3, 1, 17, 5, 30)),
        ("03/01/2024 00:00", D(2024, 3, 1, 0, 0, 0)),
        ("03/01/2024 9:05", D(2024, 3, 1, 9, 5, 0)),
    ],
)
def test_range_start_begins_at_the_stated_moment(value, expected):
    assert range_start(value) == expected


@pytest.mark.parametrize(
    "value, expected",
    [
        # a date covers its whole day, a minute its whole minute
        ("03/01/2024", D(2024, 3, 1, 23, 59, 59)),
        ("03/01/2024 17:05", D(2024, 3, 1, 17, 5, 59)),
        ("03/01/2024 17:05:30", D(2024, 3, 1, 17, 5, 30)),
        ("03/01/2024 23:59", D(2024, 3, 1, 23, 59, 59)),
    ],
)
def test_range_end_covers_the_last_stated_unit(value, expected):
    assert range_end(value) == expected


@pytest.mark.parametrize(
    "value",
    [
        "2024-03-01",
        "13/01/2024",
        "03/01/2024 24:00",
        "03/01/2024 17:60",
        "03/01/2024 17:00:60",
        "03/01/2024 5pm",
        "03/01/2024 05:00 PM",
        "03/01/2024T17:00",
        "03/01/2024 17",
        "",
    ],
)
def test_invalid_values_are_rejected(value):
    with pytest.raises(ValueError):
        range_start(value)
    with pytest.raises(ValueError):
        range_end(value)
