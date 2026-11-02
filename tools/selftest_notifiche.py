"""Verifica della memoria delle notifiche e dei canali, senza rete.

Due pezzi da provare, ed entrambi si possono provare solo fingendo il mondo
esterno:

* `engine/visti.py` - decide che cosa e' nuovo e che cosa e' una ripetizione.
  E' la parte che protegge l'utente dalle dodici notifiche al giorno, quindi i
  controlli qui sono sui casi che fanno danno: lo stesso titolo al ciclo dopo,
  il periodo di riposo, il file di stato corrotto.
* `engine/channels.py` - push e email. Il push gira contro un `urlopen` finto
  (compreso il caso in cui ntfy risponde 500); l'email gira contro un **server
  SMTP finto scritto qui sotto**, un socket in ascolto su localhost che parla
  abbastanza SMTP da accettare un messaggio. Cosi' si prova davvero che il
  messaggio parte e che il contenuto e' quello giusto, senza avere credenziali.

    python tools/selftest_notifiche.py
    python tools/selftest_notifiche.py --rete    # aggiunge una prova vera su ntfy.sh

Senza `--rete` nessun pacchetto esce da questo computer: le connessioni sono
verso 127.0.0.1.
"""

from __future__ import annotations

import email.policy
import io
import json
import os
import secrets
import socket
import sys
import tempfile
import threading
import time
import urllib.error
import urllib.request
from datetime import datetime, timedelta, timezone
from email.parser import BytesParser
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from engine import channels, visti                   # noqa: E402

T0 = datetime(2026, 3, 2, 9, 0, tzinfo=timezone.utc)
VERO_URLOPEN = urllib.request.urlopen


def check(label: str, condition: bool, detail: str = "") -> bool:
    print(f"  [{'ok ' if condition else 'KO '}] {label}" + (f" - {detail}" if detail else ""))
    return bool(condition)


def opportunita(ticker="AMD", punteggio=86, fascia="Opportunità forte",
                prezzo=100.0, valore=130.0, uscita=90.0, nome=None) -> dict:
    """Un'opportunita' nella forma in cui la produce il motore (nomi inglesi,
    come in `notifications.build_notification`): il modulo deve digerirla senza
    traduzioni intermedie."""
    return {"ticker": ticker, "name": nome or f"Societa {ticker}",
            "opportunity_score": punteggio, "classification": fascia,
            "price": prezzo, "fair_value": valore, "currency": "USD",
            "plan": {"stop_loss": uscita, "target": valore},
            "reasons": ["crescita dei ricavi sopra la media del settore"]}


# ===========================================================================
# ntfy finto
# ===========================================================================

class Ctx:
    def __init__(self, data):
        self.data = data

    def __enter__(self):
        return self.data

    def __exit__(self, *a):
        return False


RICHIESTE: list[dict] = []


def installa_ntfy_finto(modo: str = "ok"):
    """modo: ok | errore_500 | senza_id | salute_rotta"""
    def finto_urlopen(req, timeout=None, context=None):
        url = req.full_url
        RICHIESTE.append({
            "url": url,
            "metodo": req.get_method(),
            "corpo": (req.data or b"").decode("utf-8"),
            "titolo": req.get_header("Title"),
            "priorita": req.get_header("Priority"),
            "etichette": req.get_header("Tags"),
            "click": req.get_header("Click"),
        })
        if url.endswith("/v1/health"):
            if modo == "salute_rotta":
                raise urllib.error.URLError("nome non risolto")
            return Ctx(io.BytesIO(b'{"healthy":true,"role":"active"}'))
        if modo == "errore_500":
            raise urllib.error.HTTPError(url, 500, "Internal Server Error", {},
                                         io.BytesIO(b'{"error":"server guasto"}'))
        if modo == "senza_id":
            return Ctx(io.BytesIO(b'{"ok":"forse"}'))
        return Ctx(io.BytesIO(json.dumps(
            {"id": "aBcD1234", "time": 1793000000, "event": "message",
             "topic": url.rsplit("/", 1)[-1]}).encode("utf-8")))

    urllib.request.urlopen = finto_urlopen


# ===========================================================================
# Server SMTP finto
# ===========================================================================

