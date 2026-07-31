-- Layer schemas for the medallion layout (ADR-003).
-- Apply as a migration owner / superuser before roles and grants.

CREATE SCHEMA IF NOT EXISTS bronze;
CREATE SCHEMA IF NOT EXISTS silver;
CREATE SCHEMA IF NOT EXISTS gold;
