"""Verifica dell'integrazione Gemini senza chiamare Gemini.

Serve a provare la parte che non si può provare senza chiave API: come viene
composta la richiesta, come viene letta la risposta, dove finiscono i numeri del
modello e che cosa succede quando il modello risponde male.

    python tools/selftest_llm.py

Non chiama la rete: sostituisce `urlopen` con una finta risposta nel formato
dell'API Gemini.
"""

from __future__ import annotations

import io
import json
import os
import sys
import urllib.request

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from engine import agents, llm as llm_mod          # noqa: E402
from engine.pipeline import run_scan               # noqa: E402

SENT_REQUESTS: list[dict] = []


def fake_response(payload: dict) -> io.BytesIO:
    body = {
        "candidates": [{"content": {"parts": [{"text": json.dumps(payload)}]}}],
        "usageMetadata": {"promptTokenCount": 420, "candidatesTokenCount": 110,
                          "totalTokenCount": 530},
    }
    return io.BytesIO(json.dumps(body).encode("utf-8"))


def install_fake_api(mode: str = "ok"):
    """mode: ok | malformed | out_of_range | http_error"""
    class Ctx:
        def __init__(self, data):
            self.data = data

        def __enter__(self):
            return self.data

        def __exit__(self, *a):
            return False

    def fake_urlopen(req, timeout=None, context=None):
        body = json.loads(req.data.decode("utf-8"))
        prompt = body["contents"][0]["parts"][0]["text"]
        schema_props = set(body["generationConfig"]["responseSchema"]["properties"])
        SENT_REQUESTS.append({"prompt": prompt, "props": schema_props,
                              "has_system": "systemInstruction" in body,
                              "mime": body["generationConfig"]["responseMimeType"],
                              "thinking": body["generationConfig"].get("thinkingConfig")})

        if mode == "http_error":
            raise urllib.error.HTTPError(req.full_url, 429, "Too Many Requests", {},
                                         io.BytesIO(b'{"error":"quota"}'))
        if mode == "server_error":
            raise urllib.error.HTTPError(req.full_url, 400, "Bad Request", {},
                                         io.BytesIO(b'{"error":"API key not valid"}'))
        if mode == "malformed":
            return Ctx(io.BytesIO(b'{"candidates":[{"content":{"parts":[{"text":"non json"}]}}]}'))

        if "fair_value" in schema_props:
            # il modello propone un valore: in modalità out_of_range lo manda
            # fuori dalla banda consentita e deve essere scartato
            base = float(prompt.split("Stima del modello interno: valore ")[1].split()[0])
            value = base * (2.5 if mode == "out_of_range" else 1.08)
            return Ctx(fake_response({"fair_value": round(value, 2), "score": 88,
                                      "confidence": 72,
                                      "reasoning": "Multiplo ancora sotto la crescita attesa.",
                                      "drivers": ["crescita ricavi +29%", "ROIC 26%"]}))
        if "summary" in schema_props:
            return Ctx(fake_response({"score": 77,
                                      "summary": "Le notizie delle ultime due settimane sono "
                                                 "in prevalenza positive.",
                                      "drivers": ["contratto pluriennale annunciato"]}))
        if "fundamental_adjustment" in schema_props:
            return Ctx(fake_response({"fundamental_adjustment": 3,
                                      "technical_adjustment": -2,
                                      "risk_adjustment": 40 if mode == "out_of_range" else 4,
                                      "reasoning": "Bilancio solido, prezzo esteso nel breve."}))
        if "executive_summary" in schema_props:
            return Ctx(fake_response({
                "executive_summary": "Sintesi scritta dal modello sui dati forniti. " * 3,
                "key_risk": "Concentrazione della domanda su pochi clienti."}))
        return Ctx(fake_response({}))

    urllib.request.urlopen = fake_urlopen


def check(label: str, condition: bool, detail: str = "") -> bool:
    print(f"  [{'ok ' if condition else 'KO '}] {label}" + (f" - {detail}" if detail else ""))
    return condition


