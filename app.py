# app.py
# =====================================================
# Dashboard Streamlit para visualização dos dados Garmin
# Dados são carregados do Google Sheets (já atualizado
# pelo script garmin_to_gsheets.py).
# + Integração de HUD com Notion (code block)
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
import requests  # <-- Notion API
import gsheet

# ================= CONFIGURAÇÃO ==================
GSHEET_ID = "1rwcDJA1yZ2hbsJx-HOW0dCduvWqV0z7f9Iio0HI1WwY"  # ID da planilha

service_account_info = st.secrets["gcp_service_account"]
scopes = ["https://www.googleapis.com/auth/spreadsheets"]
creds = Credentials.from_service_account_info(service_account_info, scopes=scopes)
client = gspread.authorize(creds)

# Notion (defina em .streamlit/secrets.toml)
NOTION_TOKEN = st.secrets.get("notion_token", None)
NOTION_BLOCK_ID = st.secrets.get("notion_block_id", "25f695cea74880c4a25dc91582810bdb")
NOTION_COUNTER_DB_ID = st.secrets.get("notion_counter_db_id", None)
NOTION_VERSION = "2022-06-28"
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
        if temp[date_col].notna().any():
            start = temp[date_col].min().date()
        else:
            return None

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

def pace_series_to_hover(series: pd.Series):
    """Transforma uma série numérica (minutos decimais) em lista mm:ss para hover."""
    return [format_pace(v) if pd.notna(v) and v not in ("", 0) else None for v in series]

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

# ---------- Funções Notion ----------
def notion_headers():
    if not NOTION_TOKEN:
        return None
    return {
        "Authorization": f"Bearer {NOTION_TOKEN}",
        "Notion-Version": NOTION_VERSION,
        "Content-Type": "application/json",
    }

def update_notion_block(block_id: str, content: str):
    """Atualiza o conteúdo de um bloco de código no Notion (language=markdown)."""
    hdrs = notion_headers()
    if not hdrs:
        st.error("❌ NOTION_TOKEN não configurado em st.secrets['notion_token'].")
        return
    url = f"https://api.notion.com/v1/blocks/{block_id}"
    payload = {
        "object": "block",
        "type": "code",
        "code": {
            "rich_text": [{"type": "text", "text": {"content": content}}],
            "language": "markdown",
        },
    }
    resp = requests.patch(url, headers=hdrs, json=payload)
    if resp.status_code == 200:
        st.success("✅ HUD atualizado no Notion!")
    else:
        st.error(f"❌ Erro ao atualizar bloco Notion ({resp.status_code})")
        try:
            st.write(resp.json())
        except Exception:
            st.write(resp.text)

def notion_query_counter_streak() -> Optional[str]:
    """
    Lê a database 'Counter' no Notion (se NOTION_COUNTER_DB_ID estiver em secrets)
    e tenta extrair um valor de streak.
    Fallback: retorna '-' se não conseguir ler.
    """
    if not NOTION_COUNTER_DB_ID:
        return "-"
    hdrs = notion_headers()
    if not hdrs:
        return "-"
    url = f"https://api.notion.com/v1/databases/{NOTION_COUNTER_DB_ID}/query"
    resp = requests.post(url, headers=hdrs, json={})
    if resp.status_code != 200:
        return "-"
    data = resp.json()
    results = data.get("results", [])
    if not results:
        return "-"
    # Heurística: tenta achar uma propriedade numérica chamada Streak/Count
    for prop_name in ["Streak", "streak", "Count", "count", "Valor", "value"]:
        for page in results:
            props = page.get("properties", {})
            prop = props.get(prop_name)
            if not prop:
                continue
            if prop.get("type") == "number":
                val = prop.get("number")
                if val is not None:
                    return str(int(val)) if float(val).is_integer() else str(val)
            if prop.get("type") == "rich_text":
                texts = prop.get("rich_text", [])
                if texts:
                    return texts[0].get("plain_text", "-")
    # fallback genérico: pega o primeiro número encontrado
    for page in results:
        props = page.get("properties", {})
        for p in props.values():
            if p.get("type") == "number" and p.get("number") is not None:
                val = p.get("number")
                return str(int(val)) if float(val).is_integer() else str(val)
    return "-"

