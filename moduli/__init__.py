"""
moduli/__init__.py
------------------
File di inizializzazione del package `moduli`.

Definisce le costanti globali dell'applicazione NomadCash
importabili da qualsiasi modulo con:
    from moduli import APP_NAME, VERSION

Nota: questo file era usato dalla versione Streamlit (main.py).
Nella versione Flask (app.py) le costanti non sono ancora richiamate
attivamente, ma restano qui per riferimento e future estensioni.
"""

# Nome visualizzato dell'applicazione
APP_NAME = "Nomadcash"

# Versione corrente del software (usa Semantic Versioning: MAJOR.MINOR.PATCH)
VERSION = "1.0.0"