"""Invio delle notifiche sui canali reali (BR-07).

Tre canali, nessuno dei quali richiede un'approvazione o una libreria esterna:

* **Push** (`Push`, servizio ntfy.sh) - il canale preferito: arriva sul telefono
  come una notifica di sistema, senza chiavi e senza registrazione;
* **Email** (`Email`, `smtplib`) - l'alternativa quando il telefono non si vuole
  toccare; serve un server SMTP;
* **Telegram** (`Telegram`) - il primo che era stato collegato, resta valido.

Il testo del messaggio lo scrive una funzione sola, `messaggio_opportunita`:
tre o quattro righe, in italiano, uguali su tutti i canali. Una notifica che non
si legge a schermo bloccato non serve a niente, quindi la lunghezza e' un
vincolo di prodotto e non una preferenza estetica.

Telegram, che era qui dal primo giorno
--------------------------------------

Serve un bot e la propria chat:

1. su Telegram scrivi a @BotFather, comando /newbot, ti dà un token;
2. scrivi un messaggio qualsiasi al tuo bot;
3. `python cli.py telegram-id` stampa il tuo chat id;
4. `$env:TELEGRAM_TOKEN`, `$env:TELEGRAM_CHAT_ID`, poi `scan --telegram`.

Il messaggio contiene la segnalazione in italiano semplice: la stessa che la
vista cliente mostra a schermo.

Push con ntfy.sh
----------------

Si installa l'app ntfy (Android/iOS, oppure https://ntfy.sh/app nel browser), si
aggiunge un argomento ("topic") e si mette lo stesso nome in `NTFY_TOPIC`:

    $env:NTFY_TOPIC = "scout-<qualcosa-di-lungo-e-casuale>"

ATTENZIONE ALLA RISERVATEZZA. Su ntfy.sh non c'e' nessuna chiave e nessun
account: **chiunque conosca il nome dell'argomento riceve le sue notifiche**, e
chiunque possa indovinarlo pure. Un nome come "borsa" o "mario" e' pubblico di
fatto. Quindi: nome lungo e casuale (venti caratteri o piu'), e dentro il
messaggio niente dati di portafoglio - solo la segnalazione, che e' la stessa
per tutti. Chi vuole la riservatezza vera fa girare il proprio server ntfy e lo
indica in `NTFY_SERVER`.

Email con SMTP
--------------

Quattro variabili d'ambiente e il canale e' attivo:

    $env:SMTP_HOST = "smtp.gmail.com"      # $env:SMTP_PORT = "587" se diversa
    $env:SMTP_USER = "io@gmail.com"
    $env:SMTP_PASS = "xxxx xxxx xxxx xxxx" # password PER LE APP, non quella dell'account
    $env:SMTP_TO   = "io@gmail.com"

Con Gmail la password dell'account **non funziona**: serve una "password per le
app" (account Google, Sicurezza, verifica in due passaggi, Password per le app),
che e' una stringa di sedici caratteri generata per questo programma e
revocabile da sola. Lo stesso vale per Outlook/Microsoft 365 e per iCloud.
"""

from __future__ import annotations

import json
import os
import re
import smtplib
import ssl
import urllib.error
import urllib.parse
import urllib.request
from email.message import EmailMessage

API = "https://api.telegram.org/bot{token}/{method}"
TIMEOUT_S = 20

NTFY_SERVER = "https://ntfy.sh"
NTFY_TOPIC_MIN = 20          # sotto questa lunghezza l'argomento e' indovinabile
SMTP_PORT_DEFAULT = 587      # la porta dello STARTTLS
SMTP_TIMEOUT_S = 25
MAX_RIGHE = 4                # tetto di lunghezza della notifica, vincolo di prodotto


def _call(token: str, method: str, payload: dict) -> dict:
    url = API.format(token=token, method=method)
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(url, data=data, method="POST",
                                 headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=TIMEOUT_S,
                                context=ssl.create_default_context()) as r:
        return json.loads(r.read().decode("utf-8"))


