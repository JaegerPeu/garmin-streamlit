# app.py
# =====================================================
# Dashboard Streamlit para visualização dos dados Garmin
# + HUD estilo RPG (envio para Notion via Code Block)
# + Sync incremental da aba DailyHUD para Notion
# =====================================================

import streamlit as st
import pandas as pd
import gspread
from gspread_dataframe import get_as_dataframe
from google.oauth2.service_account import Credentials
import plotly.express as px
import plotly.graph_objects as go
from plotly.subplots import make_subplots
import datetime as dt
from typing import Optional, List, Tuple
import requests
import json
import time
import gsheet

# ================= CONFIGURAÇÃO ==================
GSHEET_ID = "1rwcDJA1yZ2hbsJx-HOW0dCduvWqV0z7f9Iio0HI1WwY"  # ID da planilha

service_account_info = st.secrets["gcp_service_account"]
scopes = ["https://www.googleapis.com/auth/spreadsheets"]
creds = Credentials.from_service_account_info(service_account_info, scopes=scopes)
client = gspread.authorize(creds)

# Notion
NOTION_TOKEN = st.secrets["notion"]["token"]
NOTION_BLOCK_ID = st.secrets["notion"]["block_id"]
NOTION_COUNTER_DB_ID = st.secrets["notion"]["counter_db_id"]
NOTION_DAILYHUD_DB_ID = st.secrets["notion"].get("dailyhud_db_id", "")
NOTION_VERSION = "2022-06-28"

# =================================================

# ================== HELPERS =====================

def _notion_headers():
    return {"Authorization": f"Bearer {NOTION_TOKEN}", "Content-Type": "application/json", "Notion-Version": NOTION_VERSION}

def normalize_id(i: str) -> str:
    return (i or "").replace("-", "").strip()

def push_hud_to_notion_codeblock(hud_text: str, block_id: str) -> Tuple[bool, str]:
    try:
        payload = {
            "code": {"rich_text": [{"type": "text", "text": {"content": hud_text}}], "language": "plain text"}
        }
        url = f"https://api.notion.com/v1/blocks/{normalize_id(block_id)}"
        r = requests.patch(url, headers=_notion_headers(), data=json.dumps(payload), timeout=15)
        if r.status_code == 200: return True, "Atualizado!"
        return False, f"HTTP {r.status_code} - {r.text}"
    except Exception as e:
        return False, str(e)

def load_sheet(sheet_name: str) -> pd.DataFrame:
    try:
        ws = client.open_by_key(GSHEET_ID).worksheet(sheet_name)
        df = get_as_dataframe(ws, evaluate_formulas=True, header=0)
        return df.dropna(how="all")
    except Exception as e:
        st.error(f"Erro ao carregar aba {sheet_name}: {e}")
        return pd.DataFrame()

def mmss_to_minutes(x) -> Optional[float]:
    if pd.isna(x) or x == "": return None
    try:
        if isinstance(x, (int, float)): return float(x)
        s = str(x).strip().replace(",", ".")
        parts = s.split(":")
        if len(parts) == 2: return float(parts[0]) + float(parts[1])/60.0
        if len(parts) == 3: return float(parts[0])*60 + float(parts[1]) + float(parts[2])/60.0
        return float(s)
    except: return None

def format_hours(value):
    if pd.isna(value) or value == "": return "-"
    try:
        horas = int(float(value))
        minutos = int(round((float(value)-horas)*60))
        return f"{horas:02d}:{minutos:02d}"
    except: return "-"

def format_pace(value):
    if pd.isna(value) or value == "" or float(value) == 0: return "-"
    try:
        minutos = int(float(value))
        segundos = int(round((float(value)-minutos)*60))
        return f"{minutos}:{segundos:02d}"
    except: return "-"

def pace_series_to_hover(series: pd.Series):
    return [format_pace(v) if pd.notna(v) and v not in ("", 0) else None for v in series]

def get_today_turtle_objective() -> str:
    try:
        turtle = load_sheet("Turtle")
        if turtle.empty: return "-"
        turtle["Data"] = pd.to_datetime(turtle["Data"], errors="coerce", dayfirst=True)
        today = dt.date.today()
        row = turtle[turtle["Data"].dt.date <= today].sort_values("Data")
        if row.empty: return "-"
        return str(row.iloc[-1]["Objetivo"]).strip()
    except: return "-"

# =================================================
# ================== APP =========================
st.set_page_config(page_title="📊 Dashboard Garmin / HUD RPG", layout="wide")
st.title("🏃‍♂️ Dashboard de Atividades Garmin + 🎮 HUD RPG")

# ---------- Atualização Garmin → Google Sheets ----------
if st.button("🔄 Atualizar dados do Garmin"):
    with st.spinner("Atualizando..."):
        try:
            gsheet.main()
            st.cache_data.clear()
            st.success("✅ Dados atualizados com sucesso!")
        except Exception as e:
            st.error("Erro ao atualizar os dados")
            st.exception(e)

# ---------- Carrega dados ----------
daily_df = load_sheet("DailyHUD")
acts_df = load_sheet("Activities")

