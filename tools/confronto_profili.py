"""Lo stesso mercato, tre profili: chi riceve che cosa.

L'analisi è una sola per tutti — gli stessi 48 strumenti, gli stessi voti. Quello
che cambia da persona a persona è il **filtro**: tetto di rischio, mercati,
settori, tipi di strumento, quante volte a settimana. Questo script lo mostra
sui dati del ciclo corrente, senza inventare niente.

    python tools/confronto_profili.py            # dati sintetici
    python tools/confronto_profili.py --real     # dati di mercato veri
    python tools/confronto_profili.py --threshold 70   # soglia più bassa, per vedere di più
"""

from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from engine import notifications as notif          # noqa: E402
from engine import onboarding                      # noqa: E402
from engine.pipeline import run_scan               # noqa: E402
from engine.users import RISK_CEILING              # noqa: E402

# Tre persone che rispondono in modo diverso allo stesso questionario.
PERSONE = {
    "cauto": {
        "orizzonte": "breve", "perdita": "vendo", "esperienza": ["deposito"],
        "strumenti": ["sceglilei"], "mercati": ["europa"], "settori": ["tutti"],
        "frequenza": "una", "canale": ["email"],
    },
    "equilibrato": {
        "orizzonte": "medio", "perdita": "aspetto", "esperienza": ["fondi", "panieri"],
        "strumenti": ["panieri", "azioni"], "mercati": ["usa", "europa"],
        "settori": ["tech", "ai", "salute"], "frequenza": "due", "canale": ["telegram"],
    },
    "aggressivo": {
        "orizzonte": "lungo", "perdita": "compro", "esperienza": ["azioni", "digitali"],
        "strumenti": ["azioni", "panieri", "digitali"], "mercati": ["tutti"],
        "settori": ["tutti"], "frequenza": "tre", "canale": ["telegram"],
    },
}


def main() -> int:
    real = "--real" in sys.argv
    soglia = None
    for i, a in enumerate(sys.argv):
        if a == "--threshold" and i + 1 < len(sys.argv):
            soglia = int(sys.argv[i + 1])
    state = run_scan(source="real" if real else "synthetic", threshold=soglia)
    assets, analyses = state["assets"], state["analyses"]
    triggers = state["triggers"]

    print(f"\nCiclo del {state['today']} · {state['data']['source']}")
    print(f"Soglia di notifica: {notif.SCORE_THRESHOLD} su 100 · "
          f"strumenti analizzati: {len(assets)}")
    above = [t for t, a in analyses.items() if a["opportunity_score"] > notif.SCORE_THRESHOLD]
    print(f"Sopra soglia, per chiunque: {len(above)} "
          f"({', '.join(sorted(above)) if above else 'nessuno'})\n")

    print("=" * 94)
    for nome, risposte in PERSONE.items():
        user = onboarding.profile_from_answers(risposte)
        p = user["profile"]
        decision = notif.evaluate_user(user, assets, analyses, triggers)
        ceiling = RISK_CEILING[p["risk_profile"]]
        print(f"\n{nome.upper()}  →  profilo {p['risk_profile']} (rischio massimo {ceiling}/100)")
        print(f"  mercati: {', '.join(p['markets'])}")
        print(f"  settori: {', '.join(p['sectors'][:4])}{'…' if len(p['sectors']) > 4 else ''}")
        print(f"  strumenti: {', '.join(p['asset_classes'])}")
        print(f"  al massimo {user['weekly_limit']} segnalazioni a settimana "
              f"su {', '.join(user['channels'])}")
        print(f"  idonei nel suo perimetro: {len(decision['eligible'])}")
        if decision["notifications"]:
            print("  RICEVE:")
            for n in decision["notifications"]:
                print(f"    - {n['name']} ({n['ticker']}): voto {n['opportunity_score']}, "
                      f"rischio {n['risk_label'].lower()}, "
                      f"valore stimato {n['target_price']} contro prezzo {n['price']}")
                print(f"      motivi: {'; '.join(n['reasons'][:3])}")
        else:
            print("  RICEVE: niente oggi")
        # perché gli altri no: i tre scarti più vicini
        print("  scartati più vicini:")
        for r in decision["rejected"][:3]:
            print(f"    - {r['ticker']} (voto {r['score']}): {r['reason']}")
    print("\n" + "=" * 94)
    print("L'analisi è identica per tutti: cambia solo chi la riceve, e perché.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
