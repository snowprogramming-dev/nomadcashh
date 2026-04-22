"""
database.py
-----------
Punto di ingresso unico per la connessione al database MySQL.

Questo file crea l'oggetto `engine` di SQLAlchemy, che viene importato
da tutti gli altri moduli (modelli.py, moduli/partecipanti.py).
Centralizzare la connessione qui significa che per cambiare database
basta modificare solo DB_URL in questo file.

Formato della stringa di connessione:
    mysql+mysqlconnector://<utente>:<password>@<host>/<nome_database>
    - mysql+mysqlconnector : usa il driver mysql-connector-python
    - root                 : utente MySQL (nessuna password in sviluppo locale)
    - localhost            : server MySQL in esecuzione sulla stessa macchina
    - nomadcash            : nome del database a cui connettersi
"""

from sqlalchemy import create_engine

# Stringa di connessione al database MySQL locale.
# In produzione, sostituisci con una variabile d'ambiente per non esporre credenziali.
DB_URL = "mysql+mysqlconnector://root@localhost/nomadcash"

# engine è il "motore" SQLAlchemy: gestisce il connection pool e
# viene passato a ogni query tramite engine.connect() o engine.begin().
engine = create_engine(DB_URL)