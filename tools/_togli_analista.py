"""Rimuove la vista analista: non la usa nessuno, e il codice morto e' un
debito. Resta solo la pagina delle opportunita'.

Taglia per intervalli di righe fra funzioni, verificando ogni volta che il
nome rimosso non sia piu' usato da nessuna parte. Script temporaneo.
"""
import pathlib
import re

p = pathlib.Path("web/app.js")
testo = p.read_text(encoding="utf-8")
righe = testo.splitlines(keepends=True)


def indice_funzione(nome: str) -> int:
    for i, r in enumerate(righe):
        if r.startswith(f"function {nome}(") or r.startswith(f"const {nome} ="):
            return i
    raise LookupError(nome)


# Blocchi contigui da togliere: (prima funzione del blocco, prima funzione che RESTA)
BLOCCHI = [
    # tutte le viste tecniche, dal nav fino al drawer compreso
    ("renderNav", "pack"),
    # la conversazione con l'agente: tolta dalla specifica
    ("renderBubble", "altezzaCard"),
]

for primo, dopo in BLOCCHI:
    i = indice_funzione(primo)
    j = indice_funzione(dopo)
    # si risale al commento-banner che precede il blocco, se c'e'
    k = i
    while k > 0 and (righe[k - 1].startswith("/* -") or righe[k - 1].startswith("/* =")
                     or righe[k - 1].strip() == ""):
        k -= 1
    print(f"  taglio {primo} .. (prima di {dopo}): righe {k + 1}-{j}")
    del righe[k:j]

testo = "".join(righe)

# --- render(): una vista sola, niente modalita' -----------------------------
vecchio_render = testo[testo.index("const RENDERERS = {"):testo.index("function boot() {")]
nuovo_render = '''/* Una vista sola. La vista analista e' stata rimossa: non la usava nessuno, e
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

'''
testo = testo.replace(vecchio_render, nuovo_render)

# saveMode non serve piu'
testo = testo.replace(
    "function saveMode() { localStorage.setItem('ams-mode', state.mode); }\n\n", "")
testo = re.sub(r"\n *saveMode\(\);", "", testo)

p.write_text(testo, encoding="utf-8")
print("fatto. righe ora:", len(testo.splitlines()))

# --- chi e' rimasto orfano? ------------------------------------------------
nomi = re.findall(r"^function (\w+)\(", testo, re.M)
orfani = [n for n in nomi
          if len(re.findall(r"\b" + n + r"\b", testo)) == 1]
print("funzioni definite ma non piu' usate:", ", ".join(orfani) or "nessuna")
