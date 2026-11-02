/* Dashboard demo (BR-10): Home, Opportunity Center, Portfolio, Research,
   Reports, più due aree di servizio (Pipeline e Scelte di demo) che servono a
   mostrare come il motore ha deciso. Script classico: nessun bundler. */

(function () {
'use strict';

const D = window.DEMO_DATA;
const F = Charts.fmt;
const $ = (sel, root = document) => root.querySelector(sel);
// punteggio assente = dato non disponibile, non zero
const nd = (v) => (v === null || v === undefined) ? '<span class="note">n.d.</span>' : v;

// L'etichetta di freschezza in testa alla pagina.
//
// Mostra l'ora dell'ultimo scambio dichiarata dalla borsa, non l'ora in cui e'
// girato il ciclo. La differenza conta: il ciclo gira dodici volte al giorno,
// anche di notte, e se scrivesse la propria ora direbbe "aggiornato alle 3:05"
// sopra dei prezzi fermi alla chiusura di New York. Un orario che si muove
// sopra dei numeri che non si muovono e' peggio di nessun orario, perche'
// invita a rileggere la pagina per vedere cosa e' cambiato quando non puo'
// essere cambiato niente.
function quandoTesto() {
  if (D.meta.data_mode !== 'real') return 'dimostrazione · dati simulati';
  const al = (D.data || {}).prezzi_al;
  const ora = al ? F.ora(al) : '';
  if (!ora) return 'controllato il ' + F.date(D.meta.today);
  if (!F.oggi(al)) return 'prezzi di chiusura del ' + F.date(al.slice(0, 10));
  return ((D.data || {}).seduta_in_corso ? 'prezzi delle ' : 'chiusura delle ') + ora;
}

const VIEWS = [
  { id: 'home', label: 'Home', group: 'Dashboard (BR-10)' },
  { id: 'opportunities', label: 'Opportunity Center' },
  { id: 'portfolio', label: 'Portfolio' },
  { id: 'research', label: 'Research' },
  { id: 'reports', label: 'Reports' },
  { id: 'pipeline', label: 'Pipeline del ciclo', group: 'Dietro le quinte' },
  { id: 'demo', label: 'Scelte di demo' },
];

const state = {
  mode: 'simple',          // 'simple' = la vista del cliente, 'expert' = la dashboard analista
  view: 'home',
  user: D.users[0].id,
  filters: { cls: '', market: '', min: 0, q: '' },
  research: 'MSFT',
  replay: 0,
  thread: [],              // conversazione con l'agente nella vista semplice
  pendingCharts: [],
  onbAnswers: {},          // risposte al questionario iniziale
  onbStep: 0,
  onbSkipped: false,
  localUser: null,         // profilo ricavato dal questionario (resta nel browser)
  // Lo stato dell'interfaccia cliente deve sopravvivere a un nuovo disegno:
  // render() ricostruisce tutto l'HTML, e senza questi due il foglio della
  // conversazione si chiuderebbe a ogni domanda e le schede aperte si
  // richiuderebbero da sole.
  sheet: false,            // foglio della conversazione aperto
  conf: false,             // foglio "come lavoro" aperto
  pagina: 'opportunita',   // 'opportunita' | 'seguiti'
  aperte: [],              // indici delle card girate
};

const assetByTicker = {};
D.assets.forEach(a => { assetByTicker[a.ticker] = a; });
// Il profilo caricato da profilo.json non è un esempio: è il tuo. Quando serve
// un profilo dimostrativo si prende il primo che non viene da quel file.
const demoUser = () => D.users.find(u => !u.from_file) || D.users[0];

const user = () => {
  if (state.user === 'local') {
    const u = state.localUser || (state.localUser = localUser());
    return u || demoUser();      // profilo cancellato: mai restituire null
  }
  return D.users.find(u => u.id === state.user) || demoUser();
};
const asset = (t) => assetByTicker[t];

/* ------------------------------------------------------------- utility */
function esc(s) { return String(s).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;'); }

/* Notifica nella stessa forma di engine/notifications.py:build_notification.
   Serve perché le due viste leggono gli stessi campi: se qui ne manca uno, la
   vista analista va in errore sul profilo del questionario. */
function localNotification(saved, a) {
  const plan = a.plan;
  const val = a.valuation || {};
  const reasons = (a.triggers || []).slice(0, 3).map(t => t.label);
  const drivers = ((a.agents.fundamental || {}).drivers || []).slice(0, 1)
    .concat(((a.agents.technical || {}).drivers || []).slice(0, 1));
  drivers.forEach(d => { if (d.score >= 70) reasons.push(d.label + ': ' + d.value); });
  return {
    notification_id: 'NTF-local-' + a.ticker.replace('.', '-') + '-' + D.meta.today,
    user_id: 'local', user_name: saved.name,
    sent_on: D.meta.today,
    channels: saved.channels,
    ticker: a.ticker, name: a.name, currency: a.currency,
    opportunity_score: a.opportunity_score, classification: a.classification,
    price: a.price,
    target_price: plan.target, upside: plan.upside_to_target,
    fundamental_score: a.scores.fundamental, technical_score: a.scores.technical,
    valuation_score: a.scores.valuation,
    fair_value: val.fair_value, valuation_source: val.source,
    valuation_confidence: val.confidence,
    sentiment_score: a.scores.sentiment,
    risk_score: a.scores.risk, risk_label: a.risk_label,
    reasons: reasons.slice(0, 4),
    plan: { entry_low: plan.entry_low, entry_high: plan.entry_high,
            stop_loss: plan.stop_loss, target: plan.target,
            risk_reward: plan.risk_reward },
    // Nessuna cronologia di interazioni nel browser: la priorità è il punteggio
    // e il moltiplicatore resta neutro, come nel motore a storico vuoto.
    priority: a.opportunity_score, priority_boost: 1,
    headline: a.ticker + ' - ' + a.classification + ' (score ' + a.opportunity_score +
              '): upside ' + (plan.upside_to_target >= 0 ? '+' : '') +
              Math.round(plan.upside_to_target * 100) + '% al target ' + plan.target,
  };
}

/* L'utente della vista cliente può venire da due posti: i profili calcolati dal
   motore (i tre clienti demo) o il questionario compilato nel browser. Qui si
   riportano alla stessa forma, così la vista è una sola. */
function localUser() {
  const saved = Onboarding.load();
  if (!saved) return null;
  const decision = Onboarding.decideFor(saved);
  const notifications = decision.selected.map(a => localNotification(saved, a));
  return {
    id: 'local', name: saved.name, first_name: saved.first_name || '',
    profile: saved.profile, channels: saved.channels, watchlist: [],
    notifications_this_week_before: 0,
    is_local: true, weekly_limit: decision.limit,
    decision: { notifications: notifications, eligible: decision.eligible,
                rejected: decision.rejected },
    plain_rejected: decision.rejected.slice(0, 3),
    plain_greeting: {
      line: (notifications.length === 0
        ? 'Buongiorno. Oggi non ho niente di urgente per lei.'
        : notifications.length === 1
          ? 'Buongiorno. Ho una cosa da farle vedere.'
          : `Buongiorno. Ho ${notifications.length} cose da farle vedere.`),
      sub: 'Ho lavorato stanotte sui mercati. Qui sotto trova tutto in ordine di ' +
           'importanza, e sotto ancora può chiedermi quello che vuole.',
    },
    plain_story: Onboarding.story(saved, decision),
    plain_commitments: Onboarding.commitments(saved, decision),
    plain_portfolio: {
      declared: false,
      summary: 'Non mi ha detto che cosa ha già, e va benissimo così: guardo il mercato ' +
               'per lei e le scrivo quando trovo qualcosa che vale la pena.',
      risk_sentence: 'Se un giorno vuole, può dirmi che cosa possiede: da quel momento ' +
                     'tengo d’occhio anche quello e la avviso se cambia qualcosa.',
      concentration_sentence: '', items: [], alerts_plain: [],
    },
    plain_assets: {},
    // La vista analista legge queste strutture: senza di esse andrebbe in
    // errore quando il cliente attivo è quello del questionario.
    portfolio: {
      user_id: 'local', positions: [], alerts: [], missing_tickers: [],
      total_value: 0, total_cost: 0, pl: 0, pl_pct: 0, cash: null,
      allocation_by_class: {}, allocation_by_sector: {}, allocation_by_market: {},
      hhi: 0, risk_score: 0,
      risk_ceiling: (D.meta.risk_ceiling || {})[saved.profile.risk_profile] || 60,
    },
    learned: { affinity: {}, top_sectors: [] },
    interactions: [],
    chat_chips: ['Che cosa ha fatto oggi per me?', 'Che profilo mi ha assegnato?',
                 'Come fa a dare un voto a un investimento?', 'Che cos’è un ETF?',
                 'Lei è un consulente finanziario?',
                 'Conviene comprare Microsoft?'],
    chat_answers: localAnswers(saved, decision),
    chat_fallback: [
      { type: 'text', text: 'Su questo non so risponderle con certezza, e preferisco dirglielo ' +
        'invece di inventare. Posso aiutarla su queste cose:' },
      { type: 'list', items: [
        'Che cosa ho fatto oggi e perché le ho segnalato (o non le ho segnalato) qualcosa',
        'Che cos’è un singolo investimento e se oggi è interessante — mi scriva il nome, ' +
        'per esempio "Microsoft" o "Bitcoin"',
        'Il significato delle parole difficili: ETF, stop loss, volatilità',
        'Il profilo che le ho assegnato e come lo cambio'] },
    ],
  };
}

function localAnswers(saved, decision) {
  const p = saved.profile;
  const a = {};
  a.portfolio_status = [
    { type: 'text', text: 'Non mi ha detto che cosa possiede, e non è obbligatorio: le ' +
      'percentuali le traduco su una base di 1.000 euro, così il confronto è chiaro comunque.' },
    { type: 'text', text: 'Se vuole che tenga d’occhio anche quello che ha già, me lo può dire ' +
      'in qualunque momento.' },
  ];
  a.portfolio_risk = [
    { type: 'text', text: `Il suo profilo è ${p.risk_profile.toLowerCase()}: le propongo solo ` +
      `investimenti con un rischio entro ${decision.ceiling} su 100.` },
    { type: 'text', text: 'Il rischio non si elimina, si dosa: per questo le ricordo sempre di ' +
      'non concentrare tutto su una sola idea e di tenere una vendita automatica di protezione.' },
  ];
  a.what_did_you_do = [{ type: 'list', items: Onboarding.story(saved, decision) },
                       { type: 'pipeline_link' }];
  a.commitments = [{ type: 'text', text: 'Da qui in avanti mi occupo io di queste cose:' },
                   { type: 'list', items: Onboarding.commitments(saved, decision) }];
  a.my_profile = [
    { type: 'text', text: `Dalle sue risposte l’ho capita così: profilo ` +
      `${p.risk_profile.toLowerCase()}, orizzonte ${p.horizon.toLowerCase()}, senza importi ` +
      `dichiarati.` },
    { type: 'list', items: [
      `Mercati che le interessano: ${p.markets.join(', ')}`,
      `Settori preferiti: ${p.sectors.join(', ')}`,
      `Tipi di investimento: ${p.asset_classes.join(', ')}`,
      `Canali su cui le scrivo: ${saved.channels.join(', ')}`,
      `Al massimo ${decision.limit} segnalazioni a settimana`] },
    { type: 'text', text: 'Se ho capito male, può rifare il questionario dal fondo della pagina.' },
  ];
  a.what_now = decision.selected.length
    ? [{ type: 'text', text: `Sulla cosa che le ho segnalato, ${decision.selected[0].name}, ` +
         `farei così:` },
       { type: 'list', items: (D.plain[decision.selected[0].ticker] || {}).what_to_do || [] },
       { type: 'text', text: (D.plain[decision.selected[0].ticker] || {}).caveat || '' }]
    : [{ type: 'text', text: 'Oggi non farei nulla di nuovo. Le scrivo io quando c’è un motivo.' }];
  a.why_notified = decision.selected.length
    ? [{ type: 'text', text: `Le ho segnalato ${decision.selected.length} ` +
         `${decision.selected.length === 1 ? 'opportunità' : 'opportunità'} perché ha superato ` +
         `il voto di ${decision.threshold} su 100 e rientra nel suo profilo.` },
       ...decision.selected.map(x => ({ type: 'asset_card', ticker: x.ticker }))]
    : [{ type: 'text', text: 'Oggi non le ho segnalato niente, e non è una dimenticanza: ' +
         'nessun investimento ha superato la soglia restando dentro il suo profilo.' },
       { type: 'list', title: 'I casi più vicini, e perché li ho scartati',
         items: decision.rejected.slice(0, 3).map(r => `${r.name}: ${r.text}`) }];
  return a;
}



/* =========================================================================
   I PRODOTTI SEGUITI

   La stellina mette uno strumento sotto osservazione. Si salva nel browser
   insieme al prezzo e al valore stimato del giorno in cui l'hai messa: senza
   quel riferimento non si potrebbe dire "da quando la segui ha fatto +3%",
   che e' l'unica cosa che interessa a chi segue qualcosa.
   ========================================================================= */
const SEGUITI = 'ams-seguiti';

function seguitiLeggi() {
  try {
    const d = JSON.parse(localStorage.getItem(SEGUITI) || '{}');
    return (d && typeof d === 'object') ? d : {};
  } catch (e) { return {}; }
}
function seguitiScrivi(d) {
  try { localStorage.setItem(SEGUITI, JSON.stringify(d)); } catch (e) { /* niente */ }
}
function segue(ticker) { return !!seguitiLeggi()[ticker]; }

function seguiAlterna(o) {
  const d = seguitiLeggi();
  if (d[o.ticker]) {
    delete d[o.ticker];
  } else {
    d[o.ticker] = {
      dal: D.meta.today,
      prezzo: o.price,            // il prezzo del giorno in cui l'hai seguita
      target: o.target,
      stop: o.stop_loss,
      nome: o.name,
      valuta: o.currency,
    };
  }
  seguitiScrivi(d);
  return !!d[o.ticker];
}

/* Come sta andando uno strumento seguito, e che cosa conviene fare.
   Le regole sono le stesse del motore, non opinioni nuove: raggiunto il valore
   stimato, rotto il livello di uscita, oppure ancora in mezzo. */
function statoSeguito(ticker, salvato) {
  const a = asset(ticker);
  // carte() e non solo la lista: si puo' seguire anche un osservato, e in quel
  // caso il suo prezzo e i suoi dati stanno li'. Cercando nella sola lista
  // delle opportunita' un osservato seguito sarebbe risultato "non ho piu' i
  // dati di questo strumento", che e' falso.
  const opp = carte().find(o => o.ticker === ticker);
  const prezzoOggi = a ? a.price : (opp ? opp.price : null);
  if (prezzoOggi === null || prezzoOggi === undefined) {
    return { nome: salvato.nome || ticker, ticker: ticker, noto: false,
             riga: 'Non ho più i dati di questo strumento in questo ciclo.',
             azione: 'Lo rivedo al prossimo controllo.', da: salvato.dal };
  }
  const daQuando = salvato.prezzo ? (prezzoOggi / salvato.prezzo - 1) : null;
  const target = (opp && opp.target) || salvato.target;
  const stop = (opp && opp.stop_loss) || salvato.stop;
  const mancano = target ? (target / prezzoOggi - 1) : null;

  let azione, livello;
  if (target && prezzoOggi >= target) {
    livello = 'arrivato';
    azione = 'Ha raggiunto il valore che gli attribuivo. Da qui non ho più un ' +
             'motivo per tenerlo: valuterei se uscire.';
  } else if (stop && prezzoOggi <= stop) {
    livello = 'rotto';
    azione = 'È scesa sotto il livello di uscita che mi ero dato: la tesi non ' +
             'regge più, uscirei con una perdita piccola.';
  } else if (opp) {
    livello = 'in corso';
    const allUscita = stop ? (stop / prezzoOggi - 1) : null;
    azione = 'Resta una delle opportunità di oggi: la tesi tiene, non farei nulla.' +
      (allUscita !== null
        ? ` Il livello di uscita è a ${Charts.fmt.num(stop)}, cioè ` +
          `${Charts.fmt.signed(allUscita)} da qui: finché non ci arriva, un calo è rumore.`
        : '');
  } else {
    livello = 'uscito';
    azione = 'Non è più sopra la soglia: non la segnalerei a nuovi, ma se già la ' +
             'ha non c\'è un motivo per muoversi finché non rompe il livello di uscita.';
  }
  return {
    ticker: ticker, nome: (opp && opp.name) || salvato.nome || ticker,
    noto: true, da: salvato.dal,
    prezzo: prezzoOggi, prezzoAllora: salvato.prezzo,
    valuta: (opp && opp.currency) || salvato.valuta || '',
    daQuando: daQuando, mancano: mancano, target: target, stop: stop,
    livello: livello, azione: azione,
    score: opp ? opp.score : null,
  };
}

/* =========================================================================
   LA CARD DELL'OPPORTUNITA', due facce.
   Fronte: che cos'e', il verdetto, e la mia visione in parole.
   Retro:  i dati, per chi vuole verificare.
   ========================================================================= */
function fascia(score) {
  return score >= 90 ? 'eccezionale' : score >= 80 ? 'forte'
       : score >= 70 ? 'da monitorare' : 'nessuna azione';
}

/* LE CARD A SCHERMO, IN ORDINE: le opportunita' vere e poi gli osservati.
   Una funzione sola perche' l'indice di una card e' usato in tre posti
   lontani fra loro - il disegno, l'anello col voto e la stellina - e se
   quei tre non contassero nella stessa maniera la stella di una card
   seguirebbe un altro strumento. Meglio un elenco unico che tre liste da
   tenere allineate a mano. */
function carte() {
  const o = D.opportunita || {};
  return (o.lista || []).concat(o.osservati || []);
}

/* Un numero da mostrare, o null se non c'e'. Serve perche' rigaDato() salta
   le righe vuote ma non quelle che valgono "-": per gli osservati, che non
   hanno prezzo obiettivo, una riga "Target price -" occuperebbe spazio per
   dire niente. */
function numOpz(v, d) {
  return (v === null || v === undefined) ? null : F.num(v, d === undefined ? 2 : d);
}

function rigaDato(etichetta, valore, nota) {
  if (valore === null || valore === undefined || valore === '') return '';
  return `<div><dt>${esc(etichetta)}</dt><dd>${valore}${
    nota ? `<i>${esc(nota)}</i>` : ''}</dd></div>`;
}

/* In una riga: che cos'e' e dove sta. "ETF sulle piccole imprese giapponesi"
   si costruisce da qui, dai campi che il motore ha gia'.

   Attenzione alla grammatica: un'azione e' UNA impresa (singolare femminile),
   un ETF ne tiene MOLTE (plurale). Con un'unica tabella di aggettivi veniva
   fuori "azione di un'impresa grandissime americane", che fa sembrare
   sciatto tutto il resto. */
const LUOGO = {
  singolare: { USA: 'americana', Europa: 'europea', Asia: 'asiatica',
               Global: 'internazionale' },
  plurale:   { USA: 'americane', Europa: 'europee', Asia: 'asiatiche',
               Global: 'di tutto il mondo' },
};
const TAGLIA = {
  singolare: { 'Mega cap': 'grandissima', 'Large cap': 'grande',
               'Mid cap': 'media', 'Small cap': 'piccola' },
  plurale:   { 'Mega cap': 'grandissime', 'Large cap': 'grandi',
               'Mid cap': 'medie', 'Small cap': 'piccole' },
};

function targhetta(o) {
  const num = (o.asset_class === 'Azioni' || o.asset_class === 'REIT')
    ? 'singolare' : 'plurale';
  const dove = LUOGO[num][o.market] || o.market || '';
  const taglia = TAGLIA[num][o.size] || '';
  // il settore si scrive come lo scrive il motore: "AI" non "ai"
  const settore = o.sector && o.sector !== 'Diversificato' ? o.sector : '';

  if (o.asset_class === 'ETF') {
    return ['ETF su imprese', taglia, dove].filter(Boolean).join(' ') +
           (settore ? `, settore ${settore}` : '');
  }
  if (o.asset_class === 'Obbligazioni') return `Obbligazioni ${dove}`.trim();
  if (o.asset_class === 'Crypto') return 'Moneta digitale';
  if (o.asset_class === 'Commodities') return 'Materia prima';
  if (o.asset_class === 'REIT') return `Società immobiliare ${dove}`.trim();
  return ["Azione di un'impresa", taglia, dove].filter(Boolean).join(' ') +
         (settore ? `, settore ${settore}` : '');
}

function opportunityCard(o, idx) {
  const a = asset(o.ticker);
  const id = o.identita || {};
  const girata = state.aperte.indexOf(idx) > -1;
  const sc = o.scores || {};
  const v = o.visione || {};
  const seguita = segue(o.ticker);
  // "nuova" vuol dire: non c'era nell'ultima versione pubblicata, cioe' in
  // quello che l'utente ha visto finora. E' l'unico confronto che per lui
  // significa qualcosa.
  const n = D.novita || {};
  const nuova = (n.nuove || []).indexOf(o.ticker) > -1 && !n.primo_giro;
  const salita = (n.salite || []).indexOf(o.ticker) > -1;
  const scesa = (n.scese || []).indexOf(o.ticker) > -1;
  // L'ISIN non viene da nessuna fonte gratuita. Una riga che dice "non
  // disponibile" occupa spazio per dire niente: se c'e' si mostra, se manca
  // la riga non esiste. Quello che non si mostra mai e' un ISIN indovinato.
  const isin = id.isin ? `<span class="mono">${esc(id.isin)}</span>` : null;
  return `
  <div class="flip${girata ? ' girata' : ''}" id="opp-${idx}" style="--i:<#i>">
    <div class="flip-inner">

      <div class="faccia avanti">
        <div class="fr-top">
          <div>
            <span class="light ${o.score >= 85 ? 'verde' : 'giallo'}">
              <span class="ic">${o.score >= 85 ? '✓' : '▲'}</span>${esc(o.classification)}</span>
            ${nuova ? '<span class="nuova">nuova</span>' : ''}${
              salita ? '<span class="mossa su">&#9650; salita</span>'
              : scesa ? '<span class="mossa giu">&#9660; scesa</span>' : ''}
            <div class="fr-nome">${esc(o.name)}<span class="tk">${esc(o.ticker)} ·
              ${esc(targhetta(o))}</span></div>
          </div>
          <div class="fr-destra">
            <button class="stella${seguita ? ' on' : ''}" data-act="segui" data-i="${idx}"
              title="${seguita ? 'Smetti di seguirla' : 'Segui questo strumento'}"
              aria-pressed="${seguita}">${seguita ? '★' : '☆'}</button>
            <div class="ring" id="ring-${idx}" title="Voto ${o.score} su 100"></div>
          </div>
        </div>
        ${o.che_cos_e ? `<p class="fr-cos">${esc(o.che_cos_e)}</p>` : ''}
        <div class="fr-spark"><div class="spark" id="sch-${idx}"></div></div>
        ${o.senza_valore ? `<div class="fr-euro sv">Costa
          <b>${F.num(o.price)} ${esc(o.currency)}</b>. Di questo strumento non
          stimo quanto vale: non ha bilanci da cui calcolarlo, quindi non ho un
          prezzo obiettivo da darle.</div>`
        : `<div class="fr-euro${v.al_tetto ? ' incerto' : ''}">Costa
          <b>${F.num(o.price)} ${esc(o.currency)}</b>,
          secondo i miei conti vale <b>${F.num(o.target)}</b>:
          ${F.signed(o.upside)} rispetto a oggi.${v.al_tetto
            ? ' <span class="nota">stima al tetto del modello, poco precisa</span>' : ''}</div>`}
        ${(v.azione || v.attesa) ? `<div class="visione">
          <div class="vt">La mia visione</div>
          <p class="va">${esc(v.azione || '')}</p>
          <p>${esc(v.attesa || '')}</p>
          ${v.orizzonte ? `<p class="vo"><span>Orizzonte</span>
            <b>${esc(v.orizzonte)}</b></p>` : ''}
          ${v.limite ? `<p class="vl">${esc(v.limite)}</p>` : ''}
          <p class="vr">${esc(v.rumore || '')}</p>
          <p class="vc">${esc(v.cambio_idea || '')}</p>
          ${(v.scenari || []).length ? `<details class="vs">
            <summary>I tre scenari, con le probabilità</summary>
            ${v.scenari.map(t => `<p>${esc(t)}</p>`).join('')}</details>` : ''}
        </div>` : ''}
        <div class="cbar">
          <button data-act="gira" data-i="${idx}">Girala: tutti i dati &rarr;</button>
        </div>
      </div>

      <div class="faccia dietro">
        <div class="dt-top">
          <div class="n">${esc(o.ticker)}</div>
          <div class="v">${o.score}/100 · ${esc(fascia(o.score))}</div>
        </div>
        <dl class="sint fitta">
          ${rigaDato('ISIN', isin, id.isin_fonte || null)}
          ${rigaDato('Codice FIGI', id.figi ? `<span class="mono">${esc(id.figi)}</span>` : null,
                     'identificativo aperto')}
          ${rigaDato('Tipologia', esc(o.asset_class), id.tipo || null)}
          ${rigaDato('Settore', esc(o.sector))}
          ${rigaDato('Mercato', esc(o.market), o.size ? String(o.size) : null)}
          ${rigaDato('Valuta', esc(o.currency))}
          ${rigaDato('Prezzo oggi', F.num(o.price))}
          ${rigaDato('Target price', numOpz(o.target),
                     o.upside === null || o.upside === undefined
                       ? null : F.signed(o.upside))}
          ${rigaDato('Uscita (stop)', numOpz(o.stop_loss),
                     o.downside === null || o.downside === undefined
                       ? null : F.signed(o.downside))}
          ${rigaDato('Fascia di ingresso', o.entry_low === null || o.entry_low === undefined
                     ? null : F.num(o.entry_low) + ' – ' + F.num(o.entry_high))}
          ${rigaDato('Rischio / rendimento', o.risk_reward === null
                     || o.risk_reward === undefined ? null : F.num(o.risk_reward) + 'x')}
          ${o.senza_valore ? rigaDato('Prezzo obiettivo', 'non calcolabile',
                                      'senza bilanci non stimo un valore') : ''}
          ${rigaDato('Rischio', esc(o.risk_label), o.risk_score + '/100')}
          ${rigaDato('Orizzonte della mia stima', esc(v.orizzonte || ''))}
          ${rigaDato('Come ho calcolato il valore', esc(o.valuation_method || ''),
                     o.valuation_confidence
                       ? 'confidenza ' + o.valuation_confidence + '/100' +
                         (o.valuation_confidence < 70 ? ' — bassa' : '')
                       : null)}
        </dl>
        <div class="comp">
          ${[['conti', sc.fundamental], ['prezzo', sc.technical], ['valore', sc.valuation],
             ['notizie', sc.sentiment], ['rischio', sc.risk]].map(([k, val]) => `
            <div class="cq"><span class="k">${k}</span>
              <span class="b"><i style="width:${val === null || val === undefined ? 0 : val}%"></i></span>
              <span class="n">${val === null || val === undefined ? 'n.d.' : val}</span></div>`).join('')}
        </div>
        ${(o.reasons || []).length ? `<ul class="perche">
          ${o.reasons.map(r => `<li><span class="ic">&check;</span>
            <span><b>${esc(r)}</b></span></li>`).join('')}</ul>` : ''}
        <div class="cbar">
          <button class="quieto" data-act="gira" data-i="${idx}">&larr; Indietro</button>
        </div>
      </div>

    </div>
  </div>`;
}

/* =========================================================================
   LA PAGINA: le opportunita' di oggi, e quelle che segui.
   ========================================================================= */
/* La pagina dei preferiti. Prima stava in fondo alle opportunita': chi seguiva
   qualcosa doveva scorrere tutte le card per arrivarci, ed e' il contrario di
   quello che serve a chi ha gia' scelto. Ora e' una pagina sua. */
function vistaSeguiti() {
  const d = seguitiLeggi();
  const ticker = Object.keys(d);
  const stati = ticker.map(t => statoSeguito(t, d[t]));
  const segno = (x) => (x === null || x === undefined) ? '' : (x >= 0 ? 'su' : 'giu');

  let i = 0;
  const blocchi = [];
  const push = (html) => { if (html) blocchi.push(html.split('<#i>').join(String(i++))); };

  const titolo = stati.length === 0 ? 'Non sta seguendo niente.'
    : stati.length === 1 ? 'Segue un prodotto.' : 'Segue ' + stati.length + ' prodotti.';
  push(`<div class="hero" style="--i:<#i>">
    <span class="quando${D.meta.data_mode === 'real' ? '' : ' finta'}"><i></i>${
      esc(quandoTesto())}</span>
    <h1>${esc(titolo)}</h1>
  </div>`);

  if (!stati.length) {
    push(`<div class="vuoto" style="--i:<#i>">
      <h2>Qui finiscono i prodotti che mette sotto osservazione</h2>
      <p>Nella pagina delle opportunità tocchi la stellina in alto a destra di una card.
        Da quel momento le dico come sta andando rispetto a quando l'ha seguita, e che
        cosa conviene fare.</p>
      <div class="cbar" style="margin-top:16px">
        <button data-act="pagina" data-p="opportunita">Vai alle opportunità</button>
      </div>
    </div>`);
  }

  stati.forEach((st) => push(`
    <div class="scard sr ${esc(st.livello || '')}" style="--i:<#i>">
      <div class="sr-cap">
        <div class="sr-nome">${esc(st.nome)}<span>${esc(st.ticker)}${
          st.score !== null && st.score !== undefined ? ' · ' + st.score + '/100' : ''}</span></div>
        ${st.daQuando === null || st.daQuando === undefined ? ''
          : `<div class="sr-var ${segno(st.daQuando)}">${F.signed(st.daQuando)}
               <i>da quando la segue</i></div>`}
        <button class="stella on" data-act="smetti" data-t="${esc(st.ticker)}"
          title="Smetti di seguirla" aria-label="Smetti di seguire ${esc(st.nome)}">&#9733;</button>
      </div>
      ${st.noto ? `<dl class="sint fitta" style="margin:12px 0 0">
        <div><dt>Costa oggi</dt><dd>${F.num(st.prezzo)}<i>${esc(st.valuta)}</i></dd></div>
        ${st.prezzoAllora ? `<div><dt>Quando l'ha seguita</dt>
          <dd>${F.num(st.prezzoAllora)}</dd></div>` : ''}
        ${st.target ? `<div><dt>Secondo me vale</dt><dd>${F.num(st.target)}<i>${
          st.mancano !== null && st.mancano !== undefined ? F.signed(st.mancano) + ' da qui' : ''
        }</i></dd></div>` : ''}
        ${st.stop ? `<div><dt>Esco se scende a</dt><dd>${F.num(st.stop)}</dd></div>` : ''}
        <div><dt>Segue da</dt><dd>${esc(F.date(st.da || D.meta.today))}</dd></div>
      </dl>` : ''}
      <div class="sr-az">${esc(st.azione)}</div>
    </div>`));

  if (stati.length) {
    push(`<p class="chiusa" style="--i:<#i>">L'elenco resta in questo browser: non lo
      vedo io e non esce da qui. Si aggiorna a ogni controllo, ogni due ore.</p>`);
  }
  return blocchi.join('\n');
}


function viewSimple() {
  // Due pagine, un disegno: l'intestazione e il foglio "come lavoro" sono gli
  // stessi, cambia il corpo. Cosi' non ci sono due impianti da tenere allineati.
  const inSeguiti = state.pagina === 'seguiti';
  const quanti = Object.keys(seguitiLeggi()).length;
  const altra = inSeguiti ? 'opportunita' : 'seguiti';
  const opp = (D.opportunita && D.opportunita.lista) || [];
  const scartati = (D.opportunita && D.opportunita.scartati) || [];
  const soglia = (D.opportunita && D.opportunita.soglia) || D.meta.score_threshold;

  let i = 0;
  const blocchi = [];
  const push = (html) => { if (html) blocchi.push(html.split('<#i>').join(String(i++))); };

  const titolo = opp.length === 0 ? 'Nessuna opportunità, in questo momento.'
    : opp.length === 1 ? 'Una opportunità.' : opp.length + ' opportunità.';

  push(`<div class="hero" style="--i:<#i>">
    <span class="quando${D.meta.data_mode === 'real' ? '' : ' finta'}"><i></i>${
      esc(quandoTesto())}</span>
    <h1>${esc(titolo)}</h1>
  </div>`);

  opp.forEach((o, k) => push(opportunityCard(o, k)));

  /* GLI OSSERVATI, in una sezione loro e non mescolati sopra.
     Sono strumenti che hanno superato la soglia ma di cui non si puo' stimare
     un valore: ETF, obbligazionari, materie prime non hanno bilanci. Senza
     valore stimato non c'e' prezzo obiettivo, quindi non sono opportunita' e
     metterli nella stessa lista direbbe una cosa falsa. Ma tenerli invisibili
     ne nascondeva di buoni: un ETF a 75 punti era il secondo punteggio della
     giornata e non arrivava in pagina. Quindi: visibili, separati, e con
     scritto perche' sono separati. */
  const osservati = (D.opportunita && D.opportunita.osservati) || [];
  if (osservati.length) {
    push(`<div class="sezione" style="--i:<#i>">
      <h2>${osservati.length === 1 ? 'Ne tengo d’occhio un altro'
            : 'Ne tengo d’occhio altri ' + osservati.length}</h2>
      <p>Hanno superato ${soglia} punti, ma sono panieri, obbligazioni o materie
        prime: non hanno bilanci, quindi non posso calcolare quanto valgono e non
        le do un prezzo obiettivo. Non sono proposte d’acquisto e non le
        segnalo con una notifica.</p>
    </div>`);
    osservati.forEach((o, k) => push(opportunityCard(o, opp.length + k)));
  }

  const nov = D.novita || {};
  const nuove = (nov.nuove || []).length;
  const uscite = (nov.uscite || []).length;
  if (!nov.primo_giro && (nuove || uscite)) {
    push(`<p class="movimenti" style="--i:<#i>">${[
      nuove ? `<b>${nuove}</b> ${nuove === 1 ? 'nuova' : 'nuove'} rispetto all'ultimo controllo`
            : '',
      uscite ? `<b>${uscite}</b> ${uscite === 1 ? 'è scesa' : 'sono scese'} sotto ${soglia} e
                ${uscite === 1 ? 'non la propongo più' : 'non le propongo più'}
                (${esc((nov.uscite || []).join(', '))})` : '',
    ].filter(Boolean).join(' · ')}</p>`);
  }

  if (!opp.length) {
    /* Il testo cambia se ci sono osservati, e non e' pignoleria: dire
       "nessuno ha superato 70" mentre poco sopra c'e' una card con 75 punti
       e' una contraddizione che si legge in pagina. Gli osservati HANNO
       superato la soglia; quello che non hanno e' un prezzo obiettivo. */
    push(`<div class="vuoto" style="--i:<#i>">
      <h2>Oggi non c'è niente da proporle</h2>
      <p>${osservati.length
        ? `Non è un guasto: dei ${D.stats.assets} strumenti controllati, nessuno di
           quelli di cui riesco a stimare un valore ha superato ${soglia} punti su 100.
           ${osservati.length === 1 ? 'Quello qui sopra lo ha superato'
             : 'Quelli qui sopra la hanno superata'}, ma senza bilanci non posso dirle
           a che prezzo vale la pena comprarlo.`
        : `Non è un guasto: nessuno dei ${D.stats.assets} strumenti controllati ha superato
           ${soglia} punti su 100.`}
        Il controllo si ripete ogni due ore, e appena qualcosa
        supera la soglia arriva la notifica.</p>
      ${scartati.length ? `<div class="vicini">
        <div class="conto">i più vicini</div>
        ${scartati.slice(0, 4).map(v => `<div class="vic">
          <span class="t">${esc(v.name)}</span>
          <span class="s">${v.score}</span>
          <span class="m">${esc(v.motivo)}</span></div>`).join('')}
      </div>` : ''}
    </div>`);
  }

  push(vistaSeguiti());

  push(`<p class="chiusa" style="--i:<#i>">Supporto decisionale su dati di mercato:
    non sostituisce il consulente finanziario. Nessun ordine viene inviato.
    ${D.meta.data_mode === 'real'
      ? 'Prezzi e bilanci veri (' + esc(D.meta.data_source || '') + ').'
      : 'In questa dimostrazione i dati sono simulati.'}</p>`);

  const d = D.data || {};
  const reale = D.meta.data_mode === 'real';
  const fonti = [
    ['Prezzi e andamento', reale ? (d.source || 'Yahoo Finance') : 'generatore della demo', true],
    ['Ultimo scambio sul mercato',
     reale ? (d.prezzi_al ? F.date(d.prezzi_al.slice(0, 10)) + ' alle ' + F.ora(d.prezzi_al)
                          : 'non dichiarato')
           : 'simulato',
     reale ? !!d.prezzi_al : true],
    ['Bilanci societari', reale ? (d.with_fundamentals || 0) + ' strumenti' : 'simulati',
     reale ? !!d.with_fundamentals : true],
    ['Notizie, ultime due settimane', reale ? (d.with_news || 0) + ' strumenti' : 'simulate',
     reale ? !!d.with_news : true],
    ['Giudizio sulle notizie', D.llm && D.llm.enabled ? 'AI · ' + D.llm.model : 'non disponibile',
     !!(D.llm && D.llm.enabled)],
  ];
  const conf = `
  <div class="velo${state.conf ? ' on' : ''}" id="velo"></div>
  <aside class="sheet${state.conf ? ' on' : ''}" id="conf" aria-label="Come lavoro">
    <div class="maniglia"><i></i></div>
    <div class="testa">
      <div class="t">Come lavoro<small>${D.stats.assets} strumenti, ${D.stats.triggers}
        segnali in questo ciclo</small></div>
      <div class="spacer"></div>
      <button class="chiudi" id="chiudiConf">Chiudi</button>
    </div>
    <div class="corpo">
      <div class="conto" style="padding-top:0">da dove prendo i dati</div>
      <div class="righe">
        ${fonti.map(f => `<div class="riga">
          <div><span class="pallino ${f[2] ? 'ok' : 'no'}"></span>${esc(f[0])}</div>
          <div class="val">${esc(String(f[1]))}</div></div>`).join('')}
      </div>
      <div class="conto">come scelgo</div>
      <div class="righe">
        <div class="riga"><div>Cinque voti da 0 a 100 per ogni strumento
          <div class="d">conti dell'azienda 30%, andamento del prezzo 20%, confronto fra
          prezzo e valore 25%, notizie 15%, rischio 10% (al contrario: meno rischio,
          più punti)</div></div></div>
        <div class="riga"><div>Soglia ${soglia} su 100
          <div class="d">sotto quella non segnalo niente, per nessuno: le opportunità sono
          le stesse per tutti</div></div></div>
        <div class="riga"><div>Controllo ogni due ore
          <div class="d">se una cosa nuova supera la soglia arriva una notifica; se è la
          stessa di prima, non la ripeto</div></div></div>
        <div class="riga"><div>Quanto tempo do alle mie stime
          <div class="d">l'orizzonte lo calcolo dalla volatilità dello strumento, non lo
          scelgo: un movimento ampio su un titolo tranquillo richiede mesi, e dirlo in
          due settimane sarebbe una bugia</div></div></div>
        <div class="riga"><div>Strumenti senza bilanci
          <div class="d">ETF, obbligazioni e cripto non hanno conti da leggere: li
          monitoro ma non li propongo, e lo dichiaro</div></div></div>
      </div>
      <div class="conto">parole difficili</div>
      <div class="know">
        ${D.glossary.map(g => `<details><summary>${esc(
          g.term.charAt(0).toUpperCase() + g.term.slice(1))}</summary>
          <p>${esc(g.definition)}</p></details>`).join('')}
      </div>
    </div>
  </aside>`;

  return `
  <div class="topper" id="topper">
    <div class="brandline">${inSeguiti ? 'Che segue' : 'Opportunità'}<small>AI Market
      Scout · ${F.date(D.meta.today)}</small></div>
    <div class="spacer"></div>
    <button class="tbtn stella-nav${quanti && !inSeguiti ? ' pieni' : ''}"
      data-act="pagina" data-p="${altra}"
      title="${inSeguiti ? 'Torna alle opportunità'
        : (quanti ? 'I prodotti che segue' : 'Niente ancora sotto osservazione')}">${
      inSeguiti ? '&#8592;' : (quanti ? '&#9733;' : '&#9734;')}${
      quanti && !inSeguiti ? `<b>${quanti}</b>` : ''}</button>
    <button class="tbtn" id="confBtn" title="Come lavoro e da dove prendo i dati">&#9432;</button>
    <button class="tbtn" id="themeBtn2" title="Chiaro o scuro">&#9681;</button>
  </div>
  <div class="feed">${inSeguiti ? vistaSeguiti() : blocchi.join('\n')}</div>
  ${conf}`;
}

/* ======================================================================
   QUESTIONARIO INIZIALE (BR-01): una domanda per schermata, niente importi.
   ====================================================================== */
function viewQuestionnaire() {
  const conf = D.onboarding;
  const qs = conf.questions;
  const step = Math.min(state.onbStep, qs.length);
  if (step >= qs.length) return viewQuestionnaireRecap();
  const q = qs[step];
  const given = state.onbAnswers[q.id];
  const chosen = given === undefined ? [] : [].concat(given);
  return `
  <div class="onb">
    <div class="steps-bar">${qs.map((_, i) =>
      `<i class="${i <= step ? 'done' : ''}"></i>`).join('')}</div>
    <div class="kicker">Domanda ${step + 1} di ${qs.length}</div>
    <h1>${esc(q.text)}</h1>
    <p class="help">${esc(q.help)}${q.kind === 'multi'
      ? ' <strong>Può scegliere più di una risposta.</strong>' : ''}</p>
    <div class="opts">
      ${q.options.map(o => `
        <button class="opt ${chosen.includes(o.id) ? 'sel' : ''}" data-opt="${o.id}">
          <span class="box">${chosen.includes(o.id) ? '✓' : ''}</span>
          <span>${esc(o.label)}</span>
        </button>`).join('')}
    </div>
    <div class="onb-nav">
      ${step > 0 ? '<button data-onb="back">Indietro</button>' : ''}
      <div class="spacer"></div>
      <button class="go" data-onb="next" ${chosen.length ? '' : 'disabled'}>
        ${step === qs.length - 1 ? 'Ho finito' : 'Avanti'}</button>
    </div>
    <div style="margin-top:18px">
      <button class="skip" data-onb="skip">Salto le domande e guardo com’è fatto</button>
    </div>
    <p class="small-note" style="margin-top:26px">${esc(conf.privacy_note)}</p>
  </div>`;
}

function viewQuestionnaireRecap() {
  const u = Onboarding.profileFromAnswers(state.onbAnswers);
  state.onbPreview = u;
  const p = u.profile;
  const dec = Onboarding.decideFor(u);
  const rows = [
    ['Come la tratto', p.risk_profile.toLowerCase()],
    ['Per quanto tempo', p.horizon.toLowerCase()],
    ['Dove guardo', p.markets.join(', ')],
    ['Di che cosa le parlo', p.sectors.join(', ')],
    ['Che strumenti le propongo', p.asset_classes.join(', ')],
    ['Quanto la disturbo', `al massimo ${u.weekly_limit} ` +
      (u.weekly_limit === 1 ? 'volta' : 'volte') + ' a settimana'],
    ['Dove le scrivo', u.channels.join(', ')],
    ['Rischio massimo che le propongo', `${dec.ceiling} su 100`],
  ];
  return `
  <div class="onb">
    <div class="steps-bar">${D.onboarding.questions.map(() => '<i class="done"></i>').join('')}</div>
    <div class="kicker">Ci siamo</div>
    <h1>${esc(D.onboarding.closing.title)}</h1>
    <p class="help">${esc(D.onboarding.closing.body)}</p>
    <div class="recap">
      ${rows.map(([k, v]) => `<div><span>${esc(k)}</span><span><strong>${esc(v)}</strong></span></div>`).join('')}
    </div>
    ${(p.asset_classes.includes('Crypto') && p.risk_profile !== 'Aggressivo') ? `
    <p class="help" style="margin-top:16px"><strong>Una cosa da dirle subito:</strong> ha chiesto
      le monete digitali, e le tengo nel suo profilo. Ma oscillano più di quanto il suo profilo
      ${esc(p.risk_profile.toLowerCase())} permette, quindi nella pratica non glielo segnalerò
      quasi mai. Non alzo il suo profilo per farcele entrare.</p>` : ''}
    <p class="help" style="margin-top:18px">${dec.selected.length
      ? `Con questo profilo, oggi avrei <strong>${dec.selected.length} ` +
        (dec.selected.length === 1 ? 'cosa' : 'cose') + '</strong> da farle vedere.'
      : 'Con questo profilo, oggi non avrei niente da segnalarle: le mostro comunque come ' +
        'lavoro e perché.'}</p>
    <div class="onb-nav">
      <button data-onb="restart">Rifaccio le domande</button>
      <div class="spacer"></div>
      <button class="go" data-onb="confirm">Va bene, mi faccia vedere</button>
    </div>
    <p class="small-note" style="margin-top:22px">${esc(D.onboarding.privacy_note)}</p>
  </div>`;
}

function afterQuestionnaire() {
  const conf = D.onboarding;
  const qs = conf.questions;
  const step = Math.min(state.onbStep, qs.length);
  const q = qs[step];

  $('#view').querySelectorAll('[data-opt]').forEach(el => {
    el.onclick = () => {
      const id = el.dataset.opt;
      if (q.kind === 'multi') {
        const cur = [].concat(state.onbAnswers[q.id] || []);
        const opt = q.options.find(o => o.id === id) || {};
        if (cur.includes(id)) {
          state.onbAnswers[q.id] = cur.filter(x => x !== id);
        } else if (opt.exclusive) {
          state.onbAnswers[q.id] = [id];            // "tutte" esclude il resto
        } else {
          const exclusives = q.options.filter(o => o.exclusive).map(o => o.id);
          state.onbAnswers[q.id] = cur.filter(x => !exclusives.includes(x)).concat(id);
        }
      } else {
        state.onbAnswers[q.id] = id;
        state.onbStep = step + 1;        // scelta singola: avanti subito
      }
      render();
    };
  });

  $('#view').querySelectorAll('[data-onb]').forEach(el => {
    el.onclick = () => {
      const act = el.dataset.onb;
      if (act === 'next') state.onbStep = step + 1;
      else if (act === 'back') state.onbStep = Math.max(0, step - 1);
      else if (act === 'restart') { state.onbAnswers = {}; state.onbStep = 0; }
      else if (act === 'skip') {
        state.onbSkipped = true;
        state.user = D.users[0].id;
      } else if (act === 'confirm') {
        const u = Onboarding.profileFromAnswers(state.onbAnswers);
        Onboarding.save(u);
        state.localUser = null;
        state.user = 'local';
        state.thread = [];
      }
      render();
    };
  });
}
function altezzaCard() {
  const carte = $('#view') && $('#view').querySelectorAll('.flip');
  if (!carte || !carte.length) return;
  Array.prototype.forEach.call(carte, (card) => {
    const facce = card.querySelectorAll('.faccia');
    // Le facce sono in posizione assoluta dentro la card: se la card ha già
    // un'altezza, misurarle lì dentro restituisce quell'altezza e non la loro.
    // Quindi si libera la card e si riporta ogni faccia nel flusso una per
    // una: così ognuna dichiara l'altezza che le serve davvero. Senza questo
    // il retro, che è più alto del fronte, risultava tagliato.
    card.style.height = 'auto';
    const misure = [];
    Array.prototype.forEach.call(facce, (f) => {
      const posPrima = f.style.position;
      f.style.position = 'relative';
      misure.push(f.offsetHeight || f.scrollHeight || 0);
      f.style.position = posPrima;
    });
    // Le due facce hanno altezze molto diverse: il retro porta tutti i dati,
    // il fronte il solo verdetto. Tenere la card alta quanto la piu' alta
    // lascerebbe mezzo schermo di vuoto sul fronte, quindi ognuna si porta la
    // propria misura e la card cresce mentre gira.
    card.dataset.hAvanti = String(misure[0] || 0);
    card.dataset.hDietro = String(misure[1] || misure[0] || 0);
    const girata = card.classList.contains('girata');
    const voluta = girata ? card.dataset.hDietro : card.dataset.hAvanti;
    if (Number(voluta) > 0) card.style.height = voluta + 'px';
  });
  if (!state.onResize && typeof window.addEventListener === 'function') {
    state.onResize = () => altezzaCard();
    window.addEventListener('resize', state.onResize);
  }
  // Aprire "i tre scenari" fa crescere il contenuto, ma l'altezza della card
  // era stata fissata prima: il testo finiva tagliato e non c'era modo di
  // leggerlo. Qui si rimisura ogni volta che un pieghevole si apre o si
  // chiude. Il difetto si vedeva solo cliccando, mai leggendo il codice.
  const pieghevoli = $('#view') && $('#view').querySelectorAll('details');
  if (pieghevoli) {
    Array.prototype.forEach.call(pieghevoli, (d) => {
      if (d.dataset.misurato === '1') return;
      d.dataset.misurato = '1';
      d.addEventListener('toggle', () => {
        // due misure: una subito e una a transizione finita, perche' il
        // browser rivela il contenuto in un fotogramma successivo
        altezzaCard();
        if (typeof setTimeout === 'function') setTimeout(altezzaCard, 60);
      });
    });
  }
}

/* Le schede si rivelano mentre si scorre. Senza IntersectionObserver la classe
   non viene messa e la pagina resta normale: leggibile prima che animata. */
function rivela() {
  const feed = $('#view .feed');
  if (!feed || typeof IntersectionObserver !== 'function') return;
  const fermo = typeof window.matchMedia === 'function' &&
                window.matchMedia('(prefers-reduced-motion: reduce)').matches;
  if (fermo) return;
  feed.classList.add('rivela');
  const figli = Array.prototype.slice.call(feed.children);
  const occhio = new IntersectionObserver((voci) => {
    voci.forEach((v) => {
      if (!v.isIntersecting) return;
      const k = figli.indexOf(v.target);
      v.target.style.transitionDelay = ((k % 4) * 60) + 'ms';
      v.target.classList.add('dentro');
      occhio.unobserve(v.target);
    });
  }, { rootMargin: '0px 0px -8% 0px', threshold: 0.04 });
  figli.forEach((f) => occhio.observe(f));

  // Rete di sicurezza. Se per qualunque motivo l'osservatore non scatta — un
  // browser vecchio che lo dichiara ma non lo esegue, una pagina ripresa dalla
  // cache dell'app, uno schermo lunghissimo — dopo un secondo e mezzo si mostra
  // tutto comunque. Un effetto grafico non puo' lasciare una pagina vuota.
  if (typeof setTimeout === 'function') {
    setTimeout(() => {
      figli.forEach((f) => f.classList.add('dentro'));
      if (occhio.disconnect) occhio.disconnect();
    }, 1500);
  }
}

function toast(text) {
  let el = $('#toast');
  if (!el) {
    el = document.createElement('div');
    el.id = 'toast';
    el.className = 'toast';
    document.body.appendChild(el);
  }
  el.textContent = text;
  el.classList.add('show');
  clearTimeout(window.__toastT);
  window.__toastT = setTimeout(() => el.classList.remove('show'), 4200);
}

function afterSimple() {
  const c = Charts.colors();
  // carte(), non solo la lista: gli osservati hanno anello e grafico come le
  // altre, e devono contare nello stesso ordine con cui sono stati disegnati.
  const opp = carte();

  opp.forEach((o, i) => {
    const a = asset(o.ticker);
    // anello del voto: colore dalla fascia, non dal gusto
    const anello = $('#ring-' + i);
    if (anello) {
      const col = o.score >= 85 ? c.good : o.score >= 70 ? c.s1 : c.muted;
      Charts.ring(anello, { score: o.score, color: col });
    }
    // Andamento: una serie sola, quindi un colore solo e nessuna legenda.
    // Niente verde/rosso secondo la direzione: il colore di stato e' gia'
    // impegnato dal semaforo del verdetto.
    const sp = $('#sch-' + i);
    if (sp && a && a.chart) {
      Charts.sparkArea(sp, { values: a.chart.close, dates: D.meta.chart_dates,
                             color: c.s1, height: 54 });
    }
  });

  altezzaCard();
  rivela();

  // ---- il foglio "come lavoro" ----
  const mostra = (apri) => {
    state.conf = apri;
    const cf = $('#conf'), v = $('#velo');
    if (cf) cf.classList.toggle('on', apri);
    if (v) v.classList.toggle('on', apri);
  };
  if ($('#confBtn')) $('#confBtn').onclick = () => mostra(true);
  if ($('#chiudiConf')) $('#chiudiConf').onclick = () => mostra(false);
  if ($('#velo')) $('#velo').onclick = () => mostra(false);
  if (state.conf) mostra(true);

  $('#themeBtn2').onclick = toggleTheme;

  // ---- intestazione che si assottiglia quando si scorre ----
  if ($('#topper') && !state.onScroll) {
    state.onScroll = () => {
      const t = $('#topper');
      if (t) t.classList.toggle('giu', window.scrollY > 12);
    };
    window.addEventListener('scroll', state.onScroll, { passive: true });
  }
  if (state.onScroll) state.onScroll();

  $('#view').querySelectorAll('[data-act]').forEach(el => {
    el.onclick = () => {
      const act = el.dataset.act;
      if (act === 'gira') {
        // Gira la card. Non si ridisegna il feed: ridisegnare farebbe
        // ripartire le animazioni d'entrata di tutte le card.
        const i = Number(el.dataset.i);
        const card = $('#opp-' + i);
        const pos = state.aperte.indexOf(i);
        if (pos > -1) state.aperte.splice(pos, 1); else state.aperte.push(i);
        if (card) {
          const girata = state.aperte.indexOf(i) > -1;
          card.classList.toggle('girata', girata);
          const h = girata ? card.dataset.hDietro : card.dataset.hAvanti;
          if (Number(h) > 0) card.style.height = h + 'px';
        }
      } else if (act === 'segui') {
        // La stellina non ridisegna tutto: cambia solo se stessa e l'elenco
        // dei seguiti, perche' un nuovo disegno farebbe ripartire le
        // animazioni di tutte le card e si perderebbe il punto di scorrimento.
        const i = Number(el.dataset.i);
        const o = carte()[i];
        if (!o) return;
        const ora = seguiAlterna(o);
        el.textContent = ora ? '★' : '☆';
        el.classList.toggle('on', ora);
        el.setAttribute('aria-pressed', String(ora));
        el.title = ora ? 'Smetti di seguirla' : 'Segui questo strumento';
        toast(ora ? `Seguo ${o.name}: le dico come va a ogni controllo.`
                  : `Non seguo più ${o.name}.`);
        render();
      } else if (act === 'pagina') {
        state.pagina = el.dataset.p === 'seguiti' ? 'seguiti' : 'opportunita';
        render();
        if (typeof window.scrollTo === 'function') window.scrollTo({ top: 0 });
      } else if (act === 'smetti') {
        const t = el.dataset.t;
        const d = seguitiLeggi();
        const nome = (d[t] && d[t].nome) || t;
        delete d[t];
        seguitiScrivi(d);
        toast(`Non seguo più ${nome}.`);
        render();
      }
    };
  });
}

function toggleTheme() {
  const next = document.documentElement.getAttribute('data-theme') === 'dark' ? 'light' : 'dark';
  document.documentElement.setAttribute('data-theme', next);
  localStorage.setItem('ams-theme', next);
  render();
}

/* --------------------------------------------------------------- render */
/* Una vista sola. La vista analista e' stata rimossa: non la usava nessuno, e
   mantenere due interfacce sugli stessi dati voleva dire controllarle tutte e
   due a ogni modifica. Il motore non e' cambiato: i punteggi, i segnali, il log
   del ciclo e le scelte di demo restano tutti, e si leggono da riga di comando
   (python cli.py scan, opportunities, triggers, pipeline, decisions). */
function render() {
  document.body.dataset.mode = 'simple';
  // Il questionario e' spento (D.meta.questionario false): resta raggiungibile
  // solo riaccendendo l'interruttore, perche' BR-01 e' ancora tutto nel motore.
  const serveQuestionario = D.meta.questionario === true && D.onboarding &&
    !state.onbSkipped && !state.forcedUser && !Onboarding.load();
  if (serveQuestionario) {
    $('#view').innerHTML = viewQuestionnaire();
    afterQuestionnaire();
    return;
  }
  $('#view').innerHTML = viewSimple();
  afterSimple();
}

function boot() {
  const q = new URLSearchParams(location.search);
  const saved = q.get('theme') || localStorage.getItem('ams-theme');
  if (saved) document.documentElement.setAttribute('data-theme', saved);

  // Risposte precompilate dall'indirizzo: resta perche' serve a far vedere il
  // questionario quando lo si riaccende, e ai controlli automatici.
  //   ?risposte=orizzonte:lungo,perdita:aspetto,settori:ai|tech&conferma=1
  if (q.get('risposte')) {
    for (const part of q.get('risposte').split(',')) {
      const [qid, vals] = part.split(':');
      if (!qid || !vals) continue;
      const list = vals.split('|');
      state.onbAnswers[qid] = list.length > 1 ? list : list[0];
    }
    const conf = D.onboarding;
    const multi = new Set((conf ? conf.questions : []).filter(x => x.kind === 'multi')
                          .map(x => x.id));
    for (const k of Object.keys(state.onbAnswers)) {
      if (multi.has(k) && !Array.isArray(state.onbAnswers[k])) {
        state.onbAnswers[k] = [state.onbAnswers[k]];
      }
    }
    state.onbStep = (D.onboarding ? D.onboarding.questions.length : 0);
    if (q.get('conferma')) {
      const u = Onboarding.profileFromAnswers(state.onbAnswers);
      Onboarding.save(u);
      state.user = 'local';
      state.localUser = null;
    }
  }
  render();
}

document.addEventListener('DOMContentLoaded', boot);

// Piccola finestra sullo stato della pagina: serve per capire cosa sta facendo
// dalla console del browser, e al controllo automatico tools/selftest_vista.js.
/* QUANDO SI RIAPRE L'APP.
   Un'applicazione installata non riparte da zero: il telefono la tiene in
   memoria, e riaprendola si rivede la pagina di prima - con i prezzi di
   prima. Il ciclo pubblica ogni due ore, ma senza questo pezzo l'unico modo
   di vedere i dati nuovi sarebbe chiudere e riaprire l'app a mano, cosa che
   nessuno fa. Al rientro, se la pagina e' ferma da un po', si ricarica: il
   guscio e' in cache, quindi costa una richiesta sola, condizionale.

   MA NON SOTTO LE DITA. Se c'e' una card girata o il foglio "come lavoro"
   alzato, chi guarda sta leggendo qualcosa e una ricarica gli farebbe
   perdere il punto. Lo stesso se e' sulla pagina dei prodotti seguiti. In
   quei casi non si fa niente e nessuno viene ingannato, perche' l'etichetta
   in alto dice sempre di quando sono i prezzi: si aggiorna al rientro dopo. */
// In un oggetto e non in una costante perche' il controllo automatico deve
// poter invecchiare la pagina senza spostare l'orologio del processo.
const tempo = { caricata: Date.now(), vecchiaDopoMs: 10 * 60 * 1000 };

function rientro() {
  if (document.visibilityState !== 'visible') return;
  if (Date.now() - tempo.caricata < tempo.vecchiaDopoMs) return;
  if (state.aperte && state.aperte.length) return;
  if (state.conf) return;
  if (state.pagina && state.pagina !== 'opportunita') return;
  location.reload();
}

document.addEventListener('visibilitychange', rientro);

window.AMS = { state: state, render: render, seguiAlterna: seguiAlterna,
               seguitiLeggi: seguitiLeggi, statoSeguito: statoSeguito,
               quandoTesto: quandoTesto, rientro: rientro, tempo: tempo,
               user: user, demoUser: demoUser, localUser: localUser };
})();
