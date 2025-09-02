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
from typing import Optional
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

def calc_period(
    df: pd.DataFrame,
    col: str,
    freq: str,
    date_col="Data",
    only_positive: bool = False,
    mode: str = "mean",
    filter_col: Optional[str] = None,
) -> Optional[float]:
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
    subset = temp.loc[mask]

    if filter_col and filter_col in subset.columns:
        subset[filter_col] = pd.to_numeric(subset[filter_col], errors="coerce")
        subset = subset[subset[filter_col] > 0]

    vals = pd.to_numeric(subset[col], errors="coerce").dropna()

    if only_positive:
        vals = vals[vals > 0]

    if vals.empty:
        return None

    return float(vals.sum() if mode == "sum" else vals.mean())

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

def format_metric(value: Optional[float], fmt: str) -> str:
    """Formata métricas para a tabela de insights."""
    if value is None:
        return "-"
    if fmt == "time":
        return format_hours(value)
    if fmt == "pace":
        return format_pace(value)
    if fmt == "int":
        return f"{value:,.0f}"
    return f"{value:.2f}"

def mmss_to_minutes(x) -> Optional[float]:
    """Converte 'mm:ss' (ou 'h:mm:ss') para minutos decimais. Aceita número já decimal."""
    if pd.isna(x) or x == "":
        return None
    try:
        if isinstance(x, (int, float)):
            return float(x)
        s = str(x).strip().replace(",", ".")
        parts = s.split(":")
        if len(parts) == 2:
            m = float(parts[0]); sec = float(parts[1])
            return m + sec/60.0
        if len(parts) == 3:
            h = float(parts[0]); m = float(parts[1]); sec = float(parts[2])
            return h*60.0 + m + sec/60.0
        return float(s)
    except Exception:
        return None

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

# Converter colunas numéricas (DailyHUD)
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

# 🔧 ALTERAÇÃO: garantir Pace diário em número (para gráficos/insights)
if "Pace (min/km)" in daily_df.columns:
    daily_df["PaceNum"] = daily_df["Pace (min/km)"].apply(mmss_to_minutes)

# ---------- GRÁFICO MULTIMÉTRICAS (DailyHUD) ----------
st.header("📊 Evolução das Métricas (Daily)")

metrics = numeric_cols
selected_metrics = st.multiselect(
    "📊 Escolha as métricas para visualizar:",
    metrics,
    default=["Sono (h)", "Sono (score)"]
)

def series_for_metric(df: pd.DataFrame, colname: str) -> pd.Series:
    """Se a métrica for Pace (min/km), usar PaceNum (decimal). Senão, usa a própria coluna."""
    if colname == "Pace (min/km)" and "PaceNum" in df.columns:
        return df["PaceNum"]
    return df[colname]

if selected_metrics:
    fig = make_subplots(specs=[[{"secondary_y": True}]])
    colors = px.colors.qualitative.Set2
    color_idx = 0

    # Primeiro eixo Y
    y1 = selected_metrics[0]
    fig.add_trace(
        go.Scatter(
            x=daily_df["Data"], y=series_for_metric(daily_df, y1),
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
                x=daily_df["Data"], y=series_for_metric(daily_df, y2),
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
                x=daily_df["Data"], y=series_for_metric(daily_df, m),
                mode="lines+markers", name=m,
                line=dict(color=colors[color_idx % len(colors)]),
                yaxis="y2" if len(selected_metrics) > 1 else "y"
            )
        )
        color_idx += 1

    fig.update_layout(
        title="Comparativo de Métricas Selecionadas (DailyHUD)",
        legend=dict(orientation="h", y=-0.2),
        margin=dict(l=40, r=40, t=40, b=40),
    )
    st.plotly_chart(fig, use_container_width=True)

# ---------- ATIVIDADES (Activities) ----------
st.header("🏃‍♀️ Atividades (agregado por dia)")

