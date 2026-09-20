from fastapi import FastAPI, HTTPException, Depends, Form, status, Query, UploadFile, File
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, StreamingResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
import io
import os
import datetime
from typing import Optional
import bcrypt
import qrcode
import base64
import urllib.parse
from reportlab.lib.pagesizes import letter
from reportlab.pdfgen import canvas
from supabase import create_client, Client

app = FastAPI(title="API Gestion Tinka ka Mein Haaldi fotti", version="28.0")

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

def formater_montant(montant: float) -> str:
    try:
        return f"{int(montant):,}".replace(",", " ")
    except Exception:
        return str(montant)

def hacher_mdp(mdp: str) -> str:
    return bcrypt.hashpw(mdp.encode('utf-8'), bcrypt.gensalt()).decode('utf-8')

def verifier_mdp(mdp: str, hashed: str) -> bool:
    try:
        return bcrypt.checkpw(mdp.encode('utf-8'), hashed.encode('utf-8'))
    except Exception:
        return mdp == hashed

def generer_qrcode_base64(url: str) -> str:
    qr = qrcode.QRCode(box_size=4, border=2)
    qr.add_data(url)
    qr.make(fit=True)
    img = qr.make_image(fill_color="black", back_color="white")
    buffered = io.BytesIO()
    img.save(buffered, format="PNG")
    return base64.b64encode(buffered.getvalue()).decode("utf-8")

@app.get("/login-form", include_in_schema=False)
@app.get("/login-form/", include_in_schema=False)
def login_get_redirect():
    return RedirectResponse(url="/", status_code=303)

@app.post("/login-form/")
@app.post("/login-form")
def login_form(telephone: str = Form(...), mot_de_passe: str = Form(...)):
    try:
        res = supabase.table("adherents").select("*").eq("telephone", telephone).execute()
        users = res.data
        if not users:
            return HTMLResponse(content="<script>alert('Numéro de téléphone ou mot de passe incorrect.'); window.location.href='/';</script>", status_code=401)
        
        user = users[0]
        if not verifier_mdp(mot_de_passe, user['mot_de_passe']):
            return HTMLResponse(content="<script>alert('Numéro de téléphone ou mot de passe incorrect.'); window.location.href='/';</script>", status_code=401)

        if user.get('statut') != 'actif':
            return HTMLResponse(content="<script>alert('Votre compte est en attente de validation par l\\'administrateur.'); window.location.href='/';</script>", status_code=403)
        return RedirectResponse(url=f"/dashboard?id={user['id']}", status_code=status.HTTP_303_SEE_OTHER)
    except Exception as e:
        return HTMLResponse(content=f"<h3>Erreur de connexion Supabase :</h3><p>{str(e)}</p><a href='/'>Retour</a>", status_code=500)

@app.post("/adherents-form/")
@app.post("/adherents-form")
async def creer_adherent_form(
    nom: str = Form(...), prenom: str = Form(...), telephone: str = Form(...),
    adresse: str = Form(...), secteur: str = Form(...),
    mot_de_passe: str = Form(...), file_photo: UploadFile = File(None)
):
    photo_path = ""
    if file_photo and file_photo.filename:
        file_location = os.path.join(UPLOAD_DIR, file_photo.filename)
        with open(file_location, "wb+") as file_object:
            file_object.write(await file_photo.read())
        photo_path = f"/static/uploads/{file_photo.filename}"

    mdp_securise = hacher_mdp(mot_de_passe)

    try:
        supabase.table("adherents").insert({
            "nom": nom, "prenom": prenom, "email": f"{telephone}@tinka.local", "telephone": telephone,
            "adresse": adresse, "secteur": secteur, "photo_profil": photo_path, "mot_de_passe": mdp_securise
        }).execute()
        return HTMLResponse(content="<script>alert('Compte créé avec succès ! En attente de validation.'); window.location.href='/';</script>")
    except Exception as e:
        return HTMLResponse(content=f"<script>alert('Erreur : Ce numéro de téléphone existe déjà ou un problème est survenu.'); window.location.href='/';</script>")

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

