import os
import re
import secrets

from flask import Blueprint, flash, redirect, render_template, request, session, url_for
from werkzeug.security import check_password_hash, generate_password_hash

from models import goal as goal_model
from models import transaction as tx
from models import user as user_model
from routes.auth import EMAIL_RE, login_required

profile_bp = Blueprint("profile", __name__)

UPLOAD_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "static", "uploads"
)
try:
    os.makedirs(UPLOAD_DIR, exist_ok=True)
except OSError:   # Vercel : système de fichiers en lecture seule
    pass


def _render(errors=None, form=None):
    uid = session["user_id"]
    stats = {"transactions": tx.count_all(uid), "goals": goal_model.count(uid)}
    return render_template("profile.html", errors=errors or {}, form=form or {}, stats=stats)


def _detect_extension(head):
    """Vérifie le contenu réel du fichier (pas seulement son nom)."""
    if head.startswith(b"\x89PNG\r\n\x1a\n"):
        return "png"
    if head.startswith(b"\xff\xd8\xff"):
        return "jpg"
    if head[:4] == b"RIFF" and head[8:12] == b"WEBP":
        return "webp"
    return None


def _remove_file(filename):
    if not filename:
        return
    path = os.path.join(UPLOAD_DIR, os.path.basename(filename))
    if os.path.isfile(path):
        try:
            os.remove(path)
        except OSError:
            pass


@profile_bp.route("/profile")
@login_required
def index():
    return _render()


@profile_bp.route("/profile/update", methods=["POST"])
@login_required
def update():
    uid = session["user_id"]
    full_name = " ".join(request.form.get("full_name", "").split())
    email = request.form.get("email", "").strip().lower()
    errors = {}

    if not full_name:
        errors["full_name"] = "Veuillez saisir votre nom complet."
    elif len(full_name) < 2 or len(full_name) > 60:
        errors["full_name"] = "Le nom doit contenir entre 2 et 60 caractères."

    if not email:
        errors["email"] = "Veuillez saisir votre adresse email."
    elif not EMAIL_RE.match(email) or len(email) > 120:
        errors["email"] = "Adresse email invalide (exemple : nom@mail.com)."
    elif user_model.email_taken(email, uid):
        errors["email"] = "Cette adresse email est déjà utilisée."

    if not errors and not user_model.update_profile(uid, full_name, email):
        errors["email"] = "Cette adresse email est déjà utilisée."

    if errors:
        flash("Les informations n'ont pas été enregistrées. Vérifiez les champs en rouge.", "error")
        return _render(errors, {"full_name": full_name, "email": email})

    flash("Vos informations ont été mises à jour.", "success")
    return redirect(url_for("profile.index"))


@profile_bp.route("/profile/password", methods=["POST"])
@login_required
def password():
    uid = session["user_id"]
    user = user_model.get_with_hash(uid)
    current = request.form.get("current_password", "")
    new = request.form.get("new_password", "")
    confirm = request.form.get("confirm_password", "")
    errors = {}

    if not current:
        errors["current_password"] = "Veuillez saisir votre mot de passe actuel."
    elif not check_password_hash(user["password_hash"], current):
        errors["current_password"] = "Mot de passe actuel incorrect."

    if not new:
        errors["new_password"] = "Veuillez saisir un nouveau mot de passe."
    elif len(new) < 8:
        errors["new_password"] = "Minimum 8 caractères."
    elif not (re.search(r"[A-Za-z]", new) and re.search(r"\d", new)):
        errors["new_password"] = "Le mot de passe doit contenir au moins une lettre et un chiffre."
    elif new == current:
        errors["new_password"] = "Le nouveau mot de passe doit être différent de l'ancien."

    if not confirm:
        errors["confirm_password"] = "Veuillez confirmer le nouveau mot de passe."
    elif confirm != new:
        errors["confirm_password"] = "Les mots de passe ne correspondent pas."

    if errors:
        flash("Le mot de passe n'a pas été modifié. Vérifiez les champs en rouge.", "error")
        return _render(errors)

    user_model.update_password(uid, generate_password_hash(new))
    flash("Votre mot de passe a été modifié.", "success")
    return redirect(url_for("profile.index"))


@profile_bp.route("/profile/photo", methods=["POST"])
@login_required
def photo():
    uid = session["user_id"]
    file = request.files.get("photo")

    if not file or not file.filename:
        flash("Veuillez choisir une image.", "error")
        return _render({"photo": "Veuillez choisir une image."})

    head = file.stream.read(12)
    file.stream.seek(0)
    ext = _detect_extension(head)
    if ext is None:
        flash("Format non pris en charge. Utilisez PNG, JPG ou WebP.", "error")
        return _render({"photo": "Format non pris en charge (PNG, JPG ou WebP)."})

    old = user_model.get_by_id(uid)["photo"]
    filename = f"user{uid}_{secrets.token_hex(8)}.{ext}"  # on ne garde jamais le nom d'origine
    try:
        file.save(os.path.join(UPLOAD_DIR, filename))
    except OSError:   # Vercel : on ne peut pas écrire de fichiers sur le serveur
        flash("L'envoi de photo n'est pas disponible sur cet hébergement.", "error")
        return redirect(url_for("profile.index"))
    user_model.set_photo(uid, filename)
    _remove_file(old)

    flash("Votre photo de profil a été mise à jour.", "success")
    return redirect(url_for("profile.index"))


@profile_bp.route("/profile/photo/delete", methods=["POST"])
@login_required
def photo_delete():
    uid = session["user_id"]
    old = user_model.get_by_id(uid)["photo"]
    user_model.set_photo(uid, None)
    _remove_file(old)
    flash("Votre photo de profil a été supprimée.", "success")
    return redirect(url_for("profile.index"))