if daily_df.empty:
    st.warning("Nenhum dado encontrado na aba `DailyHUD`.")
    st.stop()

daily_df["Data"] = pd.to_datetime(daily_df["Data"], errors="coerce")
numeric_cols = [
    "Sono (h)", "Sono Deep (h)", "Sono REM (h)", "Sono Light (h)",
    "Sono (score)", "Body Battery (start)", "Body Battery (end)",
    "Body Battery (mín)", "Body Battery (máx)", "Body Battery (média)",
    "Stress (média)", "Passos", "Calorias (total dia)",
    "Corrida (km)", "Pace (min/km)", "Breathwork (min)"
]
for c in numeric_cols:
    if c in daily_df.columns: daily_df[c] = pd.to_numeric(daily_df[c], errors="coerce")
if "Pace (min/km)" in daily_df.columns: daily_df["PaceNum"] = daily_df["Pace (min/km)"].apply(mmss_to_minutes)

# ---------- HUD RPG ----------
st.header("🎮 HUD — Status de Hoje")
today = dt.date.today()
last_day_row = daily_df.sort_values("Data").dropna(subset=["Data"]).iloc[-1]
turtle_obj = get_today_turtle_objective()

energia = last_day_row.get("Body Battery (máx)", last_day_row.get("Body Battery (end)", None))
energia_txt = f"{int(energia)}%" if energia else "-"

def energy_bar(x):
    if not x or pd.isna(x): return "[..........]"
    x = int(x)
    filled = max(0, min(10, round(x/10)))
    return "[" + "#"*filled + "."*(10-filled) + "]"

sono_h = last_day_row.get("Sono (h)", None)
sono_txt = f"{float(sono_h):.1f}h" if sono_h else "-"
score_txt = f"{int(last_day_row.get('Sono (score)',0))}" if last_day_row.get('Sono (score)',None) else "-"

breath_today_txt = f"{int(last_day_row.get('Breathwork (min)',0))}"

# --- Monta HUD monoespaçado ---
WIDTH = 66
def line(text=""): return f"║ {text.ljust(WIDTH-2)} ║"
def title_box(t): return f"╔{'═'*WIDTH}╗\n{line(t)}\n╠{'═'*WIDTH}╣"
def end_box(): return f"╚{'═'*WIDTH}╝"

hud_lines = []
hud_lines.append(title_box(f"HUD — {today.strftime('%A, %d/%m/%Y')}"))
hud_lines.append(line(f"Player: Pedro Duarte"))
hud_lines.append(line(f"Energia: {energy_bar(energia)} {energia_txt}"))
hud_lines.append(line(f"Sono: {sono_txt} | Qualidade: {score_txt}"))
hud_lines.append(end_box())
hud_lines.append(title_box("Mente"))
hud_lines.append(line(f"Meditação hoje: {breath_today_txt:>3} min"))
hud_lines.append(end_box())
hud_lines.append(title_box("Trabalho / Trade"))
hud_lines.append(line(f"Objetivo de hoje: {turtle_obj[:WIDTH-22]}"))
hud_lines.append(end_box())
st.code("\n".join(hud_lines), language="")

# --- Envio para Notion ---
st.subheader("Exportar HUD para o Notion")
blk_id_input = st.text_input("Code Block ID do Notion:", value=NOTION_BLOCK_ID or "")
if st.button("🚀 Enviar HUD ao Notion"):
    target_block = blk_id_input.strip() or NOTION_BLOCK_ID
    if not target_block: st.error("Informe um Code Block ID do Notion.")
    else:
        ok,msg = push_hud_to_notion_codeblock("\n".join(hud_lines), target_block)
        st.success("HUD enviado ao Notion! ✅") if ok else st.error(f"Falhou ao enviar: {msg}")

# =================================================
# ========= Gráfico métricas ==========
st.header("📊 Evolução das Métricas (Daily)")

selected_metrics = st.multiselect("Escolha as métricas:", numeric_cols, default=["Sono (h)", "Sono (score)"])
if selected_metrics:
    fig = make_subplots(specs=[[{"secondary_y": True}]])
    colors = px.colors.qualitative.Set2
    for idx, m in enumerate(selected_metrics):
        yseries = daily_df["PaceNum"] if m=="Pace (min/km)" else daily_df[m]
        trace_kwargs = {}
        if m=="Pace (min/km)":
            trace_kwargs["customdata"] = pace_series_to_hover(yseries)
            trace_kwargs["hovertemplate"] = "%{x|%Y-%m-%d}<br>" + m + ": %{customdata}<extra></extra>"
        fig.add_trace(go.Scatter(x=daily_df["Data"], y=yseries, mode="lines+markers",
                                 name=m, line=dict(color=colors[idx%len(colors)]), **trace_kwargs),
                      secondary_y=(idx>0))
        fig.update_yaxes(title_text=m, secondary_y=(idx>0))
    fig.update_layout(title="Comparativo de Métricas Selecionadas (DailyHUD)",
                      legend=dict(orientation="h", y=-0.2), margin=dict(l=50,r=50,t=50,b=50))
    st.plotly_chart(fig, use_container_width=True)
