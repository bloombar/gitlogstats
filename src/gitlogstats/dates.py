"""
FILT-1, FILT-9: read the -s/--start and -e/--end values, which are a date
(mm/dd/yyyy) with an optional 24-hour time (HH:MM or HH:MM:SS), as the local
moments that begin and end the date range.
"""

import datetime

# each accepted format, with the moment the range ends at for a value given in
# it: a value includes everything up to the end of its last stated unit, so a
# date runs to the end of that day and HH:MM to the end of that minute
FORMATS = (
    ("%m/%d/%Y %H:%M:%S", {}),
    ("%m/%d/%Y %H:%M", {"second": 59}),
    ("%m/%d/%Y", {"hour": 23, "minute": 59, "second": 59}),
)


def _parse(value, end):
    """
    Read a date with an optional time as a local moment.
    @param value: e.g. "03/01/2024", "03/01/2024 17:00" or "03/01/2024 17:00:30"
    @param end: whether the value ends the range, so that it covers the whole
        day or minute it names
    @returns: a naive local datetime
    @raises ValueError: if the value is in none of the accepted formats
    """
    for fmt, end_of_unit in FORMATS:
        try:
            moment = datetime.datetime.strptime(value, fmt)
        except ValueError:
            continue
        return moment.replace(**end_of_unit) if end else moment
    raise ValueError(f"invalid date '{value}'")


def range_start(value):
    """
    The first moment of the range: midnight when no time is given.
    @param value: the -s/--start value
    @returns: a naive local datetime
    @raises ValueError: if the value is not a valid date and time
    """
    return _parse(value, end=False)


def range_end(value):
    """
    The last moment of the range, included: the end of the day when no time is
    given, and the end of the minute when a time has no seconds.
    @param value: the -e/--end value
    @returns: a naive local datetime
    @raises ValueError: if the value is not a valid date and time
    """
    return _parse(value, end=True)