# ---------- HUD ----------
def gerar_hud_markdown(daily_df: pd.DataFrame, acts_df: pd.DataFrame, turtle_df: pd.DataFrame) -> str:
    """Gera HUD em estilo RPG a partir dos dados (DailyHUD, Activities e Turtle)."""
    today = dt.date.today()

    # --- Daily base (último registro válido)
    ddf = daily_df.copy()
    ddf["Data"] = pd.to_datetime(ddf["Data"], errors="coerce")
    ddf = ddf.sort_values("Data")
    ultimo = ddf.iloc[-1] if not ddf.empty else pd.Series(dtype="object")

    def gv(s, col, default="-"):
        try:
            v = s.get(col, default)
            if pd.isna(v): return default
            return v
        except Exception:
            return default

    sono_horas = gv(ultimo, "Sono (h)", "-")
    sono_score = gv(ultimo, "Sono (score)", "-")
    bb_max     = gv(ultimo, "Body Battery (máx)", "-")
    calorias_d = gv(ultimo, "Calorias (total dia)", "-")
    passos_d   = gv(ultimo, "Passos", "-")
    breath_d   = gv(ultimo, "Breathwork (min)", "-")

    # --- Breathwork últimos 7 dias
    last7_mask = ddf["Data"].dt.date >= (today - dt.timedelta(days=6))
    breath_7d_sum = ddf.loc[last7_mask, "Breathwork (min)"].dropna().sum() if "Breathwork (min)" in ddf.columns else 0
    breath_7d_avg = ddf.loc[last7_mask, "Breathwork (min)"].dropna().mean() if "Breathwork (min)" in ddf.columns else 0

    # --- Atividade (running) últimos 7d
    runs_7d_sessions = 0
    runs_7d_km = 0.0
    runs_7d_pace = "-"
    runs_7d_km_per_session = "-"

    if not acts_df.empty:
        adf = acts_df.copy()
        adf["Data"] = pd.to_datetime(adf["Data"], errors="coerce")
        adf = adf.dropna(subset=["Data"])
        adf["DataDay"] = adf["Data"].dt.normalize()
        # últimos 7 dias
        adf7 = adf[adf["DataDay"].dt.date >= (today - dt.timedelta(days=6))]
        adf7_run = adf7[adf7["Tipo"] == "running"]
        if not adf7_run.empty:
            runs_7d_sessions = len(adf7_run)
            runs_7d_km = pd.to_numeric(adf7_run["Distância (km)"], errors="coerce").fillna(0).sum()
            dur_sum = pd.to_numeric(adf7_run["Duração (min)"], errors="coerce").fillna(0).sum()
            if runs_7d_km > 0:
                runs_7d_pace = format_pace(dur_sum / runs_7d_km)
                runs_7d_km_per_session = f"{(runs_7d_km / runs_7d_sessions):.2f}"

    passos_7d_med = "-"
    if "Passos" in ddf.columns:
        passos_7d_med = ddf.loc[last7_mask, "Passos"].dropna().mean()
        passos_7d_med = f"{passos_7d_med:,.0f}" if pd.notna(passos_7d_med) else "-"

    # --- Períodos WTD/MTD/QTD/YTD (running): sessões, km, pace
    def period_stats(acts: pd.DataFrame, start_date: dt.date):
        zz = acts[(acts["Tipo"] == "running") & (acts["Data"].dt.date >= start_date)]
        if zz.empty:
            return {"sess": 0, "km": "-", "pace": "-"}
        sess = len(zz)
        km = pd.to_numeric(zz["Distância (km)"], errors="coerce").fillna(0).sum()
        dur = pd.to_numeric(zz["Duração (min)"], errors="coerce").fillna(0).sum()
        pace = format_pace(dur / km) if km > 0 else "-"
        return {"sess": sess, "km": f"{km:.2f}", "pace": pace}

    wtd_start = today - dt.timedelta(days=today.weekday())
    mtd_start = today.replace(day=1)
    q = (today.month - 1) // 3 + 1
    qtd_start = dt.date(today.year, 3 * (q - 1) + 1, 1)
    ytd_start = dt.date(today.year, 1, 1)

    periods_tbl = []
    if not acts_df.empty:
        acts_tmp = acts_df.copy()
        acts_tmp["Data"] = pd.to_datetime(acts_tmp["Data"], errors="coerce")
        acts_tmp = acts_tmp.dropna(subset=["Data"])
        for label, sdate in [("WTD", wtd_start), ("MTD", mtd_start), ("QTD", qtd_start), ("YTD", ytd_start)]:
            p = period_stats(acts_tmp, sdate)
            periods_tbl.append((label, p["sess"], p["km"], p["pace"]))
    else:
        periods_tbl = [("WTD", 0, "-", "-"), ("MTD", 0, "-", "-"), ("QTD", 0, "-", "-"), ("YTD", 0, "-", "-")]

    # --- Objetivo do dia (Turtle / coluna 'Objetivo')
    objetivo = "-"
    if not turtle_df.empty and "Data" in turtle_df.columns:
        tdf = turtle_df.copy()
        tdf["Data"] = pd.to_datetime(tdf["Data"], errors="coerce")
        row = tdf[tdf["Data"].dt.date == today]
        if not row.empty:
            if "Objetivo" in row.columns:
                objetivo = row.iloc[0]["Objetivo"]

    # --- Streak (Notion Counter)
    streak_val = notion_query_counter_streak()  # "-" se não configurado

    # barras de energia 10/10 baseada no Body Battery max
    try:
        bb_int = int(float(bb_max))
        ticks = max(0, min(10, round(bb_int / 10)))
        energia_bar = "[" + "#" * ticks + "." * (10 - ticks) + f"] {bb_int}%"
    except Exception:
        energia_bar = f"[####......] {bb_max}%"

    # HUD
    hud = f"""
╔══════════════════════════════════════════════════════════════════╗
║ HUD — {today.strftime("%A, %d/%m/%Y")}                                  ║
╠══════════════════════════════════════════════════════════════════╣
║ Player: Pedro Duarte                                             ║
║ Energia: {energia_bar:<56}║
║ Sono: {format_hours(sono_horas) if isinstance(sono_horas,(int,float)) else sono_horas} | Qualidade: {sono_score}                    ║
╚══════════════════════════════════════════════════════════════════╝

╔══════════════════════════════════════════════════════════════════╗
║                              Mente                               ║
╠══════════════════════════════════════════════════════════════════╣
║ Meditação hoje: {breath_d if breath_d!='-' else 0} min                                  ║
║ Últimos 7d:     {int(breath_7d_sum)} min (média {int(round(breath_7d_avg))} min/dia)    ║
╚══════════════════════════════════════════════════════════════════╝

╔══════════════════════════════════════════════════════════════════╗
║                      Atividade Física (7d)                       ║
╠══════════════════════════════════════════════════════════════════╣
║ Sessões:        {runs_7d_sessions:<3}                                           ║
║ Distância:      {runs_7d_km:.2f} km                                        ║
║ Pace médio:     {runs_7d_pace:<9}                                     ║
║ Km/treino:      {runs_7d_km_per_session:<6} km                                  ║
║ Passos médios:  {passos_7d_med:<10}                                  ║
╚══════════════════════════════════════════════════════════════════╝

| Período  | Sessões |     Km |    Pace |
|---------------------------------------------|
| {periods_tbl[0][0]:<7}  | {periods_tbl[0][1]:>7} | {periods_tbl[0][2]:>6} | {periods_tbl[0][3]:>7} |
| {periods_tbl[1][0]:<7}  | {periods_tbl[1][1]:>7} | {periods_tbl[1][2]:>6} | {periods_tbl[1][3]:>7} |
| {periods_tbl[2][0]:<7}  | {periods_tbl[2][1]:>7} | {periods_tbl[2][2]:>6} | {periods_tbl[2][3]:>7} |
| {periods_tbl[3][0]:<7}  | {periods_tbl[3][1]:>7} | {periods_tbl[3][2]:>6} | {periods_tbl[3][3]:>7} |

╔══════════════════════════════════════════════════════════════════╗
║                           Corpo (hoje)                           ║
╠══════════════════════════════════════════════════════════════════╣
║ Body Battery:   {bb_max}%                                         ║
║ Calorias d-1:   {calorias_d}                                      ║
║ Passos d-1:     {passos_d}                                        ║
╚══════════════════════════════════════════════════════════════════╝

╔══════════════════════════════════════════════════════════════════╗
║                         Trabalho / Trade                         ║
╠══════════════════════════════════════════════════════════════════╣
║ Objetivo de hoje:   {objetivo}                                    ║
╚══════════════════════════════════════════════════════════════════╝

╔══════════════════════════════════════════════════════════════════╗
║                            Lifestyle                             ║
╠══════════════════════════════════════════════════════════════════╣
║ Streak:         {streak_val}                                      ║
╚══════════════════════════════════════════════════════════════════╝
"""
    return hud

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
turtle_df = load_sheet("Turtle")  # <- para Objetivo do dia

