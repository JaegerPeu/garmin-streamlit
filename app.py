# app.py
# =====================================================
# Dashboard Streamlit para visualização dos dados Garmin
# + HUD estilo RPG (envio para Notion via Code Block)
# Dados são carregados do Google Sheets (já atualizado
# pelo script gsheet.main()).
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
from typing import Optional, List, Tuple
import requests
import json
import gsheet

# ================= CONFIGURAÇÃO ==================
GSHEET_ID = "1rwcDJA1yZ2hbsJx-HOW0dCduvWqV0z7f9Iio0HI1WwY"  # ID da planilha

service_account_info = st.secrets["gcp_service_account"]
scopes = ["https://www.googleapis.com/auth/spreadsheets"]
creds = Credentials.from_service_account_info(service_account_info, scopes=scopes)
client = gspread.authorize(creds)

# Notion (opcional, para enviar HUD)
NOTION_TOKEN = st.secrets["notion"]["token"]
NOTION_BLOCK_ID = st.secrets["notion"]["block_id"]
NOTION_COUNTER_DB_ID = st.secrets["notion"]["counter_db_id"]
NOTION_VERSION = "2022-06-28"
# =================================================


# ---------- Helpers Notion ----------
def _notion_headers():
    return {
        "Authorization": f"Bearer {NOTION_TOKEN}",
        "Content-Type": "application/json",
        "Notion-Version": NOTION_VERSION,
    }

def push_hud_to_notion_codeblock(hud_text: str, block_id: str) -> Tuple[bool, str]:
    """
    Atualiza um code block existente no Notion (PATCH /v1/blocks/{block_id})
    substituindo o conteúdo pelo hud_text.
    """
    try:
        payload = {
            "code": {
                "rich_text": [
                    {"type": "text", "text": {"content": hud_text}}
                ],
                "language": "plain text"
            }
        }
        url = f"https://api.notion.com/v1/blocks/{block_id}"
        r = requests.patch(url, headers=_notion_headers(), data=json.dumps(payload), timeout=15)
        if r.status_code == 200:
            return True, "Atualizado!"
    except Exception as e:
        return False, str(e)



# ---------- Utils básicos ----------
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


def get_today_turtle_objective() -> str:
    """Lê a aba 'Turtle' e retorna o 'Objetivo' do dia atual (colunas: Data/Objetivo, tolerando variações)."""
    try:
        import unicodedata
        import pandas as pd

        def _norm(s: str) -> str:
            s = str(s)
            s = "".join(c for c in unicodedata.normalize("NFD", s) if unicodedata.category(c) != "Mn")
            return s.strip().lower()

        # 1) Carrega
        turtle = load_sheet("Turtle")
        if turtle is None or turtle.empty:
            return "-"

        # 2) Mapeia colunas por nome normalizado (ignora acentos/maiúsculas)
        name_map = {_norm(c): c for c in turtle.columns}

        date_keys = ["data", "date", "dia"]
        obj_keys  = ["objetivo", "objective", "goal", "meta"]

        date_col = next((name_map[k] for k in date_keys if k in name_map), None)
        obj_col  = next((name_map[k] for k in obj_keys if k in name_map), None)
        if not date_col or not obj_col:
            return "-"

        # 3) Converte datas (texto, datetime, ou serial Excel)
        s = turtle[date_col]
        if pd.api.types.is_numeric_dtype(s):
            # Excel serial (origem 1899-12-30)
            dates = pd.to_datetime(s, unit="D", origin="1899-12-30", errors="coerce")
        else:
            # Strings/datetime; Brasil costuma ser dia/mês/ano
            dates = pd.to_datetime(s, errors="coerce", dayfirst=True)

        # Ajuste de timezone para não errar a virada de dia
        try:
            from zoneinfo import ZoneInfo
            tz = ZoneInfo("America/Sao_Paulo")
            today = dt.datetime.now(tz).date()
            if getattr(dates.dt, "tz", None) is not None:
                dates = dates.dt.tz_convert(tz)
        except Exception:
            # Fallback se ZoneInfo não existir
            today = dt.date.today()

        turtle["_date"] = dates.dt.date

        # 4) Filtra linha de hoje; se não houver, pega a última <= hoje
        valid = turtle.dropna(subset=["_date"])
        row = valid.loc[valid["_date"] == today]
        if row.empty:
            row = valid.loc[valid["_date"] <= today].sort_values("_date")
            if row.empty:
                return "-"

        objetivo_val = str(row.iloc[-1][obj_col]).strip()
        return objetivo_val if objetivo_val and objetivo_val.lower() not in {"nan", "none"} else "-"

    except Exception:
        return "-"


