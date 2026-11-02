/* Service worker: fa funzionare la pagina come un'applicazione sul telefono,
   anche quando la rete non c'è.

   Due comportamenti diversi, di proposito:
   - i file della pagina (html, css, js, icone) vengono dalla cache: si aprono
     subito e non cambiano quasi mai;
   - `data.js` viene prima dalla rete, e solo se la rete manca dalla cache: così
     appena il ciclo è pubblicato lo si vede, e se si è senza campo si vede
     quello dell'ultima volta.

   TRE TRAPPOLE, tutte pagate sul campo:

   1. NIENTE "index.html" nei percorsi. Cloudflare (come molti altri) serve la
      cartella e REINDIRIZZA /index.html su /. Un reindirizzamento dentro un
      service worker, su una navigazione, in Chrome diventa "pagina non
      trovata": l'app installata si apriva vuota mentre il link nel browser
      funzionava. Qui si usa sempre './', che è l'indirizzo che il server
      serve davvero.

   2. cache.addAll e' ATOMICO: se UNO dei file non risponde, l'intera lista non
      viene messa in cache e l'app resta senza guscio, senza che nessuno se ne
      accorga. Qui si mette in cache un file per volta, cosi' un file mancante
      costa quel file e non tutti.

   3. Non si mette in cache una risposta reindirizzata o non valida: la Cache
      API la rifiuta, e un rifiuto silenzioso lascia l'app convinta di avere un
      guscio che non ha.

   Funziona solo su https (quindi online); aperta da disco la pagina gira
   normalmente senza di esso. */

// La versione la riscrive build_web.py con l'impronta dei file pubblicati
// (DEMO-35): cambia quando cambia la pagina, cosi' chi ha l'app installata
// riceve la versione nuova senza doverlo sapere.
const VERSIONE = 'ams-b12996887a';
const GUSCIO = [
  './',
  './styles.css',
  './stili-cliente.css',
  './charts.js',
  './onboarding.js',
  './app.js',
  './manifest.webmanifest',
  './icona-192.png',
  './icona-512.png',
];

/** Mette in cache una risposta solo se ha senso tenerla. */
function conservabile(res) {
  return res && res.ok && res.type !== 'opaque' && !res.redirected;
}

self.addEventListener('install', (e) => {
  e.waitUntil(
    caches.open(VERSIONE).then((c) =>
      // uno per volta, non addAll: un file che manca non deve azzerare il resto
      Promise.all(GUSCIO.map((url) =>
        fetch(new Request(url, { cache: 'reload' }))
          .then((res) => (conservabile(res) ? c.put(url, res) : undefined))
          .catch(() => undefined)))
    ).then(() => self.skipWaiting())
  );
});

self.addEventListener('activate', (e) => {
  e.waitUntil(
    caches.keys()
      .then((nomi) => Promise.all(nomi.filter((n) => n !== VERSIONE).map((n) => caches.delete(n))))
      .then(() => self.clients.claim())
  );
});

self.addEventListener('fetch', (e) => {
  const req = e.request;
  if (req.method !== 'GET') return;
  const url = new URL(req.url);
  if (url.origin !== location.origin) return;

  // Le navigazioni (aprire l'app, ricaricare) hanno una strada loro: prima la
  // rete, e se non c'e' la pagina dalla cache. Mai passare per un
  // reindirizzamento, che e' quello che rompeva l'app installata.
  if (req.mode === 'navigate') {
    e.respondWith(
      fetch(req)
        .then((res) => {
          if (conservabile(res)) {
            const copia = res.clone();
            caches.open(VERSIONE).then((c) => c.put('./', copia)).catch(() => undefined);
          }
          return res;
        })
        .catch(() => caches.match('./').then((hit) => hit || caches.match('./index.html')))
    );
    return;
  }

  // I dati del ciclo: prima la rete, poi la cache.
  //
  // `cache: 'no-cache'` non e' un dettaglio. "Prima la rete" non basta: un
  // fetch normale puo' essere soddisfatto dalla cache HTTP del browser senza
  // che la rete venga mai toccata, se la risposta precedente dichiarava una
  // scadenza lunga. Il service worker crederebbe di aver chiesto il dato
  // nuovo e servirebbe quello di stamattina. Con 'no-cache' la richiesta va
  // sempre al server a chiedere "e' cambiato?": se non e' cambiato il server
  // risponde 304 e non si scarica niente, quindi non costa banda. Sopra i
  // prezzi di un'applicazione finanziaria, una scadenza decisa da altri non
  // va bene.
  if (url.pathname.endsWith('/data.js')) {
    e.respondWith(
      fetch(new Request(req.url, { cache: 'no-cache', credentials: 'same-origin' }))
        .then((res) => {
          if (conservabile(res)) {
            const copia = res.clone();
            caches.open(VERSIONE).then((c) => c.put(req, copia)).catch(() => undefined);
          }
          return res;
        })
        .catch(() => caches.match(req).then((hit) => hit || Response.error()))
    );
    return;
  }

  // il resto: prima la cache, poi la rete
  e.respondWith(
    caches.match(req).then((hit) => hit || fetch(req).then((res) => {
      if (conservabile(res)) {
        const copia = res.clone();
        caches.open(VERSIONE).then((c) => c.put(req, copia)).catch(() => undefined);
      }
      return res;
    }).catch(() => caches.match('./')))
  );
});
