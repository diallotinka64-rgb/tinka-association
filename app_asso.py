from fastapi import FastAPI, HTTPException, Depends, Form, status, Query, UploadFile, File
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, StreamingResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
import io
import os
import datetime
from typing import Optional
from reportlab.lib.pagesizes import letter
from reportlab.pdfgen import canvas
from supabase import create_client, Client

app = FastAPI(title="API Gestion Association Tinka", version="9.3")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

SUPABASE_URL = os.getenv("SUPABASE_URL", "")
SUPABASE_KEY = os.getenv("SUPABASE_KEY", "")
supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)

UPLOAD_DIR = "static/uploads"
os.makedirs(UPLOAD_DIR, exist_ok=True)
app.mount("/static", StaticFiles(directory="static"), name="static")

@app.post("/login-form")
def login_form(email: str = Form(...), mot_de_passe: str = Form(...)):
    try:
        res = supabase.table("adherents").select("*").eq("email", email).eq("mot_de_passe", mot_de_passe).execute()
        users = res.data
        if not users:
            return HTMLResponse(content="<script>alert('Email ou mot de passe incorrect.'); window.location.href='/';</script>", status_code=401)
        user = users[0]
        if user.get('statut') != 'actif':
            return HTMLResponse(content="<script>alert('Votre compte est en attente de validation.'); window.location.href='/';</script>", status_code=403)
        return RedirectResponse(url=f"/dashboard?id={user['id']}", status_code=status.HTTP_303_SEE_OTHER)
    except Exception as e:
        return HTMLResponse(content=f"<h3>Erreur de connexion Supabase :</h3><p>{str(e)}</p><a href='/'>Retour</a>", status_code=500)

@app.post("/adherents-form")
async def creer_adherent_form(
    nom: str = Form(...), prenom: str = Form(...), email: str = Form(...),
    telephone: str = Form(...), adresse: str = Form(...), secteur: str = Form(...),
    mot_de_passe: str = Form(...), file_photo: UploadFile = File(None)
):
    photo_path = ""
    if file_photo and file_photo.filename:
        file_location = os.path.join(UPLOAD_DIR, file_photo.filename)
        with open(file_location, "wb+") as file_object:
            file_object.write(await file_photo.read())
        photo_path = f"/static/uploads/{file_photo.filename}"

    try:
        supabase.table("adherents").insert({
            "nom": nom, "prenom": prenom, "email": email, "telephone": telephone,
            "adresse": adresse, "secteur": secteur, "photo_profil": photo_path, "mot_de_passe": mot_de_passe
        }).execute()
        return HTMLResponse(content="<script>alert('Compte créé avec succès ! En attente de validation.'); window.location.href='/';</script>")
    except Exception as e:
        return HTMLResponse(content=f"<script>alert('Erreur : {str(e)}'); window.location.href='/';</script>")

@app.post("/modifier-photo")
async def modifier_photo(user_id: int = Form(...), file_photo: UploadFile = File(...)):
    photo_path = ""
    if file_photo and file_photo.filename:
        file_location = os.path.join(UPLOAD_DIR, file_photo.filename)
        with open(file_location, "wb+") as file_object:
            file_object.write(await file_photo.read())
        photo_path = f"/static/uploads/{file_photo.filename}"

    supabase.table("adherents").update({"photo_profil": photo_path}).eq("id", user_id).execute()
    return RedirectResponse(url=f"/dashboard?id={user_id}", status_code=status.HTTP_303_SEE_OTHER)

@app.post("/admin/valider-adherent")
def valider_adherent(user_id: int = Form(...), adherent_id: int = Form(...)):
    supabase.table("adherents").update({"statut": "actif"}).eq("id", adherent_id).execute()
    return RedirectResponse(url=f"/dashboard?id={user_id}", status_code=status.HTTP_303_SEE_OTHER)

@app.post("/admin/changer-role")
def changer_role(user_id: int = Form(...), adherent_id: int = Form(...), nouveau_role: str = Form(...)):
    supabase.table("adherents").update({"role": nouveau_role}).eq("id", adherent_id).execute()
    return RedirectResponse(url=f"/dashboard?id={user_id}", status_code=status.HTTP_303_SEE_OTHER)

@app.post("/admin/reset-password")
def reset_password(user_id: int = Form(...), adherent_id: int = Form(...), nouveau_mdp: str = Form(...)):
    supabase.table("adherents").update({"mot_de_passe": nouveau_mdp}).eq("id", adherent_id).execute()
    return HTMLResponse(content=f"<script>alert('Mot de passe réinitialisé avec succès !'); window.location.href='/dashboard?id={user_id}';</script>")

