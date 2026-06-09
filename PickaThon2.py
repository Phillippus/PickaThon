import streamlit as st
import pandas as pd
import random
import json
import os
import requests
from datetime import datetime

# ── Persistent storage ──────────────────────────────────────────────────────
DOCTORS_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "doctors.json")

def load_doctors():
    if os.path.exists(DOCTORS_FILE):
        with open(DOCTORS_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    return {}

def save_doctors(doctors_defaults):
    with open(DOCTORS_FILE, "w", encoding="utf-8") as f:
        json.dump(doctors_defaults, f, indent=2, ensure_ascii=False)

# ── Public holidays (Slovak API) ─────────────────────────────────────────────
@st.cache_data(ttl=86400)
def get_public_holidays(year):
    """Načíta slovenské štátne sviatky z nager.date API. Fallback na pevný zoznam."""
    try:
        response = requests.get(
            f"https://date.nager.at/api/v3/PublicHolidays/{year}/SK",
            timeout=5
        )
        if response.status_code == 200:
            return set(h["date"] for h in response.json())
    except Exception:
        pass
    # Fallback – fixné sviatky (bez Veľkej noci)
    fixed = ["01-01", "01-06", "05-01", "05-08", "07-05",
             "08-29", "09-01", "09-15", "11-01", "11-17",
             "12-24", "12-25", "12-26"]
    return set(f"{year}-{d}" for d in fixed)

# ── Calendar helpers ──────────────────────────────────────────────────────────
def get_num_days(year, month):
    return (pd.Timestamp(year=year, month=month, day=1) + pd.offsets.MonthEnd(0)).day

def is_off_day(day, year, month, holidays):
    date_str = f"{year}-{month:02d}-{day:02d}"
    date_obj = datetime.strptime(date_str, "%Y-%m-%d")
    return date_obj.weekday() >= 5 or date_str in holidays

DAY_NAMES = ["Po", "Ut", "St", "Šv", "Pi", "So", "Ne"]

# ── Scheduling algorithm ──────────────────────────────────────────────────────
def generate_schedule(doctors_monthly, year, month, holidays):
    """
    doctors_monthly: {name: {excluded_days, wanted_days,
                              max_weekday_shifts, max_weekend_shifts, no_weekend_shifts}}
    Returns: (schedule {day: doctor|"—"}, shift_count {doctor: {weekday, weekend}})
    """
    num_days = get_num_days(year, month)
    final_schedule = {}
    shift_count = {d: {"weekday": 0, "weekend": 0} for d in doctors_monthly}

    def off(day):
        return is_off_day(day, year, month, holidays)

    def can_assign(day, doctor):
        info = doctors_monthly[doctor]
        if day < 1 or day > num_days:
            return False
        if day in info["excluded_days"]:
            return False
        # No consecutive shifts (both directions, using already-assigned days)
        if final_schedule.get(day - 1) == doctor:
            return False
        if final_schedule.get(day + 1) == doctor:
            return False
        if off(day):
            if info["no_weekend_shifts"]:
                return False
            mx = info["max_weekend_shifts"]
            if mx > 0 and shift_count[doctor]["weekend"] >= mx:
                return False
        else:
            mx = info["max_weekday_shifts"]
            if mx > 0 and shift_count[doctor]["weekday"] >= mx:
                return False
        return True

    def assign(day, doctor):
        final_schedule[day] = doctor
        if off(day):
            shift_count[doctor]["weekend"] += 1
        else:
            shift_count[doctor]["weekday"] += 1

    def unassign(day):
        doctor = final_schedule.pop(day, None)
        if doctor and doctor != "—":
            if off(day):
                shift_count[doctor]["weekend"] = max(0, shift_count[doctor]["weekend"] - 1)
            else:
                shift_count[doctor]["weekday"] = max(0, shift_count[doctor]["weekday"] - 1)

    # Step 1: Wanted days (priority; conflicts resolved randomly)
    wanted_map = {}
    for doctor, info in doctors_monthly.items():
        for day in info["wanted_days"]:
            if 1 <= day <= num_days:
                wanted_map.setdefault(day, []).append(doctor)

    for day in sorted(wanted_map):
        if day in final_schedule:
            continue
        candidates = [d for d in wanted_map[day] if can_assign(day, d)]
        if candidates:
            assign(day, random.choice(candidates))

    # Step 2: Friday + Sunday same doctor (skip if already assigned)
    for day in range(1, num_days + 1):
        date_obj = datetime.strptime(f"{year}-{month:02d}-{day:02d}", "%Y-%m-%d")
        if date_obj.weekday() != 4:  # only Fridays
            continue
        sunday = day + 2
        if sunday > num_days:
            continue
        fri_assigned = day in final_schedule
        sun_assigned = sunday in final_schedule

        if fri_assigned and sun_assigned:
            continue  # both already set, leave them

        if not fri_assigned and not sun_assigned:
            # Find doctor who can do both
            candidates = [d for d in doctors_monthly
                          if can_assign(day, d) and can_assign(sunday, d)]
            if candidates:
                chosen = random.choice(candidates)
                assign(day, chosen)
                assign(sunday, chosen)
        elif not fri_assigned:
            candidates = [d for d in doctors_monthly if can_assign(day, d)]
            if candidates:
                assign(day, random.choice(candidates))
        else:  # Sunday not assigned — try same as Friday
            fri_doc = final_schedule[day]
            if can_assign(sunday, fri_doc):
                assign(sunday, fri_doc)
            else:
                candidates = [d for d in doctors_monthly if can_assign(sunday, d)]
                if candidates:
                    assign(sunday, random.choice(candidates))

    # Step 3: Fill remaining days (balanced — prefer least-loaded)
    for day in range(1, num_days + 1):
        if day in final_schedule:
            continue
        candidates = [d for d in doctors_monthly if can_assign(day, d)]
        if not candidates:
            final_schedule[day] = "—"
            continue
        key = "weekend" if off(day) else "weekday"
        candidates.sort(key=lambda d: shift_count[d][key])
        # Pick randomly among the least-loaded third
        top = max(1, len(candidates) // 3)
        assign(day, random.choice(candidates[:top]))

    # Step 4: Fix any remaining consecutive shifts (forward pass)
    for day in range(1, num_days):
        if final_schedule.get(day) == final_schedule.get(day + 1) == "—":
            continue
        if final_schedule.get(day) == final_schedule.get(day + 1):
            unassign(day + 1)
            candidates = [d for d in doctors_monthly if can_assign(day + 1, d)]
            if candidates:
                key = "weekend" if off(day + 1) else "weekday"
                candidates.sort(key=lambda d: shift_count[d][key])
                assign(day + 1, random.choice(candidates[:max(1, len(candidates) // 3)]))
            else:
                final_schedule[day + 1] = "—"

    return final_schedule, shift_count


# ── UI ────────────────────────────────────────────────────────────────────────
def main():
    st.set_page_config(layout="wide", page_title="PickaThon v3.0")
    st.title("PickaThon v 3.0 — Rozpisovač nočných služieb")

    if "doctors_defaults" not in st.session_state:
        st.session_state["doctors_defaults"] = load_doctors()

    tab1, tab2 = st.tabs(["👨‍⚕️ Správa lekárov", "📅 Generovanie rozvrhu"])

    # ── TAB 1: Doctor management ──────────────────────────────────────────────
    with tab1:
        st.header("Lekári (uložení natrvalo)")
        dd = st.session_state["doctors_defaults"]

        with st.form("add_doctor_form", clear_on_submit=True):
            st.subheader("Pridať / upraviť lekára")
            col1, col2, col3 = st.columns(3)
            with col1:
                name = st.text_input("Meno lekára")
                no_weekend = st.checkbox("Bez víkendových služieb")
            with col2:
                default_weekday = st.number_input(
                    "Def. max nočných — pracovný deň", min_value=0, step=1, value=5,
                    help="0 = bez limitu")
                default_weekend = st.number_input(
                    "Def. max nočných — víkend/sviatok", min_value=0, step=1, value=2,
                    help="0 = bez limitu")
            with col3:
                st.markdown("&nbsp;")
                st.markdown("**0 = bez limitu**")

            if st.form_submit_button("💾 Uložiť lekára"):
                if name:
                    dd[name] = {
                        "max_weekday_shifts": int(default_weekday),
                        "max_weekend_shifts": 0 if no_weekend else int(default_weekend),
                        "no_weekend_shifts": no_weekend,
                    }
                    save_doctors(dd)
                    st.success(f"Lekár **{name}** uložený.")
                else:
                    st.error("Zadajte meno lekára.")

        if dd:
            st.subheader("Zoznam lekárov")
            for doctor in list(dd.keys()):
                info = dd[doctor]
                col1, col2 = st.columns([6, 1])
                with col1:
                    wd = f"max {info['max_weekday_shifts']} pracovných" if info["max_weekday_shifts"] > 0 else "pracovné bez limitu"
                    if info["no_weekend_shifts"]:
                        we = "❌ bez víkendov"
                    elif info["max_weekend_shifts"] > 0:
                        we = f"max {info['max_weekend_shifts']} víkend/sviatok"
                    else:
                        we = "víkend bez limitu"
                    st.write(f"**{doctor}** — {wd} | {we}")
                with col2:
                    if st.button("🗑️ Odstrániť", key=f"del_{doctor}"):
                        del dd[doctor]
                        save_doctors(dd)
                        st.rerun()
        else:
            st.info("Zatiaľ žiadni lekári. Pridajte ich vyššie.")

    # ── TAB 2: Schedule generation ────────────────────────────────────────────
    with tab2:
        st.header("Generovanie mesačného rozvrhu")
        dd = st.session_state["doctors_defaults"]

        if not dd:
            st.warning("Najprv pridajte lekárov v záložke **Správa lekárov**.")
            return

        today = datetime.today()
        col1, col2 = st.columns(2)
        with col1:
            selected_year = st.selectbox("Rok", list(range(today.year, today.year + 5)))
        with col2:
            selected_month = st.selectbox("Mesiac", list(range(1, 13)), index=today.month - 1)

        holidays = get_public_holidays(selected_year)
        num_days = get_num_days(selected_year, selected_month)

        # Holiday source info
        api_ok = True
        try:
            r = requests.get(f"https://date.nager.at/api/v3/PublicHolidays/{selected_year}/SK", timeout=3)
            api_ok = r.status_code == 200
        except Exception:
            api_ok = False
        if api_ok:
            st.caption(f"✅ Štátne sviatky načítané z internetu ({len(holidays)} sviatkov v {selected_year})")
        else:
            st.caption("⚠️ Sviatky z internetu nedostupné — použitý pevný zoznam (bez pohyblivej Veľkej noci)")

        st.subheader("Mesačné nastavenia lekárov")
        st.caption("Defaulty sú z profilu. Upravte pre tento mesiac ak treba.")

        monthly_settings = {}
        for doctor, defaults in dd.items():
            with st.expander(f"⚙️ {doctor}"):
                c1, c2, c3 = st.columns(3)
                with c1:
                    max_wd = st.number_input("Max pracovných nočných", min_value=0, step=1,
                                             value=defaults["max_weekday_shifts"], key=f"wd_{doctor}")
                    max_we = st.number_input("Max víkend/sviatok nočných", min_value=0, step=1,
                                             value=defaults["max_weekend_shifts"], key=f"we_{doctor}")
                    no_we = st.checkbox("Bez víkendových", value=defaults["no_weekend_shifts"], key=f"nowe_{doctor}")
                with c2:
                    excl = st.multiselect("Vylúčené dni", list(range(1, num_days + 1)), key=f"excl_{doctor}")
                with c3:
                    want = st.multiselect("Požadované dni", list(range(1, num_days + 1)), key=f"want_{doctor}")

                monthly_settings[doctor] = {
                    "max_weekday_shifts": int(max_wd),
                    "max_weekend_shifts": 0 if no_we else int(max_we),
                    "no_weekend_shifts": no_we,
                    "excluded_days": excl,
                    "wanted_days": want,
                }

        if st.button("🎲 Generovať rozvrh", type="primary"):
            schedule, shift_count = generate_schedule(
                monthly_settings, selected_year, selected_month, holidays)
            st.session_state["final_schedule"] = schedule
            st.session_state["shift_count"] = shift_count
            st.session_state["sched_year"] = selected_year
            st.session_state["sched_month"] = selected_month

        if "final_schedule" in st.session_state:
            schedule = st.session_state["final_schedule"]
            shift_count = st.session_state["shift_count"]
            yr = st.session_state["sched_year"]
            mo = st.session_state["sched_month"]
            hols = get_public_holidays(yr)
            n_days = get_num_days(yr, mo)

            st.subheader("📋 Výsledný rozvrh")
            rows = []
            for day in range(1, n_days + 1):
                date_str = f"{yr}-{mo:02d}-{day:02d}"
                date_obj = datetime.strptime(date_str, "%Y-%m-%d")
                day_name = DAY_NAMES[date_obj.weekday()]
                is_special = date_obj.weekday() >= 5 or date_str in hols
                flag = "🔴" if is_special else ""
                rows.append({
                    "Deň": f"{flag} {day}. {day_name}",
                    "Dátum": date_str,
                    "Lekár": schedule.get(day, "—"),
                })
            df = pd.DataFrame(rows).set_index("Deň")
            st.dataframe(df, use_container_width=True)

            st.subheader("📊 Počet služieb")
            summary = [
                {
                    "Lekár": doc,
                    "Pracovné nočné": cnts["weekday"],
                    "Víkend/sviatok": cnts["weekend"],
                    "Celkom": cnts["weekday"] + cnts["weekend"],
                }
                for doc, cnts in shift_count.items()
            ]
            st.dataframe(pd.DataFrame(summary).set_index("Lekár"), use_container_width=True)

            unassigned = [d for d, doc in schedule.items() if doc == "—"]
            if unassigned:
                st.warning(f"⚠️ Neobsadené dni: {unassigned}")
            else:
                st.success("✅ Všetky dni obsadené.")


if __name__ == "__main__":
    main()
