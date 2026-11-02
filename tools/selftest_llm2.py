"""Controlla il secondo modello e la ricaduta dal primo al secondo.

La cosa da verificare non e' "il secondo modello risponde": e' QUANDO entra in
gioco. Se entrasse sempre si spenderebbe due volte; se non entrasse mai non
servirebbe a niente; se entrasse quando il primo ha solo sbagliato formato si
nasconderebbe un difetto invece di aggirarlo.

    python tools/selftest_llm2.py

Gira senza rete: le risposte dei due provider sono finte.
"""
from __future__ import annotations

import io
import json
import os
import sys
import urllib.error
import urllib.request

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from engine import llm as llm_mod  # noqa: E402
from engine import llm2 as llm2_mod  # noqa: E402

VERDE, ROSSO, RESET = "\033[32m", "\033[31m", "\033[0m"
ok_totale = True
RICHIESTE: list[dict] = []


def check(label: str, condizione: bool, dettaglio: str = "") -> None:
    global ok_totale
    segno = f"{VERDE}ok {RESET}" if condizione else f"{ROSSO}KO {RESET}"
    print(f"  [{segno}] {label}" + (f" - {dettaglio}" if dettaglio else ""))
    if not condizione:
        ok_totale = False


SCHEMA = {"type": "object",
          "properties": {"score": {"type": "NUMBER"}, "nota": {"type": "STRING"}},
          "required": ["score", "nota"]}


def finto(modo: str = "ok", contenuto: str | None = None):
    """Sostituisce urlopen. `modo` decide come si comporta il provider."""
    class Ctx:
        def __init__(self, dati):
            self.dati = dati

        def __enter__(self):
            return self.dati

        def __exit__(self, *a):
            return False

    def fake(req, timeout=None, context=None):
        corpo = json.loads(req.data.decode("utf-8")) if req.data else {}
        RICHIESTE.append({"url": req.full_url, "body": corpo,
                          "auth": req.headers.get("Authorization")})
        if modo == "429":
            raise urllib.error.HTTPError(
                req.full_url, 429, "Too Many Requests", {},
                io.BytesIO(b'{"error":{"message":"Quota exceeded for metric: '
                           b'generate_content_free_tier_requests, limit: 20"}}'))
        if modo == "500":
            raise urllib.error.HTTPError(req.full_url, 500, "Server Error", {},
                                         io.BytesIO(b'{"error":"boom"}'))
        if modo == "rete":
            raise urllib.error.URLError("nessuna rete")
        testo = contenuto if contenuto is not None else '{"score": 77, "nota": "va bene"}'
        risposta = {"choices": [{"message": {"content": testo}}],
                    "usage": {"prompt_tokens": 10, "completion_tokens": 5,
                              "total_tokens": 15}}
        return Ctx(io.BytesIO(json.dumps(risposta).encode("utf-8")))

    urllib.request.urlopen = fake


class Finto:
    """Un primo modello finto, per decidere a tavolino quando non risponde."""

    def __init__(self, risposta=None, **stato):
        self.risposta = risposta
        self.chiamate = 0
        self.enabled = stato.get("enabled", True)
        self.circuit_open = stato.get("circuit_open", False)
        self.quota_error = stato.get("quota_error")
        self.last_error = None
        self.model = "finto-1"
        self.mode = "live (finto)"
        self.use_cache = False
        self.budget = stato.get("budget")
        self.stats = {"live": 0, "errors": 0, "skipped": 0,
                      "over_budget": stato.get("over_budget", 0)}

    def generate_json(self, prompt, schema, cache_key, **kw):
        self.chiamate += 1
        return self.risposta

    def _spent(self):
        return 0


