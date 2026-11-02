"""Memoria di cosa e' gia' stato annunciato: il filtro anti-ripetizione.

Il ciclo gira **ogni due ore**, dodici volte al giorno. Se notificasse tutte le
opportunita' sopra soglia, manderebbe dodici volte lo stesso messaggio e chi lo
riceve spegnerebbe le notifiche entro sera. Il valore del prodotto non sta nel
numero di segnalazioni: sta nel fatto che quando arriva una segnalazione vale la
pena aprirla. Questo modulo esiste per difendere quella proprieta'.

Tiene su disco (`.opportunita_viste.json`) lo stato di ogni titolo che e' stato
sopra soglia almeno una volta, e a ogni ciclo risponde a una domanda sola: di
questo elenco, che cosa l'utente non sa ancora?

Tre esiti separati:

* **nuove** - titoli che prima non erano sopra soglia (compreso il rientro di
  uno che era uscito);
* **cambiate** - erano gia' sopra soglia, ma e' cambiato qualcosa che vale un
  secondo messaggio: le regole sono poche e strette, e sono motivate sotto;
* **uscite** - non sono piu' sopra soglia. Servono ad aggiornare lo stato, non a
  notificare: nessuno vuole una vibrazione del telefono per dire che un titolo
  che non ha comprato e' scivolato di due punti.

Il confronto NON e' con il ciclo precedente ma con **l'ultimo valore
annunciato**: altrimenti una salita lenta di quattro punti per ciclo non
scatterebbe mai, pur avendo portato il punteggio da 84 a 96 in un giorno.

Niente qui solleva eccezioni verso il chiamante (OP-06): un file di stato
corrotto o un disco in sola lettura producono un avviso nel log e il ciclo
continua. Perdere la memoria di cosa e' stato annunciato costa al massimo un
messaggio ripetuto; fermare la scansione costa l'opportunita'.
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

STATO_PATH = Path(__file__).resolve().parent.parent / ".opportunita_viste.json"
VERSIONE = 1

# Soglia di punteggio: la stessa di notifications.SCORE_THRESHOLD (BR-06), ma
# ricopiata qui invece di importata perche' questo modulo deve poter girare da
# solo nei controlli automatici, senza tirarsi dietro il motore di scoring.
SOGLIA_PUNTEGGIO = 85

RIPOSO_ORE = 12             # due messaggi sullo stesso titolo non stanno piu' vicini di cosi'
SALTO_PUNTEGGIO = 6         # variazione minima di punteggio che vale un secondo messaggio
SALTO_PUNTEGGIO_GROSSO = 12  # variazione che rompe anche il periodo di riposo
GIORNI_OBLIO = 30           # dopo quanto si dimentica un titolo uscito e mai piu' visto

# Le fasce sono quelle di scoring.BANDS. Il rango serve solo a dire se il titolo
# e' salito o sceso di fascia: se l'etichetta arriva scritta in modo diverso da
# quello previsto, il rango viene ricalcolato dal punteggio e il confronto regge
# comunque.
FASCE = {
    "nessuna azione": 0,
    "da monitorare": 1,
    "opportunità forte": 2,
    "opportunita' forte": 2,
    "opportunita forte": 2,
    "opportunità eccezionale": 3,
    "opportunita' eccezionale": 3,
    "opportunita eccezionale": 3,
}
FASCIA_MASSIMA = 3


# --------------------------------------------------------------------- lettura
def _adesso(quando: datetime | None = None) -> datetime:
    """Tutto il modulo lavora in UTC: lo stato sopravvive a un cambio di ora
    legale e a un PC spostato di fuso senza che il periodo di riposo salti."""
    if isinstance(quando, datetime):
        return quando if quando.tzinfo else quando.replace(tzinfo=timezone.utc)
    return datetime.now(timezone.utc)


def _leggi_ora(testo) -> datetime | None:
    """Una data illeggibile nello stato vale come "non so quando": meglio un
    messaggio in piu' che un titolo zittito per sempre da una stringa sbagliata."""
    if not isinstance(testo, str) or not testo.strip():
        return None
    try:
        d = datetime.fromisoformat(testo.strip())
    except Exception:
        return None
    return d if d.tzinfo else d.replace(tzinfo=timezone.utc)


def _num(valore) -> float | None:
    """Numeri che possono arrivare come stringa (da un JSON scritto a mano)."""
    if isinstance(valore, bool) or valore is None:
        return None
    if isinstance(valore, (int, float)):
        return float(valore)
    if isinstance(valore, str):
        try:
            return float(valore.strip().replace(",", "."))
        except Exception:
            return None
    return None


