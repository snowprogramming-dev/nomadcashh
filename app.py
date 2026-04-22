"""
app.py
------
Punto di ingresso principale dell'applicazione Flask di NomadCash.

Questo file definisce:
    - La configurazione dell'app Flask (secret_key per le sessioni)
    - Tutte le route HTTP (URL → funzione Python)
    - La logica di presentazione (calcoli per il template della dashboard)

Architettura delle route:
    /                           → login / registrazione
    /logout                     → disconnessione
    /dashboard                  → dashboard principale (trip attivo o no)
    /dashboard/create_trip      → crea un nuovo viaggio (POST)
    /dashboard/join_trip        → entra in un viaggio con codice invito (POST)
    /spese/add                  → aggiunge una spesa al viaggio (POST)
    /spese/delete/<id>          → elimina una spesa (POST)
    /spese/settle               → salda tutti i conti senza divisione (POST, solo admin)
    /spese/divisione_equa       → applica la divisione equa con commissione (POST, solo admin)
    /admin/promote/<email>      → promuove un utente ad admin (POST, solo admin)
    /admin/demote/<email>       → degrada un admin a partecipante (POST, solo admin)
    /admin/remove/<email>       → rimuove un partecipante (POST, solo admin)
    /admin/add_participant      → aggiunge forzatamente un utente al viaggio (POST, solo admin)

Sessione Flask:
    session["user"] contiene il dizionario dell'utente loggato
    (come restituito da Utente.find_by_email()).
    Chiavi principali: "email", "nome", "avatar", "admin" (bool).

Dipendenze:
    - modelli.py       → classi Viaggio, Utente, Spesa
    - moduli/partecipanti.py → funzioni CRUD per la tabella partecipanti
    - database.py      → engine SQLAlchemy
"""

from flask import Flask, render_template, request, redirect, url_for, session, flash
from datetime import datetime, date
from collections import defaultdict
import uuid

import database
from modelli import Utente, Viaggio, Spesa
from moduli.partecipanti import list_partecipanti, add_partecipante, remove_partecipante, count_admins

from sqlalchemy import text

# Istanza principale dell'applicazione Flask
app = Flask(__name__)

# Secret key usata per firmare i cookie di sessione.
# IMPORTANTE: in produzione cambiare con una stringa casuale lunga e tenerla in una variabile d'ambiente.
app.secret_key = "nomadcash-secret-key-change-me"


# =============================================================================
# FUNZIONI DI SUPPORTO
# =============================================================================

def get_spese_viaggio(id_viaggio):
    """
    Restituisce tutte le spese di un viaggio, ordinate per data e ID.

    Esegue una JOIN con la tabella utenti per recuperare anche il campo `nome`
    del pagatore (usato nel template per mostrare "Mario" invece di "mario@email.it").

    Args:
        id_viaggio (int): ID del viaggio di cui caricare le spese.

    Returns:
        list[dict]: Lista di dizionari, una entry per ogni spesa.
                    Campi: id_spesa, email_utente, testo_messaggio, importo,
                           categoria, data_spesa, pagata, nome (del pagatore).
    """
    query = text("""
        SELECT s.id_spesa, s.email_utente, s.testo_messaggio,
               s.importo, s.categoria, s.data_spesa, s.pagata,
               u.nome
        FROM spese s
        JOIN utenti u ON s.email_utente = u.email
        WHERE s.id_viaggio = :iv and u.email = s.email_utente
        ORDER BY s.data_spesa ASC, s.id_spesa ASC
    """)
    with database.engine.connect() as conn:
        res = conn.execute(query, {"iv": id_viaggio}).mappings().fetchall()
        return [dict(r) for r in res]


# =============================================================================
# CONTEXT PROCESSOR — dati disponibili in tutti i template
# =============================================================================

@app.context_processor
def inject_user():
    """
    Inietta automaticamente `current_user` in ogni template Jinja2.

    Grazie a questo, qualsiasi template può scrivere:
        {% if current_user %}  o  {{ current_user.nome }}
    senza dover passare esplicitamente l'utente da ogni singola route.

    Returns:
        dict: {"current_user": <dict utente dalla sessione, o None>}
    """
    return dict(current_user=session.get('user'))


