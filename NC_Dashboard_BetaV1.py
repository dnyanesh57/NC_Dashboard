# digiqc_dashboard_NC_V2.6_BRAND.py
# Digital NC Register — Streamlit (SJCPL Brand)
# - Brand-locked palette: Blue(#00AEDA), Black(#000000), Grey(#939598), White(#FFFFFF)
# - Roboto everywhere (UI + Plotly)
# - Unique series colors generated from brand gradient (no reuse)
# - Robust data loader (normalize_colname + load_data from URL / Excel / CSV encodings)
# - Restored Timelines tab + New "Status" tab with click→highlight
# - R2C included across visuals
# --------------------------------------------------------------------
# Run:
#   pip install -U streamlit plotly pandas numpy openpyxl streamlit-plotly-events
#   streamlit run digiqc_dashboard_NC_V2.6_BRAND.py

from __future__ import annotations
from typing import Optional, Any, Tuple, List, Sequence
import io
import datetime as dt
import re
import numpy as np
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st

# Optional: capture Plotly click events
try:
    from streamlit_plotly_events import plotly_events  # type: ignore
    _PLOTLY_EVENTS_AVAILABLE = True
except Exception:
    _PLOTLY_EVENTS_AVAILABLE = False

# ---------- Page ----------
st.set_page_config(page_title="Digital NC Register — SJCPL", page_icon="🧭", layout="wide")

# ---------- SJCPL Brand (locked) ----------
WHITE = "#FFFFFF"
BLACK = "#000000"
GREY  = "#939598"
BLUE  = "#00AEDA"

SJCPL_STATUS = {
    "Closed":     BLACK,
    "Resolved":   BLACK,
    "Approved":   GREY,
    "In Process": BLUE,
    "In-Process": BLUE,
    "Open":       BLUE,
    "Redo":       GREY,
    "Rejected":   GREY,
    "Responded":  BLUE,
}

SJCPL_METRICS = {
    "Total":    BLUE,
    "Resolved": BLACK,
    "R2C":      GREY,
    "Open":     BLUE,
    "RespOnly": GREY,
}

THEMES = {
    "SJCPL": {
        "template": "plotly_white",
        "status_map": SJCPL_STATUS,
        "metric_map": SJCPL_METRICS,
    }
}
theme = "SJCPL"

# ---------- Brand-aware colour helpers (self-contained) ----------
def _hex_to_rgb(h: str) -> tuple[int, int, int]:
    h = h.lstrip("#")
    return tuple(int(h[i:i+2], 16) for i in (0, 2, 4))

def _rgb_to_hex(rgb: tuple[int, int, int]) -> str:
    return "#%02X%02X%02X" % rgb

def _mix(c1: str, c2: str, t: float) -> str:
    r1, g1, b1 = _hex_to_rgb(c1); r2, g2, b2 = _hex_to_rgb(c2)
    r = int(round(r1 + (r2 - r1) * t))
    g = int(round(g1 + (g2 - g1) * t))
    b = int(round(b1 + (b2 - b1) * t))
    return _rgb_to_hex((r, g, b))

def _text_on(bg_hex: str) -> str:
    r, g, b = _hex_to_rgb(bg_hex)
    lum = 0.2126*r + 0.7152*g + 0.0722*b
    return WHITE if lum < 140 else BLACK

def sample_brand_gradient(n: int, clamp: tuple[float, float] = (0.06, 0.94)) -> list[str]:
    """Evenly sample n distinct colours from WHITE→BLUE→BLACK, clamped away from pure white/black."""
    if n <= 0:
        return []
    xs = np.linspace(clamp[0], clamp[1], n)
    out: list[str] = []
    for t in xs:
        if t <= 0.5:
            out.append(_mix(WHITE, BLUE, (t - 0.0) / 0.5))
        else:
            out.append(_mix(BLUE, BLACK, (t - 0.5) / 0.5))
    # enforce uniqueness defensively
    seen = set(); uniq = []
    for i, c in enumerate(out):
        u = c.upper()
        if u in seen:
            tj = float(xs[i]) + 0.001
            tj = min(clamp[1], max(clamp[0], tj))
            c = _mix(WHITE, BLUE, (tj - 0.0)/0.5) if tj <= 0.5 else _mix(BLUE, BLACK, (tj - 0.5)/0.5)
            u = c.upper()
        uniq.append(c); seen.add(u)
    return uniq

def generate_brand_sequence(n: int) -> list[str]:
    """Start with base 3 brand colours, then extend with gradient so no colour repeats."""
    base = [BLUE, GREY, BLACK]
    if n <= len(base):
        return base[:n]
    return base + sample_brand_gradient(n - len(base))

def brand_map_for(values: Sequence) -> dict[str, str]:
    """Stable map: each unique value → a distinct brand-derived colour."""
    uniq_vals = list(dict.fromkeys(str(v) for v in values))
    cols = generate_brand_sequence(len(uniq_vals))
    return dict(zip(uniq_vals, cols))

# ---------- Plot helpers ----------
def style_fig(fig, theme_name: str):
    fig.update_layout(
        template=THEMES[theme_name]["template"],
        font=dict(family="Roboto, Arial, sans-serif", size=12, color=BLACK),
        legend=dict(title='', orientation="h", yanchor="bottom", y=1.05, xanchor="left", x=0),
        hoverlabel=dict(bgcolor="rgba(255,255,255,0.95)", font=dict(family="Roboto, Arial, sans-serif", color=BLACK)),
        bargap=0.22,
        margin=dict(l=10, r=10, t=80, b=30)
    )
    fig.update_traces(marker_line_width=0.5, marker_line_color="rgba(0,0,0,0.20)")
    fig.update_xaxes(showgrid=True, gridcolor="#ECEFF1", zeroline=False)
    fig.update_yaxes(showgrid=True, gridcolor="#ECEFF1", zeroline=False)
    return fig

def show_chart(fig, key: str):
    try:
        st.plotly_chart(fig, use_container_width=True, key=key)
    except Exception as e:
        st.warning(f"Chart failed ({key}): {e}")

# ---------- Explicit date/time parsing ----------
_date_ddmmyyyy_slash = re.compile(r"^\s*(\d{1,2})/(\d{1,2})/(\d{2,4})\s*$")
_date_ddmmyyyy_dash  = re.compile(r"^\s*(\d{1,2})-(\d{1,2})-(\d{2,4})\s*$")
_date_yyyymmdd_dash  = re.compile(r"^\s*(\d{4})-(\d{1,2})-(\d{1,2})\s*$")
_time_hhmm_ampm      = re.compile(r"^\s*(\d{1,2}):(\d{2})(?::(\d{2}))?\s*([ap]\.?m\.?)\s*$", re.I)
_time_hhmm_24        = re.compile(r"^\s*(\d{1,2}):(\d{2})(?::(\d{2}))?\s*$")

def _norm_year(y: int) -> int:
    if y < 100: return 2000 + y if y < 70 else 1900 + y
    return y

def _normalize_date_str(s: str) -> str:
    if not s or s.lower() in ("nan", "nat", "none"): return ""
    s = s.strip()
    m = _date_ddmmyyyy_slash.match(s) or _date_ddmmyyyy_dash.match(s)
    if m:
        d, mth, y = int(m.group(1)), int(m.group(2)), _norm_year(int(m.group(3)))
        try: return f"{y:04d}-{mth:02d}-{d:02d}"
        except Exception: return ""
    m = _date_yyyymmdd_dash.match(s)
    if m:
        y, mth, d = int(m.group(1)), int(m.group(2)), int(m.group(3))
        try: return f"{y:04d}-{mth:02d}-{d:02d}"
        except Exception: return ""
    return ""

