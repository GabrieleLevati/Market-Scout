"""Universo investibile costruito sui dati veri.

Produce esattamente la stessa forma di dati di `universe.load_universe()`, così
tutto il resto del motore — indicatori, agenti, scoring, trigger, notifiche,
vista cliente — non cambia di una riga. È la cucitura prevista dall'FDD: cambia
il provider, non il sistema.

Che cosa è reale e che cosa manca, per ogni asset, sta in `data_quality` e viene
mostrato a schermo. Senza un contratto dati a pagamento non sono disponibili:

* operazioni degli insider (serve Finnhub o simili) -> trigger disattivato;
* bilanci di ETF, obbligazioni, crypto e materie prime -> nessuna stima di
  valore, quindi l'asset viene monitorato ma non proposto;
* la polarità delle notizie, che qui non è un dato ma un giudizio: la produce
  Gemini (con `--live`), altrimenti il sentiment resta neutro e lo dice.
"""

from __future__ import annotations

from datetime import date

from .indicators import snapshot
from .providers import DataError, Yahoo, derive_fundamentals, statement_currency
from .universe import CLASS_IN_WORDS, DESCRIPTIONS, FX_TO_EUR
from .valuation import fair_value, peer_stats

# simbolo Yahoo, nome, asset class, mercato, settore, dimensione, query per le news
#
# COME SI SCEGLIE COSA METTERE QUI, perche' non e' solo "aggiungere nomi".
#
# 1. MERCATO solo fra USA / Europa / Asia / Global, e DIMENSIONE solo fra Mega,
#    Large, Mid, Small cap. Non e' una limitazione del motore: la pagina
#    costruisce frasi in italiano da questi due campi ("azione di un'impresa
#    grandissima americana"), e un valore fuori tabella produce una frase
#    sgrammaticata o mutila. Il settore invece si scrive libero: viene
#    stampato come sta scritto qui.
#
# 2. NIENTE LISTINO DI LONDRA (.L). Yahoo dichiara molte quotazioni di Londra
#    in "GBp", cioe' PENNY, non sterline. Il cambio verso euro si chiede come
#    "GBpEUR=X", che non esiste: la conversione ricadrebbe su 1.0 e il prezzo
#    in euro sarebbe sbagliato di cento volte, senza che niente segnali
#    l'errore. Per i nomi britannici si usa la quotazione americana (ADR), che
#    e' in dollari e si converte bene.
#
# 3. SERVONO ALMENO 260 SEDUTE di storia (MIN_BARS): un titolo quotato da
#    pochi mesi viene scartato con il suo motivo, non e' un guasto.
#
# 4. NON C'E' GENERALI, e non e' una dimenticanza. Chi lavora in una societa'
#    quotata ha di norma vincoli sull'operare in azioni del proprio datore di
#    lavoro, e uno strumento che emette segnali d'acquisto su quel titolo
#    metterebbe chi lo usa in una posizione scomoda per primo. Se un giorno
#    servisse, e' una decisione da prendere con la compliance, non qui.
REAL_SPECS = [
    ("AMD", "Advanced Micro Devices", "Azioni", "USA", "AI", "Large cap", "AMD"),
    ("MSFT", "Microsoft", "Azioni", "USA", "Tecnologia", "Mega cap", "Microsoft"),
    ("NVDA", "NVIDIA", "Azioni", "USA", "AI", "Mega cap", "Nvidia"),
    ("GOOGL", "Alphabet", "Azioni", "USA", "Tecnologia", "Mega cap", "Alphabet Google"),
    ("META", "Meta Platforms", "Azioni", "USA", "Tecnologia", "Mega cap", "Meta Platforms"),
    ("AAPL", "Apple", "Azioni", "USA", "Tecnologia", "Mega cap", "Apple"),
    ("JPM", "JPMorgan Chase", "Azioni", "USA", "Finanza", "Mega cap", "JPMorgan"),
    ("UNH", "UnitedHealth", "Azioni", "USA", "Healthcare", "Large cap", "UnitedHealth"),
    ("LLY", "Eli Lilly", "Azioni", "USA", "Healthcare", "Mega cap", "Eli Lilly"),
    ("XOM", "Exxon Mobil", "Azioni", "USA", "Energia", "Mega cap", "Exxon Mobil"),
    ("CAT", "Caterpillar", "Azioni", "USA", "Industriale", "Large cap", "Caterpillar"),
    ("KO", "Coca-Cola", "Azioni", "USA", "Consumer", "Mega cap", "Coca-Cola"),
    ("ASML.AS", "ASML Holding", "Azioni", "Europa", "AI", "Mega cap", "ASML"),
    ("SAP.DE", "SAP", "Azioni", "Europa", "Tecnologia", "Large cap", "SAP SE"),
    ("NOVO-B.CO", "Novo Nordisk", "Azioni", "Europa", "Healthcare", "Large cap", "Novo Nordisk"),
    ("MC.PA", "LVMH", "Azioni", "Europa", "Consumer", "Large cap", "LVMH"),
    ("SIE.DE", "Siemens", "Azioni", "Europa", "Industriale", "Large cap", "Siemens AG"),
    ("AIR.PA", "Airbus", "Azioni", "Europa", "Industriale", "Large cap", "Airbus"),
    ("ENEL.MI", "Enel", "Azioni", "Europa", "Energia", "Large cap", "Enel SpA"),
    ("ISP.MI", "Intesa Sanpaolo", "Azioni", "Europa", "Finanza", "Large cap", "Intesa Sanpaolo"),
    ("STLAM.MI", "Stellantis", "Azioni", "Europa", "Consumer", "Mid cap", "Stellantis"),
    ("TSM", "TSMC (ADR)", "Azioni", "Asia", "AI", "Mega cap", "TSMC"),
    ("7203.T", "Toyota Motor", "Azioni", "Asia", "Consumer", "Large cap", "Toyota Motor"),
    ("9984.T", "SoftBank Group", "Azioni", "Asia", "Tecnologia", "Large cap", "SoftBank Group"),
    ("005930.KS", "Samsung Electronics", "Azioni", "Asia", "Tecnologia", "Mega cap",
     "Samsung Electronics"),
    ("SPY", "SPDR S&P 500 ETF", "ETF", "USA", "Diversificato", "ETF", "S&P 500 ETF"),
    ("QQQ", "Invesco QQQ Trust", "ETF", "USA", "Tecnologia", "ETF", "Nasdaq 100 ETF"),
    ("VWCE.DE", "Vanguard FTSE All-World", "ETF", "Global", "Diversificato", "ETF",
     "Vanguard FTSE All-World"),
    ("EXS1.DE", "iShares Core DAX", "ETF", "Europa", "Diversificato", "ETF", "DAX ETF"),
    ("SMH", "VanEck Semiconductor ETF", "ETF", "Global", "AI", "ETF", "semiconductor ETF"),
    ("EEM", "iShares MSCI Emerging Markets", "ETF", "Asia", "Diversificato", "ETF",
     "emerging markets ETF"),
    ("IEF", "iShares 7-10Y Treasury", "Obbligazioni", "USA", "Obbligazionario", "Governativo",
     "Treasury bond ETF"),
    ("TLT", "iShares 20+Y Treasury", "Obbligazioni", "USA", "Obbligazionario", "Governativo",
     "long Treasury ETF"),
    ("LQD", "iShares USD Investment Grade", "Obbligazioni", "USA", "Obbligazionario",
     "Corporate IG", "investment grade bond ETF"),
    ("IEAC.AS", "iShares Core Euro Corp Bond", "Obbligazioni", "Europa", "Obbligazionario",
     "Corporate IG", "euro corporate bond ETF"),
    ("EMB", "iShares JPM USD EM Bond", "Obbligazioni", "Global", "Obbligazionario", "Emerging",
     "emerging market bond ETF"),
    ("BTC-USD", "Bitcoin", "Crypto", "Global", "Crypto", "Large cap", "Bitcoin"),
    ("ETH-USD", "Ethereum", "Crypto", "Global", "Crypto", "Large cap", "Ethereum"),
    ("SOL-USD", "Solana", "Crypto", "Global", "Crypto", "Mid cap", "Solana"),
    ("LINK-USD", "Chainlink", "Crypto", "Global", "Crypto", "Mid cap", "Chainlink"),
    ("GC=F", "Oro (future)", "Commodities", "Global", "Materie prime", "Metalli preziosi",
     "gold price"),
    ("SI=F", "Argento (future)", "Commodities", "Global", "Materie prime", "Metalli preziosi",
     "silver price"),
    ("CL=F", "Petrolio WTI (future)", "Commodities", "Global", "Materie prime", "Energia",
     "crude oil price"),
    ("HG=F", "Rame (future)", "Commodities", "Global", "Materie prime", "Metalli industriali",
     "copper price"),
    ("PLD", "Prologis", "REIT", "USA", "Immobiliare", "Logistica", "Prologis"),
    ("SPG", "Simon Property Group", "REIT", "USA", "Immobiliare", "Retail", "Simon Property"),
    ("VNA.DE", "Vonovia", "REIT", "Europa", "Immobiliare", "Residenziale", "Vonovia"),
    ("0823.HK", "Link REIT", "REIT", "Asia", "Immobiliare", "Retail", "Link REIT"),

    # ---- allargamento: azioni USA -------------------------------------------
    ("AVGO", "Broadcom", "Azioni", "USA", "AI", "Mega cap", "Broadcom"),
    ("ORCL", "Oracle", "Azioni", "USA", "Tecnologia", "Mega cap", "Oracle"),
    ("CRM", "Salesforce", "Azioni", "USA", "Tecnologia", "Large cap", "Salesforce"),
    ("ADBE", "Adobe", "Azioni", "USA", "Tecnologia", "Large cap", "Adobe"),
    ("AMZN", "Amazon", "Azioni", "USA", "Consumer", "Mega cap", "Amazon"),
    ("NFLX", "Netflix", "Azioni", "USA", "Comunicazione", "Large cap", "Netflix"),
    ("INTC", "Intel", "Azioni", "USA", "AI", "Large cap", "Intel"),
    ("MU", "Micron Technology", "Azioni", "USA", "AI", "Large cap", "Micron"),
    ("QCOM", "Qualcomm", "Azioni", "USA", "AI", "Large cap", "Qualcomm"),
    ("TXN", "Texas Instruments", "Azioni", "USA", "AI", "Large cap", "Texas Instruments"),
    ("AMAT", "Applied Materials", "Azioni", "USA", "AI", "Large cap", "Applied Materials"),
    ("LRCX", "Lam Research", "Azioni", "USA", "AI", "Large cap", "Lam Research"),
    ("KLAC", "KLA Corporation", "Azioni", "USA", "AI", "Large cap", "KLA Corp"),
    ("PLTR", "Palantir Technologies", "Azioni", "USA", "AI", "Large cap", "Palantir"),
    ("NOW", "ServiceNow", "Azioni", "USA", "Tecnologia", "Large cap", "ServiceNow"),
    ("IBM", "IBM", "Azioni", "USA", "Tecnologia", "Large cap", "IBM"),
    ("CSCO", "Cisco Systems", "Azioni", "USA", "Tecnologia", "Large cap", "Cisco"),
    ("ACN", "Accenture", "Azioni", "USA", "Tecnologia", "Large cap", "Accenture"),
    ("UBER", "Uber Technologies", "Azioni", "USA", "Tecnologia", "Large cap", "Uber"),
    ("TSLA", "Tesla", "Azioni", "USA", "Consumer", "Mega cap", "Tesla"),
    ("BAC", "Bank of America", "Azioni", "USA", "Finanza", "Mega cap", "Bank of America"),
    ("WFC", "Wells Fargo", "Azioni", "USA", "Finanza", "Large cap", "Wells Fargo"),
    ("GS", "Goldman Sachs", "Azioni", "USA", "Finanza", "Large cap", "Goldman Sachs"),
    ("MS", "Morgan Stanley", "Azioni", "USA", "Finanza", "Large cap", "Morgan Stanley"),
    ("BLK", "BlackRock", "Azioni", "USA", "Finanza", "Large cap", "BlackRock"),
    ("V", "Visa", "Azioni", "USA", "Finanza", "Mega cap", "Visa Inc"),
    ("MA", "Mastercard", "Azioni", "USA", "Finanza", "Mega cap", "Mastercard"),
    ("AXP", "American Express", "Azioni", "USA", "Finanza", "Large cap", "American Express"),
    ("BRK-B", "Berkshire Hathaway", "Azioni", "USA", "Finanza", "Mega cap",
     "Berkshire Hathaway"),
    ("SCHW", "Charles Schwab", "Azioni", "USA", "Finanza", "Large cap", "Charles Schwab"),
    ("JNJ", "Johnson & Johnson", "Azioni", "USA", "Healthcare", "Mega cap",
     "Johnson & Johnson"),
    ("PFE", "Pfizer", "Azioni", "USA", "Healthcare", "Large cap", "Pfizer"),
    ("MRK", "Merck & Co", "Azioni", "USA", "Healthcare", "Large cap", "Merck & Co"),
    ("ABBV", "AbbVie", "Azioni", "USA", "Healthcare", "Mega cap", "AbbVie"),
    ("TMO", "Thermo Fisher Scientific", "Azioni", "USA", "Healthcare", "Large cap",
     "Thermo Fisher"),
    ("ABT", "Abbott Laboratories", "Azioni", "USA", "Healthcare", "Large cap", "Abbott"),
    ("AMGN", "Amgen", "Azioni", "USA", "Healthcare", "Large cap", "Amgen"),
    ("ISRG", "Intuitive Surgical", "Azioni", "USA", "Healthcare", "Large cap",
     "Intuitive Surgical"),
    ("VRTX", "Vertex Pharmaceuticals", "Azioni", "USA", "Healthcare", "Large cap", "Vertex"),
    ("CVX", "Chevron", "Azioni", "USA", "Energia", "Mega cap", "Chevron"),
    ("COP", "ConocoPhillips", "Azioni", "USA", "Energia", "Large cap", "ConocoPhillips"),
    ("SLB", "SLB", "Azioni", "USA", "Energia", "Large cap", "Schlumberger SLB"),
    ("NEE", "NextEra Energy", "Azioni", "USA", "Utilities", "Large cap", "NextEra Energy"),
    ("DUK", "Duke Energy", "Azioni", "USA", "Utilities", "Large cap", "Duke Energy"),
    ("SO", "Southern Company", "Azioni", "USA", "Utilities", "Large cap", "Southern Company"),
    ("BA", "Boeing", "Azioni", "USA", "Industriale", "Large cap", "Boeing"),
    ("LMT", "Lockheed Martin", "Azioni", "USA", "Difesa", "Large cap", "Lockheed Martin"),
    ("RTX", "RTX Corporation", "Azioni", "USA", "Difesa", "Large cap", "RTX Raytheon"),
    ("GE", "GE Aerospace", "Azioni", "USA", "Industriale", "Large cap", "GE Aerospace"),
    ("HON", "Honeywell", "Azioni", "USA", "Industriale", "Large cap", "Honeywell"),
    ("UNP", "Union Pacific", "Azioni", "USA", "Industriale", "Large cap", "Union Pacific"),
    ("DE", "Deere & Company", "Azioni", "USA", "Industriale", "Large cap", "Deere"),
    ("MMM", "3M", "Azioni", "USA", "Industriale", "Large cap", "3M Company"),
    ("PG", "Procter & Gamble", "Azioni", "USA", "Consumer", "Mega cap", "Procter & Gamble"),
    ("PEP", "PepsiCo", "Azioni", "USA", "Consumer", "Mega cap", "PepsiCo"),
    ("COST", "Costco Wholesale", "Azioni", "USA", "Consumer", "Mega cap", "Costco"),
    ("WMT", "Walmart", "Azioni", "USA", "Consumer", "Mega cap", "Walmart"),
    ("MCD", "McDonald's", "Azioni", "USA", "Consumer", "Large cap", "McDonalds"),
    ("NKE", "Nike", "Azioni", "USA", "Consumer", "Large cap", "Nike"),
    ("SBUX", "Starbucks", "Azioni", "USA", "Consumer", "Large cap", "Starbucks"),
    ("HD", "Home Depot", "Azioni", "USA", "Consumer", "Mega cap", "Home Depot"),
    ("DIS", "Walt Disney", "Azioni", "USA", "Comunicazione", "Large cap", "Walt Disney"),
    ("T", "AT&T", "Azioni", "USA", "Telecom", "Large cap", "AT&T"),
    ("VZ", "Verizon", "Azioni", "USA", "Telecom", "Large cap", "Verizon"),
    ("LIN", "Linde", "Azioni", "USA", "Materiali", "Large cap", "Linde plc"),
    ("FCX", "Freeport-McMoRan", "Azioni", "USA", "Materiali", "Large cap", "Freeport-McMoRan"),
    ("NEM", "Newmont", "Azioni", "USA", "Materiali", "Large cap", "Newmont mining"),

    # ---- allargamento: azioni europee (niente listino di Londra) ------------
    ("SHELL.AS", "Shell", "Azioni", "Europa", "Energia", "Mega cap", "Shell plc"),
    ("TTE.PA", "TotalEnergies", "Azioni", "Europa", "Energia", "Mega cap", "TotalEnergies"),
    ("OR.PA", "L'Oréal", "Azioni", "Europa", "Consumer", "Large cap", "L'Oreal"),
    ("SAN.PA", "Sanofi", "Azioni", "Europa", "Healthcare", "Large cap", "Sanofi"),
    ("BNP.PA", "BNP Paribas", "Azioni", "Europa", "Finanza", "Large cap", "BNP Paribas"),
    ("CS.PA", "AXA", "Azioni", "Europa", "Finanza", "Large cap", "AXA assicurazioni"),
    ("DG.PA", "Vinci", "Azioni", "Europa", "Industriale", "Large cap", "Vinci SA"),
    ("SU.PA", "Schneider Electric", "Azioni", "Europa", "Industriale", "Large cap",
     "Schneider Electric"),
    ("RMS.PA", "Hermès", "Azioni", "Europa", "Consumer", "Large cap", "Hermes"),
    ("AI.PA", "Air Liquide", "Azioni", "Europa", "Materiali", "Large cap", "Air Liquide"),
    ("EL.PA", "EssilorLuxottica", "Azioni", "Europa", "Healthcare", "Large cap",
     "EssilorLuxottica"),
    ("SAF.PA", "Safran", "Azioni", "Europa", "Difesa", "Large cap", "Safran"),
    ("ALV.DE", "Allianz", "Azioni", "Europa", "Finanza", "Large cap", "Allianz"),
    ("DTE.DE", "Deutsche Telekom", "Azioni", "Europa", "Telecom", "Large cap",
     "Deutsche Telekom"),
    ("MBG.DE", "Mercedes-Benz Group", "Azioni", "Europa", "Consumer", "Large cap",
     "Mercedes-Benz"),
    ("BMW.DE", "BMW", "Azioni", "Europa", "Consumer", "Large cap", "BMW"),
    ("VOW3.DE", "Volkswagen", "Azioni", "Europa", "Consumer", "Large cap", "Volkswagen"),
    ("BAS.DE", "BASF", "Azioni", "Europa", "Materiali", "Large cap", "BASF"),
    ("MRK.DE", "Merck KGaA", "Azioni", "Europa", "Healthcare", "Large cap", "Merck KGaA"),
    ("RHM.DE", "Rheinmetall", "Azioni", "Europa", "Difesa", "Large cap", "Rheinmetall"),
    ("ADS.DE", "Adidas", "Azioni", "Europa", "Consumer", "Large cap", "Adidas"),
    ("DB1.DE", "Deutsche Börse", "Azioni", "Europa", "Finanza", "Large cap",
     "Deutsche Boerse"),
    ("IFX.DE", "Infineon Technologies", "Azioni", "Europa", "AI", "Large cap", "Infineon"),
    ("ITX.MC", "Inditex", "Azioni", "Europa", "Consumer", "Large cap", "Inditex Zara"),
    ("SAN.MC", "Banco Santander", "Azioni", "Europa", "Finanza", "Large cap",
     "Banco Santander"),
    ("IBE.MC", "Iberdrola", "Azioni", "Europa", "Utilities", "Large cap", "Iberdrola"),
    ("NESN.SW", "Nestlé", "Azioni", "Europa", "Consumer", "Mega cap", "Nestle"),
    ("NOVN.SW", "Novartis", "Azioni", "Europa", "Healthcare", "Mega cap", "Novartis"),
    ("ROG.SW", "Roche", "Azioni", "Europa", "Healthcare", "Mega cap", "Roche Holding"),
    ("UBSG.SW", "UBS Group", "Azioni", "Europa", "Finanza", "Large cap", "UBS Group"),
    ("ABBN.SW", "ABB", "Azioni", "Europa", "Industriale", "Large cap", "ABB Ltd"),
    ("ENI.MI", "Eni", "Azioni", "Europa", "Energia", "Large cap", "Eni SpA"),
    ("UCG.MI", "UniCredit", "Azioni", "Europa", "Finanza", "Large cap", "UniCredit"),
    ("STM.MI", "STMicroelectronics", "Azioni", "Europa", "AI", "Large cap",
     "STMicroelectronics"),
    ("PRY.MI", "Prysmian", "Azioni", "Europa", "Industriale", "Mid cap", "Prysmian"),
    ("ASM.AS", "ASM International", "Azioni", "Europa", "AI", "Large cap",
     "ASM International"),
    ("ADYEN.AS", "Adyen", "Azioni", "Europa", "Tecnologia", "Large cap", "Adyen"),
    ("INGA.AS", "ING Groep", "Azioni", "Europa", "Finanza", "Large cap", "ING Groep"),
    ("AD.AS", "Ahold Delhaize", "Azioni", "Europa", "Consumer", "Large cap",
     "Ahold Delhaize"),
    ("PHIA.AS", "Philips", "Azioni", "Europa", "Healthcare", "Large cap", "Philips"),
    ("EQNR.OL", "Equinor", "Azioni", "Europa", "Energia", "Large cap", "Equinor"),
    ("VOLV-B.ST", "Volvo", "Azioni", "Europa", "Industriale", "Large cap", "Volvo AB"),
    ("ATCO-A.ST", "Atlas Copco", "Azioni", "Europa", "Industriale", "Large cap",
     "Atlas Copco"),
    ("ERIC-B.ST", "Ericsson", "Azioni", "Europa", "Telecom", "Large cap", "Ericsson"),
    ("SAND.ST", "Sandvik", "Azioni", "Europa", "Industriale", "Large cap", "Sandvik"),
    ("NOKIA.HE", "Nokia", "Azioni", "Europa", "Telecom", "Large cap", "Nokia"),
    ("MAERSK-B.CO", "A.P. Møller-Mærsk", "Azioni", "Europa", "Industriale", "Large cap",
     "Maersk"),

    # ---- allargamento: azioni asiatiche ------------------------------------
    ("6758.T", "Sony Group", "Azioni", "Asia", "Tecnologia", "Mega cap", "Sony Group"),
    ("8306.T", "Mitsubishi UFJ Financial", "Azioni", "Asia", "Finanza", "Large cap",
     "Mitsubishi UFJ"),
    ("6861.T", "Keyence", "Azioni", "Asia", "Industriale", "Large cap", "Keyence"),
    ("6902.T", "Denso", "Azioni", "Asia", "Consumer", "Large cap", "Denso"),
    ("4063.T", "Shin-Etsu Chemical", "Azioni", "Asia", "Materiali", "Large cap",
     "Shin-Etsu Chemical"),
    ("7974.T", "Nintendo", "Azioni", "Asia", "Consumer", "Large cap", "Nintendo"),
    ("9433.T", "KDDI", "Azioni", "Asia", "Telecom", "Large cap", "KDDI"),
    ("8035.T", "Tokyo Electron", "Azioni", "Asia", "AI", "Large cap", "Tokyo Electron"),
    ("000660.KS", "SK Hynix", "Azioni", "Asia", "AI", "Large cap", "SK Hynix"),
    ("0700.HK", "Tencent Holdings", "Azioni", "Asia", "Tecnologia", "Mega cap", "Tencent"),
    ("9988.HK", "Alibaba Group", "Azioni", "Asia", "Consumer", "Mega cap", "Alibaba"),
    ("1299.HK", "AIA Group", "Azioni", "Asia", "Finanza", "Large cap", "AIA Group"),
    ("3690.HK", "Meituan", "Azioni", "Asia", "Consumer", "Large cap", "Meituan"),
    ("INFY", "Infosys (ADR)", "Azioni", "Asia", "Tecnologia", "Large cap", "Infosys"),
    ("HDB", "HDFC Bank (ADR)", "Azioni", "Asia", "Finanza", "Large cap", "HDFC Bank"),

    # ---- allargamento: ETF --------------------------------------------------
    ("VTI", "Vanguard Total Stock Market", "ETF", "USA", "Diversificato", "ETF",
     "total stock market ETF"),
    ("IWM", "iShares Russell 2000", "ETF", "USA", "Diversificato", "ETF", "Russell 2000 ETF"),
    ("EFA", "iShares MSCI EAFE", "ETF", "Global", "Diversificato", "ETF", "MSCI EAFE ETF"),
    ("VGK", "Vanguard FTSE Europe", "ETF", "Europa", "Diversificato", "ETF", "FTSE Europe ETF"),
    ("EWJ", "iShares MSCI Japan", "ETF", "Asia", "Diversificato", "ETF", "MSCI Japan ETF"),
    ("INDA", "iShares MSCI India", "ETF", "Asia", "Diversificato", "ETF", "MSCI India ETF"),
    ("MCHI", "iShares MSCI China", "ETF", "Asia", "Diversificato", "ETF", "MSCI China ETF"),
    ("XLF", "Financial Select Sector", "ETF", "USA", "Finanza", "ETF", "financial sector ETF"),
    ("XLE", "Energy Select Sector", "ETF", "USA", "Energia", "ETF", "energy sector ETF"),
    ("XLV", "Health Care Select Sector", "ETF", "USA", "Healthcare", "ETF",
     "health care sector ETF"),
    ("XLK", "Technology Select Sector", "ETF", "USA", "Tecnologia", "ETF",
     "technology sector ETF"),
    ("XLI", "Industrial Select Sector", "ETF", "USA", "Industriale", "ETF",
     "industrial sector ETF"),
    ("XLP", "Consumer Staples Select", "ETF", "USA", "Consumer", "ETF",
     "consumer staples ETF"),
    ("XLU", "Utilities Select Sector", "ETF", "USA", "Utilities", "ETF", "utilities ETF"),
    ("XLB", "Materials Select Sector", "ETF", "USA", "Materiali", "ETF", "materials ETF"),
    ("XBI", "SPDR S&P Biotech", "ETF", "USA", "Healthcare", "ETF", "biotech ETF"),
    ("ICLN", "iShares Global Clean Energy", "ETF", "Global", "Energia", "ETF",
     "clean energy ETF"),
    ("ARKK", "ARK Innovation", "ETF", "USA", "Tecnologia", "ETF", "ARK Innovation ETF"),
    ("GDX", "VanEck Gold Miners", "ETF", "Global", "Materiali", "ETF", "gold miners ETF"),
    ("ITA", "iShares US Aerospace & Defense", "ETF", "USA", "Difesa", "ETF",
     "aerospace defense ETF"),
    ("EUNL.DE", "iShares Core MSCI World", "ETF", "Global", "Diversificato", "ETF",
     "MSCI World ETF"),
    ("SXR8.DE", "iShares Core S&P 500", "ETF", "USA", "Diversificato", "ETF",
     "S&P 500 UCITS ETF"),
    ("IS3N.DE", "iShares Core MSCI EM IMI", "ETF", "Asia", "Diversificato", "ETF",
     "MSCI emerging markets IMI ETF"),

    # ---- allargamento: obbligazionari --------------------------------------
    ("SHY", "iShares 1-3Y Treasury", "Obbligazioni", "USA", "Obbligazionario", "Governativo",
     "short Treasury ETF"),
    ("TIP", "iShares TIPS Bond", "Obbligazioni", "USA", "Obbligazionario", "Inflazione",
     "TIPS inflation bond ETF"),
    ("HYG", "iShares High Yield Corporate", "Obbligazioni", "USA", "Obbligazionario",
     "High yield", "high yield bond ETF"),
    ("AGG", "iShares Core US Aggregate", "Obbligazioni", "USA", "Obbligazionario",
     "Aggregato", "aggregate bond ETF"),
    ("BND", "Vanguard Total Bond Market", "Obbligazioni", "USA", "Obbligazionario",
     "Aggregato", "total bond market ETF"),
    ("IEGA.AS", "iShares Core Euro Govt Bond", "Obbligazioni", "Europa", "Obbligazionario",
     "Governativo", "euro government bond ETF"),

    # ---- allargamento: crypto ----------------------------------------------
    ("XRP-USD", "XRP", "Crypto", "Global", "Crypto", "Large cap", "XRP Ripple"),
    ("ADA-USD", "Cardano", "Crypto", "Global", "Crypto", "Mid cap", "Cardano"),
    ("AVAX-USD", "Avalanche", "Crypto", "Global", "Crypto", "Mid cap", "Avalanche crypto"),
    ("DOT-USD", "Polkadot", "Crypto", "Global", "Crypto", "Mid cap", "Polkadot"),
    ("LTC-USD", "Litecoin", "Crypto", "Global", "Crypto", "Mid cap", "Litecoin"),
    ("DOGE-USD", "Dogecoin", "Crypto", "Global", "Crypto", "Mid cap", "Dogecoin"),

    # ---- allargamento: materie prime ---------------------------------------
    ("NG=F", "Gas naturale (future)", "Commodities", "Global", "Materie prime", "Energia",
     "natural gas price"),
    ("PL=F", "Platino (future)", "Commodities", "Global", "Materie prime",
     "Metalli preziosi", "platinum price"),
    ("PA=F", "Palladio (future)", "Commodities", "Global", "Materie prime",
     "Metalli preziosi", "palladium price"),
    ("ZC=F", "Mais (future)", "Commodities", "Global", "Materie prime", "Agricoli",
     "corn price"),
    ("ZW=F", "Grano (future)", "Commodities", "Global", "Materie prime", "Agricoli",
     "wheat price"),
    ("KC=F", "Caffè (future)", "Commodities", "Global", "Materie prime", "Agricoli",
     "coffee price"),

    # ---- allargamento: immobiliare -----------------------------------------
    ("O", "Realty Income", "REIT", "USA", "Immobiliare", "Retail", "Realty Income"),
    ("AMT", "American Tower", "REIT", "USA", "Immobiliare", "Infrastrutture",
     "American Tower"),
    ("EQIX", "Equinix", "REIT", "USA", "Immobiliare", "Data center", "Equinix"),
    ("WELL", "Welltower", "REIT", "USA", "Immobiliare", "Sanitario", "Welltower"),
    ("PSA", "Public Storage", "REIT", "USA", "Immobiliare", "Self storage",
     "Public Storage"),
    ("DLR", "Digital Realty Trust", "REIT", "USA", "Immobiliare", "Data center",
     "Digital Realty"),
]

