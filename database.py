"""
Module de gestion de la base de données PostgreSQL (hébergée sur Supabase).
Stocke : la banque de questions (Action / Vérité) et les confessions/partages
publiés dans les salons.

Connexion via la variable d'environnement DATABASE_URL (définie sur Render).
"""

import os
import json
import random
from datetime import datetime, timedelta

import psycopg2
import psycopg2.extras

DATABASE_URL = os.environ.get("DATABASE_URL")
SEED_PATH = os.path.join(os.path.dirname(__file__), "questions_seed.json")


def get_connection():
    conn = psycopg2.connect(DATABASE_URL, cursor_factory=psycopg2.extras.RealDictCursor)
    return conn


def init_db():
    """Crée les tables si elles n'existent pas et importe les questions de départ."""
    conn = get_connection()
    cur = conn.cursor()

    cur.execute("""
        CREATE TABLE IF NOT EXISTS questions (
            id SERIAL PRIMARY KEY,
            category TEXT NOT NULL,       -- 'action' ou 'verite'
            intensity TEXT NOT NULL,      -- 'leger', 'ose', 'tres_ose', 'amis', 'adultes', 'extreme'
            text TEXT NOT NULL
        )
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS confessions (
            id SERIAL PRIMARY KEY,
            room_code TEXT NOT NULL,
            pseudo TEXT NOT NULL,
            message TEXT NOT NULL,
            anonymous INTEGER NOT NULL DEFAULT 0,
            created_at TEXT NOT NULL
        )
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS confession_comments (
            id SERIAL PRIMARY KEY,
            confession_id INTEGER NOT NULL,
            room_code TEXT NOT NULL,
            pseudo TEXT NOT NULL,
            message TEXT NOT NULL,
            created_at TEXT NOT NULL
        )
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS chat_messages (
            id SERIAL PRIMARY KEY,
            room_code TEXT NOT NULL,
            pseudo TEXT NOT NULL,
            message TEXT NOT NULL,
            created_at TEXT NOT NULL
        )
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS profiles (
            room_code TEXT NOT NULL,
            pseudo TEXT NOT NULL,
            avatar_path TEXT,
            updated_at TEXT NOT NULL,
            PRIMARY KEY (room_code, pseudo)
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
            "INSERT INTO questions (category, intensity, text) VALUES (%s, %s, %s)",
            rows,
        )
        conn.commit()

    cur.close()
    conn.close()


def get_random_question(category, intensity, exclude_ids=None):
    """Tire une question aléatoire non déjà utilisée dans la session."""
    exclude_ids = exclude_ids or []
    conn = get_connection()
    cur = conn.cursor()

    if exclude_ids:
        placeholders = ",".join(["%s"] * len(exclude_ids))
        query = f"""
            SELECT * FROM questions
            WHERE category = %s AND intensity = %s
            AND id NOT IN ({placeholders})
        """
        cur.execute(query, [category, intensity] + exclude_ids)
    else:
        cur.execute(
            "SELECT * FROM questions WHERE category = %s AND intensity = %s",
            (category, intensity),
        )

    rows = cur.fetchall()
    cur.close()
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
           VALUES (%s, %s, %s, %s, %s) RETURNING id""",
        (room_code, pseudo, message, int(anonymous), datetime.utcnow().isoformat()),
    )
    confession_id = cur.fetchone()["id"]
    conn.commit()
    cur.close()
    conn.close()
    return confession_id


def get_confessions(room_code, limit=100):
    conn = get_connection()
    cur = conn.cursor()
    # On récupère les `limit` confessions les plus RÉCENTES, mais on les
    # renvoie triées du plus ancien au plus récent (ordre d'affichage type
    # "fil de discussion", nouveauté en bas).
    cur.execute(
        """SELECT * FROM (
               SELECT * FROM confessions WHERE room_code = %s
               ORDER BY created_at DESC LIMIT %s
           ) sub
           ORDER BY sub.created_at ASC""",
        (room_code, limit),
    )
    rows = [dict(r) for r in cur.fetchall()]

    if rows:
        ids = [r["id"] for r in rows]
        placeholders = ",".join(["%s"] * len(ids))
        cur.execute(
            f"""SELECT * FROM confession_comments
                WHERE confession_id IN ({placeholders})
                ORDER BY created_at ASC""",
            ids,
        )
        comments_by_confession = {}
        for c in cur.fetchall():
            comments_by_confession.setdefault(c["confession_id"], []).append(dict(c))
        for r in rows:
            r["comments"] = comments_by_confession.get(r["id"], [])

    cur.close()
    conn.close()
    return rows


