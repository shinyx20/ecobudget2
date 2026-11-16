import re
from functools import wraps

from flask import (Blueprint, flash, jsonify, redirect, render_template,
                   request, session, url_for)
from werkzeug.security import check_password_hash, generate_password_hash

from models import user as user_model

auth_bp = Blueprint("auth", __name__)

EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


def is_user_admin(u):
    """Source unique de vérité : la colonne is_admin de la base (jamais le cookie)."""
    if not u:
        return False
    try:
        return bool(u["is_admin"])
    except (KeyError, IndexError):
        return False


def login_required(view):
    """Protège une page UTILISATEUR : non connecté -> login ; administrateur -> espace admin."""
    @wraps(view)
    def wrapped(*args, **kwargs):
        uid = session.get("user_id")
        u = user_model.get_by_id(uid) if uid else None
        if not u:
            session.clear()
            flash("Veuillez vous connecter pour accéder à cette page.", "info")
            return redirect(url_for("auth.login"))
        if is_user_admin(u):
            if request.path.startswith("/chatbot"):
                return jsonify(ok=False, error="Réservé aux utilisateurs."), 403
            flash("Cette page est réservée aux utilisateurs. Vous êtes connecté en administrateur.", "info")
            return redirect(url_for("reviews.admin_index"))
        return view(*args, **kwargs)
    return wrapped


def admin_required(view):
    """Protège l'espace administrateur."""
    @wraps(view)
    def wrapped(*args, **kwargs):
        uid = session.get("user_id")
        u = user_model.get_by_id(uid) if uid else None
        if not u:
            session.clear()
            flash("Veuillez vous connecter.", "info")
            return redirect(url_for("auth.login"))
        if not is_user_admin(u):
            flash("Accès réservé à l'administrateur.", "error")
            return redirect(url_for("dashboard.index"))
        return view(*args, **kwargs)
    return wrapped


@auth_bp.route("/login", methods=["GET", "POST"])
def login():
    if "user_id" in session:
        u = user_model.get_by_id(session["user_id"])
        if u:
            return redirect(url_for("reviews.admin_index") if is_user_admin(u) else url_for("dashboard.index"))

    errors, form = {}, {}
    if request.method == "POST":
        email = request.form.get("email", "").strip().lower()
        password = request.form.get("password", "")
        remember = request.form.get("remember") == "on"
        form = {"email": email}

        if not email:
            errors["email"] = "Veuillez saisir votre adresse email."
        elif not EMAIL_RE.match(email):
            errors["email"] = "Adresse email invalide (exemple : nom@mail.com)."
        if not password:
            errors["password"] = "Veuillez saisir votre mot de passe."

        if not errors:
            user = user_model.get_by_email(email)
            if user and check_password_hash(user["password_hash"], password):
                session.clear()
                session["user_id"] = user["id"]
                session.permanent = remember
                if is_user_admin(user):
                    flash("Bienvenue dans l'espace administrateur.", "success")
                    return redirect(url_for("reviews.admin_index"))
                flash(f"Bon retour, {user['full_name'].split(' ')[0]} !", "success")
                return redirect(url_for("dashboard.index"))
            flash("Email ou mot de passe incorrect.", "error")

    return render_template("login.html", errors=errors, form=form)


@auth_bp.route("/signup", methods=["GET", "POST"])
def signup():
    if "user_id" in session:
        u = user_model.get_by_id(session["user_id"])
        if u:
            return redirect(url_for("reviews.admin_index") if is_user_admin(u) else url_for("dashboard.index"))
        session.clear()

    errors, form = {}, {}
    if request.method == "POST":
        full_name = " ".join(request.form.get("full_name", "").split())
        email = request.form.get("email", "").strip().lower()
        password = request.form.get("password", "")
        confirm = request.form.get("confirm_password", "")
        form = {"full_name": full_name, "email": email}

        if not full_name:
            errors["full_name"] = "Veuillez saisir votre nom complet."
        elif len(full_name) < 2 or len(full_name) > 60:
            errors["full_name"] = "Le nom doit contenir entre 2 et 60 caractères."

        if not email:
            errors["email"] = "Veuillez saisir votre adresse email."
        elif not EMAIL_RE.match(email) or len(email) > 120:
            errors["email"] = "Adresse email invalide (exemple : nom@mail.com)."
        elif user_model.email_exists(email):
            errors["email"] = "Cette adresse email est déjà utilisée."

        if not password:
            errors["password"] = "Veuillez saisir un mot de passe."
        elif len(password) < 8:
            errors["password"] = "Minimum 8 caractères."
        elif not (re.search(r"[A-Za-z]", password) and re.search(r"\d", password)):
            errors["password"] = "Le mot de passe doit contenir au moins une lettre et un chiffre."

        if not confirm:
            errors["confirm_password"] = "Veuillez confirmer votre mot de passe."
        elif confirm != password:
            errors["confirm_password"] = "Les mots de passe ne correspondent pas."

        if not errors:
            user_id = user_model.create_user(
                full_name, email, generate_password_hash(password)
            )
            if user_id is None:
                errors["email"] = "Cette adresse email est déjà utilisée."
            else:
                session.clear()
                session["user_id"] = user_id
                flash("Compte créé avec succès. Bienvenue sur EcoBudget !", "success")
                return redirect(url_for("dashboard.index"))

        flash("Le formulaire contient des erreurs. Vérifiez les champs en rouge.", "error")

    return render_template("signup.html", errors=errors, form=form)


@auth_bp.route("/logout")
def logout():
    session.clear()
    flash("Vous êtes déconnecté. À bientôt !", "success")
    return redirect(url_for("auth.login"))