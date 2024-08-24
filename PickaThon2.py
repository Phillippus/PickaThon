import streamlit as st
import pandas as pd
import random
from datetime import datetime

# List of public holidays in Slovakia
public_holidays = {
    1: ["01-01", "01-06"],
    4: ["04-01"],  # Example Easter Monday, update with actual dates for each year
    5: ["05-01", "05-08"],
    7: ["07-05"],
    8: ["08-29"],
    9: ["09-01", "09-15"],
    11: ["11-01", "11-17"],
    12: ["12-24", "12-25", "12-26"]
}

def get_public_holidays(year):
    holidays = []
    for month, days in public_holidays.items():
        for day in days:
            holidays.append(f"{year}-{month:02d}-{day}")
    return holidays

def validate_days(days, num_days):
    return [day for day in days if day <= num_days]

def generate_initial_schedule(doctors, month, year):
    num_days = (pd.Timestamp(year=year, month=month, day=1) + pd.offsets.MonthEnd(0)).day
    schedule = {day: [] for day in range(1, num_days + 1)}

    # Assign doctors to their wanted days, ensuring mutual exclusivity with excluded days
    for doctor, details in doctors.items():
        validated_wanted_days = validate_days(details['wanted_days'], num_days)
        for day in validated_wanted_days:
            if day not in details['excluded_days']:
                schedule[day].append(doctor)

    return schedule

def identify_conflicts(schedule):
    conflicts = {day: doctors for day, doctors in schedule.items() if len(doctors) > 1}
    return conflicts

def resolve_conflicts(conflicts):
    resolved_schedule = {}

    for day, doctors_list in conflicts.items():
        if f"conflict_{day}" not in st.session_state:
            st.session_state[f"conflict_{day}"] = doctors_list[0]

        selected_doctor = st.selectbox(
            f"Resolve conflict for day {day}:", 
            doctors_list, 
            key=f"conflict_{day}", 
            index=doctors_list.index(st.session_state[f"conflict_{day}"])
        )
        resolved_schedule[day] = selected_doctor

    return resolved_schedule

def finalize_schedule(schedule, resolved_schedule, doctors):
    final_schedule = {}
    doctor_shift_count = {doctor: 0 for doctor in doctors.keys()}

    # Apply resolved conflicts and ensure no consecutive shifts
    for day, assigned_doctors in schedule.items():
        if day in resolved_schedule:
            final_schedule[day] = resolved_schedule[day]
            doctor_shift_count[resolved_schedule[day]] += 1
        elif len(assigned_doctors) == 1:
            final_schedule[day] = assigned_doctors[0]
            doctor_shift_count[assigned_doctors[0]] += 1
        else:
            final_schedule[day] = None

    # Distribute remaining shifts fairly, ensuring no consecutive days and respecting excluded days
    for day in range(1, len(final_schedule) + 1):
        if final_schedule[day] is None:  # If no doctor is assigned
            available_doctors = [
                doctor for doctor, count in doctor_shift_count.items()
                if doctors[doctor].get('num_shifts', float('inf')) > count
                and day not in doctors[doctor]['excluded_days']  # Respect excluded days
                and (day == 1 or final_schedule[day - 1] != doctor)
                and (day == len(final_schedule) or final_schedule[day + 1] != doctor)
            ]
            if available_doctors:
                selected_doctor = random.choice(available_doctors)
                final_schedule[day] = selected_doctor
                doctor_shift_count[selected_doctor] += 1

    # Ensure no doctor is scheduled on consecutive days
    for day in range(2, len(final_schedule)):
        if final_schedule[day] == final_schedule[day - 1]:
            final_schedule[day] = None  # Unassign this day to avoid consecutive shifts

    return final_schedule

def is_weekend_or_holiday(date_str, holidays):
    date_obj = datetime.strptime(date_str, "%Y-%m-%d")
    is_weekend = date_obj.weekday() >= 5
    is_holiday = date_str in holidays
    return is_weekend or is_holiday

