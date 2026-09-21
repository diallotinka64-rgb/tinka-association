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

app = FastAPI(title="API Gestion Tinka ka Mein Haaldi fotti", version="54.0")

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

@app.get("/", response_class=HTMLResponse)
def afficher_portail():
    try:
        url_site = "https://tinka-association.onrender.com"
        qr_b64 = generer_qrcode_base64(url_site)

        try:
            panorama_res = supabase.table("panorama_village").select("*, adherents(nom, prenom)").order("id", desc=True).execute()
            all_panorama = panorama_res.data or []
        except Exception:
            all_panorama = []

        panorama_cards_public = ""
        for pano in all_panorama:
            adh_p = pano.get('adherents', {}) or {}
            auteur_nom = f"{adh_p.get('prenom', '')} {adh_p.get('nom', '')}" if adh_p else "Administration"
            photo_url = pano.get('photo_url', '')
            panorama_cards_public += f"""
            <div class="bg-white rounded-2xl overflow-hidden shadow-sm border border-slate-200 flex flex-col">
                <img src="{photo_url}" class="w-full h-48 object-cover bg-slate-100" onerror="this.onerror=null; this.src='https://images.unsplash.com/photo-1507525428034-b723cf961d3e?w=400&auto=format&fit=crop&q=60';">
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
                                <div><label class="block text-xs font-bold text-slate-600 mb-1">Nom</label><input type="text" name="nom" required class="w-full px-2.5 py-2 text-sm bg-white border border-slate-300 rounded-lg"></div>
                                <div><label class="block text-xs font-bold text-slate-600 mb-1">Prénom</label><input type="text" name="prenom" required class="w-full px-2.5 py-2 text-sm bg-white border border-slate-300 rounded-lg"></div>
                            </div>
                            <div><label class="block text-xs font-bold text-slate-600 mb-1">Téléphone</label><input type="text" name="telephone" required class="w-full px-2.5 py-2 text-sm bg-white border border-slate-300 rounded-lg"></div>
                            <div><label class="block text-xs font-bold text-slate-600 mb-1">Adresse</label><input type="text" name="adresse" required class="w-full px-2.5 py-2 text-sm bg-white border border-slate-300 rounded-lg"></div>
                            <div><label class="block text-xs font-bold text-slate-600 mb-1">Secteur</label><input type="text" name="secteur" required class="w-full px-2.5 py-2 text-sm bg-white border border-slate-300 rounded-lg"></div>
                            <div><label class="block text-xs font-bold text-slate-600 mb-1">Photo de profil</label><input type="file" name="file_photo" accept="image/*" class="w-full text-xs text-slate-500 file:py-2 file:px-3 file:rounded-lg file:border-0 file:bg-emerald-50 file:text-emerald-700"></div>
                            <div><label class="block text-xs font-bold text-slate-600 mb-1">Mot de passe</label><input type="password" name="mot_de_passe" required class="w-full px-2.5 py-2 text-sm bg-white border border-slate-300 rounded-lg"></div>
                            <button type="submit" class="w-full bg-emerald-600 hover:bg-emerald-700 text-white font-bold py-2.5 px-4 rounded-lg shadow text-sm mt-2">S'inscrire</button>
                        </form>
                    </div>
                </div>
            </div>

            <div class="max-w-4xl mx-auto w-full bg-slate-100 p-6 rounded-3xl border border-slate-200 mt-6">
                <h3 class="text-center text-lg font-black text-slate-800 mb-1">🌍 Souvenirs & Panorama du Village</h3>
                <div class="grid grid-cols-1 sm:grid-cols-2 md:grid-cols-3 gap-4 mt-4">
                    {panorama_cards_public or '<p class="col-span-3 text-center text-xs text-slate-400 py-4">Aucune photo de panorama publiée pour le moment.</p>'}
                </div>
            </div>
        </body>
        </html>
        """
    except Exception as e:
        return HTMLResponse(content=f"<h3>Erreur critique :</h3><p>{str(e)}</p>", status_code=500)

@app.api_route("/login-form", methods=["GET", "POST"])
@app.api_route("/login-form/", methods=["GET", "POST"])
def login_form(telephone: Optional[str] = Form(None), mot_de_passe: Optional[str] = Form(None)):
    if not telephone or not mot_de_passe:
        return RedirectResponse(url="/", status_code=303)
    try:
        res = supabase.table("adherents").select("*").eq("telephone", telephone).execute()
        users = res.data or []
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

@app.api_route("/adherents-form", methods=["GET", "POST"])
@app.api_route("/adherents-form/", methods=["GET", "POST"])
async def creer_adherent_form(
    nom: Optional[str] = Form(None), prenom: Optional[str] = Form(None), telephone: Optional[str] = Form(None),
    adresse: Optional[str] = Form(None), secteur: Optional[str] = Form(None),
    mot_de_passe: Optional[str] = Form(None), file_photo: UploadFile = File(None)
):
    if not telephone:
        return RedirectResponse(url="/", status_code=303)
    try:
        existing_user = supabase.table("adherents").select("id").eq("telephone", telephone).execute()
        if existing_user.data:
            return HTMLResponse(content="<script>alert('Erreur : Ce numéro de téléphone est déjà associé à un compte existant.'); window.location.href='/';</script>")

        photo_b64 = await fichier_vers_base64(file_photo)
        mdp_securise = hacher_mdp(mot_de_passe or "123456")

        supabase.table("adherents").insert({
            "nom": nom or "", "prenom": prenom or "", "email": f"{telephone}@tinka.local", "telephone": telephone,
            "adresse": adresse or "", "secteur": secteur or "", "photo_profil": photo_b64, "mot_de_passe": mdp_securise
        }).execute()
        return HTMLResponse(content="<script>alert('Compte créé avec succès ! En attente de validation.'); window.location.href='/';</script>")
    except Exception as e:
        return HTMLResponse(content=f"<script>alert('Erreur lors de l\\'inscription : {str(e)}'); window.location.href='/';</script>")

