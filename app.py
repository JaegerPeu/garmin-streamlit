import streamlit as st
import pandas as pd
import gspread
from gspread_dataframe import get_as_dataframe
from google.oauth2.service_account import Credentials
import plotly.express as px
import garmin_to_gsheets

# ================= CONFIGURAÇÃO ==================
GSHEET_ID = "1rwcDJA1yZ2hbsJx-HOW0dCduvWqV0z7f9Iio0HI1WwY"  # coloque o ID completo da sua planilha

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
        df = df.dropna(how="all")  # remove linhas totalmente vazias
        return df
    except Exception as e:
        st.error(f"❌ Erro ao carregar aba {sheet_name}: {e}")
        return pd.DataFrame()

# =================================================
# APP STREAMLIT
# =================================================
st.set_page_config(page_title="📊 Dashboard Garmin", layout="wide")

st.title("🏃‍♂️ Dashboard de Atividades Garmin")
st.write("Sincronize seus dados do Garmin com o Google Sheets e veja análises em tempo real.")

# Botão de atualização
if st.button("🔄 Atualizar dados do Garmin"):
    with st.spinner("Conectando ao Garmin e atualizando planilha..."):
        try:
            garmin_to_gsheets.main()
            st.success("✅ Dados atualizados com sucesso!")
        except Exception as e:
            st.error("❌ Erro ao atualizar os dados")
            st.exception(e)

# Carrega os dados do Sheets
daily_df = load_sheet("DailyHUD")
acts_df  = load_sheet("Activities")

if daily_df.empty:
    st.warning("Nenhum dado encontrado na aba `DailyHUD`. Clique em **Atualizar dados** acima.")
    st.stop()

# ---------- VISUALIZAÇÕES ----------
st.header("📈 Evolução diária")

# Converter colunas
daily_df["Data"] = pd.to_datetime(daily_df["Data"], errors="coerce")

col1, col2 = st.columns(2)

with col1:
    fig_sleep = px.line(daily_df, x="Data", y="Sono (h)", title="Horas de Sono por Dia", markers=True)
    st.plotly_chart(fig_sleep, use_container_width=True)

    fig_stress = px.line(daily_df, x="Data", y="Stress (média)", title="Nível Médio de Stress", markers=True)
    st.plotly_chart(fig_stress, use_container_width=True)

with col2:
    fig_battery = px.line(
        daily_df, 
        x="Data", 
        y=["Body Battery (mín)", "Body Battery (média)", "Body Battery (máx)"], 
        title="Body Battery (Start / Média / Máx)"
    )
    st.plotly_chart(fig_battery, use_container_width=True)

    fig_steps = px.bar(daily_df, x="Data", y="Passos", title="Passos por Dia")
    st.plotly_chart(fig_steps, use_container_width=True)

st.header("🏃‍♀️ Corridas")
if not acts_df.empty:
    acts_df["Data"] = pd.to_datetime(acts_df["Data"], errors="coerce")

    fig_runs = px.scatter(
        acts_df[acts_df["Tipo"] == "running"],
        x="Data",
        y="Pace (min/km)",
        size="Distância (km)",
        color="Calorias",
        hover_data=["Nome", "Duração (min)"],
        title="Corridas: Pace x Data"
    )
    st.plotly_chart(fig_runs, use_container_width=True)

    st.subheader("Tabela de Atividades")
    st.dataframe(acts_df)
else:
    st.info("Nenhuma atividade de corrida encontrada ainda.")

# ---------- ANÁLISE HOLÍSTICA ----------
st.header("🔍 Insights sobre sua saúde e performance")

try:
    avg_sono = daily_df["Sono (h)"].dropna().astype(float).mean()
    avg_stress = daily_df["Stress (média)"].dropna().astype(float).mean()
    avg_passos = daily_df["Passos"].dropna().astype(float).mean()
    avg_corrida = daily_df["Corrida (km)"].dropna().astype(float).mean()
    avg_pace = daily_df["Pace (min/km)"].replace("", None).dropna().mean()

    st.markdown(f"""
    - 💤 **Sono médio/dia:** {avg_sono:.1f} horas  
    - 🏃‍♂️ **Distância média corrida/dia:** {avg_corrida:.2f} km  
    - 🚶 **Passos médios/dia:** {avg_passos:.0f} passos  
    - ❤️ **Stress médio:** {avg_stress if not pd.isna(avg_stress) else "N/A"}  
    - ⏱️ **Pace médio corridas:** {avg_pace if not pd.isna(avg_pace) else "N/A"} min/km  
    """)

    # Correlação sono vs stress
    if not daily_df["Sono (h)"].isna().all() and not daily_df["Stress (média)"].isna().all():
        fig_corr = px.scatter(
            daily_df,
            x="Sono (h)",
            y="Stress (média)",
            trendline="ols",
            title="Correlação: Sono (h) x Stress Médio"
        )
        st.plotly_chart(fig_corr, use_container_width=True)

except Exception as e:
    st.error("Erro ao calcular insights")
    st.exception(e)
