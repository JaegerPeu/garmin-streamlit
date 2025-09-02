# garmin_to_gsheets.py
# ----------------------------------------------------
# Coleta dados do Garmin e salva direto no Google Sheets
# - Aba "DailyHUD": 1 linha por dia (sono, score, body battery, stress, corrida, pace, passos, calorias)
# - Aba "Activities": 1 linha por atividade (com Pace por atividade)
# - Rodadas futuras mesclam com o conteúdo existente (sem duplicar)
# ----------------------------------------------------

import datetime as dt
from typing import List, Dict, Any, Optional, Tuple
import pandas as pd
import gspread
from gspread_dataframe import set_with_dataframe, get_as_dataframe
from google.oauth2.service_account import Credentials
import streamlit as st
from garminconnect import Garmin

# =============== CONFIGURAÇÃO ===============
GARMIN_EMAIL    = st.secrets["garmin"]["email"]
GARMIN_PASSWORD = st.secrets["garmin"]["password"]

USE_LAST_N_DAYS = True
LAST_N_DAYS     = 3
START_DATE = "2024-02-19"
END_DATE   = "2025-08-31"

# ID da planilha no Google Sheets (já compartilhada com a service account)
GSHEET_ID = "1rwcDJA1yZ2hbsJx-HOW0dCduvWqV0z7f9Iio0HI1WwY"  # substitua pelo ID da sua planilha

# Credenciais do Google (do secrets do Streamlit)
service_account_info = st.secrets["gcp_service_account"]
scopes = ["https://www.googleapis.com/auth/spreadsheets"]
creds = Credentials.from_service_account_info(service_account_info, scopes=scopes)
client = gspread.authorize(creds)
# ===========================================

# ---------- Utilidades ----------
def login_garmin() -> Garmin:
    g = Garmin(GARMIN_EMAIL, GARMIN_PASSWORD)
    g.login()
    return g

def daterange(start_date: dt.date, end_date: dt.date):
    for n in range((end_date - start_date).days + 1):
        yield start_date + dt.timedelta(n)

def pace_str(total_seconds: Optional[float], km: Optional[float]) -> str:
    if not km or km == 0 or not total_seconds:
        return ""
    sec_per_km = int(total_seconds / km)
    return f"{sec_per_km // 60:02d}:{sec_per_km % 60:02d}"

# ---------- Fetchers ----------
def fetch_activities_by_day(g: Garmin, day_iso: str) -> List[Dict[str, Any]]:
    try:
        return g.get_activities_by_date(day_iso, day_iso) or []
    except Exception:
        return []

def fetch_sleep(g: Garmin, day_iso: str) -> Dict[str, Any]:
    out = {"total_h": None, "deep_h": None, "rem_h": None, "light_h": None, "awake_min": None, "score": None}
    try:
        sleep = g.get_sleep_data(day_iso) or {}
        dto = sleep.get("dailySleepDTO") or {}

        if dto:
            deep_h  = round((dto.get("deepSleepSeconds")  or 0) / 3600.0, 2)
            rem_h   = round((dto.get("remSleepSeconds")   or 0) / 3600.0, 2)
            light_h = round((dto.get("lightSleepSeconds") or 0) / 3600.0, 2)

            out["deep_h"]  = deep_h
            out["rem_h"]   = rem_h
            out["light_h"] = light_h
            out["total_h"] = round((deep_h + rem_h + light_h), 2)

            if dto.get("awakeSleepSeconds") is not None:
                out["awake_min"] = round(dto["awakeSleepSeconds"] / 60.0, 1)

            scores = dto.get("sleepScores") or {}
            overall = scores.get("overall") or {}
            val = overall.get("value")
            if isinstance(val, (int, float)):
                out["score"] = float(val)
    except Exception:
        pass
    return out

def fetch_body_battery(g: Garmin, day_iso: str) -> Dict[str, Optional[float]]:
    out = {"bb_start": None, "bb_end": None, "bb_min": None, "bb_max": None, "bb_avg": None}
    try:
        stats = g.get_stats(day_iso) or {}
        out["bb_start"] = stats.get("bodyBatteryAtWakeTime")
        out["bb_end"]   = stats.get("bodyBatteryMostRecentValue")
        out["bb_min"]   = stats.get("bodyBatteryLowestValue")
        out["bb_max"]   = stats.get("bodyBatteryHighestValue")
    except Exception:
        pass
    return out

def fetch_stress_avg(g: Garmin, day_iso: str) -> Optional[float]:
    try:
        stats = g.get_stats(day_iso) or {}
        avg = stats.get("averageStressLevel")
        if isinstance(avg, (int, float)):
            return round(float(avg), 1)
    except Exception:
        pass
    return None

def fetch_steps_and_calories(g: Garmin, day_iso: str) -> Dict[str, Any]:
    out = {"steps": None, "calories": None}
    try:
        stats = g.get_stats(day_iso) or {}
        out["steps"]    = stats.get("totalSteps") if stats.get("totalSteps") is not None else stats.get("steps")
        out["calories"] = stats.get("totalKilocalories") if stats.get("totalKilocalories") is not None else stats.get("calories")
    except Exception:
        pass
    return out

