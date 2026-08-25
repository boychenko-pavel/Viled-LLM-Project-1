from __future__ import annotations

import pytest

from sql_agent.hh_api import HhApiClient, HhApiError, ResumeSearch, VacancySearch


class FakeResponse:
    def __init__(self, payload, status_code: int = 200) -> None:
        self.payload = payload
        self.status_code = status_code
        self.ok = 200 <= status_code < 300

    def json(self):
        return self.payload


class FakeSession:
    def __init__(self, response: FakeResponse) -> None:
        self.response = response
        self.calls = []

    def get(self, url, **kwargs):
        self.calls.append((url, kwargs))
        return self.response


def test_vacancy_search_builds_hh_kz_parameters() -> None:
    params = VacancySearch(
        text=" HR manager ",
        area="160",
        experience="between1And3",
        salary=500_000,
        only_with_salary=True,
        period=7,
    ).as_params()

    assert params == {
        "host": "hh.kz",
        "locale": "RU",
        "text": "HR manager",
        "area": "160",
        "experience": "between1And3",
        "salary": 500_000,
        "currency": "KZT",
        "label": "with_salary",
        "period": 7,
        "order_by": "publication_time",
        "page": 0,
        "per_page": 20,
    }


def test_client_sends_required_headers_and_normalizes_vacancy() -> None:
    session = FakeSession(
        FakeResponse(
            {
                "found": 1,
                "page": 0,
                "pages": 1,
                "per_page": 20,
                "items": [
                    {
                        "id": "123",
                        "name": "HR manager",
                        "employer": {"name": "Viled"},
                        "area": {"name": "Алматы"},
                        "experience": {"name": "От 1 года до 3 лет"},
                        "salary": {"from": 500000, "to": 700000, "currency": "KZT", "gross": False},
                        "published_at": "2026-08-06T10:00:00+0600",
                        "alternate_url": "https://hh.kz/vacancy/123",
                        "snippet": {"requirement": "Опыт", "responsibility": "Подбор"},
                    }
                ],
            }
        )
    )
    client = HhApiClient(
        access_token="secret-token",
        user_agent="ViledATLAS/1.0 (hr@example.com)",
        session=session,
    )

    result = client.search_vacancies(VacancySearch(text="HR manager"))

    assert result["items"][0]["employer"] == "Viled"
    assert result["items"][0]["salary_from"] == 500000
    _, request = session.calls[0]
    assert request["params"]["host"] == "hh.kz"
    assert request["params"]["area"] == "40"
    assert request["headers"]["Authorization"] == "Bearer secret-token"
    assert request["headers"]["HH-User-Agent"] == "ViledATLAS/1.0 (hr@example.com)"


@pytest.mark.parametrize(
    "search",
    [
        VacancySearch(text=""),
        VacancySearch(text="HR", period=31),
        VacancySearch(text="HR", area="Алматы"),
        VacancySearch(text="HR", page=20, per_page=100),
    ],
)
def test_invalid_search_is_rejected(search: VacancySearch) -> None:
    with pytest.raises(ValueError):
        search.as_params()


def test_client_requires_token_and_user_agent() -> None:
    with pytest.raises(HhApiError, match="HH_APPLICATION_NAME"):
        HhApiClient(access_token="token", user_agent="").search_vacancies(
            VacancySearch(text="HR")
        )

    with pytest.raises(HhApiError, match="HH_CLIENT_ID"):
        HhApiClient(access_token="", user_agent="App/1.0 (hr@example.com)").search_vacancies(
            VacancySearch(text="HR")
        )


def test_resume_search_builds_hh_kz_parameters() -> None:
    params = ResumeSearch(
        text=" продавец-консультант ",
        area="160",
        experience="between1And3",
        salary_from=300_000,
        salary_to=800_000,
        only_with_salary=True,
        education_level="higher",
        job_search_status="active_search",
        period=7,
    ).as_params()

    assert params == {
        "host": "hh.kz",
        "locale": "RU",
        "text": "продавец-консультант",
        "area": "160",
        "experience": "between1And3",
        "education_level": "higher",
        "job_search_status": "active_search",
        "salary_from": 300_000,
        "salary_to": 800_000,
        "currency": "KZT",
        "label": "only_with_salary",
        "period": 7,
        "order_by": "publication_time",
        "page": 0,
        "per_page": 20,
    }