# descrizioni in parole semplici: le stesse della demo, con i simboli che cambiano
DESCRIPTION_ALIASES = {"GC=F": "XAUUSD", "SI=F": "XAGUSD"}

MIN_FUNDAMENTAL_FIELDS = 8      # sotto questa soglia l'asset non si può valutare


def peer_for_label(asset: dict, peers: dict) -> dict | None:
    from .valuation import peer_for
    p = peer_for(asset, peers)
    if not p:
        return None
    sector = asset["sector"] if asset["sector"] in peers.get("sectors", {}) else "tutto il listino"
    return {"reference": sector, "pe_median": round(p["pe"], 1),
            "growth_median": round(p.get("growth") or 0.0, 4), "n": p["n"]}


def _description(symbol: str) -> str:
    return DESCRIPTIONS.get(DESCRIPTION_ALIASES.get(symbol, symbol), "")


def _earnings_from_fundamentals(f: dict) -> dict:
    """"Conti migliori del previsto" senza previsioni di analisti: confronto
    con lo stesso trimestre dell'anno prima, che è un fatto pubblicato."""
    rev, eps = f.get("quarterly_revenue_yoy"), f.get("quarterly_eps_yoy")
    if rev is None and eps is None:
        return {"coverage": False, "reason": "nessun bilancio trimestrale disponibile"}
    return {"coverage": True, "basis": "crescita anno su anno",
            "report_date": f.get("last_report_date") or date.today().isoformat(),
            "revenue_yoy": rev, "eps_yoy": eps,
            # campi usati dagli agenti: qui la "sorpresa" è la crescita reale
            "revenue_surprise": rev, "eps_surprise": eps}


