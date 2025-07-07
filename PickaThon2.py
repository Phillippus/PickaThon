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

    for doctor, details in doctors.items():
        validated_wanted_days = validate_days(details['wanted_days'], num_days)
        for day in validated_wanted_days:
            if day not in details['excluded_days']:
                schedule[day].append(doctor)

    return schedule

def identify_conflicts(schedule):
    return {day: doctors for day, doctors in schedule.items() if len(doctors) > 1}



def is_weekend_or_holiday(date_str, holidays):
    date_obj = datetime.strptime(date_str, "%Y-%m-%d")
    is_weekend = date_obj.weekday() >= 5
    is_holiday = date_str in holidays
    return is_weekend or is_holiday

def reset_scheduling_process():
    for key in list(st.session_state.keys()):
        if key.startswith("conflict_") or key in ["initial_schedule", "conflicts", "final_schedule"]:
            del st.session_state[key]

def finalize_schedule(schedule, resolved_schedule, doctors, holidays, selected_year, selected_month):
    final_schedule = {}
    doctor_shift_count = {doctor: {"weekday": 0, "weekend": 0} for doctor in doctors.keys()}
    num_days = len(schedule)

    # Helper to check if a doctor is valid for a specific day
    def is_valid_doctor(day, doctor):
        is_weekend_day = is_weekend(day)
        return (
            day not in doctors[doctor]["excluded_days"]
            and (day == 1 or final_schedule.get(day - 1) != doctor)  # Prevent consecutive shifts
            and (day == num_days or final_schedule.get(day + 1) != doctor)  # Prevent consecutive shifts
            and (
                not is_weekend_day or
                (not doctors[doctor]["no_weekend_shifts"] and
                 (doctors[doctor]["max_weekend_shifts"] == 0 or
                  doctor_shift_count[doctor]["weekend"] < doctors[doctor]["max_weekend_shifts"]))
            )  # Respect weekend rules
            and (
                is_weekend_day or
                (doctors[doctor]["max_weekday_shifts"] == 0 or
                 doctor_shift_count[doctor]["weekday"] < doctors[doctor]["max_weekday_shifts"])
            )  # Respect weekday limits
        )

    # Helper to determine if a day is a weekend
    def is_weekend(day):
        day_date = datetime.strptime(f"{selected_year}-{selected_month:02d}-{day:02d}", "%Y-%m-%d")
        return day_date.weekday() >= 5

    # Step 1: Assign wanted days
    for doctor, details in doctors.items():
        for wanted_day in details["wanted_days"]:
            if wanted_day in final_schedule:
                continue  # Skip if already assigned
            if is_valid_doctor(wanted_day, doctor):
                final_schedule[wanted_day] = doctor
                shift_type = "weekend" if is_weekend(wanted_day) else "weekday"
                doctor_shift_count[doctor][shift_type] += 1

    # Step 2: Enforce Friday-Sunday priority
    for day in range(1, num_days + 1):
        day_date = datetime.strptime(f"{selected_year}-{selected_month:02d}-{day:02d}", "%Y-%m-%d")
        if day_date.weekday() == 4:  # Friday
            sunday = day + 2
            saturday = day + 1

            if sunday <= num_days:
                available_doctors = [
                    doctor for doctor in doctors
                    if is_valid_doctor(day, doctor) and is_valid_doctor(sunday, doctor)
                ]

                if available_doctors:
                    selected_doctor = random.choice(available_doctors)
                    final_schedule[day] = selected_doctor  # Assign Friday
                    final_schedule[sunday] = selected_doctor  # Assign Sunday
                    doctor_shift_count[selected_doctor]["weekend"] += 2
                else:
                    # Leave Friday-Sunday unassigned if no valid doctor
                    final_schedule[day] = "None"
                    final_schedule[saturday] = "None"
                    final_schedule[sunday] = "None"

    # Step 3: Assign remaining days
    for day in range(1, num_days + 1):
        if day not in final_schedule or final_schedule[day] is None:
            shift_type = "weekend" if is_weekend(day) else "weekday"
            available_doctors = [
                doctor for doctor in doctors
                if is_valid_doctor(day, doctor)
            ]

            if available_doctors:
                selected_doctor = random.choice(available_doctors)
                final_schedule[day] = selected_doctor
                doctor_shift_count[selected_doctor][shift_type] += 1
            else:
                final_schedule[day] = "None"  # Leave day unassigned if no valid doctor

    # Step 4: Revalidate to fix consecutive shifts
    for day in range(2, num_days + 1):
        if final_schedule.get(day) == final_schedule.get(day - 1):  # Consecutive shift detected
            available_doctors = [
                doctor for doctor in doctors
                if doctor != final_schedule.get(day - 1)
                and is_valid_doctor(day, doctor)
            ]
            if available_doctors:
                selected_doctor = random.choice(available_doctors)
                final_schedule[day] = selected_doctor
                shift_type = "weekend" if is_weekend(day) else "weekday"
                doctor_shift_count[selected_doctor][shift_type] += 1
            else:
                final_schedule[day] = "None"  # Leave day unassigned if no valid doctor

    return final_schedule

