# Database migrations

Runtime migrations are the numbered SQL files in [`feedsmith/migrations`](../feedsmith/migrations). They are package data, so a wheel or normal `pip install` contains everything needed to upgrade an existing SQLite database.

Add schema changes as a new, forward-only numbered file there and register it in `Database._apply_migrations()`. Test both an empty database and an upgrade from the preceding schema. Never rewrite a migration that has been released.
