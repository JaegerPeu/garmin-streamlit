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
from typing import List, Dict, Any, Optional

# ================= CONFIGURAÇÃO ==================
GSHEET_ID = "1rwcDJA1yZ2hbsJx-HOW0dCduvWqV0z7f9Iio0HI1wWY"  # ID da planilha no Google Sheets

service_account_info = st.secrets["gcp_service_account"]
scopes = ["https://www.googleapis.com/auth/spreadsheets"]
creds = Credentials.from_service_account_info(service_account_info, scopes=scopes)
client = gspread.authorize(creds)
# =================================================

# ---------- Utilidades ----------
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

def calc_period_metric(df: pd.DataFrame, col: str, period: str, mode: str = "mean", only_positive: bool = False, date_col="Data") -> Optional[float]:
    """Calcula estatística (média ou soma) de uma métrica em um período específico."""
    if col not in df.columns:
        return None

    temp = df.copy()
    temp[date_col] = pd.to_datetime(temp[date_col], errors="coerce")
    temp[col] = pd.to_numeric(temp[col], errors="coerce")

    today = dt.date.today()
    if period == "WTD":
        start = today - dt.timedelta(days=today.weekday())
    elif period == "MTD":
        start = today.replace(day=1)
    elif period == "QTD":
        q = (today.month - 1) // 3 + 1
        start = dt.date(today.year, 3 * (q - 1) + 1, 1)
    elif period == "YTD":
        start = dt.date(today.year, 1, 1)
    else:  # TOTAL
        start = temp[date_col].min().date()

    mask = temp[date_col].dt.date >= start
    vals = temp.loc[mask, col].dropna()

    if only_positive:
        vals = vals[vals > 0]

    if vals.empty:
        return None

    if mode == "sum":
        return float(vals.sum())
    return float(vals.mean())

def format_metric(value: Optional[float], label: str) -> str:
    """Formata métricas (horas, pace, passos, etc)."""
    if value is None:
        return "-"

    # Pace em min/km
    if "Pace" in label:
        minutos = int(value)
        segundos = int(round((value - minutos) * 60))
        return f"{minutos}:{segundos:02d}"

    # Horas de sono em h:mm
    if "Sono" in label and "(h)" in label:
        horas = int(value)
        minutos = int(round((value - horas) * 60))
        return f"{horas}h{minutos:02d}"

    # Passos como inteiro
    if "Passos" in label:
        return f"{value:,.0f}"

    # Padrão: número com 2 casas
    return f"{value:.2f}"

# ---------- APP ----------
st.set_page_config(page_title="📊 Dashboard Garmin", layout="wide")

st.title("🏃‍♂️ Dashboard de Atividades Garmin")
st.write("Sincronize seus dados do Garmin com o Google Sheets e veja análises em tempo real.")

# Botão para atualizar planilha
if st.button("🔄 Atualizar dados do Garmin"):
    with st.spinner("Conectando ao Garmin e atualizando planilha..."):
        try:
            gsheet.main()
            st.cache_data.clear()  # limpa cache ao atualizar
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

# Converter colunas numéricas
daily_df["Data"] = pd.to_datetime(daily_df["Data"], errors="coerce")

numeric_cols = [
    "Sono (h)", "Sono Deep (h)", "Sono REM (h)", "Sono Light (h)", 
    "Sono (score)", "Body Battery (start)", "Body Battery (end)", 
    "Body Battery (mín)", "Body Battery (máx)", "Body Battery (média)", 
    "Stress (média)", "Passos", "Calorias (total dia)", "Corrida (km)", 
    "Pace (min/km)", "Breathwork (min)"
]
for c in numeric_cols:
    if c in daily_df.columns:
        daily_df[c] = pd.to_numeric(daily_df[c], errors="coerce")

# Criar colunas auxiliares para cálculo correto
if "Pace (min/km)" in daily_df.columns:
    daily_df["PaceNum"] = pd.to_numeric(daily_df["Pace (min/km)"], errors="coerce")
if "Sono (h)" in daily_df.columns:
    daily_df["SonoHorasNum"] = pd.to_numeric(daily_df["Sono (h)"], errors="coerce")

