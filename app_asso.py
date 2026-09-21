from fastapi import FastAPI, HTTPException, Depends, Form, status, Query, UploadFile, File
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, StreamingResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
import io
import os
import datetime
from typing import Optional, List
import bcrypt
import qrcode
import base64
from reportlab.lib.pagesizes import letter
from reportlab.pdfgen import canvas
from supabase import create_client, Client

app = FastAPI(title="API Gestion Tinka ka Mein Haaldi fotti", version="51.0")

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

def formater_date(date_str: str) -> str:
    if not date_str:
        return ""
    try:
        nettoi = date_str[:10]
        annee, mois, jour = nettoi.split("-")
        return f"{jour}-{mois}-{annee}"
    except Exception:
        return date_str

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

async def fichier_vers_base64(file_upload: UploadFile) -> str:
    if not file_upload or not file_upload.filename:
        return ""
    contents = await file_upload.read()
    if not contents:
        return ""
    encoded = base64.b64encode(contents).decode("utf-8")
    return f"data:image/jpeg;base64,{encoded}"

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
    try:
        existing_user = supabase.table("adherents").select("id").eq("telephone", telephone).execute()
        if existing_user.data:
            return HTMLResponse(content="<script>alert('Erreur : Ce numéro de téléphone est déjà associé à un compte existant. Veuillez vous connecter.'); window.location.href='/';</script>")

        photo_b64 = await fichier_vers_base64(file_photo)
        mdp_securise = hacher_mdp(mot_de_passe)

        supabase.table("adherents").insert({
            "nom": nom, "prenom": prenom, "email": f"{telephone}@tinka.local", "telephone": telephone,
            "adresse": adresse, "secteur": secteur, "photo_profil": photo_b64, "mot_de_passe": mdp_securise
        }).execute()
        return HTMLResponse(content="<script>alert('Compte créé avec succès ! En attente de validation.'); window.location.href='/';</script>")
    except Exception as e:
        return HTMLResponse(content=f"<script>alert('Erreur lors de l\\'inscription : {str(e)}'); window.location.href='/';</script>")

@app.api_route("/modifier-photo", methods=["GET", "POST"])
async def modifier_photo(user_id: Optional[int] = Form(None), file_photo: Optional[UploadFile] = File(None)):
    if not user_id:
        return RedirectResponse(url="/", status_code=303)
    
    if file_photo and file_photo.filename:
        photo_b64 = await fichier_vers_base64(file_photo)
        supabase.table("adherents").update({"photo_profil": photo_b64}).eq("id", user_id).execute()

    return RedirectResponse(url=f"/dashboard?id={user_id}", status_code=status.HTTP_303_SEE_OTHER)

@app.api_route("/admin/valider-adherent", methods=["GET", "POST"])
def valider_adherent(user_id: Optional[int] = Form(None), adherent_id: Optional[int] = Form(None)):
    if user_id and adherent_id:
        supabase.table("adherents").update({"statut": "actif"}).eq("id", adherent_id).execute()
        return RedirectResponse(url=f"/dashboard?id={user_id}", status_code=status.HTTP_303_SEE_OTHER)
    return RedirectResponse(url="/", status_code=303)

@app.api_route("/admin/changer-role", methods=["GET", "POST"])
def changer_role(user_id: Optional[int] = Form(None), adherent_id: Optional[int] = Form(None), nouveau_role: Optional[str] = Form(None)):
    if user_id and adherent_id and nouveau_role:
        supabase.table("adherents").update({"role": nouveau_role}).eq("id", adherent_id).execute()
        return RedirectResponse(url=f"/dashboard?id={user_id}", status_code=status.HTTP_303_SEE_OTHER)
    return RedirectResponse(url="/", status_code=303)

@app.api_route("/admin/modifier-adherent", methods=["GET", "POST"])
def modifier_adherent(
    user_id: Optional[int] = Form(None), adherent_id: Optional[int] = Form(None),
    nom: Optional[str] = Form(None), prenom: Optional[str] = Form(None),
    telephone: Optional[str] = Form(None), secteur: Optional[str] = Form(None)
):
    if not user_id or not adherent_id:
        return RedirectResponse(url="/", status_code=303)
    try:
        supabase.table("adherents").update({
            "nom": nom, "prenom": prenom, "telephone": telephone, "secteur": secteur
        }).eq("id", adherent_id).execute()
        return HTMLResponse(content=f"<script>alert('Informations mises à jour avec succès !'); window.location.href='/dashboard?id={user_id}';</script>")
    except Exception as e:
        return HTMLResponse(content=f"<script>alert('Erreur : {str(e)}'); window.location.href='/dashboard?id={user_id}';</script>")

@app.api_route("/admin/reset-password", methods=["GET", "POST"])
def reset_password(user_id: Optional[int] = Form(None), adherent_id: Optional[int] = Form(None), nouveau_mdp: Optional[str] = Form(None)):
    if not user_id or not adherent_id or not nouveau_mdp:
        return RedirectResponse(url="/", status_code=303)
    mdp_securise = hacher_mdp(nouveau_mdp)
    supabase.table("adherents").update({"mot_de_passe": mdp_securise}).eq("id", adherent_id).execute()
    return HTMLResponse(content=f"<script>alert('Mot de passe réinitialisé et sécurisé avec succès !'); window.location.href='/dashboard?id={user_id}';</script>")

@app.api_route("/admin/maj-solde-initial", methods=["GET", "POST"])
def maj_solde_initial(user_id: Optional[int] = Form(None), solde_initial: Optional[float] = Form(None)):
    if not user_id or solde_initial is None:
        return RedirectResponse(url="/", status_code=303)
    try:
        supabase.table("parametres").update({"solde_initial": solde_initial}).eq("id", 1).execute()
        return HTMLResponse(content=f"<script>alert('Solde initial de caisse mis à jour avec succès !'); window.location.href='/dashboard?id={user_id}';</script>")
    except Exception as e:
        return HTMLResponse(content=f"<script>alert('Erreur : {str(e)}'); window.location.href='/dashboard?id={user_id}';</script>")

@app.api_route("/admin/valider-aide", methods=["GET", "POST"])
def valider_aide(user_id: Optional[int] = Form(None), aide_id: Optional[int] = Form(None), statut_validation: Optional[str] = Form(None)):
    if user_id and aide_id and statut_validation:
        supabase.table("aides").update({"statut_validation": statut_validation}).eq("id", aide_id).execute()
        return RedirectResponse(url=f"/dashboard?id={user_id}", status_code=status.HTTP_303_SEE_OTHER)
    return RedirectResponse(url="/", status_code=303)

@app.api_route("/admin/valider-paiement-mobile", methods=["GET", "POST"])
def valider_paiement_mobile(user_id: Optional[int] = Form(None), paiement_id: Optional[int] = Form(None)):
    if user_id and paiement_id:
        supabase.table("cotisations").update({"statut_paiement": "valide"}).eq("id", paiement_id).execute()
        return HTMLResponse(content=f"<script>alert('Paiement mobile vérifié et validé avec succès ! Ajouté à la caisse.'); window.location.href='/dashboard?id={user_id}';</script>")
    return RedirectResponse(url="/", status_code=303)

@app.post("/cotisations-form/")
@app.post("/cotisations-form")
def ajouter_cotisation(user_id: int = Form(...), adherent_id: int = Form(...), montant: float = Form(...), periode: str = Form(...), mode_paiement: str = Form(...)):
    supabase.table("cotisations").insert({
        "adherent_id": adherent_id, "montant": montant, "periode": periode, "mode_paiement": mode_paiement, "statut_paiement": "valide"
    }).execute()
    return RedirectResponse(url=f"/dashboard?id={user_id}", status_code=status.HTTP_303_SEE_OTHER)

