# Starter code review

| # | Where | What is wrong | How to notice | Fix |
|---|---|---|---|---|
| 1 | `compute_late_minutes` | Uses the datetime's existing timezone/naive local time and does not consistently convert the punch to IST. | Same epoch punch can produce different results on machines in different time zones. | Normalize instants to UTC and compare with shift boundaries built in IST. |
| 2 | `compute_late_minutes` | Late minutes are calculated using truncating `int()` and grace handling is not expressed against exact seconds; boundary cases can be mishandled. | Test 09:40:00 versus 09:40:01 for a 09:30 shift. | Compare exact elapsed seconds to 600, then floor whole minutes from shift start. |
| 3 | `compute_work_hours` | Python `round()` uses bankers' rounding, not required half-up rounding. | A duration whose second decimal is exactly a half boundary can round differently. | Use `Decimal` with `ROUND_HALF_UP`. |
| 4 | `compute_overtime` | Does not correctly handle overnight shifts; end is always on the attendance date. | 22:00–06:00 shift and punch-out next morning. | Resolve the shift end on the next calendar day for overnight shifts. |
| 5 | `health` | Always returns 200 without checking MongoDB. | Stop MongoDB and call `/health`. | Ping MongoDB and return 503 on failure. |
| 6 | `create_employee` | Duplicate check then insert is race-prone without a unique index; created timestamp is naive. | Parallel create requests with same `emp_code`; inspect BSON timezone handling. | Unique index handles races; catch duplicate-key error; store aware UTC timestamp. |
| 7 | `EmployeeIn` | Does not validate employee-code, email, shift time, string lengths, or date format against contract. | Submit malformed `emp_code`, shift or `joined_on`. | Add Pydantic field constraints and validators. |
| 8 | `list_employees` | Skip is `page * page_size` instead of `(page - 1) * page_size`; total ignores filters; there is no sorting or bounds. | Page 1 omits first page; filtered total is wrong. | Correct skip, count filtered query, sort by `emp_code`, validate pagination. |
| 9 | `punch_in` | Missing employee causes a server error; invalid status is accepted; timestamp uses local timezone and seconds are not truncated. | Unknown employee or string/seconds timestamp. | Return 404, validate status and epoch milliseconds, normalize/truncate timestamp. |
| 10 | `punch_in` | Check-then-insert permits concurrent duplicate records; record date is not reliably IST and overnight shift dates are wrong. | Send simultaneous punch-ins or punch into overnight shift before shift end. | Unique `(emp_code,date)` index, catch duplicate key, compute attendance day using IST shift rule. |
| 11 | `punch_in` | Response leaks a synthetic `id`, which is not part of the contract. | Inspect response body. | Return contract fields only and never expose MongoDB `_id`. |
| 12 | `list_attendance` | Loads all matching records into Python, then sorts/pages in memory; leaks MongoDB IDs and lacks validation. | Large dataset / response includes `id`. | Count and page in MongoDB with indexed filters, deterministic sort, omit `_id`. |
| 13 | Missing endpoints | Punch-out, regularization, analytics, and explain endpoint are absent. | Call endpoints from `openapi.yaml`. | Implemented in `app/main.py`; see README for run instructions. |
| 14 | Concurrency / regularization | Starter has no atomic punch-out or audit-safe correction operation. | Parallel punch-outs or two concurrent corrections. | Conditional atomic updates and `$push` for history; unique index protects punch-in. |

## Reviewed and retained
- Keeping `emp_code` as the business identifier is correct; MongoDB `_id` must remain internal.
- Storing calendar dates as `YYYY-MM-DD` strings is intentional and makes inclusive date filters straightforward.
- Analytics must use stored derived values, not recompute them from timestamps.

**********************************************************************************

# Code Review — Employee Attendance & Analytics API

## 1. Overview

This project implements an Employee Attendance and Analytics API using Python, FastAPI, and MongoDB. The API supports employee management, attendance punch-in and punch-out, attendance corrections, monthly analytics, department summaries, a late-arrival leaderboard, and MongoDB query explain information.

## 2. Areas Reviewed

- Employee creation and retrieval.
- Attendance punch-in and punch-out workflows.
- Attendance status, late minutes, work hours, and half-day calculations.
- Manual attendance correction.
- Monthly employee attendance analytics.
- Department-level attendance summary.
- Late-arrival leaderboard.
- MongoDB indexes and query execution details.

## 3. Improvements and Observations

- Added and verified API endpoints for employee management and attendance workflows.
- Used MongoDB for storing and querying employee and attendance records.
- Added monthly analytics and department-level aggregation endpoints.
- Exposed MongoDB explain information to help inspect query execution and index usage.
- Verified successful HTTP responses for the main API workflows using the interactive API documentation.

## 4. Areas Requiring Further Validation

- Validate attendance calculations across different shifts, dates, and time zones.
- Test duplicate punch-in requests and invalid punch-out sequences.
- Verify that manual corrections preserve a complete audit history, including the previous and updated values.
- Test monthly analytics for employees with no attendance records, leave records, and month-boundary cases.
- Add broader automated tests for validation errors and edge cases.

## 5. Conclusion

The main API workflows were exercised successfully during development. Further edge-case testing, audit-history verification, and automated test coverage would improve confidence in the API's correctness and maintainability.