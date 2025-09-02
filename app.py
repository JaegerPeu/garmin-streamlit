# app.py
# =====================================================
# Dashboard Streamlit para visualização dos dados Garmin
# Dados são carregados do Google Sheets (já atualizado
# pelo script garmin_to_gsheets.py).
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
import gsheet

# ================= CONFIGURAÇÃO ==================
GSHEET_ID = "1rwcDJA1yZ2hbsJx-HOW0dCduvWqV0z7f9Iio0HI1WwY"  # ID da planilha

service_account_info = st.secrets["gcp_service_account"]
scopes = ["https://www.googleapis.com/auth/spreadsheets"]
creds = Credentials.from_service_account_info(service_account_info, scopes=scopes)
client = gspread.authorize(creds)
# =================================================


# ---------- Utils ----------
def load_sheet(sheet_name: str) -> pd.DataFrame:
    """Carrega uma aba da planilha do Google Sheets em DataFrame."""
    try:
        ws = client.open_by_key(GSHEET_ID).worksheet(sheet_name)
        df = get_as_dataframe(ws, evaluate_formulas=True, header=0)
        df = df.dropna(how="all")
        return df
    except Exception as e:
        st.error(f"❌ Erro ao carregar aba {sheet_name}: {e}")
        return pd.DataFrame()

def calc_period(df: pd.DataFrame, col: str, freq: str, date_col="Data", only_positive=False, mode="mean"):
    """Calcula média ou soma por período (WTD, MTD, QTD, YTD, TOTAL)."""
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
    subset = df.loc[mask, col].dropna()
    if only_positive:
        subset = subset[subset > 0]

    if subset.empty:
        return None

    if mode == "sum":
        return subset.sum()
    else:
        return subset.mean()

def format_hours(value):
    """Converte horas decimais em hh:mm para exibição."""
    if pd.isna(value) or value == "":
        return "-"
    try:
        horas = int(float(value))
        minutos = int(round((float(value) - horas) * 60))
        return f"{horas:02d}:{minutos:02d}"
    except Exception:
        return "-"

def format_pace(value):
    """Converte pace decimal em mm:ss para exibição."""
    if pd.isna(value) or value == "" or float(value) == 0:
        return "-"
    try:
        minutos = int(float(value))
        segundos = int(round((float(value) - minutos) * 60))
        return f"{minutos}:{segundos:02d}"
    except Exception:
        return "-"


# ---------- APP ----------
st.set_page_config(page_title="📊 Dashboard Garmin", layout="wide")

st.title("🏃‍♂️ Dashboard de Atividades Garmin")
st.write("Sincronize seus dados do Garmin com o Google Sheets e veja análises em tempo real.")

# Botão para atualizar planilha
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

numeric_cols = [
    "Sono (h)", "Sono Deep (h)", "Sono REM (h)", "Sono Light (h)",
    "Sono (score)", "Body Battery (start)", "Body Battery (end)",
    "Body Battery (mín)", "Body Battery (máx)", "Body Battery (média)",
    "Stress (média)", "Passos", "Calorias (total dia)", 
    "Corrida (km)", "Pace (min/km)", "Breathwork (min)"
]
for c in numeric_cols:
    if c in daily_df.columns:
        daily_df[c] = pd.to_numeric(daily_df[c], errors="coerce")

# ---------- GRÁFICO MULTIMÉTRICAS ----------
st.header("📊 Evolução das Métricas")

metrics = numeric_cols
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
            mode="lines+markers", name=y1,
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
                x=daily_df["Data"], y=daily_df[y2],
                mode="lines+markers", name=y2,
                line=dict(color=colors[color_idx])
            ),
            secondary_y=True,
        )
        fig.update_yaxes(title_text=y2, secondary_y=True)
        color_idx += 1

    # Extras → mesmo eixo do segundo
    for m in selected_metrics[2:]:
        fig.add_trace(
            go.Scatter(
                x=daily_df["Data"], y=daily_df[m],
                mode="lines+markers", name=m,
                line=dict(color=colors[color_idx % len(colors)]),
                yaxis="y2" if len(selected_metrics) > 1 else "y"
            )
        )
        color_idx += 1

    fig.update_layout(
        title="Comparativo de Métricas Selecionadas",
        legend=dict(orientation="h", y=-0.2),
        margin=dict(l=40, r=40, t=40, b=40),
    )
    st.plotly_chart(fig, use_container_width=True)

