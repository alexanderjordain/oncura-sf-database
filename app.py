"""Oncura — Salesforce Lookup
Internal sales reference app, runs against the SF backup snapshot.

Run: streamlit run oncura_sf_app.py --server.address 0.0.0.0 --server.port 8501
"""
from __future__ import annotations
import os
import sqlite3
from datetime import datetime
import pandas as pd
import streamlit as st

LOGO_PATH = os.path.join(os.path.dirname(__file__), "assets", "oncura_logo.png")
SNAPSHOT_DATE = "2026-03-25"

st.set_page_config(
    page_title="Oncura — Salesforce Lookup",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ── Resolve the SQLite DB (downloaded from a GitHub Release on first run) ──
DB_URL = os.environ.get(
    "ONCURA_DB_URL",
    "https://github.com/alexanderjordain/oncura-sf-database/releases/download/snapshot-2026-03-25/oncura_sf_lookup_lite.db",
)
DB_LOCAL_OVERRIDE = os.environ.get("ONCURA_DB_PATH")

def _resolve_db_path() -> str:
    if DB_LOCAL_OVERRIDE and os.path.exists(DB_LOCAL_OVERRIDE):
        return DB_LOCAL_OVERRIDE
    # Versioned filename so a schema change invalidates the cache automatically.
    target = os.path.join(os.path.expanduser("~"), ".oncura_sf_lookup_v7.db")
    MIN_BYTES = 940_000_000  # the v7 DB is ~958 MB; partials are unusable
    if os.path.exists(target) and os.path.getsize(target) >= MIN_BYTES:
        # Sanity check: can SQLite open it + does it have the expected columns?
        try:
            import sqlite3 as _sq
            _c = _sq.connect(target)
            _c.execute("SELECT AccountId FROM attachments LIMIT 1")
            _c.execute("SELECT 1 FROM maps_routes LIMIT 1")
            _c.close()
            return target
        except Exception:
            try: os.remove(target)
            except Exception: pass

    import urllib.request, tempfile, shutil
    info = st.empty()
    info.info("Loading the Salesforce snapshot database… (first launch only, ~960 MB — takes 1–2 min)")
    tmp = target + ".tmp"
    try:
        with urllib.request.urlopen(DB_URL) as r, open(tmp, "wb") as out:
            while True:
                chunk = r.read(1 << 20)
                if not chunk: break
                out.write(chunk)
        # Verify size before promoting to final path
        if os.path.getsize(tmp) < MIN_BYTES:
            raise RuntimeError(f"download incomplete: only {os.path.getsize(tmp):,} bytes")
        shutil.move(tmp, target)
    except Exception as e:
        try: os.remove(tmp)
        except Exception: pass
        info.error(f"Failed to fetch the database: {e}")
        raise
    info.empty()
    return target

DB_PATH = _resolve_db_path()

# ───────────────────── styling ─────────────────────
_CSS = """
<style>
@import url('https://fonts.googleapis.com/css2?family=Fraunces:opsz,wght@9..144,400;9..144,500;9..144,600;9..144,700&family=Hanken+Grotesk:wght@400;500;600;700&family=IBM+Plex+Mono:wght@400;500;600&display=swap');

:root {
  --canvas:#F0F2F4; --surface:#FFFFFF; --ink:#2A3742; --blue:#3A6A9A;
  --blue-deep:#2F567E; --green:#469B68; --amber:#E3A033; --muted:#6B7785; --line:#E2E6EA;
  --serif:'Fraunces',Georgia,serif; --sans:'Hanken Grotesk',-apple-system,sans-serif;
  --mono:'IBM Plex Mono',ui-monospace,monospace;
}
.stApp {
  background:
    radial-gradient(900px 520px at 90% -10%, rgba(58,106,154,.06), transparent 60%),
    radial-gradient(720px 480px at -6% 6%, rgba(70,155,104,.05), transparent 55%),
    var(--canvas);
}
html, body, [class*="css"], .stApp, p, li, label, .stMarkdown { font-family: var(--sans); color: var(--ink); }
h1, h2, h3, h4 { font-family: var(--serif) !important; color: var(--blue) !important; letter-spacing:-.01em; font-weight:600; }

.oncura-head { margin:.2rem 0 1.4rem 0; padding:.1rem 0 1rem 1rem; border-bottom:1px solid var(--line); border-left:4px solid var(--green); }
.oncura-head .kicker { font-family:var(--mono); text-transform:uppercase; letter-spacing:.28em; font-size:.7rem; color:var(--amber); margin-bottom:.5rem; }
.oncura-head h1 { font-size:2.4rem; line-height:1.05; margin:0; color:var(--blue) !important; }
.oncura-head .sub { font-family:var(--sans); color:var(--muted); font-size:1rem; margin:.5rem 0 0 0; max-width:62ch; }

[data-testid="stMetric"] {
  background:var(--surface); border:1px solid var(--line);
  border-left:3px solid var(--blue); border-radius:6px;
  padding:.85rem 1rem; box-shadow:0 1px 3px rgba(42,55,66,.05);
}
[data-testid="stMetricLabel"] p {
  font-family:var(--mono) !important; text-transform:uppercase;
  letter-spacing:.12em; font-size:.66rem !important; color:var(--muted) !important;
}
[data-testid="stMetricValue"] {
  font-family:var(--mono) !important; font-weight:600;
  font-variant-numeric:tabular-nums; color:var(--blue) !important; letter-spacing:-.01em;
}

.stButton > button,
.stDownloadButton > button {
  background:#FFFFFF !important; color:#1F3D5C !important;
  border:1.5px solid #1F3D5C !important;
  font-family:var(--sans) !important; font-weight:700 !important;
  border-radius:6px; transition:transform .08s ease, box-shadow .15s ease, background .15s ease;
}
.stButton > button:hover, .stDownloadButton > button:hover {
  background:#EAF2FA !important; transform:translateY(-1px);
  box-shadow:0 4px 14px rgba(31,61,92,.18);
}
.stButton > button:disabled, .stDownloadButton > button:disabled {
  background:#F3F4F6 !important; border-color:#D1D5DB !important; color:#9CA3AF !important;
}
.stButton > button[kind="primary"], .stDownloadButton > button[kind="primary"] {
  background:#FFFFFF !important; color:#1F3D5C !important;
  border:1.5px solid #1F3D5C !important; font-weight:700 !important; box-shadow:none !important;
}
.stButton > button[kind="primary"]:hover, .stDownloadButton > button[kind="primary"]:hover {
  background:#EAF2FA !important; transform:translateY(-1px); box-shadow:0 4px 14px rgba(31,61,92,.18) !important;
}

section[data-testid="stSidebar"] { background:var(--surface); border-right:1px solid var(--line); }
section[data-testid="stSidebar"] p, section[data-testid="stSidebar"] label, section[data-testid="stSidebar"] .stMarkdown { font-family:var(--sans); }

[data-testid="stIconMaterial"], span.material-icons, span.material-symbols-rounded {
  font-family:'Material Symbols Rounded','Material Symbols Outlined','Material Icons' !important;
}

code, pre, .stCode { font-family:var(--mono) !important; }

/* ── Tables ──────────────────────────────────────────────────────────── */
[data-testid="stDataFrame"], [data-testid="stTable"] {
  border: 1px solid var(--line);
  border-radius: 6px;
  overflow: hidden;
  background: var(--surface);
}
/* The glide-data-grid header row */
[data-testid="stDataFrame"] div[role="columnheader"],
[data-testid="stTable"] thead th {
  background: #F4F7FA !important;
  color: var(--muted) !important;
  font-family: var(--sans) !important;
  font-size: 0.72rem !important;
  font-weight: 700 !important;
  text-transform: uppercase !important;
  letter-spacing: 0.10em !important;
  border-bottom: 1px solid var(--line) !important;
}
/* Body cells: tabular mono for clean column alignment of $ and IDs */
[data-testid="stDataFrame"] div[role="gridcell"],
[data-testid="stTable"] tbody td {
  font-family: var(--mono) !important;
  font-variant-numeric: tabular-nums;
  font-size: 0.84rem !important;
  color: var(--ink) !important;
  border-bottom: 1px solid #F0F2F4 !important;
}
/* Row hover */
[data-testid="stDataFrame"] div[role="row"]:hover div[role="gridcell"],
[data-testid="stTable"] tbody tr:hover td {
  background: #F4F8FB !important;
}
/* Selected row in interactive dataframe */
[data-testid="stDataFrame"] div[role="row"][aria-selected="true"] div[role="gridcell"] {
  background: rgba(58,106,154,.10) !important;
}
/* Pinned/header row protection */
[data-testid="stDataFrame"] div[role="row"]:first-child div[role="columnheader"] {
  font-family: var(--sans) !important;
}
/* st.table (used rarely) */
[data-testid="stTable"] { font-size: 0.85rem; }
[data-testid="stTable"] thead th { padding: .55rem .6rem !important; }
[data-testid="stTable"] tbody td { padding: .5rem .6rem !important; }

a, a:visited { color:var(--blue-deep); text-decoration-color:var(--amber); }
[data-testid="stExpander"] { border:1px solid var(--line); border-radius:6px; background:var(--surface); }

[data-testid="stHeader"] { background: var(--surface) !important; border-bottom:1px solid var(--line); }
[data-baseweb="tab-list"] { gap: 2.25rem; }
button[data-baseweb="tab"] { padding-left: .25rem; padding-right: .25rem; }
[data-testid="stDecoration"] { display:none; }
footer { visibility:hidden; }

.oncura-mark { font-family:var(--serif); font-weight:700; font-size:1.35rem; color:var(--blue); letter-spacing:-.02em; line-height:1; }
.oncura-mark .dot { color:var(--green); }
.oncura-mark-sub { font-family:var(--mono); text-transform:uppercase; letter-spacing:.2em; font-size:.6rem; color:var(--muted); margin-top:.3rem; }
.oncura-rule { height:1px; background:var(--line); margin:.7rem 0 1rem 0; }

/* ── Pills + cards (Salesforce-flavored detail view) ─────────────────── */
.partner-pill { display:inline-block; padding:.05rem .55rem; border-radius:999px; background:#DFF5E1; color:#1B6E3A; font-weight:600; font-size:.78rem; font-family:var(--sans); }
.lead-pill    { display:inline-block; padding:.05rem .55rem; border-radius:999px; background:#F2F2F2; color:#6B7785; font-weight:500; font-size:.78rem; font-family:var(--sans); }

/* Stage badges on opportunities */
.stage-won  { display:inline-block; padding:.1rem .55rem; border-radius:999px; background:#DFF5E1; color:#1B6E3A; font-weight:600; font-size:.78rem; font-family:var(--sans); }
.stage-lost { display:inline-block; padding:.1rem .55rem; border-radius:999px; background:#F4B6B6; color:#B23A3A; font-weight:600; font-size:.78rem; font-family:var(--sans); }
.stage-open { display:inline-block; padding:.1rem .55rem; border-radius:999px; background:#E1ECF7; color:#2F567E; font-weight:600; font-size:.78rem; font-family:var(--sans); }

/* Highlights row on clinic detail */
.highlights {
  display:grid; grid-template-columns:repeat(4, 1fr); gap:.65rem; margin-bottom:1rem;
}
.highlight-card {
  background:var(--surface); border:1px solid var(--line); border-left:3px solid var(--blue);
  border-radius:6px; padding:.65rem .85rem;
}
.highlight-card .label {
  font-family:var(--mono); text-transform:uppercase; letter-spacing:.10em;
  font-size:.62rem; color:var(--muted); margin-bottom:.2rem;
}
.highlight-card .value {
  font-family:var(--sans); font-weight:600; color:var(--ink); font-size:.95rem; line-height:1.25;
}

/* Contact cards */
.contact-card {
  background:var(--surface); border:1px solid var(--line); border-radius:6px;
  padding:.75rem .9rem; margin-bottom:.45rem; display:grid;
  grid-template-columns:auto 1fr; gap:.85rem; align-items:center;
}
.contact-card:hover { border-color: var(--blue); box-shadow:0 1px 4px rgba(47,86,126,.08); }
.contact-avatar {
  width:38px; height:38px; border-radius:999px; background:#E1ECF7; color:var(--blue-deep);
  display:flex; align-items:center; justify-content:center; font-weight:700;
  font-family:var(--sans); font-size:.85rem;
}
.contact-name { font-family:var(--sans); font-weight:600; color:var(--ink); font-size:.95rem; }
.contact-title { font-family:var(--sans); color:var(--muted); font-size:.78rem; margin-top:.1rem; }
.contact-meta { font-family:var(--mono); color:var(--muted); font-size:.78rem; margin-top:.15rem; }
.contact-meta a { color: var(--blue-deep); }

/* ── Sidebar nav (Pass-Through / Rebate Ledger styling) ──────────────── */
section[data-testid="stSidebar"] .stButton > button {
  background: transparent !important;
  border: none !important;
  color: var(--ink) !important;
  padding: .5rem .65rem !important;
  border-radius: 8px !important;
  font-family: var(--sans) !important;
  font-weight: 500 !important;
  font-size: .95rem !important;
  width: 100% !important;
  box-shadow: none !important;
  transition: background .12s ease, color .12s ease !important;
  display: flex !important;
  justify-content: flex-start !important;
  text-align: left !important;
}
/* Force the inner span (where the label text lives) to also left-align */
section[data-testid="stSidebar"] .stButton > button > div,
section[data-testid="stSidebar"] .stButton > button p,
section[data-testid="stSidebar"] .stButton > button span {
  text-align: left !important;
  justify-content: flex-start !important;
  width: 100% !important;
}
section[data-testid="stSidebar"] .stButton > button:hover {
  background: rgba(58,106,154,.07) !important;
  color: var(--blue) !important;
  transform: none !important;
}
/* Active nav item indicated by [active] marker on the button label */
section[data-testid="stSidebar"] .stButton > button[kind="primary"] {
  background: rgba(58,106,154,.12) !important;
  color: var(--blue) !important;
  font-weight: 600 !important;
  border: none !important;
}
section[data-testid="stSidebar"] .stButton > button[kind="primary"]:hover {
  background: rgba(58,106,154,.18) !important;
  color: var(--blue-deep) !important;
}

/* ── Search result rows (Salesforce-style clickable list) ───────────── */
a.result-row, a.result-row:visited {
  display:grid; grid-template-columns: 1fr auto;
  align-items:center; gap:1rem;
  padding:.75rem 1rem; margin-bottom:.4rem;
  background:var(--surface); border:1px solid var(--line); border-left:3px solid transparent;
  border-radius:6px;
  text-decoration:none; color:inherit;
  transition: border-color .12s ease, background .12s ease, box-shadow .12s ease, transform .04s ease;
  cursor:pointer;
}
a.result-row:hover {
  border-left-color: var(--blue);
  background:#F4F8FB;
  box-shadow:0 2px 6px rgba(47,86,126,.10);
  text-decoration:none;
}
a.result-row:hover .clinic-link { text-decoration: underline; }
a.result-row .name-row {
  display:flex; align-items:center; gap:.65rem; flex-wrap:wrap;
}
a.result-row .clinic-link {
  font-family:var(--sans); font-weight:600; font-size:1rem;
  color:var(--blue-deep); text-decoration:none;
}
a.result-row .secondary {
  font-family:var(--mono); font-size:.78rem; color:var(--muted); margin-top:.25rem;
}
a.result-row .secondary .sep { color:#C0C7CF; margin:0 .3rem; }
a.result-row .stats {
  display:flex; gap:.65rem; flex-shrink:0;
}
a.result-row .stat {
  text-align:right;
  font-family:var(--sans); font-size:.78rem; color:var(--muted);
}
a.result-row .stat .v {
  display:block;
  font-family:var(--mono); font-weight:600; font-size:.95rem; color:var(--ink);
}

/* Activity timeline */
.timeline-row {
  display:grid; grid-template-columns:90px 1fr; gap:1rem;
  padding:.7rem 0; border-bottom:1px solid var(--line);
}
.timeline-row:last-child { border-bottom: none; }
.timeline-date {
  font-family:var(--mono); font-size:.78rem; color:var(--muted);
  padding-top:.1rem; text-align:right;
}
.timeline-card {
  background:var(--surface); border:1px solid var(--line);
  border-left:3px solid var(--blue); border-radius:6px;
  padding:.6rem .8rem;
}
.timeline-subject { font-family:var(--sans); font-weight:600; color:var(--ink); font-size:.92rem; }
.timeline-meta    { font-family:var(--mono); font-size:.72rem; color:var(--muted); margin-top:.25rem; }
.timeline-card.task-completed { border-left-color: var(--green); }
.timeline-card.task-open      { border-left-color: var(--amber); }
.timeline-card.email          { border-left-color: var(--blue); }
</style>
"""

def inject():
    st.markdown(_CSS, unsafe_allow_html=True)

def header(title: str, subtitle: str = "", kicker: str = "ONCURA · SALESFORCE LOOKUP"):
    sub = f'<p class="sub">{subtitle}</p>' if subtitle else ""
    st.markdown(
        f'<div class="oncura-head"><div class="kicker">{kicker}</div>'
        f"<h1>{title}</h1>{sub}</div>",
        unsafe_allow_html=True,
    )

def sidebar_brand():
    if os.path.exists(LOGO_PATH) and hasattr(st, "logo"):
        try:
            st.logo(LOGO_PATH, size="large")
        except Exception:
            pass
    st.sidebar.markdown(
        '<div class="oncura-mark-sub">Salesforce &middot; Lookup</div>'
        '<div class="oncura-rule"></div>',
        unsafe_allow_html=True,
    )

def render_sidebar_nav(pages):
    """Render a clean nav (one button per page) matching the FLEX/Rebate sidebar."""
    # __page is the source of truth for which page is active.
    # __page_pending is set by callers (goto_search / goto_detail / nav-button click)
    # and reconciled here at top of script so we never mutate widget-bound keys mid-render.
    if "__page" not in st.session_state:
        st.session_state["__page"] = pages[0]
    if "__page_pending" in st.session_state:
        st.session_state["__page"] = st.session_state.pop("__page_pending")
    current = st.session_state["__page"]
    with st.sidebar:
        for label in pages:
            is_active = (label == current)
            if st.button(label, key=f"nav_btn_{label}",
                         type=("primary" if is_active else "secondary"),
                         use_container_width=True):
                if not is_active:
                    st.session_state["__page_pending"] = label
                    st.rerun()
        st.markdown('<div class="oncura-rule" style="margin-top:1.25rem;"></div>',
                    unsafe_allow_html=True)
        st.caption(f":gray[Snapshot · {SNAPSHOT_DATE}]")
    return current

inject()
sidebar_brand()

# ───────────────────── DB ─────────────────────
@st.cache_resource
def get_conn():
    con = sqlite3.connect(DB_PATH, check_same_thread=False)
    con.row_factory = sqlite3.Row
    return con

@st.cache_data(ttl=3600)
def q(sql, params=()):
    return pd.read_sql_query(sql, get_conn(), params=params)

@st.cache_data(ttl=3600)
def one(sql, params=()):
    cur = get_conn().execute(sql, params)
    row = cur.fetchone()
    return dict(row) if row else None

@st.cache_data(ttl=3600)
def kpis():
    c = get_conn()
    return {
        "accounts":  c.execute("SELECT COUNT(*) FROM accounts WHERE IsDeleted=0").fetchone()[0],
        "partners":  c.execute("SELECT COUNT(*) FROM accounts WHERE IsDeleted=0 AND Partner=1").fetchone()[0],
        "contacts":  c.execute("SELECT COUNT(*) FROM contacts WHERE IsDeleted=0").fetchone()[0],
        "opps":      c.execute("SELECT COUNT(*) FROM opportunities").fetchone()[0],
        "tasks":     c.execute("SELECT COUNT(*) FROM tasks").fetchone()[0],
        "won_total": c.execute("SELECT COALESCE(SUM(Amount),0) FROM opportunities WHERE IsWon=1").fetchone()[0],
    }

# ───────────────────── helpers ─────────────────────
def fmt_money(v):
    if v is None or pd.isna(v): return "—"
    try: return f"${float(v):,.0f}"
    except: return "—"

def fmt_date(v):
    if not v: return "—"
    return str(v)[:10]

def goto_detail(acct_id):
    st.session_state["selected_account_id"] = acct_id
    st.session_state["__page_pending"] = "Clinic detail"
    st.rerun()

def goto_search():
    st.session_state["__page_pending"] = "Clinic search"
    st.rerun()

# ── URL-based navigation ─────────────────────────────────────────────
# If a clinic-detail link was clicked from search results, the URL becomes
# ?clinic=<account-id>. Detect that here at top of script and route.
_qp = st.query_params
if "clinic" in _qp:
    _cid = _qp["clinic"]
    st.query_params.clear()
    goto_detail(_cid)

def _safe(v, fallback=""):
    """Coerce pandas NaN/None to a string fallback so .slice/.startswith/etc. work."""
    try:
        if v is None: return fallback
        # pd.isna returns True for NaN/None/NaT
        import pandas as _pd
        if _pd.isna(v): return fallback
    except Exception:
        pass
    return v if isinstance(v, str) else str(v)

# ───────────────────── sidebar nav ─────────────────────
PAGES = ["Clinic search", "Clinic detail", "Sales activity", "Renewal radar"]
page = render_sidebar_nav(PAGES)

# ───────────────────── PAGE: Search ─────────────────────
def page_search():
    header(
        "Find a clinic",
        "Search the Salesforce snapshot by clinic name, hospital ID, city, phone, or SF account ID.",
    )

    with st.container(border=True):
        c1, c2, c3, c4 = st.columns([3, 1, 1, 1])
        search = c1.text_input(
            "Search",
            placeholder="Try 'Redstone', 'CPAC78613', 'Cedar Park', or a phone number",
            label_visibility="collapsed",
        )
        state_opts = ["All"] + sorted(
            [r["BillingState"] for r in q("SELECT DISTINCT BillingState FROM accounts WHERE BillingState IS NOT NULL AND BillingState!='' ORDER BY BillingState").to_dict("records")]
        )
        state = c2.selectbox("State", state_opts)
        partner = c3.selectbox("Partner", ["All", "Partner", "Non-Partner"])
        sys_opts = ["All"] + sorted(
            [r["Ultrasound_System"] for r in q("SELECT DISTINCT Ultrasound_System FROM accounts WHERE Ultrasound_System IS NOT NULL AND Ultrasound_System!='' ORDER BY Ultrasound_System").to_dict("records")]
        )
        system = c4.selectbox("Ultrasound", sys_opts)

    where = ["IsDeleted=0"]
    params = []
    if search:
        like = f"%{search}%"
        where.append(
            "(Name LIKE ? COLLATE NOCASE OR Hospital_ID LIKE ? COLLATE NOCASE "
            "OR BillingCity LIKE ? COLLATE NOCASE OR Phone LIKE ? OR Id LIKE ?)"
        )
        params += [like, like, like, like, like]
    if state != "All":
        where.append("BillingState = ?"); params.append(state)
    if partner == "Partner":
        where.append("Partner = 1")
    elif partner == "Non-Partner":
        where.append("Partner = 0")
    if system != "All":
        where.append("Ultrasound_System = ?"); params.append(system)

    sql = f"""
    SELECT a.Id, a.Name, a.Partner, a.Hospital_ID, a.BillingState, a.BillingCity,
           a.Phone, a.US_Install_Date, a.Ultrasound_System,
           (SELECT COUNT(*) FROM contacts c WHERE c.AccountId=a.Id AND c.IsDeleted=0) AS Contacts,
           (SELECT COUNT(*) FROM opportunities o WHERE o.AccountId=a.Id) AS Opps,
           (SELECT COALESCE(SUM(o.Amount),0) FROM opportunities o WHERE o.AccountId=a.Id AND o.IsWon=1) AS WonTotal
    FROM accounts a
    WHERE {' AND '.join(where)}
    ORDER BY a.Partner DESC, a.Name COLLATE NOCASE
    LIMIT 500
    """
    df = q(sql, tuple(params))
    total = len(df)
    if df.empty:
        st.info(":material/info: No matches — try a broader search.")
        return

    # Cap inline list at 50 rows so this renders fast for broad searches.
    LIST_CAP = 50
    head = df.head(LIST_CAP)
    rest_count = total - len(head)
    if total > LIST_CAP:
        st.caption(f":gray[Showing the top {LIST_CAP} of {total:,} matches. Refine your search to see the rest, or expand the table below.]")
    else:
        st.caption(f":gray[{total:,} matches]")

    import html as _html
    rows = []
    for _, r in head.iterrows():
        cid = _safe(r['Id'])
        name = _safe(r['Name'], '(no name)')
        partner = bool(r['Partner'])
        hid   = _safe(r['Hospital_ID'])
        state = _safe(r['BillingState'])
        city  = _safe(r['BillingCity'])
        phone = _safe(r['Phone'])
        installed = _safe(r['US_Install_Date'])
        system = _safe(r['Ultrasound_System'])
        contacts = int(r['Contacts'] or 0)
        opps     = int(r['Opps'] or 0)
        won      = float(r['WonTotal'] or 0)

        partner_html = '<span class="partner-pill">Partner</span>' if partner else '<span class="lead-pill">Non-Partner</span>'
        # Build secondary line: escape each value separately, never escape the separator
        secondary_parts = []
        if hid:   secondary_parts.append(f'<code>{_html.escape(hid)}</code>')
        loc_bits = [_html.escape(p) for p in [city, state] if p]
        if loc_bits: secondary_parts.append(' &middot; '.join(loc_bits))
        if phone: secondary_parts.append(_html.escape(phone))
        if installed: secondary_parts.append(f'Installed {_html.escape(installed)}')
        if system: secondary_parts.append(_html.escape(system))
        secondary = '<span class="sep">·</span>'.join(secondary_parts) or '—'

        rows.append(
            f'<a class="result-row" href="?clinic={_html.escape(cid)}" target="_self">'
            f'<div>'
            f'<div class="name-row">'
            f'<span class="clinic-link">{_html.escape(name)}</span>'
            f'{partner_html}'
            f'</div>'
            f'<div class="secondary">{secondary}</div>'
            f'</div>'
            f'<div class="stats">'
            f'<div class="stat">Contacts<span class="v">{contacts:,}</span></div>'
            f'<div class="stat">Opps<span class="v">{opps:,}</span></div>'
            f'<div class="stat">Won $<span class="v">${won:,.0f}</span></div>'
            f'</div>'
            f'</a>'
        )
    st.html(''.join(rows))

    # Full table view for users who prefer scanning / sorting all matches
    with st.expander(f":gray[Show all {total:,} as a sortable table]"):
        df_disp = df.copy()
        df_disp["Partner"] = df_disp["Partner"].map({1: "Partner", 0: "—"})
        df_disp = df_disp.rename(columns={
            "Name": "Clinic", "BillingState": "State", "BillingCity": "City",
            "Hospital_ID": "Hospital ID", "US_Install_Date": "Installed",
            "Ultrasound_System": "System", "WonTotal": "Closed-Won $", "Opps": "Opps",
        })[["Id", "Clinic", "Partner", "Hospital ID", "State", "City", "Phone", "Installed", "System", "Contacts", "Opps", "Closed-Won $"]]
        event = st.dataframe(
            df_disp.drop(columns=["Id"]),
            use_container_width=True, hide_index=True, height=560,
            selection_mode="single-row", on_select="rerun",
            column_config={
                "Clinic":        st.column_config.TextColumn(width="large"),
                "Partner":       st.column_config.TextColumn(width="small"),
                "Hospital ID":   st.column_config.TextColumn(width="small"),
                "State":         st.column_config.TextColumn(width="small"),
                "Installed":     st.column_config.DateColumn(format="YYYY-MM-DD", width="small"),
                "System":        st.column_config.TextColumn(width="small"),
                "Contacts":      st.column_config.NumberColumn(format="%d", width="small"),
                "Opps":          st.column_config.NumberColumn(format="%d", width="small"),
                "Closed-Won $":  st.column_config.NumberColumn(format="$%d", width="small"),
            },
        )
        sel = event.get("selection", {}).get("rows", [])
        if sel:
            acct_id = df_disp.iloc[sel[0]]["Id"]
            goto_detail(acct_id)

# ───────────────────── PAGE: Clinic detail ─────────────────────
def page_detail():
    aid = st.session_state.get("selected_account_id")
    if not aid:
        header("Clinic detail", "Pick a clinic from the search page to load the record here.")
        if st.button(":material/arrow_back: Go to search"):
            goto_search()
        return

    acct = one("SELECT * FROM accounts WHERE Id=?", (aid,))
    if not acct:
        st.error(":material/error: Account not found in the snapshot."); return

    partner_pill = (
        '<span class="partner-pill">Partner</span>'
        if acct.get("Partner") else
        '<span class="lead-pill">Non-Partner</span>'
    )
    sub = (
        f"SF Account: <code>{acct['Id']}</code> &middot; "
        f"Hospital ID: <code>{acct.get('Hospital_ID') or '—'}</code> &middot; "
        f"{partner_pill}"
    )
    # Custom header so we can include HTML in the subtitle
    st.markdown(
        f'<div class="oncura-head"><div class="kicker">ONCURA · SALESFORCE LOOKUP</div>'
        f'<h1>{acct["Name"]}</h1><p class="sub">{sub}</p></div>',
        unsafe_allow_html=True,
    )

    nav1, nav2 = st.columns([1, 9])
    if nav1.button(":material/arrow_back: Back to search", use_container_width=True):
        goto_search()

    # Highlights row (Salesforce-style)
    addr = ", ".join([x for x in [acct.get("BillingStreet"), acct.get("BillingCity"), acct.get("BillingState"), acct.get("BillingPostalCode")] if x])
    owner = one("SELECT Name, Email, IsActive FROM users WHERE Id=?", (acct.get("OwnerId"),))
    owner_label = (f"{owner['Name']}" + ("" if owner and owner["IsActive"] else " (inactive)")) if owner else "—"
    won_total = one("SELECT COALESCE(SUM(Amount),0) AS t FROM opportunities WHERE AccountId=? AND IsWon=1", (aid,))["t"]
    n_contacts = one("SELECT COUNT(*) AS c FROM contacts WHERE AccountId=? AND IsDeleted=0", (aid,))["c"]
    n_opps = one("SELECT COUNT(*) AS c FROM opportunities WHERE AccountId=?", (aid,))["c"]

    import html as _html
    def _hc(label, value):
        return (f'<div class="highlight-card"><div class="label">{_html.escape(label)}</div>'
                f'<div class="value">{_html.escape(str(value)) if value not in (None,"") else "—"}</div></div>')
    highlights_html = (
        '<div class="highlights">'
        + _hc("Address", addr)
        + _hc("Phone", acct.get('Phone'))
        + _hc("Install · System", f"{fmt_date(acct.get('US_Install_Date'))} · {acct.get('Ultrasound_System') or '—'}")
        + _hc("Owner", owner_label)
        + _hc("Contacts", f"{n_contacts:,}")
        + _hc("Opportunities", f"{n_opps:,}")
        + _hc("Closed-Won $", fmt_money(won_total))
        + _hc("Territory", acct.get('Territory'))
        + '</div>'
    )
    st.html(highlights_html)

    main_tabs = st.tabs(["People", "Pipeline", "Touchpoints", "Records"])

    # ─── People ───
    with main_tabs[0]:
        sub = st.tabs(["Contacts", "Campaigns"])
        with sub[0]:  # Contacts
            df = q("""
            SELECT Id, Name, FirstName, LastName, Title, Email, Phone
            FROM contacts WHERE AccountId=? AND IsDeleted=0
            ORDER BY LastName COLLATE NOCASE, FirstName COLLATE NOCASE
            """, (aid,))
            st.caption(f":gray[{len(df):,} contacts]")
            if df.empty:
                st.markdown(":gray[—]")
            else:
                import html as _html
                cards = []
                for _, c in df.iterrows():
                    name = _safe(c.get('Name'), '').strip() or f"{_safe(c.get('FirstName'),'')} {_safe(c.get('LastName'),'')}".strip() or '(no name)'
                    title = _safe(c.get('Title'), '')
                    email = _safe(c.get('Email'), '')
                    phone = _safe(c.get('Phone'), '')
                    initials = ''.join([p[0] for p in name.split() if p][:2]).upper() or '?'
                    meta_parts = []
                    if email:
                        meta_parts.append(f'<a href="mailto:{_html.escape(email)}">{_html.escape(email)}</a>')
                    if phone:
                        meta_parts.append(_html.escape(phone))
                    meta = ' &middot; '.join(meta_parts) if meta_parts else '—'
                    cards.append(
                        f'<div class="contact-card">'
                        f'<div class="contact-avatar">{_html.escape(initials)}</div>'
                        f'<div>'
                        f'<div class="contact-name">{_html.escape(name)}</div>'
                        f'<div class="contact-title">{_html.escape(title) if title else "&nbsp;"}</div>'
                        f'<div class="contact-meta">{meta}</div>'
                        f'</div>'
                        f'</div>'
                    )
                st.html(''.join(cards))

        with sub[1]:  # Campaigns
            camp_df = q("""
            SELECT c.Name AS Campaign, c.Type, c.Status AS CampaignStatus,
                   c.StartDate, c.EndDate,
                   cm.Status AS MemberStatus, cm.HasResponded, cm.FirstRespondedDate,
                   co.Name AS ContactName, co.Title AS ContactTitle, co.Email AS ContactEmail,
                   l.Company AS LeadCompany, l.FirstName AS LeadFirst, l.LastName AS LeadLast
            FROM campaign_members cm
            JOIN campaigns c ON c.Id = cm.CampaignId
            LEFT JOIN contacts co ON co.Id = cm.ContactId
            LEFT JOIN leads l ON l.Id = cm.LeadId
            WHERE cm.ContactId IN (SELECT Id FROM contacts WHERE AccountId = ? AND IsDeleted = 0)
               OR cm.LeadId IN (SELECT Id FROM leads WHERE ConvertedAccountId = ?)
            ORDER BY c.StartDate DESC NULLS LAST, cm.CreatedDate DESC
            """, (aid, aid))
            st.caption(f":gray[{len(camp_df):,} campaign memberships]")
            if camp_df.empty:
                st.markdown(":gray[No campaign memberships on contacts at this clinic.]")
            else:
                disp = camp_df.copy()
                disp["Who"] = disp.apply(
                    lambda r: r["ContactName"] if r.get("ContactName") else
                              (f"{_safe(r.get('LeadFirst'),'')} {_safe(r.get('LeadLast'),'')} (lead)".strip()
                               if r.get("LeadFirst") or r.get("LeadLast") else "—"),
                    axis=1
                )
                disp["Responded"] = disp["HasResponded"].map({1:"Yes",0:""}).fillna("")
                disp = disp[["StartDate","Campaign","Type","Who","ContactTitle","MemberStatus","Responded","FirstRespondedDate"]]
                st.dataframe(
                    disp.rename(columns={
                        "StartDate":"Campaign Start","ContactTitle":"Title",
                        "MemberStatus":"Member status","FirstRespondedDate":"First response",
                    }),
                    use_container_width=True, hide_index=True,
                    column_config={
                        "Campaign Start":   st.column_config.DateColumn(format="YYYY-MM-DD", width="small"),
                        "Campaign":         st.column_config.TextColumn(width="large"),
                        "Type":             st.column_config.TextColumn(width="small"),
                        "Who":              st.column_config.TextColumn(width="medium"),
                        "Title":            st.column_config.TextColumn(width="medium"),
                        "Member status":    st.column_config.TextColumn(width="small"),
                        "Responded":        st.column_config.TextColumn(width="small"),
                        "First response":   st.column_config.DateColumn(format="YYYY-MM-DD", width="small"),
                    },
                )

    # ─── Pipeline ───
    with main_tabs[1]:
        sub = st.tabs(["Opportunities", "Quotes", "Assets & Training"])
        with sub[0]:  # Opportunities
            df = q("""
            SELECT Id, Name, Amount, StageName, IsWon, CloseDate, Type, LeadSource, OwnerId
            FROM opportunities WHERE AccountId=?
            ORDER BY CloseDate DESC
            """, (aid,))
            won = df[df["IsWon"] == 1]["Amount"].sum() if not df.empty else 0
            st.caption(f":gray[{len(df):,} opportunities &middot; Closed-Won total: **{fmt_money(won)}**]")
            if df.empty:
                st.markdown(":gray[—]")
            else:
                def _stage_label(row):
                    if row.get("IsWon"): return "Won"
                    stage = (row.get("StageName") or "").lower()
                    if "lost" in stage: return "Lost"
                    return "Open"
                df_disp = df.copy()
                df_disp["Status"] = df_disp.apply(_stage_label, axis=1)
                df_disp = df_disp[["Status", "CloseDate", "Name", "Amount", "StageName", "Type", "LeadSource", "Id"]]
                df_disp = df_disp.rename(columns={
                    "Name": "Opportunity", "StageName": "Stage", "CloseDate": "Close Date",
                    "LeadSource": "Source", "Id": "SF Opp ID"
                })
                st.dataframe(
                    df_disp, use_container_width=True, hide_index=True,
                    height=min(560, 60 + 36*len(df)),
                    column_config={
                        "Status":      st.column_config.TextColumn(width="small", help="Won · Lost · Open"),
                        "Close Date":  st.column_config.DateColumn(format="YYYY-MM-DD", width="small"),
                        "Opportunity": st.column_config.TextColumn(width="large"),
                        "Amount":      st.column_config.NumberColumn(format="$%d", width="small"),
                        "Stage":       st.column_config.TextColumn(width="small"),
                        "Type":        st.column_config.TextColumn(width="small"),
                        "Source":      st.column_config.TextColumn(width="small"),
                        "SF Opp ID":   st.column_config.TextColumn(width="small"),
                    },
                )

                with st.expander(":gray[Inspect stage history & description for one opportunity]"):
                    opp_choice = st.selectbox(
                        "Opportunity",
                        ["—"] + [
                            f"{_safe(r['Name'],'(no name)')}  ({fmt_money(r['Amount'])}, {fmt_date(r['CloseDate'])})  [{r['Id']}]"
                            for _, r in df.iterrows()
                        ],
                        label_visibility="collapsed",
                    )
                    if opp_choice != "—":
                        opp_id = opp_choice.split("[")[-1].rstrip("]")
                        hist = q("SELECT CreatedDate, StageName, Amount, CloseDate FROM opp_history WHERE OpportunityId=? ORDER BY CreatedDate", (opp_id,))
                        if hist.empty:
                            st.caption(":gray[No stage history rows.]")
                        else:
                            hist["CreatedDate"] = hist["CreatedDate"].str.slice(0, 19)
                            st.dataframe(
                                hist, use_container_width=True, hide_index=True,
                                column_config={
                                    "CreatedDate": st.column_config.TextColumn("Changed at", width="small"),
                                    "StageName":   st.column_config.TextColumn("Stage", width="medium"),
                                    "Amount":      st.column_config.NumberColumn(format="$%d", width="small"),
                                    "CloseDate":   st.column_config.DateColumn(format="YYYY-MM-DD", width="small"),
                                },
                            )
                        opp_full = one("SELECT Description, NextStep FROM opportunities WHERE Id=?", (opp_id,))
                        if opp_full and opp_full.get("Description"):
                            st.markdown(":gray[**Description**]")
                            st.write(opp_full["Description"])
                        if opp_full and opp_full.get("NextStep"):
                            st.markdown(f":gray[**Next step**]  {opp_full['NextStep']}")

        with sub[1]:  # Quotes
            try:
                quotes_df = q("""
                SELECT q.Name, q.QuoteNumber, q.Status, q.TotalPrice, q.ExpirationDate,
                       q.CreatedDate, u.Name AS CreatedBy
                FROM quotes q LEFT JOIN users u ON u.Id = q.CreatedById
                WHERE q.AccountId = ? OR q.OpportunityId IN (SELECT Id FROM opportunities WHERE AccountId = ?)
                ORDER BY q.CreatedDate DESC
                """, (aid, aid))
            except Exception:
                quotes_df = None
            if quotes_df is None or quotes_df.empty:
                st.caption(":gray[No SF Quotes on this clinic.]")
                st.markdown(":gray[—]")
            else:
                st.caption(f":gray[{len(quotes_df):,} quotes]")
                disp = quotes_df.rename(columns={"QuoteNumber":"Quote #","TotalPrice":"Total","ExpirationDate":"Expires","CreatedDate":"Created","CreatedBy":"By"})
                st.dataframe(
                    disp, use_container_width=True, hide_index=True,
                    column_config={"Total": st.column_config.NumberColumn(format="$%d", width="small")},
                )

        with sub[2]:  # Assets & Training
            col_a, col_b = st.columns(2)
            with col_a:
                st.markdown(":gray[**Installed equipment**]")
                assets_df = q("""
                SELECT a.Name, a.SerialNumber, a.Status, a.InstallDate, a.PurchaseDate,
                       a.Description, p.Name AS Product, c.Name AS Contact
                FROM assets a
                LEFT JOIN products p ON p.Id = a.Product2Id
                LEFT JOIN contacts c ON c.Id = a.ContactId
                WHERE a.AccountId = ? AND a.IsDeleted = 0
                ORDER BY a.InstallDate DESC NULLS LAST, a.CreatedDate DESC
                """, (aid,))
                if assets_df.empty:
                    st.markdown(":gray[—]")
                else:
                    st.dataframe(
                        assets_df.rename(columns={"InstallDate":"Installed","PurchaseDate":"Purchased","SerialNumber":"S/N"}),
                        use_container_width=True, hide_index=True,
                        column_config={
                            "Installed":  st.column_config.DateColumn(format="YYYY-MM-DD", width="small"),
                            "Purchased":  st.column_config.DateColumn(format="YYYY-MM-DD", width="small"),
                            "Name":       st.column_config.TextColumn(width="medium"),
                            "Product":    st.column_config.TextColumn(width="medium"),
                            "Status":     st.column_config.TextColumn(width="small"),
                            "S/N":        st.column_config.TextColumn(width="small"),
                        },
                    )

                st.markdown(":gray[**Corporate-group membership**]")
                tvc_df = q("""
                SELECT t.Name, t.MembershipStatus, t.CreatedDate, p.Name AS ParentAccount
                FROM tvc_memberships t
                LEFT JOIN accounts p ON p.Id = t.ParentAccountId
                WHERE t.AccountId = ?
                ORDER BY t.CreatedDate DESC
                """, (aid,))
                if tvc_df.empty:
                    st.markdown(":gray[—]")
                else:
                    st.dataframe(
                        tvc_df.rename(columns={"MembershipStatus":"Status","CreatedDate":"Created","ParentAccount":"Parent"}),
                        use_container_width=True, hide_index=True,
                        column_config={
                            "Created": st.column_config.DateColumn(format="YYYY-MM-DD", width="small"),
                            "Name":    st.column_config.TextColumn(width="large"),
                            "Status":  st.column_config.TextColumn(width="small"),
                            "Parent":  st.column_config.TextColumn(width="medium"),
                        },
                    )
            with col_b:
                st.markdown(":gray[**Training records**]")
                tr_df = q("""
                SELECT t.TrainingType, t.TrainingDate, t.CompletionDate, t.Status,
                       t.Sonographer, c.Name AS Contact, o.Name AS Opportunity
                FROM training_records t
                LEFT JOIN contacts c ON c.Id = t.ContactId
                LEFT JOIN opportunities o ON o.Id = t.OpportunityId
                WHERE t.AccountId = ?
                   OR t.OpportunityId IN (SELECT Id FROM opportunities WHERE AccountId = ?)
                   OR t.ContactId IN (SELECT Id FROM contacts WHERE AccountId = ? AND IsDeleted = 0)
                ORDER BY t.TrainingDate DESC NULLS LAST, t.CreatedDate DESC
                """, (aid, aid, aid))
                if tr_df.empty:
                    st.markdown(":gray[—]")
                else:
                    st.dataframe(
                        tr_df.rename(columns={"TrainingType":"Type","TrainingDate":"Scheduled","CompletionDate":"Completed"}),
                        use_container_width=True, hide_index=True,
                        column_config={
                            "Scheduled":   st.column_config.DateColumn(format="YYYY-MM-DD", width="small"),
                            "Completed":   st.column_config.DateColumn(format="YYYY-MM-DD", width="small"),
                            "Type":        st.column_config.TextColumn(width="medium"),
                            "Status":      st.column_config.TextColumn(width="small"),
                            "Sonographer": st.column_config.TextColumn(width="medium"),
                            "Contact":     st.column_config.TextColumn(width="medium"),
                            "Opportunity": st.column_config.TextColumn(width="medium"),
                        },
                    )

    # ─── Touchpoints ───
    with main_tabs[2]:
        sub = st.tabs(["Activities", "Emails", "Demos", "Events", "Visits", "Cases"])
        with sub[0]:  # Activities
            df = q("""
            SELECT ActivityDate, Subject, Status, Type, Priority, OwnerId, Description, Id
            FROM tasks WHERE AccountId=? OR WhatId=?
            ORDER BY ActivityDate DESC NULLS LAST, CreatedDate DESC
            """, (aid, aid))
            st.caption(f":gray[{len(df):,} activities]")
            if df.empty:
                st.markdown(":gray[—]")
            else:
                import html as _html
                owner_ids = list({_safe(x,'') for x in df["OwnerId"].tolist() if _safe(x,'')})
                owner_lookup = {}
                if owner_ids:
                    placeholders = ','.join(['?']*len(owner_ids))
                    for u in q(f"SELECT Id, Name FROM users WHERE Id IN ({placeholders})", tuple(owner_ids)).to_dict('records'):
                        owner_lookup[u['Id']] = u['Name']

                # Build a Salesforce-style timeline (chronological, most recent first)
                rows = []
                for _, t in df.head(200).iterrows():
                    date = _safe(t.get('ActivityDate'), '—')
                    subj = _safe(t.get('Subject'), '(no subject)')
                    status = _safe(t.get('Status'), '')
                    ttype  = _safe(t.get('Type'), '')
                    owner_name = owner_lookup.get(_safe(t.get('OwnerId'),''), '')
                    css_class = "timeline-card"
                    if (status or "").upper() == "COMPLETED":
                        css_class += " task-completed"
                    elif status:
                        css_class += " task-open"
                    meta_parts = [p for p in [ttype, status, owner_name] if p]
                    meta = ' &middot; '.join(_html.escape(p) for p in meta_parts) if meta_parts else '&nbsp;'
                    rows.append(
                        f'<div class="timeline-row">'
                        f'<div class="timeline-date">{_html.escape(date)}</div>'
                        f'<div class="{css_class}">'
                        f'<div class="timeline-subject">{_html.escape(subj)[:200]}</div>'
                        f'<div class="timeline-meta">{meta}</div>'
                        f'</div></div>'
                    )
                st.html(''.join(rows))
                if len(df) > 200:
                    st.caption(f":gray[Showing 200 most recent of {len(df):,} activities.]")

                with st.expander(":gray[Open the body of a specific activity]"):
                    picked = st.selectbox(
                        "Activity",
                        ["—"] + [
                            f"{_safe(r['ActivityDate'],'?')}  ·  {_safe(r['Subject'],'(no subject)')[:80]}  [{r['Id']}]"
                            for _, r in df.iterrows()
                        ],
                        label_visibility="collapsed",
                    )
                    if picked != "—":
                        tid = picked.split("[")[-1].rstrip("]")
                        row = df[df["Id"] == tid].iloc[0]
                        st.markdown(f":gray[**Subject**]  {_safe(row['Subject'],'(no subject)')}")
                        st.markdown(f":gray[**Date**]  {_safe(row['ActivityDate'],'—')}  ·  :gray[**Status**]  {_safe(row['Status'],'—')}")
                        desc = _safe(row.get('Description'), '')
                        if desc:
                            st.text(desc)

        with sub[1]:  # Emails
            try:
                emails_df = q("""
                SELECT le.Subject, le.Name AS CampaignName, le.Status,
                       les.CreatedDate AS Sent, les.Result, les.EmailAddress AS ToEmail,
                       c.Name AS ContactName
                FROM list_email_sent les
                LEFT JOIN list_email le ON le.Id = les.ListEmailId
                LEFT JOIN contacts c ON c.Id = les.RecipientId
                WHERE les.RecipientId IN (SELECT Id FROM contacts WHERE AccountId = ? AND IsDeleted = 0)
                   OR LOWER(les.EmailAddress) IN (
                       SELECT LOWER(Email) FROM contacts
                       WHERE AccountId = ? AND IsDeleted = 0 AND Email IS NOT NULL AND Email != ''
                   )
                ORDER BY les.CreatedDate DESC LIMIT 300
                """, (aid, aid))
            except Exception:
                emails_df = None
            if emails_df is None or emails_df.empty:
                st.caption(":gray[No list-email sends recorded for this clinic.]")
                st.markdown(":gray[—]")
            else:
                st.caption(f":gray[{len(emails_df):,} marketing emails sent to contacts at this clinic]")
                disp = emails_df.rename(columns={"CampaignName":"Campaign","ToEmail":"To","ContactName":"Contact"})
                st.dataframe(
                    disp[["Sent","Subject","Campaign","To","Contact","Result"]],
                    use_container_width=True, hide_index=True,
                    column_config={
                        "Sent":     st.column_config.DateColumn(format="YYYY-MM-DD", width="small"),
                        "Subject":  st.column_config.TextColumn(width="large"),
                        "Campaign": st.column_config.TextColumn(width="medium"),
                        "To":       st.column_config.TextColumn(width="medium"),
                        "Contact":  st.column_config.TextColumn(width="medium"),
                        "Result":   st.column_config.TextColumn(width="small"),
                    },
                )

        with sub[2]:  # Demos
            try:
                demos_df = q("""
                SELECT ca.EventStartTime, ca.EventTypeName, ca.EventSubject,
                       ca.InviteeName, ca.InviteeEmail,
                       ca.PublisherName AS Rep, ca.Location,
                       CASE WHEN ca.EventCanceled=1 OR ca.InviteeCanceled=1 THEN 'Canceled' ELSE 'Scheduled' END AS Status,
                       ca.CancelReason
                FROM calendly_actions ca
                WHERE LOWER(ca.InviteeEmail) IN (
                    SELECT LOWER(Email) FROM contacts
                    WHERE AccountId = ? AND IsDeleted = 0 AND Email IS NOT NULL AND Email != ''
                )
                ORDER BY ca.EventStartTime DESC LIMIT 200
                """, (aid,))
            except Exception:
                demos_df = None
            if demos_df is None or demos_df.empty:
                st.caption(":gray[No Calendly bookings for this clinic.]")
                st.markdown(":gray[—]")
            else:
                st.caption(f":gray[{len(demos_df):,} Calendly bookings]")
                disp = demos_df.rename(columns={"EventStartTime":"When","EventTypeName":"Type","EventSubject":"Subject","InviteeName":"Invitee","InviteeEmail":"Email"})
                st.dataframe(
                    disp[["When","Type","Subject","Invitee","Email","Rep","Status","Location"]],
                    use_container_width=True, hide_index=True,
                )

        with sub[3]:  # Events
            df = q("""
            SELECT ActivityDate, Subject, StartDateTime, Description, OwnerId
            FROM events WHERE AccountId=? OR WhatId=?
            ORDER BY ActivityDate DESC NULLS LAST
            """, (aid, aid))
            st.caption(f":gray[{len(df):,} events]")
            if df.empty: st.markdown(":gray[—]")
            else:
                ev_disp = df.rename(columns={"ActivityDate": "Date", "OwnerId": "Owner"})[["Date", "Subject", "StartDateTime", "Owner", "Description"]]
                st.dataframe(
                    ev_disp, use_container_width=True, hide_index=True,
                    column_config={
                        "Date":          st.column_config.DateColumn(format="YYYY-MM-DD", width="small"),
                        "Subject":       st.column_config.TextColumn(width="large"),
                        "StartDateTime": st.column_config.TextColumn("Start", width="small"),
                        "Owner":         st.column_config.TextColumn(width="small"),
                        "Description":   st.column_config.TextColumn(width="large"),
                    },
                )

        with sub[4]:  # Visits
            wp_df = q("""
            SELECT w.Id, w.VisitDate, w.ArrivalTime, w.DepartureTime, w.Notes, w.CreatedDate,
                   u.Name AS Rep, r.Name AS Route,
                   r.TravelDistance AS RouteMiles, r.TravelTime AS RouteMinutes
            FROM waypoints w
            LEFT JOIN users u ON u.Id = w.OwnerId
            LEFT JOIN maps_routes r ON r.Id = w.RouteId
            WHERE w.AccountId = ?
            ORDER BY w.VisitDate DESC NULLS LAST, w.ArrivalTime DESC, w.CreatedDate DESC
            """, (aid,))
            st.caption(f":gray[{len(wp_df):,} rep visits to this clinic (from Maps waypoints)]")
            if wp_df.empty:
                st.markdown(":gray[No logged in-person visits.]")
            else:
                # Surface rep notes prominently before the visit table — these are
                # rare (14 across the whole backup) but high-signal: KOL IDs,
                # follow-up status, conversation summaries.
                with_notes = wp_df[wp_df["Notes"].notna() & (wp_df["Notes"].astype(str).str.strip() != "")]
                if not with_notes.empty:
                    st.markdown(":gray[**Rep visit notes**]")
                    for _, row in with_notes.iterrows():
                        when = _safe(row.get("VisitDate"), "") or _safe(row.get("CreatedDate"), "")
                        when = str(when)[:10] if when else "(no date)"
                        rep = _safe(row.get("Rep"), "Unknown rep")
                        route = _safe(row.get("Route"), "")
                        meta = f"{when} &middot; {rep}"
                        if route: meta += f" &middot; {route}"
                        note_text = str(row.get("Notes")).strip()
                        st.markdown(
                            f"""<div style="border-left:3px solid var(--green); background:var(--surface);
                                  padding:.6rem .9rem; margin:.4rem 0; border-radius:4px;">
                                  <div style="font-family:var(--mono); font-size:.72rem;
                                    color:var(--muted); letter-spacing:.04em; text-transform:uppercase;
                                    margin-bottom:.3rem;">{meta}</div>
                                  <div style="color:var(--ink); font-size:.95rem; line-height:1.45;">{note_text}</div>
                                </div>""",
                            unsafe_allow_html=True,
                        )
                    st.markdown("---")

                disp = wp_df.copy()
                disp["Visit"] = disp["VisitDate"].astype(str).str.slice(0,10)
                disp["Arrived"] = disp["ArrivalTime"].astype(str).str.slice(11,16)
                disp["Left"] = disp["DepartureTime"].astype(str).str.slice(11,16)
                disp = disp[["Visit","Rep","Arrived","Left","Notes","Route","RouteMiles","RouteMinutes"]]
                st.dataframe(
                    disp.rename(columns={"RouteMiles":"Route miles","RouteMinutes":"Route min"}),
                    use_container_width=True, hide_index=True,
                    column_config={
                        "Visit":       st.column_config.TextColumn(width="small"),
                        "Rep":         st.column_config.TextColumn(width="medium"),
                        "Arrived":     st.column_config.TextColumn(width="small"),
                        "Left":        st.column_config.TextColumn(width="small"),
                        "Notes":       st.column_config.TextColumn(width="large"),
                        "Route":       st.column_config.TextColumn(width="medium"),
                        "Route miles": st.column_config.NumberColumn(format="%.1f", width="small"),
                        "Route min":   st.column_config.NumberColumn(format="%.0f", width="small"),
                    },
                )

        with sub[5]:  # Cases
            df = q("SELECT CaseNumber, Subject, Status, Priority, CreatedDate, ClosedDate FROM cases WHERE AccountId=? ORDER BY CreatedDate DESC", (aid,))
            st.caption(f":gray[{len(df):,} cases]")
            if df.empty: st.markdown(":gray[—]")
            else:
                st.dataframe(
                    df, use_container_width=True, hide_index=True,
                    column_config={
                        "CaseNumber":  st.column_config.TextColumn("Case #", width="small"),
                        "Subject":     st.column_config.TextColumn(width="large"),
                        "Status":      st.column_config.TextColumn(width="small"),
                        "Priority":    st.column_config.TextColumn(width="small"),
                        "CreatedDate": st.column_config.DateColumn("Opened", format="YYYY-MM-DD", width="small"),
                        "ClosedDate":  st.column_config.DateColumn("Closed", format="YYYY-MM-DD", width="small"),
                    },
                )

    # ─── Records ───
    with main_tabs[3]:
        sub = st.tabs(["Notes", "Chatter", "Files", "History"])
        with sub[0]:  # Notes
            # Gather notes whose ParentId is the account, any contact of the account,
            # or any opportunity of the account. Use OwnerId for author (CreatedById
            # in this org is a legacy migration user on most rows).
            notes_df = q("""
            SELECT n.Id, n.Title, n.Body, n.CreatedDate, n.OwnerId,
                   u.Name AS AuthorName, n.ParentId
            FROM notes n
            LEFT JOIN users u ON u.Id = n.OwnerId
            WHERE n.IsDeleted = 0 AND (
                n.ParentId = ?
                OR n.ParentId IN (SELECT Id FROM contacts WHERE AccountId = ? AND IsDeleted = 0)
                OR n.ParentId IN (SELECT Id FROM opportunities WHERE AccountId = ?)
            )
            ORDER BY n.CreatedDate DESC
            """, (aid, aid, aid))

            author_counts = q("""
            SELECT COALESCE(u.Name, '(unknown)') AS AuthorName, COUNT(*) AS n
            FROM notes n
            LEFT JOIN users u ON u.Id = n.OwnerId
            WHERE n.IsDeleted = 0 AND (
                n.ParentId = ?
                OR n.ParentId IN (SELECT Id FROM contacts WHERE AccountId = ? AND IsDeleted = 0)
                OR n.ParentId IN (SELECT Id FROM opportunities WHERE AccountId = ?)
            )
            GROUP BY AuthorName
            ORDER BY n DESC
            """, (aid, aid, aid))

            st.caption(f":gray[{len(notes_df):,} notes (by Jaclyn, Sarah, and other reps over the clinic's lifetime)]")
            if notes_df.empty:
                st.markdown(":gray[No notes on this clinic.]")
            else:
                authors = ["All authors"] + [f"{r['AuthorName']} ({r['n']})" for _, r in author_counts.iterrows() if r['AuthorName']]
                choice = st.selectbox("Filter by author", authors, key=f"note_author_{aid}", label_visibility="collapsed")
                if choice != "All authors":
                    target = choice.rsplit(" (", 1)[0]
                    notes_df = notes_df[notes_df["AuthorName"] == target]

                import html as _html
                cards = []
                for _, n in notes_df.iterrows():
                    title = _safe(n.get("Title"), "")
                    body  = _safe(n.get("Body"), "")
                    author = _safe(n.get("AuthorName"), "Unknown")
                    created = _safe(n.get("CreatedDate"), "")[:10]
                    # Note bodies can be plain or rich text — strip basic HTML for display
                    body_plain = (body or "").replace("<br>", "\n").replace("<br/>", "\n").replace("<br />", "\n")
                    # Render as a card
                    cards.append(
                        f'<div class="timeline-row">'
                        f'<div class="timeline-date">{_html.escape(created) or "—"}</div>'
                        f'<div class="timeline-card">'
                        f'<div class="timeline-subject">{_html.escape(title) if title else "(untitled note)"}</div>'
                        f'<div class="timeline-meta">by {_html.escape(author)}</div>'
                        f'<div style="margin-top:.5rem; font-family:var(--sans); font-size:.92rem; color:var(--ink); white-space:pre-wrap;">{_html.escape(body_plain)[:2000]}</div>'
                        f'</div></div>'
                    )
                st.html(''.join(cards))

        with sub[1]:  # Chatter
            try:
                chatter = q("""
                SELECT 'Post' AS Kind, fp.Id, fp.Title AS Subj, fp.Body, fp.CreatedDate,
                       u.Name AS Author, NULL AS Field, NULL AS OldVal, NULL AS NewVal
                FROM feed_posts fp LEFT JOIN users u ON u.Id = fp.InsertedById
                WHERE fp.IsDeleted = 0 AND (
                    fp.ParentId = ?
                    OR fp.ParentId IN (SELECT Id FROM contacts WHERE AccountId = ? AND IsDeleted = 0)
                    OR fp.ParentId IN (SELECT Id FROM opportunities WHERE AccountId = ?)
                )
                UNION ALL
                SELECT
                    CASE WHEN nf.Type = 'TrackedChange' THEN 'Tracked change' ELSE 'NewsFeed' END,
                    nf.Id, nf.Title, nf.Body, nf.CreatedDate, u.Name,
                    ftc.FieldName, ftc.OldValue, ftc.NewValue
                FROM news_feed nf
                LEFT JOIN users u ON u.Id = nf.InsertedById
                LEFT JOIN feed_tracked_change ftc ON ftc.FeedItemId = nf.Id
                WHERE nf.ParentId = ?
                   OR nf.ParentId IN (SELECT Id FROM contacts WHERE AccountId = ? AND IsDeleted = 0)
                   OR nf.ParentId IN (SELECT Id FROM opportunities WHERE AccountId = ?)
                UNION ALL
                SELECT 'Comment', fc.Id, '(reply)', fc.CommentBody, fc.CreatedDate, u.Name,
                       NULL, NULL, NULL
                FROM feed_comments fc LEFT JOIN users u ON u.Id = fc.InsertedById
                WHERE fc.IsDeleted = 0 AND (
                    fc.ParentId = ?
                    OR fc.ParentId IN (SELECT Id FROM contacts WHERE AccountId = ? AND IsDeleted = 0)
                    OR fc.ParentId IN (SELECT Id FROM opportunities WHERE AccountId = ?)
                )
                ORDER BY CreatedDate DESC LIMIT 500
                """, (aid,)*9)
            except Exception:
                chatter = None
            if chatter is None or chatter.empty:
                st.caption(":gray[No Chatter activity in the snapshot.]")
                st.markdown(":gray[—]")
            else:
                st.caption(f":gray[{len(chatter):,} Chatter entries (posts, news feed, comments)]")
                import html as _html
                rows_html = []
                for _, c in chatter.iterrows():
                    kind = _safe(c.get("Kind"), "")
                    subj = _safe(c.get("Subj"), "")
                    body = _safe(c.get("Body"), "")
                    author = _safe(c.get("Author"), "Unknown")
                    created = _safe(c.get("CreatedDate"), "")[:10]
                    field = _safe(c.get("Field"), "")
                    old_v = _safe(c.get("OldVal"), "")
                    new_v = _safe(c.get("NewVal"), "")
                    # For TrackedChange rows, the human-readable detail is in field/old/new
                    if kind == "Tracked change" and field:
                        subj_html = f"{_html.escape(field)}: {_html.escape(old_v) or '—'} &rarr; {_html.escape(new_v) or '—'}"
                    else:
                        subj_html = _html.escape(subj or "(no title)")[:200]
                    body_plain = (body or "").replace("<br>", "\n").replace("<br/>", "\n")
                    rows_html.append(
                        f'<div class="timeline-row">'
                        f'<div class="timeline-date">{_html.escape(created) or "—"}</div>'
                        f'<div class="timeline-card">'
                        f'<div class="timeline-subject">{subj_html}</div>'
                        f'<div class="timeline-meta">{_html.escape(kind)} &middot; {_html.escape(author)}</div>'
                        f'<div style="margin-top:.4rem; font-family:var(--sans); font-size:.9rem; color:var(--ink); white-space:pre-wrap;">{_html.escape(body_plain)[:1500]}</div>'
                        f'</div></div>'
                    )
                st.html(''.join(rows_html))

        with sub[2]:  # Files
            # Files tied to this clinic via ContentDocumentLink:
            # - Direct on Account
            # - Files on any Opportunity of this account
            # - Files on any Contact of this account
            # - Files on any Task tied to this account
            files_df = q("""
            SELECT fb.content_version_id, fb.parent_id, fb.parent_type,
                   fb.title, fb.extension, fb.size_bytes, fb.is_inline, fb.release_bucket
            FROM file_blobs fb
            WHERE fb.parent_id = ?
               OR fb.parent_id IN (SELECT Id FROM opportunities WHERE AccountId = ?)
               OR fb.parent_id IN (SELECT Id FROM contacts WHERE AccountId = ? AND IsDeleted = 0)
               OR fb.parent_id IN (SELECT Id FROM tasks WHERE AccountId = ? OR WhatId = ?)
            ORDER BY fb.is_inline DESC, fb.title COLLATE NOCASE
            """, (aid, aid, aid, aid, aid))
            st.caption(f":gray[{len(files_df):,} files in the Salesforce backup]")
            RELEASE_BASE = "https://github.com/alexanderjordain/oncura-sf-database/releases/download/files-2026-03-25-"
            if files_df.empty:
                st.markdown(":gray[No files on this clinic in the backup.]")
            else:
                for _, f in files_df.iterrows():
                    title = _safe(f.get("title"), "(untitled)")
                    ext = _safe(f.get("extension"), "bin") or "bin"
                    cv_id = f.get("content_version_id")
                    bucket = f.get("release_bucket") or "a"
                    size_kb = (f.get("size_bytes") or 0) / 1024
                    size_str = f"{size_kb:,.0f} KB" if size_kb < 1024 else f"{size_kb/1024:,.1f} MB"
                    parent_type = f.get("parent_type") or ""
                    parent_label = {"001": "Account", "003": "Contact", "006": "Opportunity", "00T": "Task", "002": "Note"}.get(parent_type, parent_type)
                    col_main, col_action = st.columns([5, 1])
                    col_main.markdown(f"**{title}.{ext}** · :gray[{size_str} · {parent_label}]")
                    col_action.link_button("Download", f"{RELEASE_BASE}{bucket}/{cv_id}.{ext}", use_container_width=True)

            # Legacy Salesforce Attachments (pre-Files architecture). Binary not in
            # the backup snapshot, but the metadata documents what existed.
            att_df = q("""
            SELECT Name, ContentType, BodyLength, Description, CreatedDate, CreatedById, ParentId
            FROM attachments
            WHERE (AccountId = ? OR ParentId = ?
                   OR ParentId IN (SELECT Id FROM opportunities WHERE AccountId = ?)
                   OR ParentId IN (SELECT Id FROM contacts WHERE AccountId = ? AND IsDeleted = 0)
                   OR ParentId IN (SELECT Id FROM tasks WHERE AccountId = ? OR WhatId = ?))
                  AND IsDeleted = 0
            ORDER BY CreatedDate DESC
            """, (aid, aid, aid, aid, aid, aid))
            if not att_df.empty:
                st.markdown("---")
                st.markdown(f":gray[**Legacy attachments** &middot; {len(att_df):,} pre-Files attachments (metadata only — binaries not in this snapshot)]")
                disp = att_df.copy()
                disp["When"] = disp["CreatedDate"].str.slice(0, 10)
                disp["Size"] = disp["BodyLength"].fillna(0).apply(
                    lambda b: f"{b/1024:,.0f} KB" if b and b < 1024*1024 else (f"{b/1024/1024:,.1f} MB" if b else "")
                )
                disp = disp[["When","Name","ContentType","Size","Description"]]
                st.dataframe(
                    disp, use_container_width=True, hide_index=True,
                    column_config={
                        "When":        st.column_config.TextColumn(width="small"),
                        "Name":        st.column_config.TextColumn(width="large"),
                        "ContentType": st.column_config.TextColumn("Type", width="small"),
                        "Size":        st.column_config.TextColumn(width="small"),
                        "Description": st.column_config.TextColumn(width="medium"),
                    },
                )

        with sub[3]:  # History
            try:
                df = q("SELECT CreatedDate, Field, OldValue, NewValue, CreatedById FROM account_history WHERE AccountId=? ORDER BY CreatedDate DESC LIMIT 500", (aid,))
            except Exception:
                df = None
            if df is None or df.empty:
                st.caption(":gray[No history data in this snapshot.]")
                st.markdown(":gray[—]")
            else:
                st.caption(f":gray[{len(df):,} history changes · most recent 500]")
                df["CreatedDate"] = df["CreatedDate"].str.slice(0, 19)
                st.dataframe(
                    df.rename(columns={"CreatedById": "By"}),
                    use_container_width=True, hide_index=True,
                    column_config={
                        "CreatedDate": st.column_config.TextColumn("Changed at", width="small"),
                        "Field":       st.column_config.TextColumn(width="small"),
                        "OldValue":    st.column_config.TextColumn("From", width="medium"),
                        "NewValue":    st.column_config.TextColumn("To",   width="medium"),
                        "By":          st.column_config.TextColumn(width="small"),
                    },
                )


# ───────────────────── PAGE: Sales activity ─────────────────────
def page_activity():
    header("Sales activity", "Pipeline and closed-won analytics across the snapshot.")

    df = q("""
    SELECT o.AccountId, a.Name AS Clinic, a.BillingState AS State, o.Name AS Opportunity,
           o.Amount, o.StageName, o.IsWon, o.CloseDate, o.Type, o.LeadSource
    FROM opportunities o LEFT JOIN accounts a ON a.Id=o.AccountId
    """)
    df["Year"] = df["CloseDate"].str.slice(0, 4)

    c1, c2, c3 = st.columns(3)
    c1.metric("Opportunities", f"{len(df):,}")
    c2.metric("Closed-Won", f"{int(df['IsWon'].sum()):,}")
    c3.metric("Closed-Won $", fmt_money(df[df['IsWon'] == 1]['Amount'].sum()))

    st.markdown("##### :gray[Closed-Won by year]")
    won = df[df["IsWon"] == 1].groupby("Year", as_index=False)["Amount"].sum().rename(columns={"Amount": "Total $"})
    won["Count"] = df[df["IsWon"] == 1].groupby("Year").size().values if not df.empty else []
    st.dataframe(
        won.sort_values("Year"), use_container_width=True, hide_index=True,
        column_config={
            "Year":    st.column_config.TextColumn(width="small"),
            "Total $": st.column_config.NumberColumn(format="$%d", width="small"),
            "Count":   st.column_config.NumberColumn(format="%d", width="small"),
        },
    )

    st.markdown("##### :gray[Top closed-won clinics]")
    top = df[df["IsWon"] == 1].groupby(["AccountId", "Clinic", "State"], as_index=False)["Amount"].sum().sort_values("Amount", ascending=False).head(50)
    import html as _html
    rows_html = []
    for _, r in top.iterrows():
        cid = _safe(r["AccountId"])
        cname = _safe(r["Clinic"], "(no name)")
        state = _safe(r["State"])
        amt = float(r["Amount"] or 0)
        rows_html.append(
            f'<a class="result-row" href="?clinic={_html.escape(cid)}" target="_self">'
            f'<div>'
            f'<div class="name-row">'
            f'<span class="clinic-link">{_html.escape(cname)}</span>'
            f'</div>'
            f'<div class="secondary">{_html.escape(state) or "—"}<span class="sep">·</span><code>{_html.escape(cid)}</code></div>'
            f'</div>'
            f'<div class="stats">'
            f'<div class="stat">Closed-Won<span class="v">${amt:,.0f}</span></div>'
            f'</div>'
            f'</a>'
        )
    st.html(''.join(rows_html))

# ───────────────────── PAGE: Renewal radar ─────────────────────
def page_renewal():
    header("Renewal radar", "Partner clinics ranked by install age. Use it to spot upgrade candidates.")

    df = q("""
    SELECT Id, Name AS Clinic, BillingState AS State, BillingCity AS City,
           US_Install_Date AS Installed, Ultrasound_System AS System,
           Phone, Hospital_ID,
           (SELECT COALESCE(SUM(Amount),0) FROM opportunities o WHERE o.AccountId=accounts.Id AND o.IsWon=1) AS WonTotal
    FROM accounts
    WHERE IsDeleted=0 AND Partner=1 AND Installed IS NOT NULL AND Installed != ''
    ORDER BY Installed
    """)
    if df.empty:
        st.info(":material/info: No partner install data available in the snapshot."); return
    df["YearsSinceInstall"] = ((datetime.now() - pd.to_datetime(df["Installed"], errors="coerce")).dt.days / 365.25).round(1)

    c1, c2 = st.columns(2)
    min_years = c1.slider("Minimum years since install", 0.0, 12.0, 4.0, 0.5)
    system_filter = c2.multiselect("Ultrasound system", sorted(df["System"].dropna().unique().tolist()))
    f = df[df["YearsSinceInstall"] >= min_years]
    if system_filter:
        f = f[f["System"].isin(system_filter)]
    st.caption(f":gray[{len(f):,} partner clinics meeting filters · showing top 100]")
    import html as _html
    rows_html = []
    for _, r in f.head(100).iterrows():
        cid = _safe(r["Id"])
        cname = _safe(r["Clinic"], "(no name)")
        state = _safe(r["State"])
        city  = _safe(r["City"])
        installed = _safe(r["Installed"])
        try:    years = float(r["YearsSinceInstall"])
        except: years = 0.0
        system = _safe(r["System"])
        try:    won_n = float(r["WonTotal"] or 0)
        except: won_n = 0.0
        phone = _safe(r["Phone"])
        hid = _safe(r["Hospital_ID"])
        secondary_parts = []
        if hid: secondary_parts.append(f'<code>{_html.escape(hid)}</code>')
        loc_bits = [_html.escape(p) for p in [city, state] if p]
        if loc_bits: secondary_parts.append(' &middot; '.join(loc_bits))
        if phone: secondary_parts.append(_html.escape(phone))
        if installed: secondary_parts.append(f'Installed {_html.escape(installed)}')
        if system: secondary_parts.append(_html.escape(system))
        secondary = '<span class="sep">·</span>'.join(secondary_parts) or '—'
        rows_html.append(
            f'<a class="result-row" href="?clinic={_html.escape(cid)}" target="_self">'
            f'<div>'
            f'<div class="name-row">'
            f'<span class="clinic-link">{_html.escape(cname)}</span>'
            f'</div>'
            f'<div class="secondary">{secondary}</div>'
            f'</div>'
            f'<div class="stats">'
            f'<div class="stat">Years since<span class="v">{years:.1f}</span></div>'
            f'<div class="stat">Closed-Won<span class="v">${won_n:,.0f}</span></div>'
            f'</div>'
            f'</a>'
        )
    st.html(''.join(rows_html))

# ───────────────────── Router ─────────────────────
if   page == "Clinic search":   page_search()
elif page == "Clinic detail":   page_detail()
elif page == "Sales activity":  page_activity()
elif page == "Renewal radar":   page_renewal()
