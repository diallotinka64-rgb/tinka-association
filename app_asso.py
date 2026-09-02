from fastapi import FastAPI, HTTPException, Depends, Form, status, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, StreamingResponse, RedirectResponse
import sqlite3
import io
import datetime
from typing import Optional
from reportlab.lib.pagesizes import letter
from reportlab.pdfgen import canvas

app = FastAPI(title="API Gestion Association Tinka", version="7.8")

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
        photo_profil TEXT DEFAULT '',
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
        photo_projet TEXT DEFAULT '',
        chronologie TEXT CHECK(chronologie IN ('passe', 'actuel', 'avenir')) DEFAULT 'actuel',
        statut TEXT CHECK(statut IN ('planifie', 'en_cours', 'termine')) DEFAULT 'planifie'
    )
    """)
    conn.commit()
    conn.close()

init_db()

@app.post("/login-form/")
def login_form(email: str = Form(...), mot_de_passe: str = Form(...), db: sqlite3.Connection = Depends(get_db)):
    cursor = db.cursor()
    cursor.execute("SELECT * FROM adherents WHERE email = ? AND mot_de_passe = ?", (email, mot_de_passe))
    user = cursor.fetchone()
    if not user:
        return HTMLResponse(content="<script>alert('Email ou mot de passe incorrect.'); window.location.href='/';</script>", status_code=401)
    if user['statut'] != 'actif':
        return HTMLResponse(content="<script>alert('Votre compte est en attente de validation.'); window.location.href='/';</script>", status_code=403)
    return RedirectResponse(url=f"/dashboard?id={user['id']}", status_code=status.HTTP_303_SEE_OTHER)

@app.post("/adherents-form/")
def creer_adherent_form(
    nom: str = Form(...), prenom: str = Form(...), email: str = Form(...),
    telephone: str = Form(...), adresse: str = Form(...), secteur: str = Form(...),
    photo_profil: Optional[str] = Form(""), mot_de_passe: str = Form(...), db: sqlite3.Connection = Depends(get_db)
):
    cursor = db.cursor()
    try:
        cursor.execute(
            """INSERT INTO adherents (nom, prenom, email, telephone, adresse, secteur, photo_profil, mot_de_passe) 
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (nom, prenom, email, telephone, adresse, secteur, photo_profil, mot_de_passe)
        )
        db.commit()
        return HTMLResponse(content="<script>alert('Compte créé avec succès ! En attente de validation.'); window.location.href='/';</script>")
    except sqlite3.IntegrityError:
        return HTMLResponse(content="<script>alert('Cet email est déjà utilisé.'); window.location.href='/';</script>")

@app.post("/modifier-photo")
def modifier_photo(user_id: int = Form(...), photo_profil: str = Form(...), db: sqlite3.Connection = Depends(get_db)):
    cursor = db.cursor()
    cursor.execute("UPDATE adherents SET photo_profil = ? WHERE id = ?", (photo_profil, user_id))
    db.commit()
    return RedirectResponse(url=f"/dashboard?id={user_id}", status_code=status.HTTP_303_SEE_OTHER)

@app.post("/admin/valider-adherent")
def valider_adherent(user_id: int = Form(...), adherent_id: int = Form(...), db: sqlite3.Connection = Depends(get_db)):
    cursor = db.cursor()
    cursor.execute("UPDATE adherents SET statut = 'actif' WHERE id = ?", (adherent_id,))
    db.commit()
    return RedirectResponse(url=f"/dashboard?id={user_id}", status_code=status.HTTP_303_SEE_OTHER)

@app.post("/admin/changer-role")
def changer_role(user_id: int = Form(...), adherent_id: int = Form(...), nouveau_role: str = Form(...), db: sqlite3.Connection = Depends(get_db)):
    cursor = db.cursor()
    cursor.execute("UPDATE adherents SET role = ? WHERE id = ?", (nouveau_role, adherent_id))
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
def ajouter_projet(user_id: int = Form(...), titre: str = Form(...), description: str = Form(...), objectifs: str = Form(...), cout: float = Form(...), photo_projet: str = Form(""), chronologie: str = Form(...), statut: str = Form(...), db: sqlite3.Connection = Depends(get_db)):
    cursor = db.cursor()
    cursor.execute("INSERT INTO projets (titre, description, objectifs, cout, photo_projet, chronologie, statut) VALUES (?, ?, ?, ?, ?, ?, ?)", (titre, description, objectifs, cout, photo_projet, chronologie, statut))
    db.commit()
    return RedirectResponse(url=f"/dashboard?id={user_id}", status_code=status.HTTP_303_SEE_OTHER)

