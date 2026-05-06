"""
Universe of US and Canadian stock tickers used by the screener.

Tickers are organized into named *lists*:
  - SP500   — S&P 500 (curated, mostly stable)
  - DOW30   — Dow Jones Industrial Average (30 names)
  - NDX100  — Nasdaq-100
  - TSX     — Active TSX listings (yfinance suffix `.TO`)

A ticker may appear in several lists (e.g. AAPL is in S&P 500, Dow 30,
and Nasdaq-100). Membership is exposed via :func:`lists_for` so the UI can
display chips and so the screener can filter by list.
"""

from __future__ import annotations

# --- S&P 500 components (curated; small drift over time) --------------------
SP500: list[str] = [
    "MMM", "AOS", "ABT", "ABBV", "ACN", "ADBE", "AMD", "AES", "AFL", "A",
    "APD", "ABNB", "AKAM", "ALB", "ARE", "ALGN", "ALLE", "LNT", "ALL", "GOOGL",
    "GOOG", "MO", "AMZN", "AMCR", "AEE", "AEP", "AXP", "AIG", "AMT", "AWK",
    "AMP", "AME", "AMGN", "APH", "ADI", "ANSS", "AON", "APA", "AAPL", "AMAT",
    "APTV", "ACGL", "ADM", "ANET", "AJG", "AIZ", "T", "ATO", "ADSK", "ADP",
    "AZO", "AVB", "AVY", "AXON", "BKR", "BALL", "BAC", "BAX", "BDX", "BRK-B",
    "BBY", "BIO", "TECH", "BIIB", "BLK", "BX", "BK", "BA", "BKNG", "BWA",
    "BSX", "BMY", "AVGO", "BR", "BRO", "BF-B", "BLDR", "BG", "CDNS", "CZR",
    "CPT", "CPB", "COF", "CAH", "KMX", "CCL", "CARR", "CTLT", "CAT", "CBOE",
    "CBRE", "CDW", "CE", "COR", "CNC", "CNP", "CF", "CRL", "SCHW", "CHTR",
    "CVX", "CMG", "CB", "CHD", "CI", "CINF", "CTAS", "CSCO", "C", "CFG",
    "CLX", "CME", "CMS", "KO", "CTSH", "CL", "CMCSA", "CAG", "COP", "ED",
    "STZ", "CEG", "COO", "CPRT", "GLW", "CPAY", "CTVA", "CSGP", "COST", "CTRA",
    "CRWD", "CCI", "CSX", "CMI", "CVS", "DHR", "DRI", "DVA", "DAY", "DE",
    "DAL", "DVN", "DXCM", "FANG", "DLR", "DFS", "DG", "DLTR", "D", "DPZ",
    "DOV", "DOW", "DHI", "DTE", "DUK", "DD", "EMN", "ETN", "EBAY", "ECL",
    "EIX", "EW", "EA", "ELV", "LLY", "EMR", "ENPH", "ETR", "EOG", "EPAM",
    "EQT", "EFX", "EQIX", "EQR", "ESS", "EL", "ETSY", "EG", "EVRG", "ES",
    "EXC", "EXPE", "EXPD", "EXR", "XOM", "FFIV", "FDS", "FICO", "FAST", "FRT",
    "FDX", "FIS", "FITB", "FSLR", "FE", "FI", "F", "FTNT", "FTV", "FOXA",
    "FOX", "BEN", "FCX", "GRMN", "IT", "GE", "GEHC", "GEV", "GEN", "GNRC",
    "GD", "GIS", "GM", "GPC", "GILD", "GPN", "GL", "GS", "HAL", "HIG",
    "HAS", "HCA", "DOC", "HSIC", "HSY", "HES", "HPE", "HLT", "HOLX", "HD",
    "HON", "HRL", "HST", "HWM", "HPQ", "HUBB", "HUM", "HBAN", "HII", "IBM",
    "IEX", "IDXX", "ITW", "INCY", "IR", "PODD", "INTC", "ICE", "IFF", "IP",
    "IPG", "INTU", "ISRG", "IVZ", "INVH", "IQV", "IRM", "JBHT", "JBL", "JKHY",
    "J", "JNJ", "JCI", "JPM", "JNPR", "K", "KVUE", "KDP", "KEY", "KEYS",
    "KMB", "KIM", "KMI", "KKR", "KLAC", "KHC", "KR", "LHX", "LH", "LRCX",
    "LW", "LVS", "LDOS", "LEN", "LIN", "LYV", "LKQ", "LMT", "L", "LOW",
    "LULU", "LYB", "MTB", "MPC", "MKTX", "MAR", "MMC", "MLM", "MAS", "MA",
    "MTCH", "MKC", "MCD", "MCK", "MDT", "MRK", "META", "MET", "MTD", "MGM",
    "MCHP", "MU", "MSFT", "MAA", "MRNA", "MHK", "MOH", "TAP", "MDLZ", "MPWR",
    "MNST", "MCO", "MS", "MOS", "MSI", "MSCI", "NDAQ", "NTAP", "NFLX", "NEM",
    "NWSA", "NWS", "NEE", "NKE", "NI", "NDSN", "NSC", "NTRS", "NOC", "NCLH",
    "NRG", "NUE", "NVDA", "NVR", "NXPI", "ORLY", "OXY", "ODFL", "OMC", "ON",
    "OKE", "ORCL", "OTIS", "PCAR", "PKG", "PLTR", "PANW", "PARA", "PH", "PAYX",
    "PAYC", "PYPL", "PNR", "PEP", "PFE", "PCG", "PM", "PSX", "PNW", "PNC",
    "POOL", "PPG", "PPL", "PFG", "PG", "PGR", "PLD", "PRU", "PEG", "PTC",
    "PSA", "PHM", "QRVO", "PWR", "QCOM", "DGX", "RL", "RJF", "RTX", "O",
    "REG", "REGN", "RF", "RSG", "RMD", "RVTY", "ROK", "ROL", "ROP", "ROST",
    "RCL", "SPGI", "CRM", "SBAC", "SLB", "STX", "SRE", "NOW", "SHW", "SPG",
    "SWKS", "SJM", "SW", "SNA", "SOLV", "SO", "LUV", "SWK", "SBUX", "STT",
    "STLD", "STE", "SYK", "SMCI", "SYF", "SNPS", "SYY", "TMUS", "TROW", "TTWO",
    "TPR", "TRGP", "TGT", "TEL", "TDY", "TFX", "TER", "TSLA", "TXN", "TPL",
    "TXT", "TMO", "TJX", "TSCO", "TT", "TDG", "TRV", "TRMB", "TFC", "TYL",
    "TSN", "USB", "UBER", "UDR", "ULTA", "UNP", "UAL", "UPS", "URI", "UNH",
    "UHS", "VLO", "VTR", "VLTO", "VRSN", "VRSK", "VZ", "VRTX", "VTRS", "VICI",
    "V", "VST", "VMC", "WRB", "GWW", "WAB", "WBA", "WMT", "DIS", "WBD",
    "WM", "WAT", "WEC", "WFC", "WELL", "WST", "WDC", "WY", "WMB", "WTW",
    "WYNN", "XEL", "XYL", "YUM", "ZBRA", "ZBH", "ZTS",
]