def _primo(dato: dict, *chiavi):
    for k in chiavi:
        if k in dato and dato[k] is not None:
            return dato[k]
    return None


def _rango(classificazione, punteggio) -> int:
    etichetta = (classificazione or "").strip().lower()
    if etichetta in FASCE:
        return FASCE[etichetta]
    p = _num(punteggio) or 0
    return 3 if p >= 90 else 2 if p >= 80 else 1 if p >= 70 else 0


def normalizza(op: dict) -> dict | None:
    """Dalle opportunita' come le produce il motore al minimo che serve qui.

    Accetta sia i nomi inglesi che usa `notifications.build_notification`
    (`opportunity_score`, `classification`, `fair_value`, `plan.stop_loss`) sia i
    nomi italiani: cosi' chi collega la pipeline non deve tradurre nulla, e un
    rinomino a monte non rompe la memoria delle notifiche.
    """
    if not isinstance(op, dict):
        return None
    ticker = _primo(op, "ticker", "simbolo", "symbol")
    if not isinstance(ticker, str) or not ticker.strip():
        return None
    piano = op.get("plan") or op.get("piano") or {}
    if not isinstance(piano, dict):
        piano = {}
    punteggio = _num(_primo(op, "opportunity_score", "punteggio", "score"))
    valore = _num(_primo(op, "fair_value", "valore_stimato", "target_price", "target"))
    if valore is None:
        valore = _num(_primo(piano, "target", "target_price"))
    uscita = _num(_primo(op, "stop_loss", "uscita", "livello_uscita"))
    if uscita is None:
        uscita = _num(_primo(piano, "stop_loss", "uscita"))
    motivo = _primo(op, "motivo", "reason", "headline")
    if motivo is None:
        ragioni = _primo(op, "reasons", "ragioni") or []
        if isinstance(ragioni, (list, tuple)):
            motivo = "; ".join(str(r) for r in ragioni[:2])
    return {
        "ticker": ticker.strip(),
        "nome": str(_primo(op, "name", "nome") or ticker).strip(),
        "punteggio": int(round(punteggio)) if punteggio is not None else None,
        "classificazione": str(_primo(op, "classification", "classificazione") or "").strip(),
        "prezzo": _num(_primo(op, "price", "prezzo")),
        "valore": valore,
        "uscita": uscita,
        "valuta": str(_primo(op, "currency", "valuta") or "").strip(),
        "motivo_analisi": str(motivo or "").strip(),
    }


# ------------------------------------------------------------- stato su disco
def _stato_vuoto() -> dict:
    return {"versione": VERSIONE, "aggiornato": None, "titoli": {}}


def carica(path: Path | None = None) -> tuple[dict, list[str]]:
    """Restituisce (stato, avvisi). Un file mancante e' la normalita' al primo
    giro; un file corrotto si ricomincia da zero **dichiarandolo**, perche' il
    prossimo ciclo rimandera' le segnalazioni gia' viste e l'utente deve poter
    capire dal log perche' e' successo."""
    path = Path(path) if path else STATO_PATH
    if not path.exists():
        return _stato_vuoto(), []
    try:
        dati = json.loads(path.read_text(encoding="utf-8"))
    except Exception as e:
        return _stato_vuoto(), [f"{path.name} illeggibile ({type(e).__name__}: {e}): "
                                f"memoria delle notifiche azzerata, questo ciclo "
                                f"potrebbe ripetere segnalazioni già inviate"]
    if not isinstance(dati, dict) or not isinstance(dati.get("titoli"), dict):
        return _stato_vuoto(), [f"{path.name} non ha la forma attesa: memoria delle "
                                f"notifiche azzerata, questo ciclo potrebbe ripetere "
                                f"segnalazioni già inviate"]
    avvisi: list[str] = []
    titoli = {}
    for ticker, voce in dati["titoli"].items():
        # una singola voce rotta non deve far buttare tutto il resto della
        # memoria: si scarta quella e si tiene il resto
        if isinstance(ticker, str) and isinstance(voce, dict):
            titoli[ticker] = voce
        else:
            avvisi.append(f"voce di stato scartata perché malformata: {ticker!r}")
    versione = dati.get("versione")
    if versione != VERSIONE:
        avvisi.append(f"stato scritto da un'altra versione ({versione!r} invece di "
                      f"{VERSIONE}): le voci sconosciute vengono ignorate")
    return {"versione": VERSIONE, "aggiornato": dati.get("aggiornato"), "titoli": titoli}, avvisi


