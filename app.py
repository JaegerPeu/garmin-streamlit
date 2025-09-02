import streamlit as st
import pandas as pd
import gsheet
import datetime as dt
import gspread
from gspread_dataframe import get_as_dataframe
from google.oauth2.service_account import Credentials
from plotly.subplots import make_subplots
import plotly.graph_objects as go

# ================= CONFIGURAÇÃO ==================
GSHEET_ID = "1rwcDJA1yZ2hbsJx-HOW0dCduvWq0HI1WwY"  # confirme se este é o ID correto

service_account_info = st.secrets["gcp_service_account"]
scopes = ["https://www.googleapis.com/auth/spreadsheets"]
creds = Credentials.from_service_account_info(service_account_info, scopes=scopes)
client = gspread.authorize(creds)
# =================================================

# ---------- Função para carregar aba ----------
@st.cache_data(ttl=300)
def load_sheet(sheet_name: str) -> pd.DataFrame:
    """Carrega uma aba da planilha do Google Sheets em DataFrame (com cache)."""
    try:
        ws = client.open_by_key(GSHEET_ID).worksheet(sheet_name)
        df = get_as_dataframe(ws, evaluate_formulas=True, header=0)
        df = df.dropna(how="all")
        return df
    except Exception as e:
        st.error(f"❌ Erro ao carregar aba {sheet_name}: {e}")
        return pd.DataFrame()

# ---------- Função para calcular médias ----------
def calc_period_avg(df: pd.DataFrame, col: str, freq: str, date_col="Data"):
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
    else:  # TOTAL
        start = df[date_col].min().date()

    mask = df[date_col].dt.date >= start
    vals = df.loc[mask, col].dropna().astype(float)
    if vals.empty:
        return None
    return vals.mean()

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
st.write("Sincronize seus dados do Garmin com o Google Sheets e veja análises em tempo real.")

# Botão para atualizar planilha
if st.button("🔄 Atualizar dados do Garmin"):
    with st.spinner("Conectando ao Garmin e atualizando planilha..."):
        try:
            gsheet.main()
            st.cache_data.clear()  # limpa cache para forçar reload dos dados
            st.success("✅ Dados do Garmin atualizados com sucesso!")
        except Exception as e:
            st.error("❌ Erro ao atualizar os dados")
            st.exception(e)

# Carrega dados existentes
daily_df = load_sheet("DailyHUD")
acts_df  = load_sheet("Activities")

if daily_df.empty:
    st.warning("Nenhum dado encontrado na aba `DailyHUD`. Clique em **Atualizar dados** acima.")
    st.stop()

# Converter colunas numéricas
daily_df["Data"] = pd.to_datetime(daily_df["Data"], errors="coerce")
for col in daily_df.columns:
    try:
        daily_df[col] = pd.to_numeric(daily_df[col], errors="coerce")
    except Exception:
        pass

# ---------- GRÁFICO DE MÉTRICAS ----------
st.header("📈 Evolução das Métricas")

metric_options = [
    "Sono (h)", "Sono Deep (h)", "Sono REM (h)", "Sono Light (h)", 
    "Sono (score)", "Body Battery (start)", "Body Battery (end)", 
    "Body Battery (mín)", "Body Battery (máx)", "Body Battery (média)", 
    "Stress (média)", "Passos", "Calorias (total dia)", "Pace (min/km)"
]

selected_metrics = st.multiselect(
    "📊 Escolha até 5 métricas para visualizar:", 
    metric_options, 
    default=["Sono (h)", "Sono (score)"]
)

if selected_metrics:
    fig = make_subplots(specs=[[{"secondary_y": True}]])
    colors = px.colors.qualitative.Set2

    for i, metric in enumerate(selected_metrics):
        df_metric = daily_df.copy()
        df_metric[metric] = pd.to_numeric(df_metric[metric], errors="coerce")

        use_secondary = (i >= 1)  # primeira no eixo primário, demais no secundário
        fig.add_trace(
            go.Scatter(
                x=df_metric["Data"],
                y=df_metric[metric],
                mode="lines+markers",
                name=metric,
                line=dict(color=colors[i % len(colors)])
            ),
            secondary_y=use_secondary,
        )

        if i == 0:
            fig.update_yaxes(title_text=metric, secondary_y=False)
        elif i == 1:
            fig.update_yaxes(title_text=metric, secondary_y=True)

    fig.update_layout(
        title="Comparativo de Métricas Selecionadas",
        legend=dict(orientation="h", y=-0.2)
    )
    st.plotly_chart(fig, use_container_width=True)

# ---------- GRÁFICO DE CORRIDAS ----------
st.header("🏃‍♀️ Corridas")