def calc_period(
    df: pd.DataFrame,
    col: str,
    freq: str,
    date_col="Data",
    only_positive: bool = False,
    mode: str = "mean",
    filter_col: Optional[str] = None,
) -> Optional[float]:
    """Calcula métrica (média ou soma) em um período (WTD, MTD, QTD, YTD, TOTAL)."""
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
    if pd.isna(value) or value == "":
        return "-"
    try:
        horas = int(float(value))
        minutos = int(round((float(value) - horas) * 60))
        return f"{horas:02d}:{minutos:02d}"
    except Exception:
        return "-"


def format_pace(value):
    if pd.isna(value) or value == "" or float(value) == 0:
        return "-"
    try:
        minutos = int(float(value))
        segundos = int(round((float(value) - minutos) * 60))
        return f"{minutos}:{segundos:02d}"
    except Exception:
        return "-"

def pace_series_to_hover(series: pd.Series):
    return [format_pace(v) if pd.notna(v) and v not in ("", 0) else None for v in series]

def format_metric(value: Optional[float], fmt: str) -> str:
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
st.set_page_config(page_title="📊 Dashboard Garmin / HUD RPG", layout="wide")

st.title("🏃‍♂️ Dashboard de Atividades Garmin + 🎮 HUD RPG")

# Botão para atualizar planilha (coleta Garmin -> Google Sheets)
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

# Pace diário em número (para gráficos/insights)
if "Pace (min/km)" in daily_df.columns:
    daily_df["PaceNum"] = daily_df["Pace (min/km)"].apply(mmss_to_minutes)

# ---------- ATIVIDADES (agregado por dia / tipo) ----------
acts_daily = pd.DataFrame()
if not acts_df.empty:
    acts_df["Data"] = pd.to_datetime(acts_df["Data"], errors="coerce")
    for col in ["Distância (km)", "Duração (min)", "Calorias", "FC Média", "VO2 Máx"]:
        if col in acts_df.columns:
            acts_df[col] = pd.to_numeric(acts_df[col], errors="coerce")

    acts_work = acts_df.dropna(subset=["Data", "Tipo"]).copy()
    acts_work["DataDay"] = acts_work["Data"].dt.normalize()

    def _agg(g: pd.DataFrame) -> pd.Series:
        dist_sum = g["Distância (km)"].fillna(0).sum()
        dur_sum  = g["Duração (min)"].fillna(0).sum()
        cal_sum  = g["Calorias"].sum(skipna=True)
        fc_mean  = g["FC Média"].mean(skipna=True)
        vo2_mean = g["VO2 Máx"].mean(skipna=True)
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
    acts_daily["Pace (min/km)"] = acts_daily["PaceNumDaily"].apply(format_pace)


# =========================================================
# ================  🎮 HUD — Status de Hoje  ==============
# =========================================================
st.header("🎮 HUD — Status de Hoje")

today = dt.date.today()
today_str = today.strftime("%A, %d/%m/%Y")

# Último dia registrado no DailyHUD
last_day_row = daily_df.sort_values("Data").dropna(subset=["Data"]).iloc[-1]  # mais recente

