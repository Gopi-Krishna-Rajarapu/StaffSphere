"""Employee Payroll System - a small Python + FastAPI learning project."""
from datetime import date, datetime
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from html import escape
from typing import Optional
from pathlib import Path
import os, hashlib, hmac, secrets, re, csv, json
from dotenv import load_dotenv
from google import genai
from google.genai import types

load_dotenv()

from fastapi import FastAPI, Form, HTTPException, Request, Depends
from fastapi.responses import HTMLResponse, RedirectResponse, JSONResponse
from starlette.middleware.sessions import SessionMiddleware
from fastapi.templating import Jinja2Templates

from employee_storage import (add_employee as save_employee, get_employees as load_employees, save_employees, create_employee_account, get_employee_account, get_employee_account_by_id, get_all_employee_accounts, set_employee_account, update_employee_password)

BASE_DIR = Path(__file__).resolve().parent
templates = Jinja2Templates(directory=str(BASE_DIR / "templates"))
app = FastAPI(title="StaffSphere", description="Smart Workforce Management Platform", version="3.0.0")

# Local-demo defaults only. Set these environment variables on deployment.
SESSION_SECRET = os.getenv("SESSION_SECRET", "local-learning-secret-change-before-deployment")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "").strip()
GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-3.5-flash")
if not GEMINI_API_KEY:
    raise RuntimeError("GEMINI_API_KEY is missing")
HR_EMAIL = os.getenv("HR_EMAIL", "hr@company.com").strip().lower()
HR_PASSWORD = os.getenv("HR_PASSWORD", "HR@12345")
app.add_middleware(SessionMiddleware, secret_key=SESSION_SECRET, same_site="lax", https_only=False)

def hash_password(password: str) -> str:
    salt = secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, 310_000)
    return salt.hex() + "$" + digest.hex()

def generate_temporary_password(length: int = 12) -> str:
    """Generate a random temporary password for an HR-created account."""
    alphabet = "ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz23456789!@#$%"
    return "".join(secrets.choice(alphabet) for _ in range(length))


def verify_password(password: str, stored_hash: str) -> bool:
    try:
        salt_hex, digest_hex = stored_hash.split("$", 1)
        digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), bytes.fromhex(salt_hex), 310_000)
        return hmac.compare_digest(digest.hex(), digest_hex)
    except (ValueError, TypeError):
        return False

def get_session_user(request: Request):
    return request.session.get("user")

def require_login(request: Request):
    user = get_session_user(request)
    if not user:
        raise HTTPException(status_code=401, detail="Please log in first.")
    return user

def require_hr(request: Request):
    user = require_login(request)
    if user.get("role") != "hr":
        raise HTTPException(status_code=403, detail="HR administrator access required.")
    return user

def require_employee(request: Request):
    user = require_login(request)
    if user.get("role") != "employee":
        raise HTTPException(status_code=403, detail="Employee access required.")
    return user


# Employee details are persisted in employees.txt. These lists are used while the app runs.
employees = []
PAYROLL_FILE = BASE_DIR / "payroll_records.txt"
payroll_records = []

def read_payroll_records():
    if not PAYROLL_FILE.exists():
        return []
    records = []
    with PAYROLL_FILE.open("r", newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            try:
                records.append({
                    "payroll_id": int(row["payroll_id"]), "employee_id": int(row["employee_id"]),
                    "employee_name": row["employee_name"], "department": row["department"],
                    "role": row.get("role", ""), "month": row["month"],
                    **{key: money(row[key]) for key in ("basic", "allowances", "bonus", "gross", "deductions", "net")},
                    "created_at": datetime.fromisoformat(row["created_at"]),
                })
            except (KeyError, ValueError, TypeError):
                continue
    return records

def write_payroll_records(records):
    fields = ["payroll_id", "employee_id", "employee_name", "department", "role", "month",
              "basic", "allowances", "bonus", "gross", "deductions", "net", "created_at"]
    with PAYROLL_FILE.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fields)
        writer.writeheader()
        for r in records:
            writer.writerow({**{k: str(r[k]) for k in fields if k not in ("created_at",)},
                             "created_at": r["created_at"].isoformat(timespec="seconds")})

payroll_records = []
next_employee_id = 1
next_payroll_id = 1
LEAVE_FILE = BASE_DIR / "leave_records.txt"
DEFAULT_ANNUAL_LEAVE = 20

def read_leave_records():
    if not LEAVE_FILE.exists():
        return []
    with LEAVE_FILE.open("r", newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))

def write_leave_records(records):
    fields = ["leave_id", "employee_id", "employee_name", "start_date", "end_date", "days", "reason", "status", "applied_on"]
    with LEAVE_FILE.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fields)
        writer.writeheader()
        writer.writerows(records)

def valid_name(value):
    return bool(re.fullmatch(r"[A-Za-z][A-Za-z .'-]{0,78}[A-Za-z]", value.strip()))

