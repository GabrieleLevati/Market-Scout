/* Prova la vista cliente eseguendola davvero.

   I difetti di questa parte non si vedono leggendo il codice: si vedono
   cliccando. Qui la pagina viene caricata in Node con un DOM finto — quanto
   basta a far girare app.js — e si percorrono le strade che un cliente percorre:
   apertura pulita, questionario, profilo salvato, "rifaccio il questionario",
   link di esempio, passaggio alla vista analista.

       node tools/selftest_vista.js

   Niente browser, niente dipendenze. */

'use strict';

const fs = require('fs');
const path = require('path');
const vm = require('vm');

const ROOT = path.dirname(__dirname);
const WEB = path.join(ROOT, 'web');

let ok = true;
function check(label, cond, detail) {
  console.log(`  [${cond ? 'ok ' : 'KO '}] ${label}${detail ? ' — ' + detail : ''}`);
  if (!cond) ok = false;
}

/* ------------------------------------------------------------ DOM finto */
function elemento(tag) {
  const el = {
    tagName: (tag || 'div').toUpperCase(),
    _html: '',
    children: [],
    style: {},
    dataset: {},
    onclick: null, onchange: null, oninput: null, onkeydown: null,
    classList: {
      _set: new Set(),
      add(c) { this._set.add(c); }, remove(c) { this._set.delete(c); },
      toggle(c, on) { on ? this._set.add(c) : this._set.delete(c); },
      contains(c) { return this._set.has(c); },
    },
    appendChild(c) { this.children.push(c); return c; },
    insertBefore(c) { this.children.push(c); return c; },
    setAttribute() {}, getAttribute() { return null; },
    addEventListener() {}, removeEventListener() {},
    scrollIntoView() {}, focus() {}, click() { if (this.onclick) this.onclick(); },
    closest() { return elemento('div'); },
    querySelector() { return elemento('div'); },
    querySelectorAll() { return []; },
    getBoundingClientRect() { return { left: 0, top: 0, width: 760, height: 260, right: 760 }; },
    get innerHTML() { return this._html; },
    set innerHTML(v) { this._html = String(v); },
    get textContent() { return this._html; },
    set textContent(v) { this._html = String(v); },
    get clientWidth() { return 760; },
    get offsetWidth() { return 120; },
  };
  return el;
}

/* Trova i bottoni dentro l'HTML generato: non serve un vero parser, basta
   leggere gli attributi data-* e restituire oggetti su cui chiamare onclick. */
function bottoni(html, attributo) {
  const re = new RegExp(`data-${attributo}="([^"]*)"`, 'g');
  const out = [];
  let m;
  while ((m = re.exec(html)) !== null) out.push(m[1]);
  return out;
}

function creaFinestra(search) {
  const archivio = new Map();
  const doc = {
    documentElement: {
      _theme: 'light',
      setAttribute(k, v) { if (k === 'data-theme') this._theme = v; },
      getAttribute(k) { return k === 'data-theme' ? this._theme : null; },
      clientWidth: 760, scrollWidth: 760,
    },
    body: Object.assign(elemento('body'), { dataset: {} }),
    _nodi: new Map(),
    // Si parte visibile, come un'app appena aperta. Il controllo sul rientro
    // la mette in background e la riporta avanti.
    visibilityState: 'visible',
    createElement: (t) => elemento(t),
    createElementNS: (ns, t) => Object.assign(elemento(t), { _ns: ns }),
    addEventListener() {},
    querySelector(sel) {
      if (!this._nodi.has(sel)) this._nodi.set(sel, elemento('div'));
      return this._nodi.get(sel);
    },
    querySelectorAll() { return []; },
  };
  const win = {
    document: doc,
    // `_ricariche` conta le ricariche chieste: e' l'unico modo di verificare
    // che al rientro nell'app i dati nuovi vengano davvero richiesti.
    location: { search: search || '', hash: '', protocol: 'file:', pathname: '/index.html',
                _ricariche: 0, reload() { this._ricariche += 1; } },
    history: { replaceState() {} },
    localStorage: {
      getItem: (k) => (archivio.has(k) ? archivio.get(k) : null),
      setItem: (k, v) => archivio.set(k, String(v)),
      removeItem: (k) => archivio.delete(k),
    },
    addEventListener() {},
    scrollTo() {},
    setTimeout: (fn) => { if (typeof fn === 'function') fn(); return 0; },
    clearTimeout() {},
    getComputedStyle: () => ({ getPropertyValue: () => '#2a78d6' }),
    URL: { createObjectURL: () => 'blob:finto' },
    Blob: function () {},
    navigator: { serviceWorker: undefined },
    URLSearchParams: URLSearchParams,
    console: console,
    JSON: JSON, Math: Math, Date: Date, Object: Object, Array: Array,
    String: String, Number: Number, Boolean: Boolean, Set: Set, Map: Map,
    RegExp: RegExp, Error: Error, isNaN: isNaN, parseInt: parseInt, parseFloat: parseFloat,
  };
  win.window = win;
  win.globalThis = win;
  return win;
}

