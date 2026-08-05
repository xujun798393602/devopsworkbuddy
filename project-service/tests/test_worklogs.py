from datetime import UTC, date, datetime

import pytest

from project_service.shared.errors import ValidationError
from project_service.tasks.models import Worklog


def test_worklog_is_frozen_and_correction_is_delta() -> None:
    original = Worklog(
        "w1", "p", "t", "u", "u", date.today(), 120, "work", None, None, datetime.now(UTC)
    )
    correction = Worklog(
        "w2",
        "p",
        "t",
        "u",
        "u",
        date.today(),
        -30,
        "adjust",
        original.id,
        "mistake",
        datetime.now(UTC),
    )
    assert original.minutes_delta + correction.minutes_delta == 90
    with pytest.raises(AttributeError):
        original.minutes_delta = 1


def test_normal_worklog_cannot_be_negative_and_correction_needs_reason() -> None:
    with pytest.raises(ValidationError):
        Worklog("w", "p", "t", "u", "u", date.today(), -1, "x", None, None, datetime.now(UTC))
    with pytest.raises(ValidationError):
        Worklog("w", "p", "t", "u", "u", date.today(), -1, "x", "old", None, datetime.now(UTC))