# =============================================================================
# ROUTE: AUTENTICAZIONE
# =============================================================================

@app.route("/", methods=["GET", "POST"])
def index():
    """
    Homepage — gestisce sia il login che la registrazione.

    GET  → mostra il form di login/registrazione (auth.html)
    POST → distingue l'azione tramite il campo nascosto `action`:
           - "login"    → cerca l'utente per email, lo mette in session
           - "register" → crea un nuovo utente (Utente.create())

    Dopo un login riuscito, reindirizza subito alla dashboard.
    Se l'utente è già loggato (session["user"] esiste), salta il form.
    """
    # Se c'è già un utente in sessione, vai direttamente alla dashboard
    if "user" in session:
        return redirect(url_for("dashboard"))

    if request.method == "POST":
        action = request.form.get("action")  # "login" o "register" (campo hidden nel form)

        if action == "login":
            email = request.form.get("email")
            # Cerca l'utente nel DB; se esiste, lo salva in sessione (login senza password)
            utente_db = Utente(email=email).find_by_email()
            if utente_db:
                session["user"] = utente_db
                return redirect(url_for("dashboard"))
            else:
                flash("Utente non trovato.", "danger")

        elif action == "register":
            email = request.form.get("email")
            nome = request.form.get("nome")
            # URL avatar di default generato da DiceBear (basato sulle iniziali)
            avatar = request.form.get("avatar", "https://api.dicebear.com/7.x/initials/svg?seed=User")
            if email and nome:
                nuovo_utente = Utente(email=email, nome=nome, avatar=avatar)
                if nuovo_utente.create():
                    flash("Account creato! Ora fai il login.", "success")
                else:
                    # create() restituisce False se l'email è già registrata
                    flash("Email già registrata o errore database.", "danger")
            else:
                flash("Inserisci email e nome.", "warning")

    return render_template("auth.html")


@app.route("/logout")
def logout():
    """
    Disconnette l'utente rimuovendo i dati dalla sessione Flask.
    Reindirizza alla homepage (form di login).
    """
    session.pop("user", None)  # pop con default None evita errore se la chiave non esiste
    return redirect(url_for("index"))


# =============================================================================
# ROUTE: DASHBOARD PRINCIPALE
# =============================================================================

