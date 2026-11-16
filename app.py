import os
import secrets
from datetime import datetime, timedelta

from flask import Flask, abort, flash, g, redirect, request, session, url_for

from database import close_db, init_db
from models import settings as settings_model
from models import user as user_model
from routes.advice import advice_bp
from routes.auth import auth_bp, is_user_admin
from routes.budgets import budgets_bp
from routes.dashboard import dashboard_bp
from routes.goals import goals_bp
from routes.notifications import notifications_bp
from routes.profile import profile_bp
from routes.reviews import reviews_bp
from routes.settings import settings_bp
from routes.statistics import statistics_bp
from routes.transactions import transactions_bp
from utils import currency_symbol, format_money
from routes.chatbot import chatbot_bp   
app = Flask(__name__, static_folder="public/static")
# ⚠️ En production : définir la variable d'environnement ECOBUDGET_SECRET
app.config["SECRET_KEY"] = os.environ.get("ECOBUDGET_SECRET", "dev-secret-a-changer-absolument")
app.config["PERMANENT_SESSION_LIFETIME"] = timedelta(days=30)
app.config["SESSION_COOKIE_HTTPONLY"] = True
app.config["SESSION_COOKIE_SAMESITE"] = "Lax"
app.config["MAX_CONTENT_LENGTH"] = 2 * 1024 * 1024  # 2 Mo max (photo de profil)
app.config["SESSION_COOKIE_SECURE"] = bool(os.environ.get("VERCEL"))
app.teardown_appcontext(close_db)
for blueprint in (auth_bp, dashboard_bp, transactions_bp, profile_bp, budgets_bp,
                  goals_bp, notifications_bp, statistics_bp, 
                  advice_bp, reviews_bp, settings_bp,chatbot_bp):
    app.register_blueprint(blueprint)


# ---------- Filtres Jinja (formatage) ----------
@app.template_filter("da")
def format_da(value):
    """2500.5 -> '2 500,50 DA' (symbole selon la devise choisie dans les Paramètres)"""
    return format_money(value, 2)


@app.template_filter("fr_date")
def format_date_fr(value):
    """'2026-11-10' -> '10/11/2026'"""
    try:
        return datetime.strptime(value, "%Y-%m-%d").strftime("%d/%m/%Y")
    except (TypeError, ValueError):
        return value


# ---------- Protection CSRF ----------
def csrf_token():
    if "_csrf" not in session:
        session["_csrf"] = secrets.token_hex(16)
    return session["_csrf"]


@app.before_request
def check_csrf():
    if request.method == "POST":
        sent = request.form.get("_csrf") or request.headers.get("X-CSRFToken") or ""
        if not secrets.compare_digest(sent, session.get("_csrf", "")):
            abort(400)


# ---------- Paramètres de l'utilisateur (thème, devise, ...) ----------
@app.before_request
def load_user_settings():
    g.settings = None
    g.currency = "DA"
    if request.endpoint == "static":
        return
    user_id = session.get("user_id")
    if user_id:
        g.settings = settings_model.get(user_id)
        g.currency = g.settings["currency"]


# ---------- Pas de cache : évite d'afficher la page d'un autre rôle (bouton Retour) ----------
@app.after_request
def no_store(resp):
    if request.endpoint != "static":
        resp.headers["Cache-Control"] = "no-store"
    return resp


@app.errorhandler(400)
def bad_request(e):
    return "Requête invalide. Rechargez la page et réessayez.", 400


@app.errorhandler(413)
def too_large(e):
    flash("Image trop volumineuse (2 Mo maximum).", "error")
    return redirect(url_for("profile.index"))


@app.errorhandler(404)
def not_found(e):
    return "Page introuvable.", 404


# ---------- Variables disponibles dans tous les templates ----------
@app.context_processor
def inject_globals():
    user, unread = None, 0
    user_id = session.get("user_id")
    if user_id:
        user = user_model.get_by_id(user_id)
        if user:
            unread = user_model.count_unread_notifications(user_id)
    return {
        "current_user": user,
        "is_admin": is_user_admin(user),
        "unread_count": unread,
        "csrf_token": csrf_token,
        "user_settings": g.get("settings") if user else None,
        "currency": currency_symbol(),
    }


@app.route("/")
def home():
    return redirect(url_for("dashboard.index"))


with app.app_context():
    init_db()

if __name__ == "__main__":
    app.run(debug=True)