def _normalize_time_str(s: str) -> str:
    if not s or s.lower() in ("nan", "nat", "none"): return ""
    s0 = s.strip().lower().replace(".", "")
    m = _time_hhmm_ampm.match(s0)
    if m:
        hh, mm = int(m.group(1)), int(m.group(2)); ss = int(m.group(3)) if m.group(3) else 0
        ampm = m.group(4).lower()
        if "pm" in ampm and hh < 12: hh += 12
        if "am" in ampm and hh == 12: hh = 0
        if not (0 <= hh <= 23 and 0 <= mm <= 59 and 0 <= ss <= 59): return ""
        return f"{hh:02d}:{mm:02d}:{ss:02d}"
    m = _time_hhmm_24.match(s0)
    if m:
        hh, mm = int(m.group(1)), int(m.group(2)); ss = int(m.group(3)) if m.group(3) else 0
        if not (0 <= hh <= 23 and 0 <= mm <= 59 and 0 <= ss <= 59): return ""
        return f"{hh:02d}:{mm:02d}:{ss:02d}"
    return ""

def _normalize_series_date(s: pd.Series) -> pd.Series:
    return s.astype(str).map(_normalize_date_str)

def _normalize_series_time(s: pd.Series) -> pd.Series:
    return s.astype(str).map(_normalize_time_str)

def combine_datetime(date_series: pd.Series, time_series: pd.Series) -> pd.Series:
    d = _normalize_series_date(date_series)
    t = _normalize_series_time(time_series)
    has_date = d != ""
    t = np.where((t == "") & has_date, "00:00:00", t)
    full = np.where(has_date, d + " " + t, "")
    out = pd.to_datetime(full, format="%Y-%m-%d %H:%M:%S", errors="coerce")
    return out

# ---------- Business rules / derived columns ----------
def _safe_get(df: pd.DataFrame, col: str) -> pd.Series:
    return df[col] if col in df.columns else pd.Series([np.nan] * len(df), index=df.index, name=col)

def extract_location_variable(raw: pd.Series) -> pd.Series:
    def _extract(val):
        if pd.isna(val): return val
        s = str(val)
        return s.rsplit("/", 1)[-1].strip() if "/" in s else s.strip()
    return raw.apply(_extract)

def humanize_td(td: pd.Series) -> pd.Series:
    def _fmt(x):
        if pd.isna(x): return ""
        total_seconds = int(x.total_seconds())
        if total_seconds < 0: return ""
        days, rem = divmod(total_seconds, 86400)
        hours, rem = divmod(rem, 3600)
        minutes, _ = divmod(rem, 60)
        parts = []
        if days: parts.append(f"{days}d")
        if hours: parts.append(f"{hours}h")
        if minutes: parts.append(f"{minutes}m")
        return " ".join(parts) if parts else "0m"
    return td.apply(_fmt)

def style_status_rows(df: pd.DataFrame, theme_name: str, highlight_mask: Optional[pd.Series] = None) -> "Styler":
    status_map = THEMES[theme_name]["status_map"]
    light_highlight = _mix(BLUE, WHITE, 0.85)
    def highlight(row):
        status = str(row.get("Current Status", "")).strip()
        bg = status_map.get(status, WHITE)
        txt = WHITE if bg in (BLACK, GREY) else BLACK
        if highlight_mask is not None:
            if bool(highlight_mask.loc[row.name]):
                bg = light_highlight
                txt = BLACK
        return [f"background-color: {bg}; color: {txt};"] * len(row)
    return df.style.apply(highlight, axis=1)

def add_derived_columns(df: pd.DataFrame) -> pd.DataFrame:
    # Ensure future/rolling-out fields exist
    for col in [
        "Root Cause Analysis","Correction","Corrective Action",
        "Labour Cost","Material Cost","Machinery Cost","Other Cost","Total Cost"
    ]:
        if col not in df.columns:
            df[col] = np.nan

    # Location Variable fix
    df["Location Variable (Fixed)"] = extract_location_variable(_safe_get(df, "Location Variable")) if "Location Variable" in df.columns else np.nan

    # Datetimes
    df["_RaisedOnDT"]     = combine_datetime(_safe_get(df, "Raised On Date"), _safe_get(df, "Raised On Time"))
    df["_DeadlineDT"]     = combine_datetime(_safe_get(df, "Deadline Date"), _safe_get(df, "Deadline Time"))
    df["_RespondedOnDT"]  = combine_datetime(_safe_get(df, "Responded On Date"), _safe_get(df, "Responded On Time"))
    df["_RejectedOnDT"]   = combine_datetime(_safe_get(df, "Rejected On Date"), _safe_get(df, "Rejected On Time"))
    df["_ClosedOnDT"]     = combine_datetime(_safe_get(df, "Closed On Date"), _safe_get(df, "Closed On Time"))

    # Effective resolution (vectorized): closed else responded>raised
    eff = df["_ClosedOnDT"].copy()
    mask_eff = eff.isna() & df["_RespondedOnDT"].notna() & df["_RaisedOnDT"].notna() & (df["_RespondedOnDT"] > df["_RaisedOnDT"])
    eff.loc[mask_eff] = df.loc[mask_eff, "_RespondedOnDT"]
    df["_EffectiveResolutionDT"] = eff

    # Timings
    df["Computed Closure Time (Hrs)"] = (df["_EffectiveResolutionDT"] - df["_RaisedOnDT"]).dt.total_seconds() / 3600.0
    df["Responding Time (Hrs)"]       = (df["_RespondedOnDT"] - df["_RaisedOnDT"]).dt.total_seconds() / 3600.0

    # Responded but NOT Closed
    df["_RespondedNotClosed_Flag"] = (
        df["_ClosedOnDT"].isna() &
        df["_RespondedOnDT"].notna() &
        df["_RaisedOnDT"].notna() &
        (df["_RespondedOnDT"] > df["_RaisedOnDT"])
    ).astype(int)

    # Close-after-response (only when effective >= responded)
    mask_car = df["_EffectiveResolutionDT"].notna() & df["_RespondedOnDT"].notna() & (df["_EffectiveResolutionDT"] >= df["_RespondedOnDT"])
    df["Close After Response (Hrs)"] = np.where(
        mask_car,
        (df["_EffectiveResolutionDT"] - df["_RespondedOnDT"]).dt.total_seconds() / 3600.0,
        np.nan
    )

    # SLA
    df["SLA Met"] = np.where(
        df["_DeadlineDT"].notna() & df["_EffectiveResolutionDT"].notna(),
        df["_EffectiveResolutionDT"] <= df["_DeadlineDT"],
        np.nan
    )

    # Total cost fallback
    parts = ["Labour Cost","Material Cost","Machinery Cost","Other Cost"]
    if "Total Cost" in df.columns:
        part_sum = df[[p for p in parts if p in df.columns]].apply(pd.to_numeric, errors="coerce").sum(axis=1, min_count=1)
        df["Total Cost"] = pd.to_numeric(df["Total Cost"], errors="coerce").fillna(part_sum)

    # -------- Rejected → Closed flags (inferred + strict) --------
    def _nz(series_name: str) -> pd.Series:
        s = _safe_get(df, series_name)
        return s.where(s.notna(), "").astype(str).str.strip()

    has_reject_evidence = (
        df["_RejectedOnDT"].notna() |
        _nz("Rejected By").ne("") | _nz("Rejected Comment").ne("") |
        _nz("Rejected On Date").ne("") | _nz("Rejected On Time").ne("")
    )
    cur_status = _nz("Current Status").str.lower()
    closedish  = cur_status.str.contains(r"\b(closed|approved|resolved|complete)\b", regex=True)
    has_close_evidence = (
        df["_ClosedOnDT"].notna() | closedish |
        _nz("Closed By").ne("") | _nz("Closed Comment").ne("") |
        _nz("Closed On Date").ne("") | _nz("Closed On Time").ne("")
    )
    df["_R2C_Flag"] = (has_reject_evidence & has_close_evidence).astype(int)

    both_dt = df["_RejectedOnDT"].notna() & df["_ClosedOnDT"].notna()
    df["_R2C_Strict_Flag"] = both_dt.astype(int)
    dur_hours = np.where(both_dt, (df["_ClosedOnDT"] - df["_RejectedOnDT"]).dt.total_seconds() / 3600.0, np.nan)
    df["R2C Hours (>=0)"] = np.where(np.isfinite(dur_hours), np.maximum(dur_hours, 0.0), np.nan)

