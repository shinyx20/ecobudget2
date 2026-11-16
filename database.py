"""Accès à PostgreSQL (Neon / Supabase / local) pour EcoBudget.

Les modèles utilisent encore la syntaxe sqlite (`?`, `.lastrowid`, `row["colonne"]`).
Cette couche fait la traduction, donc presque rien à changer dans models/*.py.
"""
import os
import re
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

import psycopg2
from flask import g
from werkzeug.security import generate_password_hash

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

IntegrityError = psycopg2.IntegrityError

SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    id            SERIAL PRIMARY KEY,
    full_name     TEXT NOT NULL,
    email         TEXT NOT NULL UNIQUE,
    password_hash TEXT NOT NULL,
    photo         TEXT,
    is_admin      INTEGER NOT NULL DEFAULT 0,
    created_at    TEXT NOT NULL DEFAULT to_char(now(), 'YYYY-MM-DD HH24:MI:SS')
);

CREATE TABLE IF NOT EXISTS categories (
    id         SERIAL PRIMARY KEY,
    name       TEXT NOT NULL,
    type       TEXT NOT NULL CHECK (type IN ('income', 'expense')),
    icon       TEXT NOT NULL DEFAULT 'tag',
    user_id    INTEGER REFERENCES users(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS transactions (
    id          SERIAL PRIMARY KEY,
    user_id     INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    category_id INTEGER NOT NULL REFERENCES categories(id),
    type        TEXT NOT NULL CHECK (type IN ('income', 'expense')),
    amount      DOUBLE PRECISION NOT NULL CHECK (amount > 0),
    description TEXT,
    date        TEXT NOT NULL,
    created_at  TEXT NOT NULL DEFAULT to_char(now(), 'YYYY-MM-DD HH24:MI:SS')
);

CREATE TABLE IF NOT EXISTS budgets (
    id          SERIAL PRIMARY KEY,
    user_id     INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    category_id INTEGER REFERENCES categories(id),
    month       TEXT NOT NULL,
    amount      DOUBLE PRECISION NOT NULL CHECK (amount > 0)
);

CREATE TABLE IF NOT EXISTS savings_goals (
    id            SERIAL PRIMARY KEY,
    user_id       INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    name          TEXT NOT NULL,
    target_amount DOUBLE PRECISION NOT NULL CHECK (target_amount > 0),
    saved_amount  DOUBLE PRECISION NOT NULL DEFAULT 0,
    deadline      TEXT,
    description   TEXT,
    created_at    TEXT NOT NULL DEFAULT to_char(now(), 'YYYY-MM-DD HH24:MI:SS')
);

CREATE TABLE IF NOT EXISTS savings_contributions (
    id      SERIAL PRIMARY KEY,
    goal_id INTEGER NOT NULL REFERENCES savings_goals(id) ON DELETE CASCADE,
    amount  DOUBLE PRECISION NOT NULL CHECK (amount > 0),
    date    TEXT NOT NULL DEFAULT to_char(CURRENT_DATE, 'YYYY-MM-DD')
);

CREATE TABLE IF NOT EXISTS notifications (
    id         SERIAL PRIMARY KEY,
    user_id    INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    message    TEXT NOT NULL,
    type       TEXT NOT NULL DEFAULT 'info',
    is_read    INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL DEFAULT to_char(now(), 'YYYY-MM-DD HH24:MI:SS')
);

CREATE TABLE IF NOT EXISTS reviews (
    id          SERIAL PRIMARY KEY,
    user_id     INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    type        TEXT NOT NULL DEFAULT 'avis' CHECK (type IN ('avis', 'recommandation', 'reclamation')),
    rating      INTEGER NOT NULL CHECK (rating >= 1 AND rating <= 5),
    subject     TEXT,
    comment     TEXT NOT NULL,
    status      TEXT NOT NULL DEFAULT 'en_attente' CHECK (status IN ('en_attente', 'lu', 'resolu')),
    admin_reply TEXT,
    created_at  TEXT NOT NULL DEFAULT to_char(now(), 'YYYY-MM-DD HH24:MI:SS')
);

CREATE TABLE IF NOT EXISTS settings (
    user_id               INTEGER PRIMARY KEY REFERENCES users(id) ON DELETE CASCADE,
    theme                 TEXT NOT NULL DEFAULT 'light',
    language              TEXT NOT NULL DEFAULT 'fr',
    currency              TEXT NOT NULL DEFAULT 'DA',
    notifications_enabled INTEGER NOT NULL DEFAULT 1,
    compact_view          INTEGER NOT NULL DEFAULT 0
);
"""

DEFAULT_CATEGORIES = [
    ("Alimentation", "expense", "utensils"),
    ("Transport", "expense", "bus"),
    ("Études", "expense", "graduation-cap"),
    ("Santé", "expense", "heart-pulse"),
    ("Shopping", "expense", "shopping-bag"),
    ("Loisirs", "expense", "gamepad-2"),
    ("Logement", "expense", "house"),
    ("Autres", "expense", "ellipsis"),
    ("Salaire", "income", "briefcase"),
    ("Bourse", "income", "award"),
    ("Freelance", "income", "laptop"),
    ("Cadeaux", "income", "gift"),
    ("Autres revenus", "income", "wallet"),
]

_NO_ID_TABLES = {"settings"}
_INSERT_RE = re.compile(r"^\s*INSERT\s+INTO\s+(\w+)", re.IGNORECASE)
_IS_PARAM_RE = re.compile(r"\bIS\s+%s", re.IGNORECASE)


def database_url():
    url = os.environ.get("DATABASE_URL") or os.environ.get("POSTGRES_URL") or ""
    if not url:
        raise RuntimeError(
            "Variable d'environnement DATABASE_URL manquante (voir .env.example)."
        )
    if url.startswith("postgres://"):
        url = "postgresql://" + url[len("postgres://"):]
    parts = urlsplit(url)
    keep = [(k, v) for k, v in parse_qsl(parts.query)
            if k in ("sslmode", "channel_binding", "connect_timeout")]
    if not any(k == "sslmode" for k, _ in keep) and "localhost" not in parts.netloc and "127.0.0.1" not in parts.netloc:
        keep.append(("sslmode", "require"))
    return urlunsplit((parts.scheme, parts.netloc, parts.path, urlencode(keep), ""))


class Row(dict):
    """Ligne de résultat : row["colonne"], row[0] et dict(row) fonctionnent."""

    def __init__(self, keys, values):
        super().__init__(zip(keys, values))
        self._values = tuple(values)

    def __getitem__(self, key):
        if isinstance(key, int):
            return self._values[key]
        return super().__getitem__(key)


class Cursor:
    def __init__(self, cur, lastrowid=None):
        self._cur = cur
        self.lastrowid = lastrowid
        self.rowcount = cur.rowcount
        self._cols = [d[0] for d in cur.description] if cur.description else []

    def fetchone(self):
        row = self._cur.fetchone()
        return None if row is None else Row(self._cols, row)

    def fetchall(self):
        return [Row(self._cols, r) for r in self._cur.fetchall()]


class Connection:
    def __init__(self, conn):
        self._conn = conn

    def execute(self, sql, params=None):
        cur = self._conn.cursor()
        params = tuple(params) if params is not None else None
        if params is not None:
            sql = sql.replace("%", "%%").replace("?", "%s")
            sql = _IS_PARAM_RE.sub("IS NOT DISTINCT FROM %s", sql)

        add_returning = False
        m = _INSERT_RE.match(sql)
        if m and m.group(1).lower() not in _NO_ID_TABLES and "returning" not in sql.lower():
            sql = sql.rstrip().rstrip(";") + " RETURNING id"
            add_returning = True

        try:
            cur.execute(sql, params)
        except psycopg2.Error:
            self._conn.rollback()
            raise

        lastrowid = None
        if add_returning:
            r = cur.fetchone()
            lastrowid = r[0] if r else None
        return Cursor(cur, lastrowid)

    def executemany(self, sql, seq):
        cur = self._conn.cursor()
        sql = sql.replace("%", "%%").replace("?", "%s")
        try:
            cur.executemany(sql, seq)
        except psycopg2.Error:
            self._conn.rollback()
            raise
        return Cursor(cur)

    def executescript(self, sql):
        cur = self._conn.cursor()
        cur.execute(sql)

    def commit(self):
        self._conn.commit()

    def rollback(self):
        self._conn.rollback()

    def close(self):
        self._conn.close()


def get_db():
    """Une connexion par requête, réutilisée tant que la requête dure."""
    if "db" not in g:
        g.db = Connection(psycopg2.connect(database_url(), connect_timeout=10))
    return g.db


def close_db(error=None):
    db = g.pop("db", None)
    if db is not None:
        db.close()


def init_db():
    """Crée les tables, les catégories et le compte admin par défaut."""
    db = get_db()
    db.execute("SELECT pg_advisory_xact_lock(424242)")
    db.executescript(SCHEMA)

    count = db.execute("SELECT COUNT(*) FROM categories").fetchone()[0]
    if count == 0:
        db.executemany(
            "INSERT INTO categories (name, type, icon) VALUES (?, ?, ?)",
            DEFAULT_CATEGORIES,
        )

    admin_password = os.environ.get("ECOBUDGET_ADMIN_PASSWORD", "Admin1234")
    admin = db.execute("SELECT id FROM users WHERE email = ?", ("admin@ecobudget.com",)).fetchone()
    if not admin:
        cur = db.execute(
            "INSERT INTO users (full_name, email, password_hash, is_admin) VALUES (?, ?, ?, 1)",
            ("Administrateur EcoBudget", "admin@ecobudget.com", generate_password_hash(admin_password)),
        )
        db.execute("INSERT INTO settings (user_id) VALUES (?)", (cur.lastrowid,))
    else:
        db.execute("UPDATE users SET is_admin = 1 WHERE id = ?", (admin["id"],))

    db.commit()