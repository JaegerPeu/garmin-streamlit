import streamlit as st
import pandas as pd
import gspread
from gspread_dataframe import get_as_dataframe
from google.oauth2.service_account import Credentials
import plotly.express as px
import plotly.graph_objects as go
from plotly.subplots import make_subplots
import gsheet
import datetime as dt

# ================= CONFIGURAÇÃO ==================
GSHEET_ID = "1rwcDJA1yZ2hbsJx-HOW0dCduvWqV0z7f9Iio0HI1WwY"  # coloque o ID completo

service_account_info = st.secrets["gcp_service_account"]
scopes = ["https://www.googleapis.com/auth/spreadsheets"]
creds = Credentials.from_service_account_info(service_account_info, scopes=scopes)
client = gspread.authorize(creds)
# =================================================

def load_sheet(sheet_name: str) -> pd.DataFrame:
    """Carrega uma aba da planilha do Google Sheets em DataFrame"""
    ws = client.open_by_key(GSHEET_ID).worksheet(sheet_name)
    df = get_as_dataframe(ws, evaluate_formulas=True, header=0)
    df = df.dropna(how="all")
    return df

def calc_period_avg(df: pd.DataFrame, col: str, freq: str, date_col="Data"):
    """Calcula média por período (WTD, MTD, QTD, YTD, TOTAL)."""
    if col not in df.columns:
        return None
    df = df.copy()
    df[date_col] = pd.to_datetime(df[date_col], errors="coerce")
    df[col] = pd.to_numeric(df[col], errors="coerce")
    if df[col].dropna().empty:
        return None

    today = dt.date.today()
    if freq == "WTD":
        start = today - dt.timedelta(days=today.weekday())
    elif freq == "MTD":
        start = today.replace(day=1)
    elif freq == "QTD":
        q = (today.month - 1) // 3 + 1
        start = dt.date(today.year, 3 * (q - 1) + 1, 1)
    elif freq == "YTD":
        start = dt.date(today.year, 1, 1)
    else:
        start = df[date_col].min().date()

    mask = df[date_col].dt.date >= start
    vals = df.loc[mask, col].dropna().astype(float)
    return vals.mean() if not vals.empty else None

# ---------- Função para formatar valores ----------
def format_value(val, kind: str):
    if val is None or pd.isna(val):
        return "-"
    try:
        if "Pace" in kind:
            total_seconds = int(round(val * 60))
            m, s = divmod(total_seconds, 60)
            return f"{m}:{s:02d}"
        if "Sono" in kind and "(h)" in kind:
            h = int(val)
            m = int(round((val - h) * 60))
            return f"{h:02d}:{m:02d}"
        if "Passos" in kind:
            return f"{int(val):,}".replace(",", ".")
        return f"{val:.2f}"
    except Exception:
        return str(val)

# ---------- APP ----------
st.set_page_config(page_title="📊 Dashboard Garmin", layout="wide")

st.title("🏃‍♂️ Dashboard de Atividades Garmin")

# Botão para atualizar planilha
if st.button("🔄 Atualizar dados do Garmin"):
    with st.spinner("Conectando ao Garmin e atualizando planilha..."):
        try:
            gsheet.main()
            # Recarrega planilhas e guarda em memória
            st.session_state["daily_df"] = load_sheet("DailyHUD")
            st.session_state["acts_df"] = load_sheet("Activities")
            st.success("✅ Dados atualizados com sucesso!")
        except Exception as e:
            st.error("❌ Erro ao atualizar os dados")
            st.exception(e)

# Carrega dados da sessão ou da primeira vez
if "daily_df" not in st.session_state:
    st.session_state["daily_df"] = load_sheet("DailyHUD")
if "acts_df" not in st.session_state:
    st.session_state["acts_df"] = load_sheet("Activities")

daily_df = st.session_state["daily_df"]
acts_df  = st.session_state["acts_df"]

if daily_df.empty:
    st.warning("Nenhum dado encontrado na aba `DailyHUD`. Clique em **Atualizar dados** acima.")
    st.stop()

# Converter colunas numéricas
daily_df["Data"] = pd.to_datetime(daily_df["Data"], errors="coerce")

numeric_cols = [
    "Sono (h)", "Sono Deep (h)", "Sono REM (h)", "Sono Light (h)", 
    "Sono (score)", "Body Battery (start)", "Body Battery (end)", 
    "Body Battery (mín)", "Body Battery (máx)", "Body Battery (média)", 
    "Stress (média)", "Passos", "Calorias (total dia)", "Corrida (km)", "Pace (min/km)"
]
for c in numeric_cols:
    if c in daily_df.columns:
        daily_df[c] = pd.to_numeric(daily_df[c], errors="coerce")

# ---------- GRÁFICO MULTIMÉTRICAS ----------
st.header("📊 Evolução das Métricas")

metrics = numeric_cols
selected_metrics = st.multiselect("Escolha as métricas para visualizar:", metrics, default=["Sono (h)", "Sono (score)"])

if selected_metrics:
    fig = make_subplots(specs=[[{"secondary_y": True}]])
    colors = px.colors.qualitative.Set2

    # Primeiro eixo Y
    y1 = selected_metrics[0]
    fig.add_trace(
        go.Scatter(x=daily_df["Data"], y=daily_df[y1], mode="lines+markers", name=y1, line=dict(color=colors[0])),
        secondary_y=False,
    )

    # Segundo eixo Y
    if len(selected_metrics) > 1:
        y2 = selected_metrics[1]
        fig.add_trace(
            go.Scatter(x=daily_df["Data"], y=daily_df[y2], mode="lines+markers", name=y2, line=dict(color=colors[1])),
            secondary_y=True,
        )

    # Restante também no secundário
    for i, m in enumerate(selected_metrics[2:], start=2):
        fig.add_trace(
            go.Scatter(x=daily_df["Data"], y=daily_df[m], mode="lines+markers", name=m, line=dict(color=colors[i % len(colors)])),
            secondary_y=True,
        )

    fig.update_layout(title="Comparativo de Métricas Selecionadas", legend=dict(orientation="h", y=-0.2))
    fig.update_yaxes(title_text=y1, secondary_y=False)
    if len(selected_metrics) > 1:
        fig.update_yaxes(title_text=y2, secondary_y=True)

    st.plotly_chart(fig, use_container_width=True)

# ---------- INSIGHTS ----------
st.header("🔍 Insights (WTD / MTD / QTD / YTD / Total)")

insights = {
    "Sono médio (h)": "Sono (h)",
    "Qualidade do sono (score)": "Sono (score)",
    "Distância corrida (km)": "Corrida (km)",
    "Pace médio (min/km)": "Pace (min/km)",
    "Passos": "Passos",
    "Calorias (total dia)": "Calorias (total dia)",
    "Body Battery (média)": "Body Battery (média)",
}

rows = []
for label, col in insights.items():
    row = {"Métrica": label}
    for period in ["WTD", "MTD", "QTD", "YTD", "TOTAL"]:
        val = calc_period_avg(daily_df, col, period)
        row[period] = format_value(val, label)
    rows.append(row)

st.dataframe(pd.DataFrame(rows).set_index("Métrica"))

# ---------- TABELA FINAL ----------
st.header("📑 DailyHUD (dados brutos formatados)")
df_display = daily_df.copy()
for col in ["Sono (h)", "Pace (min/km)"]:
    if col in df_display.columns:
        df_display[col] = df_display[col].apply(lambda v: format_value(v, col))
st.dataframe(df_display)
