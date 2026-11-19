-- Index selection trials (feature: 索引选型试验).
-- Applied idempotently by SQLAlchemy metadata.create_all; this file is the
-- reference DDL for environments that provision schema manually. MySQL 8.0 / InnoDB.

CREATE TABLE IF NOT EXISTS index_trials (
  id INTEGER NOT NULL AUTO_INCREMENT,
  name VARCHAR(120) NOT NULL,
  report_id INTEGER NOT NULL,
  status VARCHAR(20) NOT NULL DEFAULT 'queued',
  run_token VARCHAR(40) NOT NULL,
  input_snapshot JSON NOT NULL,
  result JSON NULL,
  error TEXT NULL,
  created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (id),
  CONSTRAINT fk_index_trials_report FOREIGN KEY (report_id) REFERENCES reports (id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS index_trial_combos (
  id INTEGER NOT NULL AUTO_INCREMENT,
  trial_id INTEGER NOT NULL,
  combo_key VARCHAR(200) NOT NULL,
  index_specs JSON NOT NULL,
  status VARCHAR(20) NOT NULL DEFAULT 'pending',
  measurements JSON NULL,
  error TEXT NULL,
  measured_at DATETIME NULL,
  PRIMARY KEY (id),
  KEY ix_index_trial_combos_trial (trial_id),
  CONSTRAINT fk_index_trial_combos_trial FOREIGN KEY (trial_id) REFERENCES index_trials (id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
