-- Dedicated least-privilege manager for isolated index-trial schemas.
-- The MySQL official image runs files in /docker-entrypoint-initdb.d once on
-- first data-dir initialisation.
--
-- trial_admin is used ONLY by the worker for the whole isolated-schema
-- lifecycle (create/drop trial_* databases, build tables/indexes, replay the
-- user-supplied read-only queries, read catalog occupancy). The `trial%`
-- wildcard scope means it cannot touch the business `schemaworkbook` database
-- or the mysql system catalog: any cross-database query fails with 1142.
CREATE USER IF NOT EXISTS 'trial_admin'@'%' IDENTIFIED WITH mysql_native_password BY 'schemaworkbook_demo_pw';
GRANT ALL PRIVILEGES ON `trial%`.* TO 'trial_admin'@'%';
FLUSH PRIVILEGES;