# ---------- Builders ----------
def normalize_activity(a: Dict[str, Any]) -> Dict[str, Any]:
    tkey = (a.get("activityType") or {}).get("typeKey", "unknown")
    duration_sec = a.get("duration") or 0
    distance_km  = (a.get("distance") or 0) / 1000.0

    activity_pace = ""
    if tkey == "running" and distance_km > 0 and duration_sec > 0:
        activity_pace = pace_str(duration_sec, distance_km)

    return {
        "Data": a.get("startTimeLocal"),
        "Tipo": tkey,
        "ID": a.get("activityId"),
        "Duração (min)": round(duration_sec / 60.0, 2),
        "Distância (km)": round(distance_km, 2),
        "Calorias": a.get("calories"),
        "Velocidade Média (km/h)": round(((a.get("averageSpeed") or 0) * 3.6), 2),
        "Velocidade Máx (km/h)": round(((a.get("maxSpeed") or 0) * 3.6), 2),
        "FC Média": a.get("averageHR"),
        "FC Máx": a.get("maxHR"),
        "VO2 Máx": a.get("vO2MaxValue"),
        "PPM": a.get("averageRunningCadenceInStepsPerMinute"),
        "Pace (min/km)": activity_pace,
        "Nome": a.get("activityName") or "",
    }

def summarize_day(g: Garmin, day_iso: str, today: dt.date) -> Dict[str, Any]:
    acts = fetch_activities_by_day(g, day_iso)

    total_run_km = 0.0
    total_run_sec = 0.0
    total_cal_acts = 0
    for a in acts:
        total_cal_acts += a.get("calories") or 0
        if a.get("activityType", {}).get("typeKey") == "running":
            total_run_km  += (a.get("distance") or 0) / 1000.0
            total_run_sec += (a.get("duration") or 0)

    sleep = fetch_sleep(g, day_iso)
    bb = fetch_body_battery(g, day_iso)

    # Pegar steps e calorias
    stats = fetch_steps_and_calories(g, day_iso)

    # Para o dia atual, usar os dados do dia anterior (fechados) para calorias e passos
    if day_iso == today.isoformat():
        try:
            yesterday = (today - dt.timedelta(days=1)).isoformat()
            stats_yest = fetch_steps_and_calories(g, yesterday)
            if stats_yest.get("calories"):
                stats["calories"] = stats_yest.get("calories")
            if stats_yest.get("steps"):
                stats["steps"] = stats_yest.get("steps")
        except Exception:
            pass

    stress = fetch_stress_avg(g, day_iso)

    row = {
        "Data": day_iso,
        "Sono (h)": sleep["total_h"],
        "Sono Deep (h)": sleep["deep_h"],
        "Sono REM (h)": sleep["rem_h"],
        "Sono Light (h)": sleep["light_h"],
        "Sono Awake (min)": sleep["awake_min"],
        "Sono (score)": sleep["score"],
        "Body Battery (start)": bb["bb_start"],
        "Body Battery (end)": bb["bb_end"],
        "Body Battery (mín)": bb["bb_min"],
        "Body Battery (máx)": bb["bb_max"],
        "Body Battery (média)": bb["bb_avg"],
        "Stress (média)": stress,
        "Corrida (km)": round(total_run_km, 2),
        "Pace (min/km)": pace_str(total_run_sec, total_run_km),
        "Passos": stats["steps"],
        "Calorias (total dia)": stats["calories"],
        "Calorias (atividades)": total_cal_acts,
    }
    return row, acts, stats

# ---------- Função para atualizar Google Sheets ----------
def update_sheet(df, sheet_name, key_cols, sort_by):
    sheet = client.open_by_key(GSHEET_ID)
    try:
        ws = sheet.worksheet(sheet_name)
    except Exception:
        ws = sheet.add_worksheet(title=sheet_name, rows="1000", cols="20")

    old_df = get_as_dataframe(ws, evaluate_formulas=False, header=0)
    old_df = old_df.dropna(how= "all")

    if not old_df.empty:
        df_merged = pd.concat([old_df, df], ignore_index=True).drop_duplicates(subset=key_cols, keep="last")
        if sort_by in df_merged.columns:
            df_merged = df_merged.sort_values(sort_by).reset_index(drop=True)
    else:
        df_merged = df

    ws.clear()
    set_with_dataframe(ws, df_merged)

# ---------- Main ----------
def main():
    today = dt.date.today()
    if USE_LAST_N_DAYS:
        end = today
        start = today - dt.timedelta(days=LAST_N_DAYS - 1)
    else:
        start = pd.to_datetime(START_DATE).date()
        end   = pd.to_datetime(END_DATE).date()

    g = login_garmin()

    daily_rows, activities_rows = [], []

    for d in daterange(start, end):
        day_iso = d.isoformat()
        row, acts, _ = summarize_day(g, day_iso, today)
        daily_rows.append(row)
        for a in acts:
            activities_rows.append(normalize_activity(a))

    # Cria DataFrames
    new_daily = pd.DataFrame(daily_rows)
    new_acts  = pd.DataFrame(activities_rows)

    # Atualiza apenas abas principais
    update_sheet(new_daily, "DailyHUD", ["Data"], "Data")
    update_sheet(new_acts, "Activities", ["ID"], "Data")

    st.success("✅ Dados do Garmin atualizados no Google Sheets!")