def reset_scheduling_process():
    for key in list(st.session_state.keys()):
        if key.startswith("conflict_") or key in ["initial_schedule", "conflicts", "final_schedule"]:
            del st.session_state[key]

def main():
    st.set_page_config(layout="wide")
    st.title("PickaThon v 1.0 - Night Shift Scheduler")

    today = datetime.today()
    year_range = list(range(today.year, today.year + 10))

    selected_year = st.selectbox("Year", year_range, index=year_range.index(st.session_state.get("selected_year", today.year)), on_change=reset_scheduling_process)
    selected_month = st.selectbox("Month", list(range(1, 13)), index=(st.session_state.get("selected_month", today.month) - 1), on_change=reset_scheduling_process)

    st.session_state["selected_year"] = selected_year
    st.session_state["selected_month"] = selected_month

    if "doctors" not in st.session_state:
        st.session_state["doctors"] = {}

    with st.form("doctor_input_form", clear_on_submit=True):
        name = st.text_input("Doctor's Name:")
        excluded_days = st.multiselect("Excluded Days:", list(range(1, 32)))
        wanted_days = st.multiselect("Wanted Days:", list(range(1, 32)))
        num_shifts = st.number_input("Maximum Number of Night Shifts:", min_value=0, max_value=31, step=1)
        add_doctor = st.form_submit_button("Add Doctor")

        if add_doctor and name:
            if set(wanted_days).intersection(set(excluded_days)):
                st.error(f"Doctor {name} cannot have the same days in both 'Wanted Days' and 'Excluded Days'.")
            else:
                st.session_state["doctors"][name] = {
                    "excluded_days": excluded_days,
                    "wanted_days": wanted_days,
                    "num_shifts": num_shifts if num_shifts > 0 else float("inf"),
                }
                st.success(f"Doctor {name} added.")

    if st.session_state["doctors"]:
        st.write("### Doctors' Availability")
        for doctor, info in st.session_state["doctors"].items():
            st.write(f"- **{doctor}**: Excluded Days: {info['excluded_days']}, Wanted Days: {info['wanted_days']}, Maximum Shifts: {'No Limit' if info['num_shifts'] == float('inf') else info['num_shifts']}")

    if selected_year and selected_month:
        holidays = get_public_holidays(selected_year)

        if st.button("Generate Schedule"):
            st.session_state["initial_schedule"] = generate_initial_schedule(st.session_state["doctors"], selected_month, selected_year)
            st.session_state["conflicts"] = identify_conflicts(st.session_state["initial_schedule"])

            # Automatically finalize schedule if there are no conflicts
            if not st.session_state["conflicts"]:
                st.session_state["final_schedule"] = finalize_schedule(st.session_state["initial_schedule"], {}, st.session_state["doctors"])

        if "conflicts" in st.session_state and st.session_state["conflicts"]:
            st.write("### Conflict Resolution")
            resolved_schedule = resolve_conflicts(st.session_state["conflicts"])

            if st.button("Finalize Schedule"):
                st.session_state["final_schedule"] = finalize_schedule(st.session_state["initial_schedule"], resolved_schedule, st.session_state["doctors"])

        if "final_schedule" in st.session_state:
            st.write("### Final Night Shift Schedule")
            schedule_data = []

            final_schedule = st.session_state["final_schedule"]

            for day in range(1, len(final_schedule) + 1):
                date_str = f"{selected_year}-{selected_month:02d}-{day:02d}"
                day_display = f"**{day}**" if is_weekend_or_holiday(date_str, holidays) else str(day)
                schedule_data.append({"Date": day_display, "Doctor": final_schedule[day] if final_schedule[day] else "None"})

            df_schedule = pd.DataFrame(schedule_data)
            st.dataframe(df_schedule.set_index("Date"))

if __name__ == "__main__":
    main()