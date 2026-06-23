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
    "https://github.com/alexanderjordain/oncura-sf-database/releases/download/snapshot-2026-06-22/oncura_sf_lookup_lite.db",
)
DB_LOCAL_OVERRIDE = os.environ.get("ONCURA_DB_PATH")

def _resolve_db_path() -> str:
    if DB_LOCAL_OVERRIDE and os.path.exists(DB_LOCAL_OVERRIDE):
        return DB_LOCAL_OVERRIDE
    # Versioned filename so a schema change invalidates the cache automatically.
    target = os.path.join(os.path.expanduser("~"), ".oncura_sf_lookup_v15.db")
    EXPECTED_BYTES = 2_070_642_688  # v15 = v14 + 64 Account_Survey__c rows
    SIZE_TOLERANCE = 2 * 1024 * 1024  # allow ±2 MB to accommodate Content-Encoding variance

    # PRAGMA integrity_check scans the entire 1.25 GB DB and takes ~21 seconds
    # on Streamlit Cloud's network FS. Since Streamlit re-runs this module on
    # every interaction, that cost compounds. We memoize the validation
    # result per (path, mtime, size) tuple so subsequent reruns short-circuit
    # in microseconds, and downgrade integrity_check to quick_check(1).
    if not hasattr(_resolve_db_path, "_validation_cache"):
        _resolve_db_path._validation_cache = {}
    _val_cache = _resolve_db_path._validation_cache

    def _is_complete_valid(path):
        if not os.path.exists(path): return False
        size = os.path.getsize(path)
        if abs(size - EXPECTED_BYTES) > SIZE_TOLERANCE: return False
        mtime = os.path.getmtime(path)
        key = (path, mtime, size)
        cached = _val_cache.get(key)
        if cached is not None:
            return cached
        try:
            import sqlite3 as _sq
            _c = _sq.connect(path)
            _c.execute("SELECT AccountId FROM attachments LIMIT 1")
            _c.execute("SELECT 1 FROM maps_routes LIMIT 1")
            _c.execute("SELECT 1 FROM contact_monthly_metric LIMIT 1")
            _c.execute("SELECT Field FROM entity_history WHERE Field IS NOT NULL LIMIT 1")
            _c.execute("SELECT Partner, Past_Due, Scan_Package FROM accounts LIMIT 1")
            _c.execute("SELECT Department, MobilePhone, DoNotCall, pi_grade FROM contacts LIMIT 1")
            _c.execute("SELECT STAT, Patient_Name, Type_of_Scan FROM cases LIMIT 1")
            _c.execute("SELECT CallFrom, AISummary FROM call_logs LIMIT 1")
            _c.execute("SELECT Body, Direction FROM sms_logs LIMIT 1")
            _c.execute("SELECT CompanySignedDate, ActivatedDate FROM contracts LIMIT 1")
            _c.execute("SELECT AssetPartNumber FROM assets LIMIT 1")
            # v13 (Post-Migration merge) probes
            _c.execute("SELECT CallDurationInSeconds FROM tasks LIMIT 1")
            _c.execute("SELECT Reason_Lost FROM opportunities LIMIT 1")
            _c.execute("SELECT Case_Duration FROM cases LIMIT 1")
            _c.execute("SELECT ParentSobjectType FROM entity_history WHERE ParentSobjectType='Contact' LIMIT 1")
            # quick_check is ~50x cheaper than integrity_check and catches
            # all the corruption modes a truncated download would produce.
            qc = _c.execute("PRAGMA quick_check(1)").fetchone()
            _c.close()
            ok = (qc is not None and qc[0] == "ok")
            _val_cache[key] = ok
            return ok
        except Exception:
            _val_cache[key] = False
            return False

    if _is_complete_valid(target):
        return target
    # Cached file is missing or corrupt — wipe and re-download.
    try: os.remove(target)
    except Exception: pass

    import urllib.request, tempfile, shutil
    info = st.empty()
    info.info("Loading the Salesforce snapshot database… (first launch only, ~2 GB — takes 3–4 min)")
    tmp = target + ".tmp"
    try:
        with urllib.request.urlopen(DB_URL) as r, open(tmp, "wb") as out:
            while True:
                chunk = r.read(1 << 20)
                if not chunk: break
                out.write(chunk)
        # Strict size check: must match the published asset within tolerance
        actual = os.path.getsize(tmp)
        if abs(actual - EXPECTED_BYTES) > SIZE_TOLERANCE:
            raise RuntimeError(f"download incomplete: got {actual:,} bytes, expected ~{EXPECTED_BYTES:,}")
        shutil.move(tmp, target)
    except Exception as e:
        try: os.remove(tmp)
        except Exception: pass
        info.error(f"Failed to fetch the database: {e}")
        raise
    info.empty()
    return target

DB_PATH = _resolve_db_path()

# Clear caches ONLY when DB_PATH rotates to a new snapshot — keyed on the
# resolved path in session_state so within a stable container we keep the
# @st.cache_data memo across reruns. The previous unconditional clear() at
# every rerun was wiping ~3.5s worth of memoized queries on every tab click.
if st.session_state.get("_db_path_seen") != DB_PATH:
    try:
        st.cache_resource.clear()
        st.cache_data.clear()
    except Exception:
        pass
    st.session_state["_db_path_seen"] = DB_PATH

# Startup self-check — surface the actual deployed schema so we can tell
# whether the v11 download is what we think it is. Renders once at the top
# of every page if the contacts table is missing the expanded columns.
def _self_check():
    try:
        import sqlite3 as _sq
        _c = _sq.connect(DB_PATH)
        cols = [r[1] for r in _c.execute("PRAGMA table_info(contacts)")]
        size_mb = os.path.getsize(DB_PATH) / 1024 / 1024
        _c.close()
        missing = [c for c in ('Department','MobilePhone','DoNotCall','pi_grade','MailingState','Abdomen_M1') if c not in cols]
        if missing:
            st.warning(
                f":material/warning: Stale snapshot detected at `{DB_PATH}` "
                f"({size_mb:.0f} MB, {len(cols)} contacts cols). Missing: {missing}. "
                f"Clearing and re-downloading on next reload…"
            )
            try: os.remove(DB_PATH)
            except Exception: pass
    except Exception as e:
        st.warning(f":material/warning: DB self-check failed: {e}")

_self_check()

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

