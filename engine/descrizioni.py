"""Che cosa fa ogni strumento, in una frase.

PERCHE' ESISTE QUESTO FILE. La pagina mostra sotto il nome una riga che
dovrebbe dire di che si occupa quell'azienda, o che cosa contiene quel
paniere. Quando la frase manca, il programma ripiega su nome e settore -
"Consumer Staples Select, consumer." - che non dice niente a nessuno. Con 48
strumenti le descrizioni scritte bastavano; passando a 224 ne mancavano 176, e
la riga più letta della card era diventata la meno utile.

COME SONO SCRITTE. Una frase, concreta, in italiano, su che cosa fa l'azienda
o che cosa contiene lo strumento. NON spiegano che cos'e' un'azione o un ETF:
quello lo dicono la riga sotto il nome e i dati sul retro, e ripeterlo su ogni
card era proprio il rumore da togliere. Niente giudizi, niente aggettivi di
valore: "la più grande catena di supermercati del mondo" e' un fatto, "una
grande opportunita'" sarebbe un'opinione travestita da descrizione.

Il mercato non si scrive qui: lo aggiunge plain.py, che lo sa dai dati.
"""
from __future__ import annotations

DESCRIZIONI: dict[str, str] = {
    # ---- azioni USA: tecnologia e semiconduttori ------------------------
    "AVGO": "Chip per reti e centri dati, e software per grandi aziende.",
    "ORCL": "Banche dati e servizi cloud su cui girano i gestionali delle aziende.",
    "CRM": "Software in abbonamento per gestire clienti, vendite e assistenza.",
    "ADBE": "Gli strumenti con cui si creano immagini, video e documenti: "
            "Photoshop, Acrobat, Premiere.",
    "AMZN": "Il più grande negozio online del mondo; con AWS affitta anche "
            "potenza di calcolo a mezza internet.",
    "NFLX": "Abbonamenti per film e serie, che in buona parte produce in proprio.",
    "INTC": "Progetta e fabbrica processori per computer e server.",
    "MU": "Memorie: i chip dove i dati stanno mentre vengono usati.",
    "QCOM": "I chip e i brevetti che fanno collegare i telefoni alla rete mobile.",
    "TXN": "Chip semplici e diffusissimi, dentro automobili, elettrodomestici e "
           "macchinari.",
    "AMAT": "I macchinari con cui le fabbriche di chip costruiscono i chip.",
    "LRCX": "Macchinari che incidono i circuiti sulle lastre di silicio.",
    "KLAC": "Strumenti che cercano i difetti durante la produzione dei chip.",
    "PLTR": "Software per analizzare grandi quantità di dati, usato da governi "
            "e grandi aziende.",
    "NOW": "Software che automatizza i processi interni delle aziende, dalle "
           "richieste informatiche al personale.",
    "IBM": "Informatica per grandi organizzazioni: consulenza, cloud e i computer "
           "centrali delle banche.",
    "CSCO": "Gli apparati che tengono in piedi le reti: router, switch, sicurezza.",
    "ACN": "Consulenza e progetti informatici su commessa per grandi aziende.",
    "UBER": "L'applicazione per le corse in auto e le consegne di cibo.",
    "TSLA": "Automobili elettriche, batterie e impianti solari.",

    # ---- azioni USA: finanza -------------------------------------------
    "BAC": "Conti, prestiti e carte per famiglie e imprese americane.",
    "WFC": "Banca americana: mutui, conti correnti e prestiti alle imprese.",
    "GS": "Banca d'investimento: consiglia le grandi operazioni societarie e "
          "opera sui mercati.",
    "MS": "Banca d'investimento e gestione dei patrimoni dei clienti ricchi.",
    "BLK": "Il più grande gestore di risparmio al mondo; sono suoi i fondi iShares.",
    "V": "Il circuito su cui viaggiano i pagamenti con carta: guadagna una "
         "commissione su ogni transazione.",
    "MA": "L'altro grande circuito dei pagamenti con carta.",
    "AXP": "Carte di credito, e insieme la banca che le emette e fa credito.",
    "BRK-B": "La holding di Warren Buffett: assicurazioni, ferrovie, energia e "
             "partecipazioni in altre aziende.",
    "SCHW": "Intermediario per investire in borsa, e banca per i suoi clienti.",

    # ---- azioni USA: salute --------------------------------------------
    "JNJ": "Farmaci e dispositivi medici, dagli impianti ortopedici alla chirurgia.",
    "PFE": "Farmaci e vaccini.",
    "MRK": "Farmaci, in particolare per la cura dei tumori.",
    "ABBV": "Farmaci, soprattutto per le malattie del sistema immunitario.",
    "TMO": "Strumenti e reagenti con cui lavorano i laboratori di ricerca e analisi.",
    "ABT": "Diagnostica, dispositivi medici e alimentazione per l'infanzia.",
    "AMGN": "Farmaci biotecnologici, prodotti da cellule invece che per sintesi "
            "chimica.",
    "ISRG": "I robot con cui i chirurghi operano attraverso piccole incisioni.",
    "VRTX": "Farmaci per la fibrosi cistica e altre malattie genetiche rare.",

    # ---- azioni USA: energia e utility ----------------------------------
    "CVX": "Estrae, raffina e vende petrolio e gas.",
    "COP": "Estrazione di petrolio e gas, senza raffinerie.",
    "SLB": "Servizi e tecnologia per chi estrae petrolio: perforazione, misure, "
           "manutenzione dei pozzi.",
    "NEE": "Elettricità in Florida, e il più grande produttore americano da "
           "vento e sole.",
    "DUK": "Elettricità e gas per il sud-est degli Stati Uniti.",
    "SO": "Elettricità per il sud degli Stati Uniti, nucleare compreso.",

    # ---- azioni USA: industria e difesa ---------------------------------
    "BA": "Aerei di linea e sistemi per la difesa.",
    "LMT": "Aerei militari, missili e satelliti, quasi tutto per governi.",
    "RTX": "Motori d'aereo, missili e radar.",
    "GE": "Motori per aerei di linea, e la manutenzione che costa più del motore.",
    "HON": "Automazione industriale, strumenti di bordo per aerei e sensori.",
    "UNP": "La rete ferroviaria merci dell'ovest degli Stati Uniti.",
    "DE": "Trattori e macchine agricole, sempre più guidate dai dati.",
    "MMM": "Adesivi, abrasivi e materiali industriali; sono suoi i Post-it.",

    # ---- azioni USA: consumo e comunicazione ----------------------------
    "PG": "Detersivi e prodotti per la casa e la persona: Dash, Gillette, Pampers.",
    "PEP": "Bibite e snack salati: Pepsi, Gatorade, Doritos.",
    "COST": "Magazzini all'ingrosso dove si entra con l'abbonamento: guadagna "
            "più dalle tessere che dai prodotti.",
    "WMT": "La più grande catena di supermercati del mondo.",
    "MCD": "La catena di ristoranti, quasi tutta gestita da affiliati: incassa "
           "royalty e affitti.",
    "NKE": "Scarpe e abbigliamento sportivo.",
    "SBUX": "La catena di caffetterie.",
    "HD": "La catena per il fai-da-te e l'edilizia.",
    "DIS": "Film, parchi a tema, televisione e lo streaming Disney+.",
    "T": "Rete telefonica e internet di casa negli Stati Uniti.",
    "VZ": "L'altro grande operatore telefonico americano.",

    # ---- azioni USA: materiali ------------------------------------------
    "LIN": "Gas industriali: ossigeno per gli ospedali, azoto e idrogeno per "
           "l'industria.",
    "FCX": "Miniere di rame, il metallo che serve a elettrificare tutto, e di oro.",
    "NEM": "La più grande società mineraria d'oro al mondo.",

    # ---- azioni europee -------------------------------------------------
    "SHELL.AS": "Petrolio, gas e carburanti, dalla ricerca al distributore.",
    "TTE.PA": "Petrolio, gas ed elettricità, con una parte crescente da "
              "rinnovabili.",
    "OR.PA": "Cosmetici: il più grande gruppo di bellezza al mondo.",
    "SAN.PA": "Farmaci e vaccini.",
    "BNP.PA": "La più grande banca francese, presente in tutta Europa.",
    "CS.PA": "Assicurazioni su vita, danni e salute.",
    "DG.PA": "Costruisce e poi gestisce autostrade e aeroporti, incassando i pedaggi.",
    "SU.PA": "Apparecchiature e software per distribuire e gestire l'energia "
             "elettrica negli edifici e nelle fabbriche.",
    "RMS.PA": "Pelletteria e moda di lusso, con produzione volutamente limitata.",
    "AI.PA": "Gas industriali e medicali, spesso forniti con impianti dentro la "
             "fabbrica del cliente.",
    "EL.PA": "Lenti e montature da vista: possiede sia i marchi sia i negozi.",
    "SAF.PA": "Motori d'aereo, in società con GE, e attrezzature per l'aviazione.",
    "ALV.DE": "Assicurazioni e gestione del risparmio.",
    "DTE.DE": "Telefonia in Germania, e proprietaria di T-Mobile negli Stati Uniti.",
    "MBG.DE": "Automobili e furgoni Mercedes-Benz.",
    "BMW.DE": "Automobili e motociclette BMW e Mini.",
    "VOW3.DE": "Automobili: Volkswagen, Audi, Porsche, Skoda, Seat.",
    "BAS.DE": "La più grande azienda chimica del mondo: materie prime per quasi "
              "ogni industria.",
    "MRK.DE": "Farmaci, materiali per l'elettronica e strumenti di laboratorio.",
    "RHM.DE": "Veicoli militari, munizioni e sistemi di difesa.",
    "ADS.DE": "Scarpe e abbigliamento sportivo Adidas.",
    "DB1.DE": "Gestisce la borsa di Francoforte e i mercati dei derivati: guadagna "
              "sugli scambi, non sui prezzi.",
    "IFX.DE": "Chip per automobili e per la gestione efficiente dell'energia.",
    "ITX.MC": "Zara e le altre catene di abbigliamento del gruppo Inditex.",
    "SAN.MC": "Banca spagnola, con gran parte degli utili in America Latina.",
    "IBE.MC": "Elettricità in Spagna, Regno Unito e America, molto da rinnovabili.",
    "NESN.SW": "Alimentari: caffè Nespresso, acque minerali, cibo per animali.",
    "NOVN.SW": "Farmaci, dopo aver separato la parte dei generici.",
    "RHHBY": "Farmaci contro i tumori e diagnostica di laboratorio.",
    "UBSG.SW": "Banca svizzera: gestisce i patrimoni dei grandi clienti di mezzo "
               "mondo.",
    "ABBN.SW": "Robot industriali, motori elettrici e apparecchiature per "
               "l'elettricità.",
    "ENI.MI": "Petrolio, gas ed energia, dalla ricerca alla vendita.",
    "UCG.MI": "Banca italiana con una rete estesa in Germania e in Europa centrale.",
    "STM": "Chip per automobili, industria ed elettronica di consumo.",
    "PRY.MI": "Cavi per l'energia e le telecomunicazioni, compresi quelli posati "
              "in fondo al mare.",
    "ASM.AS": "Macchinari che depositano gli strati sottilissimi di cui sono fatti "
              "i chip.",
    "ADYEN.AS": "L'infrastruttura con cui negozi e siti incassano i pagamenti in "
                "tutto il mondo.",
    "INGA.AS": "Banca olandese, nata e cresciuta soprattutto online.",
    "AD.AS": "Supermercati in Europa e negli Stati Uniti, fra cui Albert Heijn.",
    "PHIA.AS": "Apparecchiature mediche per immagini e diagnosi, dalle TAC agli "
               "ecografi.",
    "EQNR.OL": "Petrolio e gas norvegesi, e grandi parchi eolici in mare.",
    "VOLV-B.ST": "Camion, autobus e mezzi da cantiere.",
    "ATCO-A.ST": "Compressori d'aria, pompe e utensili per l'industria.",
    "ERIC-B.ST": "Gli apparati con cui gli operatori costruiscono le reti mobili.",
    "SAND.ST": "Utensili da taglio per le officine e macchine per le miniere.",
    "NOKIA.HE": "Apparati per le reti telefoniche, e un grande portafoglio di "
                "brevetti.",
    "MAERSK-B.CO": "Trasporto marittimo di container e logistica: il "
                   "termometro del commercio mondiale.",

    # ---- azioni asiatiche ----------------------------------------------
    "6758.T": "PlayStation, sensori per fotocamere, musica e film.",
    "8306.T": "La più grande banca giapponese.",
    "6861.T": "Sensori e sistemi di controllo per le fabbriche automatizzate.",
    "6902.T": "Componenti per automobili, dai sistemi di iniezione ai sensori.",
    "4063.T": "Silicio e prodotti chimici speciali per fabbricare i chip.",
    "7974.T": "Console e videogiochi: Mario, Zelda, Pokémon.",
    "9433.T": "Telefonia mobile e servizi internet in Giappone.",
    "8035.T": "Macchinari per produrre i chip, fra i pochi al mondo a saperli fare.",
    "000660.KS": "Memorie per computer e per i centri dati dell'intelligenza "
                 "artificiale.",
    "0700.HK": "WeChat, videogiochi e pagamenti: l'applicazione da cui passa "
               "mezza vita digitale cinese.",
    "9988.HK": "Commercio online e servizi cloud in Cina.",
    "1299.HK": "Assicurazioni vita in tutta l'Asia.",
    "3690.HK": "L'applicazione cinese per le consegne di cibo e i servizi di "
               "quartiere.",
    "INFY": "Servizi informatici su commessa, con i tecnici in India e i clienti "
            "in Occidente.",
    "HDB": "La più grande banca privata indiana.",

    # ---- panieri (ETF): aree geografiche --------------------------------
    "VTI": "Tutta la borsa americana in un paniere solo, dalle grandissime alle "
           "piccole.",
    "IWM": "Le duemila società americane più piccole: più mosse, più rischio.",
    "EFA": "Azioni dei paesi sviluppati fuori da Stati Uniti e Canada.",
    "VGK": "Azioni delle grandi società europee.",
    "EWJ": "Azioni giapponesi.",
    "INDA": "Azioni indiane.",
    "MCHI": "Azioni cinesi.",
    "EUNL.DE": "Le azioni di tutti i paesi sviluppati in un paniere, con dentro "
               "più di millecinquecento società.",
    "SXR8.DE": "Le cinquecento maggiori società americane.",
    "IS3N.DE": "Azioni dei paesi emergenti, Cina, India e Taiwan in testa.",

    # ---- panieri (ETF): settori ----------------------------------------
    "XLF": "Le banche e le assicurazioni americane.",
    "XLE": "Le società americane del petrolio e del gas.",
    "XLV": "La sanità americana: farmaci, assicurazioni mediche, ospedali.",
    "XLK": "La tecnologia americana, con le grandissime che pesano molto.",
    "XLI": "L'industria americana: trasporti, macchinari, difesa.",
    "XLP": "I beni che si comprano sempre: cibo, detersivi, bevande.",
    "XLU": "Le società americane dell'elettricità e dell'acqua.",
    "XLB": "Chimica, metalli e materiali da costruzione americani.",
    "XBI": "Le biotecnologie americane, molte piccole e senza farmaci ancora in "
           "vendita.",
    "ICLN": "Energie rinnovabili nel mondo: solare, vento, idrogeno.",
    "ARKK": "Società tecnologiche in forte crescita, scelte una per una dal "
            "gestore invece che da un indice.",
    "GDX": "Le società che estraggono oro, che si muovono più dell'oro stesso.",
    "ITA": "Aerospazio e difesa americani.",

    # ---- obbligazionari ------------------------------------------------
    "SHY": "Titoli di stato americani che scadono fra uno e tre anni: poco "
           "sensibili ai tassi.",
    "TIP": "Titoli di stato americani il cui valore sale con l'inflazione.",
    "HYG": "Obbligazioni di aziende con giudizio di credito basso: rendono di "
           "più perché rischiano di più.",
    "AGG": "Quasi tutto il debito americano di buona qualità in un paniere: "
           "stato, agenzie, imprese.",
    "BND": "Come AGG: l'intero mercato obbligazionario americano di qualità.",
    "IEGA.AS": "Titoli di stato dei paesi che usano l'euro.",

    # ---- cripto --------------------------------------------------------
    "XRP-USD": "Moneta digitale pensata per far viaggiare pagamenti fra "
               "istituzioni.",
    "ADA-USD": "Moneta digitale con una sua rete per far girare contratti "
               "automatici.",
    "AVAX-USD": "Rete per contratti automatici, costruita per essere veloce ed "
                "economica.",
    "DOT-USD": "Rete pensata per far comunicare fra loro catene diverse.",
    "LTC-USD": "Una delle prime monete digitali, nata come versione più rapida "
               "di Bitcoin.",
    "DOGE-USD": "Moneta digitale nata per scherzo, il cui prezzo dipende quasi "
                "solo dall'umore del pubblico.",

    # ---- materie prime -------------------------------------------------
    "NG=F": "Gas naturale: riscalda le case e alimenta molte centrali elettriche.",
    "PL=F": "Platino: marmitte catalitiche, industria chimica, gioielleria.",
    "PA=F": "Palladio: serve soprattutto alle marmitte delle auto a benzina.",
    "ZC=F": "Mais: mangime per animali, alimenti e biocarburanti.",
    "ZW=F": "Grano: la materia prima del pane e della pasta.",
    "KC=F": "Caffè: il prezzo dipende dal clima in Brasile e Vietnam.",

    # ---- immobiliare ---------------------------------------------------
    "O": "Affitta negozi e magazzini con contratti molto lunghi, e distribuisce "
         "l'affitto ogni mese.",
    "AMT": "Possiede le torri su cui gli operatori telefonici montano le antenne, "
           "e le affitta.",
    "EQIX": "Centri dati dove le aziende mettono i propri server e si collegano "
            "fra loro.",
    "WELL": "Residenze per anziani e strutture sanitarie, date in gestione a "
            "operatori.",
    "PSA": "Magazzini self storage, affittati a privati e piccole imprese.",
    "DLR": "Centri dati su grande scala, affittati soprattutto alle aziende del "
           "cloud.",
}