/* app.js registra boot() su document.addEventListener: lo intercettiamo.

   `soglia` abbassa la soglia di punteggio prima del primo disegno: serve perché
   il data.js sul disco può essere sintetico o reale, e sui dati reali spesso
   nessuno strumento supera 85. Senza questo i controlli direbbero "fallito"
   quando invece è il mercato a non offrire niente. */
function avvia(search, soglia, prepara) {
  const win = creaFinestra(search);
  let boot = null;
  win.document.addEventListener = (ev, fn) => { if (ev === 'DOMContentLoaded') boot = fn; };
  const ctx = vm.createContext(win);
  for (const f of ['data.js', 'charts.js', 'onboarding.js', 'app.js']) {
    vm.runInContext(fs.readFileSync(path.join(WEB, f), 'utf8'), ctx, { filename: f });
    if (f === 'data.js') {
      if (soglia) win.DEMO_DATA.meta.score_threshold = soglia;
      // `prepara` fissa i dati del caso di prova: serve perche' il data.js sul
      // disco dipende dal mercato del giorno, e un controllo che passa o
      // fallisce secondo l'umore della borsa non controlla niente.
      if (typeof prepara === 'function') prepara(win.DEMO_DATA);
    }
  }
  // i file dichiarano `const Onboarding`/`const Charts`: nello stesso contesto
  // app.js li vede, dall'esterno no. Si espongono per poterli controllare.
  vm.runInContext('globalThis.Onboarding = Onboarding; globalThis.Charts = Charts;', ctx);
  if (!boot) throw new Error('app.js non ha registrato DOMContentLoaded');
  boot();
  return win;
}

const vista = (win) => win.document.querySelector('#view').innerHTML;

/* Un'opportunita' fissata, con tutti i campi che la card mostra. Serve perche'
   il data.js sul disco dipende dal mercato del giorno: un controllo che passa
   o fallisce secondo l'umore della borsa non controlla niente. La regola che
   decide quali strumenti diventano opportunita' ha il suo controllo a parte,
   in tools/selftest_opportunita.py. */
function fissaOpportunita(d) {
  const a = d.assets[0];
  d.opportunita = {
    soglia: 85, scartati: [],
    lista: [{
      ticker: a.ticker, name: a.name, score: 88,
      classification: 'Opportunita forte', final_rating: 'Strong Buy',
      risk_label: 'Moderato', risk_score: 40,
      sector: 'Tecnologia', asset_class: 'Azioni', market: 'USA',
      size: 'Large cap', currency: 'USD',
      price: 212.8, target: 268.92, stop_loss: 200.88,
      entry_low: 209.94, entry_high: 213.75,
      upside: 0.2637, downside: -0.056, risk_reward: 4.71,
      fair_value: 268.92, valuation_method: 'utili x multiplo giusto',
      valuation_source: 'modello quantitativo', valuation_confidence: 94,
      scores: { fundamental: 93, technical: 90, valuation: 89,
                sentiment: null, risk: 40 },
      reasons: ['Sottovalutazione', 'Insider buying'],
      che_cos_e: 'Fa le schede grafiche e i chip su cui gira quasi tutta '
                 + 'l intelligenza artificiale. E un azione, cioe una piccola '
                 + 'parte di un azienda, quotata negli Stati Uniti.',
      identita: { isin: 'US67066G1040', figi: 'BBG000BBJQV0', tipo: 'Common Stock',
                  isin_fonte: 'isin.json' },
      visione: {
        azione: 'La comprerei.',
        attesa: 'Oggi costa fra 209,94 e 213,75, ed e quella la fascia in cui entrerei.',
        orizzonte: '15 mesi circa',
        rumore: 'Nelle prossime due settimane un movimento fino al 5% e normale: '
                + 'non vuol dire niente, e io non ci reagirei.',
        cambio_idea: 'Cambio idea se scende a 200,88.',
        al_tetto: false, limite: '',
        scenari: ['Se va bene (43%): il prezzo arriva a 299,27.',
                  'Lo scenario piu probabile (37%): arriva a 268,92.'],
      },
    }],
  };
}