# --- Dow Jones Industrial Average (30 components) ---------------------------
DOW30: list[str] = [
    "AAPL", "AMGN", "AMZN", "AXP", "BA", "CAT", "CRM", "CSCO", "CVX", "DIS",
    "GS", "HD", "HON", "IBM", "JNJ", "JPM", "KO", "MCD", "MMM", "MRK",
    "MSFT", "NKE", "NVDA", "PG", "SHW", "TRV", "UNH", "V", "VZ", "WMT",
]

# --- Nasdaq (curated broader Nasdaq listing — Nasdaq-100 + active mid/small
# caps across software, semis, biotech, consumer, fintech, EV). The full
# Nasdaq Composite is ~3,500 names; we keep this to a tractable subset of
# liquid names. -------------------------------------------------------------
NASDAQ: list[str] = [
    # Nasdaq-100 mega-caps
    "AAPL", "ABNB", "ADBE", "ADI", "ADP", "ADSK", "AEP", "AMAT", "AMD",
    "AMGN", "AMZN", "ANSS", "ARM", "ASML", "AVGO", "AZN", "BIIB", "BKNG",
    "BKR", "CCEP", "CDNS", "CDW", "CEG", "CHTR", "CMCSA", "COST", "CPRT",
    "CRWD", "CSCO", "CSGP", "CSX", "CTAS", "CTSH", "DASH", "DDOG", "DLTR",
    "DXCM", "EA", "EXC", "FANG", "FAST", "FTNT", "GEHC", "GFS", "GILD",
    "GOOG", "GOOGL", "HON", "IDXX", "ILMN", "INTC", "INTU", "ISRG", "KDP",
    "KHC", "KLAC", "LIN", "LRCX", "LULU", "MAR", "MCHP", "MDB", "MDLZ",
    "MELI", "META", "MNST", "MRNA", "MRVL", "MSFT", "MU", "NFLX", "NVDA",
    "NXPI", "ODFL", "ON", "ORLY", "PANW", "PAYX", "PCAR", "PDD", "PEP",
    "PYPL", "QCOM", "REGN", "ROP", "ROST", "SBUX", "SNPS", "TEAM", "TMUS",
    "TSLA", "TTD", "TTWO", "TXN", "VRSK", "VRTX", "WBA", "WBD", "WDAY",
    "XEL", "ZS",
    # Software / SaaS / cloud
    "ZM", "DOCU", "OKTA", "SNOW", "NET", "TWLO", "FSLY", "ESTC", "U",
    "PATH", "S", "AI", "GTLB", "BILL", "DOCS", "DBX", "HUBS", "FIVN",
    "DT", "NEWR", "PD", "BAND", "EVBG", "RPD", "ALRM", "APPN", "BL",
    "AYX", "COUP", "SMAR", "FROG", "MNDY", "ZI", "TENB", "QLYS", "JAMF",
    "BRZE", "SPT", "BLKB", "TYL", "JKHY", "SSNC", "PCTY", "PEGA", "WK",
    "WIX", "AKAM", "VRSN", "NTAP", "PTC", "CRUS", "TRMB", "ZBRA", "VRNS",
    "QTWO", "SPWH", "FORG", "EGAN", "VEEV", "AUR", "RDFN",
    # Semiconductors / hardware
    "CRDO", "COHR", "IPGP", "ENTG", "ONTO", "RMBS", "NVMI", "FORM", "BESI",
    "ICHR", "KLIC", "AEHR", "AMBA", "SIMO", "SLAB", "ACMR", "SITM", "ALGM",
    "CALX", "CIEN", "COMM", "INFN", "POWI", "SGH", "SYNA", "UCTT", "VECO",
    "WOLF", "FN", "AOSL", "MTSI", "AMKR", "VICR", "DIOD", "AMSC", "TER",
    "QRVO", "MPWR", "SWKS", "STX", "WDC", "LITE", "SANM",
    # Biotech / pharma
    "ALNY", "BMRN", "IONS", "MRTX", "EXEL", "CRSP", "BEAM", "NTLA", "EDIT",
    "RGNX", "HALO", "LEGN", "NBIX", "AKRO", "ARWR", "SAGE", "TGTX", "RPRX",
    "ACAD", "GH", "INSM", "FATE", "RXRX", "NUVL", "JANX", "ALLO", "IOVA",
    "DAWN", "VKTX", "MDGL", "KRTX", "KYMR", "RVMD", "PRTA", "STOK", "SRPT",
    "ARGX", "ALEC", "RYTM", "IMVT", "HIMS", "ANNX", "REPL", "SDGR", "GMAB",
    "VCYT", "LXRX", "ATAI", "ALDX", "CYTK", "CTKB", "ESPR", "ALPN", "RVNC",
    "GERN", "CPRX", "BNTX", "INCY", "NVAX", "AKBA", "CLDX", "TVTX", "BPMC",
    "FOLD", "PTCT", "ARCT", "ADMA", "RIGL", "TWST", "PACB", "AMRX",
    "HOLX", "MASI", "PEN", "INMD", "NTRA", "TDOC", "CERT", "OMCL",
    # Consumer / retail / restaurants / leisure (Nasdaq-listed)
    "DKNG", "ROKU", "TXRH", "WING", "JACK", "PLAY", "FOXF", "YETI", "BJRI",
    "CAKE", "CHEF", "CHUY", "CHWY", "PTON", "ETSY", "FUBO", "POOL", "WW",
    "ZUMZ", "EYE", "CASY", "DRVN", "BURL", "DKS", "FIVE", "OLLI", "TCOM",
    "VIK", "OPRA", "GRAB", "SE", "BIDU", "JD", "BABA", "ROL",
    "SBOW", "CHRD", "CDNA",
    # Fintech / financials
    "COIN", "HOOD", "SOFI", "AFRM", "UPST", "LC", "OPEN", "RKT", "MQ",
    "DAVE", "ALLY", "TREE", "NU", "PAGS", "STNE", "FOUR",
    "FLYW", "FOA", "PFSI",
    # EV / mobility / auto
    "RIVN", "LCID", "FSR", "NIO", "LI", "XPEV", "GOEV", "BLNK", "CHPT",
    "QS", "EVGO",
    # Energy (Nasdaq-listed)
    "AR", "CIVI", "CRC", "MEG", "PR", "SD", "SM", "MTDR", "GPRE",
    # Media / telecom (Nasdaq-listed)
    "PARA", "SIRI", "FOXA", "FOX", "LYV", "NWSA", "NWS", "DISH", "LBRDA",
    "LBRDK", "LSXMK", "LSXMA",
    # Industrials / misc Nasdaq-listed names
    "FFIV", "ULTA", "EXPE", "TRIP", "SAIA", "WERN", "JBHT",
    "LANC", "HSIC", "CINF", "FITB", "HBAN", "MTCH", "TROW", "EBAY",
    "ZG", "Z",
]

