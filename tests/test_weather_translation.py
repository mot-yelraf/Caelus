import requests
import pytest

from caelus.weather_translation import WeatherTranslator


@pytest.mark.parametrize(("language", "target"), [("es-419", "es"), ("fr-CA", "fr-CA")])
def test_translator_keeps_paragraphs_and_reuses_exact_source(monkeypatch, language, target):
    calls = []

    class Response:
        def raise_for_status(self):
            pass

        def json(self):
            return {"data": {"translations": [{"translatedText": f"ES {text}"} for text in calls[-1]]}}

    def translate(_url, **kwargs):
        assert kwargs["json"]["format"] == "text"
        assert kwargs["json"]["target"] == target
        calls.append(kwargs["json"]["q"])
        return Response()

    monkeypatch.setattr(requests, "post", translate)
    translator = WeatherTranslator("test-key")
    original = {"description": "First.\n\nSecond.", "instruction": "Act now."}
    assert translator.translate(original, language) == {
        "description": "ES First.\n\nES Second.", "instruction": "ES Act now.",
    }
    translator.translate(original, language)
    translator.translate({**original, "instruction": "Updated."}, language)
    assert calls == [["First.", "Second.", "Act now."], ["First.", "Second.", "Updated."]]


def test_translation_timeout_returns_no_result_and_backs_off(monkeypatch):
    calls = []

    def timeout(*_args, **_kwargs):
        calls.append(1)
        raise requests.Timeout

    monkeypatch.setattr(requests, "post", timeout)
    translator = WeatherTranslator("test-key")
    assert translator.translate({"narrative": "Forecast."}, "es-419") is None
    assert translator.translate({"narrative": "Forecast."}, "es-419") is None
    assert len(calls) == 1


def test_partial_response_does_not_expose_incomplete_alert(monkeypatch):
    class Response:
        def raise_for_status(self):
            pass

        def json(self):
            return {"data": {"translations": [{"translatedText": "Aviso"}]}}

    monkeypatch.setattr(requests, "post", lambda *_args, **_kwargs: Response())
    assert WeatherTranslator("test-key").translate(
        {"headline": "Warning", "instruction": "Take shelter immediately."}, "es-419"
    ) is None