class Telegram:
    def __init__(self, token: str | None = None, chat_id: str | None = None,
                 enabled: bool = False):
        self.token = (token or os.environ.get("TELEGRAM_TOKEN", "")).strip()
        self.chat_id = (chat_id or os.environ.get("TELEGRAM_CHAT_ID", "")).strip()
        self.enabled = bool(enabled and self.token and self.chat_id)
        self.sent = 0
        self.errors: list[str] = []

    @property
    def mode(self) -> str:
        if self.enabled:
            return "attivo"
        if not self.token:
            return "spento (manca TELEGRAM_TOKEN)"
        if not self.chat_id:
            return "spento (manca TELEGRAM_CHAT_ID)"
        return "spento (non richiesto)"

    def whoami(self) -> dict:
        """Trova il chat id leggendo gli ultimi messaggi ricevuti dal bot."""
        if not self.token:
            return {"ok": False, "detail": "TELEGRAM_TOKEN non impostata"}
        try:
            me = _call(self.token, "getMe", {})
            upd = _call(self.token, "getUpdates", {"limit": 10})
        except urllib.error.HTTPError as e:
            return {"ok": False, "detail": f"HTTP {e.code}: {e.read()[:200].decode('utf-8', 'replace')}"}
        except Exception as e:
            return {"ok": False, "detail": f"{type(e).__name__}: {e}"}
        chats = []
        for u in upd.get("result", []):
            msg = u.get("message") or u.get("channel_post") or {}
            chat = msg.get("chat") or {}
            if chat.get("id") and chat["id"] not in [c["id"] for c in chats]:
                chats.append({"id": chat["id"],
                              "name": chat.get("first_name") or chat.get("title") or "",
                              "type": chat.get("type")})
        return {"ok": True, "bot": (me.get("result") or {}).get("username"), "chats": chats}

    def send(self, text: str) -> bool:
        if not self.enabled:
            return False
        try:
            res = _call(self.token, "sendMessage",
                        {"chat_id": self.chat_id, "text": text,
                         "parse_mode": "HTML", "disable_web_page_preview": True})
            if res.get("ok"):
                self.sent += 1
                return True
            self.errors.append(str(res)[:200])
        except urllib.error.HTTPError as e:
            self.errors.append(f"HTTP {e.code}: {e.read()[:200].decode('utf-8', 'replace')}")
        except Exception as e:
            self.errors.append(f"{type(e).__name__}: {e}")
        return False


def opportunity_message(user: dict, notification: dict, plain: dict) -> str:
    """La segnalazione come la legge il cliente, in HTML minimale."""
    p = notification["plan"]
    lines = [
        f"<b>{plain['light_label']}: {notification['name']}</b> ({notification['ticker']})",
        "",
        plain["what_is_it"],
        "",
        f"<b>In euro.</b> {plain['money']['sentence']}",
        "",
        "<b>Perché adesso</b>",
    ]
    for w in plain["why_now"][:3]:
        lines.append(f"• <b>{w['title']}</b>: {w['text']}")
    lines += [
        "",
        f"<b>Quanto rischia.</b> {plain['risk_plain']}",
        "",
        "<b>Che cosa fare, se vuole</b>",
    ]
    for i, step in enumerate(plain["what_to_do"], 1):
        lines.append(f"{i}. {step}")
    lines += [
        "",
        f"<i>{plain['analysis_by']} {plain['caveat']}</i>",
        f"<i>Voto {notification['opportunity_score']}/100 · ingresso "
        f"{p['entry_low']}-{p['entry_high']} · protezione {p['stop_loss']} · "
        f"obiettivo {p['target']}</i>",
    ]
    return "\n".join(lines)


def digest_message(user: dict, state: dict) -> str:
    """Messaggio di riepilogo quando non c'è niente da segnalare."""
    pf = user["plain_portfolio"]
    lines = [f"<b>{user['plain_greeting']['line']}</b>", "", pf["summary"]]
    if pf["alerts_plain"]:
        lines += ["", "<b>Cose da sapere</b>"]
        for a in pf["alerts_plain"][:3]:
            lines.append(f"• <b>{a['title']}</b>: {a['text']}")
    lines += ["", f"<i>Ciclo del {state['today']} · {len(state['assets'])} strumenti "
                  f"controllati · dati: {state['data']['source']}</i>"]
    return "\n".join(lines)


# ===========================================================================
# Il messaggio: una funzione sola per tutti i canali
# ===========================================================================

TIPI = {
    "nuova": ("Nuova opportunità", "chart_with_upwards_trend"),
    "cambiata": ("Aggiornamento", "arrows_counterclockwise"),
}


