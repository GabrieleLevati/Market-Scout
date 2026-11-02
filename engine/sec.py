"""Bilanci UFFICIALI dalla SEC, e confronto con Yahoo Finance.

Oggi i bilanci della demo arrivano da un'unica fonte (`providers.Yahoo`). La SEC
pubblica gli stessi numeri presi dai depositi ufficiali delle societa' (10-K e
10-Q, in formato XBRL): avere due fonti indipendenti permette di dire **"i conti
concordano"** oppure **"le due fonti non concordano, abbasso la fiducia"**, ed e'
quello che rende la parte di analisi dati verificabile invece che fideistica.

Tre endpoint, nessuna chiave, nessuna registrazione:

* mappa ticker -> CIK: `https://www.sec.gov/files/company_tickers.json`;
* bilanci completi: `https://data.sec.gov/api/xbrl/companyfacts/CIK##########.json`
  (il CIK va imbottito di zeri fino a 10 cifre);
* anagrafica e settore SIC: `https://data.sec.gov/submissions/CIK##########.json`.

USER-AGENT OBBLIGATORIO. Senza, o con User-Agent vuoto o generico, la SEC
risponde 403 e scrive: "Please declare your traffic by updating your user agent
to include company specific information". Qui l'intestazione si legge dalla
variabile d'ambiente `SEC_USER_AGENT`; se manca si usa un valore di riserva
onesto, che NON contiene un indirizzo di posta inventato. **Chi vuole essere
conforme alla richiesta della SEC deve dichiarare il proprio contatto**, una
volta sola:

    setx SEC_USER_AGENT "Nome Cognome (nome.cognome@esempio.it)"

LIMITE DI FREQUENZA dichiarato dalla SEC: non piu' di 10 richieste al secondo.
Qui la pausa tra due chiamate e' prudenziale (`PACE_S`), molto sotto il limite:
una scansione non ha nessuna fretta.

Quattro trappole verificate su questa macchina, gestite tutte:

1. **il tag XBRL dei ricavi cambia da societa' a societa'**, e peggio: la stessa
   societa' puo' avere due tag, uno dei quali fermo ad anni fa. NVDA pubblica in
   `Revenues` (aggiornato), AAPL ha `Revenues` fermo al 2018 e i ricavi veri in
   `RevenueFromContractWithCustomerExcludingAssessedTax`, MSFT ha `Revenues`
   fermo al 2010, JPM (banca) usa `RevenuesNetOfInterestExpense`. Per questo la
   scelta del tag non e' per ordine di preferenza ma **per data piu' recente**:
   prendere il primo tag presente darebbe ad Apple i ricavi del 2018;
2. **ogni deposito ripubblica i periodi comparativi**: lo stesso `filed`
   contiene il trimestre corrente e quello di un anno prima (verificato su NVDA:
   il deposito del 2026-08-26 contiene sia `end` 2026-07-26 da 96,2 miliardi sia
   `end` 2025-07-27 da 46,7). Il periodo si sceglie per il campo `end`, **mai per
   `filed`**; `filed` serve solo a districare le riesposizioni dello stesso
   periodo (a parita' di `end` vince il deposito piu' recente);
3. **le societa' non statunitensi non ci sono**: ENI.MI, ISP.MI, NESN.SW non
   esistono per la SEC (verificato). Per quelle la fonte resta Yahoo, e il modulo
   lo dichiara invece di restituire un buco silenzioso;
4. **chi deposita il 20-F pubblica in IFRS**: TSM e' nella mappa ma i suoi fatti
   stanno nella tassonomia `ifrs-full` (`Revenue`, `ProfitLoss`, `Equity`), non in
   `us-gaap`, e sono in dollari di Taiwan. Anche qui: si dichiara, non si finge.

Niente di quello che c'e' qui solleva un'eccezione verso il chiamante (OP-06):
una fonte che non risponde produce `disponibile: False` con il motivo scritto, e
il ciclo di scansione va avanti.

Cache su disco giornaliera in `.data_cache/`, con lo stesso schema di
`providers.py`: un file per fonte per giorno, un secondo giro nello stesso giorno
non tocca la rete.
"""

from __future__ import annotations

import json
import os
import re
import ssl
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import date, datetime, timezone
from pathlib import Path

CACHE_DIR = Path(__file__).resolve().parent.parent / ".data_cache"

# User-Agent di riserva. Volutamente senza posta elettronica: un indirizzo
# inventato sarebbe una bugia detta a un ente pubblico. Vedi il docstring.
UA_RISERVA = "AI-Market-Scout-demo/0.1 (uso personale, nessun contatto dichiarato)"
UA_AVVISO = ("User-Agent di riserva: per essere conformi alla richiesta della SEC "
             'impostare SEC_USER_AGENT con il proprio contatto (setx SEC_USER_AGENT '
             '"Nome Cognome (nome@esempio.it)")')

TIMEOUT_S = 40
PACE_S = 0.4            # la SEC dichiara 10 richieste al secondo: stiamo molto sotto
MAX_TENTATIVI = 2

# Durata di un periodo, in giorni, per riconoscere un anno da un trimestre. Gli
# esercizi non finiscono il 31 dicembre (NVDA chiude a gennaio, MSFT a giugno) e
# le "52/53 settimane" fanno ballare le date: le finestre sono larghe. I periodi
# intermedi (semestre, nove mesi) esistono nei depositi e vanno scartati, non
# confusi con un trimestre.
GIORNI_ANNO = (330, 400)
GIORNI_TRIMESTRE = (80, 100)

# Tolleranza nel confronto fra le date delle due fonti: Yahoo arrotonda la data di
# chiusura alla fine del mese (NVDA 2026-01-31 dove la SEC dice 2026-01-25), quindi
# due date vicine sono lo stesso periodo. Resta molto sotto i 90 giorni che
# separano due trimestri, percio' non si possono confondere periodi diversi.
GIORNI_TOLLERANZA = 15

# Soglie del verdetto sul confronto fra le due fonti.
SOGLIA_CONCORDANO = 0.02
SOGLIA_ACCETTABILE = 0.10

# --------------------------------------------------------------------- i tag
# Metriche di flusso (hanno un inizio e una fine: ricavi, utile, cassa).
# L'ordine conta solo a pari data: la scelta vera e' per data piu' recente
# (trappola 1). Le alternative non sono eleganza, sono necessita': senza
# `RevenuesNetOfInterestExpense` una banca non ha ricavi, senza
# `RevenueFromContractWithCustomer...` Apple non ne ha.
TAG_FLUSSI = {
    "ricavi": ["Revenues",
               "RevenueFromContractWithCustomerExcludingAssessedTax",
               "RevenueFromContractWithCustomerIncludingAssessedTax",
               "RevenuesNetOfInterestExpense",
               "SalesRevenueNet",
               "SalesRevenueGoodsNet",
               "TotalRevenuesAndOtherIncome"],
    "utile_netto": ["NetIncomeLoss",
                    "ProfitLoss",
                    "NetIncomeLossAvailableToCommonStockholdersBasic"],
    "utile_per_azione": ["EarningsPerShareDiluted",
                         "EarningsPerShareBasicAndDiluted",
                         "IncomeLossFromContinuingOperationsPerDilutedShare"],
    "flusso_cassa_operativo": ["NetCashProvidedByUsedInOperatingActivities",
                               "NetCashProvidedByUsedInOperatingActivities"
                               "ContinuingOperations"],
    # serve solo per ricavare il flusso di cassa libero e poterlo confrontare con
    # quello che pubblica Yahoo: la SEC non espone un "free cash flow", e' una
    # grandezza derivata (cassa operativa meno investimenti in immobilizzazioni)
    "investimenti": ["PaymentsToAcquirePropertyPlantAndEquipment",
                     "PaymentsToAcquireProductiveAssets",
                     "PaymentsToAcquireOtherPropertyPlantAndEquipment"],
}