@app.post("/cotisations-form")
def ajouter_cotisation(user_id: int = Form(...), adherent_id: int = Form(...), montant: float = Form(...), periode: str = Form(...), mode_paiement: str = Form(...)):
    supabase.table("cotisations").insert({
        "adherent_id": adherent_id, "montant": montant, "periode": periode, "mode_paiement": mode_paiement
    }).execute()
    return RedirectResponse(url=f"/dashboard?id={user_id}", status_code=status.HTTP_303_SEE_OTHER)

@app.post("/aides-form")
def demander_aide(user_id: int = Form(...), motif: str = Form(...), montant_demande: float = Form(...)):
    supabase.table("aides").insert({
        "adherent_id": user_id, "motif": motif, "montant_demande": montant_demande
    }).execute()
    return RedirectResponse(url=f"/dashboard?id={user_id}", status_code=status.HTTP_303_SEE_OTHER)

@app.post("/decaissements-form")
def ajouter_decaissement(user_id: int = Form(...), motif: str = Form(...), montant: float = Form(...), beneficiaire: str = Form(...)):
    supabase.table("decaissements").insert({
        "motif": motif, "montant": montant, "beneficiaire": beneficiaire
    }).execute()
    return RedirectResponse(url=f"/dashboard?id={user_id}", status_code=status.HTTP_303_SEE_OTHER)

@app.post("/projets-form")
async def ajouter_projet(
    user_id: int = Form(...), titre: str = Form(...), description: str = Form(...), 
    objectifs: str = Form(...), cout: float = Form(...), file_projet: UploadFile = File(None), 
    chronologie: str = Form(...), statut: str = Form(...)
):
    photo_path = ""
    if file_projet and file_projet.filename:
        file_location = os.path.join(UPLOAD_DIR, file_projet.filename)
        with open(file_location, "wb+") as file_object:
            file_object.write(await file_projet.read())
        photo_path = f"/static/uploads/{file_projet.filename}"

    supabase.table("projets").insert({
        "titre": titre, "description": description, "objectifs": objectifs,
        "cout": cout, "photo_projet": photo_path, "chronologie": chronologie, "statut": statut
    }).execute()
    return RedirectResponse(url=f"/dashboard?id={user_id}", status_code=status.HTTP_303_SEE_OTHER)