# --- TSX (Canada) - active large/mid caps -----------------------------------
_TSX_BASE: list[str] = [
    "RY", "TD", "BNS", "BMO", "CM", "NA", "ENB", "TRP", "CNQ", "SU",
    "CVE", "IMO", "CPG", "ARX", "TOU", "MEG", "VET", "WCP", "BTE", "CNR",
    "CP", "BCE", "T", "RCI-B", "QBR-B", "SJR-B", "ATD", "L", "WN", "MRU",
    "EMP-A", "DOL", "GIB-A", "OTEX", "SHOP", "CSU", "DSG", "KXS", "LSPD", "NVEI",
    "BB", "CLS", "DCBO", "TIXT", "ABX", "AEM", "FNV", "WPM", "K", "ELD",
    "OR", "PAAS", "FM", "TECK-B", "LUN", "HBM", "ERO", "IVN", "FVI", "AGI",
    "KGC", "NGD", "OGC", "CG", "SSL", "TXG", "BTO", "EQX", "EDV", "SVM",
    "MFC", "SLF", "GWO", "IFC", "FFH", "POW", "IAG", "X", "TRI", "WSP",
    "STN", "GIL", "MG", "MRE", "BYD", "DOO", "LNR", "NFI", "CTC-A", "CCL-B",
    "ATZ", "GOOS", "AC", "CAE", "TFII", "BIP-UN", "BEP-UN", "BAM", "BN", "PPL",
    "ALA", "KEY", "FTS", "EMA", "H", "AQN", "INE", "BLX", "CPX", "CU",
    "NPI", "TIH", "FSV", "REI-UN", "CAR-UN", "AP-UN", "GRT-UN", "SRU-UN", "HR-UN", "CHP-UN",
    "ATRL", "OSB", "WFG", "IFP", "CFP", "NTR", "AFN", "ATA", "BIR", "BLDP",
    "BHC", "CCA", "CIGI", "CRR-UN", "CWB", "DPM", "EFN", "ENGH", "FCR-UN", "FRU",
    "GFL", "HPS-A", "IGM", "IIP-UN", "ITP", "LIF", "MX", "NVA", "ONEX", "PEY",
    "PKI", "PSI", "PXT", "RBA", "SAP", "SES", "SIA", "SII", "SMU-UN", "TPZ",
    "TVE", "TSU",
]
TSX: list[str] = [t + ".TO" for t in _TSX_BASE]