@app.api_route("/modifier-photo", methods=["GET", "POST"])
async def modifier_photo(user_id: Optional[int] = Form(None), file_photo: Optional[UploadFile] = File(None)):
    if not user_id:
        return RedirectResponse(url="/", status_code=303)
    try:
        if file_photo and file_photo.filename:
            photo_b64 = await fichier_vers_base64(file_photo)
            supabase.table("adherents").update({"photo_profil": photo_b64}).eq("id", user_id).execute()
    except Exception:
        pass
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
        return HTMLResponse(content=f"<script>alert('Solde initial mis à jour avec succès !'); window.location.href='/dashboard?id={user_id}';</script>")
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
        return HTMLResponse(content=f"<script>alert('Paiement mobile validé avec succès !'); window.location.href='/dashboard?id={user_id}';</script>")
    return RedirectResponse(url="/", status_code=303)

@app.api_route("/cotisations-form", methods=["GET", "POST"])
@app.api_route("/cotisations-form/", methods=["GET", "POST"])
def ajouter_cotisation(user_id: Optional[int] = Form(None), adherent_id: Optional[int] = Form(None), montant: Optional[float] = Form(None), periode: Optional[str] = Form(None), mode_paiement: Optional[str] = Form(None)):
    if user_id and adherent_id and montant is not None:
        supabase.table("cotisations").insert({
            "adherent_id": adherent_id, "montant": montant, "periode": periode or "", "mode_paiement": mode_paiement or "especes", "statut_paiement": "valide"
        }).execute()
        return RedirectResponse(url=f"/dashboard?id={user_id}", status_code=status.HTTP_303_SEE_OTHER)
    return RedirectResponse(url="/", status_code=303)

@app.api_route("/paiement-mobile-form", methods=["GET", "POST"])
@app.api_route("/paiement-mobile-form/", methods=["GET", "POST"])
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
        return HTMLResponse(content=f"<script>alert('Paiement déclaré avec succès ! En attente de validation.'); window.location.href='/dashboard?id={user_id}';</script>")
    except Exception as e:
        return HTMLResponse(content=f"<script>alert('Erreur : {str(e)}'); window.location.href='/dashboard?id={user_id}';</script>")

@app.api_route("/aides-form", methods=["GET", "POST"])
@app.api_route("/aides-form/", methods=["GET", "POST"])
def demander_aide(user_id: Optional[int] = Form(None), motif: Optional[str] = Form(None), montant_demande: Optional[float] = Form(None)):
    if user_id:
        supabase.table("aides").insert({
            "adherent_id": user_id, "motif": motif or "", "montant_demande": montant_demande or 0, "statut_validation": "en_attente"
        }).execute()
        return RedirectResponse(url=f"/dashboard?id={user_id}", status_code=status.HTTP_303_SEE_OTHER)
    return RedirectResponse(url="/", status_code=303)

@app.api_route("/decaissements-form", methods=["GET", "POST"])
@app.api_route("/decaissements-form/", methods=["GET", "POST"])
def ajouter_decaissement(user_id: Optional[int] = Form(None), motif: Optional[str] = Form(None), montant: Optional[float] = Form(None), beneficiaire: Optional[str] = Form(None), categorie: Optional[str] = Form(None)):
    if user_id:
        supabase.table("decaissements").insert({
            "motif": motif or "", "montant": montant or 0, "beneficiaire": beneficiaire or "", "categorie": categorie or "Divers"
        }).execute()
        return RedirectResponse(url=f"/dashboard?id={user_id}", status_code=status.HTTP_303_SEE_OTHER)
    return RedirectResponse(url="/", status_code=303)

@app.api_route("/projets-form", methods=["GET", "POST"])
@app.api_route("/projets-form/", methods=["GET", "POST"])
async def ajouter_projet(
    user_id: Optional[int] = Form(None), titre: Optional[str] = Form(None), description: Optional[str] = Form(None), 
    objectifs: Optional[str] = Form(None), cout: Optional[float] = Form(None), file_projet: UploadFile = File(None), 
    chronologie: Optional[str] = Form(None), statut: Optional[str] = Form(None)
):
    if not user_id:
        return RedirectResponse(url="/", status_code=303)
    try:
        photo_b64 = await fichier_vers_base64(file_projet)
        supabase.table("projets").insert({
            "titre": titre or "", "description": description or "", "objectifs": objectifs or "N/A",
            "cout": cout or 0, "photo_projet": photo_b64, "chronologie": chronologie or "N/A", "statut": statut or "En cours"
        }).execute()
    except Exception:
        pass
    return RedirectResponse(url=f"/dashboard?id={user_id}", status_code=status.HTTP_303_SEE_OTHER)