@app.get("/cotisations/export-pdf")
def export_cotisations_pdf(periode: Optional[str] = Query(None)):
    query = supabase.table("cotisations").select("*, adherents(nom, prenom, secteur)")
    if periode:
        query = query.eq("periode", periode)
        titre_rapport = f"Association Tinka - Rapport des Cotisations ({periode})"
    else:
        titre_rapport = "Association Tinka - Rapport Global des Cotisations"
    
    res = query.execute()
    cotis = res.data

    buffer = io.BytesIO()
    p = canvas.Canvas(buffer, pagesize=letter)
    width, height = letter

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
        adh = c.get('adherents', {}) or {}
        nom = adh.get('nom', '')
        prenom = adh.get('prenom', '')
        secteur = adh.get('secteur', '')
        p.drawString(50, y, f"- {prenom} {nom} ({secteur}) | Période: {c['periode']} | Montant: {c['montant']} CFA ({c['mode_paiement']})")
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
                <form action="/login-form" method="POST">
                    <div class="form-group"><label>Email :</label><input type="email" name="email" required></div>
                    <div class="form-group"><label>Mot de passe :</label><input type="password" name="mot_de_passe" required></div>
                    <button type="submit" style="background-color: var(--info);">Se connecter</button>
                </form>
            </div>
            <div class="card">
                <h2>Inscription d'un Nouvel Adhérent</h2>
                <form action="/adherents-form" method="POST" enctype="multipart/form-data">
                    <div class="form-group"><label>Nom :</label><input type="text" name="nom" required></div>
                    <div class="form-group"><label>Prénom :</label><input type="text" name="prenom" required></div>
                    <div class="form-group"><label>Email :</label><input type="email" name="email" required></div>
                    <div class="form-group"><label>Téléphone :</label><input type="text" name="telephone" required></div>
                    <div class="form-group"><label>Adresse :</label><input type="text" name="adresse" required></div>
                    <div class="form-group"><label>Secteur :</label><input type="text" name="secteur" required></div>
                    <div class="form-group"><label>Photo de profil (PC ou Téléphone) :</label><input type="file" name="file_photo" accept="image/*"></div>
                    <div class="form-group"><label>Mot de passe :</label><input type="password" name="mot_de_passe" required></div>
                    <button type="submit">S'inscrire</button>
                </form>
            </div>
        </div>
    </body>
    </html>
    """

@app.get("/dashboard", response_class=HTMLResponse)
def afficher_dashboard(id: int, filtre_periode: Optional[str] = Query(None)):
    try:
        user_res = supabase.table("adherents").select("*").eq("id", id).execute()
        if not user_res.data:
            return RedirectResponse(url="/", status_code=303)
        user = user_res.data[0]

        is_admin = user['role'] == 'admin'
        is_tresorier = user['role'] in ['admin', 'tresorier']

        annee_courante = datetime.datetime.now().year
        mois_12 = [f"{annee_courante}-{m:02d}" for m in range(1, 13)]

        all_actifs = supabase.table("adherents").select("*").eq("statut", "actif").execute().data
        all_adherents = supabase.table("adherents").select("*").execute().data
        
        cotis_res = supabase.table("cotisations").select("*, adherents(nom, prenom, secteur, telephone)").execute()
        all_cotisations = cotis_res.data

        cotis_affichees = [c for c in all_cotisations if c['periode'] == filtre_periode] if filtre_periode else all_cotisations

        aides_res = supabase.table("aides").select("*, adherents(nom, prenom, secteur)").execute()
        all_aides = aides_res.data

        dec_res = supabase.table("decaissements").select("*").execute()
        all_decaissements = dec_res.data

        proj_res = supabase.table("projets").select("*").execute()
        all_projets = proj_res.data

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

            cotis_table_html = ""
            for c in cotis_affichees:
                adh = c.get('adherents', {}) or {}
                cotis_table_html += f"<tr><td>{adh.get('prenom','')} {adh.get('nom','')}</td><td>{adh.get('secteur','')}</td><td><b>{c['montant']} CFA</b></td><td>{c['periode']}</td><td>{c['mode_paiement']}</td></tr>"

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
                    </form>
                    <form action="/admin/reset-password" method="POST" style="display:inline-block; margin-left:5px; margin-top:5px;">
                        <input type="hidden" name="user_id" value="{user['id']}">
                        <input type="hidden" name="adherent_id" value="{a['id']}">
                        <input type="text" name="nouveau_mdp" placeholder="Nouveau mdp" required style="width:100px; padding:2px; display:inline-block; font-size:0.75rem;">
                        <button type="submit" style="background:#d35400; padding:2px 5px; font-size:0.7rem; width:auto;">Réinitialiser MDP</button>
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
                <h2>Gestion des Adhérents & Réinitialisation des Mots de Passe</h2>
                <ul>{adherents_gestion_html}</ul>
            </div>

            <div class="card">
                <h2>Enregistrer une Cotisation</h2>
                <form action="/cotisations-form" method="POST">
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
                <form action="/projets-form" method="POST" enctype="multipart/form-data">
                    <input type="hidden" name="user_id" value="{user['id']}">
                    <div class="form-group"><label>Titre :</label><input type="text" name="titre" required></div>
                    <div class="form-group"><label>Description :</label><textarea name="description" rows="2"></textarea></div>
                    <div class="form-group"><label>Objectifs :</label><textarea name="objectifs" rows="2"></textarea></div>
                    <div class="form-group"><label>Coût Prévu (CFA) :</label><input type="number" name="cout" required></div>
                    <div class="form-group"><label>Photo du projet (PC/Téléphone) :</label><input type="file" name="file_projet" accept="image/*"></div>
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
                <form action="/aides-form" method="POST">
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
                    <form action="/modifier-photo" method="POST" enctype="multipart/form-data" style="display:flex; gap:10px; align-items:flex-end;">
                        <input type="hidden" name="user_id" value="{user['id']}">
                        <div style="flex:1;" class="form-group">
                            <label style="font-size:0.8rem;">Mettre à jour ma photo (depuis PC ou Téléphone) :</label>
                            <input type="file" name="file_photo" accept="image/*" required style="padding:3px; font-size:0.85rem;">
                        </div>
                        <div>
                            <button type="submit" style="background:#2980b9; padding:6px 12px; font-size:0.85rem; width:auto;">Envoyer</button>
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
    except Exception as e:
        return HTMLResponse(content=f"<h3>Erreur du Tableau de bord :</h3><p>{str(e)}</p><a href='/'>Retour</a>", status_code=500)

if __name__ == "__main__":
    uvicorn.run("app_asso:app", host="127.0.0.1", port=8000, reload=True)