# -------- Last Status Change (for Status tab) --------
# Candidate events and their timestamps; choose latest non-null as "last"
    last_dt = pd.concat([
        df["_ClosedOnDT"].rename("Closed"),
        df["_RejectedOnDT"].rename("Rejected"),
        df["_RespondedOnDT"].rename("Responded"),
        df["_EffectiveResolutionDT"].rename("Effective"),
    ], axis=1)
    
    df["_LastStatusChangeDT"] = last_dt.max(axis=1, skipna=True)

# Label of the event that produced the latest timestamp (object dtype — no np.where with NaN)
    latest = df["_LastStatusChangeDT"]
    evt = pd.Series(pd.NA, index=df.index, dtype="object")

    m = latest.notna() & df["_ClosedOnDT"].eq(latest)
    evt.loc[m] = "Closed"
    m = latest.notna() & df["_RejectedOnDT"].eq(latest)
    evt.loc[m] = "Rejected"
    m = latest.notna() & df["_RespondedOnDT"].eq(latest)
    evt.loc[m] = "Responded"
    m = latest.notna() & df["_EffectiveResolutionDT"].eq(latest)
    evt.loc[m] = "Effective"

    df["_LastStatusEvent"] = evt  # remains object; downstream code can .fillna("—")


    # Label of the event that produced the latest timestamp (priority if ties: Closed > Rejected > Responded > Effective)
    latest = df["_LastStatusChangeDT"]
    evt = np.where(df["_ClosedOnDT"].eq(latest), "Closed",
          np.where(df["_RejectedOnDT"].eq(latest), "Rejected",
          np.where(df["_RespondedOnDT"].eq(latest), "Responded",
          np.where(df["_EffectiveResolutionDT"].eq(latest), "Effective", np.nan))))
    df["_LastStatusEvent"] = pd.Series(evt, index=df.index)

    return df

# ---------- Metrics header ----------
def metrics_summary(df: pd.DataFrame, theme_name: str):
    metric_colors = THEMES[theme_name]["metric_map"]
    total_issues = len(df)
    resolved = (df["_EffectiveResolutionDT"].notna()).sum()
    open_issues = total_issues - resolved
    median_response = pd.to_timedelta(df["Responding Time (Hrs)"], unit="h").median(skipna=True)
    median_close    = pd.to_timedelta(df["Computed Closure Time (Hrs)"], unit="h").median(skipna=True)
    sla_known = df["SLA Met"].dropna() if "SLA Met" in df.columns else pd.Series(dtype=float)
    sla_rate = (sla_known.mean() * 100) if len(sla_known) else np.nan

    def _fmt(td):
        if pd.isna(td): return "—"
        secs = int(td.total_seconds())
        d, r = divmod(secs, 86400); h, r = divmod(r, 3600); m, _ = divmod(r, 60)
        if d or h or m: return f"{d}d {h}h {m}m"
        return "0m"

    t1, t2, t3, t4, t5, t6 = st.columns(6)
    with t1: st.metric("Total Issues", f"{total_issues}")
    with t2: st.metric("Resolved (Closed/Effective)", f"{resolved}")
    with t3: st.metric("Open / Unresolved", f"{open_issues}")
    with t4: st.metric("Median Closure Time", _fmt(median_close))
    with t5: st.metric("Median Responding Time", _fmt(median_response))
    with t6: st.metric("SLA Met Rate", f"{sla_rate:.1f}%" if pd.notna(sla_rate) else "—")

# ----------------------------- Load data ----------------------------
def normalize_colname(c: str) -> str:
    """Keep official column labels intact, but clean whitespace and unicode quirks."""
    s = str(c).replace("\u2013", "-").replace("\u2014", "-").replace("\u00A0", " ")
    s = re.sub(r"\s+", " ", s).strip()
    return s

def load_data(file: Optional[io.BytesIO]) -> pd.DataFrame:
    """
    Robust reader:
      - If file is None: pull demo CSV from GitHub
      - Else: try Excel, else CSV with multiple encodings
      - Normalize column names and drop duplicate columns
    """
    if file is None:
        default_path = "https://raw.githubusercontent.com/dnyanesh57/NC_Dashboard/main/data/CSV-INSTRUCTION-DETAIL-REPORT-09-08-2025-04-25-44.csv"
        try:
            df = pd.read_csv(default_path)
        except Exception:
            st.error("No file uploaded and demo CSV not found in working directory.")
            st.stop()
    else:
        name = getattr(file, "name", "uploaded.csv").lower()
        if name.endswith(".xlsx") or name.endswith(".xls"):
            df = pd.read_excel(file)
        else:
            for enc in [None, "utf-8", "utf-8-sig", "latin-1"]:
                try:
                    file.seek(0)
                    df = pd.read_csv(file, encoding=enc)
                    break
                except Exception:
                    continue
            else:
                st.error("Could not read the uploaded CSV with common encodings.")
                st.stop()
    df = df.rename(columns={c: normalize_colname(c) for c in df.columns})
    df = df.loc[:, ~pd.Series(df.columns).duplicated().values]
    return df

# ---------- Sidebar (brand-locked) ----------
with st.sidebar:
    st.title("🧭 Digital NC Register")
    st.caption("SJCPL brand-locked UI (Roboto + Blue/Black/Grey/White)")
    logo_url = st.text_input("Logo URL (optional)", value="")
    uploaded = st.file_uploader("Upload Issue Register (CSV / Excel)", type=["csv","xlsx","xls"], key="uploader")

# ---------- Sticky Header (branding) ----------
st.markdown(
    f"""
    <style>
    @import url('https://fonts.googleapis.com/css2?family=Roboto:wght@300;400;500;700;900&display=swap');
    html, body, [class*="css"], .stApp {{
      font-family: 'Roboto', Arial, sans-serif !important;
      color: {BLACK};
    }}
    :root {{
      --sj-primary: {BLUE};
      --sj-surface: {WHITE};
      --sj-text: {BLACK};
      --sj-muted: {GREY};
    }}
    .sj-header {{
      position: sticky; top: 0; z-index: 1000;
      background: linear-gradient(90deg, {BLACK} 0%, {BLUE} 100%);
      border-radius: 14px;
      color: {WHITE};
      padding: 12px 16px;
      margin: -1rem -1rem 0.5rem -1rem;
    }}
    .sj-header-inner {{
      display:flex; justify-content:space-between; align-items:center;
      gap: 1rem;
    }}
    .sj-title {{
      font-weight: 800; font-size: 20px; color: {WHITE};
    }}
    .sj-subtle {{ color: rgba(255,255,255,0.90); font-size: 13px; }}
    .sj-logo {{ height: 32px; object-fit: contain; }}
    </style>
    <div class="sj-header">
      <div class="sj-header-inner">
        <div>
          <div class="sj-title">DigiQC — EQC Insights Dashboard (v2.6)</div>
          <div class="sj-subtle">SJCPL visual theme · Roboto · Brand colors only</div>
        </div>
        <div>
          {"<img class='sj-logo' src='" + logo_url + "' />" if logo_url else ""}
        </div>
      </div>
    </div>
    """,
    unsafe_allow_html=True
)

# ---------- Data load + preprocess ----------
try:
    df_raw = load_data(uploaded)
except Exception as e:
    st.error(f"Failed to load data: {e}")
    st.stop()

@st.cache_data(show_spinner=False)
def preprocess(df_in: pd.DataFrame) -> pd.DataFrame:
    df = df_in.copy()
    df.columns = [c.strip() for c in df.columns]
    return add_derived_columns(df)

df = preprocess(df_raw)

