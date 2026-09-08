# AURA 2026

# 🎙️ Aura — Intelligent Virtual Voice Assistant

Aura is a Python-based intelligent voice assistant designed to combine
natural voice interaction, AI reasoning, automation, and external APIs
into a unified assistant.

## ✨ Features

- 🎤 Voice command recognition
- 💬 Natural-language interaction
- 🧠 LLM-powered responses
- 🌐 Real-time API integration
- ⚙️ Task automation
- 🖥️ Interactive user interface
- 🔊 Text-to-speech responses
- 🔌 Modular architecture for adding new capabilities

## 🏗️ Architecture

User Voice
    ↓
Speech Recognition
    ↓
Intent Understanding
    ↓
AI / LLM Engine
    ↓
Tool & API Router
    ↓
External Services / Automation
    ↓
Response Generation
    ↓
Text-to-Speech
    ↓
User

## 🛠️ Tech Stack

Python
Speech Recognition
Text-to-Speech
LLM APIs
REST APIs
GUI Framework
JSON

## 🚀 Getting Started

### Clone

git clone <repository>

### Install dependencies

pip install -r requirements.txt

### Run

python main.py

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
