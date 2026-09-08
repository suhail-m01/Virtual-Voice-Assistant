"""AURA 2026 restrained dark design system."""

BACKGROUND = "#0B0D12"
SURFACE = "#12151D"
SURFACE_ELEVATED = "#181C26"
BORDER = "#252B37"
TEXT = "#F2F4F8"
MUTED = "#929AAA"
ACCENT = "#7B83FF"
ACCENT_SOFT = "#4C55B5"
SUCCESS = "#65D6A2"
WARNING = "#F6C976"
ERROR = "#FF7F91"


def stylesheet() -> str:
    return f"""
    QWidget {{ color: {TEXT}; font-family: 'Segoe UI', 'Inter', sans-serif; font-size: 14px; }}
    QMainWindow, #root {{ background: {BACKGROUND}; }}
    QFrame#sidebar, QFrame#card {{ background: {SURFACE}; border: 1px solid {BORDER}; border-radius: 16px; }}
    QLabel#eyebrow {{ color: {MUTED}; font-size: 11px; font-weight: 600; letter-spacing: 1px; }}
    QLabel#title {{ color: {TEXT}; font-size: 27px; font-weight: 700; }}
    QLabel#subtitle, QLabel#muted {{ color: {MUTED}; }}
    QPushButton {{ background: {SURFACE_ELEVATED}; color: {TEXT}; border: 1px solid {BORDER}; border-radius: 10px; padding: 10px 15px; }}
    QPushButton:hover {{ background: #202635; border-color: {ACCENT_SOFT}; }}
    QPushButton#primary {{ background: {ACCENT_SOFT}; border-color: {ACCENT}; font-weight: 600; }}
    QPushButton#primary:hover {{ background: {ACCENT}; }}
    QPushButton#danger {{ color: {ERROR}; border-color: #63323C; }}
    QPushButton#nav {{ text-align: left; padding: 12px 14px; border: none; background: transparent; color: {MUTED}; }}
    QPushButton#nav:hover, QPushButton#nav[selected='true'] {{ color: {TEXT}; background: #1B2030; border-left: 2px solid {ACCENT}; }}
    QLineEdit, QTextEdit, QPlainTextEdit {{ background: {SURFACE_ELEVATED}; color: {TEXT}; border: 1px solid {BORDER}; border-radius: 10px; padding: 10px; selection-background-color: {ACCENT_SOFT}; }}
    QLineEdit:focus, QTextEdit:focus {{ border-color: {ACCENT}; }}
    QScrollArea {{ border: none; background: transparent; }}
    QProgressBar {{ background: {SURFACE_ELEVATED}; border: none; border-radius: 5px; height: 7px; }}
    QProgressBar::chunk {{ background: {ACCENT}; border-radius: 5px; }}
    """
