"""Gli identificativi di uno strumento: ISIN, FIGI, denominazione, borsa.

Le card delle opportunita' devono dire **quale** strumento comprare, non solo che
e' una buona idea. Settore, tipologia e prezzo obiettivo il motore li ha gia'
(stanno negli asset e nel piano operativo); quello che manca e' l'identita'
anagrafica, cioe' i codici con cui si cerca il titolo nella piattaforma della
banca. Questo modulo la procura.

CHE COSA SI PUO' AVERE GRATIS, e che cosa no. Verificato da questa rete:

* **FIGI** (Financial Instrument Global Identifier) da OpenFIGI, l'anagrafica
  aperta di Bloomberg: nessuna chiave, nessuna registrazione. Da' il codice FIGI
  della singola quotazione, il FIGI composito, il FIGI della classe di azioni, la
  **denominazione ufficiale** dell'emittente, il **tipo di strumento**
  (`Common Stock`, `ETP`, `REIT`, `Crypto`...), il **settore di mercato**
  (`Equity`, `Curncy`, `Comdty`) e la **borsa**.
* **ISIN**: OpenFIGI mappa *verso* il FIGI, non verso l'ISIN, e nessuna fonte
  gratuita trovata lo pubblica. L'ISIN quindi **non arriva dalla rete**: lo
  scrive a mano l'utente in `isin.json`, e il programma lo controlla.

VINCOLO MORALE, ed e' il motivo per cui questo modulo e' fatto cosi'. Un ISIN
sbagliato non produce un errore: produce un ordine eseguito sullo strumento
sbagliato, con i soldi veri di chi ci ha creduto. Percio' qui dentro **nessun
ISIN viene inventato, dedotto, ricostruito dal prefisso del paese o indovinato
per somiglianza**. Se non c'e', non c'e', e la card scrive "non disponibile".
Quelli che l'utente scrive passano due controlli:

1. la cifra di controllo della ISO 6166 (algoritmo di Luhn sulla stringa
   espansa): rifiuta gli errori di battitura, che sono il caso frequente. Misurato
   su dieci ISIN veri: **846 cifre sbagliate su 846 vengono respinte**, tutte,
   che e' la garanzia di Luhn; ma su 3150 alterazioni che coinvolgono una lettera
   ne passano 239 (7,6%), e su 69 scambi di due caratteri vicini ne passano 5. Non
   e' un difetto dell'implementazione, e' la norma: una lettera vale due cifre
   nella stringa espansa, e Luhn garantisce solo l'errore di una cifra sola. Per
   quel 7% serve il secondo controllo;
2. il riscontro con OpenFIGI: l'ISIN scritto viene mappato verso i suoi FIGI e si
   verifica che fra le sue quotazioni ci sia proprio quella che il motore prezza.
   Questo intercetta l'errore pericoloso, cioe' l'ISIN formalmente perfetto ma di
   un altro strumento. Se non concordano, l'ISIN viene **rifiutato** e il motivo
   dice entrambi i nomi, cosi' si vede subito chi dei due e' sbagliato.

LIMITI DI OPENFIGI dichiarati dal servizio e confermati sulle sue risposte:
`ratelimit-policy: 25;w=60`, cioe' 25 richieste al minuto senza chiave, e
**massimo 10 strumenti per richiesta** (con 11 risponde `HTTP 413 "Request may
only contain 10 mapping jobs."`). Qui le richieste sono raggruppate a dieci, la
pausa fra due e' prudenziale e molto sopra il minimo, e gli header del limite
vengono letti a ogni risposta: se il contatore sta per esaurirsi si aspetta la
finestra invece di farsi respingere. Esiste anche una chiave gratuita che alza i
limiti: non e' usata, perche' non ho potuto provarla e un percorso non provato
non va nel ciclo automatico.

CACHE PERMANENTE. Il FIGI di Microsoft non cambia mai: la denominazione, il tipo
e la borsa di uno strumento non sono dati di mercato. Il ciclo gira ogni due ore,
dodici volte al giorno: rifare la stessa domanda a OpenFIGI dodici volte al
giorno per avere la stessa risposta sarebbe maleducato verso un servizio che
regala i dati. Quindi un file solo (`.identificativi.json`), scritto una volta e
riletto sempre, con dentro la data in cui ogni voce e' stata scritta. I **buchi**
invece non sono per sempre: una voce non trovata si riprova dopo una settimana,
perche' potrebbe essere stata la rete, non lo strumento.

Niente qui solleva eccezioni verso il chiamante (OP-06): una fonte che non
risponde produce `trovato: False` con il motivo scritto nel registro, e la
scansione va avanti. Un'opportunita' senza ISIN resta un'opportunita'; una
scansione fermata da un'anagrafica e' un'opportunita' persa.

    python tools/selftest_identificativi.py     # i controlli, senza rete
"""

from __future__ import annotations

import json
import re
import ssl
import time
import urllib.error
import urllib.request
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

RADICE = Path(__file__).resolve().parent.parent
CACHE_PATH = RADICE / ".identificativi.json"
ISIN_PATH = RADICE / "isin.json"
VERSIONE = 1

URL_MAPPING = "https://api.openfigi.com/v3/mapping"
TIMEOUT_S = 30

# Massimo di strumenti per richiesta: dichiarato da OpenFIGI e verificato
# (con 11 risponde 413 "Request may only contain 10 mapping jobs.").
MAX_JOB = 10
# Limite di frequenza letto dall'header `ratelimit-policy: 25;w=60`.
LIMITE_RICHIESTE, LIMITE_FINESTRA_S = 25, 60
# La media consentita sarebbe una richiesta ogni 2,4 secondi. Stiamo sopra: una
# scansione non ha nessuna fretta, e con la cache permanente queste richieste si
# fanno una volta sola nella vita del programma.
PAUSA_S = 3.0
MAX_TENTATIVI = 2
ATTESA_429_S = 20.0
# Limite di buon senso sulla ricerca senza borsa: la difesa vera contro gli
# omonimi e' l'unanimita' del nome e della classe di azioni (vedi `_senza_borsa`),
# questo numero serve solo a non fidarsi di una risposta smisurata.
MAX_QUOTAZIONI_AMMESSE = 400
GIORNI_RIPROVA = 7          # dopo quanto si riprova una voce non trovata

FONTE_FIGI = "OpenFIGI (api.openfigi.com/v3/mapping)"
FONTE_ISIN = "isin.json, compilato a mano e verificato"
FONTE_SCHEDA = "scheda interna del progetto"
FONTE_MOTORE = "stima del motore (non un obiettivo di analisti)"
NON_DISPONIBILE = "non disponibile"

