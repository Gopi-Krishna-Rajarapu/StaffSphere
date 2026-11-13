# StaffSphere – Smart Workforce Management Platform

## Project Overview

**StaffSphere** is a FastAPI-based workforce management platform designed to simplify employee administration, payroll processing, and leave management through a centralized web application.

The platform provides role-based access for HR administrators and employees, enabling HR teams to manage employee records, process payroll, and review leave requests, while employees can access their profiles, view relevant information, and submit leave applications.

It also integrates Google's Gemini API to provide an AI-powered employee leave assistant that helps employees prepare leave applications through natural-language conversations.

## Key Features

- **Role-Based Authentication:** Separate access for HR administrators and employees.
- **Employee Management:** Add, view, update, and deactivate employee records.
- **Employee Account Management:** Manage employee login credentials and account access.
- **Payroll Management:** Calculate gross salary, allowances, bonuses, deductions, and net salary.
- **Leave Management:** Submit, track, approve, and reject employee leave requests.
- **AI-Powered Leave Assistant:** Use Gemini to understand employee leave requests and assist with application preparation.
- **Confirmation-Based Submission:** Employees review and confirm AI-prepared leave applications before submission.
- **Data Persistence:** Maintain application records using file-based storage.

## Technology Stack

| Technology | Purpose |
|---|---|
| Python | Core programming language |
| FastAPI | Backend framework and API development |
| Jinja2 | Dynamic HTML page rendering |
| HTML5 | Web page structure |
| CSS3 | Styling and responsive layouts |
| JavaScript | Client-side interactions |
| Google Gemini API | AI-powered leave assistant |
| CSV/Text Files | File-based data persistence |
| Uvicorn | ASGI server |
| Git & GitHub | Version control and source-code management |
| Render | Application deployment |

## Project Architecture

```text
StaffSphere/
│
├── main.py
├── employee_storage.py
├── requirements.txt
├── .env.example
├── .gitignore
├── README.md
│
├── templates/
│   ├── base.html
│   ├── login.html
│   ├── register.html
│   └── assistant.html
│
└── static/
    ├── css/
    │   ├── style.css
    │   └── auth.css
    │
    └── js/
        └── assistant.js
```

*Note: This represents the separated frontend structure. Other application pages may be rendered through HTML generated in `main.py`, depending on the current implementation.*

## Modules and Their Responsibilities

### 1. main.py – Application Controller

The primary application module responsible for connecting the different components of StaffSphere.

Responsibilities:
- Initialize the FastAPI application.
- Configure middleware and session management.
- Define application routes and endpoints.
- Handle HR and employee authentication.
- Enforce role-based authorization.
- Manage employee operations.
- Process payroll calculations.
- Handle leave applications and HR decisions.
- Integrate the Gemini AI assistant.
- Validate user input and coordinate file operations.

### 2. employee_storage.py – Data Persistence Module

Handles reading and writing employee information to local text files.

Responsibilities:
- Load existing employee records.
- Save newly created employee records.
- Update employee information.
- Maintain employee status.
- Preserve inactive employee records instead of permanently deleting them.

### 3. templates/ – Frontend Templates

Contains HTML templates used to render the application's web pages.

- `base.html` – Common layout and navigation structure.
- `login.html` – User authentication interface.
- `register.html` – Employee registration interface.
- `assistant.html` – AI assistant interface.

### 4. static/css/ – Styling Module

Contains CSS files responsible for the application's visual presentation.

- `style.css` – General application styling.
- `auth.css` – Authentication page styling.

### 5. static/js/ – Client-Side Interaction

- `assistant.js` – Handles interactions with the Gemini-powered assistant, including sending messages and displaying responses.

## Packages and Libraries

| Package / Library | Why It Is Used |
|---|---|
| `fastapi` | Builds backend routes, APIs, and request handling. |
| `uvicorn` | Runs the FastAPI application as an ASGI server. |
| `jinja2` | Renders dynamic HTML templates using backend data. |
| `python-multipart` | Processes HTML form submissions and form data. |
| `python-dotenv` | Loads configuration and secrets from environment variables. |
| `google-genai` | Connects the application to Google's Gemini API. |
| `itsdangerous` | Supports signed session cookies through Starlette's SessionMiddleware. |

### Python Standard Libraries

| Module | Why It Is Used |
|---|---|
| `csv` | Reads and writes structured records in CSV format, if used by the storage implementation. |
| `datetime` | Handles dates, joining dates, payroll periods, and leave durations. |
| `decimal` | Provides accurate monetary calculations for payroll. |
| `hashlib` | Supports secure password hashing. |
| `secrets` | Generates secure random values. |
| `pathlib` | Handles file paths and storage locations. |
| `os` | Reads environment variables and operating-system configuration. |

*Standard-library modules are included with Python and do not need separate installation. The package list should be checked against the final application imports.*

## Application Workflow – End-to-End Process

### 1. Authentication and Access Control

1. A user opens the StaffSphere application.
2. The user enters login credentials.
3. The backend validates the credentials.
4. A session is established after successful authentication.
5. The application identifies the user's role.
6. HR users are redirected to the HR dashboard.
7. Employees are redirected to the employee dashboard.

### 2. HR Employee Management

1. HR logs in to the application.
2. HR opens the employee management section.
3. HR enters employee details.
4. The backend validates the submitted information.
5. The employee record is saved in the storage file.
6. HR can view and manage employee information.
7. When an employee becomes inactive, their status is updated rather than deleting their historical record.

### 3. Employee Account Management