function main() {
  console.log('1. Apertura: le opportunita, subito, senza domande');
  let win = avvia('');
  let html = vista(win);
  check('nessun questionario', html.indexOf('Domanda 1 di') === -1);
  check('nessun selettore di cliente', html.indexOf('<select') === -1);
  check('il feed esiste', html.indexOf('class="feed"') > -1);
  check('niente spiegazioni di soglia in pagina',
        html.indexOf('nessun filtro, nessun profilo') === -1);

  console.log('\n2. Quello che e stato tolto non deve tornare');
  check('niente grafico del patrimonio', html.indexOf('id="onda"') === -1);
  check('niente conversazione con l agente', html.indexOf('id="fab"') === -1 &&
        html.indexOf('id="askInput"') === -1);
  check('niente portafoglio inventato', html.indexOf('investimenti valgono oggi') === -1);
  check('niente profilo di esempio', html.indexOf('profilo di esempio') === -1);
  // Il glossario non è stato cancellato: è passato dietro la "i". Quindi il
  // controllo giusto non è "non esiste", è "non sta in pagina": niente
  // <details> prima del foglio, tutti dentro.
  const primaDelFoglio = html.slice(0, Math.max(0, html.indexOf('id="conf"')));
  check('niente glossario in pagina', primaDelFoglio.indexOf('<details>') === -1);
  check('il glossario è dietro la "i"', html.indexOf('<details>') > -1);

  console.log('\n3. La card con tutti i dati che sono stati chiesti');
  // Fissato un elenco noto: cosi i controlli valgono anche nei giorni in cui
  // il mercato non offre niente sopra soglia. La regola del motore ha il suo
  // controllo a parte, in tools/selftest_opportunita.py.
  win = avvia('', null, fissaOpportunita);
  html = vista(win);
  check('la card c e', html.indexOf('class="flip') > -1);
  check('due facce', (html.match(/class="faccia/g) || []).length >= 2);
  check('anello del voto', html.indexOf('id="ring-0"') > -1);
  check('andamento', html.indexOf('id="sch-0"') > -1);
  // i dati chiesti esplicitamente dall utente
  const dati = [['ISIN', 'US67066G1040'], ['FIGI', 'BBG000BBJQV0'],
                ['settore', 'Tecnologia'], ['tipologia', 'Azioni'],
                ['target price', '268,92'], ['uscita', '200,88'],
                ['valuta', 'USD'], ['mercato', 'USA'],
                ['rischio/rendimento', '4,71']];
  dati.forEach(([nome, valore]) => {
    check('sul retro c e ' + nome, html.indexOf(valore) > -1, valore);
  });
  check('i cinque voti per componente', (html.match(/class="cq"/g) || []).length === 5,
        String((html.match(/class="cq"/g) || []).length));
  check('un voto mancante dice n.d., non zero', html.indexOf('n.d.') > -1);

  console.log('\n3b. La visione: che faccio, dove va, in quanto tempo');
  win = avvia('', null, fissaOpportunita);
  html = vista(win);
  check('c e il blocco della visione', html.indexOf('class="visione"') > -1);
  check('dice che cosa farebbe', html.indexOf('La comprerei') > -1);
  check('l orizzonte e un dato, non un discorso',
        html.indexOf('class="vo"') > -1 &&
        html.indexOf('orizzonte su cui ragiono') === -1);
  check('dice che movimento e solo rumore', html.indexOf('non ci reagirei') > -1);
  check('dice cosa gli farebbe cambiare idea', html.indexOf('Cambio idea se scende') > -1);
  check('NON promette tempi brevi inventati',
        html.indexOf('in 2 settimane') === -1 && html.indexOf('due settimane +') === -1);
  check('dice che cosa e lo strumento', html.indexOf('class="fr-cos"') > -1);
  check('niente testo tagliato a meta', html.indexOf('line-clamp') === -1);
  check('c e la stellina per seguirlo', html.indexOf('data-act="segui"') > -1);
  check('ci sono i tre scenari, richiudibili', html.indexOf('I tre scenari') > -1);

  console.log('\n3c. Una stima al tetto del modello va dichiarata');
  // E' il caso in cui il numero piu' grosso della lista e' il meno affidabile:
  // se la card non lo dice, chi legge crede sia l'occasione migliore.
  win = avvia('', null, (d) => {
    const a = d.assets[0];
    d.opportunita = { soglia: 70, scartati: [], lista: [{
      ticker: a.ticker, name: a.name, score: 75, classification: 'Da monitorare',
      risk_label: 'Alto', risk_score: 60, sector: 'AI', asset_class: 'Azioni',
      market: 'USA', currency: 'USD', price: 100, target: 160, stop_loss: 90,
      entry_low: 99, entry_high: 101, upside: 0.60, downside: -0.1,
      risk_reward: 6, valuation_confidence: 58, scores: {}, reasons: [],
      valuation_method: 'confronto con i simili di settore',
      visione: { azione: 'La terrei d occhio.', attesa: 'x', tempo: 'y',
                 rumore: 'z', cambio_idea: 'w', al_tetto: true,
                 limite: 'Attenzione a questo +60%: e il tetto che mi sono dato.' },
    }] };
  });
  html = vista(win);
  check('il numero al tetto e segnalato come poco preciso',
        html.indexOf('stima al tetto del modello') > -1);
  check('la riga della visione lo spiega', html.indexOf('class="vl"') > -1);
  check('la confidenza bassa e detta bassa', html.indexOf('58/100 — bassa') > -1);

  console.log('\n4. Girare la card');
  let errore = null;
  try {
    win.AMS.state.aperte = [0];
    win.AMS.render();
  } catch (e) { errore = e; }
  check('girare non da errore', !errore, errore && errore.message);
  // la classe si cerca nell'elenco, non come stringa attaccata: fra "flip" e
  // "girata" ora c'e' anche la tinta del tipo, e un controllo che pretende
  // le due parole adiacenti falliva per una classe in piu'.
  check('lo stato resta dopo un nuovo disegno',
        /class="flip [^"]*girata/.test(vista(win)));

  console.log('\n3d. Le novita: quello che prima non c era, e quello che e uscito');
  win = avvia('', null, (d) => {
    fissaOpportunita(d);
    const t = d.opportunita.lista[0].ticker;
    d.novita = { nuove: [t], uscite: ['VECCHIA'], salite: [], scese: [],
                 primo_giro: false };
  });
  html = vista(win);
  check('la card nuova porta il distintivo', html.indexOf('class="nuova"') > -1);
  check('la pagina dice quante sono nuove', html.indexOf('nuova rispetto') > -1 ||
        html.indexOf('nuove rispetto') > -1);
  check('e dice chi e uscito, con il nome', html.indexOf('VECCHIA') > -1);
  check('e perche e uscito', html.indexOf('non la propongo') > -1 ||
        html.indexOf('non le propongo') > -1);

  // Al primo giro tutto sarebbe "nuovo": un distintivo su ogni card, cioe'
  // nessuna informazione. Quindi al primo giro non si segnala niente.
  win = avvia('', null, (d) => {
    fissaOpportunita(d);
    d.novita = { nuove: [d.opportunita.lista[0].ticker], uscite: [], salite: [],
                 scese: [], primo_giro: true };
  });
  check('al primo giro non si segnala nulla come nuovo',
        vista(win).indexOf('class="nuova"') === -1);

  // La richiesta: in pagina ci devono essere TUTTE e SOLE quelle sopra soglia.
  win = avvia('', null, (d) => {
    fissaOpportunita(d);
    const base = d.opportunita.lista[0];
    d.opportunita.soglia = 70;
    d.opportunita.lista = [
      Object.assign({}, base, { ticker: 'ALTA', score: 95 }),
      Object.assign({}, base, { ticker: 'GIUSTA', score: 71 }),
    ];
  });
  html = vista(win);
  check('ci sono tutte quelle sopra soglia',
        html.indexOf('ALTA') > -1 && html.indexOf('GIUSTA') > -1);
  check('il conto in testa corrisponde', html.indexOf('2 opportunità') > -1);

  console.log('\n4b. Seguire un prodotto con la stellina');
  win = avvia('', null, fissaOpportunita);
  const primo = win.DEMO_DATA.opportunita.lista[0];
  errore = null;
  try { win.AMS.seguiAlterna(primo); win.AMS.render(); } catch (e) { errore = e; }
  check('seguire non da errore', !errore, errore && errore.message);
  const salvato = JSON.parse(win.localStorage.getItem('ams-seguiti') || '{}')[primo.ticker];
  check('resta salvato nel browser', !!salvato);
  check('salva il prezzo di quando lo ha seguito', !!salvato && !!salvato.prezzo,
        salvato && String(salvato.prezzo));
  check('salva la data', !!salvato && !!salvato.dal, salvato && String(salvato.dal));

  console.log('\n4c. I preferiti stanno in una pagina loro');
  /* LA VERIFICA CHE MANCAVA. I controlli dicevano che la pagina dei seguiti
     esisteva e si apriva, e passavano: intanto la stessa vista veniva ANCHE
     accodata in fondo alle opportunita, che si ritrovava due intestazioni e
     la lista dei seguiti sotto le card. Verificare che una cosa ci sia non
     verifica che non sia anche dove non deve stare. */
  html = vista(win);
  check('nella pagina delle opportunita non c e la coda dei seguiti',
        html.indexOf('che segui') === -1);
  check('e non ci finisce la vista dei seguiti per intero',
        html.indexOf('Segue ') === -1 && html.indexOf('Non sta seguendo') === -1);
  check('una sola intestazione nella pagina',
        (html.match(/class="hero"/g) || []).length === 1,
        String((html.match(/class="hero"/g) || []).length));
  // Non basta che la pagina esista: deve esserci un modo di arrivarci
  // cliccando. Il test prima cambiava pagina da codice, e intanto nella
  // barra in alto il bottone non c'era: una funzione irraggiungibile.
  const barra = html.slice(0, html.indexOf('class="feed"'));
  check('c e una navigazione per arrivare ai preferiti',
        barra.indexOf('class="navpag"') > -1 && barra.indexOf('data-p="seguiti"') > -1);
  check('e anche alla pagina di quelli da approfondire',
        barra.indexOf('data-p="osservati"') > -1);
  check('la navigazione dice quanti ne segue', barra.indexOf('<b>1</b>') > -1);
  errore = null;
  try { win.AMS.state.pagina = 'seguiti'; win.AMS.render(); } catch (e) { errore = e; }
  check('la pagina dei preferiti si apre', !errore, errore && errore.message);
  html = vista(win);
  check('dice quanti ne segue', html.indexOf('Segue ') > -1);
  check('per ognuno dice come va', html.indexOf('da quando la segue') > -1);
  check('dice quando lo ha seguito', html.indexOf("Quando l'ha seguita") > -1);
  check('e che cosa conviene fare', html.indexOf('class="sr-az"') > -1);
  check('la barra cambia titolo', html.indexOf('Che segue') > -1);
  check('si torna alle opportunita', html.indexOf('data-p="opportunita"') > -1);
  win.AMS.state.pagina = 'opportunita';
  win.AMS.render();

  console.log('\n5. Senza ISIN si dice che manca, non si indovina');
  win = avvia('', null, (d) => {
    const a = d.assets[0];
    d.opportunita = { soglia: 85, scartati: [], lista: [{
      ticker: a.ticker, name: a.name, score: 88, classification: 'Opportunita forte',
      risk_label: 'Moderato', risk_score: 40, sector: 'Tecnologia',
      asset_class: 'Azioni', market: 'USA', currency: 'USD', price: 100,
      target: 120, stop_loss: 90, entry_low: 99, entry_high: 101,
      upside: 0.2, downside: -0.1, risk_reward: 2, scores: {}, reasons: [],
    }] };
  });
  html = vista(win);
  // Prima la riga diceva "non disponibile": occupava spazio per dire niente.
  // Ora se l'ISIN manca la riga non esiste. Quello che non deve mai comparire
  // e' un ISIN indovinato.
  check('la riga ISIN non compare affatto', html.indexOf('>ISIN<') === -1);
  check('non inventa un codice', html.indexOf('US0000') === -1);
  check('gli altri dati ci sono comunque', html.indexOf('Target price') > -1);

  console.log('\n6. Giornata senza opportunita: si spiega, non sembra un guasto');
  win = avvia('', null, (d) => {
    d.opportunita = { soglia: 85, lista: [], scartati: [
      { ticker: 'XXX', name: 'Qualcosa', score: 82,
        motivo: 'Ha preso 82 punti su 100: per segnalarlo dovrebbe superare 85.' }] };
  });
  html = vista(win);
  check('dice che non e un guasto', html.indexOf('Non è un guasto') > -1);
  check('mostra i piu vicini', html.indexOf('i più vicini') > -1);
  check('con il loro motivo', html.indexOf('dovrebbe superare 85') > -1);
  check('dice che il controllo si ripete', html.indexOf('ogni due ore') > -1);

  /* Gli osservati HANNO superato la soglia: quello che non hanno e un prezzo
     obiettivo. Quindi in una giornata senza opportunita ma con osservati, la
     frase "nessuno ha superato 70" sarebbe falsa e contraddetta da una card
     con 75 punti poco sopra. L ho visto in una schermata, non nel codice. */
  win = avvia('', null, (d) => {
    d.opportunita = {
      soglia: 70, lista: [], scartati: [],
      osservati: [{ ticker: 'EXS1.DE', name: 'iShares Core DAX', score: 94,
                    classification: 'Opportunità eccezionale', asset_class: 'ETF',
                    sector: 'Indice', market: 'Europa', currency: 'EUR',
                    price: 214.1, risk_label: 'Moderato', risk_score: 40,
                    senza_valore: true, target: null, upside: null,
                    scores: { fundamental: null, technical: 70, valuation: null,
                              sentiment: null, risk: 40 },
                    motivo: 'Di questo strumento non ho i conti per stimare un valore.' }],
    };
  });
  html = vista(win);
  /* Gli osservati stanno su una pagina loro, non mescolati qui: nella pagina
     delle opportunita ci deve essere il RIMANDO, altrimenti chi sta qui non
     sa che esiste l altra. */
  check('c e il rimando alla pagina di quelli da approfondire',
        html.indexOf('data-p="osservati"') > -1);
  check('e il rimando dice quanti sono e perche sono altrove',
        html.replace(/\s+/g, ' ').indexOf('non posso stimarne il valore') > -1);
  check('le card degli osservati NON stanno fra le opportunita',
        html.indexOf('EXS1.DE') === -1);

  win.AMS.state.pagina = 'osservati';
  win.AMS.render();
  html = vista(win);
  /* Spazi normalizzati prima di confrontare: nel sorgente la frase va a capo
     e l HTML collassa gli spazi in resa ma non nella stringa. Cercare il testo
     cosi come lo legge l utente evita controlli che falliscono per una
     riformattazione invece che per un difetto. */
  const piatto = html.replace(/\s+/g, ' ');
  check('la pagina dedicata mostra lo strumento', html.indexOf('EXS1.DE') > -1);
  /* L etichetta non deve chiamarli opportunita. Il motore classifica per
     fascia di punteggio e per un 94 scrive "Opportunita eccezionale": giusto
     fra le opportunita, contraddittorio su una pagina che dichiara "non sono
     proposte d acquisto". Visto in una schermata, non nel codice. */
  check('non li chiama opportunita, perche la pagina dice il contrario',
        piatto.indexOf('Opportunità eccezionale') === -1
        && piatto.indexOf('Opportunità forte') === -1, piatto.slice(0, 0));
  check('ma dice che il punteggio e alto, perche lo e',
        piatto.indexOf('Punteggio alto') > -1 || piatto.indexOf('Da monitorare') > -1);
  check('e spiega perche non ha un prezzo obiettivo',
        piatto.indexOf('non hanno bilanci') > -1);
  check('la card dell osservato non promette un prezzo obiettivo',
        piatto.indexOf('non stimo quanto vale') > -1);
  check('e non mostra la riga del target vuota',
        html.indexOf('Target price') === -1 || html.indexOf('>-<') === -1);
  win.AMS.state.pagina = 'opportunita';
  win.AMS.render();
  html = vista(win);
  check('NON dice che nessuno ha superato la soglia',
        html.indexOf('nessuno dei') === -1 || html.indexOf('di cui riesco a stimare') > -1,
        'sarebbe contraddetto dalla card con 94 punti');
  check('dice invece che manca il prezzo, non il punteggio',
        html.indexOf('senza bilanci non posso dirle') > -1);

  console.log('\n7. Uguali per tutti: nessun parametro cambia l elenco');
  const conUtente = vista(avvia('?user=u3'));
  const senza = vista(avvia(''));
  const carte = (t) => (t.match(/class="flip/g) || []).length;
  check('?user= non cambia quante card si vedono',
        carte(conUtente) === carte(senza), carte(conUtente) + ' contro ' + carte(senza));

  console.log('\n8. La vista analista non esiste piu');
  html = vista(avvia('?mode=expert'));
  check('?mode=expert non apre nulla di tecnico', html.indexOf('Opportunity Center') === -1);
  check('si vede comunque la pagina delle opportunita', html.indexOf('class="feed"') > -1);
  check('nessun selettore di cliente', html.indexOf('<select') === -1);

  console.log('\n9. L etichetta di freschezza dice di quando sono i prezzi');
  /* PERCHE'. I prezzi ora si rinnovano ogni due ore, quindi i numeri in pagina
     si muovono durante la giornata. Senza un orario accanto, chi guarda non ha
     modo di sapere se sta leggendo il prezzo di adesso o quello di stanotte.
     E l orario deve essere quello della BORSA, non quello del ciclo: il ciclo
     gira anche alle 3 del mattino, e scrivere "aggiornato alle 3:05" sopra dei
     prezzi fermi alla chiusura di New York e peggio che non scrivere niente,
     perche invita a cercare un cambiamento che non ci puo essere. */
  const quando = (prepara) => avvia('', null, prepara).AMS.quandoTesto();

  const adesso = new Date();
  const isoDiOggi = (ore, minuti) => {
    const t = new Date(adesso.getFullYear(), adesso.getMonth(), adesso.getDate(),
                       ore, minuti, 0);
    return t.toISOString().replace(/\.\d+Z$/, '+00:00');
  };

  let testo = quando((d) => {
    d.meta.data_mode = 'real';
    d.data = { prezzi_al: isoDiOggi(15, 47), seduta_in_corso: true };
  });
  check('a seduta aperta dice l ora dei prezzi', /prezzi delle 15:47/.test(testo), testo);

  testo = quando((d) => {
    d.meta.data_mode = 'real';
    d.data = { prezzi_al: isoDiOggi(22, 0), seduta_in_corso: false };
  });
  check('a seduta chiusa lo dice, con l ora della chiusura',
        /chiusura delle 22:00/.test(testo), testo);

  testo = quando((d) => {
    d.meta.data_mode = 'real';
    d.data = { prezzi_al: '2026-10-30T20:00:00+00:00', seduta_in_corso: false };
  });
  check('se i prezzi sono di un altro giorno lo dichiara, con la data',
        /chiusura del 30\/10\/26/.test(testo), testo);
  check('e non spaccia per odierno un prezzo vecchio',
        testo.indexOf('prezzi delle') === -1, testo);

  testo = quando((d) => {
    d.meta.data_mode = 'real';
    d.data = { prezzi_al: null };
  });
  check('senza l ora ripiega sulla data del controllo',
        /controllato il/.test(testo), testo);

  testo = quando((d) => {
    d.meta.data_mode = 'real';
    d.data = { prezzi_al: 'non una data' };
  });
  check('un orario illeggibile non stampa "NaN" in faccia al lettore',
        testo.indexOf('NaN') === -1 && /controllato il/.test(testo), testo);

  testo = quando((d) => { d.meta.data_mode = 'synthetic'; });
  check('in dimostrazione resta dichiarato che i dati sono simulati',
        /simulati/.test(testo), testo);

  html = vista(avvia('', null, (d) => {
    d.meta.data_mode = 'real';
    d.data = { prezzi_al: isoDiOggi(15, 47), seduta_in_corso: true };
  }));
  check('e l etichetta finisce davvero in pagina', html.indexOf('prezzi delle 15:47') > -1);

  console.log('\n10. Riaprendo l app si rivedono dati nuovi, non quelli di prima');
  /* PERCHE'. Un applicazione installata non riparte da zero: il telefono la
     tiene in memoria. Senza niente che reagisca al rientro, chi riapre l app
     alle 19 rivede la pagina caricata alle 15, con i prezzi delle 15 - e il
     ciclo nel frattempo ha pubblicato due volte. A freddo funzionava, ma
     riaprire dal background e il caso normale, non l eccezione. */
  /* La pagina si invecchia spostando INDIETRO il momento del caricamento, non
     avanti l orologio: Date e lo stesso oggetto del processo che esegue i
     controlli, e spostarlo avrebbe sporcato tutti i controlli successivi. */
  const ferma = (win, minuti) => { win.AMS.tempo.caricata -= minuti * 60 * 1000; };

  win = avvia('', null, fissaOpportunita);
  check('appena caricata, nessuna ricarica', win.location._ricariche === 0,
        String(win.location._ricariche));
  win.AMS.rientro();
  check('e nemmeno rientrando subito (sarebbe un giro infinito)',
        win.location._ricariche === 0, String(win.location._ricariche));

  win = avvia('', null, fissaOpportunita);
  ferma(win, 30);
  win.AMS.rientro();
  check('dopo mezz ora di pausa, rientrando ricarica',
        win.location._ricariche === 1, String(win.location._ricariche));

  win = avvia('', null, fissaOpportunita);
  ferma(win, 30);
  win.AMS.state.aperte = [0];
  win.AMS.rientro();
  check('ma non con una card aperta: si sta leggendo',
        win.location._ricariche === 0, String(win.location._ricariche));

  win = avvia('', null, fissaOpportunita);
  ferma(win, 30);
  win.AMS.state.conf = true;
  win.AMS.rientro();
  check('ne col foglio "come lavoro" alzato',
        win.location._ricariche === 0, String(win.location._ricariche));

  win = avvia('', null, fissaOpportunita);
  ferma(win, 30);
  win.AMS.state.pagina = 'seguiti';
  win.AMS.rientro();
  check('ne sulla pagina dei prodotti seguiti',
        win.location._ricariche === 0, String(win.location._ricariche));

  win = avvia('', null, fissaOpportunita);
  ferma(win, 30);
  win.document.visibilityState = 'hidden';
  win.AMS.rientro();
  check('e mai mentre l app e in background',
        win.location._ricariche === 0, String(win.location._ricariche));

  console.log('\n10b. Il colore del tipo e la banda dei numeri');
  /* Il colore del tipo e un CODICE, non una decorazione: il posto di ogni
     tipo nella scala e fisso e non dipende da quali altri tipi ci sono quel
     giorno. Un colore che cambia significato da un ciclo all altro sarebbe
     peggio di nessun colore. E un tipo sconosciuto prende il neutro, non una
     tinta inventata. */
  win = avvia('', null, (d) => {
    fissaOpportunita(d);
    const base = d.opportunita.lista[0];
    const copia = (tk, classe, voto) => Object.assign({}, base,
      { ticker: tk, asset_class: classe, score: voto });
    d.opportunita.lista = [copia('AAA', 'Azioni', 90), copia('BBB', 'ETF', 72),
                           copia('CCC', 'Sconosciuto', 71)];
    d.opportunita.osservati = [];
  });
  html = vista(win);
  check('le azioni prendono il primo posto della scala',
        /class="flip tp1/.test(html));
  check('gli ETF il secondo, sempre lo stesso', /class="flip tp2/.test(html));
  check('un tipo sconosciuto prende il neutro, non una tinta inventata',
        /class="flip tp0/.test(html));
  check('il colore non e mai l unica informazione: il tipo e scritto',
        html.indexOf('ETF') > -1 && html.indexOf('Azioni') > -1);

  check('c e la banda dei numeri in cima', html.indexOf('class="banda"') > -1);
  const numeri = (html.match(/<div class="n">([^<]*)</g) || [])
    .map(s => s.replace(/.*>/, '').replace(/<$/, ''));
  check('dice quante opportunita', numeri[0] === '3', String(numeri[0]));
  check('quanti da approfondire', numeri[1] === '0', String(numeri[1]));
  check('e il voto piu alto di oggi', numeri[2] === '90', String(numeri[2]));
  check('la cella a zero si distingue', html.indexOf('class="bt vuota"') > -1);
  check('l alone sul voto alto compare solo sopra 85',
        (html.match(/class="ring alto"/g) || []).length === 1,
        String((html.match(/class="ring alto"/g) || []).length));

  console.log('\n11. Il menu dei tipi: scegliere cosa vedere, non cosa esiste');
  /* E un filtro di VISUALIZZAZIONE: la lista che il motore produce resta
     identica per tutti e questo cambia solo cosa si disegna. La distinzione
     non e formale - un elenco calcolato sul profilo di chi guarda sarebbe
     una raccomandazione personalizzata, che e un altra cosa. */
  const treTipi = (d) => {
    fissaOpportunita(d);
    const base = d.opportunita.lista[0];
    const copia = (tk, nome, classe, voto) => Object.assign({}, base,
      { ticker: tk, name: nome, asset_class: classe, score: voto });
    d.opportunita.lista = [
      copia('AAA', 'Una azione', 'Azioni', 90),
      copia('BBB', 'Un paniere', 'ETF', 88),
      copia('CCC', 'Un altra azione', 'Azioni', 80),
    ];
    d.opportunita.osservati = [];
  };

  win = avvia('', null, treTipi);
  win.AMS.tipiScrivi([]);
  win.AMS.render();
  html = vista(win);
  check('i pulsanti dei tipi compaiono', html.indexOf('class="chipsrow"') > -1);
  check('c e il pulsante Azioni col suo numero',
        html.indexOf('data-t="Azioni"') > -1 && html.indexOf('>Azioni<b>2</b>') > -1);
  check('e quello ETF', html.indexOf('data-t="ETF"') > -1);
  check('con niente scelto, "Tutti" risulta attivo',
        html.indexOf('class="chip on" data-act="tipo" data-t=""') > -1);
  check('si vedono tutte e tre le card',
        (html.match(/id="opp-/g) || []).length === 3,
        String((html.match(/id="opp-/g) || []).length));

  win.AMS.tipiScrivi(['ETF']);
  win.AMS.render();
  html = vista(win);
  check('scelto ETF, resta una card sola',
        (html.match(/id="opp-/g) || []).length === 1,
        String((html.match(/id="opp-/g) || []).length));
  check('ed e quella giusta', html.indexOf('BBB') > -1 && html.indexOf('AAA') === -1);
  check('il titolo continua a dire il totale vero, non il filtrato',
        html.indexOf('3 opportunità') > -1);

  /* IL CONTROLLO CHE CONTA. L indice di una card e usato in tre posti
     lontani - il disegno, l anello col voto, la stellina - e la stellina
     prende lo strumento per posizione. Con un filtro attivo, se quei tre
     contassero sull elenco completo mentre a schermo c e un sottoinsieme,
     la stella della prima card seguirebbe lo strumento sbagliato: il
     danno sarebbe silenzioso e nei dati di chi guarda. */
  const visibili = win.AMS.carteVisibili();
  check('le card a schermo sono solo quelle filtrate',
        visibili.length === 1 && visibili[0].ticker === 'BBB',
        visibili.map(o => o.ticker).join(','));
  check('mentre la ricerca per ticker trova anche i nascosti',
        !!win.AMS.carteTutte().find(o => o.ticker === 'AAA'));
  check('la stellina della prima card punta allo strumento mostrato',
        html.indexOf('data-act="segui" data-i="0"') > -1
        && win.AMS.carteVisibili()[0].ticker === 'BBB');

  win.AMS.tipiScrivi(['Crypto']);
  win.AMS.render();
  html = vista(win);
  check('un filtro che non lascia passare niente lo dichiara',
        html.indexOf('Il filtro non lascia passare niente') > -1);
  check('e non si spaccia per una giornata vuota',
        html.indexOf('Oggi non c') === -1);
  check('e dice come tornare indietro',
        html.replace(/\s+/g, ' ').indexOf('Tocchi <b>Tutti</b>') > -1);

  win.AMS.tipiScrivi([]);
  win.AMS.render();
  check('azzerando il filtro tornano tutte',
        (vista(win).match(/id="opp-/g) || []).length === 3);

  win = avvia('', null, (d) => {
    treTipi(d);
    d.opportunita.lista = [d.opportunita.lista[0]];
  });
  check('con un tipo solo il menu non compare, perche non servirebbe',
        vista(win).indexOf('class="chipsrow"') === -1);

  console.log('\n11b. Il filtro di una pagina non svuota l altra');
  /* IL DIFETTO, segnalato dall utente. Le due pagine contengono tipi che non
     si sovrappongono: fra le opportunita solo azioni e immobiliare (gli
     unici con bilanci da cui stimare un valore), fra quelli da approfondire
     solo panieri, obbligazioni e materie prime. Con un filtro unico per
     tutta l app, scegliere "Obbligazioni" di la svuotava completamente di
     qua - e la pagina annunciava "il filtro non lascia passare niente" su
     una scelta che l utente non aveva fatto li. */
  win = avvia('', null, (d) => {
    fissaOpportunita(d);
    const base = d.opportunita.lista[0];
    const copia = (tk, classe) => Object.assign({}, base,
      { ticker: tk, asset_class: classe, senza_valore: classe !== 'Azioni' });
    d.opportunita.lista = [copia('AAA', 'Azioni'), copia('DDD', 'Azioni')];
    d.opportunita.osservati = [copia('BBB', 'ETF'), copia('CCC', 'Obbligazioni')];
  });

  // sulla pagina "da approfondire" si sceglie Obbligazioni
  win.AMS.state.pagina = 'osservati';
  win.AMS.tipiScrivi(['Obbligazioni']);
  win.AMS.render();
  check('la scelta vale sulla pagina dove e stata fatta',
        win.AMS.carteVisibili().map(o => o.ticker).join(',') === 'CCC',
        win.AMS.carteVisibili().map(o => o.ticker).join(','));

  // e non deve toccare le opportunita, che sono tutte azioni
  win.AMS.state.pagina = 'opportunita';
  win.AMS.render();
  const dopo = win.AMS.carteVisibili().map(o => o.ticker).join(',');
  check('ma NON tocca la pagina delle opportunita', dopo === 'AAA,DDD', dopo);
  check('e quella pagina non dichiara un filtro che nessuno ha scelto',
        vista(win).indexOf('Il filtro non lascia passare niente') === -1);
  check('la scelta di la resta di la', win.AMS.tipiLeggi('osservati').length === 1,
        JSON.stringify(win.AMS.tipiLeggi('osservati')));
  check('e di qua non c e nessun filtro', win.AMS.tipiLeggi('opportunita').length === 0,
        JSON.stringify(win.AMS.tipiLeggi('opportunita')));

  console.log('\n' + (ok ? 'Tutti i controlli superati.' : 'ALCUNI CONTROLLI FALLITI.'));
  return ok ? 0 : 1;
}

process.exit(main());