# Metriche di saldo (fotografia a una data: patrimonio, debito).
TAG_SALDI = {
    "patrimonio_netto": ["StockholdersEquity",
                         "StockholdersEquityIncludingPortionAttributable"
                         "ToNoncontrollingInterest"],
}

# Il debito totale non ha un tag solo. Dove c'e' `DebtCurrent` la parte a breve e'
# quella e basta; dove non c'e' (Apple e Microsoft non lo usano) va ricomposta
# sommando le voci, perche' la carta commerciale e la quota corrente dei bond sono
# righe separate dello stato patrimoniale. Sommare anche `DebtCurrent` insieme a
# `LongTermDebtCurrent` conterebbe due volte la stessa cosa.
DEBITO_BREVE_UNICO = ["DebtCurrent"]
DEBITO_BREVE_COMPONENTI = ["LongTermDebtCurrent", "ShortTermBorrowings",
                           "CommercialPaper", "OtherShortTermBorrowings"]
DEBITO_LUNGO = ["LongTermDebtNoncurrent", "LongTermDebtAndCapitalLeaseObligations",
                "LongTermDebt"]
# Il leasing non e' debito finanziario, ma Yahoo a volte lo include nel suo
# "total debt" (verificato: su NVDA e MSFT la differenza con la SEC e' esattamente
# il leasing operativo non corrente; su AAPL no). Si estrae a parte, per spiegare
# lo scostamento invece di chiamarlo errore.
LEASING = ["OperatingLeaseLiabilityNoncurrent", "FinanceLeaseLiabilityNoncurrent"]

UNITA_SOLDI = "USD"
UNITA_PER_AZIONE = "USD/shares"

# Un deposito periodico e' la fonte autorevole; un comunicato (8-K) o un prospetto
# contengono gli stessi numeri ma non sempre definitivi. A pari data vince il
# periodico.
FORME_PERIODICHE = ("10-K", "10-Q", "20-F", "40-F")

# Nomi delle metriche come le chiama Yahoo in `providers.Yahoo.statements()`.
# Il flusso di cassa operativo non c'e': Yahoo in questa configurazione pubblica
# il flusso di cassa libero. Non e' un buco da riempire a occhio, e' un dato che
# una delle due fonti non da'.
CHIAVI_YAHOO = {
    "annuali": {"ricavi": "annualTotalRevenue",
                "utile_netto": "annualNetIncome",
                "utile_per_azione": "annualDilutedEPS",
                "patrimonio_netto": "annualStockholdersEquity",
                "debito": "annualTotalDebt",
                "flusso_cassa_libero": "annualFreeCashFlow"},
    "trimestrali": {"ricavi": "quarterlyTotalRevenue",
                    "utile_netto": "quarterlyNetIncome",
                    "utile_per_azione": "quarterlyDilutedEPS",
                    "flusso_cassa_libero": "quarterlyFreeCashFlow"},
}

# Ordine di presentazione delle metriche nel confronto.
METRICHE = ["ricavi", "utile_netto", "utile_per_azione", "patrimonio_netto",
            "debito", "flusso_cassa_operativo", "flusso_cassa_libero"]

# Tabella di riserva ticker -> CIK. Serve quando `www.sec.gov` non risponde (su
# questa macchina risponde 403 "Request Rate Threshold Exceeded" anche con
# User-Agent dichiarato, mentre `data.sec.gov` risponde benissimo) e la ricerca
# full-text non e' raggiungibile. Ogni riga e' stata verificata una per una
# chiedendo l'anagrafica alla SEC: il CIK e' giusto se l'endpoint submissions
# restituisce quel ticker e quel nome. Copre i titoli statunitensi dell'universo
# della demo (`real_universe.REAL_SPECS`), non e' una mappa generale.
CIK_RISERVA = {
    "AAPL": (320193, "Apple Inc."),
    "AMD": (2488, "ADVANCED MICRO DEVICES INC"),
    "CAT": (18230, "CATERPILLAR INC"),
    "GOOGL": (1652044, "Alphabet Inc."),
    "JPM": (19617, "JPMORGAN CHASE & CO"),
    "KO": (21344, "COCA COLA CO"),
    "LLY": (59478, "ELI LILLY & Co"),
    "META": (1326801, "Meta Platforms, Inc."),
    "MSFT": (789019, "MICROSOFT CORP"),
    "NVDA": (1045810, "NVIDIA CORP"),
    "PLD": (1045609, "Prologis, Inc."),
    "SPG": (1063761, "SIMON PROPERTY GROUP INC."),
    "TSM": (1046179, "TAIWAN SEMICONDUCTOR MANUFACTURING CO LTD"),
    "UNH": (731766, "UNITEDHEALTH GROUP INC"),
    "XOM": (34088, "EXXON MOBIL CORP"),
}

# Nella ricerca full-text EDGAR il nome arriva impacchettato cosi':
# "NVIDIA CORP  (NVDA)  (CIK 0001045810)".
RE_NOME_EDGAR = re.compile(r"^(?P<nome>.+?)\s+\((?P<ticker>[A-Z0-9.\-]{1,12})\)"
                           r"\s+\(CIK (?P<cik>\d{10})\)$")


def user_agent() -> str:
    """L'intestazione da dichiarare alla SEC. Vedi il docstring del modulo: la SEC
    chiede di identificare il traffico, e senza intestazione risponde 403."""
    ua = (os.environ.get("SEC_USER_AGENT") or "").strip()
    return ua or UA_RISERVA


def _giorni(inizio: str, fine: str) -> int | None:
    try:
        a = date(*(int(x) for x in inizio.split("-")))
        b = date(*(int(x) for x in fine.split("-")))
    except Exception:
        return None
    return (b - a).days


def _distanza(a: str | None, b: str | None) -> int:
    """Giorni fra due date, senza segno.

    Se una delle due manca o non si legge, restituisce un numero grande: due date
    che non si possono confrontare non sono "vicine". Attenzione allo zero:
    scrivere `_giorni(a, b) or 999` sarebbe un errore silenzioso, perche' zero
    giorni di distanza e' proprio il caso buono (le due fonti chiudono lo stesso
    giorno) e in Python zero e' falso.
    """
    if not a or not b:
        return 10 ** 6
    g = _giorni(a, b)
    return 10 ** 6 if g is None else abs(g)


def _cik10(cik: int) -> str:
    """Il CIK va imbottito di zeri a dieci cifre: 1045810 -> CIK0001045810."""
    return f"CIK{int(cik):010d}"


