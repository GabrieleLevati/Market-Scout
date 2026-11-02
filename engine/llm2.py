"""Il secondo modello: un provider compatibile con l'interfaccia OpenAI.

Perche' un secondo modello. Gemini e' il piu' bravo ma il suo piano gratuito
concede una ventina di chiamate al giorno: coprono due strumenti su
quarantotto. Un secondo provider gratuito fa il volume, e quando la quota di
Gemini finisce il ciclo non cade sul solo calcolo.

Perche' COMPATIBILE OPENAI e non "un adattatore per Groq". Groq, Cerebras e
OpenRouter parlano tutti lo stesso dialetto (`POST /chat/completions`, campo
`messages`, risposta in `choices[0].message.content`). Scrivendo l'adattatore
su quel dialetto invece che su un fornitore, cambiare fornitore diventa
cambiare due variabili d'ambiente, e non riscrivere un file.

Si configura con:
    LLM2_BASE    indirizzo base, per esempio https://api.groq.com/openai/v1
    LLM2_KEY     la chiave
    LLM2_MODEL   il nome del modello
Per comodita', se c'e' GROQ_API_KEY e non c'e' LLM2_KEY, base e modello
prendono i valori di Groq.

Una differenza da Gemini che conta: Gemini accetta uno `responseSchema` e
garantisce la forma della risposta. Qui si puo' solo chiedere "rispondi in
JSON" e descrivere lo schema nel testo. Quindi la validazione che il progetto
ha sempre fatto sulle uscite del modello (campi presenti, numeri nel dominio
atteso) qui non e' una precauzione: e' l'unica difesa.
"""

from __future__ import annotations

import json
import os
import ssl
import time
import urllib.error
import urllib.request

from .llm import CACHE_DIR, MAX_ATTEMPTS, MAX_CONSECUTIVE_FAILURES, SYSTEM_INSTRUCTION
from .llm import TIMEOUT_S, quota_detail

__all__ = ["Compatibile", "Coppia", "PRONTI", "MAX_ATTEMPTS"]

# Valori pronti per i fornitori verificati raggiungibili da questa rete.
# Chi siamo, per chi ci chiede di presentarci. Serve davvero: vedi il commento
# sulla richiesta, piu' sotto.
USER_AGENT = "AI-Market-Scout-demo/0.1 (uso personale)"

PRONTI = {
    "groq": ("https://api.groq.com/openai/v1", "llama-3.3-70b-versatile"),
    "cerebras": ("https://api.cerebras.ai/v1", "llama3.1-70b"),
    "openrouter": ("https://openrouter.ai/api/v1", "google/gemma-4-31b-it:free"),
}


# Nomi che NON sono modelli di testo: trascrizione, sintesi vocale, immagini,
# filtri di sicurezza. Se il modello va scelto da un elenco, questi vanno via.
NON_DI_TESTO = ("whisper", "tts", "guard", "vision", "embed", "rerank",
                "transcribe", "image", "audio", "moderation")

# In che ordine preferirli, a parita' di tutto: prima quelli grossi e
# generalisti, perche' il lavoro qui e' giudizio e non chiacchiera.
PREFERENZE = ("versatile", "70b", "-large", "32b", "instruct", "8b")


def scegli_modello(nomi: list[str]) -> str | None:
    """Da un elenco di modelli, quello piu' adatto a questo lavoro.

    Serve perche' i nomi dei modelli invecchiano: Groq ha ritirato
    llama-3.3-70b-versatile e Google gemini-2.5-flash nello spazio di pochi
    mesi. Scrivere un nome a mano vuol dire mettere nel programma una data di
    scadenza che nessuno conosce. Meglio chiedere l'elenco e scegliere.
    """
    testo = [n for n in nomi if not any(x in n.lower() for x in NON_DI_TESTO)]
    if not testo:
        return None
    for chiave in PREFERENZE:
        for n in testo:
            if chiave in n.lower():
                return n
    return sorted(testo)[0]


def _schema_a_parole(schema: dict) -> str:
    """Lo schema descritto in una riga, da mettere nel prompt.

    Serve perche' questi provider non accettano uno schema formale: l'unico
    modo di chiedere la forma giusta e' scriverla nella domanda.
    """
    prop = (schema or {}).get("properties") or {}
    richiesti = set((schema or {}).get("required") or [])
    pezzi = []
    for nome, spec in prop.items():
        tipo = {"NUMBER": "numero", "INTEGER": "numero intero", "STRING": "testo",
                "BOOLEAN": "true o false", "ARRAY": "elenco",
                "number": "numero", "integer": "numero intero", "string": "testo",
                "boolean": "true o false", "array": "elenco",
                }.get(str(spec.get("type")), "valore")
        pezzi.append(f'"{nome}" ({tipo}{"" if nome in richiesti else ", facoltativo"})')
    return "; ".join(pezzi)