@pytest.mark.parametrize(
    "search",
    [
        ResumeSearch(text=""),
        ResumeSearch(text="HR", education_level="phd"),
        ResumeSearch(text="HR", job_search_status="maybe"),
        ResumeSearch(text="HR", salary_from=900_000, salary_to=300_000),
        ResumeSearch(text="HR", period=31),
    ],
)
def test_invalid_resume_search_is_rejected(search: ResumeSearch) -> None:
    with pytest.raises(ValueError):
        search.as_params()


def test_client_normalizes_resume_item() -> None:
    session = FakeSession(
        FakeResponse(
            {
                "found": 1,
                "page": 0,
                "pages": 1,
                "per_page": 20,
                "items": [
                    {
                        "id": "res-1",
                        "title": "Продавец-консультант",
                        "first_name": "Иван",
                        "last_name": "Иванов",
                        "age": 29,
                        "gender": {"id": "male", "name": "Мужской"},
                        "area": {"name": "Алматы"},
                        "salary": {"amount": 450000, "currency": "KZT"},
                        "total_experience": {"months": 38},
                        "education": {"level": {"name": "Высшее"}},
                        "job_search_status": {"name": "Активно ищет работу"},
                        "experience": [{"company": "Viled", "position": "Продавец"}],
                        "updated_at": "2026-08-05T09:00:00+0600",
                        "alternate_url": "https://hh.kz/resume/res-1",
                    }
                ],
            }
        )
    )
    client = HhApiClient(
        access_token="secret-token",
        user_agent="ViledATLAS/1.0 (hr@example.com)",
        session=session,
    )

    result = client.search_resumes(ResumeSearch(text="Продавец"))

    item = result["items"][0]
    assert item["full_name"] == "Иванов Иван"
    assert item["salary_amount"] == 450000
    assert item["total_experience_months"] == 38
    assert item["education_level"] == "Высшее"
    assert item["last_company"] == "Viled"
    url, request = session.calls[0]
    assert url.endswith("/resumes")
    assert request["params"]["host"] == "hh.kz"
    assert request["params"]["area"] == "40"


def test_resume_search_forbidden_explains_employer_token() -> None:
    session = FakeSession(FakeResponse({"description": "Forbidden"}, status_code=403))
    client = HhApiClient(
        access_token="secret-token",
        user_agent="ViledATLAS/1.0 (hr@example.com)",
        session=session,
    )

    with pytest.raises(HhApiError, match="менеджера работодателя") as error:
        client.search_resumes(ResumeSearch(text="Продавец"))
    assert error.value.status_code == 403


def test_client_obtains_and_reuses_application_token() -> None:
    class TokenSession:
        def __init__(self) -> None:
            self.post_calls = []
            self.get_calls = []

        def post(self, url, **kwargs):
            self.post_calls.append((url, kwargs))
            return FakeResponse({"access_token": "application-token"})

        def get(self, url, **kwargs):
            self.get_calls.append((url, kwargs))
            return FakeResponse({"found": 0, "page": 0, "pages": 0, "per_page": 20, "items": []})

    session = TokenSession()
    client = HhApiClient(
        client_id="client-id",
        client_secret="client-secret",
        application_name="Viled ATLAS",
        session=session,
    )

    client.search_vacancies(VacancySearch(text="HR"))
    client.search_vacancies(VacancySearch(text="HR"))

    assert len(session.post_calls) == 1
    assert session.post_calls[0][1]["data"]["grant_type"] == "client_credentials"
    assert session.get_calls[0][1]["headers"]["Authorization"] == "Bearer application-token"