class Sec:
    """Client minimale sugli endpoint XBRL della SEC.

    Stessa forma di `providers.Yahoo` (cache giornaliera, contatori, registro
    delle chiamate) con una differenza voluta: qui **nessun metodo solleva**. Un
    403 o una rete giu' producono `None` e una riga nel registro, perche' questo
    modulo serve a confrontare due fonti e il confronto deve poter dire "la
    seconda fonte oggi non c'era" senza fermare la scansione.
    """

    def __init__(self, use_cache: bool = True, pace_s: float = PACE_S,
                 user_agent_: str | None = None):
        self.use_cache = use_cache
        self.pace_s = pace_s
        self.ua = (user_agent_ or user_agent()).strip() or UA_RISERVA
        self.ua_dichiarato = bool((os.environ.get("SEC_USER_AGENT") or "").strip()
                                  or user_agent_)
        self._last = 0.0
        self.stats = {"http": 0, "cache": 0, "errors": 0, "bytes": 0}
        self.log: list[dict] = []
        self.ultimo_errore: str | None = None
        self._mappa: dict[str, tuple[int, str]] | None = None
        self._mappa_origine: str | None = None
        if use_cache:
            CACHE_DIR.mkdir(exist_ok=True)

    # ------------------------------------------------------------------ rete
    def _cache_file(self, kind: str, symbol: str) -> Path:
        safe = urllib.parse.quote(symbol, safe="")
        return CACHE_DIR / f"sec_{kind}_{safe}_{date.today().isoformat()}.json"

    def _fetch(self, kind: str, url: str, symbol: str, pota=None) -> dict | None:
        """Una chiamata, con cache giornaliera e un tentativo di recupero sugli
        errori temporanei. Restituisce `None` se non si e' potuto leggere nulla:
        chi chiama controlla, nessuno viene interrotto da un'eccezione.

        `pota` e' una funzione che riduce la risposta prima di salvarla. I
        `companyfacts` di una sola societa' pesano 4-5 MB (NVDA ne ha 627 tag) e
        salvarli interi significherebbe decine di megabyte al giorno nella cache
        per dati che non guardiamo: si tiene solo cio' che il modulo usa. Se si
        allunga la lista dei tag va svuotata la cache del giorno (o si passa
        `use_cache=False`), altrimenti i tag nuovi non ci sono.
        """
        cf = self._cache_file(kind, symbol)
        if self.use_cache and cf.exists():
            try:
                self.stats["cache"] += 1
                return json.loads(cf.read_text(encoding="utf-8"))
            except Exception:
                pass            # cache illeggibile: si riscarica, non si fallisce
        for tentativo in range(1, MAX_TENTATIVI + 1):
            attesa = self.pace_s - (time.monotonic() - self._last)
            if attesa > 0:
                time.sleep(attesa)
            try:
                req = urllib.request.Request(url, headers={
                    "User-Agent": self.ua,
                    "Accept": "application/json",
                    "Accept-Encoding": "identity",
                })
                with urllib.request.urlopen(req, timeout=TIMEOUT_S,
                                            context=ssl.create_default_context()) as r:
                    raw = r.read()
                self._last = time.monotonic()
                self.stats["http"] += 1
                self.stats["bytes"] += len(raw)
                dati = json.loads(raw)
                if pota:
                    dati = pota(dati)
                if self.use_cache:
                    try:
                        cf.write_text(json.dumps(dati), encoding="utf-8")
                    except Exception:
                        pass    # disco pieno o percorso lungo: si procede comunque
                self.log.append({"kind": kind, "symbol": symbol, "status": "ok"})
                return dati
            except urllib.error.HTTPError as e:
                self._last = time.monotonic()
                if e.code in (429, 500, 502, 503) and tentativo < MAX_TENTATIVI:
                    time.sleep(2.0)
                    continue
                self.stats["errors"] += 1
                motivo = f"HTTP {e.code}"
                if e.code == 403:
                    # testo letterale della SEC: "Please declare your traffic by
                    # updating your user agent to include company specific
                    # information". Lo stesso 403 arriva anche quando l'indirizzo
                    # di rete ha superato il limite di frequenza.
                    motivo += (" (la SEC chiede di dichiarare il traffico con un "
                               "User-Agent proprio, oppure il limite di frequenza "
                               "e' stato superato)")
                self.ultimo_errore = f"{symbol}: {motivo} su {kind}"
                self.log.append({"kind": kind, "symbol": symbol,
                                 "status": f"http {e.code}"})
                return None
            except Exception as e:
                self._last = time.monotonic()
                if tentativo < MAX_TENTATIVI:
                    time.sleep(1.0)
                    continue
                self.stats["errors"] += 1
                self.ultimo_errore = f"{symbol}: {type(e).__name__} su {kind}"
                self.log.append({"kind": kind, "symbol": symbol,
                                 "status": type(e).__name__})
                return None
        return None

    # ------------------------------------------------------- ticker -> CIK
    def mappa_ticker(self) -> tuple[dict[str, tuple[int, str]], str]:
        """La mappa ufficiale ticker -> CIK, con due ripieghi dichiarati.

        Restituisce (mappa, origine). La mappa ufficiale e' l'unica completa
        (circa diecimila societa'); quando `www.sec.gov` non risponde si resta
        con la tabella interna, che copre solo l'universo della demo. In entrambi
        i casi l'origine viaggia col dato, perche' "non trovato nella tabella di
        riserva" e "non esiste per la SEC" sono due risposte diverse.
        """
        if self._mappa is not None:
            return self._mappa, self._mappa_origine or ""
        dati = self._fetch("tickers", "https://www.sec.gov/files/company_tickers.json",
                           "mappa")
        mappa: dict[str, tuple[int, str]] = {}
        if isinstance(dati, dict):
            for v in dati.values():
                if not isinstance(v, dict) or not v.get("ticker"):
                    continue
                mappa[str(v["ticker"]).upper()] = (int(v.get("cik_str") or 0),
                                                   str(v.get("title") or ""))
        if mappa:
            origine = f"mappa ufficiale company_tickers.json ({len(mappa)} societa')"
        else:
            mappa = dict(CIK_RISERVA)
            origine = ("tabella di riserva interna (la mappa ufficiale della SEC non "
                       f"risponde: {self.ultimo_errore or 'nessuna risposta'})")
        self._mappa, self._mappa_origine = mappa, origine
        return mappa, origine

    def _cik_da_ricerca(self, ticker: str) -> tuple[int, str] | None:
        """Secondo ripiego: la ricerca full-text dei depositi, su `efts.sec.gov`,
        che qui risponde anche quando `www.sec.gov` da' 403. Il ticker compare nel
        nome del depositante ("NVIDIA CORP  (NVDA)  (CIK 0001045810)"), quindi il
        CIK si legge da li'. Si accetta solo una corrispondenza esatta del ticker:
        una ricerca testuale che "assomiglia" non e' un'identificazione.
        """
        q = urllib.parse.quote(f'"{ticker}"')
        url = (f"https://efts.sec.gov/LATEST/search-index?q={q}"
               f"&forms=10-K,10-Q,20-F")
        dati = self._fetch("ricerca", url, ticker)
        if not isinstance(dati, dict):
            return None
        conteggio: dict[tuple[int, str], int] = {}
        for h in ((dati.get("hits") or {}).get("hits") or []):
            for nome in ((h.get("_source") or {}).get("display_names") or []):
                m = RE_NOME_EDGAR.match(" ".join(str(nome).split()))
                if m and m.group("ticker").upper() == ticker.upper():
                    k = (int(m.group("cik")), m.group("nome"))
                    conteggio[k] = conteggio.get(k, 0) + 1
        if not conteggio:
            return None
        # il depositante che compare piu' volte e' l'emittente, non chi lo cita
        return max(conteggio.items(), key=lambda kv: kv[1])[0]

    def cik_di(self, ticker: str) -> dict:
        """Dal ticker al CIK, dicendo da dove viene e, se non c'e', perche'."""
        t = (ticker or "").upper().strip()
        if not t:
            # niente da cercare: non si disturba la SEC per un ticker vuoto, che
            # chiederebbe una richiesta sul suo limite di frequenza per nulla
            return {"cik": None, "nome": None, "origine": "nessuna",
                    "motivo": "ticker vuoto: niente da cercare"}
        mappa, origine = self.mappa_ticker()
        if t in mappa and mappa[t][0]:
            return {"cik": mappa[t][0], "nome": mappa[t][1], "origine": origine}
        ufficiale = origine.startswith("mappa ufficiale")
        if ufficiale:
            # la mappa ufficiale e' completa: se il ticker non c'e', non e' una
            # societa' quotata negli Stati Uniti (trappola 3)
            return {"cik": None, "nome": None, "origine": origine,
                    "motivo": f"{t} non e' nella mappa ufficiale della SEC "
                              f"({len(mappa)} societa'): non e' una societa' quotata "
                              f"negli Stati Uniti, la fonte resta Yahoo Finance"}
        errore_prima = self.ultimo_errore
        trovato = self._cik_da_ricerca(t)
        if trovato:
            return {"cik": trovato[0], "nome": trovato[1],
                    "origine": "ricerca full-text EDGAR (efts.sec.gov), usata perche' "
                               "la mappa ufficiale non risponde"}
        # Perche' non l'abbiamo trovato cambia tutto: "la SEC ci ha respinti" e
        # "questa societa' non esiste per la SEC" portano a due azioni diverse, e
        # scrivere la seconda quando e' vera la prima manderebbe fuori strada chi
        # legge. Se la ricerca e' andata in errore lo si dice con le sue parole.
        ricerca_ko = self.ultimo_errore != errore_prima
        if ricerca_ko:
            return {"cik": None, "nome": None, "origine": origine,
                    "motivo": f"{t}: la SEC non risponde, quindi non si puo' nemmeno "
                              f"dire se la societa' c'e'. Mappa ufficiale: "
                              f"{errore_prima or 'nessuna risposta'}. Ricerca EDGAR: "
                              f"{self.ultimo_errore}. Il ticker non e' nella tabella "
                              f"di riserva ({len(mappa)} societa'): la fonte resta "
                              f"Yahoo Finance"}
        return {"cik": None, "nome": None, "origine": origine,
                "motivo": f"{t} non e' nella tabella di riserva ({len(mappa)} "
                          f"societa') e la ricerca EDGAR non l'ha trovato fra i "
                          f"depositanti: se e' una societa' statunitense riprovare "
                          f"quando www.sec.gov e' raggiungibile, altrimenti non e' "
                          f"quotata negli Stati Uniti e la fonte resta Yahoo Finance"}

    # -------------------------------------------------------------- anagrafica
    def anagrafica(self, cik: int) -> dict | None:
        """Nome, settore SIC, borsa, mese di chiusura dell'esercizio. Non serve ai
        numeri, serve a far vedere a chi legge che stiamo guardando la societa'
        giusta."""
        dati = self._fetch("anagrafica",
                           f"https://data.sec.gov/submissions/{_cik10(cik)}.json",
                           str(cik), pota=_pota_anagrafica)
        if not isinstance(dati, dict):
            return None
        return {"nome": dati.get("name"),
                "sic": dati.get("sic"),
                "settore": dati.get("sicDescription"),
                "borse": dati.get("exchanges") or [],
                "ticker": dati.get("tickers") or [],
                "chiusura_esercizio": dati.get("fiscalYearEnd"),
                "tipo": dati.get("entityType"),
                "categoria": dati.get("category")}

    # ------------------------------------------------------------------ fatti
    def fatti(self, cik: int, ticker: str) -> dict | None:
        """I `companyfacts`, potati ai tag che usiamo (vedi `_fetch`)."""
        return self._fetch("fatti",
                           f"https://data.sec.gov/api/xbrl/companyfacts/"
                           f"{_cik10(cik)}.json",
                           ticker, pota=_pota_fatti)

    # ---------------------------------------------------------------- bilanci
    def bilanci(self, ticker: str) -> dict:
        """Le metriche ufficiali di una societa'. **Sempre un dizionario**, anche
        quando non c'e' niente: `disponibile` dice se ci sono numeri e `motivo`
        perche' no."""
        t = (ticker or "").upper().strip()
        base = {"ticker": t, "fonte": "SEC EDGAR XBRL (companyfacts)",
                "disponibile": False, "motivo": None, "avvisi": [],
                "letto_il": datetime.now(timezone.utc).isoformat(timespec="seconds")}
        if not self.ua_dichiarato:
            base["avvisi"].append(UA_AVVISO)

        ident = self.cik_di(t)
        base["cik_origine"] = ident.get("origine")
        if not ident.get("cik"):
            base["motivo"] = ident.get("motivo") or "CIK non risolto"
            base["fonte_di_ripiego"] = "Yahoo Finance"
            return base
        base["cik"] = ident["cik"]
        base["nome"] = ident.get("nome")

        dati = self.fatti(ident["cik"], t)
        if not isinstance(dati, dict):
            base["motivo"] = (f"la SEC non ha restituito i bilanci di {t}: "
                              f"{self.ultimo_errore or 'nessuna risposta'}")
            base["fonte_di_ripiego"] = "Yahoo Finance"
            return base

        base["nome"] = dati.get("entityName") or base.get("nome")
        fatti = dati.get("facts") or {}
        base["tassonomie"] = sorted(fatti)
        us = fatti.get("us-gaap") or {}
        # la presenza della chiave conta piu' del suo contenuto: dopo la potatura
        # (vedi `_pota_fatti`) una societa' che pubblica in us-gaap senza nessuno
        # dei nostri tag lascia la chiave vuota, e non va confusa con chi non
        # pubblica in us-gaap per niente
        if "us-gaap" not in fatti:
            # trappola 4: chi deposita il 20-F pubblica in IFRS
            altra = [x for x in fatti if x not in ("dei", "srt", "ecd", "ffd", "invest")]
            base["motivo"] = (
                f"{t} non pubblica nella tassonomia us-gaap"
                + (f" ma in {', '.join(altra)}" if altra else "")
                + ": e' un emittente estero che deposita il modulo 20-F, i suoi tag e "
                  "la sua valuta sono altri. La fonte resta Yahoo Finance")
            base["fonte_di_ripiego"] = "Yahoo Finance"
            return base

        annuali, avvisi_a = _metriche(us, "annuale")
        trimestrali, avvisi_t = _metriche(us, "trimestrale")
        base["annuali"] = annuali
        base["trimestrali"] = trimestrali
        base["avvisi"].extend(sorted(set(avvisi_a) | set(avvisi_t)))
        base["valuta"] = (_valuta(annuali) or _valuta(trimestrali) or UNITA_SOLDI)
        base["disponibile"] = bool(annuali or trimestrali)
        if not base["disponibile"]:
            base["motivo"] = (f"{t} ha fatti XBRL ma nessuna delle metriche cercate: "
                              f"puo' essere un fondo o un veicolo che non pubblica un "
                              f"conto economico d'impresa. La fonte resta Yahoo Finance")
            base["fonte_di_ripiego"] = "Yahoo Finance"
            return base
        ana = self.anagrafica(ident["cik"])
        if ana:
            base["anagrafica"] = ana
        base["ultimo_bilancio"] = (annuali.get("ricavi") or {}).get("data")
        base["ultimo_trimestre"] = (trimestrali.get("ricavi") or {}).get("data")
        return base