def main() -> int:
    originale = urllib.request.urlopen
    try:
        print("1. Il secondo modello parla il dialetto compatibile OpenAI")
        RICHIESTE.clear()
        finto("ok")
        c = llm2_mod.Compatibile(enabled=True, api_key="finta", use_cache=False)
        out = c.generate_json("prova", SCHEMA, cache_key="k1")
        check("risposta interpretata", out == {"score": 77, "nota": "va bene"}, str(out))
        r = RICHIESTE[-1]
        check("va su /chat/completions", r["url"].endswith("/chat/completions"), r["url"])
        check("la chiave va nell'intestazione Bearer",
              r["auth"] == "Bearer finta", str(r["auth"]))
        check("chiede esplicitamente JSON",
              (r["body"].get("response_format") or {}).get("type") == "json_object")
        check("c'e' il messaggio di sistema",
              r["body"]["messages"][0]["role"] == "system")
        check("lo schema e' descritto nel testo, perche' non si puo' imporre",
              '"score"' in r["body"]["messages"][0]["content"],
              r["body"]["messages"][0]["content"][-90:])

        print("\n2. Il JSON incorniciato in un blocco di codice non si butta")
        finto("ok", contenuto='```json\n{"score": 50, "nota": "ok"}\n```')
        c = llm2_mod.Compatibile(enabled=True, api_key="finta", use_cache=False)
        out = c.generate_json("prova", SCHEMA, cache_key="k2")
        check("la cornice viene togliere e il contenuto resta",
              out == {"score": 50, "nota": "ok"}, str(out))

        print("\n3. Una risposta che non e' JSON viene scartata, non indovinata")
        finto("ok", contenuto="Certo! Ecco la mia analisi: il titolo sale.")
        c = llm2_mod.Compatibile(enabled=True, api_key="finta", use_cache=False)
        out = c.generate_json("prova", SCHEMA, cache_key="k3")
        check("restituisce None", out is None)
        check("l'errore e' registrato", "non interpretabile" in (c.last_error or ""),
              c.last_error or "")
        finto("ok", contenuto='[1, 2, 3]')
        c = llm2_mod.Compatibile(enabled=True, api_key="finta", use_cache=False)
        check("un elenco invece di un oggetto viene scartato",
              c.generate_json("p", SCHEMA, cache_key="k4") is None)

        print("\n4. Errori: 429 e 500 si riprovano, il resto no")
        finto("429")
        c = llm2_mod.Compatibile(enabled=True, api_key="finta", use_cache=False,
                                 retry_wait_s=0)
        out = c.generate_json("prova", SCHEMA, cache_key="k5")
        check("nessuna eccezione verso il chiamante", out is None)
        check("ha riprovato", c.stats["retries"] == llm2_mod.MAX_ATTEMPTS - 1,
              str(c.stats["retries"]))
        check("la quota dichiarata viene letta", "20" in (c.quota_error or ""),
              c.quota_error or "nessuna")
        finto("rete")
        c = llm2_mod.Compatibile(enabled=True, api_key="finta", use_cache=False)
        check("senza rete restituisce None e lo dichiara",
              c.generate_json("p", SCHEMA, cache_key="k6") is None and c.last_error)

        print("\n5. La coppia: il secondo entra SOLO se il primo non puo'")
        finto("ok")
        # caso a: il primo risponde -> il secondo non viene nemmeno sfiorato
        primo = Finto(risposta={"score": 1, "nota": "dal primo"})
        secondo = llm2_mod.Compatibile(enabled=True, api_key="finta", use_cache=False)
        coppia = llm2_mod.Coppia(primo, secondo)
        out = coppia.generate_json("p", SCHEMA, cache_key="c1")
        check("la risposta e' del primo", out["nota"] == "dal primo", str(out))
        check("il secondo non e' stato chiamato", secondo.stats["live"] == 0,
              str(secondo.stats["live"]))
        check("nessuna ricaduta contata", coppia.ricadute == 0)

        # caso b: il primo ha la quota finita -> ricade sul secondo
        primo = Finto(risposta=None, quota_error="limite 20 richieste")
        secondo = llm2_mod.Compatibile(enabled=True, api_key="finta", use_cache=False)
        coppia = llm2_mod.Coppia(primo, secondo)
        out = coppia.generate_json("p", SCHEMA, cache_key="c2")
        check("risponde il secondo", out == {"score": 77, "nota": "va bene"}, str(out))
        check("la ricaduta e' contata", coppia.ricadute == 1)
        check("il log dice PERCHE' e' ricaduta",
              any("quota" in v.get("status", "") for v in coppia.log),
              str(coppia.log))

        # caso c: il primo ha il circuito aperto
        primo = Finto(risposta=None, circuit_open=True)
        coppia = llm2_mod.Coppia(primo, llm2_mod.Compatibile(
            enabled=True, api_key="finta", use_cache=False))
        coppia.generate_json("p", SCHEMA, cache_key="c3")
        check("il circuito aperto fa ricadere, e lo dice",
              any("circuito" in v.get("status", "") for v in coppia.log), str(coppia.log))

        # caso d: il primo ha esaurito il tetto di chiamate
        primo = Finto(risposta=None, over_budget=3)
        coppia = llm2_mod.Coppia(primo, llm2_mod.Compatibile(
            enabled=True, api_key="finta", use_cache=False))
        coppia.generate_json("p", SCHEMA, cache_key="c4")
        check("il tetto raggiunto fa ricadere, e lo dice",
              any("tetto" in v.get("status", "") for v in coppia.log), str(coppia.log))

        # caso e: nessun secondo configurato -> si resta sul calcolo
        primo = Finto(risposta=None)
        secondo = llm2_mod.Compatibile(enabled=False, api_key="", use_cache=False)
        coppia = llm2_mod.Coppia(primo, secondo)
        check("senza secondo configurato restituisce None",
              coppia.generate_json("p", SCHEMA, cache_key="c5") is None)
        check("e non conta ricadute inesistenti", coppia.ricadute == 0)

        print("\n6. La coppia si presenta come un modello solo")
        primo = Finto(risposta={"x": 1})
        secondo = llm2_mod.Compatibile(enabled=True, api_key="finta", use_cache=False)
        coppia = llm2_mod.Coppia(primo, secondo)
        for attributo in ("enabled", "model", "mode", "circuit_open", "stats",
                          "last_error", "quota_error", "use_cache", "budget"):
            check(f"espone {attributo}", hasattr(coppia, attributo))
        check("il nome dice entrambi i modelli", "+" in coppia.model, coppia.model)
        check("le statistiche sono la somma dei due",
              "ricadute" in coppia.stats, str(sorted(coppia.stats))[:70])

        print("\n7. I fornitori pronti sono quelli verificati raggiungibili")
        for nome in ("groq", "cerebras", "openrouter"):
            base, modello = llm2_mod.PRONTI[nome]
            check(f"{nome}: base e modello preimpostati",
                  base.startswith("https://") and bool(modello), f"{base} · {modello}")

        print("\n8. Senza chiave il secondo e' spento e lo dichiara")
        for var in ("LLM2_KEY", "GROQ_API_KEY"):
            os.environ.pop(var, None)
        c = llm2_mod.Compatibile(enabled=True, use_cache=False)
        check("non e' abilitato", not c.enabled)
        check("lo dice in chiaro", "nessuna chiave" in c.mode, c.mode)
        res = c.check()
        check("il controllo spiega che cosa manca",
              not res["ok"] and "LLM2_KEY" in res["detail"], res["detail"][:60])
    finally:
        urllib.request.urlopen = originale

    print("\n" + ("Tutti i controlli superati." if ok_totale
                  else "ALCUNI CONTROLLI FALLITI."))
    return 0 if ok_totale else 1


if __name__ == "__main__":
    raise SystemExit(main())