def save_comment(confession_id, room_code, pseudo, message):
    conn = get_connection()
    cur = conn.cursor()
    cur.execute(
        """INSERT INTO confession_comments (confession_id, room_code, pseudo, message, created_at)
           VALUES (%s, %s, %s, %s, %s) RETURNING id""",
        (confession_id, room_code, pseudo, message, datetime.utcnow().isoformat()),
    )
    comment_id = cur.fetchone()["id"]
    conn.commit()
    cur.close()
    conn.close()
    return comment_id


def register_room(code, expires_hours=None, max_players=None):
    conn = get_connection()
    cur = conn.cursor()
    expires_at = None
    if expires_hours:
        expires_at = (datetime.utcnow() + timedelta(hours=expires_hours)).isoformat()
    cur.execute(
        """INSERT INTO rooms (code, created_at, expires_at, max_players)
           VALUES (%s, %s, %s, %s)
           ON CONFLICT (code) DO UPDATE SET
               created_at = excluded.created_at,
               expires_at = excluded.expires_at,
               max_players = excluded.max_players""",
        (code, datetime.utcnow().isoformat(), expires_at, max_players),
    )
    conn.commit()
    cur.close()
    conn.close()


def get_room_meta(code):
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("SELECT * FROM rooms WHERE code = %s", (code,))
    row = cur.fetchone()
    cur.close()
    conn.close()
    return dict(row) if row else None


def is_room_expired(code):
    meta = get_room_meta(code)
    if not meta or not meta.get("expires_at"):
        return False
    return datetime.utcnow() > datetime.fromisoformat(meta["expires_at"])


# --- Discussion instantanée ---------------------------------------------------

def save_chat_message(room_code, pseudo, message):
    conn = get_connection()
    cur = conn.cursor()
    cur.execute(
        """INSERT INTO chat_messages (room_code, pseudo, message, created_at)
           VALUES (%s, %s, %s, %s) RETURNING id""",
        (room_code, pseudo, message, datetime.utcnow().isoformat()),
    )
    message_id = cur.fetchone()["id"]
    conn.commit()
    cur.close()
    conn.close()
    return message_id


def get_chat_messages(room_code, limit=200):
    """Renvoie les `limit` derniers messages, triés du plus ancien au plus récent."""
    conn = get_connection()
    cur = conn.cursor()
    cur.execute(
        """SELECT * FROM (
               SELECT * FROM chat_messages WHERE room_code = %s
               ORDER BY created_at DESC LIMIT %s
           ) sub
           ORDER BY sub.created_at ASC""",
        (room_code, limit),
    )
    rows = [dict(r) for r in cur.fetchall()]
    cur.close()
    conn.close()
    return rows


# --- Profils / avatars ---------------------------------------------------------

def set_profile_avatar(room_code, pseudo, avatar_path):
    conn = get_connection()
    cur = conn.cursor()
    cur.execute(
        """INSERT INTO profiles (room_code, pseudo, avatar_path, updated_at)
           VALUES (%s, %s, %s, %s)
           ON CONFLICT (room_code, pseudo) DO UPDATE SET
               avatar_path = excluded.avatar_path,
               updated_at = excluded.updated_at""",
        (room_code, pseudo, avatar_path, datetime.utcnow().isoformat()),
    )
    conn.commit()
    cur.close()
    conn.close()


def get_profile_avatar(room_code, pseudo):
    conn = get_connection()
    cur = conn.cursor()
    cur.execute(
        "SELECT avatar_path FROM profiles WHERE room_code = %s AND pseudo = %s",
        (room_code, pseudo),
    )
    row = cur.fetchone()
    cur.close()
    conn.close()
    return row["avatar_path"] if row else None


def get_profiles_map(room_code):
    """Renvoie { pseudo: avatar_path } pour tout le salon, en une seule requête."""
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("SELECT pseudo, avatar_path FROM profiles WHERE room_code = %s", (room_code,))
    result = {r["pseudo"]: r["avatar_path"] for r in cur.fetchall()}
    cur.close()
    conn.close()
    return result
