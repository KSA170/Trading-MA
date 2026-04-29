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

# --- Nasdaq-100 (curated; ~100 names, may drift) ----------------------------
NDX100: list[str] = [
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

# --- list registry ----------------------------------------------------------
LISTS: dict[str, list[str]] = {
    "sp500": SP500,
    "dow": DOW30,
    "nasdaq100": NDX100,
    "tsx": TSX,
}

LIST_LABELS: dict[str, str] = {
    "sp500": "S&P 500",
    "dow": "Dow 30",
    "nasdaq100": "Nasdaq 100",
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
