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
GSHEET_ID = "1rwcDJA1yZ2hbsJx-HOW0dCduvWqV0z7f9Iio0HI1WwY"

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

# ---------- APP ----------
st.set_page_config(page_title="📊 Dashboard Garmin", layout="wide")

st.title("🏃‍♂️ Dashboard de Atividades Garmin")

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

# ---------- TABELA FINAL ----------
st.header("📑 DailyHUD (dados brutos)")
st.dataframe(daily_df)
