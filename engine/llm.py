"""Client Gemini (OP-07 chiuso: il provider LLM è Gemini API).

Sola libreria standard: una POST HTTPS con `urllib`, risposta in JSON forzata
dallo schema (`responseSchema`), cache su disco e fallback.

Tre modi di funzionare, nello stesso codice:

* **live** — c'è una chiave API (`GEMINI_API_KEY`) e si passa `--live`: le analisi
  qualitative le fa Gemini.
* **cache** — la risposta per quella stessa domanda è già su disco
  (`.llm_cache/`): si riusa, a costo zero. Serve a ripetere la demo identica e a
  non pagare due volte lo stesso ciclo.
* **offline** — nessuna chiave o nessuna rete: ogni funzione cade sul proprio
  nucleo quantitativo deterministico e lo dichiara. La demo resta eseguibile
  dietro un proxy aziendale, senza inventare numeri.

Ogni risposta del modello passa da una validazione (campi presenti, numeri nei
limiti attesi): un LLM che sbaglia formato o esce dal dominio viene scartato e
si usa il nucleo deterministico. Niente output del modello finisce nei conti
senza controllo.
"""

from __future__ import annotations

import hashlib
import json
import os
import ssl
import time
import urllib.error
import urllib.request
from pathlib import Path

DEFAULT_MODEL = "gemini-3.8-flash"
BASE_URL = "https://generativelanguage.googleapis.com/v1beta/models"
CACHE_DIR = Path(__file__).resolve().parent.parent / ".llm_cache"
# Sul piano gratuito una singola risposta può richiedere minuti: misurati 161 s
# sulla prima chiamata e 33 s sulle successive (gemini-3.8-flash, ottobre 2026).
# Con un timeout corto si butta via una chiamata già fatta e si ricade sul
# calcolo senza motivo.
TIMEOUT_S = 240
MAX_ATTEMPTS = 3                 # tentativi per chiamata, sugli errori passeggeri
MAX_CONSECUTIVE_FAILURES = 3     # oltre i quali il ciclo smette di chiamare il modello

SYSTEM_INSTRUCTION = (
    "Sei l'analista quantitativo di AI Market Scout, un servizio di supporto alle decisioni "
    "di investimento per clienti retail italiani. Lavori solo sui dati che ti vengono passati: "
    "non inventi numeri, non citi fonti che non hai, non usi conoscenze di mercato successive "
    "ai dati forniti. Se un dato manca, abbassi la confidenza invece di indovinare. "
    "Scrivi in italiano. Non dai mai un consiglio personalizzato e non prometti rendimenti."
)


