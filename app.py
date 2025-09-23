# app.py
# =====================================================
# Dashboard Streamlit Garmin + HUD RPG + Sync Notion
# =====================================================

import time
import datetime as dt
from typing import Optional, List, Tuple
import pandas as pd
import streamlit as st
import requests
import json
import gspread
from gspread_dataframe import get_as_dataframe
from google.oauth2.service_account import Credentials
import plotly.express as px
import plotly.graph_objects as go
from plotly.subplots import make_subplots
import gsheet  # script local para atualizar Google Sheets

# ================= CONFIGURAÇÃO ==================
GSHEET_ID = "1rwcDJA1yZ2hbsJx-HOW0dCduvWqV0z7f9Iio0HI1WwY"
service_account_info = st.secrets["gcp_service_account"]
scopes = ["https://www.googleapis.com/auth/spreadsheets"]
creds = Credentials.from_service_account_info(service_account_info, scopes=scopes)
client = gspread.authorize(creds)

# Notion
NOTION_TOKEN = st.secrets["notion"]["token"]
NOTION_BLOCK_ID = st.secrets["notion"]["block_id"]
NOTION_DAILYHUD_DB_ID = st.secrets["notion"].get("dailyhud_db_id", "")
NOTION_VERSION = "2022-06-28"

# ================= Helpers Notion ==================
def _notion_headers():
    return {
        "Authorization": f"Bearer {NOTION_TOKEN}",
        "Content-Type": "application/json",
        "Notion-Version": NOTION_VERSION,
    }

def normalize_id(i: str) -> str:
    return (i or "").replace("-", "").strip()

def push_hud_to_notion_codeblock(hud_text: str, block_id: str) -> Tuple[bool, str]:
    try:
        payload = {
            "code": {"rich_text": [{"type": "text", "text": {"content": hud_text}}], "language": "plain text"}
        }
        url = f"https://api.notion.com/v1/blocks/{normalize_id(block_id)}"
        r = requests.patch(url, headers=_notion_headers(), data=json.dumps(payload), timeout=15)
        return (True, "Atualizado!") if r.status_code == 200 else (False, f"HTTP {r.status_code} - {r.text}")
    except Exception as e:
        return False, str(e)

def notion_get_database(db_id: str) -> dict:
    db = normalize_id(db_id)
    r = requests.get(f"https://api.notion.com/v1/databases/{db}", headers=_notion_headers(), timeout=30)
    r.raise_for_status()
    return r.json()

def notion_update_database_add_props(db_id: str, props_to_add: dict) -> None:
    if not props_to_add:
        return
    url = f"https://api.notion.com/v1/databases/{normalize_id(db_id)}"
    r = requests.patch(url, headers=_notion_headers(), data=json.dumps({"properties": props_to_add}), timeout=30)
    r.raise_for_status()

def notion_create_page_in_db(db_id: str, properties: dict) -> str:
    payload = {"parent": {"database_id": normalize_id(db_id)}, "properties": properties}
    r = requests.post("https://api.notion.com/v1/pages", headers=_notion_headers(), data=json.dumps(payload), timeout=30)
    r.raise_for_status()
    return r.json()["id"]

def notion_query_all_keys(db_id: str, key_prop: str = "Key") -> dict:
    existing, payload, next_cursor = {}, {"page_size": 100}, None
    while True:
        if next_cursor:
            payload["start_cursor"] = next_cursor
        r = requests.post(f"https://api.notion.com/v1/databases/{normalize_id(db_id)}/query",
                          headers=_notion_headers(), data=json.dumps(payload), timeout=30)
        r.raise_for_status()
        data = r.json()
        for page in data.get("results", []):
            props = page.get("properties", {})
            if key_prop in props and props[key_prop].get("type") == "rich_text":
                rich = props[key_prop].get("rich_text", [])
                if rich:
                    key = "".join([t.get("plain_text", "") for t in rich]).strip()
                    if key:
                        existing[key] = page["id"]
        if not data.get("has_more"):
            break
        next_cursor = data.get("next_cursor")
    return existing