def main() -> int:
    ok = True
    print("1. Risposte valide: i numeri del modello entrano nei conti")
    install_fake_api("ok")
    state = run_scan(live=True, api_key="chiave-finta", use_cache=False)
    a = state["analyses"]["AMD"]
    val, sent = a["agents"]["valuation"], a["agents"]["sentiment"]
    ok &= check("la valutazione viene da Gemini", val["source"].startswith("Gemini"),
                val["source"])
    ok &= check("il punteggio di valutazione è quello del modello", val["score"] == 88,
                str(val["score"]))
    ok &= check("il valore stimato è quello del modello (entro la banda)",
                abs(val["fair_value"] - val["model_value"] * 1.08) < 0.5,
                f"{val['fair_value']} vs modello {val['model_value']}")
    ok &= check("il target del piano operativo usa il valore del modello",
                abs(a["plan"]["target"] - val["fair_value"]) < 0.01)
    ok &= check("il sentiment viene da Gemini", sent["score"] == 77 and
                sent["source"].startswith("Gemini"))
    ok &= check("la revisione AI ha spostato i punteggi",
                a["agents"]["fundamental"].get("ai_adjustment") == 3 and
                a["agents"]["risk"].get("ai_adjustment") == 4)
    rep = next(r for r in state["reports"] if r["ticker"] == "AMD")
    ok &= check("il report è scritto dal modello", rep["narrative_engine"].startswith("Gemini"))
    # DEMO-33: senza questo i token del ragionamento mangiano la risposta
    ok &= check("la richiesta spegne il ragionamento del modello",
                all(r["thinking"] == {"thinkingBudget": 0} for r in SENT_REQUESTS),
                str(SENT_REQUESTS[0]["thinking"]))
    ok &= check("la richiesta porta le istruzioni di sistema e forza il JSON",
                all(r["has_system"] and r["mime"] == "application/json" for r in SENT_REQUESTS))
    ok &= check("il modello non è stato chiamato fuori dal batch profondo",
                state["analyses"]["0823.HK"]["agents"]["valuation"]["source"]
                == "modello quantitativo")
    print(f"  chiamate simulate: {state['llm']['stats']['live']}, "
          f"token {state['llm']['stats']['prompt_tokens'] + state['llm']['stats']['output_tokens']}")

    print("\n2. Risposte fuori dai limiti: scartate, si usa il calcolo")
    SENT_REQUESTS.clear()
    install_fake_api("out_of_range")
    state = run_scan(live=True, api_key="chiave-finta", use_cache=False)
    a = state["analyses"]["AMD"]
    val = a["agents"]["valuation"]
    ok &= check("valore fuori banda scartato", val["fair_value"] == val["model_value"],
                f"{val['fair_value']}")
    ok &= check("correzione di rischio oltre il limite scartata",
                a["agents"]["risk"].get("ai_adjustment") in (None, 10),
                str(a["agents"]["risk"].get("ai_adjustment")))

    print("\n3. Risposta illeggibile: il ciclo non si ferma")
    install_fake_api("malformed")
    state = run_scan(live=True, api_key="chiave-finta", use_cache=False)
    ok &= check("errori contati", state["llm"]["stats"]["errors"] > 0,
                str(state["llm"]["stats"]["errors"]))
    ok &= check("punteggi calcolati comunque disponibili",
                state["analyses"]["AMD"]["opportunity_score"] > 0)

    print("\n4. Chiave rifiutata dal provider: si continua sul calcolo")
    install_fake_api("server_error")
    state = run_scan(live=True, api_key="chiave-finta", use_cache=False)
    ok &= check("l'errore è registrato", "400" in (state["llm"]["last_error"] or ""),
                state["llm"]["last_error"] or "")
    ok &= check("il ciclo è completo", len(state["analyses"]) == 48)
    ok &= check("dopo pochi errori di fila smette di chiamare il modello",
                state["llm"]["stats"]["errors"] <= 5 and state["llm"]["stats"]["skipped"] > 0,
                f"errori {state['llm']['stats']['errors']}, "
                f"salti {state['llm']['stats']['skipped']}")

    print("\n5. Limite di frequenza del piano (429): riprova, poi cede")
    install_fake_api("http_error")
    g = llm_mod.Gemini(enabled=True, api_key="chiave-finta", use_cache=False,
                       retry_429_s=0.01)
    out = g.generate_json("prova", {"type": "OBJECT", "properties": {"x": {"type": "STRING"}},
                                    "required": ["x"]}, cache_key="k")
    ok &= check("nessuna eccezione, risposta assente", out is None)
    ok &= check("i nuovi tentativi sono stati fatti",
                g.stats["retries"] == llm_mod.MAX_ATTEMPTS - 1,
                f"{g.stats['retries']} su {llm_mod.MAX_ATTEMPTS - 1} previsti")
    ok &= check("un errore definitivo non viene riprovato",
                g._retry_wait(400, 1) is None and g._retry_wait(404, 1) is None)
    ok &= check("un sovraccarico del servizio (503) viene riprovato",
                g._retry_wait(503, 1) is not None)

    print("\n6. Il circuito si riapre: un limite di frequenza non spegne tutto il ciclo")
    SCHEMA_X = {"type": "OBJECT", "properties": {"x": {"type": "STRING"}}, "required": ["x"]}
    install_fake_api("http_error")
    g = llm_mod.Gemini(enabled=True, api_key="chiave-finta", use_cache=False,
                       retry_429_s=0, circuit_cooldown_s=0)
    for i in range(3):
        g.generate_json("prova", SCHEMA_X, cache_key=f"k{i}")
    ok &= check("dopo tre rifiuti il circuito si apre", g.circuit_open,
                f"aperture {g.stats['circuit_opens']}")
    # passata l'attesa (qui zero) la chiamata successiva va fatta, non saltata
    saltate = g.stats["skipped"]
    install_fake_api("ok")
    out = g.generate_json(
        "Leggi queste notizie su NVDA",
        {"type": "OBJECT",
         "properties": {"score": {"type": "NUMBER"}, "summary": {"type": "STRING"}},
         "required": ["score", "summary"]},
        cache_key="sentiment|NVDA|3")
    ok &= check("passata l'attesa il modello viene richiamato",
                g.stats["skipped"] == saltate, f"salti {g.stats['skipped']}")
    ok &= check("se risponde, il circuito si richiude",
                out is not None and not g.circuit_open)

    print("\n" + ("Tutti i controlli superati." if ok else "ALCUNI CONTROLLI FALLITI."))
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
