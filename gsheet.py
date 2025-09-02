import gspread
from google.oauth2.service_account import Credentials
from gspread_dataframe import set_with_dataframe
import pandas as pd

SERVICE_ACCOUNT_FILE = "credentials.json"
GSHEET_ID = "COLOQUE_O_ID_DA_SUA_PLANILHA"

scopes = ["https://www.googleapis.com/auth/spreadsheets"]
creds = Credentials.from_service_account_file(SERVICE_ACCOUNT_FILE, scopes=scopes)

client = gspread.authorize(creds)

# Abre a planilha
sheet = client.open_by_key(GSHEET_ID)

# Testa com uma aba "DailyHUD"
ws = sheet.worksheet("DailyHUD")

# Exemplo: escreve um dataframe de teste
df = pd.DataFrame({"Data": ["2025-09-02"], "Teste": [123]})
set_with_dataframe(ws, df)
print("✅ Planilha atualizada com sucesso!")