# ---------- GRÁFICO MULTIMÉTRICAS ----------
st.header("📊 Evolução das Métricas")

metrics = [
    "Sono (h)", "Sono Deep (h)", "Sono REM (h)", "Sono Light (h)", "Sono (score)",
    "Body Battery (start)", "Body Battery (end)", "Body Battery (mín)",
    "Body Battery (máx)", "Body Battery (média)", "Stress (média)",
    "Passos", "Calorias (total dia)", "Corrida (km)", 
    "Pace (min/km)", "Breathwork (min)"
]

selected_metrics = st.multiselect("Escolha as métricas para visualizar:", metrics, default=["Sono (h)", "Sono (score)"])

if selected_metrics:
    fig = make_subplots(specs=[[{"secondary_y": True}]])
    colors = px.colors.qualitative.Set2
    color_idx = 0

    # Primeiro eixo Y
    y1 = selected_metrics[0]
    fig.add_trace(
        go.Scatter(
            x=daily_df["Data"],
            y=daily_df[y1],
            mode="lines+markers",
            name=y1,
            line=dict(color=colors[color_idx])
        ),
        secondary_y=False,
    )
    fig.update_yaxes(title_text=y1, secondary_y=False)
    color_idx += 1

    # Segundo eixo Y
    if len(selected_metrics) > 1:
        y2 = selected_metrics[1]
        fig.add_trace(
            go.Scatter(
                x=daily_df["Data"],
                y=daily_df[y2],
                mode="lines+markers",
                name=y2,
                line=dict(color=colors[color_idx])
            ),
            secondary_y=True,
        )
        fig.update_yaxes(title_text=y2, secondary_y=True)
        color_idx += 1

    # Restantes → mesmo eixo do 2º
    for m in selected_metrics[2:]:
        fig.add_trace(
            go.Scatter(
                x=daily_df["Data"],
                y=daily_df[m],
                mode="lines+markers",
                name=m,
                line=dict(color=colors[color_idx % len(colors)]),
                yaxis="y2"
            )
        )
        color_idx += 1

    fig.update_layout(
        title="Comparativo de Métricas Selecionadas",
        legend=dict(orientation="h", y=-0.2),
        margin=dict(l=40, r=40, t=40, b=40),
    )
    st.plotly_chart(fig, use_container_width=True)

# ---------- FILTRO DE ATIVIDADES ----------
st.header("🏃‍♀️ Atividades")

if not acts_df.empty:
    acts_df["Data"] = pd.to_datetime(acts_df["Data"], errors="coerce")

    activity_types = acts_df["Tipo"].dropna().unique().tolist()
    selected_activity = st.selectbox("Escolha o tipo de atividade:", activity_types, index=0)

    filtered_acts = acts_df[acts_df["Tipo"] == selected_activity]

    run_metrics = ["Distância (km)", "Pace (min/km)", "Duração (min)", "Calorias"]
    selected_run_metrics = st.multiselect(
        "Escolha métricas para o gráfico da atividade:", 
        run_metrics, 
        default=["Distância (km)", "Pace (min/km)"]
    )

    if selected_run_metrics:
        fig_run = make_subplots(specs=[[{"secondary_y": True}]])
        colors = px.colors.qualitative.Plotly
        idx = 0

        y1 = selected_run_metrics[0]
        fig_run.add_trace(
            go.Scatter(
                x=filtered_acts["Data"],
                y=pd.to_numeric(filtered_acts[y1], errors="coerce"),
                mode="lines+markers",
                name=y1,
                line=dict(color=colors[idx])
            ),
            secondary_y=False,
        )
        fig_run.update_yaxes(title_text=y1, secondary_y=False)
        idx += 1

        if len(selected_run_metrics) > 1:
            y2 = selected_run_metrics[1]
            fig_run.add_trace(
                go.Scatter(
                    x=filtered_acts["Data"],
                    y=pd.to_numeric(filtered_acts[y2], errors="coerce"),
                    mode="lines+markers",
                    name=y2,
                    line=dict(color=colors[idx])
                ),
            secondary_y=True,
            )
            fig_run.update_yaxes(title_text=y2, secondary_y=True)
            idx += 1

        st.plotly_chart(fig_run, use_container_width=True)

    st.subheader("📋 Tabela de Atividades")
    st.dataframe(filtered_acts)
