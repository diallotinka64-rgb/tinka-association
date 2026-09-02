from fastapi import FastAPI, HTTPException, Depends, Form, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, StreamingResponse, RedirectResponse
import sqlite3
import io
import uvicorn
from typing import Optional
from reportlab.lib.pagesizes import letter
from reportlab.pdfgen import canvas

app = FastAPI(title="API Gestion Association Tinka", version="6.9")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

DB_NAME = "association.db"

def get_db():
    conn = sqlite3.connect(DB_NAME)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
    finally:
        conn.close()

def init_db():
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS adherents (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        nom TEXT NOT NULL,
        prenom TEXT NOT NULL,
        email TEXT UNIQUE NOT NULL,
        telephone TEXT,
        adresse TEXT,
        secteur TEXT,
        mot_de_passe TEXT NOT NULL,
        role TEXT CHECK(role IN ('admin', 'tresorier', 'membre')) DEFAULT 'membre',
        statut TEXT CHECK(statut IN ('en_attente', 'actif', 'inactif')) DEFAULT 'en_attente',
        date_adhesion TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )
    """)
    cursor.execute("SELECT COUNT(*) FROM adherents")
    if cursor.fetchone()[0] == 0:
        cursor.execute("""
        INSERT INTO adherents (nom, prenom, email, telephone, adresse, secteur, mot_de_passe, role, statut)
        VALUES ('Admin', 'Super', 'admin@tinka.com', '770000000', 'Siège', 'Bureau', 'admin123', 'admin', 'actif')
        """)

    cursor.execute("""
    CREATE TABLE IF NOT EXISTS cotisations (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        adherent_id INTEGER NOT NULL,
        montant REAL NOT NULL,
        periode TEXT NOT NULL,
        date_paiement TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        mode_paiement TEXT CHECK(mode_paiement IN ('especes', 'mobile_money', 'virement')),
        FOREIGN KEY (adherent_id) REFERENCES adherents(id) ON DELETE CASCADE
    )
    """)

    cursor.execute("""
    CREATE TABLE IF NOT EXISTS aides (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        adherent_id INTEGER NOT NULL,
        motif TEXT NOT NULL,
        montant_demande REAL NOT NULL,
        statut_validation TEXT CHECK(statut_validation IN ('en_attente', 'approuve', 'rejete')) DEFAULT 'en_attente',
        date_demande TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY (adherent_id) REFERENCES adherents(id) ON DELETE CASCADE
    )
    """)

    cursor.execute("""
    CREATE TABLE IF NOT EXISTS decaissements (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        motif TEXT NOT NULL,
        montant REAL NOT NULL,
        beneficiaire TEXT NOT NULL,
        date_decaissement TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )
    """)

    cursor.execute("""
    CREATE TABLE IF NOT EXISTS projets (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        titre TEXT NOT NULL,
        description TEXT,
        objectifs TEXT,
        cout REAL,
        chronologie TEXT CHECK(chronologie IN ('passe', 'actuel', 'avenir')) DEFAULT 'actuel',
        statut TEXT CHECK(statut IN ('planifie', 'en_cours', 'termine')) DEFAULT 'planifie'
    )
    """)
    conn.commit()
    conn.close()

init_db()

# --- ROUTES FORMULAIRES ---
@app.post("/login-form/")
def login_form(email: str = Form(...), mot_de_passe: str = Form(...), db: sqlite3.Connection = Depends(get_db)):
    cursor = db.cursor()
    cursor.execute("SELECT * FROM adherents WHERE email = ? AND mot_de_passe = ?", (email, mot_de_passe))
    user = cursor.fetchone()
    if not user:
        return HTMLResponse(content="<script>alert('Email ou mot de passe incorrect.'); window.location.href='/';</script>", status_code=401)
    if user['statut'] != 'actif':
        return HTMLResponse(content="<script>alert('Votre compte est en attente de validation par l\\'administrateur.'); window.location.href='/';</script>", status_code=403)
    return RedirectResponse(url=f"/dashboard?id={user['id']}", status_code=status.HTTP_303_SEE_OTHER)

@app.post("/adherents-form/")
def creer_adherent_form(
    nom: str = Form(...), prenom: str = Form(...), email: str = Form(...),
    telephone: str = Form(...), adresse: str = Form(...), secteur: str = Form(...),
    mot_de_passe: str = Form(...), db: sqlite3.Connection = Depends(get_db)
):
    cursor = db.cursor()
    try:
        cursor.execute(
            """INSERT INTO adherents (nom, prenom, email, telephone, adresse, secteur, mot_de_passe) 
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (nom, prenom, email, telephone, adresse, secteur, mot_de_passe)
        )
        db.commit()
        return HTMLResponse(content="<script>alert('Compte créé avec succès ! En attente de validation.'); window.location.href='/';</script>")
    except sqlite3.IntegrityError:
        return HTMLResponse(content="<script>alert('Cet email est déjà utilisé.'); window.location.href='/';</script>")