# ---------- Global filters ----------
def get_date_range_inputs(df: pd.DataFrame) -> Tuple[Optional[dt.date], Optional[dt.date]]:
    enable = st.checkbox("Enable Raised On date filter", value=False, key="datefilter-enable")
    if not enable:
        return None, None
    if df["_RaisedOnDT"].notna().any():
        dmin = pd.to_datetime(df["_RaisedOnDT"].min()).date()
        dmax = pd.to_datetime(df["_RaisedOnDT"].max()).date()
    else:
        today = dt.date.today()
        dmin = dmax = today
    picked = st.date_input("Raised On — Range", value=(dmin, dmax), key="datefilter-range")
    if isinstance(picked, tuple) and len(picked) == 2:
        return picked[0], picked[1]
    return picked, picked

def filtered_view(df: pd.DataFrame) -> pd.DataFrame:
    with st.sidebar:
        st.markdown("#### Filters")
        def options(col: str):
            return sorted(df.get(col, pd.Series(dtype=str)).dropna().astype(str).unique().tolist())
        proj          = st.multiselect("Project Name", options("Project Name"), key="f-proj")
        status        = st.multiselect("Current Status", options("Current Status"), key="f-status")
        types_l0      = st.multiselect("Type L0", options("Type L0"), key="f-typeL0")
        types_l1      = st.multiselect("Type L1", options("Type L1"), key="f-typeL1")
        types_l2      = st.multiselect("Type L2", options("Type L2"), key="f-typeL2")
        tags1         = st.multiselect("Tag 1", options("Tag 1"), key="f-tag1")
        tags2         = st.multiselect("Tag 2", options("Tag 2"), key="f-tag2")
        raised_by     = st.multiselect("Raised By", options("Raised By"), key="f-raisedby")
        assigned_team = st.multiselect("Assigned Team", options("Assigned Team"), key="f-ateam")
        assigned_user = st.multiselect("Assigned Team User", options("Assigned Team User"), key="f-auser")
        date_min, date_max = get_date_range_inputs(df)

    m = np.ones(len(df), dtype=bool)
    def match(col: str, sel: list):
        if sel:
            return df.get(col).astype(str).isin([str(x) for x in sel]).to_numpy()
        return np.ones(len(df), dtype=bool)

    if proj:          m &= match("Project Name", proj)
    if status:        m &= match("Current Status", status)
    if types_l0:      m &= match("Type L0", types_l0)
    if types_l1:      m &= match("Type L1", types_l1)
    if types_l2:      m &= match("Type L2", types_l2)
    if tags1:         m &= match("Tag 1", tags1)
    if tags2:         m &= match("Tag 2", tags2)
    if raised_by:     m &= match("Raised By", raised_by)
    if assigned_team: m &= match("Assigned Team", assigned_team)
    if assigned_user: m &= match("Assigned Team User", assigned_user)
    if date_min:      m &= (df["_RaisedOnDT"].dt.date >= date_min).fillna(False).to_numpy()
    if date_max:      m &= (df["_RaisedOnDT"].dt.date <= date_max).fillna(False).to_numpy()

    return df.loc[m].copy()

df_filtered = filtered_view(df)
st.divider()

metric_colors = THEMES[theme]["metric_map"]
status_colors = THEMES[theme]["status_map"]

mask_r2c_inferred   = (df_filtered["_R2C_Flag"] == 1)
mask_responly       = (df_filtered["_RespondedNotClosed_Flag"] == 1)

r2c_count_scope     = int(mask_r2c_inferred.sum())
resp_only_count     = int(mask_responly.sum())
total_ncs_scope     = len(df_filtered)

# ---------- Tabs ----------
tabs = st.tabs([
    "Overview",
    "Status",            # <-- new rich tab
    "Project Status",
    "Project Explorer",
    "Tower-Wise",
    "User-Wise",
    "Timelines",
    "NC-View",
    "Sketch-View",
    "NC Table",
])

# ---------- Overview ----------
with tabs[0]:
    st.header("Overview")
    metrics_summary(df_filtered, theme)

    comp = pd.DataFrame({"Metric": ["Total","Rejected→Closed"], "Count": [total_ncs_scope, r2c_count_scope]})
    cmap_comp = brand_map_for(comp["Metric"].tolist())
    fig_comp = px.bar(
        comp.sort_values("Count"),
        x="Count", y="Metric", orientation="h",
        text_auto=True, title="Comparative — Total vs Rejected→Closed (inferred)",
        color="Metric", color_discrete_map=cmap_comp
    )
    show_chart(style_fig(fig_comp, theme), key="ov-comp-r2c")

    if "Current Status" in df_filtered.columns:
        vc = df_filtered["Current Status"].fillna("—").astype(str).value_counts().reset_index()
        vc.columns = ["Current Status","Count"]
        cmap_stat = brand_map_for(vc["Current Status"].tolist())
        fig_sd = px.bar(vc, x="Current Status", y="Count", text_auto=True, title="Current Status Distribution",
                        color="Current Status", color_discrete_map=cmap_stat)
        fig_sd.update_xaxes(tickangle=0, tickfont=dict(size=11))
        show_chart(style_fig(fig_sd, theme), key="ov-status-dist")

    st.subheader("Response vs Closure — Time Distributions")
    c3, c4 = st.columns(2)
    with c3:
        series = pd.to_numeric(df_filtered["Responding Time (Hrs)"], errors="coerce")
        series = series.replace([np.inf, -np.inf], np.nan).dropna()
        series = series[series >= 0]
        if len(series):
            fig = px.histogram(
                x=series, nbins=30,
                labels={"x": "Responding Time (Hrs)"},
                opacity=0.9, color_discrete_sequence=[metric_colors["RespOnly"]]
            )
            fig.update_traces(showlegend=False)
            fig.update_layout(title="Responding Time (Hrs)")
            show_chart(style_fig(fig, theme), key="tab0-hist-responding")
        else:
            st.info("No data for Responding Time.")
    with c4:
        series = pd.to_numeric(df_filtered["Computed Closure Time (Hrs)"], errors="coerce")
        series = series.replace([np.inf, -np.inf], np.nan).dropna()
        series = series[series >= 0]
        if len(series):
            fig = px.histogram(
                x=series, nbins=30,
                labels={"x": "Computed Closure Time (Hrs)"},
                opacity=0.9, color_discrete_sequence=[metric_colors["Resolved"]]
            )
            fig.update_traces(showlegend=False)
            fig.update_layout(title="Computed Closure Time (Hrs)")
            show_chart(style_fig(fig, theme), key="tab0-hist-closure")
        else:
            st.info("No data for Computed Closure Time.")

