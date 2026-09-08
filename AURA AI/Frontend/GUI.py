"""AURA 2026 PyQt5 shell.

The shell is intentionally a presentation layer: long-running agent, network,
speech and tool work happens in a worker thread and communicates through Qt
signals.  Legacy file-based status helpers remain available for the 2024 entry
point and integrations.
"""
from __future__ import annotations

from pathlib import Path
from html import escape
import sys
from typing import Optional

from .theme import stylesheet
from .visualizer import AuraState, AuraVisualizer

PROJECT_DIR = Path(__file__).resolve().parents[1]
TempDirPath = PROJECT_DIR / "Frontend" / "Files"
GraphicsDirPath = PROJECT_DIR / "Frontend" / "Graphics"
TempDirPath.mkdir(parents=True, exist_ok=True)


def TempDirectoryPath(filename: str) -> str:
    return str(TempDirPath / filename)


def GraphicsDirectoryPath(filename: str) -> str:
    return str(GraphicsDirPath / filename)


def AnswerModifier(answer: str) -> str:
    return "\n".join(line.strip() for line in str(answer).splitlines() if line.strip())


def QueryModifier(query: str) -> str:
    clean = str(query).lower().strip()
    if not clean:
        return ""
    question = clean.startswith(("how ", "what ", "who ", "where ", "when ", "why ", "which ", "can you "))
    return clean.rstrip(".!?") + ("?" if question else ".")


def _write(name: str, value: str) -> None:
    TempDirPath.mkdir(parents=True, exist_ok=True)
    (TempDirPath / name).write_text(str(value), encoding="utf-8")


def _read(name: str, default: str = "") -> str:
    try:
        return (TempDirPath / name).read_text(encoding="utf-8")
    except OSError:
        return default


def SetMicrophoneStatus(command: str) -> None:
    _write("Mic.data", command)


def GetMicrophoneStatus() -> str:
    return _read("Mic.data", "False").strip()


def SetAsssistantStatus(status: str) -> None:
    _write("Status.data", status)


def GetAssistantStatus() -> str:
    return _read("Status.data", "Available...")


def ShowTextToScreen(text: str) -> None:
    _write("Responses.data", text)


def MicButtonInitiated() -> None:
    SetMicrophoneStatus("False")


def MicButtonClosed() -> None:
    SetMicrophoneStatus("True")


try:
    from PyQt5.QtCore import QObject, QThread, QTimer, Qt, pyqtSignal, pyqtSlot
    from PyQt5.QtGui import QFont
    from PyQt5.QtWidgets import (
        QApplication, QFrame, QHBoxLayout, QLabel, QLineEdit, QListWidget,
        QListWidgetItem, QMainWindow, QPushButton, QStackedWidget, QTextEdit,
        QVBoxLayout, QWidget,
    )
    PYQT_AVAILABLE = True
except ImportError:  # pragma: no cover - backend test environments may omit Qt
    PYQT_AVAILABLE = False


