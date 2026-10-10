"""Inicializa los recursos locales antes de arrancar Streamlit en Docker."""

import os
import sys
from services.database import ensure_database


def main() -> None:
    """Asegura la base y reemplaza el proceso por la aplicación Streamlit."""
    ensure_database()
    os.execv(sys.executable, [
        sys.executable, "-m", "streamlit", "run", "app.py",
        "--server.address=0.0.0.0",
    ])


if __name__ == "__main__":
    main()
