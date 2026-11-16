import re
from flask import Blueprint, flash, redirect, render_template, request, session, url_for
from werkzeug.security import check_password_hash, generate_password_hash

from models import review as review_model
from models import user as user_model
from routes.auth import admin_required, login_required

reviews_bp = Blueprint("reviews", __name__)


@reviews_bp.route("/reviews", methods=["GET", "POST"])
@login_required
def index():
    uid = session["user_id"]
    errors, form = {}, {}

    if request.method == "POST":
        review_type = request.form.get("type", "avis")
        if review_type not in ("avis", "recommandation", "reclamation"):
            review_type = "avis"

        try:
            rating = int(request.form.get("rating", 5))
        except (TypeError, ValueError):
            rating = 5
        rating = max(1, min(5, rating))

        subject = " ".join(request.form.get("subject", "").split())
        comment = " ".join(request.form.get("comment", "").split())
        form = {"type": review_type, "rating": rating, "subject": subject, "comment": comment}

        if len(subject) > 120:
            errors["subject"] = "Le sujet est limité à 120 caractères."
        if not comment:
            errors["comment"] = "Veuillez rédiger votre avis, recommandation ou réclamation."
        elif len(comment) < 5:
            errors["comment"] = "Votre message doit contenir au moins 5 caractères."
        elif len(comment) > 1000:
            errors["comment"] = "Votre message est limité à 1000 caractères."

        if not errors:
            review_model.create(uid, review_type, rating, subject, comment)
            flash("Merci ! Votre avis a bien été envoyé.", "success")
            return redirect(url_for("reviews.index"))

        flash("Veuillez corriger les champs indiqués.", "error")

    my_reviews = review_model.list_by_user(uid)
    return render_template(
        "reviews.html",
        view_mode="user",
        reviews=my_reviews,
        errors=errors,
        form=form,
    )


@reviews_bp.route("/admin/reviews")
@admin_required
def admin_index():
    type_filter = request.args.get("type", "")
    status_filter = request.args.get("status", "")
    all_reviews = review_model.list_all(type_filter, status_filter)
    summary = review_model.stats()
    return render_template(
        "reviews.html",
        view_mode="admin",
        reviews=all_reviews,
        stats=summary,
        filters={"type": type_filter, "status": status_filter},
        errors={},
        form={},
    )


@reviews_bp.route("/admin/reviews/<int:review_id>/reply", methods=["POST"])
@admin_required
def admin_reply(review_id):
    status = request.form.get("status", "lu")
    if status not in ("en_attente", "lu", "resolu"):
        status = "lu"
    reply_text = " ".join(request.form.get("admin_reply", "").split())[:1000]

    if review_model.reply_and_update(review_id, status, reply_text):
        flash("Retour mis à jour et réponse enregistrée.", "success")
    else:
        flash("Élément introuvable.", "error")
    return redirect(url_for("reviews.admin_index"))


@reviews_bp.route("/admin/reviews/<int:review_id>/delete", methods=["POST"])
@admin_required
def admin_delete(review_id):
    if review_model.delete(review_id):
        flash("Avis / réclamation supprimé.", "success")
    else:
        flash("Élément introuvable.", "error")
    return redirect(url_for("reviews.admin_index"))


@reviews_bp.route("/admin/password", methods=["POST"])
@admin_required
def admin_password():
    uid = session["user_id"]
    admin = user_model.get_with_hash(uid)
    current = request.form.get("current_password", "")
    new = request.form.get("new_password", "")
    confirm = request.form.get("confirm_password", "")

    if not current or not check_password_hash(admin["password_hash"], current):
        flash("Mot de passe actuel incorrect.", "error")
        return redirect(url_for("reviews.admin_index"))

    if len(new) < 8 or not (re.search(r"[A-Za-z]", new) and re.search(r"\d", new)):
        flash("Le nouveau mot de passe doit contenir au moins 8 caractères, une lettre et un chiffre.", "error")
        return redirect(url_for("reviews.admin_index"))

    if new != confirm:
        flash("La confirmation du nouveau mot de passe ne correspond pas.", "error")
        return redirect(url_for("reviews.admin_index"))

    user_model.update_password(uid, generate_password_hash(new))
    flash("Mot de passe administrateur mis à jour avec succès.", "success")
    return redirect(url_for("reviews.admin_index"))