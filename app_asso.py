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
            <div class="bg-white/5 backdrop-blur-md p-5 rounded-2xl border border-white/10 mb-4 shadow-lg">
                <div class="flex justify-between items-start gap-2 mb-2">
                    <h4 class="font-bold text-base text-emerald-300">{pr.get('titre', '')}</h4>
                    <span class="text-[10px] font-extrabold px-3 py-1 rounded-full bg-indigo-500/20 text-indigo-300 border border-indigo-500/30 uppercase">{pr.get('statut', '')}</span>
                </div>
                <p class="text-xs text-slate-300 mb-3 leading-relaxed">{pr.get('description', '')}</p>
                <div class="text-xs text-slate-300 space-y-1.5 bg-black/20 p-3 rounded-xl border border-white/5">
                    <div><b>🎯 Objectifs :</b> {pr.get('objectifs', 'Non spécifié')}</div>
                    <div><b>📅 Planning :</b> {pr.get('chronologie', 'Non spécifié')}</div>
                    <div class="font-bold text-emerald-400">💰 Budget estimé : {formater_montant(pr.get('cout', 0))} CFA</div>
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
            
            btn_wa = f"<a href='{link_wa}' target='_blank' class='bg-emerald-600 hover:bg-emerald-500 text-white px-3 py-1.5 rounded-xl text-xs font-bold ml-2 shadow-md transition inline-flex items-center gap-1'>💬 Relancer</a>" if mois_manquants else ""
            
            statut_ajour = "<span class='text-emerald-400 font-bold bg-emerald-500/10 border border-emerald-500/20 px-3 py-1 rounded-full text-xs'>À jour ✓</span>" if not mois_manquants else f"<span class='text-amber-400 font-bold bg-amber-500/10 border border-amber-500/20 px-3 py-1 rounded-full text-xs'>En attente ({mois_passes[0]})</span>{btn_wa}"
            
            suivi_retards_html += f"""
            <tr class='border-b border-white/5 text-sm retard-row hover:bg-white/5 transition' data-nom='{str(a.get('prenom','')).lower()} {str(a.get('nom','')).lower()}' data-secteur='{str(a.get('secteur','')).lower()}'>
                <td class='p-3.5 font-bold text-white'>{a.get('prenom','')} {a.get('nom','')} <span class='text-xs text-slate-400 font-normal'>({a.get('secteur','')})</span></td>
                <td class='p-3.5 text-right'>{statut_ajour}</td>
            </tr>
            """

        adherents_table_rows = ""
        modals_html = ""
        for a in all_adherents:
            actions_admin = ""
            if is_tresorier and a.get('statut') == 'en_attente':
                actions_admin += f"""
                <form action="/admin/valider-adherent" method="POST" class="inline"><input type="hidden" name="user_id" value="{user['id']}"><input type="hidden" name="adherent_id" value="{a['id']}"><button type="submit" class="bg-emerald-600 hover:bg-emerald-500 text-white px-3 py-1.5 rounded-xl text-xs font-bold shadow-md transition">Valider</button></form>
                """
            if is_admin:
                actions_admin += f"""
                <form action="/admin/changer-role" method="POST" class="inline-block ml-1">
                    <input type="hidden" name="user_id" value="{user['id']}"><input type="hidden" name="adherent_id" value="{a['id']}">
                    <select name="nouveau_role" onchange="this.form.submit()" class="p-1.5 text-xs bg-slate-900 border border-white/20 rounded-xl text-emerald-300 font-bold shadow-sm">
                        <option value="membre" {'selected' if a.get('role')=='membre' else ''}>Membre</option>
                        <option value="tresorier" {'selected' if a.get('role')=='tresorier' else ''}>Trésorier</option>
                        <option value="admin" {'selected' if a.get('role')=='admin' else ''}>Admin</option>
                    </select>
                </form>
                """

            btn_modif = f"""<button onclick="openModal({a['id']})" class="bg-blue-500/20 hover:bg-blue-500/30 text-blue-300 border border-blue-500/30 px-3 py-1 rounded-xl text-xs font-bold ml-1 transition">⚙️ Modifier</button>""" if is_tresorier or a['id'] == user['id'] else ""

            adherents_table_rows += f"""
            <tr class="hover:bg-white/5 border-b border-white/5 text-sm adherent-row transition" data-nom="{str(a.get('prenom','')).lower()} {str(a.get('nom','')).lower()}" data-secteur="{str(a.get('secteur','')).lower()}" data-tel="{str(a.get('telephone',''))}">
                <td class="p-3.5 font-semibold text-white">{a.get('prenom','')} {a.get('nom','')}</td>
                <td class="p-3.5"><span class="text-[10px] bg-white/10 text-slate-300 px-3 py-1 rounded-full font-bold uppercase tracking-wider">{a.get('role','')}</span></td>
                <td class="p-3.5 text-slate-300">{a.get('secteur','')}</td>
                <td class="p-3.5 font-mono text-xs text-slate-400">{a.get('telephone','')}</td>
                <td class="p-3.5 text-right">{actions_admin}{btn_modif}</td>
            </tr>
            """

            modals_html += f"""
            <div id="modal-{a['id']}" class="fixed inset-0 bg-black/70 backdrop-blur-md z-50 hidden flex items-center justify-center p-4">
                <div class="bg-slate-900 border border-white/20 rounded-3xl max-w-lg w-full p-6 shadow-2xl">
                    <div class="flex justify-between items-center mb-4 border-b border-white/10 pb-3"><h3 class="font-bold text-lg text-emerald-300">Modifier : {a.get('prenom','')} {a.get('nom','')}</h3><button onclick="closeModal({a['id']})" class="font-bold text-lg text-slate-400 hover:text-white">✕</button></div>
                    <form action="/admin/modifier-adherent" method="POST" class="space-y-4 mb-4">
                        <input type="hidden" name="user_id" value="{user['id']}"><input type="hidden" name="adherent_id" value="{a['id']}">
                        <div class="grid grid-cols-2 gap-3">
                            <div><label class="block text-xs font-bold mb-1 text-slate-300">Prénom</label><input type="text" name="prenom" value="{a.get('prenom','')}" required class="w-full p-3 text-sm bg-slate-800 border border-white/20 rounded-xl text-white"></div>
                            <div><label class="block text-xs font-bold mb-1 text-slate-300">Nom</label><input type="text" name="nom" value="{a.get('nom','')}" required class="w-full p-3 text-sm bg-slate-800 border border-white/20 rounded-xl text-white"></div>
                        </div>
                        <div class="grid grid-cols-2 gap-3">
                            <div><label class="block text-xs font-bold mb-1 text-slate-300">Téléphone</label><input type="text" name="telephone" value="{a.get('telephone','')}" required class="w-full p-3 text-sm bg-slate-800 border border-white/20 rounded-xl text-white"></div>
                            <div><label class="block text-xs font-bold mb-1 text-slate-300">Secteur</label><input type="text" name="secteur" value="{a.get('secteur','')}" required class="w-full p-3 text-sm bg-slate-800 border border-white/20 rounded-xl text-white"></div>
                        </div>
                        <div>
                            <label class="block text-xs font-bold mb-1 text-amber-300">🔐 Réinitialiser le mot de passe (optionnel)</label>
                            <input type="password" name="nouveau_mdp" placeholder="Laisser vide pour ne pas changer" class="w-full p-3 text-sm bg-slate-800 border border-amber-500/30 rounded-xl text-white placeholder-slate-500">
                        </div>
                        <button type="submit" class="w-full bg-gradient-to-r from-emerald-600 to-teal-600 hover:from-emerald-500 hover:to-teal-500 text-white py-3 rounded-xl text-sm font-bold shadow-lg transition">Enregistrer les modifications</button>
                    </form>
                </div>
            </div>
            """

        presences_table_rows = "".join([f"<tr class='border-b border-white/5 text-sm presence-row hover:bg-white/5 transition' data-nom='{str(p.get('adherents',{}).get('prenom','')).lower()} {str(p.get('adherents',{}).get('nom','')).lower()}' data-event='{str(p.get('evenement_titre','')).lower()}'><td class='p-3.5 font-bold text-white'>{p.get('adherents',{}).get('prenom','')} {p.get('adherents',{}).get('nom','')}</td><td class='p-3.5 text-slate-300'>{p.get('evenement_titre','')}</td><td class='p-3.5 text-slate-400'>{formater_date(p.get('date_reunion',''))}</td><td class='p-3.5'><span class='text-xs px-3 py-1 rounded-full font-bold bg-emerald-500/20 text-emerald-300 border border-emerald-500/30'>{p.get('statut_presence','')}</span></td></tr>" for p in all_presences])
        
        paiements_mobiles_admin = [c for c in all_cotisations if "passerelle_" in str(c.get('mode_paiement', '')) or "1-clic_" in str(c.get('mode_paiement', ''))]
        paiements_mobiles_rows = ""
        for pm in paiements_mobiles_admin:
            adh_pm = pm.get('adherents', {}) or {}
            st_paiement = pm.get('statut_paiement', 'en_attente')
            if is_tresorier:
                action_cell = f"""
                <form action="/admin/valider-paiement-mobile" method="POST" class="inline">
                    <input type="hidden" name="user_id" value="{user['id']}"><input type="hidden" name="paiement_id" value="{pm['id']}">
                    <button type="submit" class="bg-amber-500/20 hover:bg-amber-500/30 text-amber-300 border border-amber-500/30 px-3 py-1.5 rounded-xl text-xs font-bold shadow-sm transition">⏳ Valider</button>
                </form>
                """ if st_paiement != 'valide' else f"""
                <span class="text-xs font-bold text-emerald-300 bg-emerald-500/20 border border-emerald-500/30 px-3 py-1 rounded-full mr-2">Validé ✓</span>
                <a href="/cotisation/recu-pdf/{pm['id']}" target="_blank" class="bg-blue-600 hover:bg-blue-500 text-white px-3 py-1.5 rounded-xl text-xs font-bold shadow-sm transition">📄 PDF</a>
                """
            else:
                action_cell = "<span class='text-xs font-bold text-emerald-300 bg-emerald-500/20 px-3 py-1 rounded-full'>Validé ✓</span>" if st_paiement == 'valide' else "<span class='text-xs font-bold text-amber-300 bg-amber-500/20 px-3 py-1 rounded-full'>⏳ En attente</span>"

            paiements_mobiles_rows += f"""
            <tr class="hover:bg-white/5 border-b border-white/5 text-sm mobile-row transition" data-nom="{str(adh_pm.get('prenom','')).lower()} {str(adh_pm.get('nom','')).lower()}">
                <td class="p-3.5 font-bold text-white">{adh_pm.get('prenom','')} {adh_pm.get('nom','')}</td>
                <td class="p-3.5 font-semibold text-blue-300 text-xs uppercase">{pm.get('mode_paiement','')}</td>
                <td class="p-3.5 font-bold text-emerald-400">{formater_montant(pm.get('montant',0))} CFA</td>
                <td class="p-3.5 text-slate-300">{pm.get('periode','')}</td>
                <td class="p-3.5 text-right">{action_cell}</td>
            </tr>
            """

        aides_admin_html = ""
        for ai in all_aides:
            adh_aide = ai.get('adherents', {}) or {}
            st_aide = ai.get('statut_validation', 'en_attente')
            if is_tresorier:
                actions_aide = f"""
                <form action="/admin/valider-aide" method="POST" class="inline-block"><input type="hidden" name="user_id" value="{user['id']}"><input type="hidden" name="aide_id" value="{ai['id']}"><input type="hidden" name="statut_validation" value="approuve"><button type="submit" class="bg-emerald-600 hover:bg-emerald-500 text-white px-3 py-1.5 rounded-lg text-xs font-bold mr-1 shadow-sm transition">Approuver</button></form>
                <form action="/admin/valider-aide" method="POST" class="inline-block"><input type="hidden" name="user_id" value="{user['id']}"><input type="hidden" name="aide_id" value="{ai['id']}"><input type="hidden" name="statut_validation" value="refuse"><button type="submit" class="bg-red-600 hover:bg-red-500 text-white px-3 py-1.5 rounded-lg text-xs font-bold shadow-sm transition">Refuser</button></form>
                """ if st_aide == 'en_attente' else f"<span class='text-xs font-bold py-1 px-3 rounded-full bg-white/10 text-slate-300 uppercase'>{st_aide}</span>"
            else:
                actions_aide = f"<span class='text-xs font-bold py-1 px-3 rounded-full bg-white/10 text-slate-300 uppercase'>{st_aide}</span>"
            aides_admin_html += f"<li class='py-3 border-b border-white/5 flex justify-between items-center text-sm aide-item' data-motif='{str(ai.get('motif','')).lower()}'><div><b class='text-white'>{adh_aide.get('prenom','')} {adh_aide.get('nom','')}</b> — <span class='text-slate-300'>{ai.get('motif','')}</span> <span class='text-amber-400 font-bold'>({formater_montant(ai.get('montant_demande',0))} CFA)</span></div><div>{actions_aide}</div></li>"

        options_adherents_select = "".join([f"<option value='{a['id']}' class='bg-slate-900 adherent-option' data-text='{str(a.get('prenom','')).lower()} {str(a.get('nom','')).lower()} {str(a.get('secteur','')).lower()}'>{a.get('prenom','')} {a.get('nom','')} ({a.get('secteur','')})</option>" for a in all_actifs])
        options_evenements_select = "".join([f"<option value='{e.get('titre','')}' data-date='{e.get('date_reunion','')}' class='bg-slate-900'>{e.get('titre','')} ({formater_date(e.get('date_reunion',''))})</option>" for e in all_evenements])

        tresorerie_box_html = f"""
        <div class="space-y-6">
            <div class="bg-white/5 backdrop-blur-xl p-6 rounded-3xl shadow-xl border border-white/10">
                <h2 class="text-base font-extrabold mb-5 border-b border-white/10 pb-3 text-emerald-300 flex items-center gap-2">💼 Trésorerie & Solde Global</h2>
                """
        if is_tresorier:
            tresorerie_box_html += f"""
                <form action="/admin/maj-solde-initial" method="POST" class="bg-gradient-to-r from-emerald-950/60 to-teal-950/60 p-5 rounded-2xl border border-emerald-500/30 mb-6 flex gap-3 items-end shadow-inner backdrop-blur-md">
                    <input type="hidden" name="user_id" value="{user['id']}">
                    <div class="flex-1"><label class="block text-xs font-bold text-emerald-300 mb-1.5">Solde Initial Réel en Caisse</label><input type="number" name="solde_initial" value="{solde_initial}" required class="w-full p-3 text-sm bg-slate-900/80 border border-emerald-500/40 rounded-xl text-white shadow-sm focus:outline-none focus:ring-2 focus:ring-emerald-400"></div>
                    <button type="submit" class="bg-emerald-600 hover:bg-emerald-500 text-white font-bold py-3 px-6 rounded-xl text-sm shadow-lg shadow-emerald-600/30 transition">Mettre à jour</button>
                </form>

                <div class="bg-white/5 p-5 rounded-2xl border border-white/10 mb-6 backdrop-blur-md">
                    <h3 class="text-xs font-extrabold text-emerald-300 mb-3 uppercase tracking-wider">➕ Saisie Manuelle d'une Cotisation Membre</h3>
                    
                    <!-- Barre de recherche pour filtrer les membres du menu déroulant -->
                    <div class="mb-3">
                        <label class="block text-xs font-bold text-slate-300 mb-1">🔍 Rechercher un membre pour la cotisation</label>
                        <input type="text" id="search-select-membre" onkeyup="filterAdherentSelect()" placeholder="Tapez un nom, prénom ou secteur..." class="w-full p-3 text-sm bg-slate-900 border border-white/20 rounded-xl text-white placeholder-slate-400 focus:outline-none focus:ring-2 focus:ring-emerald-400 shadow-sm">
                    </div>

                    <form action="/admin/saisir-cotisation" method="POST" class="grid grid-cols-1 sm:grid-cols-4 gap-3">
                        <input type="hidden" name="user_id" value="{user['id']}">
                        <select name="adherent_id" id="select-adherent-cotisation" required class="p-3 text-sm border border-white/20 rounded-xl bg-slate-900 text-white font-semibold shadow-sm focus:outline-none focus:ring-2 focus:ring-emerald-400">
                            <option value="">-- Choisir un membre --</option>
                            {options_adherents_select}
                        </select>
                        <input type="text" name="periode" placeholder="Période (ex: 2026-09)" required class="p-3 text-sm border border-white/20 rounded-xl bg-slate-900 text-white shadow-sm focus:outline-none focus:ring-2 focus:ring-emerald-400">
                        <input type="number" name="montant" placeholder="Montant (CFA)" required class="p-3 text-sm border border-white/20 rounded-xl bg-slate-900 text-white shadow-sm focus:outline-none focus:ring-2 focus:ring-emerald-400">
                        <button type="submit" class="bg-emerald-600 hover:bg-emerald-500 text-white font-bold py-3 px-4 rounded-xl text-sm shadow-lg shadow-emerald-600/30 transition">Enregistrer</button>
                    </form>
                </div>
            """
        tresorerie_box_html += f"""
                <div class="text-center bg-gradient-to-r from-slate-900 via-emerald-950 to-teal-950 text-white py-5 px-6 rounded-2xl font-black text-xl mb-6 shadow-xl border border-emerald-500/30">Solde Réel en Caisse : <span class="text-emerald-400 font-mono">{formater_montant(solde)} CFA</span></div>
                
                <div class="flex justify-between items-center mb-3">
                    <h3 class="text-xs font-extrabold text-slate-300 uppercase tracking-wider">État des cotisations membres (À jour & Retards)</h3>
                    <input type="text" id="search-retards" onkeyup="filterRetards()" placeholder="Filtrer les retards..." class="px-3.5 py-1.5 text-xs border border-white/20 rounded-xl w-48 bg-slate-900/60 text-white placeholder-slate-400 focus:outline-none focus:ring-2 focus:ring-emerald-400">
                </div>
                <div class="overflow-x-auto max-h-72 overflow-y-auto border border-white/10 rounded-2xl bg-black/20">
                    <table class="w-full text-left">
                        <tbody>{suivi_retards_html}</tbody>
                    </table>
                </div>
            </div>
            
            <div class="bg-white/5 backdrop-blur-xl p-6 rounded-3xl shadow-xl border border-white/10">
                <div class="flex justify-between items-center mb-4 border-b border-white/10 pb-3">
                    <h2 class="text-base font-extrabold text-emerald-300">📱 Paiements Passerelle & Mobile</h2>
                    <input type="text" id="search-mobile" onkeyup="filterMobile()" placeholder="Rechercher..." class="px-3.5 py-1.5 text-xs border border-white/20 rounded-xl w-48 bg-slate-900/60 text-white placeholder-slate-400 focus:outline-none focus:ring-2 focus:ring-emerald-400">
                </div>
                <div class="overflow-x-auto max-h-60 overflow-y-auto border border-white/10 rounded-2xl bg-black/20">
                    <table class="w-full text-left"><thead class="bg-white/5 text-[11px] font-bold text-slate-300 uppercase tracking-wider"><tr><th class="p-3.5">Adhérent</th><th class="p-3.5">Détails</th><th class="p-3.5">Montant</th><th class="p-3.5">Période</th><th class="p-3.5 text-right">Action</th></tr></thead><tbody id="mobile-tbody">{paiements_mobiles_rows or '<tr><td colspan="5" class="p-4 text-center text-sm text-slate-400">Aucun paiement.</td></tr>'}</tbody></table>
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
                    badge_recu = f"<a href='/cotisation/recu-pdf/{c['id']}' target='_blank' class='bg-blue-600 hover:bg-blue-500 text-white px-3.5 py-1.5 rounded-xl text-xs font-bold shadow-md transition inline-flex items-center gap-1.5'>📄 Télécharger Reçu PDF</a>"
                else:
                    badge_recu = "<span class='bg-amber-500/20 text-amber-300 border border-amber-500/30 px-3.5 py-1.5 rounded-xl text-xs font-bold'>⏳ En attente de validation admin</span>"
                mois_payes_html += f"<li class='py-3.5 border-b border-white/5 text-sm flex justify-between items-center'><span class='text-slate-200'>Mois de <b class='text-emerald-300'>{c.get('periode','')}</b> : <span class='text-emerald-400 font-bold'>{formater_montant(c.get('montant',0))} CFA</span></span> {badge_recu}</li>"

            avatar_html = f"<img src='{user.get('photo_profil')}' class='w-16 h-16 rounded-2xl object-cover shadow-lg border-2 border-emerald-400/80'>" if user.get('photo_profil') else f"<div class='w-16 h-16 rounded-2xl bg-emerald-500/20 border border-emerald-500/40 flex items-center justify-center text-emerald-300 font-black text-xl shadow-lg'>{user.get('prenom','M')[0]}</div>"

            per_str = f"{annee_actuelle}-{mois_actuel:02d}"
            member_specific_html = f"""
            <div class="bg-gradient-to-r from-slate-900 via-emerald-950 to-teal-950 text-white p-6 rounded-3xl shadow-2xl flex justify-between items-center relative overflow-hidden border border-white/10 backdrop-blur-xl">
                <div>
                    <span class="bg-emerald-500/20 text-emerald-300 text-[10px] font-extrabold px-3 py-1 rounded-full uppercase tracking-widest border border-emerald-500/30">Mon Compte Membre</span>
                    <h2 class="text-xl font-black mt-2 text-white">{user.get('prenom','')} {user.get('nom','')}</h2>
                    <p class="text-xs text-slate-300 font-medium mt-1">Secteur : <span class='text-emerald-300 font-semibold'>{user.get('secteur','')}</span> | Tél : <span class='text-emerald-300 font-semibold'>{user.get('telephone','')}</span></p>
                </div>
                <div class="flex items-center gap-3">
                    {avatar_html}
                    <div class="bg-white/90 p-2 rounded-2xl shadow-xl border border-white/20"><img src="data:image/png;base64,{qr_perso_b64}" class="w-14 h-14 rounded-xl"></div>
                </div>
            </div>

            <!-- Module de Test de Passerelle de Paiement Sécurisée -->
            <div class="bg-white/5 backdrop-blur-xl p-6 rounded-3xl shadow-xl border border-white/10 space-y-4">
                <div class="border-b border-white/10 pb-3 flex justify-between items-center">
                    <h2 class="text-base font-extrabold text-emerald-300">💳 Passerelle de Paiement (Mode Test)</h2>
                    <span class="text-[11px] bg-indigo-500/20 text-indigo-300 px-3 py-1 rounded-full font-bold border border-indigo-500/30">Sandbox Gratuite</span>
                </div>
                
                <p class="text-xs text-slate-300 leading-relaxed">
                    Testez le tunnel de paiement sécurisé de la passerelle. Vous serez redirigé vers une page de simulation de paiement (Wave, Orange Money ou Carte).
                </p>

                <form action="/initier-paiement-passerelle" method="POST" class="space-y-4">
                    <input type="hidden" name="user_id" value="{user['id']}">
                    <div class="grid grid-cols-1 sm:grid-cols-2 gap-3">
                        <div>
                            <label class="block text-xs font-bold mb-1 text-slate-300">Mois concerné</label>
                            <input type="text" name="periode" value="{per_str}" required class="w-full p-3 border border-white/20 rounded-xl text-sm bg-slate-900/60 text-white text-center font-bold">
                        </div>
                        <div>
                            <label class="block text-xs font-bold mb-1 text-slate-300">Montant (CFA)</label>
                            <input type="number" name="montant" value="5000" required class="w-full p-3 border border-white/20 rounded-xl text-sm bg-slate-900/60 text-white text-center font-bold">
                        </div>
                    </div>
                    
                    <div class="grid grid-cols-1 sm:grid-cols-2 gap-3 pt-2">
                        <button type="submit" name="operateur" value="WaveSandbox" class="w-full bg-gradient-to-r from-cyan-600 to-blue-600 hover:from-cyan-500 hover:to-blue-500 text-white font-black py-3.5 px-4 rounded-2xl shadow-lg shadow-cyan-600/30 transition flex items-center justify-center gap-2 text-sm cursor-pointer">
                            💙 Payer via Passerelle Wave
                        </button>
                        <button type="submit" name="operateur" value="OrangeSandbox" class="w-full bg-gradient-to-r from-orange-600 to-amber-600 hover:from-orange-500 hover:to-amber-500 text-white font-black py-3.5 px-4 rounded-2xl shadow-lg shadow-orange-600/30 transition flex items-center justify-center gap-2 text-sm cursor-pointer">
                            🧡 Payer via Passerelle Orange
                        </button>
                    </div>
                </form>
            </div>

            <div class="bg-white/5 backdrop-blur-xl p-6 rounded-3xl shadow-xl border border-white/10">
                <h2 class="text-base font-extrabold mb-4 border-b border-white/10 pb-3 text-emerald-300">📋 Mes Cotisations & Reçus</h2>
                <ul class="max-h-60 overflow-y-auto pr-2">{mois_payes_html or '<p class="text-sm text-slate-400">Aucun versement enregistré pour le moment.</p>'}</ul>
            </div>
            """

        evenements_cards = "".join([f"<div class='bg-white/5 p-4 rounded-2xl border border-white/10 mb-3'><h4 class='font-bold text-sm text-emerald-300'>{e.get('titre','')}</h4><p class='text-xs text-slate-400'>Date : {formater_date(e.get('date_reunion',''))}</p><p class='text-xs text-slate-300 mt-1'>{e.get('description','')}</p></div>" for e in all_evenements])
        
        admin_event_pointage_html = ""
        if is_tresorier:
            admin_event_pointage_html = f"""
            <div class="grid grid-cols-1 md:grid-cols-2 gap-6 mb-6">
                <div class="bg-white/5 backdrop-blur-xl p-6 rounded-3xl shadow-xl border border-white/10">
                    <h2 class="text-base font-extrabold mb-4 border-b border-white/10 pb-3 text-emerald-300">📅 Planification d'Événement</h2>
                    <form action="/admin/creer-evenement" method="POST" class="space-y-3.5">
                        <input type="hidden" name="user_id" value="{user['id']}">
                        <div><label class="block text-xs font-bold mb-1 text-slate-300">Titre de l'événement</label><input type="text" name="titre" placeholder="ex: Assemblée Générale Mensuelle" required class="w-full p-3 text-sm bg-slate-900 border border-white/20 rounded-xl text-white"></div>
                        <div><label class="block text-xs font-bold mb-1 text-slate-300">Date</label><input type="date" name="date_reunion" required class="w-full p-3 text-sm bg-slate-900 border border-white/20 rounded-xl text-white"></div>
                        <div><label class="block text-xs font-bold mb-1 text-slate-300">Description</label><textarea name="description" rows="2" class="w-full p-3 text-sm bg-slate-900 border border-white/20 rounded-xl text-white" placeholder="Ordre du jour..."></textarea></div>
                        <button type="submit" class="w-full bg-gradient-to-r from-blue-600 to-indigo-600 hover:from-blue-500 hover:to-indigo-500 text-white py-3 rounded-xl text-sm font-bold shadow-lg transition">Créer l'événement</button>
                    </form>
                    <div class="mt-4 max-h-40 overflow-y-auto">{evenements_cards or '<p class="text-xs text-slate-400">Aucun événement planifié.</p>'}</div>
                </div>
                <div class="bg-white/5 backdrop-blur-xl p-6 rounded-3xl shadow-xl border border-white/10">
                    <h2 class="text-base font-extrabold mb-4 border-b border-white/10 pb-3 text-emerald-300">📌 Scanner / Pointage Présence</h2>
                    <div class="mb-4 bg-emerald-500/10 p-4 rounded-2xl border border-emerald-500/20 text-center backdrop-blur-md">
                        <input type="file" accept="image/*" capture="environment" id="scan-photo-input" onchange="handleScanPhoto(this)" class="hidden">
                        <button type="button" onclick="document.getElementById('scan-photo-input').click()" class="bg-emerald-600 hover:bg-emerald-500 text-white text-xs font-bold py-2.5 px-5 rounded-xl shadow-lg shadow-emerald-600/30 transition inline-flex items-center gap-2">📷 Scanner Photo / QrCode Présence</button>
                        <p id="scan-result-text" class="text-[11px] text-emerald-300 font-semibold mt-2">Cliquez pour scanner ou photographier la feuille de présence</p>
                    </div>
                    <form action="/admin/pointer-presence" method="POST" class="space-y-3.5">
                        <input type="hidden" name="user_id" value="{user['id']}">
                        <div>
                            <label class="block text-xs font-bold mb-1 text-slate-300">Sélectionner l'événement</label>
                            <select name="evenement_titre" id="select-event" onchange="updateEventDate(this)" required class="w-full p-3 text-sm bg-slate-900 border border-white/20 rounded-xl text-white font-semibold">
                                <option value="">-- Choisir un événement --</option>
                                {options_evenements_select}
                            </select>
                        </div>
                        <div>
                            <label class="block text-xs font-bold mb-1 text-slate-300">Date de la réunion</label>
                            <input type="date" name="date_reunion" id="input-event-date" required class="w-full p-3 text-sm bg-slate-900 border border-white/20 rounded-xl text-white">
                        </div>
                        <div>
                            <label class="block text-xs font-bold mb-1 text-slate-300">Membre présent</label>
                            <select name="adherent_id" required class="w-full p-3 text-sm bg-slate-900 border border-white/20 rounded-xl text-white font-semibold">
                                <option value="">-- Choisir un membre --</option>
                                {options_adherents_select}
                            </select>
                        </div>
                        <div>
                            <label class="block text-xs font-bold mb-1 text-slate-300">Statut</label>
                            <select name="statut_presence" required class="w-full p-3 text-sm bg-slate-900 border border-white/20 rounded-xl text-white font-semibold">
                                <option value="Present">Présent(e)</option>
                                <option value="Retard">Retard</option>
                                <option value="Absent">Absent(e)</option>
                                <option value="Excuse">Excusé(e)</option>
                            </select>
                        </div>
                        <button type="submit" class="w-full bg-gradient-to-r from-emerald-600 to-teal-600 hover:from-emerald-500 hover:to-teal-500 text-white py-3 rounded-xl text-sm font-bold shadow-lg transition">Valider le pointage</button>
                    </form>
                </div>
            </div>
            """

        admin_projet_form = ""
        if is_tresorier:
            admin_projet_form = f"""
            <div class="bg-white/5 backdrop-blur-xl p-6 rounded-3xl shadow-xl border border-white/10 mb-6">
                <h2 class="text-base font-extrabold mb-4 border-b border-white/10 pb-3 text-emerald-300">➕ Proposer / Ajouter un Projet</h2>
                <form action="/projets-form" method="POST" class="space-y-3.5">
                    <input type="hidden" name="user_id" value="{user['id']}">
                    <div class="grid grid-cols-1 sm:grid-cols-2 gap-3">
                        <div><label class="block text-xs font-bold mb-1 text-slate-300">Titre du projet</label><input type="text" name="titre" required class="w-full p-3 text-sm bg-slate-900 border border-white/20 rounded-xl text-white"></div>
                        <div><label class="block text-xs font-bold mb-1 text-slate-300">Coût estimé (CFA)</label><input type="number" name="cout" required class="w-full p-3 text-sm bg-slate-900 border border-white/20 rounded-xl text-white"></div>
                    </div>
                    <div><label class="block text-xs font-bold mb-1 text-slate-300">Description</label><textarea name="description" rows="2" required class="w-full p-3 text-sm bg-slate-900 border border-white/20 rounded-xl text-white"></textarea></div>
                    <div class="grid grid-cols-1 sm:grid-cols-3 gap-3">
                        <div><label class="block text-xs font-bold mb-1 text-slate-300">Objectifs</label><input type="text" name="objectifs" class="w-full p-3 text-sm bg-slate-900 border border-white/20 rounded-xl text-white"></div>
                        <div><label class="block text-xs font-bold mb-1 text-slate-300">Planning / Chronologie</label><input type="text" name="chronologie" class="w-full p-3 text-sm bg-slate-900 border border-white/20 rounded-xl text-white"></div>
                        <div>
                            <label class="block text-xs font-bold mb-1 text-slate-300">Statut</label>
                            <select name="statut" class="w-full p-3 text-sm bg-slate-900 border border-white/20 rounded-xl text-white font-semibold">
                                <option value="En cours">En cours</option>
                                <option value="Planifié">Planifié</option>
                                <option value="Terminé">Terminé</option>
                            </select>
                        </div>
                    </div>
                    <button type="submit" class="w-full bg-gradient-to-r from-indigo-600 to-purple-600 hover:from-indigo-500 hover:to-purple-500 text-white py-3 rounded-xl text-sm font-bold shadow-lg transition">Publier le projet</button>
                </form>
            </div>
            """

        navigation_onglets_html = ""
        if is_tresorier:
            navigation_onglets_html = f"""
            <div class="sticky top-0 z-40 bg-slate-900/80 backdrop-blur-xl py-3 px-4 rounded-2xl shadow-2xl border border-white/10 flex flex-wrap gap-2">
                <button onclick="switchTab('tab-tresorerie')" id="btn-tab-tresorerie" class="tab-btn px-4 py-2.5 text-xs font-extrabold rounded-xl bg-gradient-to-r from-emerald-600 to-teal-600 text-white shadow-lg transition">💼 Trésorerie</button>
                <button onclick="switchTab('tab-adherents')" id="btn-tab-adherents" class="tab-btn px-4 py-2.5 text-xs font-extrabold rounded-xl bg-white/5 text-slate-300 border border-white/10 hover:bg-white/10 transition">👥 Annuaire</button>
                <button onclick="switchTab('tab-pointage')" id="btn-tab-pointage" class="tab-btn px-4 py-2.5 text-xs font-extrabold rounded-xl bg-white/5 text-slate-300 border border-white/10 hover:bg-white/10 transition">📋 Pointage</button>
                <button onclick="switchTab('tab-projets')" id="btn-tab-projets" class="tab-btn px-4 py-2.5 text-xs font-extrabold rounded-xl bg-white/5 text-slate-300 border border-white/10 hover:bg-white/10 transition">🚀 Projets</button>
            </div>

            <div id="tab-tresorerie" class="tab-content space-y-6">
                {tresorerie_box_html}
            </div>

            <div id="tab-adherents" class="tab-content hidden space-y-6">
                <div class="bg-white/5 backdrop-blur-xl p-6 rounded-3xl shadow-xl border border-white/10">
                    <div class="flex flex-col sm:flex-row justify-between items-center mb-5 border-b border-white/10 pb-3 gap-3">
                        <h2 class="text-base font-extrabold text-emerald-300">👥 Annuaire ({len(all_adherents)})</h2>
                        <div class="flex gap-2 w-full sm:w-auto">
                            <input type="text" id="search-annuaire" onkeyup="filterAnnuaire()" placeholder="Rechercher par nom, secteur, téléphone..." class="px-3.5 py-2 text-xs border border-white/20 rounded-xl w-full sm:w-64 bg-slate-900 text-white placeholder-slate-400">
                            <a href="/adherents/export-pdf" target="_blank" class="bg-red-600 hover:bg-red-500 text-white px-4 py-2 rounded-xl text-xs font-bold shadow-lg transition whitespace-nowrap">📄 PDF</a>
                        </div>
                    </div>
                    <div class="overflow-x-auto max-h-96 overflow-y-auto border border-white/10 rounded-2xl bg-black/20">
                        <table class="w-full text-left">
                            <thead class="bg-white/5 text-[11px] font-bold text-slate-300 uppercase tracking-wider">
                                <tr><th class="p-3.5">Nom & Prénom</th><th class="p-3.5">Rôle</th><th class="p-3.5">Secteur</th><th class="p-3.5">Téléphone</th><th class="p-3.5 text-right">Actions</th></tr>
                            </thead>
                            <tbody>{adherents_table_rows}</tbody>
                        </table>
                    </div>
                </div>
            </div>

            <div id="tab-pointage" class="tab-content hidden space-y-6">
                {admin_event_pointage_html}
                <div class="bg-white/5 backdrop-blur-xl p-6 rounded-3xl shadow-xl border border-white/10">
                    <div class="flex justify-between items-center mb-4 border-b border-white/10 pb-3">
                        <h2 class="text-base font-extrabold text-emerald-300">📋 Historique des Pointages</h2>
                        <input type="text" id="search-pointage" onkeyup="filterPointage()" placeholder="Filtrer par nom, événement..." class="px-3.5 py-2 text-xs border border-white/20 rounded-xl w-56 bg-slate-900 text-white placeholder-slate-400">
                    </div>
                    <div class="overflow-x-auto max-h-96 overflow-y-auto border border-white/10 rounded-2xl bg-black/20">
                        <table class="w-full text-left"><thead class="bg-white/5 text-[11px] font-bold text-slate-300 uppercase tracking-wider"><tr><th class="p-3.5">Membre</th><th class="p-3.5">Événement</th><th class="p-3.5">Date</th><th class="p-3.5">Statut</th></tr></thead><tbody id="presence-tbody">{presences_table_rows or '<tr><td colspan="4" class="p-4 text-center text-sm text-slate-400">Aucun pointage enregistré.</td></tr>'}</tbody></table>
                    </div>
                </div>
            </div>

            <div id="tab-projets" class="tab-content hidden space-y-6">
                {admin_projet_form}
                <div class="bg-white/5 backdrop-blur-xl p-6 rounded-3xl shadow-xl border border-white/10">
                    <div class="flex justify-between items-center mb-4 border-b border-white/10 pb-3">
                        <h2 class="text-base font-extrabold text-emerald-300">🤝 Demandes d'Aide</h2>
                        <input type="text" id="search-projets" onkeyup="filterProjets()" placeholder="Filtrer demandes..." class="px-3.5 py-2 text-xs border border-white/20 rounded-xl w-48 bg-slate-900 text-white placeholder-slate-400">
                    </div>
                    <ul class="max-h-60 overflow-y-auto pr-2" id="aides-ul">{aides_admin_html or '<p class="text-sm text-slate-400">Aucune demande.</p>'}</ul>
                </div>
                <div class="bg-white/5 backdrop-blur-xl p-6 rounded-3xl shadow-xl border border-white/10">
                    <h2 class="text-base font-extrabold mb-4 border-b border-white/10 pb-3 text-emerald-300">🚀 Projets de l'Association</h2>
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
                        b.classList.remove('bg-gradient-to-r', 'from-emerald-600', 'to-teal-600', 'text-white', 'shadow-lg');
                        b.classList.add('bg-white/5', 'text-slate-300', 'border', 'border-white/10');
                    }}
                    let activeBtn = document.getElementById('btn-' + tabId);
                    if (activeBtn) {{
                        activeBtn.classList.remove('bg-white/5', 'text-slate-300', 'border', 'border-white/10');
                        activeBtn.classList.add('bg-gradient-to-r', 'from-emerald-600', 'to-teal-600', 'text-white', 'shadow-lg');
                    }}
                }}
                function openModal(id) {{ let m = document.getElementById('modal-' + id); if(m) m.classList.remove('hidden'); }}
                function closeModal(id) {{ let m = document.getElementById('modal-' + id); if(m) m.classList.add('hidden'); }}
                
                function filterAdherentSelect() {{
                    let input = document.getElementById('search-select-membre');
                    if (!input) return;
                    let val = input.value.toLowerCase();
                    let select = document.getElementById('select-adherent-cotisation');
                    if (!select) return;
                    let options = select.getElementsByClassName('adherent-option');
                    for (let opt of options) {{
                        let text = opt.getAttribute('data-text');
                        opt.style.display = text.includes(val) ? "" : "none";
                    }}
                }}

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
                    let txt = document.getElementById('scan-result-text');
                    if (txt) {{
                        txt.innerText = "Photo scannée avec succès ! Prêt pour le pointage.";
                        txt.classList.remove('text-emerald-300');
                        txt.classList.add('text-emerald-400', 'font-black');
                    }}
                }}
            </script>
        </head>
        <body class="bg-gradient-to-tr from-slate-950 via-emerald-950 to-teal-950 text-slate-100 font-sans min-h-screen py-8 px-4">
            <div class="max-w-4xl mx-auto space-y-6">
                <div class="bg-white/5 backdrop-blur-xl p-5 rounded-3xl shadow-2xl border border-white/10 flex justify-between items-center">
                    <div class="flex items-center gap-3.5">
                        <div class="w-12 h-12 rounded-2xl bg-gradient-to-br from-emerald-500 to-teal-600 flex items-center justify-center text-white font-black text-lg shadow-lg">{user.get('prenom','M')[0]}</div>
                        <div>
                            <h2 class="text-base font-extrabold text-white">{user.get('prenom','')} {user.get('nom','')}</h2>
                            <p class="text-xs text-emerald-400 uppercase font-bold tracking-widest">{user.get('role','')}</p>
                        </div>
                    </div>
                    <a href="/" class="bg-red-600 hover:bg-red-500 text-white px-4 py-2 rounded-xl text-xs font-bold shadow-lg transition">Déconnexion</a>
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
