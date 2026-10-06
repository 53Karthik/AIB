import math
import re
from datetime import datetime, timedelta, timezone


DMY = re.compile(r"^(\d{1,2})/(\d{1,2})/(\d{4})(?:\s+(\d{1,2}):(\d{2})(?::(\d{2}))?)?$")
ISO = re.compile(r"^(\d{4})-(\d{2})-(\d{2})(?:[T\s](\d{2}):(\d{2})(?::(\d{2}))?)?")
EPOCH = datetime(1970, 1, 1)


def _rounded(stamp):
    seconds = (stamp - EPOCH).total_seconds()
    return EPOCH + timedelta(seconds=math.floor(seconds + 0.5))


def _parts(year, month, day, hour, minute, second):
    year = year + 1900 if 0 <= year <= 99 else year
    year_offset, month_index = divmod(month - 1, 12)
    return datetime(year + year_offset, month_index + 1, 1) + timedelta(
        days=day - 1, hours=hour, minutes=minute, seconds=second
    )


def parse_stamp(value):
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, datetime):
        if value.tzinfo is not None:
            value = value.astimezone(timezone.utc).replace(tzinfo=None)
        return _rounded(value)
    if isinstance(value, (int, float)):
        if not math.isfinite(value):
            return None
        return EPOCH + timedelta(seconds=math.floor((value - 25569) * 86400 + 0.5))
    text = str(value).strip()
    if not text or text.lower() == "nan":
        return None
    match = DMY.match(text)
    if match:
        day, month, year, hour, minute, second = [int(part or 0) for part in match.groups()]
        return _parts(year, month, day, hour, minute, second)
    match = ISO.match(text)
    if match:
        return _parts(*[int(part or 0) for part in match.groups()])
    if re.fullmatch(r"\d+(\.\d+)?", text):
        return parse_stamp(float(text))
    return None


def day_of(stamp):
    return stamp.strftime("%Y-%m-%d") if stamp is not None else None


def month_of(stamp):
    return stamp.strftime("%Y-%m") if stamp is not None else None


def iso_of(stamp):
    return stamp.isoformat(timespec="seconds") if stamp is not None else None


def add_days(day, count):
    return day_of(datetime.fromisoformat(day) + timedelta(days=count))


def weekday_of(day):
    return (datetime.fromisoformat(day).weekday() + 1) % 7


def hours_between(start, end):
    return (end - start).total_seconds() / 3600
