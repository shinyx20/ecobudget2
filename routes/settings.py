from datetime import datetime
from io import BytesIO

from flask import (Blueprint, Response, flash, jsonify, redirect, render_template,
                   request, session, url_for)
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import cm
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle
from werkzeug.security import check_password_hash

from database import get_db
from models import settings as settings_model
from models import user as user_model
from routes.auth import login_required
from routes.profile import _remove_file
from utils import currency_symbol, format_money

settings_bp = Blueprint("settings", __name__)


@settings_bp.route("/settings")
@login_required
def index():
    return render_template(
        "settings.html",
        s=settings_model.get(session["user_id"]),
        currency_options=list(settings_model.CURRENCIES.items()),
    )


@settings_bp.route("/settings/save", methods=["POST"])
@login_required
def save():
    theme = request.form.get("theme", "")
    language = request.form.get("language", "")
    currency = request.form.get("currency", "")
    notifications = request.form.get("notifications") == "on"
    compact = request.form.get("compact") == "on"

    if (theme not in settings_model.THEMES
            or language not in settings_model.LANGUAGES
            or currency not in settings_model.CURRENCIES):
        flash("Valeur invalide : les paramètres n'ont pas été enregistrés.", "error")
        return redirect(url_for("settings.index"))

    settings_model.save(session["user_id"], theme, language, currency, notifications, compact)
    flash("Paramètres enregistrés.", "success")
    return redirect(url_for("settings.index"))


@settings_bp.route("/settings/theme", methods=["POST"])
@login_required
def theme():
    """Appelé par le bouton lune/soleil de la barre du haut."""
    data = request.get_json(silent=True) or {}
    value = data.get("theme")
    if value not in settings_model.THEMES:
        return jsonify(ok=False), 400
    settings_model.set_theme(session["user_id"], value)
    return jsonify(ok=True)


def _pdf_money(value):
    """Formate les montants avec des espaces normaux pour compatibilité PDF Helvetica."""
    return format_money(value, 2).replace("\u202f", " ").replace("\u00a0", " ")


def _styled_table(rows_data, col_widths):
    """Crée un tableau PDF aux couleurs d'EcoBudget."""
    table = Table(rows_data, colWidths=col_widths, repeatRows=1)
    table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#123B35")),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("FONTSIZE", (0, 0), (-1, 0), 9.5),
        ("BOTTOMPADDING", (0, 0), (-1, 0), 8),
        ("TOPPADDING", (0, 0), (-1, 0), 8),
        ("FONTNAME", (0, 1), (-1, -1), "Helvetica"),
        ("FONTSIZE", (0, 1), (-1, -1), 9),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#F1F5F2")]),
        ("GRID", (0, 0), (-1, -1), 0.4, colors.HexColor("#D1DDD7")),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("LEFTPADDING", (0, 0), (-1, -1), 6),
        ("RIGHTPADDING", (0, 0), (-1, -1), 6),
        ("TOPPADDING", (0, 1), (-1, -1), 6),
        ("BOTTOMPADDING", (0, 1), (-1, -1), 6),
    ]))
    return table


