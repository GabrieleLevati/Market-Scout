/* Questionario iniziale e profilo locale (BR-01).

   Il cliente non deve dichiarare importi né posizioni: risponde a poche domande
   e il profilo si ricava da quelle. Le domande e le loro regole arrivano dal
   motore (`engine/onboarding.py`, esportate in data.js): qui c'è solo
   l'interprete, così la regola vive in un posto solo.

   Il profilo resta nel browser (localStorage): non viene spedito a nessuno.
   Con il profilo, questa pagina ricalcola quali delle opportunità già
   analizzate andrebbero segnalate — le stesse regole di
   engine/notifications.py, applicate qui perché una pagina statica non ha un
   backend (DEMO-21). In produzione la decisione resta sul server. */

const Onboarding = (function () {
'use strict';

const KEY = 'ams-profile';
const D = () => window.DEMO_DATA;

/* ----------------------------------------------------- profilo da risposte */
const SUM_KEYS = ['risk_points'];
const MAX_KEYS = ['experience_points'];   // conta la cosa più impegnativa, non quante
const CAP_ORDER = ['Conservativo', 'Bilanciato', 'Aggressivo'];

const BLANK = () => ({
  risk_points: 0,
  experience_points: 0,
  risk_cap: null,
  horizon: null,
  markets: [],
  sectors: [],
  asset_classes: [],
  channels: [],
  weekly_limit: null,
  currency: null,
  country: null,
  wants_portfolio: false,
});

function stricter(a, b) {
  if (a === null || a === undefined) return b === undefined ? null : b;
  if (b === null || b === undefined) return a;
  return CAP_ORDER.indexOf(a) <= CAP_ORDER.indexOf(b) ? a : b;
}

function applyEffects(sets, acc) {
  for (const [key, value] of Object.entries(sets || {})) {
    if (key.endsWith('_add')) {
      const target = key.slice(0, -4);
      for (const v of [].concat(value)) if (!acc[target].includes(v)) acc[target].push(v);
    } else if (SUM_KEYS.includes(key)) {
      acc[key] += value;
    } else if (MAX_KEYS.includes(key)) {
      acc[key] = Math.max(acc[key], value);
    } else if (key === 'risk_cap') {
      acc.risk_cap = stricter(acc.risk_cap, value);
    } else {
      acc[key] = value;
    }
  }
}

function profileFromAnswers(answers) {
  const conf = D().onboarding;
  const acc = BLANK();
  for (const q of conf.questions) {
    const given = answers[q.id];
    if (given === undefined || given === null) continue;
    for (const id of [].concat(given)) {
      const opt = q.options.find(o => o.id === id);
      if (opt) applyEffects(opt.sets, acc);
    }
  }
  const d = conf.defaults;
  const band = conf.risk_bands.find(b => acc.risk_points >= b.min && acc.risk_points <= b.max);
  const profile = {
    capital: null,
    horizon: acc.horizon || d.horizon,
    currency: acc.currency || d.currency,
    country: acc.country || d.country,
    risk_profile: band ? band.label : d.risk_profile,
    markets: acc.markets.length ? acc.markets : d.markets.slice(),
    sectors: acc.sectors.length ? acc.sectors : d.sectors.slice(),
    asset_classes: acc.asset_classes.length ? acc.asset_classes : d.asset_classes.slice(),
  };
  // Il tetto dichiarato vince sempre sulla somma dei punti.
  if (acc.risk_cap && CAP_ORDER.indexOf(profile.risk_profile) > CAP_ORDER.indexOf(acc.risk_cap)) {
    profile.risk_profile = acc.risk_cap;
  }
  // L'esperienza dichiarata non amplia il rischio: può solo limitarlo.
  if (acc.experience_points <= conf.inexperienced_below && profile.risk_profile === 'Aggressivo') {
    profile.risk_profile = 'Bilanciato';
  }
  if (profile.risk_profile === 'Conservativo') {
    profile.asset_classes = profile.asset_classes.filter(c => c !== 'Crypto');
  }
  // Monete digitali senza mercati mondiali non passerebbero mai il filtro.
  if (profile.asset_classes.includes('Crypto') && !profile.markets.includes('Global')) {
    profile.markets.push('Global');
  }
  return {
    id: 'me', name: 'Il mio profilo', first_name: '',
    profile: profile,
    channels: acc.channels.length ? acc.channels : d.channels.slice(),
    weekly_limit: acc.weekly_limit || d.weekly_limit,
    wants_portfolio: acc.wants_portfolio,
    positions: [], watchlist: [], notifications_this_week: 0,
    answers: answers,
    risk_points: acc.risk_points,
    from_questionnaire: true,
  };
}

/* ------------------------------------------------- decisione di notifica */
const CLASS_MAP = { 'Azioni': ['Azioni', 'REIT'], 'ETF': ['ETF'],
                    'Obbligazioni': ['Obbligazioni'], 'Crypto': ['Crypto'] };
const EQUITY_LIKE = ['Azioni', 'REIT'];
const MARKET_WORDS = { USA: 'gli Stati Uniti', Europa: "l'Europa", Asia: "l'Asia",
                       Global: 'i mercati globali' };
const CLASS_WORDS = { Azioni: 'le azioni singole', ETF: 'gli ETF',
                      Obbligazioni: 'le obbligazioni', Crypto: 'le monete digitali',
                      Commodities: 'le materie prime', REIT: 'le società immobiliari' };

function decideFor(user) {
  const d = D();
  const p = user.profile;
  const ceiling = d.meta.risk_ceiling[p.risk_profile];
  const threshold = d.meta.score_threshold;
  const limit = user.weekly_limit || d.meta.weekly_limit;
  const allowed = p.asset_classes.flatMap(c => CLASS_MAP[c] || []);
  const eligible = [];
  const rejected = [];

  for (const a of d.assets) {
    const drop = (kind, text) => rejected.push({ ticker: a.ticker, name: a.name,
                                                 score: a.opportunity_score, kind, text,
                                                 reason: text });
    if (a.valuable === false || a.scores.valuation === null) {
      drop('no_valuation', "Di questo strumento non ho i conti: senza quelli non so dire se " +
           'costa meno di quanto vale, quindi lo tengo d’occhio ma non glielo propongo.');
      continue;
    }
    if (a.asset_class === 'Commodities') {
      drop('asset_class_domain', 'Le materie prime non sono ancora tra i tipi di investimento ' +
           'che posso proporle.');
      continue;
    }
    if (!allowed.includes(a.asset_class)) {
      drop('asset_class', 'È un tipo di investimento che lei non ha scelto: ' +
           (CLASS_WORDS[a.asset_class] || a.asset_class) + '.');
      continue;
    }
    if (!p.markets.includes(a.market)) {
      drop('market', 'Si compra su un mercato che non ha messo nel suo profilo: ' +
           (MARKET_WORDS[a.market] || a.market) + '.');
      continue;
    }
    if (EQUITY_LIKE.includes(a.asset_class) && !p.sectors.includes(a.sector)) {
      drop('sector', 'È di un settore che non le interessa: ' + a.sector.toLowerCase() + '.');
      continue;
    }
    if (a.scores.risk > ceiling) {
      drop('risk', 'È più rischioso di quanto prevede il suo profilo ' +
           p.risk_profile.toLowerCase() + ': rischio ' + a.risk_label.toLowerCase() + '.');
      continue;
    }
    if (a.opportunity_score <= threshold) {
      drop('score', 'Ha preso ' + a.opportunity_score + ' punti su 100: interessante, ma ' +
           'sotto la soglia di ' + threshold + ' che ho con lei per scriverle.');
      continue;
    }
    eligible.push(a);
  }

  eligible.sort((x, y) => y.opportunity_score - x.opportunity_score);
  const selected = eligible.slice(0, limit);
  for (const a of eligible.slice(limit)) {
    const testo = 'Questa è interessante, ma le scrivo al massimo ' + limit +
                  ' volte a settimana: glielo segnalo la prossima.';
    rejected.push({ ticker: a.ticker, name: a.name, score: a.opportunity_score,
                    kind: 'weekly_limit', text: testo, reason: testo });
  }
  rejected.sort((x, y) => y.score - x.score);
  return { eligible: eligible, selected: selected, rejected: rejected,
           ceiling: ceiling, threshold: threshold, limit: limit };
}

/* --------------------------------------------------- racconto e impegni */
function story(user, decision) {
  const d = D();
  const s = d.stats;
  const p = user.profile;
  const out = [];
  out.push(d.meta.data_mode === 'real'
    ? `Ho preso i prezzi veri di ${s.assets} strumenti (ultima seduta ` +
      `${Charts.fmt.date(d.meta.today)}), i bilanci di ${d.data.with_fundamentals} e le ` +
      `notizie di ${d.data.with_news}.`
    : `Ho letto prezzi, bilanci e notizie di ${s.assets} investimenti su ` +
      `${s.markets.length} aree del mondo.`);
  out.push('Per ognuno ho controllato cinque cose: i conti di chi lo emette, l’andamento ' +
           'del prezzo, il confronto tra il prezzo e il valore che calcolo, le notizie delle ' +
           'ultime due settimane e quanto è rischioso.');
  out.push(`Ho trovato ${s.triggers} segnali degni di nota e ho dato un voto da 0 a 100 a ` +
           'ciascun investimento.');
  out.push(`Solo ${s.above_threshold} hanno superato ${decision.threshold} su 100, la soglia ` +
           'sotto la quale ho deciso di non disturbarla.');
  out.push(decision.eligible.length
    ? `Di quelli, ${decision.eligible.length} rientrano nel suo profilo ` +
      `(${p.risk_profile.toLowerCase()}, mercati ${p.markets.join(' e ')}).`
    : `Nessuno di quelli rientra nel suo profilo: mercati ${p.markets.join(' e ')}, settori ` +
      `${p.sectors.join(', ')}.`);
  out.push(decision.selected.length
    ? `Le ho segnalato ${decision.selected.length} ` +
      (decision.selected.length === 1 ? 'opportunità' : 'opportunità diverse') +
      `: non più di ${decision.limit} a settimana, perché preferisco scriverle poco e a ragione.`
    : 'Non le ho mandato nessuna segnalazione: quando non c’è niente di solido, il ' +
      'silenzio è la risposta giusta.');
  return out;
}

function commitments(user, decision) {
  const F = Charts.fmt;
  const out = decision.selected.map(a =>
    `Seguo ${a.name} ogni giorno e la avviso subito se scende sotto ` +
    `${F.num(a.plan.stop_loss)} o se arriva a ${F.num(a.plan.target)}.`);
  if (decision.selected.length) {
    out.push(`Se non mi dice nulla su ${decision.selected[0].ticker}, glielo ricordo una volta ` +
             'sola fra sette giorni, poi smetto.');
  }
  out.push('Se un giorno mi dice che cosa possiede, da quel momento controllo anche quello ' +
           'ogni giorno: per ora non le serve dirmelo.');
  out.push(`Domani mattina ripasso tutti i ${D().stats.assets} investimenti che tengo ` +
           'd’occhio, uno per uno.');
  const postponed = decision.rejected.filter(r => r.kind === 'weekly_limit');
  if (postponed.length) {
    out.push(`Ho ${postponed.length} segnalazione in attesa: le arriverà la settimana ` +
             'prossima, per non riempirla di messaggi.');
  }
  out.push('Non compro e non vendo niente al suo posto: decide sempre lei.');
  return out;
}

/* ------------------------------------------------------------- memoria */
function load() {
  try {
    const raw = localStorage.getItem(KEY);
    if (!raw) return null;
    const u = JSON.parse(raw);
    return (u && u.profile && u.profile.risk_profile) ? u : null;
  } catch (e) { return null; }
}
function save(user) {
  try { localStorage.setItem(KEY, JSON.stringify(user)); } catch (e) { /* niente */ }
}
function clear() {
  try { localStorage.removeItem(KEY); } catch (e) { /* niente */ }
}

/* ------------------------------------------------- esportazione profilo */
function toProfileJson(user) {
  return JSON.stringify({
    id: 'me', name: user.name, first_name: user.first_name || '',
    profile: user.profile,
    channels: user.channels,
    weekly_limit: user.weekly_limit,
    wants_portfolio: !!user.wants_portfolio,
    positions: user.positions || [],
    watchlist: user.watchlist || [],
    notifications_this_week: 0,
    _creato_da: 'questionario della vista cliente',
    _risposte: user.answers,
  }, null, 2);
}

return { profileFromAnswers, decideFor, story, commitments, load, save, clear, toProfileJson };
})();
