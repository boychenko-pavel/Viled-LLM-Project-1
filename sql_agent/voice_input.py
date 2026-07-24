"""Isolated local speech-to-text support for the web voice input.

Keep voice recording/transcription concerns in this module. Other agent,
database, and chat orchestration code should depend only on ``VoiceInputService``
and should not import faster-whisper directly.
"""

from __future__ import annotations

from dataclasses import dataclass
from io import BytesIO
import os
from pathlib import Path
import re
from threading import Lock
from typing import Any, Callable


PROJECT_DIR = Path(__file__).resolve().parent.parent
DEFAULT_MODEL_DIR = PROJECT_DIR / ".models" / "faster-whisper"

_SPOKEN_DIGITS = {
    "ноль": "0",
    "нуль": "0",
    "один": "1",
    "одна": "1",
    "два": "2",
    "две": "2",
    "три": "3",
    "четыре": "4",
    "пять": "5",
    "шесть": "6",
    "семь": "7",
    "восемь": "8",
    "девять": "9",
}
_DIGIT_WORD = "|".join(_SPOKEN_DIGITS)
_DIGIT_SEQUENCE_RE = re.compile(
    rf"\b(?:{_DIGIT_WORD})(?:(?:\s*[-–—,]\s*|\s+)(?:{_DIGIT_WORD})){{3,}}\b",
    re.IGNORECASE,
)
_DIGIT_WORD_RE = re.compile(rf"\b(?:{_DIGIT_WORD})\b", re.IGNORECASE)


def normalize_spoken_digit_sequences(text: str) -> str:
    """Convert sequences of four or more separately spoken digits to a number."""

    def replace(match: re.Match[str]) -> str:
        words = _DIGIT_WORD_RE.findall(match.group(0))
        return "".join(_SPOKEN_DIGITS[word.casefold()] for word in words)

    return _DIGIT_SEQUENCE_RE.sub(replace, text)


class VoiceInputError(RuntimeError):
    """Base error for local voice transcription."""


class VoiceInputUnavailableError(VoiceInputError):
    """Raised when faster-whisper is not installed or cannot be initialized."""


@dataclass(frozen=True)
class VoiceTranscription:
    text: str
    language: str | None
    duration_seconds: float | None


class VoiceInputService:
    """Lazily loads faster-whisper and serializes local transcription calls."""

    def __init__(
        self,
        *,
        model_name: str | None = None,
        device: str | None = None,
        compute_type: str | None = None,
        language: str | None = None,
        download_root: Path | None = None,
        model_factory: Callable[..., Any] | None = None,
    ) -> None:
        self.model_name = model_name or os.getenv("VOICE_MODEL", "small")
        self.device = device or os.getenv("VOICE_DEVICE", "cpu")
        self.compute_type = compute_type or os.getenv("VOICE_COMPUTE_TYPE", "int8")
        configured_language = language or os.getenv("VOICE_LANGUAGE", "ru")
        self.language = None if configured_language.lower() == "auto" else configured_language
        configured_root = os.getenv("VOICE_MODEL_DIR")
        self.download_root = download_root or (
            Path(configured_root) if configured_root else DEFAULT_MODEL_DIR
        )
        self._model_factory = model_factory
        self._model: Any | None = None
        self._lock = Lock()

    def _create_model(self) -> Any:
        model_factory = self._model_factory
        if model_factory is None:
            try:
                from faster_whisper import WhisperModel
            except ImportError as exc:
                raise VoiceInputUnavailableError(
                    "faster-whisper is not installed. Install project dependencies first."
                ) from exc
            model_factory = WhisperModel

        self.download_root.mkdir(parents=True, exist_ok=True)
        try:
            return model_factory(
                self.model_name,
                device=self.device,
                compute_type=self.compute_type,
                download_root=str(self.download_root),
            )
        except Exception as exc:
            raise VoiceInputUnavailableError(
                "The local speech recognition model could not be loaded."
            ) from exc

    def transcribe(self, audio: bytes) -> VoiceTranscription:
        if not audio:
            raise VoiceInputError("The audio recording is empty.")

        with self._lock:
            if self._model is None:
                self._model = self._create_model()
            try:
                segments, info = self._model.transcribe(
                    BytesIO(audio),
                    language=self.language,
                    beam_size=5,
                    vad_filter=True,
                    condition_on_previous_text=False,
                    initial_prompt=(
                        "Запрос к базе данных. Идентификаторы и артикулы записывай цифрами, "
                        "например: товар 1231234."
                    ),
                )
                text = " ".join(segment.text.strip() for segment in segments).strip()
                text = normalize_spoken_digit_sequences(text)
            except Exception as exc:
                raise VoiceInputError("The audio recording could not be transcribed.") from exc

        return VoiceTranscription(
            text=text,
            language=getattr(info, "language", self.language),
            duration_seconds=getattr(info, "duration", None),
        )