# ================= Conversores ==================
def _num_or_none(x):
    try:
        if x is None or (isinstance(x, float) and pd.isna(x)): return None
        v = float(x); return None if pd.isna(v) else v
    except: return None

def _to_notion_number(x):
    v = _num_or_none(x)
    return {"number": v} if v is not None else None

def _to_notion_rich_text(text: str):
    if not text or str(text).strip() == "": return {"rich_text": []}
    return {"rich_text": [{"type": "text", "text": {"content": str(text)}}]}

def _to_notion_date(date_ts: pd.Timestamp | dt.date):
    if pd.isna(date_ts): return None
    d = date_ts.date() if isinstance(date_ts, pd.Timestamp) else date_ts
    return {"date": {"start": d.isoformat()}}

def build_properties_from_row(row: pd.Series, numeric_cols: List[str], text_cols: List[str],
                              date_prop_name: str = "Data", key_value: Optional[str] = None) -> dict:
    props = {}
    if "Data" in row and not pd.isna(row["Data"]):
        p = _to_notion_date(row["Data"])
        if p: props[date_prop_name] = p
    for c in numeric_cols:
        if c in row:
            p = _to_notion_number(row[c])
            if p: props[c] = p
    for c in text_cols:
        if c in row: props[c] = _to_notion_rich_text(row[c])
    if key_value: props["Key"] = _to_notion_rich_text(key_value)
    return props

def mmss_to_minutes(x) -> Optional[float]:
    if pd.isna(x) or x == "": return None
    try:
        s = str(x).replace(",", ".").strip()
        parts = s.split(":")
        if len(parts) == 2: return float(parts[0]) + float(parts[1])/60.0
        if len(parts) == 3: return float(parts[0])*60 + float(parts[1]) + float(parts[2])/60.0
        return float(s)
    except: return None

def build_key_for_row(row: pd.Series) -> str:
    day_str = pd.to_datetime(row["Data"]).date().isoformat()
    return f"DailyHUD::{day_str}"

def ensure_key_prop(db_id: str, key_prop: str = "Key") -> None:
    meta = notion_get_database(db_id)
    if key_prop not in meta.get("properties", {}):
        notion_update_database_add_props(db_id, {key_prop: {"rich_text": {}}})

def get_or_create_date_prop_name(db_id: str) -> str:
    meta = notion_get_database(db_id)
    props = meta.get("properties", {})
    if "Data" in props and props["Data"].get("type") == "date": return "Data"
    for name, p in props.items():
        if p.get("type") == "date": return name
    notion_update_database_add_props(db_id, {"Data": {"date": {}}})
    return "Data"

def ensure_db_schema_for_dailyhud(db_id: str, numeric_cols: List[str], text_cols: List[str]) -> None:
    meta = notion_get_database(db_id)
    existing = meta.get("properties", {})
    to_add = {}
    for c in numeric_cols:
        if c not in existing or existing[c].get("type") != "number": to_add[c] = {"number": {}}
    for c in text_cols:
        if c not in existing or existing[c].get("type") != "rich_text": to_add[c] = {"rich_text": {}}
    if to_add: notion_update_database_add_props(db_id, to_add)

