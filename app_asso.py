# =====================================================================
#  TINKA KA MEIN HAALDI FOTTI — Application de gestion d'association
#  Version 80 (sécurisée) — FastAPI + Supabase
#
#  Variables d'environnement (Render → Environment) :
#     SUPABASE_URL, SUPABASE_KEY      (déjà en place)
#     SESSION_SECRET                  (NOUVEAU : longue chaîne aléatoire, à garder secrète)
#     COTISATION_MENSUELLE            (optionnel, défaut 5000)
#  Commande de démarrage Render (inchangée) : uvicorn app_asso:app --host 0.0.0.0 --port $PORT
# =====================================================================

import base64
import csv
import datetime
import hmac
import json
import uuid
import html
import io
import logging
import os
import re
import secrets
import time
import urllib.parse
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor
from typing import Optional

import bcrypt
import qrcode
from fastapi import FastAPI, File, Form, Request, UploadFile
from fastapi.responses import HTMLResponse, RedirectResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from reportlab.lib.pagesizes import A4
from reportlab.pdfgen import canvas
from starlette.middleware.sessions import SessionMiddleware
from supabase import Client, create_client

logging.basicConfig(level=logging.INFO)
log = logging.getLogger("tinka")

# ---------------------------------------------------------------------
#  Configuration
# ---------------------------------------------------------------------
NOM_ASSO = "Tinka ka Mein Haaldi fotti"
URL_SITE = os.getenv("APP_URL", "https://tinka-association.onrender.com")
COTISATION_MENSUELLE = int(os.getenv("COTISATION_MENSUELLE", "5000"))
MOIS_SUIVIS = 6
DEVISE = "CFA"
TAILLE_MAX_PHOTO = 1_500_000  # 1,5 Mo

SESSION_SECRET = os.getenv("SESSION_SECRET")
if not SESSION_SECRET:
    SESSION_SECRET = secrets.token_hex(32)
    log.warning("SESSION_SECRET absent : clé temporaire générée, les membres seront "
                "déconnectés à chaque redémarrage. Ajoutez SESSION_SECRET sur Render.")

app = FastAPI(title=f"API Gestion {NOM_ASSO}", version="80.0")
# Pas de CORS ouvert : l'application sert ses propres pages. Un CORS "*" avec
# cookies permettrait à n'importe quel site de lire les données d'un membre connecté.
app.add_middleware(
    SessionMiddleware,
    secret_key=SESSION_SECRET,
    session_cookie="tinka_session",
    max_age=60 * 60 * 24 * 7,           # 7 jours
    same_site="lax",                     # bloque les formulaires envoyés depuis un autre site
    https_only=bool(os.getenv("RENDER")),
)

SUPABASE_URL = os.getenv("SUPABASE_URL", "")
SUPABASE_KEY = os.getenv("SUPABASE_KEY", "")
supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)

UPLOAD_DIR = "static/uploads"
os.makedirs(UPLOAD_DIR, exist_ok=True)
app.mount("/static", StaticFiles(directory="static"), name="static")

MOIS_FR = ["", "janvier", "février", "mars", "avril", "mai", "juin", "juillet",
           "août", "septembre", "octobre", "novembre", "décembre"]
MOIS_COURT = ["", "Jan", "Fév", "Mar", "Avr", "Mai", "Juin", "Juil", "Aoû",
              "Sep", "Oct", "Nov", "Déc"]
ROLES = ("membre", "tresorier", "admin")

# Colonnes lues pour les listes (sans la photo base64 ni le mot de passe : bien plus rapide)
COLONNES_ADHERENT = "id,nom,prenom,telephone,secteur,role,statut"


# ---------------------------------------------------------------------
#  Utilitaires
# ---------------------------------------------------------------------
def h(valeur) -> str:
    """Échappe toute donnée saisie par un utilisateur avant de l'insérer en HTML."""
    return html.escape("" if valeur is None else str(valeur), quote=True)


def normaliser_telephone(tel: str) -> str:
    if not tel:
        return ""
    nettoye = "".join(c for c in str(tel) if c.isdigit())
    if nettoye.startswith("00"):
        nettoye = nettoye[2:]
    for indicatif in ["221", "224", "223", "225", "33"]:
        if nettoye.startswith(indicatif) and len(nettoye) > 9:
            nettoye = nettoye[len(indicatif):]
            break
    return nettoye


def formater_montant(montant_v) -> str:
    try:
        return f"{int(float(montant_v or 0)):,}".replace(",", " ")
    except Exception:
        return str(montant_v)


def formater_date(date_str) -> str:
    if not date_str:
        return ""
    try:
        annee, mois, jour = str(date_str)[:10].split("-")
        return f"{jour}-{mois}-{annee}"
    except Exception:
        return str(date_str)


montant = formater_montant
date_fr = formater_date


