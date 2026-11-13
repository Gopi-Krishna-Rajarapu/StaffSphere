"""CSV-based employee and employee-login storage."""
import csv
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
EMPLOYEE_FILE = BASE_DIR / "employees.txt"
ACCOUNT_FILE = BASE_DIR / "employee_accounts.txt"
ACCOUNT_FIELDS = ["employee_id", "email", "password_hash", "must_change_password"]

def get_employees():
    """Read current seven-column and legacy five/six-column employee rows."""
    if not EMPLOYEE_FILE.exists():
        return []
    records = []
    with EMPLOYEE_FILE.open("r", newline="", encoding="utf-8") as file:
        for row in csv.reader(file):
            if not row:
                continue
            try:
                if len(row) >= 7:
                    employee_id, name, department, role, salary, active, joined_on = row[:7]
                elif len(row) == 6:
                    employee_id, name, department, role, salary, active = row
                    joined_on = ""
                elif len(row) == 5:
                    employee_id, name, department, role, salary = row
                    active, joined_on = "true", ""
                else:
                    continue
                records.append({
                    "employee_id": int(employee_id), "name": name, "department": department,
                    "role": role, "salary": salary,
                    "active": str(active).strip().lower() in ("true", "1", "yes"),
                    "joined_on": joined_on,
                })
            except (ValueError, TypeError):
                continue
    return records

def save_employees(employees):
    with EMPLOYEE_FILE.open("w", newline="", encoding="utf-8") as file:
        writer = csv.writer(file)
        for e in employees:
            writer.writerow([e["employee_id"], e["name"], e["department"], e["role"],
                             e["salary"], str(e["active"]).lower(), e["joined_on"]])

def add_employee(employee_id, name, department, role, salary, active=True, joined_on=None):
    records = get_employees()
    records.append({"employee_id": employee_id, "name": name, "department": department,
                    "role": role, "salary": str(salary), "active": active, "joined_on": joined_on or ""})
    save_employees(records)

def get_employee_account(email):
    if not ACCOUNT_FILE.exists():
        return None
    with ACCOUNT_FILE.open("r", newline="", encoding="utf-8") as file:
        for row in csv.DictReader(file):
            if row.get("email", "").strip().lower() == email.strip().lower():
                return row
    return None

def create_employee_account(employee_id, email, password_hash):
    if get_employee_account(email):
        raise ValueError("An account already exists for this email.")
    new_file = not ACCOUNT_FILE.exists()
    with ACCOUNT_FILE.open("a", newline="", encoding="utf-8") as file:
        writer = csv.DictWriter(file, fieldnames=ACCOUNT_FIELDS)
        if new_file:
            writer.writeheader()
        writer.writerow({"employee_id": employee_id, "email": email.strip().lower(),
                         "password_hash": password_hash, "must_change_password": "true"})


def get_employee_account_by_id(employee_id):
    """Find an employee login account by employee ID."""
    if not ACCOUNT_FILE.exists():
        return None
    with ACCOUNT_FILE.open("r", newline="", encoding="utf-8") as file:
        for row in csv.DictReader(file):
            try:
                if int(row.get("employee_id", -1)) == int(employee_id):
                    return row
            except (TypeError, ValueError):
                continue
    return None


def get_all_employee_accounts():
    """Return account emails and IDs without exposing password hashes."""
    if not ACCOUNT_FILE.exists():
        return []
    accounts = []
    with ACCOUNT_FILE.open("r", newline="", encoding="utf-8") as file:
        for row in csv.DictReader(file):
            try:
                accounts.append({"employee_id": int(row["employee_id"]),
                                 "email": row["email"].strip().lower()})
            except (KeyError, TypeError, ValueError):
                continue
    return accounts


def set_employee_account(employee_id, email, password_hash):
    """Create or replace credentials for one employee."""
    email = email.strip().lower()
    accounts = get_all_employee_accounts()
    if any(a["email"] == email and a["employee_id"] != int(employee_id) for a in accounts):
        raise ValueError("This email address is already assigned to another employee.")

    rows = []
    if ACCOUNT_FILE.exists():
        with ACCOUNT_FILE.open("r", newline="", encoding="utf-8") as file:
            rows = list(csv.DictReader(file))

    found = False
    for row in rows:
        if int(row.get("employee_id", -1)) == int(employee_id):
            row["email"] = email
            row["password_hash"] = password_hash
            row["must_change_password"] = "true"
            found = True
            break
    if not found:
        rows.append({"employee_id": int(employee_id), "email": email,
                     "password_hash": password_hash, "must_change_password": "true"})

    with ACCOUNT_FILE.open("w", newline="", encoding="utf-8") as file:
        writer = csv.DictWriter(file, fieldnames=ACCOUNT_FIELDS)
        writer.writeheader()
        writer.writerows([{**row, "must_change_password": row.get("must_change_password", "false")} for row in rows])


def update_employee_password(employee_id, password_hash):
    """Update a password and clear the forced-change flag."""
    if not ACCOUNT_FILE.exists():
        raise ValueError("Employee login account not found.")
    with ACCOUNT_FILE.open("r", newline="", encoding="utf-8") as file:
        rows = list(csv.DictReader(file))
    found = False
    for row in rows:
        if int(row.get("employee_id", -1)) == int(employee_id):
            row["password_hash"] = password_hash
            row["must_change_password"] = "false"
            found = True
            break
    if not found:
        raise ValueError("Employee login account not found.")
    with ACCOUNT_FILE.open("w", newline="", encoding="utf-8") as file:
        writer = csv.DictWriter(file, fieldnames=ACCOUNT_FIELDS)
        writer.writeheader()
        writer.writerows([{**row, "must_change_password": row.get("must_change_password", "false")} for row in rows])
