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

# ---------- GRÁFICO MULTIMÉTRICAS ----------
st.header("📊 Evolução das Métricas")

metrics = [
    "Sono (h)", "Sono Deep (h)", "Sono REM (h)", "Sono Light (h)", "Sono (score)",
    "Body Battery (start)", "Body Battery (end)", "Body Battery (mín)",
    "Body Battery (máx)", "Body Battery (média)", "Stress (média)",
    "Passos", "Calorias (total dia)", "Corrida (km)", "Pace (min/km)"
]

selected_metrics = st.multiselect(
    "📊 Escolha as métricas para visualizar:",
    metrics,
    default=["Sono (h)", "Sono (score)"]
)

if selected_metrics:
    fig = make_subplots(specs=[[{"secondary_y": True}]])
    colors = px.colors.qualitative.Set2
    color_idx = 0

    # Primeiro eixo Y
    y1 = selected_metrics[0]
    fig.add_trace(
        go.Scatter(
            x=daily_df["Data"], y=daily_df[y1],
            mode="lines+markers", name=y1, line=dict(color=colors[color_idx])
        ),
        secondary_y=False,
    )
    color_idx += 1

    # Segundo eixo Y
    if len(selected_metrics) > 1:
        y2 = selected_metrics[1]
        fig.add_trace(
            go.Scatter(
                x=daily_df["Data"], y=daily_df[y2],
                mode="lines+markers", name=y2, line=dict(color=colors[color_idx])
            ),
            secondary_y=True,
        )
        color_idx += 1

    # Extras → também no eixo secundário
    for m in selected_metrics[2:]:
        fig.add_trace(
            go.Scatter(
                x=daily_df["Data"], y=daily_df[m],
                mode="lines+markers", name=m,
                line=dict(color=colors[color_idx % len(colors)])
            ),
            secondary_y=True,
        )
        color_idx += 1

    fig.update_layout(
        title="Comparativo de Métricas Selecionadas",
        legend=dict(orientation="h", y=-0.2),
        margin=dict(l=40, r=40, t=40, b=40),
    )
    fig.update_xaxes(title="Data")
    fig.update_yaxes(title=y1, secondary_y=False)
    if len(selected_metrics) > 1:
        fig.update_yaxes(title=selected_metrics[1], secondary_y=True)

    st.plotly_chart(fig, use_container_width=True)


# ---------- CORRIDAS ----------
st.header("🏃‍♀️ Corridas")

if not acts_df.empty:
    acts_df["Data"] = pd.to_datetime(acts_df["Data"], errors="coerce")

    activity_types = acts_df["Tipo"].dropna().unique().tolist()
    selected_type = st.selectbox("Escolha o tipo de atividade:", activity_types, index=0)

    run_metrics = ["Distância (km)", "Pace (min/km)", "Calorias"]
    selected_run_metrics = st.multiselect(
        "Escolha métricas da atividade:",
        run_metrics,
        default=["Distância (km)", "Pace (min/km)"]
    )

    df_filtered = acts_df[acts_df["Tipo"] == selected_type]

    if selected_run_metrics and not df_filtered.empty:
        fig_run = make_subplots(specs=[[{"secondary_y": True}]])
        colors = px.colors.qualitative.Plotly
        color_idx = 0

        # Primeiro eixo
        y1 = selected_run_metrics[0]
        fig_run.add_trace(
            go.Scatter(
                x=df_filtered["Data"], y=df_filtered[y1],
                mode="lines+markers", name=y1,
                line=dict(color=colors[color_idx])
            ),
            secondary_y=False,
        )
        color_idx += 1

        # Segundo eixo
        if len(selected_run_metrics) > 1:
            y2 = selected_run_metrics[1]
            fig_run.add_trace(
                go.Scatter(
                    x=df_filtered["Data"], y=df_filtered[y2],
                    mode="lines+markers", name=y2,
                    line=dict(color=colors[color_idx])
                ),
                secondary_y=True,
            )
            color_idx += 1

        # Extras
        for m in selected_run_metrics[2:]:
            fig_run.add_trace(
                go.Scatter(
                    x=df_filtered["Data"], y=df_filtered[m],
                    mode="lines+markers", name=m,
                    line=dict(color=colors[color_idx % len(colors)])
                ),
                secondary_y=True,
            )
            color_idx += 1

        fig_run.update_layout(
            title=f"Evolução das Atividades ({selected_type})",
            legend=dict(orientation="h", y=-0.2)
        )
        fig_run.update_xaxes(title="Data")
        fig_run.update_yaxes(title=y1, secondary_y=False)
        if len(selected_run_metrics) > 1:
            fig_run.update_yaxes(title=selected_run_metrics[1], secondary_y=True)

        st.plotly_chart(fig_run, use_container_width=True)

    st.subheader("📋 Tabela de Atividades")
    st.dataframe(df_filtered)
else:
    st.info("Nenhuma atividade encontrada ainda.")


# ---------- TABELA FINAL ----------
st.header("📑 DailyHUD (dados brutos)")
st.dataframe(daily_df)