def hacher_mdp(mdp: str) -> str:
    return bcrypt.hashpw(mdp.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")


def est_hache(valeur: str) -> bool:
    return str(valeur or "").startswith(("$2a$", "$2b$", "$2y$"))


def verifier_mdp(mdp: str, stocke: str) -> bool:
    if not stocke:
        return False
    if est_hache(stocke):
        try:
            return bcrypt.checkpw(mdp.encode("utf-8"), stocke.encode("utf-8"))
        except Exception:
            return False
    # Ancien mot de passe en clair : comparaison à temps constant (il sera re-haché à la connexion)
    return hmac.compare_digest(mdp.encode("utf-8"), str(stocke).encode("utf-8"))


def generer_qrcode_base64(texte: str) -> str:
    qr = qrcode.QRCode(box_size=4, border=2)
    qr.add_data(texte)
    qr.make(fit=True)
    img = qr.make_image(fill_color="black", back_color="white")
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return base64.b64encode(buf.getvalue()).decode("utf-8")


async def photo_vers_base64(fichier: Optional[UploadFile]) -> str:
    if not fichier or not fichier.filename:
        return ""
    type_mime = (fichier.content_type or "").lower()
    if type_mime not in ("image/jpeg", "image/png", "image/webp", "image/gif"):
        raise ValueError("La photo doit être une image JPEG, PNG ou WEBP.")
    contenu = await fichier.read(TAILLE_MAX_PHOTO + 1)
    if len(contenu) > TAILLE_MAX_PHOTO:
        raise ValueError("La photo est trop lourde (1,5 Mo maximum).")
    if not contenu:
        return ""
    return f"data:{type_mime};base64,{base64.b64encode(contenu).decode('utf-8')}"


def periodes_recentes(n: int, ref: datetime.date) -> list:
    """['2026-06', ..., '2026-11'] — du plus ancien au plus récent."""
    y, m, out = ref.year, ref.month, []
    for _ in range(n):
        out.append(f"{y}-{m:02d}")
        m -= 1
        if m == 0:
            y, m = y - 1, 12
    return out[::-1]


def libelle_periode(p, court: bool = False) -> str:
    try:
        y, m = str(p).split("-")[:2]
        return f"{MOIS_COURT[int(m)]} {y[2:]}" if court else f"{MOIS_FR[int(m)]} {y}"
    except Exception:
        return str(p or "")


def periode_valide(p: str) -> bool:
    return bool(re.fullmatch(r"20\d\d-(0[1-9]|1[0-2])", str(p or "")))


def tel_international(tel) -> str:
    """Les numéros sont stockés sans indicatif : on le devine pour WhatsApp."""
    n = re.sub(r"\D", "", str(tel or ""))
    if n.startswith("00"):
        n = n[2:]
    if len(n) == 9 and n.startswith("7"):
        return "221" + n          # Sénégal
    if len(n) == 9 and n.startswith("6"):
        return "224" + n          # Guinée
    if len(n) == 8:
        return "223" + n          # Mali
    if len(n) == 10 and n.startswith("0"):
        return "225" + n          # Côte d'Ivoire
    return n


def lien_whatsapp(tel, message: str) -> str:
    num = tel_international(tel)
    return f"https://wa.me/{num}?text={urllib.parse.quote(message)}" if num else ""


def tout_charger(table: str, colonnes: str = "*", filtres: Optional[list] = None, page: int = 1000) -> list:
    """Supabase renvoie 1000 lignes maximum par requête : on pagine pour des totaux justes."""
    lignes, debut = [], 0
    while True:
        q = supabase.table(table).select(colonnes)
        for col, val in (filtres or []):
            q = q.eq(col, val)
        data = q.range(debut, debut + page - 1).execute().data or []
        lignes.extend(data)
        if len(data) < page:
            return lignes
        debut += page


def charger_sans_erreur(table, colonnes="*", filtres=None) -> list:
    try:
        return tout_charger(table, colonnes, filtres)
    except Exception as exc:
        log.warning("Lecture %s impossible : %s", table, exc)
        return []


def charger_adherents() -> list:
    # On essaie d'abord avec la date d'inscription (pour le calcul des retards)
    for cols in (COLONNES_ADHERENT + ",created_at", COLONNES_ADHERENT + ",date_adhesion", COLONNES_ADHERENT):
        try:
            return tout_charger("adherents", cols)
        except Exception:
            continue
    return []


def est_tresorier(user) -> bool:
    return (user or {}).get("role") in ("admin", "tresorier")


def est_admin(user) -> bool:
    return (user or {}).get("role") == "admin"


# ---------------------------------------------------------------------
#  Sécurité : session, CSRF, rôles, anti-force brute
# ---------------------------------------------------------------------
class Redirection(Exception):
    def __init__(self, url: str, message: str = "", type_msg: str = "erreur"):
        self.url, self.message, self.type_msg = url, message, type_msg


@app.exception_handler(Redirection)
async def gerer_redirection(request: Request, exc: Redirection):
    if exc.message:
        flash(request, exc.message, exc.type_msg)
    return RedirectResponse(exc.url, status_code=303)


@app.exception_handler(Exception)
async def gerer_erreur(request: Request, exc: Exception):
    log.exception("Erreur non gérée sur %s", request.url.path)
    if request.url.path == "/dashboard":
        return HTMLResponse(PAGE_ERREUR, status_code=500)
    return RedirectResponse("/dashboard?erreur=1", status_code=303)


PAGE_ERREUR = ("<div style='font-family:sans-serif;padding:2rem;max-width:30rem;margin:auto'>"
               "<h3>Le tableau de bord n'a pas pu se charger.</h3>"
               "<p>Réessayez dans un instant. Si le problème persiste, prévenez l'administrateur.</p>"
               "<a href='/dashboard'>Réessayer</a> · <a href='/deconnexion'>Se déconnecter</a></div>")


def flash(request: Request, message: str, type_msg: str = "succes"):
    request.session["flash"] = [type_msg, message[:300]]


def lire_flash(request: Request):
    f = request.session.pop("flash", None)
    if not f and request.query_params.get("erreur"):
        f = ["erreur", "Une erreur est survenue. L'opération n'a peut-être pas été enregistrée."]
    return f


def jeton_csrf(request: Request) -> str:
    if "csrf" not in request.session:
        request.session["csrf"] = secrets.token_urlsafe(24)
    return request.session["csrf"]


def utilisateur_session(request: Request) -> Optional[dict]:
    uid = request.session.get("user_id")
    if not uid:
        return None
    res = supabase.table("adherents").select("*").eq("id", uid).limit(1).execute()
    user = res.data[0] if res.data else None
    if not user or user.get("statut") != "actif":
        request.session.clear()
        return None
    user.pop("mot_de_passe", None)
    user["_csrf"] = jeton_csrf(request)
    return user


def exiger(request: Request, csrf: Optional[str] = None, roles: Optional[tuple] = None,
           onglet: str = "") -> dict:
    """À appeler au début de chaque route protégée.
    csrf : valeur du formulaire (routes POST). roles : rôles autorisés."""
    user = utilisateur_session(request)
    if not user:
        raise Redirection("/", "Veuillez vous connecter.")
    if csrf is not None and not hmac.compare_digest(str(csrf), request.session.get("csrf", "")):
        raise Redirection("/dashboard", "Formulaire expiré, veuillez réessayer.")
    if roles and user.get("role") not in roles:
        log.warning("Accès refusé : user %s (%s) sur %s", user["id"], user.get("role"), request.url.path)
        raise Redirection("/dashboard", "Action réservée au bureau de l'association.")
    return user


def retour(onglet: str = "", message: str = "", type_msg: str = "succes", request: Optional[Request] = None):
    if request is not None and message:
        flash(request, message, type_msg)
    return RedirectResponse(f"/dashboard{('#' + onglet) if onglet else ''}", status_code=303)


_tentatives = defaultdict(list)
MAX_TENTATIVES, FENETRE = 8, 15 * 60


def ip_client(request: Request) -> str:
    return (request.headers.get("x-forwarded-for", "").split(",")[0].strip()
            or (request.client.host if request.client else "?"))


def trop_de_tentatives(cle: str) -> bool:
    maintenant = time.time()
    _tentatives[cle] = [t for t in _tentatives[cle] if maintenant - t < FENETRE]
    return len(_tentatives[cle]) >= MAX_TENTATIVES


# ---------------------------------------------------------------------
#  Chargement des données (requêtes en parallèle)
# ---------------------------------------------------------------------
def charger_donnees(user: dict, tresorier: bool) -> dict:
    taches = {
        "evenements": lambda: charger_sans_erreur("evenements"),
        "projets": lambda: charger_sans_erreur("projets"),
        "galerie": lambda: charger_sans_erreur("galerie"),
    }
    if tresorier:
        taches.update({
            "adherents": charger_adherents,
            "cotisations": lambda: charger_sans_erreur(
                "cotisations", "*, adherents(nom, prenom, secteur, telephone)"),
            "aides": lambda: charger_sans_erreur("aides", "*, adherents(nom, prenom, secteur)"),
            "decaissements": lambda: charger_sans_erreur("decaissements"),
            "presences": lambda: charger_sans_erreur(
                "presences_association", "*, adherents(nom, prenom, secteur, telephone)"),
            "parametres": lambda: charger_sans_erreur("parametres", "*", [("id", 1)]),
        })
    else:
        # Un membre ne charge que SES données : plus rapide et plus confidentiel.
        uid = user["id"]
        taches.update({
            "cotisations": lambda: charger_sans_erreur("cotisations", "*", [("adherent_id", uid)]),
            "aides": lambda: charger_sans_erreur("aides", "*", [("adherent_id", uid)]),
            "presences": lambda: charger_sans_erreur("presences_association", "*", [("adherent_id", uid)]),
        })
    with ThreadPoolExecutor(max_workers=len(taches)) as pool:
        futurs = {k: pool.submit(f) for k, f in taches.items()}
        return {k: f.result() for k, f in futurs.items()}


# ---------------------------------------------------------------------
#  Calculs
# ---------------------------------------------------------------------
def est_valide(c) -> bool:
    return c.get("statut_paiement") == "valide"


def est_regularisation(c) -> bool:
    return "regularisation" in str(c.get("mode_paiement", ""))


def periodes_payees_par_membre(cotisations) -> dict:
    payees = {}
    for c in cotisations:
        if est_valide(c):
            payees.setdefault(c.get("adherent_id"), set()).add(str(c.get("periode", ""))[:7])
    return payees


def debut_adhesion(a) -> str:
    return str(a.get("date_adhesion") or a.get("created_at") or "")[:7]


def mois_en_retard(a, payees: set, periodes: list) -> list:
    debut = debut_adhesion(a)
    return [p for p in periodes if p not in payees and (not debut or p >= debut)]


def calculer_stats(d: dict, periodes: list) -> dict:
    cotis = d.get("cotisations", [])
    aides = d.get("aides", [])
    adherents = d.get("adherents", [])
    actifs = [a for a in adherents if a.get("statut") == "actif"]
    param = (d.get("parametres") or [{}])[0]
    solde_initial = float(param.get("solde_initial") or 0)

    encaisse = sum(float(c.get("montant") or 0) for c in cotis if est_valide(c) and not est_regularisation(c))
    aides_ok = sum(float(a.get("montant_demande") or 0) for a in aides if a.get("statut_validation") == "approuve")
    decaisse = sum(float(x.get("montant") or 0) for x in d.get("decaissements", []))

    par_mois = {p: 0.0 for p in periodes}
    for c in cotis:
        p = str(c.get("periode", ""))[:7]
        if p in par_mois and est_valide(c):
            par_mois[p] += float(c.get("montant") or 0)

    payees = periodes_payees_par_membre(cotis)
    courant = periodes[-1]
    a_jour = sum(1 for a in actifs if courant in payees.get(a["id"], set()))

    return {
        "solde_initial": solde_initial,
        "solde": solde_initial + encaisse - aides_ok - decaisse,
        "encaisse": encaisse,
        "aides_ok": aides_ok,
        "decaisse": decaisse,
        "par_mois": par_mois,
        "payees": payees,
        "actifs": actifs,
        "a_jour": a_jour,
        "taux": round(100 * a_jour / len(actifs)) if actifs else 0,
        "adh_attente": sum(1 for a in adherents if a.get("statut") == "en_attente"),
        "pay_attente": sum(1 for c in cotis if not est_valide(c)),
        "aides_attente": sum(1 for a in aides if a.get("statut_validation", "en_attente") == "en_attente"),
    }


# ---------------------------------------------------------------------
#  Briques d'interface
# ---------------------------------------------------------------------
def champ_user(user) -> str:
    """Jeton anti-falsification ajouté à chaque formulaire."""
    return f'<input type="hidden" name="csrf" value="{h(user.get("_csrf", ""))}">'


def badge(texte, couleur="slate") -> str:
    return f'<span class="badge badge-{couleur}">{h(texte)}</span>'


COULEUR_STATUT = {
    "actif": "vert", "en_attente": "ambre", "inactif": "slate", "suspendu": "rouge",
    "approuve": "vert", "refuse": "rouge", "rejete": "rouge", "valide": "vert",
    "Present": "vert", "Retard": "ambre", "Absent": "rouge", "Excuse": "bleu",
    "En cours": "bleu", "Planifié": "violet", "Terminé": "vert",
}


def kpi(titre, valeur, sous_titre="", couleur="vert") -> str:
    return f"""
    <div class="carte kpi">
      <p class="kpi-titre">{h(titre)}</p>
      <p class="kpi-valeur text-{ 'emerald' if couleur=='vert' else couleur }-300">{valeur}</p>
      <p class="kpi-sous">{sous_titre}</p>
    </div>"""


def graphique_barres(par_mois: dict, objectif: float) -> str:
    maxi = max(list(par_mois.values()) + [objectif, 1])
    barres = ""
    for p, v in par_mois.items():
        haut = max(4, round(100 * v / maxi))
        barres += f"""
        <div class="flex-1 flex flex-col items-center gap-1 min-w-0">
          <span class="text-[10px] text-slate-400 font-mono truncate">{h(montant(v))}</span>
          <div class="w-full h-32 flex items-end"><div class="barre w-full rounded-t-lg" style="height:{haut}%"
               title="{h(libelle_periode(p))} : {h(montant(v))} {DEVISE}"></div></div>
          <span class="text-[10px] text-slate-300 font-bold">{h(libelle_periode(p, court=True))}</span>
        </div>"""
    ligne_obj = round(100 * objectif / maxi) if objectif else 0
    return f"""
    <div class="relative">
      <div class="absolute left-0 right-0 border-t border-dashed border-amber-400/60 pointer-events-none"
           style="bottom:calc({ligne_obj}% * 0.8 + 18px)" title="Objectif mensuel"></div>
      <div class="flex gap-2 items-end">{barres}</div>
    </div>
    <p class="text-[11px] text-slate-400 mt-2">Pointillés : objectif mensuel ({h(montant(objectif))} {DEVISE} si tous les membres actifs paient).</p>"""


def options_membres(actifs) -> str:
    return "".join(
        f'<option value="{h(a["id"])}" data-text="{h((str(a.get("prenom","")) + " " + str(a.get("nom","")) + " " + str(a.get("secteur",""))).lower())}">'
        f'{h(a.get("prenom"))} {h(a.get("nom"))} ({h(a.get("secteur"))})</option>'
        for a in sorted(actifs, key=lambda x: (str(x.get("nom", "")).lower(), str(x.get("prenom", "")).lower()))
    )


# ---------------------------------------------------------------------
#  Sections — Trésorier / Admin
# ---------------------------------------------------------------------
def section_tresorerie(user, d, s, periodes) -> str:
    courant = periodes[-1]
    objectif = COTISATION_MENSUELLE * len(s["actifs"])

    # Retards (contrôle sur les MOIS_SUIVIS derniers mois, et non plus seulement le mois en cours)
    lignes = []
    for a in s["actifs"]:
        manquants = mois_en_retard(a, s["payees"].get(a["id"], set()), periodes)
        lignes.append((len(manquants), a, manquants))
    lignes.sort(key=lambda t: (-t[0], str(t[1].get("nom", "")).lower()))

    rows = ""
    for nb, a, manquants in lignes:
        if nb:
            liste = ", ".join(libelle_periode(p) for p in manquants)
            msg = (f"Bonjour {a.get('prenom','')}, petit rappel de l'association Tinka : "
                   f"cotisation(s) en attente pour {liste} "
                   f"(total {montant(nb * COTISATION_MENSUELLE)} {DEVISE}). Merci de régulariser. 🙏")
            wa = lien_whatsapp(a.get("telephone"), msg)
            btn = f'<a href="{h(wa)}" target="_blank" rel="noopener" class="btn btn-vert btn-xs">💬 Relancer</a>' if wa else ""
            etat = (f'{badge(f"{nb} mois · {montant(nb * COTISATION_MENSUELLE)} {DEVISE}", "rouge" if nb >= 3 else "ambre")}'
                    f'<div class="text-[10px] text-slate-400 mt-1">{h(liste)}</div>')
        else:
            btn, etat = "", badge("À jour ✓", "vert")
        rows += f"""
        <tr class="ligne" data-filtre="{h((str(a.get('prenom','')) + ' ' + str(a.get('nom','')) + ' ' + str(a.get('secteur',''))).lower())}"
            data-etat="{'retard' if nb else 'ajour'}">
          <td><b class="text-white">{h(a.get('prenom'))} {h(a.get('nom'))}</b>
              <span class="text-xs text-slate-400">({h(a.get('secteur'))})</span></td>
          <td class="text-right">{etat}</td>
          <td class="text-right w-28">{btn}</td>
        </tr>"""
    nb_retard = sum(1 for t in lignes if t[0])

    # Paiements à valider (passerelle / 1-clic)
    mobiles = [c for c in d["cotisations"]
               if "passerelle_" in str(c.get("mode_paiement", "")) or "1-clic_" in str(c.get("mode_paiement", ""))]
    mobiles.sort(key=lambda c: (est_valide(c), str(c.get("periode", ""))), reverse=False)
    rows_mob = ""
    for pm in mobiles:
        adh = pm.get("adherents") or {}
        if pm.get("statut_paiement") == "rejete":
            action = badge("Rejeté", "rouge")
        elif not est_valide(pm):
            action = f"""<form action="/admin/valider-paiement-mobile" method="POST" class="inline">{champ_user(user)}
                <input type="hidden" name="paiement_id" value="{h(pm['id'])}">
                <button class="btn btn-vert btn-xs">✓ Valider</button></form>
                <form action="/admin/rejeter-paiement" method="POST" class="inline">{champ_user(user)}
                <input type="hidden" name="paiement_id" value="{h(pm['id'])}">
                <button class="btn btn-rouge btn-xs" onclick="return confirm('Rejeter ce paiement non reçu ?')">✕</button></form>"""
        else:
            action = f"""{badge('Validé ✓', 'vert')}
                <a href="/cotisation/recu-pdf/{h(pm['id'])}" target="_blank" class="btn btn-bleu btn-xs ml-1">📄 Reçu</a>"""
        rows_mob += f"""
        <tr class="ligne" data-filtre="{h((str(adh.get('prenom','')) + ' ' + str(adh.get('nom',''))).lower())}">
          <td><b class="text-white">{h(adh.get('prenom'))} {h(adh.get('nom'))}</b></td>
          <td class="text-xs uppercase text-sky-300">{h(pm.get('mode_paiement'))}</td>
          <td class="font-bold text-emerald-400 whitespace-nowrap">{h(montant(pm.get('montant')))} {DEVISE}</td>
          <td class="text-slate-300 whitespace-nowrap">{h(libelle_periode(pm.get('periode')))}</td>
          <td class="text-right whitespace-nowrap">{action}</td>
        </tr>"""

    return f"""
    <div class="grid grid-cols-2 lg:grid-cols-4 gap-3">
      {kpi("Solde en caisse", f"{h(montant(s['solde']))} <small class='text-xs'>{DEVISE}</small>",
           f"Initial {h(montant(s['solde_initial']))} · Aides {h(montant(s['aides_ok']))} · Sorties {h(montant(s['decaisse']))}")}
      {kpi(f"Encaissé — {libelle_periode(courant)}", f"{h(montant(s['par_mois'][courant]))} <small class='text-xs'>{DEVISE}</small>",
           f"Objectif {h(montant(objectif))} {DEVISE}", "sky")}
      {kpi("Membres à jour", f"{s['a_jour']}/{len(s['actifs'])}",
           f"<div class='jauge mt-2'><div style='width:{s['taux']}%'></div></div><span>{s['taux']} % ce mois</span>", "amber")}
      {kpi("À traiter", f"{s['adh_attente'] + s['pay_attente'] + s['aides_attente']}",
           f"{s['adh_attente']} adhésion(s) · {s['pay_attente']} paiement(s) · {s['aides_attente']} aide(s)", "rose")}
    </div>

    <div class="carte">
      <div class="entete-carte"><h2>📈 Cotisations encaissées — {MOIS_SUIVIS} derniers mois</h2>
        <a href="/admin/export-cotisations.csv" class="btn btn-gris btn-xs">⬇️ Export Excel (CSV)</a></div>
      {graphique_barres(s['par_mois'], objectif)}
    </div>

    <div class="grid grid-cols-1 lg:grid-cols-2 gap-4">
      <div class="carte">
        <h2 class="titre">➕ Saisir une cotisation</h2>
        <form action="/admin/saisir-cotisation" method="POST" class="space-y-3" onsubmit="return verifierChoix()">{champ_user(user)}
          <script type="application/json" id="membres-json">{json_membres(lignes)}</script>
          <input type="hidden" name="adherent_id" id="adherent-cotis">
          <div class="relative">
            <input type="search" id="recherche-cotis" autocomplete="off" class="champ pl-10"
                   placeholder="Rechercher : nom, prénom, secteur ou téléphone…"
                   oninput="rechercherMembre()" onfocus="rechercherMembre()" onkeydown="toucheRecherche(event)">
            <span class="absolute left-3.5 top-1/2 -translate-y-1/2 text-slate-400 pointer-events-none">🔍</span>
            <div id="resultats-cotis" class="hidden absolute z-30 left-0 right-0 mt-1 bg-slate-900 border border-white/15
                 rounded-2xl shadow-2xl max-h-72 overflow-y-auto"></div>
          </div>
          <div id="choix-cotis" class="hidden alerte alerte-vert flex items-center justify-between gap-2">
            <div class="min-w-0"><b id="choix-nom" class="block truncate"></b><span id="choix-info" class="text-xs"></span></div>
            <button type="button" class="btn btn-gris btn-xs" onclick="effacerChoix()">Changer</button>
          </div>
          <div class="grid grid-cols-2 gap-3">
            <label class="etiquette">Période<input type="month" name="periode" id="periode-cotis" value="{courant}" required class="champ mt-1"></label>
            <label class="etiquette">Montant ({DEVISE})<input type="number" name="montant" min="1" step="1"
                   value="{COTISATION_MENSUELLE}" required class="champ mt-1"></label>
          </div>
          <select name="mode_paiement" class="champ">
            <option value="especes">💵 Espèces</option><option value="mobile_money">📱 Mobile money</option>
            <option value="virement">🏦 Virement</option><option value="regularisation">♻️ Régularisation (hors caisse)</option></select>
          <button class="btn btn-vert w-full">Enregistrer la cotisation</button>
        </form>
      </div>
      <div class="carte">
        <h2 class="titre">🏦 Solde initial réel en caisse</h2>
        <form action="/admin/maj-solde-initial" method="POST" class="space-y-3">{champ_user(user)}
          <input type="number" name="solde_initial" value="{h(s['solde_initial'])}" step="1" required class="champ">
          <button class="btn btn-gris w-full" onclick="return confirm('Modifier le solde initial change le solde affiché. Continuer ?')">Mettre à jour</button>
        </form>
        <p class="text-[11px] text-slate-400 mt-3">Solde = solde initial + cotisations validées (hors régularisations) − aides approuvées − décaissements.</p>
      </div>
    </div>

    <div class="carte">
      <h2 class="titre">💸 Dépenses / décaissements (total {h(montant(s['decaisse']))} {DEVISE})</h2>
      <form action="/admin/decaissement" method="POST" class="grid grid-cols-1 sm:grid-cols-4 gap-3 mb-4">{champ_user(user)}
        <input name="motif" maxlength="200" placeholder="Motif (ex : location bâches)" required class="champ sm:col-span-2">
        <input name="beneficiaire" maxlength="100" placeholder="Bénéficiaire" class="champ">
        <div class="flex gap-2"><input type="number" name="montant" min="1" placeholder="Montant" required class="champ">
          <button class="btn btn-rouge" onclick="return confirm('Enregistrer cette dépense ? Elle sera déduite du solde.')">＋</button></div>
      </form>
      <div class="zone-table max-h-60"><table class="tableau">
        <thead><tr><th>Date</th><th>Motif</th><th>Bénéficiaire</th><th class="text-right">Montant</th></tr></thead>
        <tbody>{lignes_decaissements(d.get('decaissements', []))}</tbody></table></div>
    </div>

    <div class="carte">
      <div class="entete-carte"><h2>⏰ Suivi des cotisations ({nb_retard} membre(s) en retard)</h2>
        <div class="flex gap-2">
          <select class="champ champ-xs w-auto" onchange="filtrerEtat(this, 'tab-retards')">
            <option value="">Tous</option><option value="retard">En retard</option><option value="ajour">À jour</option></select>
          <input type="search" placeholder="Filtrer…" class="champ champ-xs w-40" oninput="filtrerLignes(this, 'tab-retards')">
        </div></div>
      <div class="zone-table"><table id="tab-retards" class="tableau"><tbody>
        {rows or '<tr><td class="vide">Aucun membre actif.</td></tr>'}</tbody></table></div>
    </div>

    <div class="carte">
      <div class="entete-carte"><h2>📱 Paiements passerelle & mobile</h2>
        <input type="search" placeholder="Rechercher…" class="champ champ-xs w-40" oninput="filtrerLignes(this, 'tab-mobiles')"></div>
      <div class="zone-table"><table id="tab-mobiles" class="tableau">
        <thead><tr><th>Adhérent</th><th>Mode</th><th>Montant</th><th>Période</th><th class="text-right">Action</th></tr></thead>
        <tbody>{rows_mob or '<tr><td colspan="5" class="vide">Aucun paiement.</td></tr>'}</tbody></table></div>
    </div>"""


def json_membres(lignes) -> str:
    """Liste des membres actifs pour la recherche instantanée (avec leurs mois en retard)."""
    data = [{"id": a["id"], "n": f"{a.get('prenom', '')} {a.get('nom', '')}".strip(), "s": a.get("secteur") or "",
             "t": a.get("telephone") or "", "r": manquants, "rl": [libelle_periode(p) for p in manquants]}
            for _, a, manquants in lignes]
    return json.dumps(data, ensure_ascii=False).replace("<", "\\u003c").replace(">", "\\u003e").replace("&", "\\u0026")


def lignes_decaissements(decs) -> str:
    cle = lambda x: str(x.get("date_decaissement") or x.get("created_at") or "")
    rows = "".join(
        f"""<tr><td class="text-slate-400 whitespace-nowrap">{h(date_fr(cle(x)))}</td><td class="text-white">{h(x.get('motif'))}</td>
            <td class="text-slate-300">{h(x.get('beneficiaire'))}</td>
            <td class="text-right font-bold text-red-300 whitespace-nowrap">− {h(montant(x.get('montant')))} {DEVISE}</td></tr>"""
        for x in sorted(decs, key=cle, reverse=True)[:50])
    return rows or '<tr><td colspan="4" class="vide">Aucune dépense enregistrée.</td></tr>'


def section_annuaire(user, d, s) -> str:
    admin = user.get("role") == "admin"
    rows = ""
    for a in sorted(d["adherents"], key=lambda x: (x.get("statut") != "en_attente", str(x.get("nom", "")).lower())):
        actions = ""
        if a.get("statut") == "en_attente":
            actions += f"""<form action="/admin/valider-adherent" method="POST" class="inline">{champ_user(user)}
              <input type="hidden" name="adherent_id" value="{h(a['id'])}"><button class="btn btn-vert btn-xs">✓ Valider</button></form>"""
        if admin and a["id"] != user["id"]:
            opts = "".join(f'<option value="{r}" {"selected" if a.get("role") == r else ""}>{lbl}</option>'
                           for r, lbl in (("membre", "Membre"), ("tresorier", "Trésorier"), ("admin", "Admin")))
            actions += f"""<form action="/admin/changer-role" method="POST" class="inline ml-1">{champ_user(user)}
              <input type="hidden" name="adherent_id" value="{h(a['id'])}">
              <select name="nouveau_role" class="champ champ-xs w-auto inline-block"
                      onchange="if(confirm('Changer le rôle de ce membre ?')) this.form.submit(); else this.form.reset();">{opts}</select></form>"""
        if a["id"] != user["id"] and a.get("statut") in ("actif", "inactif"):
            nouveau = "inactif" if a.get("statut") == "actif" else "actif"
            actions += f"""<form action="/admin/changer-statut" method="POST" class="inline ml-1">{champ_user(user)}
              <input type="hidden" name="adherent_id" value="{h(a['id'])}"><input type="hidden" name="statut" value="{nouveau}">
              <button class="btn btn-gris btn-xs" title="{'Désactiver' if nouveau == 'inactif' else 'Réactiver'}"
                onclick="return confirm('{'Désactiver ce membre ? Il ne pourra plus se connecter.' if nouveau == 'inactif' else 'Réactiver ce membre ?'}')">{'⏸' if nouveau == 'inactif' else '▶'}</button></form>"""
        peut_modifier = admin or a.get("role") != "admin"
        actions += "" if not peut_modifier else (f"""<button type="button" class="btn btn-bleu btn-xs ml-1" onclick="ouvrirEdition(this)"
              data-id="{h(a['id'])}" data-prenom="{h(a.get('prenom'))}" data-nom="{h(a.get('nom'))}"
              data-telephone="{h(a.get('telephone'))}" data-secteur="{h(a.get('secteur'))}">✏️</button>""")
        wa = lien_whatsapp(a.get("telephone"), f"Bonjour {a.get('prenom','')}, ")
        tel = f'<a href="{h(wa)}" target="_blank" rel="noopener" class="hover:text-emerald-300">{h(a.get("telephone"))}</a>' if wa else h(a.get("telephone"))
        rows += f"""
        <tr class="ligne" data-filtre="{h((str(a.get('prenom','')) + ' ' + str(a.get('nom','')) + ' ' + str(a.get('secteur','')) + ' ' + str(a.get('telephone',''))).lower())}"
            data-etat="{h(a.get('statut'))}">
          <td><b class="text-white">{h(a.get('prenom'))} {h(a.get('nom'))}</b></td>
          <td>{badge(a.get('role'), 'violet' if a.get('role') == 'admin' else 'bleu' if a.get('role') == 'tresorier' else 'slate')}</td>
          <td>{badge(str(a.get('statut') or '').replace('_', ' '), COULEUR_STATUT.get(a.get('statut'), 'slate'))}</td>
          <td class="text-slate-300">{h(a.get('secteur'))}</td>
          <td class="font-mono text-xs text-slate-400">{tel}</td>
          <td class="text-right whitespace-nowrap">{actions}</td>
        </tr>"""

    secteurs = {}
    for a in s["actifs"]:
        secteurs[a.get("secteur") or "—"] = secteurs.get(a.get("secteur") or "—", 0) + 1
    puces = "".join(f'<span class="badge badge-slate">{h(k)} · {v}</span>' for k, v in sorted(secteurs.items(), key=lambda t: -t[1]))

    return f"""
    <div class="carte">
      <div class="entete-carte"><h2>👥 Annuaire ({len(d['adherents'])} inscrits · {len(s['actifs'])} actifs)</h2>
        <div class="flex gap-2 flex-wrap">
          <select class="champ champ-xs w-auto" onchange="filtrerEtat(this, 'tab-annuaire')">
            <option value="">Tous statuts</option><option value="actif">Actifs</option>
            <option value="en_attente">En attente</option><option value="inactif">Inactifs</option></select>
          <input type="search" placeholder="Nom, secteur, téléphone…" class="champ champ-xs w-52" oninput="filtrerLignes(this, 'tab-annuaire')">
          <a href="/adherents/export-pdf" target="_blank" class="btn btn-rouge btn-xs">📄 PDF</a>
        </div></div>
      <div class="flex flex-wrap gap-1.5 mb-3">{puces}</div>
      <div class="zone-table max-h-[32rem]"><table id="tab-annuaire" class="tableau">
        <thead><tr><th>Nom</th><th>Rôle</th><th>Statut</th><th>Secteur</th><th>Téléphone</th><th class="text-right">Actions</th></tr></thead>
        <tbody>{rows or '<tr><td colspan="6" class="vide">Aucun adhérent.</td></tr>'}</tbody></table></div>
    </div>"""


def section_pointage(user, d, s) -> str:
    aujourd_hui = datetime.date.today().isoformat()
    evts = sorted(d["evenements"], key=lambda e: str(e.get("date_reunion", "")), reverse=True)
    opts_evt = "".join(
        f'<option value="{h(e.get("titre"))}" data-date="{h(str(e.get("date_reunion",""))[:10])}">'
        f'{h(e.get("titre"))} ({h(date_fr(e.get("date_reunion")))})</option>' for e in evts)

    # Taux de présence par événement
    par_evt = {}
    for p in d["presences"]:
        k = (p.get("evenement_titre"), str(p.get("date_reunion", ""))[:10])
        par_evt.setdefault(k, {"Present": 0, "Retard": 0, "Absent": 0, "Excuse": 0})
        par_evt[k][p.get("statut_presence")] = par_evt[k].get(p.get("statut_presence"), 0) + 1
    resume = ""
    for (titre, dt), c in sorted(par_evt.items(), key=lambda t: t[0][1], reverse=True)[:6]:
        venus = c.get("Present", 0) + c.get("Retard", 0)
        taux = round(100 * venus / len(s["actifs"])) if s["actifs"] else 0
        resume += f"""<div class="flex items-center gap-3 py-2 border-b border-white/5 text-sm">
          <div class="flex-1 min-w-0"><b class="text-white truncate block">{h(titre)}</b>
            <span class="text-[11px] text-slate-400">{h(date_fr(dt))} · {venus} venu(s), {c.get('Excuse',0)} excusé(s)</span></div>
          <div class="w-24"><div class="jauge"><div style="width:{taux}%"></div></div></div>
          <span class="text-xs font-bold text-emerald-300 w-10 text-right">{taux}%</span></div>"""

    cases = "".join(
        f'<label class="case ligne" data-filtre="{h((str(a.get("prenom","")) + " " + str(a.get("nom","")) + " " + str(a.get("secteur",""))).lower())}">'
        f'<input type="checkbox" name="adherent_ids" value="{h(a["id"])}" class="accent-emerald-500 w-4 h-4"> '
        f'<span>{h(a.get("prenom"))} {h(a.get("nom"))} <small class="text-slate-400">({h(a.get("secteur"))})</small></span></label>'
        for a in sorted(s["actifs"], key=lambda x: str(x.get("nom", "")).lower()))

    rows = ""
    for p in sorted(d["presences"], key=lambda x: str(x.get("date_reunion", "")), reverse=True):
        adh = p.get("adherents") or {}
        rows += f"""<tr class="ligne" data-filtre="{h((str(adh.get('prenom','')) + ' ' + str(adh.get('nom','')) + ' ' + str(p.get('evenement_titre',''))).lower())}">
          <td><b class="text-white">{h(adh.get('prenom'))} {h(adh.get('nom'))}</b></td>
          <td class="text-slate-300">{h(p.get('evenement_titre'))}</td>
          <td class="text-slate-400 whitespace-nowrap">{h(date_fr(p.get('date_reunion')))}</td>
          <td>{badge(p.get('statut_presence'), COULEUR_STATUT.get(p.get('statut_presence'), 'slate'))}</td></tr>"""

    select_evt = f"""<select name="evenement_titre" required class="champ" onchange="majDateEvt(this)">
          <option value="">— Choisir un événement —</option>{opts_evt}</select>"""
    select_statut = """<select name="statut_presence" class="champ">
          <option value="Present">Présent(e)</option><option value="Retard">En retard</option>
          <option value="Absent">Absent(e)</option><option value="Excuse">Excusé(e)</option></select>"""

    return f"""
    <div class="grid grid-cols-1 lg:grid-cols-2 gap-4">
      <div class="carte">
        <h2 class="titre">📅 Planifier un événement</h2>
        <form action="/admin/creer-evenement" method="POST" class="space-y-3">{champ_user(user)}
          <input type="text" name="titre" maxlength="120" placeholder="ex : Assemblée générale mensuelle" required class="champ">
          <input type="date" name="date_reunion" min="{aujourd_hui}" required class="champ">
          <textarea name="description" rows="2" maxlength="1000" placeholder="Ordre du jour…" class="champ"></textarea>
          <button class="btn btn-bleu w-full">Créer l'événement</button>
        </form>
      </div>
      <div class="carte">
        <h2 class="titre">📷 Pointage rapide par QR code</h2>
        <p class="text-xs text-slate-400 mb-3">Scannez le QR code de la carte membre : le membre est sélectionné automatiquement.</p>
        <form action="/admin/pointer-presence" method="POST" class="space-y-3">{champ_user(user)}
          <button type="button" class="btn btn-vert w-full" onclick="demarrerScan()">📷 Ouvrir la caméra</button>
          <div id="lecteur-qr" class="hidden rounded-2xl overflow-hidden"></div>
          <p id="resultat-scan" class="text-xs text-emerald-300 font-semibold"></p>
          {select_evt}
          <input type="date" name="date_reunion" required class="champ date-evt">
          <select name="adherent_id" id="select-pointage" required class="champ">
            <option value="">— Membre —</option>{options_membres(s['actifs'])}</select>
          {select_statut}
          <button class="btn btn-vert w-full">Valider le pointage</button>
        </form>
      </div>
    </div>

    <div class="carte">
      <h2 class="titre">✅ Pointage groupé (cochez tous les présents d'un coup)</h2>
      <form action="/admin/pointer-presences-groupe" method="POST" class="space-y-3">{champ_user(user)}
        <div class="grid grid-cols-1 sm:grid-cols-3 gap-3">{select_evt}
          <input type="date" name="date_reunion" required class="champ date-evt">{select_statut}</div>
        <div class="flex gap-2 items-center">
          <input type="search" placeholder="Filtrer…" class="champ champ-xs flex-1" oninput="filtrerLignes(this, 'liste-cases')">
          <button type="button" class="btn btn-gris btn-xs" onclick="toutCocher(true)">Tout cocher</button>
          <button type="button" class="btn btn-gris btn-xs" onclick="toutCocher(false)">Aucun</button>
        </div>
        <div id="liste-cases" class="grid grid-cols-1 sm:grid-cols-2 gap-1 max-h-72 overflow-y-auto pr-1">{cases}</div>
        <button class="btn btn-vert w-full">Enregistrer le pointage groupé (<span id="nb-coches">0</span>)</button>
      </form>
    </div>

    <div class="grid grid-cols-1 lg:grid-cols-5 gap-4">
      <div class="carte lg:col-span-2"><h2 class="titre">📊 Participation (6 derniers événements)</h2>
        {resume or '<p class="vide">Aucun pointage enregistré.</p>'}</div>
      <div class="carte lg:col-span-3">
        <div class="entete-carte"><h2>📋 Historique des pointages</h2>
          <input type="search" placeholder="Nom, événement…" class="champ champ-xs w-48" oninput="filtrerLignes(this, 'tab-presences')"></div>
        <div class="zone-table"><table id="tab-presences" class="tableau">
          <thead><tr><th>Membre</th><th>Événement</th><th>Date</th><th>Statut</th></tr></thead>
          <tbody>{rows or '<tr><td colspan="4" class="vide">Aucun pointage.</td></tr>'}</tbody></table></div>
      </div>
    </div>"""


def cartes_projets(projets, user=None) -> str:
    out = ""
    for pr in projets:
        changer = ""
        if user and est_tresorier(user):
            opts = "".join(f'<option {"selected" if pr.get("statut") == st else ""}>{st}</option>' for st in ("Planifié", "En cours", "Terminé"))
            changer = f"""<form action="/admin/projet-statut" method="POST" class="mt-2">{champ_user(user)}
              <input type="hidden" name="projet_id" value="{h(pr.get('id'))}">
              <select name="statut" class="champ champ-xs" onchange="this.form.submit()">{opts}</select></form>"""
        out += f"""
        <div class="carte-interne">
          <div class="flex justify-between items-start gap-2 mb-2">
            <h4 class="font-bold text-emerald-300">{h(pr.get('titre'))}</h4>
            {badge(pr.get('statut'), COULEUR_STATUT.get(pr.get('statut'), 'slate'))}</div>
          <p class="text-xs text-slate-300 mb-3 leading-relaxed whitespace-pre-line">{h(pr.get('description'))}</p>
          <div class="text-xs text-slate-300 space-y-1 bg-black/20 p-3 rounded-xl">
            <div><b>🎯 Objectifs :</b> {h(pr.get('objectifs') or 'Non spécifié')}</div>
            <div><b>📅 Planning :</b> {h(pr.get('chronologie') or 'Non spécifié')}</div>
            <div class="font-bold text-emerald-400">💰 Budget : {h(montant(pr.get('cout')))} {DEVISE}</div>
          </div>{changer}</div>"""
    return out or '<p class="vide">Aucun projet enregistré.</p>'


def section_projets(user, d, s) -> str:
    aides = sorted(d["aides"], key=lambda a: (a.get("statut_validation", "en_attente") != "en_attente"))
    items = ""
    for ai in aides:
        adh = ai.get("adherents") or {}
        st = ai.get("statut_validation", "en_attente")
        if st == "en_attente":
            def bouton(val, lbl, cls, conf):
                return (f"""<form action="/admin/valider-aide" method="POST" class="inline">{champ_user(user)}
                  <input type="hidden" name="aide_id" value="{h(ai['id'])}"><input type="hidden" name="statut_validation" value="{val}">
                  <button class="btn {cls} btn-xs" onclick="return confirm('{conf}')">{lbl}</button></form>""")
            actions = (bouton("approuve", "Approuver", "btn-vert", f"Approuver {montant(ai.get('montant_demande'))} {DEVISE} ? Le montant sera déduit du solde.")
                       + " " + bouton("refuse", "Refuser", "btn-rouge", "Refuser cette demande ?"))
        else:
            actions = badge(st, COULEUR_STATUT.get(st, "slate"))
        items += f"""<li class="ligne py-3 border-b border-white/5 flex justify-between items-center gap-3 text-sm"
              data-filtre="{h((str(adh.get('prenom','')) + ' ' + str(adh.get('nom','')) + ' ' + str(ai.get('motif',''))).lower())}">
          <div class="min-w-0"><b class="text-white">{h(adh.get('prenom'))} {h(adh.get('nom'))}</b>
            <span class="text-amber-400 font-bold">· {h(montant(ai.get('montant_demande')))} {DEVISE}</span>
            <p class="text-slate-300 text-xs">{h(ai.get('motif'))}</p></div>
          <div class="whitespace-nowrap">{actions}</div></li>"""

    return f"""
    <div class="carte">
      <div class="entete-carte"><h2>🤝 Demandes d'aide ({s['aides_attente']} en attente)</h2>
        <input type="search" placeholder="Nom, motif…" class="champ champ-xs w-48" oninput="filtrerLignes(this, 'liste-aides')"></div>
      <ul id="liste-aides" class="max-h-80 overflow-y-auto pr-1">{items or '<p class="vide">Aucune demande.</p>'}</ul>
    </div>
    <div class="grid grid-cols-1 lg:grid-cols-2 gap-4">
      <div class="carte">
        <h2 class="titre">➕ Ajouter un projet</h2>
        <form action="/projets-form" method="POST" class="space-y-3">{champ_user(user)}
          <input type="text" name="titre" placeholder="Titre du projet" maxlength="120" required class="champ">
          <input type="number" name="cout" placeholder="Coût estimé ({DEVISE})" min="0" required class="champ">
          <textarea name="description" rows="3" placeholder="Description" required class="champ"></textarea>
          <input type="text" name="objectifs" placeholder="Objectifs" class="champ">
          <input type="text" name="chronologie" placeholder="Planning / chronologie" class="champ">
          <select name="statut" class="champ"><option>En cours</option><option>Planifié</option><option>Terminé</option></select>
          <button class="btn btn-violet w-full">Publier le projet</button>
        </form>
      </div>
      <div class="carte"><h2 class="titre">🚀 Projets de l'association</h2>
        <div class="max-h-[34rem] overflow-y-auto pr-1 space-y-3">{cartes_projets(d['projets'], user)}</div></div>
    </div>"""


# ---------------------------------------------------------------------
#  Sections — Membre
# ---------------------------------------------------------------------
def section_membre(user, d, periodes) -> str:
    cotis = sorted(d["cotisations"], key=lambda c: str(c.get("periode", "")), reverse=True)
    payees = periodes_payees_par_membre(cotis).get(user["id"], set())
    manquants = mois_en_retard(user, payees, periodes)
    total_paye = sum(float(c.get("montant") or 0) for c in cotis if est_valide(c))

    qr = generer_qrcode_base64(f"TINKA:{user['id']}")  # le QR ne contient plus d'accès au compte
    avatar = (f'<img src="{h(user.get("photo_profil"))}" alt="" class="w-16 h-16 rounded-2xl object-cover border-2 border-emerald-400/80">'
              if user.get("photo_profil") else
              f'<div class="w-16 h-16 rounded-2xl bg-emerald-500/20 border border-emerald-500/40 flex items-center justify-center text-emerald-300 font-black text-2xl">{h((user.get("prenom") or "M")[:1])}</div>')

    if manquants:
        etat = f"""<div class="alerte alerte-ambre">⚠️ <b>{len(manquants)} mois en attente</b> :
            {h(', '.join(libelle_periode(p) for p in manquants))}
            — {h(montant(len(manquants) * COTISATION_MENSUELLE))} {DEVISE}</div>"""
        periode_defaut = manquants[0]
    else:
        etat = '<div class="alerte alerte-vert">✅ Vous êtes à jour de vos cotisations. Merci !</div>'
        periode_defaut = periodes[-1]

    lignes = ""
    for c in cotis:
        if est_valide(c):
            act = f'<a href="/cotisation/recu-pdf/{h(c["id"])}" target="_blank" class="btn btn-bleu btn-xs">📄 Reçu PDF</a>'
        elif c.get("statut_paiement") == "rejete":
            act = badge("Rejeté — contactez le trésorier", "rouge")
        else:
            act = badge("⏳ En validation", "ambre")
        lignes += f"""<li class="py-3 border-b border-white/5 flex justify-between items-center gap-2 text-sm">
          <span><b class="text-emerald-300">{h(libelle_periode(c.get('periode')))}</b> ·
          <span class="text-emerald-400 font-bold">{h(montant(c.get('montant')))} {DEVISE}</span></span>{act}</li>"""

    aides = "".join(
        f"""<li class="py-2 border-b border-white/5 flex justify-between text-sm gap-2"><span class="text-slate-200">{h(a.get('motif'))}
            <b class="text-amber-300">· {h(montant(a.get('montant_demande')))} {DEVISE}</b></span>
            {badge(a.get('statut_validation','en_attente').replace('_',' '), COULEUR_STATUT.get(a.get('statut_validation'), 'ambre'))}</li>"""
        for a in d["aides"])

    presences = d.get("presences", [])
    venus = sum(1 for p in presences if p.get("statut_presence") in ("Present", "Retard"))

    aujourd_hui = datetime.date.today().isoformat()
    a_venir = sorted([e for e in d["evenements"] if str(e.get("date_reunion", ""))[:10] >= aujourd_hui],
                     key=lambda e: str(e.get("date_reunion", "")))
    evts = "".join(
        f"""<div class="carte-interne"><div class="flex justify-between gap-2"><h4 class="font-bold text-sm text-emerald-300">{h(e.get('titre'))}</h4>
            {badge(date_fr(e.get('date_reunion')), 'bleu')}</div>
            <p class="text-xs text-slate-300 mt-1 whitespace-pre-line">{h(e.get('description'))}</p></div>""" for e in a_venir[:5])

    return f"""
    <div class="carte bg-gradient-to-r from-slate-900 via-emerald-950 to-teal-950 flex flex-wrap justify-between items-center gap-4">
      <div class="flex items-center gap-4">{avatar}
        <div><span class="badge badge-vert">Mon compte membre</span>
          <h2 class="text-xl font-black mt-1 text-white">{h(user.get('prenom'))} {h(user.get('nom'))}</h2>
          <p class="text-xs text-slate-300">Secteur <b class="text-emerald-300">{h(user.get('secteur'))}</b> · {h(user.get('telephone'))}</p></div></div>
      <div class="text-center"><div class="bg-white p-1.5 rounded-xl inline-block">
        <img src="data:image/png;base64,{qr}" alt="QR code membre" class="w-20 h-20"></div>
        <p class="text-[10px] text-slate-400 mt-1">Ma carte de présence</p></div>
    </div>

    <div class="grid grid-cols-3 gap-3">
      {kpi("Total versé", f"{h(montant(total_paye))} <small class='text-xs'>{DEVISE}</small>")}
      {kpi("Mois en retard", str(len(manquants)), f"sur les {MOIS_SUIVIS} derniers mois", "amber" if manquants else "vert")}
      {kpi("Présences", str(venus), f"{len(presences)} pointage(s)", "sky")}
    </div>
    {etat}

    <div class="grid grid-cols-1 lg:grid-cols-2 gap-4">
      <div class="carte">
        <div class="entete-carte"><h2>💳 Payer ma cotisation</h2>{badge('Mode test', 'violet')}</div>
        <form action="/initier-paiement-passerelle" method="POST" class="space-y-3">{champ_user(user)}
          <div class="grid grid-cols-2 gap-3">
            <label class="etiquette">Mois<input type="month" name="periode" value="{periode_defaut}" required class="champ mt-1 text-center"></label>
            <label class="etiquette">Montant ({DEVISE})<input type="number" name="montant" value="{COTISATION_MENSUELLE}" min="1" required class="champ mt-1 text-center"></label>
          </div>
          <div class="grid grid-cols-2 gap-3">
            <button name="operateur" value="WaveSandbox" class="btn w-full bg-gradient-to-r from-cyan-600 to-blue-600 text-white">💙 Wave</button>
            <button name="operateur" value="OrangeSandbox" class="btn w-full bg-gradient-to-r from-orange-600 to-amber-600 text-white">🧡 Orange Money</button>
          </div>
        </form>
      </div>
      <div class="carte"><h2 class="titre">📋 Mes cotisations & reçus</h2>
        <ul class="max-h-64 overflow-y-auto pr-1">{lignes or '<p class="vide">Aucun versement pour le moment.</p>'}</ul></div>
    </div>

    <div class="grid grid-cols-1 lg:grid-cols-2 gap-4">
      <div class="carte"><h2 class="titre">📅 Prochains événements</h2>
        <div class="space-y-3">{evts or '<p class="vide">Aucun événement à venir.</p>'}</div></div>
      <div class="carte">
        <h2 class="titre">🤝 Demander une aide</h2>
        <form action="/aide/demander" method="POST" class="space-y-3">{champ_user(user)}
          <input type="text" name="motif" maxlength="300" placeholder="Motif (ex : frais médicaux, décès…)" required class="champ">
          <input type="number" name="montant_demande" min="1" placeholder="Montant demandé ({DEVISE})" required class="champ">
          <button class="btn btn-ambre w-full" onclick="return confirm('Envoyer cette demande au bureau ?')">Envoyer la demande</button>
        </form>
        <ul class="mt-3">{aides}</ul>
      </div>
    </div>

    <div class="carte"><h2 class="titre">🚀 Projets de l'association</h2>
      <div class="grid grid-cols-1 lg:grid-cols-2 gap-3">{cartes_projets(d['projets'])}</div></div>"""


# ---------------------------------------------------------------------
#  Page complète
# ---------------------------------------------------------------------
STYLES = """
<style type="text/tailwindcss">
  .carte { @apply bg-white/5 backdrop-blur-xl p-5 rounded-3xl shadow-xl border border-white/10; }
  .carte-interne { @apply bg-white/5 p-4 rounded-2xl border border-white/10; }
  .titre, .entete-carte h2 { @apply text-sm font-extrabold text-emerald-300; }
  .titre { @apply mb-4 pb-3 border-b border-white/10; }
  .entete-carte { @apply flex flex-wrap justify-between items-center gap-2 mb-4 pb-3 border-b border-white/10; }
  .champ { @apply w-full p-3 text-sm bg-slate-900/80 border border-white/15 rounded-xl text-white placeholder-slate-500
                  focus:outline-none focus:ring-2 focus:ring-emerald-400 transition; }
  .champ-xs { @apply p-2 text-xs; }
  .etiquette { @apply block text-xs font-bold text-slate-300; }
  .btn { @apply inline-flex items-center justify-center gap-1.5 px-4 py-3 rounded-xl text-sm font-bold shadow-lg transition
                active:scale-95 disabled:opacity-50 cursor-pointer; }
  .btn-xs { @apply px-3 py-1.5 text-xs rounded-lg shadow-sm; }
  .btn-vert { @apply bg-emerald-600 hover:bg-emerald-500 text-white; }
  .btn-bleu { @apply bg-blue-600 hover:bg-blue-500 text-white; }
  .btn-rouge { @apply bg-red-600 hover:bg-red-500 text-white; }
  .btn-ambre { @apply bg-amber-600 hover:bg-amber-500 text-white; }
  .btn-violet { @apply bg-indigo-600 hover:bg-indigo-500 text-white; }
  .btn-gris { @apply bg-white/10 hover:bg-white/20 text-slate-100 border border-white/10; }
  .badge { @apply inline-block text-[10px] font-extrabold px-2.5 py-1 rounded-full uppercase tracking-wide border whitespace-nowrap; }
  .badge-vert { @apply bg-emerald-500/15 text-emerald-300 border-emerald-500/30; }
  .badge-ambre { @apply bg-amber-500/15 text-amber-300 border-amber-500/30; }
  .badge-rouge { @apply bg-red-500/15 text-red-300 border-red-500/30; }
  .badge-bleu { @apply bg-sky-500/15 text-sky-300 border-sky-500/30; }
  .badge-violet { @apply bg-indigo-500/15 text-indigo-300 border-indigo-500/30; }
  .badge-slate { @apply bg-white/10 text-slate-300 border-white/10; }
  .zone-table { @apply overflow-auto max-h-80 border border-white/10 rounded-2xl bg-black/20; }
  .tableau { @apply w-full text-left text-sm; }
  .tableau th { @apply sticky top-0 bg-slate-900/95 p-3 text-[11px] font-bold text-slate-300 uppercase tracking-wider; }
  .tableau td { @apply p-3 border-b border-white/5 align-middle; }
  .tableau tr:hover td { @apply bg-white/5; }
  .vide { @apply p-4 text-center text-sm text-slate-400; }
  .kpi { @apply p-4; }
  .kpi-titre { @apply text-[11px] font-bold text-slate-400 uppercase tracking-wider; }
  .kpi-valeur { @apply text-2xl font-black mt-1 font-mono; }
  .kpi-sous { @apply text-[11px] text-slate-400 mt-1; }
  .jauge { @apply h-2 rounded-full bg-white/10 overflow-hidden; }
  .jauge > div { @apply h-full rounded-full bg-gradient-to-r from-emerald-500 to-teal-400; }
  .barre { @apply bg-gradient-to-t from-emerald-600 to-teal-400 hover:from-emerald-500 transition; }
  .alerte { @apply p-4 rounded-2xl text-sm border; }
  .alerte-ambre { @apply bg-amber-500/10 border-amber-500/30 text-amber-200; }
  .alerte-vert { @apply bg-emerald-500/10 border-emerald-500/30 text-emerald-200; }
  .case { @apply flex items-center gap-2 p-2 rounded-lg hover:bg-white/5 text-sm cursor-pointer; }
  .onglet { @apply px-4 py-2.5 text-xs font-extrabold rounded-xl text-slate-300 hover:bg-white/10 transition whitespace-nowrap; }
  .onglet.actif { @apply bg-gradient-to-r from-emerald-600 to-teal-600 text-white shadow-lg; }
  .filtre-galerie { @apply px-3 py-1.5 rounded-full text-xs font-bold bg-white/5 text-slate-300 border border-white/10 hover:bg-white/10 transition; }
  .filtre-galerie.actif { @apply bg-emerald-600 text-white border-emerald-500; }
</style>
"""

SCRIPTS = """
<script>
  function afficherOnglet(id) {
    if (!document.getElementById(id)) return;
    document.querySelectorAll('.contenu-onglet').forEach(c => c.classList.toggle('hidden', c.id !== id));
    document.querySelectorAll('.onglet').forEach(b => b.classList.toggle('actif', b.dataset.cible === id));
    history.replaceState(null, '', location.pathname + location.search + '#' + id);
    window.scrollTo({top: 0, behavior: 'smooth'});
  }
  function sansAccent(t) { return (t || '').toLowerCase().normalize('NFD').replace(/[\\u0300-\\u036f]/g, ''); }
  function filtrerLignes(input, idConteneur) {
    const v = sansAccent(input.value);
    document.querySelectorAll('#' + idConteneur + ' .ligne').forEach(r =>
      r.style.display = sansAccent(r.dataset.filtre).includes(v) ? '' : 'none');
  }
  function filtrerEtat(select, idConteneur) {
    const v = select.value;
    document.querySelectorAll('#' + idConteneur + ' .ligne').forEach(r =>
      r.style.display = (!v || r.dataset.etat === v) ? '' : 'none');
  }
  function filtrerSelect(input, idSelect) {
    const v = sansAccent(input.value), sel = document.getElementById(idSelect);
    let premier = null;
    for (const o of sel.options) {
      if (!o.value) continue;
      const ok = sansAccent(o.dataset.text).includes(v);
      o.hidden = !ok;
      if (ok && !premier) premier = o;
    }
    if (v && premier) sel.value = premier.value;
  }
  function majDateEvt(select) {
    const dt = select.options[select.selectedIndex].dataset.date;
    const form = select.closest('form');
    if (dt && form) form.querySelectorAll('.date-evt').forEach(i => i.value = dt);
  }
  function toutCocher(etat) {
    document.querySelectorAll('#liste-cases .ligne').forEach(l => {
      if (l.style.display !== 'none') l.querySelector('input').checked = etat;
    });
    compterCoches();
  }
  function compterCoches() {
    const n = document.querySelectorAll('#liste-cases input:checked').length;
    const el = document.getElementById('nb-coches'); if (el) el.textContent = n;
  }
  function ouvrirEdition(btn) {
    const m = document.getElementById('modale-edition');
    for (const k of ['id', 'prenom', 'nom', 'telephone', 'secteur'])
      m.querySelector('[data-champ="' + k + '"]').value = btn.dataset[k] || '';
    m.querySelector('#titre-edition').textContent = (btn.dataset.prenom || '') + ' ' + (btn.dataset.nom || '');
    m.classList.remove('hidden'); m.classList.add('flex');
  }
  function fermerEdition() {
    const m = document.getElementById('modale-edition'); if (!m) return; m.classList.add('hidden'); m.classList.remove('flex');
  }
  function ouvrirModale(id) { const m = document.getElementById(id); m.classList.remove('hidden'); m.classList.add('flex'); }
  function fermerModale(id) { const m = document.getElementById(id); m.classList.add('hidden'); m.classList.remove('flex'); }
  // ---- Recherche de membre (saisie de cotisation) ----
  let membres = null, indexActif = 0;
  function listeMembres() {
    if (!membres) { const el = document.getElementById('membres-json'); membres = el ? JSON.parse(el.textContent) : []; }
    return membres;
  }
  function rechercherMembre() {
    const champ = document.getElementById('recherche-cotis'), boite = document.getElementById('resultats-cotis');
    const mots = sansAccent(champ.value).split(/\\s+/).filter(Boolean);
    const res = listeMembres().filter(m => {
      const txt = sansAccent(m.n + ' ' + m.s + ' ' + m.t);
      return mots.every(w => txt.includes(w));
    }).slice(0, 12);
    indexActif = 0;
    if (!res.length) { boite.innerHTML = '<p class="vide">Aucun membre trouvé.</p>'; boite.classList.remove('hidden'); return; }
    boite.innerHTML = '';
    res.forEach((m, i) => {
      const b = document.createElement('button');
      b.type = 'button'; b.dataset.id = m.id;
      b.className = 'res-membre w-full text-left px-4 py-2.5 flex justify-between items-center gap-2 hover:bg-white/10 border-b border-white/5' + (i === 0 ? ' bg-white/10' : '');
      const g = document.createElement('div'); g.className = 'min-w-0';
      const nom = document.createElement('b'); nom.className = 'text-white text-sm block truncate'; nom.textContent = m.n;
      const sous = document.createElement('span'); sous.className = 'text-[11px] text-slate-400'; sous.textContent = m.s + (m.t ? ' · ' + m.t : '');
      g.append(nom, sous);
      const etat = document.createElement('span');
      etat.className = 'badge ' + (m.r.length ? (m.r.length >= 3 ? 'badge-rouge' : 'badge-ambre') : 'badge-vert');
      etat.textContent = m.r.length ? m.r.length + ' mois dû' : 'À jour';
      b.append(g, etat);
      b.addEventListener('mousedown', e => { e.preventDefault(); choisirMembre(m); });
      boite.appendChild(b);
    });
    boite.classList.remove('hidden');
  }
  function toucheRecherche(e) {
    const items = [...document.querySelectorAll('#resultats-cotis .res-membre')];
    if (!items.length) return;
    if (e.key === 'ArrowDown' || e.key === 'ArrowUp') {
      e.preventDefault();
      items[indexActif].classList.remove('bg-white/10');
      indexActif = (indexActif + (e.key === 'ArrowDown' ? 1 : -1) + items.length) % items.length;
      items[indexActif].classList.add('bg-white/10'); items[indexActif].scrollIntoView({block: 'nearest'});
    } else if (e.key === 'Enter') {
      e.preventDefault();
      const m = listeMembres().find(x => String(x.id) === items[indexActif].dataset.id); if (m) choisirMembre(m);
    } else if (e.key === 'Escape') { document.getElementById('resultats-cotis').classList.add('hidden'); }
  }
  function choisirMembre(m) {
    document.getElementById('adherent-cotis').value = m.id;
    document.getElementById('choix-nom').textContent = '✅ ' + m.n + (m.s ? ' (' + m.s + ')' : '');
    document.getElementById('choix-info').textContent = m.r.length ? 'En retard : ' + m.rl.join(', ') : 'À jour de ses cotisations';
    if (m.r.length) document.getElementById('periode-cotis').value = m.r[0];
    document.getElementById('choix-cotis').classList.remove('hidden');
    document.getElementById('recherche-cotis').parentElement.classList.add('hidden');
    document.getElementById('resultats-cotis').classList.add('hidden');
  }
  function effacerChoix() {
    document.getElementById('adherent-cotis').value = '';
    document.getElementById('choix-cotis').classList.add('hidden');
    const r = document.getElementById('recherche-cotis'); r.parentElement.classList.remove('hidden'); r.value = ''; r.focus();
  }
  function verifierChoix() {
    if (document.getElementById('adherent-cotis').value) return true;
    alert('Recherchez puis choisissez un membre dans la liste.');
    document.getElementById('recherche-cotis').focus(); return false;
  }
  document.addEventListener('click', e => {
    const b = document.getElementById('resultats-cotis');
    if (b && !e.target.closest('#resultats-cotis') && e.target.id !== 'recherche-cotis') b.classList.add('hidden');
  });

  // ---- Galerie photos ----
  let photosVisibles = [], photoIndex = 0, toucheX = null;
  function filtrerGalerie(cat, bouton) {
    document.querySelectorAll('.filtre-galerie').forEach(b => b.classList.toggle('actif', b === bouton));
    document.querySelectorAll('#grille-galerie .photo').forEach(f => f.classList.toggle('hidden', cat !== 'tout' && f.dataset.cat !== cat));
  }
  function ouvrirPhoto(fig) {
    photosVisibles = [...document.querySelectorAll('#grille-galerie .photo:not(.hidden)')];
    photoIndex = photosVisibles.indexOf(fig); afficherPhoto();
    const v = document.getElementById('visionneuse'); v.classList.remove('hidden'); v.classList.add('flex');
    document.body.style.overflow = 'hidden';
  }
  function afficherPhoto() {
    const f = photosVisibles[photoIndex]; if (!f) return;
    document.getElementById('visio-img').src = f.dataset.src;
    document.getElementById('visio-titre').textContent = f.dataset.titre || '';
    document.getElementById('visio-legende').textContent = f.dataset.legende || '';
    document.getElementById('visio-compteur').textContent = (photoIndex + 1) + ' / ' + photosVisibles.length;
  }
  function photoSuivante(sens) {
    if (!photosVisibles.length) return;
    photoIndex = (photoIndex + sens + photosVisibles.length) % photosVisibles.length; afficherPhoto();
  }
  function fermerPhoto() {
    const v = document.getElementById('visionneuse'); if (!v) return;
    v.classList.add('hidden'); v.classList.remove('flex'); document.body.style.overflow = '';
  }
  function apercuFichiers(input, idZone) {
    const z = document.getElementById(idZone); z.innerHTML = '';
    [...input.files].slice(0, 10).forEach(f => {
      const img = document.createElement('img'); img.className = 'w-16 h-16 object-cover rounded-lg';
      img.src = URL.createObjectURL(f); z.appendChild(img);
    });
    if (input.files.length > 10) { const p = document.createElement('p'); p.className = 'text-xs text-amber-300'; p.textContent = '10 photos maximum par envoi.'; z.appendChild(p); }
  }
  document.addEventListener('keydown', e => {
    const v = document.getElementById('visionneuse');
    if (!v || v.classList.contains('hidden')) return;
    if (e.key === 'ArrowRight') photoSuivante(1);
    if (e.key === 'ArrowLeft') photoSuivante(-1);
    if (e.key === 'Escape') fermerPhoto();
  });

  // ---- Application installable (PWA) ----
  let invitationInstall = null;
  const estInstallee = () => window.matchMedia('(display-mode: standalone)').matches || navigator.standalone === true;
  const estIOS = () => /iphone|ipad|ipod/i.test(navigator.userAgent) || (navigator.platform === 'MacIntel' && navigator.maxTouchPoints > 1);
  function montrerBoutonsInstall(oui) {
    document.querySelectorAll('.btn-installer').forEach(b => b.classList.toggle('hidden', !oui));
  }
  window.addEventListener('beforeinstallprompt', e => { e.preventDefault(); invitationInstall = e; montrerBoutonsInstall(true); });
  window.addEventListener('appinstalled', () => { invitationInstall = null; montrerBoutonsInstall(false); });
  async function installerAppli() {
    if (invitationInstall) {
      invitationInstall.prompt();
      const choix = await invitationInstall.userChoice;
      if (choix.outcome === 'accepted') montrerBoutonsInstall(false);
      invitationInstall = null;
    } else if (estIOS()) {
      ouvrirModale('modale-ios');
    } else {
      alert("Ouvrez le menu ⋮ du navigateur puis choisissez « Installer l'application » ou « Ajouter à l'écran d'accueil ».");
    }
  }
  if ('serviceWorker' in navigator) {
    window.addEventListener('load', () => navigator.serviceWorker.register('/sw.js').catch(() => {}));
  }
  document.addEventListener('DOMContentLoaded', () => { if (!estInstallee() && estIOS()) montrerBoutonsInstall(true); });

  let lecteur = null;
  function demarrerScan() {
    const zone = document.getElementById('lecteur-qr'), res = document.getElementById('resultat-scan');
    if (typeof Html5Qrcode === 'undefined') { res.textContent = "Scanner indisponible (connexion internet requise)."; return; }
    if (lecteur) { lecteur.stop().catch(() => {}); lecteur = null; zone.classList.add('hidden'); return; }
    zone.classList.remove('hidden');
    lecteur = new Html5Qrcode('lecteur-qr');
    lecteur.start({facingMode: 'environment'}, {fps: 10, qrbox: 220}, texte => {
      const m = texte.match(/TINKA:(\\d+)/) || texte.match(/[?&]id=(\\d+)/);
      const sel = document.getElementById('select-pointage');
      if (m && sel.querySelector('option[value="' + m[1] + '"]')) {
        sel.value = m[1];
        res.textContent = '✅ ' + sel.options[sel.selectedIndex].text + ' — choisissez l\\'événement puis validez.';
        if (navigator.vibrate) navigator.vibrate(120);
      } else {
        res.textContent = '❌ QR code non reconnu ou membre inactif.';
      }
      lecteur.stop().catch(() => {}); lecteur = null; zone.classList.add('hidden');
    }).catch(err => { res.textContent = "Impossible d'ouvrir la caméra : " + err; zone.classList.add('hidden'); lecteur = null; });
  }
  document.addEventListener('DOMContentLoaded', () => {
    const h = location.hash.slice(1);
    const premier = document.querySelector('.onglet');
    if (premier) afficherOnglet(document.getElementById(h) && h.startsWith('tab-') ? h : premier.dataset.cible);
    document.querySelectorAll('#liste-cases input').forEach(i => i.addEventListener('change', compterCoches));
    // Anti double-clic : désactive le bouton après l'envoi d'un formulaire
    document.querySelectorAll('form').forEach(f => f.addEventListener('submit', e => {
      const b = e.submitter; if (b) setTimeout(() => { b.disabled = true; b.style.opacity = .6; }, 0);
    }));
    const t = document.getElementById('toast'); if (t) setTimeout(() => t.remove(), 5000);
    const v = document.getElementById('visionneuse');
    if (v) {
      v.addEventListener('touchstart', e => { toucheX = e.touches[0].clientX; }, {passive: true});
      v.addEventListener('touchend', e => {
        if (toucheX === null) return;
        const dx = e.changedTouches[0].clientX - toucheX; toucheX = null;
        if (Math.abs(dx) > 50) photoSuivante(dx < 0 ? 1 : -1);
      });
    }
    document.addEventListener('keydown', e => { if (e.key === 'Escape') { fermerEdition(); fermerModale('modale-mdp'); } });
  });
</script>
"""


def modale_edition(user) -> str:
    return f"""
    <div id="modale-edition" class="fixed inset-0 bg-black/70 backdrop-blur-sm z-50 hidden items-center justify-center p-4"
         onclick="if(event.target===this) fermerEdition()">
      <div class="bg-slate-900 border border-white/20 rounded-3xl max-w-lg w-full p-6 shadow-2xl">
        <div class="flex justify-between items-center mb-4 pb-3 border-b border-white/10">
          <h3 class="font-bold text-emerald-300">✏️ Modifier : <span id="titre-edition"></span></h3>
          <button type="button" onclick="fermerEdition()" class="text-slate-400 hover:text-white text-xl" aria-label="Fermer">✕</button></div>
        <form action="/admin/modifier-adherent" method="POST" class="space-y-3">{champ_user(user)}
          <input type="hidden" name="adherent_id" data-champ="id">
          <div class="grid grid-cols-2 gap-3">
            <label class="etiquette">Prénom<input name="prenom" data-champ="prenom" required class="champ mt-1"></label>
            <label class="etiquette">Nom<input name="nom" data-champ="nom" required class="champ mt-1"></label>
            <label class="etiquette">Téléphone<input name="telephone" data-champ="telephone" type="tel" required class="champ mt-1"></label>
            <label class="etiquette">Secteur<input name="secteur" data-champ="secteur" required class="champ mt-1"></label>
          </div>
          <label class="etiquette text-amber-300">🔐 Nouveau mot de passe (optionnel)
            <input type="password" name="nouveau_mdp" minlength="6" autocomplete="new-password"
                   placeholder="Laisser vide pour ne pas changer" class="champ mt-1"></label>
          <button class="btn btn-vert w-full">Enregistrer</button>
        </form>
      </div>
    </div>"""


CATEGORIES_GALERIE = {"realisation": "🏗️ Réalisations", "village": "🏡 Le village"}


def photos_triees(galerie) -> list:
    return sorted(galerie, key=lambda g: (int(g.get("ordre") or 0), -int(g.get("id") or 0)))


def section_galerie_publique(d) -> str:
    photos = photos_triees(d.get("galerie", []))
    if not photos:
        return ""
    nb = {c: sum(1 for p in photos if p.get("categorie") == c) for c in CATEGORIES_GALERIE}
    filtres = '<button type="button" class="filtre-galerie actif" onclick="filtrerGalerie(\'tout\', this)">Tout</button>' + "".join(
        f'<button type="button" class="filtre-galerie" onclick="filtrerGalerie(\'{c}\', this)">{lbl} ({nb[c]})</button>'
        for c, lbl in CATEGORIES_GALERIE.items() if nb[c])
    vignettes = "".join(f"""
      <figure class="photo relative group cursor-pointer overflow-hidden rounded-2xl bg-black/30 aspect-square"
              data-cat="{h(p.get('categorie'))}" data-src="{h(p.get('url'))}" data-titre="{h(p.get('titre'))}"
              data-legende="{h(p.get('legende'))}" onclick="ouvrirPhoto(this)">
        <img src="{h(p.get('url'))}" alt="{h(p.get('titre') or 'Photo')}" loading="lazy"
             class="w-full h-full object-cover group-hover:scale-105 transition duration-500">
        {f'<figcaption class="absolute inset-x-0 bottom-0 bg-gradient-to-t from-black/80 to-transparent p-2.5 pt-8 text-xs font-bold text-white truncate">{h(p.get("titre"))}</figcaption>' if p.get('titre') else ''}
      </figure>""" for p in photos)
    return f"""
    <section class="carte" aria-label="Galerie photos">
      <div class="entete-carte"><h2>📸 Notre association en images</h2><div class="flex flex-wrap gap-1.5">{filtres}</div></div>
      <div id="grille-galerie" class="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-4 gap-2">{vignettes}</div>
    </section>
    <div id="visionneuse" class="fixed inset-0 z-[70] bg-black/95 hidden flex-col items-center justify-center p-3"
         onclick="if(event.target===this) fermerPhoto()">
      <button type="button" onclick="fermerPhoto()" class="absolute top-3 right-4 text-white text-3xl" aria-label="Fermer">✕</button>
      <span id="visio-compteur" class="absolute top-4 left-4 text-xs text-slate-300 font-mono"></span>
      <img id="visio-img" alt="" class="max-h-[78vh] max-w-full rounded-xl object-contain shadow-2xl">
      <div class="text-center mt-3 max-w-xl"><b id="visio-titre" class="text-white block"></b>
        <p id="visio-legende" class="text-sm text-slate-300 whitespace-pre-line"></p></div>
      <button type="button" onclick="photoSuivante(-1)" class="absolute left-2 top-1/2 -translate-y-1/2 text-white text-4xl px-3 py-6 opacity-70 hover:opacity-100" aria-label="Précédente">‹</button>
      <button type="button" onclick="photoSuivante(1)" class="absolute right-2 top-1/2 -translate-y-1/2 text-white text-4xl px-3 py-6 opacity-70 hover:opacity-100" aria-label="Suivante">›</button>
    </div>"""


def section_galerie_admin(user, d) -> str:
    photos = photos_triees(d.get("galerie", []))
    opts = lambda sel: "".join(f'<option value="{c}" {"selected" if c == sel else ""}>{lbl}</option>' for c, lbl in CATEGORIES_GALERIE.items())
    cartes = ""
    for i, p in enumerate(photos):
        pid = h(p.get("id"))
        fleches = "".join(
            f'<form action="/admin/galerie/deplacer" method="POST">{champ_user(user)}<input type="hidden" name="photo_id" value="{pid}">'
            f'<input type="hidden" name="sens" value="{sens}"><button class="btn btn-gris btn-xs" {"disabled" if bloque else ""} title="{titre}">{icone}</button></form>'
            for sens, icone, titre, bloque in ((-1, "↑", "Monter", i == 0), (1, "↓", "Descendre", i == len(photos) - 1)))
        cartes += f"""
        <div class="carte-interne flex gap-3">
          <img src="{h(p.get('url'))}" alt="" loading="lazy" class="w-24 h-24 sm:w-28 sm:h-28 object-cover rounded-xl shrink-0">
          <div class="flex-1 min-w-0 space-y-2">
            <form action="/admin/galerie/modifier" method="POST" enctype="multipart/form-data" class="space-y-2">{champ_user(user)}
              <input type="hidden" name="photo_id" value="{pid}">
              <div class="grid grid-cols-1 sm:grid-cols-2 gap-2">
                <input name="titre" value="{h(p.get('titre'))}" maxlength="80" placeholder="Titre" class="champ champ-xs">
                <select name="categorie" class="champ champ-xs">{opts(p.get('categorie'))}</select>
              </div>
              <textarea name="legende" rows="1" maxlength="300" placeholder="Légende" class="champ champ-xs">{h(p.get('legende'))}</textarea>
              <div class="flex flex-wrap gap-2 items-center">
                <label class="btn btn-gris btn-xs cursor-pointer">🔄 Remplacer la photo
                  <input type="file" name="photo" accept="image/*" class="hidden" onchange="this.closest('label').firstChild.textContent='✅ Nouvelle photo choisie '"></label>
                <button class="btn btn-vert btn-xs">Enregistrer</button>
              </div>
            </form>
            <div class="flex gap-1">
              {fleches}
              <form action="/admin/galerie/supprimer" method="POST" class="ml-auto">{champ_user(user)}<input type="hidden" name="photo_id" value="{pid}">
                <button class="btn btn-rouge btn-xs" onclick="return confirm('Supprimer définitivement cette photo ?')">🗑 Supprimer</button></form>
            </div>
          </div>
        </div>"""
    return f"""
    <div class="carte">
      <h2 class="titre">➕ Ajouter des photos</h2>
      <form action="/admin/galerie/ajouter" method="POST" enctype="multipart/form-data" class="space-y-3">{champ_user(user)}
        <label class="block border-2 border-dashed border-emerald-500/40 rounded-2xl p-5 text-center cursor-pointer hover:bg-white/5 transition">
          <span class="text-3xl">📷</span>
          <span class="block text-sm font-bold text-emerald-300 mt-1">Choisir jusqu'à 10 photos</span>
          <span class="block text-[11px] text-slate-400">JPEG, PNG ou WEBP · redimensionnées automatiquement</span>
          <input type="file" name="photos" accept="image/*" multiple required class="hidden" onchange="apercuFichiers(this, 'apercu-galerie')">
        </label>
        <div id="apercu-galerie" class="flex flex-wrap gap-2"></div>
        <div class="grid grid-cols-1 sm:grid-cols-2 gap-3">
          <select name="categorie" class="champ">{opts('realisation')}</select>
          <input name="titre" maxlength="80" placeholder="Titre (ex : Inauguration du puits)" class="champ">
        </div>
        <textarea name="legende" rows="2" maxlength="300" placeholder="Légende (optionnel)" class="champ"></textarea>
        <button class="btn btn-vert w-full">Publier les photos</button>
      </form>
    </div>
    <div class="carte">
      <h2 class="titre">🖼️ Photos publiées ({len(photos)}) — visibles en bas de la page de chaque membre</h2>
      <div class="grid grid-cols-1 lg:grid-cols-2 gap-3">{cartes or '<p class="vide">Aucune photo pour le moment.</p>'}</div>
    </div>"""


HEAD_PWA = """<meta name="theme-color" content="#064e3b">
  <link rel="manifest" href="/manifest.webmanifest">
  <link rel="icon" type="image/png" sizes="192x192" href="/icone-192.png">
  <link rel="apple-touch-icon" href="/icone-180.png">
  <meta name="apple-mobile-web-app-capable" content="yes">
  <meta name="mobile-web-app-capable" content="yes">
  <meta name="apple-mobile-web-app-status-bar-style" content="black-translucent">
  <meta name="apple-mobile-web-app-title" content="Tinka Asso">"""

BOUTON_INSTALLER = ('<button type="button" class="btn-installer hidden btn btn-vert btn-xs animate-pulse" onclick="installerAppli()" '
                    'title="Installer l\'application sur ce téléphone">📲<span>Installer l\'appli</span></button>')

MODALE_IOS = """
  <div id="modale-ios" class="fixed inset-0 bg-black/70 backdrop-blur-sm z-50 hidden items-end sm:items-center justify-center p-4"
       onclick="if(event.target===this) fermerModale('modale-ios')">
    <div class="bg-slate-900 border border-white/20 rounded-3xl max-w-sm w-full p-6 shadow-2xl text-sm space-y-3">
      <div class="flex justify-between items-center"><h3 class="font-bold text-emerald-300">📲 Installer sur iPhone / iPad</h3>
        <button type="button" onclick="fermerModale('modale-ios')" class="text-slate-400 text-xl" aria-label="Fermer">✕</button></div>
      <ol class="space-y-2 text-slate-200 list-decimal pl-5">
        <li>Ouvrez cette page dans <b>Safari</b>.</li>
        <li>Touchez le bouton <b>Partager</b> <span class="inline-block border border-white/40 rounded px-1">⬆︎</span> en bas de l'écran.</li>
        <li>Choisissez <b>« Sur l'écran d'accueil »</b>, puis <b>Ajouter</b>.</li>
      </ol>
      <p class="text-[11px] text-slate-400">L'icône Tinka apparaît alors sur votre écran d'accueil, comme une application.</p>
    </div>
  </div>"""


def modale_mdp(user) -> str:
    return f"""
    <div id="modale-mdp" class="fixed inset-0 bg-black/70 backdrop-blur-sm z-50 hidden items-center justify-center p-4"
         onclick="if(event.target===this) fermerModale('modale-mdp')">
      <div class="bg-slate-900 border border-white/20 rounded-3xl max-w-sm w-full p-6 shadow-2xl">
        <div class="flex justify-between items-center mb-4 pb-3 border-b border-white/10">
          <h3 class="font-bold text-emerald-300">🔑 Changer mon mot de passe</h3>
          <button type="button" onclick="fermerModale('modale-mdp')" class="text-slate-400 hover:text-white text-xl" aria-label="Fermer">✕</button></div>
        <form action="/profil/mot-de-passe" method="POST" class="space-y-3">{champ_user(user)}
          <input type="password" name="actuel" placeholder="Mot de passe actuel" autocomplete="current-password" required class="champ">
          <input type="password" name="nouveau" placeholder="Nouveau (6 caractères min.)" minlength="6" autocomplete="new-password" required class="champ">
          <input type="password" name="confirmation" placeholder="Confirmer le nouveau" minlength="6" autocomplete="new-password" required class="champ">
          <button class="btn btn-vert w-full">Enregistrer</button>
        </form>
      </div>
    </div>"""


def page(user, contenu, onglets_html="", msg=None) -> str:
    toast = bloc_flash(msg)
    initiale = h((user.get("prenom") or "M")[:1].upper())
    return f"""<!DOCTYPE html>
<html lang="fr">
<head>
  <meta charset="UTF-8"><meta name="viewport" content="width=device-width, initial-scale=1.0">
  {HEAD_PWA}
  <title>Tableau de bord — Tinka Association</title>
  <script src="https://cdn.tailwindcss.com"></script>
  <script src="https://unpkg.com/html5-qrcode@2.3.8/html5-qrcode.min.js" defer></script>
  {STYLES}
  {SCRIPTS}
</head>
<body class="bg-gradient-to-tr from-slate-950 via-emerald-950 to-teal-950 bg-fixed text-slate-100 font-sans min-h-screen pb-24 sm:pb-8">
  {toast}
  <div class="max-w-6xl mx-auto px-3 sm:px-6 pt-4 space-y-4">
    <header class="carte !p-4 flex justify-between items-center gap-3">
      <div class="flex items-center gap-3 min-w-0">
        <div class="w-11 h-11 shrink-0 rounded-2xl bg-gradient-to-br from-emerald-500 to-teal-600 flex items-center justify-center font-black text-lg">{initiale}</div>
        <div class="min-w-0"><h1 class="font-extrabold text-white truncate">{h(user.get('prenom'))} {h(user.get('nom'))}</h1>
          <p class="text-[11px] text-emerald-400 uppercase font-bold tracking-widest">{h(user.get('role'))} · Tinka Association</p></div>
      </div>
      <div class="flex gap-2">
        {BOUTON_INSTALLER}
        <button type="button" class="btn btn-gris btn-xs" onclick="ouvrirModale('modale-mdp')" title="Changer mon mot de passe">🔑<span class="hidden sm:inline">Mot de passe</span></button>
        <a href="/deconnexion" class="btn btn-gris btn-xs">⏻<span class="hidden sm:inline">Déconnexion</span></a>
      </div>
    </header>
    {onglets_html}
    {contenu}
  </div>
  {modale_edition(user) if est_tresorier(user) else ""}
  {modale_mdp(user)}
  {MODALE_IOS}
</body>
</html>"""


def barre_onglets(onglets) -> str:
    boutons = "".join(f'<button type="button" class="onglet" data-cible="{i}" onclick="afficherOnglet(\'{i}\')">{lbl}</button>'
                      for i, lbl in onglets)
    # En haut sur ordinateur, en bas de l'écran sur téléphone (pouce)
    return f"""<nav class="fixed bottom-0 inset-x-0 sm:sticky sm:top-2 z-40 bg-slate-900/90 backdrop-blur-xl p-2 sm:rounded-2xl
                border-t sm:border border-white/10 shadow-2xl flex gap-1 overflow-x-auto justify-between sm:justify-start">{boutons}</nav>"""


def construire_dashboard(user: dict, d: dict, msg=None, aujourd_hui: Optional[datetime.date] = None) -> str:
    periodes = periodes_recentes(MOIS_SUIVIS, aujourd_hui or datetime.date.today())
    if not est_tresorier(user):
        return page(user, section_membre(user, d, periodes) + section_galerie_publique(d), msg=msg)

    s = calculer_stats(d, periodes)
    nb_attente = s["adh_attente"]
    nb_aides = s["aides_attente"]
    onglets = [("tab-tresorerie", "💼 Trésorerie"),
               ("tab-adherents", f"👥 Annuaire{f' ({nb_attente})' if nb_attente else ''}"),
               ("tab-pointage", "📋 Pointage"),
               ("tab-projets", "🚀 Projets & aides" + (f" ({nb_aides})" if nb_aides else "")),
               ("tab-galerie", "📸 Galerie")]
    contenu = f"""
    <section id="tab-tresorerie" class="contenu-onglet space-y-4">{section_tresorerie(user, d, s, periodes)}</section>
    <section id="tab-adherents" class="contenu-onglet hidden space-y-4">{section_annuaire(user, d, s)}</section>
    <section id="tab-pointage" class="contenu-onglet hidden space-y-4">{section_pointage(user, d, s)}</section>
    <section id="tab-projets" class="contenu-onglet hidden space-y-4">{section_projets(user, d, s)}</section>
    <section id="tab-galerie" class="contenu-onglet hidden space-y-4">{section_galerie_admin(user, d)}</section>
    {section_galerie_publique(d)}"""
    return page(user, contenu, barre_onglets(onglets), msg)




# =====================================================================
#  PAGES PUBLIQUES : portail, connexion, inscription
# =====================================================================
def bloc_flash(f) -> str:
    if not f:
        return ""
    type_msg, message = f
    couleur = {"succes": "bg-emerald-600", "erreur": "bg-red-600", "info": "bg-sky-600"}.get(type_msg, "bg-slate-700")
    return (f'<div id="toast" role="status" class="fixed top-4 left-1/2 -translate-x-1/2 z-[60] {couleur} text-white text-sm font-bold '
            f'px-5 py-3 rounded-2xl shadow-2xl max-w-[92vw] text-center">{h(message)}</div>')


@app.get("/", response_class=HTMLResponse)
def afficher_portail(request: Request):
    if request.session.get("user_id"):
        return RedirectResponse("/dashboard", status_code=303)
    qr_b64 = generer_qrcode_base64(URL_SITE)
    csrf = jeton_csrf(request)
    return f"""<!DOCTYPE html>
<html lang="fr">
<head>
  <meta charset="UTF-8"><meta name="viewport" content="width=device-width, initial-scale=1.0">
  {HEAD_PWA}
  <title>{h(NOM_ASSO)} — Portail</title>
  <script src="https://cdn.tailwindcss.com"></script>
  {STYLES}
  {SCRIPTS}
</head>
<body class="bg-gradient-to-tr from-slate-950 via-emerald-950 to-teal-950 bg-fixed text-slate-100 font-sans antialiased min-h-screen py-8 px-4">
  {bloc_flash(lire_flash(request))}
  <main class="max-w-md mx-auto space-y-4">
    <div class="text-center">
      <span class="badge badge-vert">Portail officiel</span>
      <div class="mt-3">{BOUTON_INSTALLER}</div>
      <h1 class="text-2xl font-black text-white tracking-tight mt-3">{h(NOM_ASSO)}</h1>
      <p class="text-xs text-slate-300 mt-1">Gestion administrative, financière & Daara</p>
    </div>

    <div class="carte">
      <div class="flex border-b border-white/10 mb-4 -mt-1">
        <button type="button" class="onglet-portail flex-1 py-2 text-sm font-bold text-emerald-300 border-b-2 border-emerald-400" data-cible="f-connexion">🔐 Connexion</button>
        <button type="button" class="onglet-portail flex-1 py-2 text-sm font-bold text-slate-400 border-b-2 border-transparent" data-cible="f-inscription">📝 Inscription</button>
      </div>

      <form id="f-connexion" action="/login-form" method="POST" class="space-y-3">
        <input type="hidden" name="csrf" value="{h(csrf)}">
        <label class="etiquette">Numéro de téléphone
          <input type="tel" name="telephone" inputmode="tel" autocomplete="username" placeholder="ex : 771234567" required class="champ mt-1"></label>
        <label class="etiquette">Mot de passe
          <div class="relative mt-1"><input type="password" name="mot_de_passe" autocomplete="current-password" required class="champ pr-12">
          <button type="button" onclick="voirMdp(this)" class="absolute right-3 top-1/2 -translate-y-1/2 text-slate-400 text-xs" aria-label="Afficher">👁</button></div></label>
        <button class="btn btn-bleu w-full">Se connecter</button>
        <p class="text-[11px] text-slate-400 text-center">Mot de passe oublié ? Contactez le trésorier ou l'administrateur.</p>
      </form>

      <form id="f-inscription" action="/adherents-form" method="POST" enctype="multipart/form-data" class="space-y-3 hidden">
        <input type="hidden" name="csrf" value="{h(csrf)}">
        <div class="grid grid-cols-2 gap-2">
          <label class="etiquette">Nom<input name="nom" maxlength="60" required class="champ mt-1"></label>
          <label class="etiquette">Prénom<input name="prenom" maxlength="60" required class="champ mt-1"></label>
        </div>
        <label class="etiquette">Téléphone<input type="tel" name="telephone" inputmode="tel" placeholder="ex : 776510244" required class="champ mt-1"></label>
        <label class="etiquette">Adresse<input name="adresse" maxlength="150" required class="champ mt-1"></label>
        <label class="etiquette">Secteur<input name="secteur" maxlength="60" required class="champ mt-1"></label>
        <label class="etiquette">Photo de profil (optionnel, 1,5 Mo max)
          <input type="file" name="file_photo" accept="image/jpeg,image/png,image/webp"
                 class="w-full text-xs text-slate-300 mt-1 file:py-2 file:px-3 file:rounded-xl file:border-0 file:bg-emerald-500/20 file:text-emerald-300 file:font-semibold"></label>
        <label class="etiquette">Mot de passe (6 caractères minimum)
          <input type="password" name="mot_de_passe" minlength="6" autocomplete="new-password" required class="champ mt-1"></label>
        <button class="btn btn-vert w-full">S'inscrire</button>
        <p class="text-[11px] text-slate-400 text-center">Votre compte sera activé après validation par le bureau.</p>
      </form>
    </div>

    <div class="text-center">
      <div class="bg-white p-2.5 rounded-2xl inline-block"><img src="data:image/png;base64,{qr_b64}" alt="QR code du site" class="w-24 h-24"></div>
      <p class="text-[11px] text-slate-400 mt-1">Scannez pour partager le site</p>
    </div>
  </main>
  {MODALE_IOS}
  <script>
    document.querySelectorAll('.onglet-portail').forEach(b => b.addEventListener('click', () => {{
      document.querySelectorAll('.onglet-portail').forEach(x => {{
        const actif = x === b;
        x.classList.toggle('text-emerald-300', actif); x.classList.toggle('border-emerald-400', actif);
        x.classList.toggle('text-slate-400', !actif); x.classList.toggle('border-transparent', !actif);
        document.getElementById(x.dataset.cible).classList.toggle('hidden', !actif);
      }});
    }}));
    function voirMdp(b) {{ const i = b.previousElementSibling; i.type = i.type === 'password' ? 'text' : 'password'; }}
  </script>
</body>
</html>"""


def trouver_par_telephone(tel_norm: str) -> Optional[dict]:
    res = supabase.table("adherents").select("*").eq("telephone", tel_norm).limit(1).execute()
    if res.data:
        return res.data[0]
    # Anciens comptes enregistrés avec indicatif ou espaces : recherche plus large
    for a in tout_charger("adherents", "id,telephone"):
        if normaliser_telephone(a.get("telephone", "")) == tel_norm:
            r = supabase.table("adherents").select("*").eq("id", a["id"]).limit(1).execute()
            return r.data[0] if r.data else None
    return None


@app.post("/login-form")
@app.post("/login-form/")
def login_form(request: Request, telephone: str = Form(""), mot_de_passe: str = Form(""), csrf: str = Form("")):
    if not hmac.compare_digest(csrf, request.session.get("csrf", "")):
        raise Redirection("/", "Page expirée, veuillez réessayer.")
    tel_norm = normaliser_telephone(telephone)
    cle = f"{ip_client(request)}|{tel_norm}"
    if trop_de_tentatives(cle):
        raise Redirection("/", "Trop de tentatives. Réessayez dans 15 minutes.")
    user = trouver_par_telephone(tel_norm) if tel_norm and mot_de_passe else None
    if not user or not verifier_mdp(mot_de_passe, user.get("mot_de_passe", "")):
        _tentatives[cle].append(time.time())
        raise Redirection("/", "Numéro de téléphone ou mot de passe incorrect.")
    if user.get("statut") != "actif":
        raise Redirection("/", "Votre compte est en attente de validation par le bureau.", "info")
    if not est_hache(user.get("mot_de_passe")):
        # Migration automatique des anciens mots de passe en clair
        supabase.table("adherents").update({"mot_de_passe": hacher_mdp(mot_de_passe)}).eq("id", user["id"]).execute()
    _tentatives.pop(cle, None)
    request.session.clear()
    request.session["user_id"] = user["id"]
    flash(request, f"Bienvenue {user.get('prenom', '')} !")
    return RedirectResponse("/dashboard", status_code=303)


@app.post("/adherents-form")
@app.post("/adherents-form/")
async def creer_adherent_form(
    request: Request, nom: str = Form(""), prenom: str = Form(""), telephone: str = Form(""),
    adresse: str = Form(""), secteur: str = Form(""), mot_de_passe: str = Form(""),
    csrf: str = Form(""), file_photo: Optional[UploadFile] = File(None),
):
    if not hmac.compare_digest(csrf, request.session.get("csrf", "")):
        raise Redirection("/", "Page expirée, veuillez réessayer.")
    tel_norm = normaliser_telephone(telephone)
    nom, prenom, adresse, secteur = (x.strip()[:150] for x in (nom, prenom, adresse, secteur))
    if not (nom and prenom and secteur):
        raise Redirection("/", "Nom, prénom et secteur sont obligatoires.")
    if not 8 <= len(tel_norm) <= 12:
        raise Redirection("/", "Numéro de téléphone invalide.")
    if len(mot_de_passe) < 6:
        raise Redirection("/", "Le mot de passe doit contenir au moins 6 caractères.")
    if trouver_par_telephone(tel_norm):
        raise Redirection("/", "Ce numéro est déjà associé à un compte.")
    try:
        photo = await photo_vers_base64(file_photo)
    except ValueError as e:
        raise Redirection("/", str(e))
    supabase.table("adherents").insert({
        "nom": nom, "prenom": prenom, "email": f"{tel_norm}@tinka.local", "telephone": tel_norm,
        "adresse": adresse, "secteur": secteur, "photo_profil": photo, "mot_de_passe": hacher_mdp(mot_de_passe),
    }).execute()
    raise Redirection("/", "Inscription envoyée ! Votre compte sera activé après validation par le bureau.", "succes")


@app.get("/deconnexion")
def deconnexion(request: Request):
    request.session.clear()
    flash(request, "Vous êtes déconnecté.", "info")
    return RedirectResponse("/", status_code=303)


# =====================================================================
#  TABLEAU DE BORD
# =====================================================================
@app.get("/dashboard", response_class=HTMLResponse)
def afficher_dashboard(request: Request):
    user = exiger(request)
    try:
        donnees = charger_donnees(user, est_tresorier(user))
        return HTMLResponse(construire_dashboard(user, donnees, lire_flash(request)))
    except Exception:
        log.exception("Erreur dashboard (user %s)", user.get("id"))
        return HTMLResponse(PAGE_ERREUR, status_code=500)


# =====================================================================
#  ROUTES ADMINISTRATION (bureau : admin + trésorier)
# =====================================================================
BUREAU = ("admin", "tresorier")


@app.post("/admin/valider-adherent")
def valider_adherent(request: Request, adherent_id: int = Form(...), csrf: str = Form("")):
    exiger(request, csrf, BUREAU)
    supabase.table("adherents").update({"statut": "actif"}).eq("id", adherent_id).execute()
    return retour("tab-adherents", "Adhérent validé ✓", request=request)


@app.post("/admin/changer-role")
def changer_role(request: Request, adherent_id: int = Form(...), nouveau_role: str = Form(...), csrf: str = Form("")):
    user = exiger(request, csrf, ("admin",))
    if nouveau_role not in ROLES:
        return retour("tab-adherents", "Rôle inconnu.", "erreur", request)
    if adherent_id == user["id"]:
        return retour("tab-adherents", "Vous ne pouvez pas modifier votre propre rôle.", "erreur", request)
    supabase.table("adherents").update({"role": nouveau_role}).eq("id", adherent_id).execute()
    return retour("tab-adherents", "Rôle mis à jour ✓", request=request)


@app.post("/admin/changer-statut")
def changer_statut(request: Request, adherent_id: int = Form(...), statut: str = Form(...), csrf: str = Form("")):
    user = exiger(request, csrf, BUREAU)
    if statut not in ("actif", "inactif") or adherent_id == user["id"]:
        return retour("tab-adherents", "Opération impossible.", "erreur", request)
    supabase.table("adherents").update({"statut": statut}).eq("id", adherent_id).execute()
    return retour("tab-adherents", "Statut mis à jour ✓", request=request)


@app.post("/admin/modifier-adherent")
def modifier_adherent(
    request: Request, adherent_id: int = Form(...), nom: str = Form(""), prenom: str = Form(""),
    telephone: str = Form(""), secteur: str = Form(""), nouveau_mdp: str = Form(""), csrf: str = Form(""),
):
    user = exiger(request, csrf, BUREAU)
    cible = (supabase.table("adherents").select("id,role").eq("id", adherent_id).limit(1).execute().data or [None])[0]
    if not cible:
        return retour("tab-adherents", "Adhérent introuvable.", "erreur", request)
    if cible.get("role") == "admin" and not est_admin(user):
        return retour("tab-adherents", "Seul un administrateur peut modifier un compte administrateur.", "erreur", request)
    tel_norm = normaliser_telephone(telephone)
    existant = trouver_par_telephone(tel_norm) if tel_norm else None
    if existant and existant["id"] != adherent_id:
        return retour("tab-adherents", "Ce numéro appartient déjà à un autre membre.", "erreur", request)
    maj = {"nom": nom.strip()[:60], "prenom": prenom.strip()[:60], "telephone": tel_norm, "secteur": secteur.strip()[:60]}
    if nouveau_mdp.strip():
        if len(nouveau_mdp.strip()) < 6:
            return retour("tab-adherents", "Mot de passe trop court (6 caractères minimum).", "erreur", request)
        maj["mot_de_passe"] = hacher_mdp(nouveau_mdp.strip())
    supabase.table("adherents").update(maj).eq("id", adherent_id).execute()
    return retour("tab-adherents", "Informations mises à jour ✓", request=request)


@app.post("/admin/maj-solde-initial")
def maj_solde_initial(request: Request, solde_initial: float = Form(...), csrf: str = Form("")):
    exiger(request, csrf, BUREAU)
    supabase.table("parametres").update({"solde_initial": solde_initial}).eq("id", 1).execute()
    return retour("tab-tresorerie", "Solde initial mis à jour ✓", request=request)


@app.post("/admin/saisir-cotisation")
def saisir_cotisation(
    request: Request, adherent_id: int = Form(...), montant_c: float = Form(..., alias="montant"),
    periode: str = Form(...), mode_paiement: str = Form("especes"), csrf: str = Form(""),
):
    exiger(request, csrf, BUREAU)
    if not periode_valide(periode) or montant_c <= 0:
        return retour("tab-tresorerie", "Période ou montant invalide.", "erreur", request)
    if mode_paiement not in ("especes", "mobile_money", "virement", "regularisation"):
        mode_paiement = "especes"
    deja = (supabase.table("cotisations").select("id").eq("adherent_id", adherent_id)
            .eq("periode", periode).eq("statut_paiement", "valide").execute().data)
    if deja:
        return retour("tab-tresorerie", f"Ce membre a déjà une cotisation validée pour {libelle_periode(periode)}.", "erreur", request)
    supabase.table("cotisations").insert({
        "adherent_id": adherent_id, "montant": montant_c, "periode": periode,
        "mode_paiement": mode_paiement, "statut_paiement": "valide",
    }).execute()
    return retour("tab-tresorerie", f"Cotisation de {libelle_periode(periode)} enregistrée ✓", request=request)


@app.post("/admin/valider-paiement-mobile")
def valider_paiement_mobile(request: Request, paiement_id: int = Form(...), csrf: str = Form("")):
    exiger(request, csrf, BUREAU)
    supabase.table("cotisations").update({"statut_paiement": "valide"}).eq("id", paiement_id).execute()
    return retour("tab-tresorerie", "Paiement validé ✓ — le reçu est disponible pour le membre.", request=request)


@app.post("/admin/rejeter-paiement")
def rejeter_paiement(request: Request, paiement_id: int = Form(...), csrf: str = Form("")):
    exiger(request, csrf, BUREAU)
    supabase.table("cotisations").update({"statut_paiement": "rejete"}).eq("id", paiement_id).neq("statut_paiement", "valide").execute()
    return retour("tab-tresorerie", "Paiement rejeté.", "info", request)


@app.post("/admin/decaissement")
def ajouter_decaissement(request: Request, motif: str = Form(...), montant_d: float = Form(..., alias="montant"),
                         beneficiaire: str = Form(""), csrf: str = Form("")):
    exiger(request, csrf, BUREAU)
    if montant_d <= 0 or not motif.strip():
        return retour("tab-tresorerie", "Motif et montant obligatoires.", "erreur", request)
    try:
        supabase.table("decaissements").insert({
            "motif": motif.strip()[:200], "montant": montant_d, "beneficiaire": beneficiaire.strip()[:100],
        }).execute()
    except Exception:
        log.exception("Insertion décaissement")
        return retour("tab-tresorerie", "Impossible d'enregistrer : exécutez le script supabase_migration.sql.", "erreur", request)
    return retour("tab-tresorerie", "Dépense enregistrée ✓", request=request)


@app.post("/admin/creer-evenement")
def creer_evenement(request: Request, titre: str = Form(...), date_reunion: str = Form(...),
                    description: str = Form(""), csrf: str = Form("")):
    exiger(request, csrf, BUREAU)
    supabase.table("evenements").insert({
        "titre": titre.strip()[:120], "date_reunion": date_reunion, "description": description.strip()[:1000],
    }).execute()
    return retour("tab-pointage", "Événement créé ✓", request=request)


@app.post("/admin/pointer-presence")
def pointer_presence(request: Request, adherent_id: int = Form(...), evenement_titre: str = Form(...),
                     date_reunion: str = Form(...), statut_presence: str = Form("Present"), csrf: str = Form("")):
    exiger(request, csrf, BUREAU)
    if statut_presence not in ("Present", "Retard", "Absent", "Excuse"):
        statut_presence = "Present"
    deja = (supabase.table("presences_association").select("id").eq("adherent_id", adherent_id)
            .eq("evenement_titre", evenement_titre).eq("date_reunion", date_reunion).execute().data)
    if deja:
        supabase.table("presences_association").update({"statut_presence": statut_presence}).eq("id", deja[0]["id"]).execute()
        return retour("tab-pointage", "Pointage mis à jour ✓", request=request)
    supabase.table("presences_association").insert({
        "adherent_id": adherent_id, "evenement_titre": evenement_titre,
        "date_reunion": date_reunion, "statut_presence": statut_presence,
    }).execute()
    return retour("tab-pointage", "Présence enregistrée ✓", request=request)


@app.post("/admin/pointer-presences-groupe")
async def pointer_presences_groupe(request: Request):
    form = await request.form()
    exiger(request, str(form.get("csrf", "")), BUREAU)
    ids = [int(x) for x in form.getlist("adherent_ids") if str(x).isdigit()]
    titre, date_r = form.get("evenement_titre"), form.get("date_reunion")
    statut = form.get("statut_presence", "Present")
    if statut not in ("Present", "Retard", "Absent", "Excuse"):
        statut = "Present"
    if not ids or not titre or not date_r:
        return retour("tab-pointage", "Choisissez un événement, une date et au moins un membre.", "erreur", request)
    deja = {p["adherent_id"] for p in (supabase.table("presences_association").select("adherent_id")
            .eq("evenement_titre", titre).eq("date_reunion", date_r).execute().data or [])}
    lignes = [{"adherent_id": i, "evenement_titre": titre, "date_reunion": date_r, "statut_presence": statut}
              for i in ids if i not in deja]
    if lignes:
        supabase.table("presences_association").insert(lignes).execute()
    return retour("tab-pointage", f"{len(lignes)} pointage(s) enregistré(s), {len(ids) - len(lignes)} déjà pointé(s).", request=request)


@app.post("/admin/valider-aide")
def valider_aide(request: Request, aide_id: int = Form(...), statut_validation: str = Form(...), csrf: str = Form("")):
    exiger(request, csrf, BUREAU)
    if statut_validation not in ("approuve", "refuse"):
        return retour("tab-projets", "Décision inconnue.", "erreur", request)
    supabase.table("aides").update({"statut_validation": statut_validation}).eq("id", aide_id).eq("statut_validation", "en_attente").execute()
    return retour("tab-projets", "Demande approuvée ✓" if statut_validation == "approuve" else "Demande refusée.", request=request)


@app.post("/projets-form")
@app.post("/projets-form/")
def ajouter_projet(request: Request, titre: str = Form(...), description: str = Form(""), objectifs: str = Form(""),
                   cout: float = Form(0), chronologie: str = Form(""), statut: str = Form("En cours"), csrf: str = Form("")):
    exiger(request, csrf, BUREAU)
    supabase.table("projets").insert({
        "titre": titre.strip()[:120], "description": description.strip()[:2000], "objectifs": objectifs.strip()[:500] or "N/A",
        "cout": max(cout, 0), "chronologie": chronologie.strip()[:200] or "N/A",
        "statut": statut if statut in ("En cours", "Planifié", "Terminé") else "En cours",
    }).execute()
    return retour("tab-projets", "Projet publié ✓", request=request)


@app.post("/admin/projet-statut")
def projet_statut(request: Request, projet_id: int = Form(...), statut: str = Form(...), csrf: str = Form("")):
    exiger(request, csrf, BUREAU)
    if statut in ("En cours", "Planifié", "Terminé"):
        supabase.table("projets").update({"statut": statut}).eq("id", projet_id).execute()
    return retour("tab-projets", "Statut du projet mis à jour ✓", request=request)


# =====================================================================
#  ESPACE MEMBRE
# =====================================================================
@app.post("/aide/demander")
@app.post("/aides-form")
def demander_aide(request: Request, motif: str = Form(""), montant_demande: float = Form(0), csrf: str = Form("")):
    user = exiger(request, csrf)
    motif = motif.strip()[:300]
    if not motif or montant_demande <= 0:
        return retour("", "Motif et montant obligatoires.", "erreur", request)
    supabase.table("aides").insert({
        "adherent_id": user["id"], "motif": motif, "montant_demande": montant_demande, "statut_validation": "en_attente",
    }).execute()
    return retour("", "Demande d'aide envoyée au bureau ✓", request=request)


@app.post("/profil/mot-de-passe")
def changer_mon_mdp(request: Request, actuel: str = Form(""), nouveau: str = Form(""), confirmation: str = Form(""),
                    csrf: str = Form("")):
    user = exiger(request, csrf)
    stocke = (supabase.table("adherents").select("mot_de_passe").eq("id", user["id"]).limit(1).execute().data or [{}])[0]
    if not verifier_mdp(actuel, stocke.get("mot_de_passe", "")):
        return retour("", "Mot de passe actuel incorrect.", "erreur", request)
    if len(nouveau) < 6 or nouveau != confirmation:
        return retour("", "Le nouveau mot de passe doit faire 6 caractères minimum et être confirmé.", "erreur", request)
    supabase.table("adherents").update({"mot_de_passe": hacher_mdp(nouveau)}).eq("id", user["id"]).execute()
    return retour("", "Mot de passe modifié ✓", request=request)


@app.post("/initier-paiement-passerelle")
def initier_paiement_passerelle(request: Request, montant_p: float = Form(..., alias="montant"), periode: str = Form(...),
                                operateur: str = Form(...), csrf: str = Form("")):
    exiger(request, csrf)
    if not periode_valide(periode) or montant_p <= 0 or operateur not in ("WaveSandbox", "OrangeSandbox"):
        return retour("", "Paiement invalide.", "erreur", request)
    request.session["paiement"] = {"montant": montant_p, "periode": periode, "operateur": operateur}
    return RedirectResponse("/simulation-page-paiement", status_code=303)


@app.get("/simulation-page-paiement", response_class=HTMLResponse)
def simulation_page_paiement(request: Request):
    user = exiger(request)
    p = request.session.get("paiement")
    if not p:
        return RedirectResponse("/dashboard", status_code=303)
    nom_op = "Wave" if p["operateur"] == "WaveSandbox" else "Orange Money"
    return f"""<!DOCTYPE html>
<html lang="fr"><head>
  <meta charset="UTF-8"><meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>Paiement {h(nom_op)} — Test</title>
  {HEAD_PWA}
  <script src="https://cdn.tailwindcss.com"></script>{STYLES}{SCRIPTS}
</head>
<body class="bg-slate-950 text-slate-100 font-sans min-h-screen flex items-center justify-center p-4">
  <div class="carte max-w-sm w-full text-center space-y-5">
    <span class="badge badge-violet">Passerelle de test · {h(nom_op)}</span>
    <h1 class="text-xl font-black text-white">Confirmer le paiement</h1>
    <div class="bg-black/40 p-4 rounded-2xl space-y-2 text-sm text-left">
      <div class="flex justify-between"><span class="text-slate-400">Membre</span><b>{h(user.get('prenom'))} {h(user.get('nom'))}</b></div>
      <div class="flex justify-between"><span class="text-slate-400">Montant</span><b class="text-emerald-400">{h(montant(p['montant']))} {DEVISE}</b></div>
      <div class="flex justify-between"><span class="text-slate-400">Mois</span><b>{h(libelle_periode(p['periode']))}</b></div>
    </div>
    <p class="text-[11px] text-amber-300">Mode test : aucun argent n'est prélevé. Le paiement sera ensuite vérifié et validé par le trésorier.</p>
    <form action="/valider-simulation-paiement" method="POST" class="space-y-2">
      <input type="hidden" name="csrf" value="{h(user['_csrf'])}">
      <button class="btn btn-vert w-full">✅ Simuler un paiement réussi</button>
      <a href="/dashboard" class="btn btn-gris w-full">Annuler</a>
    </form>
  </div>
</body></html>"""


@app.post("/valider-simulation-paiement")
def valider_simulation_paiement(request: Request, csrf: str = Form("")):
    user = exiger(request, csrf)
    p = request.session.pop("paiement", None)
    if not p:
        return retour("", "Aucun paiement en cours.", "erreur", request)
    supabase.table("cotisations").insert({
        "adherent_id": user["id"], "montant": p["montant"], "periode": p["periode"],
        "mode_paiement": f"passerelle_{p['operateur'].lower()}",
        # En attente : le trésorier vérifie la réception avant que l'argent compte dans la caisse
        "statut_paiement": "en_attente",
    }).execute()
    return retour("", "Paiement transmis ✓ Le reçu sera disponible après validation du trésorier.", request=request)


# =====================================================================
#  DOCUMENTS : reçus, annuaire PDF, export CSV
# =====================================================================
def entete_pdf(p, titre: str, sous_titre: str = ""):
    largeur, hauteur = A4
    p.setFillColorRGB(0.02, 0.31, 0.24)
    p.rect(0, hauteur - 80, largeur, 80, stroke=0, fill=1)
    p.setFillColorRGB(1, 1, 1)
    p.setFont("Helvetica-Bold", 16)
    p.drawString(40, hauteur - 40, NOM_ASSO.upper())
    p.setFont("Helvetica", 10)
    p.drawString(40, hauteur - 58, titre)
    if sous_titre:
        p.drawRightString(largeur - 40, hauteur - 58, sous_titre)
    p.setFillColorRGB(0, 0, 0)
    return largeur, hauteur


@app.get("/cotisation/recu-pdf/{cotisation_id}")
def telecharger_recu_pdf(request: Request, cotisation_id: int):
    user = exiger(request)
    res = supabase.table("cotisations").select("*, adherents(nom, prenom, secteur, telephone)").eq("id", cotisation_id).execute()
    if not res.data:
        return retour("", "Reçu introuvable.", "erreur", request)
    c = res.data[0]
    if c.get("adherent_id") != user["id"] and not est_tresorier(user):
        return retour("", "Ce reçu ne vous appartient pas.", "erreur", request)
    if c.get("statut_paiement") != "valide":
        return retour("", "Ce paiement n'a pas encore été validé.", "info", request)
    adh = c.get("adherents") or {}
    buf = io.BytesIO()
    p = canvas.Canvas(buf, pagesize=A4)
    largeur, hauteur = entete_pdf(p, "Reçu officiel de cotisation", f"N° TK-{c['id']:05d}")
    y = hauteur - 120
    p.setFont("Helvetica", 11)
    for lbl, val in (("Date de paiement", formater_date(c.get("date_paiement") or c.get("created_at") or "")),
                     ("Membre", f"{adh.get('prenom', '')} {adh.get('nom', '')}"),
                     ("Secteur", adh.get("secteur", "")), ("Téléphone", adh.get("telephone", "")),
                     ("Période couverte", libelle_periode(c.get("periode"))),
                     ("Mode de paiement", str(c.get("mode_paiement", "")).replace("_", " "))):
        p.setFont("Helvetica", 10); p.setFillColorRGB(0.4, 0.4, 0.4); p.drawString(50, y, lbl)
        p.setFont("Helvetica-Bold", 11); p.setFillColorRGB(0, 0, 0); p.drawString(190, y, str(val or ""))
        y -= 24
    p.setStrokeColorRGB(0.02, 0.5, 0.35)
    p.roundRect(50, y - 60, largeur - 100, 50, 8, stroke=1, fill=0)
    p.setFont("Helvetica-Bold", 16)
    p.drawCentredString(largeur / 2, y - 42, f"Montant versé : {formater_montant(c.get('montant', 0))} {DEVISE}")
    qr = generer_qrcode_base64(f"TINKA-RECU:{c['id']}:{c.get('adherent_id')}:{c.get('periode')}")
    from reportlab.lib.utils import ImageReader
    p.drawImage(ImageReader(io.BytesIO(base64.b64decode(qr))), largeur - 140, 60, 90, 90)
    p.setFont("Helvetica-Oblique", 8)
    p.drawString(50, 70, f"Document généré le {datetime.date.today().strftime('%d-%m-%Y')} — {URL_SITE}")
    p.save()
    buf.seek(0)
    return StreamingResponse(buf, media_type="application/pdf",
                             headers={"Content-Disposition": f'attachment; filename="recu_TK-{c["id"]:05d}.pdf"'})


@app.get("/adherents/export-pdf")
def export_adherents_pdf(request: Request):
    exiger(request, roles=BUREAU)
    adherents = sorted(charger_adherents(), key=lambda a: (str(a.get("nom", "")).lower(), str(a.get("prenom", "")).lower()))
    buf = io.BytesIO()
    p = canvas.Canvas(buf, pagesize=A4)
    largeur, hauteur = entete_pdf(p, f"Annuaire des adhérents ({len(adherents)})", datetime.date.today().strftime("%d-%m-%Y"))
    colonnes = [(40, "Nom & prénom"), (210, "Secteur"), (320, "Téléphone"), (420, "Rôle"), (490, "Statut")]

    def entetes(y):
        p.setFont("Helvetica-Bold", 9)
        for x, t in colonnes:
            p.drawString(x, y, t)
        p.line(40, y - 4, largeur - 40, y - 4)
        p.setFont("Helvetica", 9)
        return y - 18

    y = entetes(hauteur - 110)
    for i, a in enumerate(adherents):
        if y < 50:
            p.showPage()
            y = entetes(hauteur - 50)
        if i % 2 == 0:
            p.setFillColorRGB(0.94, 0.97, 0.95); p.rect(38, y - 4, largeur - 76, 15, stroke=0, fill=1); p.setFillColorRGB(0, 0, 0)
        for (x, _), val in zip(colonnes, (f"{a.get('prenom', '')} {a.get('nom', '')}"[:32], str(a.get("secteur", ""))[:20],
                                         a.get("telephone", ""), a.get("role", ""), str(a.get("statut", "")).replace("_", " "))):
            p.drawString(x, y, str(val or ""))
        y -= 16
    p.save()
    buf.seek(0)
    return StreamingResponse(buf, media_type="application/pdf",
                             headers={"Content-Disposition": 'attachment; filename="annuaire_adherents.pdf"'})


@app.get("/admin/export-cotisations.csv")
def export_cotisations(request: Request):
    exiger(request, roles=BUREAU)
    cotis = tout_charger("cotisations", "*, adherents(nom, prenom, secteur, telephone)")
    buf = io.StringIO()
    buf.write("﻿")  # accents corrects dans Excel
    w = csv.writer(buf, delimiter=";")
    w.writerow(["Période", "Nom", "Prénom", "Secteur", "Téléphone", "Montant", "Mode", "Statut"])
    for c in sorted(cotis, key=lambda x: str(x.get("periode", "")), reverse=True):
        a = c.get("adherents") or {}
        w.writerow([c.get("periode"), a.get("nom"), a.get("prenom"), a.get("secteur"), a.get("telephone"),
                    c.get("montant"), c.get("mode_paiement"), c.get("statut_paiement")])
    nom = f"cotisations_tinka_{datetime.date.today().isoformat()}.csv"
    return StreamingResponse(iter([buf.getvalue()]), media_type="text/csv; charset=utf-8",
                             headers={"Content-Disposition": f'attachment; filename="{nom}"'})


# =====================================================================
#  GALERIE PHOTOS (stockage Supabase Storage, bucket "galerie")
# =====================================================================
BUCKET_GALERIE = os.getenv("BUCKET_GALERIE", "galerie")
TAILLE_MAX_BRUTE = 12_000_000  # 12 Mo avant compression (photos de téléphone)


def preparer_image(contenu: bytes) -> bytes:
    """Redresse, réduit à 1600 px et compresse en JPEG (~200-400 Ko)."""
    from PIL import Image, ImageOps
    try:
        img = Image.open(io.BytesIO(contenu))
        img = ImageOps.exif_transpose(img)
    except Exception:
        raise ValueError("Format d'image non reconnu (utilisez JPEG, PNG ou WEBP).")
    if img.mode not in ("RGB", "L"):
        fond = Image.new("RGB", img.size, (255, 255, 255))
        img = img.convert("RGBA")
        fond.paste(img, mask=img.split()[-1])
        img = fond
    img.thumbnail((1600, 1600))
    sortie = io.BytesIO()
    img.convert("RGB").save(sortie, format="JPEG", quality=80, optimize=True, progressive=True)
    return sortie.getvalue()


def stocker_image(jpeg: bytes) -> tuple:
    """Renvoie (url, chemin). Si le stockage Supabase n'est pas prêt, l'image est gardée en base."""
    chemin = f"{datetime.date.today():%Y/%m}/{uuid.uuid4().hex}.jpg"
    try:
        supabase.storage.from_(BUCKET_GALERIE).upload(chemin, jpeg, {"content-type": "image/jpeg"})
        url = supabase.storage.from_(BUCKET_GALERIE).get_public_url(chemin)
        return str(url).rstrip("?"), chemin
    except Exception as exc:
        log.warning("Stockage Supabase indisponible (%s) : image gardée en base.", exc)
        return "data:image/jpeg;base64," + base64.b64encode(jpeg).decode(), ""


def effacer_image(chemin: str):
    if chemin:
        try:
            supabase.storage.from_(BUCKET_GALERIE).remove([chemin])
        except Exception as exc:
            log.warning("Suppression du fichier %s impossible : %s", chemin, exc)


async def lire_image(fichier) -> Optional[bytes]:
    if not fichier or not getattr(fichier, "filename", ""):
        return None
    contenu = await fichier.read(TAILLE_MAX_BRUTE + 1)
    if len(contenu) > TAILLE_MAX_BRUTE:
        raise ValueError(f"« {fichier.filename} » est trop lourde (12 Mo maximum).")
    return preparer_image(contenu) if contenu else None


@app.post("/admin/galerie/ajouter")
async def galerie_ajouter(request: Request):
    form = await request.form()
    exiger(request, str(form.get("csrf", "")), BUREAU)
    categorie = form.get("categorie") if form.get("categorie") in CATEGORIES_GALERIE else "realisation"
    titre, legende = str(form.get("titre", "")).strip()[:80], str(form.get("legende", "")).strip()[:300]
    fichiers = [f for f in form.getlist("photos") if getattr(f, "filename", "")][:10]
    if not fichiers:
        return retour("tab-galerie", "Choisissez au moins une photo.", "erreur", request)
    existantes = charger_sans_erreur("galerie", "id,ordre")
    ordre = min([int(g.get("ordre") or 0) for g in existantes] + [0]) - len(fichiers)
    ajoutees, erreurs, en_base = 0, [], False
    for i, f in enumerate(fichiers):
        try:
            jpeg = await lire_image(f)
            if not jpeg:
                continue
            url, chemin = stocker_image(jpeg)
            en_base |= not chemin
            supabase.table("galerie").insert({
                "categorie": categorie, "titre": titre, "legende": legende,
                "url": url, "chemin": chemin, "ordre": ordre + i,
            }).execute()
            ajoutees += 1
        except ValueError as e:
            erreurs.append(str(e))
        except Exception:
            log.exception("Ajout photo galerie")
            return retour("tab-galerie", "Impossible d'enregistrer : exécutez le script supabase_migration.sql.", "erreur", request)
    msg = f"{ajoutees} photo(s) publiée(s) ✓"
    if erreurs:
        msg += " — " + " ".join(erreurs[:2])
    elif en_base:
        msg += " (stockage Supabase non configuré : voir le script SQL)"
    return retour("tab-galerie", msg, "succes" if ajoutees else "erreur", request)


@app.post("/admin/galerie/modifier")
async def galerie_modifier(request: Request):
    form = await request.form()
    exiger(request, str(form.get("csrf", "")), BUREAU)
    pid = int(form.get("photo_id") or 0)
    ancienne = (supabase.table("galerie").select("id,chemin").eq("id", pid).limit(1).execute().data or [None])[0]
    if not ancienne:
        return retour("tab-galerie", "Photo introuvable.", "erreur", request)
    maj = {"titre": str(form.get("titre", "")).strip()[:80], "legende": str(form.get("legende", "")).strip()[:300]}
    if form.get("categorie") in CATEGORIES_GALERIE:
        maj["categorie"] = form.get("categorie")
    try:
        jpeg = await lire_image(form.get("photo"))
    except ValueError as e:
        return retour("tab-galerie", str(e), "erreur", request)
    if jpeg:
        maj["url"], maj["chemin"] = stocker_image(jpeg)
    supabase.table("galerie").update(maj).eq("id", pid).execute()
    if jpeg:
        effacer_image(ancienne.get("chemin"))
    return retour("tab-galerie", "Photo mise à jour ✓", request=request)


@app.post("/admin/galerie/supprimer")
def galerie_supprimer(request: Request, photo_id: int = Form(...), csrf: str = Form("")):
    exiger(request, csrf, BUREAU)
    photo = (supabase.table("galerie").select("id,chemin").eq("id", photo_id).limit(1).execute().data or [None])[0]
    if photo:
        supabase.table("galerie").delete().eq("id", photo_id).execute()
        effacer_image(photo.get("chemin"))
    return retour("tab-galerie", "Photo supprimée.", "info", request)


@app.post("/admin/galerie/deplacer")
def galerie_deplacer(request: Request, photo_id: int = Form(...), sens: int = Form(1), csrf: str = Form("")):
    exiger(request, csrf, BUREAU)
    photos = photos_triees(charger_sans_erreur("galerie", "id,ordre"))
    pos = next((i for i, p in enumerate(photos) if p["id"] == photo_id), None)
    cible = None if pos is None else pos + (1 if sens > 0 else -1)
    if pos is None or not 0 <= cible < len(photos):
        return retour("tab-galerie", request=request)
    photos[pos], photos[cible] = photos[cible], photos[pos]
    for i, p in enumerate(photos):
        if int(p.get("ordre") or 0) != i:
            supabase.table("galerie").update({"ordre": i}).eq("id", p["id"]).execute()
    return retour("tab-galerie", "Ordre mis à jour ✓", request=request)


# =====================================================================
#  APPLICATION INSTALLABLE (PWA) : manifeste, icônes, service worker
# =====================================================================
from functools import lru_cache
from fastapi.responses import JSONResponse, Response


@lru_cache(maxsize=8)
def dessiner_icone(taille: int) -> bytes:
    """Icône dessinée à la volée (pas de fichier à héberger) : « T » blanc sur fond vert, toit doré."""
    from PIL import Image, ImageDraw
    t = taille
    img = Image.new("RGB", (t, t))
    d = ImageDraw.Draw(img)
    for y in range(t):  # dégradé vert foncé -> émeraude
        r = y / t
        d.line([(0, y), (t, y)], fill=(int(2 + 4 * r), int(44 + 76 * r), int(34 + 53 * r)))
    c = t / 2
    # Toit doré (maison commune)
    d.polygon([(c - 0.30 * t, 0.40 * t), (c, 0.20 * t), (c + 0.30 * t, 0.40 * t), (c + 0.24 * t, 0.40 * t),
               (c, 0.27 * t), (c - 0.24 * t, 0.40 * t)], fill=(251, 191, 36))
    # Lettre T
    d.rounded_rectangle([c - 0.22 * t, 0.44 * t, c + 0.22 * t, 0.53 * t], radius=int(0.02 * t), fill="white")
    d.rounded_rectangle([c - 0.05 * t, 0.44 * t, c + 0.05 * t, 0.80 * t], radius=int(0.02 * t), fill="white")
    buf = io.BytesIO()
    img.save(buf, format="PNG", optimize=True)
    return buf.getvalue()


@app.get("/icone-{taille}.png")
def icone(taille: int):
    if taille not in (180, 192, 512):
        taille = 192
    return Response(dessiner_icone(taille), media_type="image/png",
                    headers={"Cache-Control": "public, max-age=604800"})


@app.get("/manifest.webmanifest")
def manifeste():
    return JSONResponse({
        "id": "/",
        "name": NOM_ASSO,
        "short_name": "Tinka Asso",
        "description": "Cotisations, présences, aides et projets de l'association.",
        "lang": "fr",
        "start_url": "/?source=appli",
        "scope": "/",
        "display": "standalone",
        "orientation": "portrait",
        "background_color": "#022c22",
        "theme_color": "#064e3b",
        "icons": [
            {"src": "/icone-192.png", "sizes": "192x192", "type": "image/png", "purpose": "any"},
            {"src": "/icone-512.png", "sizes": "512x512", "type": "image/png", "purpose": "any"},
            {"src": "/icone-512.png", "sizes": "512x512", "type": "image/png", "purpose": "maskable"},
        ],
        "shortcuts": [{"name": "Mon tableau de bord", "url": "/dashboard", "icons": [{"src": "/icone-192.png", "sizes": "192x192"}]}],
    }, media_type="application/manifest+json")


SERVICE_WORKER = """
const CACHE = 'tinka-asso-v1';
const A_GARDER = ['/hors-ligne', '/icone-192.png', '/icone-512.png', '/manifest.webmanifest'];
self.addEventListener('install', e => {
  e.waitUntil(caches.open(CACHE).then(c => c.addAll(A_GARDER)).then(() => self.skipWaiting()));
});
self.addEventListener('activate', e => {
  e.waitUntil(caches.keys().then(cles => Promise.all(cles.filter(k => k !== CACHE).map(k => caches.delete(k))))
    .then(() => self.clients.claim()));
});
self.addEventListener('fetch', e => {
  const req = e.request;
  if (req.method !== 'GET') return;
  // Pages : toujours les données à jour ; page « hors ligne » si pas de réseau
  if (req.mode === 'navigate') {
    e.respondWith(fetch(req).catch(() => caches.match('/hors-ligne')));
    return;
  }
  // Icônes, styles, scripts externes : cache d'abord pour un démarrage rapide
  const url = new URL(req.url);
  if (A_GARDER.includes(url.pathname) || url.hostname.includes('cdn.tailwindcss.com') || url.hostname.includes('unpkg.com')) {
    e.respondWith(caches.match(req).then(r => r || fetch(req).then(rep => {
      const copie = rep.clone(); caches.open(CACHE).then(c => c.put(req, copie)); return rep;
    })));
  }
});
"""


@app.get("/sw.js")
def service_worker():
    return Response(SERVICE_WORKER, media_type="application/javascript",
                    headers={"Cache-Control": "no-cache", "Service-Worker-Allowed": "/"})


@app.get("/hors-ligne", response_class=HTMLResponse)
def hors_ligne():
    return f"""<!DOCTYPE html><html lang="fr"><head><meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0"><title>Hors connexion — Tinka</title>
<style>body{{margin:0;min-height:100vh;display:flex;align-items:center;justify-content:center;font-family:system-ui,sans-serif;
background:linear-gradient(160deg,#020617,#022c22 60%,#134e4a);color:#e2e8f0;text-align:center;padding:24px}}
.c{{max-width:340px}} img{{width:88px;height:88px;border-radius:22px}} h1{{font-size:20px;margin:18px 0 8px}}
p{{color:#94a3b8;font-size:14px;line-height:1.5}} button{{margin-top:18px;background:#059669;color:#fff;border:0;
padding:12px 22px;border-radius:14px;font-weight:700;font-size:15px}}</style></head>
<body><div class="c"><img src="/icone-192.png" alt=""><h1>Pas de connexion Internet</h1>
<p>{h(NOM_ASSO)} a besoin d'Internet pour afficher vos cotisations à jour. Vérifiez votre réseau puis réessayez.</p>
<button onclick="location.reload()">🔄 Réessayer</button></div></body></html>"""


if __name__ == "__main__":
    import uvicorn
    os.environ.setdefault("SESSION_SECRET", "dev")
    uvicorn.run("app_asso:app", host="127.0.0.1", port=8000, reload=True)