# ------------------------------------------------------------------ potatura
def _pota_fatti(dati: dict) -> dict:
    """Tiene di `companyfacts` solo i tag che il modulo usa. Senza questo la cache
    si riempie di megabyte di tag che nessuno legge (NVDA: 627 tag us-gaap, 4 MB)."""
    tenuti = set()
    for lista in TAG_FLUSSI.values():
        tenuti.update(lista)
    for lista in TAG_SALDI.values():
        tenuti.update(lista)
    tenuti.update(DEBITO_BREVE_UNICO + DEBITO_BREVE_COMPONENTI + DEBITO_LUNGO + LEASING)
    fatti = dati.get("facts") or {}
    us = fatti.get("us-gaap") or {}
    nuovi = {k: v for k, v in us.items() if k in tenuti}
    fuori = {k: {} for k in fatti if k != "us-gaap"}   # traccia le altre tassonomie
    out = {"cik": dati.get("cik"), "entityName": dati.get("entityName"),
           "facts": dict(fuori)}
    if us or nuovi:
        out["facts"]["us-gaap"] = nuovi
    out["_cache"] = ("ridotta ai tag usati da engine/sec.py: se si allunga la lista "
                     "dei tag va svuotata la cache del giorno")
    return out


def _pota_anagrafica(dati: dict) -> dict:
    """L'anagrafica porta dietro l'elenco completo dei depositi (centinaia di
    kilobyte): a noi servono otto campi."""
    return {k: dati.get(k) for k in ("cik", "name", "sic", "sicDescription",
                                     "exchanges", "tickers", "fiscalYearEnd",
                                     "entityType", "category")}