def sync_entire_dailyhud_to_notion(daily_df: pd.DataFrame, db_id: str, only_new: bool = True) -> tuple[int,int]:
    if not db_id: raise ValueError("Defina `notion.dailyhud_db_id` em secrets.toml.")
    df = daily_df.copy()
    df["Data"] = pd.to_datetime(df["Data"], errors="coerce").dt.normalize()
    df = df.dropna(subset=["Data"]).sort_values("Data").groupby(df["Data"]).tail(1)

    key_col = "Key"
    ensure_key_prop(db_id, key_col)
    date_col = get_or_create_date_prop_name(db_id)

    numeric_cols = df.select_dtypes(include="number").columns.tolist()
    text_cols = [c for c in df.columns if c not in numeric_cols + ["Data"]]

    ensure_db_schema_for_dailyhud(db_id, numeric_cols, text_cols)

    existing_keys = notion_query_all_keys(db_id, key_prop=key_col) if only_new else {}
    total, added = 0, 0
    for _, row in df.iterrows():
        key = build_key_for_row(row)
        total += 1
        if only_new and key in existing_keys: continue
        props = build_properties_from_row(row, numeric_cols, text_cols, date_prop_name=date_col, key_value=key)
        notion_create_page_in_db(db_id, props)
        added += 1
    return total, added

# ================= Streamlit App ==================
st.set_page_config(page_title="HUD Garmin RPG", layout="wide")

st.title("📊 Garmin Daily HUD – RPG Style")
st.caption("Atualizado automaticamente a partir do Google Sheets e sincronizado com Notion")

# ---------------- Load Google Sheets ----------------
@st.cache_data(ttl=300)
def load_gsheet(sheet_name: str) -> pd.DataFrame:
    sh = client.open_by_key(GSHEET_ID)
    ws = sh.worksheet(sheet_name)
    df = get_as_dataframe(ws, evaluate_formulas=True)
    df = df.dropna(how="all")
    return df

dailyhud_df = load_gsheet("DailyHUD")
activities_df = load_gsheet("Activities")

# ---------------- Process Activities ----------------
if "Duration" in activities_df.columns:
    activities_df["Duration_min"] = activities_df["Duration"].apply(mmss_to_minutes)

# Aggregate per day
agg_df = activities_df.groupby("Date").agg({
    "Duration_min": "sum",
    "Distance": "sum",
    "Calories": "sum"
}).reset_index()

# Merge with DailyHUD
if "Data" in dailyhud_df.columns:
    dailyhud_df["Data"] = pd.to_datetime(dailyhud_df["Data"]).dt.date
merged_df = pd.merge(dailyhud_df, agg_df, left_on="Data", right_on="Date", how="outer").sort_values("Data")

# ---------------- HUD RPG ----------------
def render_hud_rpg(df: pd.DataFrame, date: Optional[dt.date] = None) -> str:
    if date is None: date = df["Data"].max()
    row = df[df["Data"] == date]
    if row.empty: return "Nenhum dado disponível para essa data."
    row = row.iloc[0]
    hud = [
        "┌─────────── HUD RPG ──────────┐",
        f"│ Data: {row['Data']}              │",
    ]
    for col in df.columns:
        if col == "Data": continue
        hud.append(f"│ {col[:12].ljust(12)} : {str(row[col]).ljust(8)} │")
    hud.append("└─────────────────────────────┘")
    return "\n".join(hud)

st.subheader("HUD Diário")
selected_date = st.date_input("Selecione a data", value=merged_df["Data"].max())
hud_text = render_hud_rpg(merged_df, selected_date)
st.code(hud_text, language="text")

# ---------------- Sync with Notion -----------------
st.subheader("📤 Sincronizar com Notion")
if NOTION_DAILYHUD_DB_ID:
    st.caption("Atualiza incrementalmente as páginas da DailyHUD no Notion")
    if st.button("Sync DailyHUD → Notion"):
        total, added = sync_entire_dailyhud_to_notion(merged_df, NOTION_DAILYHUD_DB_ID)
        st.success(f"Sync concluído: Total {total}, Novos adicionados {added}")

# ---------------- Plots -----------------
st.subheader("📈 Evolução de Métricas")
metric_cols = [c for c in merged_df.columns if c != "Data"]
selected_metric = st.selectbox("Escolha a métrica", metric_cols)
fig = px.line(merged_df, x="Data", y=selected_metric, title=f"Evolução de {selected_metric}")
st.plotly_chart(fig, use_container_width=True)