def salva(stato: dict, path: Path | None = None) -> tuple[bool, str]:
    """Scrittura con file temporaneo e sostituzione: se il processo muore a meta'
    scrittura, lo stato vecchio resta valido invece di diventare un JSON troncato
    che il ciclo dopo butterebbe via."""
    path = Path(path) if path else STATO_PATH
    tmp = path.with_suffix(path.suffix + ".tmp")
    try:
        tmp.write_text(json.dumps(stato, ensure_ascii=False, indent=2), encoding="utf-8")
        tmp.replace(path)
        return True, ""
    except Exception as e:
        try:
            tmp.unlink(missing_ok=True)
        except Exception:
            pass
        return False, (f"stato delle notifiche non salvato ({type(e).__name__}: {e}): "
                       f"il prossimo ciclo potrebbe ripetere le segnalazioni")


# ---------------------------------------------------------------- confronto
def _variazioni(op: dict, prec: dict) -> tuple[list[str], bool]:
    """Le regole che decidono se un titolo gia' annunciato merita un secondo
    messaggio. Restituisce (motivi, grosso).

    Sono quattro, e sono volutamente poche. Il criterio con cui le ho scelte:
    un secondo messaggio si manda solo se la **decisione** che l'utente puo'
    prendere e' cambiata, non se sono cambiati i numeri.

    1. **Salto di fascia verso l'alto** (per esempio da "forte" a
       "eccezionale"): e' il linguaggio con cui il prodotto parla all'utente,
       se cambia l'etichetta cambia il messaggio. Il salto verso il basso NON
       notifica: un peggioramento di un titolo che non si possiede non e' una
       cosa da leggere a schermo bloccato, e si vede comunque nelle card.
    2. **Punteggio salito di almeno 6 punti** rispetto a quello annunciato. Sei
       perche' la revisione del modello linguistico vale al massimo +/-10 punti
       su un singolo componente, che pesano per una frazione sul totale: sotto i
       sei punti il totale si muove per rumore (un giorno di prezzo, un
       arrotondamento), non per una notizia. **Solo in salita**, per coerenza
       con la regola 1: il punteggio che scende non fa partire niente. Questo
       prodotto manda notifiche di opportunita', non bollettini sullo stato di
       salute di cose che l'utente non ha comprato; l'unica cattiva notizia che
       vale una vibrazione e' la 4, dove il silenzio costa soldi.
    3. **Prezzo che ha raggiunto il valore stimato**: qui la segnalazione non e'
       piu' valida nel merito, perche' lo sconto che la giustificava e' finito.
       Vale un messaggio una volta sola, e lo stato lo ricorda.
    4. **Prezzo sceso sotto il livello di uscita**: la tesi si e' rotta. E'
       l'unico caso che conta davvero come urgente.

    `grosso` marca i cambiamenti che passano sopra il periodo di riposo: il
    livello di uscita superato (soldi a rischio adesso, non fra dodici ore),
    l'ingresso nella fascia massima e una salita di punteggio di almeno 12
    punti, che il modello da solo non puo' produrre e quindi arriva dai dati.
    """
    motivi: list[str] = []
    grosso = False

    p_ora, p_prima = op["punteggio"], prec.get("punteggio_annunciato")
    p_prima = _num(p_prima)
    r_ora = _rango(op["classificazione"], p_ora)
    r_prima = _rango(prec.get("classificazione_annunciata"), p_prima)

    if p_ora is not None and r_ora > r_prima:
        motivi.append(f"passa a «{op['classificazione'] or 'fascia superiore'}»"
                      + (f" con punteggio {p_ora}" if p_ora is not None else ""))
        if r_ora >= FASCIA_MASSIMA:
            # la fascia massima e' la ragione per cui il servizio esiste: quando
            # ci si entra il messaggio parte anche durante il riposo
            grosso = True

    if p_ora is not None and p_prima is not None:
        delta = p_ora - p_prima
        if delta >= SALTO_PUNTEGGIO and not motivi:
            motivi.append(f"punteggio da {int(round(p_prima))} a {p_ora} su 100")
        if delta >= SALTO_PUNTEGGIO_GROSSO:
            # dodici punti in salita il modello da solo non li puo' produrre:
            # arrivano dai dati, e allora non aspettano la fine del riposo
            grosso = True

    prezzo, valore, uscita = op["prezzo"], op["valore"], op["uscita"]
    if (prezzo is not None and valore is not None and prezzo >= valore
            and not prec.get("annunciato_target")):
        motivi.append("il prezzo ha raggiunto il valore stimato dal sistema")
    if (prezzo is not None and uscita is not None and prezzo <= uscita
            and not prec.get("annunciato_uscita")):
        motivi.append("il prezzo è sceso sotto il livello di uscita previsto")
        grosso = True

    return motivi, grosso