# ---------- Status (new, rich) ----------
with tabs[1]:
    st.header("Status — What changed?")

    # Time window selector
    period = st.selectbox("Show status changes in:", ["Today", "Last 3 days", "This week", "All available"], index=0, key="status-period")
    now = pd.Timestamp.utcnow().tz_localize("UTC").tz_convert(None)  # naive UTC->naive for compare
    today = now.normalize()
    start_of_week = today - pd.Timedelta(days=today.weekday())  # Monday

    if period == "Today":
        mwin = df_filtered["_LastStatusChangeDT"].dt.normalize() == today
        window_label = f"Today ({today.date()})"
    elif period == "Last 3 days":
        cutoff = today - pd.Timedelta(days=2)
        mwin = df_filtered["_LastStatusChangeDT"] >= cutoff
        window_label = f"Last 3 days (since {cutoff.date()})"
    elif period == "This week":
        mwin = df_filtered["_LastStatusChangeDT"] >= start_of_week
        window_label = f"This week (since {start_of_week.date()})"
    else:
        mwin = df_filtered["_LastStatusChangeDT"].notna()
        window_label = "All available"

    changed = df_filtered.loc[mwin & df_filtered["_LastStatusChangeDT"].notna()].copy()
    changed.sort_values("_LastStatusChangeDT", ascending=False, inplace=True)

    # Top KPIs for this window
    cc1, cc2, cc3, cc4 = st.columns(4)
    with cc1: st.metric("Changed NCs", f"{len(changed)}")
    with cc2: st.metric("Projects", f"{changed.get('Project Name','').nunique()}")
    with cc3: st.metric("R2C (inferred)", f"{int(changed['_R2C_Flag'].sum())}")
    with cc4: st.metric("Resp-not-Closed", f"{int(changed['_RespondedNotClosed_Flag'].sum())}")

    # Helper to render clickable chart (falls back to selectbox)
    def clickable_bar(df_in: pd.DataFrame, x_col: str, y_col: str, title: str, key: str) -> Optional[str]:
        cmap = brand_map_for(df_in[x_col].tolist())
        fig = px.bar(df_in, x=x_col, y=y_col, text_auto=True, title=title,
                     color=x_col, color_discrete_map=cmap)
        fig = style_fig(fig, theme)
        sel_name: Optional[str] = None
        if _PLOTLY_EVENTS_AVAILABLE:
            pts = plotly_events(fig, click_event=True, hover_event=False, select_event=False,
                                override_height=420, key=f"plt_{key}")
            if pts and isinstance(pts, list) and len(pts) > 0:
                # Plotly gives category in "x"
                sel_name = str(pts[0].get("x", ""))
        else:
            show_chart(fig, key=key)
            # Fallback selector
            with st.expander("Select to focus (click capture add-on not installed)"):
                sel_name = st.selectbox(f"Focus {x_col}", ["(All)"] + df_in[x_col].tolist(), index=0, key=f"sel_{key}")
                if sel_name == "(All)":
                    sel_name = None
        return sel_name

    ctop1, ctop2 = st.columns(2)
    with ctop1:
        # Last Status Event counts
        ev_counts = (changed["_LastStatusEvent"].fillna("—").astype(str)
                     .value_counts().rename_axis("Event").reset_index(name="Count"))
        sel_event = clickable_bar(ev_counts, "Event", "Count",
                                  f"Last Status Event — {window_label} (click to focus)",
                                  key="status_event_counts")
    with ctop2:
        # Current Status distribution within changed
        st_counts = (changed["Current Status"].fillna("—").astype(str)
                     .value_counts().rename_axis("Status").reset_index(name="Count"))
        sel_status = clickable_bar(st_counts, "Status", "Count",
                                   f"Current Status (of changed) — {window_label} (click to focus)",
                                   key="status_status_counts")

    # R2C donut
    cdonut1, cdonut2 = st.columns(2)
    with cdonut1:
        lab = ["R2C", "Not R2C"]
        val = [int(changed["_R2C_Flag"].sum()), int((~changed["_R2C_Flag"].astype(bool)).sum())]
        cmap = brand_map_for(lab)
        fig_r2c = px.pie(values=val, names=lab, title="R2C Split (inferred)", hole=0.55,
                         color=lab, color_discrete_map=cmap)
        fig_r2c.update_traces(textposition='inside', textinfo='percent+label')
        show_chart(style_fig(fig_r2c, theme), key="status-r2c-donut")

    with cdonut2:
        # Mini timeline of changes per day in window
        ch = changed.copy()
        ch["Date"] = ch["_LastStatusChangeDT"].dt.date
        daily = ch.groupby("Date").size().reset_index(name="Changes")
        cmap = brand_map_for(daily["Date"].astype(str).tolist())
        fig_day = px.bar(daily, x="Date", y="Changes", title=f"Changes per Day — {window_label}",
                         color="Date", color_discrete_map=cmap, text_auto=True)
        fig_day.update_layout(showlegend=False)
        show_chart(style_fig(fig_day, theme), key="status-daily-changes")

    # Assignee-wise within window (stack by Event)
    if {"Assigned Team User","_LastStatusEvent"}.issubset(changed.columns):
        stack = (changed.assign(Assignee=changed["Assigned Team User"].fillna("—").astype(str),
                                Event=changed["_LastStatusEvent"].fillna("—").astype(str))
                 .groupby(["Assignee","Event"]).size().reset_index(name="Count"))
        cmap = brand_map_for(stack["Event"].tolist())
        fig_stack = px.bar(stack, x="Assignee", y="Count", color="Event", barmode="stack",
                           title="Assignee — Stack by Last Status Event",
                           color_discrete_map=cmap)
        fig_stack.update_xaxes(tickangle=30)
        show_chart(style_fig(fig_stack, theme), key="status-assignee-stack")

    st.subheader("Changed NCs")
    # Build highlight mask based on selection
    focus_mask = pd.Series([False]*len(changed), index=changed.index)
    focus_label = None
    if sel_event:
        focus_mask = focus_mask | (changed["_LastStatusEvent"].astype(str) == str(sel_event))
        focus_label = f"Event = {sel_event}"
    if sel_status:
        focus_mask = focus_mask | (changed["Current Status"].astype(str) == str(sel_status))
        focus_label = (f"{focus_label} OR " if focus_label else "") + f"Status = {sel_status}"

    if focus_label:
        st.caption(f"Highlighting rows where: {focus_label}")
    else:
        st.caption("Click a bar above to highlight matching rows (or use the fallback selector if offered).")

    show_cols = [c for c in [
        "Reference ID","Project Name","Location / Reference","Location Variable (Fixed)",
        "Type L0","Type L1","Type L2","Tag 1","Tag 2",
        "Assigned Team","Assigned Team User","Current Status",
        "Responding Time (Hrs)","Computed Closure Time (Hrs)","Close After Response (Hrs)",
        "_LastStatusEvent","_LastStatusChangeDT",
        "_RespondedNotClosed_Flag","_R2C_Flag","_R2C_Strict_Flag"
    ] if c in changed.columns]

    view = changed[show_cols].copy()
    # Sort to put highlights on top
    if focus_mask.any():
        view = view.assign(_HL=focus_mask).sort_values(["_HL","_LastStatusChangeDT"], ascending=[False, False]).drop(columns="_HL")

    # Styled HTML for row shading + highlight
    try:
        st.write(style_status_rows(view.head(1500), theme, highlight_mask=focus_mask).to_html(), unsafe_allow_html=True)
    except Exception:
        st.dataframe(view.head(1500), use_container_width=True)

    csv_data = view.to_csv(index=False).encode("utf-8")
    st.download_button("⬇️ Download changed rows (CSV)", data=csv_data, file_name="digiqc_status_changed.csv",
                       mime="text/csv", key="dl-status-changed")

# ---------- Project Status ----------
with tabs[2]:
    st.header("Project Status")
    if "Project Name" in df_filtered.columns:
        grp = df_filtered.groupby("Project Name").agg(
            Total=("Reference ID","count") if "Reference ID" in df_filtered.columns else ("Project Name","count"),
            Resolved=("_EffectiveResolutionDT", lambda x: x.notna().sum()),
            R2C=("_R2C_Flag", "sum"),
            RespOnly=("_RespondedNotClosed_Flag", "sum"),
            Median_Close_Hrs=("Computed Closure Time (Hrs)", "median"),
            SLA_Met=("SLA Met", "mean"),
        ).reset_index()
        if "SLA_Met" in grp.columns:
            grp["SLA_Met"] = (grp["SLA_Met"] * 100).round(1)
        st.dataframe(grp, use_container_width=True)

        melted = grp.melt(id_vars=["Project Name"], value_vars=["Total","Resolved","R2C","RespOnly"], var_name="Metric", value_name="Count")
        cmap = brand_map_for(melted["Metric"].tolist())
        fig_proj = px.bar(melted, x="Project Name", y="Count", color="Metric", barmode="group",
                          title="Project — Total vs Resolved vs Rejected→Closed vs Responded-not-Closed",
                          color_discrete_map=cmap)
        fig_proj.update_xaxes(tickangle=30, tickfont=dict(size=11))
        show_chart(style_fig(fig_proj, theme), key="tab1-project-bar")
    else:
        st.info("Column 'Project Name' not found.")