# --- Russell 2000 (US small-cap) — curated active subset --------------------
# The Russell 2000 contains ~2000 names that rebalance annually; this list is
# a curated subset of the most-traded small-caps across every sector. Adding
# it to the screened universe materially extends cold-cache run time.
RUSSELL2000: list[str] = [
    "ABCB", "AMAL", "AMTB", "ASB", "AUB", "AX", "BANC", "BANF", "BANR", "BFC",
    "BHLB", "BKU", "BMRC", "BOH", "BPOP", "BRKL", "BUSE", "BY", "CASH", "CATY",
    "CBSH", "CCBG", "CFB", "CFFI", "CFR", "CHCO", "CIVB", "CNOB", "COFS", "COLB",
    "CPF", "CTBI", "CUBI", "CVBF", "CVCY", "CWBC", "CZNC", "DCOM", "EBC", "EFSC",
    "EGBN", "EQBK", "EWBC", "FBC", "FBIZ", "FBK", "FBP", "FCBC", "FCF", "FCNCA",
    "FFBC", "FFIN", "FFWM", "FHB", "FHN", "FIBK", "FISI", "FMAO", "FMBH", "FNB",
    "FRME", "FSBC", "FULT", "GBCI", "GSBC", "HAFC", "HBCP", "HBT", "HFWA", "HIFS",
    "HMST", "HOMB", "HOPE", "HTBI", "HTLF", "IBCP", "IBOC", "IBTX", "INBK", "INDB",
    "JEF", "KRNY", "LBAI", "LCNB", "LKFN", "MBIN", "MBWM", "MCB", "MOFG", "NBHC",
    "NBN", "NBTB", "NCBS", "NFBK", "NKSH", "NRIM", "NWBI", "NWFL", "NYCB", "OBNK",
    "OCFC", "OFG", "ONB", "ORRF", "OSBC", "OZK", "PACW", "PB", "PEBO", "PFBC",
    "PFC", "PFIS", "PFS", "PGC", "PNFP", "PPBI", "PRK", "PROV", "QCRH", "RBB",
    "RNST", "SASR", "SBCF", "SBSI", "SBT", "SFBC", "SFBS", "SFNC", "SHBI", "SMBC",
    "SMBK", "SMMF", "SPFI", "SRCE", "STBA", "SYBT", "TBBK", "TBK", "TCBK", "TCFC",
    "TFIN", "TFSL", "TOWN", "TRMK", "TRST", "TRTX", "UBSI", "UCBI", "UMBF", "UMPQ",
    "UNTY", "UVSP", "VBTX", "VLY", "WABC", "WASH", "WBS", "WSBC", "WSFS", "WTBA",
    "WTFC", "AGM", "ASRV", "BFIN", "BHB", "BPRN", "CAC", "CALB", "CARV", "CHMG",
    "CIZN", "CLBK", "CMTV", "DLNG", "EBSB", "ECBK", "EQS", "FBNC", "FCAP", "FCCO",
    "FFIC", "FRBA", "GBNK", "GCBC", "GFED", "GSBD", "HFFG", "HIBB", "HONE", "HTBK",
    "HVT", "JJSF", "JOUT", "KFY", "KFRC", "KINS", "KRT", "KRO", "KW", "LARK",
    "LBC", "LCUT", "LEU", "LIVE", "LMNR", "LOAN", "LXP", "LYTS", "MBI", "MCBC",
    "MCRI", "MEC", "MGEE", "MGRC", "MKTX", "MLAB", "MLI", "MNRO", "MNTK", "MOG-A",
    "MTW", "NABL", "NMIH", "NMRK", "NNI", "NPK", "NSP", "NUS", "NVRO", "OFLX",
    "ONTF", "OPCH", "PATK", "PCRX", "PDFS", "PETQ", "PFGC", "PINC", "PJT", "PLMR",
    "PRGS", "PRIM", "PROK", "PSMT", "PTGX", "PYR", "PZN", "QNST", "REZI", "RGR",
    "RILY", "RMBL", "ROCK", "RPD", "RYI", "SAFT", "SAH", "SBH", "SCSC", "SEM",
    "SHEN", "SHOO", "SHYF", "SIEB", "SIG", "SLM", "SLP", "SMP", "SNCY", "SPB",
    "SPNT", "SRCL", "STAA", "STAR", "STC", "STEL", "STEP", "STR", "STRA", "SUPN",
    "SYBX", "TBPH", "TCMD", "TCRT", "TGNA", "THFF", "THR", "THRY", "TILE", "TITN",
    "TLYS", "TMP", "TNDM", "TPB", "TPC", "TPH", "TPRE", "TPST", "TPX", "ACIW",
    "ADTN", "AGYS", "ALRM", "ALTR", "ANGI", "APPN", "ATEN", "AVNS", "BCOV", "BLKB",
    "BOX", "BRZE", "CARG", "CASA", "CDLX", "CEVA", "CIEN", "CLFD", "CMTL", "CNDT",
    "CNXN", "CSGS", "CSWI", "CTLP", "CWAN", "CYBR", "DBX", "DOCN", "DOMO", "DT",
    "EBIX", "ECPG", "EGAN", "EGHT", "EIGI", "ENS", "ENV", "ENVX", "EPAY", "EVBG",
    "EVCM", "EVO", "EVRI", "EXTR", "FA", "FFIV", "FORTY", "FRSH", "FSV", "FWRD",
    "GLBE", "GLT", "GVA", "HCAT", "HCKT", "HLIT", "HSII", "HUBG", "IBM", "ICHR",
    "IIVI", "INFN", "INFO", "INSP", "ITRI", "ITRN", "JAMF", "KLIC", "LASR", "LFUS",
    "LFCR", "LGND", "LITE", "LPRO", "LXFR", "MANH", "MARA", "MAXR", "MEDP", "MIDD",
    "MITK", "MNDY", "MQ", "NCNO", "NEWR", "NICE", "NTAP", "NTCT", "NTGR", "NUVI",
    "OOMA", "OPRX", "OSPN", "OSTK", "PCTY", "PEGA", "PERI", "PI", "PKE", "PLNT",
    "PLUS", "POWI", "PRO", "PRTH", "PTC", "QLYS", "QTRX", "QTWO", "QXO", "RAMP",
    "RCMT", "S", "SABR", "SANM", "SEMR", "SHCO", "SITM", "SLAB", "SMAR", "SOND",
    "SPNS", "SPSC", "SPT", "SUMO", "SVII", "SWBI", "SYNA", "TASK", "TBIO", "TDC",
    "TENB", "TPG", "TREE", "UCTT", "UEIC", "UFI", "UFPI", "UFPT", "UI", "UIS",
    "UNIT", "UPLD", "VECO", "VERI", "VERX", "VGI", "VHC", "VIAV", "VICR", "VIRT",
    "VKTX", "VRNS", "VRNT", "VSAT", "VSEC", "VTEX", "WERN", "WIX", "WK", "WMS",
    "WNS", "XPER", "XPOF", "YEXT", "ZUO", "ACAD", "ACET", "ACLS", "ACMR", "ACRS",
    "ACT", "ACVA", "ADMA", "ADV", "AEMD", "AKBA", "AKRO", "AKYA", "ALDX", "ALEC",
    "ALGS", "ALLO", "ALLR", "ALPN", "ALRN", "ALT", "AMPH", "AMRX", "ANAB", "ANIK",
    "ANNX", "APLS", "APLT", "AQST", "ARCT", "ARDX", "ARGX", "ARNA", "ARQT", "ARVN",
    "ARWR", "ASMB", "ASND", "ATEC", "ATHE", "ATNX", "ATRA", "ATRC", "ATRO", "ATSG",
    "AUPH", "AVAH", "AVDL", "AVIR", "AVTE", "AVXL", "AXGN", "AXLA", "AXSM", "BBIO",
    "BCRX", "BCYC", "BEAM", "BEAT", "BFLY", "BGNE", "BHC", "BHVN", "BIO", "BLU",
    "BLUE", "BMEA", "BMRA", "BMRN", "BPMC", "BPTH", "BRKR", "BSX", "BTAI", "BVS",
    "BXRX", "CABA", "CALA", "CARA", "CCLD", "CCXI", "CDAK", "CDMO", "CDNA", "CDXC",
    "CDXS", "CERS", "CGEM", "CGEN", "CGNX", "CHRS", "CINC", "CKPT", "CLDX", "CLOV",
    "CLVS", "CMPS", "CNMD", "CNTA", "COGT", "COHU", "COLL", "CORT", "CPHC", "CPIX",
    "CPRX", "CRDF", "CRMD", "CRNX", "CRSP", "CRTX", "CRVS", "CTKB", "CTLT", "CTMX",
    "CUE", "CUTR", "CVAC", "CYCN", "CYTK", "DARE", "DAWN", "DBVT", "DCPH", "DEC",
    "DERM", "DGX", "DHC", "DHR", "DICE", "DRRX", "DSGN", "DTIL", "DVAX", "DXR",
    "DYAI", "DYN", "EAR", "EBET", "EBS", "EDIT", "EDSA", "EHTH", "ELAN", "ELOX",
    "ELVN", "EOLS", "ERAS", "ESPR", "ESTA", "ETON", "EVAX", "EVOK", "EWTX", "EXEL",
    "EYE", "EYEN", "EYPT", "FATE", "FBIO", "FBRX", "FENC", "FGEN", "FHTX", "FOLD",
    "FRPT", "GBIO", "GERN", "GH", "GILD", "GMAB", "GMDA", "GNFT", "GOSS", "GPRO",
    "GRPN", "GTBP", "GTHX", "HALO", "HARP", "HCM", "HEPS", "HIMS", "HOLX", "HOWL",
    "HRMY", "HRTX", "HSDT", "HSKA", "HSTM", "HUMA", "HZNP", "ICCC", "ICPT", "IDYA",
    "IGMS", "IGT", "IKNA", "IKT", "ILMN", "IMAB", "IMCR", "IMGN", "IMMP", "IMNM",
    "IMVT", "IMXI", "INCY", "INDV", "INMD", "INMB", "INO", "INSM", "INVA", "IONS",
    "IOVA", "IPHA", "IRIX", "IRMD", "IRWD", "ITCI", "ITGR", "ITOS", "JAGX", "JANX",
    "JAZZ", "JNCE", "KALA", "KALV", "KDNY", "KIDS", "KMDA", "KOD", "KPTI", "KRON",
    "KROS", "KRTX", "KRYS", "KURA", "KYMR", "LBPH", "LEXX", "LIAN", "LIVN", "LJPC",
    "LMNL", "LNTH", "LQDA", "LXRX", "LYEL", "MASS", "MCRB", "MDGL", "MDXG", "MGLN",
    "MGNI", "MGTA", "MIRM", "MIRO", "MNKD", "MNMD", "MOR", "MORF", "MRNS", "MRTX",
    "MTCH", "MTLS", "MTRX", "MWA", "MYE", "MYGN", "NARI", "NBIX", "NBSE", "NEOG",
    "NEXI", "NK", "NKTR", "NMRD", "NOVT", "NRIX", "NRXP", "NSPR", "NTLA", "NTNX",
    "NTRA", "NUVL", "NUVN", "NVAX", "NVCR", "NVST", "NXTC", "OCGN", "OCUL", "OCX",
    "OFIX", "OMCL", "OMER", "OMI", "OMIC", "ONCY", "ONVO", "OPK", "OPRA", "OPT",
    "ORGO", "ORIC", "ORTX", "OYST", "PACB", "PASG", "PBYI", "PDSB", "PEN", "PETS",
    "PFE", "PHAR", "PHAT", "PIRS", "PLRX", "PLSE", "PLX", "PNT", "PODD", "PRDS",
    "PRFX", "PRGO", "PRLD", "PRTA", "PRTC", "PRTG", "PSNL", "PSTV", "PTCT", "PTPI",
    "PYXS", "QGEN", "QNRX", "QURE", "RARE", "RCEL", "RCKT", "RDFN", "RDHL", "RDUS",
    "REGN", "REPL", "REPX", "RETA", "RGEN", "RGNX", "RIGL", "RLAY", "RLMD", "RNA",
    "RNAZ", "ROIV", "RPRX", "RVMD", "RXDX", "RXRX", "RYTM", "SABS", "SAGE", "SAVA",
    "SBFG", "SCPH", "SDGR", "SEER", "SGEN", "SGFY", "SGMO", "SGRY", "SHCR", "SIGA",
    "SLDB", "SLGN", "SLNO", "SLRX", "SMMT", "SNDX", "SNES", "SNGX", "SNOA", "SNSE",
    "SNY", "SPRO", "SRDX", "SRG", "SRPT", "SRRK", "STOK", "STRO", "STRY", "SURG",
    "SVRA", "SWAV", "SWTX", "SXTC", "SYK", "TARA", "TARS", "TCRR", "TDOC", "TENX",
    "TFC", "TGTX", "TIL", "TLIS", "TLRY", "TLSI", "TLX", "TMCI", "TMDX", "TMO",
    "TNGX", "TNXP", "TPTX", "TRDA", "TRHC", "TRIB", "TRIL", "TRMD", "TRVI", "TRX",
    "TSHA", "TSVT", "TVTX", "TWST", "TYRA", "UBX", "UTHR", "VANI", "VCEL", "VCNX",
    "VCYT", "VECT", "VEEV", "VERA", "VERV", "VIR", "VMD", "VNDA", "VOR", "VRAY",
    "VRDN", "VREX", "VRNA", "VRTX", "VSCO", "VSTM", "VTRS", "VTYX", "VVOS", "VVPR",
    "VYNE", "WAT", "WBA", "WST", "WVE", "XBIT", "XENE", "XERS", "XFOR", "XGN",
    "XLO", "XOMA", "XRX", "XYLG", "YMAB", "ZGNX", "ZIMV", "ZIVO", "ZLAB", "ZNTL",
    "ZSAN", "ZURA", "ZVRA", "ZYNE", "AAON", "AAWW", "ACA", "ACCO", "AEIS", "AGCO",
    "AIN", "AIR", "AIT", "ALG", "ALLE", "ALSN", "ALV", "AMRC", "AMWD", "AMSC",
    "AOS", "APAM", "APOG", "AQUA", "ARCB", "ARW", "ASGN", "ASIX", "ASTE", "ATKR",
    "ATR", "AVAV", "AYI", "AZZ", "B", "BCC", "BDC", "BECN", "BLBD", "BLDR",
    "BMI", "BNED", "BOOM", "BRC", "BRO", "BWA", "BWXT", "CASS", "CCOI", "CDRE",
    "CECO", "CIR", "CLH", "CMC", "CMCO", "CMRE", "CNHI", "CNM", "CNXC", "CR",
    "CRAI", "CRS", "CSL", "CSX", "CTAS", "CTRE", "CUB", "CVCO", "CW", "DBD",
    "DCO", "DCT", "DE", "DGII", "DIN", "DLB", "DLX", "DOOR", "DOV", "DRI",
    "DRQ", "DTM", "DV", "DXPE", "DY", "EAF", "EME", "EMR", "EPAC", "ESE",
    "EVER", "EXP", "EXPO", "FAST", "FBHS", "FCN", "FDX", "FELE", "FIX", "FLR",
    "FLS", "FOE", "FORM", "FOUR", "FSS", "FUL", "FWRG", "GBX", "GD", "GE",
    "GEF", "GFF", "GHM", "GIB", "GMS", "GNRC", "GPI", "GPK", "GTLS", "GWW",
    "HCC", "HEES", "HEI", "HII", "HOFT", "HRI", "HSC", "HUBB", "HWKN", "HXL",
    "IBP", "IDA", "IEX", "IIIN", "INGR", "INSW", "ITT", "ITW", "JBI", "JBL",
    "JBLU", "JCI", "JOE", "KAI", "KALU", "KAR", "KBR", "KEX", "KHRX", "KMT",
    "KNX", "KOP", "KRC", "LAD", "LDOS", "LECO", "LMT", "LNN", "LOGI", "LPX",
    "LRMR", "MAS", "MASI", "MATW", "MBUU", "MCRN", "MEG", "MHK", "MILE", "MMS",
    "MPAA", "MRC", "MRCY", "MSM", "MTRN", "MTX", "MYRG", "NDSN", "NJR", "NOC",
    "NOG", "NPO", "NSSC", "NVEE", "NX", "NXST", "OII", "OLN", "ORN", "OSIS",
    "OSK", "OTTR", "PBI", "PCAR", "PCG", "PCH", "PCTI", "PFG", "PGR", "PH",
    "PII", "PKG", "PKOH", "PKX", "PLOW", "PLPC", "PNR", "POWL", "PPC", "PRLB",
    "PRMW", "PWR", "PZZA", "RBC", "RBLX", "REVG", "RHI", "RKLB", "RMD", "ROLL",
    "ROP", "RRX", "RXO", "SAIA", "SAIC", "SCL", "SCS", "SEAS", "SEE", "SITE",
    "SLB", "SLG", "SM", "SMG", "SMID", "SMR", "SNA", "SNAP", "SNDR", "SNEX",
    "SNV", "SON", "SPAR", "SPCE", "SPGI", "SPH", "SPR", "SR", "SSD", "SSP",
    "SSTK", "STE", "STKL", "STKS", "STN", "STRL", "SUM", "SUPV", "SVNDY", "SWX",
    "SXI", "SXT", "SYRE", "TBI", "TCS", "TDS", "TDW", "TER", "TEX", "TGI",
    "THRM", "TKR", "TMHC", "TNL", "TOL", "TPL", "TR", "TREX", "TRN", "TROX",
    "TRTN", "TRV", "TSCO", "TT", "TTC", "TTEK", "TTI", "TUYA", "TWI", "TXT",
    "UHAL", "UMC", "UMH", "UNF", "UNFI", "UNVR", "USAP", "USFD", "USPH", "VC",
    "VEC", "VMI", "VNT", "VPG", "VRA", "VSH", "VTOL", "VVI", "WAB", "WCC",
    "WD", "WDFC", "WGO", "WHD", "WHR", "WIRE", "WMT", "WSC", "WSO", "WTI",
    "X", "XHR", "XYL", "ZEUS", "ZWS", "AE", "AESI", "AROC", "BORR", "BTU",
    "CDEV", "CEIX", "CHK", "CHRD", "CIVI", "CLNE", "CLR", "CNQ", "COG", "CPE",
    "CRC", "CRGY", "CRK", "CVI", "DK", "DMLP", "EGY", "ELLO", "EOG", "EPM",
    "EPSN", "ESTE", "ET", "EVRG", "FANG", "FET", "FRO", "GLNG", "GLP", "GPOR",
    "GPRE", "GRIN", "HAL", "HES", "HLX", "HP", "KOS", "LBRT", "LPI", "MGY",
    "MNRL", "MRO", "MTDR", "MUR", "NBR", "NEX", "NFE", "OAS", "OIS", "OVV",
    "OXY", "PAA", "PARR", "PBA", "PBF", "PDS", "PEY", "PHX", "PR", "PXD",
    "RES", "REX", "RIG", "RNW", "RRC", "SBOW", "SD", "SES", "SOI", "SPN",
    "SU", "SUN", "SWN", "TALO", "TAP", "TGS", "TRGP", "USAC", "VAL", "VET",
    "VG", "VIST", "VLO", "VNOM", "VOC", "VTLE", "WLL", "WMB", "XEC", "XOM",
    "AAT", "ACC", "ACRE", "ADC", "AHH", "AHT", "AIRC", "AIV", "AKR", "ALEX",
    "AMH", "AMT", "APLE", "ARE", "ARI", "ARR", "AVB", "AXR", "BDN", "BFS",
    "BRG", "BRT", "BRX", "BXMT", "BXP", "CDR", "CHCT", "CIO", "CLDT", "CLI",
    "CLNY", "CMCT", "COLD", "CONE", "CPA", "CPT", "CSR", "CTT", "CUBE", "CUZ",
    "CXP", "DBRG", "DEA", "DEI", "DKS", "DLR", "DOC", "DRE", "DRH", "EARN",
    "EDR", "EGP", "ELS", "EPR", "EPRT", "EQC", "EQIX", "EQR", "ESS", "EXR",
    "FCPT", "FCR", "FRT", "GEO", "GLPI", "GMRE", "GNL", "GOOD", "GPMT", "GTY",
    "HASI", "HIW", "HPP", "HR", "HRZN", "HST", "HTA", "INDS", "INN", "INVH",
    "IRM", "IRT", "JBGS", "KIM", "KRG", "LAMR", "LAND", "LSI", "LTC", "MAA",
    "MAC", "MFA", "MGP", "MPW", "NHI", "NLY", "NNN", "NREF", "NRZ", "NSA",
    "O", "OFC", "OHI", "OLP", "ONL", "OPI", "ORC", "OUT", "PDM", "PEAK",
    "PEI", "PINE", "PK", "PLD", "PLYM", "PMT", "POST", "PSA", "PSB", "PTLO",
    "QTS", "RBA", "RC", "REG", "REXR", "RHP", "RITM", "ROIC", "RPT", "RWT",
    "RYN", "SAFE", "SBAC", "SBLK", "SBRA", "SHO", "SNR", "SPG", "SRC", "SRT",
    "STAG", "STOR", "STRS", "STWD", "SUI", "TCN", "TRC", "TRNO", "TWO", "UDR",
    "URE", "USRT", "UTL", "VER", "VICI", "VNO", "VTR", "WELL", "WPC", "WPG",
    "WRE", "WSR", "WY", "AAP", "ABG", "ACI", "ACU", "AEO", "ALCO", "AMC",
    "AN", "ANF", "ANGO", "ARCO", "ASO", "BAH", "BBBY", "BBI", "BBW", "BBWI",
    "BBY", "BC", "BCAB", "BCAT", "BFAM", "BFB", "BIG", "BJ", "BJRI", "BKE",
    "BKI", "BLMN", "BOOT", "BOWX", "BRBR", "BRCC", "BRP", "BURL", "BV", "CAKE",
    "CAL", "CART", "CASY", "CATO", "CCK", "CCO", "CCS", "CENT", "CENTA", "CHDN",
    "CHE", "CHEF", "CHGG", "CHH", "CHS", "CHUY", "CHWY", "CINF", "CKE", "CLAR",
    "CMG", "CNK", "COKE", "CONN", "COOK", "COTY", "CPB", "CPRI", "CRI", "CROX",
    "CTRN", "CVNA", "CWH", "DAR", "DASH", "DBI", "DDS", "DECK", "DENN", "DG",
    "DLTR", "DNUT", "DOOO", "DORM", "DPZ", "DRVN", "DTC", "EAT", "EBAY", "ELY",
    "EML", "EVH", "EXPR", "FBM", "FDS", "FIVE", "FIVN", "FL", "FLO", "FLWS",
    "FND", "FOSL", "FOXA", "FOXF", "FPI", "FUN", "GBT", "GCO", "GES", "GIII",
    "GMTX", "GNTX", "GOOS", "GPC", "GPS", "GRBK", "H", "HAS", "HBI", "HD",
    "HEAR", "HELE", "HHC", "HLF", "HLT", "HMHC", "HMY", "HNI", "HOG", "HSY",
    "HTHT", "HWM", "HZO", "IAC", "IBKR", "ICUI", "IDEX", "IEP", "IPAR", "IRBT",
    "JACK", "JBSS", "JILL", "JWN", "KIRK", "KMX", "KO", "KSS", "KTB", "LAUR",
    "LB", "LCII", "LE", "LEA", "LEG", "LESL", "LEVI", "LGIH", "LITM", "LOCO",
    "LOW", "LULU", "LVS", "LYV", "M", "MAR", "MAT", "MCD", "MCFT", "MED",
    "MGM", "MIK", "MNST", "MO", "MODG", "MOV", "MPB", "MTH", "MTN", "MUSA",
    "NAPA", "NCLH", "NIC", "NKE", "NLS", "NOMD", "NVT", "NWL", "NWSA", "NYT",
    "ODP", "OLLI", "OMC", "ONEW", "ONON", "ORLY", "OSW", "OXM", "PAG", "PBH",
    "PG", "PLAY", "PLBY", "PLYA", "PM", "POOL", "PRDO", "PRTS", "PVH", "QSR",
    "RACE", "RCII", "RCKY", "RCL", "REAL", "REAX", "RENT", "RH", "RICK", "RIDE",
    "RL", "RNG", "ROST", "RRGB", "RVLV", "SCI", "SCVL", "SFM", "SHAK", "SIGI",
    "SITC", "SIX", "SJM", "SKIN", "SKX", "SNBR", "SONO", "SPLK", "SPWH", "SQM",
    "STZ", "SVU", "SYY", "TACT", "TACO", "TGT", "TH", "TJX", "TPR", "TRIP",
    "TROW", "TRP", "TSLA", "TWNK", "TWX", "TXRH", "UAA", "UA", "UFCS", "ULTA",
    "UPS", "URBN", "VFC", "VIK", "VRSN", "VRTV", "VSTO", "VTNR", "WBD", "WEN",
    "WH", "WING", "WMK", "WOOF", "WSM", "WW", "WWE", "WWW", "WYND", "YETI",
    "YUM", "YUMC", "ZUMZ", "AA", "AGI", "ALB", "AMR", "APD", "ARLP", "ASH",
    "ASTL", "ATI", "AVNT", "AXTA", "BCPC", "BHP", "BMS", "BPMP", "CABO", "CAR",
    "CBT", "CE", "CENX", "CF", "CG", "CLF", "CLW", "CMP", "CMT", "CNX",
    "CRH", "CRMT", "CSTM", "CTVA", "DD", "DOW", "ECL", "EMN", "ESI", "EVA",
    "FCX", "FF", "FMC", "GGB", "GOLD", "GREE", "HAYW", "HBM", "HTLD", "HUN",
    "IFF", "IOSP", "IP", "IPI", "KWR", "LIN", "LYB", "MERC", "MLM", "MOS",
    "MP", "MPLX", "MSB", "NAT", "NEM", "NEU", "NGD", "NTR", "NUE", "OEC",
    "OLIN", "ORA", "ORI", "PHM", "PLL", "POL", "POR", "PPG", "PPL", "PSX",
    "RGLD", "RIO", "ROK", "RPM", "RS", "RYAM", "SAVE", "SHW", "SIM", "SIRI",
    "SSL", "STER", "STM", "SXC", "SYNH", "THC", "THO", "TRMB", "TS", "TSE",
    "TUP", "TX", "UAN", "UEC", "USCR", "USU", "VMC", "WLK", "WPM", "WPRT",
    "WRK", "WS",
]


