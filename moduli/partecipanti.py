"""
moduli/partecipanti.py
----------------------
Modulo dedicato alla gestione della tabella `partecipanti` nel database.

La tabella `partecipanti` è la JOIN TABLE che collega:
    - utenti  (chi sei)
    - viaggi  (a quale viaggio partecipi)

Ogni riga registra che un utente (email) è membro di un viaggio (id_viaggio),
con un ruolo ('admin' o 'partecipante').

Struttura della tabella:
    id_partecipante  INT AUTO_INCREMENT PRIMARY KEY
    id_viaggio       INT NOT NULL  → FK verso viaggi.id_viaggio
    email            VARCHAR(255)  → FK verso utenti.email
    ruolo            VARCHAR(32)   → 'admin' | 'partecipante'
    UNIQUE KEY       (id_viaggio, email) → impedisce doppioni

Funzioni esportate:
    - ensure_table()         → crea la tabella se non esiste (eseguita all'import)
    - add_partecipante()     → aggiunge/aggiorna un membro
    - remove_partecipante()  → rimuove un membro
    - list_partecipanti()    → restituisce la lista completa dei membri
    - count_admins()         → conta quanti admin ha un viaggio
    - get_partecipante()     → recupera i dati di un singolo membro
"""

import database
from sqlalchemy import text

# Riferimento al motore SQLAlchemy condiviso con tutto il progetto
engine = database.engine


def ensure_table():
    """
    Crea la tabella `partecipanti` nel database se non esiste già.

    Viene chiamata automaticamente all'importazione del modulo, quindi
    non è necessario invocarla manualmente: basta importare questo file.
    Il vincolo UNIQUE KEY (id_viaggio, email) garantisce che uno stesso
    utente non possa comparire due volte nello stesso viaggio.
    """
    query = text("""
    CREATE TABLE IF NOT EXISTS partecipanti (
        id_partecipante INT AUTO_INCREMENT PRIMARY KEY,
        id_viaggio INT NOT NULL,
        email VARCHAR(255) NOT NULL,
        ruolo VARCHAR(32) DEFAULT 'partecipante',
        UNIQUE KEY ux_viaggio_email (id_viaggio, email)
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
    """)
    with engine.begin() as conn:
        conn.execute(query)


# Eseguita una volta sola all'importazione del modulo, prima di qualsiasi altra cosa
ensure_table()


def add_partecipante(id_viaggio, email, ruolo='partecipante'):
    """
    Aggiunge un utente a un viaggio oppure aggiorna il suo ruolo se già presente.

    Usa "ON DUPLICATE KEY UPDATE" per essere idempotente:
    se l'utente è già nel viaggio, aggiorna solo il ruolo senza errori.

    Args:
        id_viaggio (int): ID del viaggio a cui aggiungere l'utente.
        email (str): Email dell'utente da aggiungere.
        ruolo (str): Ruolo dell'utente ('admin' o 'partecipante'). Default: 'partecipante'.
    """
    query = text("""
    INSERT INTO partecipanti (id_viaggio, email, ruolo)
    VALUES (:iv, :e, :r)
    ON DUPLICATE KEY UPDATE ruolo = VALUES(ruolo)
    """)
    with engine.begin() as conn:
        conn.execute(query, {"iv": id_viaggio, "e": email, "r": ruolo})


def remove_partecipante(id_viaggio, email):
    """
    Rimuove un utente da un viaggio specifico.

    Nota: non elimina l'utente dal sistema, solo dalla lista partecipanti
    di quel viaggio. Le spese che ha registrato rimangono nel DB.

    Args:
        id_viaggio (int): ID del viaggio da cui rimuovere l'utente.
        email (str): Email dell'utente da rimuovere.
    """
    query = text("DELETE FROM partecipanti WHERE id_viaggio = :iv AND email = :e")
    with engine.begin() as conn:
        conn.execute(query, {"iv": id_viaggio, "e": email})


def list_partecipanti(id_viaggio):
    """
    Restituisce la lista completa dei partecipanti di un viaggio,
    con nome e ruolo presi dalla JOIN con la tabella utenti.

    Args:
        id_viaggio (int): ID del viaggio di cui elencare i membri.

    Returns:
        list[dict]: Lista di dizionari con chiavi 'email', 'nome', 'ruolo'.
                    Il nome proviene dalla tabella utenti (LEFT JOIN, può essere None).
    """
    query = text("""
    SELECT p.email, u.nome, p.ruolo
    FROM partecipanti p
    LEFT JOIN utenti u ON p.email = u.email
    WHERE p.id_viaggio = :iv
    ORDER BY u.nome
    """)
    with engine.connect() as conn:
        res = conn.execute(query, {"iv": id_viaggio}).mappings().fetchall()
        return [dict(r) for r in res]


def count_admins(id_viaggio):
    """
    Conta quanti utenti con ruolo 'admin' ha un viaggio.

    Usato come guardia di sicurezza prima di degradare un admin:
    se è l'unico, non si può procedere (il viaggio resterebbe senza capo).

    Args:
        id_viaggio (int): ID del viaggio.

    Returns:
        int: Numero di admin nel viaggio (può essere 0 se nessuno).
    """
    query = text("SELECT COUNT(*) FROM partecipanti WHERE id_viaggio = :iv AND ruolo = 'admin'")
    with engine.connect() as conn:
        return conn.execute(query, {"iv": id_viaggio}).scalar() or 0


def get_partecipante(id_viaggio, email):
    """
    Recupera i dati di un singolo partecipante in un viaggio.

    Utile per controllare il ruolo di un utente specifico senza caricare
    tutta la lista (più performante di list_partecipanti() in contesti mirati).

    Args:
        id_viaggio (int): ID del viaggio.
        email (str): Email del partecipante da cercare.

    Returns:
        dict | None: Dizionario con i dati del partecipante, oppure None se non trovato.
    """
    query = text("SELECT * FROM partecipanti WHERE id_viaggio = :iv AND email = :e")
    with engine.connect() as conn:
        res = conn.execute(query, {"iv": id_viaggio, "e": email}).mappings().fetchone()
        return dict(res) if res else None