# ------------------------------------------------------- estrazione dei numeri
def _punti(us: dict, tag: str, unita: str) -> list[dict]:
    """I punti di un tag nell'unita' chiesta. Un'unita' sbagliata non e' un
    dettaglio: Coca-Cola ha quattro vecchi utili per azione marcati `pure` invece
    di `USD/shares`, e sommarli a quelli buoni sarebbe un numero senza senso."""
    nodo = us.get(tag)
    if not isinstance(nodo, dict):
        return []
    unita_disp = nodo.get("units") or {}
    serie = unita_disp.get(unita)
    if serie is None and unita == UNITA_PER_AZIONE:
        # alcune societa' scrivono l'unita' per azione in altro modo
        for u in unita_disp:
            if u.endswith("/shares"):
                serie = unita_disp[u]
                unita = u
                break
    if serie is None and unita == UNITA_SOLDI and len(unita_disp) == 1:
        # emittente che pubblica in un'altra valuta: si prende e si dichiara
        unita, serie = next(iter(unita_disp.items()))
    if not isinstance(serie, list):
        return []
    out = []
    for p in serie:
        if not isinstance(p, dict) or p.get("val") is None or not p.get("end"):
            continue
        q = dict(p)
        q["unita"] = unita
        out.append(q)
    return out


def _filtra_periodo(punti: list[dict], tipo: str, saldo: bool) -> list[dict]:
    """Tiene solo i periodi del tipo chiesto. Per i saldi il "periodo" e' un
    istante (non c'e' `start`); per i flussi la durata decide se e' un anno o un
    trimestre, e i periodi intermedi (semestre, nove mesi) si scartano: nei
    depositi ci sono, e confonderli con un trimestre raddoppierebbe i ricavi."""
    out = []
    for p in punti:
        inizio = p.get("start")
        if saldo:
            if inizio:
                continue
            if tipo == "annuale" and (p.get("fp") or "") not in ("FY", "", None):
                # per un saldo il periodo conta poco, ma per l'annuale preferiamo
                # la fotografia di chiusura d'esercizio
                continue
            out.append(p)
            continue
        if not inizio:
            continue
        g = _giorni(inizio, p["end"])
        if g is None:
            continue
        lo, hi = GIORNI_ANNO if tipo == "annuale" else GIORNI_TRIMESTRE
        if lo <= g <= hi:
            out.append(p)
    return out


def _per_data(punti: list[dict]) -> dict[str, dict]:
    """Un valore per data di chiusura (`end`).

    Qui stanno le due trappole dei depositi. La prima: lo stesso deposito
    contiene il periodo corrente e il comparativo di un anno prima, quindi il
    periodo si identifica con `end` e **mai** con `filed`. La seconda: lo stesso
    `end` puo' comparire piu' volte con valori diversi, perche' un bilancio
    successivo lo ha riesposto (verificato su NVDA, `end` 2015-01-25:
    1.250.514.000 nel deposito del 2015, 1.251.000.000 in quello del 2016). A
    pari `end` vince il deposito piu' recente, e a pari deposito il modulo
    periodico (10-K, 10-Q) batte il comunicato (8-K).
    """
    migliore: dict[str, dict] = {}
    for p in punti:
        chiave = p["end"]
        vecchio = migliore.get(chiave)
        if vecchio is None or _rango(p) > _rango(vecchio):
            migliore[chiave] = p
    return migliore


def _rango(p: dict) -> tuple:
    """Chi vince a pari data di chiusura: prima la forma, poi la data di deposito.

    L'ordine conta. Verificato su NVDA e MSFT: l'utile netto dell'esercizio viene
    ripubblicato nella relazione per l'assemblea (DEF 14A), depositata **mesi dopo**
    il 10-K. Guardando prima la data di deposito il numero finirebbe per arrivare
    da un documento di convocazione invece che dal bilancio, con `fp` e `fy`
    mancanti. Il modulo periodico viene prima; a pari forma vince il deposito piu'
    recente, che e' la riesposizione piu' aggiornata dello stesso periodo.
    """
    forma = str(p.get("form") or "")
    periodico = 1 if forma.startswith(FORME_PERIODICHE) else 0
    return (periodico, str(p.get("filed") or ""), str(p.get("accn") or ""))


def _serie_tag(us: dict, tags: list[str], unita: str, tipo: str,
               saldo: bool) -> tuple[dict[str, dict], str | None]:
    """Sceglie il tag e restituisce la sua serie per data.

    **La scelta e' per data piu' recente, non per ordine di preferenza.** E' la
    trappola 1: Apple ha sia `Revenues` (fermo al 2018) sia
    `RevenueFromContractWithCustomerExcludingAssessedTax` (aggiornato); prendere
    il primo che esiste darebbe i ricavi di sette anni fa. A pari data piu'
    recente vince l'ordine della lista, che mette prima i tag piu' comuni.
    """
    migliore_tag, migliore_serie, migliore_chiave = None, {}, None
    for posizione, tag in enumerate(tags):
        serie = _per_data(_filtra_periodo(_punti(us, tag, unita), tipo, saldo))
        if not serie:
            continue
        ultima = max(serie)
        chiave = (ultima, -posizione, len(serie))
        if migliore_chiave is None or chiave > migliore_chiave:
            migliore_tag, migliore_serie, migliore_chiave = tag, serie, chiave
    return migliore_serie, migliore_tag


def _voce(punto: dict, tag: str, derivata: str | None = None) -> dict:
    """La forma di una metrica: il numero non viaggia mai senza la sua data, il
    tag da cui viene e il deposito che l'ha pubblicato. Senza questi, "fonte
    ufficiale" e' una parola."""
    out = {"valore": float(punto["val"]),
           "data": punto["end"],
           "inizio": punto.get("start"),
           "tag": tag,
           "unita": punto.get("unita") or UNITA_SOLDI,
           "forma": punto.get("form"),
           "depositato_il": punto.get("filed"),
           "esercizio": f"FY{punto.get('fy')}" if punto.get("fy") else None,
           "periodo": punto.get("fp")}
    if derivata:
        out["derivata"] = derivata
    return out


