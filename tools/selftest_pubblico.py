"""Verifica che il file pubblicabile non contenga dati personali.

Serve a non ripetere un errore già fatto: la prima versione di `--pubblico`
togliava il profilo dall'elenco degli utenti ma lo lasciava nel log del ciclo,
dove nome, capitale, valore del portafoglio e invii restavano in chiaro. Questo
controllo costruisce un profilo con dati riconoscibili, genera il file in
modalità pubblica e li cerca dentro.

    python tools/selftest_pubblico.py
"""

from __future__ import annotations

import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from build_web import build_payload              # noqa: E402
from engine import profile_file                  # noqa: E402
from engine.pipeline import run_scan             # noqa: E402

# Dati inventati ma inconfondibili: se compaiono nel file pubblico, c'è una fuga.
SPIA = {
    "nome completo": "Zeno Riservatissimo Esempio",
    "nome proprio": "Zeno",
    "capitale": "876543",
    "prezzo di carico": "321.99",
    "quantità": '"quantity": 17',
    "riferimento al file": "profilo.json",
    "riga del profilo": "Profilo personale",
}

PROFILO = {
    "id": "me", "name": SPIA["nome completo"], "first_name": SPIA["nome proprio"],
    "profile": {"capital": int(SPIA["capitale"]), "horizon": "Medio (3-5 anni)",
                "currency": "EUR", "country": "Italia", "risk_profile": "Bilanciato",
                "markets": ["USA", "Europa"], "sectors": ["Tecnologia", "AI"],
                "asset_classes": ["Azioni", "ETF"]},
    "channels": ["Telegram"], "weekly_limit": 2,
    "positions": [{"ticker": "MSFT", "quantity": 17, "avg_price": float(SPIA["prezzo di carico"]),
                   "opened_on": "2025-06-01"}],
    "watchlist": ["AMD"], "notifications_this_week": 0,
}

ok = True


def check(label: str, condition: bool, detail: str = "") -> None:
    global ok
    print(f"  [{'ok ' if condition else 'KO '}] {label}" + (f" — {detail}" if detail else ""))
    ok = ok and bool(condition)


def main() -> int:
    path = profile_file.PROFILE_PATH
    backup = path.read_text(encoding="utf-8") if path.exists() else None
    path.write_text(json.dumps(PROFILO, ensure_ascii=False, indent=2), encoding="utf-8")
    try:
        state = run_scan()
        user, problems = profile_file.load()
        check("il profilo di prova viene caricato", bool(user) and not problems,
              "; ".join(problems))
        check("il profilo è nel ciclo",
              any(u.get("from_file") for u in state["users"]))

        privato = json.dumps(build_payload(state, public=False), ensure_ascii=False)
        pubblico = json.dumps(build_payload(state, public=True), ensure_ascii=False)

        print("\nFile privato (la tua dashboard): i dati ci devono essere")
        check("il profilo personale è presente", SPIA["nome completo"] in privato)
        check("le posizioni sono presenti", SPIA["quantità"] in privato)

        print("\nFile pubblico (quello da mettere online): niente di personale")
        for etichetta, spia in SPIA.items():
            check(f"nessuna traccia: {etichetta}", spia not in pubblico,
                  "" if spia not in pubblico else "TROVATO")
        payload = json.loads(pubblico)
        check("nessun utente da file", not any(u.get("from_file") for u in payload["users"]))
        check("i tre profili dimostrativi restano", len(payload["users"]) == 3,
              str(len(payload["users"])))
        check("le analisi restano tutte", len(payload["assets"]) == len(state["assets"]),
              f"{len(payload['assets'])}/{len(state['assets'])}")
        check("il log del ciclo resta utilizzabile", len(payload["run_log"]) > 8,
              f"{len(payload['run_log'])} righe")
        check("la modalità è dichiarata nel file", payload.get("public") is True)
    finally:
        if backup is None:
            path.unlink(missing_ok=True)
        else:
            path.write_text(backup, encoding="utf-8")

    print("\n" + ("Nessuna fuga di dati personali." if ok else "ATTENZIONE: FUGA DI DATI."))
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