# ---------- Project Explorer ----------
with tabs[3]:
    st.header("Project Explorer")
    c1, c2 = st.columns([1,2])
    def bar_top_counts(df_in: pd.DataFrame, col: str, key: str, title: Optional[str] = None):
        if col not in df_in.columns:
            st.info(f"Column '{col}' not found."); return
        labels = df_in[col].fillna("—").astype(str)
        vc = labels.value_counts(dropna=False).head(15)
        counts = pd.DataFrame({col: vc.index.astype(str).tolist(), "Count": vc.values})
        cmap = brand_map_for(counts[col].tolist())
        fig = px.bar(
            counts.sort_values("Count", ascending=True),
            x="Count", y=col, orientation="h", title=title or f"Top {col}",
            color=col, color_discrete_map=cmap, text_auto=True
        )
        fig.update_layout(yaxis=dict(autorange="reversed"))
        show_chart(style_fig(fig, theme), key=key)

    with c1:
        st.caption("Counts by Types & Tags")
        for colname, key in [("Type L0","typeL0"), ("Type L1","typeL1"), ("Type L2","typeL2"), ("Tag 1","tag1"), ("Tag 2","tag2")]:
            if colname in df_filtered.columns:
                bar_top_counts(df_filtered, colname, key=f"tab2-{key}", title=f"Top {colname}")

    with c2:
        st.caption("Counts by Status, SLA, R→C and Responded-not-Closed")
        if "Current Status" in df_filtered.columns:
            labels = df_filtered["Current Status"].fillna("—").astype(str)
            vc = labels.value_counts(dropna=False)
            counts = pd.DataFrame({"Current Status": vc.index.astype(str).tolist(), "Count": vc.values})
            cmap = brand_map_for(counts["Current Status"].tolist())
            fig_st = px.bar(counts, x="Current Status", y="Count",
                            color="Current Status", color_discrete_map=cmap, text_auto=True,
                            title="Current Status")
            fig_st.for_each_trace(lambda t: t.update(marker=dict(line_width=0.5)))
            show_chart(style_fig(fig_st, theme), key="tab2-status")

        if "SLA Met" in df_filtered.columns:
            work = df_filtered.copy()
            work["SLA State"] = df_filtered["SLA Met"].map({True: "Met", False: "Missed"}).fillna("Unknown")
            vc = work["SLA State"].value_counts()
            counts = pd.DataFrame({"SLA State": vc.index.tolist(), "Count": vc.values})
            cmap = brand_map_for(counts["SLA State"].tolist())
            fig_sla = px.bar(counts, x="SLA State", y="Count", color="SLA State",
                             color_discrete_map=cmap, text_auto=True, title="SLA State")
            show_chart(style_fig(fig_sla, theme), key="tab2-sla")

        if "Assigned Team User" in df_filtered.columns and r2c_count_scope > 0:
            counts = (df_filtered.loc[mask_r2c_inferred, "Assigned Team User"]
                      .fillna("—").astype(str)
                      .value_counts().rename_axis("Assignee").reset_index(name="Rejected→Closed"))
            cmap = brand_map_for(counts["Assignee"].tolist())
            fig_r2c_scope = px.bar(counts.sort_values("Rejected→Closed"),
                                   x="Rejected→Closed", y="Assignee", orientation="h",
                                   title="Rejected → Closed — by Assignee (inferred, scope)",
                                   color="Assignee", color_discrete_map=cmap)
            show_chart(style_fig(fig_r2c_scope, theme), key="tab2-r2c-assignee")

        if "Assigned Team User" in df_filtered.columns and resp_only_count > 0:
            resp_counts = (df_filtered.loc[mask_responly, "Assigned Team User"]
                           .fillna("—").astype(str)
                           .value_counts().rename_axis("Assignee").reset_index(name="Responded not Closed"))
            cmap = brand_map_for(resp_counts["Assignee"].tolist())
            fig_resp_scope = px.bar(resp_counts.sort_values("Responded not Closed"),
                                    x="Responded not Closed", y="Assignee", orientation="h",
                                    title="Responded but NOT Closed — by Assignee (scope)",
                                    color="Assignee", color_discrete_map=cmap)
            show_chart(style_fig(fig_resp_scope, theme), key="tab2-responly-assignee")

# ---------- Tower-Wise ----------
with tabs[4]:
    st.header("Tower-Wise")
    tower_col = "Location L1" if "Location L1" in df_filtered.columns else None

    if tower_col:
        grp = df_filtered.groupby(tower_col).agg(
            Total=("Reference ID","count") if "Reference ID" in df_filtered.columns else (tower_col,"count"),
            Resolved=("_EffectiveResolutionDT", lambda x: x.notna().sum()),
            R2C=("_R2C_Flag", "sum"),
            RespOnly=("_RespondedNotClosed_Flag", "sum"),
        ).reset_index()
        st.dataframe(grp.sort_values("Total", ascending=False), use_container_width=True)

        melted = grp.melt(id_vars=[tower_col], value_vars=["Total","Resolved","R2C","RespOnly"], var_name="Metric", value_name="Count")
        cmap = brand_map_for(melted["Metric"].tolist())
        fig_tower = px.bar(melted, x=tower_col, y="Count", color="Metric", barmode="group",
                           title="Tower — Total vs Resolved vs Rejected→Closed vs Responded-not-Closed",
                           color_discrete_map=cmap)
        fig_tower.update_xaxes(tickangle=30, tickfont=dict(size=11))
        show_chart(style_fig(fig_tower, theme), key="tab3-tower-group")
    else:
        st.info("Column 'Location L1' not found.")

# ---------- User-Wise ----------
with tabs[5]:
    st.header("User-Wise")

    if "Assigned Team User" in df_filtered.columns:
        usr = df_filtered.groupby("Assigned Team User").agg(
            Total=("Reference ID","count") if "Reference ID" in df_filtered.columns else ("Assigned Team User","count"),
            Resolved=("_EffectiveResolutionDT", lambda x: x.notna().sum()),
            R2C=("_R2C_Flag", "sum"),
            RespOnly=("_RespondedNotClosed_Flag", "sum"),
            Median_Close_Hrs=("Computed Closure Time (Hrs)", "median"),
        ).reset_index()

        maxN = max(1, len(usr))
        topN = st.slider("Top N users (grouped bar)", 5, max(5, maxN), min(25, maxN), key="uw-topn")

        long_u = usr.melt(id_vars=["Assigned Team User"], value_vars=["Resolved","R2C","RespOnly"],
                          var_name="Metric", value_name="Count")

        tot = long_u.groupby("Assigned Team User")["Count"].sum().sort_values(ascending=False).head(topN).index
        long_u_top = long_u[long_u["Assigned Team User"].isin(tot)]

        cmap = brand_map_for(long_u_top["Metric"].tolist())
        fig_u_grp = px.bar(long_u_top.sort_values("Count"),
                           x="Count", y="Assigned Team User", color="Metric", barmode="group",
                           title="User — Resolved vs Rejected→Closed vs Responded-not-Closed (Top N)",
                           color_discrete_map=cmap, text_auto=True)
        fig_u_grp.update_yaxes(categoryorder="total ascending")
        show_chart(style_fig(fig_u_grp, theme), key="tab4-u-group")

        resp_all = usr[usr["RespOnly"] > 1].sort_values("RespOnly")
        if len(resp_all):
            cmap = brand_map_for(resp_all["Assigned Team User"].tolist())
            fig_u_resp_only = px.bar(resp_all,
                                     x="RespOnly", y="Assigned Team User", orientation="h",
                                     title="Responded but NOT Closed — Counts (ALL users, count > 1)",
                                     color="Assigned Team User", color_discrete_map=cmap)
            show_chart(style_fig(fig_u_resp_only, theme), key="tab4-u-resp-only")
        else:
            st.info("No Responded-not-Closed users with count > 1.")

        c1, c2 = st.columns(2)
        with c1:
            top = usr.sort_values("Total", ascending=False).head(25)
            cmap = brand_map_for(top["Assigned Team User"].tolist())
            fig_u_total = px.bar(top, x="Assigned Team User", y="Total", title="Top Assignees by Total",
                                 color="Assigned Team User", color_discrete_map=cmap)
            fig_u_total.update_xaxes(tickangle=30)
            show_chart(style_fig(fig_u_total, theme), key="tab4-u-total")
        with c2:
            top = usr.sort_values("Resolved", ascending=False).head(25)
            cmap = brand_map_for(top["Assigned Team User"].tolist())
            fig_u_res = px.bar(top, x="Assigned Team User", y="Resolved", title="Top Assignees by Resolved",
                               color="Assigned Team User", color_discrete_map=cmap)
            fig_u_res.update_xaxes(tickangle=30)
            show_chart(style_fig(fig_u_res, theme), key="tab4-u-resolved")

        strict_rows = df_filtered["_R2C_Strict_Flag"] == 1
        if strict_rows.any():
            med = (df_filtered.loc[strict_rows, ["Assigned Team User","R2C Hours (>=0)"]]
                   .dropna()
                   .groupby("Assigned Team User")["R2C Hours (>=0)"]
                   .median()
                   .reset_index()
                   .rename(columns={"R2C Hours (>=0)":"Median Hours to Close after Rejection"}))
            cmap = brand_map_for(med["Assigned Team User"].tolist())
            fig_u_med = px.bar(med.sort_values("Median Hours to Close after Rejection"),
                               x="Median Hours to Close after Rejection", y="Assigned Team User", orientation="h",
                               title="Median CLOSE-after-REJECTION (hours) — by Assignee (strict)",
                               color="Assigned Team User", color_discrete_map=cmap)
            show_chart(style_fig(fig_u_med, theme), key="tab4-u-med")
    else:
        st.info("Column 'Assigned Team User' not found.")

    if "Raised By" in df_filtered.columns and resp_only_count > 0:
        rb_counts = (df_filtered.loc[mask_responly, "Raised By"]
                     .fillna("—").astype(str)
                     .value_counts().rename_axis("Raised By").reset_index(name="Responded not Closed"))
        rb_counts = rb_counts[rb_counts["Responded not Closed"] > 1]
        if len(rb_counts):
            cmap = brand_map_for(rb_counts["Raised By"].tolist())
            fig_rb_all = px.bar(
                rb_counts.sort_values("Responded not Closed"),
                x="Responded not Closed", y="Raised By", orientation="h",
                title="Raised-by: Responded-not-Closed (count > 1)",
                color="Raised By", color_discrete_map=cmap
            )
            show_chart(style_fig(fig_rb_all, theme), key="tab4-raisedby-responly")
        else:
            st.info("No Responded-not-Closed raised-by reminders with count > 1 in current filters.")

