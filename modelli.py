"""
modelli.py
----------
Modelli ORM "leggeri" per NomadCash (versione Flask).

NON usa SQLAlchemy ORM dichiarativo (Base, Column, relationship...),
ma lavora direttamente con query SQL testuali tramite `sqlalchemy.text`.
Ogni classe mappa una tabella del database e raccoglie le operazioni
CRUD (Create, Read, Update, Delete) che la riguardano.

Classi:
    Viaggio  → tabella `viaggi`
    Utente   → tabella `utenti`
    Spesa    → tabella `spese`

Nota sull'engine:
    Viene importato da database.py — un solo punto di configurazione
    per tutta la connessione al DB.
"""

import database

# Riferimento all'engine SQLAlchemy; condiviso con partecipanti.py
engine = database.engine

from sqlalchemy import text
from datetime import datetime


# =============================================================================
# CLASSE VIAGGIO
# =============================================================================

class Viaggio:
    """
    Modello per la tabella `viaggi`.

    Un viaggio rappresenta il "contenitore" principale dell'app:
    ogni spesa appartiene a un viaggio, ogni utente partecipa a un viaggio.

    Struttura tabella `viaggi`:
        id_viaggio             INT AUTO_INCREMENT PK
        nome_viaggio           VARCHAR
        data_partenza          DATE
        data_fine              DATE
        descrizione_itinerario TEXT (opzionale)
        uid_invito             VARCHAR(8) UNIQUE  → codice per invitare amici
    """

    def __init__(self, id_viaggio=None, nome=None, data_p=None,
                 data_f=None, descrizione=None, uid_invito=None):
        self.id_viaggio = id_viaggio
        self.nome = nome
        self.data_p = data_p          # Data di partenza (oggetto date Python)
        self.data_f = data_f          # Data di fine (oggetto date Python)
        self.descrizione = descrizione
        self.uid_invito = uid_invito  # Codice alfanumerico (es. "A1B2C3D4") per invitare amici

    def create(self):
        """
        Salva un nuovo viaggio nel database.

        Genera automaticamente il codice uid_invito (8 caratteri maiuscoli)
        se non viene passato esplicitamente nel costruttore.
        Dopo l'inserimento, memorizza in self.id_viaggio l'ID assegnato dal DB
        (utile per usare subito l'oggetto senza rififare query).
        """
        import uuid
        # Genera il codice invito solo se non è già stato impostato
        if not self.uid_invito:
            self.uid_invito = str(uuid.uuid4())[:8].upper()

        query = text("""INSERT INTO viaggi (nome_viaggio, data_partenza, data_fine, descrizione_itinerario, uid_invito)
                        VALUES (:n, :p, :f, :d, :uid)""")
        with engine.begin() as conn:
            result = conn.execute(query, {
                "n": self.nome, "p": self.data_p, "f": self.data_f,
                "d": self.descrizione, "uid": self.uid_invito
            })
            # lastrowid è l'ID auto-increment appena generato dal DB
            self.id_viaggio = result.lastrowid

    def read(self):
        """
        Legge tutti i dati di un viaggio dato il suo id_viaggio.

        Returns:
            dict | None: Dati del viaggio come dizionario, None se non trovato.
        """
        query = text("SELECT * FROM viaggi WHERE id_viaggio = :id")
        with engine.connect() as conn:
            res = conn.execute(query, {"id": self.id_viaggio}).mappings().fetchone()
            return dict(res) if res else None

    def update(self):
        """
        Aggiorna nome e descrizione del viaggio nel database.
        Usa i valori correnti di self.nome e self.descrizione.
        """
        query = text("""UPDATE viaggi SET nome_viaggio = :n, descrizione_itinerario = :d
        WHERE id_viaggio = :id """)
        with engine.begin() as conn:
            conn.execute(query, {"n": self.nome, "d": self.descrizione, "id": self.id_viaggio})

    def delete(self):
        """
        Elimina il viaggio dal database.

        Blocca l'eliminazione se esistono spese collegate, per evitare
        perdita accidentale di dati finanziari storici.

        Raises:
            Exception: Se ci sono spese associate al viaggio.
        """
        with engine.begin() as conn:
            # Controlla se esistono spese legate a questo viaggio prima di procedere
            check = conn.execute(
                text("SELECT COUNT(*) FROM spese WHERE id_viaggio=:id"),
                {"id": self.id_viaggio}
            ).scalar()
            if check > 0:
                raise Exception("Cancellazione bloccata: esistono spese collegate.")
            conn.execute(text("DELETE FROM viaggi WHERE id_viaggio=:id"), {"id": self.id_viaggio})

    def find_viaggio_attivo_utente(self, email):
        """
        Trova il viaggio attivo a cui partecipa un determinato utente.

        "Attivo" significa che data_fine >= oggi (non ancora scaduto).
        Se l'utente è in più viaggi attivi, restituisce quello con la
        data di partenza più imminente (ORDER BY data_partenza ASC LIMIT 1).

        Usato in quasi tutte le route per capire il contesto dell'utente loggato.

        Args:
            email (str): Email dell'utente di cui cercare il viaggio.

        Returns:
            dict | None: Dati del viaggio come dizionario, None se non trovato.
        """
        oggi = datetime.now().date()
        query = text("""
            SELECT v.*
            FROM viaggi v
            JOIN partecipanti p ON v.id_viaggio = p.id_viaggio
            WHERE p.email = :email AND v.data_fine >= :oggi
            ORDER BY v.data_partenza ASC LIMIT 1
        """)
        with engine.connect() as conn:
            res = conn.execute(query, {"oggi": oggi, "email": email}).mappings().fetchone()
            return dict(res) if res else None

    def find_viaggio_attivo(self):
        """
        Restituisce il primo viaggio attivo globale (tra tutti i viaggi del DB).

        Usato raramente; più utile in contesti single-tenant dove c'è
        un solo viaggio alla volta nel sistema.

        Returns:
            dict | None: Dati del viaggio, None se non trovato.
        """
        oggi = datetime.now().date()
        query = text("SELECT * FROM viaggi WHERE data_fine >= :oggi ORDER BY data_partenza ASC LIMIT 1")
        with engine.connect() as conn:
            res = conn.execute(query, {"oggi": oggi}).mappings().fetchone()
            return dict(res) if res else None

    def find_by_uid(self, uid):
        """
        Cerca un viaggio tramite il codice di invito (es. 'A1B2C3D4').

        Args:
            uid (str): Codice invito univoco del viaggio (8 caratteri maiuscoli).

        Returns:
            dict | None: Dati del viaggio, None se il codice non esiste.
        """
        query = text("SELECT * FROM viaggi WHERE uid_invito = :uid")
        with engine.connect() as conn:
            res = conn.execute(query, {"uid": uid}).mappings().fetchone()
            return dict(res) if res else None


