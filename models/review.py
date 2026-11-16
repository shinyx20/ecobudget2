from database import get_db


def create(user_id, review_type, rating, subject, comment):
    db = get_db()
    cur = db.execute(
        """
        INSERT INTO reviews (user_id, type, rating, subject, comment)
        VALUES (?, ?, ?, ?, ?)
        """,
        (user_id, review_type, int(rating), subject, comment),
    )
    db.commit()
    return cur.lastrowid


def list_by_user(user_id):
    return get_db().execute(
        """
        SELECT id, user_id, type, rating, subject, comment, status, admin_reply, created_at
        FROM reviews
        WHERE user_id = ?
        ORDER BY created_at DESC, id DESC
        """,
        (user_id,),
    ).fetchall()


def list_all(type_filter="", status_filter=""):
    sql = """
        SELECT r.id, r.user_id, r.type, r.rating, r.subject, r.comment,
               r.status, r.admin_reply, r.created_at,
               u.full_name AS user_name, u.email AS user_email
        FROM reviews r
        LEFT JOIN users u ON u.id = r.user_id
        WHERE 1 = 1
    """
    params = []
    if type_filter in ("avis", "recommandation", "reclamation"):
        sql += " AND r.type = ?"
        params.append(type_filter)
    if status_filter in ("en_attente", "lu", "resolu"):
        sql += " AND r.status = ?"
        params.append(status_filter)

    sql += " ORDER BY CASE r.status WHEN 'en_attente' THEN 0 WHEN 'lu' THEN 1 ELSE 2 END, r.created_at DESC, r.id DESC"
    return get_db().execute(sql, params).fetchall()


def stats():
    row = get_db().execute(
        """
        SELECT
            COUNT(*) AS total,
            CAST(ROUND(COALESCE(AVG(rating), 0), 1) AS DOUBLE PRECISION) AS avg_rating,
            SUM(CASE WHEN type = 'reclamation' THEN 1 ELSE 0 END) AS reclamations,
            SUM(CASE WHEN status = 'en_attente' THEN 1 ELSE 0 END) AS pending
        FROM reviews
        """
    ).fetchone()
    return dict(row) if row else {"total": 0, "avg_rating": 0, "reclamations": 0, "pending": 0}


def reply_and_update(review_id, status, admin_reply):
    db = get_db()
    cur = db.execute(
        "UPDATE reviews SET status = ?, admin_reply = ? WHERE id = ?",
        (status, admin_reply, review_id),
    )
    rev = db.execute("SELECT user_id, subject FROM reviews WHERE id = ?", (review_id,)).fetchone()
    if rev and admin_reply:
        subj = rev["subject"] or "Votre retour"
        db.execute(
            "INSERT INTO notifications (user_id, message, type) VALUES (?, ?, 'info')",
            (rev["user_id"], f"Réponse de l'administrateur concernant « {subj} » : {admin_reply}"),
        )
    db.commit()
    return cur.rowcount > 0


def delete(review_id):
    db = get_db()
    cur = db.execute("DELETE FROM reviews WHERE id = ?", (review_id,))
    db.commit()
    return cur.rowcount > 0