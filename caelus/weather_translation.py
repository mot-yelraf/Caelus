"""On-demand translation of published weather text."""

import logging
import re
from collections import OrderedDict
from threading import Lock
from time import monotonic

import requests

LOGGER = logging.getLogger(__name__)
TRANSLATION_URL = "https://translation.googleapis.com/language/translate/v2"
TARGETS = {
    "ar": "ar",
    "de-DE": "de",
    "es-419": "es",
    "fr-CA": "fr-CA",
    "hi-IN": "hi",
    "it-IT": "it",
    "ja-JP": "ja",
    "nl-NL": "nl",
    "pl-PL": "pl",
    "pt-BR": "pt-BR",
    "uk-UA": "uk",
    "zh-Hans-CN": "zh-CN",
}
ALERT_TRANSLATION_FIELDS = ("event", "headline", "description", "instruction")
PARAGRAPH_BREAK = re.compile(r"(\r?\n[ \t]*\r?\n(?:[ \t]*\r?\n)*)")


class WeatherTranslator:
    """Translate plain text while sharing a bounded cache across viewers."""

    def __init__(self, api_key: str):
        self._api_key = api_key
        self._lock = Lock()
        self._cache: OrderedDict[tuple[str, tuple[tuple[str, str], ...]], dict[str, str]] = OrderedDict()
        self._retry_at = 0.0

    def translate(self, source: dict[str, str], language: str) -> dict[str, str] | None:
        """Return a complete translation or let callers keep displaying the original."""
        target = TARGETS.get(language)
        if not target or not any(source.values()) or sum(map(len, source.values())) > 20000:
            return None
        key = (target, tuple(source.items()))
        with self._lock:
            if key in self._cache:
                self._cache.move_to_end(key)
                return self._cache[key].copy()
            if monotonic() < self._retry_at:
                return None
            parts = {field: PARAGRAPH_BREAK.split(value) for field, value in source.items()}
            positions = [(field, index) for field, chunks in parts.items()
                         for index in range(0, len(chunks), 2) if chunks[index].strip()]
            if len(positions) > 64:
                return None
            try:
                batch = []
                length = 0
                for field, index in positions:
                    paragraph = parts[field][index]
                    if batch and length + len(paragraph) > 5000:
                        self._translate_batch(parts, batch, target)
                        batch = []
                        length = 0
                    batch.append((field, index))
                    length += len(paragraph)
                if batch:
                    self._translate_batch(parts, batch, target)
            except (requests.RequestException, ValueError, KeyError, TypeError):
                self._retry_at = monotonic() + 60
                LOGGER.warning("Weather translation unavailable. Using the provider's original text.")
                return None
            result = {field: "".join(chunks) for field, chunks in parts.items()}
            self._cache[key] = result
            if len(self._cache) > 128:
                self._cache.popitem(last=False)
            return result.copy()

    def _translate_batch(self, parts: dict, batch: list[tuple[str, int]], target: str) -> None:
        response = requests.post(
            TRANSLATION_URL,
            headers={"X-goog-api-key": self._api_key},
            json={"q": [parts[field][index] for field, index in batch],
                  "source": "en", "target": target, "format": "text"},
            timeout=(3, 5),
            allow_redirects=False,
        )
        response.raise_for_status()
        translated = response.json()["data"]["translations"]
        if len(translated) != len(batch):
            raise ValueError("Incomplete weather translation")
        for (field, index), item in zip(batch, translated, strict=True):
            value = item["translatedText"]
            if not isinstance(value, str) or not value.strip():
                raise ValueError("Empty weather translation")
            parts[field][index] = value
