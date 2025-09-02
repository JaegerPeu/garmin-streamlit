import streamlit as st
import gspread
from google.oauth2.service_account import Credentials

# ===== Configurações =====
SERVICE_ACCOUNT_FILE = "credentials.json"   # seu arquivo JSON baixado
GSHEET_ID = "1rwcDJA1yZ2hbsJx-HOW0dCduvWqV0z7f9Iio0HI1WwY"  # ID da planilha (entre /d/ e /edit)

scopes = ["https://www.googleapis.com/auth/spreadsheets"]
creds = Credentials.from_service_account_file(SERVICE_ACCOUNT_FILE, scopes=scopes)
client = gspread.authorize(creds)

# ===== App Streamlit =====
st.set_page_config(page_title="Teste Google Sheets", page_icon="✅", layout="centered")

st.title("🔗 Teste de Conexão com Google Sheets")

if st.button("🔄 Testar conexão"):
    try:
        sheet = client.open_by_key(GSHEET_ID)
        st.success(f"Conexão bem-sucedida! 🚀")
        st.write("Título da planilha:", sheet.title)
        st.write("Abas encontradas:", [ws.title for ws in sheet.worksheets()])
    except Exception as e:
        st.error("❌ Erro ao conectar na planilha")
        st.exception(e)