class Compatibile:
    """Un modello raggiunto con l'interfaccia OpenAI. Stessa superficie della
    classe Gemini, cosi' gli agenti non sanno quale dei due stanno usando."""

    def __init__(self, enabled: bool = False, api_key: str | None = None,
                 base: str | None = None, model: str | None = None,
                 use_cache: bool = True, pace_s: float = 0.0,
                 retry_wait_s: float = 5.0, budget: int | None = None):
        fornitore = (os.environ.get("LLM2_FORNITORE") or "groq").strip().lower()
        base_pronta, modello_pronto = PRONTI.get(fornitore, PRONTI["groq"])
        self.api_key = (api_key or os.environ.get("LLM2_KEY", "").strip()
                        or os.environ.get("GROQ_API_KEY", "").strip())
        self.base = (base or os.environ.get("LLM2_BASE", "").strip()
                     or base_pronta).rstrip("/")
        self.model = (model or os.environ.get("LLM2_MODEL", "").strip()
                      or modello_pronto)
        self.enabled = bool(enabled and self.api_key)
        self.use_cache = use_cache
        self.pace_s = pace_s
        self.retry_wait_s = retry_wait_s
        self.budget = budget
        self._last_call = 0.0
        self._consecutive_failures = 0
        self.circuit_open = False
        self.stats = {"live": 0, "cached": 0, "errors": 0, "skipped": 0, "retries": 0,
                      "prompt_tokens": 0, "output_tokens": 0, "circuit_opens": 0,
                      "over_budget": 0}
        self.log: list[dict] = []
        self.last_error: str | None = None
        self.quota_error: str | None = None
        # Riempito quando il modello configurato non esiste piu' e il
        # programma ne trova uno valido da se'.
        self.suggested_model: str | None = None
        if self.use_cache:
            CACHE_DIR.mkdir(exist_ok=True)

    # ------------------------------------------------------------------ util
    @property
    def mode(self) -> str:
        if self.enabled:
            return f"live ({self.base.split('//')[-1].split('/')[0]})"
        if self.api_key:
            return "offline (chiave presente, modalità live non richiesta)"
        return "offline (nessuna chiave LLM2_KEY)"

    def _spent(self) -> int:
        return self.stats["live"] + self.stats["errors"]

    def modelli(self) -> list[str]:
        """L'elenco dei modelli che questa chiave puo' usare, o vuoto."""
        req = urllib.request.Request(
            f"{self.base}/models",
            headers={"Authorization": f"Bearer {self.api_key}",
                     "User-Agent": USER_AGENT})
        try:
            ctx = ssl.create_default_context()
            with urllib.request.urlopen(req, timeout=30, context=ctx) as r:
                dati = json.loads(r.read().decode("utf-8"))
            voci = dati.get("data") or dati.get("models") or []
            return sorted(str(m.get("id") or m.get("name") or "") for m in voci
                          if (m.get("id") or m.get("name")))
        except Exception as e:
            self.last_error = f"elenco modelli non disponibile: {type(e).__name__}"
            return []

    def _cache_path(self, key: str):
        import hashlib
        h = hashlib.sha1(f"{self.model}|{key}".encode("utf-8")).hexdigest()[:20]
        return CACHE_DIR / f"c2_{h}.json"

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

    def _fail(self) -> None:
        self._consecutive_failures += 1
        if self._consecutive_failures >= MAX_CONSECUTIVE_FAILURES:
            if not self.circuit_open:
                self.stats["circuit_opens"] += 1
            self.circuit_open = True

    # ----------------------------------------------------------------- call
    def generate_json(self, prompt: str, schema: dict, cache_key: str,
                      temperature: float = 0.2, max_output_tokens: int = 1200):
        cached = self._read_cache(cache_key)
        if cached is not None:
            self.stats["cached"] += 1
            self.log.append({"key": cache_key, "status": "cache", "ms": 0})
            return cached
        if not self.enabled or self.circuit_open:
            self.stats["skipped"] += 1
            return None
        if self.budget is not None and self._spent() >= self.budget:
            self.stats["over_budget"] += 1
            self.stats["skipped"] += 1
            return None

        forma = _schema_a_parole(schema)
        istruzioni = (f"{SYSTEM_INSTRUCTION}\n\nRispondi SOLO con un oggetto JSON, "
                      f"senza testo prima o dopo e senza blocchi di codice. "
                      f"Le chiavi devono essere esattamente queste: {forma}.")
        body = {
            "model": self.model,
            "messages": [{"role": "system", "content": istruzioni},
                         {"role": "user", "content": prompt}],
            "temperature": temperature,
            "max_tokens": max_output_tokens,
            "response_format": {"type": "json_object"},
        }
        url = f"{self.base}/chat/completions"
        t0 = time.perf_counter()
        payload = None
        for attempt in range(1, MAX_ATTEMPTS + 1):
            if self.pace_s and self._last_call:
                attesa = self.pace_s - (time.monotonic() - self._last_call)
                if attesa > 0:
                    time.sleep(attesa)
            # Lo User-Agent non e' una formalita': Groq sta dietro Cloudflare,
            # che rifiuta con 403 (errore 1010) chi si presenta come
            # "Python-urllib", cioe' il default di urllib. Lo stesso problema
            # che la SEC pone in modo esplicito, qui arriva senza spiegazioni:
            # una richiesta identica passa o non passa solo per questa riga.
            req = urllib.request.Request(
                url, data=json.dumps(body).encode("utf-8"),
                headers={"Content-Type": "application/json",
                         "User-Agent": USER_AGENT,
                         "Authorization": f"Bearer {self.api_key}"},
                method="POST")
            try:
                ctx = ssl.create_default_context()
                with urllib.request.urlopen(req, timeout=TIMEOUT_S, context=ctx) as resp:
                    payload = json.loads(resp.read().decode("utf-8"))
                self._last_call = time.monotonic()
                break
            except urllib.error.HTTPError as e:
                detail = e.read().decode("utf-8", "replace")[:800]
                self.last_error = f"HTTP {e.code}: {detail}"
                if e.code == 429:
                    self.quota_error = quota_detail(detail) or self.quota_error
                self._last_call = time.monotonic()
                # Modello ritirato: non e' un guasto passeggero, e riprovare
                # lo stesso nome non servirebbe. Si chiede l'elenco, si
                # sceglie, e si riprova UNA volta col nome nuovo. Senza
                # questo, il giorno in cui il fornitore ritira un modello il
                # ciclo smette di usare l'AI e nessuno capisce perche'.
                if (e.code == 404 and "model" in detail.lower()
                        and not self.suggested_model):
                    disponibili = self.modelli()
                    scelto = scegli_modello(disponibili)
                    if scelto and scelto != self.model:
                        self.suggested_model = scelto
                        self.last_error += (
                            f"\nIl modello {self.model} non esiste piu'. "
                            f"Uso {scelto}. Per fissarlo: "
                            f'setx LLM2_MODEL "{scelto}"')
                        self.model = scelto
                        body["model"] = scelto
                        self.stats["retries"] += 1
                        continue
                riprovabile = e.code == 429 or e.code >= 500
                # attesa 0 vuol dire "riprova subito", non "non riprovare":
                # per non riprovare si passa None. La differenza conta, perche'
                # chi mette 0 per far presto non vuole perdere i ritentativi.
                if (riprovabile and attempt < MAX_ATTEMPTS
                        and self.retry_wait_s is not None):
                    self.stats["retries"] += 1
                    if self.retry_wait_s:
                        time.sleep(self.retry_wait_s * attempt)
                    continue
                self.stats["errors"] += 1
                self.log.append({"key": cache_key, "status": f"http {e.code}",
                                 "ms": round((time.perf_counter() - t0) * 1000, 1)})
                self._fail()
                return None
            except Exception as e:
                self.last_error = f"{type(e).__name__}: {e}"
                self.stats["errors"] += 1
                self.log.append({"key": cache_key, "status": "errore",
                                 "ms": round((time.perf_counter() - t0) * 1000, 1)})
                self._fail()
                return None
        if payload is None:
            return None

        ms = round((time.perf_counter() - t0) * 1000, 1)
        uso = payload.get("usage") or {}
        self.stats["prompt_tokens"] += uso.get("prompt_tokens", 0) or 0
        self.stats["output_tokens"] += uso.get("completion_tokens", 0) or 0
        try:
            testo = payload["choices"][0]["message"]["content"]
            # Qualche modello incornicia il JSON in un blocco di codice anche
            # quando gli si dice di non farlo: si toglie la cornice invece di
            # buttare via una risposta buona.
            pulito = testo.strip()
            if pulito.startswith("```"):
                pulito = pulito.split("```")[1]
                if pulito.startswith("json"):
                    pulito = pulito[4:]
            data = json.loads(pulito.strip())
            if not isinstance(data, dict):
                raise ValueError("la risposta non e' un oggetto")
        except Exception as e:
            self.last_error = f"risposta non interpretabile: {type(e).__name__}"
            self.stats["errors"] += 1
            self.log.append({"key": cache_key, "status": "formato", "ms": ms})
            self._fail()
            return None

        self._consecutive_failures = 0
        self.stats["live"] += 1
        self.log.append({"key": cache_key, "status": "live", "ms": ms,
                         "tokens": uso.get("total_tokens", 0)})
        self._write_cache(cache_key, data)
        return data

    # ------------------------------------------------------------ controllo
    def check(self) -> dict:
        if not self.api_key:
            return {"ok": False, "detail": "LLM2_KEY (o GROQ_API_KEY) non impostata.",
                    "model": self.model, "base": self.base}
        salvato, self.enabled, self.use_cache = self.use_cache, True, False
        out = self.generate_json(
            'Rispondi con {"ok": true, "nota": "connessione riuscita"}.',
            {"type": "object", "properties": {"ok": {"type": "boolean"},
                                              "nota": {"type": "string"}},
             "required": ["ok", "nota"]},
            cache_key="healthcheck2", max_output_tokens=120)
        self.use_cache = salvato
        if out is None:
            return {"ok": False, "detail": self.last_error or "nessuna risposta",
                    "model": self.model, "base": self.base}
        return {"ok": True, "detail": out.get("nota", ""), "model": self.model,
                "base": self.base,
                "tokens": self.stats["prompt_tokens"] + self.stats["output_tokens"]}