if PYQT_AVAILABLE:
    class AgentWorker(QObject):
        finished = pyqtSignal(object)
        progress = pyqtSignal(object)

        def __init__(self, services, auth, text):
            super().__init__()
            self.services = services
            self.auth = auth
            self.text = text

        @pyqtSlot()
        def run(self):
            response = self.services.agent.handle(self.text, auth=self.auth, on_event=self.progress.emit)
            self.finished.emit(response)


    class MainWindow(QMainWindow):
        def __init__(self, services=None):
            super().__init__()
            self.services = services
            self._thread: Optional[QThread] = None
            self._worker: Optional[AgentWorker] = None
            self._history: list[str] = []
            self.setObjectName("root")
            self.setWindowTitle("AURA 2026")
            self.resize(1280, 820)
            self.setStyleSheet(stylesheet())
            self._build_shell()
            self._show_page(1)

        def _build_shell(self):
            root = QWidget(); root.setObjectName("root")
            shell = QHBoxLayout(root); shell.setContentsMargins(22, 22, 22, 22); shell.setSpacing(18)
            sidebar = QFrame(); sidebar.setObjectName("sidebar"); sidebar.setFixedWidth(196)
            side = QVBoxLayout(sidebar); side.setContentsMargins(16, 20, 16, 16); side.setSpacing(6)
            brand = QLabel("AURA <span style='color:#7B83FF'>2026</span>"); brand.setTextFormat(Qt.RichText); brand.setObjectName("title")
            side.addWidget(brand); tag = QLabel("SECURE AI ASSISTANT"); tag.setObjectName("eyebrow"); side.addWidget(tag); side.addSpacing(20)
            self.nav = []
            for index, label in enumerate(("Home", "Assistant", "Activity", "Payments", "Security", "Settings", "Profile")):
                button = QPushButton(label); button.setObjectName("nav"); button.setProperty("selected", "false"); button.clicked.connect(lambda checked=False, i=index: self._show_page(i)); side.addWidget(button); self.nav.append(button)
            side.addStretch(); status = QLabel("●  Protected session\n\nLocal controls remain on your device"); status.setObjectName("muted"); side.addWidget(status)
            shell.addWidget(sidebar)
            self.pages = QStackedWidget(); shell.addWidget(self.pages, 1)
            self._add_home(); self._add_assistant(); self._add_activity(); self._add_payments(); self._add_security(); self._add_settings(); self._add_profile()
            self.setCentralWidget(root)

        def _card(self, title: str, subtitle: str = ""):
            card = QFrame(); card.setObjectName("card"); layout = QVBoxLayout(card); layout.setContentsMargins(20, 18, 20, 18); layout.setSpacing(8)
            label = QLabel(title); label.setObjectName("title"); layout.addWidget(label)
            if subtitle:
                sub = QLabel(subtitle); sub.setObjectName("subtitle"); sub.setWordWrap(True); layout.addWidget(sub)
            return card, layout

        def _page_heading(self, eyebrow: str, title: str, subtitle: str):
            wrapper = QWidget(); layout = QVBoxLayout(wrapper); layout.setContentsMargins(20, 12, 20, 12); layout.setSpacing(6)
            e = QLabel(eyebrow.upper()); e.setObjectName("eyebrow"); layout.addWidget(e); t = QLabel(title); t.setObjectName("title"); layout.addWidget(t); s = QLabel(subtitle); s.setObjectName("subtitle"); layout.addWidget(s); layout.addSpacing(18)
            return wrapper, layout

        def _add_home(self):
            page, layout = self._page_heading("AURA / HOME", "Good to see you.", "A calm command center for the work that matters.")
            row = QHBoxLayout();
            for title, value, detail in (("Aura status", "Ready", "Listening is off"), ("Privacy mode", "Balanced", "Local controls preferred"), ("Payment lock", "LOCKED", "Fresh approval required")):
                card, cl = self._card(title); value_label = QLabel(value); value_label.setObjectName("title"); cl.addWidget(value_label); detail_label = QLabel(detail); detail_label.setObjectName("subtitle"); cl.addWidget(detail_label); row.addWidget(card)
            layout.addLayout(row); layout.addStretch(); self.pages.addWidget(page)

        def _add_assistant(self):
            page, layout = self._page_heading("AURA / ASSISTANT", "What can I take care of?", "Voice-first, text-ready, and explicit when an action needs your approval.")
            card, cl = self._card("Assistant")
            self.visualizer = AuraVisualizer(); cl.addWidget(self.visualizer, alignment=Qt.AlignCenter)
            self.chat = QTextEdit(); self.chat.setReadOnly(True); self.chat.setMinimumHeight(160); cl.addWidget(self.chat)
            composer = QHBoxLayout(); self.input = QLineEdit(); self.input.setPlaceholderText("Ask Aura to search, create, open, or explain…"); self.input.returnPressed.connect(self._submit); composer.addWidget(self.input, 1)
            send = QPushButton("Send"); send.setObjectName("primary"); send.clicked.connect(self._submit); composer.addWidget(send)
            voice = QPushButton("Voice"); voice.clicked.connect(self._listen); composer.addWidget(voice)
            stop = QPushButton("Stop"); stop.setObjectName("danger"); stop.clicked.connect(self._stop); composer.addWidget(stop); cl.addLayout(composer)
            self.progress_label = QLabel("Ready"); self.progress_label.setObjectName("subtitle"); cl.addWidget(self.progress_label)
            self.approval_bar = QWidget(); approval_layout = QHBoxLayout(self.approval_bar); approval_layout.setContentsMargins(0, 8, 0, 0)
            self.approval_text = QLabel("Approval required for the exact action above."); self.approval_text.setObjectName("subtitle"); approval_layout.addWidget(self.approval_text, 1)
            approve = QPushButton("Approve"); approve.setObjectName("primary"); approve.clicked.connect(lambda: self._approval_response("yes")); approval_layout.addWidget(approve)
            cancel = QPushButton("Cancel"); cancel.setObjectName("danger"); cancel.clicked.connect(lambda: self._approval_response("cancel")); approval_layout.addWidget(cancel)
            self.approval_bar.hide(); cl.addWidget(self.approval_bar)
            layout.addWidget(card); self.pages.addWidget(page)

        def _simple_page(self, eyebrow, title, subtitle, body):
            page, layout = self._page_heading(eyebrow, title, subtitle); card, cl = self._card(body); label = QLabel("This surface is connected to the same security and persistence services as Assistant."); label.setWordWrap(True); label.setObjectName("subtitle"); cl.addWidget(label); layout.addWidget(card); layout.addStretch(); self.pages.addWidget(page)

        def _add_activity(self): self._simple_page("AURA / ACTIVITY", "Activity", "A user-understandable timeline of Aura actions.", "Recent activity")
        def _add_payments(self): self._simple_page("AURA / PAYMENTS", "Payments", "Razorpay operations stay locked until you deliberately approve them.", "PAYMENTS LOCKED  ·  TEST MODE")
        def _add_security(self): self._simple_page("AURA / SECURITY", "Security", "Authentication, consent, audit integrity, and confidential-computing status.", "Tamper-Evident Audit Ledger  ·  Verify integrity")
        def _add_settings(self): self._simple_page("AURA / SETTINGS", "Settings", "Voice, model, privacy, memory, automation, and security preferences.", "Preferences")
        def _add_profile(self): self._simple_page("AURA / PROFILE", "Profile", "Manage your account and active sessions.", "Signed-in profile")

        def _show_page(self, index: int):
            if hasattr(self, "pages") and index < self.pages.count(): self.pages.setCurrentIndex(index)
            if hasattr(self, "nav"):
                for i, button in enumerate(self.nav): button.setProperty("selected", "true" if i == index else "false"); button.style().unpolish(button); button.style().polish(button)

        def _submit(self):
            text = self.input.text().strip()
            if not text or self._thread and self._thread.isRunning(): return
            self.input.clear(); self.chat.append(f"<b>You</b>  {escape(text)}"); self.visualizer.set_state(AuraState.UNDERSTANDING); self.progress_label.setText("Understanding request…")
            if self.services is None:
                try:
                    from Backend.application import create_application
                    self.services = create_application()
                except Exception:
                    self.chat.append("<b>Aura</b>  The backend is not configured yet."); self.visualizer.set_state(AuraState.WARNING); return
            auth = self.services.local_context()
            self._thread = QThread(); self._worker = AgentWorker(self.services, auth, text); self._worker.moveToThread(self._thread); self._thread.started.connect(self._worker.run); self._worker.progress.connect(self._on_progress); self._worker.finished.connect(self._on_result); self._worker.finished.connect(self._thread.quit); self._thread.finished.connect(self._thread.deleteLater); self._thread.start()

        def _listen(self):
            SetMicrophoneStatus("True")
            self.visualizer.set_state(AuraState.LISTENING)
            self.progress_label.setText("Listening…")

        def _approval_response(self, value: str):
            self.input.setText(value)
            self._submit()

        def _on_progress(self, event):
            self.progress_label.setText(event.message or event.status or event.kind); mapping = {"approval_required": AuraState.AWAITING_APPROVAL, "tool_start": AuraState.EXECUTING, "tool_complete": AuraState.SUCCESS, "tool_failure": AuraState.ERROR}; self.visualizer.set_state(mapping.get(event.kind, AuraState.THINKING))

        def _on_result(self, response):
            self.chat.append(f"<b>Aura</b>  {escape(response.message)}"); self.progress_label.setText(response.message); self.approval_text.setText(response.message); self.approval_bar.setVisible(response.awaiting_approval); self.visualizer.set_state(AuraState.AWAITING_APPROVAL if response.awaiting_approval else AuraState.SUCCESS if response.status.value == "COMPLETE" else AuraState.ERROR); self._worker = None; self._thread = None

        def _stop(self):
            if self.services: self.services.agent.stop(self.services.local_context().user_id); self.progress_label.setText("Stop requested."); self.visualizer.set_state(AuraState.WARNING)


    def GraphicalUserInterface(services=None):
        app = QApplication.instance() or QApplication(sys.argv)
        window = MainWindow(services); window.show(); return app.exec_()
else:
    class MainWindow:  # pragma: no cover
        def __init__(self, *args, **kwargs): raise RuntimeError("PyQt5 is not installed")

    def GraphicalUserInterface(services=None):  # pragma: no cover
        raise RuntimeError("PyQt5 is not installed; install Requirements.txt to launch the desktop shell")
