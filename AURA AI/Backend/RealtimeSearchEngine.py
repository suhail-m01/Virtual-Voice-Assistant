"""Real-time search compatibility adapter."""
from __future__ import annotations

import datetime
from urllib.parse import quote_plus
import webbrowser

from .AI.provider_registry import ProviderRouter, registry_from_settings
from .config import load_settings
from .Persistence.legacy_chatlog import LegacyChatLog
from .Security.privacy import redact_sensitive


def AnswerModifier(answer: str) -> str:
    return "\n".join(line.strip() for line in str(answer).splitlines() if line.strip())


def GoogleSearch(query: str):
    try:
        from googlesearch import search
        results = list(search(query, advanced=True, num_results=5))
        return "\n".join(f"Title: {getattr(item, 'title', '')}\nDescription: {getattr(item, 'description', '')}" for item in results)
    except Exception:
        url = "https://www.google.com/search?q=" + quote_plus(query)
        webbrowser.open(url)
        return f"Search opened for {query}."


def Information() -> str:
    now = datetime.datetime.now()
    return now.strftime("Day: %A\nDate: %d %B %Y\nTime: %H:%M:%S")


def RealtimeSearchEngine(prompt: str) -> str:
    safe = redact_sensitive(prompt)
    if safe.redacted:
        return "Aura does not retain payment credentials."
    settings = load_settings()
    router = ProviderRouter(registry_from_settings(settings), preferred=settings.llm_provider)
    history = LegacyChatLog(settings.data_dir / "ChatLog.json")
    records = history.read()
    search_data = GoogleSearch(safe.text)
    context = records[-8:] + [{"role": "system", "content": "Current time:\n" + Information()}, {"role": "system", "content": search_data}]
    history.append("user", safe.text)
    try:
        response = router.generate("Answer using the search data below. Be concise and do not invent facts.\n" + search_data, context=context)
        answer = AnswerModifier(response.text)
    except Exception:
        answer = AnswerModifier(search_data)
    history.append("assistant", answer)
    return answer


if __name__ == "__main__":
    while True:
        print(RealtimeSearchEngine(input("Enter Your Query: ")))
