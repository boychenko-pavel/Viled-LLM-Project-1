from __future__ import annotations

import json
import os
from datetime import datetime, timedelta, timezone
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlencode
from urllib.request import Request, urlopen


GOOGLE_TOKEN_URL = "https://oauth2.googleapis.com/token"
GOOGLE_CALENDAR_API_URL = "https://www.googleapis.com/calendar/v3"


class CalendarConfigurationError(RuntimeError):
    pass


class CalendarApiError(RuntimeError):
    pass


class GoogleCalendarService:
    """Small Google Calendar REST client used by the Office Manager task list."""

    def __init__(self) -> None:
        self.client_id = os.getenv("GOOGLE_CALENDAR_CLIENT_ID", "").strip()
        self.client_secret = os.getenv("GOOGLE_CALENDAR_CLIENT_SECRET", "").strip()
        self.refresh_token = os.getenv("GOOGLE_CALENDAR_REFRESH_TOKEN", "").strip()
        self.calendar_id = os.getenv("GOOGLE_CALENDAR_ID", "primary").strip() or "primary"
        self.time_zone = os.getenv("GOOGLE_CALENDAR_TIME_ZONE", "Asia/Qyzylorda").strip()
        self._access_token = ""
        self._access_token_expires_at = datetime.min.replace(tzinfo=timezone.utc)

    @property
    def configured(self) -> bool:
        return bool(self.client_id and self.client_secret and self.refresh_token)

    def list_tasks(self) -> list[dict[str, Any]]:
        payload = self._request(
            "GET",
            "/calendars/{calendar_id}/events".format(
                calendar_id=quote(self.calendar_id, safe=""),
            ),
            query={
                "singleEvents": "true",
                "orderBy": "startTime",
                "maxResults": "100",
                "privateExtendedProperty": "atlasTask=true",
            },
        )
        return [self._normalize_task(item) for item in payload.get("items", [])]

    def create_task(self, title: str, due_at: datetime, notes: str = "") -> dict[str, Any]:
        cleaned_title = title.strip()
        if not cleaned_title:
            raise ValueError("Название задачи не может быть пустым.")
        if due_at.tzinfo is None:
            due_at = due_at.astimezone()
        end_at = due_at + timedelta(minutes=30)
        payload = self._request(
            "POST",
            "/calendars/{calendar_id}/events".format(
                calendar_id=quote(self.calendar_id, safe=""),
            ),
            body={
                "summary": cleaned_title,
                "description": notes.strip(),
                "start": {"dateTime": due_at.isoformat(), "timeZone": self.time_zone},
                "end": {"dateTime": end_at.isoformat(), "timeZone": self.time_zone},
                "extendedProperties": {
                    "private": {"atlasTask": "true", "atlasDone": "false"},
                },
            },
        )
        return self._normalize_task(payload)

    def set_completed(self, event_id: str, completed: bool) -> dict[str, Any]:
        payload = self._request(
            "PATCH",
            self._event_path(event_id),
            body={
                "extendedProperties": {
                    "private": {
                        "atlasTask": "true",
                        "atlasDone": "true" if completed else "false",
                    },
                },
            },
        )
        return self._normalize_task(payload)

    def delete_task(self, event_id: str) -> None:
        self._request("DELETE", self._event_path(event_id))

    def _event_path(self, event_id: str) -> str:
        cleaned_event_id = event_id.strip()
        if not cleaned_event_id:
            raise ValueError("Не указан идентификатор задачи.")
        return "/calendars/{calendar_id}/events/{event_id}".format(
            calendar_id=quote(self.calendar_id, safe=""),
            event_id=quote(cleaned_event_id, safe=""),
        )

    def _get_access_token(self) -> str:
        now = datetime.now(timezone.utc)
        if self._access_token and now < self._access_token_expires_at:
            return self._access_token
        if not self.configured:
            raise CalendarConfigurationError(
                "Google Calendar не настроен. Задайте GOOGLE_CALENDAR_CLIENT_ID, "
                "GOOGLE_CALENDAR_CLIENT_SECRET и GOOGLE_CALENDAR_REFRESH_TOKEN."
            )

        request = Request(
            GOOGLE_TOKEN_URL,
            data=urlencode(
                {
                    "client_id": self.client_id,
                    "client_secret": self.client_secret,
                    "refresh_token": self.refresh_token,
                    "grant_type": "refresh_token",
                }
            ).encode("utf-8"),
            headers={"Content-Type": "application/x-www-form-urlencoded"},
            method="POST",
        )
        payload = self._open_json(request)
        token = str(payload.get("access_token", "")).strip()
        if not token:
            raise CalendarApiError("Google OAuth не вернул access token.")
        expires_in = int(payload.get("expires_in", 3600))
        self._access_token = token
        self._access_token_expires_at = now + timedelta(seconds=max(expires_in - 60, 60))
        return token

    def _request(
        self,
        method: str,
        path: str,
        *,
        query: dict[str, str] | None = None,
        body: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        url = f"{GOOGLE_CALENDAR_API_URL}{path}"
        if query:
            url = f"{url}?{urlencode(query)}"
        data = json.dumps(body).encode("utf-8") if body is not None else None
        request = Request(
            url,
            data=data,
            headers={
                "Authorization": f"Bearer {self._get_access_token()}",
                "Accept": "application/json",
                **({"Content-Type": "application/json"} if data is not None else {}),
            },
            method=method,
        )
        return self._open_json(request)

    @staticmethod
    def _open_json(request: Request) -> dict[str, Any]:
        try:
            with urlopen(request, timeout=20) as response:
                raw = response.read()
        except HTTPError as exc:
            try:
                detail = json.loads(exc.read().decode("utf-8")).get("error", {}).get("message", "")
            except (ValueError, AttributeError):
                detail = ""
            raise CalendarApiError(detail or f"Google Calendar API вернул HTTP {exc.code}.") from exc
        except URLError as exc:
            raise CalendarApiError("Не удалось подключиться к Google Calendar API.") from exc
        if not raw:
            return {}
        try:
            return json.loads(raw.decode("utf-8"))
        except ValueError as exc:
            raise CalendarApiError("Google Calendar API вернул некорректный JSON.") from exc

    @staticmethod
    def _normalize_task(item: dict[str, Any]) -> dict[str, Any]:
        private = item.get("extendedProperties", {}).get("private", {})
        start = item.get("start", {})
        return {
            "id": str(item.get("id", "")),
            "title": str(item.get("summary", "Без названия")),
            "notes": str(item.get("description", "")),
            "due_at": str(start.get("dateTime") or start.get("date") or ""),
            "completed": private.get("atlasDone") == "true",
            "html_link": str(item.get("htmlLink", "")),
        }
