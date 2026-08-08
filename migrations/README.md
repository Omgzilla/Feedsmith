# Database migrations

The initial schema is created by `feedsmith.core.database.Database` when an empty SQLite database is opened. Future incompatible changes must be added as numbered, forward-only migrations in this directory and applied by the database layer before an existing deployment uses the new schema. Do not rewrite an already released migration.
