"""
Universe of US and Canadian stock tickers used by the screener.

The lists below cover the S&P 500 (US) and the most actively traded TSX
constituents (Canada). yfinance expects Canadian tickers with a `.TO`
suffix.
"""

# S&P 500 components (curated, may drift slightly over time).
US_TICKERS = [
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

# Most-traded TSX listings (large-cap & active mid-cap). yfinance suffix `.TO`.
CA_TICKERS_BASE = [
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

CA_TICKERS = [t + ".TO" for t in CA_TICKERS_BASE]


def all_tickers():
    """Return the combined US + Canadian universe."""
    seen = set()
    out = []
    for t in US_TICKERS + CA_TICKERS:
        if t not in seen:
            seen.add(t)
            out.append(t)
    return out


def display_symbol(ticker: str) -> str:
    """Strip exchange suffixes for display purposes."""
    if ticker.endswith(".TO"):
        return ticker[:-3] + ".TO"
    return ticker