@app.route("/dashboard")
def dashboard():
    """
    Dashboard principale dell'app. Comportamento:

    1. Ricarica i dati aggiornati dell'utente dal DB (aggiorna flag admin in sessione).
    2. Cerca il viaggio attivo dell'utente:
       - Se non trovato → mostra dashboard_no_trip.html (crea/unisciti)
       - Se trovato     → carica spese, partecipanti e calcola i bilanci

    Calcolo bilancio (visibile nel riquadro "Riepilogo"):
        - Considera solo le spese con pagata=0 (non ancora saldate)
        - Raggruppa per utente: chi ha pagato quanto
        - Calcola la quota media (totale / numero di pagatori)
        - bilancio = quanto_pagato - quota → positivo = in debito, negativo = in credito

    Variabili passate al template dashboard_trip.html:
        viaggio       → dict con i dati del viaggio attivo
        is_admin      → bool, True se l'utente ha poteri admin
        spese         → list[dict] con tutte le spese del viaggio
        partecipanti  → list[dict] con i membri del viaggio
        totale        → float, somma delle spese non saldate
        quota         → float, quota pro capite (tra i pagatori)
        situazioni    → list[dict] con email e bilancio di ogni pagatore
        users_options → list[dict] per il <select> "Acquistato da"
        datetime      → oggetto datetime passato per usare datetime.now() nel template
    """
    if "user" not in session:
        return redirect(url_for("index"))

    # Ricarica l'utente dal DB per aggiornare il flag admin in sessione
    # (potrebbe essere stato promosso/degradato da un altro admin nel frattempo)
    utente_db = Utente(email=session["user"]["email"]).find_by_email()
    session["user"] = utente_db
    user_email = session["user"]["email"]

    # Cerca il viaggio attivo a cui partecipa l'utente
    viaggio_attivo = Viaggio().find_viaggio_attivo_utente(user_email)
    if not viaggio_attivo:
        # Nessun viaggio: mostra la schermata "crea o unisciti"
        return render_template("dashboard_no_trip.html")

    id_viaggio = viaggio_attivo["id_viaggio"]
    is_admin = session["user"].get("admin", False)

    # Carica tutte le spese e i partecipanti del viaggio
    spese = get_spese_viaggio(id_viaggio)
    partecipanti = list_partecipanti(id_viaggio)

    # ── Calcolo divisione equa (solo per il riepilogo visivo — non salda nulla) ──
    # Considera solo le spese non ancora saldate
    spese_aperte = [s for s in spese if not s["pagata"]]
    totale = sum(float(s["importo"]) for s in spese_aperte)

    # Raggruppa per utente: quanto ha speso ognuno tra le spese aperte
    pagato_per_utente = defaultdict(float)
    for s in spese_aperte:
        pagato_per_utente[s["email_utente"]] += float(s["importo"])

    # Quota media: divisa tra chi ha ALMENO una spesa aperta (non tutti i partecipanti)
    n_pagatori = len(pagato_per_utente)
    quota = totale / n_pagatori if n_pagatori > 0 else 0.0

    # Costruisce la lista delle situazioni individuali per il template
    situazioni = []
    for em, pagato in pagato_per_utente.items():
        bilancio = round(pagato - quota, 2)
        situazioni.append({"email": em, "bilancio": bilancio})

    # ── Lista utenti per il <select> "Acquistato da" nel form spese ──
    # Di default usa i partecipanti del viaggio.
    # Fallback: se la lista è vuota, carica tutti gli utenti registrati nel sistema.
    users_options = [u for u in partecipanti]
    if not users_options:
        with database.engine.connect() as conn:
            users_res = conn.execute(
                text("SELECT email, nome FROM utenti ORDER BY nome")
            ).mappings().fetchall()
            users_options = [dict(u) for u in users_res]

    return render_template(
        "dashboard_trip.html",
        viaggio=viaggio_attivo,
        is_admin=is_admin,
        spese=spese,
        partecipanti=partecipanti,
        totale=totale,
        quota=quota,
        situazioni=situazioni,
        users_options=users_options,
        datetime=datetime  # Passato per poter usare datetime.now().date() nel template
    )


# =============================================================================
# ROUTE: GESTIONE VIAGGIO (crea / unisciti)
# =============================================================================

@app.route("/dashboard/join_trip", methods=["POST"])
def join_trip():
    """
    Permette a un utente loggato di unirsi a un viaggio tramite codice invito.

    Flusso:
    1. Legge il codice dal form (campo uid_invito)
    2. Lo converte in maiuscolo e cerca il viaggio corrispondente nel DB
    3. Se trovato, aggiunge l'utente come partecipante (ruolo: 'partecipante')
    4. Flash di successo o errore e redirect alla dashboard
    """
    if "user" not in session:
        return redirect(url_for("index"))

    uid_input = request.form.get("uid_invito")
    if not uid_input:
        flash("Inserisci un codice invito valido.", "danger")
        return redirect(url_for("dashboard"))

    # Cerca il viaggio — il codice è sempre salvato in maiuscolo nel DB
    viaggio_trovato = Viaggio().find_by_uid(uid_input.strip().upper())
    if viaggio_trovato:
        try:
            add_partecipante(viaggio_trovato["id_viaggio"], session["user"]["email"])
            flash(f"Ti sei unito a {viaggio_trovato['nome_viaggio']}!", "success")
        except Exception as e:
            flash(f"Errore durante l'aggiunta ai partecipanti: {e}", "danger")
    else:
        flash("Codice invito non valido o viaggio inesistente.", "danger")

    return redirect(url_for("dashboard"))


