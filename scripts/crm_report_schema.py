"""Immutable report batches; publication is a single transactional pointer."""
from __future__ import annotations

from crm_schema import connect_mysql

DDL = [
    """CREATE TABLE IF NOT EXISTS crm_wechat_order_artifact (
      proof_id char(64) PRIMARY KEY, shop_key varchar(128) NOT NULL,
      source_filename varchar(512) NOT NULL, evidence_json longtext NOT NULL,
      KEY idx_wechat_artifact(shop_key,source_filename)
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_bin""",
    """CREATE TABLE IF NOT EXISTS crm_original_order_read_batch (
      batch_id varchar(64) PRIMARY KEY, status varchar(24) NOT NULL,
      scope_end date NOT NULL, source_batch_id varchar(64) NOT NULL,
      started_at datetime NOT NULL, completed_at datetime NULL,
      summary_json longtext NOT NULL, error_summary varchar(1000) NULL
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_bin""",
    """CREATE TABLE IF NOT EXISTS crm_pdd_order_manifest (
      manifest_sha256 char(64) PRIMARY KEY, manifest_path varchar(768) NOT NULL,
      source_log_path varchar(768) NOT NULL, source_log_sha256 char(64) NOT NULL,
      period_start date NOT NULL, period_end date NOT NULL, observed_at datetime NOT NULL
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_bin""",
    """CREATE TABLE IF NOT EXISTS crm_native_snapshot_proof (
      proof_id char(64) PRIMARY KEY, platform varchar(64) NOT NULL,
      shop_key varchar(128) NOT NULL, coverage_start date NOT NULL, coverage_end date NOT NULL,
      observed_at datetime NOT NULL, evidence_json longtext NOT NULL,
      KEY idx_native_snapshot_scope(platform,shop_key,coverage_end,observed_at)
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_bin""",
    """CREATE TABLE IF NOT EXISTS crm_original_order_proof (
      platform varchar(64) NOT NULL, shop_key varchar(128) NOT NULL, order_no varchar(128) NOT NULL,
      observed_at datetime NOT NULL, endpoint varchar(128) NOT NULL,
      content_hash char(64) NOT NULL, artifact_path varchar(768) NOT NULL,
      original_order_json longtext NOT NULL,
      PRIMARY KEY(platform,shop_key,order_no,content_hash),
      KEY idx_original_order_observed(platform,shop_key,order_no,observed_at)
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_bin""",
    """CREATE TABLE IF NOT EXISTS crm_ticket_absence_evidence (
      batch_id varchar(64) NOT NULL, source_system varchar(32) NOT NULL,
      source_ticket_id varchar(128) NOT NULL, observed_at datetime NOT NULL,
      evidence_json longtext NOT NULL,
      PRIMARY KEY(batch_id,source_system,source_ticket_id)
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_bin""",
    """CREATE TABLE IF NOT EXISTS crm_report_denominator_status (
      batch_id varchar(64) NOT NULL, period_start date NOT NULL, period_end date NOT NULL,
      grain_type varchar(32) NOT NULL, grain_key varchar(512) NOT NULL,
      is_complete tinyint NOT NULL, reason varchar(128) NOT NULL,
      PRIMARY KEY(batch_id,period_start,period_end,grain_type,grain_key)
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_bin""",
    """CREATE TABLE IF NOT EXISTS crm_ticket_read_segment (
      batch_id varchar(64) NOT NULL, segment_start datetime NOT NULL, segment_end datetime NOT NULL,
      tickets_read int NOT NULL, pages_read int NOT NULL, content_digest char(64) NOT NULL,
      PRIMARY KEY(batch_id,segment_start)
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_bin""",
    """CREATE TABLE IF NOT EXISTS crm_report_batch (
      batch_id varchar(64) PRIMARY KEY, status varchar(24) NOT NULL,
      started_at datetime NOT NULL, completed_at datetime NULL,
      coverage_start date NOT NULL, coverage_end date NOT NULL,
      source_batch_id varchar(64) NOT NULL, source_synced_at datetime NOT NULL,
      issue_count int NOT NULL DEFAULT 0, summary_json longtext NOT NULL,
      evidence_path varchar(768) NOT NULL, error_summary varchar(1000) NULL
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_bin""",
    """CREATE TABLE IF NOT EXISTS crm_report_current (
      singleton tinyint PRIMARY KEY, batch_id varchar(64) NOT NULL,
      published_at datetime NOT NULL
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_bin""",
    """CREATE TABLE IF NOT EXISTS crm_report_issue (
      batch_id varchar(64) NOT NULL, issue_key char(64) NOT NULL,
      source_fact_id bigint NULL, source_system varchar(32) NOT NULL,
      source_ticket_id varchar(128) NOT NULL, source_item_id varchar(128) NOT NULL,
      created_at datetime NOT NULL, platform varchar(64) NOT NULL,
      shop_key varchar(128) NOT NULL, raw_code varchar(255) NOT NULL,
      merchant_code varchar(512) NOT NULL, product_id varchar(128) NOT NULL,
      product_title varchar(768) NOT NULL, denominator_key varchar(64) NOT NULL,
      problem1 varchar(255) NOT NULL, problem2 varchar(255) NOT NULL, problem3 varchar(255) NOT NULL,
      warehouse_code varchar(128) NOT NULL, warehouse_name varchar(255) NOT NULL,
      included_operating tinyint NOT NULL,
      match_status varchar(24) NOT NULL, match_reason varchar(128) NOT NULL,
      evidence_json longtext NOT NULL,
      PRIMARY KEY(batch_id,issue_key), KEY idx_report_created(batch_id,created_at),
      KEY idx_report_fact(batch_id,source_fact_id)
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_bin""",
    """CREATE TABLE IF NOT EXISTS crm_issue_migration_map (
      left_input_key char(64) NOT NULL, right_input_key char(64) NOT NULL,
      evidence_json longtext NOT NULL, approved_by varchar(128) NOT NULL,
      approved_at datetime NOT NULL,
      PRIMARY KEY(left_input_key,right_input_key)
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_bin""",
    """CREATE TABLE IF NOT EXISTS crm_report_issue_source (
      batch_id varchar(64) NOT NULL, input_key char(64) NOT NULL,
      canonical_issue_key char(64) NOT NULL, source_fact_id bigint NULL,
      source_system varchar(32) NOT NULL, source_ticket_id varchar(128) NOT NULL,
      source_item_id varchar(128) NOT NULL, decision varchar(32) NOT NULL,
      decision_reason varchar(128) NOT NULL, evidence_json longtext NOT NULL,
      PRIMARY KEY(batch_id,input_key),
      KEY idx_issue_source_canonical(batch_id,canonical_issue_key)
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_bin""",
    """CREATE TABLE IF NOT EXISTS crm_report_orders (
      batch_id varchar(64) NOT NULL, period_start date NOT NULL, period_end date NOT NULL,
      grain_type varchar(32) NOT NULL, grain_key varchar(512) NOT NULL,
      order_count bigint NOT NULL, sales_qty decimal(20,4) NOT NULL,
      PRIMARY KEY(batch_id,period_start,period_end,grain_type,grain_key)
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_bin""",
    """CREATE TABLE IF NOT EXISTS crm_report_product_metric (
      batch_id varchar(64) NOT NULL, period_start date NOT NULL, period_end date NOT NULL,
      merchant_code varchar(512) NOT NULL,
      order_count bigint NULL, sales_qty decimal(20,4) NULL,
      order_status varchar(32) NOT NULL, sales_status varchar(32) NOT NULL,
      reason varchar(255) NOT NULL, source_batch varchar(128) NOT NULL,
      source_artifact varchar(768) NOT NULL, evidence_hash char(64) NOT NULL,
      PRIMARY KEY(batch_id,period_start,period_end,merchant_code)
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_bin""",
    """CREATE TABLE IF NOT EXISTS crm_report_coverage (
      batch_id varchar(64) NOT NULL, platform varchar(64) NOT NULL,
      shop_key varchar(128) NOT NULL, stat_date date NOT NULL,
      status varchar(24) NOT NULL, reason varchar(255) NOT NULL,
      evidence_json longtext NOT NULL,
      PRIMARY KEY(batch_id,platform,shop_key,stat_date)
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_bin""",
    """CREATE TABLE IF NOT EXISTS crm_ticket_version (
      source_system varchar(32) NOT NULL, source_ticket_id varchar(128) NOT NULL,
      content_hash char(64) NOT NULL, observed_at datetime NOT NULL,
      import_batch varchar(64) NOT NULL, raw_payload longtext NOT NULL,
      PRIMARY KEY(source_system,source_ticket_id,content_hash)
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_bin""",
]


def ensure_report_schema(conn):
    with conn.cursor() as cur:
        for statement in DDL:
            cur.execute(statement)
    conn.commit()


if __name__ == '__main__':
    conn = connect_mysql()
    try:
        ensure_report_schema(conn)
    finally:
        conn.close()