# ---------- Timelines (restored) ----------
with tabs[6]:
    st.header("Timelines")
    if "_RaisedOnDT" in df_filtered.columns:
        work = df_filtered.copy()
        work["Date"] = work["_RaisedOnDT"].dt.date
        series = work.groupby("Date").agg(
            Raised=("Reference ID", "count") if "Reference ID" in work.columns else ("Date","count"),
            Resolved=("_EffectiveResolutionDT", lambda x: x.notna().sum()),
            R2C=("_R2C_Flag", "sum"),
            RespOnly=("_RespondedNotClosed_Flag", "sum"),
        ).reset_index()
        fig2 = go.Figure()
        cmap_line = brand_map_for(["Raised","Resolved","R2C","RespOnly"])
        fig2.add_trace(go.Scatter(x=series["Date"], y=series["Raised"], mode="lines", name="Raised", line=dict(color=cmap_line["Raised"])))
        fig2.add_trace(go.Scatter(x=series["Date"], y=series["Resolved"], mode="lines", name="Resolved", line=dict(color=cmap_line["Resolved"])))
        fig2.add_trace(go.Scatter(x=series["Date"], y=series["R2C"], mode="lines", name="R2C", line=dict(color=cmap_line["R2C"])))
        fig2.add_trace(go.Scatter(x=series["Date"], y=series["RespOnly"], mode="lines", name="RespOnly", line=dict(color=cmap_line["RespOnly"])))
        fig2.update_layout(title="Daily Flow — Raised vs Resolved vs R→C vs Responded-not-Closed")
        show_chart(style_fig(fig2, theme), key="tab6-lines")
    else:
        st.info("No Raised On timestamps available.")

# ---------- NC-View ----------
with tabs[7]:
    st.header("NC-View")

    proj_opts = sorted(df_filtered.get("Project Name", pd.Series(dtype=str)).dropna().unique().tolist())
    sel_proj = st.selectbox("Filter by Project (optional)", ["(All)"] + proj_opts, index=0, key="nc-proj")
    if sel_proj != "(All)":
        df_scope = df_filtered[df_filtered.get("Project Name","").astype(str) == sel_proj]
    else:
        df_scope = df_filtered

    if "Reference ID" in df_scope.columns and len(df_scope):
        ref_opts = df_scope["Reference ID"].astype(str).tolist()
        sel_ref = st.selectbox("Select Reference ID", ref_opts, key="nc-ref")
        row = df_scope[df_scope["Reference ID"].astype(str) == sel_ref].head(1)
    else:
        st.info("No Reference IDs available in current filters.")
        row = pd.DataFrame()

    if not row.empty:
        r = row.iloc[0]
        def _fmt_ts(x):
            return "" if pd.isna(x) else pd.to_datetime(x).strftime("%Y-%m-%d %H:%M")

        cols = st.columns(4)
        cols[0].metric("Project", str(r.get("Project Name","—")))
        cols[1].metric("Status", str(r.get("Current Status","—")))
        sla = r.get("SLA Met")
        cols[2].metric("SLA", "Met" if sla is True else ("Missed" if sla is False else "—"))
        cols[3].metric("Assignee", str(r.get("Assigned Team User","—")))
        st.caption(
            f"Raised: {_fmt_ts(r.get('_RaisedOnDT'))} | "
            f"Responded: {_fmt_ts(r.get('_RespondedOnDT'))} | "
            f"Rejected: {_fmt_ts(r.get('_RejectedOnDT'))} | "
            f"Closed: {_fmt_ts(r.get('_ClosedOnDT'))} | "
            f"Effective: {_fmt_ts(r.get('_EffectiveResolutionDT'))}"
        )

        # Event strip
        events = []
        for name, col in [
            ("Raised", "_RaisedOnDT"),
            ("Responded", "_RespondedOnDT"),
            ("Rejected", "_RejectedOnDT"),
            ("Closed", "_ClosedOnDT"),
            ("Effective", "_EffectiveResolutionDT"),
            ("Deadline", "_DeadlineDT"),
        ]:
            ts = r.get(col)
            if pd.notna(ts):
                color = {"Raised": GREY, "Responded": BLUE, "Rejected": GREY,
                         "Closed": BLACK, "Effective": BLUE, "Deadline": GREY}.get(name, BLUE)
                events.append(dict(name=name, ts=pd.to_datetime(ts), color=color))
        if events:
            evdf = pd.DataFrame(events).sort_values("ts")
            fig_ev = go.Figure()
            fig_ev.add_trace(go.Scatter(
                x=evdf["ts"], y=[0]*len(evdf),
                mode="markers+text", text=evdf["name"],
                textposition="top center", marker=dict(size=10, color=evdf["color"])
            ))
            fig_ev.update_yaxes(visible=False)
            fig_ev.update_layout(title="Event Strip", xaxis_title="", height=220)
            show_chart(style_fig(fig_ev, theme), key="nc-events")

        # Gantt segments
        segs = []
        rs = r.get("_RaisedOnDT"); rp = r.get("_RespondedOnDT"); ef = r.get("_EffectiveResolutionDT")
        if pd.notna(rs) and pd.notna(rp) and rp >= rs:
            segs.append(dict(segment="Raised→Responded", start=pd.to_datetime(rs), finish=pd.to_datetime(rp)))
        if pd.notna(rp) and pd.notna(ef) and ef >= rp:
            segs.append(dict(segment="Responded→Effective", start=pd.to_datetime(rp), finish=pd.to_datetime(ef)))
        elif pd.notna(rs) and pd.notna(ef) and ef >= rs and (pd.isna(rp) or rp < rs):
            segs.append(dict(segment="Raised→Effective", start=pd.to_datetime(rs), finish=pd.to_datetime(ef)))
        if segs:
            tdf = pd.DataFrame(segs)
            cmap = brand_map_for(tdf["segment"].tolist())
            fig_tl = px.timeline(tdf, x_start="start", x_end="finish", y="segment",
                                 color="segment", color_discrete_map=cmap)
            fig_tl.update_yaxes(autorange="reversed")
            fig_tl.update_layout(title="Gantt (segments)", height=250, showlegend=False)
            show_chart(style_fig(fig_tl, theme), key="nc-gantt")

        # Status step chart
        steps = []
        if pd.notna(rs): steps.append(("Raised", pd.to_datetime(rs), 0))
        if pd.notna(rp) and pd.notna(rs) and rp >= rs: steps.append(("Responded", pd.to_datetime(rp), 1))
        rj = r.get("_RejectedOnDT")
        if pd.notna(rj) and (not steps or pd.to_datetime(rj) >= steps[-1][1]): steps.append(("Rejected", pd.to_datetime(rj), 2))
        cl = r.get("_ClosedOnDT")
        if pd.notna(cl): steps.append(("Closed", pd.to_datetime(cl), 3))
        ef = r.get("_EffectiveResolutionDT")
        if pd.notna(ef) and (not cl or pd.to_datetime(ef) != pd.to_datetime(cl)):
            steps.append(("Effective", pd.to_datetime(ef), 4))
        if steps:
            xs = [t[1] for t in steps]
            ys = [t[2] for t in steps]
            fig_step = go.Figure(go.Scatter(x=xs, y=ys, mode="lines+markers", line_shape="hv", line=dict(color=BLUE)))
            fig_step.update_yaxes(
                tickmode="array",
                tickvals=[0,1,2,3,4],
                ticktext=["Raised","Responded","Rejected","Closed","Effective"]
            )
            fig_step.update_layout(title="Status Step Chart", height=260)
            show_chart(style_fig(fig_step, theme), key="nc-step")

        # SLA bullet
        rs = r.get("_RaisedOnDT"); dl = r.get("_DeadlineDT"); eff = r.get("_EffectiveResolutionDT")
        if pd.notna(rs) and (pd.notna(dl) or pd.notna(eff)):
            base = pd.to_datetime(rs)
            dl_hours = (pd.to_datetime(dl) - base).total_seconds()/3600 if pd.notna(dl) else None
            ef_hours = (pd.to_datetime(eff) - base).total_seconds()/3600 if pd.notna(eff) else None
            bars = []
            if dl_hours is not None: bars.append(("Deadline", max(0, dl_hours)))
            if ef_hours is not None: bars.append(("Actual", max(0, ef_hours)))
            if bars:
                bdf = pd.DataFrame(bars, columns=["Metric","Hours"])
                cmap = brand_map_for(bdf["Metric"].tolist())
                fig_b = px.bar(bdf, x="Hours", y="Metric", orientation="h",
                               title="SLA — Deadline vs Actual (hours)",
                               color="Metric", color_discrete_map=cmap, text_auto=True)
                show_chart(style_fig(fig_b, theme), key="nc-sla-bullet")

