import streamlit as st
import pandas as pd
import gspread
from gspread_dataframe import get_as_dataframe
from google.oauth2.service_account import Credentials
import plotly.express as px
import plotly.graph_objects as go
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
    try:
        ws = client.open_by_key(GSHEET_ID).worksheet(sheet_name)
        df = get_as_dataframe(ws, evaluate_formulas=True, header=0)
        df = df.dropna(how="all")
        return df
    except Exception as e:
        st.error(f"❌ Erro ao carregar aba {sheet_name}: {e}")
        return pd.DataFrame()

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
    return df.loc[mask, col].dropna().mean()

# =================================================
# APP STREAMLIT
# =================================================
st.set_page_config(page_title="📊 Dashboard Garmin", layout="wide")

st.title("🏃‍♂️ Dashboard de Atividades Garmin")
st.write("Sincronize seus dados do Garmin com o Google Sheets e veja análises em tempo real.")

# Botão de atualização
if st.button("🔄 Atualizar dados do Garmin"):
    with st.spinner("Conectando ao Garmin e atualizando planilha..."):
        try:
            gsheet.main()
            st.success("✅ Dados atualizados com sucesso!")
        except Exception as e:
            st.error("❌ Erro ao atualizar os dados")
            st.exception(e)

# Carrega dados
daily_df = load_sheet("DailyHUD")
acts_df  = load_sheet("Activities")

if daily_df.empty:
    st.warning("Nenhum dado encontrado na aba `DailyHUD`. Clique em **Atualizar dados** acima.")
    st.stop()

# Converter colunas
daily_df["Data"] = pd.to_datetime(daily_df["Data"], errors="coerce")

# ---------- VISUALIZAÇÕES ----------
st.header("📈 Evolução das Métricas")

metrics = [
    "Sono (h)", "Sono Deep (h)", "Sono REM (h)", "Sono Light (h)", "Sono (score)",
    "Body Battery (start)", "Body Battery (end)", "Body Battery (mín)",
    "Body Battery (máx)", "Body Battery (média)", "Stress (média)",
    "Passos", "Calorias (total dia)", "Corrida (km)", "Pace (min/km)"
]

selected_metrics = st.multiselect("📊 Escolha as métricas para visualizar:", metrics, default=["Sono (h)", "Sono (score)"])

if selected_metrics:
    fig = px.line(daily_df, x="Data", y=selected_metrics, markers=True)
    st.plotly_chart(fig, use_container_width=True)

# ---------- CORRIDAS ----------
st.header("🏃‍♀️ Corridas")

if not acts_df.empty:
    acts_df["Data"] = pd.to_datetime(acts_df["Data"], errors="coerce")

    run_metrics = ["Distância (km)", "Pace (min/km)", "Calorias"]
    selected_run_metrics = st.multiselect("Escolha métricas de corrida:", run_metrics, default=["Distância (km)", "Pace (min/km)"])

    if selected_run_metrics:
        fig_run = px.line(
            acts_df[acts_df["Tipo"] == "running"],
            x="Data",
            y=selected_run_metrics,
            markers=True,
            title="Evolução das Corridas"
        )
        st.plotly_chart(fig_run, use_container_width=True)

    st.subheader("📋 Tabela de Atividades")
    st.dataframe(acts_df)
else:
    st.info("Nenhuma atividade de corrida encontrada ainda.")

# ---------- INSIGHTS ----------
st.header("🔍 Insights (WTD / MTD / QTD / YTD / Total)")

periods = ["WTD", "MTD", "QTD", "YTD", "TOTAL"]
insights = {
    "Sono médio (h)": "Sono (h)",
    "Distância corrida (km)": "Corrida (km)",
    "Pace médio (min/km)": "Pace (min/km)",
    "Stress médio": "Stress (média)"
}

insight_table = {}
for label, col in insights.items():
    insight_table[label] = []
    for p in periods:
        val = calc_period_avg(daily_df, col, p)
        if val is None:
            insight_table[label].append("-")
        else:
            if "Pace" in label:
                insight_table[label].append(f"{val:.2f}")
            elif "Passos" in label:
                insight_table[label].append(f"{val:,.0f}")
            else:
                insight_table[label].append(f"{val:.2f}")

insight_df = pd.DataFrame(insight_table, index=periods)
st.dataframe(insight_df)

# ---------- CORRELAÇÕES ----------
st.header("📊 Correlações")

corr_options = {
    "Sono (h) x Sono (score)": ("Sono (h)", "Sono (score)"),
    "Sono (h) x Stress (média)": ("Sono (h)", "Stress (média)"),
    "Stress (média) x Sono (score)": ("Stress (média)", "Sono (score)"),
    "Dias com corrida x Sono (score)": ("Corrida (km)", "Sono (score)"),
    "Calorias (total dia) x Sono (h)": ("Calorias (total dia)", "Sono (h)"),
    "Distância corrida (km) x Stress": ("Corrida (km)", "Stress (média)"),
}

choice = st.selectbox("Escolha uma correlação:", list(corr_options.keys()))

xcol, ycol = corr_options[choice]
df_corr = daily_df.copy()
df_corr[xcol] = pd.to_numeric(df_corr[xcol], errors="coerce")
df_corr[ycol] = pd.to_numeric(df_corr[ycol], errors="coerce")

fig_corr = px.scatter(df_corr, x=xcol, y=ycol, trendline="ols", title=f"Correlação: {choice}")
st.plotly_chart(fig_corr, use_container_width=True)

# ---------- TABELA FINAL ----------
st.header("📑 DailyHUD (dados brutos)")
st.dataframe(daily_df)