# Objetivo do dia (Turtle)
turtle_obj = get_today_turtle_objective()

# Tipo padrão do HUD (corrida)
hud_type = "running"
if not acts_daily.empty:
    types_avail = acts_daily["Tipo"].dropna().unique().tolist()
    if hud_type not in types_avail and types_avail:
        hud_type = types_avail[0]
else:
    types_avail = []

# 7 dias atividade (por tipo)
def last_n_days_mask(df, n=7):
    start = (pd.Timestamp(today) - pd.Timedelta(days=n-1)).normalize()
    return df["Data"] >= start

sessions_7d = 0
km_7d = 0.0
pace_7d = "-"
if not acts_daily.empty and hud_type in types_avail:
    df7 = acts_daily[(acts_daily["Tipo"] == hud_type) & last_n_days_mask(acts_daily, 7)]
    sessions_7d = len(df7)  # dias com atividade
    km_7d = df7["Distância (km)"].sum()
    pace_7d = format_pace(df7["PaceNumDaily"].mean()) if not df7["PaceNumDaily"].dropna().empty else "-"

passos_7d = "-"
if "Passos" in daily_df.columns:
    d7 = daily_df[last_n_days_mask(daily_df, 7)]
    passos_7d = f"{d7['Passos'].mean():,.0f}" if not d7.empty else "-"

# Energia e sono do dia mais recente
energia = last_day_row.get("Body Battery (máx)", None)
if pd.isna(energia):
    energia = last_day_row.get("Body Battery (end)", None)
energia_txt = f"{int(energia)}%" if energia is not None and not pd.isna(energia) else "-"

def energy_bar(x):
    if x is None or pd.isna(x):
        return "[..........]"
    x = int(x)
    filled = max(0, min(10, round(x/10)))
    return "[" + "#"*filled + "."*(10-filled) + "]"

sono_h = last_day_row.get("Sono (h)", None)
sono_txt = f"{float(sono_h):.1f}h" if sono_h is not None and not pd.isna(sono_h) else "-"

sono_score = last_day_row.get("Sono (score)", None)
score_txt = f"{int(sono_score)}" if sono_score is not None and not pd.isna(sono_score) else "-"

breath_today = last_day_row.get("Breathwork (min)", None)
breath_today_txt = f"{int(breath_today)}" if breath_today is not None and not pd.isna(breath_today) else "0"

breath_7d = 0
if "Breathwork (min)" in daily_df.columns:
    d7 = daily_df[last_n_days_mask(daily_df, 7)]
    breath_7d = int(round(d7["Breathwork (min)"].fillna(0).mean())) if not d7.empty else 0

cal_d1 = last_day_row.get("Calorias (total dia)", None)
cal_txt = f"{int(cal_d1):d}" if cal_d1 is not None and not pd.isna(cal_d1) else "-"

steps_d1 = last_day_row.get("Passos", None)
steps_txt = f"{int(steps_d1):d}" if steps_d1 is not None and not pd.isna(steps_d1) else "-"

# ----- HUD format (monoespaçado) -----
WIDTH = 66
def line(text=""):
    return f"║ {text.ljust(WIDTH-2)} ║"

def title_box(t):
    bar = "═"*WIDTH
    return f"╔{bar}╗\n{line(t)}\n╠{bar}╣"

def end_box():
    return f"╚{'═'*WIDTH}╝"

hud_lines = []
# Cabeçalho
hud_lines.append(title_box(f"HUD — {today_str}"))
hud_lines.append(line(f"Player: Pedro Duarte"))
hud_lines.append(line(f"Energia: {energy_bar(energia)} {energia_txt}"))
hud_lines.append(line(f"Sono: {sono_txt} | Qualidade: {score_txt}"))
hud_lines.append(end_box())

# Mente
hud_lines.append(title_box("Mente"))
hud_lines.append(line(f"Meditação hoje: {breath_today_txt:>3} min  |  Média 7d: {breath_7d:>3} min"))
hud_lines.append(end_box())

