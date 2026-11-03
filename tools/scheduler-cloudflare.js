/* Scheduler esterno: dice a GitHub di far partire il ciclo, all'ora giusta.
 * ====================================================================
 *
 * PERCHE' ESISTE. La cadenza "ogni due ore" non e' ottenibile dallo
 * scheduler di GitHub. Misurato su questo repository: con i cron ai minuti
 * :05 non e' partito niente per cinque ore; spostati a :23 hanno cominciato a
 * partire ma con ritardi fino a SEI ORE e fasce saltate - il ciclo delle
 * 21:23 e' arrivato alle 03:13 del giorno dopo. GitHub lo dichiara: l'evento
 * schedule e' best effort, viene accodato e nei momenti di carico scartato.
 * Non c'e' niente da sistemare dall'interno: va spostata fuori la decisione
 * di quando partire.
 *
 * COSA FA. Un Cron Trigger di Cloudflare lo sveglia, e lui chiede a GitHub di
 * emettere l'evento `repository_dispatch` di tipo "ciclo". Il workflow lo
 * ascolta e parte. Nient'altro.
 *
 * COSA NON FA, DI PROPOSITO: non decide se usare l'AI. Quella scelta sta in
 * un posto solo, dentro il workflow, che guarda l'ora. Se la decidesse anche
 * questo file, l'orario dell'AI sarebbe scritto in due posti e cambiarne uno
 * solo produrrebbe un ciclo che gira all'ora nuova senza AI, senza dirlo a
 * nessuno. E' esattamente l'errore che questo progetto ha gia' fatto una
 * volta.
 *
 * DOVE SI INSTALLA: vedi AUTOMATICO.md, sezione "Lo scheduler esterno".
 * Serve una variabile segreta GITHUB_TOKEN con il solo permesso di scrivere
 * sui contenuti del repository.
 */

const PROPRIETARIO = 'GabrieleLevati';
const REPOSITORY = 'Market-Scout';

/* GitHub RIFIUTA le richieste senza User-Agent: risponde 403 e il motivo non
 * si capisce dal messaggio. In questo progetto e' gia' costato un ciclo
 * intero di diagnosi sbagliata con Groq, che sta dietro lo stesso tipo di
 * filtro. Non si tocca. */
const USER_AGENT = 'Market-Scout-scheduler (Cloudflare Worker)';

export default {
  async scheduled(evento, env, ctx) {
    ctx.waitUntil(avvia(env));
  },

  /* Una chiamata a mano per provare che funzioni, senza aspettare il cron:
   * si apre l'indirizzo del Worker nel browser. Non espone niente - il token
   * resta nelle variabili segrete - e risponde che cosa ha detto GitHub. */
  async fetch(richiesta, env) {
    const esito = await avvia(env);
    return new Response(JSON.stringify(esito, null, 2), {
      status: esito.ok ? 200 : 500,
      headers: { 'content-type': 'application/json; charset=utf-8' },
    });
  },
};

async function avvia(env) {
  if (!env.GITHUB_TOKEN) {
    return { ok: false, errore: 'manca la variabile segreta GITHUB_TOKEN' };
  }
  const url = `https://api.github.com/repos/${PROPRIETARIO}/${REPOSITORY}/dispatches`;
  let risposta;
  try {
    risposta = await fetch(url, {
      method: 'POST',
      headers: {
        'Authorization': `Bearer ${env.GITHUB_TOKEN}`,
        'Accept': 'application/vnd.github+json',
        'X-GitHub-Api-Version': '2022-11-28',
        'User-Agent': USER_AGENT,
        'Content-Type': 'application/json',
      },
      body: JSON.stringify({ event_type: 'ciclo' }),
    });
  } catch (e) {
    // La rete puo' mancare: si dichiara e il prossimo cron riprova. Non si
    // ritenta subito, perche' un ciclo in piu' non vale niente e un ciclo in
    // meno costa due ore di dati vecchi, non di piu'.
    return { ok: false, errore: 'rete: ' + e.message };
  }

  /* GitHub risponde 204 senza corpo quando ha accettato. Qualunque altra cosa
   * va riportata con il suo testo: un 404 qui vuol dire quasi sempre che il
   * token non ha i permessi su questo repository, e senza il corpo della
   * risposta lo si confonde con "repository inesistente". */
  if (risposta.status === 204) {
    return { ok: true, stato: 204, detto: 'GitHub ha accettato: il ciclo parte' };
  }
  const testo = await risposta.text();
  return {
    ok: false,
    stato: risposta.status,
    detto: testo.slice(0, 400),
    nota: risposta.status === 404
      ? 'un 404 qui e\' quasi sempre il token senza permesso di scrittura su questo repository, non un repository mancante'
      : undefined,
  };
}
