# app.py
# =================================================
# Dashboard Streamlit para dados do Garmin integrados ao Google Sheets
# Inclui:
# - Botão para atualizar planilha (executa gsheet.main())
# - Gráficos de métricas com eixos primário/secundário configuráveis
# - Gráfico de atividades filtrável por tipo (ex: corrida, ciclismo)
# - Insights WTD/MTD/QTD/YTD + Total (médias/somas)
# - Matriz de correlação entre métricas escolhidas
# =================================================

import streamlit as st
import pandas as pd
import gspread
from gspread_dataframe import get_as_dataframe
from google.oauth2.service_account import Credentials
import plotly.express as px
import plotly.graph_objects as go
from plotly.subplots import make_subplots
import datetime as dt
import gsheet

# =============== CONFIGURAÇÃO ==================
GSHEET_ID = "1rwcDJA1yZ2hbsJx-HOW0DJA1yZ2hbsJx-HOW0HI1WwY"  # ID da planilha

service_account_info = st.secrets["gcp_service_account"]
scopes = ["https://www.googleapis.com/auth/spreadsheets"]
creds = Credentials.from_service_account_info(service_account_info, scopes=scopes)
client = gspread.authorize(creds)
# =================================================

# ---------- Utils ----------
def load_sheet(sheet_name: str) -> pd.DataFrame:
    try:
        ws = client.open_by_key(GSHEET_ID).worksheet(sheet_name)
        df = get_as_dataframe(ws, evaluate_formulas=True, header=0)
        df = df.dropna(how="all")
        return df
    except Exception as e:
        st.error(f"❌ Erro ao carregar aba {sheet_name}: {e}")
        return pd.DataFrame()

def calc_period(df: pd.DataFrame, col: str, freq: str, method="mean", date_col="Data", only_positive=False):
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
    vals = df.loc[mask, col].dropna()

    if only_positive:
        vals = vals[vals > 0]

    if vals.empty:
        return None

    if method == "sum":
        return vals.sum()
    elif method == "pace":  # média em segundos/km → converter para string depois
        return vals.mean()
    else:
        return vals.mean()