# Atividade Física
hud_lines.append(title_box("Atividade Física (últimos 7 dias)"))
hud_lines.append(line(f"Tipo: {hud_type}"))
hud_lines.append(line(f"Sessões: {sessions_7d:>2}  |  Distância: {km_7d:>6.2f} km  |  Pace médio: {pace_7d}"))
#colocar algum tipo de objetivo
hud_lines.append(end_box())

# Trabalho / Trade
turtle_line = turtle_obj if turtle_obj != "-" else "—"
hud_lines.append(title_box("Trabalho / Trade"))
hud_lines.append(line(f"Objetivo de hoje: {turtle_line[:WIDTH-22]}"))
hud_lines.append(end_box())

hud_card = "\n".join(hud_lines)

# Render monoespaçado (mantém simetria)
st.code(hud_card, language="")

# --- Botão para enviar pro Notion ---
st.subheader("Exportar HUD para o Notion")
blk_id_default = NOTION_BLOCK_ID or ""
blk_id_input = st.text_input("Code Block ID do Notion (se vazio, uso o de secrets):", value=blk_id_default)

if st.button("🚀 Enviar HUD ao Notion"):
    if not NOTION_TOKEN:
        st.error("Defina `notion_token` em `secrets.toml` para enviar ao Notion.")
    else:
        target_block = blk_id_input.strip() or NOTION_BLOCK_ID
        if not target_block:
            st.error("Forneça um Code Block ID do Notion (ou configure `notion_block_id` nos secrets).")
        else:
            ok, msg = push_hud_to_notion_codeblock(hud_card, target_block)
            st.success("HUD enviado ao Notion! ✅") if ok else st.error(f"Falhou ao enviar: {msg}")


# =========================================================
# ==========  GRÁFICO MULTIMÉTRICAS (DailyHUD)  ===========
# =========================================================
st.header("📊 Evolução das Métricas (Daily)")

metrics = numeric_cols
selected_metrics = st.multiselect(
    "📊 Escolha as métricas para visualizar:",
    metrics,
    default=["Sono (h)", "Sono (score)"]
)

def series_for_metric(df: pd.DataFrame, colname: str) -> pd.Series:
    if colname == "Pace (min/km)" and "PaceNum" in df.columns:
        return df["PaceNum"]
    return df[colname]

if selected_metrics:
    fig = make_subplots(specs=[[{"secondary_y": True}]])
    colors = px.colors.qualitative.Set2
    color_idx = 0

    # Primeiro eixo Y
    y1 = selected_metrics[0]
    y1_series = series_for_metric(daily_df, y1)
    trace_kwargs = {}
    if y1 == "Pace (min/km)":
        trace_kwargs["customdata"]    = pace_series_to_hover(y1_series)
        trace_kwargs["hovertemplate"] = "%{x|%Y-%m-%d}<br>" + y1 + ": %{customdata}<extra></extra>"

    fig.add_trace(
        go.Scatter(
            x=daily_df["Data"], y=y1_series,
            mode="lines+markers", name=y1,
            line=dict(color=colors[color_idx]),
            **trace_kwargs
        ),
        secondary_y=False,
    )
    fig.update_yaxes(title_text=y1, secondary_y=False)
    color_idx += 1

    # Segundo eixo Y
    if len(selected_metrics) > 1:
        y2 = selected_metrics[1]
        y2_series = series_for_metric(daily_df, y2)
        trace_kwargs = {}
        if y2 == "Pace (min/km)":
            trace_kwargs["customdata"]    = pace_series_to_hover(y2_series)
            trace_kwargs["hovertemplate"] = "%{x|%Y-%m-%d}<br>" + y2 + ": %{customdata}<extra></extra>"

        fig.add_trace(
            go.Scatter(
                x=daily_df["Data"], y=y2_series,
                mode="lines+markers", name=y2,
                line=dict(color=colors[color_idx]),
                **trace_kwargs
            ),
            secondary_y=True,
        )
        fig.update_yaxes(title_text=y2, secondary_y=True)
        color_idx += 1

    # Extras
    for m in selected_metrics[2:]:
        m_series = series_for_metric(daily_df, m)
        trace_kwargs = {}
        if m == "Pace (min/km)":
            trace_kwargs["customdata"]    = pace_series_to_hover(m_series)
            trace_kwargs["hovertemplate"] = "%{x|%Y-%m-%d}<br>" + m + ": %{customdata}<extra></extra>"

        fig.add_trace(
            go.Scatter(
                x=daily_df["Data"], y=m_series,
                mode="lines+markers", name=m,
                line=dict(color=colors[color_idx % len(colors)]),
                yaxis="y2" if len(selected_metrics) > 1 else "y",
                **trace_kwargs
            )
        )
        color_idx += 1

    fig.update_layout(
        title="Comparativo de Métricas Selecionadas (DailyHUD)",
        legend=dict(orientation="h", y=-0.2),
        margin=dict(l=40, r=40, t=40, b=40),
    )
    st.plotly_chart(fig, use_container_width=True)


