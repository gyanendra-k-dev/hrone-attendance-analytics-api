# Employee Attendance & Analytics API

A small FastAPI + MongoDB service for employee attendance, manual regularization with audit history, and monthly/department analytics.

## Requirements
- Python 3.11+
- MongoDB 6.0+ (local MongoDB or MongoDB Atlas)

## Run on Windows PowerShell
```powershell
py -3.11 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
pip install -r requirements.txt
$env:MONGO_URI="mongodb://localhost:27017"
$env:MONGO_DB="attendance_db"
uvicorn app.main:app --reload --port 8000
```
For MongoDB Atlas, set `MONGO_URI` to your own connection string instead. Do not commit credentials or `.env`.

Open `http://127.0.0.1:8000/docs` for interactive API documentation. `GET /health` checks MongoDB readiness. Indexes are created automatically at startup.

## Optional sample data
With the server stopped or pointed at a throwaway database, install dependencies and run:
```powershell
python sample_seed.py
```
This replaces documents in the two collections in the configured database. **Do not run it against production data.**

## Important implementation notes
- API instants are epoch milliseconds; MongoDB stores BSON datetimes.
- Analytics are implemented with MongoDB aggregation pipelines.
- The included sample data is tiny and does not cover all edge cases. Run your own tests before submission.
- `MONGO_URI` and `MONGO_DB` environment variables override values in `.env`.


****************************************************************************
# Employee Attendance & Analytics API

A small FastAPI + MongoDB service for employee attendance, manual regularization with audit history, and monthly and department-level analytics.

## Features

- Employee creation and listing.
- Attendance punch-in and punch-out.
- Manual attendance correction with audit-history support.
- Monthly employee attendance analytics.
- Department-level attendance summary.
- Late-arrival leaderboard with ranking.
- MongoDB query explain information for performance inspection.
- Health endpoint for checking MongoDB readiness.
- MongoDB indexes for efficient queries and data consistency.

## Technology Stack

- **Language:** Python
- **API Framework:** FastAPI
- **Database:** MongoDB
- **Data Validation:** Pydantic
- **API Documentation:** Swagger UI (OpenAPI)

## Requirements

- Python 3.11+
- MongoDB 6.0+ (local MongoDB or MongoDB Atlas)

## Run on Windows PowerShell

Open the project folder in VS Code and run these commands in the terminal:

```powershell
py -3.11 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
pip install -r requirements.txt
```

Configure the MongoDB connection:

```powershell
$env:MONGO_URI="mongodb://localhost:27017"
$env:MONGO_DB="attendance_db"
```

For MongoDB Atlas, set `MONGO_URI` to your own connection string instead. Never commit database credentials, secrets, or `.env` files.

Start the API:

```powershell
python -m uvicorn app.main:app --reload --port 8000
```

## API Documentation

After starting the server, open:

- **Swagger UI:** http://127.0.0.1:8000/docs
- **Health endpoint:** http://127.0.0.1:8000/health

The health endpoint checks MongoDB readiness. Indexes are created automatically at startup.

## Project Structure

```text
hrone_attendance_project/
├── app/
│   └── main.py
├── sample_data/
├── sample_seed.py
├── requirements.txt
├── README.md
├── REVIEW.md
├── DECISIONS.md
└── .gitignore
```

The `.venv`, `.env`, and `.env.example` files are not included in the project structure above because they are environment-related files and should not contain committed secrets.

## Optional Sample Data

With the server stopped or pointed at a throwaway database, install dependencies and run:

```powershell
python sample_seed.py
```

**Warning:** This script replaces documents in the two collections in the configured database. Do not run it against production data.

## Important Implementation Notes

- API timestamps are accepted as epoch milliseconds; MongoDB stores BSON datetime values.
- Analytics are implemented using MongoDB aggregation pipelines.
- Employee codes are used as business identifiers; MongoDB `_id` should remain internal.
- Calendar dates are stored as `YYYY-MM-DD` strings.
- The sample dataset is small and does not cover every edge case.
- `MONGO_URI` and `MONGO_DB` environment variables override values configured in `.env`.

## Testing Notes

The main API workflows have been exercised during development, including employee operations, attendance workflows, analytics, and query explain functionality.

Further validation is recommended for edge cases, concurrent requests, timezone handling, overnight shifts, and complete audit-history behavior.

## Project Documents

- `REVIEW.md` — Code review findings and areas requiring further validation.
- `DECISIONS.md` — Key design decisions and their rationale.

## Security

- Do not commit `.env` files, database credentials, API keys, or other secrets.
- Keep `.venv/` and Python cache files out of version control.
- Use a test database when running sample data scripts.