def main():
    st.set_page_config(layout="wide")
    st.title("PickaThon v 2.2 - Night Shift Scheduler")

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
        max_weekday_shifts = st.number_input("Maximum Weekday Shifts (0 = No Limit):", min_value=0, step=1)
        max_weekend_shifts = st.number_input("Maximum Weekend/Holiday Shifts (0 = No Limit):", min_value=0, step=1)
        no_weekend_shifts = st.checkbox("No Weekend Shifts", value=False)
        add_doctor = st.form_submit_button("Add Doctor")

        if add_doctor and name:
            if set(wanted_days).intersection(set(excluded_days)):
                st.error(f"Doctor {name} cannot have the same days in both 'Wanted Days' and 'Excluded Days'.")
            else:
                st.session_state["doctors"][name] = {
                    "excluded_days": excluded_days,
                    "wanted_days": wanted_days,
                    "max_weekday_shifts": max_weekday_shifts,
                    "max_weekend_shifts": 0 if no_weekend_shifts else max_weekend_shifts,
                    "no_weekend_shifts": no_weekend_shifts,
                }
                st.success(f"Doctor {name} added.")

    if st.session_state["doctors"]:
        st.write("### Doctors' Availability and Edit Options")

        for doctor, info in st.session_state["doctors"].items():
            col1, col2 = st.columns([3, 1])
            with col1:
                st.write(f"**{doctor}** | Excluded Days: {info['excluded_days']} | Wanted Days: {info['wanted_days']} | "
                         f"Max Weekday Shifts: {'No Limit' if info['max_weekday_shifts'] == 0 else info['max_weekday_shifts']} | "
                         f"Max Weekend Shifts: {'No Weekend Shifts' if info['no_weekend_shifts'] else ('No Limit' if info['max_weekend_shifts'] == 0 else info['max_weekend_shifts'])}")
            with col2:
                if st.button(f"Edit {doctor}"):
                    st.session_state["editing_doctor"] = doctor  # Track the doctor being edited

        # If editing a doctor, show the edit form
        if "editing_doctor" in st.session_state:
            doctor = st.session_state["editing_doctor"]
            info = st.session_state["doctors"][doctor]

            st.write(f"### Edit Details for {doctor}")
            edited_excluded_days = st.multiselect(
                "Excluded Days:",
                list(range(1, 32)),
                default=info["excluded_days"],
            )
            edited_wanted_days = st.multiselect(
                "Wanted Days:",
                list(range(1, 32)),
                default=info["wanted_days"],
            )
            edited_max_weekday_shifts = st.number_input(
                "Maximum Weekday Shifts (0 = No Limit):",
                min_value=0,
                value=info["max_weekday_shifts"],
            )
            edited_max_weekend_shifts = st.number_input(
                "Maximum Weekend/Holiday Shifts (0 = No Limit):",
                min_value=0,
                value=info["max_weekend_shifts"],
            )
            edited_no_weekend_shifts = st.checkbox(
                "No Weekend Shifts",
                value=info["no_weekend_shifts"],
            )

            if st.button(f"Save Changes for {doctor}"):
                if set(edited_wanted_days).intersection(set(edited_excluded_days)):
                    st.error(f"Doctor {doctor} cannot have the same days in both 'Wanted Days' and 'Excluded Days'.")
                else:
                    # Update the doctor’s details
                    st.session_state["doctors"][doctor] = {
                        "excluded_days": edited_excluded_days,
                        "wanted_days": edited_wanted_days,
                        "max_weekday_shifts": edited_max_weekday_shifts,
                        "max_weekend_shifts": 0 if edited_no_weekend_shifts else edited_max_weekend_shifts,
                        "no_weekend_shifts": edited_no_weekend_shifts,
                    }
                    st.success(f"Doctor {doctor}'s details updated.")
                    del st.session_state["editing_doctor"]  # Clear editing state

    if selected_year and selected_month:
        holidays = get_public_holidays(selected_year)

        if st.button("Generate Schedule"):
            st.session_state["initial_schedule"] = generate_initial_schedule(st.session_state["doctors"], selected_month, selected_year)
            st.session_state["conflicts"] = identify_conflicts(st.session_state["initial_schedule"])

            if not st.session_state["conflicts"]:
                st.session_state["final_schedule"] = finalize_schedule(
                    st.session_state["initial_schedule"],
                    {},
                    st.session_state["doctors"],
                    holidays,
                    selected_year,
                    selected_month
                )

        if "conflicts" in st.session_state and st.session_state["conflicts"]:
            resolved_schedule = {}
            for day, doctors in st.session_state["conflicts"].items():
                resolved_schedule[day] = st.selectbox(f"Resolve conflict for day {day}:", doctors, key=f"conflict_{day}")

            if st.button("Finalize Schedule"):
                st.session_state["final_schedule"] = finalize_schedule(
                    st.session_state["initial_schedule"],
                    resolved_schedule,
                    st.session_state["doctors"],
                    holidays,
                    selected_year,
                    selected_month
                )

        if "final_schedule" in st.session_state:
            st.write("### Final Night Shift Schedule")
            schedule_data = []

            final_schedule = st.session_state["final_schedule"]

            num_days = (pd.Timestamp(year=selected_year, month=selected_month, day=1) + pd.offsets.MonthEnd(0)).day

            for day in range(1, num_days + 1):
                date_str = f"{selected_year}-{selected_month:02d}-{day:02d}"
                day_display = f"**{day}**" if is_weekend_or_holiday(date_str, holidays) else str(day)
                doctor = final_schedule.get(day, "None")  # Use .get() to avoid KeyError
                schedule_data.append({"Date": day_display, "Doctor": doctor})

            df_schedule = pd.DataFrame(schedule_data)
            st.dataframe(df_schedule.set_index("Date"))

if __name__ == "__main__":
    main()