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

app = FastAPI(title="API Gestion Tinka ka Mein Haaldi fotti", version="25.0")

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
        return HTMLResponse(content=f"<script>alert('Erreur (Ce numéro existe peut-être déjà) : {str(e)}'); window.location.href='/';</script>")

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
        return HTMLResponse(content=f"<script>alert('Erreur lors de la modification : {str(e)}'); window.location.href='/dashboard?id={user_id}';</script>")

@app.post("/admin/reset-password")
def reset_password(user_id: int = Form(...), adherent_id: int = Form(...), nouveau_mdp: str = Form(...)):
    mdp_securise = hacher_mdp(nouveau_mdp)
    supabase.table("adherents").update({"mot_de_passe": mdp_securise}).eq("id", adherent_id).execute()
    return HTMLResponse(content=f"<script>alert('Mot de passe réinitialisé et sécurisé avec succès !'); window.location.href='/dashboard?id={user_id}';</script>")

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
                            <label class="block text-xs font-bold text-slate-600 mb-1">Téléphone (Identifiant unique, ex: 221771234567)</label>
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

        presences_res = supabase.table("presences_association").select("*, adherents(nom, prenom, secteur, telephone)").execute()
        all_presences = presences_res.data

        total_cotis = sum([c['montant'] for c in all_cotisations])
        total_aides_approuvees = sum([ai['montant_demande'] for ai in all_aides if ai['statut_validation'] == 'approuve'])
        total_dec = sum([d['montant'] for d in all_decaissements])
        solde = total_cotis - (total_aides_approuvees + total_dec)

        # URL pointant directement vers le profil pour le QR code de la carte
        url_profil_personnel = f"https://tinka-association.onrender.com/dashboard?id={user['id']}"
        qr_perso_b64 = generer_qrcode_base64(url_profil_personnel)

        finance_sections_html = ""
        if is_tresorier:
            options_adherents = "".join([f"<option value='{a['id']}' data-text='{a['prenom'].lower()} {a['nom'].lower()} {a['secteur'].lower()} {a['telephone']}'>{a['prenom']} {a['nom']} — Secteur: {a['secteur']} (Tél: {a['telephone']})</option>" for a in all_actifs if a['role'] != 'admin'])
            
            suivi_retards_html = ""
            relances_whatsapp_html = ""
            for a in all_actifs:
                cotis_membre = [c['periode'] for c in all_cotisations if c['adherent_id'] == a['id']]
                mois_manquants = [m for m in mois_12 if m not in cotis_membre]
                
                if not mois_manquants:
                    statut_ajour = "<span class='text-emerald-600 font-bold'>À jour</span>"
                else:
                    nb_retard = len(mois_manquants)
                    statut_ajour = f"<span class='text-red-600 font-bold'>Retard ({nb_retard} mois)</span>"
                    
                    msg_whatsapp = urllib.parse.quote(f"Bonjour {a['prenom']} {a['nom']}, le bureau de Tinka ka Mein Haaldi fotti vous rappelle que vous avez {nb_retard} mois de cotisation en retard ({', '.join(mois_manquants)}). Merci de régulariser.")

                    tel = a.get('telephone', '').replace('+', '').replace(' ', '')

                    relances_whatsapp_html += f"""
                    <div class="relance-item bg-red-50 p-4 rounded-xl border border-red-100 mb-3 text-sm" data-search="{a['prenom'].lower()} {a['nom'].lower()} {a['secteur'].lower()} {tel}">
                        <div class="flex justify-between items-center">
                            <div><b>{a['prenom']} {a['nom']}</b> <span class='text-xs text-slate-500'>({a['secteur']} - +{tel})</span></div>
                            <span class="text-red-700 font-bold text-xs bg-red-100 px-2.5 py-1 rounded-full">{nb_retard} mois manquant(s)</span>
                        </div>
                        <div class="text-xs text-slate-600 mt-1">Mois en retard : {', '.join(mois_manquants)}</div>
                        <div class="mt-2">
                            <a href="https://wa.me/{tel}?text={msg_whatsapp}" target="_blank" class="bg-emerald-600 hover:bg-emerald-700 text-white px-3 py-1.5 rounded-lg text-xs font-bold inline-flex items-center gap-1.5 shadow-sm">💚 Relancer par WhatsApp</a>
                        </div>
                    </div>
                    """

                suivi_retards_html += f"<li class='py-1.5 border-b border-slate-100 flex justify-between items-center text-sm'><span><b>{a['prenom']} {a['nom']}</b> <span class='text-xs text-slate-400'>({a['secteur']})</span></span> {statut_ajour}</li>"

            cotis_table_html = ""
            for c in cotis_affichees:
                adh = c.get('adherents', {}) or {}
                btn_recu = f"<a href='/cotisation/recu-pdf/{c['id']}' target='_blank' class='bg-blue-600 hover:bg-blue-700 text-white px-2.5 py-1 rounded text-xs font-semibold'>Reçu PDF</a>"
                montant_c_fmt = formater_montant(c['montant'])
                search_cotis = f"{adh.get('prenom','')} {adh.get('nom','')} {adh.get('secteur','')} {c['periode']} {c['mode_paiement']}".lower()
                cotis_table_html += f"<tr class='cotis-row hover:bg-slate-50' data-search='{search_cotis}'><td class='p-2.5 font-medium'>{adh.get('prenom','')} {adh.get('nom','')}</td><td class='p-2.5 text-slate-600'>{adh.get('secteur','')}</td><td class='p-2.5 font-bold text-emerald-600'>{montant_c_fmt} CFA</td><td class='p-2.5 text-slate-600'>{c['periode']}</td><td class='p-2.5 text-slate-600'>{c['mode_paiement']}</td><td class='p-2.5'>{btn_recu}</td></tr>"

            options_filtre_mois = "".join([f"<option value='{m}' {'selected' if filtre_periode==m else ''}>{m}</option>" for m in mois_12])

            categories_dict = {}
            for d in all_decaissements:
                cat = d.get('categorie', 'Divers') or 'Divers'
                categories_dict[cat] = categories_dict.get(cat, 0) + d['montant']
            
            repartition_depenses_html = ""
            for cat, montant_cat in categories_dict.items():
                montant_cat_fmt = formater_montant(montant_cat)
                repartition_depenses_html += f"<li class='flex justify-between py-1 text-sm border-b border-slate-100'><span>{cat}</span><span class='font-bold text-red-600'>{montant_cat_fmt} CFA</span></li>"

            adherents_table_rows = ""
            modals_html = ""
            for a in all_adherents:
                actions_admin = ""
                if a['statut'] == 'en_attente':
                    actions_admin += f"""
                    <form action="/admin/valider-adherent" method="POST" class="inline">
                        <input type="hidden" name="user_id" value="{user['id']}"><input type="hidden" name="adherent_id" value="{a['id']}">
                        <button type="submit" class="bg-emerald-600 text-white px-2 py-1 rounded text-xs font-bold">Valider</button>
                    </form>"""
                
                if is_admin:
                    actions_admin += f"""
                    <form action="/admin/changer-role" method="POST" class="inline-block ml-1">
                        <input type="hidden" name="user_id" value="{user['id']}"><input type="hidden" name="adherent_id" value="{a['id']}">
                        <select name="nouveau_role" onchange="this.form.submit()" class="p-1 text-xs border rounded bg-white font-semibold text-blue-700">
                            <option value="membre" {'selected' if a['role']=='membre' else ''}>Membre</option>
                            <option value="tresorier" {'selected' if a['role']=='tresorier' else ''}>Trésorier</option>
                            <option value="admin" {'selected' if a['role']=='admin' else ''}>Admin</option>
                        </select>
                    </form>
                    """

                photo_tag = f"<img src='{a['photo_profil']}' class='w-7 h-7 rounded-full object-cover mr-2' onerror='this.style.display=\"none\"'>" if a['photo_profil'] else "<div class='w-7 h-7 rounded-full bg-slate-200 flex items-center justify-center font-bold text-slate-500 text-[10px] mr-2'>" + a['prenom'][0] + "</div>"

                search_str = f"{a['prenom']} {a['nom']} {a['telephone']} {a['secteur']}".lower()
                
                adherents_table_rows += f"""
                <tr class="adherent-row hover:bg-slate-50 border-b border-slate-100 text-sm" data-search="{search_str}">
                    <td class="p-2.5 flex items-center font-medium text-slate-900">{photo_tag}{a['prenom']} {a['nom']}</td>
                    <td class="p-2.5 text-slate-600"><span class="text-xs bg-slate-100 px-2 py-0.5 rounded font-semibold uppercase">{a['role']}</span></td>
                    <td class="p-2.5 text-slate-600">{a['secteur']}</td>
                    <td class="p-2.5 text-slate-600 font-mono text-xs">{a['telephone']}</td>
                    <td class="p-2.5 text-slate-600"><span class="text-xs font-bold text-slate-500">{a['statut']}</span></td>
                    <td class="p-2.5 text-right space-x-1">
                        {actions_admin}
                        <button onclick="openModal({a['id']})" class="bg-blue-50 hover:bg-blue-100 text-blue-700 px-2.5 py-1 rounded text-xs font-bold">⚙️ Modifier</button>
                    </td>
                </tr>
                """

                modals_html += f"""
                <div id="modal-{a['id']}" class="fixed inset-0 bg-black/50 backdrop-blur-sm z-50 hidden flex items-center justify-center p-4">
                    <div class="bg-white rounded-2xl max-w-lg w-full p-6 shadow-2xl border border-slate-100">
                        <div class="flex justify-between items-center mb-4 border-b pb-2">
                            <h3 class="font-bold text-lg text-slate-900">Modifier : {a['prenom']} {a['nom']}</h3>
                            <button onclick="closeModal({a['id']})" class="text-slate-400 hover:text-slate-700 font-bold text-lg">✕</button>
                        </div>
                        
                        <form action="/admin/modifier-adherent" method="POST" class="space-y-3 mb-6">
                            <input type="hidden" name="user_id" value="{user['id']}">
                            <input type="hidden" name="adherent_id" value="{a['id']}">
                            <div class="grid grid-cols-2 gap-3">
                                <div>
                                    <label class="block text-xs font-bold text-slate-600 mb-1">Prénom</label>
                                    <input type="text" name="prenom" value="{a['prenom']}" required class="w-full p-2 text-sm border rounded-lg bg-white">
                                </div>
                                <div>
                                    <label class="block text-xs font-bold text-slate-600 mb-1">Nom</label>
                                    <input type="text" name="nom" value="{a['nom']}" required class="w-full p-2 text-sm border rounded-lg bg-white">
                                </div>
                            </div>
                            <div class="grid grid-cols-2 gap-3">
                                <div>
                                    <label class="block text-xs font-bold text-slate-600 mb-1">Téléphone (ID)</label>
                                    <input type="text" name="telephone" value="{a['telephone']}" required class="w-full p-2 text-sm border rounded-lg bg-white">
                                </div>
                                <div>
                                    <label class="block text-xs font-bold text-slate-600 mb-1">Secteur</label>
                                    <input type="text" name="secteur" value="{a['secteur']}" required class="w-full p-2 text-sm border rounded-lg bg-white">
                                </div>
                            </div>
                            <button type="submit" class="w-full bg-emerald-600 hover:bg-emerald-700 text-white py-2 rounded-lg text-sm font-bold shadow">Enregistrer les modifications</button>
                        </form>

                        <form action="/admin/reset-password" method="POST" class="pt-4 border-t border-slate-200 space-y-3">
                            <input type="hidden" name="user_id" value="{user['id']}">
                            <input type="hidden" name="adherent_id" value="{a['id']}">
                            <div>
                                <label class="block text-xs font-bold text-amber-700 mb-1">Réinitialiser le mot de passe</label>
                                <input type="text" name="nouveau_mdp" placeholder="Nouveau mot de passe" required class="w-full p-2 text-sm border rounded-lg bg-white mb-2">
                            </div>
                            <button type="submit" class="w-full bg-amber-600 hover:bg-amber-700 text-white py-2 rounded-lg text-sm font-bold shadow">Mettre à jour le mot de passe</button>
                        </form>
                    </div>
                </div>
                """

            # Tableau de suivi en direct des membres présents
            presences_table_rows = ""
            for p in all_presences:
                adh = p.get('adherents', {}) or {}
                st_pres = p.get('statut_presence', 'Present')
                badge_color = "bg-emerald-100 text-emerald-800" if st_pres == 'Present' else ("bg-amber-100 text-amber-800" if "excuse" in st_pres else "bg-red-100 text-red-800")
                presences_table_rows += f"""
                <tr class="presence-row hover:bg-slate-50 border-b border-slate-100 text-sm" data-search="{adh.get('prenom','').lower()} {adh.get('nom','').lower()} {p.get('evenement_titre','').lower()}">
                    <td class="p-2.5 font-bold text-slate-900">{adh.get('prenom','')} {adh.get('nom','')}</td>
                    <td class="p-2.5 text-slate-600">{p.get('evenement_titre','')}</td>
                    <td class="p-2.5 text-slate-500 text-xs">{p.get('date_reunion','')}</td>
                    <td class="p-2.5"><span class="text-xs px-2.5 py-1 rounded-full font-bold {badge_color}">{st_pres}</span></td>
                </tr>
                """

            options_presence_adherents = "".join([f"<option value='{a['id']}' data-text='{a['prenom'].lower()} {a['nom'].lower()} {a['secteur'].lower()}'>{a['prenom']} {a['nom']} — {a['secteur']}</option>" for a in all_actifs])
            options_evenements_titres = "".join([f"<option value='{ev['titre']}'>{ev['titre']} ({ev['date_evenement'][:10]})</option>" for ev in all_evenements]) or "<option value='Réunion Générale Association'>Réunion Générale Association</option>"

            total_cotis_fmt = formater_montant(total_cotis)
            total_aides_fmt = formater_montant(total_aides_approuvees)
            total_dec_fmt = formater_montant(total_dec)
            solde_fmt = formater_montant(solde)

            finance_sections_html = f"""
            <div class="bg-white p-6 rounded-2xl shadow-sm border border-slate-200 mb-6">
                <h2 class="text-lg font-bold text-emerald-700 mb-4 border-b pb-2">💰 Trésorerie Globale & Suivi</h2>
                <div class="grid grid-cols-1 sm:grid-cols-3 gap-4 mb-4 text-center">
                    <div class="bg-emerald-50 p-3 rounded-xl border border-emerald-100"><span class="block text-xs text-emerald-600 font-bold uppercase">Cotisations</span><span class="text-lg font-black text-emerald-800">{total_cotis_fmt} CFA</span></div>
                    <div class="bg-amber-50 p-3 rounded-xl border border-amber-100"><span class="block text-xs text-amber-600 font-bold uppercase">Aides Versées</span><span class="text-lg font-black text-amber-800">{total_aides_fmt} CFA</span></div>
                    <div class="bg-red-50 p-3 rounded-xl border border-red-100"><span class="block text-xs text-red-600 font-bold uppercase">Dépenses</span><span class="text-lg font-black text-red-800">{total_dec_fmt} CFA</span></div>
                </div>
                <div class="text-center bg-slate-900 text-white py-3 rounded-xl font-bold text-lg mb-6">Solde en Caisse : <span class="text-emerald-400">{solde_fmt} CFA</span></div>
                
                <h3 class="text-sm font-bold text-slate-700 mb-2 uppercase tracking-wide">Répartition des Dépenses (Daara & Général)</h3>
                <ul class="mb-6">{repartition_depenses_html or '<li class="text-sm text-slate-400">Aucune dépense enregistrée.</li>'}</ul>

                <h3 class="text-sm font-bold text-slate-700 mb-2 uppercase tracking-wide">État des cotisations (Exercice en cours)</h3>
                <ul class="max-h-60 overflow-y-auto pr-2">{suivi_retards_html}</ul>
            </div>

            <div class="bg-white p-6 rounded-2xl shadow-sm border border-slate-200 mb-6">
                <div class="flex flex-col sm:flex-row justify-between items-start sm:items-center mb-4 border-b pb-2 gap-2">
                    <div>
                        <h2 class="text-lg font-bold text-emerald-700">📢 Centre de Relances WhatsApp</h2>
                        <p class="text-xs text-slate-500">Envoyez instantanément un rappel pré-rempli.</p>
                    </div>
                    <input type="text" id="searchRelance" placeholder="🔍 Filtrer un retardataire..." onkeyup="filtrerRelances()" class="p-2 text-xs border rounded-lg bg-slate-50 w-full sm:w-64 focus:ring-2 focus:ring-emerald-500 focus:outline-none">
                </div>
                <div id="relanceContainer" class="max-h-80 overflow-y-auto pr-1">
                    {relances_whatsapp_html or '<div class="text-sm text-emerald-600 font-semibold p-3 bg-emerald-50 rounded-xl text-center">🎉 Aucun membre en retard pour le moment ! Tout le monde est à jour.</div>'}
                </div>
            </div>

            <div class="bg-white p-6 rounded-2xl shadow-sm border border-slate-200 mb-6">
                <h2 class="text-lg font-bold text-teal-700 mb-4 border-b pb-2">📋 Pointage & Présences aux Réunions (Association)</h2>
                <form action="/presences-form" method="POST" class="space-y-4">
                    <input type="hidden" name="user_id" value="{user['id']}">
                    <div class="grid grid-cols-1 sm:grid-cols-2 gap-3">
                        <div>
                            <label class="block text-xs font-bold text-slate-600 mb-1">Réunion / Événement</label>
                            <select name="evenement_titre" required class="w-full p-2.5 border rounded-lg text-sm bg-white">
                                {options_evenements_titres}
                            </select>
                        </div>
                        <div>
                            <label class="block text-xs font-bold text-slate-600 mb-1">Date de la réunion</label>
                            <input type="date" name="date_reunion" required class="w-full p-2.5 border rounded-lg text-sm bg-white">
                        </div>
                    </div>
                    <div>
                        <label class="block text-xs font-bold text-slate-600 mb-1">Rechercher et Pointer un Membre</label>
                        <input type="text" id="searchSelectPresence" placeholder="🔍 Taper un nom, prénom ou secteur..." onkeyup="filtrerSelectPresence()" class="w-full p-2.5 mb-2 border rounded-lg text-sm bg-slate-50 focus:ring-2 focus:ring-teal-500 focus:outline-none">
                        <select name="adherent_id" id="selectPresenceAdherent" required class="w-full p-2.5 border rounded-lg text-sm bg-white" size="4">
                            <option value="">-- Choisir un membre --</option>
                            {options_presence_adherents}
                        </select>
                    </div>
                    <div>
                        <label class="block text-xs font-bold text-slate-600 mb-1">Statut de présence</label>
                        <select name="statut_presence" required class="w-full p-2.5 border rounded-lg text-sm bg-white">
                            <option value="Present">🟢 Présent(e)</option>
                            <option value="Absent_excuse">🟡 Absent(e) excusé(e)</option>
                            <option value="Absent_non_excuse">🔴 Absent(e) non excusé(e)</option>
                        </select>
                    </div>
                    <button type="submit" class="w-full bg-teal-600 hover:bg-teal-700 text-white font-bold py-2.5 rounded-lg text-sm">Enregistrer le pointage</button>
                </form>

                <!-- Tableau de suivi en direct des membres pointés -->
                <div class="mt-6 pt-4 border-t border-slate-200">
                    <div class="flex justify-between items-center mb-3">
                        <h3 class="text-sm font-bold text-slate-700 uppercase tracking-wide">Membres pointés ({len(all_presences)})</h3>
                        <input type="text" id="searchPresences" placeholder="🔍 Filtrer les présents..." onkeyup="filtrerPresencesTable()" class="p-2 text-xs border rounded-lg bg-slate-50 w-48">
                    </div>
                    <div class="overflow-x-auto max-h-60 overflow-y-auto border border-slate-200 rounded-xl">
                        <table class="w-full text-left border-collapse bg-white">
                            <thead class="bg-slate-100 text-slate-600 text-[10px] uppercase sticky top-0">
                                <tr>
                                    <th class="p-2.5">Membre</th>
                                    <th class="p-2.5">Réunion</th>
                                    <th class="p-2.5">Date</th>
                                    <th class="p-2.5">Statut</th>
                                </tr>
                            </thead>
                            <tbody id="presencesTableBody">
                                {presences_table_rows or '<tr><td colspan="4" class="text-center p-4 text-slate-400 text-xs">Aucun pointage enregistré pour le moment.</td></tr>'}
                            </tbody>
                        </table>
                    </div>
                </div>
            </div>

            <div class="bg-white p-6 rounded-2xl shadow-sm border border-slate-200 mb-6">
                <h2 class="text-lg font-bold text-red-600 mb-4 border-b pb-2">📉 Enregistrer une Dépense</h2>
                <form action="/decaissements-form" method="POST" class="space-y-4">
                    <input type="hidden" name="user_id" value="{user['id']}">
                    <div><label class="block text-xs font-bold text-slate-600 mb-1">Motif</label><input type="text" name="motif" required class="w-full p-2.5 border rounded-lg text-sm"></div>
                    <div>
                        <label class="block text-xs font-bold text-slate-600 mb-1">Catégorie</label>
                        <select name="categorie" required class="w-full p-2.5 border rounded-lg text-sm bg-white">
                            <optgroup label="Daara Tinka (École Coranique)">
                                <option value="Daara - Salaires enseignants">Daara - Salaires enseignants</option>
                                <option value="Daara - Alimentation / Vivres">Daara - Alimentation / Vivres</option>
                                <option value="Daara - Matériel & Équipement">Daara - Matériel & Équipement</option>
                                <option value="Daara - Événements & Cérémonies">Daara - Événements & Cérémonies</option>
                            </optgroup>
                            <optgroup label="Association Générale">
                                <option value="Association - Loyer & Charges">Association - Loyer & Charges</option>
                                <option value="Association - Transport & Logistique">Association - Transport & Logistique</option>
                                <option value="Association - Événements">Association - Événements</option>
                                <option value="Divers" selected>Divers</option>
                            </optgroup>
                        </select>
                    </div>
                    <div class="grid grid-cols-2 gap-3">
                        <div><label class="block text-xs font-bold text-slate-600 mb-1">Montant (CFA)</label><input type="number" name="montant" required class="w-full p-2.5 border rounded-lg text-sm"></div>
                        <div><label class="block text-xs font-bold text-slate-600 mb-1">Bénéficiaire</label><input type="text" name="beneficiaire" required class="w-full p-2.5 border rounded-lg text-sm"></div>
                    </div>
                    <button type="submit" class="w-full bg-red-600 hover:bg-red-700 text-white font-bold py-2.5 rounded-lg text-sm">Enregistrer la dépense</button>
                </form>
            </div>

            <div class="bg-white p-6 rounded-2xl shadow-sm border border-slate-200 mb-6">
                <div class="flex flex-col sm:flex-row justify-between items-start sm:items-center mb-4 border-b pb-2 gap-2">
                    <h2 class="text-lg font-bold text-blue-600">🔍 Filtrage & Historique des Cotisations</h2>
                    <input type="text" id="searchCotisTable" placeholder="🔍 Rechercher dans le tableau..." onkeyup="filtrerCotisTable()" class="p-2 text-xs border rounded-lg bg-slate-50 w-full sm:w-64 focus:ring-2 focus:ring-blue-500 focus:outline-none">
                </div>
                <form method="GET" action="/dashboard" class="flex flex-col sm:flex-row gap-3 items-end mb-4">
                    <input type="hidden" name="id" value="{user['id']}">
                    <div class="w-full sm:flex-1"><label class="block text-xs font-bold text-slate-600 mb-1">Filtrer par Mois</label><select name="filtre_periode" class="w-full p-2.5 border rounded-lg text-sm bg-white"><option value="">-- Tous les mois --</option>{options_filtre_mois}</select></div>
                    <div class="flex gap-2 w-full sm:w-auto">
                        <button type="submit" class="flex-1 sm:flex-initial bg-blue-600 text-white px-4 py-2.5 rounded-lg text-sm font-bold">Filtrer</button>
                        <a href="/cotisations/export-pdf{f'?periode={filtre_periode}' if filtre_periode else ''}" target="_blank" class="flex-1 sm:flex-initial bg-slate-700 hover:bg-slate-800 text-white px-4 py-2.5 rounded-lg text-sm font-bold text-center">Export PDF</a>
                    </div>
                </form>
                <div class="overflow-x-auto max-h-60">
                    <table class="w-full text-left text-sm border-collapse" id="cotisTable">
                        <thead><tr class="bg-slate-100 text-slate-600 text-xs uppercase"><th class="p-2.5">Membre</th><th class="p-2.5">Secteur</th><th class="p-2.5">Montant</th><th class="p-2.5">Période</th><th class="p-2.5">Mode</th><th class="p-2.5">Reçu</th></tr></thead>
                        <tbody>{cotis_table_html or '<tr><td colspan="6" class="text-center p-4 text-slate-400">Aucune cotisation trouvée.</td></tr>'}</tbody>
                    </table>
                </div>
            </div>

            <div class="bg-white p-6 rounded-2xl shadow-sm border border-slate-200 mb-6">
                <div class="flex flex-col sm:flex-row justify-between items-center mb-4 border-b pb-2 gap-2">
                    <div>
                        <h2 class="text-lg font-bold text-slate-700">👥 Annuaire & Gestion des Adhérents ({len(all_adherents)} inscrits)</h2>
                        <p class="text-xs text-slate-500">Tapez un nom pour afficher instantanément le membre.</p>
                    </div>
                    <input type="text" id="searchAdherent" placeholder="🔍 Rechercher (nom, prénom, tél)..." onkeyup="filtrerAdherents()" class="p-2.5 text-xs border rounded-lg bg-slate-50 w-full sm:w-72 focus:ring-2 focus:ring-emerald-500 focus:outline-none font-semibold">
                </div>
                
                <div class="overflow-x-auto max-h-[450px] overflow-y-auto border border-slate-200 rounded-xl">
                    <table class="w-full text-left border-collapse bg-white">
                        <thead class="bg-slate-100 text-slate-600 text-xs uppercase sticky top-0 z-10 shadow-sm">
                            <tr>
                                <th class="p-2.5">Nom & Prénom</th>
                                <th class="p-2.5">Rôle</th>
                                <th class="p-2.5">Secteur</th>
                                <th class="p-2.5">Téléphone</th>
                                <th class="p-2.5">Statut</th>
                                <th class="p-2.5 text-right">Actions</th>
                            </tr>
                        </thead>
                        <tbody id="adherentsTableBody">
                            {adherents_table_rows}
                        </tbody>
                    </table>
                </div>
            </div>

            {modals_html}

            <div class="bg-white p-6 rounded-2xl shadow-sm border border-slate-200 mb-6">
                <h2 class="text-lg font-bold text-purple-600 mb-4 border-b pb-2">➕ Enregistrer une Cotisation</h2>
                <form action="/cotisations-form" method="POST" class="space-y-4">
                    <input type="hidden" name="user_id" value="{user['id']}">
                    <div>
                        <label class="block text-xs font-bold text-slate-600 mb-1">Rechercher et Choisir un Adhérent</label>
                        <input type="text" id="searchSelectAdherent" placeholder="🔍 Taper un nom, prénom ou téléphone pour filtrer la liste..." onkeyup="filtrerSelectAdherent()" class="w-full p-2.5 mb-2 border rounded-lg text-sm bg-slate-50 focus:ring-2 focus:ring-purple-500 focus:outline-none">
                        <select name="adherent_id" id="selectAdherent" required class="w-full p-2.5 border rounded-lg text-sm bg-white" size="4">
                            <option value="">-- Choisir dans la liste ci-dessus --</option>
                            {options_adherents}
                        </select>
                    </div>
                    <div class="grid grid-cols-1 sm:grid-cols-3 gap-3">
                        <div><label class="block text-xs font-bold text-slate-600 mb-1">Montant (CFA)</label><input type="number" name="montant" required class="w-full p-2.5 border rounded-lg text-sm"></div>
                        <div><label class="block text-xs font-bold text-slate-600 mb-1">Période (Mois)</label><select name="periode" required class="w-full p-2.5 border rounded-lg text-sm bg-white">{"".join([f"<option value='{m}'>{m}</option>" for m in mois_12])}</select></div>
                        <div><label class="block text-xs font-bold text-slate-600 mb-1">Mode</label><select name="mode_paiement" class="w-full p-2.5 border rounded-lg text-sm bg-white"><option value="especes">Espèces</option><option value="mobile_money">Mobile Money</option><option value="virement">Virement</option></select></div>
                    </div>
                    <button type="submit" class="w-full bg-purple-600 hover:bg-purple-700 text-white font-bold py-2.5 rounded-lg text-sm">Valider la cotisation</button>
                </form>
            </div>
            """

        member_sections_html = ""
        if not is_tresorier:
            cotis_perso = [c for c in all_cotisations if c['adherent_id'] == user['id']]
            mois_payes_list = [c['periode'] for c in cotis_perso]
            
            mois_payes_html = ""
            for c in cotis_perso:
                btn_recu_perso = f"<a href='/cotisation/recu-pdf/{c['id']}' target='_blank' class='bg-blue-600 text-white px-2.5 py-1 rounded text-xs font-semibold inline-block ml-2'>Télécharger Reçu PDF</a>"
                montant_cp_fmt = formater_montant(c['montant'])
                mois_payes_html += f"<li class='py-2 border-b border-slate-100 text-sm flex justify-between items-center'><span>Mois de <b>{c['periode']}</b> : <span class='text-emerald-600 font-bold'>Payé ({montant_cp_fmt} CFA)</span></span> {btn_recu_perso}</li>"

            mois_retard_html = "".join([f"<li class='py-2 border-b border-slate-100 text-sm flex justify-between items-center'><span>Mois de {m}</span> <span class='text-red-600 font-bold'>Non payé</span></li>" for m in mois_12 if m not in mois_payes_list])
            
            aides_membre_html = ""
            for ai in all_aides:
                if ai['adherent_id'] == user['id']:
                    montant_ai_fmt = formater_montant(ai['montant_demande'])
                    aides_membre_html += f"<li class='py-2 border-b border-slate-100 text-sm'>Motif : <b>{ai['motif']}</b> ({montant_ai_fmt} CFA) — Statut : <span class='font-bold text-amber-600'>{ai['statut_validation']}</span></li>"

            member_sections_html = f"""
            <!-- CARTE DE MEMBRE NUMÉRIQUE OFFICIELLE -->
            <div class="bg-gradient-to-br from-slate-900 via-slate-800 to-emerald-950 text-white p-6 rounded-3xl shadow-xl border border-slate-700 mb-6 relative overflow-hidden">
                <div class="absolute -right-10 -bottom-10 w-40 h-40 bg-emerald-500/10 rounded-full blur-2xl pointer-events-none"></div>
                
                <div class="flex justify-between items-start mb-6">
                    <div>
                        <span class="text-[10px] bg-emerald-500/20 text-emerald-400 font-bold px-3 py-1 rounded-full uppercase tracking-widest border border-emerald-500/30">Carte d'Adhérent Officielle</span>
                        <h2 class="text-xl font-black tracking-tight mt-2">Tinka ka Mein Haaldi fotti</h2>
                    </div>
                    <span class="text-xs uppercase bg-blue-500/20 text-blue-300 font-bold px-2.5 py-1 rounded-lg border border-blue-500/30">{user['role']}</span>
                </div>

                <div class="flex flex-col sm:flex-row items-center gap-6 bg-white/5 p-4 rounded-2xl backdrop-blur-md border border-white/10">
                    <div class="text-center sm:text-left flex items-center gap-4 w-full">
                        <div class="w-20 h-20 rounded-2xl bg-slate-700 overflow-hidden flex-shrink-0 border-2 border-emerald-500 shadow-md">
                            {"<img src='" + user['photo_profil'] + "' class='w-full h-full object-cover'>" if user['photo_profil'] else "<div class='w-full h-full flex items-center justify-center font-bold text-xl text-white'>" + user['prenom'][0] + "</div>"}
                        </div>
                        <div>
                            <h3 class="text-lg font-bold text-white">{user['prenom']} {user['nom']}</h3>
                            <p class="text-xs text-slate-300 mt-0.5">Secteur : <span class="text-emerald-400 font-semibold">{user['secteur']}</span></p>
                            <p class="text-xs text-slate-300">Tél : <span class="font-mono text-slate-200">{user['telephone']}</span></p>
                            <p class="text-[10px] text-emerald-400 font-bold mt-2">✨ Statut : Compte Vérifié & Actif</p>
                        </div>
                    </div>
                    
                    <div class="bg-white p-2.5 rounded-xl shadow-inner text-center flex-shrink-0">
                        <img src="data:image/png;base64,{qr_perso_b64}" alt="QR Code Personnel" class="w-28 h-28 rounded">
                        <span class="block text-[9px] font-bold text-slate-700 mt-1 uppercase">ID: {user['id']}</span>
                    </div>
                </div>
            </div>

            <div class="bg-white p-6 rounded-2xl shadow-sm border border-slate-200 mb-6">
                <h2 class="text-lg font-bold text-emerald-700 mb-4 border-b pb-2">📋 Mon Suivi de Cotisations ({annee_courante})</h2>
                <ul class="max-h-60 overflow-y-auto">{mois_payes_html or '<li class="text-sm text-slate-400">Aucun versement enregistré.</li>'}{mois_retard_html}</ul>
            </div>

            <div class="bg-white p-6 rounded-2xl shadow-sm border border-slate-200 mb-6">
                <h2 class="text-lg font-bold text-amber-600 mb-4 border-b pb-2">🤝 Mes Demandes d'Aide</h2>
                <ul class="mb-6">{aides_membre_html or '<li class="text-sm text-slate-400">Aucune demande soumise.</li>'}</ul>
                <h3 class="text-sm font-bold text-slate-700 mb-3 uppercase tracking-wide">Faire une nouvelle demande</h3>
                <form action="/aides-form" method="POST" class="space-y-4">
                    <input type="hidden" name="user_id" value="{user['id']}">
                    <div><label class="block text-xs font-bold text-slate-600 mb-1">Motif</label><input type="text" name="motif" required class="w-full p-2.5 border rounded-lg text-sm"></div>
                    <div><label class="block text-xs font-bold text-slate-600 mb-1">Montant demandé (CFA)</label><input type="number" name="montant_demande" required class="w-full p-2.5 border rounded-lg text-sm"></div>
                    <button type="submit" class="w-full bg-amber-600 hover:bg-amber-700 text-white font-bold py-2.5 rounded-lg text-sm">Soumettre la demande</button>
                </form>
            </div>
            """

        evenements_html = ""
        for ev in all_evenements:
            evenements_html += f"""
            <div class="bg-slate-50 p-4 rounded-xl border border-slate-200 mb-3">
                <div class="flex justify-between items-start mb-2"><h3 class="font-bold text-slate-900 text-base">{ev['titre']}</h3><span class="bg-blue-100 text-blue-800 text-xs px-2.5 py-0.5 rounded-full font-bold">{ev['type_evenement']}</span></div>
                <p class="text-sm text-slate-600 mb-2"><b>Description :</b> {ev['description']}</p>
                <div class="text-xs text-slate-500 flex flex-wrap gap-4"><span>📅 {ev['date_evenement']}</span><span>📍 {ev['lieu']}</span><span>📌 Statut: <b>{ev['statut']}</b></span></div>
            </div>
            """

        projets_html = ""
        for p in all_projets:
            img_tag = f"<img src='{p['photo_projet']}' class='w-full h-40 object-cover rounded-xl mb-3' onerror='this.style.display=\"none\"'>" if p['photo_projet'] else ""
            cout_p_fmt = formater_montant(p['cout'])
            projets_html += f"""
            <div class="bg-slate-50 p-4 rounded-xl border border-slate-200 mb-4">
                {img_tag}
                <div class="flex justify-between items-start mb-2"><h3 class="font-bold text-slate-900 text-base">{p['titre']}</h3><span class="bg-emerald-100 text-emerald-800 text-xs px-2.5 py-0.5 rounded-full font-bold">{p['statut']}</span></div>
                <p class="text-sm text-slate-600 mb-2">{p['description']}</p>
                <div class="text-xs text-slate-500 flex gap-4"><span>💰 {cout_p_fmt} CFA</span><span>⏳ {p['chronologie']}</span></div>
            </div>
            """

        user_photo = f"<img src='{user['photo_profil']}' class='w-16 h-16 rounded-full object-cover shadow-sm' onerror='this.style.display=\"none\"'>" if user['photo_profil'] else "<div class='w-16 h-16 rounded-full bg-slate-200 flex items-center justify-center font-bold text-slate-500 text-xl'>" + user['prenom'][0] + "</div>"

        return f"""
        <!DOCTYPE html>
        <html lang="fr">
        <head>
            <meta charset="UTF-8">
            <meta name="viewport" content="width=device-width, initial-scale=1.0">
            <title>Tableau de bord - Tinka ka Mein Haaldi fotti</title>
            <script src="https://cdn.tailwindcss.com"></script>
            <script>
                function openModal(id) {{
                    document.getElementById('modal-' + id).classList.remove('hidden');
                }}
                function closeModal(id) {{
                    document.getElementById('modal-' + id).classList.add('hidden');
                }}

                function filtrerAdherents() {{
                    let input = document.getElementById('searchAdherent').value.toLowerCase();
                    let rows = document.getElementsByClassName('adherent-row');
                    for (let i = 0; i < rows.length; i++) {{
                        let text = rows[i].getAttribute('data-search');
                        rows[i].style.display = text.includes(input) ? "" : "none";
                    }}
                }}

                function filtrerSelectAdherent() {{
                    let input = document.getElementById('searchSelectAdherent').value.toLowerCase();
                    let select = document.getElementById('selectAdherent');
                    let options = select.getElementsByTagName('option');
                    for (let i = 1; i < options.length; i++) {{
                        let text = options[i].getAttribute('data-text');
                        options[i].style.display = text.includes(input) ? "" : "none";
                    }}
                }}

                function filtrerSelectPresence() {{
                    let input = document.getElementById('searchSelectPresence').value.toLowerCase();
                    let select = document.getElementById('selectPresenceAdherent');
                    let options = select.getElementsByTagName('option');
                    for (let i = 1; i < options.length; i++) {{
                        let text = options[i].getAttribute('data-text');
                        options[i].style.display = text.includes(input) ? "" : "none";
                    }}
                }}

                function filtrerPresencesTable() {{
                    let input = document.getElementById('searchPresences').value.toLowerCase();
                    let rows = document.getElementsByClassName('presence-row');
                    for (let i = 0; i < rows.length; i++) {{
                        let text = rows[i].getAttribute('data-search');
                        rows[i].style.display = text.includes(input) ? "" : "none";
                    }}
                }}

                function filtrerRelances() {{
                    let input = document.getElementById('searchRelance').value.toLowerCase();
                    let items = document.getElementsByClassName('relance-item');
                    for (let i = 0; i < items.length; i++) {{
                        let text = items[i].getAttribute('data-search');
                        items[i].style.display = text.includes(input) ? "" : "none";
                    }}
                }}

                function filtrerCotisTable() {{
                    let input = document.getElementById('searchCotisTable').value.toLowerCase();
                    let rows = document.getElementsByClassName('cotis-row');
                    for (let i = 0; i < rows.length; i++) {{
                        let text = rows[i].getAttribute('data-search');
                        rows[i].style.display = text.includes(input) ? "" : "none";
                    }}
                }}
            </script>
        </head>
        <body class="bg-slate-50 text-slate-800 font-sans antialiased min-h-screen py-6 px-4">
            <div class="max-w-4xl mx-auto">
                <header class="text-center mb-8">
                    <span class="text-xs font-bold text-emerald-700 bg-emerald-100 px-3 py-1 rounded-full uppercase tracking-wider">Espace Membre & Bureau</span>
                    <h1 class="text-2xl sm:text-3xl font-black text-slate-900 mt-2">Tinka ka Mein Haaldi fotti</h1>
                </header>

                <div class="bg-white p-6 rounded-2xl shadow-sm border border-slate-200 mb-6 flex flex-col sm:flex-row items-center gap-4 justify-between">
                    <div class="flex items-center gap-4 w-full sm:w-auto">
                        {user_photo}
                        <div>
                            <h2 class="text-lg font-bold text-slate-900">{user['prenom']} {user['nom']}</h2>
                            <p class="text-xs text-slate-500">Secteur : {user['secteur']} | Tél : {user['telephone']}</p>
                            <p class="text-xs font-bold text-blue-600 uppercase mt-1">Rôle : {user['role']}</p>
                        </div>
                    </div>
                    <div class="flex flex-col sm:flex-row gap-2 w-full sm:w-auto">
                        <form action="/modifier-photo" method="POST" enctype="multipart/form-data" class="flex gap-2 items-center">
                            <input type="hidden" name="user_id" value="{user['id']}">
                            <input type="file" name="file_photo" accept="image/*" required class="text-xs text-slate-500 file:py-1.5 file:px-3 file:rounded-lg file:border-0 file:bg-blue-50 file:text-blue-700">
                            <button type="submit" class="bg-blue-600 text-white px-3 py-1.5 rounded-lg text-xs font-bold">Photo</button>
                        </form>
                        <a href="/" class="bg-red-600 hover:bg-red-700 text-white px-4 py-1.5 rounded-lg text-xs font-bold text-center">Déconnexion</a>
                    </div>
                </div>

                {finance_sections_html}

                {member_sections_html}

                <div class="bg-white p-6 rounded-2xl shadow-sm border border-slate-200 mb-6">
                    <h2 class="text-lg font-bold text-slate-800 mb-4 border-b pb-2">📅 Agenda des Événements & Réunions</h2>
                    <div>{evenements_html or '<p class="text-sm text-slate-400">Aucun événement planifié.</p>'}</div>
                </div>

                <div class="bg-white p-6 rounded-2xl shadow-sm border border-slate-200 mb-6">
                    <h2 class="text-lg font-bold text-slate-800 mb-4 border-b pb-2">🚀 Projets de l'Association & du Bureau</h2>
                    <div>{projets_html or '<p class="text-sm text-slate-400">Aucun projet enregistré.</p>'}</div>
                </div>
            </div>
        </body>
        </html>
        """
    except Exception as e:
        return HTMLResponse(content=f"<h3>Erreur du Tableau de bord :</h3><p>{str(e)}</p><a href='/'>Retour</a>", status_code=500)

if __name__ == "__main__":
    uvicorn.run("app_asso:app", host="127.0.0.1", port=8000, reload=True)
