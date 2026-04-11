# Finance Tracker

Finance Tracker is a planning-first budgeting application for people who want a clear monthly money picture without the overhead of a full accounting system.

The core intention is simple:
- Help you plan a month before it happens.
- Help you track what actually happened during the month.
- Help you reconcile your records over time so your plan and reality stay aligned.

## Purpose and Intentions

Many personal finance tools focus heavily on historical reporting. Finance Tracker is designed around a practical monthly workflow:
1. Start with a recurring template of expected income and expenses.
2. Initialize a month from that plan.
3. Update each transaction as it moves from estimated to actual to reconciled.
4. Keep a live view of balances and net position while you work.

This is intended to make budgeting an active process, not a once-a-month spreadsheet task.

## What the App Does

At a high level, Finance Tracker supports:

- Monthly planning and tracking:
Create and manage month-specific transaction lists with separate income and expense sections.

- Recurring templates:
Build reusable recurring entries and apply them to new months.

- Status-driven transaction flow:
Move transactions through estimated, actual, and reconciled states as real-world activity occurs.

- Balance awareness:
Track running balances with both tabular summaries and visual trend views.

- Fast inline editing:
Edit dates, payees/sources, categories, amounts, notes, and flags directly in the tables.

- Guided data entry:
Use draft/ghost-row behavior, keyboard-first navigation, and suggestion pickers to enter data quickly.

- Template syncing:
Push month transaction changes back into template data when your recurring baseline evolves.

## Intended Audience

Finance Tracker is built for:

- Individuals and households who budget monthly and want a lightweight but structured workflow.
- Users who prefer hands-on control over categories, payees, and recurring assumptions.
- People who want a planning tool that still supports reconciliation discipline.

It is especially useful for users who currently maintain manual spreadsheets and want a faster interface without giving up visibility and control.

## Scope of This Document

This README is intentionally product-focused.

Technical architecture, deployment, and operational details are documented separately and will continue to evolve as the project is prepared for containerized deployment.

## Versioning And Migrations

Finance Tracker uses SemVer for the application release version. The current version lives in the root [VERSION](VERSION) file and is exposed by the app through `/api/meta`.

The rules are simple:

- Patch releases are backward-compatible bug fixes.
- Minor releases add backward-compatible features or endpoints.
- Major releases are reserved for breaking changes, especially schema changes that require data or code coordination.

SQLite schema changes are versioned separately from the app release version. The database stores its schema version in `PRAGMA user_version`, and the app applies ordered migrations on startup before serving requests. This keeps upgrades deterministic and makes the current schema state easy to inspect.

When you add a schema change:

1. Add a new migration function in [db_migrations.py](db_migrations.py).
2. Bump the schema version there.
3. Bump the app version in [VERSION](VERSION) if the release includes user-visible changes.
4. Run the app once so the migration applies before normal use.

Docker builds also carry the app version as image metadata and tag release images with the same SemVer value.

## Run With Docker

Finance Tracker can run in Docker with a persistent SQLite database volume.
The container runs the Flask app with a modest Gunicorn setup: one worker with a small thread pool.

1. Build and start:

```bash
docker compose up --build -d
```

2. Open:

```text
http://localhost:5757
```

3. Stop:

```bash
docker compose down
```

The application stores its database in `FINANCE_TRACKER_DATA_DIR`, which is set to `/data` in the container.
With the provided `docker-compose.yml`, `/data` is backed by the named volume `finance_tracker_data`, so `tracker.db` is preserved across container restarts and image upgrades.

If you need to inspect the volume:

```bash
docker volume inspect finance_tracker_data
```

## GitHub Actions Publish

On every push to `main`, GitHub Actions builds the Docker image and pushes it to DockerHub.

Create these repository settings in GitHub:

- Repository variables:
	- `DOCKERHUB_USERNAME`: your DockerHub account name.
	- `DOCKERHUB_REPOSITORY`: the full image name to push, such as `yourname/finance-tracker`.
- Repository secret:
	- `DOCKERHUB_TOKEN`: a DockerHub access token with read and write access.

Use a DockerHub access token, not your account password. If your DockerHub account has two-factor authentication enabled, the token is required.