@app.post("/admin/modifier-adherent")
def modifier_adherent(
    user_id: int = Form(...), adherent_id: int = Form(...),
    nom: str = Form(...), prenom: str = Form(...),
    telephone: str = Form(...), secteur: str = Form(...)
):
    try:
        supabase.table("adherents").update({
            "nom": nom, "prenom": prenom, "telephone": telephone, "secteur": secteur
        }).eq("id", adherent_id).execute()
        return HTMLResponse(content=f"<script>alert('Informations mises à jour avec succès !'); window.location.href='/dashboard?id={user_id}';</script>")
    except Exception as e:
        return HTMLResponse(content=f"<script>alert('Erreur (Ce numéro appartient peut-être déjà à un autre membre) : {str(e)}'); window.location.href='/dashboard?id={user_id}';</script>")

@app.post("/admin/reset-password")
def reset_password(user_id: int = Form(...), adherent_id: int = Form(...), nouveau_mdp: str = Form(...)):
    mdp_securise = hacher_mdp(nouveau_mdp)
    supabase.table("adherents").update({"mot_de_passe": mdp_securise}).eq("id", adherent_id).execute()
    return HTMLResponse(content=f"<script>alert('Mot de passe réinitialisé et sécurisé avec succès !'); window.location.href='/dashboard?id={user_id}';</script>")

@app.post("/admin/maj-solde-initial")
def maj_solde_initial(user_id: int = Form(...), solde_initial: float = Form(...)):
    try:
        supabase.table("parametres").update({"solde_initial": solde_initial}).eq("id", 1).execute()
        return HTMLResponse(content=f"<script>alert('Solde initial de caisse mis à jour avec succès !'); window.location.href='/dashboard?id={user_id}';</script>")
    except Exception as e:
        return HTMLResponse(content=f"<script>alert('Erreur : {str(e)}'); window.location.href='/dashboard?id={user_id}';</script>")

@app.post("/cotisations-form/")
@app.post("/cotisations-form")
def ajouter_cotisation(user_id: int = Form(...), adherent_id: int = Form(...), montant: float = Form(...), periode: str = Form(...), mode_paiement: str = Form(...)):
    supabase.table("cotisations").insert({
        "adherent_id": adherent_id, "montant": montant, "periode": periode, "mode_paiement": mode_paiement
    }).execute()
    return RedirectResponse(url=f"/dashboard?id={user_id}", status_code=status.HTTP_303_SEE_OTHER)

@app.post("/aides-form/")
@app.post("/aides-form")
def demander_aide(user_id: int = Form(...), motif: str = Form(...), montant_demande: float = Form(...)):
    supabase.table("aides").insert({
        "adherent_id": user_id, "motif": motif, "montant_demande": montant_demande
    }).execute()
    return RedirectResponse(url=f"/dashboard?id={user_id}", status_code=status.HTTP_303_SEE_OTHER)

@app.post("/decaissements-form/")
@app.post("/decaissements-form")
def ajouter_decaissement(user_id: int = Form(...), motif: str = Form(...), montant: float = Form(...), beneficiaire: str = Form(...), categorie: str = Form(...)):
    supabase.table("decaissements").insert({
        "motif": motif, "montant": montant, "beneficiaire": beneficiaire, "categorie": categorie
    }).execute()
    return RedirectResponse(url=f"/dashboard?id={user_id}", status_code=status.HTTP_303_SEE_OTHER)

@app.post("/projets-form/")
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

@app.post("/evenements-form/")
@app.post("/evenements-form")
def ajouter_evenement(
    user_id: int = Form(...), titre: str = Form(...), description: str = Form(...),
    date_evenement: str = Form(...), lieu: str = Form(...), type_evenement: str = Form(...), statut: str = Form(...)
):
    supabase.table("evenements").insert({
        "titre": titre, "description": description, "date_evenement": date_evenement,
        "lieu": lieu, "type_evenement": type_evenement, "statut": statut
    }).execute()
    return RedirectResponse(url=f"/dashboard?id={user_id}", status_code=status.HTTP_303_SEE_OTHER)

