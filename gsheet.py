# garmin_to_gsheets.py
# ----------------------------------------------------
# Coleta dados do Garmin e salva direto no Google Sheets
# - Aba "DailyHUD": 1 linha por dia
# - Aba "Activities": 1 linha por atividade (com Pace por atividade)
# - Abas RAW para auditoria: Raw_Summary, Raw_Sleep, Raw_Stats
# - Rodadas futuras mesclam com o conteúdo existente (sem duplicar)
# ----------------------------------------------------

import datetime as dt
import json
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
START_DATE = "2023-01-01"
END_DATE   = "2025-08-31"

# ID da planilha no Google Sheets (já compartilhada com a service account)
GSHEET_ID = "1rwcDJA1yZ2hbsJx-HOW0dCduvWqV0z7f9Iio0HI1WwY"

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

# ---------- Sleep helpers ----------
def _extract_sleep_score(sleep_obj: dict, dto: dict) -> Optional[float]:
    direct_candidates = [
        (sleep_obj or {}).get("sleepScore"),
        (sleep_obj or {}).get("sleepScoreDTO"),
        (dto or {}).get("sleepScore"),
        (dto or {}).get("sleepScoreDTO"),
    ]
    for cand in direct_candidates:
        if isinstance(cand, dict):
            for k in ("overall", "value", "overallScore", "score"):
                v = cand.get(k)
                if isinstance(v, (int, float)):
                    return float(v)

    list_candidates = (sleep_obj or {}).get("sleepScores") or (dto or {}).get("sleepScores")
    if isinstance(list_candidates, list):
        for item in list_candidates:
            if isinstance(item, dict):
                for k in ("overall", "value", "overallScore", "score"):
                    v = item.get(k)
                    if isinstance(v, (int, float)):
                        return float(v)

    for alt_key in ("scores", "summary"):
        maybe = (sleep_obj or {}).get(alt_key) or (dto or {}).get(alt_key)
        if isinstance(maybe, dict):
            for k in ("overall", "value", "overallScore", "sleepScore"):
                v = maybe.get(k)
                if isinstance(v, (int, float)):
                    return float(v)

    return None

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

        if out["score"] is None:
            out["score"] = (
                (sleep.get("sleepScore") or {}).get("value")
                or (sleep.get("sleepScore") or {}).get("overall")
                or _extract_sleep_score(sleep, dto)
            )
    except Exception:
        pass
    return out

def fetch_body_battery(g: Garmin, day_iso: str) -> Dict[str, Optional[float]]:
    out = {"bb_start": None, "bb_end": None, "bb_min": None, "bb_max": None, "bb_avg": None}
    try:
        values = []
        if hasattr(g, "get_body_battery"):
            day = pd.to_datetime(day_iso).date()
            day_next = (day + dt.timedelta(days=1)).isoformat()
            try:
                series = g.get_body_battery(day_iso, day_next)
            except Exception:
                series = None
            if isinstance(series, list):
                for it in series:
                    cal = it.get("date") or it.get("calendarDate") or it.get("calendar_date")
                    if cal and str(cal)[:10] != day_iso:
                        continue
                    v = it.get("value") or it.get("y")
                    if isinstance(v, (int, float)):
                        values.append(float(v))

        if values:
            out["bb_min"] = min(values)
            out["bb_max"] = max(values)
            out["bb_avg"] = round(sum(values) / len(values), 1)
            out["bb_start"] = values[0]
            out["bb_end"]   = values[-1]
            return out

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

    try:
        st_data = None
        if hasattr(g, "get_stress_data"):
            st_data = g.get_stress_data(day_iso)
        if not st_data and hasattr(g, "get_all_day_stress"):
            st_data = g.get_all_day_stress(day_iso)

        vals = []
        if isinstance(st_data, list):
            for x in st_data:
                v = x.get("stressLevel") or x.get("y") or x.get("value")
                if isinstance(v, (int, float)):
                    vals.append(float(v))
        elif isinstance(st_data, dict):
            for arr_key in ("stressValues", "stressValuesArray", "allDayStress", "values"):
                arr = st_data.get(arr_key)
                if isinstance(arr, list):
                    for i in arr:
                        v = (i.get("stressLevel") if isinstance(i, dict) else i)
                        if isinstance(v, (int, float)):
                            vals.append(float(v))
        return round(sum(vals)/len(vals), 1) if vals else None
    except Exception:
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

def summarize_day(g: Garmin, day_iso: str) -> Tuple[Dict[str, Any], List[Dict[str, Any]], Dict[str, Any]]:
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
    stress = fetch_stress_avg(g, day_iso)
    stats = fetch_steps_and_calories(g, day_iso)

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

# ---------- Função para atualizar o Google Sheets ----------
def update_sheet(df, sheet_name, key_cols, sort_by):
    sheet = client.open_by_key(GSHEET_ID)
    try:
        ws = sheet.worksheet(sheet_name)
    except Exception:
        ws = sheet.add_worksheet(title=sheet_name, rows="1000", cols="20")

    old_df = get_as_dataframe(ws, evaluate_formulas=False, header=0)
    old_df = old_df.dropna(how="all")

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
    raw_summary_rows, raw_sleep_rows, raw_stats_rows = [], [], []

    for d in daterange(start, end):
        day_iso = d.isoformat()
        row, acts, stats = summarize_day(g, day_iso)
        daily_rows.append(row)
        for a in acts:
            activities_rows.append(normalize_activity(a))

        raw_summary_rows.append({"Data": day_iso, "Raw": json.dumps(stats, ensure_ascii=False)})
        try:
            sleep_raw = g.get_sleep_data(day_iso) or {}
        except Exception:
            sleep_raw = {}
        try:
            stats_raw = g.get_stats(day_iso) or {}
        except Exception:
            stats_raw = {}
        raw_sleep_rows.append({"Data": day_iso, "Raw": json.dumps(sleep_raw, ensure_ascii=False)})
        raw_stats_rows.append({"Data": day_iso, "Raw": json.dumps(stats_raw, ensure_ascii=False)})

    # Cria DataFrames
    new_daily       = pd.DataFrame(daily_rows)
    new_acts        = pd.DataFrame(activities_rows)
    new_raw_summary = pd.DataFrame(raw_summary_rows)
    new_raw_sleep   = pd.DataFrame(raw_sleep_rows)
    new_raw_stats   = pd.DataFrame(raw_stats_rows)

    # Atualiza cada aba no Google Sheets
    update_sheet(new_daily, "DailyHUD", ["Data"], "Data")
    update_sheet(new_acts, "Activities", ["ID"], "Data")
    update_sheet(new_raw_summary, "Raw_Summary", ["Data"], "Data")
    update_sheet(new_raw_sleep, "Raw_Sleep", ["Data"], "Data")
    update_sheet(new_raw_stats, "Raw_Stats", ["Data"], "Data")

    st.success("✅ Dados do Garmin atualizados no Google Sheets!")
