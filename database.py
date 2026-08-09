"""
Module de gestion de la base de données SQLite.
Stocke : la banque de questions (Action / Vérité) et les confessions/partages
publiés dans les salons.
"""

import sqlite3
import json
import os
import random
from datetime import datetime, timedelta

DB_PATH = os.path.join(os.path.dirname(__file__), "app.db")
SEED_PATH = os.path.join(os.path.dirname(__file__), "questions_seed.json")


def get_connection():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    """Crée les tables si elles n'existent pas et importe les questions de départ."""
    conn = get_connection()
    cur = conn.cursor()

    cur.execute("""
        CREATE TABLE IF NOT EXISTS questions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            category TEXT NOT NULL,       -- 'action' ou 'verite'
            intensity TEXT NOT NULL,      -- 'leger', 'ose', 'tres_ose'
            text TEXT NOT NULL
        )
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS confessions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            room_code TEXT NOT NULL,
            pseudo TEXT NOT NULL,
            message TEXT NOT NULL,
            anonymous INTEGER NOT NULL DEFAULT 0,
            created_at TEXT NOT NULL
        )
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS rooms (
            code TEXT PRIMARY KEY,
            created_at TEXT NOT NULL,
            expires_at TEXT,
            max_players INTEGER
        )
    """)

    conn.commit()

    # Importer les questions de départ seulement si la table est vide
    cur.execute("SELECT COUNT(*) as c FROM questions")
    count = cur.fetchone()["c"]
    if count == 0 and os.path.exists(SEED_PATH):
        with open(SEED_PATH, "r", encoding="utf-8") as f:
            data = json.load(f)
        rows = []
        for category, intensities in data.items():
            for intensity, texts in intensities.items():
                for text in texts:
                    rows.append((category, intensity, text))
        cur.executemany(
            "INSERT INTO questions (category, intensity, text) VALUES (?, ?, ?)",
            rows,
        )
        conn.commit()

    conn.close()


def get_random_question(category, intensity, exclude_ids=None):
    """Tire une question aléatoire non déjà utilisée dans la session."""
    exclude_ids = exclude_ids or []
    conn = get_connection()
    cur = conn.cursor()

    if exclude_ids:
        placeholders = ",".join("?" for _ in exclude_ids)
        query = f"""
            SELECT * FROM questions
            WHERE category = ? AND intensity = ?
            AND id NOT IN ({placeholders})
        """
        cur.execute(query, [category, intensity] + exclude_ids)
    else:
        cur.execute(
            "SELECT * FROM questions WHERE category = ? AND intensity = ?",
            (category, intensity),
        )

    rows = cur.fetchall()
    conn.close()

    if not rows:
        # Toutes les questions de cette catégorie/intensité ont été utilisées :
        # on recommence le cycle (réinitialisation implicite côté serveur).
        return None

    return dict(random.choice(rows))


def save_confession(room_code, pseudo, message, anonymous=False):
    conn = get_connection()
    cur = conn.cursor()
    cur.execute(
        """INSERT INTO confessions (room_code, pseudo, message, anonymous, created_at)
           VALUES (?, ?, ?, ?, ?)""",
        (room_code, pseudo, message, int(anonymous), datetime.utcnow().isoformat()),
    )
    conn.commit()
    confession_id = cur.lastrowid
    conn.close()
    return confession_id


def get_confessions(room_code, limit=100):
    conn = get_connection()
    cur = conn.cursor()
    cur.execute(
        """SELECT * FROM confessions WHERE room_code = ?
           ORDER BY created_at DESC LIMIT ?""",
        (room_code, limit),
    )
    rows = [dict(r) for r in cur.fetchall()]
    conn.close()
    return rows


def register_room(code, expires_hours=None, max_players=None):
    conn = get_connection()
    cur = conn.cursor()
    expires_at = None
    if expires_hours:
        expires_at = (datetime.utcnow() + timedelta(hours=expires_hours)).isoformat()
    cur.execute(
        "INSERT OR REPLACE INTO rooms (code, created_at, expires_at, max_players) VALUES (?, ?, ?, ?)",
        (code, datetime.utcnow().isoformat(), expires_at, max_players),
    )
    conn.commit()
    conn.close()


def get_room_meta(code):
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("SELECT * FROM rooms WHERE code = ?", (code,))
    row = cur.fetchone()
    conn.close()
    return dict(row) if row else None


def is_room_expired(code):
    meta = get_room_meta(code)
    if not meta or not meta.get("expires_at"):
        return False
    return datetime.utcnow() > datetime.fromisoformat(meta["expires_at"])
def get_all_rooms():
    conn = get_connection()
    cur = conn.cursor()
    try:
        cur.execute("SELECT * FROM rooms")
        rooms = cur.fetchall()
        return rooms
    except Exception:
        return []
    finally:
        conn.close()
def delete_room(room_code):
    conn = get_connection()
    cur = conn.cursor()
    try:
        cur.execute("DELETE FROM rooms WHERE code = ?", (room_code,))
        conn.commit()
        return True
    except Exception:
        return False
    finally:
        conn.close()
        
