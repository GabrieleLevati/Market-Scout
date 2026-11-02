"""Controlla l'installazione sul telefono, cioe' manifest e service worker.

Perche' esiste: l'app si installava e poi si apriva con "pagina non trovata",
mentre lo stesso indirizzo nel browser funzionava. La causa era un percorso
che finiva con index.html, che i server statici reindirizzano sulla cartella;
un reindirizzamento dentro un service worker, su una navigazione, diventa un
errore. Il difetto si vedeva solo installando l'app: nessun controllo sul
motore o sulla pagina lo avrebbe trovato, quindi serve questo.

    python tools/selftest_pwa.py

Gira senza rete: legge i file e ne controlla la forma.
"""
from __future__ import annotations

import json
import os
import re
import sys

RADICE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
WEB = os.path.join(RADICE, "web")

VERDE, ROSSO, RESET = "\033[32m", "\033[31m", "\033[0m"
ok_totale = True


def check(label: str, condizione: bool, dettaglio: str = "") -> None:
    global ok_totale
    segno = f"{VERDE}ok {RESET}" if condizione else f"{ROSSO}KO {RESET}"
    print(f"  [{segno}] {label}" + (f" - {dettaglio}" if dettaglio else ""))
    if not condizione:
        ok_totale = False


def leggi(nome: str) -> str:
    with open(os.path.join(WEB, nome), encoding="utf-8") as f:
        return f.read()


def senza_commenti(sorgente: str) -> str:
    """Il codice senza i commenti.

    Serve perche' un controllo che cerca una stringa nel sorgente la trova
    anche dentro il commento che spiega perche' quella cosa non si deve fare.
    E' successo davvero: il commento diceva "non si usa addAll perche' e'
    atomico" e il controllo ha letto "addAll" dichiarando il difetto presente.
    """
    senza_blocchi = re.sub(r"/\*.*?\*/", "", sorgente, flags=re.S)
    return re.sub(r"(?m)//.*$", "", senza_blocchi)


def main() -> int:
    print("1. Il manifest: dove si apre l'app")
    man = json.loads(leggi("manifest.webmanifest"))
    for campo in ("name", "short_name", "start_url", "scope", "display", "icons"):
        check(f"c'e' {campo}", campo in man)
    # Il cuore del difetto: un indirizzo che finisce con index.html viene
    # reindirizzato dal server, e l'app installata non si apre.
    check("start_url NON punta a index.html",
          "index.html" not in str(man.get("start_url", "")), str(man.get("start_url")))
    check("scope NON punta a index.html",
          "index.html" not in str(man.get("scope", "")), str(man.get("scope")))
    check("start_url e' relativo, cosi' funziona a qualunque indirizzo",
          not str(man.get("start_url", "")).startswith(("http", "/")),
          str(man.get("start_url")))
    check("display standalone (si apre senza barre del browser)",
          man.get("display") == "standalone", str(man.get("display")))
    misure = {i.get("sizes") for i in man.get("icons", [])}
    check("ci sono le icone 192 e 512", {"192x192", "512x512"} <= misure, str(misure))
    check("c'e' un'icona maskable, per Android",
          any("maskable" in str(i.get("purpose", "")) for i in man.get("icons", [])))

    print("\n2. Il service worker: niente index.html nei percorsi")
    sw = leggi("sw.js")
    guscio = re.search(r"const GUSCIO = \[(.*?)\];", sw, re.S)
    check("il guscio e' dichiarato", bool(guscio))
    voci = re.findall(r"'([^']+)'", guscio.group(1)) if guscio else []
    check("il guscio contiene la radice './'", "./" in voci, str(voci[:3]))
    check("il guscio NON contiene index.html",
          not any("index.html" in v for v in voci),
          ", ".join(v for v in voci if "index.html" in v) or "nessuno")
    for atteso in ("styles.css", "stili-cliente.css", "app.js", "charts.js",
                   "onboarding.js", "manifest.webmanifest"):
        check(f"nel guscio c'e' {atteso}", any(atteso in v for v in voci))
    check("data.js NON e' nel guscio (va preso dalla rete)",
          not any("data.js" in v for v in voci))

    print("\n3. Le trappole che hanno rotto l'app")
    codice = senza_commenti(sw)
    check("non si usa addAll, che e' atomico",
          ".addAll(" not in codice,
          "addAll fallisce tutto se un solo file manca")
    check("si mette in cache un file per volta",
          "GUSCIO.map" in codice or "Promise.all" in codice)
    check("non si mette in cache una risposta reindirizzata",
          "redirected" in codice)
    check("non si mette in cache una risposta non valida",
          "res.ok" in codice)
    check("le navigazioni hanno una strada loro",
          "navigate" in codice, "req.mode === 'navigate'")
    check("il ripiego delle navigazioni e' la radice, non index.html",
          "caches.match('./')" in codice)

    print("\n4. I dati del ciclo: prima la rete")
    check("data.js viene prima dalla rete", "data.js" in sw and "fetch(req)" in sw)
    check("se la rete manca si usa la copia in cache",
          "caches.match(req)" in sw)

    print("\n5. La versione della cache la riscrive la pubblicazione")
    check("c'e' la riga VERSIONE da riscrivere",
          re.search(r"const VERSIONE = '[^']+';", sw) is not None)
    with open(os.path.join(RADICE, "build_web.py"), encoding="utf-8") as f:
        build = f.read()
    check("build_web.py la timbra con l'impronta dei file",
          "_timbra_sw" in build and "VERSIONE" in build)
    check("sw.js e' fra i file pubblicati", '"sw.js"' in build)
    check("manifest e icone sono fra i file pubblicati",
          '"manifest.webmanifest"' in build and '"icona-192.png"' in build)

    print("\n6. La pagina dichiara il manifest e registra il service worker")
    html = leggi("index.html")
    check("c'e' il link al manifest", 'rel="manifest"' in html)
    check("c'e' il colore della barra", 'name="theme-color"' in html)
    check("c'e' l'icona per iPhone", "apple-touch-icon" in html)
    check("il service worker si registra solo su http(s)",
          "location.protocol.indexOf('http')" in html,
          "aperta da disco la pagina deve funzionare comunque")

    print("\n" + ("Tutti i controlli superati." if ok_totale
                  else "ALCUNI CONTROLLI FALLITI."))
    return 0 if ok_totale else 1


if __name__ == "__main__":
    raise SystemExit(main())
