"""Genera la base de datos local de ventas y su CSV reproducible."""

import csv
import random
import sqlite3
import threading
from datetime import date, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DB_PATH = ROOT / "data" / "ventas.db"
CSV_PATH = ROOT / "data" / "ventas.csv"
SEDES = ("Medellín", "Bogotá", "Cali", "Barranquilla")
VENDEDORES = ("Ana Torres", "Luis Gómez", "María Ríos", "Carlos Vega", "Sofía Pérez", "Andrés Ruiz", "Valentina Mora", "Diego Castro")
PRODUCTOS = ("Café Andino", "Taza Solar", "Mochila Nube", "Cuaderno Río", "Lámpara Aurora", "Botella Roble", "Teclado Cóndor", "Audífonos Brisa", "Mouse Cumbre", "Agenda Guayacán")
COLUMNAS = ("id", "vendedor", "sede", "producto", "cantidad", "precio", "fecha")
_INIT_LOCK = threading.Lock()


def seed_database(db_path: Path = DB_PATH, csv_path: Path = CSV_PATH, filas: int = 400) -> int:
    """Recrea `ventas` con datos reproducibles y escribe el CSV correspondiente."""
    random.seed(42)
    inicio = date(2025, 1, 1)
    rango_dias = (date(2026, 6, 30) - inicio).days
    registros = []
    for row_id in range(1, max(300, filas) + 1):
        registros.append((
            row_id, random.choice(VENDEDORES), random.choice(SEDES),
            random.choice(PRODUCTOS), random.randint(1, 30),
            round(random.uniform(5000, 900000), 2),
            (inicio + timedelta(days=random.randint(0, rango_dias))).isoformat(),
        ))
    db_path = Path(db_path)
    csv_path = Path(csv_path)
    db_path.parent.mkdir(parents=True, exist_ok=True)
    csv_path.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(db_path) as connection:
        connection.execute("DROP TABLE IF EXISTS ventas")
        connection.execute("""CREATE TABLE ventas (
            id INTEGER PRIMARY KEY,
            vendedor TEXT,
            sede TEXT,
            producto TEXT,
            cantidad INTEGER,
            precio REAL,
            fecha TEXT
        )""")
        connection.executemany("INSERT INTO ventas VALUES (?, ?, ?, ?, ?, ?, ?)", registros)
    with csv_path.open("w", newline="", encoding="utf-8") as csv_file:
        writer = csv.writer(csv_file)
        writer.writerow(COLUMNAS)
        writer.writerows(registros)
    return len(registros)


def ensure_database() -> None:
    """Crea o repara la base si no existe la tabla y también conserva el CSV."""
    with _INIT_LOCK:
        valid = False
        if DB_PATH.exists() and DB_PATH.stat().st_size > 0:
            try:
                with sqlite3.connect(f"file:{DB_PATH.as_posix()}?mode=ro", uri=True) as connection:
                    columns = [row[1] for row in connection.execute("PRAGMA table_info(ventas)")]
                    valid = columns == list(COLUMNAS)
            except sqlite3.Error:
                valid = False
        if not valid or not CSV_PATH.exists():
            seed_database(DB_PATH, CSV_PATH)


if __name__ == "__main__":
    total = seed_database()
    print(f"Base regenerada: {total} ventas en {DB_PATH}")