# --------------------------------------------------------- da Yahoo a OpenFIGI
# Yahoo identifica la borsa con un suffisso sul ticker, OpenFIGI con il codice a
# due lettere della convenzione Bloomberg. Le corrispondenze marcate "verificata"
# le ho provate su questa rete; le altre sono la convenzione nota e, se sbagliano,
# il ripiego senza borsa (vedi `_pass3`) recupera comunque lo strumento e lo
# dichiara. Nessuna di queste righe puo' produrre un dato sbagliato in silenzio:
# il nome che torna da OpenFIGI viene mostrato accanto al nostro.
BORSE = {
    "": "US",            # verificata (NVDA, MSFT, SPY, QQQ, EMB, TSM)
    ".AS": "NA",         # verificata (ASML.AS, IEAC.AS)
    ".DE": "GY",         # verificata (SAP.DE, SIE.DE, VNA.DE)
    ".CO": "DC",         # verificata (NOVO-B.CO)
    ".PA": "FP",         # verificata (MC.PA, AIR.PA)
    ".MI": "IM",         # verificata (ENEL.MI, ISP.MI, STLAM.MI)
    ".T": "JT",          # verificata (7203.T, 9984.T)
    ".KS": "KS",         # verificata (005930.KS)
    ".HK": "HK",         # verificata (0823.HK)
    ".L": "LN",
    ".SW": "SW",
    ".MC": "SM",
    ".BR": "BB",
    ".LS": "PL",
    ".VI": "AV",
    ".ST": "SS",
    ".HE": "FH",
    ".OL": "NO",
    ".IR": "ID",
    ".TO": "CT",
    ".AX": "AU",
    ".NZ": "NZ",
    ".TW": "TT",
    ".SA": "BZ",
    ".MX": "MM",
}

# Le cripto non stanno su una borsa: OpenFIGI le tiene nel settore `Curncy` e le
# cerca col ticker nudo (BTC, ETH, SOL, LINK: verificate, tornano
# `securityType: Crypto`). Le sigle di Yahoo con il trattino e la valuta
# (`BTC-USD`) non esistono per OpenFIGI.
SETTORE_CRIPTO = "Curncy"
# I future continui di Yahoo (`GC=F`) corrispondono al future generico di prima
# scadenza della convenzione Bloomberg (`GC1 Comdty`): e' la stessa cosa che
# Yahoo prezza, cioe' il contratto piu' vicino. La corrispondenza e' per
# convenzione, non un dato restituito: viene scritta nelle note della voce.
SETTORE_MATERIE = "Comdty"


# ============================================================ cifra di controllo
RE_ISIN = re.compile(r"^[A-Z]{2}[A-Z0-9]{9}[0-9]$")


def normalizza_isin(testo) -> str:
    """Toglie spazi, trattini e minuscole. Non e' indovinare: e' leggere quello
    che l'utente ha scritto, che a volte copia l'ISIN spezzato in gruppi."""
    if not isinstance(testo, str):
        return ""
    return testo.strip().upper().replace(" ", "").replace("-", "").replace(".", "")