@app.post("/paiement-mobile-form/")
@app.post("/paiement-mobile-form")
def paiement_mobile(
    user_id: int = Form(...),
    montant: float = Form(...),
    periode: str = Form(...),
    operateur: str = Form(...),
    telephone_paiement: str = Form(...),
    reference_transaction: str = Form(...),
    numero_recepteur: str = Form(...)
):
    try:
        mode = f"mobile_{operateur.lower()} (Réf: {reference_transaction} | Vers: {numero_recepteur} | Tél: {telephone_paiement})"
        supabase.table("cotisations").insert({
            "adherent_id": user_id,
            "montant": montant,
            "periode": periode,
            "mode_paiement": mode,
            "statut_paiement": "en_attente"
        }).execute()
        return HTMLResponse(content=f"<script>alert('Paiement {operateur} déclaré avec succès ! En attente de vérification par le trésorier.'); window.location.href='/dashboard?id={user_id}';</script>")
    except Exception as e:
        return HTMLResponse(content=f"<script>alert('Erreur lors du paiement mobile : {str(e)}'); window.location.href='/dashboard?id={user_id}';</script>")

@app.post("/aides-form/")
@app.post("/aides-form")
def demander_aide(user_id: int = Form(...), motif: str = Form(...), montant_demande: float = Form(...)):
    supabase.table("aides").insert({
        "adherent_id": user_id, "motif": motif, "montant_demande": montant_demande, "statut_validation": "en_attente"
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
    photo_b64 = await fichier_vers_base64(file_projet)
    supabase.table("projets").insert({
        "titre": titre, "description": description, "objectifs": objectifs,
        "cout": cout, "photo_projet": photo_b64, "chronologie": chronologie, "statut": statut
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

@app.post("/panorama-form/")
@app.post("/panorama-form")
async def ajouter_panorama(user_id: int = Form(...), legende: str = Form(...), files_photos: List[UploadFile] = File(...)):
    try:
        user_check = supabase.table("adherents").select("role").eq("id", user_id).execute()
        if not user_check.data or user_check.data[0]['role'] not in ['admin', 'tresorier']:
            return HTMLResponse(content="<script>alert('Action non autorisée.'); window.history.back();</script>", status_code=403)

        for file_photo in files_photos:
            if file_photo and file_photo.filename:
                photo_b64 = await fichier_vers_base64(file_photo)
                if photo_b64:
                    supabase.table("panorama_village").insert({
                        "legende": legende, "photo_url": photo_b64, "auteur_id": user_id
                    }).execute()

        return RedirectResponse(url=f"/dashboard?id={user_id}", status_code=status.HTTP_303_SEE_OTHER)
    except Exception as e:
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

@app.get("/adherents/export-pdf")
def export_adherents_pdf():
    res = supabase.table("adherents").select("*").order("nom").execute()
    adherents = res.data

    buffer = io.BytesIO()
    p = canvas.Canvas(buffer, pagesize=letter)
    width, height = letter

    p.setFont("Helvetica-Bold", 14)
    p.setFillColorRGB(0.15, 0.25, 0.35)
    p.drawString(50, height - 40, "TINKA KA MEIN HAALDI FOTTI")
    p.setFont("Helvetica", 9)
    p.setFillColorRGB(0.4, 0.4, 0.4)
    p.drawString(50, height - 55, "Annuaire Officiel des Adhérents")
    p.setStrokeColorRGB(0.8, 0.8, 0.8)
    p.line(50, height - 65, width - 50, height - 65)

    p.setFont("Helvetica-Bold", 13)
    p.setFillColorRGB(0, 0, 0)
    p.drawString(50, height - 95, f"Liste Générale des Adhérents ({len(adherents)} membres)")

    p.setFont("Helvetica", 10)
    y = height - 130
    for a in adherents:
        nom = a.get('nom', '')
        prenom = a.get('prenom', '')
        secteur = a.get('secteur', '')
        telephone = a.get('telephone', '')
        role = a.get('role', '')
        statut = a.get('statut', '')
        
        p.drawString(50, y, f"- {prenom} {nom} | Secteur: {secteur} | Tél: {telephone} | Rôle: {role} ({statut})")
        y -= 20
        if y < 50:
            p.showPage()
            y = height - 50

    p.save()
    buffer.seek(0)
    return StreamingResponse(buffer, media_type="application/pdf", headers={"Content-Disposition": "attachment; filename=annuaire_adherents.pdf"})

@app.get("/cotisations/export-pdf")
def export_cotisations_pdf(periode: Optional[str] = Query(None)):
    query = supabase.table("cotisations").select("*, adherents(nom, prenom, secteur)").eq("statut_paiement", "valide")
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
    if c.get('statut_paiement', 'valide') != 'valide':
        return HTMLResponse("<script>alert('Ce paiement est encore en attente de vérification. Le reçu ne peut pas être émis.'); window.history.back();</script>", status_code=403)

    adh = c.get('adherents', {}) or {}
    montant_fmt = formater_montant(c['montant'])
    date_paiement_fr = formater_date(c.get('date_paiement', ''))

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
    p.drawString(50, height - 145, f"Date de Paiement : {date_paiement_fr}")
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

    try:
        panorama_res = supabase.table("panorama_village").select("*, adherents(nom, prenom)").order("id", desc=True).execute()
        all_panorama = panorama_res.data
    except Exception:
        all_panorama = []

    panorama_cards_public = ""
    for pano in all_panorama:
        adh_p = pano.get('adherents', {}) or {}
        auteur_nom = f"{adh_p.get('prenom', '')} {adh_p.get('nom', '')}" if adh_p else "Administration"
        photo_url = pano.get('photo_url', '')
        panorama_cards_public += f"""
        <div class="bg-white rounded-2xl overflow-hidden shadow-sm border border-slate-200 flex flex-col">
            <img src="{photo_url}" class="w-full h-48 object-cover bg-slate-100" onerror="this.onerror=null; this.src='https://via.placeholder.com/400x300?text=Image+Indisponible';">
            <div class="p-4 flex-1 flex flex-col justify-between">
                <p class="text-xs font-semibold text-slate-800 mb-2">"{pano.get('legende', '')}"</p>
                <span class="text-[10px] font-bold text-emerald-700 bg-emerald-50 px-2 py-0.5 rounded-full self-start">📸 Publié par {auteur_nom}</span>
            </div>
        </div>
        """

    return f"""
    <!DOCTYPE html>
    <html lang="fr">
    <head>
        <meta charset="UTF-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <title>Tinka ka Mein Haaldi fotti</title>
        <script src="https://cdn.tailwindcss.com"></script>
    </head>
    <body class="bg-slate-50 text-slate-800 font-sans antialiased min-h-screen py-8 px-4 flex flex-col justify-between">
        <div class="max-w-md mx-auto w-full bg-white rounded-2xl shadow-xl p-6 sm:p-8 border border-slate-100 mb-8">
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

        <div class="max-w-4xl mx-auto w-full bg-slate-100 p-6 rounded-3xl border border-slate-200 mt-6">
            <h3 class="text-center text-lg font-black text-slate-800 mb-1">🌍 Souvenirs & Panorama du Village</h3>
            <p class="text-center text-xs text-slate-500 mb-6">Découvrez les photos prises au village publiées par l'administration.</p>
            <div class="grid grid-cols-1 sm:grid-cols-2 md:grid-cols-3 gap-4">
                {panorama_cards_public or '<p class="col-span-3 text-center text-xs text-slate-400 py-4">Aucune photo de panorama publiée pour le moment.</p>'}
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

        aides_res = supabase.table("aides").select("*, adherents(nom, prenom, secteur)").execute()
        all_aides = aides_res.data

        dec_res = supabase.table("decaissements").select("*").execute()
        all_decaissements = dec_res.data

        proj_res = supabase.table("projets").select("*").execute()
        all_projets = proj_res.data

        evt_res = supabase.table("evenements").select("*").execute()
        all_evenements = evt_res.data

        try:
            presences_res = supabase.table("presences_association").select("*, adherents(nom, prenom, secteur, telephone)").execute()
            all_presences = presences_res.data
        except Exception:
            all_presences = []

        try:
            panorama_res = supabase.table("panorama_village").select("*, adherents(nom, prenom)").order("id", desc=True).execute()
            all_panorama = panorama_res.data
        except Exception:
            all_panorama = []

        param_res = supabase.table("parametres").select("solde_initial").eq("id", 1).execute()
        solde_initial = param_res.data[0]['solde_initial'] if param_res.data else 0.0

        cotisations_caisse = sum([c['montant'] for c in all_cotisations if "regularisation" not in str(c.get('mode_paiement', '')) and c.get('statut_paiement', 'valide') == 'valide'])
        total_aides_approuvees = sum([ai['montant_demande'] for ai in all_aides if ai['statut_validation'] == 'approuve'])
        total_dec = sum([d['montant'] for d in all_decaissements])
        
        solde = solde_initial + cotisations_caisse - (total_aides_approuvees + total_dec)

        url_profil_personnel = f"https://tinka-association.onrender.com/dashboard?id={user['id']}"
        qr_perso_b64 = generer_qrcode_base64(url_profil_personnel)

        projets_cards_html = ""
        for pr in all_projets:
            photo_html = f"<img src='{pr['photo_projet']}' class='w-full h-44 object-cover rounded-xl mb-3 shadow-sm border border-slate-100' onerror='this.style.display=\"none\"'>" if pr.get('photo_projet') else ""
            projets_cards_html += f"""
            <div class="bg-slate-50 p-4 rounded-2xl border border-slate-200 mb-4 shadow-sm">
                {photo_html}
                <div class="flex justify-between items-start gap-2 mb-2">
                    <h4 class="font-bold text-base text-indigo-950">{pr['titre']}</h4>
                    <span class="text-xs font-bold px-2.5 py-1 rounded-full bg-indigo-100 text-indigo-800 uppercase">{pr['statut']}</span>
                </div>
                <p class="text-xs text-slate-600 mb-3 leading-relaxed">{pr['description']}</p>
                <div class="text-xs text-slate-600 space-y-1.5 bg-white p-3 rounded-xl border border-slate-100">
                    <div><b>🎯 Objectifs :</b> {pr.get('objectifs', 'Non spécifié')}</div>
                    <div><b>📅 Planning :</b> {pr.get('chronologie', 'Non spécifié')}</div>
                    <div class="font-bold text-emerald-700">💰 Budget estimé : {formater_montant(pr['cout'])} CFA</div>
                </div>
            </div>
            """

        panorama_cards_html = ""
        for pano in all_panorama:
            adh_p = pano.get('adherents', {}) or {}
            auteur_nom = f"{adh_p.get('prenom', '')} {adh_p.get('nom', '')}" if adh_p else "Administration"
            photo_url = pano.get('photo_url', '')
            panorama_cards_html += f"""
            <div class="bg-white rounded-2xl overflow-hidden shadow-sm border border-slate-200 flex flex-col">
                <img src="{photo_url}" class="w-full h-44 object-cover bg-slate-100" onerror="this.onerror=null; this.src='https://via.placeholder.com/400x300?text=Image+Indisponible';">
                <div class="p-3 flex-1 flex flex-col justify-between">
                    <p class="text-xs font-semibold text-slate-800 mb-2">"{pano.get('legende', '')}"</p>
                    <span class="text-[10px] font-bold text-emerald-700 bg-emerald-50 px-2 py-0.5 rounded-full self-start">📸 Publié par {auteur_nom}</span>
                </div>
            </div>
            """

        finance_sections_html = ""
        if is_tresorier:
            options_adherents = "".join([f"<option value='{a['id']}' data-text='{a['prenom'].lower()} {a['nom'].lower()} {a['secteur'].lower()} {a['telephone']}'>{a['prenom']} {a['nom']} — Secteur: {a['secteur']} (Tél: {a['telephone']})</option>" for a in all_actifs if a['role'] != 'admin'])
            
            suivi_retards_html = ""
            for a in all_actifs:
                cotis_membre = [c['periode'] for c in all_cotisations if c['adherent_id'] == a['id'] and c.get('statut_paiement', 'valide') == 'valide']
                mois_manquants = [m for m in mois_12 if m not in cotis_membre]
                
                if not mois_manquants:
                    statut_ajour = "<span class='text-emerald-600 font-bold'>À jour</span>"
                else:
                    nb_retard = len(mois_manquants)
                    statut_ajour = f"<span class='text-red-600 font-bold'>Retard ({nb_retard} mois)</span>"

                suivi_retards_html += f"<li class='py-1.5 border-b border-slate-100 flex justify-between items-center text-sm'><span><b>{a['prenom']} {a['nom']}</b> <span class='text-xs text-slate-400'>({a['secteur']})</span></span> {statut_ajour}</li>"

            paiements_mobiles_admin = [c for c in all_cotisations if "mobile_" in str(c.get('mode_paiement', ''))]
            paiements_mobiles_rows = ""
            for pm in paiements_mobiles_admin:
                adh_pm = pm.get('adherents', {}) or {}
                date_paiement_fr = formater_date(pm.get('date_paiement', ''))
                montant_fmt = formater_montant(pm['montant'])
                mode_str = pm.get('mode_paiement', '')
                st_paiement = pm.get('statut_paiement', 'en_attente')

                if st_paiement != 'valide':
                    action_cell = f"""
                    <form action="/admin/valider-paiement-mobile" method="POST" class="inline">
                        <input type="hidden" name="user_id" value="{user['id']}">
                        <input type="hidden" name="paiement_id" value="{pm['id']}">
                        <button type="submit" class="bg-amber-600 hover:bg-amber-700 text-white px-3 py-1.5 rounded-lg text-xs font-bold shadow flex items-center gap-1">⏳ Vérifier & Valider</button>
                    </form>
                    """
                else:
                    action_cell = f"""
                    <span class="text-xs font-bold text-emerald-700 bg-emerald-100 px-2 py-0.5 rounded-full mr-2">Validé & Reçu</span>
                    <a href="/cotisation/recu-pdf/{pm['id']}" target="_blank" class="bg-blue-600 hover:bg-blue-700 text-white px-2.5 py-1 rounded text-xs font-bold">📄 Reçu PDF</a>
                    """

                paiements_mobiles_rows += f"""
                <tr class="hover:bg-slate-50 border-b border-slate-100 text-sm">
                    <td class="p-2.5 font-bold text-slate-900">{adh_pm.get('prenom','')} {adh_pm.get('nom','')}</td>
                    <td class="p-2.5 font-semibold text-blue-700 uppercase">{mode_str}</td>
                    <td class="p-2.5 font-bold text-emerald-700">{montant_fmt} CFA</td>
                    <td class="p-2.5 text-slate-600">{pm['periode']}</td>
                    <td class="p-2.5 text-slate-500 text-xs">{date_paiement_fr}</td>
                    <td class="p-2.5 text-right">{action_cell}</td>
                </tr>
                """

            aides_admin_html = ""
            for ai in all_aides:
                adh_aide = ai.get('adherents', {}) or {}
                st_aide = ai.get('statut_validation', 'en_attente')
                
                actions_aide = ""
                if st_aide == 'en_attente':
                    actions_aide = f"""
                    <form action="/admin/valider-aide" method="POST" class="inline-block">
                        <input type="hidden" name="user_id" value="{user['id']}"><input type="hidden" name="aide_id" value="{ai['id']}"><input type="hidden" name="statut_validation" value="approuve">
                        <button type="submit" class="bg-emerald-600 hover:bg-emerald-700 text-white px-2.5 py-1 rounded text-xs font-bold mr-1">Approuver</button>
                    </form>
                    <form action="/admin/valider-aide" method="POST" class="inline-block">
                        <input type="hidden" name="user_id" value="{user['id']}"><input type="hidden" name="aide_id" value="{ai['id']}"><input type="hidden" name="statut_validation" value="refuse">
                        <button type="submit" class="bg-red-600 hover:bg-red-700 text-white px-2.5 py-1 rounded text-xs font-bold">Refuser</button>
                    </form>
                    """
                else:
                    badge_col = "bg-emerald-100 text-emerald-800" if st_aide == 'approuve' else "bg-red-100 text-red-800"
                    actions_aide = f"<span class='text-xs font-bold px-2.5 py-1 rounded-full {badge_col}'>{st_aide.upper()}</span>"

                aides_admin_html += f"""
                <li class="py-2.5 border-b border-slate-100 flex flex-col sm:flex-row justify-between items-start sm:items-center text-sm gap-2">
                    <div>
                        <b>{adh_aide.get('prenom','')} {adh_aide.get('nom','')}</b> — <span class="text-xs text-slate-600">Motif : {ai['motif']}</span>
                        <div class="text-xs font-bold text-amber-700">Montant demandé : {formater_montant(ai['montant_demande'])} CFA</div>
                    </div>
                    <div>{actions_aide}</div>
                </li>
                """

            categories_dict = {}
            for d in all_decaissements:
                cat = d.get('categorie', 'Divers') or 'Divers'
                categories_dict[cat] = categories_dict.get(cat, 0) + d['montant']
            
            repartition_depenses_html = ""
            for cat, montant_cat in categories_dict.items():
                repartition_depenses_html += f"<li class='flex justify-between py-1 text-sm border-b border-slate-100'><span>{cat}</span><span class='font-bold text-red-600'>{formater_montant(montant_cat)} CFA</span></li>"

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
                                <div><label class="block text-xs font-bold text-slate-600 mb-1">Prénom</label><input type="text" name="prenom" value="{a['prenom']}" required class="w-full p-2 text-sm border rounded-lg bg-white"></div>
                                <div><label class="block text-xs font-bold text-slate-600 mb-1">Nom</label><input type="text" name="nom" value="{a['nom']}" required class="w-full p-2 text-sm border rounded-lg bg-white"></div>
                            </div>
                            <div class="grid grid-cols-2 gap-3">
                                <div><label class="block text-xs font-bold text-slate-600 mb-1">Téléphone (ID)</label><input type="text" name="telephone" value="{a['telephone']}" required class="w-full p-2 text-sm border rounded-lg bg-white"></div>
                                <div><label class="block text-xs font-bold text-slate-600 mb-1">Secteur</label><input type="text" name="secteur" value="{a['secteur']}" required class="w-full p-2 text-sm border rounded-lg bg-white"></div>
                            </div>
                            <button type="submit" class="w-full bg-emerald-600 hover:bg-emerald-700 text-white py-2 rounded-lg text-sm font-bold shadow">Enregistrer</button>
                        </form>
                        <form action="/admin/reset-password" method="POST" class="pt-4 border-t border-slate-200 space-y-3">
                            <input type="hidden" name="user_id" value="{user['id']}">
                            <input type="hidden" name="adherent_id" value="{a['id']}">
                            <div><label class="block text-xs font-bold text-amber-700 mb-1">Réinitialiser le mot de passe</label><input type="text" name="nouveau_mdp" placeholder="Nouveau mot de passe" required class="w-full p-2 text-sm border rounded-lg bg-white mb-2"></div>
                            <button type="submit" class="w-full bg-amber-600 hover:bg-amber-700 text-white py-2 rounded-lg text-sm font-bold shadow">Mettre à jour le mot de passe</button>
                        </form>
                    </div>
                </div>
                """

            presences_table_rows = ""
            for p in all_presences:
                adh = p.get('adherents', {}) or {}
                st_pres = p.get('statut_presence', 'Present')
                date_reunion_fr = formater_date(p.get('date_reunion', ''))
                badge_color = "bg-emerald-100 text-emerald-800" if st_pres == 'Present' else ("bg-amber-100 text-amber-800" if "excuse" in st_pres else "bg-red-100 text-red-800")
                presences_table_rows += f"""
                <tr class="presence-row hover:bg-slate-50 border-b border-slate-100 text-sm" data-search="{adh.get('prenom','').lower()} {adh.get('nom','').lower()} {p.get('evenement_titre','').lower()}">
                    <td class="p-2.5 font-bold text-slate-900">{adh.get('prenom','')} {adh.get('nom','')}</td>
                    <td class="p-2.5 text-slate-600">{p.get('evenement_titre','')}</td>
                    <td class="p-2.5 text-slate-500 text-xs">{date_reunion_fr}</td>
                    <td class="p-2.5"><span class="text-xs px-2.5 py-1 rounded-full font-bold {badge_color}">{st_pres}</span></td>
                </tr>
                """

            options_presence_adherents = "".join([f"<option value='{a['id']}' data-text='{a['prenom'].lower()} {a['nom'].lower()} {a['secteur'].lower()}'>{a['prenom']} {a['nom']} — {a['secteur']}</option>" for a in all_actifs])
            options_evenements_titres = "".join([f"<option value='{ev['titre']}'>{ev['titre']} ({formater_date(ev['date_evenement'])})</option>" for ev in all_evenements]) or "<option value='Réunion Générale'>Réunion Générale</option>"

            solde_initial_fmt = formater_montant(solde_initial)
            solde_fmt = formater_montant(solde)

            finance_sections_html = f"""
            <div class="flex flex-wrap gap-2 mb-6 border-b border-slate-200 pb-3">
                <button onclick="switchTab('tab-tresorerie')" id="btn-tab-tresorerie" class="tab-btn px-4 py-2 text-xs font-bold rounded-xl bg-slate-900 text-white shadow-md transition">💼 Trésorerie & Caisse</button>
                <button onclick="switchTab('tab-adherents')" id="btn-tab-adherents" class="tab-btn px-4 py-2 text-xs font-bold rounded-xl bg-white text-slate-700 border border-slate-200 shadow-sm transition">👥 Annuaire & Membres</button>
                <button onclick="switchTab('tab-pointage')" id="btn-tab-pointage" class="tab-btn px-4 py-2 text-xs font-bold rounded-xl bg-white text-slate-700 border border-slate-200 shadow-sm transition">📋 Planification & Pointage</button>
                <button onclick="switchTab('tab-projets')" id="btn-tab-projets" class="tab-btn px-4 py-2 text-xs font-bold rounded-xl bg-white text-slate-700 border border-slate-200 shadow-sm transition">🚀 Projets & Aides</button>
                <button onclick="switchTab('tab-panorama')" id="btn-tab-panorama" class="tab-btn px-4 py-2 text-xs font-bold rounded-xl bg-white text-slate-700 border border-slate-200 shadow-sm transition">🌍 Panorama Village (Admin)</button>
                <button onclick="switchTab('tab-profil')" id="btn-tab-profil" class="tab-btn px-4 py-2 text-xs font-bold rounded-xl bg-white text-slate-700 border border-slate-200 shadow-sm transition">🖼️ Mon Profil</button>
            </div>

            <!-- ONGLET 1 : TRÉSORIER & CAISSE -->
            <div id="tab-tresorerie" class="tab-content space-y-6">
                <div class="bg-white p-6 rounded-2xl shadow-sm border border-slate-200">
                    <h2 class="text-base font-bold text-slate-900 mb-4 border-b pb-2 flex items-center gap-2">💼 Gestion du Solde Initial & Trésorerie</h2>
                    
                    <form action="/admin/maj-solde-initial" method="POST" class="bg-emerald-50 p-4 rounded-xl border border-emerald-100 mb-6 flex flex-col sm:flex-row gap-3 items-end">
                        <input type="hidden" name="user_id" value="{user['id']}">
                        <div class="w-full sm:flex-1">
                            <label class="block text-xs font-bold text-emerald-800 mb-1">Montant total compté en caisse (Solde Initial Réel)</label>
                            <input type="number" name="solde_initial" value="{solde_initial}" required class="w-full p-2.5 text-sm bg-white border border-emerald-300 rounded-lg">
                        </div>
                        <button type="submit" class="w-full sm:w-auto bg-emerald-600 hover:bg-emerald-700 text-white font-bold py-2.5 px-5 rounded-lg text-sm shadow">Mettre à jour</button>
                    </form>

                    <div class="grid grid-cols-1 sm:grid-cols-3 gap-4 mb-4 text-center">
                        <div class="bg-slate-50 p-3 rounded-xl border border-slate-200"><span class="block text-xs text-slate-500 font-bold uppercase">Solde Initial</span><span class="text-base font-extrabold text-slate-800">{solde_initial_fmt} CFA</span></div>
                        <div class="bg-emerald-50 p-3 rounded-xl border border-emerald-100"><span class="block text-xs text-emerald-600 font-bold uppercase">Cotisations Validées</span><span class="text-base font-extrabold text-emerald-800">{formater_montant(cotisations_caisse)} CFA</span></div>
                        <div class="bg-red-50 p-3 rounded-xl border border-red-100"><span class="block text-xs text-red-600 font-bold uppercase">Dépenses & Aides</span><span class="text-base font-extrabold text-red-800">{formater_montant(total_aides_approuvees + total_dec)} CFA</span></div>
                    </div>
                    <div class="text-center bg-slate-900 text-white py-3 rounded-xl font-bold text-base mb-6">Solde Réel en Caisse : <span class="text-emerald-400">{solde_fmt} CFA</span></div>

                    <h3 class="text-xs font-bold text-slate-600 mb-2 uppercase tracking-wide">Répartition des Dépenses</h3>
                    <ul class="mb-6">{repartition_depenses_html or '<li class="text-sm text-slate-400">Aucune dépense.</li>'}</ul>

                    <h3 class="text-xs font-bold text-slate-600 mb-2 uppercase tracking-wide">État des cotisations membres</h3>
                    <ul class="max-h-60 overflow-y-auto pr-2">{suivi_retards_html}</ul>
                </div>

                <div class="bg-white p-6 rounded-2xl shadow-sm border border-slate-200">
                    <h2 class="text-base font-bold text-slate-900 mb-2 border-b pb-2">📱 Vérification & Validation des Paiements Mobile Money</h2>
                    <p class="text-xs text-slate-500 mb-4">Vérifiez l'arrivée effective des fonds sur votre compte Wave ou Orange Money avant de valider pour alimenter la caisse.</p>
                    <div class="overflow-x-auto max-h-60 overflow-y-auto border border-slate-200 rounded-xl">
                        <table class="w-full text-left border-collapse bg-white">
                            <thead class="bg-slate-100 text-slate-600 text-xs uppercase sticky top-0 z-10">
                                <tr><th class="p-2.5">Adhérent</th><th class="p-2.5">Détails & Référence</th><th class="p-2.5">Montant</th><th class="p-2.5">Période</th><th class="p-2.5">Date</th><th class="p-2.5 text-right">Statut / Action</th></tr>
                            </thead>
                            <tbody>{paiements_mobiles_rows or '<tr><td colspan="6" class="p-4 text-center text-sm text-slate-400">Aucun paiement mobile initié pour le moment.</td></tr>'}</tbody>
                        </table>
                    </div>
                </div>

                <div class="bg-white p-6 rounded-2xl shadow-sm border border-slate-200">
                    <h2 class="text-base font-bold text-slate-900 mb-4 border-b pb-2">➕ Enregistrer une Cotisation ou Régularisation</h2>
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
                        <button type="submit" class="w-full bg-purple-600 hover:bg-purple-700 text-white font-bold py-2.5 rounded-lg text-sm shadow">Valider l'enregistrement</button>
                    </form>
                </div>

                <div class="bg-white p-6 rounded-2xl shadow-sm border border-slate-200">
                    <h2 class="text-base font-bold text-slate-900 mb-4 border-b pb-2">💸 Enregistrer un Décaissement (Sortie d'argent)</h2>
                    <form action="/decaissements-form" method="POST" class="space-y-3">
                        <input type="hidden" name="user_id" value="{user['id']}">
                        <div class="grid grid-cols-1 sm:grid-cols-3 gap-3">
                            <div><label class="block text-xs font-bold text-slate-600 mb-1">Motif de la dépense</label><input type="text" name="motif" required class="w-full p-2 text-sm border rounded-lg"></div>
                            <div><label class="block text-xs font-bold text-slate-600 mb-1">Montant (CFA)</label><input type="number" name="montant" required class="w-full p-2 text-sm border rounded-lg"></div>
                            <div><label class="block text-xs font-bold text-slate-600 mb-1">Bénéficiaire</label><input type="text" name="beneficiaire" required class="w-full p-2 text-sm border rounded-lg"></div>
                        </div>
                        <div>
                            <label class="block text-xs font-bold text-slate-600 mb-1">Catégorie</label>
                            <select name="categorie" required class="w-full p-2 text-sm border rounded-lg bg-white">
                                <option value="Daara">Daara (École coranique)</option>
                                <option value="Social">Social / Aide humanitaire</option>
                                <option value="Logistique">Logistique & Fonctionnement</option>
                                <option value="Divers">Divers</option>
                            </select>
                        </div>
                        <button type="submit" class="w-full bg-red-600 hover:bg-red-700 text-white font-bold py-2 rounded-lg text-sm shadow">Enregistrer la sortie</button>
                    </form>
                </div>
            </div>

            <!-- ONGLET 2 : ANNUAIRE & MEMBRES -->
            <div id="tab-adherents" class="tab-content hidden space-y-6">
                <div class="bg-white p-6 rounded-2xl shadow-sm border border-slate-200">
                    <div class="flex flex-col sm:flex-row justify-between items-center mb-4 border-b pb-2 gap-2">
                        <div>
                            <h2 class="text-base font-bold text-slate-900">👥 Annuaire des Adhérents ({len(all_adherents)})</h2>
                        </div>
                        <div class="flex items-center gap-2">
                            <a href="/adherents/export-pdf" target="_blank" class="bg-red-600 hover:bg-red-700 text-white px-3 py-1.5 rounded-lg text-xs font-bold shadow flex items-center gap-1">📄 Exporter PDF</a>
                            <input type="text" id="searchAdherent" placeholder="🔍 Rechercher..." onkeyup="filtrerAdherents()" class="p-2 text-xs border rounded-lg bg-slate-50 w-48">
                        </div>
                    </div>
                    <div class="overflow-x-auto max-h-[450px] overflow-y-auto border border-slate-200 rounded-xl">
                        <table class="w-full text-left border-collapse bg-white">
                            <thead class="bg-slate-100 text-slate-600 text-xs uppercase sticky top-0 z-10">
                                <tr><th class="p-2.5">Nom & Prénom</th><th class="p-2.5">Rôle</th><th class="p-2.5">Secteur</th><th class="p-2.5">Téléphone</th><th class="p-2.5">Statut</th><th class="p-2.5 text-right">Actions</th></tr>
                            </thead>
                            <tbody id="adherentsTableBody">{adherents_table_rows}</tbody>
                        </table>
                    </div>
                </div>
            </div>

            <!-- ONGLET 3 : PLANIFICATION & POINTAGE -->
            <div id="tab-pointage" class="tab-content hidden space-y-6">
                <div class="bg-white p-6 rounded-2xl shadow-sm border border-slate-200">
                    <h2 class="text-base font-bold text-slate-900 mb-4 border-b pb-2">📅 Planifier un Événement ou une Réunion</h2>
                    <form action="/evenements-form" method="POST" class="space-y-3">
                        <input type="hidden" name="user_id" value="{user['id']}">
                        <div class="grid grid-cols-1 sm:grid-cols-2 gap-3">
                            <div><label class="block text-xs font-bold text-slate-600 mb-1">Titre de l'événement</label><input type="text" name="titre" required class="w-full p-2 text-sm border rounded-lg"></div>
                            <div><label class="block text-xs font-bold text-slate-600 mb-1">Date</label><input type="date" name="date_evenement" required class="w-full p-2 text-sm border rounded-lg"></div>
                        </div>
                        <div class="grid grid-cols-1 sm:grid-cols-3 gap-3">
                            <div><label class="block text-xs font-bold text-slate-600 mb-1">Lieu</label><input type="text" name="lieu" required class="w-full p-2 text-sm border rounded-lg"></div>
                            <div><label class="block text-xs font-bold text-slate-600 mb-1">Type</label><input type="text" name="type_evenement" placeholder="ex: Réunion, Assemblée..." required class="w-full p-2 text-sm border rounded-lg"></div>
                            <div><label class="block text-xs font-bold text-slate-600 mb-1">Statut</label><select name="statut" class="w-full p-2 text-sm border rounded-lg"><option value="Prevu">Prévu</option><option value="En cours">En cours</option><option value="Termine">Terminé</option></select></div>
                        </div>
                        <div><label class="block text-xs font-bold text-slate-600 mb-1">Description</label><textarea name="description" rows="2" class="w-full p-2 text-sm border rounded-lg"></textarea></div>
                        <button type="submit" class="w-full bg-blue-600 hover:bg-blue-700 text-white font-bold py-2 rounded-lg text-sm shadow">Enregistrer l'événement</button>
                    </form>
                </div>

                <div class="bg-white p-6 rounded-2xl shadow-sm border border-slate-200">
                    <div class="flex flex-col sm:flex-row justify-between items-start sm:items-center mb-4 border-b pb-2 gap-2">
                        <h2 class="text-base font-bold text-slate-900">📋 Pointage & Scanner QR Code</h2>
                        <button type="button" onclick="toggleScanner()" class="bg-teal-600 hover:bg-teal-700 text-white px-3 py-2 rounded-lg text-xs font-bold flex items-center gap-1.5 shadow">📷 Ouvrir / Fermer le Scanner Caméra</button>
                    </div>

                    <div id="scanner-container" class="hidden mb-6 p-4 bg-slate-900 rounded-2xl text-center">
                        <p class="text-xs text-emerald-400 font-bold mb-2">Pointez la caméra vers le QR Code de la carte du membre</p>
                        <div id="reader" class="mx-auto max-w-sm rounded-xl overflow-hidden bg-black"></div>
                        <p id="scan-result" class="text-xs text-white mt-3 font-mono"></p>
                    </div>

                    <form action="/presences-form" method="POST" class="space-y-4">
                        <input type="hidden" name="user_id" value="{user['id']}">
                        <div class="grid grid-cols-1 sm:grid-cols-2 gap-3">
                            <div>
                                <label class="block text-xs font-bold text-slate-600 mb-1">Événement / Réunion</label>
                                <select name="evenement_titre" required class="w-full p-2.5 border rounded-lg text-sm bg-white">{options_evenements_titres}</select>
                            </div>
                            <div>
                                <label class="block text-xs font-bold text-slate-600 mb-1">Date</label>
                                <input type="date" name="date_reunion" required class="w-full p-2.5 border rounded-lg text-sm bg-white">
                            </div>
                        </div>
                        <div>
                            <label class="block text-xs font-bold text-slate-600 mb-1">Membre (ou scanné par QR Code)</label>
                            <input type="text" id="searchSelectPresence" placeholder="🔍 Filtrer le membre..." onkeyup="filtrerSelectPresence()" class="w-full p-2.5 mb-2 border rounded-lg text-sm bg-slate-50">
                            <select name="adherent_id" id="selectPresenceAdherent" required class="w-full p-2.5 border rounded-lg text-sm bg-white" size="4">
                                <option value="">-- Choisir un membre --</option>
                                {options_presence_adherents}
                            </select>
                        </div>
                        <div>
                            <label class="block text-xs font-bold text-slate-600 mb-1">Statut</label>
                            <select name="statut_presence" required class="w-full p-2.5 border rounded-lg text-sm bg-white">
                                <option value="Present">🟢 Présent(e)</option>
                                <option value="Absent_excuse">🟡 Absent(e) excusé(e)</option>
                                <option value="Absent_non_excuse">🔴 Absent(e) non excusé(e)</option>
                            </select>
                        </div>
                        <button type="submit" class="w-full bg-teal-600 hover:bg-teal-700 text-white font-bold py-2.5 rounded-lg text-sm shadow">Enregistrer le pointage</button>
                    </form>
                </div>
            </div>

            <!-- ONGLET 4 : PROJETS & AIDES -->
            <div id="tab-projets" class="tab-content hidden space-y-6">
                <div class="bg-white p-6 rounded-2xl shadow-sm border border-slate-200">
                    <h2 class="text-base font-bold text-slate-900 mb-4 border-b pb-2">🤝 Demandes d'Aide Communautaire (Validation)</h2>
                    <ul class="max-h-60 overflow-y-auto">{aides_admin_html or '<li class="text-sm text-slate-400">Aucune demande d\'aide en attente.</li>'}</ul>
                </div>

                <div class="bg-white p-6 rounded-2xl shadow-sm border border-slate-200">
                    <h2 class="text-base font-bold text-slate-900 mb-4 border-b pb-2">🚀 Ajouter un Projet (Daara & Communauté)</h2>
                    <form action="/projets-form" method="POST" enctype="multipart/form-data" class="space-y-3 mb-6">
                        <input type="hidden" name="user_id" value="{user['id']}">
                        <div class="grid grid-cols-1 sm:grid-cols-2 gap-3">
                            <div><label class="block text-xs font-bold text-slate-600 mb-1">Titre du projet</label><input type="text" name="titre" required class="w-full p-2 text-sm border rounded-lg"></div>
                            <div><label class="block text-xs font-bold text-slate-600 mb-1">Coût estimé (CFA)</label><input type="number" name="cout" required class="w-full p-2 text-sm border rounded-lg"></div>
                        </div>
                        <div><label class="block text-xs font-bold text-slate-600 mb-1">Description</label><textarea name="description" rows="2" required class="w-full p-2 text-sm border rounded-lg"></textarea></div>
                        <div class="grid grid-cols-1 sm:grid-cols-3 gap-3">
                            <div><label class="block text-xs font-bold text-slate-600 mb-1">Objectifs</label><input type="text" name="objectifs" required class="w-full p-2 text-sm border rounded-lg"></div>
                            <div><label class="block text-xs font-bold text-slate-600 mb-1">Chronologie / Planning</label><input type="text" name="chronologie" placeholder="ex: Octobre - Décembre" required class="w-full p-2 text-sm border rounded-lg"></div>
                            <div><label class="block text-xs font-bold text-slate-600 mb-1">Statut</label><select name="statut" class="w-full p-2 text-sm border rounded-lg"><option value="En cours">En cours</option><option value="Planifie">Planifié</option><option value="Termine">Terminé</option></select></div>
                        </div>
                        <div><label class="block text-xs font-bold text-slate-600 mb-1">Photo / Illustration du projet</label><input type="file" name="file_projet" accept="image/*" class="w-full text-xs text-slate-500 file:py-1.5 file:px-3 file:rounded-lg file:border-0 file:bg-indigo-50 file:text-indigo-700"></div>
                        <button type="submit" class="w-full bg-indigo-600 hover:bg-indigo-700 text-white font-bold py-2 rounded-lg text-sm shadow">Enregistrer le projet</button>
                    </form>

                    <h3 class="text-xs font-bold text-slate-700 mb-3 border-t pt-4 uppercase">Projets enregistrés</h3>
                    <div class="max-h-96 overflow-y-auto">
                        {projets_cards_html or '<p class="text-xs text-slate-400">Aucun projet enregistré pour le moment.</p>'}
                    </div>
                </div>
            </div>

            <!-- ONGLET 5 : PANORAMA VILLAGE (ADMIN / TRÉSORIER SEULEMENT) -->
            <div id="tab-panorama" class="tab-content hidden space-y-6">
                <div class="bg-white p-6 rounded-2xl shadow-sm border border-slate-200">
                    <h2 class="text-base font-bold text-slate-900 mb-4 border-b pb-2">🌍 Ajouter des Photos au Panorama (Réservé Admin)</h2>
                    <form action="/panorama-form" method="POST" enctype="multipart/form-data" class="space-y-3 mb-6">
                        <input type="hidden" name="user_id" value="{user['id']}">
                        <div>
                            <label class="block text-xs font-bold text-slate-600 mb-1">Légende globale des photos</label>
                            <input type="text" name="legende" placeholder="ex: Célébration au village..." required class="w-full p-2.5 text-sm border rounded-lg">
                        </div>
                        <div>
                            <label class="block text-xs font-bold text-slate-600 mb-1">Sélectionner plusieurs photos (Maintenez Ctrl ou Cmd)</label>
                            <input type="file" name="files_photos" accept="image/*" multiple required class="w-full text-xs text-slate-500 file:py-2 file:px-3 file:rounded-lg file:border-0 file:bg-emerald-50 file:text-emerald-700">
                        </div>
                        <button type="submit" class="w-full bg-emerald-600 hover:bg-emerald-700 text-white font-bold py-2.5 rounded-lg text-sm shadow">Publier la sélection dans le Panorama</button>
                    </form>
                </div>
            </div>

            <!-- ONGLET 6 : MON PROFIL -->
            <div id="tab-profil" class="tab-content hidden space-y-6">
                <div class="bg-white p-6 rounded-2xl shadow-sm border border-slate-200">
                    <h2 class="text-base font-bold text-slate-900 mb-4 border-b pb-2">🖼️ Modifier ma Photo de Profil</h2>
                    <form action="/modifier-photo" method="POST" enctype="multipart/form-data" class="space-y-3">
                        <input type="hidden" name="user_id" value="{user['id']}">
                        <div>
                            <label class="block text-xs font-bold text-slate-600 mb-1">Choisir une nouvelle photo</label>
                            <input type="file" name="file_photo" accept="image/*" required class="w-full text-xs text-slate-500 file:py-2 file:px-3 file:rounded-lg file:border-0 file:bg-emerald-50 file:text-emerald-700">
                        </div>
                        <button type="submit" class="w-full bg-slate-800 hover:bg-slate-900 text-white font-bold py-2 rounded-lg text-sm shadow">Mettre à jour la photo</button>
                    </form>
                </div>
            </div>

            {modals_html}
            """

        member_sections_html = ""
        if not is_tresorier:
            cotis_perso = [c for c in all_cotisations if c['adherent_id'] == user['id']]
            
            mois_payes_html = ""
            for c in cotis_perso:
                st_p = c.get('statut_paiement', 'valide')
                if st_p == 'valide':
                    badge_etat = "<span class='text-emerald-600 font-bold'>Payé & Validé</span>"
                    action_recu = f"<a href='/cotisation/recu-pdf/{c['id']}' target='_blank' class='bg-blue-600 text-white px-2.5 py-1 rounded text-xs font-semibold'>Reçu PDF</a>"
                else:
                    badge_etat = "<span class='text-amber-600 font-bold'>En attente de vérification</span>"
                    action_recu = "<span class='text-xs text-slate-400 italic'>En cours</span>"

                mois_payes_html += f"""
                <li class='py-2 border-b border-slate-100 text-sm flex justify-between items-center'>
                    <span>Mois de <b>{c['periode']}</b> ({c['mode_paiement']}) : {badge_etat} ({formater_montant(c['montant'])} CFA)</span>
                    {action_recu}
                </li>
                """
            
            evenements_membre_html = "".join([f"<div class='p-3 bg-slate-50 rounded-xl border border-slate-100 mb-2'><h4 class='font-bold text-sm text-blue-900'>{ev['titre']}</h4><p class='text-xs text-slate-600'>{ev['description']}</p><div class='text-[10px] text-slate-400 mt-1'>📅 Date : {formater_date(ev['date_evenement'])} | 📍 Lieu : {ev['lieu']}</div></div>" for ev in all_evenements])

            photo_carte_tag = f"<img src='{user['photo_profil']}' class='w-20 h-20 rounded-xl object-cover border-2 border-white/20 shadow' onerror='this.style.display=\"none\"'>" if user['photo_profil'] else "<div class='w-20 h-20 rounded-xl bg-white/10 flex items-center justify-center font-bold text-white text-xl border-2 border-white/20'>" + user['prenom'][0] + "</div>"

            member_sections_html = f"""
            <div class="bg-gradient-to-br from-slate-900 to-emerald-950 text-white p-6 rounded-3xl shadow-xl mb-6">
                <div class="flex justify-between items-start gap-4">
                    <div>
                        <span class="bg-emerald-500/20 text-emerald-400 text-[10px] font-bold px-2.5 py-1 rounded-full uppercase tracking-wider border border-emerald-500/30">Carte Officielle</span>
                        <h2 class="text-xl font-black mt-2">{user['prenom']} {user['nom']}</h2>
                        <p class="text-xs text-slate-300 mt-0.5">Secteur : {user['secteur']} | Tél : {user['telephone']}</p>
                    </div>
                    <div>{photo_carte_tag}</div>
                </div>
                <div class="bg-white p-3 rounded-xl inline-block mt-4 text-center">
                    <img src="data:image/png;base64,{qr_perso_b64}" alt="QR Code" class="w-24 h-24 rounded">
                    <span class="block text-[9px] font-bold text-slate-700 mt-1 uppercase">ID: {user['id']}</span>
                </div>
            </div>

            <div class="bg-white p-6 rounded-2xl shadow-sm border border-slate-200 mb-6">
                <h2 class="text-base font-bold text-slate-900 mb-4 border-b pb-2">🖼️ Modifier ma Photo de Profil</h2>
                <form action="/modifier-photo" method="POST" enctype="multipart/form-data" class="space-y-3">
                    <input type="hidden" name="user_id" value="{user['id']}">
                    <div>
                        <label class="block text-xs font-bold text-slate-600 mb-1">Choisir une nouvelle photo</label>
                        <input type="file" name="file_photo" accept="image/*" required class="w-full text-xs text-slate-500 file:py-2 file:px-3 file:rounded-lg file:border-0 file:bg-emerald-50 file:text-emerald-700">
                    </div>
                    <button type="submit" class="w-full bg-slate-800 hover:bg-slate-900 text-white font-bold py-2 rounded-lg text-sm shadow">Mettre à jour la photo</button>
                </form>
            </div>

            <div class="bg-white p-6 rounded-2xl shadow-sm border border-slate-200 mb-6">
                <h2 class="text-base font-bold text-slate-900 mb-4 border-b pb-2">📱 Déclarer un Paiement Mobile (Wave / Orange Money)</h2>
                <form action="/paiement-mobile-form" method="POST" class="space-y-3">
                    <input type="hidden" name="user_id" value="{user['id']}">
                    <div class="grid grid-cols-1 sm:grid-cols-3 gap-3">
                        <div>
                            <label class="block text-xs font-bold text-slate-600 mb-1">Opérateur</label>
                            <select name="operateur" required class="w-full p-2 text-sm border rounded-lg bg-white">
                                <option value="Wave">🌊 Wave</option>
                                <option value="OrangeMoney">🟠 Orange Money</option>
                            </select>
                        </div>
                        <div>
                            <label class="block text-xs font-bold text-slate-600 mb-1">Votre N° de téléphone payeur</label>
                            <input type="text" name="telephone_paiement" value="{user['telephone']}" required class="w-full p-2 text-sm border rounded-lg">
                        </div>
                        <div>
                            <label class="block text-xs font-bold text-slate-600 mb-1">N° du Trésorier récepteur</label>
                            <input type="text" name="numero_recepteur" placeholder="ex: 221770000000" required class="w-full p-2 text-sm border rounded-lg">
                        </div>
                    </div>
                    <div class="grid grid-cols-1 sm:grid-cols-3 gap-3">
                        <div><label class="block text-xs font-bold text-slate-600 mb-1">Référence Transaction</label><input type="text" name="reference_transaction" placeholder="ex: WV-12345678" required class="w-full p-2 text-sm border rounded-lg"></div>
                        <div><label class="block text-xs font-bold text-slate-600 mb-1">Montant (CFA)</label><input type="number" name="montant" required class="w-full p-2 text-sm border rounded-lg"></div>
                        <div><label class="block text-xs font-bold text-slate-600 mb-1">Période concernée</label><input type="text" name="periode" placeholder="ex: 2026-09" required class="w-full p-2 text-sm border rounded-lg"></div>
                    </div>
                    <button type="submit" class="w-full bg-blue-600 hover:bg-blue-700 text-white font-bold py-2.5 rounded-lg text-sm shadow">Déclarer & Soumettre le paiement</button>
                </form>
            </div>

            <div class="bg-white p-6 rounded-2xl shadow-sm border border-slate-200 mb-6">
                <h2 class="text-base font-bold text-slate-900 mb-4 border-b pb-2">📋 Mon Suivi de Cotisations</h2>
                <ul class="max-h-60 overflow-y-auto">{mois_payes_html or '<li class="text-sm text-slate-400">Aucun versement.</li>'}</ul>
            </div>

            <div class="bg-white p-6 rounded-2xl shadow-sm border border-slate-200 mb-6">
                <h2 class="text-base font-bold text-slate-900 mb-4 border-b pb-2">📅 Événements & Réunions à venir</h2>
                <div class="max-h-60 overflow-y-auto">{evenements_membre_html or '<p class="text-xs text-slate-400">Aucune réunion ou événement planifié pour le moment.</p>'}</div>
            </div>

            <div class="bg-white p-6 rounded-2xl shadow-sm border border-slate-200 mb-6">
                <h2 class="text-base font-bold text-slate-900 mb-4 border-b pb-2">🚀 Projets du Daara & de l'Association</h2>
                <div class="max-h-96 overflow-y-auto">
                    {projets_cards_html or '<p class="text-xs text-slate-400">Aucun projet enregistré pour le moment.</p>'}
                </div>
            </div>

            <div class="bg-white p-6 rounded-2xl shadow-sm border border-slate-200 mb-6">
                <h2 class="text-base font-bold text-slate-900 mb-4 border-b pb-2">🤝 Demander une Aide Communautaire</h2>
                <form action="/aides-form" method="POST" class="space-y-3">
                    <input type="hidden" name="user_id" value="{user['id']}">
                    <div><label class="block text-xs font-bold text-slate-600 mb-1">Motif de la demande</label><input type="text" name="motif" required class="w-full p-2 text-sm border rounded-lg"></div>
                    <div><label class="block text-xs font-bold text-slate-600 mb-1">Montant demandé (CFA)</label><input type="number" name="montant_demande" required class="w-full p-2 text-sm border rounded-lg"></div>
                    <button type="submit" class="w-full bg-amber-600 hover:bg-amber-700 text-white font-bold py-2 rounded-lg text-sm shadow">Envoyer la demande</button>
                </form>
            </div>
            """

        user_photo = f"<img src='{user['photo_profil']}' class='w-16 h-16 rounded-full object-cover shadow-sm' onerror='this.style.display=\"none\"'>" if user['photo_profil'] else "<div class='w-16 h-16 rounded-full bg-slate-200 flex items-center justify-center font-bold text-slate-500 text-xl'>" + user['prenom'][0] + "</div>"

        return f"""
        <!DOCTYPE html>
        <html lang="fr">
        <head>
            <meta charset="UTF-8">
            <meta name="viewport" content="width=device-width, initial-scale=1.0">
            <title>Dashboard - Tinka</title>
            <script src="https://cdn.tailwindcss.com"></script>
            <script src="https://unpkg.com/html5-qrcode" type="text/javascript"></script>
            <script>
                let html5QrCode = null;
                function toggleScanner() {{
                    let container = document.getElementById('scanner-container');
                    if (container.classList.contains('hidden')) {{
                        container.classList.remove('hidden');
                        if (!html5QrCode) html5QrCode = new Html5Qrcode("reader");
                        html5QrCode.start({{ facingMode: "environment" }}, {{ fps: 10, qrbox: {{ width: 250, height: 250 }} }}, (decodedText) => {{
                            let urlParams = new URLSearchParams(decodedText.split('?')[1]);
                            let scannedId = urlParams.get('id');
                            if (scannedId) {{
                                document.getElementById('selectPresenceAdherent').value = scannedId;
                                toggleScanner();
                            }}
                        }});
                    }} else {{
                        container.classList.add('hidden');
                        if (html5QrCode && html5QrCode.isScanning) html5QrCode.stop();
                    }}
                }}
                function switchTab(tabId) {{
                    let contents = document.getElementsByClassName('tab-content');
                    for (let c of contents) c.classList.add('hidden');
                    document.getElementById(tabId).classList.remove('hidden');

                    let buttons = document.getElementsByClassName('tab-btn');
                    for (let b of buttons) {{
                        b.classList.remove('bg-slate-900', 'text-white', 'shadow-md');
                        b.classList.add('bg-white', 'text-slate-700', 'border', 'border-slate-200', 'shadow-sm');
                    }}
                    let activeBtn = document.getElementById('btn-' + tabId);
                    if (activeBtn) {{
                        activeBtn.classList.remove('bg-white', 'text-slate-700', 'border', 'border-slate-200', 'shadow-sm');
                        activeBtn.classList.add('bg-slate-900', 'text-white', 'shadow-md');
                    }}
                }}
                function openModal(id) {{ document.getElementById('modal-' + id).classList.remove('hidden'); }}
                function closeModal(id) {{ document.getElementById('modal-' + id).classList.add('hidden'); }}
                function filtrerAdherents() {{
                    let input = document.getElementById('searchAdherent').value.toLowerCase();
                    let rows = document.getElementsByClassName('adherent-row');
                    for (let r of rows) r.style.display = r.getAttribute('data-search').includes(input) ? "" : "none";
                }}
                function filtrerSelectPresence() {{
                    let input = document.getElementById('searchSelectPresence').value.toLowerCase();
                    let opts = document.getElementById('selectPresenceAdherent').getElementsByTagName('option');
                    for (let i = 1; i < opts.length; i++) opts[i].style.display = opts[i].getAttribute('data-text').includes(input) ? "" : "none";
                }}
            </script>
        </head>
        <body class="bg-slate-50 text-slate-800 font-sans antialiased min-h-screen py-6 px-4">
            <div class="max-w-4xl mx-auto">
                <div class="bg-white p-6 rounded-2xl shadow-sm border border-slate-200 mb-6 flex justify-between items-center">
                    <div class="flex items-center gap-4">
                        {user_photo}
                        <div>
                            <h2 class="text-base font-bold text-slate-900">{user['prenom']} {user['nom']}</h2>
                            <p class="text-xs text-slate-500">Rôle : <span class="font-bold text-blue-600 uppercase">{user['role']}</span></p>
                        </div>
                    </div>
                    <a href="/" class="bg-red-600 hover:bg-red-700 text-white px-4 py-2 rounded-lg text-xs font-bold">Déconnexion</a>
                </div>
                {finance_sections_html}
                {member_sections_html}

                <!-- PANORAMA DU VILLAGE (FOOTER VISIBLE PAR TOUS EN MODE CONTEMPLATION) -->
                <div class="bg-white p-6 rounded-3xl shadow-sm border border-slate-200 mt-8">
                    <h3 class="text-center text-base font-black text-slate-900 mb-1">🌍 Souvenirs & Panorama du Village</h3>
                    <p class="text-center text-xs text-slate-500 mb-6">Contemplez les magnifiques photos du village partagées par l'administration.</p>
                    <div class="grid grid-cols-1 sm:grid-cols-2 md:grid-cols-3 gap-4">
                        {panorama_cards_html or '<p class="col-span-3 text-center text-xs text-slate-400">Aucune photo de panorama publiée pour le moment.</p>'}
                    </div>
                </div>
            </div>
        </body>
        </html>
        """
    except Exception as e:
        return HTMLResponse(content=f"<h3>Erreur :</h3><p>{str(e)}</p><a href='/'>Retour</a>", status_code=500)

if __name__ == "__main__":
    uvicorn.run("app_asso:app", host="127.0.0.1", port=8000, reload=True)