def confronta(opportunita, stato: dict | None = None, quando: datetime | None = None,
              riposo_ore: float = RIPOSO_ORE, soglia: int | None = None) -> dict:
    """Confronta l'elenco di questo ciclo con lo stato salvato.

    `soglia`, se passata, filtra qui le opportunita' sotto soglia: comoda per
    chi gli passa l'intero elenco analizzato invece dei soli candidati. Con
    `None` si fida di chi chiama (la pipeline filtra gia' a monte).
    """
    ora = _adesso(quando)
    stato = stato if isinstance(stato, dict) and isinstance(stato.get("titoli"), dict) \
        else _stato_vuoto()
    precedenti = stato["titoli"]
    titoli: dict[str, dict] = {}

    nuove, cambiate, rinviate, ignorate = [], [], [], []
    riposo = timedelta(hours=max(0.0, _num(riposo_ore) or 0.0))

    for grezza in (opportunita or []):
        op = normalizza(grezza)
        if op is None:
            ignorate.append(repr(grezza)[:80])
            continue
        if op["punteggio"] is None:
            ignorate.append(f"{op['ticker']} senza punteggio")
            continue
        if soglia is not None and op["punteggio"] <= soglia:
            continue

        prec = precedenti.get(op["ticker"])
        era_sopra = bool(prec and prec.get("sopra_soglia"))
        ultimo = _leggi_ora((prec or {}).get("ultimo_avviso"))

        if not era_sopra:
            tipo = "nuova"
            if prec is None:
                motivi = ["prima volta sopra la soglia di segnalazione"]
            else:
                motivi = ["torna sopra la soglia di segnalazione"]
            # un rientro non e' mai "grosso": il caso tipico e' un titolo che
            # oscilla attorno alla soglia, ed e' esattamente il rumore che il
            # periodo di riposo deve assorbire
            grosso = False
        else:
            tipo = "cambiata"
            motivi, grosso = _variazioni(op, prec)

        voce = {
            # `sopra_soglia` non vuol dire "supera la soglia": vuol dire "supera
            # la soglia **e l'utente lo sa**. La differenza conta quando un
            # messaggio viene rinviato per il periodo di riposo: se marcassimo
            # il titolo come annunciato, il rientro rinviato si perderebbe per
            # sempre (il ciclo dopo lo vedrebbe come un vecchio conosciuto senza
            # variazioni) e la notifica non arriverebbe mai piu'.
            "sopra_soglia": era_sopra,
            "punteggio": op["punteggio"],
            "classificazione": op["classificazione"],
            "prezzo": op["prezzo"],
            "valore": op["valore"],
            "uscita": op["uscita"],
            "visto": ora.isoformat(),
            "primo_avvistamento": (prec or {}).get("primo_avvistamento") or ora.isoformat(),
            "punteggio_annunciato": (prec or {}).get("punteggio_annunciato"),
            "classificazione_annunciata": (prec or {}).get("classificazione_annunciata"),
            "ultimo_avviso": (prec or {}).get("ultimo_avviso"),
            "avvisi": int(_num((prec or {}).get("avvisi")) or 0),
            "annunciato_target": bool((prec or {}).get("annunciato_target")),
            "annunciato_uscita": bool((prec or {}).get("annunciato_uscita")),
        }

        if not motivi:
            titoli[op["ticker"]] = voce
            continue

        in_riposo = bool(ultimo and (ora - ultimo) < riposo)
        if in_riposo and not grosso:
            restano = riposo - (ora - ultimo)
            rinviate.append({
                "ticker": op["ticker"],
                "motivo": "; ".join(motivi),
                "attesa_ore": round(restano.total_seconds() / 3600.0, 1),
            })
            # i valori correnti si salvano, ma `punteggio_annunciato` resta
            # quello che l'utente ha letto: cosi' la variazione si accumula e
            # scatta appena finito il riposo, invece di sparire
            titoli[op["ticker"]] = voce
            continue

        voce["sopra_soglia"] = True
        voce["punteggio_annunciato"] = op["punteggio"]
        voce["classificazione_annunciata"] = op["classificazione"]
        voce["ultimo_avviso"] = ora.isoformat()
        voce["avvisi"] += 1
        if op["prezzo"] is not None and op["valore"] is not None \
                and op["prezzo"] >= op["valore"]:
            voce["annunciato_target"] = True
        if op["prezzo"] is not None and op["uscita"] is not None \
                and op["prezzo"] <= op["uscita"]:
            voce["annunciato_uscita"] = True
        titoli[op["ticker"]] = voce

        avviso = dict(op)
        avviso["tipo"] = tipo
        avviso["motivo"] = "; ".join(motivi)
        avviso["urgente"] = grosso
        (nuove if tipo == "nuova" else cambiate).append(avviso)

    # chi non e' nell'elenco di questo ciclo e prima era sopra soglia: uscito.
    uscite = []
    for ticker, prec in precedenti.items():
        if ticker in titoli:
            continue
        voce = dict(prec)
        if prec.get("sopra_soglia"):
            uscite.append(ticker)
            voce["sopra_soglia"] = False
            voce["uscito"] = ora.isoformat()
            # se rientrera', sara' un'altra storia: i due promemoria "target
            # raggiunto" e "uscita toccata" valgono per la segnalazione che si
            # e' appena chiusa, non per la prossima
            voce["annunciato_target"] = False
            voce["annunciato_uscita"] = False
        visto = _leggi_ora(prec.get("visto")) or _leggi_ora(prec.get("uscito"))
        if visto and (ora - visto) > timedelta(days=GIORNI_OBLIO):
            # un titolo uscito e mai piu' visto da un mese si dimentica: il file
            # di stato non deve crescere per sempre, e dopo un mese un messaggio
            # ripetuto non e' piu' una ripetizione
            continue
        titoli[ticker] = voce

    stato_nuovo = {"versione": VERSIONE, "aggiornato": ora.isoformat(), "titoli": titoli}
    return {
        "nuove": sorted(nuove, key=lambda a: -(a["punteggio"] or 0)),
        "cambiate": sorted(cambiate, key=lambda a: -(a["punteggio"] or 0)),
        "uscite": sorted(uscite),
        "rinviate": sorted(rinviate, key=lambda r: r["ticker"]),
        "ignorate": ignorate,
        "stato": stato_nuovo,
        "quando": ora.isoformat(),
    }