def cifra_controllo_isin(corpo: str) -> str | None:
    """La cifra di controllo prevista dalla ISO 6166 per i primi undici caratteri.

    Due passaggi: ogni lettera diventa il suo valore a due cifre (A=10 ... Z=35),
    poi sulla stringa cosi' espansa si applica l'algoritmo di Luhn.

    Il punto in cui tutti sbagliano e' la parita': il raddoppio parte dall'ultima
    cifra della stringa **espansa**, non dall'ultimo carattere dell'ISIN. Una
    lettera vale due cifre e sposta la parita' di tutto quello che le sta a
    sinistra, quindi contare sui caratteri dell'ISIN da' il risultato giusto solo
    per caso. Restituisce `None` se il corpo non e' undici caratteri alfanumerici:
    chi chiama se ne accorge, nessuno riceve un'eccezione.

    Quello che questo controllo NON garantisce: Luhn prende ogni errore di una
    cifra (846 su 846, misurato), ma una lettera sbagliata cambia due cifre e puo'
    sfuggire (239 casi su 3150). Chi vuole essere sicuro deve passare dal
    riscontro con OpenFIGI, che e' il motivo per cui quel riscontro esiste.
    """
    if not isinstance(corpo, str) or len(corpo) != 11:
        return None
    cifre: list[int] = []
    for c in corpo.upper():
        if c.isdigit():
            cifre.append(int(c))
        elif "A" <= c <= "Z":
            valore = ord(c) - 55          # A -> 10, Z -> 35
            cifre.append(valore // 10)
            cifre.append(valore % 10)
        else:
            return None
    somma = 0
    for i, d in enumerate(reversed(cifre)):
        if i % 2 == 0:                    # la prima da destra si raddoppia
            d *= 2
            if d > 9:
                d -= 9                    # equivale a sommare le due cifre
        somma += d
    return str((10 - somma % 10) % 10)


def valida_isin(testo) -> dict:
    """Esito del controllo su un ISIN scritto a mano.

    Restituisce `{"isin", "valido", "motivo", "vuoto"}`. Il motivo e' scritto per
    essere letto da chi ha compilato il file: dice quale dei controlli non e'
    passato e, sulla cifra di controllo, dice anche quale sarebbe quella giusta,
    perche' nove volte su dieci l'errore e' una cifra storta in mezzo al codice e
    non la cifra finale.
    """
    isin = normalizza_isin(testo)
    if not isin:
        return {"isin": None, "valido": False, "vuoto": True,
                "motivo": "casella vuota: ISIN da compilare"}
    if len(isin) != 12:
        return {"isin": isin, "valido": False, "vuoto": False,
                "motivo": f"un ISIN ha 12 caratteri, questo ne ha {len(isin)}"}
    if not RE_ISIN.match(isin):
        return {"isin": isin, "valido": False, "vuoto": False,
                "motivo": "formato non valido: servono 2 lettere di paese, "
                          "9 caratteri alfanumerici e 1 cifra finale"}
    attesa = cifra_controllo_isin(isin[:11])
    if attesa is None:
        return {"isin": isin, "valido": False, "vuoto": False,
                "motivo": "corpo del codice non interpretabile"}
    if attesa != isin[11]:
        return {"isin": isin, "valido": False, "vuoto": False,
                "motivo": f"cifra di controllo errata: finisce con {isin[11]} ma la "
                          f"ISO 6166 richiede {attesa} (c'è un carattere sbagliato "
                          f"nel codice, non necessariamente l'ultimo)"}
    return {"isin": isin, "valido": True, "vuoto": False, "motivo": ""}


# ================================================================== isin.json
NOTE_ISIN = [
    "Scrivi l'ISIN accanto al suo ticker. Lascia \"\" quello che non hai.",
    "L'ISIN si trova sul documento informativo dello strumento (KID per gli ETF), "
    "sul sito dell'emittente o nella scheda del titolo nella tua banca.",
    "Il programma NON inventa ISIN: quello che non scrivi qui resta "
    "\"non disponibile\" sulla card.",
    "Ogni ISIN viene controllato due volte: la cifra di controllo (ISO 6166) e il "
    "riscontro con OpenFIGI, che verifica che il codice sia di QUESTO strumento.",
    "Un ISIN rifiutato non viene usato e il motivo compare nel registro del ciclo.",
    "Le cripto e i future non hanno ISIN: lasciali vuoti.",
]


def leggi_isin(path: Path | None = None) -> tuple[dict[str, dict], list[str]]:
    """Legge `isin.json` e valida tutto quello che c'e' dentro.

    Restituisce `(voci, problemi)`. In `voci` sta un esito per ogni ticker
    presente nel file, valido o no, perche' la card deve poter distinguere "ISIN
    non compilato" da "ISIN compilato male e rifiutato": sono due messaggi diversi
    per l'utente. In `problemi` ci sono solo gli errori veri, pronti da stampare.
    Un file mancante non e' un errore: e' la condizione iniziale.
    """
    path = Path(path) if path else ISIN_PATH
    if not path.exists():
        return {}, []
    try:
        dati = json.loads(path.read_text(encoding="utf-8"))
    except Exception as e:
        return {}, [f"{path.name} non è un JSON valido ({type(e).__name__}: {e}): "
                    f"nessun ISIN caricato, le card diranno \"non disponibile\""]
    if not isinstance(dati, dict):
        return {}, [f"{path.name} deve essere un oggetto JSON "
                    f"nella forma {{\"NVDA\": \"US67066G1040\"}}"]

    voci: dict[str, dict] = {}
    problemi: list[str] = []
    for ticker, valore in dati.items():
        if not isinstance(ticker, str) or ticker.startswith("_"):
            continue                      # le note del modello non sono strumenti
        if isinstance(valore, dict):      # tollera {"isin": "..."} oltre alla stringa
            valore = valore.get("isin")
        if valore is not None and not isinstance(valore, str):
            problemi.append(f"{ticker}: il valore deve essere una stringa, "
                            f"non {type(valore).__name__}")
            voci[ticker] = {"isin": None, "valido": False, "vuoto": False,
                            "motivo": "valore non testuale nel file"}
            continue
        esito = valida_isin(valore)
        voci[ticker] = esito
        if not esito["valido"] and not esito["vuoto"]:
            problemi.append(f"{ticker}: ISIN rifiutato ({esito['isin']}) - {esito['motivo']}")
    return voci, problemi


def ticker_universo() -> list[str]:
    """I ticker dell'universo del progetto, per generare il modello.

    L'import sta qui dentro e non in testa al modulo di proposito: `real_universe`
    si tira dietro provider, indicatori e valutazione, e questo modulo deve poter
    girare da solo nei controlli automatici senza caricare mezzo motore.
    """
    try:
        from .real_universe import REAL_SPECS
        return [s[0] for s in REAL_SPECS]
    except Exception:
        return []


def scrivi_modello_isin(tickers: list[str] | None = None,
                        path: Path | None = None) -> tuple[Path | None, str, dict]:
    """Crea (o completa) `isin.json` con tutti i ticker e il valore vuoto.

    Non sovrascrive mai un ISIN gia' scritto: un rigenera-il-file che cancella il
    lavoro a mano di chi ha cercato trenta codici uno per uno e' un danno, non un
    comodo. Aggiunge i ticker che mancano, tiene quelli in piu' (uno strumento
    puo' essere stato toccato dalla watchlist) e lascia tutto il resto dov'era.

    Restituisce `(percorso, messaggio, riepilogo)`; a percorso `None` corrisponde
    un messaggio che dice perche' non si e' potuto scrivere.
    """
    path = Path(path) if path else ISIN_PATH
    elenco = [t for t in (tickers or ticker_universo()) if isinstance(t, str) and t.strip()]
    if not elenco:
        return None, ("non so quali ticker mettere nel modello: l'universo del "
                      "progetto non è leggibile e non me ne sono stati passati"), {}

    esistenti: dict[str, str] = {}
    if path.exists():
        voci, _ = leggi_isin(path)
        for ticker, esito in voci.items():
            # si conserva anche quello rifiutato: e' il lavoro dell'utente, e il
            # motivo del rifiuto glielo diciamo altrove. Cancellarglielo lo
            # costringerebbe a cercarlo di nuovo per scoprire lo stesso errore.
            esistenti[ticker] = esito["isin"] or ""

    contenuto: dict[str, object] = {}
    aggiunti = []
    for ticker in elenco:
        contenuto[ticker] = esistenti.get(ticker, "")
        if ticker not in esistenti:
            aggiunti.append(ticker)
    conservati = [t for t in esistenti if t not in contenuto]
    for ticker in conservati:
        contenuto[ticker] = esistenti[ticker]
    contenuto["_note"] = list(NOTE_ISIN)

    tmp = path.with_suffix(path.suffix + ".tmp")
    try:
        tmp.write_text(json.dumps(contenuto, ensure_ascii=False, indent=2),
                       encoding="utf-8")
        tmp.replace(path)
    except Exception as e:
        try:
            tmp.unlink(missing_ok=True)
        except Exception:
            pass
        return None, f"{path.name} non scritto ({type(e).__name__}: {e})", {}

    compilati = sum(1 for t in elenco if esistenti.get(t))
    riepilogo = {"ticker": len(elenco), "compilati": compilati,
                 "da_compilare": len(elenco) - compilati,
                 "aggiunti": aggiunti, "conservati": conservati}
    return path, (f"{path.name}: {len(elenco)} ticker, {compilati} già compilati, "
                  f"{len(elenco) - compilati} da compilare"), riepilogo


# ============================================================== cache su disco
def _oggi() -> str:
    return date.today().isoformat()


def _cache_vuota() -> dict:
    return {"versione": VERSIONE, "aggiornato": None, "strumenti": {}, "isin_verificati": {}}


def carica_cache(path: Path | None = None) -> tuple[dict, list[str]]:
    """Legge la cache permanente. Un file illeggibile non e' un guaio: si
    ricomincia a chiedere a OpenFIGI, dichiarandolo."""
    path = Path(path) if path else CACHE_PATH
    if not path.exists():
        return _cache_vuota(), []
    try:
        dati = json.loads(path.read_text(encoding="utf-8"))
    except Exception as e:
        return _cache_vuota(), [f"{path.name} illeggibile ({type(e).__name__}: {e}): "
                                f"gli identificativi verranno richiesti di nuovo"]
    if not isinstance(dati, dict) or not isinstance(dati.get("strumenti"), dict):
        return _cache_vuota(), [f"{path.name} non ha la forma attesa: "
                                f"gli identificativi verranno richiesti di nuovo"]
    avvisi: list[str] = []
    if dati.get("versione") != VERSIONE:
        avvisi.append(f"cache degli identificativi scritta da un'altra versione "
                      f"({dati.get('versione')!r} invece di {VERSIONE})")
    strumenti = {k: v for k, v in dati["strumenti"].items()
                 if isinstance(k, str) and isinstance(v, dict)}
    verificati = dati.get("isin_verificati")
    if not isinstance(verificati, dict):
        verificati = {}
    return {"versione": VERSIONE, "aggiornato": dati.get("aggiornato"),
            "strumenti": strumenti,
            "isin_verificati": {k: v for k, v in verificati.items()
                                if isinstance(k, str) and isinstance(v, dict)}}, avvisi


def salva_cache(cache: dict, path: Path | None = None) -> tuple[bool, str]:
    """Scrittura con file temporaneo e sostituzione: un processo interrotto a
    meta' lascia la cache vecchia valida invece di un JSON troncato."""
    path = Path(path) if path else CACHE_PATH
    cache = dict(cache)
    cache["versione"] = VERSIONE
    cache["aggiornato"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
    tmp = path.with_suffix(path.suffix + ".tmp")
    try:
        tmp.write_text(json.dumps(cache, ensure_ascii=False, indent=2), encoding="utf-8")
        tmp.replace(path)
        return True, ""
    except Exception as e:
        try:
            tmp.unlink(missing_ok=True)
        except Exception:
            pass
        return False, (f"cache degli identificativi non salvata "
                       f"({type(e).__name__}: {e}): il prossimo ciclo rifarà le richieste")


def _scaduta(voce: dict) -> bool:
    """Una voce trovata non scade mai: il FIGI di Microsoft e' lo stesso di dieci
    anni fa. Una voce NON trovata scade dopo una settimana, perche' il buco puo'
    essere stato un problema di rete e non una proprieta' dello strumento."""
    if voce.get("trovato"):
        return False
    scritto = voce.get("scritto_il")
    if not isinstance(scritto, str):
        return True
    try:
        quando = date.fromisoformat(scritto[:10])
    except Exception:
        return True
    return quando + timedelta(days=GIORNI_RIPROVA) <= date.today()


# ========================================================= le richieste a OpenFIGI
def pezzi_ticker(ticker: str) -> tuple[str, str]:
    """Separa il corpo del ticker dal suffisso di borsa di Yahoo."""
    t = (ticker or "").strip().upper()
    if "." in t:
        corpo, _, suff = t.rpartition(".")
        return corpo, "." + suff
    return t, ""


def job_per_ticker(ticker: str) -> list[dict]:
    """Le richieste da provare per un ticker, in ordine di fiducia.

    La prima e' quella giusta nella convenzione nota; le altre sono le varianti di
    scrittura su cui si inciampa davvero (il trattino che Yahoo mette e Bloomberg
    no, lo zero di riempimento dei codici di Hong Kong). Si provano solo se la
    prima non trova niente, e si fermano appena una risponde: nessuna variante
    puo' "correggere" un risultato gia' ottenuto.
    """
    t = (ticker or "").strip().upper()
    if not t:
        return []
    corpo, suff = pezzi_ticker(t)

    # cripto: `BTC-USD` -> ticker nudo nel settore valute (verificato)
    if t.endswith("-USD") or t.endswith("-EUR"):
        base = t.rsplit("-", 1)[0]
        return [{"idType": "TICKER", "idValue": base, "marketSecDes": SETTORE_CRIPTO}]

    # future continui: `GC=F` -> `GC1 Comdty`, il generico di prima scadenza
    if t.endswith("=F"):
        base = t[:-2]
        return [{"idType": "TICKER", "idValue": base + "1", "marketSecDes": SETTORE_MATERIE},
                {"idType": "TICKER", "idValue": base, "marketSecDes": SETTORE_MATERIE}]

    borsa = BORSE.get(suff)
    if borsa is None:
        # suffisso che non conosco: non invento un codice di borsa, cerco senza
        return [{"idType": "TICKER", "idValue": corpo}]

    varianti = [corpo]
    if "-" in corpo:
        # NOVO-B.CO -> NOVOB e BRK-B -> BRK/B: entrambe verificate su questa rete.
        # Fuori dagli Stati Uniti il trattino di Yahoo semplicemente non esiste,
        # negli Stati Uniti la classe di azioni si scrive con la barra. Si provano
        # in quest'ordine e la prima che risponde chiude la partita.
        varianti.append(corpo.replace("-", ""))
        varianti.append(corpo.replace("-", "/"))
    if suff == ".HK" and corpo.lstrip("0") != corpo:
        # Yahoo riempie di zeri a quattro cifre (0823), OpenFIGI no (823)
        varianti.insert(0, corpo.lstrip("0") or corpo)
    fuori = []
    for v in varianti:
        if v and v not in fuori:
            fuori.append(v)
    return [{"idType": "TICKER", "idValue": v, "exchCode": borsa} for v in fuori]


def _voce_da_risposta(job: dict, dati: list[dict], nota: str = "") -> dict:
    """Dalla risposta di OpenFIGI alla voce di cache. Prende la prima quotazione
    (quando si e' chiesta una borsa precisa ce n'e' una sola) e porta con se'
    quante ne ha trovate, perche' "una" e "quarantotto" vanno lette in modo
    diverso da chi guarda il dato."""
    primo = dati[0] if dati else {}
    classi = {d.get("shareClassFIGI") for d in dati if d.get("shareClassFIGI")}
    return {
        "trovato": True,
        "figi": primo.get("figi"),
        "figi_composito": primo.get("compositeFIGI"),
        # se tutte le quotazioni condividono la classe di azioni, quella classe e'
        # l'identita' piu' solida che abbiamo: e' il livello a cui corrisponde
        # l'ISIN, e non dipende da quale borsa si guarda
        "figi_classe": primo.get("shareClassFIGI") if len(classi) <= 1 else None,
        "nome": primo.get("name"),
        "tipo": primo.get("securityType"),
        "tipo_dettaglio": primo.get("securityType2"),
        "settore_mercato": primo.get("marketSector"),
        "borsa": primo.get("exchCode"),
        "ticker_borsa": primo.get("ticker"),
        "quotazioni": len(dati),
        "nota": nota,
        "motivo": "",
        "richiesta": job,
        "fonte": FONTE_FIGI,
        "scritto_il": _oggi(),
    }


def _voce_mancante(motivo: str, job: dict | None = None) -> dict:
    return {"trovato": False, "figi": None, "figi_composito": None, "figi_classe": None,
            "nome": None, "tipo": None, "tipo_dettaglio": None, "settore_mercato": None,
            "borsa": None, "ticker_borsa": None, "quotazioni": 0, "nota": "",
            "motivo": motivo, "richiesta": job, "fonte": FONTE_FIGI,
            "scritto_il": _oggi()}


class OpenFigi:
    """Client minimale su OpenFIGI: niente chiave, niente dipendenze, cache
    permanente, richieste raggruppate e limite di frequenza rispettato.

    Nessun metodo solleva eccezioni: chi non si e' potuto leggere torna come
    `trovato: False` con il motivo, e il registro (`self.log`) dice che cosa e'
    stato chiesto e come e' andata.
    """

    def __init__(self, usa_cache: bool = True, pausa_s: float = PAUSA_S,
                 cache_path: Path | None = None, usa_rete: bool = True):
        self.usa_cache = usa_cache
        self.pausa_s = pausa_s
        self.usa_rete = usa_rete
        self.cache_path = Path(cache_path) if cache_path else CACHE_PATH
        self.cache, self.avvisi = (carica_cache(self.cache_path) if usa_cache
                                   else (_cache_vuota(), []))
        self.stats = {"http": 0, "cache": 0, "errori": 0, "byte": 0,
                      "job": 0, "attese": 0}
        self.log: list[dict] = []
        self.ultimo_errore: str | None = None
        self._ultima = 0.0
        self._restanti: int | None = None
        self._reset_s: int | None = None
        self._modificata = False

    # ------------------------------------------------------------------ rete
    def _aspetta(self) -> None:
        """La pausa fra due richieste, piu' l'attesa della finestra quando il
        contatore del servizio e' agli sgoccioli. Farsi respingere con un 429 e
        poi riprovare costa piu' tempo che aspettare."""
        if self._restanti is not None and self._restanti <= 1:
            # `_reset_s` puo' valere zero (finestra che sta girando proprio ora) e
            # zero non e' "non lo so": col solito `or` si finirebbe ad aspettare un
            # minuto intero per un secondo di attesa necessaria
            resto = self._reset_s if self._reset_s is not None else LIMITE_FINESTRA_S
            attesa = min(float(resto) + 1.0, LIMITE_FINESTRA_S + 1.0)
            self.stats["attese"] += 1
            self.log.append({"evento": "attesa_finestra", "secondi": round(attesa, 1)})
            time.sleep(attesa)
            self._restanti = None
            self._ultima = time.monotonic()
            return
        resta = self.pausa_s - (time.monotonic() - self._ultima)
        if resta > 0:
            time.sleep(resta)

    def _leggi_limiti(self, headers) -> None:
        """Gli header del limite di frequenza, se ci sono. OpenFIGI manda
        `ratelimit-limit`, `ratelimit-remaining` e `ratelimit-reset`: leggerli
        evita di scoprire il limite sbattendoci contro."""
        def intero(nome):
            try:
                return int(str(headers.get(nome)).strip())
            except Exception:
                return None
        self._restanti = intero("ratelimit-remaining")
        self._reset_s = intero("ratelimit-reset")

    def _chiama(self, job: list[dict]) -> tuple[list | None, str]:
        """Una richiesta di mappatura. Restituisce `(risposta, motivo)`: a
        risposta `None` corrisponde sempre un motivo scritto, mai un'eccezione.

        Attenzione alla differenza fra i due modi di non trovare niente: qui si
        gestisce la richiesta che NON E' ARRIVATA (rete, 429, 500), che non dice
        nulla sugli strumenti; il singolo strumento sconosciuto arriva invece
        dentro una risposta riuscita, come `warning`, e lo legge `identita`.
        """
        if not job:
            return [], ""
        if len(job) > MAX_JOB:
            return None, (f"richiesta non inviata: {len(job)} strumenti, il massimo "
                          f"senza chiave è {MAX_JOB}")
        if not self.usa_rete:
            return None, "rete non richiesta (usa_rete=False)"
        corpo = json.dumps(job).encode("utf-8")
        for tentativo in range(1, MAX_TENTATIVI + 1):
            self._aspetta()
            try:
                req = urllib.request.Request(
                    URL_MAPPING, data=corpo, method="POST",
                    headers={"Content-Type": "application/json",
                             "Accept": "application/json"})
                with urllib.request.urlopen(req, timeout=TIMEOUT_S,
                                            context=ssl.create_default_context()) as r:
                    raw = r.read()
                    self._leggi_limiti(getattr(r, "headers", {}) or {})
                self._ultima = time.monotonic()
                self.stats["http"] += 1
                self.stats["byte"] += len(raw)
                self.stats["job"] += len(job)
                risposta = json.loads(raw)
                if not isinstance(risposta, list) or len(risposta) != len(job):
                    self.stats["errori"] += 1
                    motivo = (f"risposta inattesa da OpenFIGI: {len(job)} strumenti "
                              f"chiesti, {type(risposta).__name__} ricevuto")
                    self.ultimo_errore = motivo
                    self.log.append({"evento": "mapping", "job": len(job),
                                     "esito": "forma inattesa"})
                    return None, motivo
                self.log.append({"evento": "mapping", "job": len(job), "esito": "ok",
                                 "restanti": self._restanti})
                return risposta, ""
            except urllib.error.HTTPError as e:
                self._ultima = time.monotonic()
                self._leggi_limiti(e.headers or {})
                testo = ""
                try:
                    testo = e.read()[:200].decode("utf-8", "replace")
                except Exception:
                    pass
                if e.code == 429 and tentativo < MAX_TENTATIVI:
                    # il servizio dice quando riprovare: se non lo dice, si usa
                    # un'attesa prudenziale. Un limite di frequenza non e' un
                    # errore del programma, e' traffico da distanziare.
                    attesa = ATTESA_429_S
                    try:
                        attesa = float((e.headers or {}).get("retry-after") or ATTESA_429_S)
                    except Exception:
                        pass
                    attesa = max(1.0, min(attesa, LIMITE_FINESTRA_S + 1.0))
                    self.stats["attese"] += 1
                    self.log.append({"evento": "429", "attesa": round(attesa, 1)})
                    time.sleep(attesa)
                    self._restanti = None
                    continue
                if e.code in (500, 502, 503) and tentativo < MAX_TENTATIVI:
                    time.sleep(2.0)
                    continue
                self.stats["errori"] += 1
                motivo = f"HTTP {e.code} da OpenFIGI"
                if e.code == 429:
                    motivo += (f" (limite di frequenza: il servizio dichiara "
                               f"{LIMITE_RICHIESTE} richieste ogni {LIMITE_FINESTRA_S}s)")
                elif e.code == 413:
                    motivo += f" (troppi strumenti in una richiesta: {testo.strip()})"
                elif testo.strip():
                    motivo += f": {testo.strip()}"
                self.ultimo_errore = motivo
                self.log.append({"evento": "mapping", "job": len(job),
                                 "esito": f"http {e.code}"})
                return None, motivo
            except Exception as e:
                self._ultima = time.monotonic()
                if tentativo < MAX_TENTATIVI:
                    time.sleep(1.0)
                    continue
                self.stats["errori"] += 1
                motivo = f"{type(e).__name__}: {e}"
                self.ultimo_errore = motivo
                self.log.append({"evento": "mapping", "job": len(job),
                                 "esito": type(e).__name__})
                return None, motivo
        return None, "richiesta non riuscita"

    # --------------------------------------------------------------- identita'
    def identita(self, tickers: list[str]) -> dict[str, dict]:
        """Gli identificativi per un elenco di ticker, dalla cache o da OpenFIGI.

        Tre passaggi, e ciascuno chiede solo quello che il precedente non ha
        trovato, raggruppato a dieci per richiesta:

        1. ticker piu' codice di borsa, la domanda precisa;
        2. le varianti di scrittura del ticker (trattino, zeri di riempimento);
        3. ricerca senza borsa, come ripiego. Qui la risposta puo' contenere molte
           quotazioni: si accetta **solo se sono tutte dello stesso strumento**
           (stesso nome e stessa classe di azioni), altrimenti si rinuncia. Un
           omonimo preso per buono metterebbe sulla card il codice di un'altra
           societa', che e' esattamente il danno che questo modulo deve evitare.
        """
        richiesti = [t for t in dict.fromkeys(tickers or []) if isinstance(t, str) and t.strip()]
        esiti: dict[str, dict] = {}
        da_fare: list[str] = []
        for t in richiesti:
            voce = self.cache["strumenti"].get(t) if self.usa_cache else None
            if isinstance(voce, dict) and not _scaduta(voce):
                self.stats["cache"] += 1
                esiti[t] = dict(voce)
            else:
                da_fare.append(t)

        # passaggi 1 e 2: la domanda precisa, poi le varianti di scrittura
        varianti = {t: job_per_ticker(t) for t in da_fare}
        for t in da_fare:
            if not varianti[t]:
                esiti[t] = _voce_mancante("ticker vuoto o non interpretabile")

        def fuori(ticker: str) -> bool:
            """Chi e' trovato non si richiede, e chi non si e' potuto raggiungere
            per un problema di rete nemmeno: riprovare le varianti con la rete giu'
            moltiplica le attese senza cambiare l'esito."""
            voce = esiti.get(ticker) or {}
            return bool(voce.get("trovato") or voce.get("temporaneo"))

        mancanti = [t for t in da_fare if varianti[t]]
        giri = max((len(v) for v in varianti.values()), default=0)
        for giro in range(giri):
            tentativi = [(t, varianti[t][giro]) for t in mancanti
                         if giro < len(varianti[t])]
            if not tentativi:
                continue
            for blocco in [tentativi[i:i + MAX_JOB]
                           for i in range(0, len(tentativi), MAX_JOB)]:
                risposta, motivo = self._chiama([j for _, j in blocco])
                if risposta is None:
                    # richiesta non arrivata: non si conclude nulla sugli
                    # strumenti, e il buco NON va in cache come "non esiste"
                    for t, j in blocco:
                        esiti[t] = _voce_mancante(f"OpenFIGI non raggiunto ({motivo})", j)
                        esiti[t]["temporaneo"] = True
                    continue
                for (t, j), ris in zip(blocco, risposta):
                    dati = ris.get("data") if isinstance(ris, dict) else None
                    if isinstance(dati, list) and dati:
                        esiti[t] = _voce_da_risposta(j, dati)
                    else:
                        # `warning` quando il codice non e' noto, `error` quando la
                        # richiesta stessa non va bene: due diagnosi diverse
                        avviso = (ris.get("warning") or ris.get("error")
                                  if isinstance(ris, dict) else None)
                        esiti[t] = _voce_mancante(
                            f"OpenFIGI non conosce questo codice "
                            f"({avviso or 'nessuna corrispondenza'})", j)
            mancanti = [t for t in mancanti if not fuori(t)]
            if not mancanti:
                break

        # passaggio 3: ricerca senza codice di borsa, solo per chi e' ancora fuori
        residui = [t for t in da_fare if varianti[t] and not fuori(t)]
        if residui:
            self._senza_borsa(residui, esiti)

        if self.usa_cache:
            for t, voce in esiti.items():
                if voce.get("temporaneo"):
                    continue              # un problema di rete non si mette in cache
                if t in da_fare:
                    self.cache["strumenti"][t] = voce
                    self._modificata = True
        return esiti

    def _senza_borsa(self, tickers: list[str], esiti: dict[str, dict]) -> None:
        """Ripiego: si cerca il ticker senza dire su quale borsa.

        Serve ai casi veri in cui la quotazione che prezziamo non e' nell'anagrafica
        con quel codice di borsa (verificato su EXS1.DE: OpenFIGI ha quattro
        quotazioni dello stesso ETF, nessuna delle quali su Xetra). Si accetta solo
        l'unanimita': stesso nome, una sola classe di azioni, numero di quotazioni
        ragionevole. In quel caso il dato utile e' la **classe di azioni**, non la
        singola quotazione, e la nota lo dice.
        """
        job = []
        for t in tickers:
            corpo, suff = pezzi_ticker(t)
            if t.endswith("-USD") or t.endswith("-EUR") or t.endswith("=F"):
                continue                  # cripto e future: senza settore non ha senso
            job.append((t, {"idType": "TICKER", "idValue": corpo.replace("-", "")}))
        for blocco in [job[i:i + MAX_JOB] for i in range(0, len(job), MAX_JOB)]:
            risposta, motivo = self._chiama([j for _, j in blocco])
            if risposta is None:
                for t, j in blocco:
                    esiti[t] = _voce_mancante(f"OpenFIGI non raggiunto ({motivo})", j)
                    esiti[t]["temporaneo"] = True
                continue
            for (t, j), ris in zip(blocco, risposta):
                dati = ris.get("data") if isinstance(ris, dict) else None
                if not isinstance(dati, list) or not dati:
                    continue              # resta il motivo del passaggio precedente
                nomi = {(d.get("name") or "").strip().upper() for d in dati}
                classi = {d.get("shareClassFIGI") for d in dati if d.get("shareClassFIGI")}
                if len(nomi) != 1 or len(classi) > 1 or len(dati) > MAX_QUOTAZIONI_AMMESSE:
                    esiti[t] = _voce_mancante(
                        f"ricerca senza borsa ambigua: {len(dati)} quotazioni, "
                        f"{len(nomi)} denominazioni diverse. Nessuna scelta "
                        f"automatica: un omonimo metterebbe sulla card il codice "
                        f"di un altro strumento", j)
                    continue
                voce = _voce_da_risposta(
                    j, dati,
                    nota=(f"OpenFIGI non ha questo codice sulla borsa attesa: il FIGI "
                          f"è di un'altra quotazione dello stesso strumento "
                          f"({len(dati)} quotazioni, una sola classe di azioni)"))
                voce["borsa_attesa_assente"] = True
                esiti[t] = voce

    # ------------------------------------------------ riscontro sugli ISIN
    def controlla_isin(self, coppie: dict[str, str],
                       anagrafiche: dict[str, dict]) -> dict[str, dict]:
        """Verifica che ogni ISIN scritto a mano sia **di quello strumento**.

        OpenFIGI sa mappare anche nel verso ISIN -> FIGI: si chiede l'elenco delle
        quotazioni di quell'ISIN e si guarda se dentro c'e' la quotazione che il
        motore prezza (o almeno la sua classe di azioni, o la stessa denominazione
        ufficiale). E' il controllo che prende l'errore pericoloso: la cifra di
        controllo accorge l'ISIN battuto male, non l'ISIN perfetto di un'altra
        societa'.

        Tre esiti possibili, e la differenza conta: `concorda` (si usa),
        `non_concorda` (si rifiuta e si spiega), `non_verificato` (si usa, ma la
        nota dice che il riscontro non e' stato fatto, perche' non avere la rete
        non e' una buona ragione per buttare via il lavoro dell'utente).
        I verdetti stanno nella stessa cache permanente: il legame fra un ISIN e
        il suo FIGI non cambia, quindi si chiede una volta e basta.
        """
        esiti: dict[str, dict] = {}
        da_chiedere: list[tuple[str, str]] = []
        for ticker, isin in (coppie or {}).items():
            if not isin:
                continue
            chiave = f"{ticker}|{isin}"
            memo = self.cache["isin_verificati"].get(chiave) if self.usa_cache else None
            if isinstance(memo, dict) and memo.get("esito") in ("concorda", "non_concorda"):
                self.stats["cache"] += 1
                esiti[ticker] = dict(memo)
            else:
                da_chiedere.append((ticker, isin))

        for blocco in [da_chiedere[i:i + MAX_JOB]
                       for i in range(0, len(da_chiedere), MAX_JOB)]:
            job = [{"idType": "ID_ISIN", "idValue": isin} for _, isin in blocco]
            risposta, motivo = self._chiama(job)
            if risposta is None:
                for ticker, isin in blocco:
                    esiti[ticker] = {"esito": "non_verificato", "isin": isin,
                                     "motivo": f"riscontro non fatto: {motivo}",
                                     "scritto_il": _oggi()}
                continue
            for (ticker, isin), ris in zip(blocco, risposta):
                dati = ris.get("data") if isinstance(ris, dict) else None
                if not isinstance(dati, list) or not dati:
                    avviso = (ris.get("warning") or ris.get("error")
                              if isinstance(ris, dict) else None)
                    esiti[ticker] = {
                        "esito": "non_concorda", "isin": isin, "quotazioni": 0,
                        "motivo": f"OpenFIGI non conosce questo ISIN "
                                  f"({avviso or 'nessuna corrispondenza'}): "
                                  f"controllare il codice",
                        "scritto_il": _oggi()}
                    continue
                attesa = anagrafiche.get(ticker) or {}
                figi = {d.get("figi") for d in dati if d.get("figi")}
                classi = {d.get("shareClassFIGI") for d in dati if d.get("shareClassFIGI")}
                nomi = {(d.get("name") or "").strip().upper() for d in dati}
                nome_isin = (dati[0].get("name") or "").strip()
                concorda = bool(
                    (attesa.get("figi") and attesa["figi"] in figi)
                    or (attesa.get("figi_composito") and attesa["figi_composito"] in figi)
                    or (attesa.get("figi_classe") and attesa["figi_classe"] in classi)
                    or (attesa.get("nome") and attesa["nome"].strip().upper() in nomi))
                if not attesa.get("figi") and not attesa.get("nome"):
                    esiti[ticker] = {
                        "esito": "non_verificato", "isin": isin,
                        "nome_isin": nome_isin, "quotazioni": len(dati),
                        "motivo": "riscontro non fatto: di questo strumento non "
                                  "abbiamo il FIGI con cui confrontare l'ISIN",
                        "scritto_il": _oggi()}
                    continue
                esiti[ticker] = {
                    "esito": "concorda" if concorda else "non_concorda",
                    "isin": isin, "nome_isin": nome_isin, "quotazioni": len(dati),
                    "tipo_isin": dati[0].get("securityType"),
                    "motivo": "" if concorda else
                              (f"l'ISIN {isin} è di \"{nome_isin}\", mentre lo "
                               f"strumento analizzato è \"{attesa.get('nome') or ticker}\": "
                               f"uno dei due è sbagliato, l'ISIN non viene usato"),
                    "scritto_il": _oggi()}

        # in cache vanno solo i verdetti definitivi: un riscontro non fatto per
        # colpa della rete va rifatto, non ereditato per sempre
        if self.usa_cache:
            for ticker, isin in da_chiedere:
                voce = esiti.get(ticker) or {}
                if voce.get("esito") in ("concorda", "non_concorda"):
                    self.cache["isin_verificati"][f"{ticker}|{isin}"] = voce
                    self._modificata = True
        return esiti

    def chiudi(self) -> tuple[bool, str]:
        """Salva la cache se e' cambiata. Si chiama alla fine del ciclo."""
        if not (self.usa_cache and self._modificata):
            return True, ""
        return salva_cache(self.cache, self.cache_path)


# ================================================================ arricchimento
def _identita_vuota() -> dict:
    return {"isin": None, "figi": None, "figi_composito": None, "figi_classe": None,
            "nome_ufficiale": None, "tipo": None, "tipo_dettaglio": None,
            "settore_mercato": None, "borsa": None, "ticker_borsa": None,
            "settore": None, "tipologia": None, "target": None, "valuta": None,
            "ticker": None, "quotazioni": None, "completa": False,
            "fonti": {}, "note": [], "mancanti": []}


def _elenco_asset(assets) -> list[dict]:
    """Accetta sia la lista che esce da `load_real_universe` sia il dizionario
    per ticker che gira nella pipeline: chi chiama non deve convertire niente."""
    if isinstance(assets, dict):
        valori = list(assets.values())
    elif isinstance(assets, (list, tuple)):
        valori = list(assets)
    else:
        return []
    return [a for a in valori if isinstance(a, dict) and a.get("ticker")]


def _target_di(asset: dict, analisi: dict | None) -> tuple[float | None, str]:
    """Il prezzo obiettivo e da dove viene. Non e' un target di analisti: e' la
    stima del motore, e la fonte deve dirlo a chi legge la card."""
    ticker = asset.get("ticker")
    if isinstance(analisi, dict):
        an = analisi.get(ticker)
        piano = (an or {}).get("plan") if isinstance(an, dict) else None
        if isinstance(piano, dict) and piano.get("target") is not None:
            return piano["target"], "piano operativo del motore (" + FONTE_MOTORE + ")"
    val = asset.get("valuation")
    if isinstance(val, dict) and val.get("value") is not None:
        metodo = val.get("method") or ""
        return val["value"], f"modello di valutazione del motore ({metodo})".strip()
    return None, NON_DISPONIBILE


def arricchisci(assets, analisi: dict | None = None, figi: OpenFigi | None = None,
                isin_path: Path | None = None, usa_rete: bool = True,
                verifica_isin: bool = True) -> dict:
    """Aggiunge a ogni asset la voce `identita` e restituisce un riepilogo.

    `identita` porta i codici (ISIN, FIGI), la denominazione ufficiale, il tipo e
    la borsa, piu' i dati che il motore aveva gia' (settore, tipologia, prezzo
    obiettivo) **e la fonte di ciascun campo**, in `identita["fonti"]`. La fonte
    non e' un ornamento: su una card che dice "compra questo" chi legge ha il
    diritto di sapere quale riga arriva da un'anagrafica pubblica, quale l'ha
    scritta lui a mano e quale e' una stima del programma. Dove un campo manca
    resta `None`, compare in `identita["mancanti"]` e la fonte dice
    "non disponibile": nessun campo viene riempito per non lasciare un buco.

    Gli asset vengono modificati sul posto. Niente eccezioni verso il chiamante.

    Chi passa un client suo in `figi` si prende anche il compito di chiamare
    `figi.chiudi()` alla fine del ciclo, che e' il momento in cui la cache viene
    scritta: serve a chi fa piu' di una chiamata (per esempio universo e
    watchlist) e non vuole riscrivere il file due volte. Senza `figi` ci pensa
    questa funzione.
    """
    elenco = _elenco_asset(assets)
    riepilogo: dict = {"strumenti": len(elenco), "con_isin": 0, "con_figi": 0,
                       "isin_rifiutati": 0, "problemi": [], "avvisi": [],
                       "fonte_figi": FONTE_FIGI, "rete": bool(usa_rete)}
    if not elenco:
        return riepilogo

    client = figi or OpenFigi(usa_rete=usa_rete)
    riepilogo["avvisi"].extend(client.avvisi)

    voci_isin, problemi_isin = leggi_isin(isin_path)
    riepilogo["problemi"].extend(problemi_isin)
    riepilogo["isin_file"] = str(Path(isin_path) if isin_path else ISIN_PATH)
    riepilogo["isin_nel_file"] = sum(1 for v in voci_isin.values() if v.get("valido"))

    try:
        anagrafiche = client.identita([a["ticker"] for a in elenco])
    except Exception as e:                # rete di sicurezza: OP-06 sopra ogni cosa
        anagrafiche = {}
        riepilogo["problemi"].append(f"anagrafica non disponibile ({type(e).__name__}: {e})")

    # il riscontro online si chiede solo per gli ISIN che hanno passato la cifra
    # di controllo: mandare a OpenFIGI un codice che sappiamo gia' sbagliato
    # sarebbe traffico buttato
    coppie = {a["ticker"]: (voci_isin.get(a["ticker"]) or {}).get("isin")
              for a in elenco
              if (voci_isin.get(a["ticker"]) or {}).get("valido")}
    coppie = {k: v for k, v in coppie.items() if v}
    riscontri: dict[str, dict] = {}
    if coppie and verifica_isin:
        try:
            riscontri = client.controlla_isin(coppie, anagrafiche)
        except Exception as e:
            riepilogo["problemi"].append(f"riscontro ISIN non fatto "
                                         f"({type(e).__name__}: {e})")

    for asset in elenco:
        ticker = asset["ticker"]
        ide = _identita_vuota()
        fonti = ide["fonti"]
        note = ide["note"]

        # --- quello che il motore aveva gia': settore, tipologia, obiettivo
        ide["settore"] = asset.get("sector")
        fonti["settore"] = FONTE_SCHEDA if ide["settore"] else NON_DISPONIBILE
        ide["tipologia"] = asset.get("class_in_words") or asset.get("asset_class")
        fonti["tipologia"] = FONTE_SCHEDA if ide["tipologia"] else NON_DISPONIBILE
        ide["valuta"] = asset.get("currency")
        fonti["valuta"] = "quotazione (Yahoo Finance)" if ide["valuta"] else NON_DISPONIBILE
        ide["target"], fonti["target"] = _target_di(asset, analisi)
        ide["ticker"] = ticker
        fonti["ticker"] = "simbolo Yahoo Finance usato dal motore"

        # --- quello che arriva da OpenFIGI
        ana = anagrafiche.get(ticker) or {}
        if ana.get("trovato"):
            ide["figi"] = ana.get("figi")
            ide["figi_composito"] = ana.get("figi_composito")
            ide["figi_classe"] = ana.get("figi_classe")
            ide["nome_ufficiale"] = ana.get("nome")
            ide["tipo"] = ana.get("tipo")
            ide["tipo_dettaglio"] = ana.get("tipo_dettaglio")
            ide["settore_mercato"] = ana.get("settore_mercato")
            ide["borsa"] = ana.get("borsa")
            ide["ticker_borsa"] = ana.get("ticker_borsa")
            ide["quotazioni"] = ana.get("quotazioni")
            for campo in ("figi", "figi_composito", "figi_classe", "nome_ufficiale",
                          "tipo", "tipo_dettaglio", "settore_mercato", "borsa",
                          "ticker_borsa"):
                fonti[campo] = FONTE_FIGI if ide[campo] else NON_DISPONIBILE
            if ana.get("nota"):
                note.append(ana["nota"])
            riepilogo["con_figi"] += 1
        else:
            for campo in ("figi", "figi_composito", "figi_classe", "nome_ufficiale",
                          "tipo", "tipo_dettaglio", "settore_mercato", "borsa",
                          "ticker_borsa"):
                fonti[campo] = NON_DISPONIBILE
            if ana.get("motivo"):
                note.append(ana["motivo"])
        if not ide["nome_ufficiale"] and asset.get("name"):
            # il nome di comodo della scheda interna e' meglio di niente, purche'
            # sia dichiarato per quello che e': non e' la denominazione ufficiale
            ide["nome_ufficiale"] = asset["name"]
            fonti["nome_ufficiale"] = FONTE_SCHEDA + " (non la denominazione ufficiale)"

        # --- l'ISIN: solo da isin.json, solo se passa i controlli
        voce = voci_isin.get(ticker)
        riscontro = riscontri.get(ticker) or {}
        if voce is None:
            fonti["isin"] = NON_DISPONIBILE
            note.append("ISIN non disponibile: nessuna fonte gratuita lo pubblica, "
                        "va scritto a mano in isin.json")
        elif voce.get("vuoto"):
            fonti["isin"] = NON_DISPONIBILE
            note.append("ISIN non disponibile: casella vuota in isin.json")
        elif not voce.get("valido"):
            fonti["isin"] = NON_DISPONIBILE
            riepilogo["isin_rifiutati"] += 1
            note.append(f"ISIN scritto in isin.json RIFIUTATO ({voce.get('isin')}): "
                        f"{voce.get('motivo')}")
        elif riscontro.get("esito") == "non_concorda":
            fonti["isin"] = NON_DISPONIBILE
            riepilogo["isin_rifiutati"] += 1
            note.append(f"ISIN RIFIUTATO dal riscontro con OpenFIGI: "
                        f"{riscontro.get('motivo')}")
        else:
            ide["isin"] = voce["isin"]
            riepilogo["con_isin"] += 1
            if riscontro.get("esito") == "concorda":
                fonti["isin"] = (FONTE_ISIN + ": cifra di controllo ISO 6166 e "
                                 "riscontro con OpenFIGI superati")
            else:
                fonti["isin"] = (FONTE_ISIN + ": cifra di controllo ISO 6166 "
                                 "superata, riscontro con OpenFIGI non fatto")
                if riscontro.get("motivo"):
                    note.append(riscontro["motivo"])

        ide["mancanti"] = [c for c in ("isin", "figi", "nome_ufficiale", "tipo",
                                       "borsa", "target")
                           if ide.get(c) in (None, "")]
        ide["completa"] = not ide["mancanti"]
        asset["identita"] = ide

    riepilogo["senza_isin"] = len(elenco) - riepilogo["con_isin"]
    riepilogo["senza_figi"] = len(elenco) - riepilogo["con_figi"]
    riepilogo["stats"] = dict(client.stats)
    if client.ultimo_errore:
        riepilogo["ultimo_errore"] = client.ultimo_errore
    if figi is None:
        ok, motivo = client.chiudi()
        if not ok:
            riepilogo["problemi"].append(motivo)
    return riepilogo


def riga_identita(ide: dict) -> str:
    """Una riga di testo con i codici, per il messaggio di notifica e per il log.
    Quello che manca si dice, non si salta: una card che tace sull'ISIN sembra una
    card a cui l'ISIN non serviva."""
    if not isinstance(ide, dict):
        return ""
    pezzi = [f"ISIN {ide.get('isin')}" if ide.get("isin") else "ISIN non disponibile"]
    if ide.get("figi"):
        pezzi.append(f"FIGI {ide['figi']}")
    if ide.get("tipo"):
        pezzi.append(str(ide["tipo"]))
    if ide.get("settore"):
        pezzi.append(str(ide["settore"]))
    if ide.get("borsa"):
        pezzi.append(f"borsa {ide['borsa']}")
    if ide.get("target") is not None:
        pezzi.append(f"obiettivo {ide['target']}"
                     + (f" {ide['valuta']}" if ide.get("valuta") else ""))
    return " · ".join(pezzi)