# =========================================================
# ============  ATIVIDADES (agregado por dia)  ============
# =========================================================
st.header("🏃‍♀️ Atividades (agregado por dia)")

if not acts_daily.empty:
    activity_types = acts_daily["Tipo"].dropna().unique().tolist()
    selected_type_plot = st.selectbox("Escolha o tipo de atividade:", activity_types, index=0)
    df_filtered = acts_daily[acts_daily["Tipo"] == selected_type_plot].copy()

    act_metrics = ["Distância (km)", "Pace (min/km)", "Duração (min)", "Calorias", "FC Média", "VO2 Máx"]
    selected_act_metrics = st.multiselect(
        "Escolha métricas da atividade:",
        act_metrics,
        default=["Distância (km)", "Pace (min/km)"]
    )

    def series_for_act_daily(df: pd.DataFrame, colname: str) -> pd.Series:
        if colname == "Pace (min/km)":
            return pd.to_numeric(df["PaceNumDaily"], errors="coerce")
        return pd.to_numeric(df[colname], errors="coerce")

    if selected_act_metrics and not df_filtered.empty:
        fig_act = make_subplots(specs=[[{"secondary_y": True}]])
        colors = px.colors.qualitative.Plotly
        idx = 0

        # 1º eixo
        y1 = selected_act_metrics[0]
        y1_series = series_for_act_daily(df_filtered, y1)
        trace_kwargs = {}
        if y1 == "Pace (min/km)":
            trace_kwargs["customdata"]    = pace_series_to_hover(df_filtered["PaceNumDaily"])
            trace_kwargs["hovertemplate"] = "%{x|%Y-%m-%d}<br>" + y1 + ": %{customdata}<extra></extra>"

        fig_act.add_trace(
            go.Scatter(
                x=df_filtered["Data"], y=y1_series,
                mode="lines+markers", name=y1,
                line=dict(color=colors[idx]),
                **trace_kwargs
            ),
            secondary_y=False,
        )
        fig_act.update_yaxes(title_text=y1, secondary_y=False)
        idx += 1

        # 2º eixo
        if len(selected_act_metrics) > 1:
            y2 = selected_act_metrics[1]
            y2_series = series_for_act_daily(df_filtered, y2)
            trace_kwargs = {}
            if y2 == "Pace (min/km)":
                trace_kwargs["customdata"]    = pace_series_to_hover(df_filtered["PaceNumDaily"])
                trace_kwargs["hovertemplate"] = "%{x|%Y-%m-%d}<br>" + y2 + ": %{customdata}<extra></extra>"

            fig_act.add_trace(
                go.Scatter(
                    x=df_filtered["Data"], y=y2_series,
                    mode="lines+markers", name=y2,
                    line=dict(color=colors[idx]),
                    **trace_kwargs
                ),
                secondary_y=True,
            )
            fig_act.update_yaxes(title_text=y2, secondary_y=True)
            idx += 1

        # extras
        for m in selected_act_metrics[2:]:
            m_series = series_for_act_daily(df_filtered, m)
            trace_kwargs = {}
            if m == "Pace (min/km)":
                trace_kwargs["customdata"]    = pace_series_to_hover(df_filtered["PaceNumDaily"])
                trace_kwargs["hovertemplate"] = "%{x|%Y-%m-%d}<br>" + m + ": %{customdata}<extra></extra>"

            fig_act.add_trace(
                go.Scatter(
                    x=df_filtered["Data"], y=m_series,
                    mode="lines+markers", name=m,
                    line=dict(color=colors[idx % len(colors)]),
                    yaxis="y2" if len(selected_act_metrics) > 1 else "y",
                    **trace_kwargs
                )
            )
            idx += 1

        fig_act.update_layout(
            title=f"Evolução diária agregada — {selected_type_plot}",
            legend=dict(orientation="h", y=-0.2)
        )
        st.plotly_chart(fig_act, use_container_width=True)

    with st.expander("📋 Tabela de Atividades (agregado por dia)"):
        st.dataframe(df_filtered)

    with st.expander("Ver tabela de atividades brutas (todas as sessões)"):
        st.dataframe(acts_df)
