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

app = FastAPI(title="API Gestion Tinka ka Mein Haaldi fotti", version="68.0")

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

def normaliser_telephone(tel: str) -> str:
    if not tel:
        return ""
    nettoye = "".join([c for c in tel if c.isdigit()])
    for indicatif in ["221", "224", "223", "225", "33"]:
        if nettoye.startswith(indicatif) and len(nettoye) > 9:
            nettoye = nettoye[len(indicatif):]
            break
    return nettoye

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

@app.get("/", response_class=HTMLResponse)
def afficher_portail():
    try:
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
        <body class="bg-gradient-to-br from-slate-50 via-slate-100 to-emerald-50 text-slate-800 font-sans antialiased min-h-screen py-8 px-4 flex flex-col justify-between">
            <div class="max-w-md mx-auto w-full bg-white/90 backdrop-blur-md rounded-3xl shadow-2xl p-6 sm:p-8 border border-slate-100">
                <div class="text-center mb-6">
                    <span class="inline-block bg-emerald-100 text-emerald-800 text-xs font-extrabold px-3.5 py-1 rounded-full uppercase tracking-wider mb-2 shadow-sm">Portail Officiel</span>
                    <h1 class="text-2xl font-black text-slate-900 tracking-tight">Tinka ka Mein Haaldi fotti</h1>
                    <p class="text-xs text-slate-500 mt-1 font-medium">Gestion administrative, financière & Daara</p>
                </div>
                <div class="flex justify-center mb-6">
                    <div class="bg-white p-3 rounded-2xl border-2 border-dashed border-emerald-200 shadow-sm text-center">
                        <img src="data:image/png;base64,{qr_b64}" alt="QR Code" class="w-28 h-28 mx-auto mb-2 rounded-xl">
                        <span class="text-[11px] font-bold text-slate-600">Scannez pour accéder au site</span>
                    </div>
                </div>
                <div class="space-y-6">
                    <div class="bg-slate-50/80 p-5 rounded-2xl border border-slate-200/80 shadow-inner">
                        <h2 class="text-sm font-extrabold text-slate-800 mb-3 flex items-center gap-2 uppercase tracking-wide">🔐 Connexion</h2>
                        <form action="/login-form" method="POST" class="space-y-3.5">
                            <div>
                                <label class="block text-[11px] font-bold uppercase tracking-wider text-slate-600 mb-1">Numéro de téléphone</label>
                                <input type="text" name="telephone" placeholder="ex: 771234567 ou 221771234567" required class="w-full px-3 py-2.5 text-sm bg-white border border-slate-300 rounded-xl focus:ring-2 focus:ring-emerald-500 focus:outline-none transition shadow-sm">
                            </div>
                            <div>
                                <label class="block text-[11px] font-bold uppercase tracking-wider text-slate-600 mb-1">Mot de passe</label>
                                <input type="password" name="mot_de_passe" required class="w-full px-3 py-2.5 text-sm bg-white border border-slate-300 rounded-xl focus:ring-2 focus:ring-emerald-500 focus:outline-none transition shadow-sm">
                            </div>
                            <button type="submit" class="w-full bg-blue-600 hover:bg-blue-700 text-white font-bold py-2.5 px-4 rounded-xl shadow-lg shadow-blue-600/20 transition duration-200 text-sm">Se connecter</button>
                        </form>
                    </div>
                    <div class="bg-slate-50/80 p-5 rounded-2xl border border-slate-200/80 shadow-inner">
                        <h2 class="text-sm font-extrabold text-emerald-800 mb-3 flex items-center gap-2 uppercase tracking-wide">📝 Nouvel Adhérent</h2>
                        <form action="/adherents-form" method="POST" enctype="multipart/form-data" class="space-y-3">
                            <div class="grid grid-cols-2 gap-2">
                                <div><label class="block text-[11px] font-bold text-slate-600 mb-1">Nom</label><input type="text" name="nom" required class="w-full px-2.5 py-2 text-sm bg-white border border-slate-300 rounded-xl shadow-sm"></div>
                                <div><label class="block text-[11px] font-bold text-slate-600 mb-1">Prénom</label><input type="text" name="prenom" required class="w-full px-2.5 py-2 text-sm bg-white border border-slate-300 rounded-xl shadow-sm"></div>
                            </div>
                            <div><label class="block text-[11px] font-bold text-slate-600 mb-1">Téléphone</label><input type="text" name="telephone" placeholder="ex: 776510244" required class="w-full px-2.5 py-2 text-sm bg-white border border-slate-300 rounded-xl shadow-sm"></div>
                            <div><label class="block text-[11px] font-bold text-slate-600 mb-1">Adresse</label><input type="text" name="adresse" required class="w-full px-2.5 py-2 text-sm bg-white border border-slate-300 rounded-xl shadow-sm"></div>
                            <div><label class="block text-[11px] font-bold text-slate-600 mb-1">Secteur</label><input type="text" name="secteur" required class="w-full px-2.5 py-2 text-sm bg-white border border-slate-300 rounded-xl shadow-sm"></div>
                            <div><label class="block text-[11px] font-bold text-slate-600 mb-1">Photo de profil</label><input type="file" name="file_photo" accept="image/*" class="w-full text-xs text-slate-500 file:py-2 file:px-3 file:rounded-xl file:border-0 file:bg-emerald-50 file:text-emerald-700 font-semibold"></div>
                            <div><label class="block text-[11px] font-bold text-slate-600 mb-1">Mot de passe</label><input type="password" name="mot_de_passe" required class="w-full px-2.5 py-2 text-sm bg-white border border-slate-300 rounded-xl shadow-sm"></div>
                            <button type="submit" class="w-full bg-emerald-600 hover:bg-emerald-700 text-white font-bold py-2.5 px-4 rounded-xl shadow-lg shadow-emerald-600/20 text-sm mt-1 transition duration-200">S'inscrire</button>
                        </form>
                    </div>
                </div>
            </div>
        </body>
        </html>
        """
    except Exception as e:
        return HTMLResponse(content=f"<h3>Erreur critique :</h3><p>{str(e)}</p>", status_code=500)

@app.api_route("/login-form", methods=["GET", "POST"], response_class=HTMLResponse)
@app.api_route("/login-form/", methods=["GET", "POST"], response_class=HTMLResponse)
def login_form(telephone: Optional[str] = Form(None), mot_de_passe: Optional[str] = Form(None)):
    if not telephone or not mot_de_passe:
        return RedirectResponse(url="/", status_code=303)
    try:
        tel_norm = normaliser_telephone(telephone)
        res = supabase.table("adherents").select("*").execute()
        users = res.data or []
        
        user = None
        for u in users:
            if normaliser_telephone(u.get('telephone', '')) == tel_norm:
                user = u
                break

        if not user:
            return HTMLResponse(content="<script>alert('Numéro de téléphone ou mot de passe incorrect.'); window.location.href='/';</script>", status_code=401)
        
        if not verifier_mdp(mot_de_passe, user['mot_de_passe']):
            return HTMLResponse(content="<script>alert('Numéro de téléphone ou mot de passe incorrect.'); window.location.href='/';</script>", status_code=401)
        
        if user.get('statut') != 'actif':
            return HTMLResponse(content="<script>alert('Votre compte est en attente de validation par l\\'administrateur.'); window.location.href='/';</script>", status_code=403)
        
        return RedirectResponse(url=f"/dashboard?id={user['id']}", status_code=status.HTTP_303_SEE_OTHER)
    except Exception as e:
        return HTMLResponse(content=f"<h3>Erreur de connexion Supabase :</h3><p>{str(e)}</p><a href='/'>Retour</a>", status_code=500)

@app.api_route("/adherents-form", methods=["GET", "POST"], response_class=HTMLResponse)
@app.api_route("/adherents-form/", methods=["GET", "POST"], response_class=HTMLResponse)
async def creer_adherent_form(
    nom: Optional[str] = Form(None), prenom: Optional[str] = Form(None), telephone: Optional[str] = Form(None),
    adresse: Optional[str] = Form(None), secteur: Optional[str] = Form(None),
    mot_de_passe: Optional[str] = Form(None), file_photo: UploadFile = File(None)
):
    if not telephone:
        return RedirectResponse(url="/", status_code=303)
    try:
        tel_norm = normaliser_telephone(telephone)
        
        res_all = supabase.table("adherents").select("telephone").execute()
        existing_users = res_all.data or []
        for eu in existing_users:
            if normaliser_telephone(eu.get('telephone', '')) == tel_norm:
                return HTMLResponse(content="<script>alert('Erreur : Ce numéro de téléphone est déjà associé à un compte existant.'); window.location.href='/';</script>")

        photo_b64 = await fichier_vers_base64(file_photo)
        mdp_securise = hacher_mdp(mot_de_passe or "123456")
        
        supabase.table("adherents").insert({
            "nom": nom or "", "prenom": prenom or "", "email": f"{tel_norm}@tinka.local", "telephone": tel_norm,
            "adresse": adresse or "", "secteur": secteur or "", "photo_profil": photo_b64, "mot_de_passe": mdp_securise
        }).execute()
        return HTMLResponse(content="<script>alert('Compte créé avec succès ! En attente de validation.'); window.location.href='/';</script>")
    except Exception as e:
        return HTMLResponse(content=f"<script>alert('Erreur lors de l\\'inscription : {str(e)}'); window.location.href='/';</script>")

@app.api_route("/admin/valider-adherent", methods=["GET", "POST"], response_class=HTMLResponse)
def valider_adherent(user_id: Optional[int] = Form(None), adherent_id: Optional[int] = Form(None)):
    if user_id and adherent_id:
        supabase.table("adherents").update({"statut": "actif"}).eq("id", adherent_id).execute()
        return RedirectResponse(url=f"/dashboard?id={user_id}", status_code=status.HTTP_303_SEE_OTHER)
    return RedirectResponse(url="/", status_code=303)

@app.api_route("/admin/changer-role", methods=["GET", "POST"], response_class=HTMLResponse)
def changer_role(user_id: Optional[int] = Form(None), adherent_id: Optional[int] = Form(None), nouveau_role: Optional[str] = Form(None)):
    if user_id and adherent_id and nouveau_role:
        supabase.table("adherents").update({"role": nouveau_role}).eq("id", adherent_id).execute()
        return RedirectResponse(url=f"/dashboard?id={user_id}", status_code=status.HTTP_303_SEE_OTHER)
    return RedirectResponse(url="/", status_code=303)

@app.api_route("/admin/modifier-adherent", methods=["GET", "POST"], response_class=HTMLResponse)
def modifier_adherent(
    user_id: Optional[int] = Form(None), adherent_id: Optional[int] = Form(None),
    nom: Optional[str] = Form(None), prenom: Optional[str] = Form(None),
    telephone: Optional[str] = Form(None), secteur: Optional[str] = Form(None)
):
    if not user_id or not adherent_id:
        return RedirectResponse(url="/", status_code=303)
    try:
        tel_norm = normaliser_telephone(telephone)
        supabase.table("adherents").update({
            "nom": nom, "prenom": prenom, "telephone": tel_norm, "secteur": secteur
        }).eq("id", adherent_id).execute()
        return HTMLResponse(content=f"<script>alert('Informations mises à jour avec succès !'); window.location.href='/dashboard?id={user_id}';</script>")
    except Exception as e:
        return HTMLResponse(content=f"<script>alert('Erreur : {str(e)}'); window.location.href='/dashboard?id={user_id}';</script>")

@app.api_route("/admin/maj-solde-initial", methods=["GET", "POST"], response_class=HTMLResponse)
def maj_solde_initial(user_id: Optional[int] = Form(None), solde_initial: Optional[float] = Form(None)):
    if not user_id or solde_initial is None:
        return RedirectResponse(url="/", status_code=303)
    try:
        supabase.table("parametres").update({"solde_initial": solde_initial}).eq("id", 1).execute()
        return HTMLResponse(content=f"<script>alert('Solde initial mis à jour avec succès !'); window.location.href='/dashboard?id={user_id}';</script>")
    except Exception as e:
        return HTMLResponse(content=f"<script>alert('Erreur : {str(e)}'); window.location.href='/dashboard?id={user_id}';</script>")

@app.api_route("/admin/saisir-cotisation", methods=["GET", "POST"], response_class=HTMLResponse)
def saisir_cotisation(
    user_id: Optional[int] = Form(None), adherent_id: Optional[int] = Form(None),
    montant: Optional[float] = Form(None), periode: Optional[str] = Form(None), mode_paiement: Optional[str] = Form(None)
):
    if not user_id or not adherent_id:
        return RedirectResponse(url="/", status_code=303)
    try:
        supabase.table("cotisations").insert({
            "adherent_id": adherent_id, "montant": montant or 0, "periode": periode or "",
            "mode_paiement": mode_paiement or "especes", "statut_paiement": "valide"
        }).execute()
        return HTMLResponse(content=f"<script>alert('Cotisation enregistrée et validée avec succès !'); window.location.href='/dashboard?id={user_id}';</script>")
    except Exception as e:
        return HTMLResponse(content=f"<script>alert('Erreur : {str(e)}'); window.location.href='/dashboard?id={user_id}';</script>")

@app.api_route("/admin/creer-evenement", methods=["GET", "POST"], response_class=HTMLResponse)
def creer_evenement(user_id: Optional[int] = Form(None), titre: Optional[str] = Form(None), date_reunion: Optional[str] = Form(None), description: Optional[str] = Form(None)):
    if not user_id:
        return RedirectResponse(url="/", status_code=303)
    try:
        supabase.table("evenements").insert({
            "titre": titre or "", "date_reunion": date_reunion or "", "description": description or ""
        }).execute()
    except Exception:
        pass
    return RedirectResponse(url=f"/dashboard?id={user_id}", status_code=status.HTTP_303_SEE_OTHER)

@app.api_route("/admin/pointer-presence", methods=["GET", "POST"], response_class=HTMLResponse)
def pointer_presence(user_id: Optional[int] = Form(None), adherent_id: Optional[int] = Form(None), evenement_titre: Optional[str] = Form(None), date_reunion: Optional[str] = Form(None), statut_presence: Optional[str] = Form(None)):
    if not user_id or not adherent_id:
        return RedirectResponse(url="/", status_code=303)
    try:
        supabase.table("presences_association").insert({
            "adherent_id": adherent_id, "evenement_titre": evenement_titre or "Réunion", "date_reunion": date_reunion or str(datetime.date.today()), "statut_presence": statut_presence or "Present"
        }).execute()
        return HTMLResponse(content=f"<script>alert('Présence enregistrée !'); window.location.href='/dashboard?id={user_id}';</script>")
    except Exception as e:
        return HTMLResponse(content=f"<script>alert('Erreur : {str(e)}'); window.location.href='/dashboard?id={user_id}';</script>")

@app.api_route("/admin/valider-aide", methods=["GET", "POST"], response_class=HTMLResponse)
def valider_aide(user_id: Optional[int] = Form(None), aide_id: Optional[int] = Form(None), statut_validation: Optional[str] = Form(None)):
    if user_id and aide_id and statut_validation:
        supabase.table("aides").update({"statut_validation": statut_validation}).eq("id", aide_id).execute()
        return RedirectResponse(url=f"/dashboard?id={user_id}", status_code=status.HTTP_303_SEE_OTHER)
    return RedirectResponse(url="/", status_code=303)

@app.api_route("/admin/valider-paiement-mobile", methods=["GET", "POST"], response_class=HTMLResponse)
def valider_paiement_mobile(user_id: Optional[int] = Form(None), paiement_id: Optional[int] = Form(None)):
    if user_id and paiement_id:
        supabase.table("cotisations").update({"statut_paiement": "valide"}).eq("id", paiement_id).execute()
        return HTMLResponse(content=f"<script>alert('Paiement mobile validé avec succès ! Le reçu est désormais disponible pour le membre.'); window.location.href='/dashboard?id={user_id}';</script>")
    return RedirectResponse(url="/", status_code=303)

@app.api_route("/paiement-mobile-form", methods=["GET", "POST"], response_class=HTMLResponse)
@app.api_route("/paiement-mobile-form/", methods=["GET", "POST"], response_class=HTMLResponse)
def paiement_mobile(
    user_id: Optional[int] = Form(None), montant: Optional[float] = Form(None), periode: Optional[str] = Form(None),
    operateur: Optional[str] = Form(None), telephone_paiement: Optional[str] = Form(None),
    reference_transaction: Optional[str] = Form(None), numero_recepteur: Optional[str] = Form(None)
):
    if not user_id:
        return RedirectResponse(url="/", status_code=303)
    try:
        mode = f"mobile_{str(operateur).lower()} (Réf: {reference_transaction} | Vers: {numero_recepteur} | Tél: {telephone_paiement})"
        supabase.table("cotisations").insert({
            "adherent_id": user_id, "montant": montant or 0, "periode": periode or "",
            "mode_paiement": mode, "statut_paiement": "en_attente"
        }).execute()
        return HTMLResponse(content=f"<script>alert('Paiement déclaré avec succès ! En attente de validation par le trésorier.'); window.location.href='/dashboard?id={user_id}';</script>")
    except Exception as e:
        return HTMLResponse(content=f"<script>alert('Erreur : {str(e)}'); window.location.href='/dashboard?id={user_id}';</script>")

@app.api_route("/projets-form", methods=["GET", "POST"], response_class=HTMLResponse)
@app.api_route("/projets-form/", methods=["GET", "POST"], response_class=HTMLResponse)
def ajouter_projet(
    user_id: Optional[int] = Form(None), titre: Optional[str] = Form(None), description: Optional[str] = Form(None), 
    objectifs: Optional[str] = Form(None), cout: Optional[float] = Form(None),
    chronologie: Optional[str] = Form(None), statut: Optional[str] = Form(None)
):
    if not user_id:
        return RedirectResponse(url="/", status_code=303)
    try:
        supabase.table("projets").insert({
            "titre": titre or "", "description": description or "", "objectifs": objectifs or "N/A",
            "cout": cout or 0, "chronologie": chronologie or "N/A", "statut": statut or "En cours"
        }).execute()
    except Exception:
        pass
    return RedirectResponse(url=f"/dashboard?id={user_id}", status_code=status.HTTP_303_SEE_OTHER)

@app.get("/adherents/export-pdf")
def export_adherents_pdf():
    res = supabase.table("adherents").select("*").order("nom").execute()
    adherents = res.data or []
    buffer = io.BytesIO()
    p = canvas.Canvas(buffer, pagesize=letter)
    width, height = letter
    p.setFont("Helvetica-Bold", 14)
    p.drawString(50, height - 40, "TINKA KA MEIN HAALDI FOTTI")
    p.setFont("Helvetica", 9)
    p.drawString(50, height - 55, "Annuaire Officiel des Adhérents")
    p.line(50, height - 65, width - 50, height - 65)
    p.setFont("Helvetica-Bold", 13)
    p.drawString(50, height - 95, f"Liste Générale des Adhérents ({len(adherents)} membres)")
    p.setFont("Helvetica", 10)
    y = height - 130
    for a in adherents:
        p.drawString(50, y, f"- {a.get('prenom','')} {a.get('nom','')} | Secteur: {a.get('secteur','')} | Tél: {a.get('telephone','')} | Rôle: {a.get('role','')} ({a.get('statut','')})")
        y -= 20
        if y < 50:
            p.showPage()
            y = height - 50
    p.save()
    buffer.seek(0)
    return StreamingResponse(buffer, media_type="application/pdf", headers={"Content-Disposition": "attachment; filename=annuaire_adherents.pdf"})

@app.get("/cotisation/recu-pdf/{cotisation_id}")
def telecharger_recu_pdf(cotisation_id: int):
    res = supabase.table("cotisations").select("*, adherents(nom, prenom, secteur, telephone)").eq("id", cotisation_id).execute()
    if not res.data:
        return HTMLResponse("Reçu introuvable", status_code=404)
    c = res.data[0]
    if c.get('statut_paiement') != 'valide':
        return HTMLResponse("<script>alert('Accès refusé : Ce paiement n\\'a pas encore été validé par l\\'administration.'); window.history.back();</script>", status_code=403)
    adh = c.get('adherents', {}) or {}
    montant_fmt = formater_montant(c.get('montant', 0))
    buffer = io.BytesIO()
    p = canvas.Canvas(buffer, pagesize=letter)
    width, height = letter
    p.setFont("Helvetica-Bold", 16)
    p.drawString(50, height - 50, "TINKA KA MEIN HAALDI FOTTI")
    p.setFont("Helvetica", 10)
    p.drawString(50, height - 68, "Reçu Officiel de Paiement de Cotisation")
    p.line(50, height - 80, width - 50, height - 80)
    p.setFont("Helvetica-Bold", 12)
    p.drawString(50, height - 120, f"Reçu N° : TK-{c['id']:04d}")
    p.setFont("Helvetica", 11)
    p.drawString(50, height - 145, f"Date de Paiement : {formater_date(c.get('date_paiement',''))}")
    p.drawString(50, height - 170, f"Membre : {adh.get('prenom','')} {adh.get('nom','')}")
    p.drawString(50, height - 195, f"Secteur : {adh.get('secteur','')}")
    p.drawString(50, height - 220, f"Téléphone : {adh.get('telephone','')}")
    p.rect(50, height - 310, width - 100, 60, stroke=1, fill=0)
    p.setFont("Helvetica-Bold", 14)
    p.drawString(70, height - 265, f"Montant Versé : {montant_fmt} CFA")
    p.setFont("Helvetica", 11)
    p.drawString(70, height - 285, f"Période couverte : {c.get('periode','')} | Mode : {c.get('mode_paiement','')}")
    p.save()
    buffer.seek(0)
    return StreamingResponse(buffer, media_type="application/pdf", headers={"Content-Disposition": f"attachment; filename=recu_cotisation_{c['id']}.pdf"})

@app.api_route("/dashboard", methods=["GET", "POST"], response_class=HTMLResponse)
def afficher_dashboard(id: Optional[int] = Query(None)):
    if not id:
        return RedirectResponse(url="/", status_code=303)
    try:
        user_res = supabase.table("adherents").select("*").eq("id", id).execute()
        if not user_res.data:
            return RedirectResponse(url="/", status_code=303)
        user = user_res.data[0]

        is_admin = user.get('role') == 'admin'
        is_tresorier = user.get('role') in ['admin', 'tresorier']

        maintenant = datetime.datetime.now()
        annee_actuelle = maintenant.year
        mois_actuel = maintenant.month

        mois_passes = [f"{annee_actuelle}-{mois_actuel:02d}"]

        all_actifs = supabase.table("adherents").select("*").eq("statut", "actif").execute().data or []
        all_adherents = supabase.table("adherents").select("*").execute().data or []
        all_cotisations = supabase.table("cotisations").select("*, adherents(nom, prenom, secteur, telephone)").execute().data or []
        all_aides = supabase.table("aides").select("*, adherents(nom, prenom, secteur)").execute().data or []
        all_decaissements = supabase.table("decaissements").select("*").execute().data or []
        all_projets = supabase.table("projets").select("*").execute().data or []
        all_evenements = supabase.table("evenements").select("*").execute().data or []

        try:
            all_presences = supabase.table("presences_association").select("*, adherents(nom, prenom, secteur, telephone)").execute().data or []
        except Exception:
            all_presences = []

        param_res = supabase.table("parametres").select("solde_initial").eq("id", 1).execute()
        solde_initial = param_res.data[0]['solde_initial'] if param_res.data else 0.0

        cotisations_caisse = sum([c['montant'] for c in all_cotisations if "regularisation" not in str(c.get('mode_paiement', '')) and c.get('statut_paiement') == 'valide'])
        total_aides_approuvees = sum([ai['montant_demande'] for ai in all_aides if ai.get('statut_validation') == 'approuve'])
        total_dec = sum([d['montant'] for d in all_decaissements])
        
        solde = solde_initial + cotisations_caisse - (total_aides_approuvees + total_dec)

        url_profil_personnel = f"https://tinka-association.onrender.com/dashboard?id={user['id']}"
        qr_perso_b64 = generer_qrcode_base64(url_profil_personnel)

        projets_cards_html = ""
        for pr in all_projets:
            projets_cards_html += f"""
            <div class="bg-white p-5 rounded-2xl border border-slate-200/80 mb-4 shadow-sm">
                <div class="flex justify-between items-start gap-2 mb-2">
                    <h4 class="font-black text-base text-indigo-950">{pr.get('titre', '')}</h4>
                    <span class="text-[11px] font-extrabold px-2.5 py-1 rounded-full bg-indigo-50 text-indigo-700 uppercase">{pr.get('statut', '')}</span>
                </div>
                <p class="text-xs text-slate-600 mb-3 leading-relaxed">{pr.get('description', '')}</p>
                <div class="text-xs text-slate-600 space-y-1.5 bg-slate-50 p-3 rounded-xl border border-slate-100">
                    <div><b>🎯 Objectifs :</b> {pr.get('objectifs', 'Non spécifié')}</div>
                    <div><b>📅 Planning :</b> {pr.get('chronologie', 'Non spécifié')}</div>
                    <div class="font-extrabold text-emerald-700">💰 Budget estimé : {formater_montant(pr.get('cout', 0))} CFA</div>
                </div>
            </div>
            """

        suivi_retards_html = ""
        for a in all_actifs:
            cotis_membre = []
            for c in all_cotisations:
                if c.get('adherent_id') == a['id'] and c.get('statut_paiement') == 'valide':
                    cotis_membre.append(c.get('periode'))
            
            mois_manquants = []
            for m in mois_passes:
                if m not in cotis_membre:
                    mois_manquants.append(m)
            
            txt_wa = f"Bonjour {a.get('prenom','')}, rappel amical de l'association Tinka : votre cotisation pour le mois de {mois_actuel} est en attente. Merci de régulariser."
            link_wa = f"https://wa.me/{str(a.get('telephone','')).replace('+', '')}?text={txt_wa}" if a.get('telephone') else "#"
            
            btn_wa = f"<a href='{link_wa}' target='_blank' class='bg-emerald-600 hover:bg-emerald-700 text-white px-2.5 py-1 rounded-lg text-xs font-bold ml-2 shadow-sm transition'>💬 Relancer WhatsApp</a>" if mois_manquants else ""
            
            statut_ajour = "<span class='text-emerald-700 font-extrabold bg-emerald-50 px-2.5 py-1 rounded-full text-xs'>À jour ✓</span>" if not mois_manquants else f"<span class='text-red-700 font-extrabold bg-red-50 px-2.5 py-1 rounded-full text-xs'>En attente ({mois_passes[0]})</span>{btn_wa}"
            
            suivi_retards_html += f"""
            <tr class='border-b text-sm retard-row' data-nom='{str(a.get('prenom','')).lower()} {str(a.get('nom','')).lower()}' data-secteur='{str(a.get('secteur','')).lower()}'>
                <td class='p-3 font-bold text-slate-900'>{a.get('prenom','')} {a.get('nom','')} <span class='text-xs text-slate-400 font-normal'>({a.get('secteur','')})</span></td>
                <td class='p-3 text-right'>{statut_ajour}</td>
            </tr>
            """

        adherents_table_rows = ""
        modals_html = ""
        for a in all_adherents:
            actions_admin = ""
            if is_tresorier and a.get('statut') == 'en_attente':
                actions_admin += f"""
                <form action="/admin/valider-adherent" method="POST" class="inline"><input type="hidden" name="user_id" value="{user['id']}"><input type="hidden" name="adherent_id" value="{a['id']}"><button type="submit" class="bg-emerald-600 hover:bg-emerald-700 text-white px-2.5 py-1 rounded-lg text-xs font-bold shadow-sm transition">Valider</button></form>
                """
            if is_admin:
                actions_admin += f"""
                <form action="/admin/changer-role" method="POST" class="inline-block ml-1">
                    <input type="hidden" name="user_id" value="{user['id']}"><input type="hidden" name="adherent_id" value="{a['id']}">
                    <select name="nouveau_role" onchange="this.form.submit()" class="p-1.5 text-xs border border-slate-300 rounded-xl bg-white text-blue-700 font-bold shadow-sm">
                        <option value="membre" {'selected' if a.get('role')=='membre' else ''}>Membre</option>
                        <option value="tresorier" {'selected' if a.get('role')=='tresorier' else ''}>Trésorier</option>
                        <option value="admin" {'selected' if a.get('role')=='admin' else ''}>Admin</option>
                    </select>
                </form>
                """

            btn_modif = f"""<button onclick="openModal({a['id']})" class="bg-blue-50 hover:bg-blue-100 text-blue-700 px-3 py-1 rounded-xl text-xs font-bold ml-1 transition">⚙️</button>""" if is_tresorier or a['id'] == user['id'] else ""

            adherents_table_rows += f"""
            <tr class="hover:bg-slate-50 border-b text-sm adherent-row" data-nom="{str(a.get('prenom','')).lower()} {str(a.get('nom','')).lower()}" data-secteur="{str(a.get('secteur','')).lower()}" data-tel="{str(a.get('telephone',''))}">
                <td class="p-3 font-semibold text-slate-900">{a.get('prenom','')} {a.get('nom','')}</td>
                <td class="p-3"><span class="text-[11px] bg-slate-100 text-slate-700 px-2.5 py-1 rounded-full font-bold uppercase">{a.get('role','')}</span></td>
                <td class="p-3 text-slate-600">{a.get('secteur','')}</td>
                <td class="p-3 font-mono text-xs text-slate-500">{a.get('telephone','')}</td>
                <td class="p-3 text-right">{actions_admin}{btn_modif}</td>
            </tr>
            """

            modals_html += f"""
            <div id="modal-{a['id']}" class="fixed inset-0 bg-slate-900/60 backdrop-blur-sm z-50 hidden flex items-center justify-center p-4">
                <div class="bg-white rounded-3xl max-w-lg w-full p-6 shadow-2xl border border-slate-100">
                    <div class="flex justify-between items-center mb-4 border-b pb-3"><h3 class="font-black text-lg text-slate-800">Modifier : {a.get('prenom','')} {a.get('nom','')}</h3><button onclick="closeModal({a['id']})" class="font-bold text-lg text-slate-400 hover:text-slate-700">✕</button></div>
                    <form action="/admin/modifier-adherent" method="POST" class="space-y-4 mb-4">
                        <input type="hidden" name="user_id" value="{user['id']}"><input type="hidden" name="adherent_id" value="{a['id']}">
                        <div class="grid grid-cols-2 gap-3">
                            <div><label class="block text-xs font-bold mb-1 text-slate-600">Prénom</label><input type="text" name="prenom" value="{a.get('prenom','')}" required class="w-full p-2.5 text-sm border border-slate-300 rounded-xl"></div>
                            <div><label class="block text-xs font-bold mb-1 text-slate-600">Nom</label><input type="text" name="nom" value="{a.get('nom','')}" required class="w-full p-2.5 text-sm border border-slate-300 rounded-xl"></div>
                        </div>
                        <div class="grid grid-cols-2 gap-3">
                            <div><label class="block text-xs font-bold mb-1 text-slate-600">Téléphone</label><input type="text" name="telephone" value="{a.get('telephone','')}" required class="w-full p-2.5 text-sm border border-slate-300 rounded-xl"></div>
                            <div><label class="block text-xs font-bold mb-1 text-slate-600">Secteur</label><input type="text" name="secteur" value="{a.get('secteur','')}" required class="w-full p-2.5 text-sm border border-slate-300 rounded-xl"></div>
                        </div>
                        <button type="submit" class="w-full bg-emerald-600 hover:bg-emerald-700 text-white py-2.5 rounded-xl text-sm font-bold shadow-md transition">Enregistrer les modifications</button>
                    </form>
                </div>
            </div>
            """

        presences_table_rows = "".join([f"<tr class='border-b text-sm presence-row' data-nom='{str(p.get('adherents',{}).get('prenom','')).lower()} {str(p.get('adherents',{}).get('nom','')).lower()}' data-event='{str(p.get('evenement_titre','')).lower()}'><td class='p-3 font-bold'>{p.get('adherents',{}).get('prenom','')} {p.get('adherents',{}).get('nom','')}</td><td class='p-3 text-slate-700'>{p.get('evenement_titre','')}</td><td class='p-3 text-slate-500'>{formater_date(p.get('date_reunion',''))}</td><td class='p-3'><span class='text-xs px-2.5 py-1 rounded-full font-extrabold bg-emerald-50 text-emerald-700'>{p.get('statut_presence','')}</span></td></tr>" for p in all_presences])
        
        paiements_mobiles_admin = [c for c in all_cotisations if "mobile_" in str(c.get('mode_paiement', ''))]
        paiements_mobiles_rows = ""
        for pm in paiements_mobiles_admin:
            adh_pm = pm.get('adherents', {}) or {}
            st_paiement = pm.get('statut_paiement', 'en_attente')
            if is_tresorier:
                action_cell = f"""
                <form action="/admin/valider-paiement-mobile" method="POST" class="inline">
                    <input type="hidden" name="user_id" value="{user['id']}"><input type="hidden" name="paiement_id" value="{pm['id']}">
                    <button type="submit" class="bg-amber-500 hover:bg-amber-600 text-white px-3 py-1.5 rounded-xl text-xs font-bold shadow-sm transition">⏳ Valider</button>
                </form>
                """ if st_paiement != 'valide' else f"""
                <span class="text-xs font-bold text-emerald-700 bg-emerald-100 px-2.5 py-1 rounded-full mr-2">Validé ✓</span>
                <a href="/cotisation/recu-pdf/{pm['id']}" target="_blank" class="bg-blue-600 hover:bg-blue-700 text-white px-3 py-1 rounded-xl text-xs font-bold shadow-sm transition">📄 PDF</a>
                """
            else:
                action_cell = "<span class='text-xs font-bold text-emerald-700 bg-emerald-50 px-2.5 py-1 rounded-full'>Validé ✓</span>" if st_paiement == 'valide' else "<span class='text-xs font-bold text-amber-700 bg-amber-50 px-2.5 py-1 rounded-full'>⏳ En attente</span>"

            paiements_mobiles_rows += f"""
            <tr class="hover:bg-slate-50 border-b text-sm mobile-row" data-nom="{str(adh_pm.get('prenom','')).lower()} {str(adh_pm.get('nom','')).lower()}">
                <td class="p-3 font-bold">{adh_pm.get('prenom','')} {adh_pm.get('nom','')}</td>
                <td class="p-3 font-semibold text-blue-700 text-xs uppercase">{pm.get('mode_paiement','')}</td>
                <td class="p-3 font-black text-emerald-700">{formater_montant(pm.get('montant',0))} CFA</td>
                <td class="p-3 text-slate-600 font-medium">{pm.get('periode','')}</td>
                <td class="p-3 text-right">{action_cell}</td>
            </tr>
            """

        aides_admin_html = ""
        for ai in all_aides:
            adh_aide = ai.get('adherents', {}) or {}
            st_aide = ai.get('statut_validation', 'en_attente')
            if is_tresorier:
                actions_aide = f"""
                <form action="/admin/valider-aide" method="POST" class="inline-block"><input type="hidden" name="user_id" value="{user['id']}"><input type="hidden" name="aide_id" value="{ai['id']}"><input type="hidden" name="statut_validation" value="approuve"><button type="submit" class="bg-emerald-600 hover:bg-emerald-700 text-white px-2.5 py-1 rounded-lg text-xs font-bold mr-1 transition">Approuver</button></form>
                <form action="/admin/valider-aide" method="POST" class="inline-block"><input type="hidden" name="user_id" value="{user['id']}"><input type="hidden" name="aide_id" value="{ai['id']}"><input type="hidden" name="statut_validation" value="refuse"><button type="submit" class="bg-red-600 hover:bg-red-700 text-white px-2.5 py-1 rounded-lg text-xs font-bold transition">Refuser</button></form>
                """ if st_aide == 'en_attente' else f"<span class='text-xs font-bold py-1 px-2.5 rounded-full bg-slate-100 text-slate-600 uppercase'>{st_aide}</span>"
            else:
                actions_aide = f"<span class='text-xs font-bold py-1 px-2.5 rounded-full bg-slate-100 text-slate-600 uppercase'>{st_aide}</span>"
            aides_admin_html += f"<li class='py-3 border-b flex justify-between items-center text-sm aide-item' data-motif='{str(ai.get('motif','')).lower()}'><div><b>{adh_aide.get('prenom','')} {adh_aide.get('nom','')}</b> — {ai.get('motif','')} <span class='text-amber-700 font-black'>({formater_montant(ai.get('montant_demande',0))} CFA)</span></div><div>{actions_aide}</div></li>"

        options_adherents_select = "".join([f"<option value='{a['id']}'>{a.get('prenom','')} {a.get('nom','')} ({a.get('secteur','')})</option>" for a in all_actifs])
        options_evenements_select = "".join([f"<option value='{e.get('titre','')}' data-date='{e.get('date_reunion','')}' >{e.get('titre','')} ({formater_date(e.get('date_reunion',''))})</option>" for e in all_evenements])

        tresorerie_box_html = f"""
        <div class="space-y-6">
            <div class="bg-white p-6 rounded-3xl shadow-sm border border-slate-200/80">
                <h2 class="text-base font-black mb-4 border-b pb-3 text-slate-800">💼 Trésorerie & Solde Global</h2>
                """
        if is_tresorier:
            tresorerie_box_html += f"""
                <form action="/admin/maj-solde-initial" method="POST" class="bg-gradient-to-r from-emerald-50 to-teal-50 p-4 rounded-2xl border border-emerald-200/60 mb-6 flex gap-3 items-end shadow-inner">
                    <input type="hidden" name="user_id" value="{user['id']}">
                    <div class="flex-1"><label class="block text-xs font-bold text-emerald-900 mb-1">Solde Initial Réel en Caisse</label><input type="number" name="solde_initial" value="{solde_initial}" required class="w-full p-2.5 text-sm bg-white border border-emerald-300 rounded-xl shadow-sm"></div>
                    <button type="submit" class="bg-emerald-600 hover:bg-emerald-700 text-white font-bold py-2.5 px-5 rounded-xl text-sm shadow-md transition">Mettre à jour</button>
                </form>

                <div class="bg-slate-50 p-5 rounded-2xl border border-slate-200 mb-6">
                    <h3 class="text-xs font-black text-slate-800 mb-3 uppercase tracking-wider">➕ Saisie Manuelle d'une Cotisation Membre</h3>
                    <form action="/admin/saisir-cotisation" method="POST" class="grid grid-cols-1 sm:grid-cols-4 gap-3">
                        <input type="hidden" name="user_id" value="{user['id']}">
                        <select name="adherent_id" required class="p-2.5 text-sm border border-slate-300 rounded-xl bg-white font-semibold">
                            <option value="">-- Choisir un membre --</option>
                            {options_adherents_select}
                        </select>
                        <input type="text" name="periode" placeholder="Période (ex: 2026-09)" required class="p-2.5 text-sm border border-slate-300 rounded-xl bg-white">
                        <input type="number" name="montant" placeholder="Montant (CFA)" required class="p-2.5 text-sm border border-slate-300 rounded-xl bg-white">
                        <button type="submit" class="bg-emerald-600 hover:bg-emerald-700 text-white font-bold py-2.5 px-4 rounded-xl text-sm shadow-md transition">Enregistrer</button>
                    </form>
                </div>
            """
        tresorerie_box_html += f"""
                <div class="text-center bg-gradient-to-r from-slate-900 to-emerald-950 text-white py-4 rounded-2xl font-black text-lg mb-6 shadow-md">Solde Réel en Caisse : <span class="text-emerald-400">{formater_montant(solde)} CFA</span></div>
                
                <div class="flex justify-between items-center mb-3">
                    <h3 class="text-xs font-black text-slate-600 uppercase tracking-wider">État des cotisations membres (À jour & Retards)</h3>
                    <input type="text" id="search-retards" onkeyup="filterRetards()" placeholder="Filtrer les retards..." class="px-3 py-1 text-xs border border-slate-300 rounded-xl w-48 bg-slate-50">
                </div>
                <div class="overflow-x-auto max-h-72 overflow-y-auto border border-slate-200 rounded-2xl">
                    <table class="w-full text-left bg-white">
                        <tbody>{suivi_retards_html}</tbody>
                    </table>
                </div>
            </div>
            
            <div class="bg-white p-6 rounded-3xl shadow-sm border border-slate-200/80">
                <div class="flex justify-between items-center mb-3 border-b pb-3">
                    <h2 class="text-base font-black text-slate-800">📱 Paiements Mobile Money</h2>
                    <input type="text" id="search-mobile" onkeyup="filterMobile()" placeholder="Rechercher..." class="px-3 py-1 text-xs border border-slate-300 rounded-xl w-48 bg-slate-50">
                </div>
                <div class="overflow-x-auto max-h-60 overflow-y-auto border border-slate-200 rounded-2xl">
                    <table class="w-full text-left bg-white"><thead class="bg-slate-100 text-[11px] font-bold text-slate-600 uppercase"><tr><th class="p-3">Adhérent</th><th class="p-3">Détails</th><th class="p-3">Montant</th><th class="p-3">Période</th><th class="p-3 text-right">Action</th></tr></thead><tbody id="mobile-tbody">{paiements_mobiles_rows or '<tr><td colspan="5" class="p-4 text-center text-sm text-slate-400">Aucun paiement.</td></tr>'}</tbody></table>
                </div>
            </div>
        </div>
        """

        member_specific_html = ""
        if not is_tresorier:
            cotis_perso = [c for c in all_cotisations if c.get('adherent_id') == user['id']]
            mois_payes_html = ""
            for c in cotis_perso:
                st_p = c.get('statut_paiement', 'en_attente')
                if st_p == 'valide':
                    badge_recu = f"<a href='/cotisation/recu-pdf/{c['id']}' target='_blank' class='bg-blue-600 hover:bg-blue-700 text-white px-3 py-1 rounded-xl text-xs font-bold shadow-sm transition'>📄 Télécharger Reçu PDF</a>"
                else:
                    badge_recu = "<span class='bg-amber-100 text-amber-800 px-3 py-1 rounded-xl text-xs font-bold'>⏳ En attente de validation admin</span>"
                mois_payes_html += f"<li class='py-3 border-b border-slate-100 text-sm flex justify-between items-center'><span>Mois de <b>{c.get('periode','')}</b> : <span class='text-emerald-700 font-bold'>{formater_montant(c.get('montant',0))} CFA</span></span> {badge_recu}</li>"

            avatar_html = f"<img src='{user.get('photo_profil')}' class='w-16 h-16 rounded-2xl object-cover shadow-md border-2 border-emerald-400'>" if user.get('photo_profil') else f"<div class='w-16 h-16 rounded-2xl bg-emerald-100 flex items-center justify-center text-emerald-800 font-black text-xl shadow-md'>{user.get('prenom','M')[0]}</div>"

            member_specific_html = f"""
            <div class="bg-gradient-to-br from-slate-900 via-emerald-950 to-slate-900 text-white p-6 rounded-3xl shadow-xl flex justify-between items-center relative overflow-hidden">
                <div>
                    <span class="bg-emerald-500/20 text-emerald-300 text-[10px] font-extrabold px-2.5 py-1 rounded-full uppercase tracking-widest border border-emerald-500/30">Mon Compte Membre</span>
                    <h2 class="text-xl font-black mt-2">{user.get('prenom','')} {user.get('nom','')}</h2>
                    <p class="text-xs text-slate-300 font-medium mt-0.5">Secteur : {user.get('secteur','')} | Tél : {user.get('telephone','')}</p>
                </div>
                <div class="flex items-center gap-3">
                    {avatar_html}
                    <div class="bg-white p-2 rounded-2xl shadow-lg"><img src="data:image/png;base64,{qr_perso_b64}" class="w-14 h-14 rounded-xl"></div>
                </div>
            </div>
            <div class="bg-white p-6 rounded-3xl shadow-sm border border-slate-200/85">
                <h2 class="text-base font-black mb-4 border-b pb-3 text-slate-800">📱 Déclarer un Paiement Mobile</h2>
                <form action="/paiement-mobile-form" method="POST" class="space-y-3.5">
                    <input type="hidden" name="user_id" value="{user['id']}">
                    <div class="grid grid-cols-3 gap-2">
                        <select name="operateur" class="p-2.5 border border-slate-300 rounded-xl text-sm bg-white font-semibold"><option value="Wave">Wave</option><option value="OrangeMoney">Orange Money</option></select>
                        <input type="text" name="telephone_paiement" value="{user.get('telephone','')}" required class="p-2.5 border border-slate-300 rounded-xl text-sm" placeholder="Mon Tél">
                        <input type="text" name="numero_recepteur" required class="p-2.5 border border-slate-300 rounded-xl text-sm" placeholder="N° Récepteur">
                    </div>
                    <div class="grid grid-cols-3 gap-2">
                        <input type="text" name="reference_transaction" required class="p-2.5 border border-slate-300 rounded-xl text-sm" placeholder="Réf. Transaction">
                        <input type="number" name="montant" required class="p-2.5 border border-slate-300 rounded-xl text-sm" placeholder="Montant">
                        <input type="text" name="periode" required class="p-2.5 border border-slate-300 rounded-xl text-sm" placeholder="Mois (ex: 2026-09)">
                    </div>
                    <button type="submit" class="w-full bg-blue-600 hover:bg-blue-700 text-white font-bold py-2.5 rounded-xl text-sm shadow-md transition">Soumettre la déclaration</button>
                </form>
            </div>
            <div class="bg-white p-6 rounded-3xl shadow-sm border border-slate-200/85">
                <h2 class="text-base font-black mb-4 border-b pb-3 text-slate-800">📋 Mes Cotisations & Reçus</h2>
                <ul class="max-h-60 overflow-y-auto pr-2">{mois_payes_html or '<p class="text-sm text-slate-400">Aucun versement enregistré pour le moment.</p>'}</ul>
            </div>
            """

        evenements_cards = "".join([f"<div class='bg-slate-50 p-4 rounded-2xl border border-slate-200 mb-3'><h4 class='font-black text-sm text-slate-800'>{e.get('titre','')}</h4><p class='text-xs text-slate-500'>Date : {formater_date(e.get('date_reunion',''))}</p><p class='text-xs text-slate-600 mt-1'>{e.get('description','')}</p></div>" for e in all_evenements])
        
        admin_event_pointage_html = ""
        if is_tresorier:
            admin_event_pointage_html = f"""
            <div class="grid grid-cols-1 md:grid-cols-2 gap-6 mb-6">
                <div class="bg-white p-6 rounded-3xl shadow-sm border border-slate-200/80">
                    <h2 class="text-base font-black mb-4 border-b pb-3 text-slate-800">📅 Planification d'Événement</h2>
                    <form action="/admin/creer-evenement" method="POST" class="space-y-3">
                        <input type="hidden" name="user_id" value="{user['id']}">
                        <div><label class="block text-xs font-bold mb-1 text-slate-600">Titre de l'événement</label><input type="text" name="titre" placeholder="ex: Assemblée Générale Mensuelle" required class="w-full p-2.5 text-sm border border-slate-300 rounded-xl"></div>
                        <div><label class="block text-xs font-bold mb-1 text-slate-600">Date</label><input type="date" name="date_reunion" required class="w-full p-2.5 text-sm border border-slate-300 rounded-xl"></div>
                        <div><label class="block text-xs font-bold mb-1 text-slate-600">Description</label><textarea name="description" rows="2" class="w-full p-2.5 text-sm border border-slate-300 rounded-xl" placeholder="Ordre du jour..."></textarea></div>
                        <button type="submit" class="w-full bg-blue-600 hover:bg-blue-700 text-white py-2.5 rounded-xl text-sm font-bold shadow-md transition">Créer l'événement</button>
                    </form>
                    <div class="mt-4 max-h-40 overflow-y-auto">{evenements_cards or '<p class="text-xs text-slate-400">Aucun événement planifié.</p>'}</div>
                </div>
                <div class="bg-white p-6 rounded-3xl shadow-sm border border-slate-200/80">
                    <h2 class="text-base font-black mb-4 border-b pb-3 text-slate-800">📌 Scanner / Pointage Présence</h2>
                    <div class="mb-4 bg-emerald-50 p-3 rounded-2xl border border-emerald-200 text-center">
                        <input type="file" accept="image/*" capture="environment" id="scan-photo-input" onchange="handleScanPhoto(this)" class="hidden">
                        <button type="button" onclick="document.getElementById('scan-photo-input').click()" class="bg-emerald-600 hover:bg-emerald-700 text-white text-xs font-bold py-2 px-4 rounded-xl shadow-md transition">📷 Scanner Photo / QrCode Présence</button>
                        <p id="scan-result-text" class="text-[11px] text-emerald-800 font-semibold mt-2">Cliquez pour scanner ou photographier la feuille de présence</p>
                    </div>
                    <form action="/admin/pointer-presence" method="POST" class="space-y-3">
                        <input type="hidden" name="user_id" value="{user['id']}">
                        <div>
                            <label class="block text-xs font-bold mb-1 text-slate-600">Sélectionner l'événement</label>
                            <select name="evenement_titre" id="select-event" onchange="updateEventDate(this)" required class="w-full p-2.5 text-sm border border-slate-300 rounded-xl bg-white font-semibold">
                                <option value="">-- Choisir un événement --</option>
                                {options_evenements_select}
                            </select>
                        </div>
                        <div>
                            <label class="block text-xs font-bold mb-1 text-slate-600">Date de la réunion</label>
                            <input type="date" name="date_reunion" id="input-event-date" required class="w-full p-2.5 text-sm border border-slate-300 rounded-xl">
                        </div>
                        <div>
                            <label class="block text-xs font-bold mb-1 text-slate-600">Membre présent</label>
                            <select name="adherent_id" required class="w-full p-2.5 text-sm border border-slate-300 rounded-xl bg-white font-semibold">
                                <option value="">-- Choisir un membre --</option>
                                {options_adherents_select}
                            </select>
                        </div>
                        <div>
                            <label class="block text-xs font-bold mb-1 text-slate-600">Statut</label>
                            <select name="statut_presence" required class="w-full p-2.5 text-sm border border-slate-300 rounded-xl bg-white font-semibold">
                                <option value="Present">Présent(e)</option>
                                <option value="Retard">Retard</option>
                                <option value="Absent">Absent(e)</option>
                                <option value="Excuse">Excusé(e)</option>
                            </select>
                        </div>
                        <button type="submit" class="w-full bg-emerald-600 hover:bg-emerald-700 text-white py-2.5 rounded-xl text-sm font-bold shadow-md transition">Valider le pointage</button>
                    </form>
                </div>
            </div>
            """

        admin_projet_form = ""
        if is_tresorier:
            admin_projet_form = f"""
            <div class="bg-white p-6 rounded-3xl shadow-sm border border-slate-200/80 mb-6">
                <h2 class="text-base font-black mb-4 border-b pb-3 text-slate-800">➕ Proposer / Ajouter un Projet</h2>
                <form action="/projets-form" method="POST" class="space-y-3">
                    <input type="hidden" name="user_id" value="{user['id']}">
                    <div class="grid grid-cols-1 sm:grid-cols-2 gap-3">
                        <div><label class="block text-xs font-bold mb-1 text-slate-600">Titre du projet</label><input type="text" name="titre" required class="w-full p-2.5 text-sm border border-slate-300 rounded-xl"></div>
                        <div><label class="block text-xs font-bold mb-1 text-slate-600">Coût estimé (CFA)</label><input type="number" name="cout" required class="w-full p-2.5 text-sm border border-slate-300 rounded-xl"></div>
                    </div>
                    <div><label class="block text-xs font-bold mb-1 text-slate-600">Description</label><textarea name="description" rows="2" required class="w-full p-2.5 text-sm border border-slate-300 rounded-xl"></textarea></div>
                    <div class="grid grid-cols-1 sm:grid-cols-3 gap-3">
                        <div><label class="block text-xs font-bold mb-1 text-slate-600">Objectifs</label><input type="text" name="objectifs" class="w-full p-2.5 text-sm border border-slate-300 rounded-xl"></div>
                        <div><label class="block text-xs font-bold mb-1 text-slate-600">Planning / Chronologie</label><input type="text" name="chronologie" class="w-full p-2.5 text-sm border border-slate-300 rounded-xl"></div>
                        <div>
                            <label class="block text-xs font-bold mb-1 text-slate-600">Statut</label>
                            <select name="statut" class="w-full p-2.5 text-sm border border-slate-300 rounded-xl bg-white font-semibold">
                                <option value="En cours">En cours</option>
                                <option value="Planifié">Planifié</option>
                                <option value="Terminé">Terminé</option>
                            </select>
                        </div>
                    </div>
                    <button type="submit" class="w-full bg-indigo-600 hover:bg-indigo-700 text-white py-2.5 rounded-xl text-sm font-bold shadow-md transition">Publier le projet</button>
                </form>
            </div>
            """

        # Barre de navigation administrative affichée UNIQUEMENT si l'utilisateur est admin ou trésorier
        navigation_onglets_html = ""
        contenus_onglets_admin_html = ""

        if is_tresorier:
            navigation_onglets_html = f"""
            <div class="sticky top-0 z-40 bg-white/95 backdrop-blur-md py-3 px-4 rounded-2xl shadow-md border border-slate-200/80 flex flex-wrap gap-2">
                <button onclick="switchTab('tab-tresorerie')" id="btn-tab-tresorerie" class="tab-btn px-4 py-2 text-xs font-extrabold rounded-xl bg-slate-900 text-white shadow-md transition">💼 Trésorerie</button>
                <button onclick="switchTab('tab-adherents')" id="btn-tab-adherents" class="tab-btn px-4 py-2 text-xs font-extrabold rounded-xl bg-white text-slate-700 border border-slate-200 shadow-sm hover:bg-slate-50 transition">👥 Annuaire</button>
                <button onclick="switchTab('tab-pointage')" id="btn-tab-pointage" class="tab-btn px-4 py-2 text-xs font-extrabold rounded-xl bg-white text-slate-700 border border-slate-200 shadow-sm hover:bg-slate-50 transition">📋 Pointage</button>
                <button onclick="switchTab('tab-projets')" id="btn-tab-projets" class="tab-btn px-4 py-2 text-xs font-extrabold rounded-xl bg-white text-slate-700 border border-slate-200 shadow-sm hover:bg-slate-50 transition">🚀 Projets</button>
            </div>

            <div id="tab-tresorerie" class="tab-content space-y-6">
                {tresorerie_box_html}
            </div>

            <div id="tab-adherents" class="tab-content hidden space-y-6">
                <div class="bg-white p-6 rounded-3xl shadow-sm border border-slate-200/80">
                    <div class="flex flex-col sm:flex-row justify-between items-center mb-4 border-b pb-3 gap-3">
                        <h2 class="text-base font-black text-slate-800">👥 Annuaire ({len(all_adherents)})</h2>
                        <div class="flex gap-2 w-full sm:w-auto">
                            <input type="text" id="search-annuaire" onkeyup="filterAnnuaire()" placeholder="Rechercher par nom, secteur, téléphone..." class="px-3 py-1.5 text-xs border border-slate-300 rounded-xl w-full sm:w-64 bg-slate-50">
                            <a href="/adherents/export-pdf" target="_blank" class="bg-red-600 hover:bg-red-700 text-white px-3.5 py-1.5 rounded-xl text-xs font-extrabold shadow-md transition whitespace-nowrap">📄 PDF</a>
                        </div>
                    </div>
                    <div class="overflow-x-auto max-h-96 overflow-y-auto border border-slate-200 rounded-2xl">
                        <table class="w-full text-left bg-white">
                            <thead class="bg-slate-100 text-[11px] font-bold text-slate-600 uppercase">
                                <tr><th class="p-3">Nom & Prénom</th><th class="p-3">Rôle</th><th class="p-3">Secteur</th><th class="p-3">Téléphone</th><th class="p-3 text-right">Actions</th></tr>
                            </thead>
                            <tbody>{adherents_table_rows}</tbody>
                        </table>
                    </div>
                </div>
            </div>

            <div id="tab-pointage" class="tab-content hidden space-y-6">
                {admin_event_pointage_html}
                <div class="bg-white p-6 rounded-3xl shadow-sm border border-slate-200/80">
                    <div class="flex justify-between items-center mb-4 border-b pb-3">
                        <h2 class="text-base font-black text-slate-800">📋 Historique des Pointages</h2>
                        <input type="text" id="search-pointage" onkeyup="filterPointage()" placeholder="Filtrer par nom, événement..." class="px-3 py-1 text-xs border border-slate-300 rounded-xl w-56 bg-slate-50">
                    </div>
                    <div class="overflow-x-auto max-h-96 overflow-y-auto border border-slate-200 rounded-2xl">
                        <table class="w-full text-left bg-white"><thead class="bg-slate-100 text-[11px] font-bold text-slate-600 uppercase"><tr><th class="p-3">Membre</th><th class="p-3">Événement</th><th class="p-3">Date</th><th class="p-3">Statut</th></tr></thead><tbody id="presence-tbody">{presences_table_rows or '<tr><td colspan="4" class="p-4 text-center text-sm text-slate-400">Aucun pointage enregistré.</td></tr>'}</tbody></table>
                    </div>
                </div>
            </div>

            <div id="tab-projets" class="tab-content hidden space-y-6">
                {admin_projet_form}
                <div class="bg-white p-6 rounded-3xl shadow-sm border border-slate-200/80">
                    <div class="flex justify-between items-center mb-4 border-b pb-3">
                        <h2 class="text-base font-black text-slate-800">🤝 Demandes d'Aide</h2>
                        <input type="text" id="search-projets" onkeyup="filterProjets()" placeholder="Filtrer demandes..." class="px-3 py-1 text-xs border border-slate-300 rounded-xl w-48 bg-slate-50">
                    </div>
                    <ul class="max-h-60 overflow-y-auto pr-2" id="aides-ul">{aides_admin_html or '<p class="text-sm text-slate-400">Aucune demande.</p>'}</ul>
                </div>
                <div class="bg-white p-6 rounded-3xl shadow-sm border border-slate-200/80">
                    <h2 class="text-base font-black mb-4 border-b pb-3 text-slate-800">🚀 Projets de l'Association</h2>
                    <div class="max-h-96 overflow-y-auto pr-2">{projets_cards_html or '<p class="text-xs text-slate-400">Aucun projet enregistré.</p>'}</div>
                </div>
            </div>
            """

        return f"""
        <!DOCTYPE html>
        <html lang="fr">
        <head>
            <meta charset="UTF-8"><meta name="viewport" content="width=device-width, initial-scale=1.0"><title>Dashboard - Tinka</title>
            <script src="https://cdn.tailwindcss.com"></script>
            <script>
                function switchTab(tabId) {{
                    let contents = document.getElementsByClassName('tab-content');
                    for (let c of contents) c.classList.add('hidden');
                    let target = document.getElementById(tabId);
                    if (target) target.classList.remove('hidden');
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
                function openModal(id) {{ let m = document.getElementById('modal-' + id); if(m) m.classList.remove('hidden'); }}
                function closeModal(id) {{ let m = document.getElementById('modal-' + id); if(m) m.classList.add('hidden'); }}
                function filterAnnuaire() {{
                    let input = document.getElementById('search-annuaire');
                    if (!input) return;
                    let val = input.value.toLowerCase();
                    let rows = document.getElementsByClassName('adherent-row');
                    for (let r of rows) {{
                        let nom = r.getAttribute('data-nom');
                        let secteur = r.getAttribute('data-secteur');
                        let tel = r.getAttribute('data-tel');
                        r.style.display = (nom.includes(val) || secteur.includes(val) || tel.includes(val)) ? "" : "none";
                    }}
                }}
                function filterRetards() {{
                    let input = document.getElementById('search-retards');
                    if (!input) return;
                    let val = input.value.toLowerCase();
                    let rows = document.getElementsByClassName('retard-row');
                    for (let r of rows) {{
                        let nom = r.getAttribute('data-nom');
                        let secteur = r.getAttribute('data-secteur');
                        r.style.display = (nom.includes(val) || secteur.includes(val)) ? "" : "none";
                    }}
                }}
                function filterPointage() {{
                    let input = document.getElementById('search-pointage');
                    if (!input) return;
                    let val = input.value.toLowerCase();
                    let rows = document.getElementsByClassName('presence-row');
                    for (let r of rows) {{
                        let nom = r.getAttribute('data-nom');
                        let ev = r.getAttribute('data-event');
                        r.style.display = (nom.includes(val) || ev.includes(val)) ? "" : "none";
                    }}
                }}
                function filterProjets() {{
                    let input = document.getElementById('search-projets');
                    if (!input) return;
                    let val = input.value.toLowerCase();
                    let items = document.getElementsByClassName('aide-item');
                    for (let i of items) {{
                        let motif = i.getAttribute('data-motif');
                        i.style.display = motif.includes(val) ? "" : "none";
                    }}
                }}
                function filterMobile() {{
                    let input = document.getElementById('search-mobile');
                    if (!input) return;
                    let val = input.value.toLowerCase();
                    let rows = document.getElementsByClassName('mobile-row');
                    for (let r of rows) {{
                        let nom = r.getAttribute('data-nom');
                        r.style.display = nom.includes(val) ? "" : "none";
                    }}
                }}
                function updateEventDate(select) {{
                    let opt = select.options[select.selectedIndex];
                    let dt = opt.getAttribute('data-date');
                    if (dt) {{
                        let inputDate = document.getElementById('input-event-date');
                        if (inputDate) inputDate.value = dt.substring(0, 10);
                    }}
                }}
                function handleScanPhoto(input) {{
                    if (input.files && input.files[0]) {{
                        let txt = document.getElementById('scan-result-text');
                        if (txt) {{
                            txt.innerText = "Photo scannée avec succès ! Prêt pour le pointage.";
                            txt.classList.remove('text-emerald-800');
                            txt.classList.add('text-blue-700', 'font-black');
                        }}
                    }}
                }}
            </script>
        </head>
        <body class="bg-gradient-to-br from-slate-50 via-slate-100 to-emerald-50 text-slate-800 font-sans min-h-screen py-6 px-4">
            <div class="max-w-4xl mx-auto space-y-6">
                <div class="bg-white p-5 rounded-3xl shadow-sm border border-slate-200/80 flex justify-between items-center backdrop-blur-md">
                    <div class="flex items-center gap-3">
                        <div class="w-11 h-11 rounded-2xl bg-emerald-100 flex items-center justify-center text-emerald-800 font-black text-lg shadow-sm">{user.get('prenom','M')[0]}</div>
                        <div>
                            <h2 class="text-base font-black text-slate-900">{user.get('prenom','')} {user.get('nom','')}</h2>
                            <p class="text-xs text-blue-700 uppercase font-extrabold tracking-wider">{user.get('role','')}</p>
                        </div>
                    </div>
                    <a href="/" class="bg-red-600 hover:bg-red-700 text-white px-4 py-2 rounded-xl text-xs font-bold shadow-md transition">Déconnexion</a>
                </div>

                {member_specific_html}

                {navigation_onglets_html}

                {modals_html}
            </div>
        </body>
        </html>
        """
    except Exception as e:
        return HTMLResponse(content=f"<h3>Erreur critique sur le Dashboard :</h3><p>{str(e)}</p><a href='/'>Retour</a>", status_code=500)

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("app_asso:app", host="127.0.0.1", port=8000, reload=True)