@app.route("/dashboard/create_trip", methods=["POST"])
def create_trip():
    """
    Crea un nuovo viaggio e rende l'utente corrente il suo Admin.

    Flusso:
    1. Legge i dati dal form (nome, date, descrizione)
    2. Valida che data_fine > data_partenza
    3. Crea il record del viaggio nel DB (genera il codice invito automaticamente)
    4. Promuove l'utente ad admin (Utente.diventa_admin())
    5. Aggiunge l'utente come partecipante con ruolo='admin'
    6. Mostra il codice invito nel flash message così può condividerlo

    Raises (gestite internamente):
        Exception: Se le date non sono valide o ci sono errori DB.
    """
    if "user" not in session:
        return redirect(url_for("index"))

    nome = request.form.get("nome_viaggio")
    data_p_str = request.form.get("data_partenza")
    data_f_str = request.form.get("data_fine")
    descrizione = request.form.get("descrizione_itinerario")

    if not nome or not data_p_str or not data_f_str:
        flash("Compila tutti i campi obbligatori.", "danger")
        return redirect(url_for("dashboard"))

    try:
        # Converte le stringhe dalle date HTML (formato YYYY-MM-DD) in oggetti date Python
        data_p = datetime.strptime(data_p_str, "%Y-%m-%d").date()
        data_f = datetime.strptime(data_f_str, "%Y-%m-%d").date()

        if data_f <= data_p:
            flash("La data di fine deve essere successiva alla data di partenza.", "danger")
            return redirect(url_for("dashboard"))

        # Crea il viaggio nel DB (genera automaticamente uid_invito)
        nuovo_viaggio = Viaggio(nome=nome, data_p=data_p, data_f=data_f, descrizione=descrizione)
        nuovo_viaggio.create()

        # Promuove l'utente ad admin globale e lo aggiunge come partecipante admin del viaggio
        utente = Utente(email=session["user"]["email"])
        utente.diventa_admin()
        add_partecipante(nuovo_viaggio.id_viaggio, session["user"]["email"], ruolo="admin")

        flash(
            f"Viaggio {nome} creato! Sei l'Admin del viaggio. "
            f"Codice Invito: {nuovo_viaggio.uid_invito}",
            "success"
        )
    except Exception as e:
        flash(f"Errore nella creazione: {str(e)}", "danger")

    return redirect(url_for("dashboard"))


# =============================================================================
# ROUTE: GESTIONE SPESE
# =============================================================================

@app.route("/spese/add", methods=["POST"])
def add_expense():
    """
    Aggiunge una nuova spesa al viaggio attivo dell'utente loggato.

    Il campo `payer` nel form permette all'utente di registrare la spesa
    a nome di un altro partecipante (es. "Mario ha pagato la benzina").
    Campi obbligatori: testo (descrizione) e importo.
    """
    if "user" not in session:
        return redirect(url_for("index"))

    # Recupera il viaggio attivo a cui associare la spesa
    viaggio_attivo = Viaggio().find_viaggio_attivo_utente(session["user"]["email"])
    if not viaggio_attivo:
        return redirect(url_for("dashboard"))

    # Legge i dati dal form HTML
    payer = request.form.get("payer")          # Email di chi ha pagato fisicamente
    testo = request.form.get("testo")          # Descrizione (es. "Cena al ristorante")
    importo = request.form.get("importo")
    categoria = request.form.get("categoria")  # Es. "Cibo", "Benzina"
    data = request.form.get("data")

    if not testo or not importo:
        flash("Inserisci descrizione e importo.", "warning")
        return redirect(url_for("dashboard"))

    try:
        s = Spesa(
            id_viaggio=viaggio_attivo["id_viaggio"],
            email_utente=payer,
            testo_messaggio=testo,
            importo=float(importo),
            categoria=categoria,
            data_spesa=datetime.strptime(data, "%Y-%m-%d").date()
        )
        s.create()
        flash("Spesa aggiunta con successo.", "success")
    except Exception as e:
        flash(f"Errore aggiunta spesa: {e}", "danger")

    return redirect(url_for("dashboard"))


@app.route("/spese/delete/<int:id_spesa>", methods=["POST"])
def delete_expense(id_spesa):
    """
    Elimina una singola spesa dal database.

    Solo chi ha creato la spesa può eliminarla (controllo nel template HTML —
    il bottone 🗑️ appare solo se spesa.email_utente == current_user.email).
    Il modello Spesa.delete() blocca ulteriormente l'eliminazione se la
    spesa è già stata saldata (pagata=1).

    Args:
        id_spesa (int): ID della spesa da eliminare (estratto dall'URL).
    """
    if "user" not in session:
        return redirect(url_for("index"))

    s = Spesa(id_spesa=id_spesa)
    try:
        s.delete()
        flash("Spesa eliminata.", "success")
    except Exception as e:
        flash(str(e), "danger")

    return redirect(url_for("dashboard"))


