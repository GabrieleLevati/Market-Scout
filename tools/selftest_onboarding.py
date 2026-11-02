"""Verifica del questionario iniziale.

Tre cose, che insieme bastano a fidarsi del profilo che ne esce:

1. **Coerenza dei dati**: ogni domanda ha opzioni valide, ogni effetto usa una
   chiave del vocabolario, ogni domanda determina almeno un campo del profilo.
2. **Comportamento**: chi risponde prudente a tutto è Conservativo, chi risponde
   spavaldo è Aggressivo, chi non risponde ottiene il profilo prudente, e
   l'esperienza non può ampliare il rischio.
3. **Parità tra i due lettori**: il motore (`engine/onboarding.py`) e la pagina
   (`web/onboarding.js`) devono ricavare lo stesso profilo dalle stesse
   risposte. La pagina viene eseguita con Node su un `DEMO_DATA` finto.

    python tools/selftest_onboarding.py
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from engine import onboarding                    # noqa: E402
from engine.users import RISK_CEILING            # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ALLOWED_EFFECTS = {"risk_points", "experience_points", "risk_cap", "horizon", "weekly_limit",
                   "currency", "country", "wants_portfolio",
                   "markets_add", "sectors_add", "asset_classes_add", "channels_add"}
VALID = {
    "markets": {"USA", "Europa", "Asia", "Global"},
    "sectors": set(onboarding.ALL_SECTORS),
    "asset_classes": {"Azioni", "ETF", "Obbligazioni", "Crypto"},
    "channels": {"Email", "Telegram", "WhatsApp", "Push", "Solo a schermo"},
}
BANNED_WORDS = ("etf", "obbligazion", "volatilit", "asset", "equity", "benchmark",
                "drawdown", "liquidità")

ok = True


def check(label: str, condition: bool, detail: str = "") -> bool:
    global ok
    print(f"  [{'ok ' if condition else 'KO '}] {label}" + (f" — {detail}" if detail else ""))
    ok = ok and bool(condition)
    return bool(condition)


def answers_for(pick) -> dict:
    """Costruisce un set di risposte scegliendo un'opzione per domanda con una
    funzione di selezione (indice o criterio)."""
    out = {}
    for q in onboarding.QUESTIONS:
        idx = pick(q)
        if idx is None:
            continue
        opt = q["options"][idx]
        out[q["id"]] = [opt["id"]] if q["kind"] == "multi" else opt["id"]
    return out


def risk_of(option: dict) -> int:
    return (option.get("sets") or {}).get("risk_points", 0)


def main() -> int:
    print("1. Struttura del questionario")
    check("ci sono domande", len(onboarding.QUESTIONS) > 0, f"{len(onboarding.QUESTIONS)}")
    check("non più di 8 domande", len(onboarding.QUESTIONS) <= 8,
          f"{len(onboarding.QUESTIONS)}")
    ids = [q["id"] for q in onboarding.QUESTIONS]
    check("identificativi unici", len(set(ids)) == len(ids))
    bad_effects, no_effect, bad_values, jargon = [], [], [], []
    for q in onboarding.QUESTIONS:
        determines = set()
        for o in q["options"]:
            sets = o.get("sets") or {}
            for k, v in sets.items():
                if k not in ALLOWED_EFFECTS:
                    bad_effects.append(f"{q['id']}/{o['id']}: {k}")
                determines.add(k)
                if k.endswith("_add"):
                    target = k[:-4]
                    for item in (v if isinstance(v, list) else [v]):
                        if item not in VALID.get(target, {item}):
                            bad_values.append(f"{q['id']}/{o['id']}: {target}={item}")
            low = o["label"].lower()
            for w in BANNED_WORDS:
                if w in low:
                    jargon.append(f"{q['id']}/{o['id']}: «{w}»")
        if not determines:
            no_effect.append(q["id"])
    check("ogni effetto usa una chiave del vocabolario", not bad_effects,
          "; ".join(bad_effects[:3]))
    check("ogni valore aggiunto è ammesso dal motore", not bad_values, "; ".join(bad_values[:3]))
    check("ogni domanda determina qualcosa", not no_effect, "; ".join(no_effect))
    check("nessun gergo nelle risposte", not jargon, "; ".join(jargon[:3]))

    print("\n2. Comportamento")
    prudent = answers_for(lambda q: min(range(len(q["options"])),
                                        key=lambda i: risk_of(q["options"][i])))
    def boldest(q):
        """L'opzione più spavalda: punti alti e nessun tetto prudente."""
        best, best_key = None, None
        for i, o in enumerate(q["options"]):
            cap = (o.get("sets") or {}).get("risk_cap")
            key = (0 if cap else 1, risk_of(o),
                   (o.get("sets") or {}).get("experience_points", 0))
            if best_key is None or key > best_key:
                best, best_key = i, key
        return best

    bold = answers_for(boldest)
    u_prudent = onboarding.profile_from_answers(prudent)
    u_bold = onboarding.profile_from_answers(bold)
    u_empty = onboarding.profile_from_answers({})
    check("risposte prudenti -> Conservativo",
          u_prudent["profile"]["risk_profile"] == "Conservativo",
          u_prudent["profile"]["risk_profile"])
    check("risposte spavalde -> Aggressivo",
          u_bold["profile"]["risk_profile"] == "Aggressivo",
          f"{u_bold['profile']['risk_profile']} (punti {u_bold['risk_points']})")
    check("nessuna risposta -> profilo prudente completo",
          u_empty["profile"]["risk_profile"] == onboarding.DEFAULTS["risk_profile"] and
          u_empty["profile"]["markets"] and u_empty["profile"]["asset_classes"],
          u_empty["profile"]["risk_profile"])
    check("mai capitale richiesto", all(u["profile"]["capital"] is None
                                        for u in (u_prudent, u_bold, u_empty)))
    check("mai posizioni richieste", all(u["positions"] == []
                                         for u in (u_prudent, u_bold, u_empty)))
    check("conservativo senza monete digitali",
          "Crypto" not in u_prudent["profile"]["asset_classes"])
    check("profilo sempre valido per il motore",
          all(u["profile"]["risk_profile"] in RISK_CEILING
              for u in (u_prudent, u_bold, u_empty)))
    check("limite settimanale sensato",
          all(1 <= u["weekly_limit"] <= 3 for u in (u_prudent, u_bold, u_empty)),
          f"{u_prudent['weekly_limit']}/{u_bold['weekly_limit']}/{u_empty['weekly_limit']}")

    # l'esperienza non deve ampliare il rischio
    exp_q = next((q for q in onboarding.QUESTIONS
                  if any("experience_points" in (o.get("sets") or {}) for o in q["options"])),
                 None)
    if exp_q:
        least = min(exp_q["options"],
                    key=lambda o: (o.get("sets") or {}).get("experience_points", 0))
        bold_novice = dict(bold)
        bold_novice[exp_q["id"]] = ([least["id"]] if exp_q["kind"] == "multi" else least["id"])
        u = onboarding.profile_from_answers(bold_novice)
        check("spavaldo ma senza esperienza -> non Aggressivo",
              u["profile"]["risk_profile"] != "Aggressivo", u["profile"]["risk_profile"])
    else:
        check("esiste una domanda sull'esperienza", False)

    print("\n3. Parità tra motore e pagina")
    cases = {"prudente": prudent, "spavaldo": bold, "vuoto": {},
             "misto": answers_for(lambda q: len(q["options"]) // 2)}
    harness = f"""
const fs = require('fs');
globalThis.window = globalThis;
globalThis.DEMO_DATA = {{ onboarding: {json.dumps(onboarding.export(), ensure_ascii=False)} }};
const src = fs.readFileSync({json.dumps(os.path.join(ROOT, 'web', 'onboarding.js'))}, 'utf8');
// eval indiretto: il const dichiarato nel file resta accessibile come globale
(0, eval)(src + ';globalThis.Onboarding = Onboarding;');
const cases = {json.dumps(cases, ensure_ascii=False)};
const out = {{}};
for (const [name, answers] of Object.entries(cases)) {{
  const u = Onboarding.profileFromAnswers(answers);
  out[name] = {{ profile: u.profile, channels: u.channels, weekly_limit: u.weekly_limit }};
}}
process.stdout.write(JSON.stringify(out));
"""
    with tempfile.TemporaryDirectory() as tmp:
        path = os.path.join(tmp, "harness.js")
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(harness)
        try:
            res = subprocess.run(["node", path], capture_output=True, text=True,
                                 timeout=60, encoding="utf-8")
        except FileNotFoundError:
            print("  [--  ] Node non disponibile: parità non verificata")
            res = None
    if res is not None:
        if res.returncode != 0:
            check("la pagina esegue il questionario", False, res.stderr[:200])
        else:
            js = json.loads(res.stdout)
            for name, answers in cases.items():
                u = onboarding.profile_from_answers(answers)
                mine = {"profile": u["profile"], "channels": u["channels"],
                        "weekly_limit": u["weekly_limit"]}
                same = json.dumps(mine, sort_keys=True, ensure_ascii=False) == \
                    json.dumps(js[name], sort_keys=True, ensure_ascii=False)
                check(f"caso «{name}»: stesso profilo da motore e pagina", same,
                      "" if same else f"motore {mine} / pagina {js[name]}")

    print("\n" + ("Tutti i controlli superati." if ok else "ALCUNI CONTROLLI FALLITI."))
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