# ---------- ATIVIDADES ----------
st.header("🏃‍♀️ Atividades")

if not acts_df.empty:
    acts_df["Data"] = pd.to_datetime(acts_df["Data"], errors="coerce")

    activity_types = acts_df["Tipo"].dropna().unique().tolist()
    selected_type = st.selectbox("Escolha o tipo de atividade:", activity_types, index=0)

    # Seleciona métricas de acordo com o tipo
    act_metrics = ["Distância (km)", "Pace (min/km)", "Calorias", "Duração (min)", "FC Média", "VO2 Máx"]
    selected_act_metrics = st.multiselect(
        "Escolha métricas da atividade:",
        act_metrics,
        default=["Distância (km)", "Pace (min/km)"]
    )

    df_filtered = acts_df[acts_df["Tipo"] == selected_type]

    if selected_act_metrics and not df_filtered.empty:
        fig_act = make_subplots(specs=[[{"secondary_y": True}]])
        colors = px.colors.qualitative.Plotly
        color_idx = 0

        # Primeiro eixo
        y1 = selected_act_metrics[0]
        fig_act.add_trace(
            go.Scatter(
                x=df_filtered["Data"], y=df_filtered[y1],
                mode="lines+markers", name=y1,
                line=dict(color=colors[color_idx])
            ),
            secondary_y=False,
        )
        fig_act.update_yaxes(title_text=y1, secondary_y=False)
        color_idx += 1

        # Segundo eixo
        if len(selected_act_metrics) > 1:
            y2 = selected_act_metrics[1]
            fig_act.add_trace(
                go.Scatter(
                    x=df_filtered["Data"], y=df_filtered[y2],
                    mode="lines+markers", name=y2,
                    line=dict(color=colors[color_idx])
                ),
                secondary_y=True,
            )
            fig_act.update_yaxes(title_text=y2, secondary_y=True)
            color_idx += 1

        # Extras
        for m in selected_act_metrics[2:]:
            fig_act.add_trace(
                go.Scatter(
                    x=df_filtered["Data"], y=df_filtered[m],
                    mode="lines+markers", name=m,
                    line=dict(color=colors[color_idx % len(colors)]),
                    yaxis="y2" if len(selected_act_metrics) > 1 else "y"
                )
            )
            color_idx += 1

        fig_act.update_layout(title=f"Evolução de {selected_type}", legend=dict(orientation="h", y=-0.2))
        st.plotly_chart(fig_act, use_container_width=True)

    st.subheader("📋 Tabela de Atividades")
    st.dataframe(df_filtered)
else:
    st.info("Nenhuma atividade encontrada ainda.")

# ---------- INSIGHTS ----------
st.header("🔍 Insights (WTD / MTD / QTD / YTD / Total)")

