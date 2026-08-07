from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import requests

from sql_agent.config import (
    HH_ACCESS_TOKEN,
    HH_API_BASE_URL,
    HH_APPLICATION_NAME,
    HH_CLIENT_ID,
    HH_CLIENT_SECRET,
    HH_USER_AGENT,
)


KAZAKHSTAN_AREA_ID = "40"
ALLOWED_ORDER_VALUES = {"relevance", "publication_time", "salary_desc", "salary_asc"}
ALLOWED_EXPERIENCE_VALUES = {"noExperience", "between1And3", "between3And6", "moreThan6"}


class HhApiError(RuntimeError):
    def __init__(self, message: str, status_code: int = 502) -> None:
        super().__init__(message)
        self.status_code = status_code


@dataclass(frozen=True)
class VacancySearch:
    text: str
    area: str = KAZAKHSTAN_AREA_ID
    experience: str | None = None
    salary: int | None = None
    only_with_salary: bool = False
    period: int | None = None
    order_by: str = "publication_time"
    page: int = 0
    per_page: int = 20

    def as_params(self) -> dict[str, str | int]:
        text = self.text.strip()
        if not text:
            raise ValueError("Укажите должность или ключевые слова для поиска.")
        if len(text) > 3000:
            raise ValueError("Поисковая фраза не должна превышать 3000 символов.")
        if not self.area.isdigit():
            raise ValueError("Некорректный идентификатор региона hh.")
        if self.experience and self.experience not in ALLOWED_EXPERIENCE_VALUES:
            raise ValueError("Некорректное значение опыта работы.")
        if self.salary is not None and self.salary < 0:
            raise ValueError("Зарплата не может быть отрицательной.")
        if self.period is not None and not 1 <= self.period <= 30:
            raise ValueError("Период публикации должен быть от 1 до 30 дней.")
        if self.order_by not in ALLOWED_ORDER_VALUES:
            raise ValueError("Некорректная сортировка вакансий.")
        if not 1 <= self.per_page <= 100:
            raise ValueError("Количество вакансий на странице должно быть от 1 до 100.")
        if self.page < 0 or self.page * self.per_page >= 2000:
            raise ValueError("API hh позволяет просматривать не более 2000 результатов поиска.")

        params: dict[str, str | int] = {
            "host": "hh.kz",
            "locale": "RU",
            "text": text,
            "area": self.area,
            "order_by": self.order_by,
            "page": self.page,
            "per_page": self.per_page,
        }
        if self.experience:
            params["experience"] = self.experience
        if self.salary is not None:
            params["salary"] = self.salary
            params["currency"] = "KZT"
        if self.only_with_salary:
            params["label"] = "with_salary"
        if self.period is not None:
            params["period"] = self.period
        return params


