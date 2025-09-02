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

# Converter colunas numéricas
daily_df["Data"] = pd.to_datetime(daily_df["Data"], errors="coerce")

numeric_cols = [
    "Sono (h)", "Sono Deep (h)", "Sono REM (h)", "Sono Light (h)", 
    "Sono (score)", "Body Battery (start)", "Body Battery (end)", 
    "Body Battery (mín)", "Body Battery (máx)", "Body Battery (média)", 
    "Stress (média)", "Passos", "Calorias (total dia)", "Corrida (km)"
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
    "Passos", "Calorias (total dia)", "Corrida (km)", "Pace (min/km)"
]

selected_metrics = st.multiselect("Escolha as métricas para visualizar:", metrics, default=["Sono (h)", "Sono (score)"])

if selected_metrics:
    fig = make_subplots(specs=[[{"secondary_y": True}]])
    colors = px.colors.qualitative.Set2
    color_idx = 0

    # Primeiro eixo Y (esquerdo)
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
    color_idx += 1

    # Segundo eixo Y (direito, se existir)
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
        color_idx += 1

    # Métricas extras também vão no eixo secundário
    for m in selected_metrics[2:]:
        fig.add_trace(
            go.Scatter(
                x=daily_df["Data"],
                y=daily_df[m],
                mode="lines+markers",
                name=m,
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

    run_metrics = ["Distância (km)", "Pace (min/km)", "Calorias"]
    selected_run_metrics = st.multiselect("Escolha métricas de corrida:", run_metrics, default=["Distância (km)", "Pace (min/km)"])

    if selected_run_metrics:
        fig_run = make_subplots(specs=[[{"secondary_y": True}]])
        colors = px.colors.qualitative.Plotly
        if selected_run_metrics:
            y1 = selected_run_metrics[0]
            fig_run.add_trace(
                go.Scatter(
                    x=acts_df[acts_df["Tipo"] == "running"]["Data"],
                    y=acts_df[acts_df["Tipo"] == "running"][y1],
                    mode="lines+markers",
                    name=y1,
                    line=dict(color=colors[0])
                ),
                secondary_y=False,
            )
        if len(selected_run_metrics) > 1:
            y2 = selected_run_metrics[1]
            fig_run.add_trace(
                go.Scatter(
                    x=acts_df[acts_df["Tipo"] == "running"]["Data"],
                    y=acts_df[acts_df["Tipo"] == "running"][y2],
                    mode="lines+markers",
                    name=y2,
                    line=dict(color=colors[1])
                ),
                secondary_y=True,
            )
            fig_run.update_yaxes(title_text=y1, secondary_y=False)
            fig_run.update_yaxes(title_text=y2, secondary_y=True)

        fig_run.update_layout(title="Métricas de Corrida", legend=dict(orientation="h", y=-0.2))
        st.plotly_chart(fig_run, use_container_width=True)

    st.subheader("📋 Tabela de Atividades")
    st.dataframe(acts_df)
else:
    st.info("Nenhuma atividade de corrida encontrada ainda.")

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

insight_data = []
for label, col in insights.items():
    row_data = {"Métrica": label}
    for period in ["WTD", "MTD", "QTD", "YTD", "TOTAL"]:
        val = calc_period_avg(daily_df, col, period)
        if val is None:
            row_data[period] = "-"
        else:
            if "Pace" in label:
                minutos = int(val)
                segundos = int(round((val - minutos) * 60))
                row_data[period] = f"{minutos}:{segundos:02d}"
            elif "Passos" in label:
                row_data[period] = f"{val:,.0f}"
            else:
                row_data[period] = f"{val:.2f}"
    insight_data.append(row_data)

insight_df = pd.DataFrame(insight_data).set_index("Métrica")
st.dataframe(insight_df)

# ---------- CORRELAÇÕES ----------
st.header("📊 Explorar Correlações")

corr_options = {
    "Sono (h) x Sono (score)": ("Sono (h)", "Sono (score)"),
    "Sono (h) x Stress (média)": ("Sono (h)", "Stress (média)"),
    "Stress (média) x Sono (score)": ("Stress (média)", "Sono (score)"),
    "Dias com corrida (km>0) x Sono (score)": ("Corrida (km)", "Sono (score)"),
    "Calorias (total dia) x Sono (h)": ("Calorias (total dia)", "Sono (h)"),
    "Distância corrida (km) x Stress (média)": ("Corrida (km)", "Stress (média)"),
}

choice = st.selectbox("Escolha a correlação:", list(corr_options.keys()))

xcol, ycol = corr_options[choice]
df_corr = daily_df.copy()

df_corr[xcol] = pd.to_numeric(df_corr[xcol], errors="coerce")
df_corr[ycol] = pd.to_numeric(df_corr[ycol], errors="coerce")

# Caso especial: "dias com corrida x sono"
if "Dias com corrida" in choice:
    df_corr["Dias com corrida"] = df_corr["Corrida (km)"].apply(lambda x: 1 if pd.notna(x) and float(x) > 0 else 0)

fig_corr = px.scatter(
    df_corr,
    x=xcol,
    y=ycol,
    trendline="ols",
    title=f"Correlação: {choice}"
)
st.plotly_chart(fig_corr, use_container_width=True)

# ---------- TABELA FINAL ----------
st.header("📑 DailyHUD (dados brutos)")
st.dataframe(daily_df)


