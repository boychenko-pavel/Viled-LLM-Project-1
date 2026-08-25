from __future__ import annotations

from datetime import datetime, timezone

import pytest

from sql_agent.office_calendar import CalendarConfigurationError, GoogleCalendarService


def test_calendar_requires_oauth_configuration(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in (
        "GOOGLE_CALENDAR_CLIENT_ID",
        "GOOGLE_CALENDAR_CLIENT_SECRET",
        "GOOGLE_CALENDAR_REFRESH_TOKEN",
    ):
        monkeypatch.delenv(name, raising=False)

    service = GoogleCalendarService()

    assert service.configured is False
    with pytest.raises(CalendarConfigurationError):
        service._get_access_token()


def test_create_task_marks_calendar_event_as_atlas_task(monkeypatch: pytest.MonkeyPatch) -> None:
    service = GoogleCalendarService()
    captured: dict[str, object] = {}

    def fake_request(method: str, path: str, **kwargs: object) -> dict[str, object]:
        captured.update({"method": method, "path": path, **kwargs})
        body = kwargs["body"]
        assert isinstance(body, dict)
        return {
            "id": "event-1",
            "summary": body["summary"],
            "description": body["description"],
            "start": body["start"],
            "extendedProperties": body["extendedProperties"],
            "htmlLink": "https://calendar.google.com/event?eid=event-1",
        }

    monkeypatch.setattr(service, "_request", fake_request)
    task = service.create_task(
        "Подготовить отчет",
        datetime(2026, 8, 13, 10, 0, tzinfo=timezone.utc),
        "До встречи",
    )

    assert captured["method"] == "POST"
    assert task["id"] == "event-1"
    assert task["completed"] is False
    body = captured["body"]
    assert isinstance(body, dict)
    assert body["extendedProperties"]["private"] == {
        "atlasTask": "true",
        "atlasDone": "false",
    }


def test_complete_task_preserves_task_marker(monkeypatch: pytest.MonkeyPatch) -> None:
    service = GoogleCalendarService()

    def fake_request(method: str, path: str, **kwargs: object) -> dict[str, object]:
        body = kwargs["body"]
        assert method == "PATCH"
        assert path.endswith("/event-1")
        assert isinstance(body, dict)
        return {
            "id": "event-1",
            "summary": "Задача",
            "start": {"dateTime": "2026-08-13T10:00:00+00:00"},
            "extendedProperties": body["extendedProperties"],
        }

    monkeypatch.setattr(service, "_request", fake_request)

    task = service.set_completed("event-1", True)

    assert task["completed"] is True