def load_real_universe(provider: Yahoo | None = None, only: list[str] | None = None,
                       on_progress=None) -> tuple[list[dict], list[dict]]:
    """Scarica e normalizza l'universo. Restituisce (asset, scartati)."""
    y = provider or Yahoo()
    specs = [s for s in REAL_SPECS if not only or s[0] in only]
    fx_cache: dict[str, float] = {}
    assets: list[dict] = []
    skipped: list[dict] = []

    for i, (symbol, name, acls, market, sector, size, query) in enumerate(specs):
        if on_progress:
            on_progress(i + 1, len(specs), symbol)
        try:
            chart = y.chart(symbol)
        except DataError as e:
            skipped.append({"ticker": symbol, "reason": str(e)})
            continue

        price = chart["close"][-1]
        cur = chart["currency"] or "USD"
        if cur not in fx_cache:
            fx_cache[cur] = y.fx_to_eur(cur) or FX_TO_EUR.get(cur) or 1.0
        series = {k: chart[k] for k in ("date", "open", "high", "low", "close", "volume")}

        try:
            statements = y.statements(symbol)
        except DataError:
            statements = {}

        # L'utile per azione va portato nella valuta del prezzo, altrimenti il
        # rapporto prezzo/utili non significa niente.
        stmt_cur = statement_currency(statements)
        eps_fx, fx_note = 1.0, None
        if stmt_cur and stmt_cur != cur:
            if stmt_cur not in fx_cache:
                fx_cache[stmt_cur] = y.fx_to_eur(stmt_cur) or FX_TO_EUR.get(stmt_cur) or 0.0
            if fx_cache[stmt_cur] and fx_cache[cur]:
                eps_fx = fx_cache[stmt_cur] / fx_cache[cur]
                fx_note = f"utile per azione convertito da {stmt_cur} a {cur}"
            else:
                fx_note = f"bilanci in {stmt_cur}, prezzo in {cur}: cambio non disponibile"

        f = derive_fundamentals(statements, price, eps_fx=eps_fx)
        has_fundamentals = f["fields_available"] >= MIN_FUNDAMENTAL_FIELDS
        if not has_fundamentals:
            f = {"basis": "solo prezzo (nessun bilancio disponibile senza contratto dati)",
                 "fields_available": f["fields_available"]}

        # Controllo di sanità: un utile per azione negativo o un multiplo fuori
        # scala rendono la stima di valore priva di senso. Si dichiara, non si
        # pubblica un numero sbagliato.
        valuation_note = fx_note
        valuable = has_fundamentals
        if has_fundamentals:
            pe = f.get("pe")
            if not f.get("eps_ttm") or f["eps_ttm"] <= 0:
                valuable, valuation_note = False, "utile per azione negativo o nullo"
            elif not pe or pe < 3 or pe > 150:
                valuable = False
                valuation_note = (f"rapporto prezzo/utili fuori scala ({pe:.0f}x)" if pe
                                  else "rapporto prezzo/utili non calcolabile")

        news = y.news(symbol, query=query)
        asset = {
            "ticker": symbol, "name": name, "asset_class": acls, "market": market,
            "sector": sector, "size": size, "currency": cur,
            "fx_to_eur": fx_cache[cur],
            "description": _description(symbol),
            "class_in_words": CLASS_IN_WORDS.get(acls, acls),
            "series": series, "tech": snapshot(series),
            "fundamentals": f,
            "news": news,
            "insider": {"coverage": False,
                        "reason": "dati insider non disponibili senza contratto dati"},
            "earnings": _earnings_from_fundamentals(f) if has_fundamentals
            else {"coverage": False, "reason": "nessun bilancio trimestrale disponibile"},
            "valuable": valuable,
            "valuation_note": valuation_note,
            "data_quality": {
                "source": "Yahoo Finance",
                "bars": len(series["close"]),
                "last_bar": series["date"][-1],
                # L'ora dell'ultimo scambio secondo la borsa. Sta qui e non in
                # "series" perche' series e' un dizionario di liste parallele,
                # che gli indicatori e il grafico scorrono per indice: un
                # valore singolo in mezzo le romperebbe.
                "market_time": chart.get("market_time"),
                "fundamental_fields": f.get("fields_available", 0),
                "fundamentals": has_fundamentals,
                "valuable": valuable,
                "note": valuation_note or "",
                "news": len(news),
                "news_polarity": "da modello" if news else "nessuna notizia",
                "insider": False,
                "fx_live": cur in fx_cache and cur != "EUR",
            },
            "_shape": "reale",
        }
        assets.append(asset)

    # Secondo passaggio: il multiplo giusto si misura sui simili, quindi serve
    # prima avere tutto il listino (DEMO-26).
    peers = peer_stats(assets)
    for a in assets:
        a["valuation"] = fair_value(a, peers)
        a["peers"] = peer_for_label(a, peers)
    return assets, skipped