/* Status chips for clinic header */
.chip-row { display:flex; flex-wrap:wrap; gap:.4rem; margin:.4rem 0 .9rem 0; }
.chip { display:inline-flex; align-items:center; gap:.3rem; padding:.18rem .55rem; border-radius:999px; font-weight:600; font-size:.74rem; font-family:var(--sans); letter-spacing:.01em; border:1px solid transparent; }
.chip-good { background:#DFF5E1; color:#1B6E3A; border-color:#B7E2BD; }
.chip-warn { background:#FBE9C5; color:#8B5A0F; border-color:#EFCB78; }
.chip-bad  { background:#F4D9D9; color:#9C2727; border-color:#E2A0A0; }
.chip-info { background:#E1ECF7; color:#2F567E; border-color:#B9D0E6; }
.chip-vip  { background:#F5E0F8; color:#7A2A86; border-color:#D9B0E0; }
.chip-mute { background:#F2F2F2; color:#6B7785; border-color:#DDD; }

/* Compliance chips on contact cards */
.compliance-chip { display:inline-block; padding:.05rem .45rem; margin-right:.25rem; border-radius:4px; font-size:.7rem; font-family:var(--mono); letter-spacing:.04em; }
.cc-dnc  { background:#F4D9D9; color:#9C2727; }
.cc-oo   { background:#FBE9C5; color:#8B5A0F; }
.cc-grade-A { background:#DFF5E1; color:#1B6E3A; }
.cc-grade-B { background:#E1ECF7; color:#2F567E; }
.cc-grade-C { background:#FBE9C5; color:#8B5A0F; }
.cc-grade-D { background:#F4D9D9; color:#9C2727; }
.cc-grade-F { background:#F4D9D9; color:#9C2727; }
.cc-bounce { background:#F4D9D9; color:#9C2727; }
.cc-noatcompany { background:#F2F2F2; color:#6B7785; text-decoration:line-through; }
.cc-primary { background:#F5E0F8; color:#7A2A86; }

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
# get_conn() caches a single sqlite3 connection per DB_PATH. The DB_PATH is
# the cache key, so when the snapshot rotates (v11 → v12) the new path gets
# a fresh connection and the old one is GC'd — this preserves the stale-
# connection fix while restoring per-session warm-up of the page cache,
# mmap, and prepared-statement plans across the ~30 queries on the detail
# page.
@st.cache_resource(show_spinner=False)
def _open_conn(path: str):
    con = sqlite3.connect(path, check_same_thread=False)
    con.row_factory = sqlite3.Row
    # 256 MB memory-mapped reads — eliminates userspace page-cache copy on
    # Streamlit Cloud's network FS for a 1.25 GB read-heavy DB.
    con.execute("PRAGMA mmap_size=268435456")
    # 64 MB per-connection page cache holds ~16k pages.
    con.execute("PRAGMA cache_size=-65536")
    # Sort/temp tables in memory; we never write so it can't bloat.
    con.execute("PRAGMA temp_store=MEMORY")
    # Defensive — the snapshot is strictly read-only.
    con.execute("PRAGMA query_only=1")
    return con

def get_conn():
    return _open_conn(DB_PATH)

@st.cache_data(ttl=3600)
def q(sql, params=()):
    # Direct sqlite3 cursor avoids pandas's opaque DatabaseError wrapper.
    # On failure we show the message inline via st.error() and return an
    # empty DataFrame so the rest of the page can still render. Streamlit
    # Cloud redacts exceptions in production, so st.error() with our own
    # text is the only reliable way to surface diagnostics.
    try:
        cur = get_conn().execute(sql, params)
        cols = [d[0] for d in cur.description] if cur.description else []
        rows = cur.fetchall()
        return pd.DataFrame(rows, columns=cols)
    except sqlite3.OperationalError as e:
        preview = ' '.join(sql.split())[:300]
        st.error(f"Query failed — {e}\n\nSQL: `{preview}`")
        return pd.DataFrame()
    except sqlite3.DatabaseError as e:
        preview = ' '.join(sql.split())[:300]
        st.error(f"DB error — {e}\n\nSQL: `{preview}`")
        return pd.DataFrame()

@st.cache_data(ttl=3600)
def one(sql, params=()):
    try:
        cur = get_conn().execute(sql, params)
        row = cur.fetchone()
        return dict(row) if row else None
    except sqlite3.OperationalError as e:
        preview = ' '.join(sql.split())[:300]
        st.error(f"Query failed — {e}\n\nSQL: `{preview}`")
        return None

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
    if not _real(v): return "—"
    s = str(v)[:10]
    return s if s and s.lower() != "nan" else "—"

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
    if isinstance(v, str):
        # Catch pandas-stringified NaN sentinels like "nan"/"NaT"/"None"
        if v.strip().lower() in ("nan","nat","none","null"): return fallback
        return v
    return str(v)

def _num(v, fallback=None):
    """Coerce a value to float, returning fallback for None/NaN/non-numeric.
    Use to guard int() casts on pandas-returned numeric columns where NULL
    becomes float NaN (bool-truthy but int()-fatal)."""
    try:
        if v is None: return fallback
        import pandas as _pd
        if _pd.isna(v): return fallback
        return float(v)
    except (TypeError, ValueError):
        return fallback

def _truthy(v):
    """Robust truthiness for SQLite columns that may be:
      - real Python bool / int (1, True)
      - float (NaN must NOT count as truthy, despite Python default!)
      - TEXT '1'/'0'/'true'/'false' (SF often stores booleans as strings)
      - None
    Returns True only when v unambiguously represents a positive value."""
    if v is None: return False
    try:
        import pandas as _pd
        if _pd.isna(v): return False
    except Exception:
        pass
    if isinstance(v, bool): return v
    if isinstance(v, (int, float)):
        try: return float(v) > 0
        except (TypeError, ValueError): return False
    s = str(v).strip().lower()
    if s in ("1","true","yes","y","t"): return True
    if s in ("0","false","no","n","f","","none","nan","nat","null"): return False
    # Any other non-empty string is considered truthy (e.g. a real value like
    # "Abdominal Cert 2023-01-15" stored in a TEXT column)
    return True

def _real(v):
    """Returns True iff v is a real value worth rendering — not None, NaN,
    or one of the common pandas/SF sentinel strings."""
    if v is None: return False
    try:
        import pandas as _pd
        if _pd.isna(v): return False
    except Exception:
        pass
    s = str(v).strip().lower()
    return bool(s) and s not in ("nan","nat","none","null")

# ───────────────────── sidebar nav ─────────────────────
# "Clinic detail" is intentionally NOT in this list — reps reach it by
# clicking a clinic from search results (?clinic=<id> URL), not by sidebar
# navigation. The router below still dispatches to page_detail() when
# st.session_state["__page"] resolves to "Clinic detail".
PAGES = ["Clinic search", "Sales activity", "SonixOne upgrades"]
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
    # Parent / corporate-group breadcrumb if present
    parent_html = ""
    parent_id = acct.get("ParentId")
    corp_group = acct.get("Corporate_Group")
    if parent_id:
        parent_row = one("SELECT Name FROM accounts WHERE Id=?", (parent_id,))
        if parent_row:
            parent_html = f' &middot; Parent: <code>{_safe(parent_row.get("Name"), parent_id)}</code>'
    elif corp_group:
        parent_html = f' &middot; Corporate Group: <code>{_safe(corp_group, "")}</code>'

    sub = (
        f"SF Account: <code>{acct['Id']}</code> &middot; "
        f"Hospital ID: <code>{acct.get('Hospital_ID') or '—'}</code> &middot; "
        f"{partner_pill}"
        f"{parent_html}"
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

    # ── Status chips row ──
    # Surface high-signal binary states + countdowns the rep needs at a glance.
    import datetime as _dt
    import html as _html
    def _days_until(date_str):
        if not date_str: return None
        try:
            d = _dt.date.fromisoformat(str(date_str)[:10])
            today = _dt.date.fromisoformat("2026-06-22")
            return (d - today).days
        except Exception:
            return None
    chips = []
    if acct.get("VIP"):                chips.append('<span class="chip chip-vip">★ VIP</span>')
    if acct.get("Past_Due"):           chips.append('<span class="chip chip-bad">⚠ Past Due</span>')
    if acct.get("Compliant") == 1:     chips.append('<span class="chip chip-good">✓ Compliant</span>')
    elif acct.get("Compliant") == 0 and acct.get("Partner"): chips.append('<span class="chip chip-warn">⌀ Non-compliant</span>')
    if acct.get("Has_Ultrasound"):     chips.append('<span class="chip chip-info">Has US</span>')
    tier = acct.get("Clinic_Performance_Tier")
    if tier:                           chips.append(f'<span class="chip chip-info">Tier: {_html.escape(str(tier))}</span>')
    ps  = acct.get("Practice_Specialty")
    if ps:                             chips.append(f'<span class="chip chip-mute">{_html.escape(str(ps))}</span>')
    spk = acct.get("Scan_Package")
    if spk and str(spk).strip():       chips.append(f'<span class="chip chip-info">Pkg: {_html.escape(str(spk))}</span>')
    # Contract end-date countdowns
    for label, d_field in [
        ("Pkg ends",   "Scan_Package_End_Date"),
        ("EMA support", "EMA_Support_End_Date"),
        ("EMA hardware", "EMA_Hardware_End_Date"),
    ]:
        d = acct.get(d_field)
        days = _days_until(d)
        if days is not None:
            d_str = str(d)[:10]
            if days < 0:     css = "chip-bad";  suffix = f"{-days}d overdue"
            elif days < 30:  css = "chip-warn"; suffix = f"in {days}d"
            elif days < 90:  css = "chip-info"; suffix = f"in {days}d"
            else:            css = "chip-mute"; suffix = d_str
            chips.append(f'<span class="chip {css}">{label}: {suffix}</span>')
    if chips:
        chips_html = '<div class="chip-row">' + ''.join(chips) + '</div>'
        # Streamlit's :material/...: syntax only works in st.markdown not st.html; use markdown
        st.markdown(chips_html, unsafe_allow_html=True)

    # Highlights row (Salesforce-style)
    addr = ", ".join([x for x in [acct.get("BillingStreet"), acct.get("BillingCity"), acct.get("BillingState"), acct.get("BillingPostalCode")] if x])
    owner = one("SELECT Name, Email, IsActive FROM users WHERE Id=?", (acct.get("OwnerId"),))
    owner_label = (f"{owner['Name']}" + ("" if owner and owner["IsActive"] else " (inactive)")) if owner else "—"
    won_total = one("SELECT COALESCE(SUM(Amount),0) AS t FROM opportunities WHERE AccountId=? AND IsWon=1", (aid,))["t"]
    n_contacts = one("SELECT COUNT(*) AS c FROM contacts WHERE AccountId=? AND IsDeleted=0", (aid,))["c"]
    n_opps = one("SELECT COUNT(*) AS c FROM opportunities WHERE AccountId=?", (aid,))["c"]
    rcs = acct.get("Regional_Clinical_Specialist")
    n_docs = acct.get("Number_of_Doctors")
    _nd = _num(n_docs)
    n_docs_label = f"{int(_nd)}" if _nd and _nd > 0 else "—"

    def _hc(label, value):
        return (f'<div class="highlight-card"><div class="label">{_html.escape(label)}</div>'
                f'<div class="value">{_html.escape(str(value)) if value not in (None,"") else "—"}</div></div>')
    highlights_html = (
        '<div class="highlights">'
        + _hc("Address", addr)
        + _hc("Phone", acct.get('Phone'))
        + _hc("Install · System", f"{fmt_date(acct.get('US_Install_Date'))} · {acct.get('Ultrasound_System') or '—'}")
        + _hc("Owner", owner_label)
        + _hc("RCS", rcs)
        + _hc("Doctors", n_docs_label)
        + _hc("Contacts", f"{n_contacts:,}")
        + _hc("Opportunities", f"{n_opps:,}")
        + _hc("Closed-Won $", fmt_money(won_total))
        + _hc("Territory", acct.get('Territory'))
        + _hc("Last OSR visit", fmt_date(acct.get('Last_OSR_Call_Visit')))
        + _hc("Website", acct.get('Website'))
        + '</div>'
    )
    st.html(highlights_html)

    main_tabs = st.tabs(["People", "Pipeline", "Touchpoints", "Records"])

    # ─── People ───
    with main_tabs[0]:
        sub = st.tabs(["Contacts", "Campaigns"])
        with sub[0]:  # Contacts
            df = q("""
            SELECT Id, Name, FirstName, LastName, Title, Department,
                   Email, Phone, MobilePhone,
                   HasOptedOutOfEmail, DoNotCall, EmailBouncedDate, EmailBouncedReason,
                   No_longer_at_Company, Primary_Contact,
                   pi_grade, pi_score, pi_last_activity,
                   Certification, Cardiac_Certification,
                   MailingCity, MailingState,
                   Abdomen_M1, Abdomen_M2, Abdomen_M3, Abdominal_M4, Abdominal_M5,
                   Cardiac_M1, Cardiac_M2, Cardiac_M5, Contact_Confirmed, Confirmed_Date
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
                    dept = _safe(c.get('Department'), '')
                    email = _safe(c.get('Email'), '')
                    phone = _safe(c.get('Phone'), '')
                    mobile = _safe(c.get('MobilePhone'), '')
                    city_state = ', '.join([x for x in [_safe(c.get('MailingCity'),''), _safe(c.get('MailingState'),'')] if x])
                    initials = ''.join([p[0] for p in name.split() if p][:2]).upper() or '?'

                    # Compliance / scoring chips — guard every flag with _truthy so
                    # TEXT '0' / NaN / 'nan' string values don't paint false-positive chips.
                    chip_html = []
                    if _truthy(c.get('No_longer_at_Company')):
                        chip_html.append('<span class="compliance-chip cc-noatcompany">No longer at co</span>')
                    if _truthy(c.get('Primary_Contact')):
                        chip_html.append('<span class="compliance-chip cc-primary">PRIMARY</span>')
                    if _truthy(c.get('Contact_Confirmed')):
                        cd = _safe(c.get('Confirmed_Date'), '')[:10]
                        chip_html.append(f'<span class="compliance-chip cc-grade-A">✓ confirmed{(" " + _html.escape(cd)) if cd else ""}</span>')
                    if _truthy(c.get('DoNotCall')):
                        chip_html.append('<span class="compliance-chip cc-dnc">DO NOT CALL</span>')
                    if _truthy(c.get('HasOptedOutOfEmail')):
                        chip_html.append('<span class="compliance-chip cc-oo">opted-out email</span>')
                    if _real(c.get('EmailBouncedDate')):
                        chip_html.append('<span class="compliance-chip cc-bounce">bounced</span>')
                    g = _safe(c.get('pi_grade'), '')
                    if g: chip_html.append(f'<span class="compliance-chip cc-grade-{_html.escape(g[0].upper())}">Grade {_html.escape(g)}</span>')
                    # Certification / Cardiac_Certification are SF TEXT '0'/'1'
                    # in this snapshot (yes/no flags), not free-text. Render
                    # as boolean Certified/Cardiac chips, not the literal value.
                    if _truthy(c.get('Certification')):
                        chip_html.append('<span class="compliance-chip cc-grade-A">Abdominal certified</span>')
                    if _truthy(c.get('Cardiac_Certification')):
                        chip_html.append('<span class="compliance-chip cc-grade-A">Cardiac certified</span>')

                    # Training milestones — Abdomen M1-M5 and Cardiac M1-M5.
                    # Each populated REAL date = one filled dot. NaN/None/'nan' = empty dot.
                    abd_dates = [c.get('Abdomen_M1'), c.get('Abdomen_M2'), c.get('Abdomen_M3'),
                                 c.get('Abdominal_M4'), c.get('Abdominal_M5')]
                    car_dates = [c.get('Cardiac_M1'), c.get('Cardiac_M2'),
                                 None, None, c.get('Cardiac_M5')]  # M3/M4 not exported
                    def _milestone_dots(label, dates):
                        filled = sum(1 for d in dates if _real(d))
                        if filled == 0: return None
                        real_strs = [str(d)[:10] for d in dates if _real(d)]
                        latest = max(real_strs, default='')
                        dots = ''.join('●' if _real(d) else '○' for d in dates)
                        return (f'<span class="compliance-chip" style="background:#E1ECF7; color:#2F567E;'
                                f' font-family:var(--mono);" title="latest: {_html.escape(latest)}">'
                                f'{label} {dots} {filled}/{len(dates)}</span>')
                    abd_chip = _milestone_dots("ABD", abd_dates)
                    car_chip = _milestone_dots("CARD", car_dates)
                    if abd_chip: chip_html.append(abd_chip)
                    if car_chip: chip_html.append(car_chip)

                    chip_row = ('<div style="margin-top:.25rem;">' + ''.join(chip_html) + '</div>') if chip_html else ''

                    meta_parts = []
                    if email:  meta_parts.append(f'<a href="mailto:{_html.escape(email)}">{_html.escape(email)}</a>')
                    if phone:  meta_parts.append(f'☎ {_html.escape(phone)}')
                    if mobile and mobile != phone: meta_parts.append(f'📱 {_html.escape(mobile)}')
                    if city_state: meta_parts.append(_html.escape(city_state))
                    meta = ' &middot; '.join(meta_parts) if meta_parts else '—'

                    title_html = _html.escape(title) if title else "&nbsp;"
                    if dept and dept != title:
                        title_html = f"{title_html} <span style='color:var(--muted)'>· {_html.escape(dept)}</span>"

                    cards.append(
                        f'<div class="contact-card">'
                        f'<div class="contact-avatar">{_html.escape(initials)}</div>'
                        f'<div>'
                        f'<div class="contact-name">{_html.escape(name)}</div>'
                        f'<div class="contact-title">{title_html}</div>'
                        f'<div class="contact-meta">{meta}</div>'
                        f'{chip_row}'
                        f'</div>'
                        f'</div>'
                    )
                st.html(''.join(cards))

                # Engagement panel — aggregate the last 12 months of email/call activity
                # per contact from contact_monthly_metric.
                with st.expander(":gray[Email & call engagement (last 12 months per contact)]"):
                    eng = q("""
                    SELECT c.Name AS Contact, c.Title,
                           SUM(COALESCE(m.EmailsSent,0))     AS EmailsSent,
                           SUM(COALESCE(m.EmailsOpened,0))   AS Opens,
                           SUM(COALESCE(m.EmailsClicked,0))  AS Clicks,
                           SUM(COALESCE(m.EmailsReplied,0))  AS Replies,
                           SUM(COALESCE(m.EmailsHardBounced,0)+COALESCE(m.EmailsSoftBounced,0)) AS Bounces,
                           SUM(COALESCE(m.CallsConnect,0))   AS CallsConnected,
                           SUM(COALESCE(m.CallsLeftVoicemail,0)) AS Voicemails,
                           MAX(m.EndDateTime)                AS LastActivityWindow
                    FROM contacts c
                    LEFT JOIN contact_monthly_metric m
                      ON m.ContactId = c.Id AND m.Month >= date('2025-06-01')
                    WHERE c.AccountId=? AND c.IsDeleted=0
                    GROUP BY c.Id
                    ORDER BY (Opens+Clicks+Replies+CallsConnected) DESC, c.Name
                    """, (aid,))
                    eng = eng.dropna(subset=['Contact'])
                    if eng.empty or eng[['EmailsSent','CallsConnected','Voicemails']].sum().sum() == 0:
                        st.caption(":gray[No tracked email or call activity for contacts at this clinic.]")
                    else:
                        st.dataframe(
                            eng[['Contact','Title','EmailsSent','Opens','Clicks','Replies','Bounces','CallsConnected','Voicemails','LastActivityWindow']],
                            use_container_width=True, hide_index=True,
                            column_config={
                                'Contact':            st.column_config.TextColumn(width='medium'),
                                'Title':              st.column_config.TextColumn(width='medium'),
                                'EmailsSent':         st.column_config.NumberColumn('Emails sent', width='small'),
                                'Opens':              st.column_config.NumberColumn(width='small'),
                                'Clicks':             st.column_config.NumberColumn(width='small'),
                                'Replies':            st.column_config.NumberColumn(width='small'),
                                'Bounces':            st.column_config.NumberColumn(width='small'),
                                'CallsConnected':     st.column_config.NumberColumn('Calls conn.', width='small'),
                                'Voicemails':         st.column_config.NumberColumn('VM', width='small'),
                                'LastActivityWindow': st.column_config.TextColumn('Latest window', width='small'),
                            },
                        )

                # Website behavioral panel from HubSpot Intelligence
                with st.expander(":gray[Website / lead behavior (HubSpot Intelligence)]"):
                    hi = q("""
                    SELECT c.Name AS Contact, h.LeadGrade,
                           h.WebsiteVisits, h.TotalPageViews, h.UniquePagesViewed, h.AveragePageViews,
                           h.FirstConversionDate, h.FirstConversionEvent,
                           h.RecentConversionDate, h.RecentConversionEvent,
                           h.RecentVisit, h.FoundSiteVia, h.IPCity, h.IPState
                    FROM contacts c
                    JOIN hubspot_intelligence h ON h.ContactId = c.Id
                    WHERE c.AccountId=? AND c.IsDeleted=0
                    ORDER BY h.WebsiteVisits DESC NULLS LAST
                    """, (aid,))
                    if hi.empty:
                        st.caption(":gray[No HubSpot web-tracking on contacts at this clinic.]")
                    else:
                        st.dataframe(
                            hi, use_container_width=True, hide_index=True,
                            column_config={
                                'Contact':              st.column_config.TextColumn(width='medium'),
                                'LeadGrade':            st.column_config.TextColumn('Grade', width='small'),
                                'WebsiteVisits':        st.column_config.NumberColumn('Visits', width='small'),
                                'TotalPageViews':       st.column_config.NumberColumn('Pageviews', width='small'),
                                'UniquePagesViewed':    st.column_config.NumberColumn('Unique pages', width='small'),
                                'AveragePageViews':     st.column_config.NumberColumn('Avg pv/visit', width='small'),
                                'FirstConversionDate':  st.column_config.DateColumn('1st convert', format='YYYY-MM-DD', width='small'),
                                'FirstConversionEvent': st.column_config.TextColumn('1st event', width='medium'),
                                'RecentConversionDate': st.column_config.DateColumn('Last convert', format='YYYY-MM-DD', width='small'),
                                'RecentConversionEvent':st.column_config.TextColumn('Last event', width='medium'),
                                'RecentVisit':          st.column_config.TextColumn('Last visit', width='small'),
                                'FoundSiteVia':         st.column_config.TextColumn('Found via', width='medium'),
                                'IPCity':               st.column_config.TextColumn('IP city', width='small'),
                                'IPState':              st.column_config.TextColumn('IP state', width='small'),
                            },
                        )

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
            SELECT Id, Name, Amount, StageName, IsWon, CloseDate, Type, LeadSource, OwnerId,
                   Reason_Lost, Reason_Lost_Note, Sub_Type,
                   Mindray_Shipped_Date, Demo_Completed_Date, Date_of_Rad_Set_Up,
                   Funding_Source, Order_Placed_with_Terason
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
                # Reason_Lost only meaningful for Lost opps; surface inline
                df_disp["Why Lost"] = df_disp.apply(
                    lambda r: _safe(r.get("Reason_Lost"), "") if "lost" in _safe(r.get("StageName"), "").lower() else "",
                    axis=1,
                )
                df_disp = df_disp[["Status", "CloseDate", "Name", "Amount", "StageName", "Type", "Sub_Type", "LeadSource", "Why Lost", "Id"]]
                df_disp = df_disp.rename(columns={
                    "Name": "Opportunity", "StageName": "Stage", "CloseDate": "Close Date",
                    "LeadSource": "Source", "Sub_Type": "Sub-type", "Id": "SF Opp ID"
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
                        "Sub-type":    st.column_config.TextColumn(width="small"),
                        "Source":      st.column_config.TextColumn(width="small"),
                        "Why Lost":    st.column_config.TextColumn(width="medium", help="Reason_Lost field — only populated for closed-lost opps"),
                        "SF Opp ID":   st.column_config.TextColumn(width="small"),
                    },
                )

                # Lost-reason rollup — one-line summary of churn-reasons across this clinic's opps
                lost = df[df["StageName"].fillna("").str.lower().str.contains("lost", na=False)]
                if not lost.empty:
                    reasons = lost["Reason_Lost"].dropna().astype(str)
                    reasons = reasons[reasons.str.strip() != ""]
                    if not reasons.empty:
                        from collections import Counter
                        counts = Counter(reasons.tolist())
                        top = ", ".join(f"{r} ({n})" for r, n in counts.most_common(5))
                        st.caption(f":gray[Lost-reason mix: {top}]")

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
                SELECT a.Name, a.SerialNumber, a.AssetSerialNumber, a.AssetPartNumber,
                       a.Ultrasound_System, a.Status, a.InstallDate, a.PurchaseDate, a.ShippedDate,
                       a.UsageEndDate, a.Price, a.Description,
                       a.City, a.State, a.IsCompetitorProduct,
                       a.Synced_EMA_Contract, a.Synced_Probe_Contract, a.Synced_SSA_Contract,
                       p.Name AS Product, c.Name AS Contact
                FROM assets a
                LEFT JOIN products p ON p.Id = a.Product2Id
                LEFT JOIN contacts c ON c.Id = a.ContactId
                WHERE a.AccountId = ? AND a.IsDeleted = 0
                ORDER BY a.InstallDate DESC NULLS LAST, a.CreatedDate DESC
                """, (aid,))
                if assets_df.empty:
                    st.markdown(":gray[—]")
                else:
                    disp_a = assets_df.copy()
                    disp_a["Location"] = disp_a.apply(
                        lambda r: ', '.join([x for x in [_safe(r.get('City'),''), _safe(r.get('State'),'')] if x]) or None,
                        axis=1
                    )
                    disp_a["SN"] = disp_a["SerialNumber"].fillna(disp_a["AssetSerialNumber"])
                    disp_a["Comp?"] = disp_a["IsCompetitorProduct"].map({1:"⚠ comp", 0:""}).fillna("")
                    disp_a = disp_a[[
                        "Name","Product","Ultrasound_System","SN","AssetPartNumber",
                        "Status","InstallDate","ShippedDate","UsageEndDate","Price",
                        "Location","Contact","Comp?",
                        "Synced_EMA_Contract","Synced_Probe_Contract","Synced_SSA_Contract",
                    ]]
                    st.dataframe(
                        disp_a.rename(columns={
                            "AssetPartNumber":"Part #",
                            "Ultrasound_System":"US System",
                            "InstallDate":"Installed","ShippedDate":"Shipped","UsageEndDate":"Usage end",
                            "Synced_EMA_Contract":"EMA contract",
                            "Synced_Probe_Contract":"Probe contract",
                            "Synced_SSA_Contract":"SSA contract",
                        }),
                        use_container_width=True, hide_index=True,
                        column_config={
                            "Name":           st.column_config.TextColumn(width="medium"),
                            "Product":        st.column_config.TextColumn(width="medium"),
                            "US System":      st.column_config.TextColumn(width="small"),
                            "SN":             st.column_config.TextColumn("S/N", width="small"),
                            "Part #":         st.column_config.TextColumn(width="small"),
                            "Status":         st.column_config.TextColumn(width="small"),
                            "Installed":      st.column_config.DateColumn(format="YYYY-MM-DD", width="small"),
                            "Shipped":        st.column_config.DateColumn(format="YYYY-MM-DD", width="small"),
                            "Usage end":      st.column_config.DateColumn(format="YYYY-MM-DD", width="small"),
                            "Price":          st.column_config.NumberColumn(format="$%d", width="small"),
                            "Location":       st.column_config.TextColumn(width="small"),
                            "Contact":        st.column_config.TextColumn(width="medium"),
                            "Comp?":          st.column_config.TextColumn(width="small"),
                            "EMA contract":   st.column_config.TextColumn(width="small"),
                            "Probe contract": st.column_config.TextColumn(width="small"),
                            "SSA contract":   st.column_config.TextColumn(width="small"),
                        },
                    )

                # Serial numbers (ultrasound device serials, separate table)
                sn_df = q("SELECT Name, CreatedDate FROM serial_numbers WHERE AccountId=? AND IsDeleted=0 ORDER BY CreatedDate DESC", (aid,))
                if not sn_df.empty:
                    st.markdown(":gray[**Additional serial numbers**]")
                    st.dataframe(
                        sn_df.rename(columns={"Name":"Serial #","CreatedDate":"Recorded"}),
                        use_container_width=True, hide_index=True,
                        column_config={
                            "Serial #": st.column_config.TextColumn(width="medium"),
                            "Recorded": st.column_config.DateColumn(format="YYYY-MM-DD", width="small"),
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

            # Contracts — execution timeline below the two-column equipment grid
            st.markdown(":gray[**Contracts**]")
            ct_df = q("""
            SELECT Name, ContractNumber, Contract_Type, Status, StatusCode,
                   StartDate, ActivatedDate, CompanySignedDate, CustomerSignedDate,
                   CustomerSignedTitle, ContractTerm, Shipped,
                   ShippingStreet, ShippingCity, ShippingState, ShippingPostalCode,
                   Description, SpecialTerms
            FROM contracts WHERE AccountId=? AND IsDeleted=0
            ORDER BY COALESCE(ActivatedDate, CustomerSignedDate, StartDate, CreatedDate) DESC
            """, (aid,))
            if ct_df.empty:
                st.markdown(":gray[—]")
            else:
                import html as _html
                cards = []
                for _, c in ct_df.iterrows():
                    name = _safe(c.get('Name'), 'Contract')
                    num  = _safe(c.get('ContractNumber'), '')
                    ctyp = _safe(c.get('Contract_Type'), '')
                    status = _safe(c.get('Status'), '')
                    term = c.get('ContractTerm')
                    _t = _num(term)
                    term_s = f"{int(_t)} mo" if _t and _t > 0 else ""
                    company_signed = str(_safe(c.get('CompanySignedDate'), ''))[:10]
                    cust_signed    = str(_safe(c.get('CustomerSignedDate'), ''))[:10]
                    activated      = str(_safe(c.get('ActivatedDate'), ''))[:10]
                    start_         = str(_safe(c.get('StartDate'), ''))[:10]
                    shipped        = c.get('Shipped')
                    cust_title     = _safe(c.get('CustomerSignedTitle'), '')
                    ship_addr      = ', '.join([x for x in [_safe(c.get('ShippingCity'),''), _safe(c.get('ShippingState'),''), _safe(c.get('ShippingPostalCode'),'')] if x])

                    timeline_chips = []
                    for label, val in [
                        ("Start", start_),
                        ("Co. signed", company_signed),
                        ("Customer signed", cust_signed),
                        ("Activated", activated),
                    ]:
                        if val and val.lower() not in ("none","nan","nat","null"):
                            timeline_chips.append(f'<span class="chip chip-info">{label}: {_html.escape(val)}</span>')
                    if term_s:           timeline_chips.append(f'<span class="chip chip-mute">{_html.escape(term_s)}</span>')
                    if _truthy(shipped): timeline_chips.append('<span class="chip chip-good">Shipped</span>')
                    if status:           timeline_chips.append(f'<span class="chip chip-info">{_html.escape(status)}</span>')

                    detail_lines = []
                    if cust_title:  detail_lines.append(f'<b>Signed by:</b> {_html.escape(cust_title)}')
                    if ctyp:        detail_lines.append(f'<b>Type:</b> {_html.escape(ctyp)}')
                    if ship_addr:   detail_lines.append(f'<b>Ship to:</b> {_html.escape(ship_addr)}')
                    if _safe(c.get('Description'), ''):
                        detail_lines.append(f'<b>Description:</b> {_html.escape(_safe(c.get("Description"),"")[:400])}')
                    if _safe(c.get('SpecialTerms'), ''):
                        detail_lines.append(f'<b>Special terms:</b> {_html.escape(_safe(c.get("SpecialTerms"),"")[:400])}')
                    detail_html = '<br>'.join(detail_lines)

                    cards.append(
                        f'<div style="background:var(--surface); border:1px solid var(--line); border-left:3px solid var(--green);'
                        f' border-radius:6px; padding:.55rem .8rem; margin-bottom:.4rem;">'
                        f'<div style="display:flex; justify-content:space-between; align-items:baseline;">'
                        f'<div style="font-weight:600; color:var(--ink); font-family:var(--sans);">{_html.escape(name)}</div>'
                        f'<div style="font-family:var(--mono); font-size:.7rem; color:var(--muted);">{_html.escape(num)}</div>'
                        f'</div>'
                        f'<div style="margin:.3rem 0;">{"".join(timeline_chips)}</div>'
                        f'{("<div style=\"font-size:.88rem; color:var(--ink);\">" + detail_html + "</div>") if detail_html else ""}'
                        f'</div>'
                    )
                st.html(''.join(cards))

    # ─── Touchpoints ───
    with main_tabs[2]:
        # Unified chronological timeline of every clinic touchpoint —
        # tasks, calls, SMS, marketing emails, Calendly demos, calendar
        # events, in-person rep visits, and support cases — merged in
        # date order. Type-filter chips let the rep narrow when needed.

        import html as _html
        from datetime import datetime as _dt

        def _date_str(v):
            if not _real(v): return ""
            s = str(v)
            if s.lower() == "nan": return ""
            return s[:10] if len(s) >= 10 else s

        def _datetime_sort(v):
            if not _real(v): return "0000-00-00"
            s = str(v)
            if s.lower() == "nan": return "0000-00-00"
            return s[:19] if len(s) >= 10 else "0000-00-00"

        timeline_items = []  # list of dicts: kind, when, sort_key, title, meta, body, color

        # ─── Tasks (Activities) ───
        tasks_df = q("""
        SELECT t.ActivityDate, t.Subject, t.Status, t.Type, t.OwnerId,
               t.Description, t.Id, u.Name AS OwnerName,
               t.CallDurationInSeconds, t.CallDisposition, t.CallType,
               t.Dialpad_Call_Recording_URL
        FROM tasks t LEFT JOIN users u ON u.Id = t.OwnerId
        WHERE t.AccountId = ?
           OR t.WhatId    = ?
           OR t.WhatId IN (SELECT Id FROM opportunities WHERE AccountId = ?)
           OR t.WhoId  IN (SELECT Id FROM contacts WHERE AccountId = ? AND IsDeleted = 0)
           OR t.WhoId  IN (SELECT Id FROM leads WHERE ConvertedAccountId = ?)
           OR t.Id IN (
               SELECT tr.TaskId FROM task_relations tr
               WHERE tr.RelationId = ?
                  OR tr.RelationId IN (SELECT Id FROM contacts WHERE AccountId = ? AND IsDeleted = 0)
                  OR tr.RelationId IN (SELECT Id FROM opportunities WHERE AccountId = ?)
           )
        ORDER BY t.ActivityDate DESC NULLS LAST, t.CreatedDate DESC
        """, (aid, aid, aid, aid, aid, aid, aid, aid))
        # Most call/email touchpoints were logged as Task records (Subject
        # "Call", "Email: Re ...", etc.) rather than dedicated SF Call/Email
        # objects — only 100 Dialpad call_logs and 0 dedicated email tasks
        # exist, vs ~49k call-subject and ~57k email-subject tasks. Classify
        # each Task by its Type+Subject so the type-filter chips work.
        for _, t in tasks_df.iterrows():
            d = _date_str(t.get("ActivityDate"))
            ttype = _safe(t.get("Type"), "")
            status = _safe(t.get("Status"), "")
            owner = _safe(t.get("OwnerName"), "")
            subj = _safe(t.get("Subject"), "(no subject)")
            subj_l = (subj or "").lower().lstrip()
            ttype_l = ttype.lower()

            # Dialpad-sourced tasks carry CallDurationInSeconds / CallType /
            # Dialpad_Call_Recording_URL on the row itself.
            call_dur  = _num(t.get("CallDurationInSeconds"))   # None if NULL/NaN
            call_type_native = (_safe(t.get("CallType"), "") or "").lower()
            call_disp = _safe(t.get("CallDisposition"), "")
            recording = _safe(t.get("Dialpad_Call_Recording_URL"), "")
            has_call_signal = bool((call_dur and call_dur > 0) or call_type_native or recording)

            if (ttype_l == "call"
                or has_call_signal
                or subj_l.startswith(("call", "phone", "vm ", "voicemail",
                                     "returning vm", "left vm", "missed call",
                                     "outbound", "inbound"))
                or "dialpad" in subj_l):
                kind = "Call"
                color = "#2F567E"
            elif (ttype_l == "email"
                  or subj_l.startswith(("email", "re:", "fw:", "fwd:",
                                       "sent email", "re ", "fw ", "fwd ",
                                       "e-mail"))):
                kind = "Email"
                color = "#E3A033"
            elif subj_l.startswith(("sms", "text:", "text message", "txt")):
                kind = "SMS"
                color = "#469B68"
            elif subj_l.startswith(("visit", "in-person", "stopped by",
                                    "drop in", "drop-in", "drop off",
                                    "drop-off", "dropped off")):
                kind = "Visit"
                color = "#1B6E3A"
            elif "demo" in subj_l or "training" in subj_l:
                kind = "Demo"
                color = "#7A2A86"
            elif "meeting" in subj_l or "meet" in subj_l:
                kind = "Event"
                color = "#2F567E"
            else:
                kind = "Activity"
                color = "#3A6A9A"

            # Enrich meta with Dialpad call details when present
            meta_bits = [b for b in [ttype, status, owner] if b]
            if call_dur and call_dur > 0:
                meta_bits.insert(0, f"{int(call_dur)}s")
            if call_type_native:
                arrow = "→ outbound" if call_type_native == "outbound" else ("← inbound" if call_type_native == "inbound" else call_type_native)
                meta_bits.insert(0, arrow)
            if call_disp:
                meta_bits.append(call_disp)

            body_val = _safe(t.get("Description"), "")
            body_html_override = None
            if recording:
                # Render recording link as HTML so it stays clickable
                import html as _h
                body_html_override = (
                    f'<a href="{_h.escape(recording)}" target="_blank" style="font-family:var(--mono); font-size:.8rem;">▶ Recording</a>'
                    + (("<br>" + _h.escape(body_val)[:600]) if body_val else "")
                )

            timeline_items.append({
                "kind": kind,
                "when": d, "sort_key": _datetime_sort(t.get("ActivityDate")),
                "title": subj,
                "meta": " · ".join(meta_bits),
                "body": body_val,
                "body_html": body_html_override,
                "color": color,
            })

        # ─── Calls (Dialpad) ───
        calls_df = q("""
        SELECT cl.CreatedDate, cl.ActivityDate, cl.AgentName,
               cl.CallFrom, cl.CallTo, cl.CallType,
               cl.CallDuration, cl.ConnectedDuration,
               cl.CallDisposition, cl.CallDispositionNotes,
               cl.AICallPurpose, cl.AIOutcome, cl.AISummary, cl.AIActionItems,
               cl.RecordingURL, cl.Comments
        FROM call_logs cl
        WHERE cl.ParentObjectId = ?
           OR cl.ParentObjectId IN (SELECT Id FROM contacts WHERE AccountId = ? AND IsDeleted = 0)
           OR cl.ParentObjectId IN (SELECT Id FROM opportunities WHERE AccountId = ?)
           OR cl.RelatedObjectIds LIKE ?
        """, (aid, aid, aid, f"%{aid}%"))
        for _, r in calls_df.iterrows():
            when_raw = r.get("ActivityDate") or r.get("CreatedDate")
            ctype = (_safe(r.get("CallType"), "") or "").lower()
            arrow = "→" if ctype == "outbound" else ("←" if ctype == "inbound" else "·")
            from_ = _safe(r.get("CallFrom"), "")
            to_   = _safe(r.get("CallTo"), "")
            dur   = _num(r.get("ConnectedDuration")) or _num(r.get("CallDuration"))
            dur_s = f"{int(dur)}s" if dur and dur > 0 else ""
            disp  = _safe(r.get("CallDisposition"), "")
            purpose = _safe(r.get("AICallPurpose"), "")
            outcome = _safe(r.get("AIOutcome"), "")
            summary = _safe(r.get("AISummary"), "")
            actions = _safe(r.get("AIActionItems"), "")
            notes   = _safe(r.get("CallDispositionNotes"), "") or _safe(r.get("Comments"), "")
            rec     = _safe(r.get("RecordingURL"), "")
            agent_  = _safe(r.get("AgentName"), "")

            meta_bits = [f"{from_} {arrow} {to_}"]
            if agent_: meta_bits.append(agent_)
            if dur_s:  meta_bits.append(dur_s)
            if disp:   meta_bits.append(disp)
            if outcome:meta_bits.append(outcome)

            body_parts = []
            if purpose: body_parts.append(f"Purpose: {purpose}")
            if summary: body_parts.append(f"AI summary: {summary[:500]}")
            if actions: body_parts.append(f"Action items: {actions[:300]}")
            if notes:   body_parts.append(f"Rep notes: {notes[:400]}")
            if rec:     body_parts.append(f'<a href="{_html.escape(rec)}" target="_blank">Recording</a>')

            timeline_items.append({
                "kind": "Call",
                "when": _date_str(when_raw),
                "sort_key": _datetime_sort(when_raw),
                "title": "Call",
                "meta": " · ".join(meta_bits),
                "body": "\n".join(body_parts),
                "body_html": "<br>".join(body_parts) if rec else None,
                "color": "#2F567E",  # blue-deep
            })

        # ─── SMS (Dialpad) ───
        sms_df = q("""
        SELECT sl.CreatedDate, sl.ActivityDate, sl.AgentName,
               sl.CompanyNumber, sl.CustomerNumber, sl.Direction,
               sl.Body, sl.MessageStatus, sl.Subject
        FROM sms_logs sl
        WHERE sl.ParentObjectId = ?
           OR sl.ParentObjectId IN (SELECT Id FROM contacts WHERE AccountId = ? AND IsDeleted = 0)
           OR sl.ParentObjectId IN (SELECT Id FROM opportunities WHERE AccountId = ?)
           OR sl.RelatedObjectIds LIKE ?
        """, (aid, aid, aid, f"%{aid}%"))
        for _, r in sms_df.iterrows():
            when_raw = r.get("ActivityDate") or r.get("CreatedDate")
            direction = (_safe(r.get("Direction"), "") or "").lower()
            arrow = "→" if direction == "outbound" else ("←" if direction == "inbound" else "·")
            company = _safe(r.get("CompanyNumber"), "")
            customer = _safe(r.get("CustomerNumber"), "")
            agent_ = _safe(r.get("AgentName"), "")
            body = _safe(r.get("Body"), "") or _safe(r.get("Subject"), "")
            meta_bits = [f"{company} {arrow} {customer}"]
            if agent_: meta_bits.append(agent_)
            timeline_items.append({
                "kind": "SMS",
                "when": _date_str(when_raw),
                "sort_key": _datetime_sort(when_raw),
                "title": "SMS",
                "meta": " · ".join(meta_bits),
                "body": body[:1500],
                "color": "#469B68",  # green
            })

        # ─── Marketing emails ───
        emails_df = q("""
        WITH local_contacts AS (
            SELECT Id, LOWER(Email) AS email_lower FROM contacts
            WHERE AccountId = ? AND IsDeleted = 0
        )
        SELECT * FROM (
            SELECT le.Subject AS subj, le.Name AS Campaign, le.Status AS le_status,
                   les.CreatedDate AS Sent, les.Result AS res, les.EmailAddress AS ToEmail,
                   c.Name AS ContactName, les.Id AS _lid
            FROM list_email_sent les
            JOIN local_contacts lc ON lc.Id = les.RecipientId
            LEFT JOIN list_email le ON le.Id = les.ListEmailId
            LEFT JOIN contacts c ON c.Id = les.RecipientId
            UNION
            SELECT le.Subject AS subj, le.Name AS Campaign, le.Status AS le_status,
                   les.CreatedDate AS Sent, les.Result AS res, les.EmailAddress AS ToEmail,
                   c.Name AS ContactName, les.Id AS _lid
            FROM list_email_sent les
            JOIN local_contacts lc ON lc.email_lower = LOWER(les.EmailAddress)
              AND lc.email_lower IS NOT NULL AND lc.email_lower != ''
            LEFT JOIN list_email le ON le.Id = les.ListEmailId
            LEFT JOIN contacts c ON c.Id = les.RecipientId
        )
        ORDER BY Sent DESC LIMIT 300
        """, (aid,))
        for _, r in emails_df.iterrows():
            when_raw = r.get("Sent")
            subj  = _safe(r.get("subj"), "")
            camp  = _safe(r.get("Campaign"), "")
            to_   = _safe(r.get("ToEmail"), "")
            contact = _safe(r.get("ContactName"), "")
            result = _safe(r.get("res"), "")
            meta_bits = [b for b in [contact or to_, camp, result] if b]
            timeline_items.append({
                "kind": "Email",
                "when": _date_str(when_raw),
                "sort_key": _datetime_sort(when_raw),
                "title": f"Email: {subj}" if subj else "Email",
                "meta": " · ".join(meta_bits),
                "body": "",
                "color": "#E3A033",  # amber
            })

        # ─── Calendly demos ───
        demos_df = q("""
        WITH emails AS (
            SELECT LOWER(Email) AS em FROM contacts
            WHERE AccountId = ? AND IsDeleted = 0
              AND Email IS NOT NULL AND Email != ''
        )
        SELECT ca.EventStartTime, ca.EventTypeName, ca.EventSubject,
               ca.InviteeName, ca.InviteeEmail, ca.PublisherName AS Rep, ca.Location,
               CASE WHEN ca.EventCanceled=1 OR ca.InviteeCanceled=1 THEN 'Canceled' ELSE 'Scheduled' END AS Status,
               ca.CancelReason
        FROM emails e
        JOIN calendly_actions ca ON LOWER(ca.InviteeEmail) = e.em
        ORDER BY ca.EventStartTime DESC
        """, (aid,))
        for _, r in demos_df.iterrows():
            when_raw = r.get("EventStartTime")
            typ = _safe(r.get("EventTypeName"), "")
            inv = _safe(r.get("InviteeName"), "")
            inv_email = _safe(r.get("InviteeEmail"), "")
            rep = _safe(r.get("Rep"), "")
            loc = _safe(r.get("Location"), "")
            status = _safe(r.get("Status"), "")
            reason = _safe(r.get("CancelReason"), "")
            meta_bits = [b for b in [typ, inv or inv_email, rep, status, loc] if b]
            body = reason if reason and status == "Canceled" else ""
            timeline_items.append({
                "kind": "Demo",
                "when": _date_str(when_raw),
                "sort_key": _datetime_sort(when_raw),
                "title": _safe(r.get("EventSubject"), "Calendly demo") or "Calendly demo",
                "meta": " · ".join(meta_bits),
                "body": body,
                "color": "#7A2A86",  # purple
            })

        # ─── Calendar events ───
        events_df = q("""
        SELECT ActivityDate, Subject, StartDateTime, Description, OwnerId,
               Location, DurationInMinutes, Type, Sales_Rep,
               Calendly_IsNoShow, Calendly_IsRescheduled, Demo_Completed_Date
        FROM events
        WHERE AccountId=? OR WhatId=?
        ORDER BY ActivityDate DESC NULLS LAST
        """, (aid, aid))
        owner_ids = [r["OwnerId"] for _, r in events_df.iterrows() if r.get("OwnerId")]
        owner_map = {}
        if owner_ids:
            placeholders = ",".join(["?"]*len(set(owner_ids)))
            for u in q(f"SELECT Id, Name FROM users WHERE Id IN ({placeholders})",
                       tuple(set(owner_ids))).to_dict('records'):
                owner_map[u['Id']] = u['Name']
        for _, r in events_df.iterrows():
            when_raw = r.get("ActivityDate")
            etype = _safe(r.get("Type"), "")
            loc = _safe(r.get("Location"), "")
            dur = _num(r.get("DurationInMinutes"))
            dur_s = f"{int(dur)}m" if dur and dur > 0 else ""
            rep = _safe(r.get("Sales_Rep"), "") or owner_map.get(_safe(r.get("OwnerId"),""), "")
            chips = []
            if _truthy(r.get("Calendly_IsNoShow")):     chips.append("NO-SHOW")
            if _truthy(r.get("Calendly_IsRescheduled")):chips.append("rescheduled")
            if _real(r.get("Demo_Completed_Date")):     chips.append("demo completed")
            meta_bits = [b for b in [etype, dur_s, loc, rep] + chips if b]
            timeline_items.append({
                "kind": "Event",
                "when": _date_str(when_raw),
                "sort_key": _datetime_sort(when_raw),
                "title": _safe(r.get("Subject"), "(no subject)"),
                "meta": " · ".join(meta_bits),
                "body": _safe(r.get("Description"), ""),
                "color": "#2F567E",
            })

        # ─── Maps waypoint visits ───
        visits_df = q("""
        SELECT w.VisitDate, w.ArrivalTime, w.DepartureTime, w.Notes,
               u.Name AS Rep, r.Name AS Route,
               r.TravelDistance AS RouteMiles, r.TravelTime AS RouteMinutes
        FROM waypoints w
        LEFT JOIN users u ON u.Id = w.OwnerId
        LEFT JOIN maps_routes r ON r.Id = w.RouteId
        WHERE w.AccountId = ?
        """, (aid,))
        for _, r in visits_df.iterrows():
            when_raw = r.get("VisitDate")
            rep = _safe(r.get("Rep"), "")
            route = _safe(r.get("Route"), "")
            arr = str(_safe(r.get("ArrivalTime"), ""))[11:16]
            dep = str(_safe(r.get("DepartureTime"), ""))[11:16]
            time_range = f"{arr}–{dep}" if arr and dep else (arr or dep)
            meta_bits = [b for b in [rep, time_range, route] if b]
            timeline_items.append({
                "kind": "Visit",
                "when": _date_str(when_raw),
                "sort_key": _datetime_sort(when_raw),
                "title": "In-person visit",
                "meta": " · ".join(meta_bits),
                "body": _safe(r.get("Notes"), ""),
                "color": "#1B6E3A",  # forest green
            })

        # ─── Support cases ───
        cases_df = q("""
        SELECT c.CaseNumber, c.Subject, c.Status, c.Priority, c.STAT,
               c.Level_of_Urgency, c.Type_of_Scan, c.Patient_Name, c.Patient_Age,
               c.Immediate_Area_of_Concern, c.Notes_on_OPD, c.Description,
               c.Sonographer_Call_Back_Log_Priority,
               c.X1st_Callback_Time, c.X1st_Callback_Completed_At,
               c.CreatedDate, c.ClosedDate
        FROM cases c WHERE c.AccountId=?
        """, (aid,))
        for _, r in cases_df.iterrows():
            when_raw = r.get("CreatedDate")
            status = _safe(r.get("Status"), "")
            prio = _safe(r.get("Priority"), "")
            urg = _safe(r.get("Level_of_Urgency"), "")
            pat = _safe(r.get("Patient_Name"), "")
            age = _safe(r.get("Patient_Age"), "")
            scan = _safe(r.get("Type_of_Scan"), "")
            aoc = _safe(r.get("Immediate_Area_of_Concern"), "")
            cb_prio = _safe(r.get("Sonographer_Call_Back_Log_Priority"), "")

            chips = []
            is_stat = _truthy(r.get("STAT"))
            if is_stat: chips.append("★ STAT")
            if urg:     chips.append(urg)
            if prio:    chips.append(prio)
            if status:  chips.append(status)
            if cb_prio: chips.append(f"CB prio: {cb_prio}")
            meta_bits = chips + [b for b in [scan, (pat + (f" (age {age})" if age else "") if pat else "")] if b]
            body = _safe(r.get("Description"), "")
            if aoc:    body = (f"Area of concern: {aoc}\n\n" + body).strip()
            if _safe(r.get("Notes_on_OPD"), ""):
                body = (body + f"\n\nOPD notes: {_safe(r.get('Notes_on_OPD'), '')}").strip()
            color = "#9C2727" if is_stat else "#3A6A9A"
            timeline_items.append({
                "kind": "Case",
                "when": _date_str(when_raw),
                "sort_key": _datetime_sort(when_raw),
                "title": f"Case #{_safe(r.get('CaseNumber'),'?')}: {_safe(r.get('Subject'),'')}",
                "meta": " · ".join(meta_bits),
                "body": body,
                "color": color,
            })

        # ─── Render unified timeline ───
        kind_counts = {}
        for it in timeline_items:
            kind_counts[it["kind"]] = kind_counts.get(it["kind"], 0) + 1
        all_kinds = ["Activity","Call","SMS","Email","Demo","Event","Visit","Case"]

        st.caption(
            f":gray[{len(timeline_items):,} touchpoints &middot; "
            + " · ".join(f"{kind_counts.get(k,0)} {k.lower()}{'s' if kind_counts.get(k,0)!=1 else ''}" for k in all_kinds if kind_counts.get(k,0))
            + "]"
        )

        # Type filter chips (multi-select)
        active_kinds = st.multiselect(
            "Filter touchpoint types",
            options=all_kinds,
            default=all_kinds,
            label_visibility="collapsed",
            key=f"tp_kinds_{aid}",
            placeholder="Show all touchpoint types",
        )
        col_hide_l, col_hide_r = st.columns([1, 4])
        hide_empty = col_hide_l.checkbox("Hide empty-body", value=False, key=f"tp_hide_empty_{aid}")

        # Sort descending by date
        timeline_items.sort(key=lambda x: x.get("sort_key", ""), reverse=True)

        # Filter + cap
        filtered = [it for it in timeline_items if it["kind"] in active_kinds]
        if hide_empty:
            filtered = [it for it in filtered if (it.get("body") or "").strip()]
        SHOW_LIMIT = 300
        shown = filtered[:SHOW_LIMIT]
        if len(filtered) > SHOW_LIMIT:
            st.caption(f":gray[Showing {SHOW_LIMIT} most recent of {len(filtered):,} (use type filters above to narrow).]")

        if not shown:
            st.markdown(":gray[—]")
        else:
            cards_html = []
            for it in shown:
                kind = it["kind"]
                when = it.get("when") or "—"
                title = _html.escape(it.get("title") or "")
                meta = _html.escape(it.get("meta") or "") or "&nbsp;"
                body = it.get("body_html") or _html.escape(it.get("body") or "")
                color = it["color"]
                # Truncate body for the timeline card
                if body and not it.get("body_html") and len(body) > 600:
                    body = body[:600] + "…"
                body_html = (f'<div style="margin-top:.45rem; font-family:var(--sans); font-size:.9rem;'
                             f' color:var(--ink); white-space:pre-wrap; line-height:1.45;">{body}</div>') if body else ""
                kind_chip = f'<span style="display:inline-block; padding:.05rem .45rem; border-radius:4px; font-family:var(--mono); font-size:.65rem; letter-spacing:.04em; background:{color}; color:white; margin-right:.4rem;">{kind.upper()}</span>'
                cards_html.append(
                    f'<div class="timeline-row">'
                    f'<div class="timeline-date">{_html.escape(when)}</div>'
                    f'<div class="timeline-card" style="border-left-color:{color};">'
                    f'<div class="timeline-subject">{kind_chip}{title}</div>'
                    f'<div class="timeline-meta">{meta}</div>'
                    f'{body_html}'
                    f'</div></div>'
                )
            st.html(''.join(cards_html))

        # Inline body expander — for tasks/activities where the description is
        # often longer than the 600-char preview; lets a rep open one specific item.
        if tasks_df is not None and not tasks_df.empty:
            with st.expander(":gray[Open the full body of a specific activity]"):
                picked = st.selectbox(
                    "Activity",
                    ["—"] + [
                        f"{_safe(r['ActivityDate'],'?')}  ·  {_safe(r['Subject'],'(no subject)')[:80]}  [{r['Id']}]"
                        for _, r in tasks_df.iterrows()
                    ],
                    label_visibility="collapsed",
                    key=f"tp_full_{aid}",
                )
                if picked != "—":
                    tid = picked.split("[")[-1].rstrip("]")
                    row = tasks_df[tasks_df["Id"] == tid].iloc[0]
                    st.markdown(f":gray[**Subject**]  {_safe(row['Subject'],'(no subject)')}")
                    st.markdown(f":gray[**Date**]  {_safe(row['ActivityDate'],'—')}  ·  :gray[**Status**]  {_safe(row['Status'],'—')}")
                    desc = _safe(row.get('Description'), '')
                    if desc:
                        st.text(desc)

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
            # Expanded reach: chatter posts/tracked-changes can be attached
            # not just to the account/contact/opportunity but also to any
            # case, task, lead, asset, or contract that traces back to this
            # clinic. The CTE materializes the full set of clinic-related
            # SF Ids once; downstream branches just JOIN against it.
            chatter = q("""
            WITH clinic_ids AS (
                SELECT ? AS Id
                UNION SELECT Id FROM contacts      WHERE AccountId=? AND IsDeleted=0
                UNION SELECT Id FROM opportunities WHERE AccountId=?
                UNION SELECT Id FROM cases         WHERE AccountId=?
                UNION SELECT Id FROM tasks         WHERE AccountId=? OR WhatId=?
                UNION SELECT Id FROM leads         WHERE ConvertedAccountId=?
                UNION SELECT Id FROM assets        WHERE AccountId=? AND IsDeleted=0
                UNION SELECT Id FROM contracts     WHERE AccountId=? AND IsDeleted=0
            ),
            -- Every FeedItem (post OR news_feed entry) that lives on a
            -- clinic-related parent. Comments join HERE via FeedItemId,
            -- not directly to the clinic.
            clinic_feed_items AS (
                SELECT fp.Id AS FeedItemId FROM feed_posts fp
                  JOIN clinic_ids ci ON ci.Id = fp.ParentId
                  WHERE fp.IsDeleted = 0
                UNION
                SELECT nf.Id FROM news_feed nf
                  JOIN clinic_ids ci ON ci.Id = nf.ParentId
            )
            SELECT * FROM (
                SELECT 'Post' AS Kind, fp.Id AS FeedId, fp.Title AS Subj, fp.Body,
                       fp.CreatedDate AS CreatedDate,
                       u.Name AS Author, NULL AS Field, NULL AS OldVal, NULL AS NewVal
                FROM feed_posts fp
                JOIN clinic_ids ci ON ci.Id = fp.ParentId
                LEFT JOIN users u ON u.Id = fp.InsertedById
                WHERE fp.IsDeleted = 0
                UNION ALL
                -- Tracked changes — collapse the Id/Name dup pairs SF stores
                -- by keeping the row whose value is NOT an SF Id (15/18-char).
                SELECT 'Tracked change', nf.Id, nf.Title, nf.Body, nf.CreatedDate,
                       u.Name, ftc.FieldName, ftc.OldValue, ftc.NewValue
                FROM news_feed nf
                JOIN clinic_ids ci ON ci.Id = nf.ParentId
                JOIN feed_tracked_change ftc ON ftc.FeedItemId = nf.Id
                LEFT JOIN users u ON u.Id = nf.InsertedById
                WHERE nf.Type = 'TrackedChange' AND ftc.FieldName IS NOT NULL
                  AND NOT (
                    (ftc.OldValue IS NOT NULL AND length(ftc.OldValue) IN (15, 18)
                     AND ftc.OldValue GLOB '[0-9a-zA-Z][0-9a-zA-Z][0-9a-zA-Z]*')
                    OR (ftc.NewValue IS NOT NULL AND length(ftc.NewValue) IN (15, 18)
                        AND ftc.NewValue GLOB '[0-9a-zA-Z][0-9a-zA-Z][0-9a-zA-Z]*')
                  )
                UNION ALL
                -- Comments — feed_comments.ParentId is the FeedItem the comment
                -- is on, NOT the underlying clinic record. Route via the
                -- clinic_feed_items CTE to surface the right comments.
                SELECT 'Comment', fc.Id, '(reply)', fc.CommentBody, fc.CreatedDate,
                       u.Name, NULL, NULL, NULL
                FROM feed_comments fc
                JOIN clinic_feed_items cfi ON cfi.FeedItemId = fc.ParentId
                LEFT JOIN users u ON u.Id = fc.InsertedById
                WHERE fc.IsDeleted = 0
            )
            ORDER BY CreatedDate DESC LIMIT 500
            """, (aid,)*9)
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
            WITH clinic_ids AS (
                SELECT ? AS Id
                UNION SELECT Id FROM contacts      WHERE AccountId=? AND IsDeleted=0
                UNION SELECT Id FROM opportunities WHERE AccountId=?
                UNION SELECT Id FROM tasks         WHERE AccountId=? OR WhatId=?
                UNION SELECT Id FROM cases         WHERE AccountId=?
                UNION SELECT Id FROM contracts     WHERE AccountId=? AND IsDeleted=0
                UNION SELECT Id FROM assets        WHERE AccountId=? AND IsDeleted=0
            )
            SELECT fb.content_version_id, fb.parent_id, fb.parent_type,
                   fb.title, fb.extension, fb.size_bytes, fb.is_inline, fb.release_bucket
            FROM file_blobs fb
            JOIN clinic_ids ci ON ci.Id = fb.parent_id
            ORDER BY fb.is_inline DESC, fb.title COLLATE NOCASE
            """, (aid, aid, aid, aid, aid, aid, aid, aid))
            st.caption(f":gray[{len(files_df):,} files in the Salesforce backup]")
            # Two release-tag families now host the binaries:
            #   files-2026-03-25-{a..e}  — pre-migration ContentVersion files (4,297 rows,
            #                              bucket column stores just 'a'-'e')
            #   files-2026-06-22-{a..f}  — post-migration Attachment + ContentVersion files
            #                              (5,524 rows, bucket column stores '2026-06-22-a' etc.)
            BASE_PRE  = "https://github.com/alexanderjordain/oncura-sf-database/releases/download/files-2026-03-25-"
            BASE_POST = "https://github.com/alexanderjordain/oncura-sf-database/releases/download/files-2026-06-22-"

            def _build_file_url(bucket_value, cv_id, ext):
                bv = str(bucket_value or 'a')
                if bv.startswith('2026-06-22-'):
                    # post-migration bucket value already encodes the date
                    return f"{BASE_POST}{bv[-1]}/{cv_id}.{ext}"
                # legacy single-letter bucket — pre-migration release
                return f"{BASE_PRE}{bv}/{cv_id}.{ext}"

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
                    parent_label = {
                        "001": "Account", "003": "Contact", "006": "Opportunity",
                        "00T": "Task", "002": "Note", "500": "Case",
                        "800": "Contract", "02i": "Asset",
                    }.get(parent_type, parent_type)
                    col_main, col_action = st.columns([5, 1])
                    col_main.markdown(f"**{title}.{ext}** · :gray[{size_str} · {parent_label}]")
                    col_action.link_button("Download", _build_file_url(bucket, cv_id, ext), use_container_width=True)

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
                def _size_label(b):
                    bb = _num(b)
                    if not bb or bb <= 0: return ""
                    if bb < 1024 * 1024:   return f"{bb/1024:,.0f} KB"
                    return f"{bb/1024/1024:,.1f} MB"
                disp["Size"] = disp["BodyLength"].apply(_size_label)
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
            # account_history table was dropped; entity_history is the unified
            # field-history store with ParentId pointing at any object. Surface
            # changes on this account + any of its opps/contacts/cases so reps
            # can see the full audit trail.
            df = q("""
            SELECT eh.CreatedDate, eh.ParentSobjectType AS ObjType,
                   eh.Field, eh.OldValue, eh.NewValue,
                   u.Name AS By
            FROM entity_history eh
            LEFT JOIN users u ON u.Id = eh.CreatedById
            WHERE eh.ParentId = ?
               OR eh.ParentId IN (SELECT Id FROM opportunities WHERE AccountId = ?)
               OR eh.ParentId IN (SELECT Id FROM contacts WHERE AccountId = ? AND IsDeleted = 0)
               OR eh.ParentId IN (SELECT Id FROM cases WHERE AccountId = ?)
            ORDER BY eh.CreatedDate DESC LIMIT 500
            """, (aid, aid, aid, aid))
            if df is None or df.empty:
                st.caption(":gray[No history data in this snapshot.]")
                st.markdown(":gray[—]")
            else:
                st.caption(f":gray[{len(df):,} field changes · most recent 500]")
                df["CreatedDate"] = df["CreatedDate"].astype(str).str.slice(0, 19)
                st.dataframe(
                    df, use_container_width=True, hide_index=True,
                    column_config={
                        "CreatedDate": st.column_config.TextColumn("Changed at", width="small"),
                        "ObjType":     st.column_config.TextColumn("On", width="small"),
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
    # dropna=False so opps whose AccountId/Clinic/State are NULL (e.g. converted-
    # from-lead deals whose account FK never linked back) still aggregate into
    # an "Unknown clinic" row instead of silently dropping ~$24.5M from the
    # leaderboard while the KPI metric above stays whole.
    won_df = df[df["IsWon"] == 1].copy()
    won_df["Clinic"] = won_df["Clinic"].fillna("(unknown clinic)")
    won_df["State"]  = won_df["State"].fillna("—")
    won_df["AccountId"] = won_df["AccountId"].fillna("")
    top = (won_df.groupby(["AccountId", "Clinic", "State"], as_index=False, dropna=False)
                 ["Amount"].sum()
                 .sort_values("Amount", ascending=False).head(50))
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

# ───────────────────── PAGE: SonixOne upgrade radar ─────────────────────
def page_sonixone():
    header(
        "SonixOne upgrades",
        "Clinics still running SonixOne."
    )

    import datetime as _dt
    today = _dt.date(2026, 6, 23)

    # Pull every account flagged as SonixOne, plus every SonixOne asset
    # so we can show serial counts + most-recent install per clinic.
    df = q("""
    SELECT a.Id, a.Name AS Clinic,
           a.BillingState AS State, a.BillingCity AS City,
           a.BillingStreet AS Street, a.Email AS Email,
           a.Phone, a.Hospital_ID, a.Partner, a.Past_Due,
           a.Ultrasound_System AS PrimarySystem,
           a.US_Install_Date AS PrimaryInstall,
           a.Most_Recent_Install_Date AS RecentInstall,
           a.OwnerId, a.Regional_Clinical_Specialist AS RCS,
           a.Territory, a.Last_OSR_Call_Visit AS LastOSRVisit,
           u.Name AS Owner,
           (SELECT COUNT(*) FROM assets s
             WHERE s.AccountId=a.Id AND s.IsDeleted=0
               AND s.Ultrasound_System LIKE '%SonixOne%') AS SonixUnits,
           (SELECT GROUP_CONCAT(COALESCE(s.SerialNumber, s.AssetSerialNumber), ', ')
              FROM assets s WHERE s.AccountId=a.Id AND s.IsDeleted=0
                AND s.Ultrasound_System LIKE '%SonixOne%') AS Serials,
           (SELECT MIN(s.InstallDate) FROM assets s
             WHERE s.AccountId=a.Id AND s.IsDeleted=0
               AND s.Ultrasound_System LIKE '%SonixOne%') AS EarliestSonixInstall,
           (SELECT MAX(s.InstallDate) FROM assets s
             WHERE s.AccountId=a.Id AND s.IsDeleted=0
               AND s.Ultrasound_System LIKE '%SonixOne%') AS LatestSonixInstall,
           (SELECT COUNT(*) FROM assets s2 WHERE s2.AccountId=a.Id AND s2.IsDeleted=0
             AND s2.Ultrasound_System IS NOT NULL AND s2.Ultrasound_System != ''
             AND s2.Ultrasound_System NOT LIKE '%SonixOne%') AS NonSonixUnits,
           (SELECT COALESCE(SUM(o.Amount),0) FROM opportunities o
             WHERE o.AccountId=a.Id AND o.IsWon=1) AS LifetimeWon
    FROM accounts a
    LEFT JOIN users u ON u.Id = a.OwnerId
    WHERE a.IsDeleted=0
      AND (a.Ultrasound_System LIKE '%SonixOne%'
           OR a.Id IN (SELECT AccountId FROM assets s
                       WHERE s.IsDeleted=0
                         AND s.Ultrasound_System LIKE '%SonixOne%'))
    ORDER BY a.Name COLLATE NOCASE
    """)

    if df.empty:
        st.info(":gray[No SonixOne clinics found in the snapshot.]"); return

    # Already-upgraded = clinic has both SonixOne AND another system on file
    df["AlreadyUpgraded"] = df["NonSonixUnits"].fillna(0) > 0

    def _years_installed(row):
        for col in ("EarliestSonixInstall", "PrimaryInstall"):
            v = row.get(col)
            if v is None: continue
            try:
                if pd.isna(v): continue
            except Exception:
                pass
            s = str(v).strip()
            if not s or s.lower() == "nan" or len(s) < 10: continue
            try:
                d = _dt.date.fromisoformat(s[:10])
                return round((_dt.date(2026,6,23) - d).days / 365.25, 1)
            except ValueError:
                continue
        return None
    df["YearsInstalled"] = df.apply(_years_installed, axis=1)

    # Header KPI strip
    total = len(df)
    upgrade_needed = int((~df["AlreadyUpgraded"]).sum())
    still_partner = int(df["Partner"].fillna(0).astype(int).eq(1).sum())
    units = int(df["SonixUnits"].fillna(0).sum())

    import html as _html
    st.markdown(
        f'<div class="chip-row">'
        f'<span class="chip chip-info">Clinics: {total}</span>'
        f'<span class="chip chip-info">Need upgrade: {upgrade_needed}</span>'
        f'<span class="chip chip-good">Already upgraded: {total - upgrade_needed}</span>'
        f'<span class="chip chip-info">Active partners: {still_partner}</span>'
        f'<span class="chip chip-mute">Total SonixOne units: {units}</span>'
        f'</div>', unsafe_allow_html=True,
    )

    # Filters
    c1, c2, c3, c4 = st.columns([1.5, 1.5, 1.2, 1.2])
    state_opts = sorted([s for s in df["State"].dropna().unique() if s])
    state_pick = c1.multiselect("State", state_opts, placeholder="All states")
    owner_opts = sorted([o for o in df["Owner"].dropna().unique() if o])
    owner_pick = c2.multiselect("Owner", owner_opts, placeholder="All owners")
    partner_only = c3.checkbox("Active partners only", value=True)
    hide_upgraded = c4.checkbox("Hide already-upgraded", value=True)

    f = df.copy()
    if state_pick: f = f[f["State"].isin(state_pick)]
    if owner_pick: f = f[f["Owner"].isin(owner_pick)]
    if partner_only: f = f[f["Partner"].fillna(0).astype(int).eq(1)]
    if hide_upgraded: f = f[~f["AlreadyUpgraded"]]

    # Sort: oldest installs first, then highest lifetime revenue
    f = f.sort_values(
        by=["YearsInstalled", "LifetimeWon"],
        ascending=[False, False],
        na_position="last",
    )

    st.caption(f":gray[{len(f):,} clinics meeting filters — sorted by install age (oldest first).]")

    # Render as a tight, call-list-ready table — required fields only.
    # Reps need: status flag, clinic name, location, who owns it, urgency
    # signal (years on platform), original install date, and phone to dial.
    disp = f.copy()
    disp_cols = ["Clinic", "Street", "City", "State", "Owner",
                 "YearsInstalled", "LastOSRVisit", "Phone", "Email"]
    disp = disp[disp_cols].rename(columns={
        "YearsInstalled": "Yrs old",
        "LastOSRVisit":   "Last OSR visit",
    })
    st.dataframe(
        disp, use_container_width=True, hide_index=True,
        height=min(640, 60 + 36*len(disp)),
        column_config={
            "Clinic":         st.column_config.TextColumn(width="large"),
            "Street":         st.column_config.TextColumn(width="medium"),
            "City":           st.column_config.TextColumn(width="small"),
            "State":          st.column_config.TextColumn(width="small"),
            "Owner":          st.column_config.TextColumn("Owner", width="medium"),
            "Yrs old":        st.column_config.NumberColumn(format="%.1f", width="small"),
            "Last OSR visit": st.column_config.DateColumn(format="YYYY-MM-DD", width="small"),
            "Phone":          st.column_config.TextColumn(width="medium"),
            "Email":          st.column_config.TextColumn(width="medium"),
        },
    )

    # CSV download — full data set (every column), not the trimmed table
    csv_bytes = f.to_csv(index=False).encode("utf-8")
    st.download_button(
        "Download list as CSV",
        data=csv_bytes,
        file_name=f"sonixone_upgrade_list_{today.isoformat()}.csv",
        mime="text/csv",
    )

    with st.expander(":gray[Open one clinic directly]"):
        if not f.empty:
            choice = st.selectbox(
                "Clinic",
                ["—"] + [f"{r['Clinic']} [{r['Id']}]" for _, r in f.iterrows()],
                label_visibility="collapsed",
            )
            if choice != "—":
                cid = choice.split("[")[-1].rstrip("]")
                st.markdown(f'[:material/arrow_forward: Open clinic detail page](?clinic={cid})')


# ───────────────────── Router ─────────────────────
if   page == "Clinic search":   page_search()
elif page == "Clinic detail":   page_detail()
elif page == "Sales activity":  page_activity()
elif page == "SonixOne upgrades": page_sonixone()
