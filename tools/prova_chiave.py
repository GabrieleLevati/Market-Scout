"""Prova una chiave Gemini e dice che limiti le concede l'API.

A che serve: la quota non si legge da nessuna parte nel pannello: la dichiara
l'API stessa nel messaggio di errore quando la superi. Questo strumento fa una
chiamata vera, minima, e poi ne fa qualcuna di fila per vedere se e quando
arriva il rifiuto, riportando il limite dichiarato.

    python tools/prova_chiave.py                # usa GEMINI_API_KEY
    python tools/prova_chiave.py --chiedi       # la chiede senza mostrarla
    python tools/prova_chiave.py --raffica 6    # prova 6 chiamate di fila

La chiave non viene mai stampata e non finisce in nessun file.
"""
from __future__ import annotations

import argparse
import getpass
import json
import os
import ssl
import sys
import time
import urllib.error
import urllib.request

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from engine.llm import DEFAULT_MODEL, quota_detail, suggested_model  # noqa: E402

BASE = "https://generativelanguage.googleapis.com/v1beta"


def chiama(chiave: str, modello: str, timeout: int = 180) -> tuple[str, float, str]:
    """Una chiamata minima. Restituisce (esito, secondi, dettaglio)."""
    corpo = {
        "contents": [{"role": "user", "parts": [{"text": "Rispondi solo: ok"}]}],
        "generationConfig": {"maxOutputTokens": 30,
                             "thinkingConfig": {"thinkingBudget": 0}},
    }
    req = urllib.request.Request(
        f"{BASE}/models/{modello}:generateContent",
        data=json.dumps(corpo).encode("utf-8"),
        headers={"Content-Type": "application/json", "x-goog-api-key": chiave},
        method="POST")
    t0 = time.time()
    try:
        with urllib.request.urlopen(req, timeout=timeout,
                                    context=ssl.create_default_context()) as r:
            json.loads(r.read().decode("utf-8"))
        return "ok", time.time() - t0, ""
    except urllib.error.HTTPError as e:
        testo = e.read().decode("utf-8", "replace")
        return f"http {e.code}", time.time() - t0, testo
    except Exception as e:
        return type(e).__name__, time.time() - t0, str(e)


def elenca_modelli(chiave: str) -> list[str]:
    req = urllib.request.Request(f"{BASE}/models",
                                 headers={"x-goog-api-key": chiave})
    try:
        with urllib.request.urlopen(req, timeout=60,
                                    context=ssl.create_default_context()) as r:
            dati = json.loads(r.read().decode("utf-8"))
        return sorted(m["name"].split("/")[-1] for m in dati.get("models", [])
                      if "generateContent" in m.get("supportedGenerationMethods", []))
    except Exception:
        return []


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--chiedi", action="store_true",
                    help="chiede la chiave da tastiera senza mostrarla")
    ap.add_argument("--modello", default=os.environ.get("GEMINI_MODEL") or DEFAULT_MODEL)
    ap.add_argument("--raffica", type=int, default=1,
                    help="quante chiamate di fila (per far dichiarare la quota)")
    args = ap.parse_args()

    if args.chiedi:
        chiave = getpass.getpass("Incolla la chiave (non viene mostrata): ").strip()
    else:
        chiave = os.environ.get("GEMINI_API_KEY", "").strip()
    if not chiave:
        print("Nessuna chiave. Usa --chiedi, oppure imposta GEMINI_API_KEY.")
        return 1

    print(f"Modello: {args.modello}")
    modelli = elenca_modelli(chiave)
    print(f"Modelli che questa chiave puo' usare: {len(modelli)}")
    if modelli and args.modello not in modelli:
        print(f"  ATTENZIONE: {args.modello} non e' nell'elenco. Alternative flash: "
              + ", ".join(m for m in modelli if "flash" in m)[:200])

    quota = None
    riuscite = 0
    for i in range(1, max(1, args.raffica) + 1):
        esito, secondi, dettaglio = chiama(chiave, args.modello)
        print(f"  chiamata {i}: {esito} in {secondi:.1f}s", end="")
        if esito == "ok":
            riuscite += 1
            print()
            continue
        q = quota_detail(dettaglio)
        if q:
            quota = q
            print(f"  -> {q}")
            break
        sug = suggested_model(dettaglio)
        if sug:
            print(f"  -> il modello da usare sembra essere {sug}")
            break
        print(f"  -> {dettaglio[:200].replace(chr(10), ' ')}")
        break

    print()
    if riuscite and not quota:
        print(f"La chiave FUNZIONA ({riuscite} chiamate riuscite) e in questa prova non ha "
              f"dichiarato nessun limite.")
        print("Per sapere se e' sul piano gratuito o su quello a pagamento, rilancia con "
              "--raffica 25: se e' gratuito, intorno alla ventesima chiamata l'API dichiara "
              "la quota.")
    elif quota:
        print(f"La chiave funziona ma e' sul piano con quota: {quota}.")
        print("Vuol dire piano gratuito. Per togliere il tetto serve attivare la "
              "fatturazione sul progetto Google Cloud a cui appartiene la chiave.")
    else:
        print("La chiave non ha funzionato: vedi il dettaglio qui sopra.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
