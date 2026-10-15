# Design decisions

1. **Indexes.** A unique index on `employees.emp_code` protects employee identity. The unique compound `(emp_code, date)` attendance index is the concurrency guarantee for one record per employee/day and supports employee/date lookups. Department/employee and department/join-date indexes support employee listings and headcount. Attendance indexes on date/employee, status/date and date/late-minutes support filtered lists and month-based analytics. I did not add an index for every field combination because extra indexes slow writes and consume storage.

2. **Punch-in race.** Both requests may read the employee, but the unique `(emp_code, date)` index lets only one insert succeed. The winning request returns 201; the other insert raises duplicate-key and returns 409. The application does not rely on a pre-insert existence check for correctness.

3. **Ties.** The leaderboard uses MongoDB `$rank`, not array positions. If the cutoff rank is tied, every employee with rank at or below `limit` is returned, even when that makes the result longer than the limit. Ties are ordered by employee code for stable output.

4. **Headcount.** The department summary starts from employees who joined by the end of the month and then looks up their attendance. Employees with no logs remain in the result, so headcount does not depend on attendance records.

5. **100x data.** I would review explain plans against representative data, consider pre-aggregated monthly summaries if the product permits eventual consistency, and add load tests and metrics before scaling the database tier.
