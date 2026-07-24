from types import SimpleNamespace

import pytest

from sql_agent.voice_input import (
    VoiceInputError,
    VoiceInputService,
    normalize_spoken_digit_sequences,
)


class FakeWhisperModel:
    def __init__(self) -> None:
        self.calls = 0

    def transcribe(self, audio, **kwargs):
        self.calls += 1
        assert audio.read() == b"audio"
        assert kwargs["language"] == "ru"
        segments = [
            SimpleNamespace(text=" Первый фрагмент "),
            SimpleNamespace(text="второй фрагмент."),
        ]
        return iter(segments), SimpleNamespace(language="ru", duration=1.25)


def test_voice_service_loads_model_lazily_and_combines_segments(tmp_path):
    model = FakeWhisperModel()
    factory_calls = []

    def model_factory(model_name, **kwargs):
        factory_calls.append((model_name, kwargs))
        return model

    service = VoiceInputService(
        model_name="small",
        language="ru",
        download_root=tmp_path,
        model_factory=model_factory,
    )

    assert factory_calls == []
    result = service.transcribe(b"audio")
    service.transcribe(b"audio")

    assert result.text == "Первый фрагмент второй фрагмент."
    assert result.language == "ru"
    assert result.duration_seconds == 1.25
    assert len(factory_calls) == 1
    assert model.calls == 2


def test_voice_service_rejects_empty_audio(tmp_path):
    service = VoiceInputService(
        download_root=tmp_path,
        model_factory=lambda *args, **kwargs: FakeWhisperModel(),
    )

    with pytest.raises(VoiceInputError, match="empty"):
        service.transcribe(b"")


@pytest.mark.parametrize(
    ("source", "expected"),
    [
        (
            "Себе с товаром один-два-три, один-два-три, четыре.",
            "Себе с товаром 1231234.",
        ),
        ("товар ноль один два три четыре", "товар 01234"),
        ("за один или два дня", "за один или два дня"),
    ],
)
def test_normalizes_long_spoken_digit_sequences(source, expected):
    assert normalize_spoken_digit_sequences(source) == expected