def _ultimo(serie: dict[str, dict]) -> dict | None:
    return serie[max(serie)] if serie else None


def _serie_somma(us: dict, unico: list[str], componenti: list[str], tipo: str
                 ) -> tuple[dict[str, dict], list[str]]:
    """Il debito a breve: un tag solo dove c'e', altrimenti la somma delle voci.

    Apple e Microsoft non usano `DebtCurrent`: la loro parte a breve e' la quota
    corrente dei bond piu' la carta commerciale, righe separate. Sommare
    `DebtCurrent` *e* `LongTermDebtCurrent` conterebbe due volte lo stesso debito,
    percio' o l'uno o gli altri.
    """
    serie, tag = _serie_tag(us, unico, UNITA_SOLDI, tipo, saldo=True)
    if serie:
        return serie, [tag] if tag else []
    pezzi: dict[str, dict[str, dict]] = {}
    for c in componenti:
        s = _per_data(_filtra_periodo(_punti(us, c, UNITA_SOLDI), tipo, saldo=True))
        if s:
            pezzi[c] = s
    if not pezzi:
        return {}, []
    out: dict[str, dict] = {}
    usati: set[str] = set()
    for data in set().union(*(set(s) for s in pezzi.values())):
        totale, riferimento, parti = 0.0, None, []
        for c in componenti:                 # ordine fisso: la somma e' ripetibile
            s = pezzi.get(c) or {}
            if data in s:
                totale += float(s[data]["val"])
                riferimento = riferimento or s[data]
                parti.append(c)
        if riferimento is None:
            continue
        p = dict(riferimento)
        p["val"] = totale
        # quali voci sono state sommate a QUELLA data: cambia da bilancio a
        # bilancio (la carta commerciale c'e' un anno e non c'e' l'anno dopo) e
        # chi legge il numero ha diritto di sapere da cosa e' fatto
        p["_parti"] = list(parti)
        out[data] = p
        usati.update(parti)
    return out, sorted(usati)


def _metriche(us: dict, tipo: str) -> tuple[dict, list[str]]:
    """Tutte le metriche di un tipo di periodo, con i loro avvisi."""
    out: dict[str, dict] = {}
    avvisi: list[str] = []

    for nome, tags in TAG_FLUSSI.items():
        unita = UNITA_PER_AZIONE if nome == "utile_per_azione" else UNITA_SOLDI
        serie, tag = _serie_tag(us, tags, unita, tipo, saldo=False)
        p = _ultimo(serie)
        if p and tag:
            out[nome] = _voce(p, tag)
    for nome, tags in TAG_SALDI.items():
        serie, tag = _serie_tag(us, tags, UNITA_SOLDI, tipo, saldo=True)
        p = _ultimo(serie)
        if p and tag:
            out[nome] = _voce(p, tag)

    # il debito: breve + lungo, alla stessa data. Mettere insieme due date
    # diverse darebbe una somma che non e' mai stata scritta in nessun bilancio.
    breve, tag_breve = _serie_somma(us, DEBITO_BREVE_UNICO, DEBITO_BREVE_COMPONENTI, tipo)
    lungo, tag_lungo = _serie_tag(us, DEBITO_LUNGO, UNITA_SOLDI, tipo, saldo=True)
    comuni = sorted(set(breve) & set(lungo))
    if comuni:
        data = comuni[-1]
        totale = float(breve[data]["val"]) + float(lungo[data]["val"])
        p = dict(lungo[data])
        p["val"] = totale
        parti = breve[data].get("_parti") or tag_breve
        voce = _voce(p, " + ".join(list(parti) + ([tag_lungo] if tag_lungo else [])),
                     derivata="debito a breve + debito a lungo dello stesso bilancio")
        voce["debito_a_breve"] = float(breve[data]["val"])
        voce["debito_a_lungo"] = float(lungo[data]["val"])
        # il leasing e' a parte: non e' debito finanziario, ma Yahoo a volte lo
        # somma. Tenerlo da parte permette di spiegare uno scostamento invece di
        # chiamarlo disaccordo (vedi `confronta`).
        leasing = 0.0
        tag_leasing = []
        for tagl in LEASING:
            s = _per_data(_filtra_periodo(_punti(us, tagl, UNITA_SOLDI), tipo, saldo=True))
            if data in s:
                leasing += float(s[data]["val"])
                tag_leasing.append(tagl)
        if tag_leasing:
            voce["leasing_non_corrente"] = leasing
            voce["debito_incl_leasing"] = totale + leasing
            voce["tag_leasing"] = tag_leasing
        out["debito"] = voce
    elif breve or lungo:
        avvisi.append("debito incompleto: le due parti (a breve e a lungo) non "
                      "compaiono alla stessa data di bilancio")

    # il flusso di cassa libero non esiste nei depositi: e' cassa operativa meno
    # investimenti in immobilizzazioni. Lo calcoliamo solo per poterlo confrontare
    # con quello che pubblica Yahoo, e lo dichiariamo derivato.
    ocf, inv = out.get("flusso_cassa_operativo"), out.get("investimenti")
    if ocf and inv:
        if _distanza(inv["data"], ocf["data"]) <= GIORNI_TOLLERANZA:
            fcf = dict(ocf)
            fcf["valore"] = ocf["valore"] - inv["valore"]
            fcf["tag"] = f"{ocf['tag']} - {inv['tag']}"
            fcf["derivata"] = ("cassa operativa meno investimenti in immobilizzazioni: "
                               "la SEC non pubblica un flusso di cassa libero")
            out["flusso_cassa_libero"] = fcf
        else:
            avvisi.append("flusso di cassa libero non calcolato: cassa operativa e "
                          "investimenti sono di periodi diversi")
    elif ocf and not inv:
        avvisi.append("flusso di cassa libero non calcolato: manca la voce degli "
                      "investimenti in immobilizzazioni")

    valute = {v.get("unita") for v in out.values() if v.get("unita")}
    estranee = {u for u in valute if u not in (UNITA_SOLDI, UNITA_PER_AZIONE)}
    if estranee:
        avvisi.append(f"valori in {', '.join(sorted(estranee))}: non sono dollari, "
                      f"il confronto con Yahoo richiede un cambio")
    avvisi.extend(_disallineate(out, tipo))
    return out, avvisi


def _disallineate(metriche: dict, tipo: str) -> list[str]:
    """Quali metriche sono di un periodo piu' vecchio delle altre.

    Succede davvero, e va detto. Nei trimestrali di NVDA e Apple il rendiconto
    finanziario e' cumulato da inizio esercizio: l'unico periodo che dura un
    trimestre e' il primo, quindi la cassa operativa dell'ultimo trimestre
    semplicemente non esiste come dato a se' e il modulo riporta quella del
    trimestre buono, con la sua data. Chi legge "cassa operativa" accanto a
    "ricavi" ha diritto di sapere che non sono lo stesso trimestre.
    """
    date_ = {k: v.get("data") for k, v in metriche.items() if v.get("data")}
    if len(date_) < 2:
        return []
    piu_recente = max(date_.values())
    vecchie = sorted(k for k, d in date_.items()
                     if _distanza(d, piu_recente) > GIORNI_TOLLERANZA)
    if not vecchie:
        return []
    for k in vecchie:
        # un anno di ritardo non e' un disallineamento di calendario, e' un dato
        # vecchio: JPM ha l'ultimo `LongTermDebt` del 2013 (poi ha cambiato tag) e
        # chi prende il numero senza guardare la data si porta a casa un bilancio
        # di dodici anni fa
        metriche[k]["disallineata_da"] = piu_recente
        if _distanza(date_[k], piu_recente) > 365:
            metriche[k]["obsoleta"] = True
    etichetta = "annuale" if tipo == "annuale" else "trimestrale"
    return [f"periodo {etichetta} non allineato: {', '.join(vecchie)} vengono da un "
            f"bilancio precedente ({', '.join(date_[k] for k in vecchie)}), non dal "
            f"{piu_recente} come le altre voci"]


