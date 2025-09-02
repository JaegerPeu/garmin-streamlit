import streamlit as st
from google.oauth2.service_account import Credentials
import gspread

# Lê credenciais direto do secrets do Streamlit
service_account_info = st.secrets["gcp_service_account"]
scopes = ["https://www.googleapis.com/auth/spreadsheets"]
creds = Credentials.from_service_account_info(service_account_info, scopes=scopes)

client = gspread.authorize(creds)

# ID da sua planilha
GSHEET_ID = "1rwcDJA1yZ2hbsJx-HOW0dCduvWqV0z7f9Iio0HI1WwY"


def connect_gsheets():
    try:
        # Lê credenciais do secrets do Streamlit Cloud
        service_account_info = st.secrets["gcp_service_account"]
        scopes = ["https://www.googleapis.com/auth/spreadsheets"]
        creds = Credentials.from_service_account_info(service_account_info, scopes=scopes)
        client = gspread.authorize(creds)

        # Abre a planilha pelo ID
        sheet = client.open_by_key(GSHEET_ID)
        return sheet

    except Exception as e:
        st.error("❌ Erro ao conectar no Google Sheets")
        st.exception(e)
        return None

if st.button("🔄 Testar Conexão"):
    with st.spinner("Conectando ao Google Sheets..."):
        sheet = connect_gsheets()
        if sheet:
            st.success("✅ Conexão bem-sucedida!")
            st.write("📄 Nome da planilha:", sheet.title)
            st.write("📑 Abas encontradas:", [ws.title for ws in sheet.worksheets()])