acts_daily = pd.DataFrame()
if not acts_df.empty:
    acts_df["Data"] = pd.to_datetime(acts_df["Data"], errors="coerce")

    # garantir numérico nas colunas usadas no agregado
    for col in ["Distância (km)", "Duração (min)", "Calorias", "FC Média", "VO2 Máx"]:
        if col in acts_df.columns:
            acts_df[col] = pd.to_numeric(acts_df[col], errors="coerce")

    # AGRUPA por dia + tipo
    acts_work = acts_df.dropna(subset=["Data", "Tipo"]).copy()
    acts_work["DataDay"] = acts_work["Data"].dt.normalize()

    def _agg(g: pd.DataFrame) -> pd.Series:
        dist_sum = g["Distância (km)"].fillna(0).sum()
        dur_sum  = g["Duração (min)"].fillna(0).sum()
        cal_sum  = g["Calorias"].sum(skipna=True)
        fc_mean  = g["FC Média"].mean(skipna=True)
        vo2_mean = g["VO2 Máx"].mean(skipna=True)

        # pace diário correto = duração total (min) / distância total (km)
        pace_num_daily = (dur_sum / dist_sum) if (dist_sum and dist_sum > 0) else None

        return pd.Series({
            "Distância (km)": dist_sum,
            "Duração (min)": dur_sum,
            "Calorias": cal_sum,
            "FC Média": fc_mean,
            "VO2 Máx": vo2_mean,
            "PaceNumDaily": pace_num_daily
        })

    acts_daily = (
        acts_work
        .groupby(["DataDay", "Tipo"], as_index=False)
        .apply(_agg)
        .reset_index(drop=True)
        .rename(columns={"DataDay": "Data"})
    )

    # pace formatado só para a tabela (o gráfico usa PaceNumDaily)
    acts_daily["Pace (min/km)"] = acts_daily["PaceNumDaily"].apply(format_pace)

    # Filtro de tipo
    activity_types = acts_daily["Tipo"].dropna().unique().tolist()
    if not activity_types:
        st.info("Não há atividades agregadas para exibir.")
    else:
        selected_type = st.selectbox("Escolha o tipo de atividade:", activity_types, index=0)
        df_filtered = acts_daily[acts_daily["Tipo"] == selected_type].copy()

        act_metrics = ["Distância (km)", "Pace (min/km)", "Duração (min)", "Calorias", "FC Média", "VO2 Máx"]
        selected_act_metrics = st.multiselect(
            "Escolha métricas da atividade:",
            act_metrics,
            default=["Distância (km)", "Pace (min/km)"]
        )

        def series_for_act_daily(df: pd.DataFrame, colname: str) -> pd.Series:
            # no gráfico, se for Pace (min/km), usamos a série numérica correta (minutos por km)
            if colname == "Pace (min/km)":
                return pd.to_numeric(df["PaceNumDaily"], errors="coerce")
            return pd.to_numeric(df[colname], errors="coerce")

        if selected_act_metrics and not df_filtered.empty:
            fig_act = make_subplots(specs=[[{"secondary_y": True}]])
            colors = px.colors.qualitative.Plotly
            idx = 0

            # 1º eixo
            y1 = selected_act_metrics[0]
            fig_act.add_trace(
                go.Scatter(
                    x=df_filtered["Data"], y=series_for_act_daily(df_filtered, y1),
                    mode="lines+markers", name=y1,
                    line=dict(color=colors[idx])
                ),
                secondary_y=False,
            )
            fig_act.update_yaxes(title_text=y1, secondary_y=False)
            idx += 1

            # 2º eixo
            if len(selected_act_metrics) > 1:
                y2 = selected_act_metrics[1]
                fig_act.add_trace(
                    go.Scatter(
                        x=df_filtered["Data"], y=series_for_act_daily(df_filtered, y2),
                        mode="lines+markers", name=y2,
                        line=dict(color=colors[idx])
                    ),
                    secondary_y=True,
                )
                fig_act.update_yaxes(title_text=y2, secondary_y=True)
                idx += 1

            # extras -> mesmo eixo do 2º
            for m in selected_act_metrics[2:]:
                fig_act.add_trace(
                    go.Scatter(
                        x=df_filtered["Data"], y=series_for_act_daily(df_filtered, m),
                        mode="lines+markers", name=m,
                        line=dict(color=colors[idx % len(colors)]),
                        yaxis="y2" if len(selected_act_metrics) > 1 else "y"
                    )
                )
                idx += 1

            fig_act.update_layout(
                title=f"Evolução diária agregada — {selected_type}",
                legend=dict(orientation="h", y=-0.2)
            )
            st.plotly_chart(fig_act, use_container_width=True)

        st.subheader("📋 Tabela de Atividades (agregado por dia)")
        st.dataframe(df_filtered)

        with st.expander("Ver tabela de atividades brutas (todas as sessões)"):
            st.dataframe(acts_df)
else:
    st.info("Nenhuma atividade encontrada ainda.")



# ---------- INSIGHTS ----------
st.header("🔍 Insights (WTD / MTD / QTD / YTD / Total)")

periods = ["WTD", "MTD", "QTD", "YTD", "TOTAL"]

# usamos colunas auxiliares: SonoHorasNum (para horas) e PaceNum (para cálculo de pace)
if "Sono (h)" in daily_df.columns and "SonoHorasNum" not in daily_df.columns:
    daily_df["SonoHorasNum"] = pd.to_numeric(daily_df["Sono (h)"], errors="coerce")