@app.post("/admin/valider-adherent")
def valider_adherent(user_id: int = Form(...), adherent_id: int = Form(...), db: sqlite3.Connection = Depends(get_db)):
    cursor = db.cursor()
    cursor.execute("UPDATE adherents SET statut = 'actif' WHERE id = ?", (adherent_id,))
    db.commit()
    return RedirectResponse(url=f"/dashboard?id={user_id}", status_code=status.HTTP_303_SEE_OTHER)

@app.post("/admin/reset-password")
def reset_password(user_id: int = Form(...), adherent_id: int = Form(...), nouveau_mdp: str = Form(...), db: sqlite3.Connection = Depends(get_db)):
    cursor = db.cursor()
    cursor.execute("UPDATE adherents SET mot_de_passe = ? WHERE id = ?", (nouveau_mdp, adherent_id))
    db.commit()
    return HTMLResponse(content=f"<script>alert('Mot de passe réinitialisé avec succès !'); window.location.href='/dashboard?id={user_id}';</script>")

@app.post("/admin/statuer-aide")
def statuer_aide(user_id: int = Form(...), aide_id: int = Form(...), statut_aide: str = Form(...), db: sqlite3.Connection = Depends(get_db)):
    cursor = db.cursor()
    cursor.execute("UPDATE aides SET statut_validation = ? WHERE id = ?", (statut_aide, aide_id))
    db.commit()
    return RedirectResponse(url=f"/dashboard?id={user_id}", status_code=status.HTTP_303_SEE_OTHER)

@app.post("/cotisations-form/")
def ajouter_cotisation(user_id: int = Form(...), adherent_id: int = Form(...), montant: float = Form(...), periode: str = Form(...), mode_paiement: str = Form(...), db: sqlite3.Connection = Depends(get_db)):
    cursor = db.cursor()
    cursor.execute("INSERT INTO cotisations (adherent_id, montant, periode, mode_paiement) VALUES (?, ?, ?, ?)", (adherent_id, montant, periode, mode_paiement))
    db.commit()
    return RedirectResponse(url=f"/dashboard?id={user_id}", status_code=status.HTTP_303_SEE_OTHER)

@app.post("/aides-form/")
def demander_aide(user_id: int = Form(...), motif: str = Form(...), montant_demande: float = Form(...), db: sqlite3.Connection = Depends(get_db)):
    cursor = db.cursor()
    cursor.execute("INSERT INTO aides (adherent_id, motif, montant_demande) VALUES (?, ?, ?)", (user_id, motif, montant_demande))
    db.commit()
    return RedirectResponse(url=f"/dashboard?id={user_id}", status_code=status.HTTP_303_SEE_OTHER)