class HhApiClient:
    def __init__(
        self,
        access_token: str = HH_ACCESS_TOKEN,
        user_agent: str = HH_USER_AGENT,
        client_id: str = HH_CLIENT_ID,
        client_secret: str = HH_CLIENT_SECRET,
        application_name: str = HH_APPLICATION_NAME,
        base_url: str = HH_API_BASE_URL,
        session: requests.Session | None = None,
    ) -> None:
        self.access_token = access_token.strip()
        self.user_agent = user_agent.strip() or application_name.strip()
        self.client_id = client_id.strip()
        self.client_secret = client_secret.strip()
        self.base_url = base_url.rstrip("/")
        self.session = session or requests.Session()

    @property
    def configured(self) -> bool:
        return bool(self.user_agent and (self.access_token or (self.client_id and self.client_secret)))

    def search_vacancies(self, search: VacancySearch) -> dict[str, Any]:
        payload = self._get("/vacancies", params=search.as_params())
        return {
            "found": int(payload.get("found") or 0),
            "page": int(payload.get("page") or 0),
            "pages": int(payload.get("pages") or 0),
            "per_page": int(payload.get("per_page") or search.per_page),
            "items": [self._vacancy_item(item) for item in payload.get("items") or []],
        }

    def kazakhstan_areas(self) -> list[dict[str, str]]:
        countries = self._get("/areas", params={"host": "hh.kz", "locale": "RU"})
        kazakhstan = next(
            (country for country in countries if str(country.get("id")) == KAZAKHSTAN_AREA_ID),
            None,
        )
        if not kazakhstan:
            return [{"id": KAZAKHSTAN_AREA_ID, "name": "Казахстан"}]
        result = [{"id": KAZAKHSTAN_AREA_ID, "name": "Весь Казахстан"}]
        self._flatten_areas(kazakhstan.get("areas") or [], result)
        return result

    def _get(self, path: str, params: dict[str, Any]) -> Any:
        if not self.user_agent:
            raise HhApiError(
                "Не задан HH_APPLICATION_NAME. Укажите название приложения hh.",
                status_code=503,
            )
        access_token = self._authorization_token()

        try:
            response = self.session.get(
                f"{self.base_url}{path}",
                params=params,
                headers={
                    "Authorization": f"Bearer {access_token}",
                    "HH-User-Agent": self.user_agent,
                    "Accept": "application/json",
                },
                timeout=20,
            )
        except requests.RequestException as exc:
            raise HhApiError("Не удалось подключиться к API hh.kz.") from exc

        if response.ok:
            return response.json()

        detail = self._error_detail(response)
        if response.status_code == 401:
            detail = "OAuth-токен hh недействителен или истёк."
        elif response.status_code == 403:
            detail = "API hh отклонил запрос: проверьте права токена или требование CAPTCHA."
        elif response.status_code == 429:
            detail = "Превышен лимит запросов API hh. Повторите поиск позже."
        raise HhApiError(detail, status_code=response.status_code)

    def _authorization_token(self) -> str:
        if self.access_token:
            return self.access_token
        if not self.client_id or not self.client_secret:
            raise HhApiError(
                "Не заданы HH_CLIENT_ID и HH_CLIENT_SECRET в secrets/HH_API.env.",
                status_code=503,
            )

        try:
            response = self.session.post(
                f"{self.base_url}/token",
                data={
                    "grant_type": "client_credentials",
                    "client_id": self.client_id,
                    "client_secret": self.client_secret,
                },
                headers={
                    "HH-User-Agent": self.user_agent,
                    "Content-Type": "application/x-www-form-urlencoded",
                    "Accept": "application/json",
                },
                timeout=20,
            )
        except requests.RequestException as exc:
            raise HhApiError("Не удалось получить токен приложения hh.") from exc

        if not response.ok:
            raise HhApiError(
                self._error_detail(response),
                status_code=response.status_code,
            )
        token = str(response.json().get("access_token") or "").strip()
        if not token:
            raise HhApiError("API hh не вернул access_token.")
        self.access_token = token
        return token

    @staticmethod
    def _error_detail(response: requests.Response) -> str:
        try:
            payload = response.json()
        except ValueError:
            return f"API hh вернул ошибку HTTP {response.status_code}."
        return str(payload.get("description") or f"API hh вернул ошибку HTTP {response.status_code}.")

    @staticmethod
    def _flatten_areas(areas: list[dict[str, Any]], result: list[dict[str, str]]) -> None:
        for area in areas:
            area_id = str(area.get("id") or "")
            name = str(area.get("name") or "")
            if area_id and name:
                result.append({"id": area_id, "name": name})
            HhApiClient._flatten_areas(area.get("areas") or [], result)

    @staticmethod
    def _vacancy_item(item: dict[str, Any]) -> dict[str, Any]:
        salary = item.get("salary_range") or item.get("salary")
        employer = item.get("employer") or {}
        area = item.get("area") or {}
        experience = item.get("experience") or {}
        return {
            "id": str(item.get("id") or ""),
            "name": str(item.get("name") or ""),
            "employer": str(employer.get("name") or ""),
            "area": str(area.get("name") or ""),
            "experience": str(experience.get("name") or ""),
            "salary_from": salary.get("from") if salary else None,
            "salary_to": salary.get("to") if salary else None,
            "salary_currency": str(salary.get("currency") or "") if salary else "",
            "salary_gross": salary.get("gross") if salary else None,
            "published_at": str(item.get("published_at") or ""),
            "url": str(item.get("alternate_url") or ""),
            "snippet_requirement": str((item.get("snippet") or {}).get("requirement") or ""),
            "snippet_responsibility": str((item.get("snippet") or {}).get("responsibility") or ""),
        }
