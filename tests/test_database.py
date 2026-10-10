"""Pruebas de reproducibilidad y esquema de la base de ventas."""

import csv
import sqlite3

import pandas as pd

from services.database import COLUMNAS, seed_database, ensure_database


def test_database_is_reproducible_and_matches_csv(tmp_path):
    """La regeneración mantiene el esquema y coincide exactamente con el CSV."""
    db_path = tmp_path / "data" / "ventas.db"
    csv_path = tmp_path / "data" / "ventas.csv"
    assert seed_database(db_path, csv_path) == 400
    first_csv = csv_path.read_bytes()
    assert seed_database(db_path, csv_path) == 400
    assert csv_path.read_bytes() == first_csv

    with sqlite3.connect(db_path) as conn:
        info = conn.execute("PRAGMA table_info(ventas)").fetchall()
        rows = conn.execute("SELECT * FROM ventas ORDER BY id LIMIT 5").fetchall()
        count = conn.execute("SELECT COUNT(*) FROM ventas").fetchone()[0]
    assert [item[1] for item in info] == list(COLUMNAS)
    assert [item[2] for item in info] == ["INTEGER", "TEXT", "TEXT", "TEXT", "INTEGER", "REAL", "TEXT"]
    assert info[0][5] == 1
    assert count == 400
    assert len(rows) == 5

    csv_frame = pd.read_csv(csv_path)
    with sqlite3.connect(db_path) as conn:
        db_frame = pd.read_sql_query("SELECT * FROM ventas ORDER BY id", conn)
    pd.testing.assert_frame_equal(csv_frame, db_frame, check_dtype=False)
    assert csv_frame["sede"].isin(["Medellín", "Bogotá", "Cali", "Barranquilla"]).all()
    dates = pd.to_datetime(csv_frame["fecha"])
    assert dates.min() >= pd.Timestamp("2025-01-01")
    assert dates.max() <= pd.Timestamp("2026-06-30")


def test_ensure_database_repairs_an_empty_database(tmp_path, monkeypatch):
    """Recrea archivos vacíos o incompletos en lugar de aceptarlos como válidos."""
    from services import database

    db_path = tmp_path / "data" / "ventas.db"
    csv_path = tmp_path / "data" / "ventas.csv"
    db_path.parent.mkdir(parents=True)
    db_path.touch()
    monkeypatch.setattr(database, "DB_PATH", db_path)
    monkeypatch.setattr(database, "CSV_PATH", csv_path)
    ensure_database()
    with sqlite3.connect(db_path) as connection:
        assert connection.execute("SELECT COUNT(*) FROM ventas").fetchone()[0] == 400
    assert csv_path.exists()
