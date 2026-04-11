from pathlib import Path

VERSION_FILE = Path(__file__).with_name("VERSION")

try:
    APP_VERSION = VERSION_FILE.read_text(encoding="utf-8").strip()
except FileNotFoundError:
    APP_VERSION = "0.0.0"