# ---------- Sketch-View (Treemap) ----------
with tabs[8]:
    st.header("Sketch-View")
    st.caption("Treemap from 'Location / Reference' (pre-aggregated). Brand-derived palette only.")

    path_col = "Location / Reference" if "Location / Reference" in df_filtered.columns else None
    if not path_col:
        st.info("Column 'Location / Reference' not found.")
    else:
        treemap_enable = st.checkbox("Show Treemap", value=True, key="sk-enable")
        max_depth = st.slider("Max depth", 1, 6, 4, step=1, key="sk-depth")
        max_nodes = st.slider("Max nodes", 100, 5000, 800, step=100, help="Limit total rectangles for performance.", key="sk-nodes")

        @st.cache_data(show_spinner=False)
        def build_levels(df_src: pd.DataFrame, col: str, depth: int) -> pd.DataFrame:
            parts = df_src[col].fillna("").astype(str).str.split("/")
            out = pd.DataFrame(index=df_src.index)
            for i in range(depth):
                out[f"Level_{i}"] = parts.str[i].fillna("").str.strip().where(parts.str.len() > i, "")
            out["Count"] = 1
            return out

        def unique_columns(df_in: pd.DataFrame) -> pd.DataFrame:
            cols = []
            seen = {}
            for c in df_in.columns:
                if c not in seen:
                    seen[c] = 1; cols.append(c)
                else:
                    seen[c] += 1; cols.append(f"{c}__{seen[c]}")
            dfc = df_in.copy(); dfc.columns = cols
            return dfc

        if treemap_enable:
            lv = build_levels(df_filtered, path_col, max_depth)
            grp_cols = [c for c in lv.columns if c.startswith("Level_")]
            agg = lv.groupby(grp_cols, dropna=False, as_index=False)["Count"].sum()
            if len(agg) > max_nodes:
                agg = agg.sort_values("Count", ascending=False).head(max_nodes)
            agg = unique_columns(agg)
            path_cols = [c for c in agg.columns if c.startswith("Level_")]
            fig_t = px.treemap(
                agg, path=path_cols, values="Count",
                color=path_cols[-1],  # derive diverse colors
                color_discrete_map=brand_map_for(agg[path_cols[-1]].astype(str).tolist())
            )
            fig_t.update_layout(title="Location / Reference — Treemap (aggregated)")
            show_chart(style_fig(fig_t, theme), key="sk-treemap")

        st.subheader("Issues at Selected Path")
        selected = st.text_input("Filter by path contains", "", key="sketch-filter")
        view = df_filtered[df_filtered[path_col].str.contains(selected, case=False, na=False)] if selected else df_filtered

        show_cols = [c for c in [
            "Reference ID","Project Name", path_col, "Location Variable (Fixed)",
            "Type L0","Type L1","Type L2","Tag 1","Tag 2",
            "Assigned Team","Assigned Team User","Current Status",
            "Responding Time (Hrs)","Computed Closure Time (Hrs)","Close After Response (Hrs)",
        ] if c in view.columns]
        if len(view):
            st.dataframe(view[show_cols].head(1500), use_container_width=True)
        else:
            st.info("No issues match the selected filter.")

# ---------- NC Table ----------
with tabs[9]:
    st.header("NC Table")
    st.caption("Styled table with row shading by Current Status (brand colours).")
    shade = st.toggle("Enable row shading", value=False, key="tbl-shade")

    display_cols = [c for c in [
        "Reference ID","Project Name","Location / Reference","Location Variable (Fixed)",
        "Location L0","Location L1","Location L2","Location L3",
        "Description","Recommendation",
        "Raised By","Raised On Date","Raised On Time",
        "Deadline Date","Deadline Time",
        "Assigned Team","Assigned Team User",
        "Current Status",
        "Responded By","Responded On Date","Responded On Time",
        "Rejected By","Rejected On Date","Rejected On Time",
        "Closed By","Closed On Date","Closed On Time",
        "Responding Time (Hrs)","Computed Closure Time (Hrs)","Close After Response (Hrs)",
        "_RespondedNotClosed_Flag", "_R2C_Flag", "_R2C_Strict_Flag",
        "Type L0","Type L1","Type L2","Tag 1","Tag 2",
        "Root Cause Analysis","Correction","Corrective Action",
        "Labour Cost","Material Cost","Machinery Cost","Other Cost","Total Cost",
    ] if c in df_filtered.columns]

    if not display_cols:
        st.info("No known NC columns found in the dataset.")
    else:
        view = df_filtered[display_cols]
        if shade:
            try:
                st.write(style_status_rows(view.head(1500), theme).to_html(), unsafe_allow_html=True)
            except Exception:
                st.dataframe(view.head(1500), use_container_width=True)
        else:
            st.dataframe(view.head(1500), use_container_width=True)
        csv_data = view.to_csv(index=False).encode("utf-8")
        st.download_button("⬇️ Download filtered table (CSV)", data=csv_data, file_name="digiqc_filtered.csv", mime="text/csv", key="dl-full-table")

st.caption("© Digital Issue Dashboard — Streamlit (SJCPL Brand)")