@app.route("/spese/settle", methods=["POST"])
def settle_expenses():
    """
    Salda TUTTI i conti del viaggio senza applicare la divisione equa.

    Comportamento: marca tutte le spese con pagata=0 come pagata=1,
    registrando la data odierna. Non calcola chi deve cosa a chi —
    chiude semplicemente la contabilità.

    Accessibile solo dall'admin del viaggio.
    Mostra un flash con il numero di spese chiuse.
    """
    if "user" not in session:
        return redirect(url_for("index"))

    is_admin = session["user"].get("admin", False)
    if not is_admin:
        flash("Azione non autorizzata.", "danger")
        return redirect(url_for("dashboard"))

    viaggio_attivo = Viaggio().find_viaggio_attivo_utente(session["user"]["email"])
    if not viaggio_attivo:
        return redirect(url_for("dashboard"))

    # Crea l'oggetto Spesa con solo i campi necessari a settle_all()
    spesa_obj = Spesa(
        id_viaggio=viaggio_attivo["id_viaggio"],
        email_utente=session["user"]["email"]
    )
    try:
        count = spesa_obj.settle_all()
        if count == 0:
            flash("Nessuna spesa da saldare.", "warning")
        else:
            flash(f"Tutti i conti sono stati saldati ({count} spese).", "success")
    except Exception as ex:
        flash(str(ex), "danger")

    return redirect(url_for("dashboard"))


@app.route("/spese/divisione_equa", methods=["POST"])
def divisione_equa():
    """
    Esegue la divisione equa delle spese con eventuale commissione di gestione.

    Comportamento completo (vedere Spesa.divisione_equa() per i dettagli):
    1. Calcola il totale non saldato
    2. Se > €300 → aggiunge €0.50 per ogni partecipante (commissione gestione)
    3. Ricalcola e salda tutto

    Accessibile solo dall'admin del viaggio.
    Il flash message avvisa l'admin se la commissione è stata applicata.
    """
    if "user" not in session:
        return redirect(url_for("index"))

    is_admin = session["user"].get("admin", False)
    if not is_admin:
        flash("Azione non autorizzata.", "danger")
        return redirect(url_for("dashboard"))

    viaggio_attivo = Viaggio().find_viaggio_attivo_utente(session["user"]["email"])
    if not viaggio_attivo:
        return redirect(url_for("dashboard"))

    # email_utente sarà usata da divisione_equa() per il reset admin a fine viaggio
    spesa_obj = Spesa(
        id_viaggio=viaggio_attivo["id_viaggio"],
        email_utente=session["user"]["email"]
    )
    try:
        risultato = spesa_obj.divisione_equa()
        if not risultato:
            flash("Nessuna spesa da dividere.", "warning")
        else:
            # Notifica speciale se la commissione di €0.50/persona è scattata
            if risultato.get("commissione_applicata"):
                flash(
                    "✅ Divisione equa applicata. Commissione di gestione di €0.50 "
                    "aggiunta per ogni partecipante (totale superiore a €300).",
                    "success"
                )
            else:
                flash("✅ Divisione equa applicata con successo.", "success")
    except Exception as ex:
        flash(str(ex), "danger")

    return redirect(url_for("dashboard"))


# =============================================================================
# ROUTE: PANNELLO ADMIN — gestione partecipanti
# =============================================================================