@app.post("/decaissements-form/")
def ajouter_decaissement(user_id: int = Form(...), motif: str = Form(...), montant: float = Form(...), beneficiaire: str = Form(...), db: sqlite3.Connection = Depends(get_db)):
    cursor = db.cursor()
    cursor.execute("INSERT INTO decaissements (motif, montant, beneficiaire) VALUES (?, ?, ?)", (motif, montant, beneficiaire))
    db.commit()
    return RedirectResponse(url=f"/dashboard?id={user_id}", status_code=status.HTTP_303_SEE_OTHER)

@app.post("/projets-form/")
def ajouter_projet(user_id: int = Form(...), titre: str = Form(...), description: str = Form(...), objectifs: str = Form(...), cout: float = Form(...), chronologie: str = Form(...), statut: str = Form(...), db: sqlite3.Connection = Depends(get_db)):
    cursor = db.cursor()
    cursor.execute("INSERT INTO projets (titre, description, objectifs, cout, chronologie, statut) VALUES (?, ?, ?, ?, ?, ?)", (titre, description, objectifs, cout, chronologie, statut))
    db.commit()
    return RedirectResponse(url=f"/dashboard?id={user_id}", status_code=status.HTTP_303_SEE_OTHER)

@app.get("/cotisations/export-pdf")
def export_cotisations_pdf(db: sqlite3.Connection = Depends(get_db)):
    cursor = db.cursor()
    cursor.execute("SELECT c.*, a.nom, a.prenom FROM cotisations c JOIN adherents a ON c.adherent_id = a.id")
    cotis = cursor.fetchall()
    buffer = io.BytesIO()
    p = canvas.Canvas(buffer, pagesize=letter)
    width, height = letter
    p.setFont("Helvetica-Bold", 16)
    p.drawString(50, height - 50, "Association Tinka - Rapport des Cotisations")
    p.setFont("Helvetica", 10)
    y = height - 100
    total = 0
    for c in cotis:
        p.drawString(50, y, f"{c['prenom']} {c['nom']} - {c['periode']} : {c['montant']} CFA ({c['mode_paiement']})")
        total += c['montant']
        y -= 20
    p.drawString(50, y - 10, f"Total Général : {total} CFA")
    p.save()
    buffer.seek(0)
    return StreamingResponse(buffer, media_type="application/pdf", headers={"Content-Disposition": "attachment; filename=rapport_cotisations.pdf"})

@app.get("/", response_class=HTMLResponse)
def afficher_portail():
    return """
    <!DOCTYPE html>
    <html lang="fr">
    <head>
        <meta charset="UTF-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <title>Gestion Association - Tinka</title>
        <style>
            :root { --primary: #2c3e50; --accent: #27ae60; --bg: #f8f9fa; --info: #2980b9; }
            body { font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif; background-color: var(--bg); margin: 0; padding: 20px; color: #333; }
            .container { max-width: 800px; margin: 0 auto; background: white; padding: 30px; border-radius: 10px; box-shadow: 0 4px 15px rgba(0,0,0,0.05); }
            h1 { color: var(--primary); text-align: center; margin-bottom: 25px; }
            .card { background: #fff; border: 1px solid #e1e8ed; padding: 20px; border-radius: 8px; margin-bottom: 20px; }
            .card h2 { margin-top: 0; color: var(--accent); font-size: 1.2rem; border-bottom: 2px solid #f1f1f1; padding-bottom: 8px; }
            .form-group { margin-bottom: 12px; }
            label { display: block; margin-bottom: 4px; font-weight: 600; font-size: 0.9rem; }
            input, select, textarea { width: 100%; padding: 8px; border: 1px solid #ccc; border-radius: 5px; box-sizing: border-box; }
            button { background-color: var(--accent); color: white; border: none; padding: 10px 15px; border-radius: 5px; cursor: pointer; font-size: 1rem; width: 100%; font-weight: bold; }
            button:hover { background-color: #219653; }
        </style>
    </head>
    <body>
        <div class="container">
            <h1>Association Tinka - Portail</h1>
            <div class="card">
                <h2>Connexion</h2>
                <form action="/login-form/" method="POST">
                    <div class="form-group"><label>Email :</label><input type="email" name="email" required></div>
                    <div class="form-group"><label>Mot de passe :</label><input type="password" name="mot_de_passe" required></div>
                    <button type="submit" style="background-color: var(--info);">Se connecter</button>
                </form>
            </div>
            <div class="card">
                <h2>Inscription d'un Nouvel Adhérent</h2>
                <form action="/adherents-form/" method="POST">
                    <div class="form-group"><label>Nom :</label><input type="text" name="nom" required></div>
                    <div class="form-group"><label>Prénom :</label><input type="text" name="prenom" required></div>
                    <div class="form-group"><label>Email :</label><input type="email" name="email" required></div>
                    <div class="form-group"><label>Téléphone :</label><input type="text" name="telephone" required></div>
                    <div class="form-group"><label>Adresse :</label><input type="text" name="adresse" required></div>
                    <div class="form-group"><label>Secteur :</label><input type="text" name="secteur" required></div>
                    <div class="form-group"><label>Mot de passe :</label><input type="password" name="mot_de_passe" required></div>
                    <button type="submit">S'inscrire</button>
                </form>
            </div>
        </div>
    </body>
    </html>
    """