# =============================================================================
# CLASSE UTENTE
# =============================================================================

class Utente:
    """
    Modello per la tabella `utenti`.

    Gestisce account, login (senza password — sistema basato solo su email),
    e il flag `admin` che determina se un utente ha poteri di gestione
    su un viaggio.

    Struttura tabella `utenti`:
        id_utente  INT AUTO_INCREMENT PK
        email      VARCHAR(255) UNIQUE
        nome       VARCHAR(255)
        avatar     TEXT (URL immagine profilo)
        admin      TINYINT(1)  → 0 = utente normale, 1 = amministratore

    Nota sul flag admin:
        Il flag è GLOBALE sull'utente, non per-viaggio. Un utente può
        essere admin di un solo viaggio alla volta (check nel metodo
        diventa_admin che blocca se è già admin).
    """

    def __init__(self, id_utente=None, email=None, nome=None, avatar=None, is_admin=False):
        self.id_utente = id_utente
        self.email = email
        self.nome = nome
        self.avatar = avatar
        self.is_admin = is_admin  # Flag locale Python; il valore reale viene dal DB

    def create(self):
        """
        Registra un nuovo utente nel sistema.

        Returns:
            bool: True se creato con successo, False se l'email è già registrata
                  o si verifica un altro errore DB.
        """
        query = text("""
            INSERT INTO utenti (email, nome, avatar, admin)
            VALUES (:e, :n, :av, :a)
        """)
        try:
            with engine.begin() as conn:
                result = conn.execute(query, {
                    "e": self.email,
                    "n": self.nome,
                    "av": self.avatar,
                    "a": self.is_admin
                })
                self.id_utente = result.lastrowid
            return True
        except Exception:
            # Fallisce se l'email è già in uso (UNIQUE constraint sul DB)
            return False

    def read(self):
        """
        Legge un utente partendo dal suo ID numerico.

        Returns:
            dict | None: Dati dell'utente, None se non trovato.
        """
        query = text("SELECT * FROM utenti WHERE id_utente = :id")
        with engine.connect() as conn:
            res = conn.execute(query, {"id": self.id_utente}).mappings().fetchone()
            return dict(res) if res else None

    def find_by_email(self):
        """
        Cerca e restituisce un utente tramite la sua email.

        È il metodo principale per il "login": se l'email esiste nel DB,
        l'utente viene autenticato e i suoi dati vengono messi in session.

        Returns:
            dict | None: Dati dell'utente (incluso il flag admin), None se non trovato.
        """
        query = text("SELECT * FROM utenti WHERE email = :e")
        with engine.connect() as conn:
            res = conn.execute(query, {"e": self.email}).mappings().fetchone()
            return dict(res) if res else None

    def delete(self):
        """
        Elimina l'utente dal sistema.

        Blocca se l'utente ha spese registrate per preservare la
        coerenza dei dati finanziari storici.

        Raises:
            Exception: Se l'utente ha spese collegate.
        """
        with engine.begin() as conn:
            check = conn.execute(
                text("SELECT COUNT(*) FROM spese WHERE id_utente = :id"),
                {"id": self.id_utente}
            ).scalar()

            if check > 0:
                raise Exception("Impossibile eliminare: utente con spese registrate.")

            conn.execute(
                text("DELETE FROM utenti WHERE id_utente = :id"),
                {"id": self.id_utente}
            )

    def diventa_admin(self):
        """
        Promuove l'utente ad amministratore (setta admin=1 nel DB).

        Blocca l'operazione se l'utente è già admin, per evitare
        conflitti in contesti multi-viaggio.

        Raises:
            Exception: Se l'utente è già admin di un altro viaggio.
        """
        # Legge lo stato attuale prima di modificare
        with engine.connect() as conn:
            is_admin = conn.execute(
                text("SELECT admin FROM utenti WHERE email = :e"),
                {"e": self.email}
            ).scalar()
            if is_admin:
                raise Exception("Operazione non consentita: l'utente è già admin di un viaggio.")

        query = text("UPDATE utenti SET admin = 1 WHERE email = :e")
        with engine.begin() as conn:
            conn.execute(query, {"e": self.email})

    def diventa_non_admin(self):
        """
        Rimuove i poteri di admin dall'utente (setta admin=0 nel DB).

        Blocca se l'utente non è admin (per evitare operazioni ridondanti
        che potrebbero indicare un bug nella logica chiamante).

        Raises:
            Exception: Se l'utente non è admin.
        """
        with engine.connect() as conn:
            is_admin = conn.execute(
                text("SELECT admin FROM utenti WHERE email = :e"),
                {"e": self.email}
            ).scalar()
            if not is_admin:
                raise Exception("Operazione non consentita: l'utente non è admin.")

        query = text("UPDATE utenti SET admin = 0 WHERE email = :e")
        with engine.begin() as conn:
            conn.execute(query, {"e": self.email})


