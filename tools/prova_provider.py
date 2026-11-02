"""Quali provider di AI riesce a raggiungere questa rete.

Non serve nessuna chiave: si chiama l'endpoint senza credenziali e si guarda la
RISPOSTA. Un 401 o un 403 e' una buona notizia (il server ha risposto, manca
solo la chiave); un timeout o un errore di DNS vuol dire che la rete aziendale
blocca quel dominio, e allora quel provider e' fuori discussione a prescindere
da quanto sia generoso il suo piano gratuito.

    python tools/prova_provider.py

Verificare prima di scegliere evita di aprire un account per un servizio che
da qui non si raggiunge: e' gia' successo con una fonte di prezzi.
"""
from __future__ import annotations

import json
import socket
import ssl
import time
import urllib.error
import urllib.request

# (nome, url, metodo, note sul piano gratuito dichiarato dal provider)
PROVIDER = [
    ("Google Gemini", "https://generativelanguage.googleapis.com/v1beta/models",
     "GET", "quello in uso: gratis con quota giornaliera"),
    ("Groq", "https://api.groq.com/openai/v1/models",
     "GET", "piano gratuito a limiti di frequenza, modelli aperti"),
    ("OpenRouter", "https://openrouter.ai/api/v1/models",
     "GET", "elenca anche modelli marcati :free"),
    ("Mistral", "https://api.mistral.ai/v1/models",
     "GET", "piano sperimentale gratuito"),
    ("Cerebras", "https://api.cerebras.ai/v1/models",
     "GET", "piano gratuito, inferenza molto rapida"),
    ("GitHub Models", "https://models.github.ai/catalog/models",
     "GET", "gratis per account GitHub, a limiti"),
    ("Cloudflare Workers AI", "https://api.cloudflare.com/client/v4/accounts/0/ai/models/search",
     "GET", "quota giornaliera gratuita; account Cloudflare gia' presente"),
    ("Hugging Face", "https://huggingface.co/api/models?limit=1",
     "GET", "inferenza serverless gratuita, a limiti"),
    ("Ollama (sul tuo computer)", "http://127.0.0.1:11434/api/tags",
     "GET", "nessun limite e nessun costo, ma gira sul tuo PC"),
]


def prova(url: str) -> tuple[str, int | None, float, str]:
    """Restituisce (esito, codice http, secondi, dettaglio)."""
    req = urllib.request.Request(url, headers={"Accept": "application/json",
                                               "User-Agent": "AI-Market-Scout-demo/0.1"})
    t0 = time.time()
    try:
        ctx = ssl.create_default_context()
        with urllib.request.urlopen(req, timeout=12, context=ctx) as r:
            corpo = r.read(400).decode("utf-8", "replace")
        return "raggiungibile", r.status, time.time() - t0, corpo[:90]
    except urllib.error.HTTPError as e:
        # 401/403 = il server c'e' e chiede la chiave: per noi e' un SI
        testo = e.read(300).decode("utf-8", "replace").replace("\n", " ")
        esito = "raggiungibile" if e.code in (400, 401, 403, 404, 422) else "risposta strana"
        return esito, e.code, time.time() - t0, testo[:90]
    except urllib.error.URLError as e:
        motivo = str(getattr(e, "reason", e))
        if "certificate" in motivo.lower():
            return "TLS ispezionato", None, time.time() - t0, motivo[:90]
        return "BLOCCATO", None, time.time() - t0, motivo[:90]
    except socket.timeout:
        return "BLOCCATO", None, time.time() - t0, "timeout"
    except Exception as e:
        return "BLOCCATO", None, time.time() - t0, f"{type(e).__name__}: {e}"[:90]


def main() -> int:
    print("Provider di AI raggiungibili da questa rete")
    print("=" * 74)
    esiti = []
    for nome, url, _metodo, nota in PROVIDER:
        esito, codice, secondi, dettaglio = prova(url)
        segno = {"raggiungibile": "SI ", "BLOCCATO": "NO ",
                 "TLS ispezionato": "TLS", "risposta strana": "?  "}[esito]
        print(f"{segno} {nome:<28} {str(codice or '-'):>4}  {secondi:5.1f}s  {nota}")
        if esito != "raggiungibile":
            print(f"      -> {dettaglio}")
        esiti.append((nome, esito))
    print("=" * 74)
    ok = [n for n, e in esiti if e == "raggiungibile"]
    print(f"Raggiungibili: {len(ok)} su {len(PROVIDER)}")
    print()
    print("Come si legge: SI vuol dire che il server ha risposto, anche se con un")
    print("401 'manca la chiave' - ed e' esattamente quello che ci serve sapere.")
    print("NO vuol dire che la rete blocca il dominio: quel provider e' fuori,")
    print("qualunque sia il suo piano gratuito.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