if daily_df.empty:
    st.warning("Nenhum dado encontrado na aba `DailyHUD`. Clique em **Atualizar dados** acima.")
    st.stop()

# Converter colunas numéricas (DailyHUD)
daily_df["Data"] = pd.to_datetime(daily_df["Data"], errors="coerce")

numeric_cols = [
    "Sono (h)", "Sono Deep (h)", "Sono REM (h)", "Sono Light (h)",
    "Sono (score)", "Body Battery (start)", "Body Battery (end)",
    "Body Battery (mín)", "Body Battery (máx)", "Body Battery (máx)",
    "Stress (média)", "Passos", "Calorias (total dia)",
    "Corrida (km)", "Pace (min/km)", "Breathwork (min)"
]
for c in numeric_cols:
    if c in daily_df.columns:
        daily_df[c] = pd.to_numeric(daily_df[c], errors="coerce")

# Pace diário em número (para gráficos/insights)
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

    # Extras → mesmo eixo do segundo
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
        cal_sum  = g["Calorias"].sum(skipna=True) if "Calorias" in g.columns else None
        fc_mean  = g["FC Média"].mean(skipna=True) if "FC Média" in g.columns else None
        vo2_mean = g["VO2 Máx"].mean(skipna=True) if "VO2 Máx" in g.columns else None

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
            y1_series = series_for_act_daily(df_filtered, y1)
            trace_kwargs = {}
            if y1 == "Pace (min/km)":
                # aqui o numérico é PaceNumDaily
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

            # extras -> mesmo eixo do 2º
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
                title=f"Evolução diária agregada — {selected_type}",
                legend=dict(orientation="h", y=-0.2)
            )
            st.plotly_chart(fig_act, use_container_width=True)

        with st.expander("📋 Tabela de Atividades (agregado por dia)"):
            st.dataframe(df_filtered)

        with st.expander("Ver tabela de atividades brutas (todas as sessões)"):
            st.dataframe(acts_df)
else:
    st.info("Nenhuma atividade encontrada ainda.")

# ---------- INSIGHTS ----------
st.header("🔍 Insights (WTD / MTD / QTD / YTD / Total)")

periods = ["WTD", "MTD", "QTD", "YTD", "TOTAL"]

# colunas auxiliares
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
    "Body Battery (máx)":            {"col": "Body Battery (máx)",   "mode": "mean", "fmt": "num"},
    "Stress médio":                  {"col": "Stress (média)",       "mode": "mean", "fmt": "num"},

    # Breathwork: média (considerando >0)
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

# ---------- HUD NOTION ----------
st.header("🧾 HUD (preview) + Notion")

try:
    hud_md = gerar_hud_markdown(daily_df, acts_df, turtle_df)
    st.code(hud_md, language="markdown")
except Exception as e:
    st.error("Falha ao gerar HUD.")
    st.exception(e)
    hud_md = None

if st.button("⚔️ Atualizar HUD no Notion"):
    if not hud_md:
        st.error("Não foi possível gerar o HUD. Verifique os dados.")
    else:
        update_notion_block(NOTION_BLOCK_ID, hud_md)