@settings_bp.route("/settings/export")
@login_required
def export():
    """Télécharge toutes les données de l'utilisateur au format PDF."""
    uid = session["user_id"]
    db = get_db()

    def rows(sql):
        return [dict(r) for r in db.execute(sql, (uid,)).fetchall()]

    user = user_model.get_by_id(uid)
    user_settings = settings_model.get(uid)
    sym = currency_symbol()

    transactions = rows(
        "SELECT t.date, t.type, t.amount, c.name AS categorie, t.description "
        "FROM transactions t JOIN categories c ON c.id = t.category_id "
        "WHERE t.user_id = ? ORDER BY t.date DESC, t.id DESC"
    )
    budgets = rows(
        "SELECT b.month AS mois, COALESCE(c.name, 'Budget global') AS categorie, b.amount AS montant "
        "FROM budgets b LEFT JOIN categories c ON c.id = b.category_id "
        "WHERE b.user_id = ? ORDER BY b.month DESC"
    )
    goals = rows(
        "SELECT name AS nom, target_amount AS cible, saved_amount AS economise, "
        "COALESCE(deadline, '—') AS echeance FROM savings_goals WHERE user_id = ?"
    )

    total_income = sum(t["amount"] for t in transactions if t["type"] == "income")
    total_expense = sum(t["amount"] for t in transactions if t["type"] == "expense")
    balance = total_income - total_expense

    buffer = BytesIO()
    doc = SimpleDocTemplate(
        buffer,
        pagesize=A4,
        leftMargin=1.5 * cm,
        rightMargin=1.5 * cm,
        topMargin=1.5 * cm,
        bottomMargin=1.5 * cm,
        title="Export des données EcoBudget",
    )

    styles = getSampleStyleSheet()
    title_style = ParagraphStyle(
        "EcoTitle",
        parent=styles["Heading1"],
        fontName="Helvetica-Bold",
        fontSize=18,
        textColor=colors.HexColor("#123B35"),
        spaceAfter=4,
    )
    h2_style = ParagraphStyle(
        "EcoH2",
        parent=styles["Heading2"],
        fontName="Helvetica-Bold",
        fontSize=12.5,
        textColor=colors.HexColor("#20A889"),
        spaceBefore=14,
        spaceAfter=6,
    )
    normal_style = ParagraphStyle(
        "EcoNormal",
        parent=styles["Normal"],
        fontSize=9.5,
        textColor=colors.HexColor("#263238"),
    )

    elements = []

    # En-tête du rapport
    elements.append(Paragraph("EcoBudget — Exportation de vos données", title_style))
    elements.append(Paragraph(
        f"Généré le {datetime.now().strftime('%d/%m/%Y à %H:%M')} · Devise : {sym}",
        normal_style,
    ))
    elements.append(Spacer(1, 0.4 * cm))

    # 1. Profil & Résumé financier
    elements.append(Paragraph("1. Profil & Résumé financier", h2_style))
    profile_data = [
        ["Nom complet", user["full_name"], "Total Revenus", _pdf_money(total_income)],
        ["Adresse email", user["email"], "Total Dépenses", _pdf_money(total_expense)],
        ["Membre depuis", str(user["created_at"])[:10], "Solde actuel", _pdf_money(balance)],
        ["Thème / Vue compacte", f"{user_settings['theme']} / {'Oui' if user_settings['compact_view'] else 'Non'}", "Nb. transactions", str(len(transactions))],
    ]
    elements.append(_styled_table(profile_data, [3.8 * cm, 5.2 * cm, 3.8 * cm, 5.2 * cm]))

    # 2. Transactions
    elements.append(Paragraph(f"2. Historique des transactions ({len(transactions)})", h2_style))
    if transactions:
        tx_rows = [["Date", "Type", "Catégorie", "Description", "Montant"]]
        for t in transactions:
            type_label = "Revenu" if t["type"] == "income" else "Dépense"
            sign = "+" if t["type"] == "income" else "-"
            desc = (t["description"] or "—")[:42]
            tx_rows.append([
                t["date"],
                type_label,
                t["categorie"],
                Paragraph(desc, normal_style),
                f"{sign} {_pdf_money(t['amount'])}",
            ])
        elements.append(_styled_table(tx_rows, [2.5 * cm, 2.2 * cm, 3.3 * cm, 6.4 * cm, 3.6 * cm]))
    else:
        elements.append(Paragraph("Aucune transaction enregistrée.", normal_style))

    # 3. Budgets
    elements.append(Paragraph(f"3. Budgets ({len(budgets)})", h2_style))
    if budgets:
        b_rows = [["Mois", "Catégorie", "Montant alloué"]]
        for b in budgets:
            b_rows.append([b["mois"], b["categorie"], _pdf_money(b["montant"])])
        elements.append(_styled_table(b_rows, [4.0 * cm, 8.5 * cm, 5.5 * cm]))
    else:
        elements.append(Paragraph("Aucun budget configuré.", normal_style))

    # 4. Objectifs d'épargne
    elements.append(Paragraph(f"4. Objectifs d'épargne ({len(goals)})", h2_style))
    if goals:
        g_rows = [["Objectif", "Épargné", "Cible", "Progression", "Échéance"]]
        for g in goals:
            pct = round((g["economise"] / g["cible"] * 100), 1) if g["cible"] > 0 else 0
            g_rows.append([
                g["nom"],
                _pdf_money(g["economise"]),
                _pdf_money(g["cible"]),
                f"{pct} %",
                g["echeance"],
            ])
        elements.append(_styled_table(g_rows, [5.2 * cm, 3.4 * cm, 3.4 * cm, 2.8 * cm, 3.2 * cm]))
    else:
        elements.append(Paragraph("Aucun objectif d'épargne enregistré.", normal_style))

    doc.build(elements)
    pdf_bytes = buffer.getvalue()
    buffer.close()

    filename = f"ecobudget-donnees-{datetime.now().strftime('%Y-%m-%d')}.pdf"
    return Response(
        pdf_bytes,
        mimetype="application/pdf",
        headers={"Content-Disposition": f"attachment; filename={filename}"},
    )


@settings_bp.route("/settings/delete-account", methods=["POST"])
@login_required
def delete_account():
    uid = session["user_id"]
    user = user_model.get_with_hash(uid)
    password = request.form.get("password", "")

    if not password or not check_password_hash(user["password_hash"], password):
        flash("Mot de passe incorrect : votre compte n'a pas été supprimé.", "error")
        return redirect(url_for("settings.index"))

    photo = user["photo"]
    user_model.delete_user(uid)
    _remove_file(photo)
    session.clear()
    flash("Votre compte et toutes vos données ont été supprimés.", "success")
    return redirect(url_for("auth.login"))