@app.get("/dashboard", response_class=HTMLResponse)
def afficher_dashboard(id: int, db: sqlite3.Connection = Depends(get_db)):
    cursor = db.cursor()
    cursor.execute("SELECT * FROM adherents WHERE id = ?", (id,))
    user = cursor.fetchone()
    if not user:
        return RedirectResponse(url="/", status_code=303)

    is_admin = user['role'] in ['admin', 'tresorier']

    # Données globales ou personnelles selon le rôle
    if is_admin:
        cursor.execute("SELECT SUM(montant) as total FROM cotisations")
        cotis = cursor.fetchone()['total'] or 0.0
        cursor.execute("SELECT SUM(montant_demande) as total FROM aides WHERE statut_validation = 'approuve'")
        aides_versees = cursor.fetchone()['total'] or 0.0
        cursor.execute("SELECT SUM(montant) as total FROM decaissements")
        decs = cursor.fetchone()['total'] or 0.0
        solde = cotis - (aides_versees + decs)

        cursor.execute("SELECT * FROM adherents")
        all_adherents = cursor.fetchall()

        cursor.execute("SELECT c.*, a.nom, a.prenom FROM cotisations c JOIN adherents a ON c.adherent_id = a.id")
        all_cotisations = cursor.fetchall()

        cursor.execute("SELECT ai.*, a.nom, a.prenom FROM aides ai JOIN adherents a ON ai.adherent_id = a.id")
        all_aides = cursor.fetchall()

        cursor.execute("SELECT * FROM decaissements")
        all_decaissements = cursor.fetchall()
    else:
        # Données spécifiques au membre connecté
        cursor.execute("SELECT SUM(montant) as total FROM cotisations WHERE adherent_id = ?", (user['id'],))
        cotis = cursor.fetchone()['total'] or 0.0

        cursor.execute("SELECT * FROM cotisations WHERE adherent_id = ?", (user['id'],))
        all_cotisations = cursor.fetchall()

        cursor.execute("SELECT ai.*, a.nom, a.prenom FROM aides ai JOIN adherents a ON ai.adherent_id = a.id WHERE ai.adherent_id = ?", (user['id'],))
        all_aides = cursor.fetchall()

    cursor.execute("SELECT * FROM projets")
    all_projets = cursor.fetchall()

    # --- HTML SECTION ADMIN ---
    admin_sections_html = ""
    if is_admin:
        options_adherents = "".join([f"<option value='{a['id']}'>{a['prenom']} {a['nom']} ({a['secteur']})</option>" for a in all_adherents if a['statut'] == 'actif' and a['role'] != 'admin'])
        
        adherents_html = ""
        for a in all_adherents:
            actions_admin = ""
            if a['statut'] == 'en_attente':
                actions_admin += f"""
                <form action="/admin/valider-adherent" method="POST" style="display:inline; margin-left: 5px;">
                    <input type="hidden" name="user_id" value="{user['id']}">
                    <input type="hidden" name="adherent_id" value="{a['id']}">
                    <button type="submit" style="background:#27ae60; padding:2px 8px; font-size:0.8rem; width:auto;">Valider</button>
                </form>"""
            actions_admin += f"""
            <form action="/admin/reset-password" method="POST" style="display:inline-block; margin-left: 5px; margin-top:5px;">
                <input type="hidden" name="user_id" value="{user['id']}">
                <input type="hidden" name="adherent_id" value="{a['id']}">
                <input type="text" name="nouveau_mdp" placeholder="Nouveau mdp" required style="width:110px; padding:2px; display:inline-block;">
                <button type="submit" style="background:#d35400; padding:2px 6px; font-size:0.75rem; width:auto;">Réinitialiser MDP</button>
            </form>"""
            adherents_html += f"<li><b>{a['prenom']} {a['nom']}</b> ({a['email']}) - Secteur: {a['secteur']} [Statut: <b>{a['statut']}</b>] {actions_admin}</li>"

        aides_admin_html = ""
        for ai in all_aides:
            validation_actions = ""
            if ai['statut_validation'] == 'en_attente':
                validation_actions = f"""
                <form action="/admin/statuer-aide" method="POST" style="display:inline; margin-left: 5px;">
                    <input type="hidden" name="user_id" value="{user['id']}">
                    <input type="hidden" name="aide_id" value="{ai['id']}">
                    <input type="hidden" name="statut_aide" value="approuve">
                    <button type="submit" style="background:#27ae60; padding:2px 6px; font-size:0.75rem; width:auto;">Approuver</button>
                </form>
                <form action="/admin/statuer-aide" method="POST" style="display:inline; margin-left: 5px;">
                    <input type="hidden" name="user_id" value="{user['id']}">
                    <input type="hidden" name="aide_id" value="{ai['id']}">
                    <input type="hidden" name="statut_aide" value="rejete">
                    <button type="submit" style="background:#c0392b; padding:2px 6px; font-size:0.75rem; width:auto;">Rejeter</button>
                </form>"""
            aides_admin_html += f"<li><b>{ai['prenom']} {ai['nom']}</b> - Motif : {ai['motif']} ({ai['montant_demande']} CFA) [<b>{ai['statut_validation']}</b>] {validation_actions}</li>"

        decaissements_html = "".join([f"<li>{d['motif']} - <b>{d['montant']} CFA</b> (Bénéficiaire: {d['beneficiaire']})</li>" for d in all_decaissements])

        admin_sections_html = f"""
        <div class="card">
            <h2>Trésorerie Globale de l'Association</h2>
            <div class="dashboard-box">
                <div>Total Cotisations : {cotis} CFA</div>
                <div>Aides Versées : {aides_versees} CFA</div>
                <div>Décaissements : {decs} CFA</div>
            </div>
            <div style="text-align: center; font-size: 1.2rem; font-weight: bold;">Solde Caisse : <span style="color: #27ae60;">{solde} CFA</span></div>
        </div>

        <div class="card">
            <h2>Gestion & Validation des Adhérents</h2>
            <ul>{adherents_html}</ul>
        </div>

        <div class="card">
            <h2>Suivi & Validation des Demandes d'Aide</h2>
            <ul>{aides_admin_html or '<li>Aucune demande en attente.</li>'}</ul>
        </div>

        <div class="card">
            <h2>Enregistrer une Cotisation pour un Membre</h2>
            <form action="/cotisations-form/" method="POST">
                <input type="hidden" name="user_id" value="{user['id']}">
                <div class="form-group"><label>Adhérent :</label><select name="adherent_id" required><option value="">-- Choisir --</option>{options_adherents}</select></div>
                <div class="form-group"><label>Montant (CFA) :</label><input type="number" name="montant" required></div>
                <div class="form-group"><label>Période (ex: 2026-09) :</label><input type="text" name="periode" required></div>
                <div class="form-group"><label>Mode de paiement :</label><select name="mode_paiement"><option value="especes">Espèces</option><option value="mobile_money">Mobile Money</option><option value="virement">Virement</option></select></div>
                <button type="submit" style="background-color: #8e44ad;">Enregistrer la cotisation</button>
            </form>
        </div>

        <div class="card">
            <h2>Enregistrer un Décaissement (Dépense)</h2>
            <ul>{decaissements_html or '<li>Aucun décaissement.</li>'}</ul>
            <hr style="border:0; border-top:1px solid #eee; margin:15px 0;">
            <form action="/decaissements-form/" method="POST">
                <input type="hidden" name="user_id" value="{user['id']}">
                <div class="form-group"><label>Motif :</label><input type="text" name="motif" required></div>
                <div class="form-group"><label>Montant :</label><input type="number" name="montant" required></div>
                <div class="form-group"><label>Bénéficiaire :</label><input type="text" name="beneficiaire" required></div>
                <button type="submit" style="background-color: #c0392b;">Enregistrer la dépense</button>
            </form>
        </div>

        <div class="card">
            <h2>Ajouter un Projet à l'Association</h2>
            <form action="/projets-form/" method="POST">
                <input type="hidden" name="user_id" value="{user['id']}">
                <div class="form-group"><label>Titre :</label><input type="text" name="titre" required></div>
                <div class="form-group"><label>Description :</label><textarea name="description" rows="2"></textarea></div>
                <div class="form-group"><label>Objectifs :</label><textarea name="objectifs" rows="2"></textarea></div>
                <div class="form-group"><label>Coût Prévu (CFA) :</label><input type="number" name="cout" required></div>
                <div class="form-group"><label>Chronologie :</label><select name="chronologie"><option value="passe">Passé</option><option value="actuel" selected>Actuel</option><option value="avenir">À venir</option></select></div>
                <div class="form-group"><label>Statut :</label><select name="statut"><option value="planifie">Planifié</option><option value="en_cours">En cours</option><option value="termine">Terminé</option></select></div>
                <button type="submit" style="background-color: #2980b9;">Ajouter le projet</button>
            </form>
        </div>
        """

    # --- HTML SECTION MEMBRE ---
    member_sections_html = ""
    if not is_admin:
        aides_membre_html = "".join([f"<li>Motif : {ai['motif']} ({ai['montant_demande']} CFA) - Statut : [<b>{ai['statut_validation']}</b>]</li>" for ai in all_aides])
        cotisations_membre_html = "".join([f"<li>Période {c['periode']} : {c['montant']} CFA ({c['mode_paiement']})</li>" for c in all_cotisations])

        member_sections_html = f"""
        <div class="card">
            <h2>Mon Espace Cotisations</h2>
            <p><b>Total de vos cotisations versées :</b> <span style="color: #27ae60; font-weight: bold;">{cotis} CFA</span></p>
            <ul>{cotisations_membre_html or '<li>Aucune cotisation enregistrée pour le moment.</li>'}</ul>
        </div>

        <div class="card">
            <h2>Mes Demandes d'Aide</h2>
            <ul>{aides_membre_html or '<li>Aucune demande soumise.</li>'}</ul>
            <hr style="border:0; border-top:1px solid #eee; margin:15px 0;">
            <h3 style="font-size:1rem; color:#2980b9;">Faire une nouvelle demande d'aide</h3>
            <form action="/aides-form/" method="POST">
                <input type="hidden" name="user_id" value="{user['id']}">
                <div class="form-group"><label>Motif :</label><input type="text" name="motif" required></div>
                <div class="form-group"><label>Montant demandé (CFA) :</label><input type="number" name="montant_demande" required></div>
                <button type="submit" style="background-color: #d35400;">Soumettre la demande</button>
            </form>
        </div>
        """

    # Projets visibles pour tous
    projets_html = "".join([f"<li><b>{p['titre']}</b> [Statut: {p['statut']} | Coût: {p['cout']} CFA]<br><small>{p['description']}</small></li>" for p in all_projets])

    return f"""
    <!DOCTYPE html>
    <html lang="fr">
    <head>
        <meta charset="UTF-8">
        <title>Tableau de bord - Association Tinka</title>
        <style>
            :root {{ --primary: #2c3e50; --accent: #27ae60; --bg: #f8f9fa; --info: #2980b9; --pdf: #c0392b; --danger: #e74c3c; }}
            body {{ font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif; background-color: var(--bg); margin: 0; padding: 20px; color: #333; }}
            .container {{ max-width: 1000px; margin: 0 auto; background: white; padding: 30px; border-radius: 10px; box-shadow: 0 4px 15px rgba(0,0,0,0.05); }}
            h1 {{ color: var(--primary); text-align: center; }}
            .card {{ background: #fff; border: 1px solid #e1e8ed; padding: 20px; border-radius: 8px; margin-bottom: 20px; }}
            .card h2 {{ margin-top: 0; color: var(--accent); font-size: 1.2rem; border-bottom: 2px solid #f1f1f1; padding-bottom: 8px; display: flex; justify-content: space-between; align-items: center; }}
            .dashboard-box {{ display: flex; justify-content: space-around; background: #e8f8f5; padding: 15px; border-radius: 6px; text-align: center; margin-bottom: 15px; font-weight: bold; font-size: 1.1rem; color: #16a085; }}
            .form-group {{ margin-bottom: 12px; }}
            label {{ display: block; margin-bottom: 4px; font-weight: 600; font-size: 0.9rem; }}
            input, select, textarea {{ width: 100%; padding: 8px; border: 1px solid #ccc; border-radius: 5px; box-sizing: border-box; }}
            button {{ background-color: var(--accent); color: white; border: none; padding: 10px 15px; border-radius: 5px; cursor: pointer; font-size: 1rem; width: 100%; font-weight: bold; }}
            button:hover {{ background-color: #219653; }}
            .btn-danger {{ background-color: var(--danger); color: white; padding: 8px 15px; text-decoration: none; border-radius: 5px; font-weight: bold; display: inline-block; }}
            .btn-pdf {{ background-color: var(--pdf); color: white; padding: 5px 10px; text-decoration: none; border-radius: 4px; font-size: 0.85rem; }}
            ul {{ padding-left: 20px; }}
            li {{ margin-bottom: 10px; font-size: 0.9rem; }}
        </style>
    </head>
    <body>
        <div class="container">
            <h1>Association Tinka - Tableau de Bord</h1>
            
            <div class="card" style="background: #eaf2f8;">
                <h2>Mon Profil</h2>
                <p><b>Nom :</b> {user['prenom']} {user['nom']}</p>
                <p><b>Secteur :</b> {user['secteur']} | <b>Email :</b> {user['email']}</p>
                <p><b>Rôle :</b> <span style="text-transform: uppercase; color: #2980b9; font-weight: bold;">{user['role']}</span></p>
                <a href="/" class="btn-danger">Se déconnecter</a>
            </div>

            {admin_sections_html}

            {member_sections_html}

            <div class="card">
                <h2>
                    Projets de l'Association
                    {f'<a href="/cotisations/export-pdf" class="btn-pdf" target="_blank">Télécharger Rapport PDF</a>' if is_admin else ''}
                </h2>
                <ul>{projets_html or '<li>Aucun projet enregistré.</li>'}</ul>
            </div>
        </div>
    </body>
    </html>
    """

if __name__ == "__main__":
    uvicorn.run("app_asso:app", host="127.0.0.1", port=8000, reload=True)