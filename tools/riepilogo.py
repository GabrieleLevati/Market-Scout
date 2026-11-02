"""Il riepilogo del ciclo, in Markdown.

Lo usa il ciclo automatico per scrivere il riassunto che si legge su GitHub
senza aprire il log, e si puo' usare a mano:

    python tools/riepilogo.py              # legge sito/data.js
    python tools/riepilogo.py web/data.js

Sta in un file invece che dentro il file del ciclo automatico per un motivo
pratico: il Python incollato dentro un YAML dipende dall'indentazione del
YAML, non si prova se non eseguendo il ciclo, e quando si rompe si rompe in
produzione. Qui si prova in un secondo.
"""
from __future__ import annotations

import json
import os
import sys


def carica(percorso: str) -> dict | None:
    try:
        with open(percorso, encoding="utf-8") as f:
            testo = f.read()
        return json.loads(testo[testo.index("{"):testo.rindex("}") + 1])
    except Exception as e:
        print(f"Non riesco a leggere {percorso}: {type(e).__name__}")
        return None


def righe(d: dict) -> list[str]:
    o = d.get("opportunita") or {}
    lista = o.get("lista") or []
    dati = d.get("data") or {}
    llm = d.get("llm") or {}
    nov = d.get("novita") or {}
    out = []

    quando = f"ultima seduta {dati.get('last_bar', '?')}"
    if dati.get("seduta_in_corso"):
        quando = (f"seduta del {dati.get('last_bar')} ANCORA IN CORSO "
                  f"({dati.get('su_oggi', 0)} strumenti su oggi, "
                  f"{dati.get('su_seduta_precedente', 0)} sulla chiusura prima)")
    out.append(f"- dati: {dati.get('source', '?')}, {quando}")
    out.append(f"- analisi: {llm.get('mode', '?')} · {llm.get('model', '?')}")
    ric = (llm.get("stats") or {}).get("ricadute")
    if ric:
        out.append(f"- il secondo modello è subentrato {ric} volte")
    out.append(f"- opportunità sopra {o.get('soglia', '?')}: **{len(lista)}**")
    if nov.get("primo_giro"):
        out.append("- primo giro: niente da confrontare")
    else:
        if nov.get("nuove"):
            out.append(f"- **nuove**: {', '.join(nov['nuove'])}")
        if nov.get("uscite"):
            out.append(f"- **uscite** (sotto soglia, non più proposte): "
                       f"{', '.join(nov['uscite'])}")
        if nov.get("salite"):
            out.append(f"- salite di punteggio: {', '.join(nov['salite'])}")
        if nov.get("scese"):
            out.append(f"- scese di punteggio: {', '.join(nov['scese'])}")

    if lista:
        out.append("")
        out.append("| strumento | voto | tipo | chi l'ha analizzato |")
        out.append("|---|---:|---|---|")
        for x in lista:
            fonti = x.get("analysis_sources") or {}
            quali = [k for k, v in fonti.items() if _da_modello(v)]
            chi = ("modello su " + ", ".join(quali)) if quali else "solo calcolo"
            out.append(f"| {x.get('ticker')} {x.get('name', '')} | {x.get('score')} | "
                       f"{x.get('asset_class', '')} | {chi} |")
    else:
        out.append("")
        out.append("Nessuno strumento sopra soglia in questo ciclo: non è un guasto, "
                   "è il mercato.")
    return out


def _da_modello(valore) -> bool:
    """Vero se quel componente l'ha prodotto un modello e non il calcolo."""
    t = str(valore).lower()
    return any(s in t for s in ("gemini", "llama", "gemma", "nemotron", "ai ("))


def main(argv: list[str]) -> int:
    percorso = argv[1] if len(argv) > 1 else os.path.join("sito", "data.js")
    d = carica(percorso)
    if d is None:
        return 1
    testo = "\n".join(righe(d))
    print(testo)
    # su GitHub il riepilogo va in un file apposito, in locale basta lo schermo
    sommario = os.environ.get("GITHUB_STEP_SUMMARY")
    if sommario:
        with open(sommario, "a", encoding="utf-8") as f:
            f.write("## Ciclo\n\n" + testo + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