def _cifra(valore, decimali: int = 2) -> str:
    """Numeri scritti come li scrive un italiano: 1.234,56 e non 1,234.56.
    Un prezzo letto al contrario dentro una notifica e' un prezzo sbagliato."""
    try:
        testo = f"{float(valore):,.{decimali}f}"
    except Exception:
        return "n.d."
    return testo.replace(",", "\x00").replace(".", ",").replace("\x00", ".")


def messaggio_opportunita(opportunita: dict, tipo: str | None = None,
                          motivo: str | None = None) -> dict:
    """Il testo della notifica, uguale su push, email e Telegram.

    Una funzione sola per tre canali per un motivo pratico: se il testo vivesse
    in tre posti, la riga di avvertenza finirebbe per mancare in uno dei tre.

    Vincoli che rispetta, e che sono vincoli di prodotto e non gusto personale:

    * al massimo quattro righe (`MAX_RIGHE`), perche' la notifica si deve poter
      leggere a schermo bloccato senza aprirla;
    * testo semplice senza marcatori, perche' lo stesso testo deve stare bene
      in una notifica di sistema, in una email e in una chat;
    * tono formale, la terza persona di cortesia;
    * nessuna promessa di rendimento e nessun consiglio personalizzato: le
      opportunita' sono le stesse per tutti e nessuno qui sa che cosa sia
      adatto a chi legge.

    Restituisce titolo, corpo e i due parametri che servono al push (priorita'
    ed etichette): ogni canale prende quello che sa usare e ignora il resto.
    """
    op = opportunita if isinstance(opportunita, dict) else {}
    tipo = (tipo or op.get("tipo") or "nuova").strip().lower()
    prefisso, tag = TIPI.get(tipo, TIPI["nuova"])
    motivo = (motivo if motivo is not None else op.get("motivo") or "").strip()

    ticker = str(op.get("ticker") or op.get("simbolo") or "?").strip()
    nome = str(op.get("nome") or op.get("name") or ticker).strip()
    punteggio = op.get("punteggio")
    if punteggio is None:
        punteggio = op.get("opportunity_score")
    fascia = str(op.get("classificazione") or op.get("classification") or "").strip()
    valuta = str(op.get("valuta") or op.get("currency") or "").strip()
    prezzo = op.get("prezzo") if op.get("prezzo") is not None else op.get("price")
    valore = op.get("valore")
    if valore is None:
        valore = op.get("fair_value") if op.get("fair_value") is not None \
            else op.get("target_price")

    voto = f"{int(round(float(punteggio)))}" if isinstance(punteggio, (int, float)) \
        and not isinstance(punteggio, bool) else "n.d."
    titolo = f"{prefisso}: {ticker} {voto}/100"

    prima = f"{nome} ({ticker})" if nome != ticker else ticker
    if fascia:
        prima += f" - {fascia[0].lower() + fascia[1:]}"
    prima += f", punteggio {voto} su 100."

    seconda = f"Prezzo {_cifra(prezzo)} {valuta}".rstrip()
    if valore is not None:
        seconda += f", valore stimato dal sistema {_cifra(valore)} {valuta}".rstrip()
    righe = [prima, seconda + "."]

    if motivo:
        # il motivo sta su una riga: se e' lungo si taglia invece di riassumerlo,
        # perche' un riassunto automatico di una riga puo' cambiarne il senso
        testo = motivo if len(motivo) <= 150 else motivo[:147].rstrip(" ,;.") + "..."
        testo = testo[0].lower() + testo[1:]
        righe.append(f"Perché: {testo}" + ("" if testo.endswith((".", "...", "!")) else "."))
    righe.append("Analisi automatica su dati pubblici: valuti lei, non è un consiglio "
                 "di investimento.")

    urgente = bool(op.get("urgente"))
    return {
        "titolo": titolo,
        "corpo": "\n".join(righe[:MAX_RIGHE]),
        "righe": righe[:MAX_RIGHE],
        "priorita": "high" if urgente else "default",
        "tags": [tag] + (["warning"] if urgente else []),
        "ticker": ticker,
        "tipo": tipo,
    }


# ===========================================================================
# Push: ntfy.sh
# ===========================================================================