@app.route("/admin/promote/<email>", methods=["POST"])
def promote_user(email):
    """
    Promuove un partecipante al ruolo di admin del viaggio.

    Aggiorna sia la tabella `partecipanti` (ruolo → 'admin')
    che la tabella `utenti` (flag admin → 1), in modo che il
    partecipante abbia i permessi completi alla prossima visita.

    Accessibile solo all'admin corrente del viaggio.

    Args:
        email (str): Email del partecipante da promuovere (nell'URL).
    """
    if "user" not in session or not session["user"].get("admin", False):
        return redirect(url_for("index"))

    viaggio_attivo = Viaggio().find_viaggio_attivo_utente(session["user"]["email"])
    try:
        # Aggiorna il ruolo nella tabella partecipanti
        add_partecipante(viaggio_attivo["id_viaggio"], email, ruolo='admin')
        # Aggiorna il flag globale nella tabella utenti
        ut = Utente(email=email)
        ut.diventa_admin()
        flash(f"{email} promosso a admin.", "success")
    except Exception as ex:
        flash(str(ex), "danger")

    return redirect(url_for("dashboard"))


@app.route("/admin/demote/<email>", methods=["POST"])
def demote_user(email):
    """
    Degrada un admin al ruolo di semplice partecipante.

    Blocca l'operazione se è l'unico admin del viaggio (count_admins <= 1),
    per evitare di lasciare il viaggio senza nessuno che possa gestirlo.

    Accessibile solo all'admin corrente.

    Args:
        email (str): Email dell'admin da degradare (nell'URL).
    """
    if "user" not in session or not session["user"].get("admin", False):
        return redirect(url_for("index"))

    viaggio_attivo = Viaggio().find_viaggio_attivo_utente(session["user"]["email"])
    try:
        # Sicurezza: non permettere di rimuovere l'ultimo admin
        if count_admins(viaggio_attivo["id_viaggio"]) <= 1:
            flash("Impossibile degradare: è l'unico admin.", "danger")
        else:
            add_partecipante(viaggio_attivo["id_viaggio"], email, ruolo='partecipante')
            ut = Utente(email=email)
            ut.diventa_non_admin()
            flash(f"{email} degradato.", "success")
    except Exception as ex:
        flash(str(ex), "danger")

    return redirect(url_for("dashboard"))


@app.route("/admin/remove/<email>", methods=["POST"])
def remove_user(email):
    """
    Rimuove un partecipante dal viaggio corrente.

    Elimina solo il record dalla tabella `partecipanti` — l'utente rimane
    registrato nel sistema e le sue spese restano nella tabella `spese`.

    Accessibile solo all'admin corrente.

    Args:
        email (str): Email del partecipante da rimuovere (nell'URL).
    """
    if "user" not in session or not session["user"].get("admin", False):
        return redirect(url_for("index"))

    viaggio_attivo = Viaggio().find_viaggio_attivo_utente(session["user"]["email"])
    try:
        remove_partecipante(viaggio_attivo["id_viaggio"], email)
        flash(f"{email} rimosso dal viaggio.", "success")
    except Exception as ex:
        flash(str(ex), "danger")

    return redirect(url_for("dashboard"))


@app.route("/admin/add_participant", methods=["POST"])
def add_participant():
    """
    Aggiunge forzatamente un utente registrato al viaggio (invito diretto da admin).

    A differenza di join_trip (che usa il codice invito), questo endpoint
    è riservato all'admin e permette di aggiungere qualsiasi utente già
    registrato nel sistema, scegliendo anche il ruolo.

    Verifica preventiva: l'email deve corrispondere a un account esistente.
    """
    if "user" not in session or not session["user"].get("admin", False):
        return redirect(url_for("index"))

    viaggio_attivo = Viaggio().find_viaggio_attivo_utente(session["user"]["email"])

    email = request.form.get("email")
    ruolo = request.form.get("ruolo", "partecipante")

    # Controlla che l'utente esista nel sistema prima di aggiungerlo
    ut = Utente(email=email)
    if not ut.find_by_email():
        flash("Utente non registrato all'app.", "danger")
    else:
        try:
            add_partecipante(viaggio_attivo["id_viaggio"], email, ruolo)
            flash(f"Partecipante {email} aggiunto.", "success")
        except Exception as ex:
            flash(str(ex), "danger")

    return redirect(url_for("dashboard"))


# =============================================================================
# AVVIO APPLICAZIONE
# =============================================================================

if __name__ == "__main__":
    # debug=True: ricarica automaticamente il server ad ogni modifica del codice.
    # NON usare debug=True in produzione (espone il debugger interattivo).
    app.run(debug=True, port=5000)
