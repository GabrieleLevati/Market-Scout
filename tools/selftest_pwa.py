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


def senza_commenti_css(sorgente: str) -> str:
    """Un foglio di stile senza i commenti.

    Serve una funzione a parte da senza_commenti(): quella toglie anche da
    "//" a fine riga, che in CSS NON e' un commento e sta dentro ogni URL
    (url(https://...)). E serve per forza: i commenti qui dentro spiegano
    quali regole non si devono scrivere, quindi contengono le stesse parole
    che i controlli cercano. Un controllo che legge i commenti ha trovato il
    difetto dentro la sua spiegazione e, peggio, il falso riscontro si e'
    mangiato la regola vera che veniva subito dopo: diceva "tutto a posto"
    proprio mentre il difetto era presente.
    """
    return re.sub(r"/\*.*?\*/", "", sorgente, flags=re.S)


def senza_rem(sorgente: str) -> str:
    """Un file .cmd senza le righe di commento, per la stessa ragione.

    Qui i commenti spiegano proprio che "--cartella sito" non si deve usare:
    cercarlo nel sorgente intero lo troverebbe nella spiegazione.
    """
    return re.sub(r"(?mi)^\s*rem\b.*$", "", sorgente)


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

    print("\n6a. Ogni colore usato nel foglio di stile deve esistere")
    # PERCHE'. Una variabile CSS inesistente non da' errore: il browser
    # scarta la dichiarazione e tira avanti. Ho scritto var(--card),
    # var(--sh-1) e var(--text) a memoria - i token veri sono --surface-1,
    # --lift e --text-1 - e dodici dichiarazioni sono state ignorate in
    # silenzio: pulsanti attivi senza fondo, riquadri senza superficie. Si
    # vedeva solo guardando una schermata, e solo sapendo cosa cercare.
    # senza i commenti: le spiegazioni qui dentro contengono le stesse parole
    # che questi controlli cercano, e un falso riscontro in un commento si
    # mangia la regola vera che viene subito dopo.
    css = senza_commenti_css(
        "\n".join(leggi(n) for n in ("styles.css", "stili-cliente.css")))
    # Queste non si dichiarano nel foglio: le mette il programma sull'elemento
    # (--i l'ordine di comparsa, --len la lunghezza del tracciato da animare,
    # --tinta il colore del tipo, che arriva da una classe).
    A_RUNTIME = {"i", "len", "tinta"}
    definite = set(re.findall(r"--([a-z0-9-]+)\s*:", css)) | A_RUNTIME
    usate = set(re.findall(r"var\(\s*--([a-z0-9-]+)", css))
    mancanti = sorted(usate - definite)
    check("nessuna variabile usata senza essere definita", not mancanti,
          ", ".join(mancanti) if mancanti else f"{len(usate)} variabili, tutte definite")
    # e il contrario: una tinta per tipo dichiarata e mai usata sarebbe un
    # colore che non arriva in pagina
    for n in range(1, 7):
        check(f"la tinta del tipo {n} e' dichiarata e usata",
              f"--tp{n}:" in css and f"var(--tp{n})" in css)

    print("\n6c. Il giro della carta: due regole che non si possono toccare")
    # Rotte entrambe aggiungendo un bordino colorato in cima alla card, e
    # scoperte dall'utente e non dai test: la pagina era diventata
    # illeggibile, con le card accavallate una sull'altra.
    #
    # Le due facce stanno una SOPRA l'altra perche' sono in posizione
    # assoluta. Riportarle nel flusso le fa diventare alte come tutto il loro
    # contenuto, e la card perde l'altezza misurata: non e' un difetto
    # grafico, e' il giro della carta che smette di funzionare.
    regole_faccia = re.findall(r"(?ms)^[^@{}\n]*\.faccia[^{]*\{[^}]*\}", css)
    relative = [r for r in regole_faccia
                if re.search(r"position\s*:\s*relative", r)
                and "::" not in r.split("{")[0]]
    check("nessuna regola riporta .faccia nel flusso", not relative,
          "trovata: " + (relative[0].split("{")[0].strip() if relative else "nessuna"))
    check(".faccia resta in posizione assoluta",
          any(re.search(r"position\s*:\s*absolute", r) for r in regole_faccia))

    # Lo pseudo-elemento ::before della faccia e' GIA' la riga di luce in
    # cima al vetro. Una seconda regola sullo stesso pseudo-elemento non si
    # somma: lo sostituisce, e quel dettaglio sparisce in silenzio.
    prima = re.findall(r"\.faccia::before", css)
    check("un solo ::before sulla faccia, quello della riga di luce",
          len(prima) == 1, f"{len(prima)} regole")
    check("e il bordino del tipo usa il bordo, non uno pseudo-elemento",
          re.search(r"\.flip \.faccia\s*\{[^}]*border-top-color", css) is not None)

    # La navigazione non deve scorrere: tre voci stanno in larghezza, e una
    # barra che scorre lascia la terza voce fuori dallo schermo.
    nav = re.search(r"(?ms)^\.navpag\s*\{[^}]*\}", css)
    check("la navigazione e' centrata",
          nav is not None and "justify-content: center" in nav.group(0))
    check("e non scorre in orizzontale",
          nav is not None and "overflow-x" not in nav.group(0),
          "con lo scorrimento la terza voce resta mezza fuori")

    print("\n6b. I dati nuovi devono arrivare sul telefono")
    # "Prima la rete" non basta. Un fetch normale puo' essere soddisfatto
    # dalla cache HTTP del browser senza toccare la rete, se la risposta
    # precedente dichiarava una scadenza lunga: il service worker crede di
    # aver chiesto il dato nuovo e serve quello di stamattina. Niente da
    # vedere nei log, nessun errore, solo numeri vecchi con l'aria di essere
    # nuovi. Due cose lo impediscono, e si controllano entrambe.
    sw = senza_commenti(leggi("sw.js"))
    ramo_dati = sw[sw.find("/data.js"):]
    check("data.js viene chiesto prima alla rete",
          "/data.js" in sw and "fetch(" in ramo_dati)
    check("e la richiesta salta la cache HTTP del browser",
          "'no-cache'" in ramo_dati or '"no-cache"' in ramo_dati,
          "serve cache: 'no-cache' nel ramo di data.js")
    check("se la rete manca si ricade sulla copia in cache",
          "caches.match(req)" in ramo_dati)

    check("c'e' il file delle scadenze HTTP per l'hosting",
          os.path.exists(os.path.join(WEB, "_headers")),
          "senza, la scadenza di data.js la decide Cloudflare")
    if os.path.exists(os.path.join(WEB, "_headers")):
        with open(os.path.join(WEB, "_headers"), encoding="utf-8") as f:
            righe = [r.strip() for r in f if r.strip() and not r.strip().startswith("#")]
        testo = "\n".join(righe)
        check("dichiara data.js senza conservazione cieca",
              "/data.js" in testo and "no-cache" in testo, testo[:70])
        check("e vale anche per il service worker, che decide quale app gira",
              "/sw.js" in testo)
    check("_headers e' fra i file pubblicati",
          '"_headers"' in build,
          "se non viene copiato nella cartella, l'hosting non lo vede")

    print("\n7. La cartella pubblicata ha UN SOLO autore")
    # Il difetto che questo gruppo impedisce: "sito" era rigenerata sia dai
    # cicli sul PC sia da quello nel cloud, e tutti e due la salvavano nel
    # repository. Alla prima divergenza git ha fatto il suo mestiere e ha
    # scritto i marcatori di conflitto DENTRO sito/data.js: il file non era
    # piu' JavaScript valido, la pagina si apriva bianca, e il motivo non si
    # vedeva ne' nel codice ne' nei dati - solo aprendo il file.
    scrittori = []
    for nome in sorted(f for f in os.listdir(RADICE) if f.lower().endswith(".cmd")):
        with open(os.path.join(RADICE, nome), encoding="utf-8", errors="replace") as f:
            if "--cartella sito" in senza_rem(f.read()):
                scrittori.append(nome)
    check("nessuno script sul PC rigenera \"sito\"", not scrittori,
          ", ".join(scrittori) or "nessuno, giusto cosi'")

    ciclo = os.path.join(RADICE, ".github", "workflows", "ciclo.yml")
    with open(ciclo, encoding="utf-8") as f:
        yml = f.read()
    check("il ciclo nel cloud la rigenera, cioe' l'autore unico esiste",
          "--cartella sito" in yml)

    # L'orario del ciclo con AI e' scritto in DUE posti: fra i cron e nel
    # confronto che decide se usare il modello. Spostarne uno e dimenticare
    # l'altro non rompe niente in modo visibile: il ciclo gira all'ora nuova
    # ma prende il ramo "senza AI", e le analisi restano del solo calcolo
    # senza che nessuno lo dichiari. E' il tipo di difetto che si scopre un
    # mese dopo guardando perche' il modello non risponde mai.
    dichiarati = set(re.findall(r"(?m)^\s*-\s*cron:\s*'([^']+)'", yml))
    confrontati = set(re.findall(r"github\.event\.schedule\s*\}\}\"?\s*=\s*\"([^\"]+)\"", yml))
    check("ci sono cron dichiarati", bool(dichiarati), str(sorted(dichiarati)))
    check("ogni orario confrontato nel codice e' un cron che esiste davvero",
          confrontati <= dichiarati,
          f"orfani: {sorted(confrontati - dichiarati)}" if confrontati - dichiarati
          else f"{len(confrontati)} confronto/i, tutti validi")
    check("il ciclo non dipende dal solo cron, che GitHub non garantisce",
          re.search(r"(?m)^\s*push:", yml) is not None,
          "serve anche un innesco su push: lo scheduler non e' mai partito")
    check("e il push non rincorre i commit del ciclo stesso",
          "paths-ignore" in yml and "'sito/**'" in yml)

    with open(os.path.join(RADICE, ".gitattributes"), encoding="utf-8") as f:
        attributi = f.read()
    check("git ha l'ordine di non fondere i file generati",
          re.search(r"(?m)^sito/\*\*.*-merge", attributi) is not None,
          "serve 'sito/** -merge' in .gitattributes")

    with open(os.path.join(RADICE, ".gitignore"), encoding="utf-8") as f:
        ignorati = f.read()
    check("la cartella del PC resta fuori dal repository",
          re.search(r"(?m)^da-caricare/?$", ignorati) is not None,
          "serve 'da-caricare/' in .gitignore")

    dati = os.path.join(RADICE, "sito", "data.js")
    if os.path.exists(dati):
        with open(dati, encoding="utf-8", errors="replace") as f:
            testo = f.read()
        check("sito/data.js non contiene marcatori di conflitto",
              "<<<<<<<" not in testo and ">>>>>>>" not in testo,
              "se falliscono, rigenera il file: non si fonde a mano")
        try:
            json.loads(testo[testo.index("{"):testo.rindex("}") + 1])
            leggibile = True
        except Exception as e:
            leggibile = f"{type(e).__name__}: {e}"
        check("e si legge ancora come JSON", leggibile is True,
              "" if leggibile is True else str(leggibile)[:80])

    print("\n" + ("Tutti i controlli superati." if ok_totale
                  else "ALCUNI CONTROLLI FALLITI."))
    return 0 if ok_totale else 1


if __name__ == "__main__":
    raise SystemExit(main())