def _intestazione(valore) -> str:
    """Un'intestazione HTTP con gli accenti e senza sorprese.

    Due cose da sapere. La prima: `urllib` scrive le intestazioni in latin-1 e
    ntfy le rilegge come UTF-8, quindi passandogli i byte UTF-8 travestiti da
    latin-1 gli accenti arrivano giusti (verificato pubblicando e rileggendo
    davvero un messaggio). La seconda: un ritorno a capo dentro un'intestazione
    permetterebbe di aggiungerne altre, percio' si toglie sempre - il titolo
    nasce da dati di mercato, e i dati di mercato non li scriviamo noi.
    """
    pulito = re.sub(r"[\r\n]+", " ", str(valore or "")).strip()
    return pulito.encode("utf-8").decode("latin-1")


class Push:
    """Notifica push sul telefono con ntfy.sh: nessuna chiave, nessun account.

    Si pubblica con una POST a `https://ntfy.sh/<argomento>`, il testo nel corpo
    e titolo, priorita' ed etichette nelle intestazioni. Chi ha l'app aperta su
    quell'argomento riceve la notifica in un secondo.

    RISERVATEZZA, e non e' un dettaglio di contorno: l'argomento e' l'unico
    segreto che esiste. Chiunque lo conosca - o lo indovini - riceve tutte le
    notifiche, e puo' anche scriverne di finte. Per questo l'argomento va scelto
    lungo e casuale e nel messaggio non finiscono mai dati di portafoglio.
    `avvisi()` protesta quando l'argomento e' corto, perche' un nome corto su un
    server pubblico e' un nome pubblico. Chi vuole riservatezza vera fa girare
    il proprio server ntfy e lo indica in NTFY_SERVER.
    """

    def __init__(self, topic: str | None = None, server: str | None = None,
                 enabled: bool = False):
        self.topic = (topic or os.environ.get("NTFY_TOPIC", "")).strip().strip("/")
        self.server = (server or os.environ.get("NTFY_SERVER") or NTFY_SERVER).rstrip("/")
        self.enabled = bool(enabled and self.topic)
        self.sent = 0
        self.errors: list[str] = []

    @property
    def mode(self) -> str:
        if self.enabled:
            return f"attivo ({self.server}, argomento di {len(self.topic)} caratteri)"
        if not self.topic:
            return "spento (manca NTFY_TOPIC)"
        return "spento (non richiesto)"

    def avvisi(self) -> list[str]:
        """Quello che va detto a chi configura il canale, non a chi lo riceve."""
        fuori: list[str] = []
        if not self.topic:
            return fuori
        if len(self.topic) < NTFY_TOPIC_MIN:
            fuori.append(f"NTFY_TOPIC è troppo corto ({len(self.topic)} caratteri): su un "
                         f"server pubblico chiunque lo indovini riceve le sue notifiche, "
                         f"ne usi almeno {NTFY_TOPIC_MIN} casuali")
        if not re.fullmatch(r"[A-Za-z0-9_-]{1,64}", self.topic):
            fuori.append("NTFY_TOPIC può contenere solo lettere, cifre, trattino e "
                         "trattino basso, per un massimo di 64 caratteri")
        return fuori

    def health(self) -> dict:
        """Il servizio risponde? Serve a distinguere "ntfy è giù" da "la rete
        dell'ufficio blocca ntfy", che nel log sarebbero la stessa riga."""
        try:
            req = urllib.request.Request(f"{self.server}/v1/health",
                                         headers={"Accept": "application/json"})
            with urllib.request.urlopen(req, timeout=TIMEOUT_S,
                                        context=ssl.create_default_context()) as r:
                dati = json.loads(r.read().decode("utf-8"))
            return {"ok": bool(dati.get("healthy")), "detail": json.dumps(dati)}
        except urllib.error.HTTPError as e:
            return {"ok": False, "detail": f"HTTP {e.code}"}
        except Exception as e:
            return {"ok": False, "detail": f"{type(e).__name__}: {e}"}

    def send(self, text: str, title: str | None = None, priority: str | None = None,
             tags=None, click: str | None = None) -> bool:
        """Pubblica il messaggio. Non solleva mai: un push che non parte e' una
        riga di log, non la fine del ciclo di scansione (OP-06)."""
        if not self.enabled:
            return False
        intestazioni = {"Content-Type": "text/plain; charset=utf-8"}
        if title:
            intestazioni["Title"] = _intestazione(title)
        if priority:
            intestazioni["Priority"] = _intestazione(priority)
        if tags:
            intestazioni["Tags"] = _intestazione(tags if isinstance(tags, str)
                                                 else ",".join(str(t) for t in tags))
        if click:
            intestazioni["Click"] = _intestazione(click)
        url = f"{self.server}/{urllib.parse.quote(self.topic, safe='-_')}"
        try:
            req = urllib.request.Request(url, data=str(text).encode("utf-8"),
                                         method="POST", headers=intestazioni)
            with urllib.request.urlopen(req, timeout=TIMEOUT_S,
                                        context=ssl.create_default_context()) as r:
                corpo = r.read().decode("utf-8", "replace")
            # ntfy risponde con il messaggio appena registrato: se nella risposta
            # non c'e' l'identificativo non e' andata, anche con stato HTTP 200
            try:
                registrato = json.loads(corpo)
            except Exception:
                registrato = {}
            if isinstance(registrato, dict) and registrato.get("id"):
                self.sent += 1
                return True
            self.errors.append(f"risposta senza identificativo: {corpo[:200]}")
        except urllib.error.HTTPError as e:
            self.errors.append(f"HTTP {e.code}: "
                               f"{e.read()[:200].decode('utf-8', 'replace')}")
        except Exception as e:
            self.errors.append(f"{type(e).__name__}: {e}")
        return False

    def send_message(self, messaggio: dict, click: str | None = None) -> bool:
        """Manda quello che ha scritto `messaggio_opportunita`."""
        m = messaggio or {}
        return self.send(m.get("corpo", ""), title=m.get("titolo"),
                         priority=m.get("priorita"), tags=m.get("tags"), click=click)