class Coppia:
    """Due modelli in fila: prima il bravo, poi quello che regge il volume.

    Il secondo entra in gioco SOLO quando il primo non puo' rispondere: quota
    esaurita, circuito aperto, tetto di chiamate raggiunto, chiave assente.
    Non si chiamano entrambi per la stessa domanda - sarebbe spendere due volte
    per avere due pareri che nessuno mette a confronto.

    Agli agenti presenta la stessa superficie di un modello solo, quindi non
    sanno nemmeno di essere davanti a una coppia.
    """

    def __init__(self, primario, secondario):
        self.primario = primario
        self.secondario = secondario
        self.log: list[dict] = []
        self.ricadute = 0

    # --- proprieta' che il resto del programma legge ------------------------
    @property
    def enabled(self) -> bool:
        return bool(self.primario.enabled or self.secondario.enabled)

    @property
    def model(self) -> str:
        if self.secondario.enabled:
            return f"{self.primario.model} + {self.secondario.model}"
        return self.primario.model

    @property
    def mode(self) -> str:
        if self.primario.enabled and self.secondario.enabled:
            return f"live, due modelli (ricadute: {self.ricadute})"
        return self.primario.mode if self.primario.enabled else self.secondario.mode

    @property
    def circuit_open(self) -> bool:
        return bool(self.primario.circuit_open and self.secondario.circuit_open)

    @property
    def last_error(self):
        """Gli errori di TUTTI E DUE.

        Prima restituiva solo quello del primo: quando fallivano entrambi, il
        motivo del secondo era invisibile e la diagnosi impossibile. E'
        successo davvero - un ciclo con quattordici ricadute e zero risposte,
        e dal file pubblicato non si capiva che il secondo modello rifiutava
        la chiave.
        """
        pezzi = []
        if self.primario.last_error:
            pezzi.append(f"[1] {self.primario.last_error}")
        if self.secondario.last_error:
            pezzi.append(f"[2] {self.secondario.last_error}")
        return "\n".join(pezzi) or None

    @property
    def quota_error(self):
        return self.primario.quota_error or self.secondario.quota_error

    @property
    def use_cache(self) -> bool:
        return self.primario.use_cache

    @use_cache.setter
    def use_cache(self, v) -> None:
        self.primario.use_cache = v
        self.secondario.use_cache = v

    @property
    def budget(self):
        return self.primario.budget

    @property
    def stats(self) -> dict:
        a, b = self.primario.stats, self.secondario.stats
        somma = {k: (a.get(k, 0) + b.get(k, 0)) for k in set(a) | set(b)}
        somma["ricadute"] = self.ricadute
        # Anche separate: una somma a zero non dice QUALE dei due ha fallito,
        # e senza quello non si sa dove intervenire.
        somma["primo"] = {"live": a.get("live", 0), "errors": a.get("errors", 0),
                          "modello": self.primario.model}
        somma["secondo"] = {"live": b.get("live", 0), "errors": b.get("errors", 0),
                            "modello": self.secondario.model}
        return somma

    def _spent(self) -> int:
        return self.primario._spent() + self.secondario._spent()

    # --- la chiamata --------------------------------------------------------
    def generate_json(self, prompt: str, schema: dict, cache_key: str, **kw):
        out = self.primario.generate_json(prompt, schema, cache_key, **kw)
        if out is not None:
            return out
        if not self.secondario.enabled:
            return None
        # Il primo non ha risposto: si annota il perche', perche' "e' finita la
        # quota" e "il modello ha sbagliato formato" sono problemi diversi e
        # chi legge il log deve poterli distinguere.
        motivo = ("tetto di chiamate" if self.primario.stats.get("over_budget")
                  else "circuito aperto" if self.primario.circuit_open
                  else "quota" if self.primario.quota_error
                  else "nessuna risposta")
        self.ricadute += 1
        self.log.append({"key": cache_key, "status": f"ricaduta sul secondo ({motivo})"})
        return self.secondario.generate_json(prompt, schema, cache_key, **kw)
