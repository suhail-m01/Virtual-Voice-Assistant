# AURA 2026

AURA is a secure, agentic, voice-first computer assistant upgraded from the original 2024 PyQt5 application. The existing speech, TTS, search, image, content, media and application capability modules remain available as adapters; the new agent decides **what** to do, while deterministic tools and a security gateway decide **whether and how** it may happen.

## Run

```bash
cd "AURA AI"
python -m pip install -r Requirements.txt
# copy ../.env.example to .env and fill only the providers you intend to use
python main.py
```

Use `python main.py --console` for a non-GUI smoke run. PyQt5 is optional for backend tests but required for the desktop shell. A clean install reports missing AI/provider credentials instead of crashing or executing guessed actions.

## Security defaults

- Payments start **locked** and in **TEST MODE**.
- Financial/destructive/sensitive tools require authentication, permission, policy and exact fresh consent.
- LLM output is strict structured data; it is never Python, shell, or payment authorization.
- No PIN, CVV, OTP, bank password or full card credential is persisted, logged, sent to an LLM, or placed in the audit ledger.
- Local development does not claim TEE attestation. It reports `TEE Mode: Local Development / Hardware Attestation: Unavailable`.

Read [docs/AURA_2026_ARCHITECTURE.md](docs/AURA_2026_ARCHITECTURE.md) for the architecture map, implementation status, schema, setup guides, tests and known limitations.