def _valuta(metriche: dict) -> str | None:
    for nome in ("ricavi", "utile_netto", "patrimonio_netto"):
        u = (metriche.get(nome) or {}).get("unita")
        if u:
            return u
    return None


# ------------------------------------------------------------------ confronto
def _metriche_yahoo(dati_yahoo: dict | None, periodo: str) -> dict[str, dict]:
    """Normalizza quello che arriva da Yahoo.

    Accetta due forme: l'uscita di `providers.Yahoo.statements()` (chiavi
    `annualTotalRevenue`... con la serie di punti) oppure un dizionario piatto
    `{"ricavi": 215938000000}` / `{"ricavi": {"valore": ..., "data": ...}}`, che
    e' comodo per i controlli automatici e per chi ha gia' i numeri in mano.
    """
    if not isinstance(dati_yahoo, dict):
        return {}
    chiavi = CHIAVI_YAHOO.get(periodo, {})
    pare_statements = any(k in dati_yahoo for k in list(CHIAVI_YAHOO["annuali"].values())
                          + list(CHIAVI_YAHOO["trimestrali"].values()))
    out: dict[str, dict] = {}
    if pare_statements:
        for metrica, chiave in chiavi.items():
            serie = dati_yahoo.get(chiave)
            if not isinstance(serie, list) or not serie:
                continue
            punti = [p for p in serie if isinstance(p, dict) and p.get("value") is not None]
            if not punti:
                continue
            p = sorted(punti, key=lambda x: str(x.get("date") or ""))[-1]
            out[metrica] = {"valore": float(p["value"]), "data": p.get("date"),
                            "unita": p.get("currency"), "chiave": chiave}
        return out
    for metrica, v in dati_yahoo.items():
        if isinstance(v, dict) and v.get("valore") is not None:
            out[metrica] = {"valore": float(v["valore"]), "data": v.get("data"),
                            "unita": v.get("unita"), "chiave": v.get("chiave")}
        elif isinstance(v, (int, float)):
            out[metrica] = {"valore": float(v), "data": None, "unita": None,
                            "chiave": None}
    return out


def _verdetto(scostamento: float) -> str:
    a = abs(scostamento)
    if a <= SOGLIA_CONCORDANO:
        return "concordano"
    if a <= SOGLIA_ACCETTABILE:
        return "scostamento accettabile"
    return "non concordano"


def confronta(ticker: str, dati_yahoo: dict | None, dati_sec: dict | None = None,
              periodo: str = "annuali", provider: "Sec | None" = None) -> dict:
    """Mette le due fonti una accanto all'altra, metrica per metrica.

    Per ogni metrica: valore SEC, valore Yahoo, scostamento percentuale e un
    verdetto fra "concordano" (entro il 2%), "scostamento accettabile" (entro il
    10%), "non concordano" (oltre), "una delle due fonti manca il dato". In piu'
    una valutazione complessiva con un `fattore_fiducia` fra 0 e 1, da moltiplicare
    per la confidenza dell'analisi (`valuation.confidence`): due fonti che
    concordano non alzano la fiducia, due fonti che litigano la abbassano.

    `dati_yahoo` e' l'uscita di `providers.Yahoo.statements()` (vedi
    `_metriche_yahoo` per le forme accettate). `dati_sec` si puo' passare se e'
    gia' stato letto, altrimenti lo legge questa funzione.

    Nota sul debito: Yahoo a volte include nel suo "total debt" il leasing
    operativo non corrente, che nei depositi non e' debito finanziario
    (verificato: su NVDA e MSFT la differenza con la SEC e' **esattamente** il
    leasing, su AAPL no). Quando lo scostamento si spiega cosi', il confronto lo
    dice e non lo conta come disaccordo: e' una differenza di definizione, non un
    numero sbagliato. Abbassare la fiducia per una differenza di definizione
    sarebbe un falso allarme.
    """
    t = (ticker or "").upper().strip()
    if periodo not in CHIAVI_YAHOO:
        periodo = "annuali"
    if dati_sec is None:
        dati_sec = (provider or Sec()).bilanci(t)
    sec_metriche = (dati_sec or {}).get(periodo) or {}
    yh_metriche = _metriche_yahoo(dati_yahoo, periodo)

    out = {"ticker": t, "periodo": periodo,
           "fonte_sec": (dati_sec or {}).get("fonte", "SEC EDGAR XBRL (companyfacts)"),
           "fonte_yahoo": "Yahoo Finance (fundamentals-timeseries)",
           "confronto_possibile": bool(sec_metriche and yh_metriche),
           "metriche": {}}

    if not sec_metriche:
        out["complessivo"] = {
            "verdetto": "verifica non possibile",
            "motivo": (dati_sec or {}).get("motivo") or "bilanci SEC non disponibili",
            "fattore_fiducia": 1.0, "confrontate": 0, "concordano": 0,
            "accettabili": 0, "non_concordano": 0, "mancanti": len(yh_metriche),
            "fonte_unica": "Yahoo Finance"}
        return out
    if not yh_metriche:
        out["complessivo"] = {
            "verdetto": "verifica non possibile",
            "motivo": "nessuna metrica di Yahoo da confrontare",
            "fattore_fiducia": 1.0, "confrontate": 0, "concordano": 0,
            "accettabili": 0, "non_concordano": 0, "mancanti": len(sec_metriche),
            "fonte_unica": "SEC"}
        return out

    conta = {"concordano": 0, "scostamento accettabile": 0, "non concordano": 0,
             "una delle due fonti manca il dato": 0}
    non_spiegati: list[str] = []
    spiegati: list[str] = []
    accettabili: list[str] = []

    nomi = [m for m in METRICHE if m in sec_metriche or m in yh_metriche]
    for metrica in nomi:
        s, y = sec_metriche.get(metrica), yh_metriche.get(metrica)
        riga = {"sec": (s or {}).get("valore"), "yahoo": (y or {}).get("valore"),
                "data_sec": (s or {}).get("data"), "data_yahoo": (y or {}).get("data"),
                "tag_sec": (s or {}).get("tag"), "chiave_yahoo": (y or {}).get("chiave"),
                "scostamento_pct": None, "verdetto": None, "nota": None}
        if s and s.get("derivata"):
            riga["nota"] = f"SEC: {s['derivata']}"

        if not s or not y:
            riga["verdetto"] = "una delle due fonti manca il dato"
            manca = "SEC" if not s else "Yahoo"
            riga["nota"] = _nota_mancante(metrica, manca, riga["nota"])
        elif (s.get("data") and y.get("data")
              and _distanza(y["data"], s["data"]) > GIORNI_TOLLERANZA):
            # due periodi diversi non si confrontano: sarebbe un falso disaccordo
            riga["verdetto"] = "una delle due fonti manca il dato"
            riga["nota"] = (f"periodi non confrontabili: la SEC chiude al "
                            f"{s['data']}, Yahoo al {y['data']} "
                            f"({_distanza(y['data'], s['data'])} giorni di "
                            f"distanza). Una delle due non ha ancora pubblicato "
                            f"l'ultimo periodo")
        elif y["valore"] == 0:
            riga["verdetto"] = "una delle due fonti manca il dato"
            riga["nota"] = "Yahoo riporta zero: scostamento non calcolabile"
        else:
            scost = s["valore"] / abs(y["valore"]) - 1
            riga["scostamento_pct"] = round(scost * 100, 2)
            riga["verdetto"] = _verdetto(scost)
            if riga["verdetto"] != "concordano" and metrica == "debito":
                spiegazione = _spiega_debito(s, y)
                if spiegazione:
                    riga["nota"] = spiegazione
                    riga["spiegato_da_definizione"] = True
        conta[riga["verdetto"]] = conta.get(riga["verdetto"], 0) + 1
        if riga["verdetto"] in ("non concordano", "scostamento accettabile"):
            if riga.get("spiegato_da_definizione"):
                spiegati.append(metrica)
            elif riga["verdetto"] == "non concordano":
                non_spiegati.append(metrica)
            else:
                accettabili.append(metrica)
        out["metriche"][metrica] = riga

    confrontate = (conta["concordano"] + conta["scostamento accettabile"]
                   + conta["non concordano"])
    out["complessivo"] = _complessivo(conta, confrontate, non_spiegati, spiegati,
                                      accettabili)
    return out


