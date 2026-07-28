# Licensed to Apache Software Foundation (ASF) under one or more contributor
# license agreements. See the NOTICE file distributed with
# this work for additional information regarding copyright
# ownership. Apache Software Foundation (ASF) licenses this file to you under
# the Apache License, Version 2.0 (the "License"); you may
# not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing,
# software distributed under the License is distributed on an
# "AS IS" BASIS, WITHOUT WARRANTIES OR CONDITIONS OF ANY
# KIND, either express or implied.  See the License for the
# specific language governing permissions and limitations
# under the License.

"""Time, duration and pagination helpers — a faithful port of internal/tools/common.go.

Duration handling must match the Go server closely because the OAP GraphQL
``Duration`` input (Start/End strings + Step granularity) is sensitive to the exact
formatting and step selection the original produced.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any

# Step granularity (matches goapi query.Step string values).
STEP_SECOND = "SECOND"
STEP_MINUTE = "MINUTE"
STEP_HOUR = "HOUR"
STEP_DAY = "DAY"
_VALID_STEPS = {STEP_SECOND, STEP_MINUTE, STEP_HOUR, STEP_DAY}

# Defaults (mirror common.go).
DEFAULT_PAGE_SIZE = 15
DEFAULT_PAGE_NUM = 1
DEFAULT_DURATION = 30  # minutes
NOW_KEYWORD = "now"


# --- Go-style duration string parsing ---------------------------------------

_GO_DURATION_UNIT = {
    "ns": 1e-9,
    "us": 1e-6,
    "µs": 1e-6,
    "ms": 1e-3,
    "s": 1.0,
    "m": 60.0,
    "h": 3600.0,
}
_GO_DUR_TOKEN = re.compile(r"([0-9]*\.?[0-9]+)(ns|us|µs|ms|s|m|h)")

# Go's ParseDuration stops at hours. Days and weeks are accepted only for
# explicitly signed offsets (see parse_relative_offset), so the bare legacy form
# "7d" ("the last 7 days") keeps its own meaning.
_EXT_DURATION_UNIT = {**_GO_DURATION_UNIT, "d": 86400.0, "w": 604800.0}
_EXT_DUR_TOKEN = re.compile(r"([0-9]*\.?[0-9]+)(ns|us|µs|ms|s|m|h|d|w)")


def _accumulate_duration(
    s: str, token_re: re.Pattern[str], units: dict[str, float]
) -> float | None:
    """Sum a unit-suffixed token sequence ("2h45m"); None if anything fails to match."""
    pos = 0
    total = 0.0
    matched = False
    while pos < len(s):
        m = token_re.match(s, pos)
        if not m:
            return None
        total += float(m.group(1)) * units[m.group(2)]
        pos = m.end()
        matched = True
    return total if matched else None


def go_parse_duration(text: str) -> timedelta | None:
    """Parse a Go time.ParseDuration string (e.g. "-30m", "1.5h", "2h45m").

    Returns None when the string is not a valid Go duration, so callers can fall
    back to legacy/absolute parsing exactly like the Go code branches on err.
    """
    if not text:
        return None
    s = text.strip()
    sign = 1.0
    if s and s[0] in "+-":
        if s[0] == "-":
            sign = -1.0
        s = s[1:]
    if not s:
        return None
    total = _accumulate_duration(s, _GO_DUR_TOKEN, _GO_DURATION_UNIT)
    return None if total is None else timedelta(seconds=sign * total)


def parse_relative_offset(text: str) -> timedelta | None:
    """Parse a signed offset for the start/end parameters, e.g. "-7d", "-1w".

    Extends Go's units with days and weeks: operators naturally write "-7d" for a
    weekly inspection, and because Go rejects it the window used to collapse
    silently to the 30m default. The sign is what enables the extension, leaving
    the unsigned legacy form ("7d" = the last 7 days) to its own parser.
    """
    if not text:
        return None
    s = text.strip()
    if s[:1] not in ("+", "-"):
        return go_parse_duration(s)
    sign = -1.0 if s[0] == "-" else 1.0
    total = _accumulate_duration(s[1:], _EXT_DUR_TOKEN, _EXT_DURATION_UNIT)
    return None if total is None else timedelta(seconds=sign * total)


# --- Time context ------------------------------------------------------------


@dataclass
class TimeContext:
    now_utc: datetime  # timezone-aware UTC
    location: timezone  # tzinfo used to interpret absolute times


def _parse_timezone_offset(offset: str) -> timezone | None:
    """Parse a "+0800"/"-0530" offset into a fixed tzinfo (port of parseTimezoneOffset)."""
    if len(offset) != 5 or offset[0] not in "+-":
        return None
    try:
        hours = int(offset[1:3])
        minutes = int(offset[3:5])
    except ValueError:
        return None
    total = hours * 3600 + minutes * 60
    if offset[0] == "-":
        total = -total
    return timezone(timedelta(seconds=total))


def new_time_context(time_info: dict[str, Any] | None = None) -> TimeContext:
    """Build a TimeContext from server TimeInfo, falling back to local UTC now."""
    now_utc = datetime.now(timezone.utc)
    location: timezone = timezone.utc
    if time_info:
        ts = time_info.get("currentTimestamp")
        if ts is not None:
            now_utc = datetime.fromtimestamp(int(ts) / 1000.0, tz=timezone.utc)
        tz = time_info.get("timezone")
        if tz:
            loc = _parse_timezone_offset(str(tz))
            if loc is not None:
                location = loc
    return TimeContext(now_utc=now_utc, location=location)


# --- Formatting --------------------------------------------------------------


def format_time_by_step(t: datetime, step: str) -> str:
    """Format a datetime for the OAP Duration input according to step granularity."""
    if step == STEP_DAY:
        return t.strftime("%Y-%m-%d")
    if step == STEP_HOUR:
        return t.strftime("%Y-%m-%d %H")
    if step == STEP_MINUTE:
        return t.strftime("%Y-%m-%d %H%M")
    if step == STEP_SECOND:
        return t.strftime("%Y-%m-%d %H%M%S")
    return t.strftime("%Y-%m-%d %H:%M:%S")


def _determine_adaptive_step(start: datetime, end: datetime) -> str:
    duration = end - start
    if duration >= timedelta(days=7):
        return STEP_DAY
    if duration >= timedelta(hours=24):
        return STEP_HOUR
    # < 24h (including < 1h) resolves to MINUTE, matching the Go fall-through.
    return STEP_MINUTE


def _parse_legacy_duration(duration_str: str, now: datetime) -> tuple[datetime, datetime, str]:
    """Parse legacy strings like "7d"/"24h" (port of parseLegacyDuration)."""
    if len(duration_str) > 1 and duration_str[-1] in "dD":
        try:
            days = int(duration_str[:-1])
        except ValueError:
            days = 0
        if days > 0:
            return now - timedelta(days=days), now, STEP_DAY
        return now - timedelta(days=7), now, STEP_DAY
    if len(duration_str) > 1 and duration_str[-1] in "hH":
        try:
            hours = int(duration_str[:-1])
        except ValueError:
            hours = 0
        if hours > 0:
            return now - timedelta(hours=hours), now, STEP_HOUR
        return now - timedelta(hours=1), now, STEP_HOUR
    return now - timedelta(days=7), now, STEP_DAY


_ABSOLUTE_FORMATS = [
    "%Y-%m-%d %H:%M:%S",
    "%Y-%m-%d %H:%M",
    "%Y-%m-%d %H%M",
    "%Y-%m-%d %H",
    "%Y-%m-%d %H%M%S",
    "%Y-%m-%d",
]


def _parse_absolute_time(time_str: str, location: timezone) -> datetime | None:
    for fmt in _ABSOLUTE_FORMATS:
        try:
            parsed = datetime.strptime(time_str, fmt)
        except ValueError:
            continue
        return parsed.replace(tzinfo=location)
    return None


def _parse_time_string(time_str: str, default_time: datetime, tc: TimeContext) -> datetime:
    now = tc.now_utc
    if time_str == "":
        return default_time
    if time_str.lower() == NOW_KEYWORD:
        return now
    rel = parse_relative_offset(time_str)
    if rel is not None:
        return now + rel
    absolute = _parse_absolute_time(time_str, tc.location)
    if absolute is not None:
        return absolute.astimezone(timezone.utc)
    return default_time


def _parse_start_end_times(start: str, end: str, tc: TimeContext) -> tuple[datetime, datetime]:
    now = tc.now_utc
    default_start = now - timedelta(minutes=30)
    return _parse_time_string(start, default_start, tc), _parse_time_string(end, now, tc)


# --- Public duration builders ------------------------------------------------


def _duration_dict(start: datetime, end: datetime, step: str, cold: bool) -> dict[str, Any]:
    d: dict[str, Any] = {
        "start": format_time_by_step(start, step),
        "end": format_time_by_step(end, step),
        "step": step,
    }
    # coldStage is omitted unless requested: the field does not exist on OAP < 10.2.0
    # and sending it there fails the whole request with a validation error.
    if cold:
        d["coldStage"] = True
    return d


def parse_duration_with_context(duration_str: str, cold: bool, tc: TimeContext) -> dict[str, Any]:
    rel = go_parse_duration(duration_str)
    if rel is not None:
        if rel.total_seconds() < 0:
            start, end = tc.now_utc + rel, tc.now_utc
        else:
            start, end = tc.now_utc, tc.now_utc + rel
        step = _determine_adaptive_step(start, end)
    else:
        start, end, step = _parse_legacy_duration(duration_str, tc.now_utc)
    if step not in _VALID_STEPS:
        step = STEP_MINUTE
    return _duration_dict(start, end, step, cold)


def build_duration_with_context(
    start: str,
    end: str,
    step: str,
    cold: bool,
    default_duration_minutes: int,
    tc: TimeContext,
) -> dict[str, Any]:
    if start != "" or end != "":
        step_enum = step
        start_t, end_t = _parse_start_end_times(start, end, tc)
        if step == "" or step_enum not in _VALID_STEPS:
            step_enum = _determine_adaptive_step(start_t, end_t)
        return _duration_dict(start_t, end_t, step_enum, cold)

    if default_duration_minutes <= 0:
        default_duration_minutes = DEFAULT_DURATION
    return parse_duration_with_context(f"-{default_duration_minutes}m", cold, tc)


def build_pagination(page_num: int, page_size: int) -> dict[str, Any]:
    if page_num <= 0:
        page_num = DEFAULT_PAGE_NUM
    if page_size <= 0:
        page_size = DEFAULT_PAGE_SIZE
    return {"pageNum": page_num, "pageSize": page_size}