# ===========================================================================
# Email: smtplib della libreria standard
# ===========================================================================

LOCALI = {"localhost", "127.0.0.1", "::1", "[::1]"}


class Email:
    """Notifica per posta, con `smtplib` e STARTTLS.

    Server, porta, utente, password e destinatario vengono dall'ambiente
    (SMTP_HOST, SMTP_PORT, SMTP_USER, SMTP_PASS, SMTP_TO; SMTP_FROM se il
    mittente e' diverso dall'utente): fuori dal codice e fuori dai file del
    progetto, cosi' una password non finisce per sbaglio in un backup.

    Con Gmail serve una **password per le app**, non la password dell'account:
    dal 2022 Google rifiuta la seconda sui client SMTP. Si genera dalle
    impostazioni di sicurezza dell'account Google (serve la verifica in due
    passaggi), e' una stringa di sedici caratteri valida solo per questo
    programma e si revoca senza toccare l'account. Stessa storia su Outlook e
    su iCloud.

    Se manca una variabile il canale e' spento e lo dichiara in `mode`: non e'
    un errore, e' una configurazione incompleta, e la scansione continua.
    """

    def __init__(self, host: str | None = None, port: int | None = None,
                 user: str | None = None, password: str | None = None,
                 to: str | None = None, sender: str | None = None,
                 starttls: bool | None = None, enabled: bool = False):
        self.host = (host or os.environ.get("SMTP_HOST", "")).strip()
        porta = port if port is not None else os.environ.get("SMTP_PORT", "")
        try:
            self.port = int(str(porta).strip() or SMTP_PORT_DEFAULT)
        except Exception:
            self.port = SMTP_PORT_DEFAULT
        self.user = (user or os.environ.get("SMTP_USER", "")).strip()
        self.password = password if password is not None else os.environ.get("SMTP_PASS", "")
        destinatari = (to or os.environ.get("SMTP_TO", "")).strip()
        self.to = [d.strip() for d in re.split(r"[,;]", destinatari) if d.strip()]
        self.sender = (sender or os.environ.get("SMTP_FROM") or self.user).strip()
        if starttls is None:
            # SMTP_STARTTLS=0 esiste solo per provare il canale contro il server
            # finto su questo computer, che un certificato non ce l'ha. In rete
            # va lasciato acceso, e `send` si rifiuta di spegnerlo verso un
            # server che non sia locale: altrimenti la password uscirebbe in
            # chiaro senza che nessuno se ne accorga.
            scelta = os.environ.get("SMTP_STARTTLS", "1").strip().lower()
            self.starttls = scelta not in ("0", "no", "false", "off")
        else:
            self.starttls = bool(starttls)
        self.enabled = bool(enabled and self.host and self.user and self.password and self.to)
        self.sent = 0
        self.errors: list[str] = []

    @property
    def mode(self) -> str:
        if self.enabled:
            return (f"attivo ({self.user} -> {', '.join(self.to)} via "
                    f"{self.host}:{self.port}"
                    + (", STARTTLS" if self.starttls else ", IN CHIARO") + ")")
        mancanti = [nome for nome, valore in (("SMTP_HOST", self.host),
                                              ("SMTP_USER", self.user),
                                              ("SMTP_PASS", self.password),
                                              ("SMTP_TO", self.to)) if not valore]
        if mancanti:
            return f"spento (manca {', '.join(mancanti)})"
        return "spento (non richiesto)"

    def _messaggio(self, corpo, titolo) -> EmailMessage:
        msg = EmailMessage()
        msg["Subject"] = re.sub(r"[\r\n]+", " ", str(titolo or "AI Market Scout")).strip()
        msg["From"] = self.sender
        msg["To"] = ", ".join(self.to)
        # set_content sceglie da solo la codifica: con gli accenti passa a UTF-8
        # quoted-printable, che e' esattamente quello che serve
        msg.set_content(str(corpo))
        return msg

    def send(self, text: str, title: str | None = None) -> bool:
        """Invia. Come gli altri canali non solleva: registra l'errore e
        restituisce False, perche' una notifica mancata non deve fermare la
        scansione (OP-06)."""
        if not self.enabled:
            return False
        if not self.starttls and self.host.lower() not in LOCALI:
            self.errors.append(f"invio annullato: STARTTLS disattivato verso "
                               f"{self.host}, la password viaggerebbe in chiaro")
            return False
        msg = self._messaggio(text, title)
        server = None
        try:
            server = smtplib.SMTP(self.host, self.port, timeout=SMTP_TIMEOUT_S)
            server.ehlo()
            if self.starttls:
                if not server.has_extn("starttls"):
                    self.errors.append(f"{self.host}:{self.port} non offre STARTTLS: "
                                       f"invio annullato per non mandare la password "
                                       f"in chiaro")
                    return False
                server.starttls(context=ssl.create_default_context())
                server.ehlo()
            if server.has_extn("auth"):
                server.login(self.user, self.password)
            rifiutati = server.send_message(msg)
            if rifiutati:
                self.errors.append(f"destinatari rifiutati dal server: {rifiutati}")
                return False
            self.sent += 1
            return True
        except smtplib.SMTPAuthenticationError as e:
            self.errors.append(f"autenticazione rifiutata ({e.smtp_code}): con Gmail "
                               f"serve una password per le app, non quella dell'account")
        except smtplib.SMTPException as e:
            self.errors.append(f"{type(e).__name__}: {e}")
        except Exception as e:
            self.errors.append(f"{type(e).__name__}: {e}")
        finally:
            if server is not None:
                try:
                    server.quit()
                except Exception:
                    # il server puo' aver gia' chiuso la connessione: chiudere
                    # male non deve diventare un invio fallito
                    pass
        return False

    def send_message(self, messaggio: dict) -> bool:
        m = messaggio or {}
        return self.send(m.get("corpo", ""), title=m.get("titolo"))