# =============================================================================
# CLASSE SPESA
# =============================================================================

class Spesa:
    """
    Modello per la tabella `spese`.

    Ogni spesa rappresenta un acquisto effettuato durante il viaggio
    da uno specifico partecipante. Il campo `pagata` indica se la spesa
    è già stata "contabilizzata" nella divisione equa.

    Struttura tabella `spese`:
        id_spesa        INT AUTO_INCREMENT PK
        id_viaggio      INT NOT NULL  → FK verso viaggi
        email_utente    VARCHAR(255)  → chi ha pagato lo scontrino
        testo_messaggio TEXT          → descrizione della spesa
        importo         DECIMAL       → importo in euro
        categoria       VARCHAR       → es. "Cibo", "Benzina", "Commissione"
        data_spesa      DATE          → quando è avvenuta la spesa
        pagata          TINYINT(1)    → 0 = aperta/da dividere, 1 = già saldata
        data_pagamento  DATE          → data in cui è stata saldata (NULL se aperta)

    Metodi principali:
        create()           → inserisce una spesa nel DB
        delete()           → elimina una spesa non ancora saldata
        segna_come_pagata()→ salda una singola spesa
        settle_all()       → salda TUTTE le spese senza calcoli (bottone admin)
        divisione_equa()   → calcola e applica la divisione con commissione opzionale
    """

    def __init__(self, id_spesa=None, id_viaggio=None, email_utente=None,
                 testo_messaggio=None, importo=None, categoria=None,
                 data_spesa=None, pagata=False, data_pagamento=None):
        self.id_spesa = id_spesa
        self.id_viaggio = id_viaggio          # Viaggio a cui appartiene la spesa
        self.email_utente = email_utente      # Chi ha pagato lo scontrino fisicamente
        self.testo_messaggio = testo_messaggio  # Testo descrittivo (es. "Cena al ristorante")
        self.importo = importo
        self.categoria = categoria            # Es. "Cibo", "Benzina", "Hotel", "Commissione"
        self.data_spesa = data_spesa
        self.pagata = pagata                  # False (da dividere) | True (già saldata storicamente)
        self.data_pagamento = data_pagamento  # Popolata quando viene saldata

    def create(self):
        """
        Salva una nuova spesa nel database.

        Dopo l'inserimento, self.id_spesa viene aggiornato con l'ID
        assegnato dal DB (utile per riferimenti immediati).
        """
        query = text("""
            INSERT INTO spese (id_viaggio, email_utente, testo_messaggio,
                               importo, categoria, data_spesa, pagata)
            VALUES (:iv, :eu, :tm, :im, :ca, :ds, :pa)
        """)
        with engine.begin() as conn:
            result = conn.execute(query, {
                "iv": self.id_viaggio,
                "eu": self.email_utente,
                "tm": self.testo_messaggio,
                "im": self.importo,
                "ca": self.categoria,
                "ds": self.data_spesa,
                "pa": self.pagata
            })
            self.id_spesa = result.lastrowid

    def read(self):
        """
        Recupera una spesa dal DB tramite il suo id_spesa.

        Returns:
            dict | None: Dati della spesa, None se non trovata.
        """
        query = text("SELECT * FROM spese WHERE id_spesa = :id")
        with engine.connect() as conn:
            res = conn.execute(query, {"id": self.id_spesa}).mappings().fetchone()
            return dict(res) if res else None

    def delete(self):
        """
        Elimina una spesa, ma solo se non è ancora stata saldata.

        Impedisce la cancellazione di spese già chiuse (pagata=1) per
        preservare l'integrità dello storico contabile.

        Raises:
            Exception: Se la spesa risulta già pagata nel DB.
        """
        with engine.begin() as conn:
            # Controlla lo stato PRIMA di eliminare
            check = conn.execute(
                text("SELECT pagata FROM spese WHERE id_spesa = :id"),
                {"id": self.id_spesa}
            ).scalar()
            if check:  # Se pagata=1, blocca l'operazione
                raise Exception("Cancellazione bloccata: la spesa è già stata saldata.")
            conn.execute(
                text("DELETE FROM spese WHERE id_spesa = :id"),
                {"id": self.id_spesa}
            )

    def segna_come_pagata(self):
        """
        Segna una singola spesa come saldata, inserendo la data odierna.

        Usata per chiudere manualmente una spesa specifica (non tutta la
        lista del viaggio). Aggiorna anche i campi Python locali.
        """
        oggi = datetime.now().date()
        query = text("""
            UPDATE spese
            SET pagata = 1, data_pagamento = :oggi
            WHERE id_spesa = :id
        """)
        with engine.begin() as conn:
            conn.execute(query, {"oggi": oggi, "id": self.id_spesa})
        # Aggiorna anche i valori locali dell'istanza Python
        self.pagata = True
        self.data_pagamento = oggi

    def settle_all(self):
        """
        Salda TUTTE le spese aperte del viaggio senza applicare la divisione equa.

        Questo è il comportamento del pulsante "💸 Salda tutti i conti":
        marca tutte le spese non pagate come pagata=1, registrando la
        data odierna, senza ricalcolare chi deve cosa a chi.

        Differenza con divisione_equa():
            - settle_all() → segna e basta, nessun calcolo di crediti/debiti
            - divisione_equa() → calcola prima i bilanci, poi segna tutto

        Returns:
            int: Numero di spese saldare (0 se non c'era nulla da saldare).
        """
        oggi = datetime.now().date()

        # Controlla prima quante spese sono aperte
        query_check = text("""
            SELECT COUNT(*) FROM spese
            WHERE id_viaggio = :iv AND pagata = 0
        """)
        query_salda = text("""
            UPDATE spese
            SET pagata = 1, data_pagamento = :oggi
            WHERE id_viaggio = :iv AND pagata = 0
        """)
        with engine.connect() as conn:
            count = conn.execute(query_check, {"iv": self.id_viaggio}).scalar() or 0

        if count == 0:
            return 0  # Nessuna spesa da saldare — esce subito

        with engine.begin() as conn:
            conn.execute(query_salda, {"oggi": oggi, "iv": self.id_viaggio})

        return count  # Restituisce il numero di spese chiuse, utile per il flash message

    def numero_viaggiatori(self):
        """
        Conta quanti partecipanti ha il viaggio corrente.

        Usato per calcolare la quota pro capite nella divisione equa.
        Conta i partecipanti dalla tabella `partecipanti`, non dalla tabella `spese`
        (quindi include anche chi non ha ancora registrato spese).

        Returns:
            int: Numero totale di partecipanti al viaggio.
        """
        query = text("""
            SELECT COUNT(*)
            FROM partecipanti
            WHERE id_viaggio = :iv
        """)
        with engine.connect() as conn:
            return conn.execute(query, {"iv": self.id_viaggio}).scalar()

    def divisione_equa(self):
        """
        Algoritmo principale per chiudere i conti con divisione equa.

        Flusso completo:
        ──────────────────────────────────────────────────────────────
        STEP 1 — Calcola il totale delle spese non saldate (pagata=0).
                 Se è zero, non c'è nulla da fare.

        STEP 2 — Commissione di gestione (condizionale):
                 Se il totale supera €300, inserisce automaticamente
                 una spesa di €0.50 per OGNI partecipante del viaggio.
                 Queste spese vengono create con pagata=0 così vengono
                 incluse nel ricalcolo del totale.
                 Scopo: far contribuire equamente al costo operativo del sistema.

        STEP 3 — Calcola la divisione equa sul totale aggiornato
                 (spese ordinarie + eventuali commissioni).
                 Divide solo tra chi ha almeno una spesa aperta nel DB.
                 Formula: bilancio = quanto_hai_pagato - quota_media

        STEP 4 — Segna tutte le spese come pagata=1 (incluse le commissioni).

        STEP 5 — Reset automatico del flag admin se il viaggio è scaduto
                 e non ci sono più spese aperte.

        Nota importante:
            self.email_utente deve essere l'email dell'admin che ha
            invocato l'azione, perché viene usato nello step 5 per
            revocare i poteri admin a fine viaggio.

        Returns:
            dict: {
                "bilanci": {email: bilancio_float, ...},
                "commissione_applicata": bool
            }
            Dizionario vuoto {} se non c'era nulla da dividere.

        Esempi bilancio:
            bilancio > 0  → l'utente è in DEBITO (ha pagato meno della quota)
            bilancio < 0  → l'utente è in CREDITO (ha pagato più della quota)
            bilancio == 0 → pari
        """
        oggi = datetime.now().date()

        # ── STEP 1: Totale spese non saldate ──────────────────────────────────
        query_totale_iniziale = text("""
            SELECT COALESCE(SUM(importo), 0)
            FROM spese
            WHERE id_viaggio = :iv AND pagata = 0
        """)
        with engine.connect() as conn:
            totale_iniziale = float(conn.execute(query_totale_iniziale, {"iv": self.id_viaggio}).scalar())

        # Nessuna spesa da dividere: esci subito senza fare nulla
        if totale_iniziale == 0:
            return {}

        # ── STEP 2: Commissione di gestione (solo se totale > €300) ───────────
        commissione_applicata = False
        if totale_iniziale > 300.0:
            # Recupera TUTTI i partecipanti (non solo chi ha spese aperte)
            query_partecipanti = text("""
                SELECT email FROM partecipanti WHERE id_viaggio = :iv
            """)
            with engine.connect() as conn:
                partecipanti_rows = conn.execute(query_partecipanti, {"iv": self.id_viaggio}).fetchall()

            # Inserisce una riga di commissione per ciascun partecipante.
            # pagata=0 → viene inclusa nel calcolo della quota qui sotto.
            # Categoria "Commissione" → distinguibile visivamente nella lista spese.
            query_ins_commissione = text("""
                INSERT INTO spese (id_viaggio, email_utente, testo_messaggio,
                                   importo, categoria, data_spesa, pagata)
                VALUES (:iv, :eu, :tm, :im, :ca, :ds, 0)
            """)
            with engine.begin() as conn:
                for row in partecipanti_rows:
                    conn.execute(query_ins_commissione, {
                        "iv": self.id_viaggio,
                        "eu": row[0],                              # email del partecipante
                        "tm": "Commissione di gestione divisione equa",
                        "im": 0.50,                               # 50 centesimi fissi
                        "ca": "Commissione",
                        "ds": oggi
                    })
            commissione_applicata = True

        # ── STEP 3: Calcolo divisione equa (include commissioni se aggiunte) ──
        # Raggruppa per utente: somma di tutto ciò che ha pagato finora (non saldato)
        query_spese = text("""
            SELECT email_utente, SUM(importo) AS totale_pagato
            FROM spese
            WHERE id_viaggio = :iv AND pagata = 0
            GROUP BY email_utente
        """)
        # Totale aggiornato (può includere le commissioni appena inserite)
        query_totale = text("""
            SELECT COALESCE(SUM(importo), 0)
            FROM spese
            WHERE id_viaggio = :iv AND pagata = 0
        """)
        with engine.connect() as conn:
            totale = float(conn.execute(query_totale, {"iv": self.id_viaggio}).scalar())
            righe = conn.execute(query_spese, {"iv": self.id_viaggio}).mappings().fetchall()

        if not righe:
            # Non dovrebbe mai succedere qui, ma per sicurezza
            return {}

        # Numero di utenti che hanno spese aperte (= divisore per la quota)
        n = len(righe)
        quota = totale / n  # Quanto dovrebbe aver speso ognuno in media

        # Costruisce il dizionario dei bilanci
        # bilancio positivo = ha pagato MENO della quota → è in DEBITO verso gli altri
        # bilancio negativo = ha pagato PIÙ della quota → è in CREDITO
        bilanci = {}
        for riga in righe:
            bilanci[riga["email_utente"]] = round(float(riga["totale_pagato"]) - float(quota), 2)

        # ── STEP 4: Salda tutto — spese ordinarie + commissioni ─────────────
        query_salda = text("""
            UPDATE spese
            SET pagata = 1, data_pagamento = :oggi
            WHERE id_viaggio = :iv AND pagata = 0
        """)
        with engine.begin() as conn:
            conn.execute(query_salda, {"oggi": oggi, "iv": self.id_viaggio})

        # ── STEP 5: Reset admin se il viaggio è terminato ────────────────────
        # Controlla se la data di fine viaggio è già passata E non ci sono più spese aperte.
        # In quel caso revoca automaticamente i poteri admin per "chiudere" il viaggio.
        query_viaggio = text("SELECT data_fine FROM viaggi WHERE id_viaggio = :iv")
        query_spese_aperte = text("""
            SELECT COUNT(*) FROM spese
            WHERE id_viaggio = :iv AND pagata = 0
        """)
        with engine.connect() as conn:
            data_fine = conn.execute(query_viaggio, {"iv": self.id_viaggio}).scalar()
            spese_aperte = conn.execute(query_spese_aperte, {"iv": self.id_viaggio}).scalar()

        # Revoca l'admin usando self.email_utente (deve essere l'email dell'admin chiamante)
        if data_fine and oggi >= data_fine and spese_aperte == 0:
            admin = Utente(email=self.email_utente)
            admin.diventa_non_admin()

        return {"bilanci": bilanci, "commissione_applicata": commissione_applicata}


"""
NOTA IMPLEMENTATIVA — divisione_equa() e self.email_utente
──────────────────────────────────────────────────────────
Nello step 5 si usa self.email_utente per la revoca admin.
Questo è corretto perché la route /spese/divisione_equa
costruisce l'oggetto Spesa passando email_utente=session["user"]["email"],
e solo l'admin può accedere a quella route.

Se in futuro servisse passare esplicitamente l'email dell'admin
(es. per test o automazioni), basta aggiungere un parametro
`admin_email=None` al metodo e usarlo al posto di self.email_utente.
"""