# --- list registry ----------------------------------------------------------
LISTS: dict[str, list[str]] = {
    "sp500": SP500,
    "dow": DOW30,
    "nasdaq": NASDAQ,
    "russell2000": RUSSELL2000,
    "tsx": TSX,
}

LIST_LABELS: dict[str, str] = {
    "sp500": "S&P 500",
    "dow": "Dow 30",
    "nasdaq": "Nasdaq",
    "russell2000": "Russell 2000",
    "tsx": "TSX",
}


def _membership_index() -> dict[str, set[str]]:
    out: dict[str, set[str]] = {}
    for key, members in LISTS.items():
        for sym in members:
            out.setdefault(sym, set()).add(key)
    return out


_MEMBERSHIP = _membership_index()


def lists_for(ticker: str) -> list[str]:
    """Return list-keys that this ticker belongs to (e.g. ['sp500','dow'])."""
    return sorted(_MEMBERSHIP.get(ticker, set()))


def list_labels(keys: list[str]) -> list[str]:
    return [LIST_LABELS[k] for k in keys if k in LIST_LABELS]


def universe(selected: list[str] | None = None) -> list[str]:
    """Tickers belonging to any of `selected` lists (de-duplicated, ordered).

    Pass `None` or an empty list to get the union of every known list.
    """
    if not selected:
        selected = list(LISTS.keys())
    seen: set[str] = set()
    out: list[str] = []
    for key in selected:
        for sym in LISTS.get(key, []):
            if sym not in seen:
                seen.add(sym)
                out.append(sym)
    return out


def all_tickers() -> list[str]:
    """Backwards-compatible: union of all lists."""
    return universe(None)


def display_symbol(ticker: str) -> str:
    """Strip exchange suffixes for display purposes."""
    if ticker.endswith(".TO"):
        return ticker[:-3] + ".TO"
    return ticker