@app.get("/cotisations/export-pdf")
def export_cotisations_pdf(periode: Optional[str] = Query(None), db: sqlite3.Connection = Depends(get_db)):
    cursor = db.cursor()
    if periode:
        cursor.execute("SELECT c.*, a.nom, a.prenom, a.secteur FROM cotisations c JOIN adherents a ON c.adherent_id = a.id WHERE c.periode = ?", (periode,))
        titre_rapport = f"Association Tinka - Rapport des Cotisations ({periode})"
    else:
        cursor.execute("SELECT c.*, a.nom, a.prenom, a.secteur FROM cotisations c JOIN adherents a ON c.adherent_id = a.id")
        titre_rapport = "Association Tinka - Rapport Global des Cotisations"

    cotis = cursor.fetchall()
    buffer = io.BytesIO()
    p = canvas.Canvas(buffer, pagesize=letter)
    width, height = letter

    # En-tête avec Logo de l'association
    p.setFont("Helvetica-Bold", 14)
    p.setFillColorRGB(0.15, 0.25, 0.35)
    p.drawString(50, height - 40, "ASSOCIATION TINKA")
    p.setFont("Helvetica", 9)
    p.setFillColorRGB(0.4, 0.4, 0.4)
    p.drawString(50, height - 55, "Bureau Exécutif & Conseil - Rapport Officiel")
    p.setStrokeColorRGB(0.8, 0.8, 0.8)
    p.line(50, height - 65, width - 50, height - 65)

    p.setFont("Helvetica-Bold", 13)
    p.setFillColorRGB(0, 0, 0)
    p.drawString(50, height - 95, titre_rapport)

    p.setFont("Helvetica", 10)
    y = height - 130
    total = 0
    for c in cotis:
        p.drawString(50, y, f"- {c['prenom']} {c['nom']} ({c['secteur']}) | Période: {c['periode']} | Montant: {c['montant']} CFA ({c['mode_paiement']})")
        total += c['montant']
        y -= 20
        if y < 50:
            p.showPage()
            y = height - 50

    p.setFont("Helvetica-Bold", 11)
    p.drawString(50, y - 10, f"Total Général : {total} CFA")
    p.save()
    buffer.seek(0)
    return StreamingResponse(buffer, media_type="application/pdf", headers={"Content-Disposition": f"attachment; filename=rapport_cotisations_{periode or 'global'}.pdf"})

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
                    <div class="form-group"><label>URL de votre Photo de profil :</label><input type="url" name="photo_profil" placeholder="https://exemple.com/photo.jpg"></div>
                    <div class="form-group"><label>Mot de passe :</label><input type="password" name="mot_de_passe" required></div>
                    <button type="submit">S'inscrire</button>
                </form>
            </div>
        </div>
    </body>
    </html>
    """

@app.get("/dashboard", response_class=HTMLResponse)
def afficher_dashboard(id: int, filtre_periode: Optional[str] = Query(None), db: sqlite3.Connection = Depends(get_db)):
    cursor = db.cursor()
    cursor.execute("SELECT * FROM adherents WHERE id = ?", (id,))
    user = cursor.fetchone()
    if not user:
        return RedirectResponse(url="/", status_code=303)

    is_admin = user['role'] == 'admin'
    is_tresorier = user['role'] in ['admin', 'tresorier']

    annee_courante = datetime.datetime.now().year
    mois_12 = [f"{annee_courante}-{m:02d}" for m in range(1, 13)]

    cursor.execute("SELECT * FROM adherents WHERE statut = 'actif'")
    all_actifs = cursor.fetchall()

    cursor.execute("SELECT * FROM adherents")
    all_adherents = cursor.fetchall()

    cursor.execute("SELECT c.*, a.nom, a.prenom, a.secteur, a.telephone FROM cotisations c JOIN adherents a ON c.adherent_id = a.id")
    all_cotisations = cursor.fetchall()

    cotis_affichees = [c for c in all_cotisations if c['periode'] == filtre_periode] if filtre_periode else all_cotisations

    cursor.execute("SELECT ai.*, a.nom, a.prenom, a.secteur FROM aides ai JOIN adherents a ON ai.adherent_id = a.id")
    all_aides = cursor.fetchall()

    cursor.execute("SELECT * FROM decaissements")
    all_decaissements = cursor.fetchall()

    cursor.execute("SELECT * FROM projets")
    all_projets = cursor.fetchall()

    total_cotis = sum([c['montant'] for c in all_cotisations])
    total_aides_approuvees = sum([ai['montant_demande'] for ai in all_aides if ai['statut_validation'] == 'approuve'])
    total_dec = sum([d['montant'] for d in all_decaissements])
    solde = total_cotis - (total_aides_approuvees + total_dec)

    finance_sections_html = ""
    if is_tresorier:
        options_adherents = "".join([f"<option value='{a['id']}'>{a['prenom']} {a['nom']} — Secteur: {a['secteur']} (Tél: {a['telephone']})</option>" for a in all_actifs if a['role'] != 'admin'])
        
        suivi_retards_html = ""
        for a in all_actifs:
            cotis_membre = [c['periode'] for c in all_cotisations if c['adherent_id'] == a['id']]
            mois_manquants = [m for m in mois_12 if m not in cotis_membre]
            statut_ajour = "<span style='color: #27ae60; font-weight:bold;'>À jour</span>" if not mois_manquants else f"<span style='color: #c0392b;'>Retard ({len(mois_manquants)} mois)</span>"
            suivi_retards_html += f"<li><b>{a['prenom']} {a['nom']}</b> (Secteur: {a['secteur']} | Tél: {a['telephone']}) : {statut_ajour}</li>"

        cotis_table_html = "".join([f"<tr><td>{c['prenom']} {c['nom']}</td><td>{c['secteur']}</td><td><b>{c['montant']} CFA</b></td><td>{c['periode']}</td><td>{c['mode_paiement']}</td></tr>" for c in cotis_affichees])
        options_filtre_mois = "".join([f"<option value='{m}' {'selected' if filtre_periode==m else ''}>{m}</option>" for m in mois_12])

        adherents_gestion_html = ""
        for a in all_adherents:
            actions = ""
            if a['statut'] == 'en_attente':
                actions += f"""
                <form action="/admin/valider-adherent" method="POST" style="display:inline; margin-left:5px;">
                    <input type="hidden" name="user_id" value="{user['id']}"><input type="hidden" name="adherent_id" value="{a['id']}">
                    <button type="submit" style="background:#27ae60; padding:2px 8px; font-size:0.75rem; width:auto;">Valider</button>
                </form>"""
            if is_admin:
                actions += f"""
                <form action="/admin/changer-role" method="POST" style="display:inline-block; margin-left:5px;">
                    <input type="hidden" name="user_id" value="{user['id']}"><input type="hidden" name="adherent_id" value="{a['id']}">
                    <select name="nouveau_role" onchange="this.form.submit()" style="padding:2px; font-size:0.75rem; width:auto; display:inline-block;">
                        <option value="membre" {'selected' if a['role']=='membre' else ''}>Membre</option>
                        <option value="tresorier" {'selected' if a['role']=='tresorier' else ''}>Trésorier</option>
                        <option value="admin" {'selected' if a['role']=='admin' else ''}>Admin</option>
                    </select>
                </form>"""
            
            photo_tag = f"<img src='{a['photo_profil']}' style='width:30px; height:30px; border-radius:50%; object-fit:cover; vertical-align:middle; margin-right:8px;' onerror='this.style.display=\"none\"'>" if a['photo_profil'] else ""
            adherents_gestion_html += f"<li>{photo_tag}<b>{a['prenom']} {a['nom']}</b> — <em>{a['secteur']}</em> (Tél: {a['telephone']}) [Statut: <b>{a['statut']}</b> | Rôle: {a['role']}] {actions}</li>"

        finance_sections_html = f"""
        <div class="card">
            <h2>Trésorerie Globale & Suivi des Cotisations</h2>
            <div class="dashboard-box">
                <div>Total Cotisations : {total_cotis} CFA</div>
                <div>Aides Versées : {total_aides_approuvees} CFA</div>
                <div>Dépenses : {total_dec} CFA</div>
            </div>
            <div style="text-align: center; font-size: 1.2rem; font-weight: bold; margin-bottom: 15px;">Solde Caisse : <span style="color: #27ae60;">{solde} CFA</span></div>
            <h3 style="font-size:1rem; color:#2980b9;">État des cotisations des membres ({annee_courante})</h3>
            <ul>{suivi_retards_html}</ul>
        </div>

        <div class="card">
            <h2>Filtrage et Consultation des Cotisations</h2>
            <form method="GET" action="/dashboard" style="display:flex; gap:10px; margin-bottom:15px; align-items:flex-end;">
                <input type="hidden" name="id" value="{user['id']}">
                <div style="flex:1;" class="form-group" style="margin:0;">
                    <label>Filtrer par Mois :</label>
                    <select name="filtre_periode">
                        <option value="">-- Tous les mois --</option>
                        {options_filtre_mois}
                    </select>
                </div>
                <div>
                    <button type="submit" style="background:#2980b9; padding:9px 15px;">Filtrer</button>
                </div>
                <div>
                    <a href="/cotisations/export-pdf{f'?periode={filtre_periode}' if filtre_periode else ''}" class="btn-pdf" target="_blank" style="padding:10px 15px; display:inline-block; font-size:1rem;">Exporter PDF Filtré</a>
                </div>
            </form>
            <div style="max-height:200px; overflow-y:auto;">
                <table style="width:100%; border-collapse:collapse; font-size:0.9rem;">
                    <tr style="background:#f1f1f1; text-align:left;"><th style="padding:6px;">Membre</th><th style="padding:6px;">Secteur</th><th style="padding:6px;">Montant</th><th style="padding:6px;">Période</th><th style="padding:6px;">Mode</th></tr>
                    {cotis_table_html or '<tr><td colspan="5" style="text-align:center; padding:10px;">Aucune cotisation trouvée pour cette période.</td></tr>'}
                </table>
            </div>
        </div>

        <div class="card">
            <h2>Gestion des Adhérents</h2>
            <ul>{adherents_gestion_html}</ul>
        </div>

        <div class="card">
            <h2>Enregistrer une Cotisation</h2>
            <form action="/cotisations-form/" method="POST">
                <input type="hidden" name="user_id" value="{user['id']}">
                <div class="form-group"><label>Adhérent :</label><select name="adherent_id" required><option value="">-- Choisir --</option>{options_adherents}</select></div>
                <div class="form-group"><label>Montant (CFA) :</label><input type="number" name="montant" required></div>
                <div class="form-group"><label>Période (Mois) :</label><select name="periode" required>{"".join([f"<option value='{m}'>{m}</option>" for m in mois_12])}</select></div>
                <div class="form-group"><label>Mode de paiement :</label><select name="mode_paiement"><option value="especes">Espèces</option><option value="mobile_money">Mobile Money</option><option value="virement">Virement</option></select></div>
                <button type="submit" style="background-color: #8e44ad;">Valider la cotisation</button>
            </form>
        </div>

        {f'''
        <div class="card">
            <h2>Ajouter un Projet au Bureau (Planification)</h2>
            <form action="/projets-form/" method="POST">
                <input type="hidden" name="user_id" value="{user['id']}">
                <div class="form-group"><label>Titre :</label><input type="text" name="titre" required></div>
                <div class="form-group"><label>Description :</label><textarea name="description" rows="2"></textarea></div>
                <div class="form-group"><label>Objectifs :</label><textarea name="objectifs" rows="2"></textarea></div>
                <div class="form-group"><label>Coût Prévu (CFA) :</label><input type="number" name="cout" required></div>
                <div class="form-group"><label>URL de la Photo du projet :</label><input type="url" name="photo_projet" placeholder="https://exemple.com/projet.jpg"></div>
                <div class="form-group"><label>Chronologie :</label><select name="chronologie"><option value="passe">Passé</option><option value="actuel" selected>Actuel</option><option value="avenir">À venir</option></select></div>
                <div class="form-group"><label>Statut :</label><select name="statut"><option value="planifie">Planifié</option><option value="en_cours">En cours</option><option value="termine">Terminé</option></select></div>
                <button type="submit" style="background-color: #2980b9;">Ajouter le projet</button>
            </form>
        </div>
        ''' if is_admin else ''}
        """

    member_sections_html = ""
    if not is_tresorier:
        cotis_perso = [c['periode'] for c in all_cotisations if c['adherent_id'] == user['id']]
        mois_payes_html = "".join([f"<li>Mois de {m} : Payé</li>" for m in mois_12 if m in cotis_perso])
        mois_retard_html = "".join([f"<li style='color:#c0392b;'>Mois de {m} : <b>Non payé</b></li>" for m in mois_12 if m not in cotis_perso])
        
        aides_membre_html = "".join([f"<li>Motif : {ai['motif']} ({ai['montant_demande']} CFA) - Statut : [<b>{ai['statut_validation']}</b>]</li>" for ai in all_aides if ai['adherent_id'] == user['id']])

        member_sections_html = f"""
        <div class="card">
            <h2>Mon Suivi de Cotisations ({annee_courante})</h2>
            <p>Voici l'état de vos versements mensuels :</p>
            <ul>{mois_payes_html}{mois_retard_html}</ul>
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

    projets_html = ""
    for p in all_projets:
        img_tag = f"<img src='{p['photo_projet']}' style='width:100%; max-height:200px; object-fit:cover; border-radius:5px; margin-bottom:10px;' onerror='this.style.display=\"none\"'>" if p['photo_projet'] else ""
        projets_html += f"""
        <div style="border: 1px solid #eee; padding: 15px; border-radius: 6px; margin-bottom: 15px; background: #fafafa;">
            {img_tag}
            <h3 style="margin:0 0 8px 0; color:#2c3e50;">{p['titre']} <span style="font-size:0.8rem; font-weight:normal; background:#e1e8ed; padding:2px 6px; border-radius:4px;">{p['statut']}</span></h3>
            <p style="margin:0 0 5px 0; font-size:0.9rem;">{p['description']}</p>
            <p style="margin:0; font-size:0.85rem; color:#7f8c8d;"><b>Coût :</b> {p['cout']} CFA | <b>Chronologie :</b> {p['chronologie']}</p>
        </div>
        """

    user_photo = f"<img src='{user['photo_profil']}' style='width:70px; height:70px; border-radius:50%; object-fit:cover; float:right;' onerror='this.style.display=\"none\"'>" if user['photo_profil'] else ""

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
            .form-group {{ margin-bottom: 12px; }}
            label {{ display: block; margin-bottom: 4px; font-weight: 600; font-size: 0.9rem; }}
            input, select, textarea {{ width: 100%; padding: 8px; border: 1px solid #ccc; border-radius: 5px; box-sizing: border-box; }}
            button {{ background-color: var(--accent); color: white; border: none; padding: 10px 15px; border-radius: 5px; cursor: pointer; font-size: 1rem; width: 100%; font-weight: bold; }}
            button:hover {{ background-color: #219653; }}
            .btn-danger {{ background-color: var(--danger); color: white; padding: 8px 15px; text-decoration: none; border-radius: 5px; font-weight: bold; display: inline-block; }}
            ul {{ padding-left: 20px; }}
            li {{ margin-bottom: 8px; font-size: 0.9rem; }}
            table th, table td {{ border-bottom: 1px solid #eee; padding: 8px; text-align: left; }}
        </style>
    </head>
    <body>
        <div class="container">
            <h1>Association Tinka - Tableau de Bord</h1>
            
            <div class="card" style="background: #eaf2f8; overflow:hidden;">
                {user_photo}
                <h2>Mon Profil</h2>
                <p><b>Nom & Prénom :</b> {user['prenom']} {user['nom']}</p>
                <p><b>Secteur :</b> {user['secteur']} | <b>Téléphone :</b> {user['telephone']} | <b>Email :</b> {user['email']}</p>
                <p><b>Rôle :</b> <span style="text-transform: uppercase; color: #2980b9; font-weight: bold;">{user['role']}</span></p>
                
                <hr style="border:0; border-top:1px solid #d0e1f9; margin:10px 0;">
                <form action="/modifier-photo" method="POST" style="display:flex; gap:10px; align-items:flex-end;">
                    <input type="hidden" name="user_id" value="{user['id']}">
                    <div style="flex:1;" class="form-group">
                        <label style="font-size:0.8rem;">Modifier/Ajouter ma photo (URL) :</label>
                        <input type="url" name="photo_profil" value="{user['photo_profil']}" placeholder="https://..." required style="padding:5px; font-size:0.85rem;">
                    </div>
                    <div>
                        <button type="submit" style="background:#2980b9; padding:6px 12px; font-size:0.85rem; width:auto;">Mettre à jour</button>
                    </div>
                </form>
                <br>
                <a href="/" class="btn-danger" style="font-size:0.85rem; padding:6px 12px;">Se déconnecter</a>
            </div>

            {finance_sections_html}

            {member_sections_html}

            <div class="card">
                <h2>Projets de l'Association & Bureau</h2>
                <div>{projets_html or '<p>Aucun projet enregistré.</p>'}</div>
            </div>
        </div>
    </body>
    </html>
    """

if __name__ == "__main__":
    uvicorn.run("app_asso:app", host="127.0.0.1", port=8000, reload=True)