@app.api_route("/evenements-form", methods=["GET", "POST"])
@app.api_route("/evenements-form/", methods=["GET", "POST"])
def ajouter_evenement(
    user_id: Optional[int] = Form(None), titre: Optional[str] = Form(None), description: Optional[str] = Form(None),
    date_evenement: Optional[str] = Form(None), lieu: Optional[str] = Form(None), type_evenement: Optional[str] = Form(None), statut: Optional[str] = Form(None)
):
    if user_id:
        supabase.table("evenements").insert({
            "titre": titre or "", "description": description or "", "date_evenement": date_evenement or "",
            "lieu": lieu or "", "type_evenement": type_evenement or "", "statut": statut or "Prevu"
        }).execute()
        return RedirectResponse(url=f"/dashboard?id={user_id}", status_code=status.HTTP_303_SEE_OTHER)
    return RedirectResponse(url="/", status_code=303)

@app.api_route("/panorama-form", methods=["GET", "POST"])
@app.api_route("/panorama-form/", methods=["GET", "POST"])
async def ajouter_panorama(user_id: Optional[int] = Form(None), legende: Optional[str] = Form(None), files_photos: List[UploadFile] = File([])):
    if not user_id:
        return RedirectResponse(url="/", status_code=303)
    try:
        for file_photo in files_photos:
            if file_photo and file_photo.filename:
                photo_b64 = await fichier_vers_base64(file_photo)
                if photo_b64:
                    supabase.table("panorama_village").insert({
                        "legende": legende or "", "photo_url": photo_b64, "auteur_id": user_id
                    }).execute()
    except Exception as e:
        print(f"Erreur panorama: {e}")
    return RedirectResponse(url=f"/dashboard?id={user_id}", status_code=status.HTTP_303_SEE_OTHER)

@app.api_route("/presences-form", methods=["GET", "POST"])
@app.api_route("/presences-form/", methods=["GET", "POST"])
def enregistrer_presence(user_id: Optional[int] = Form(None), adherent_id: Optional[int] = Form(None), evenement_titre: Optional[str] = Form(None), statut_presence: Optional[str] = Form(None), date_reunion: Optional[str] = Form(None)):
    if user_id and adherent_id:
        try:
            supabase.table("presences_association").insert({
                "adherent_id": adherent_id, "evenement_titre": evenement_titre or "", "statut_presence": statut_presence or "Present", "date_reunion": date_reunion or ""
            }).execute()
        except Exception:
            pass
        return RedirectResponse(url=f"/dashboard?id={user_id}", status_code=status.HTTP_303_SEE_OTHER)
    return RedirectResponse(url="/", status_code=303)

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

@app.get("/cotisations/export-pdf")
def export_cotisations_pdf(periode: Optional[str] = Query(None)):
    query = supabase.table("cotisations").select("*, adherents(nom, prenom, secteur)").eq("statut_paiement", "valide")
    if periode:
        query = query.eq("periode", periode)
        titre_rapport = f"Tinka ka Mein Haaldi fotti - Rapport des Cotisations ({periode})"
    else:
        titre_rapport = "Tinka ka Mein Haaldi fotti - Rapport Global des Cotisations"
    
    res = query.execute()
    cotis = res.data or []

    buffer = io.BytesIO()
    p = canvas.Canvas(buffer, pagesize=letter)
    width, height = letter

    p.setFont("Helvetica-Bold", 14)
    p.drawString(50, height - 40, "TINKA KA MEIN HAALDI FOTTI")
    p.setFont("Helvetica", 9)
    p.drawString(50, height - 55, "Bureau Exécutif & Conseil - Rapport Officiel")
    p.line(50, height - 65, width - 50, height - 65)

    p.setFont("Helvetica-Bold", 13)
    p.drawString(50, height - 95, titre_rapport)

    p.setFont("Helvetica", 10)
    y = height - 130
    total = 0
    for c in cotis:
        adh = c.get('adherents', {}) or {}
        p.drawString(50, y, f"- {adh.get('prenom','')} {adh.get('nom','')} ({adh.get('secteur','')}) | Période: {c.get('periode','')} | Montant: {formater_montant(c.get('montant',0))} CFA")
        total += c.get('montant', 0)
        y -= 20
        if y < 50:
            p.showPage()
            y = height - 50

    p.setFont("Helvetica-Bold", 11)
    p.drawString(50, y - 10, f"Total Général : {formater_montant(total)} CFA")
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