def _nota_mancante(metrica: str, manca: str, nota: str | None) -> str:
    """Perche' manca, quando si sa. Un "dato assente" senza motivo e' un buco
    silenzioso, ed e' esattamente quello che questo modulo deve evitare."""
    if metrica == "flusso_cassa_operativo" and manca == "Yahoo":
        return ("Yahoo in questa configurazione non espone il flusso di cassa "
                "operativo (pubblica il flusso di cassa libero): confronto "
                "impossibile, non disaccordo")
    if metrica == "patrimonio_netto" and manca == "Yahoo":
        return ("Yahoo non pubblica il patrimonio netto trimestrale in questa "
                "configurazione")
    return nota or f"il dato manca su {manca}"


def _spiega_debito(s: dict, y: dict) -> str | None:
    """Lo scostamento sul debito si spiega col leasing? Se si', e' una differenza
    di definizione fra le due fonti, non un numero sbagliato."""
    con_leasing = s.get("debito_incl_leasing")
    if not con_leasing or not y.get("valore"):
        return None
    scost = con_leasing / abs(y["valore"]) - 1
    if abs(scost) <= SOGLIA_CONCORDANO:
        return (f"differenza di definizione, non di dato: il debito ufficiale e' "
                f"{s['valore']:,.0f}, col leasing non corrente diventa "
                f"{con_leasing:,.0f} e coincide con Yahoo ({scost * 100:+.2f}%). "
                f"Yahoo include il leasing nel debito totale, i depositi no")
    return None


def _complessivo(conta: dict, confrontate: int, non_spiegati: list[str],
                 spiegati: list[str], accettabili: list[str]) -> dict:
    """La riga che serve a chi deve decidere: quanta fiducia meritano i numeri.

    Il fattore si moltiplica per la confidenza calcolata altrove. Due fonti che
    concordano non la alzano (concordare e' il minimo che si aspetta), due fonti
    che litigano la abbassano, e piu' metriche litigano piu' scende.

    Le differenze spiegate da una definizione diversa (il leasing dentro o fuori
    dal debito) non abbassano la fiducia, ma non vengono nemmeno nascoste: il
    motivo le nomina. Scrivere "tutto coincide entro il 2%" quando una metrica sta
    al 23% sarebbe una bugia comoda.
    """
    if not confrontate:
        return {"verdetto": "verifica non possibile", "fattore_fiducia": 1.0,
                "motivo": "nessuna metrica presente su entrambe le fonti",
                "confrontate": 0, "concordano": 0, "accettabili": 0,
                "non_concordano": 0,
                "mancanti": conta.get("una delle due fonti manca il dato", 0)}
    n = len(non_spiegati)
    coda = (f"; {len(spiegati)} differisce solo per come le due fonti la definiscono "
            f"({', '.join(spiegati)})" if spiegati else "")
    if n == 0 and not accettabili and not spiegati:
        verdetto = "i conti concordano"
        fattore, motivo = 1.0, (f"tutte e {confrontate} le metriche confrontabili "
                                f"coincidono entro il 2% fra deposito ufficiale e "
                                f"Yahoo")
    elif n == 0 and not accettabili:
        verdetto = "i conti concordano"
        fattore = 1.0
        motivo = (f"{conta['concordano']} metriche su {confrontate} coincidono entro "
                  f"il 2%{coda}")
    elif n == 0:
        verdetto = "i conti concordano, con scostamenti minori"
        fattore = 0.95
        motivo = (f"{len(accettabili)} metriche su {confrontate} differiscono fra il "
                  f"2% e il 10% ({', '.join(accettabili)}): arrotondamenti e perimetri "
                  f"di consolidamento, nessun numero in contrasto{coda}")
    elif n == 1:
        verdetto = "una metrica non concorda"
        fattore = 0.8
        motivo = (f"{non_spiegati[0]}: le due fonti danno numeri diversi oltre il "
                  f"10% e la differenza non si spiega con una definizione. "
                  f"Fiducia abbassata")
    else:
        verdetto = "le due fonti non concordano"
        fattore = 0.6
        motivo = (f"{n} metriche su {confrontate} in contrasto oltre il 10% "
                  f"({', '.join(non_spiegati)}): i numeri di questa societa' vanno "
                  f"guardati a mano prima di usarli. Fiducia abbassata")
    return {"verdetto": verdetto, "fattore_fiducia": fattore, "motivo": motivo,
            "confrontate": confrontate, "concordano": conta["concordano"],
            "accettabili": conta["scostamento accettabile"],
            "non_concordano": conta["non concordano"],
            "non_concordano_non_spiegati": n,
            "mancanti": conta.get("una delle due fonti manca il dato", 0),
            "metriche_in_contrasto": non_spiegati,
            "metriche_con_scostamento": accettabili,
            "differenze_di_definizione": spiegati}


# ------------------------------------------------------- comodita' d'uso
def bilanci(ticker: str, provider: "Sec | None" = None) -> dict:
    """I bilanci ufficiali di un titolo. Mai un'eccezione, mai un buco muto."""
    return (provider or Sec()).bilanci(ticker)


def verifica(ticker: str, yahoo_provider=None, sec_provider: "Sec | None" = None,
             periodo: str = "annuali") -> dict:
    """Scorciatoia che fa tutto: prende i bilanci dalle due fonti e le confronta.

    `yahoo_provider` e' un `providers.Yahoo`; se manca se ne costruisce uno. Se
    Yahoo non risponde il confronto lo dichiara, non si ferma (OP-06).
    """
    sec_provider = sec_provider or Sec()
    dati_sec = sec_provider.bilanci(ticker)
    dati_yahoo = None
    try:
        from .providers import Yahoo
        y = yahoo_provider or Yahoo()
        dati_yahoo = y.statements(ticker)
    except Exception as e:
        # anche un errore di importazione o di rete resta dentro: il confronto
        # dira' "verifica non possibile" col motivo
        dati_sec.setdefault("avvisi", []).append(
            f"Yahoo non ha risposto: {type(e).__name__}")
    out = confronta(ticker, dati_yahoo, dati_sec=dati_sec, periodo=periodo,
                    provider=sec_provider)
    out["sec"] = dati_sec
    return out