insights = {
    "Sono (h) — Média":              {"col": "SonoHorasNum",         "mode": "mean", "fmt": "time"},
    "Sono Deep (h) — Média":         {"col": "Sono Deep (h)",        "mode": "mean", "fmt": "time"},
    "Sono REM (h) — Média":          {"col": "Sono REM (h)",         "mode": "mean", "fmt": "time"},
    "Sono Light (h) — Média":        {"col": "Sono Light (h)",       "mode": "mean", "fmt": "time"},
    "Qualidade do sono (score)":     {"col": "Sono (score)",         "mode": "mean", "fmt": "num"},

    # Corrida (usar apenas dias com corrida > 0)
    "Distância corrida (km) — Soma": {"col": "Corrida (km)",         "mode": "sum",  "fmt": "num",  "only_positive": True, "filter_col": "Corrida (km)"},
    "Distância corrida (km) — Média":{"col": "Corrida (km)",         "mode": "mean", "fmt": "num",  "only_positive": True, "filter_col": "Corrida (km)"},
    "Pace médio (min/km)":           {"col": "PaceNum",              "mode": "mean", "fmt": "pace", "only_positive": True, "filter_col": "Corrida (km)"},

    "Passos — Média":                {"col": "Passos",               "mode": "mean", "fmt": "int"},
    "Calorias (total dia) — Média":  {"col": "Calorias (total dia)", "mode": "mean", "fmt": "num"},
    "Body Battery (média)":          {"col": "Body Battery (máx)", "mode": "mean", "fmt": "num"},
    "Stress médio":                  {"col": "Stress (média)",       "mode": "mean", "fmt": "num"},

    # Breathwork: soma e média (considerando >0)
    #"Breathwork (min) — Soma":       {"col": "Breathwork (min)",     "mode": "sum",  "fmt": "int", "only_positive": True},
    "Breathwork (min) — Média":      {"col": "Breathwork (min)",     "mode": "mean", "fmt": "int", "only_positive": True},
}

insight_rows = []
for label, cfg in insights.items():
    row = {"Métrica": label}
    for p in periods:
        val = calc_period(
            daily_df,
            col=cfg["col"],
            freq=p,
            only_positive=cfg.get("only_positive", False),
            mode=cfg.get("mode", "mean"),
            filter_col=cfg.get("filter_col")
        )
        row[p] = format_metric(val, cfg.get("fmt", "num"))
    insight_rows.append(row)

insight_df = pd.DataFrame(insight_rows).set_index("Métrica")
st.dataframe(insight_df)

# ---------- MATRIZ DE CORRELAÇÃO ----------
st.header("📊 Matriz de Correlação")

corr_metrics = st.multiselect(
    "Escolha métricas para calcular correlação:",
    ["Sono (h)", "Sono (score)", "Stress (média)", "Corrida (km)", "Pace (min/km)", "Breathwork (min)", "Passos", "Calorias (total dia)", "Body Battery (média)"],
    default=["Sono (h)", "Sono (score)", "Stress (média)", "Corrida (km)", "Pace (min/km)", "Breathwork (min)"]
)

if len(corr_metrics) >= 2:
    df_corr = daily_df.copy()
    # usar série numérica para Pace
    if "Pace (min/km)" in corr_metrics and "PaceNum" in df_corr.columns:
        df_corr["Pace (min/km)"] = df_corr["PaceNum"]
    df_corr = df_corr[corr_metrics].apply(pd.to_numeric, errors="coerce").dropna()
    if not df_corr.empty:
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
        st.info("Não há dados suficientes para calcular correlação com as métricas escolhidas.")
else:
    st.info("Selecione pelo menos 2 métricas para ver correlações.")

# ---------- TABELA FINAL ----------
#st.header("📑 DailyHUD (dados brutos)")

#df_display = daily_df.copy()
#if "Sono (h)" in df_display.columns:
 #   df_display["Sono (h)"] = df_display["Sono (h)"].apply(format_hours)
  #  if "Sono Deep (h)" in df_display.columns:
       # df_display["Sono Deep (h)"] = df_display["Sono Deep (h)"].apply(format_hours)
   # if "Sono REM (h)" in df_display.columns:
        #df_display["Sono REM (h)"] = df_display["Sono REM (h)"].apply(format_hours)
    #if "Sono Light (h)" in df_display.columns:
     #   df_display["Sono Light (h)"] = df_display["Sono Light (h)"].apply(format_hours)

# exibição do pace em mm:ss na tabela final
#if "PaceNum" in df_display.columns:
#    df_display["Pace (min/km)"] = df_display["PaceNum"].apply(format_pace)

#st.dataframe(df_display)