@app.post("/presences-form/")
@app.post("/presences-form")
def enregistrer_presence(user_id: int = Form(...), adherent_id: int = Form(...), evenement_titre: str = Form(...), statut_presence: str = Form(...), date_reunion: str = Form(...)):
    try:
        supabase.table("presences_association").insert({
            "adherent_id": adherent_id, "evenement_titre": evenement_titre, "statut_presence": statut_presence, "date_reunion": date_reunion
        }).execute()
    except Exception:
        pass
    return RedirectResponse(url=f"/dashboard?id={user_id}", status_code=status.HTTP_303_SEE_OTHER)

@app.get("/cotisations/export-pdf")
def export_cotisations_pdf(periode: Optional[str] = Query(None)):
    query = supabase.table("cotisations").select("*, adherents(nom, prenom, secteur)")
    if periode:
        query = query.eq("periode", periode)
        titre_rapport = f"Tinka ka Mein Haaldi fotti - Rapport des Cotisations ({periode})"
    else:
        titre_rapport = "Tinka ka Mein Haaldi fotti - Rapport Global des Cotisations"
    
    res = query.execute()
    cotis = res.data

    buffer = io.BytesIO()
    p = canvas.Canvas(buffer, pagesize=letter)
    width, height = letter

    p.setFont("Helvetica-Bold", 14)
    p.setFillColorRGB(0.15, 0.25, 0.35)
    p.drawString(50, height - 40, "TINKA KA MEIN HAALDI FOTTI")
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
        montant_fmt = formater_montant(c['montant'])
        p.drawString(50, y, f"- {prenom} {nom} ({secteur}) | Période: {c['periode']} | Montant: {montant_fmt} CFA ({c['mode_paiement']})")
        total += c['montant']
        y -= 20
        if y < 50:
            p.showPage()
            y = height - 50

    total_fmt = formater_montant(total)
    p.setFont("Helvetica-Bold", 11)
    p.drawString(50, y - 10, f"Total Général : {total_fmt} CFA")
    p.save()
    buffer.seek(0)
    return StreamingResponse(buffer, media_type="application/pdf", headers={"Content-Disposition": f"attachment; filename=rapport_cotisations_{periode or 'global'}.pdf"})

@app.get("/cotisation/recu-pdf/{cotisation_id}")
def telecharger_recu_pdf(cotisation_id: int):
    res = supabase.table("cotisations").select("*, adherents(nom, prenom, secteur, telephone)").eq("id", cotisation_id).execute()
    if not res.data:
        return HTMLResponse("Reçu introuvable", status_code=404)
    
    c = res.data[0]
    adh = c.get('adherents', {}) or {}
    montant_fmt = formater_montant(c['montant'])

    buffer = io.BytesIO()
    p = canvas.Canvas(buffer, pagesize=letter)
    width, height = letter

    p.setFont("Helvetica-Bold", 16)
    p.setFillColorRGB(0.15, 0.25, 0.35)
    p.drawString(50, height - 50, "TINKA KA MEIN HAALDI FOTTI")
    p.setFont("Helvetica", 10)
    p.setFillColorRGB(0.4, 0.4, 0.4)
    p.drawString(50, height - 68, "Reçu Officiel de Paiement de Cotisation")
    p.setStrokeColorRGB(0.8, 0.8, 0.8)
    p.line(50, height - 80, width - 50, height - 80)

    p.setFont("Helvetica-Bold", 12)
    p.setFillColorRGB(0, 0, 0)
    p.drawString(50, height - 120, f"Reçu N° : TK-{c['id']:04d}")
    p.setFont("Helvetica", 11)
    p.drawString(50, height - 145, f"Date de Paiement : {c['date_paiement'][:10]}")
    p.drawString(50, height - 170, f"Membre : {adh.get('prenom','')} {adh.get('nom','')}")
    p.drawString(50, height - 195, f"Secteur : {adh.get('secteur','')}")
    p.drawString(50, height - 220, f"Téléphone : {adh.get('telephone','')}")

    p.rect(50, height - 310, width - 100, 60, stroke=1, fill=0)
    p.setFont("Helvetica-Bold", 14)
    p.setFillColorRGB(0.15, 0.65, 0.35)
    p.drawString(70, height - 265, f"Montant Versé : {montant_fmt} CFA")
    p.setFont("Helvetica", 11)
    p.setFillColorRGB(0, 0, 0)
    p.drawString(70, height - 285, f"Période couverte : {c['periode']} | Mode de règlement : {c['mode_paiement']}")

    p.setFont("Helvetica-Oblique", 9)
    p.setFillColorRGB(0.5, 0.5, 0.5)
    p.drawString(50, 100, "Ce reçu est certifié conforme par le Bureau Exécutif de Tinka ka Mein Haaldi fotti.")

    p.save()
    buffer.seek(0)
    return StreamingResponse(buffer, media_type="application/pdf", headers={"Content-Disposition": f"attachment; filename=recu_cotisation_{c['id']}.pdf"})