else:
    st.info("Nenhuma atividade encontrada ainda.")

# ---------- INSIGHTS ----------
st.header("🔍 Insights (WTD / MTD / QTD / YTD / Total)")

insights = {
    "Sono médio (h)": {"col": "SonoHorasNum", "mode": "mean", "format": "hours", "only_positive": True},
    "Qualidade do sono (score)": {"col": "Sono (score)", "mode": "mean", "format": "num", "only_positive": True},
    "Distância corrida (km) [soma]": {"col": "Corrida (km)", "mode": "sum", "format": "num", "only_positive": True},
    "Distância corrida (km) [média]": {"col": "Corrida (km)", "mode": "mean", "format": "num", "only_positive": True},
    "Pace médio (min/km)": {"col": "PaceNum", "mode": "mean", "format": "pace", "only_positive": True},
    "Passos [soma]": {"col": "Passos", "mode": "sum", "format": "num", "only_positive": True},
    "Passos [média]": {"col": "Passos", "mode": "mean", "format": "num", "only_positive": True},
    "Calorias (total dia) [soma]": {"col": "Calorias (total dia)", "mode": "sum", "format": "num", "only_positive": True},
    "Calorias (total dia) [média]": {"col": "Calorias (total dia)", "mode": "mean", "format": "num", "only_positive": True},
    "Body Battery (média)": {"col": "Body Battery (média)", "mode": "mean", "format": "num", "only_positive": True},
    "Stress médio": {"col": "Stress (média)", "mode": "mean", "format": "num", "only_positive": True},
    "Breathwork (min) [soma]": {"col": "Breathwork (min)", "mode": "sum", "format": "num", "only_positive": True},
    "Breathwork (min) [média]": {"col": "Breathwork (min)", "mode": "mean", "format": "num", "only_positive": True},
}

periods = ["WTD", "MTD", "QTD", "YTD", "TOTAL"]

insight_data = []
for label, cfg in insights.items():
    row_data = {"Métrica": label}
    for p in periods:
        val = calc_period_metric(
            daily_df, 
            col=cfg["col"], 
            period=p, 
            mode=cfg.get("mode", "mean"), 
            only_positive=cfg.get("only_positive", False)
        )
        row_data[p] = format_metric(val, label)
    insight_data.append(row_data)

insight_df = pd.DataFrame(insight_data).set_index("Métrica")
st.dataframe(insight_df)

# ---------- MATRIZ DE CORRELAÇÃO ----------
st.header("📊 Matriz de Correlação")

corr_metrics = st.multiselect(
    "Escolha as métricas para correlação:", 
    metrics, 
    default=["Sono (h)", "Sono (score)", "Stress (média)", "Corrida (km)", "Pace (min/km)", "Breathwork (min)"]
)

if len(corr_metrics) >= 2:
    df_corr = daily_df[corr_metrics].copy()
    df_corr = df_corr.apply(pd.to_numeric, errors="coerce")
    corr_matrix = df_corr.corr()

    fig_corr_matrix = px.imshow(
        corr_matrix,
        text_auto=True,
        aspect="auto",
        color_continuous_scale="RdBu",
        origin="lower",
        title="Matriz de Correlação"
    )
    st.plotly_chart(fig_corr_matrix, use_container_width=True)

    # Scatterplot se exatamente 2 métricas forem escolhidas
    if len(corr_metrics) == 2:
        fig_scatter = px.scatter(
            df_corr,
            x=corr_metrics[0],
            y=corr_metrics[1],
            trendline="ols",
            title=f"Correlação: {corr_metrics[0]} × {corr_metrics[1]}"
        )
        st.plotly_chart(fig_scatter, use_container_width=True)

# ---------- TABELA FINAL ----------
st.header("📑 DailyHUD (dados brutos)")
st.dataframe(daily_df)
