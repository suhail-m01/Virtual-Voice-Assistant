"""Lazy speech-to-text adapter preserving the Aura 2024 browser pipeline."""
from __future__ import annotations

from pathlib import Path
import time
from typing import Optional

from .config import load_settings


def QueryModifier(query: str) -> str:
    clean = str(query).lower().strip()
    if not clean:
        return ""
    words = clean.split()
    question_words = ("how", "what", "who", "where", "when", "why", "which", "whose", "whom", "can you")
    punctuation = "?" if any(clean.startswith(word + " ") or clean == word for word in question_words) else "."
    clean = clean.rstrip(".!?") + punctuation
    return clean.capitalize()


def UniversalTranslator(text: str) -> str:
    try:
        import mtranslate as mt
        return mt.translate(text, "en", "auto").capitalize()
    except Exception:
        return text


def SpeechRecognition(*, timeout_seconds: int = 120) -> str:
    settings = load_settings()
    try:
        from selenium import webdriver
        from selenium.webdriver.common.by import By
        from selenium.webdriver.chrome.service import Service
        from selenium.webdriver.chrome.options import Options
        from webdriver_manager.chrome import ChromeDriverManager
    except ImportError as exc:
        raise RuntimeError("Speech recognition dependencies are not installed") from exc
    voice_file = settings.data_dir / "Voice.html"
    html = f'''<!doctype html><html><body><button id="start">Start</button><button id="end">Stop</button><p id="output"></p><script>let r;start.onclick=()=>{{r=new (webkitSpeechRecognition||SpeechRecognition)();r.lang={settings.input_language!r};r.continuous=true;r.onresult=e=>output.textContent+=e.results[e.results.length-1][0].transcript;r.start()}};end.onclick=()=>r&&r.stop();</script></body></html>'''
    voice_file.write_text(html, encoding="utf-8")
    options = Options()
    options.add_argument("--use-fake-ui-for-media-stream")
    options.add_argument("--headless-new")
    driver = webdriver.Chrome(service=Service(ChromeDriverManager().install()), options=options)
    try:
        driver.get(voice_file.as_uri())
        driver.find_element(By.ID, "start").click()
        start = time.monotonic()
        while time.monotonic() - start < timeout_seconds:
            text = driver.find_element(By.ID, "output").text
            if text:
                driver.find_element(By.ID, "end").click()
                return QueryModifier(text) if settings.input_language.lower().startswith("en") else QueryModifier(UniversalTranslator(text))
            time.sleep(0.1)
        raise TimeoutError("Speech recognition timed out")
    finally:
        driver.quit()


SetAssistantStatus = lambda status: None

if __name__ == "__main__":
    print(SpeechRecognition())