@app.get("/", response_class=HTMLResponse)
def afficher_portail():
    url_site = "https://tinka-association.onrender.com"
    qr_b64 = generer_qrcode_base64(url_site)

    return f"""
    <!DOCTYPE html>
    <html lang="fr">
    <head>
        <meta charset="UTF-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <title>Tinka ka Mein Haaldi fotti</title>
        <script src="https://cdn.tailwindcss.com"></script>
    </head>
    <body class="bg-slate-50 text-slate-800 font-sans antialiased min-h-screen py-8 px-4">
        <div class="max-w-md mx-auto bg-white rounded-2xl shadow-xl p-6 sm:p-8 border border-slate-100">
            <div class="text-center mb-6">
                <span class="inline-block bg-emerald-100 text-emerald-800 text-xs font-bold px-3 py-1 rounded-full uppercase tracking-wider mb-2">Portail Officiel</span>
                <h1 class="text-2xl font-black text-slate-900 tracking-tight">Tinka ka Mein Haaldi fotti</h1>
                <p class="text-sm text-slate-500 mt-1">Gestion administrative, financière & Daara</p>
            </div>
            
            <div class="flex justify-center mb-6">
                <div class="bg-white p-3 rounded-xl border-2 border-dashed border-slate-200 shadow-sm text-center">
                    <img src="data:image/png;base64,{qr_b64}" alt="QR Code" class="w-32 h-32 mx-auto mb-2 rounded">
                    <span class="text-xs font-semibold text-slate-600">Scannez pour vous connecter</span>
                </div>
            </div>

            <div class="space-y-6">
                <div class="bg-slate-50 p-5 rounded-xl border border-slate-200">
                    <h2 class="text-base font-bold text-slate-800 mb-4 flex items-center gap-2">🔐 Connexion</h2>
                    <form action="/login-form" method="POST" class="space-y-4">
                        <div>
                            <label class="block text-xs font-bold uppercase tracking-wider text-slate-600 mb-1">Numéro de téléphone</label>
                            <input type="text" name="telephone" placeholder="ex: 221771234567" required class="w-full px-3 py-2.5 text-sm bg-white border border-slate-300 rounded-lg focus:ring-2 focus:ring-emerald-500 focus:outline-none">
                        </div>
                        <div>
                            <label class="block text-xs font-bold uppercase tracking-wider text-slate-600 mb-1">Mot de passe</label>
                            <input type="password" name="mot_de_passe" required class="w-full px-3 py-2.5 text-sm bg-white border border-slate-300 rounded-lg focus:ring-2 focus:ring-emerald-500 focus:outline-none">
                        </div>
                        <button type="submit" class="w-full bg-blue-600 hover:bg-blue-700 text-white font-bold py-2.5 px-4 rounded-lg shadow transition duration-200 text-sm">Se connecter</button>
                    </form>
                </div>

                <div class="bg-slate-50 p-5 rounded-xl border border-slate-200">
                    <h2 class="text-base font-bold text-emerald-700 mb-4 flex items-center gap-2">📝 Nouvel Adhérent</h2>
                    <form action="/adherents-form" method="POST" enctype="multipart/form-data" class="space-y-3">
                        <div class="grid grid-cols-2 gap-2">
                            <div>
                                <label class="block text-xs font-bold text-slate-600 mb-1">Nom</label>
                                <input type="text" name="nom" required class="w-full px-2.5 py-2 text-sm bg-white border border-slate-300 rounded-lg">
                            </div>
                            <div>
                                <label class="block text-xs font-bold text-slate-600 mb-1">Prénom</label>
                                <input type="text" name="prenom" required class="w-full px-2.5 py-2 text-sm bg-white border border-slate-300 rounded-lg">
                            </div>
                        </div>
                        <div>
                            <label class="block text-xs font-bold text-slate-600 mb-1">Téléphone (Identifiant unique)</label>
                            <input type="text" name="telephone" required class="w-full px-2.5 py-2 text-sm bg-white border border-slate-300 rounded-lg">
                        </div>
                        <div>
                            <label class="block text-xs font-bold text-slate-600 mb-1">Adresse</label>
                            <input type="text" name="adresse" required class="w-full px-2.5 py-2 text-sm bg-white border border-slate-300 rounded-lg">
                        </div>
                        <div>
                            <label class="block text-xs font-bold text-slate-600 mb-1">Secteur</label>
                            <input type="text" name="secteur" required class="w-full px-2.5 py-2 text-sm bg-white border border-slate-300 rounded-lg">
                        </div>
                        <div>
                            <label class="block text-xs font-bold text-slate-600 mb-1">Photo de profil</label>
                            <input type="file" name="file_photo" accept="image/*" class="w-full text-xs text-slate-500 file:mr-2 file:py-2 file:px-3 file:rounded-lg file:border-0 file:text-xs file:font-semibold file:bg-emerald-50 file:text-emerald-700 hover:file:bg-emerald-100">
                        </div>
                        <div>
                            <label class="block text-xs font-bold text-slate-600 mb-1">Mot de passe</label>
                            <input type="password" name="mot_de_passe" required class="w-full px-2.5 py-2 text-sm bg-white border border-slate-300 rounded-lg">
                        </div>
                        <button type="submit" class="w-full bg-emerald-600 hover:bg-emerald-700 text-white font-bold py-2.5 px-4 rounded-lg shadow transition duration-200 text-sm mt-2">S'inscrire</button>
                    </form>
                </div>
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
        mois_12 = [f"{annee_courante}-{m:02d}" for m in range(9, 13)] + [f"{annee_courante+1}-{m:02d}" for m in range(1, 9)]

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

        evt_res = supabase.table("evenements").select("*").execute()
        all_evenements = evt_res.data

        # Récupération du solde initial de la caisse
        param_res = supabase.table("parametres").select("solde_initial").eq("id", 1).execute()
        solde_initial = param_res.data[0]['solde_initial'] if param_res.data else 0.0

        # Calcul financier : On exclut les cotisations de type "regularisation" pour le calcul de l'argent physique en caisse
        cotisations_caisse = sum([c['montant'] for c in all_cotisations if c.get('mode_paiement') != 'regularisation'])
        total_cotis_global = sum([c['montant'] for c in all_cotisations])
        total_aides_approuvees = sum([ai['montant_demande'] for ai in all_aides if ai['statut_validation'] == 'approuve'])
        total_dec = sum([d['montant'] for d in all_decaissements])
        
        # Solde réel en caisse = Solde initial + Cotisations standard - Aides - Dépenses
        solde = solde_initial + cotisations_caisse - (total_aides_approuvees + total_dec)

        url_profil_personnel = f"https://tinka-association.onrender.com/dashboard?id={user['id']}"
        qr_perso_b64 = generer_qrcode_base64(url_profil_personnel)

        finance_sections_html = ""
        if is_tresorier:
            options_adherents = "".join([f"<option value='{a['id']}' data-text='{a['prenom'].lower()} {a['nom'].lower()} {a['secteur'].lower()} {a['telephone']}'>{a['prenom']} {a['nom']} — Secteur: {a['secteur']} (Tél: {a['telephone']})</option>" for a in all_actifs if a['role'] != 'admin'])
            
            suivi_retards_html = ""
            for a in all_actifs:
                cotis_membre = [c['periode'] for c in all_cotisations if c['adherent_id'] == a['id']]
                mois_manquants = [m for m in mois_12 if m not in cotis_membre]
                
                if not mois_manquants:
                    statut_ajour = "<span class='text-emerald-600 font-bold'>À jour</span>"
                else:
                    nb_retard = len(mois_manquants)
                    statut_ajour = f"<span class='text-red-600 font-bold'>Retard ({nb_retard} mois)</span>"

                suivi_retards_html += f"<li class='py-1.5 border-b border-slate-100 flex justify-between items-center text-sm'><span><b>{a['prenom']} {a['nom']}</b> <span class='text-xs text-slate-400'>({a['secteur']})</span></span> {statut_ajour}</li>"

            cotis_table_html = ""
            for c in cotis_affichees:
                adh = c.get('adherents', {}) or {}
                btn_recu = f"<a href='/cotisation/recu-pdf/{c['id']}' target='_blank' class='bg-blue-600 hover:bg-blue-700 text-white px-2.5 py-1 rounded text-xs font-semibold'>Reçu PDF</a>"
                montant_c_fmt = formater_montant(c['montant'])
                search_cotis = f"{adh.get('prenom','')} {adh.get('nom','')} {adh.get('secteur','')} {c['periode']} {c['mode_paiement']}".lower()
                cotis_table_html += f"<tr class='cotis-row hover:bg-slate-50' data-search='{search_cotis}'><td class='p-2.5 font-medium'>{adh.get('prenom','')} {adh.get('nom','')}</td><td class='p-2.5 text-slate-600'>{adh.get('secteur','')}</td><td class='p-2.5 font-bold text-emerald-600'>{montant_c_fmt} CFA</td><td class='p-2.5 text-slate-600'>{c['periode']}</td><td class='p-2.5 text-slate-600'>{c['mode_paiement']}</td><td class='p-2.5'>{btn_recu}</td></tr>"

            options_filtre_mois = "".join([f"<option value='{m}' {'selected' if filtre_periode==m else ''}>{m}</option>" for m in mois_12])

            solde_initial_fmt = formater_montant(solde_initial)
            solde_fmt = formater_montant(solde)

            finance_sections_html = f"""
            <div class="bg-white p-6 rounded-2xl shadow-sm border border-slate-200 mb-6">
                <h2 class="text-lg font-bold text-emerald-700 mb-4 border-b pb-2">💼 Gestion du Solde Initial & Trésorerie</h2>
                
                <!-- Formulaire de configuration du solde initial réel compté -->
                <form action="/admin/maj-solde-initial" method="POST" class="bg-emerald-50 p-4 rounded-xl border border-emerald-100 mb-6 flex flex-col sm:flex-row gap-3 items-end">
                    <input type="hidden" name="user_id" value="{user['id']}">
                    <div class="w-full sm:flex-1">
                        <label class="block text-xs font-bold text-emerald-800 mb-1">Montant total compté en caisse (Solde Initial Réel)</label>
                        <input type="number" name="solde_initial" value="{solde_initial}" required class="w-full p-2.5 text-sm bg-white border border-emerald-300 rounded-lg">
                    </div>
                    <button type="submit" class="w-full sm:w-auto bg-emerald-600 hover:bg-emerald-700 text-white font-bold py-2.5 px-5 rounded-lg text-sm shadow">Mettre à jour le solde de départ</button>
                </form>

                <div class="grid grid-cols-1 sm:grid-cols-3 gap-4 mb-4 text-center">
                    <div class="bg-slate-50 p-3 rounded-xl border border-slate-200"><span class="block text-xs text-slate-500 font-bold uppercase">Solde Initial</span><span class="text-lg font-black text-slate-800">{solde_initial_fmt} CFA</span></div>
                    <div class="bg-emerald-50 p-3 rounded-xl border border-emerald-100"><span class="block text-xs text-emerald-600 font-bold uppercase">Cotisations Standard</span><span class="text-lg font-black text-emerald-800">{formater_montant(cotisations_caisse)} CFA</span></div>
                    <div class="bg-red-50 p-3 rounded-xl border border-red-100"><span class="block text-xs text-red-600 font-bold uppercase">Dépenses & Aides</span><span class="text-lg font-black text-red-800">{formater_montant(total_aides_approuvees + total_dec)} CFA</span></div>
                </div>
                <div class="text-center bg-slate-900 text-white py-3 rounded-xl font-bold text-lg mb-6">Solde Réel en Caisse : <span class="text-emerald-400">{solde_fmt} CFA</span></div>

                <h3 class="text-sm font-bold text-slate-700 mb-2 uppercase tracking-wide">État des cotisations (Exercice en cours)</h3>
                <ul class="max-h-60 overflow-y-auto pr-2">{suivi_retards_html}</ul>
            </div>

            <div class="bg-white p-6 rounded-2xl shadow-sm border border-slate-200 mb-6">
                <h2 class="text-lg font-bold text-purple-600 mb-4 border-b pb-2">➕ Enregistrer une Cotisation ou Régularisation</h2>
                <form action="/cotisations-form" method="POST" class="space-y-4">
                    <input type="hidden" name="user_id" value="{user['id']}">
                    <div>
                        <label class="block text-xs font-bold text-slate-600 mb-1">Choisir un Adhérent</label>
                        <select name="adherent_id" required class="w-full p-2.5 border rounded-lg text-sm bg-white" size="4">
                            <option value="">-- Sélectionner dans la liste --</option>
                            {options_adherents}
                        </select>
                    </div>
                    <div class="grid grid-cols-1 sm:grid-cols-3 gap-3">
                        <div><label class="block text-xs font-bold text-slate-600 mb-1">Montant (CFA)</label><input type="number" name="montant" required class="w-full p-2.5 border rounded-lg text-sm"></div>
                        <div><label class="block text-xs font-bold text-slate-600 mb-1">Période (Mois ou Plage)</label><input type="text" name="periode" placeholder="ex: 2026-09 ou Sept-Janv" required class="w-full p-2.5 border rounded-lg text-sm bg-white"></div>
                        <div>
                            <label class="block text-xs font-bold text-slate-600 mb-1">Mode de règlement</label>
                            <select name="mode_paiement" class="w-full p-2.5 border rounded-lg text-sm bg-white">
                                <option value="especes">Espèces</option>
                                <option value="mobile_money">Mobile Money (Wave / OM)</option>
                                <option value="regularisation" class="font-bold text-purple-700">🔄 Régularisation (Sans impacter la caisse)</option>
                            </select>
                        </div>
                    </div>
                    <button type="submit" class="w-full bg-purple-600 hover:bg-purple-700 text-white font-bold py-2.5 rounded-lg text-sm">Valider l'enregistrement</button>
                </form>
            </div>
            """

        # Espace membre classique...
        return f"""
        <!DOCTYPE html>
        <html lang="fr">
        <head>
            <meta charset="UTF-8">
            <meta name="viewport" content="width=device-width, initial-scale=1.0">
            <title>Tableau de bord - Tinka ka Mein Haaldi fotti</title>
            <script src="https://cdn.tailwindcss.com"></script>
        </head>
        <body class="bg-slate-50 text-slate-800 font-sans antialiased min-h-screen py-6 px-4">
            <div class="max-w-4xl mx-auto">
                <header class="text-center mb-8">
                    <h1 class="text-2xl font-black text-slate-900">Tinka ka Mein Haaldi fotti</h1>
                    <a href="/" class="text-xs text-red-600 font-bold">Déconnexion</a>
                </header>
                {finance_sections_html}
            </div>
        </body>
        </html>
        """
    except Exception as e:
        return HTMLResponse(content=f"<h3>Erreur :</h3><p>{str(e)}</p><a href='/'>Retour</a>", status_code=500)

if __name__ == "__main__":
    uvicorn.run("app_asso:app", host="127.0.0.1", port=8000, reload=True)