1. HR creates or manages employee accounts.
2. Employee login information is maintained separately from employee profile records.
3. Employees authenticate using their assigned credentials.
4. Password protection and session validation control access to employee-specific pages.

### 4. Payroll Processing

1. HR selects an employee.
2. The payroll form collects the required salary information.
3. The application processes basic salary, allowances, bonuses, and deductions.
4. The payroll calculator determines gross salary and net salary.
5. Monetary calculations use Python's `Decimal` type.
6. The payroll record is saved for historical reference.

**Payroll calculation:**

Gross Salary = Basic Salary + Allowances + Bonus

Net Salary = Gross Salary − Deductions

### 5. Employee Leave Application

1. The employee logs in.
2. The employee opens the leave application section.
3. The employee provides leave dates and a reason.
4. The backend validates the leave information.
5. The application checks relevant leave rules and overlapping requests.
6. A valid request is stored with a Pending status.
7. HR reviews the submitted request.

### 6. HR Leave Approval

1. HR opens the leave management section.
2. HR views pending leave applications.
3. HR reviews employee details and requested dates.
4. HR approves or rejects the application.
5. The application updates the leave request status.
6. The employee can view the updated status.

### 7. Gemini AI Leave Assistant

1. The employee opens the AI assistant.
2. The employee describes their leave requirement in natural language.
3. The frontend sends the message to the FastAPI backend.
4. The backend communicates with the Gemini API.
5. Gemini interprets the request and assists in preparing the leave application.
6. The assistant asks for missing information when necessary.
7. The employee reviews the prepared application.
8. The employee explicitly confirms submission.
9. The backend validates the request and saves it as Pending.
10. HR retains exclusive authority to approve or reject the leave.

**Important:** AI-assisted preparation does not grant the assistant permission to approve leave. The application backend remains responsible for validation, employee identity, and submission.

## Data Storage Strategy

StaffSphere currently uses flat-file persistence instead of an external database.

| File | Purpose |
|---|---|
| `employees.txt` | Stores employee profile details and employment status. |
| `employee_accounts.txt` | Stores employee account information. |
| `payroll_records.txt` | Maintains payroll transaction history. |
| `leave_records.txt` | Maintains employee leave applications and their statuses. |

### Employee Record Management

Employee records are retained throughout their lifecycle. When an employee becomes inactive, their status is changed instead of permanently deleting their record.

### Why Flat-File Persistence?

- Simple to implement and understand.
- Does not require database server configuration.
- Suitable for learning file handling and data persistence.
- Provides a lightweight storage mechanism for small-scale applications.

**Limitation:** Flat-file storage is suitable for a learning project but has limitations involving concurrent writes, scalability, querying, and data recovery. Production deployments should use a managed database or appropriately configured persistent storage.

## Environment Configuration

Create a `.env` file in the project root.

```env
GEMINI_API_KEY=your_gemini_api_key
GEMINI_MODEL=gemini-3.5-flash
SESSION_SECRET=your_secure_random_secret
HR_EMAIL=your_hr_email
HR_PASSWORD=your_hr_password
```

Never commit the actual `.env` file or API credentials to GitHub.

## Installation and Local Execution

### 1. Clone the repository

```bash
git clone YOUR_GITHUB_REPOSITORY_URL
cd StaffSphere
```

### 2. Create a virtual environment

```bash
python -m venv .venv
```

### 3. Activate the environment

Windows PowerShell:

```powershell
.venv\Scripts\activate
```

### 4. Install dependencies

```bash
pip install -r requirements.txt
```

### 5. Configure environment variables

Create `.env` and provide the required configuration values.

### 6. Start the application

```bash
python -m uvicorn main:app --reload
```

### 7. Open the application

```text
http://127.0.0.1:8000
```

## Deployment – Render

StaffSphere can be deployed as a Render Web Service.

**Build Command**

```bash
pip install -r requirements.txt
```

**Start Command**

```bash
uvicorn main:app --host 0.0.0.0 --port $PORT
```

Configure the following environment variables in Render:

- `GEMINI_API_KEY`
- `GEMINI_MODEL`
- `SESSION_SECRET`
- `HR_EMAIL`
- `HR_PASSWORD`

**Deployment consideration:** Render's default filesystem is ephemeral. Configure persistent storage or migrate to a database if employee, payroll, and leave records must survive service restarts and redeployments.

## Security Considerations

- Passwords should be stored as hashes rather than plaintext.
- Environment variables should be used for API keys and application secrets.
- Role-based authorization should protect HR-only routes.
- Employee identity should be obtained from the authenticated session.
- AI-generated information must be validated by the backend.
- Leave applications should require employee confirmation.
- HR approval must remain a separate authorization-controlled operation.

## Learning Outcomes

This project demonstrates practical implementation of:

- Python backend development.
- FastAPI routing and REST API concepts.
- Authentication and session management.
- Role-based access control.
- Object-oriented programming and modular code organization.
- File handling and data persistence.
- Payroll calculations using `Decimal`.
- Input validation and exception handling.
- Frontend and backend integration.
- Third-party API integration using Google's Gemini SDK.
- Environment configuration and deployment using Render.

## Future Enhancements

- Migrate flat-file storage to PostgreSQL or another relational database.
- Add automated payroll reports and downloadable payslips.
- Introduce employee attendance tracking.
- Add email notifications for leave decisions.
- Improve audit logging and administrative reporting.
- Add automated testing and deployment workflows.

## Project Summary

StaffSphere combines workforce administration, payroll processing, leave management, and AI-assisted employee interactions in a single FastAPI application.

The project demonstrates how Python backend development, file-based data persistence, authentication, and generative AI integration can be combined to build a practical workforce management solution.