class ServerSmtpFinto:
    """Un server SMTP che parla il minimo indispensabile, su localhost.

    Non si puo' provare l'email vera senza credenziali, e un invio verso un
    server reale in un controllo automatico sarebbe comunque sbagliato. Allora
    il server lo scriviamo noi: saluta, accetta l'autenticazione, prende il
    messaggio e lo tiene da parte. Cosi' il controllo verifica le due cose che
    contano - che il messaggio parta e che dentro ci sia il testo giusto - senza
    uscire dal computer.

    Nessun STARTTLS: un certificato qui non c'e'. Per questo il canale va
    costruito con `starttls=False`, che la classe `Email` accetta solo verso un
    indirizzo locale (il controllo su quel rifiuto e' piu' sotto).
    """

    def __init__(self):
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.sock.bind(("127.0.0.1", 0))
        self.sock.listen(1)
        self.sock.settimeout(20)
        self.host, self.port = self.sock.getsockname()
        self.conversazione: list[str] = []
        self.messaggi: list[dict] = []
        self.errore: str | None = None
        self._t = threading.Thread(target=self._servi, daemon=True)

    def avvia(self) -> "ServerSmtpFinto":
        self._t.start()
        return self

    def chiudi(self, secondi: float = 10.0) -> bool:
        self._t.join(secondi)
        try:
            self.sock.close()
        except Exception:
            pass
        return not self._t.is_alive()

    def _servi(self):
        try:
            conn, _ = self.sock.accept()
        except Exception as e:
            self.errore = f"{type(e).__name__}: {e}"
            return
        mittente, destinatari = None, []
        try:
            conn.settimeout(20)
            with conn, conn.makefile("rwb") as f:
                def rispondi(testo: str):
                    f.write(testo.encode("utf-8") + b"\r\n")
                    f.flush()

                rispondi("220 localhost ESMTP server finto del selftest")
                while True:
                    linea = f.readline()
                    if not linea:
                        break
                    cmd = linea.decode("utf-8", "replace").rstrip("\r\n")
                    self.conversazione.append(cmd)
                    alto = cmd.upper()
                    if alto.startswith(("EHLO", "HELO")):
                        # niente SIZE e niente 8BITMIME: meno estensioni
                        # dichiariamo, meno strade diverse puo' prendere smtplib
                        f.write(b"250-localhost\r\n250-AUTH PLAIN LOGIN\r\n250 HELP\r\n")
                        f.flush()
                    elif alto.startswith("AUTH PLAIN"):
                        if len(cmd.split()) == 2:
                            rispondi("334 ")          # credenziali su riga separata
                            f.readline()
                        rispondi("235 2.7.0 autenticazione accettata")
                    elif alto.startswith("AUTH LOGIN"):
                        rispondi("334 VXNlcm5hbWU6")
                        f.readline()
                        rispondi("334 UGFzc3dvcmQ6")
                        f.readline()
                        rispondi("235 2.7.0 autenticazione accettata")
                    elif alto.startswith("MAIL FROM"):
                        mittente = cmd[cmd.find(":") + 1:].strip()
                        rispondi("250 2.1.0 mittente accettato")
                    elif alto.startswith("RCPT TO"):
                        destinatari.append(cmd[cmd.find(":") + 1:].strip())
                        rispondi("250 2.1.5 destinatario accettato")
                    elif alto == "DATA":
                        rispondi("354 scriva il messaggio, chiuda con un punto da solo")
                        righe = []
                        while True:
                            l = f.readline()
                            if not l or l in (b".\r\n", b".\n"):
                                break
                            if l.startswith(b".."):
                                l = l[1:]             # il punto raddoppiato va tolto
                            righe.append(l)
                        self.messaggi.append({"mittente": mittente,
                                              "destinatari": list(destinatari),
                                              "dati": b"".join(righe)})
                        rispondi("250 2.0.0 messaggio accettato")
                    elif alto == "QUIT":
                        rispondi("221 2.0.0 arrivederci")
                        break
                    elif alto in ("RSET", "NOOP"):
                        rispondi("250 2.0.0 ok")
                    else:
                        rispondi("502 5.5.1 comando non previsto dal server finto")
        except Exception as e:
            self.errore = f"{type(e).__name__}: {e}"


def leggi_email(grezza: bytes):
    return BytesParser(policy=email.policy.default).parsebytes(grezza)


# ===========================================================================
# I controlli
# ===========================================================================