@app.api_route("/dashboard", methods=["GET", "POST"])
def afficher_dashboard(id: Optional[int] = Query(None), filtre_periode: Optional[str] = Query(None)):
    if not id:
        return RedirectResponse(url="/", status_code=303)
    try:
        user_res = supabase.table("adherents").select("*").eq("id", id).execute()
        if not user_res.data:
            return RedirectResponse(url="/", status_code=303)
        user = user_res.data[0]

        is_admin = user.get('role') == 'admin'
        is_tresorier = user.get('role') in ['admin', 'tresorier']

        annee_courante = datetime.datetime.now().year
        mois_12 = [f"{annee_courante}-{m:02d}" for m in range(9, 13)] + [f"{annee_courante+1}-{m:02d}" for m in range(1, 9)]

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

        try:
            all_panorama = supabase.table("panorama_village").select("*, adherents(nom, prenom)").order("id", desc=True).execute().data or []
        except Exception:
            all_panorama = []

        param_res = supabase.table("parametres").select("solde_initial").eq("id", 1).execute()
        solde_initial = param_res.data[0]['solde_initial'] if param_res.data else 0.0

        cotisations_caisse = sum([c['montant'] for c in all_cotisations if "regularisation" not in str(c.get('mode_paiement', '')) and c.get('statut_paiement', 'valide') == 'valide'])
        total_aides_approuvees = sum([ai['montant_demande'] for ai in all_aides if ai.get('statut_validation') == 'approuve'])
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
                    <h4 class="font-bold text-base text-indigo-950">{pr.get('titre', '')}</h4>
                    <span class="text-xs font-bold px-2.5 py-1 rounded-full bg-indigo-100 text-indigo-800 uppercase">{pr.get('statut', '')}</span>
                </div>
                <p class="text-xs text-slate-600 mb-3 leading-relaxed">{pr.get('description', '')}</p>
                <div class="text-xs text-slate-600 space-y-1.5 bg-white p-3 rounded-xl border border-slate-100">
                    <div><b>🎯 Objectifs :</b> {pr.get('objectifs', 'Non spécifié')}</div>
                    <div><b>📅 Planning :</b> {pr.get('chronologie', 'Non spécifié')}</div>
                    <div class="font-bold text-emerald-700">💰 Budget estimé : {formater_montant(pr.get('cout', 0))} CFA</div>
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
                <img src="{photo_url}" class="w-full h-44 object-cover bg-slate-100" onerror="this.onerror=null; this.src='https://images.unsplash.com/photo-1507525428034-b723cf961d3e?w=400&auto=format&fit=crop&q=60';">
                <div class="p-3 flex-1 flex flex-col justify-between">
                    <p class="text-xs font-semibold text-slate-800 mb-2">"{pano.get('legende', '')}"</p>
                    <span class="text-[10px] font-bold text-emerald-700 bg-emerald-50 px-2 py-0.5 rounded-full self-start">📸 Publié par {auteur_nom}</span>
                </div>
            </div>
            """

        finance_sections_html = ""
        if is_tresorier:
            options_adherents = "".join([f"<option value='{a['id']}'>{a.get('prenom','')} {a.get('nom','')} — Secteur: {a.get('secteur','')} (Tél: {a.get('telephone','')})</option>" for a in all_actifs if a.get('role') != 'admin'])
            
            suivi_retards_html = ""
            for a in all_actifs:
                cotis_membre = [c['periode'] for c in all_cotisations if c.get('adherent_id') == a['id'] and c.get('statut_paiement') == 'valide']
                mois_manquants = [m for m in mois_12 if m not in cotis_membre]
                statut_ajour = "<span class='text-emerald-600 font-bold'>À jour</span>" if not mois_manquants else f"<span class='text-red-600 font-bold'>Retard ({len(mois_manquants)} mois)</span>"
                suivi_retards_html += f"<li class='py-1.5 border-b border-slate-100 flex justify-between items-center text-sm'><span><b>{a.get('prenom','')} {a.get('nom','')}</b> <span class='text-xs text-slate-400'>({a.get('secteur','')})</span></span> {statut_ajour}</li>"

            paiements_mobiles_admin = [c for c in all_cotisations if "mobile_" in str(c.get('mode_paiement', ''))]
            paiements_mobiles_rows = ""
            for pm in paiements_mobiles_admin:
                adh_pm = pm.get('adherents', {}) or {}
                st_paiement = pm.get('statut_paiement', 'en_attente')
                action_cell = f"""
                <form action="/admin/valider-paiement-mobile" method="POST" class="inline">
                    <input type="hidden" name="user_id" value="{user['id']}"><input type="hidden" name="paiement_id" value="{pm['id']}">
                    <button type="submit" class="bg-amber-600 text-white px-3 py-1.5 rounded text-xs font-bold shadow">⏳ Valider</button>
                </form>
                """ if st_paiement != 'valide' else f"""
                <span class="text-xs font-bold text-emerald-700 bg-emerald-100 px-2 py-0.5 rounded-full mr-2">Validé</span>
                <a href="/cotisation/recu-pdf/{pm['id']}" target="_blank" class="bg-blue-600 text-white px-2.5 py-1 rounded text-xs font-bold">📄 PDF</a>
                """
                paiements_mobiles_rows += f"""
                <tr class="hover:bg-slate-50 border-b text-sm">
                    <td class="p-2.5 font-bold">{adh_pm.get('prenom','')} {adh_pm.get('nom','')}</td>
                    <td class="p-2.5 font-semibold text-blue-700 uppercase">{pm.get('mode_paiement','')}</td>
                    <td class="p-2.5 font-bold text-emerald-700">{formater_montant(pm.get('montant',0))} CFA</td>
                    <td class="p-2.5 text-slate-600">{pm.get('periode','')}</td>
                    <td class="p-2.5 text-right">{action_cell}</td>
                </tr>
                """

            aides_admin_html = ""
            for ai in all_aides:
                adh_aide = ai.get('adherents', {}) or {}
                st_aide = ai.get('statut_validation', 'en_attente')
                actions_aide = f"""
                <form action="/admin/valider-aide" method="POST" class="inline-block"><input type="hidden" name="user_id" value="{user['id']}"><input type="hidden" name="aide_id" value="{ai['id']}"><input type="hidden" name="statut_validation" value="approuve"><button type="submit" class="bg-emerald-600 text-white px-2 py-1 rounded text-xs font-bold mr-1">Approuver</button></form>
                <form action="/admin/valider-aide" method="POST" class="inline-block"><input type="hidden" name="user_id" value="{user['id']}"><input type="hidden" name="aide_id" value="{ai['id']}"><input type="hidden" name="statut_validation" value="refuse"><button type="submit" class="bg-red-600 text-white px-2 py-1 rounded text-xs font-bold">Refuser</button></form>
                """ if st_aide == 'en_attente' else f"<span class='text-xs font-bold px-2 py-1 rounded-full bg-slate-100'>{st_aide.upper()}</span>"
                aides_admin_html += f"<li class='py-2 border-b flex justify-between items-center text-sm'><div><b>{adh_aide.get('prenom','')} {adh_aide.get('nom','')}</b> — {ai.get('motif','')} <span class='text-amber-700 font-bold'>({formater_montant(ai.get('montant_demande',0))} CFA)</span></div><div>{actions_aide}</div></li>"

            adherents_table_rows = ""
            modals_html = ""
            for a in all_adherents:
                actions_admin = ""
                if a.get('statut') == 'en_attente':
                    actions_admin += f"""
                    <form action="/admin/valider-adherent" method="POST" class="inline"><input type="hidden" name="user_id" value="{user['id']}"><input type="hidden" name="adherent_id" value="{a['id']}"><button type="submit" class="bg-emerald-600 text-white px-2 py-1 rounded text-xs font-bold">Valider</button></form>
                    """
                if is_admin:
                    actions_admin += f"""
                    <form action="/admin/changer-role" method="POST" class="inline-block ml-1">
                        <input type="hidden" name="user_id" value="{user['id']}"><input type="hidden" name="adherent_id" value="{a['id']}">
                        <select name="nouveau_role" onchange="this.form.submit()" class="p-1 text-xs border rounded bg-white text-blue-700 font-semibold">
                            <option value="membre" {'selected' if a.get('role')=='membre' else ''}>Membre</option>
                            <option value="tresorier" {'selected' if a.get('role')=='tresorier' else ''}>Trésorier</option>
                            <option value="admin" {'selected' if a.get('role')=='admin' else ''}>Admin</option>
                        </select>
                    </form>
                    """

                photo_tag = f"<img src='{a['photo_profil']}' class='w-7 h-7 rounded-full object-cover mr-2' onerror='this.style.display=\"none\"'>" if a.get('photo_profil') else f"<div class='w-7 h-7 rounded-full bg-slate-200 flex items-center justify-center font-bold text-slate-500 text-[10px] mr-2'>{a.get('prenom','M')[0]}</div>"
                
                adherents_table_rows += f"""
                <tr class="hover:bg-slate-50 border-b text-sm">
                    <td class="p-2.5 flex items-center font-medium">{photo_tag}{a.get('prenom','')} {a.get('nom','')}</td>
                    <td class="p-2.5"><span class="text-xs bg-slate-100 px-2 py-0.5 rounded uppercase">{a.get('role','')}</span></td>
                    <td class="p-2.5">{a.get('secteur','')}</td>
                    <td class="p-2.5 font-mono text-xs">{a.get('telephone','')}</td>
                    <td class="p-2.5 text-right">{actions_admin}<button onclick="openModal({a['id']})" class="bg-blue-50 text-blue-700 px-2 py-1 rounded text-xs font-bold ml-1">⚙️</button></td>
                </tr>
                """

                modals_html += f"""
                <div id="modal-{a['id']}" class="fixed inset-0 bg-black/50 z-50 hidden flex items-center justify-center p-4">
                    <div class="bg-white rounded-2xl max-w-lg w-full p-6 shadow-2xl border">
                        <div class="flex justify-between items-center mb-4 border-b pb-2"><h3 class="font-bold text-lg">Modifier : {a.get('prenom','')} {a.get('nom','')}</h3><button onclick="closeModal({a['id']})" class="font-bold text-lg">✕</button></div>
                        <form action="/admin/modifier-adherent" method="POST" class="space-y-3 mb-6">
                            <input type="hidden" name="user_id" value="{user['id']}"><input type="hidden" name="adherent_id" value="{a['id']}">
                            <div class="grid grid-cols-2 gap-3">
                                <div><label class="block text-xs font-bold mb-1">Prénom</label><input type="text" name="prenom" value="{a.get('prenom','')}" required class="w-full p-2 text-sm border rounded"></div>
                                <div><label class="block text-xs font-bold mb-1">Nom</label><input type="text" name="nom" value="{a.get('nom','')}" required class="w-full p-2 text-sm border rounded"></div>
                            </div>
                            <div class="grid grid-cols-2 gap-3">
                                <div><label class="block text-xs font-bold mb-1">Téléphone</label><input type="text" name="telephone" value="{a.get('telephone','')}" required class="w-full p-2 text-sm border rounded"></div>
                                <div><label class="block text-xs font-bold mb-1">Secteur</label><input type="text" name="secteur" value="{a.get('secteur','')}" required class="w-full p-2 text-sm border rounded"></div>
                            </div>
                            <button type="submit" class="w-full bg-emerald-600 text-white py-2 rounded text-sm font-bold">Enregistrer</button>
                        </form>
                    </div>
                </div>
                """

            presences_table_rows = "".join([f"<tr class='border-b text-sm'><td class='p-2.5 font-bold'>{p.get('adherents',{}).get('prenom','')} {p.get('adherents',{}).get('nom','')}</td><td class='p-2.5'>{p.get('evenement_titre','')}</td><td class='p-2.5'>{formater_date(p.get('date_reunion',''))}</td><td class='p-2.5'><span class='text-xs px-2 py-0.5 rounded-full font-bold bg-emerald-100 text-emerald-800'>{p.get('statut_presence','')}</span></td></tr>" for p in all_presences])
            options_presence_adherents = "".join([f"<option value='{a['id']}'>{a.get('prenom','')} {a.get('nom','')} — {a.get('secteur','')}</option>" for a in all_actifs])
            options_evenements_titres = "".join([f"<option value='{ev.get('titre','')}'>{ev.get('titre','')}</option>" for ev in all_evenements]) or "<option value='Réunion Générale'>Réunion Générale</option>"

            finance_sections_html = f"""
            <div class="flex flex-wrap gap-2 mb-6 border-b pb-3">
                <button onclick="switchTab('tab-tresorerie')" id="btn-tab-tresorerie" class="tab-btn px-4 py-2 text-xs font-bold rounded-xl bg-slate-900 text-white shadow-md">💼 Trésorerie</button>
                <button onclick="switchTab('tab-adherents')" id="btn-tab-adherents" class="tab-btn px-4 py-2 text-xs font-bold rounded-xl bg-white text-slate-700 border shadow-sm">👥 Annuaire</button>
                <button onclick="switchTab('tab-pointage')" id="btn-tab-pointage" class="tab-btn px-4 py-2 text-xs font-bold rounded-xl bg-white text-slate-700 border shadow-sm">📋 Pointage</button>
                <button onclick="switchTab('tab-projets')" id="btn-tab-projets" class="tab-btn px-4 py-2 text-xs font-bold rounded-xl bg-white text-slate-700 border shadow-sm">🚀 Projets</button>
                <button onclick="switchTab('tab-panorama')" id="btn-tab-panorama" class="tab-btn px-4 py-2 text-xs font-bold rounded-xl bg-white text-slate-700 border shadow-sm">🌍 Panorama</button>
                <button onclick="switchTab('tab-profil')" id="btn-tab-profil" class="tab-btn px-4 py-2 text-xs font-bold rounded-xl bg-white text-slate-700 border shadow-sm">🖼️ Profil</button>
            </div>

            <!-- ONGLET 1 -->
            <div id="tab-tresorerie" class="tab-content space-y-6">
                <div class="bg-white p-6 rounded-2xl shadow-sm border">
                    <h2 class="text-base font-bold mb-4 border-b pb-2">💼 Trésorerie & Solde</h2>
                    <form action="/admin/maj-solde-initial" method="POST" class="bg-emerald-50 p-4 rounded-xl border mb-6 flex gap-3 items-end">
                        <input type="hidden" name="user_id" value="{user['id']}">
                        <div class="flex-1"><label class="block text-xs font-bold text-emerald-800 mb-1">Solde Initial Réel en Caisse</label><input type="number" name="solde_initial" value="{solde_initial}" required class="w-full p-2.5 text-sm bg-white border rounded"></div>
                        <button type="submit" class="bg-emerald-600 text-white font-bold py-2.5 px-5 rounded text-sm shadow">Mettre à jour</button>
                    </form>
                    <div class="text-center bg-slate-900 text-white py-3 rounded-xl font-bold text-base mb-6">Solde Réel en Caisse : <span class="text-emerald-400">{formater_montant(solde)} CFA</span></div>
                    <h3 class="text-xs font-bold text-slate-600 mb-2 uppercase">État des cotisations membres</h3>
                    <ul class="max-h-60 overflow-y-auto">{suivi_retards_html}</ul>
                </div>
                <div class="bg-white p-6 rounded-2xl shadow-sm border">
                    <h2 class="text-base font-bold mb-2 border-b pb-2">📱 Paiements Mobile Money</h2>
                    <div class="overflow-x-auto max-h-60 overflow-y-auto border rounded-xl">
                        <table class="w-full text-left bg-white"><thead class="bg-slate-100 text-xs uppercase"><tr><th class="p-2.5">Adhérent</th><th class="p-2.5">Détails</th><th class="p-2.5">Montant</th><th class="p-2.5">Période</th><th class="p-2.5 text-right">Action</th></tr></thead><tbody>{paiements_mobiles_rows or '<tr><td colspan="5" class="p-4 text-center text-sm text-slate-400">Aucun paiement.</td></tr>'}</tbody></table>
                    </div>
                </div>
            </div>

            <!-- ONGLET 2 -->
            <div id="tab-adherents" class="tab-content hidden space-y-6">
                <div class="bg-white p-6 rounded-2xl shadow-sm border">
                    <div class="flex justify-between items-center mb-4 border-b pb-2"><h2 class="text-base font-bold">👥 Annuaire ({len(all_adherents)})</h2><a href="/adherents/export-pdf" target="_blank" class="bg-red-600 text-white px-3 py-1.5 rounded text-xs font-bold">📄 PDF</a></div>
                    <div class="overflow-x-auto max-h-96 overflow-y-auto border rounded-xl"><table class="w-full text-left bg-white"><thead class="bg-slate-100 text-xs uppercase"><tr><th class="p-2.5">Nom & Prénom</th><th class="p-2.5">Rôle</th><th class="p-2.5">Secteur</th><th class="p-2.5">Téléphone</th><th class="p-2.5 text-right">Actions</th></tr></thead><tbody>{adherents_table_rows}</tbody></table></div>
                </div>
            </div>

            <!-- ONGLET 3 -->
            <div id="tab-pointage" class="tab-content hidden space-y-6">
                <div class="bg-white p-6 rounded-2xl shadow-sm border">
                    <h2 class="text-base font-bold mb-4 border-b pb-2">📋 Pointage</h2>
                    <form action="/presences-form" method="POST" class="space-y-4">
                        <input type="hidden" name="user_id" value="{user['id']}">
                        <div class="grid grid-cols-2 gap-3">
                            <div><label class="block text-xs font-bold mb-1">Événement</label><select name="evenement_titre" required class="w-full p-2.5 border rounded bg-white">{options_evenements_titres}</select></div>
                            <div><label class="block text-xs font-bold mb-1">Date</label><input type="date" name="date_reunion" required class="w-full p-2.5 border rounded bg-white"></div>
                        </div>
                        <div><label class="block text-xs font-bold mb-1">Membre</label><select name="adherent_id" required class="w-full p-2.5 border rounded bg-white" size="4">{options_presence_adherents}</select></div>
                        <div><label class="block text-xs font-bold mb-1">Statut</label><select name="statut_presence" required class="w-full p-2.5 border rounded bg-white"><option value="Present">🟢 Présent(e)</option><option value="Absent_excuse">🟡 Excusé(e)</option></select></div>
                        <button type="submit" class="w-full bg-teal-600 text-white font-bold py-2.5 rounded text-sm shadow">Enregistrer</button>
                    </form>
                </div>
            </div>

            <!-- ONGLET 4 -->
            <div id="tab-projets" class="tab-content hidden space-y-6">
                <div class="bg-white p-6 rounded-2xl shadow-sm border">
                    <h2 class="text-base font-bold mb-4 border-b pb-2">🤝 Demandes d'Aide</h2>
                    <ul class="max-h-60 overflow-y-auto">{aides_admin_html or '<p class="text-sm text-slate-400">Aucune demande.</p>'}</ul>
                </div>
                <div class="bg-white p-6 rounded-2xl shadow-sm border">
                    <h2 class="text-base font-bold mb-4 border-b pb-2">🚀 Projets</h2>
                    <form action="/projets-form" method="POST" enctype="multipart/form-data" class="space-y-3 mb-6">
                        <input type="hidden" name="user_id" value="{user['id']}">
                        <div class="grid grid-cols-2 gap-3">
                            <div><label class="block text-xs font-bold mb-1">Titre</label><input type="text" name="titre" required class="w-full p-2 border rounded"></div>
                            <div><label class="block text-xs font-bold mb-1">Coût (CFA)</label><input type="number" name="cout" required class="w-full p-2 border rounded"></div>
                        </div>
                        <div><label class="block text-xs font-bold mb-1">Description</label><textarea name="description" rows="2" required class="w-full p-2 border rounded"></textarea></div>
                        <div><label class="block text-xs font-bold mb-1">Photo</label><input type="file" name="file_projet" accept="image/*" class="w-full text-xs"></div>
                        <button type="submit" class="w-full bg-indigo-600 text-white font-bold py-2 rounded text-sm shadow">Ajouter</button>
                    </form>
                    <div class="max-h-96 overflow-y-auto">{projets_cards_html or '<p class="text-xs text-slate-400">Aucun projet.</p>'}</div>
                </div>
            </div>

            <!-- ONGLET 5 -->
            <div id="tab-panorama" class="tab-content hidden space-y-6">
                <div class="bg-white p-6 rounded-2xl shadow-sm border">
                    <h2 class="text-base font-bold mb-4 border-b pb-2">🌍 Panorama Village</h2>
                    <form action="/panorama-form" method="POST" enctype="multipart/form-data" class="space-y-3">
                        <input type="hidden" name="user_id" value="{user['id']}">
                        <div><label class="block text-xs font-bold mb-1">Légende</label><input type="text" name="legende" required class="w-full p-2 border rounded"></div>
                        <div><label class="block text-xs font-bold mb-1">Photos</label><input type="file" name="files_photos" accept="image/*" multiple required class="w-full text-xs"></div>
                        <button type="submit" class="w-full bg-emerald-600 text-white font-bold py-2.5 rounded text-sm shadow">Publier</button>
                    </form>
                </div>
            </div>

            <!-- ONGLET 6 -->
            <div id="tab-profil" class="tab-content hidden space-y-6">
                <div class="bg-white p-6 rounded-2xl shadow-sm border">
                    <h2 class="text-base font-bold mb-4 border-b pb-2">🖼️ Mon Profil</h2>
                    <form action="/modifier-photo" method="POST" enctype="multipart/form-data" class="space-y-3">
                        <input type="hidden" name="user_id" value="{user['id']}">
                        <input type="file" name="file_photo" accept="image/*" required class="w-full text-xs">
                        <button type="submit" class="w-full bg-slate-800 text-white font-bold py-2 rounded text-sm shadow">Mettre à jour</button>
                    </form>
                </div>
            </div>

            {modals_html}
            """

        member_sections_html = ""
        if not is_tresorier:
            cotis_perso = [c for c in all_cotisations if c.get('adherent_id') == user['id']]
            mois_payes_html = "".join([f"<li class='py-2 border-b text-sm flex justify-between'><span>Mois de <b>{c.get('periode','')}</b> : Payé ({formater_montant(c.get('montant',0))} CFA)</span><a href='/cotisation/recu-pdf/{c['id']}' target='_blank' class='bg-blue-600 text-white px-2 py-0.5 rounded text-xs font-semibold'>PDF</a></li>" for c in cotis_perso if c.get('statut_paiement') == 'valide'])
            
            member_sections_html = f"""
            <div class="bg-gradient-to-br from-slate-900 to-emerald-950 text-white p-6 rounded-3xl shadow-xl mb-6">
                <h2 class="text-xl font-black">{user.get('prenom','')} {user.get('nom','')}</h2>
                <p class="text-xs text-slate-300">Secteur : {user.get('secteur','')} | Tél : {user.get('telephone','')}</p>
                <div class="bg-white p-2 rounded-xl inline-block mt-4"><img src="data:image/png;base64,{qr_perso_b64}" class="w-20 h-20 rounded"></div>
            </div>
            <div class="bg-white p-6 rounded-2xl shadow-sm border mb-6">
                <h2 class="text-base font-bold mb-4 border-b pb-2">🖼️ Ma Photo de Profil</h2>
                <form action="/modifier-photo" method="POST" enctype="multipart/form-data" class="space-y-3">
                    <input type="hidden" name="user_id" value="{user['id']}">
                    <input type="file" name="file_photo" accept="image/*" required class="w-full text-xs">
                    <button type="submit" class="w-full bg-slate-800 text-white font-bold py-2 rounded text-sm shadow">Mettre à jour</button>
                </form>
            </div>
            <div class="bg-white p-6 rounded-2xl shadow-sm border mb-6">
                <h2 class="text-base font-bold mb-4 border-b pb-2">📱 Déclarer un Paiement Mobile</h2>
                <form action="/paiement-mobile-form" method="POST" class="space-y-3">
                    <input type="hidden" name="user_id" value="{user['id']}">
                    <div class="grid grid-cols-3 gap-2">
                        <select name="operateur" class="p-2 border rounded text-sm"><option value="Wave">Wave</option><option value="OrangeMoney">Orange Money</option></select>
                        <input type="text" name="telephone_paiement" value="{user.get('telephone','')}" required class="p-2 border rounded text-sm" placeholder="Mon Tél">
                        <input type="text" name="numero_recepteur" required class="p-2 border rounded text-sm" placeholder="N° Récepteur">
                    </div>
                    <div class="grid grid-cols-3 gap-2">
                        <input type="text" name="reference_transaction" required class="p-2 border rounded text-sm" placeholder="Réf. Transaction">
                        <input type="number" name="montant" required class="p-2 border rounded text-sm" placeholder="Montant">
                        <input type="text" name="periode" required class="p-2 border rounded text-sm" placeholder="Mois (ex: 2026-09)">
                    </div>
                    <button type="submit" class="w-full bg-blue-600 text-white font-bold py-2 rounded text-sm shadow">Soumettre</button>
                </form>
            </div>
            <div class="bg-white p-6 rounded-2xl shadow-sm border mb-6">
                <h2 class="text-base font-bold mb-4 border-b pb-2">📋 Mes Cotisations</h2>
                <ul class="max-h-60 overflow-y-auto">{mois_payes_html or '<p class="text-sm text-slate-400">Aucun versement validé.</p>'}</ul>
            </div>
            """

        user_photo = f"<img src='{user.get('photo_profil','')}' class='w-16 h-16 rounded-full object-cover shadow-sm' onerror='this.style.display=\"none\"'>" if user.get('photo_profil') else f"<div class='w-16 h-16 rounded-full bg-slate-200 flex items-center justify-center font-bold text-slate-500 text-xl'>{user.get('prenom','M')[0]}</div>"

        return f"""
        <!DOCTYPE html>
        <html lang="fr">
        <head>
            <meta charset="UTF-8"><meta name="viewport" content="width=device-width, initial-scale=1.0"><title>Dashboard</title>
            <script src="https://cdn.tailwindcss.com"></script>
            <script>
                function switchTab(tabId) {{
                    let contents = document.getElementsByClassName('tab-content');
                    for (let c of contents) c.classList.add('hidden');
                    document.getElementById(tabId).classList.remove('hidden');
                    let buttons = document.getElementsByClassName('tab-btn');
                    for (let b of buttons) {{
                        b.classList.remove('bg-slate-900', 'text-white', 'shadow-md');
                        b.classList.add('bg-white', 'text-slate-700', 'border', 'shadow-sm');
                    }}
                    let activeBtn = document.getElementById('btn-' + tabId);
                    if (activeBtn) {{
                        activeBtn.classList.remove('bg-white', 'text-slate-700', 'border', 'shadow-sm');
                        activeBtn.classList.add('bg-slate-900', 'text-white', 'shadow-md');
                    }}
                }}
                function openModal(id) {{ document.getElementById('modal-' + id).classList.remove('hidden'); }}
                function closeModal(id) {{ document.getElementById('modal-' + id).classList.add('hidden'); }}
            </script>
        </head>
        <body class="bg-slate-50 text-slate-800 font-sans min-h-screen py-6 px-4">
            <div class="max-w-4xl mx-auto">
                <div class="bg-white p-6 rounded-2xl shadow-sm border mb-6 flex justify-between items-center">
                    <div class="flex items-center gap-4">{user_photo}<div><h2 class="text-base font-bold">{user.get('prenom','')} {user.get('nom','')}</h2><p class="text-xs text-slate-500 uppercase font-bold text-blue-600">{user.get('role','')}</p></div></div>
                    <a href="/" class="bg-red-600 text-white px-4 py-2 rounded text-xs font-bold">Déconnexion</a>
                </div>
                {finance_sections_html}
                {member_sections_html}
                <div class="bg-white p-6 rounded-3xl shadow-sm border mt-8">
                    <h3 class="text-center text-base font-black mb-4">🌍 Panorama du Village</h3>
                    <div class="grid grid-cols-1 sm:grid-cols-3 gap-4">{panorama_cards_html or '<p class="col-span-3 text-center text-xs text-slate-400">Aucune photo.</p>'}</div>
                </div>
            </div>
        </body>
        </html>
        """
    except Exception as e:
        return HTMLResponse(content=f"<h3>Erreur critique sur le Dashboard :</h3><p>{str(e)}</p><a href='/'>Retour</a>", status_code=500)

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("app_asso:app", host="127.0.0.1", port=8000, reload=True)