class Gemini:
    """Un solo punto di contatto con il modello, per poterlo spegnere, misurare
    e sostituire senza toccare gli agenti."""

    def __init__(self, enabled: bool = False, api_key: str | None = None,
                 model: str | None = None, use_cache: bool = True,
                 pace_s: float = 0.0, retry_429_s: float = 15.0,
                 circuit_cooldown_s: float = 120.0, budget: int | None = None):
        self.api_key = api_key or os.environ.get("GEMINI_API_KEY", "").strip()
        self.model = (model or os.environ.get("GEMINI_MODEL", "").strip()
                      or DEFAULT_MODEL)
        self.enabled = bool(enabled and self.api_key)
        self.use_cache = use_cache
        # `pace_s` serve sul piano gratuito, dove il limite è di poche richieste
        # al minuto: distanzia le chiamate invece di farsi rifiutare.
        self.pace_s = pace_s
        self.retry_429_s = retry_429_s
        # Il ragionamento interno del modello resta spento (DEMO-33). Si può
        # riaccendere con GEMINI_THINKING=1 per confrontare la qualità: serve
        # alzare anche i tetti di token, altrimenti le risposte tornano vuote.
        # Si spegne da sé anche al primo rifiuto: non tutti i modelli accettano
        # il campo.
        self.thinking_off = os.environ.get("GEMINI_THINKING", "").strip() not in ("1", "true")
        # Dopo l'apertura del circuito si riprova una volta passato questo tempo:
        # sul piano gratuito tre rifiuti di fila sono spesso solo il limite di
        # frequenza, e spegnere il modello per tutto il ciclo sarebbe eccessivo.
        self.circuit_cooldown_s = circuit_cooldown_s
        # Quante chiamate può fare questo ciclo (None = nessun tetto).
        self.budget = budget
        self._last_call = 0.0
        self._consecutive_failures = 0
        self.circuit_open = False
        self._circuit_until = 0.0
        self.stats = {"live": 0, "cached": 0, "errors": 0, "skipped": 0, "retries": 0,
                      "prompt_tokens": 0, "output_tokens": 0, "circuit_opens": 0,
                      "over_budget": 0}
        self.log: list[dict] = []
        self.last_error: str | None = None
        self.suggested_model: str | None = None
        # Riempito quando l'API dichiara una quota superata: è l'informazione che
        # serve per decidere quanti strumenti far analizzare dal modello.
        self.quota_error: str | None = None
        if self.use_cache:
            CACHE_DIR.mkdir(exist_ok=True)

    # ------------------------------------------------------------------ util
    @property
    def mode(self) -> str:
        if self.enabled:
            return "live"
        if self.api_key:
            return "offline (chiave presente, modalità live non richiesta)"
        return "offline (nessuna chiave GEMINI_API_KEY)"

    def _spent(self) -> int:
        """Chiamate che hanno raggiunto l'API in questo ciclo: la quota conta i
        tentativi, non le risposte buone."""
        return self.stats["live"] + self.stats["errors"]

    def budget_left(self) -> int | None:
        return None if self.budget is None else max(0, self.budget - self._spent())

    def _cache_path(self, key: str) -> Path:
        h = hashlib.sha1(f"{self.model}|{key}".encode("utf-8")).hexdigest()[:20]
        return CACHE_DIR / f"{h}.json"

    def _read_cache(self, key: str):
        if not self.use_cache:
            return None
        p = self._cache_path(key)
        if p.exists():
            try:
                return json.loads(p.read_text(encoding="utf-8"))["data"]
            except Exception:
                return None
        return None

    def _write_cache(self, key: str, data) -> None:
        if not self.use_cache:
            return
        try:
            self._cache_path(key).write_text(
                json.dumps({"key": key, "model": self.model, "data": data},
                           ensure_ascii=False), encoding="utf-8")
        except Exception:
            pass

    # ----------------------------------------------------------------- call
    def generate_json(self, prompt: str, schema: dict, cache_key: str,
                      temperature: float = 0.2, max_output_tokens: int = 1200):
        """Restituisce un dict dal modello, oppure None (e chi chiama ricade sul
        nucleo deterministico). Non solleva mai: un ciclo di scansione non si
        ferma perché un modello non risponde (OP-06)."""
        cached = self._read_cache(cache_key)
        if cached is not None:
            self.stats["cached"] += 1
            self.log.append({"key": cache_key, "status": "cache", "ms": 0})
            return cached
        if not self.enabled:
            self.stats["skipped"] += 1
            return None
        # Tetto di chiamate per ciclo: la quota del piano gratuito è giornaliera,
        # quindi per fare due cicli al giorno ognuno deve sapere quanto può
        # spendere. Si contano i tentativi arrivati all'API, non i successi.
        if self.budget is not None and self._spent() >= self.budget:
            self.stats["over_budget"] += 1
            self.stats["skipped"] += 1
            return None
        if self.circuit_open:
            # passato il tempo di attesa si concede una chiamata di prova: se
            # va a buon fine il circuito si richiude e il ciclo riprende con
            # le analisi del modello invece di finire tutto sul calcolo.
            if time.monotonic() < self._circuit_until:
                self.stats["skipped"] += 1
                return None
            self.circuit_open = False
            self._consecutive_failures = MAX_CONSECUTIVE_FAILURES - 1

        body = {
            "systemInstruction": {"parts": [{"text": SYSTEM_INSTRUCTION}]},
            "contents": [{"role": "user", "parts": [{"text": prompt}]}],
            "generationConfig": {
                "temperature": temperature,
                "maxOutputTokens": max_output_tokens,
                "responseMimeType": "application/json",
                "responseSchema": schema,
            },
        }
        # I modelli Gemini 3 ragionano per impostazione predefinita, e i token del
        # ragionamento escono dallo stesso budget della risposta: con un budget
        # stretto la risposta torna VUOTA (finishReason MAX_TOKENS) e il ciclo
        # ricadrebbe sul calcolo senza che si capisca perché. Qui il ragionamento
        # si spegne: il lavoro di giudizio è già guidato dal prompt e dallo schema.
        if self.thinking_off:
            body["generationConfig"]["thinkingConfig"] = {"thinkingBudget": 0}
        url = f"{BASE_URL}/{self.model}:generateContent"
        t0 = time.perf_counter()
        payload = None
        for attempt in range(1, MAX_ATTEMPTS + 1):
            if self.pace_s and self._last_call:
                wait = self.pace_s - (time.monotonic() - self._last_call)
                if wait > 0:
                    time.sleep(wait)
            req = urllib.request.Request(
                url, data=json.dumps(body).encode("utf-8"),
                headers={"Content-Type": "application/json",
                         "x-goog-api-key": self.api_key},
                method="POST")
            try:
                # Su Windows il contesto di default carica la root store di
                # sistema: dietro un proxy con ispezione TLS funziona se la CA
                # aziendale è installata (nessuna verifica disabilitata qui).
                ctx = ssl.create_default_context()
                with urllib.request.urlopen(req, timeout=TIMEOUT_S, context=ctx) as resp:
                    payload = json.loads(resp.read().decode("utf-8"))
                self._last_call = time.monotonic()
                break
            except urllib.error.HTTPError as e:
                # 800 e non 400: nel messaggio dei 429 c'è la quota superata, che
                # è l'informazione utile e sta in fondo.
                detail = e.read().decode("utf-8", "replace")[:800]
                self.last_error = f"HTTP {e.code}: {detail}"
                if e.code == 429:
                    self.quota_error = quota_detail(detail) or self.quota_error
                if e.code == 404:
                    # l'API dice da sé quale modello usare: lo si ripete all'utente
                    suggerito = suggested_model(detail)
                    if suggerito:
                        self.suggested_model = suggerito
                        self.last_error += (f"\nIl modello da usare sembra essere "
                                            f"{suggerito}.")
                self._last_call = time.monotonic()
                # 429 = quota o limite di frequenza del piano; 503 = il modello è
                # sovraccarico, cosa frequente e passeggera. Si riprova con attese
                # crescenti, poi si cede al calcolo: un ciclo non si blocca per un
                # servizio occupato, ma non lo si abbandona al primo rifiuto.
                attesa = self._retry_wait(e.code, attempt)
                if attesa is not None and attempt < MAX_ATTEMPTS:
                    self.stats["retries"] += 1
                    self.log.append({"key": cache_key, "status": f"http {e.code}, "
                                     f"riprovo tra {attesa:.0f}s", "ms": 0})
                    if attesa:
                        time.sleep(attesa)
                    continue
                # un modello che non conosce thinkingConfig: si riprova senza
                if (e.code == 400 and attempt == 1 and self.thinking_off
                        and "thinking" in detail.lower()):
                    self.thinking_off = False
                    body["generationConfig"].pop("thinkingConfig", None)
                    self.stats["retries"] += 1
                    continue
                self.stats["errors"] += 1
                self.log.append({"key": cache_key, "status": f"http {e.code}",
                                 "ms": round((time.perf_counter() - t0) * 1000, 1)})
                self._fail()
                return None
            except Exception as e:  # rete, DNS, TLS, timeout
                self.last_error = f"{type(e).__name__}: {e}"
                self.stats["errors"] += 1
                self.log.append({"key": cache_key, "status": "errore",
                                 "ms": round((time.perf_counter() - t0) * 1000, 1)})
                self._fail()
                return None
        if payload is None:
            return None

        ms = round((time.perf_counter() - t0) * 1000, 1)
        usage = payload.get("usageMetadata", {})
        self.stats["prompt_tokens"] += usage.get("promptTokenCount", 0)
        self.stats["output_tokens"] += usage.get("candidatesTokenCount", 0)
        try:
            text = payload["candidates"][0]["content"]["parts"][0]["text"]
            data = json.loads(text)
        except Exception as e:
            motivo = (payload.get("candidates") or [{}])[0].get("finishReason", "")
            if motivo == "MAX_TOKENS":
                # risposta troncata: il tetto di token non bastava
                self.last_error = (f"risposta troncata dal tetto di "
                                   f"{max_output_tokens} token di uscita "
                                   f"({usage.get('thoughtsTokenCount', 0)} usati per "
                                   f"il ragionamento)")
            else:
                self.last_error = f"risposta non interpretabile: {type(e).__name__}"
            self.stats["errors"] += 1
            self.log.append({"key": cache_key, "status": "formato", "ms": ms})
            self._fail()
            return None

        self._consecutive_failures = 0
        self.stats["live"] += 1
        self.log.append({"key": cache_key, "status": "live", "ms": ms,
                         "tokens": usage.get("totalTokenCount", 0)})
        self._write_cache(cache_key, data)
        return data

    def _retry_wait(self, code: int, attempt: int) -> float | None:
        """Secondi da aspettare prima di riprovare, o None se non vale la pena.
        Un 400 o un 404 non migliorano riprovando; un 429 e un 503 sì."""
        # attesa None = non riprovare; attesa 0 = riprova subito
        if self.retry_429_s is None:
            return None
        if code == 429:
            return self.retry_429_s * attempt
        if code in (500, 502, 503, 504):
            # sovraccarico del servizio: attese brevi e crescenti
            return min(self.retry_429_s, 5.0) * attempt
        return None

    def _fail(self) -> None:
        """Dopo alcuni errori di fila si smette di chiamare il modello: con un
        limite di frequenza esaurito, insistere allungherebbe la scansione di
        minuti senza risultato (OP-06). Non è però definitivo: passato
        `circuit_cooldown_s` si riprova una volta."""
        self._consecutive_failures += 1
        if self._consecutive_failures >= MAX_CONSECUTIVE_FAILURES:
            if not self.circuit_open:
                self.stats["circuit_opens"] += 1
            self.circuit_open = True
            self._circuit_until = time.monotonic() + self.circuit_cooldown_s

    # ------------------------------------------------------------ controllo
    def check(self) -> dict:
        """Prova di connessione, usata da `cli.py llm-check`."""
        if not self.api_key:
            return {"ok": False, "detail": "GEMINI_API_KEY non impostata."}
        saved, self.enabled, self.use_cache = self.use_cache, True, False
        out = self.generate_json(
            "Rispondi esattamente con {\"ok\": true, \"nota\": \"connessione riuscita\"}.",
            {"type": "OBJECT", "properties": {"ok": {"type": "BOOLEAN"},
                                              "nota": {"type": "STRING"}},
             "required": ["ok", "nota"]},
            cache_key="healthcheck", max_output_tokens=120)
        self.use_cache = saved
        if out is None:
            return {"ok": False, "detail": self.last_error or "nessuna risposta",
                    "model": self.model, "suggested": self.suggested_model}
        return {"ok": True, "detail": out.get("nota", ""), "model": self.model,
                "tokens": self.stats["prompt_tokens"] + self.stats["output_tokens"]}


