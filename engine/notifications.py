"""Decisione di notifica del Chief Investment Officer Agent
(BR-06, BR-07, A-07, step 6-7 del workflow).

Regole dell'FDD applicate in quest'ordine:
  1. l'opportunità deve essere coerente con profilo e preferenze apprese (A-07)
  2. Opportunity Score > 85 (BR-06)
  3. massimo 3 notifiche a settimana per utente (BR-06, S-04)
  4. se le idonee sono più di 3, vincono quelle con lo score più alto
Ogni scarto resta tracciato con il motivo: è la parte che il cliente vuole
vedere quando chiede "perché non mi ha avvisato".
"""

from __future__ import annotations

from .users import ASSET_CLASS_MAP, RISK_CEILING, priority_boost
from .universe import TODAY

SCORE_THRESHOLD = 85          # BR-06: "superiore a 85"
WEEKLY_LIMIT = 3              # BR-06 / S-04: massimo del servizio


def weekly_limit_for(user: dict) -> int:
    """Il limite scelto dall'utente in onboarding, mai sopra quello del servizio.
    Senza scelta vale il massimo previsto da BR-06."""
    chosen = user.get("weekly_limit")
    if not isinstance(chosen, int) or chosen < 1:
        return WEEKLY_LIMIT
    return min(chosen, WEEKLY_LIMIT)
SECTOR_FILTER_CLASSES = {"Azioni", "REIT"}   # DEMO-16 (OP-10)


def _eligible_classes(profile: dict) -> list[str]:
    out: list[str] = []
    for pref in profile["asset_classes"]:
        out += ASSET_CLASS_MAP.get(pref, [])
    return out


def evaluate_user(user: dict, assets: dict, analyses: dict,
                  triggers_by_ticker: dict) -> dict:
    profile = user["profile"]
    classes = _eligible_classes(profile)
    ceiling = RISK_CEILING[profile["risk_profile"]]
    candidates, rejected = [], []

    for ticker, an in analyses.items():
        a = assets[ticker]
        score = an["opportunity_score"]

        def drop(kind, reason, **values):
            # `kind` e `values` permettono allo strato in linguaggio semplice di
            # riscrivere il motivo senza riusare questo testo tecnico.
            rejected.append({"ticker": ticker, "score": score, "reason": reason,
                             "kind": kind, "values": values})

        if not a.get("valuable", True) or an["scores"].get("valuation") is None:
            drop("no_valuation",
                 "Nessuna stima di valore disponibile (dati di bilancio assenti): "
                 "monitorato ma non proposto",
                 basis=a["fundamentals"].get("basis", ""))
            continue
        if a["asset_class"] == "Commodities":
            drop("asset_class_domain",
                 "Asset class fuori dal dominio \"Asset preferiti\" del profilo (OP-10)",
                 asset_class=a["asset_class"])
            continue
        if a["asset_class"] not in classes:
            drop("asset_class",
                 f"Asset class {a['asset_class']} non tra le preferenze del profilo",
                 asset_class=a["asset_class"])
            continue
        if a["market"] not in profile["markets"]:
            drop("market", f"Mercato {a['market']} non tra quelli di interesse",
                 market=a["market"])
            continue
        if a["asset_class"] in SECTOR_FILTER_CLASSES and a["sector"] not in profile["sectors"]:
            drop("sector", f"Settore {a['sector']} non tra quelli preferiti",
                 sector=a["sector"])
            continue
        if an["scores"]["risk"] > ceiling:
            drop("risk", f"Risk Score {an['scores']['risk']} oltre il massimo del profilo "
                         f"{profile['risk_profile']} ({ceiling})",
                 risk=an["scores"]["risk"], ceiling=ceiling,
                 risk_label=an["risk_label"], profile=profile["risk_profile"])
            continue
        if score <= SCORE_THRESHOLD:
            drop("score", f"Opportunity Score {score} non superiore a {SCORE_THRESHOLD}",
                 threshold=SCORE_THRESHOLD)
            continue

        boost = priority_boost(user["id"], a["sector"])
        candidates.append({"ticker": ticker, "score": score, "priority": round(score * boost, 2),
                           "boost": boost, "sector": a["sector"]})

    candidates.sort(key=lambda c: (-c["priority"], -c["score"]))
    limit = weekly_limit_for(user)
    remaining = max(0, limit - user["notifications_this_week"])
    selected = candidates[:remaining]
    for c in candidates[remaining:]:
        rejected.append({"ticker": c["ticker"], "score": c["score"],
                         "kind": "weekly_limit",
                         "values": {"limit": limit,
                                    "sent": user["notifications_this_week"]},
                         "reason": f"Limite di {limit} notifiche settimanali "
                                   f"già raggiunto ({user['notifications_this_week']} inviate): "
                                   f"idonea ma rinviata"})

    notifications = [build_notification(user, assets[c["ticker"]], analyses[c["ticker"]],
                                        triggers_by_ticker.get(c["ticker"], []), c)
                     for c in selected]
    return {
        "user_id": user["id"],
        "eligible": candidates,
        "notifications": notifications,
        "rejected": sorted(rejected, key=lambda r: -r["score"])[:12],
        "weekly_limit": limit,
        "slots_remaining_before": remaining,
        "slots_remaining_after": remaining - len(selected),
    }


def build_notification(user: dict, asset: dict, analysis: dict,
                       triggers: list[dict], candidate: dict) -> dict:
    """Contenuto della notifica secondo 3.4 (esempio AMD dell'FDD)."""
    t, plan = asset["tech"], analysis["plan"]
    val = analysis["agents"]["valuation"]
    reasons = [tr["label"] for tr in triggers][:3]
    for d in analysis["agents"]["fundamental"]["drivers"][:1] + \
            analysis["agents"]["technical"]["drivers"][:1]:
        if d["score"] >= 70:
            reasons.append(f"{d['label']}: {d['value']}")
    return {
        "notification_id": f"NTF-{user['id']}-{asset['ticker'].replace('.', '-')}-{TODAY.isoformat()}",
        "user_id": user["id"],
        "user_name": user["name"],
        "sent_on": TODAY.isoformat(),
        "channels": user["channels"],
        "ticker": asset["ticker"],
        "name": asset["name"],
        "currency": asset["currency"],
        "opportunity_score": analysis["opportunity_score"],
        "classification": analysis["classification"],
        "price": t["price"],
        "target_price": plan["target"],       # stima del sistema, non di analisti
        "upside": plan["upside_to_target"],
        "fundamental_score": analysis["scores"]["fundamental"],
        "technical_score": analysis["scores"]["technical"],
        "valuation_score": analysis["scores"]["valuation"],
        "fair_value": val["fair_value"],
        "valuation_source": val["source"],
        "valuation_confidence": val["confidence"],
        "sentiment_score": analysis["scores"]["sentiment"],
        "risk_score": analysis["scores"]["risk"],
        "risk_label": analysis["risk_label"],
        "reasons": reasons[:4],
        "plan": {"entry_low": plan["entry_low"], "entry_high": plan["entry_high"],
                 "stop_loss": plan["stop_loss"], "target": plan["target"],
                 "risk_reward": plan["risk_reward"]},
        "priority": candidate["priority"],
        "priority_boost": candidate["boost"],
        "headline": (f"{asset['ticker']} - {analysis['classification']} "
                     f"(score {analysis['opportunity_score']}): upside "
                     f"{plan['upside_to_target'] * 100:+.0f}% al target {plan['target']}"),
    }
