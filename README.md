# 🤖 AI Browser Assistant (Nexus)

An autonomous, full-stack **AI-Powered Browser Assistant** that interprets natural language instructions and executes complex browser-based workflows—such as automating job/application forms, composing and sending emails via Gmail, and managing Google Calendar events—using a multi-agent LLM architecture with real-time WebSocket feedback and human-in-the-loop clarification.

---

## 📑 Table of Contents

- [Overview & Key Features](#-overview--key-features)
- [System Architecture](#-system-architecture)
- [Tech Stack](#-tech-stack)
- [Prerequisites](#-prerequisites)
- [Repository Structure](#-repository-structure)
- [Quick Start Guide](#-quick-start-guide)
  - [1. Backend Setup](#1-backend-setup)
  - [2. Google OAuth Configuration (Gmail & Calendar)](#2-google-oauth-configuration-gmail--calendar)
  - [3. Frontend Setup](#3-frontend-setup)
- [Running the Application](#-running-the-application)
- [How to Use the Assistant](#-how-to-use-the-assistant)
- [API & WebSocket Endpoints](#-api--websocket-endpoints)
- [Diagnostics & Testing](#-diagnostics--testing)
- [Troubleshooting & Common Pitfalls](#-troubleshooting--common-pitfalls)
- [License](#-license)

---

## 🌟 Overview & Key Features

- **Multi-Agent Orchestration**: High-level intent classifier powered by Gemini 2.5 Flash breaks complex instructions down and delegates subtasks sequentially to specialized ReAct agents.
- **Autonomous Web Form Filling**: Playwright-driven browser agent detects form inputs across frames and iframes, performs single-call batch mapping of profile details to fields, and fills forms automatically.
- **Persistent Chrome Session**: Clones your local Google Chrome profile to execute browser tasks with authenticated cookies and login states without needing manual re-authentication.
- **AI Email Management**: Drafts context-aware emails, resolves contact groups, and enforces a mandatory human confirmation step prior to dispatching via Gmail API.
- **Smart Calendar Management**: Analyzes Google Calendar availability using a sweep-line free slot algorithm, checks for schedule conflicts, and schedules events (including recurring RRULE support).
- **Human-in-the-Loop Clarification**: Thread-synchronized pause/resume flow (`threading.Event`) allows agents to pause mid-execution to prompt the user for missing details or file uploads, resuming instantly upon response.
- **Real-Time Activity Streaming**: Live status and tool execution updates delivered from FastAPI to React via WebSocket.

---

## 🏗️ System Architecture

```
                      ┌────────────────────────────────────────┐
                      │          React 19 + Vite UI            │
                      │  (Port 3000: TanStack Router & Query)   │
                      └──────────────────┬─────────────────────┘
                                         │ REST + WebSocket
                                         ▼
                      ┌────────────────────────────────────────┐
                      │          FastAPI Backend Server        │
                      │         (Port 8000 / Uvicorn)          │
                      └────┬─────────────┬─────────────────┬───┘
                           │             │                 │
                           ▼             ▼                 ▼
             ┌───────────────────┐ ┌───────────┐ ┌────────────────────┐
             │ SQLite (Users.db) │ │ Google    │ │ Gemini 2.5 Flash   │
             │ Status & Profiles │ │ Workspace │ │ LangChain Orchestr.│
             └───────────────────┘ │ APIs      │ └────────────────────┘
                                   └───────────┘
                                         │
                                         ▼
                     ┌───────────────────────────────────────┐
                     │          Specialized Agents           │
                     ├───────────────────┬───────────────────┤
                     │ Form Filler Agent │ Playwright Chrome │
                     │ Email Agent       │ Gmail API         │
                     │ Calendar Agent    │ Calendar API      │
                     └───────────────────┴───────────────────┘
```

---

## 🛠️ Tech Stack

### Backend

- **Framework**: [FastAPI](https://fastapi.tiangolo.com/), Uvicorn
- **AI & Agents**: [LangChain](https://www.langchain.com/), Google Gemini 2.5 Flash (`google-genai`, `langchain-google-genai`), Groq (`langchain-groq`)
- **Browser Automation**: [Playwright](https://playwright.dev/)
- **Database & ORM**: SQLite, [SQLAlchemy](https://www.sqlalchemy.org/), Pydantic
- **APIs & Auth**: Google API Client (`google-api-python-client`, `google-auth-oauthlib`)

### Frontend

- **Framework**: [React 19](https://react.dev/), [Vite](https://vitejs.dev/)
- **Routing & State**: [TanStack Router](https://tanstack.com/router), [TanStack Query](https://tanstack.com/query), [TanStack Form](https://tanstack.com/form)
- **Styling**: [Tailwind CSS v4](https://tailwindcss.com/), Lucide Icons, React Hot Toast
- **Language**: TypeScript

---

## 📋 Prerequisites

Ensure you have the following installed on your machine:

1. **Python 3.10+** (Python 3.10, 3.11, or 3.12 recommended)
2. **Node.js 18+ or 20+** and `npm` (or `pnpm`)
3. **Google Chrome** installed (required for Playwright persistent browser context and session cloning)
4. **Google Gemini API Key** (obtain free from [Google AI Studio](https://aistudio.google.com/app/apikey))
5. **Google Cloud Project** with OAuth 2.0 Credentials (for Gmail & Calendar automation)

---

## 📂 Repository Structure

```
AI-browser-assistant/
├── backend/
│   ├── app/
│   │   ├── AgentsForModules/     # AI Agent implementations (Form, Email, Calendar, Router)
│   │   │   ├── calendar_manager.py
│   │   │   ├── email_sender.py
│   │   │   ├── form_filler.py
│   │   │   ├── pendingAnswers.py
│   │   │   └── topLevelModuleClassifier.py
│   │   ├── models_db/            # SQLAlchemy database tables
│   │   ├── routes/               # FastAPI endpoints & WebSocket router
│   │   ├── schemasPydantic/      # Pydantic request/response models
│   │   ├── services/             # Gmail and service helpers
│   │   └── database.py           # Database connection & session setup
│   ├── uploadedResumes/          # Stored user documents and resumes
│   ├── main.py                   # FastAPI application entry point
│   ├── quickstartCalendar.py     # Google OAuth consent flow & verification
│   ├── test_agent.py             # Agent tool execution diagnostic script
│   ├── check_db.py               # SQLite inspection script
│   ├── requirements.txt          # Python package dependencies
│   ├── .env.example              # Environment variable template
│   └── .env                      # Local environment configuration (API keys)
│
├── frontend/
│   ├── src/
│   │   ├── routes/               # File-based routes (Profile, Upload, Commands)
│   │   │   ├── index.tsx         # User Profile Setup (/)
│   │   │   ├── resume_upload.tsx # Document / Resume Upload (/resume_upload)
│   │   │   └── CommandsSection.tsx # AI Agent Command Dashboard (/CommandsSection)
│   │   ├── routeTree.gen.ts      # Generated TanStack route tree
│   │   └── main.tsx              # React mounting entry point
│   ├── package.json              # Frontend scripts & dependencies
│   └── vite.config.ts            # Vite bundler configuration
│
├── project_analysis.md           # In-depth architectural & resume analysis
└── README.md                     # Project documentation & run guide
```

---

## 🚀 Quick Start Guide

### 1. Backend Setup

Open a terminal and navigate to the `backend` folder:

```bash
cd backend
```

#### Step 1.1: Create and Activate a Python Virtual Environment

- **Windows (PowerShell)**:

  ```powershell
  python -m venv venv
  .\venv\Scripts\Activate.ps1
  ```

  _(If script execution is restricted, run: `Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass`)_

- **Windows (Command Prompt)**:

  ```cmd
  python -m venv venv
  venv\Scripts\activate.bat
  ```

- **Linux / macOS**:
  ```bash
  python3 -m venv venv
  source venv/bin/activate
  ```

#### Step 1.2: Install Dependencies

```bash
pip install -r requirements.txt
```

#### Step 1.3: Install Playwright Browsers

Playwright uses Chromium to automate web forms:

```bash
playwright install chromium
```

#### Step 1.4: Configure Environment Variables

Create your `.env` file in the `backend/` directory from the provided example:

```bash
cp .env.example .env
```

Open `backend/.env` and add your Gemini API Key:

```env
GEMINI_API_KEY="your_google_gemini_api_key_here"
GROQ_API_KEY="your_groq_api_key_here" # Optional
```

---

### 2. Google OAuth Configuration (Gmail & Calendar)

To enable the Email Sender and Calendar Manager agents, set up Google OAuth 2.0:

1. Visit the [Google Cloud Console](https://console.cloud.google.com/).
2. Create a new project (e.g., `Nexus-Browser-Assistant`).
3. Enable the following APIs under **APIs & Services > Library**:
   - **Gmail API**
   - **Google Calendar API**
4. Configure the **OAuth Consent Screen**:
   - Select **External**.
   - Add your test Google account email under **Test Users**.
5. Create Credentials:
   - Go to **APIs & Services > Credentials > Create Credentials > OAuth client ID**.
   - Select **Desktop app**.
   - Download the client secrets file and rename it to **`credentials.json`**.
   - Place `credentials.json` directly inside the `backend/` directory (`backend/credentials.json`).
6. Generate your `token.json` authorization token:
   Run the quickstart script from the `backend` directory:
   ```bash
   python quickstartCalendar.py
   ```
   A browser window will open prompting you to grant access to your Gmail and Calendar accounts. Once authorized, a `token.json` file will be created in `backend/` automatically.

> [!NOTE]
> **Chrome Profile Configuration (Form Filler):**
> By default, `backend/app/AgentsForModules/form_filler.py` clones your default Chrome user profile on Windows (`C:\Users\<USER>\AppData\Local\Google\Chrome\User Data`). If your Chrome data is stored in another location or user profile, update `SOURCE_PROFILE` in `backend/app/AgentsForModules/form_filler.py`.

---

### 3. Frontend Setup

Open a new terminal window and navigate to the `frontend` folder:

```bash
cd frontend
```

#### Step 3.1: Install Dependencies

```bash
npm install
```

---

## 🏃 Running the Application

You will run the backend and frontend simultaneously in separate terminal windows.

### Terminal 1: Backend Server (Port 8000)

Make sure your virtual environment is active in `backend`:

```bash
# From the backend/ folder
uvicorn main:app --reload --host 127.0.0.1 --port 8000
```

- Backend API: `http://127.0.0.1:8000`
- Interactive Swagger API Docs: `http://127.0.0.1:8000/docs`

### Terminal 2: Frontend Server (Port 3000)

```bash
# From the frontend/ folder
npm run dev
```

- Open your browser and navigate to: **`http://localhost:3000`**

---

## 🧭 How to Use the Assistant

### Step 1: Complete User Profile (`/`)

1. Open `http://localhost:3000` in your browser.
2. Fill out your core details: **Name, Email, Contact Number, College, and Skills**.
3. Submit the form. This information is saved to SQLite (`Users.db`) and used by the Form Filler to populate web application forms automatically.

### Step 2: Upload Resume & Documents (`/resume_upload`)

1. Click **Resume Upload** in the navigation bar.
2. Select your user ID and upload your resume (`.pdf`, `.docx`, etc.).
3. Documents are saved to `backend/uploadedResumes/` and indexed for auto-attachment during job applications.

### Step 3: Issue Natural Language Commands (`/CommandsSection`)

Navigate to the **Commands** section and enter any task in plain English:

#### Example Commands to Try:

- **Web Form Automation**:
  > _"Open https://example.com/apply and fill out the internship application form using my profile."_
- **Drafting & Sending Emails**:
  > _"Draft a formal email to professor.smith@university.edu requesting a meeting regarding the research project."_
- **Google Calendar Management**:
  > _"Check my calendar for free slots tomorrow afternoon and schedule a 45-minute project review at 3 PM."_
- **Multi-Agent Pipeline**:
  > _"Schedule a meeting with my team tomorrow at 10 AM on Google Calendar, and send an email to team@company.com with the meeting details."_

#### Handling Clarifications (Human-in-the-Loop):

If an agent encounters a required field that is not in your profile (e.g., custom question or missing file), or drafts an email requiring confirmation:

- The WebSocket stream will flag an `ASKING_USER::` prompt.
- An input box, confirmation prompt, or file upload form will appear in the UI.
- Submit your answer, and the agent will unblock and complete the task.

---

## 📡 API & WebSocket Endpoints

| Method | Endpoint                           | Description                                                          |
| ------ | ---------------------------------- | -------------------------------------------------------------------- |
| `POST` | `/users/`                          | Create or update user profile details                                |
| `POST` | `/documents/{user_id}`             | Upload documents/resumes for a user                                  |
| `POST` | `/commands/`                       | Submit a natural language command to launch background AI agent task |
| `GET`  | `/commands/{task_id}`              | Retrieve command status and log history                              |
| `POST` | `/commands/{task_id}/answer`       | Submit text or confirmation response to a blocked agent              |
| `POST` | `/documents/{task_id}/answer/file` | Submit file upload response to a blocked agent                       |
| `WS`   | `/commands/ws/{task_id}`           | WebSocket stream pushing real-time agent execution status            |

---

## 🧪 Diagnostics & Testing

The project includes test and diagnostic scripts to verify your environment:

### Verify Google OAuth (Gmail & Calendar)

```bash
python backend/quickstartCalendar.py
```

_Outputs: `Gmail OK — X labels found.` and `Calendar OK — Y calendars found.`_

### Test ReAct Email Agent Tool Execution

```bash
python backend/test_agent.py
```

_Verifies that the LLM ReAct agent properly executes tool calls rather than answering directly._

### Inspect Task Statuses in SQLite

```bash
python backend/check_db.py
```

_Displays the latest command status recorded in `Users.db`._

### Run Frontend Unit Tests

```bash
cd frontend
npm run test
```

---

## 🔧 Troubleshooting & Common Pitfalls

### 1. `CORS` or Connection Refused Errors

- Make sure the backend is running on `127.0.0.1:8000` or `localhost:8000`.
- The backend CORS middleware is configured to allow `http://localhost:3000`. Ensure your frontend runs on port `3000` (which is configured in `package.json` under `"dev": "vite dev --port 3000"`).

### 2. Google OAuth Error / `token.json` Expired

- If you see `RefreshError` or invalid grant, delete `backend/token.json` and re-run:
  ```bash
  python quickstartCalendar.py
  ```
- Verify that your email is listed under **Test Users** in the Google Cloud Console OAuth consent screen.

### 3. Chrome Profile In Use / Playwright Lock Errors

- If the Form Filler throws an error indicating Chrome is locked (`SingletonLock`):
  1. Close any running Google Chrome instances before initiating the form filling command, or
  2. Delete the cloned cache folder at `C:\Users\<USER>\AppData\Local\AgentChromeProfile` to allow a clean clone.

### 4. `GEMINI_API_KEY` Missing or Invalid

- Ensure `backend/.env` exists and contains a valid key from [Google AI Studio](https://aistudio.google.com/app/apikey).
- Restart the FastAPI backend server after updating `.env`.

### 5. Playwright Browser Executable Not Found

- Run `playwright install chromium` inside the active Python virtual environment.

---