def format_pace(sec_per_km: float) -> str:
    if pd.isna(sec_per_km):
        return "-"
    m = int(sec_per_km // 60)
    s = int(round(sec_per_km % 60))
    return f"{m:02d}:{s:02d}"

# ---------- APP ----------
st.set_page_config(page_title="📊 Dashboard Garmin", layout="wide")
st.title("🏃‍♂️ Dashboard de Atividades Garmin")
st.write("Sincronize seus dados do Garmin com o Google Sheets e veja análises em tempo real.")

# Botão para atualizar planilha
if st.button("🔄 Atualizar dados do Garmin"):
    with st.spinner("Conectando ao Garmin e atualizando planilha..."):
        try:
            gsheet.main()
            st.success("✅ Dados atualizados com sucesso! Recarregue a página para ver os novos dados.")
        except Exception as e:
            st.error("❌ Erro ao atualizar os dados")
            st.exception(e)

# Carrega dados
daily_df = load_sheet("DailyHUD")
acts_df  = load_sheet("Activities")

if daily_df.empty:
    st.warning("Nenhum dado encontrado na aba `DailyHUD`. Clique em **Atualizar dados** acima.")
    st.stop()

# Converter colunas numéricas
daily_df["Data"] = pd.to_datetime(daily_df["Data"], errors="coerce")
numeric_cols = [
    "Sono (h)", "Sono Deep (h)", "Sono REM (h)", "Sono Light (h)", 
    "Sono (score)", "Body Battery (start)", "Body Battery (end)", 
    "Body Battery (mín)", "Body Battery (máx)", "Body Battery (média)", 
    "Stress (média)", "Passos", "Calorias (total dia)", 
    "Corrida (km)", "Duração (min)", "Pace (s/km)"
]
for c in numeric_cols:
    if c in daily_df.columns:
        daily_df[c] = pd.to_numeric(daily_df[c], errors="coerce")

# ---------- GRÁFICO MULTIMÉTRICAS ----------
st.header("📊 Evolução das Métricas")

metrics = [
    "Sono (h)", "Sono Deep (h)", "Sono REM (h)", "Sono Light (h)", "Sono (score)",
    "Body Battery (start)", "Body Battery (end)", "Body Battery (mín)",
    "Body Battery (máx)", "Body Battery (média)", "Stress (média)",
    "Passos", "Calorias (total dia)", "Corrida (km)", "Duração (min)", "Pace (s/km)"
]

selected_metrics = st.multiselect("Escolha métricas para visualizar:", metrics, default=["Sono (h)", "Sono (score)"])

if selected_metrics:
    fig = make_subplots(specs=[[{"secondary_y": True}]])
    colors = px.colors.qualitative.Set2
    color_idx = 0

    y1 = selected_metrics[0]
    fig.add_trace(go.Scatter(x=daily_df["Data"], y=daily_df[y1], mode="lines+markers", name=y1, line=dict(color=colors[color_idx])), secondary_y=False)
    color_idx += 1

    if len(selected_metrics) > 1:
        y2 = selected_metrics[1]
        fig.add_trace(go.Scatter(x=daily_df["Data"], y=daily_df[y2], mode="lines+markers", name=y2, line=dict(color=colors[color_idx])), secondary_y=True)
        color_idx += 1
        fig.update_yaxes(title_text=y2, secondary_y=True)

    for m in selected_metrics[2:]:
        fig.add_trace(go.Scatter(x=daily_df["Data"], y=daily_df[m], mode="lines+markers", name=m, line=dict(color=colors[color_idx % len(colors)])), secondary_y=True)
        color_idx += 1

    fig.update_layout(title="Comparativo de Métricas Selecionadas", legend=dict(orientation="h", y=-0.2), margin=dict(l=40, r=40, t=40, b=40))
    fig.update_xaxes(title="Data")
    fig.update_yaxes(title_text=y1, secondary_y=False)
    st.plotly_chart(fig, use_container_width=True)

# ---------- ATIVIDADES ----------
st.header("🏃‍♀️ Atividades")

if not acts_df.empty:
    acts_df["Data"] = pd.to_datetime(acts_df["Data"], errors="coerce")

    tipos_disponiveis = acts_df["Tipo"].dropna().unique().tolist()
    tipo_escolhido = st.selectbox("Filtrar por tipo de atividade:", ["Todos"] + tipos_disponiveis)

    df_plot = acts_df.copy()
    if tipo_escolhido != "Todos":
        df_plot = df_plot[df_plot["Tipo"] == tipo_escolhido]

    run_metrics = ["Distância (km)", "Pace (s/km)", "Duração (min)", "Calorias"]
    selected_run_metrics = st.multiselect("Escolha métricas da atividade:", run_metrics, default=["Distância (km)", "Pace (s/km)"])

    if selected_run_metrics:
        fig_act = make_subplots(specs=[[{"secondary_y": True}]])
        colors = px.colors.qualitative.Plotly
        y1 = selected_run_metrics[0]
        fig_act.add_trace(go.Scatter(x=df_plot["Data"], y=pd.to_numeric(df_plot[y1], errors="coerce"), mode="lines+markers", name=y1, line=dict(color=colors[0])), secondary_y=False)

        if len(selected_run_metrics) > 1:
            y2 = selected_run_metrics[1]
            fig_act.add_trace(go.Scatter(x=df_plot["Data"], y=pd.to_numeric(df_plot[y2], errors="coerce"), mode="lines+markers", name=y2, line=dict(color=colors[1])), secondary_y=True)
            fig_act.update_yaxes(title_text=y2, secondary_y=True)

        fig_act.update_layout(title=f"Métricas da atividade: {tipo_escolhido}", legend=dict(orientation="h", y=-0.2))
        fig_act.update_xaxes(title="Data")
        fig_act.update_yaxes(title_text=y1, secondary_y=False)
        st.plotly_chart(fig_act, use_container_width=True)

    st.subheader("📋 Tabela de Atividades")
    st.dataframe(df_plot)
else:
    st.info("Nenhuma atividade encontrada ainda.")

# ---------- INSIGHTS ----------
st.header("🔍 Insights (WTD / MTD / QTD / YTD / Total)")

insights = {
    "Sono médio (h)": ("Sono (h)", "mean"),
    "Qualidade do sono (score)": ("Sono (score)", "mean"),
    "Distância corrida (km) - média": ("Corrida (km)", "mean"),
    "Distância corrida (km) - soma": ("Corrida (km)", "sum"),
    "Pace médio (min/km)": ("Pace (s/km)", "pace"),
    "Passos médios": ("Passos", "mean"),
    "Calorias (total dia)": ("Calorias (total dia)", "mean"),
    "Body Battery (média)": ("Body Battery (média)", "mean"),
    "Breathwork (min)": ("Duração (min)", "mean"),
}

insight_data = []
for label, (col, method) in insights.items():
    row_data = {"Métrica": label}
    for period in ["WTD", "MTD", "QTD", "YTD", "TOTAL"]:
        val = calc_period(daily_df, col, period, method, only_positive=("Corrida" in label or "Pace" in label or "Breathwork" in label))
        if val is None:
            row_data[period] = "-"
        else:
            if method == "pace":
                row_data[period] = format_pace(val)
            elif "Passos" in label:
                row_data[period] = f"{val:,.0f}"
            else:
                row_data[period] = f"{val:.2f}"
    insight_data.append(row_data)

insight_df = pd.DataFrame(insight_data).set_index("Métrica")
st.dataframe(insight_df)

# ---------- MATRIZ DE CORRELAÇÃO ----------
st.header("📊 Matriz de Correlação")

corr_metrics = st.multiselect("Escolha métricas para matriz de correlação:", metrics, default=["Sono (h)", "Sono (score)", "Stress (média)", "Corrida (km)", "Pace (s/km)", "Duração (min)"])

if corr_metrics:
    df_corr = daily_df[corr_metrics].apply(pd.to_numeric, errors="coerce").dropna()
    if not df_corr.empty:
        corr_matrix = df_corr.corr()
        fig_heat = px.imshow(corr_matrix, text_auto=True, color_continuous_scale="RdBu_r", origin="lower", title="Matriz de Correlação")
        st.plotly_chart(fig_heat, use_container_width=True)
    else:
        st.info("Dados insuficientes para calcular a matriz de correlação.")

# ---------- TABELA FINAL ----------
st.header("📑 DailyHUD (dados brutos)")
st.dataframe(daily_df)
