import streamlit as st
import garmin_to_gsheets

st.set_page_config(page_title="Garmin → Google Sheets", page_icon="⌚", layout="centered")

st.title("📊 Garmin → Google Sheets")

st.write("Clique no botão abaixo para buscar os dados do Garmin e atualizar a planilha:")

if st.button("🔄 Atualizar dados do Garmin"):
    with st.spinner("Conectando ao Garmin e atualizando a planilha..."):
        try:
            gsheet.main()
            st.success("✅ Dados do Garmin atualizados no Google Sheets com sucesso!")
            st.write("📂 [Abrir planilha no Google Sheets](https://docs.google.com/spreadsheets/d/1rwcDJA1yZ2hbsJx-HOW0dCduvWqV0z7f9Iio0HI1WwY/edit)")
        except Exception as e:
            st.error("❌ Erro ao atualizar a planilha")
            st.exception(e)