else:
    st.info("Nenhuma atividade encontrada ainda.")


# =========================================================
# ==================  INSIGHTS & CORRELAÇÃO  ==============
# =========================================================
st.header("🔍 Insights (WTD / MTD / QTD / YTD / Total)")

periods = ["WTD", "MTD", "QTD", "YTD", "TOTAL"]

if "Sono (h)" in daily_df.columns and "SonoHorasNum" not in daily_df.columns:
    daily_df["SonoHorasNum"] = pd.to_numeric(daily_df["Sono (h)"], errors="coerce")

insights = {
    "Sono (h) — Média":              {"col": "SonoHorasNum",         "mode": "mean", "fmt": "time"},
    "Sono Deep (h) — Média":         {"col": "Sono Deep (h)",        "mode": "mean", "fmt": "time"},
    "Sono REM (h) — Média":          {"col": "Sono REM (h)",         "mode": "mean", "fmt": "time"},
    "Sono Light (h) — Média":        {"col": "Sono Light (h)",       "mode": "mean", "fmt": "time"},
    "Qualidade do sono (score)":     {"col": "Sono (score)",         "mode": "mean", "fmt": "num"},
    "Distância corrida (km) — Soma": {"col": "Corrida (km)",         "mode": "sum",  "fmt": "num",  "only_positive": True, "filter_col": "Corrida (km)"},
    "Distância corrida (km) — Média":{"col": "Corrida (km)",         "mode": "mean", "fmt": "num",  "only_positive": True, "filter_col": "Corrida (km)"},
    "Pace médio (min/km)":           {"col": "PaceNum",              "mode": "mean", "fmt": "pace", "only_positive": True, "filter_col": "Corrida (km)"},
    "Passos — Média":                {"col": "Passos",               "mode": "mean", "fmt": "int"},
    "Calorias (total dia) — Média":  {"col": "Calorias (total dia)", "mode": "mean", "fmt": "num"},
    "Body Battery (máx)":            {"col": "Body Battery (máx)",   "mode": "mean", "fmt": "num"},
    "Stress médio":                  {"col": "Stress (média)",       "mode": "mean", "fmt": "num"},
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
    ["Sono (h)", "Sono (score)", "Stress (média)", "Corrida (km)", "Pace (min/km)", "Breathwork (min)", "Passos", "Calorias (total dia)", "Body Battery (máx)"],
    default=["Sono (h)", "Sono (score)"]
)

if len(corr_metrics) >= 2:
    df_corr = daily_df.copy()
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