def novita(opportunita, path: Path | None = None, quando: datetime | None = None,
           riposo_ore: float = RIPOSO_ORE, soglia: int | None = None,
           scrivi: bool = True) -> dict:
    """Il giro completo: legge lo stato, confronta, riscrive lo stato.

    E' l'unica funzione che serve a chi collega il ciclo. Non solleva mai:
    qualunque imprevisto diventa un avviso nel log e un elenco di novita' vuoto,
    perche' una notifica mancata e' un danno piccolo e una scansione interrotta
    e' un danno grande (OP-06).

    `scrivi=False` serve a vedere che cosa partirebbe senza consumare lo stato,
    e ai controlli automatici.
    """
    avvisi: list[str] = []
    try:
        stato, avvisi_lettura = carica(path)
        avvisi += avvisi_lettura
        esito = confronta(opportunita, stato, quando=quando,
                          riposo_ore=riposo_ore, soglia=soglia)
        if scrivi:
            ok, errore = salva(esito["stato"], path)
            if not ok:
                avvisi.append(errore)
            esito["salvato"] = ok
        else:
            esito["salvato"] = False
        for t in esito["ignorate"]:
            avvisi.append(f"opportunità ignorata perché incompleta: {t}")
        esito["avvisi"] = avvisi
        return esito
    except Exception as e:
        return {"nuove": [], "cambiate": [], "uscite": [], "rinviate": [], "ignorate": [],
                "stato": _stato_vuoto(), "salvato": False,
                "quando": _adesso(quando).isoformat(),
                "avvisi": avvisi + [f"confronto con le opportunità già viste non "
                                    f"eseguito ({type(e).__name__}: {e}): questo ciclo "
                                    f"non manda notifiche, i calcoli restano validi"]}


def riassunto(esito: dict) -> str:
    """Una riga per il log del ciclo, nello stile delle altre righe di pipeline."""
    return (f"novità: {len(esito.get('nuove') or [])} nuove, "
            f"{len(esito.get('cambiate') or [])} aggiornate, "
            f"{len(esito.get('rinviate') or [])} rinviate per riposo, "
            f"{len(esito.get('uscite') or [])} uscite dalla soglia")