periods = ["WTD", "MTD", "QTD", "YTD", "TOTAL"]
insights = {
    "Sono (h)": {"col": "Sono (h)", "mode": "mean", "format": "time"},
    "Sono Deep (h)": {"col": "Sono Deep (h)", "mode": "mean", "format": "time"},
    "Sono REM (h)": {"col": "Sono REM (h)", "mode": "mean", "format": "time"},
    "Sono Light (h)": {"col": "Sono Light (h)", "mode": "mean", "format": "time"},
    "Qualidade do sono (score)": {"col": "Sono (score)", "mode": "mean", "format": "num"},
    "Distância corrida (km) — Média": {"col": "Corrida (km)", "mode": "mean", "format": "num_pos"},
    "Distância corrida (km) — Soma": {"col": "Corrida (km)", "mode": "sum", "format": "num_pos"},
    "Pace médio (min/km)": {"col": "Pace (min/km)", "mode": "mean", "format": "pace", "only_positive": True},
    "Passos — Média": {"col": "Passos", "mode": "mean", "format": "int"},
    "Passos — Soma": {"col": "Passos", "mode": "sum", "format": "int"},
    "Calorias (total dia) — Média": {"col": "Calorias (total dia)", "mode": "mean", "format": "num"},
    "Calorias (total dia) — Soma": {"col": "Calorias (total dia)", "mode": "sum", "format": "int"},
    "Body Battery (média)": {"col": "Body Battery (média)", "mode": "mean", "format": "num"},
    "Stress médio": {"col": "Stress (média)", "mode": "mean", "format": "num"},
    "Breathwork (min) — Média": {"col": "Breathwork (min)", "mode": "mean", "format": "int", "only_positive": True},
    "Breathwork (min) — Soma": {"col": "Breathwork (min)", "mode": "sum", "format": "int", "only_positive": True},
}

insight_data = []
for label, cfg in insights.items():
    col = cfg["col"]
    mode = cfg.get("mode", "mean")
    only_positive = cfg.get("only_positive", False)
    fmt = cfg.get("format", "num")

    row_data = {"Métrica": label}
    for p in periods:
        val = calc_period(daily_df, col, p, only_positive=only_positive, mode=mode)
        if val is None:
            row_data[p] = "-"
        else:
            if fmt == "time":
                row_data[p] = format_hours(val)
            elif fmt == "pace":
                row_data[p] = format_pace(val)
            elif fmt == "int":
                row_data[p] = f"{val:,.0f}"
            else:
                row_data[p] = f"{val:.2f}"
    insight_data.append(row_data)

insight_df = pd.DataFrame(insight_data).set_index("Métrica")
st.dataframe(insight_df)

# ---------- MATRIZ DE CORRELAÇÃO ----------
st.header("📊 Matriz de Correlação")

corr_metrics = st.multiselect(
    "Escolha métricas para calcular correlação:",
    metrics,
    default=["Sono (h)", "Sono (score)", "Stress (média)", "Corrida (km)", "Pace (min/km)", "Breathwork (min)"]
)

if len(corr_metrics) >= 2:
    df_corr = daily_df.copy()
    df_corr = df_corr[corr_metrics].apply(pd.to_numeric, errors="coerce").dropna()
    corr_matrix = df_corr.corr()

    fig_heat = px.imshow(
        corr_matrix,
        text_auto=True,
        color_continuous_scale="RdBu",
        zmin=-1, zmax=1,
        title="Matriz de Correlação"
    )
    st.plotly_chart(fig_heat, use_container_width=True)

    # scatter se escolher exatamente 2
    if len(corr_metrics) == 2:
        xcol, ycol = corr_metrics
        fig_scatter = px.scatter(
            df_corr,
            x=xcol, y=ycol,
            trendline="ols",
            title=f"Relação: {xcol} x {ycol}"
        )
        st.plotly_chart(fig_scatter, use_container_width=True)
else:
    st.info("Selecione pelo menos 2 métricas para ver correlações.")

# ---------- TABELA FINAL ----------
st.header("📑 DailyHUD (dados brutos)")

df_display = daily_df.copy()
if "Sono (h)" in df_display.columns:
    df_display["Sono (h)"] = df_display["Sono (h)"].apply(format_hours)
    if "Sono Deep (h)" in df_display.columns:
        df_display["Sono Deep (h)"] = df_display["Sono Deep (h)"].apply(format_hours)
    if "Sono REM (h)" in df_display.columns:
        df_display["Sono REM (h)"] = df_display["Sono REM (h)"].apply(format_hours)
    if "Sono Light (h)" in df_display.columns:
        df_display["Sono Light (h)"] = df_display["Sono Light (h)"].apply(format_hours)

if "Pace (min/km)" in df_display.columns:
    df_display["Pace (min/km)"] = df_display["Pace (min/km)"].apply(format_pace)

st.dataframe(df_display)
