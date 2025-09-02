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

def calc_period(df: pd.DataFrame, col: str, freq: str, date_col="Data", only_positive=False, mode="mean", filter_col=None) -> Optional[float]:
    """Calcula métrica (média ou soma) em um período (WTD, MTD, QTD, YTD, TOTAL).
       - only_positive: ignora valores <= 0
       - filter_col: se informado, só calcula quando filter_col > 0 (ex: pace apenas em dias com corrida)
    """
    if col not in df.columns:
        return None

    temp = df.copy()
    temp[date_col] = pd.to_datetime(temp[date_col], errors="coerce")
    temp[col] = pd.to_numeric(temp[col], errors="coerce")

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
    else:  # TOTAL
        start = temp[date_col].min().date()

    mask = temp[date_col].dt.date >= start
    subset = temp.loc[mask, [col]]

    if filter_col and filter_col in temp.columns:
        temp[filter_col] = pd.to_numeric(temp[filter_col], errors="coerce")
        subset = temp.loc[(mask) & (temp[filter_col] > 0), [col]]

    vals = subset[col].dropna()

    if only_positive:
        vals = vals[vals > 0]

    if vals.empty:
        return None

    return float(vals.sum() if mode == "sum" else vals.mean())

def format_metric(value: Optional[float], fmt: str) -> str:
    """Formata métricas (horas, pace, passos, número, etc)."""
    if value is None:
        return "-"

    if fmt == "pace":  # min/km em decimal → mm:ss
        minutos = int(value)
        segundos = int(round((value - minutos) * 60))
        return f"{minutos}:{segundos:02d}"

    if fmt == "time":  # horas decimais → h:mm
        horas = int(float(value))
        minutos = int(round((float(value) - horas) * 60))
        return f"{horas}h{minutos:02d}"

    if fmt == "int":
        return f"{value:,.0f}"

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
            st.cache_data.clear()
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

# Colunas auxiliares
if "Pace (min/km)" in daily_df.columns:
    daily_df["PaceNum"] = pd.to_numeric(daily_df["Pace (min/km)"], errors="coerce")
if "Sono (h)" in daily_df.columns:
    daily_df["SonoHorasNum"] = pd.to_numeric(daily_df["Sono (h)"], errors="coerce")

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
    idx = 0

    # Primeiro eixo Y
    y1 = selected_metrics[0]
    fig.add_trace(
        go.Scatter(
            x=daily_df["Data"], y=daily_df[y1],
            mode="lines+markers", name=y1,
            line=dict(color=colors[idx])
        ),
        secondary_y=False,
    )
    fig.update_yaxes(title_text=y1, secondary_y=False)
    idx += 1

    # Segundo eixo Y
    if len(selected_metrics) > 1:
        y2 = selected_metrics[1]
        fig.add_trace(
            go.Scatter(
                x=daily_df["Data"], y=daily_df[y2],
                mode="lines+markers", name=y2,
                line=dict(color=colors[idx])
            ),
            secondary_y=True,
        )
        fig.update_yaxes(title_text=y2, secondary_y=True)
        idx += 1

    # Extras → mesmo eixo do segundo
    for m in selected_metrics[2:]:
        fig.add_trace(
            go.Scatter(
                x=daily_df["Data"], y=daily_df[m],
                mode="lines+markers", name=m,
                line=dict(color=colors[idx % len(colors)]),
                yaxis="y2" if len(selected_metrics) > 1 else "y"
            )
        )
        idx += 1

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

    df_filtered = acts_df[acts_df["Tipo"] == selected_type]

    act_metrics = ["Distância (km)", "Pace (min/km)", "Duração (min)", "Calorias", "FC Média", "VO2 Máx"]
    selected_act_metrics = st.multiselect(
        "Escolha métricas da atividade:",
        act_metrics,
        default=["Distância (km)", "Pace (min/km)"]
    )

    if selected_act_metrics and not df_filtered.empty:
        fig_act = make_subplots(specs=[[{"secondary_y": True}]])
        colors = px.colors.qualitative.Plotly
        idx = 0

        y1 = selected_act_metrics[0]
        fig_act.add_trace(
            go.Scatter(
                x=df_filtered["Data"], y=pd.to_numeric(df_filtered[y1], errors="coerce"),
                mode="lines+markers", name=y1,
                line=dict(color=colors[idx])
            ),
            secondary_y=False,
        )
        fig_act.update_yaxes(title_text=y1, secondary_y=False)
        idx += 1