def main(argv=None) -> int:
    argv = list(argv if argv is not None else sys.argv[1:])
    con_rete = "--rete" in argv
    ok = True
    cartella = Path(tempfile.mkdtemp(prefix="scout_notifiche_"))
    stato = cartella / ".opportunita_viste.json"

    print("1. Prima volta che si vede un titolo: notifica")
    e1 = visti.novita([opportunita()], path=stato, quando=T0)
    ok &= check("una sola novità", len(e1["nuove"]) == 1 and not e1["cambiate"],
                f"{len(e1['nuove'])} nuove, {len(e1['cambiate'])} cambiate")
    ok &= check("il motivo dice che è la prima volta",
                "prima volta" in (e1["nuove"][0]["motivo"] if e1["nuove"] else ""),
                e1["nuove"][0]["motivo"] if e1["nuove"] else "")
    ok &= check("i nomi inglesi del motore sono stati letti",
                e1["nuove"] and e1["nuove"][0]["punteggio"] == 86
                and e1["nuove"][0]["valore"] == 130.0 and e1["nuove"][0]["uscita"] == 90.0)
    ok &= check("lo stato è stato scritto su disco", stato.exists() and e1["salvato"])
    salvato = json.loads(stato.read_text(encoding="utf-8"))
    ok &= check("lo stato ricorda il punteggio annunciato",
                salvato["titoli"]["AMD"]["punteggio_annunciato"] == 86)
    ok &= check("nessun avviso al primo giro", not e1["avvisi"], str(e1["avvisi"]))
    # chi passa l'elenco completo invece dei soli candidati può far filtrare qui
    e1b = visti.novita([opportunita("LOW", punteggio=71, fascia="Da monitorare"),
                        opportunita("ALTO", punteggio=91, fascia="Opportunità eccezionale")],
                       path=cartella / "soglia.json", quando=T0,
                       soglia=visti.SOGLIA_PUNTEGGIO)
    ok &= check("con la soglia passata resta solo chi la supera",
                [n["ticker"] for n in e1b["nuove"]] == ["ALTO"],
                str([n["ticker"] for n in e1b["nuove"]]))

    print("\n2. Lo stesso titolo ai cicli dopo: nessuna notifica")
    e2 = visti.novita([opportunita()], path=stato, quando=T0 + timedelta(hours=2))
    ok &= check("niente da notificare con gli stessi numeri",
                not e2["nuove"] and not e2["cambiate"] and not e2["rinviate"])
    e3 = visti.novita([opportunita(punteggio=89)], path=stato,
                      quando=T0 + timedelta(hours=4))
    ok &= check("+3 punti nella stessa fascia sono rumore, non una notizia",
                not e3["nuove"] and not e3["cambiate"],
                f"nuove {len(e3['nuove'])}, cambiate {len(e3['cambiate'])}")
    ok &= check("e non è il riposo a fermarla, è la regola", not e3["rinviate"],
                str(e3["rinviate"]))
    # scelta esplicita: il punteggio che scende non manda niente. Questo è un
    # prodotto di segnalazioni, non un bollettino sulla salute di titoli che
    # l'utente non ha comprato (l'unica cattiva notizia che notifica è il
    # livello di uscita superato, provato al punto 5)
    stato_giu = cartella / "discesa.json"
    visti.novita([opportunita("INTC", punteggio=92, fascia="Opportunità eccezionale")],
                 path=stato_giu, quando=T0)
    e_giu = visti.novita([opportunita("INTC", punteggio=74, fascia="Da monitorare")],
                         path=stato_giu, quando=T0 + timedelta(hours=20))
    ok &= check("un crollo di 18 punti e due fasce in giù non manda messaggi",
                not e_giu["cambiate"] and not e_giu["rinviate"],
                str(e_giu["cambiate"] or e_giu["rinviate"]))

    print("\n3. Salto di fascia: secondo messaggio")
    e4 = visti.novita([opportunita(punteggio=92, fascia="Opportunità eccezionale")],
                      path=stato, quando=T0 + timedelta(hours=14))
    ok &= check("una modifica rilevante", len(e4["cambiate"]) == 1 and not e4["nuove"])
    ok &= check("il motivo cita la nuova fascia",
                "eccezionale" in (e4["cambiate"][0]["motivo"] if e4["cambiate"] else ""),
                e4["cambiate"][0]["motivo"] if e4["cambiate"] else "")
    ok &= check("il salto in fascia massima vale come urgente",
                e4["cambiate"] and e4["cambiate"][0]["urgente"])

    print("\n4. Periodo di riposo: due messaggi non si toccano")
    e5 = visti.novita([opportunita(punteggio=99, fascia="Opportunità eccezionale")],
                      path=stato, quando=T0 + timedelta(hours=16))
    ok &= check("+7 punti due ore dopo: rinviata, non inviata",
                not e5["cambiate"] and len(e5["rinviate"]) == 1,
                str(e5["rinviate"]))
    ok &= check("il log dice quanto manca",
                e5["rinviate"] and e5["rinviate"][0]["attesa_ore"] == 10.0,
                str(e5["rinviate"][0]["attesa_ore"]) if e5["rinviate"] else "")
    e6 = visti.novita([opportunita(punteggio=99, fascia="Opportunità eccezionale")],
                      path=stato, quando=T0 + timedelta(hours=27))
    ok &= check("passato il riposo la variazione accumulata esce",
                len(e6["cambiate"]) == 1,
                e6["cambiate"][0]["motivo"] if e6["cambiate"] else "")
    ok &= check("il confronto è con l'ultimo valore annunciato (92), non col ciclo prima",
                e6["cambiate"] and "da 92 a 99" in e6["cambiate"][0]["motivo"],
                e6["cambiate"][0]["motivo"] if e6["cambiate"] else "")

    print("\n5. Il riposo non copre i casi gravi")
    stato2 = cartella / "secondo.json"
    visti.novita([opportunita("NVDA", prezzo=100.0, uscita=90.0)], path=stato2, quando=T0)
    e7 = visti.novita([opportunita("NVDA", prezzo=89.0, uscita=90.0)], path=stato2,
                      quando=T0 + timedelta(hours=1))
    ok &= check("prezzo sotto il livello di uscita: passa sopra il riposo",
                len(e7["cambiate"]) == 1 and not e7["rinviate"],
                e7["cambiate"][0]["motivo"] if e7["cambiate"] else str(e7["rinviate"]))
    ok &= check("ed è marcato urgente", e7["cambiate"] and e7["cambiate"][0]["urgente"])
    e8 = visti.novita([opportunita("NVDA", prezzo=88.0, uscita=90.0)], path=stato2,
                      quando=T0 + timedelta(hours=3))
    ok &= check("ma lo dice una volta sola", not e8["cambiate"] and not e8["rinviate"],
                str(e8["cambiate"]))
    e9 = visti.novita([opportunita("NVDA", prezzo=135.0, valore=130.0)], path=stato2,
                      quando=T0 + timedelta(hours=40))
    ok &= check("prezzo oltre il valore stimato: un messaggio",
                len(e9["cambiate"]) == 1 and "valore stimato" in e9["cambiate"][0]["motivo"],
                e9["cambiate"][0]["motivo"] if e9["cambiate"] else "")

    print("\n6. Uscite dalla soglia: aggiornano lo stato, non notificano")
    e10 = visti.novita([], path=stato2, quando=T0 + timedelta(hours=42))
    ok &= check("il titolo scomparso risulta uscito", e10["uscite"] == ["NVDA"],
                str(e10["uscite"]))
    ok &= check("l'uscita non manda messaggi", not e10["nuove"] and not e10["cambiate"])
    e11 = visti.novita([opportunita("NVDA")], path=stato2, quando=T0 + timedelta(hours=44))
    ok &= check("il rientro subito dopo è tenuto a bada dal riposo",
                not e11["nuove"] and len(e11["rinviate"]) == 1,
                str(e11["rinviate"]))
    e12 = visti.novita([opportunita("NVDA")], path=stato2, quando=T0 + timedelta(hours=60))
    ok &= check("il rientro dopo il riposo è una novità",
                len(e12["nuove"]) == 1 and "torna sopra" in e12["nuove"][0]["motivo"],
                e12["nuove"][0]["motivo"] if e12["nuove"] else "")

    print("\n7. File di stato corrotto o impossibile: si ricomincia, dichiarandolo")
    stato.write_text("{questo non e' json", encoding="utf-8")
    e13 = visti.novita([opportunita(punteggio=99, fascia="Opportunità eccezionale")],
                       path=stato, quando=T0 + timedelta(hours=30))
    ok &= check("nessuna eccezione e il titolo torna nuovo", len(e13["nuove"]) == 1)
    ok &= check("l'avviso spiega che si potrebbero ripetere segnalazioni",
                any("illeggibile" in a for a in e13["avvisi"]), "; ".join(e13["avvisi"]))
    stato.write_text(json.dumps({"versione": 1, "titoli": "non un dizionario"}),
                     encoding="utf-8")
    e14 = visti.novita([opportunita()], path=stato, quando=T0 + timedelta(hours=32))
    ok &= check("uno stato con la forma sbagliata non fa cadere il ciclo",
                len(e14["nuove"]) == 1 and any("forma attesa" in a for a in e14["avvisi"]),
                "; ".join(e14["avvisi"]))
    e15 = visti.novita([opportunita()], path=cartella / "manca" / "stato.json",
                       quando=T0)
    ok &= check("una cartella inesistente: avvisa e non salva",
                not e15["salvato"] and any("non salvato" in a for a in e15["avvisi"]),
                "; ".join(e15["avvisi"]))
    ok &= check("dati spazzatura in ingresso non sollevano",
                visti.novita(None, path=stato2, quando=T0, scrivi=False)["nuove"] == []
                and visti.novita([{"niente": 1}, None, "AMD"], path=stato2, quando=T0,
                                 scrivi=False)["nuove"] == [])

    print("\n8. Il testo della notifica: una funzione sola, al massimo quattro righe")
    msg = channels.messaggio_opportunita(e4["cambiate"][0] if e4["cambiate"] else {})
    for riga in [msg["titolo"]] + msg["righe"]:
        print(f"      | {riga}")
    ok &= check("non più di quattro righe", len(msg["righe"]) <= channels.MAX_RIGHE,
                str(len(msg["righe"])))
    ok &= check("il titolo è corto e porta il punteggio",
                len(msg["titolo"]) <= 60 and "92/100" in msg["titolo"], msg["titolo"])
    corpo = msg["corpo"]
    ok &= check("ci sono nome, punteggio, prezzo e valore stimato",
                all(p in corpo for p in ("AMD", "92 su 100", "100,00", "130,00")))
    ok &= check("i numeri sono scritti all'italiana",
                channels._cifra(1234.5) == "1.234,50", channels._cifra(1234.5))
    ok &= check("c'è l'avvertenza e non ci sono promesse",
                "non è un consiglio" in corpo
                and not any(p in corpo.lower() for p in ("guadagn", "rendimento garant",
                                                         "sicuro", "comprare")))
    ok &= check("un motivo lunghissimo viene tagliato, non lasciato correre",
                len(channels.messaggio_opportunita(
                    {"ticker": "X", "punteggio": 90, "motivo": "parola " * 60}
                )["righe"][2]) < 170)
    ok &= check("un'opportunità senza numeri non fa cadere la formattazione",
                channels.messaggio_opportunita({"ticker": "Y"})["corpo"].count("n.d.") >= 1,
                channels.messaggio_opportunita({"ticker": "Y"})["corpo"].splitlines()[1])

    print("\n9. Push su ntfy: pubblicazione, intestazioni, errore 500")
    RICHIESTE.clear()
    installa_ntfy_finto("ok")
    push = channels.Push(topic="scout-" + "a" * 20, enabled=True)
    ok &= check("il canale è attivo", push.enabled and push.mode.startswith("attivo"),
                push.mode)
    ok &= check("il servizio risponde sano", push.health()["ok"])
    ok &= check("pubblicazione riuscita", push.send_message(msg) and push.sent == 1,
                str(push.errors))
    pubblicata = RICHIESTE[-1]
    ok &= check("POST sull'argomento giusto",
                pubblicata["metodo"] == "POST" and pubblicata["url"].endswith(push.topic),
                pubblicata["url"])
    ok &= check("il corpo è il testo della notifica", pubblicata["corpo"] == msg["corpo"])
    ok &= check("il titolo arriva con gli accenti giusti",
                pubblicata["titolo"].encode("latin-1").decode("utf-8") == msg["titolo"],
                pubblicata["titolo"].encode("latin-1").decode("utf-8"))
    ok &= check("priorità ed etichette sono nelle intestazioni",
                pubblicata["priorita"] == "high"
                and "warning" in (pubblicata["etichette"] or ""),
                f"{pubblicata['priorita']} / {pubblicata['etichette']}")
    ok &= check("un titolo con ritorni a capo non inietta intestazioni",
                "\n" not in channels._intestazione("Titolo\r\nX-Finta: 1")
                and "\r" not in channels._intestazione("Titolo\r\nX-Finta: 1"))
    installa_ntfy_finto("errore_500")
    prima = push.sent
    ok &= check("ntfy risponde 500: esito negativo, nessuna eccezione",
                push.send_message(msg) is False and push.sent == prima)
    ok &= check("l'errore è dichiarato nel log",
                push.errors and "HTTP 500" in push.errors[-1], str(push.errors[-1:]))
    installa_ntfy_finto("senza_id")
    ok &= check("un 200 senza identificativo non conta come inviato",
                push.send_message(msg) is False
                and "identificativo" in push.errors[-1])
    installa_ntfy_finto("salute_rotta")
    salute = push.health()
    ok &= check("rete che non risponde: esito negativo dichiarato",
                not salute["ok"] and "URLError" in salute["detail"], salute["detail"])
    spento = channels.Push(topic="", enabled=True)
    ok &= check("senza NTFY_TOPIC il canale è spento e lo dice",
                not spento.enabled and "NTFY_TOPIC" in spento.mode, spento.mode)
    ok &= check("un argomento corto viene segnalato come indovinabile",
                channels.Push(topic="borsa", enabled=True).avvisi(),
                "; ".join(channels.Push(topic="borsa", enabled=True).avvisi()))
    urllib.request.urlopen = VERO_URLOPEN

    print("\n10. Email senza variabili impostate: spenta, senza errori")
    vecchie = {k: os.environ.pop(k, None) for k in
               ("SMTP_HOST", "SMTP_PORT", "SMTP_USER", "SMTP_PASS", "SMTP_TO",
                "SMTP_FROM", "SMTP_STARTTLS")}
    try:
        vuota = channels.Email(enabled=True)
        ok &= check("spenta e dichiara che cosa manca",
                    not vuota.enabled and "SMTP_HOST" in vuota.mode, vuota.mode)
        ok &= check("l'invio restituisce un esito negativo senza sollevare",
                    vuota.send_message(msg) is False and not vuota.errors)
        os.environ.update({"SMTP_HOST": "smtp.gmail.com", "SMTP_USER": "io@gmail.com",
                           "SMTP_PASS": "x", "SMTP_TO": "io@gmail.com",
                           "SMTP_STARTTLS": "0"})
        remota = channels.Email(enabled=True)
        ok &= check("STARTTLS spento verso un server remoto: invio rifiutato",
                    remota.send_message(msg) is False
                    and "in chiaro" in remota.errors[-1], str(remota.errors[-1:]))
        ok &= check("le variabili d'ambiente vengono lette",
                    channels.Email(enabled=True).to == ["io@gmail.com"])
    finally:
        for k, v in vecchie.items():
            os.environ.pop(k, None)
            if v is not None:
                os.environ[k] = v

    print("\n11. Email contro un server SMTP finto su localhost: il messaggio parte")
    finto = ServerSmtpFinto().avvia()
    posta = channels.Email(host=finto.host, port=finto.port, user="scout@localhost",
                           password="password-per-le-app", to="io@localhost; altro@localhost",
                           starttls=False, enabled=True)
    inviato = posta.send_message(msg)
    chiuso = finto.chiudi()
    ok &= check("invio riuscito", inviato and posta.sent == 1, str(posta.errors))
    ok &= check("il server finto ha chiuso la conversazione", chiuso and not finto.errore,
                finto.errore or "")
    ok &= check("il server ha ricevuto un messaggio", len(finto.messaggi) == 1,
                f"{len(finto.messaggi)} messaggi, comandi: {finto.conversazione[:3]}")
    if finto.messaggi:
        ricevuto = finto.messaggi[0]
        letto = leggi_email(ricevuto["dati"])
        ok &= check("l'autenticazione è stata fatta",
                    any(c.upper().startswith("AUTH") for c in finto.conversazione))
        ok &= check("mittente e destinatari sono quelli configurati",
                    "scout@localhost" in ricevuto["mittente"]
                    and len(ricevuto["destinatari"]) == 2,
                    f"{ricevuto['mittente']} -> {ricevuto['destinatari']}")
        ok &= check("l'oggetto è il titolo della notifica",
                    str(letto["Subject"]) == msg["titolo"], str(letto["Subject"]))
        # SMTP impone il ritorno a capo in due caratteri: si normalizza prima di
        # confrontare, altrimenti si confronterebbe il protocollo, non il testo
        testo = letto.get_content().replace("\r\n", "\n")
        ok &= check("il corpo ricevuto è identico a quello scritto",
                    testo.strip() == msg["corpo"].strip(),
                    repr(testo.strip()[:80]))
        ok &= check("gli accenti sono sopravvissuti al trasporto",
                    "Perché" in testo and "non è un consiglio" in testo)
        print(f"      | oggetto: {letto['Subject']}")
        print(f"      | a: {letto['To']}")

    print("\n12. Consegna su più canali: uno che cade non ferma gli altri")
    finto2 = ServerSmtpFinto().avvia()
    posta2 = channels.Email(host=finto2.host, port=finto2.port, user="scout@localhost",
                            password="x", to="io@localhost", starttls=False, enabled=True)
    installa_ntfy_finto("errore_500")
    push2 = channels.Push(topic="scout-" + "b" * 20, enabled=True)
    esito = channels.consegna(msg, {"push": push2, "email": posta2,
                                    "telegram": channels.Telegram()})
    finto2.chiudi()
    urllib.request.urlopen = VERO_URLOPEN
    ok &= check("consegnato perché l'email ha funzionato", esito["consegnato"])
    ok &= check("il push risulta fallito con il motivo",
                not esito["esiti"]["push"]["inviato"]
                and "500" in esito["esiti"]["push"]["dettaglio"],
                esito["esiti"]["push"]["dettaglio"])
    ok &= check("il canale spento è dichiarato spento",
                not esito["esiti"]["telegram"]["inviato"]
                and "spento" in esito["esiti"]["telegram"]["dettaglio"],
                esito["esiti"]["telegram"]["dettaglio"])

    class CanaleRotto:
        enabled = True
        errors: list[str] = []

        def send_message(self, m):
            raise RuntimeError("canale scritto male")

    esito2 = channels.consegna(msg, {"rotto": CanaleRotto()})
    ok &= check("un canale che solleva non arriva al ciclo di scansione",
                not esito2["consegnato"]
                and "canale scritto male" in esito2["esiti"]["rotto"]["dettaglio"],
                esito2["esiti"]["rotto"]["dettaglio"])

    print("\n13. Dodici cicli in un giorno: quante notifiche arrivano davvero")
    stato3 = cartella / "giornata.json"
    inviate = 0
    for i in range(12):
        # sei titoli stabili sopra soglia, il caso normale: la prima scansione
        # notifica, le altre undici devono tacere
        lista = [opportunita(f"T{n}", punteggio=86 + n) for n in range(6)]
        e = visti.novita(lista, path=stato3, quando=T0 + timedelta(hours=2 * i))
        inviate += len(e["nuove"]) + len(e["cambiate"])
    ok &= check("sei notifiche in tutto, non settantadue", inviate == 6, str(inviate))
    ok &= check("la riga di riassunto è leggibile", "novità" in visti.riassunto(e4),
                visti.riassunto(e4))

    if con_rete:
        print("\n14. Prova vera su ntfy.sh (richiesta con --rete)")
        argomento = "scout-prova-" + secrets.token_hex(10)
        vero = channels.Push(topic=argomento, enabled=True)
        salute = vero.health()
        ok &= check("il servizio risponde", salute["ok"], salute["detail"])
        ok &= check("pubblicazione reale", vero.send_message(msg), str(vero.errors))
        time.sleep(2.0)
        try:
            with VERO_URLOPEN(f"{vero.server}/{argomento}/json?poll=1", timeout=20) as r:
                righe = [json.loads(l) for l in r.read().decode("utf-8").splitlines() if l]
        except Exception as e:
            righe = []
            print(f"      rilettura non riuscita: {type(e).__name__}: {e}")
        ok &= check("il messaggio si rilegge dal server",
                    any(x.get("message") == msg["corpo"] and x.get("title") == msg["titolo"]
                        for x in righe),
                    f"{len(righe)} messaggi riletti su {argomento}")
    else:
        print("\n(prova vera su ntfy.sh non eseguita: aggiunga --rete per farla)")

    print("\n" + ("Tutti i controlli superati." if ok else "ALCUNI CONTROLLI FALLITI."))
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