# ===========================================================================
# Consegna su piu' canali
# ===========================================================================

def consegna(messaggio: dict, canali: dict) -> dict:
    """Manda lo stesso messaggio su tutti i canali accesi e racconta com'e'
    andata, uno per uno.

    Esiste per il principio OP-06: un canale che non risponde non deve impedire
    agli altri di provare, ne' fermare la scansione. Chi chiama guarda
    `consegnato` per sapere se almeno uno ha funzionato, e `esiti` per il log.
    """
    esiti = {}
    for nome, canale in (canali or {}).items():
        if canale is None or not getattr(canale, "enabled", False):
            esiti[nome] = {"inviato": False,
                           "dettaglio": getattr(canale, "mode", "canale assente")}
            continue
        prima = len(getattr(canale, "errors", []))
        try:
            inviato = bool(canale.send_message(messaggio))
        except Exception as e:
            # i canali non dovrebbero sollevare: se succede comunque l'errore
            # resta dentro questa funzione e non sale al ciclo di scansione
            inviato = False
            getattr(canale, "errors", []).append(f"{type(e).__name__}: {e}")
        nuovi = getattr(canale, "errors", [])[prima:]
        esiti[nome] = {"inviato": inviato,
                       "dettaglio": "inviato" if inviato
                       else (nuovi[-1] if nuovi else "non inviato")}
    return {"consegnato": any(e["inviato"] for e in esiti.values()),
            "esiti": esiti,
            "titolo": (messaggio or {}).get("titolo", "")}
