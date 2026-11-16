from database import IntegrityError, get_db


def get_by_id(user_id):
    return get_db().execute(
        "SELECT id, full_name, email, photo, created_at FROM users WHERE id = ?",
        (user_id,),
    ).fetchone()


def get_with_hash(user_id):
    return get_db().execute(
        "SELECT * FROM users WHERE id = ?", (user_id,)
    ).fetchone()


def get_by_email(email):
    return get_db().execute(
        "SELECT * FROM users WHERE email = ?", (email,)
    ).fetchone()


def email_exists(email):
    row = get_db().execute(
        "SELECT 1 FROM users WHERE email = ?", (email,)
    ).fetchone()
    return row is not None


def email_taken(email, user_id):
    """True si l'email appartient à un AUTRE utilisateur."""
    row = get_db().execute(
        "SELECT 1 FROM users WHERE email = ? AND id <> ?", (email, user_id)
    ).fetchone()
    return row is not None


def create_user(full_name, email, password_hash):
    """Crée l'utilisateur + ses paramètres + une notification de bienvenue.
    Retourne l'id, ou None si l'email existe déjà."""
    db = get_db()
    try:
        cur = db.execute(
            "INSERT INTO users (full_name, email, password_hash) VALUES (?, ?, ?)",
            (full_name, email, password_hash),
        )
    except IntegrityError:
        return None
    user_id = cur.lastrowid
    db.execute("INSERT INTO settings (user_id) VALUES (?)", (user_id,))
    db.execute(
        "INSERT INTO notifications (user_id, message, type) VALUES (?, ?, 'info')",
        (user_id, "Bienvenue sur EcoBudget ! Commencez par ajouter votre première transaction."),
    )
    db.commit()
    return user_id


def update_profile(user_id, full_name, email):
    """Retourne False si l'email est déjà pris."""
    db = get_db()
    try:
        db.execute(
            "UPDATE users SET full_name = ?, email = ? WHERE id = ?",
            (full_name, email, user_id),
        )
    except IntegrityError:
        return False
    db.commit()
    return True


def update_password(user_id, password_hash):
    db = get_db()
    db.execute("UPDATE users SET password_hash = ? WHERE id = ?", (password_hash, user_id))
    db.commit()


def set_photo(user_id, filename):
    db = get_db()
    db.execute("UPDATE users SET photo = ? WHERE id = ?", (filename, user_id))
    db.commit()


def count_unread_notifications(user_id):
    return get_db().execute(
        "SELECT COUNT(*) FROM notifications WHERE user_id = ? AND is_read = 0",
        (user_id,),
    ).fetchone()[0]




def delete_user(user_id):
    """Supprime le compte. Les transactions, budgets, objectifs, notifications et
    paramètres sont supprimés automatiquement (ON DELETE CASCADE)."""
    db = get_db()
    db.execute("DELETE FROM users WHERE id = ?", (user_id,))
    db.commit()