def valid_label(value):
    clean = value.strip()
    return 2 <= len(clean) <= 60 and bool(re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9 &().,'/-]*", clean))

def leave_days_used(employee_id):
    return sum(int(r["days"]) for r in read_leave_records()
               if int(r["employee_id"]) == employee_id and r["status"] == "Approved")



def money(value) -> Decimal:
    """Convert a value to a 2-decimal-place Decimal safely."""
    try:
        amount = Decimal(str(value)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    except (InvalidOperation, ValueError, TypeError):
        raise ValueError("Enter a valid numeric amount.")
    if not amount.is_finite() or amount < 0:
        raise ValueError("Amounts must be valid, non-negative numbers.")
    return amount


# Load persisted payroll only after the money() validator is defined.
payroll_records = read_payroll_records()
next_payroll_id = max((r["payroll_id"] for r in payroll_records), default=0) + 1


class Employee:
    """Represent one employee."""
    def __init__(self, employee_id: int, name: str, department: str, role: str,
                 monthly_basic: Decimal, active: bool = True, joined_on: Optional[date] = None):
        self.employee_id = employee_id
        self.name = name.strip()
        self.department = department.strip()
        self.role = role.strip()
        self.monthly_basic = monthly_basic
        self.joined_on = joined_on or date.today()
        self.active = active


class PayrollCalculator:
    """Calculate sample monthly salary values."""
    def calculate(self, basic, allowances, bonus, deductions):
        basic, allowances, bonus, deductions = map(money, (basic, allowances, bonus, deductions))
        gross = basic + allowances + bonus
        if deductions > gross:
            raise ValueError("Deductions cannot be greater than gross salary.")
        return {
            "basic": basic,
            "allowances": allowances,
            "bonus": bonus,
            "gross": gross,
            "deductions": deductions,
            "net": gross - deductions,
        }


calculator = PayrollCalculator()


def employee_file_record(employee):
    return {
        "employee_id": employee.employee_id,
        "name": employee.name,
        "department": employee.department,
        "role": employee.role,
        "salary": str(employee.monthly_basic),
        "active": employee.active,
        "joined_on": employee.joined_on.isoformat(),
    }


def persist_employees():
    save_employees([employee_file_record(employee) for employee in employees])


def load_saved_employees():
    """Load employee details and their active status when the app starts."""
    global next_employee_id
    for record in load_employees():
        try:
            joined_on = date.fromisoformat(record["joined_on"]) if record.get("joined_on") else date.today()
            employee = Employee(
                record["employee_id"], record["name"], record["department"],
                record["role"], money(record["salary"]), record["active"], joined_on,
            )
            employees.append(employee)
        except (ValueError, TypeError, KeyError):
            continue
    if employees:
        next_employee_id = max(employee.employee_id for employee in employees) + 1


load_saved_employees()


def page(content: str, title: str = "StaffSphere") -> HTMLResponse:
    """Return a responsive HTML page."""
    return HTMLResponse(f'''<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>{escape(title)}</title>
<style>
*{{box-sizing:border-box}} body{{margin:0;background:#f3f6fb;color:#172033;font:15px Arial,sans-serif}}
header{{background:#173b67;color:white;padding:22px max(20px,calc((100% - 1080px)/2))}} header h1{{margin:0 0 8px;font-size:25px}}
nav{{display:flex;gap:16px;flex-wrap:wrap;margin-top:12px}} nav a{{color:#dceaff;text-decoration:none}}
main{{max-width:1080px;margin:26px auto;padding:0 18px}} .card{{background:white;border:1px solid #e1e7f0;border-radius:12px;padding:20px;margin-bottom:18px;box-shadow:0 3px 12px #17203308}}
.grid{{display:grid;grid-template-columns:repeat(auto-fit,minmax(210px,1fr));gap:14px}} label{{display:block;font-weight:600;margin:10px 0 5px}}
input,select{{width:100%;padding:10px;border:1px solid #cbd5e1;border-radius:7px;font:inherit}}
button,.button{{display:inline-block;border:0;border-radius:7px;padding:9px 12px;background:#1765b3;color:white;font-weight:600;text-decoration:none;cursor:pointer;margin:3px}}
button.secondary{{background:#64748b}} .muted{{color:#64748b}} .stats{{font-size:25px;font-weight:700;margin-top:8px}} .message{{padding:12px;background:#fff7df;border-radius:8px}}
table{{border-collapse:collapse;width:100%;margin-top:12px}} th,td{{padding:10px;text-align:left;border-bottom:1px solid #e2e8f0}} th{{background:#f8fafc}}
.table-wrap{{overflow-x:auto}} .status-active{{color:#166534;font-weight:700}} .status-inactive{{color:#9f1239;font-weight:700}}
footer{{text-align:center;color:#64748b;padding:20px}} @media(max-width:600px){{header h1{{font-size:21px}}th,td{{padding:8px;font-size:13px}}}}
</style></head><body><header><h1>StaffSphere</h1>
<div>Smart Workforce Management Platform</div><nav>
<a href="/">Dashboard</a><a href="/employees">Employees</a><a href="/employees/new">Add Employee</a><a href="/hr/accounts">Employee Login Accounts</a>
<a href="/payroll/new">Calculate Payroll</a><a href="/payroll/history">Payroll History</a><a href="/hr/leaves">Leave Management</a><a href="/docs">API Docs</a><a href="/logout">Logout</a>
</nav></header><main>{content}</main>
<footer>Employee records: employees.txt · Payroll history: payroll_records.txt · Leave requests: leave_records.txt</footer></body></html>''')


def employee_by_id(employee_id: int) -> Optional[Employee]:
    for employee in employees:
        if employee.employee_id == employee_id:
            return employee
    return None




@app.get("/login", response_class=HTMLResponse)
def login_page(request: Request):
    if get_session_user(request):
        return RedirectResponse("/", status_code=303)
    return templates.TemplateResponse(request=request, name="login.html", context={"error": None})

@app.post("/login", response_class=HTMLResponse)
def login(request: Request, role: str = Form(...), email: str = Form(...), password: str = Form(...)):
    email = email.strip().lower()
    if role == "hr" and hmac.compare_digest(email, HR_EMAIL) and hmac.compare_digest(password, HR_PASSWORD):
        request.session.clear()
        request.session["user"] = {"role": "hr", "email": HR_EMAIL}
        return RedirectResponse("/", status_code=303)
    if role == "employee":
        account = get_employee_account(email)
        if account and verify_password(password, account["password_hash"]):
            employee = employee_by_id(int(account["employee_id"]))
            if employee and employee.active:
                request.session.clear()
                request.session["user"] = {"role": "employee", "email": email, "employee_id": employee.employee_id}
                if str(account.get("must_change_password", "false")).lower() == "true":
                    return RedirectResponse("/employee/change-password", status_code=303)
                return RedirectResponse("/employee", status_code=303)
    return templates.TemplateResponse(request=request, name="login.html",
        context={"error": "Invalid credentials, or the employee account is inactive."}, status_code=401)

@app.get("/register", response_class=HTMLResponse)
def register_page(request: Request):
    if get_session_user(request):
        return RedirectResponse("/", status_code=303)
    return templates.TemplateResponse(request=request, name="register.html", context={"error": None})

@app.post("/register", response_class=HTMLResponse)
def register_employee(request: Request, employee_id: int = Form(...), name: str = Form(...),
                      email: str = Form(...), password: str = Form(...), confirm_password: str = Form(...)):
    if get_session_user(request):
        return RedirectResponse("/", status_code=303)
    employee = employee_by_id(employee_id)
    email = email.strip().lower()
    error = None
    if not valid_name(name):
        error = "Enter a valid name using letters, spaces, periods or hyphens."
    elif employee is None or employee.name.casefold() != name.strip().casefold():
        error = "Employee ID and name do not match an employee record. Contact HR."
    elif not employee.active:
        error = "Inactive employees cannot register."
    elif len(password) < 8:
        error = "Password must contain at least 8 characters."
    elif password != confirm_password:
        error = "Passwords do not match."
    elif get_employee_account(email):
        error = "An account already exists for this email."
    if error:
        return templates.TemplateResponse(request=request, name="register.html", context={"error": error}, status_code=400)
    create_employee_account(employee_id, email, hash_password(password))
    request.session.clear()
    request.session["user"] = {"role": "employee", "email": email, "employee_id": employee_id}
    return RedirectResponse("/employee", status_code=303)

@app.get("/employee/change-password", response_class=HTMLResponse)
def change_password_page(request: Request):
    user = require_employee(request)
    return page("""<section class='card'><h2>Set your own password</h2>
<p class='message'>For security, change the temporary password before using your employee account.</p>
<form method='post' action='/employee/change-password'>
<label>New password</label><input type='password' name='new_password' minlength='10' maxlength='128' required autocomplete='new-password'>
<label>Confirm new password</label><input type='password' name='confirm_password' minlength='10' maxlength='128' required autocomplete='new-password'>
<button type='submit'>Update password</button></form></section>""")

@app.post("/employee/change-password")
def change_password(request: Request, new_password: str = Form(...), confirm_password: str = Form(...)):
    user = require_employee(request)
    if len(new_password) < 10 or len(new_password) > 128 or not re.search(r"[A-Za-z]", new_password) or not re.search(r"[0-9]", new_password):
        return page("<section class='card'><h2>Password not updated</h2><p class='message'>Use 10–128 characters with at least one letter and one number.</p><a class='button' href='/employee/change-password'>Try again</a></section>")
    if new_password != confirm_password:
        return page("<section class='card'><h2>Password not updated</h2><p class='message'>The passwords do not match.</p><a class='button' href='/employee/change-password'>Try again</a></section>")
    update_employee_password(user["employee_id"], hash_password(new_password))
    return RedirectResponse("/employee", status_code=303)

@app.get("/logout")
def logout(request: Request):
    request.session.clear()
    return RedirectResponse("/login", status_code=303)

def employee_payroll_rows(employee_id):
    own_records = [r for r in payroll_records if int(r["employee_id"]) == int(employee_id)]
    if not own_records:
        return "<p class='muted'>No payroll history is available for your employee account yet.</p>"
    rows = "".join(f"<tr><td>{escape(r['month'])}</td><td>₹{r['basic']:.2f}</td><td>₹{r['allowances']:.2f}</td><td>₹{r['bonus']:.2f}</td><td>₹{r['gross']:.2f}</td><td>₹{r['deductions']:.2f}</td><td><strong>₹{r['net']:.2f}</strong></td></tr>" for r in sorted(own_records, key=lambda x: x["month"], reverse=True))
    return f"<div class='table-wrap'><table><thead><tr><th>Month</th><th>Basic</th><th>Allowances</th><th>Bonus</th><th>Gross</th><th>Deductions</th><th>Net pay</th></tr></thead><tbody>{rows}</tbody></table></div>"

@app.get("/employee", response_class=HTMLResponse)
def employee_portal(request: Request):
    user = require_employee(request)
    employee = employee_by_id(user["employee_id"])
    if not employee or not employee.active:
        request.session.clear()
        return RedirectResponse("/login", status_code=303)
    return page(f"""<section class="card"><h2>Employee Self-Service</h2>
<p>Welcome, {escape(employee.name)}.</p>
<p><b>Employee ID:</b> {employee.employee_id}</p>
<p><b>Department:</b> {escape(employee.department)}</p>
<p><b>Role:</b> {escape(employee.role)}</p>
<p><b>Basic monthly salary:</b> ₹{employee.monthly_basic:.2f}</p>
<p><b>Joining date:</b> {employee.joined_on.isoformat()}</p>
<p><b>Annual leave allowance:</b> {DEFAULT_ANNUAL_LEAVE} days</p>
<p><b>Approved leave used:</b> {leave_days_used(employee.employee_id)} days</p>
<p><b>Remaining leave:</b> {max(0, DEFAULT_ANNUAL_LEAVE - leave_days_used(employee.employee_id))} days</p>
<p><a class="button" href="/employee/assistant">Gemini 3.5 AI Leave Assistant</a></p>
<h3>Apply for leave</h3><form method="post" action="/employee/leaves/apply">
<div class="grid"><div><label>Start date *</label><input type="date" name="start_date" min="{date.today().isoformat()}" required></div>
<div><label>End date *</label><input type="date" name="end_date" min="{date.today().isoformat()}" required></div></div>
<label>Reason *</label><input name="reason" minlength="5" maxlength="250" required>
<button type="submit">Submit leave request</button></form>
<h3>My leave requests</h3>{employee_leave_rows(employee.employee_id)}
<h3>My Payroll History</h3>{employee_payroll_rows(employee.employee_id)}
<a class="button" href="/logout">Logout</a></section>""", "Employee Portal")

def employee_leave_rows(employee_id):
    records = [r for r in read_leave_records() if int(r["employee_id"]) == employee_id]
    if not records:
        return "<p class='muted'>No leave requests submitted yet.</p>"
    rows = "".join(f"<tr><td>{r['start_date']}</td><td>{r['end_date']}</td><td>{r['days']}</td><td>{escape(r['reason'])}</td><td>{escape(r['status'])}</td></tr>" for r in reversed(records))
    return f"<div class='table-wrap'><table><thead><tr><th>From</th><th>To</th><th>Days</th><th>Reason</th><th>Status</th></tr></thead><tbody>{rows}</tbody></table></div>"

def create_leave_request(employee, start_date: str, end_date: str, reason: str):
    """Shared leave validation and persistence used by the form and AI assistant."""
    start, end = date.fromisoformat(start_date), date.fromisoformat(end_date)
    days = (end - start).days + 1
    if start < date.today() or end < start:
        raise ValueError("Choose valid future dates and ensure the end date is not before the start date.")
    if days > 30:
        raise ValueError("A single leave request cannot exceed 30 calendar days.")
    clean_reason = re.sub(r"\s+", " ", reason).strip()
    if not 5 <= len(clean_reason) <= 250 or not re.search(r"[A-Za-z0-9]", clean_reason):
        raise ValueError("Enter a meaningful leave reason between 5 and 250 characters.")
    records = read_leave_records()
    reserved_days = sum(int(r["days"]) for r in records
                        if int(r["employee_id"]) == employee.employee_id and r["status"] in ("Approved", "Pending"))
    if reserved_days + days > DEFAULT_ANNUAL_LEAVE:
        raise ValueError("This request exceeds your remaining annual leave balance, including pending requests.")
    if any(int(r["employee_id"]) == employee.employee_id and r["status"] == "Pending"
           and not (end < date.fromisoformat(r["start_date"]) or start > date.fromisoformat(r["end_date"])) for r in records):
        raise ValueError("You already have a pending request for overlapping dates.")
    next_id = max([int(r["leave_id"]) for r in records], default=0) + 1
    record = {"leave_id": next_id, "employee_id": employee.employee_id, "employee_name": employee.name,
        "start_date": start.isoformat(), "end_date": end.isoformat(), "days": days,
        "reason": clean_reason, "status": "Pending", "applied_on": date.today().isoformat()}
    records.append(record)
    write_leave_records(records)
    return record

@app.post("/employee/leaves/apply", response_class=HTMLResponse)
def apply_leave(request: Request, start_date: str = Form(...), end_date: str = Form(...), reason: str = Form(...)):
    user = require_employee(request)
    employee = employee_by_id(user["employee_id"])
    try:
        create_leave_request(employee, start_date, end_date, reason)
    except ValueError as exc:
        return page(f"<section class='card'><h2>Leave request not submitted</h2><p class='message'>{escape(str(exc))}</p><a class='button' href='/employee'>Back</a></section>")
    return RedirectResponse("/employee", status_code=303)

@app.get("/employee/assistant", response_class=HTMLResponse)
def employee_assistant_page(request: Request):
    user = require_employee(request)
    employee = employee_by_id(user["employee_id"])
    if not employee or not employee.active:
        request.session.clear()
        return RedirectResponse("/login", status_code=303)
    return page("""<section class='card'><h2>StaffSphere AI Leave Assistant</h2>
<p class='muted'>Describe your leave request or ask about your own leave status. The assistant will prepare a request for your confirmation before submitting it.</p>
<div id='chat' style='height:340px;overflow:auto;border:1px solid #dbe3ee;border-radius:10px;padding:12px;background:#f8fafc;margin:14px 0'>
<div class='message'>Hello! I can help you apply for leave or check your leave status. For example: “Apply for leave from 2026-11-16 to 2026-11-18 because of a family function.”</div></div>
<form id='chat-form'><label for='message'>Your message</label><input id='message' autocomplete='off' maxlength='1500' placeholder='Type your leave instruction...' required>
<button id='send' type='submit'>Send message</button></form>
<div id='confirm-area'></div><p><a class='button secondary' href='/employee'>Back to Employee Portal</a></p></section>
<script>
const chat=document.getElementById('chat'), form=document.getElementById('chat-form'), input=document.getElementById('message'), send=document.getElementById('send'), confirmArea=document.getElementById('confirm-area');
function bubble(who,text){const el=document.createElement('p');el.style.cssText='padding:10px 12px;border-radius:9px;background:'+(who==='You'?'#e0edff':'#e7f7ed')+';white-space:pre-wrap';const b=document.createElement('b');b.textContent=who+': ';el.appendChild(b);el.appendChild(document.createTextNode(text));chat.appendChild(el);chat.scrollTop=chat.scrollHeight;}
form.addEventListener('submit',async e=>{e.preventDefault();const message=input.value.trim();if(!message)return;bubble('You',message);input.value='';send.disabled=true;send.textContent='Thinking...';confirmArea.replaceChildren();try{const r=await fetch('/api/employee/assistant/chat',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({message})});const data=await r.json();if(!r.ok)throw new Error(data.detail||'Unable to process your message.');bubble('Assistant',data.reply);if(data.pending_confirmation){const box=document.createElement('div');box.className='message';const info=document.createElement('p');info.textContent='Confirm leave application: '+data.pending_confirmation.start_date+' to '+data.pending_confirmation.end_date+' ('+data.pending_confirmation.days+' days). Reason: '+data.pending_confirmation.reason;box.appendChild(info);const yes=document.createElement('button');yes.textContent='Confirm and submit';yes.onclick=()=>submitDecision(true);const no=document.createElement('button');no.className='secondary';no.textContent='Cancel';no.onclick=()=>submitDecision(false);box.append(yes,no);confirmArea.appendChild(box);}}catch(err){bubble('Assistant',err.message);}finally{send.disabled=false;send.textContent='Send message';}});
async function submitDecision(confirm){const r=await fetch('/api/employee/assistant/confirm',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({confirm})});const data=await r.json();bubble('Assistant',data.reply||data.detail||'Request completed.');confirmArea.replaceChildren();}
</script>""", "StaffSphere AI Leave Assistant")

@app.post("/api/employee/assistant/chat")
async def employee_assistant_chat(request: Request):
    user = require_employee(request)
    employee = employee_by_id(user["employee_id"])
    if not employee or not employee.active:
        request.session.clear()
        raise HTTPException(status_code=401, detail="Your employee account is inactive. Please contact HR.")
    if not GEMINI_API_KEY:
        raise HTTPException(status_code=503, detail="AI assistant is not configured. Add GEMINI_API_KEY to your environment.")

    payload = await request.json()
    message = str(payload.get("message", "")).strip()
    if not message or len(message) > 1500:
        raise HTTPException(status_code=400, detail="Enter a message of up to 1500 characters.")

    client = genai.Client(api_key=GEMINI_API_KEY)
    tool = types.Tool(function_declarations=[
        types.FunctionDeclaration(
            name="prepare_leave_request",
            description="Prepare a leave request for the currently authenticated employee. Never submit it. Use only when start date, end date and reason are known.",
            parameters=types.Schema(
                type=types.Type.OBJECT,
                properties={
                    "start_date": types.Schema(type=types.Type.STRING, description="Start date in YYYY-MM-DD format"),
                    "end_date": types.Schema(type=types.Type.STRING, description="End date in YYYY-MM-DD format"),
                    "reason": types.Schema(type=types.Type.STRING, description="Reason for leave")
                },
                required=["start_date", "end_date", "reason"]
            )
        ),
        types.FunctionDeclaration(
            name="get_my_leave_status",
            description="Read leave requests and remaining leave balance for the currently authenticated employee only. Takes no arguments.",
            parameters=types.Schema(type=types.Type.OBJECT, properties={})
        )
    ])
    instructions = (
        "You are StaffSphere's employee leave assistant. Help only with leave applications, leave balances, and leave status. "
        "Use function tools for status queries and to prepare leave requests. Never claim a request is submitted unless the backend confirms it. "
        "Preparing a request is not submitting it: the employee must separately confirm using the website confirmation button. "
        "Never ask for or accept employee IDs; identity comes from the authenticated session. Use ISO dates YYYY-MM-DD. "
        "If dates or a meaningful reason are missing, ask a concise follow-up. Do not approve or reject leave; only HR can do that. "
        f"Today is {date.today().isoformat()}. The authenticated employee's first name is {employee.name.split()[0]}. "
        "Do not reveal other employees' information."
    )
    contents = [types.Content(role="user", parts=[types.Part(text=message)])]
    config = types.GenerateContentConfig(system_instruction=instructions, tools=[tool], temperature=0.2)
    pending = None

    try:
        response = client.models.generate_content(model=GEMINI_MODEL, contents=contents, config=config)
        # Handle a bounded number of tool rounds; tools are executed only by this backend.
        for _ in range(4):
            function_calls = response.function_calls or []
            if not function_calls:
                break
            contents.append(response.candidates[0].content)
            function_response_parts = []
            for call in function_calls:
                args = dict(call.args or {})
                if call.name == "prepare_leave_request":
                    try:
                        start_date = date.fromisoformat(str(args["start_date"]))
                        end_date = date.fromisoformat(str(args["end_date"]))
                        days = (end_date - start_date).days + 1
                        reason = re.sub(r"\s+", " ", str(args["reason"])).strip()
                        if start_date < date.today() or end_date < start_date or days > 30:
                            raise ValueError("Choose valid future dates with a maximum duration of 30 days.")
                        if not 5 <= len(reason) <= 250 or not re.search(r"[A-Za-z0-9]", reason):
                            raise ValueError("Enter a meaningful leave reason between 5 and 250 characters.")
                        pending = {"start_date": start_date.isoformat(), "end_date": end_date.isoformat(), "days": days, "reason": reason}
                        request.session["pending_ai_leave"] = pending
                        tool_result = {"prepared": True, "request": pending, "note": "Not submitted. Waiting for explicit employee confirmation."}
                    except (ValueError, KeyError, TypeError) as exc:
                        tool_result = {"prepared": False, "error": str(exc)}
                elif call.name == "get_my_leave_status":
                    own = [r for r in read_leave_records() if int(r["employee_id"]) == int(user["employee_id"])]
                    tool_result = {
                        "remaining_annual_leave": max(0, DEFAULT_ANNUAL_LEAVE - leave_days_used(int(user["employee_id"]))),
                        "requests": [{k: r[k] for k in ("start_date", "end_date", "days", "reason", "status")} for r in own[-10:]]
                    }
                else:
                    tool_result = {"error": "Unknown function."}
                function_response_parts.append(types.Part.from_function_response(name=call.name, response=tool_result))
            contents.append(types.Content(role="user", parts=function_response_parts))
            response = client.models.generate_content(model=GEMINI_MODEL, contents=contents, config=config)

        reply = response.text or ("I prepared your leave request. Please review and confirm it." if pending else "Could you provide the leave dates and reason?")
        return {"reply": reply, "pending_confirmation": pending}
    except HTTPException:
        raise
    except Exception as exc:
        # Avoid exposing API keys, request headers, or provider internals to the browser.
        print(f"Gemini assistant error: {type(exc).__name__}: {exc}")
        raise HTTPException(status_code=502, detail="The AI service could not process your request. Check the server logs and Gemini API configuration.")
    finally:
        client.close()

@app.post("/api/employee/assistant/confirm")
async def employee_assistant_confirm(request: Request):
    user = require_employee(request)
    employee = employee_by_id(user["employee_id"])
    if not employee or not employee.active:
        raise HTTPException(status_code=401, detail="Your employee account is inactive.")
    payload = await request.json()
    pending = request.session.get("pending_ai_leave")
    if not pending:
        raise HTTPException(status_code=400, detail="There is no prepared leave request to confirm.")
    request.session.pop("pending_ai_leave", None)
    if payload.get("confirm") is not True:
        return {"reply":"Your leave request was cancelled. Nothing was submitted."}
    try:
        record = create_leave_request(employee, pending["start_date"], pending["end_date"], pending["reason"])
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return {"reply":f"Leave request #{record['leave_id']} submitted successfully for {record['days']} day(s). Status: Pending HR Approval."}


@app.get("/hr/leaves", response_class=HTMLResponse, dependencies=[Depends(require_hr)])
def hr_leave_management():
    rows = []
    for r in read_leave_records():
        action = "—"
        if r["status"] == "Pending":
            action = f"""<form method="post" action="/hr/leaves/{r['leave_id']}/decision">
            <button name="decision" value="Approved">Approve</button>
            <button class="secondary" name="decision" value="Rejected">Reject</button></form>"""
        rows.append(f"<tr><td>{r['leave_id']}</td><td>{escape(r['employee_name'])}</td><td>{r['start_date']} – {r['end_date']}</td><td>{r['days']}</td><td>{escape(r['reason'])}</td><td>{r['status']}</td><td>{action}</td></tr>")
    body = "".join(rows) or "<tr><td colspan='7'>No leave requests yet.</td></tr>"
    return page(f"""<section class='card'><h2>Leave Management</h2><div class='table-wrap'><table>
    <thead><tr><th>ID</th><th>Employee</th><th>Dates</th><th>Days</th><th>Reason</th><th>Status</th><th>Action</th></tr></thead><tbody>{body}</tbody></table></div></section>""")

@app.post("/hr/leaves/{leave_id}/decision", dependencies=[Depends(require_hr)])
def decide_leave(leave_id: int, decision: str = Form(...)):
    if decision not in ("Approved", "Rejected"):
        raise HTTPException(status_code=400, detail="Invalid decision.")
    records = read_leave_records()
    for r in records:
        if int(r["leave_id"]) == leave_id and r["status"] == "Pending":
            if decision == "Approved":
                other_approved = sum(int(x["days"]) for x in records if int(x["employee_id"]) == int(r["employee_id"]) and x["status"] == "Approved")
                if other_approved + int(r["days"]) > DEFAULT_ANNUAL_LEAVE:
                    raise HTTPException(status_code=400, detail="Approval exceeds remaining annual leave.")
            r["status"] = decision
            write_leave_records(records)
            return RedirectResponse("/hr/leaves", status_code=303)
    raise HTTPException(status_code=404, detail="Pending leave request not found.")

@app.get("/", response_class=HTMLResponse)
def dashboard(request: Request):
    user = get_session_user(request)
    if not user:
        return RedirectResponse("/login", status_code=303)
    if user.get("role") != "hr":
        return RedirectResponse("/employee", status_code=303)
    active_count = sum(1 for employee in employees if employee.active)
    inactive_count = len(employees) - active_count
    total_net = sum((record["net"] for record in payroll_records), Decimal("0.00"))
    recent = sorted(payroll_records, key=lambda item: item["created_at"], reverse=True)[:5]
    recent_rows = "".join(
        f"<tr><td>{r['payroll_id']}</td><td>{escape(r['employee_name'])}</td><td>{escape(r['month'])}</td><td>₹{r['net']:.2f}</td></tr>"
        for r in recent
    )
    if not recent_rows:
        recent_rows = '<tr><td colspan="4" class="muted">No payroll records yet. Calculate a payroll to see it here.</td></tr>'
    return page(f'''<section class="grid">
<div class="card"><div class="muted">Active employees</div><div class="stats">{active_count}</div></div>
<div class="card"><div class="muted">Inactive employees</div><div class="stats">{inactive_count}</div></div>
<div class="card"><div class="muted">Payroll calculations this session</div><div class="stats">{len(payroll_records)}</div></div>
<div class="card"><div class="muted">Total net pay calculated</div><div class="stats">₹{total_net:.2f}</div></div></section>
<section class="card"><h2>Welcome</h2><p>A Python and FastAPI learning application for employee records and monthly salary calculations.</p>
<p class="message">Employee and payroll records are maintained using CSV-based file storage for streamlined data persistence.</p>
<a class="button" href="/employees/new">+ Add Employee</a><a class="button" href="/employees">Manage Employees</a><a class="button" href="/hr/accounts">Manage Login Accounts</a><a class="button" href="/payroll/new">Calculate Payroll</a></section>
<section class="card"><h2>Recent payroll calculations</h2><div class="table-wrap"><table><thead><tr><th>ID</th><th>Employee</th><th>Month</th><th>Net salary</th></tr></thead><tbody>{recent_rows}</tbody></table></div></section>''')


@app.get("/employees", response_class=HTMLResponse, dependencies=[Depends(require_hr)])
def list_employees():
    rows = []
    for employee in employees:
        status = "Active" if employee.active else "Inactive"
        status_class = "status-active" if employee.active else "status-inactive"
        action = "Deactivate" if employee.active else "Reactivate"
        button_class = "" if employee.active else "secondary"
        rows.append(f'''<tr><td>{employee.employee_id}</td><td>{escape(employee.name)}</td>
<td>{escape(employee.department)}</td><td>{escape(employee.role)}</td><td>₹{employee.monthly_basic:.2f}</td>
<td>{employee.joined_on.isoformat()}</td><td class="{status_class}">{status}</td><td>
<form method="post" action="/employees/{employee.employee_id}/toggle-status" onsubmit="return confirm('Change this employee status?');">
<button class="{button_class}" type="submit">{action}</button></form></td></tr>''')
    if not rows:
        row_html = '<tr><td colspan="8" class="muted">No employees yet. Add your first employee.</td></tr>'
    else:
        row_html = "".join(rows)
    return page(f'''<section class="card"><h2>Employee Directory</h2>
<p class="muted">Employee profiles and employment status are maintained in employees.txt, preserving inactive records for historical reference.</p>
<a class="button" href="/employees/new">+ Add Employee</a><div class="table-wrap"><table>
<thead><tr><th>ID</th><th>Name</th><th>Department</th><th>Role</th><th>Basic salary</th><th>Joined</th><th>Status</th><th>Action</th></tr></thead>
<tbody>{row_html}</tbody></table></div></section>''')


@app.get("/employees/new", response_class=HTMLResponse, dependencies=[Depends(require_hr)])
def new_employee_form():
    return page('''<section class="card"><h2>Add Employee</h2><form method="post" action="/employees"><div class="grid">
<div><label>Full name *</label><input name="name" required minlength="2" maxlength="80" pattern="[A-Za-z][A-Za-z .-]{0,78}[A-Za-z]" title="Letters, spaces, periods and hyphens only." placeholder="e.g. Ravi Kumar"></div>
<div><label>Department *</label><input name="department" required minlength="2" maxlength="60" pattern="[A-Za-z0-9][A-Za-z0-9 &().,/-]{0,58}" placeholder="e.g. Finance"></div>
<div><label>Job role *</label><input name="role" required minlength="2" maxlength="60" pattern="[A-Za-z0-9][A-Za-z0-9 &().,/-]{0,58}" placeholder="e.g. Junior Analyst"></div>
<div><label>Monthly basic salary (₹) *</label><input name="monthly_basic" type="number" min="1" max="10000000" step="0.01" required placeholder="25000"></div>
</div><button type="submit">Save Employee</button></form></section>''')


@app.post("/employees", dependencies=[Depends(require_hr)])
def add_employee(name: str = Form(...), department: str = Form(...), role: str = Form(...), monthly_basic: str = Form(...)):
    global next_employee_id
    name, department, role = name.strip(), department.strip(), role.strip()
    if not valid_name(name):
        return page("<section class='card'><h2>Invalid name</h2><p class='message'>Enter 2–80 letters. Spaces, periods and hyphens are allowed.</p><a class='button' href='/employees/new'>Go back</a></section>")
    if not valid_label(department) or not valid_label(role):
        return page("<section class='card'><h2>Invalid department or role</h2><p class='message'>Use 2–60 letters/numbers and common punctuation only.</p><a class='button' href='/employees/new'>Go back</a></section>")
    if any(e.name.casefold() == name.casefold() and e.active for e in employees):
        return page('<section class="card"><h2>Employee not added</h2><p class="message">An active employee with this name already exists in this demo.</p><a class="button" href="/employees/new">Go back</a></section>')
    try:
        basic = money(monthly_basic)
    except ValueError as exc:
        return page(f'<section class="card"><h2>Invalid salary</h2><p class="message">{escape(str(exc))}</p><a class="button" href="/employees/new">Go back</a></section>')
    employee = Employee(next_employee_id, name, department, role, basic)
    employees.append(employee)
    # Save the full employee list, including status and joining date.
    persist_employees()
    next_employee_id += 1
    return RedirectResponse("/employees", status_code=303)


@app.post("/employees/{employee_id}/toggle-status", dependencies=[Depends(require_hr)])
def toggle_employee_status(employee_id: int):
    employee = employee_by_id(employee_id)
    if employee is None:
        raise HTTPException(status_code=404, detail="Employee not found.")
    employee.active = not employee.active
    persist_employees()
    return RedirectResponse("/employees", status_code=303)




@app.get("/hr/accounts", response_class=HTMLResponse, dependencies=[Depends(require_hr)])
def hr_employee_accounts():
    """HR can view login-account status and manage employee credentials."""
    account_by_id = {a["employee_id"]: a for a in get_all_employee_accounts()}
    rows = []
    for employee in employees:
        account = account_by_id.get(employee.employee_id)
        email = escape(account["email"]) if account else "Not created"
        label = "Account created" if account else "No login account"
        css = "status-active" if account else "status-inactive"
        reset_action = (
            f'<form method="post" action="/hr/accounts/{employee.employee_id}/reset" '
            f'onsubmit="return confirm(\'Generate a new temporary password?\')">'
            f'<button class="secondary" type="submit">Reset password</button></form>'
            if account else "—"
        )
        rows.append(
            f'<tr><td>{employee.employee_id}</td><td>{escape(employee.name)}</td>'
            f'<td>{email}</td><td class="{css}">{label}</td>'
            f'<td>{"Active" if employee.active else "Inactive"}</td><td>{reset_action}</td></tr>'
        )
    row_html = "".join(rows) or '<tr><td colspan="6">No employees found.</td></tr>'
    options = "".join(
        f'<option value="{e.employee_id}">{e.employee_id} - {escape(e.name)}</option>'
        for e in employees if e.active
    ) or '<option value="">No active employees available</option>'

    return page(f"""<section class="card"><h2>Employee Login Account Management</h2>
<p class="muted">Create employee login accounts, assign company email addresses and reset passwords.</p>
<h3>Create employee login</h3><form method="post" action="/hr/accounts/create">
<label>Employee</label><select name="employee_id" required>{options}</select>
<label>Company email address</label><input name="email" type="email" required placeholder="employee@company.com">
<button type="submit">Create account and generate temporary password</button></form>
<p class="message">A temporary password is displayed once after creation. Share it privately with the employee.</p>
</section><section class="card"><h2>Employee accounts</h2><div class="table-wrap"><table>
<thead><tr><th>ID</th><th>Employee</th><th>Email</th><th>Login account</th><th>Employment status</th><th>Action</th></tr></thead>
<tbody>{row_html}</tbody></table></div></section>""", "HR Account Management")


@app.post("/hr/accounts/create", response_class=HTMLResponse, dependencies=[Depends(require_hr)])
def hr_create_employee_account(employee_id: int = Form(...), email: str = Form(...)):
    employee = employee_by_id(employee_id)
    email = email.strip().lower()
    if employee is None or not employee.active:
        return page('<section class="card"><h2>Account not created</h2><p class="message">Select an existing active employee.</p><a class="button" href="/hr/accounts">Back</a></section>')
    if not re.fullmatch(r"[A-Za-z0-9.!#$%&'*+/=?^_`{|}~-]+@[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?(?:\.[A-Za-z]{2,})+", email):
        return page('<section class="card"><h2>Account not created</h2><p class="message">Enter a valid company email address.</p><a class="button" href="/hr/accounts">Back</a></section>')
    if get_employee_account_by_id(employee_id):
        return page('<section class="card"><h2>Account already exists</h2><p class="message">Use Reset password to generate new credentials.</p><a class="button" href="/hr/accounts">Back</a></section>')
    temporary_password = generate_temporary_password()
    try:
        set_employee_account(employee_id, email, hash_password(temporary_password))
    except ValueError as exc:
        return page(f'<section class="card"><h2>Account not created</h2><p class="message">{escape(str(exc))}</p><a class="button" href="/hr/accounts">Back</a></section>')
    return page(f"""<section class="card"><h2>Employee account created</h2>
<p><b>Employee:</b> {escape(employee.name)} (ID: {employee.employee_id})</p>
<p><b>Login email:</b> {escape(email)}</p><p><b>Temporary password:</b></p>
<p class="message"><strong>{escape(temporary_password)}</strong></p>
<p>Copy this password now and share it privately. The application stores only its password hash.</p>
<a class="button" href="/hr/accounts">Back to account management</a></section>""", "Temporary Employee Credentials")


@app.post("/hr/accounts/{employee_id}/reset", response_class=HTMLResponse, dependencies=[Depends(require_hr)])
def hr_reset_employee_password(employee_id: int):
    employee = employee_by_id(employee_id)
    account = get_employee_account_by_id(employee_id)
    if employee is None or account is None:
        return page('<section class="card"><h2>Password not reset</h2><p class="message">Employee or login account not found.</p><a class="button" href="/hr/accounts">Back</a></section>')
    if not employee.active:
        return page('<section class="card"><h2>Password not reset</h2><p class="message">Reactivate the employee before resetting credentials.</p><a class="button" href="/hr/accounts">Back</a></section>')
    temporary_password = generate_temporary_password()
    set_employee_account(employee_id, account["email"], hash_password(temporary_password))
    return page(f"""<section class="card"><h2>Password reset successfully</h2>
<p><b>Employee:</b> {escape(employee.name)} (ID: {employee.employee_id})</p>
<p><b>Login email:</b> {escape(account["email"])}</p><p><b>New temporary password:</b></p>
<p class="message"><strong>{escape(temporary_password)}</strong></p>
<p>The previous password is now invalid. Share this new temporary password privately.</p>
<a class="button" href="/hr/accounts">Back to account management</a></section>""", "Temporary Password Reset")

@app.get("/payroll/new", response_class=HTMLResponse, dependencies=[Depends(require_hr)])
def payroll_form():
    active_employees = [employee for employee in employees if employee.active]
    if not active_employees:
        return page('<section class="card"><h2>Calculate Payroll</h2><p class="message">There are no active employees. Add or reactivate an employee before calculating payroll.</p><a class="button" href="/employees">Manage Employees</a></section>')
    options = "".join(f'<option value="{e.employee_id}">{e.employee_id} - {escape(e.name)} (₹{e.monthly_basic:.2f} basic)</option>' for e in active_employees)
    current_month = date.today().strftime("%Y-%m")
    return page(f'''<section class="card"><h2>Payroll Calculator</h2><p class="muted">Only active employees can be selected.</p>
<form method="post" action="/payroll"><label>Employee *</label><select name="employee_id" required>{options}</select><div class="grid">
<div><label>Payroll month *</label><input type="month" name="month" value="{current_month}" required></div>
<div><label>Allowances (₹)</label><input type="number" name="allowances" min="0" step="0.01" value="0" required></div>
<div><label>Bonus (₹)</label><input type="number" name="bonus" min="0" step="0.01" value="0" required></div>
<div><label>Deductions (₹)</label><input type="number" name="deductions" min="0" step="0.01" value="0" required></div>
</div><button type="submit">Calculate and Save</button></form></section>''')


@app.post("/payroll", response_class=HTMLResponse, dependencies=[Depends(require_hr)])
def calculate_payroll(employee_id: int = Form(...), month: str = Form(...), allowances: str = Form("0"), bonus: str = Form("0"), deductions: str = Form("0")):
    global next_payroll_id
    employee = employee_by_id(employee_id)
    if employee is None or not employee.active:
        return page('<section class="card"><h2>Unable to calculate payroll</h2><p class="message">Choose an active employee. Inactive employees cannot be used for new payroll calculations.</p><a class="button" href="/payroll/new">Try again</a></section>')
    try:
        parsed_month = datetime.strptime(month, "%Y-%m")
        if parsed_month.strftime("%Y-%m") != month:
            raise ValueError("Select a valid payroll month.")
        if any(int(r["employee_id"]) == employee_id and r["month"] == month for r in payroll_records):
            raise ValueError("Payroll has already been generated for this employee and month.")
        result = calculator.calculate(employee.monthly_basic, allowances, bonus, deductions)
    except (ValueError, TypeError) as exc:
        return page(f'<section class="card"><h2>Check your inputs</h2><p class="message">{escape(str(exc))}</p><a class="button" href="/payroll/new">Try again</a></section>')
    record = {"payroll_id": next_payroll_id, "employee_id": employee.employee_id, "employee_name": employee.name,
              "department": employee.department, "role": employee.role, "month": month, **result, "created_at": datetime.now()}
    payroll_records.append(record)
    write_payroll_records(payroll_records)
    next_payroll_id += 1
    rows = "".join(f'<tr><th>{escape(label)}</th><td>₹{result[key]:.2f}</td></tr>' for label, key in [
        ("Basic salary", "basic"), ("Allowances", "allowances"), ("Bonus", "bonus"),
        ("Gross salary", "gross"), ("Deductions", "deductions"), ("Net salary", "net")])
    return page(f'''<section class="card"><h2>Payroll Calculated Successfully</h2><p><strong>Employee:</strong> {escape(employee.name)} &nbsp; <strong>Month:</strong> {escape(month)}</p>
<div class="table-wrap"><table><tbody>{rows}</tbody></table></div><p class="message">Net salary: <strong>₹{result['net']:.2f}</strong></p>
<a class="button" href="/payroll/new">Calculate another</a> <a class="button" href="/payroll/history">View history</a></section>''')


@app.get("/payroll/history", response_class=HTMLResponse, dependencies=[Depends(require_hr)])
def payroll_history():
    rows = "".join(f'''<tr><td>{r['payroll_id']}</td><td>{escape(r['employee_name'])}</td><td>{escape(r['department'])}</td>
<td>{escape(r['month'])}</td><td>₹{r['gross']:.2f}</td><td>₹{r['deductions']:.2f}</td><td><strong>₹{r['net']:.2f}</strong></td>
<td>{r['created_at'].strftime('%d %b %Y %H:%M')}</td></tr>''' for r in reversed(payroll_records))
    if not rows:
        rows = '<tr><td colspan="8" class="muted">No payroll calculations saved yet.</td></tr>'
    return page(f'''<section class="card"><h2>Payroll History</h2><p class="muted">HR view: payroll records for all employees.</p>
<div class="table-wrap"><table><thead><tr><th>ID</th><th>Employee</th><th>Department</th><th>Month</th><th>Gross</th><th>Deductions</th><th>Net pay</th><th>Created</th></tr></thead><tbody>{rows}</tbody></table></div></section>''')


@app.get("/api/employees", dependencies=[Depends(require_hr)])
def api_employees():
    """Return employee data, including each employee's active status."""
    return [{"id": e.employee_id, "name": e.name, "department": e.department, "role": e.role,
             "monthly_basic": str(e.monthly_basic), "joined_on": e.joined_on.isoformat(), "active": e.active}
            for e in employees]


@app.get("/api/payroll/history", dependencies=[Depends(require_hr)])
def api_payroll_history():
    return [{"payroll_id": r["payroll_id"], "employee_name": r["employee_name"], "month": r["month"],
             "basic": str(r["basic"]), "allowances": str(r["allowances"]), "bonus": str(r["bonus"]),
             "gross": str(r["gross"]), "deductions": str(r["deductions"]), "net": str(r["net"]),
             "created_at": r["created_at"].isoformat(timespec="seconds")} for r in payroll_records]