if not acts_df.empty:
    acts_df["Data"] = pd.to_datetime(acts_df["Data"], errors="coerce")
    acts_df["Distância (km)"] = pd.to_numeric(acts_df["Distância (km)"], errors="coerce")
    acts_df["Calorias"] = pd.to_numeric(acts_df["Calorias"], errors="coerce")
    # Converter pace string para minutos (caso já esteja salvo como string)
    def parse_pace(val):
        if pd.isna(val) or val == "":
            return None
        if isinstance(val, (int, float)):
            return val
        try:
            m, s = val.split(":")
            return int(m) + int(s)/60
        except Exception:
            return None
    acts_df["Pace_num"] = acts_df["Pace (min/km)"].apply(parse_pace)

    run_metrics = ["Distância (km)", "Pace_num", "Calorias"]
    metric_labels = {
        "Distância (km)": "Distância (km)",
        "Pace_num": "Pace (min/km)",
        "Calorias": "Calorias"
    }
    selected_run_metrics = st.multiselect(
        "Escolha métricas de corrida:", 
        ["Distância (km)", "Pace (min/km)", "Calorias"], 
        default=["Distância (km)", "Pace (min/km)"]
    )

    if selected_run_metrics:
        # Troca "Pace (min/km)" pela versão numérica para plotar
        plot_metrics = []
        for m in selected_run_metrics:
            if m == "Pace (min/km)":
                plot_metrics.append("Pace_num")
            else:
                plot_metrics.append(m)

        fig_run = make_subplots(specs=[[{"secondary_y": True}]])
        colors = px.colors.qualitative.Pastel

        for i, metric in enumerate(plot_metrics):
            use_secondary = (i >= 1)
            fig_run.add_trace(
                go.Scatter(
                    x=acts_df[acts_df["Tipo"] == "running"]["Data"],
                    y=acts_df[acts_df["Tipo"] == "running"][metric],
                    mode="lines+markers",
                    name=metric_labels.get(metric, metric),
                    line=dict(color=colors[i % len(colors)])
                ),
                secondary_y=use_secondary,
            )

            # Ajusta label de cada eixo
            if i == 0:
                label = metric_labels.get(metric, metric)
                if "Pace" in label:
                    fig_run.update_yaxes(title_text=label, tickformat="%M:%S", secondary_y=False)
                else:
                    fig_run.update_yaxes(title_text=label, secondary_y=False)
            elif i == 1:
                label = metric_labels.get(metric, metric)
                if "Pace" in label:
                    fig_run.update_yaxes(title_text=label, tickformat="%M:%S", secondary_y=True)
                else:
                    fig_run.update_yaxes(title_text=label, secondary_y=True)

        fig_run.update_layout(title="Evolução das Corridas", legend=dict(orientation="h", y=-0.2))
        st.plotly_chart(fig_run, use_container_width=True)

    st.subheader("📋 Tabela de Atividades")
    # Formatar Pace e Sono no dataframe mostrado
    display_df = daily_df.copy()
    for label, col in [
        ("Sono (h)", "Sono (h)"),
        ("Sono Deep (h)", "Sono Deep (h)"),
        ("Sono REM (h)", "Sono REM (h)"),
        ("Sono Light (h)", "Sono Light (h)"),
        ("Sono Awake (min)", "Sono Awake (min)"),
        ("Sono (score)", "Sono (score)"),
        ("Body Battery (start)", "Body Battery (start)"),
        ("Body Battery (end)", "Body Battery (end)"),
        ("Body Battery (mín)", "Body Battery (mín)"),
        ("Body Battery (máx)", "Body Battery (máx)"),
        ("Body Battery (média)", "Body Battery (média)"),
        ("Stress (média)", "Stress (média)"),
        ("Corrida (km)", "Corrida (km)"),
        ("Pace (min/km)", "Pace (min/km)"),
    ]:
        if col in display_df.columns:
            display_df[col] = display_df[col].apply(lambda v: format_value(v, label))
    st.dataframe(display_df)
else:
    st.info("Nenhuma atividade de corrida encontrada ainda.")

# ---------- INSIGHTS ----------
st.header("🔍 Insights (WTD / MTD / QTD / YTD / Total)")

insights = {
    "Sono médio (h)": "Sono (h)",
    "Qualidade do sono (score)": "Sono (score)",
    "Distância corrida (km)": "Corrida (km)",
    "Pace médio (min/km)": "Pace (min/km)",
    "Stress médio": "Stress (média)",
    "Passos": "Passos",
    "Calorias (total dia)": "Calorias (total dia)",
}

periods = ["WTD", "MTD", "QTD", "YTD", "TOTAL"]
insight_data = []

for label, col in insights.items():
    row_data = {"Métrica": label}
    for p in periods:
        val = calc_period_avg(daily_df, col, p)
        if val is None:
            row_data[p] = "-"
        else:
            row_data[p] = format_value(val, label)
    insight_data.append(row_data)

insight_df = pd.DataFrame(insight_data).set_index("Métrica")
st.dataframe(insight_df)