# --------------------------------------------------------------- validazione
def quota_detail(messaggio: str) -> str | None:
    """Estrae dal messaggio di un 429 la quota superata, in forma leggibile:
    l'API dichiara metrica, limite e modello, ed è l'unico modo di sapere quante
    chiamate concede il piano gratuito (cambia nel tempo, senza preavviso)."""
    import re as _re
    metrica = _re.search(r"Quota exceeded for metric:\s*([^\s,]+)", messaggio)
    limite = _re.search(r"limit:\s*([0-9]+)", messaggio)
    if not (metrica or limite):
        return None
    pezzi = []
    if limite:
        pezzi.append(f"limite dichiarato dall'API: {limite.group(1)} richieste")
    if metrica:
        nome = metrica.group(1).split("/")[-1]
        pezzi.append(f"metrica {nome}")
    return "; ".join(pezzi)


def suggested_model(messaggio: str) -> str | None:
    """Estrae dal messaggio di errore il modello che l'API consiglia."""
    import re as _re
    m = _re.search(r"use (?:model|models)[/ ]+([a-zA-Z0-9.\-]+)", messaggio)
    if m:
        return m.group(1).strip(".,)")
    m = _re.search(r"models/([a-zA-Z0-9.\-]+) for the latest", messaggio)
    return m.group(1) if m else None


def num(value, lo: float, hi: float, default=None):
    """Numero del modello accettato solo dentro il dominio atteso."""
    try:
        v = float(value)
    except (TypeError, ValueError):
        return default
    if v != v or v < lo or v > hi:          # NaN o fuori limiti
        return default
    return v


def score_0_100(value, default=None):
    v = num(value, 0, 100, None)
    return int(round(v)) if v is not None else default


def text(value, max_len: int = 600, default: str = "") -> str:
    if not isinstance(value, str):
        return default
    v = " ".join(value.split())
    return v[:max_len] if v else default


def str_list(value, max_items: int = 5, max_len: int = 300) -> list[str]:
    if not isinstance(value, list):
        return []
    out = []
    for item in value[:max_items]:
        t = text(item, max_len)
        if t:
            out.append(t)
    return out
