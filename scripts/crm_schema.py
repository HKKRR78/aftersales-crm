from __future__ import annotations

import os

import pymysql


def connect_mysql():
    return pymysql.connect(
        host=os.environ.get("MYSQL_HOST", "127.0.0.1"),
        port=int(os.environ.get("MYSQL_PORT", "3306")),
        user=os.environ.get("MYSQL_USER") or os.environ.get("DB_USER") or "root",
        password=os.environ.get("MYSQL_PASSWORD") or os.environ.get("DB_PASSWORD") or "",
        database=os.environ.get("MYSQL_DATABASE") or os.environ.get("DB_NAME") or "ecom_profit",
        charset="utf8mb4",
        autocommit=False,
    )


DDL = [
    """
    CREATE TABLE IF NOT EXISTS dim_crm_source_state (
      source_system varchar(32) NOT NULL,
      analytics_enabled tinyint NOT NULL DEFAULT 0,
      analytics_start_at datetime DEFAULT NULL,
      analytics_end_at datetime DEFAULT NULL,
      approved_by varchar(128) DEFAULT NULL,
      approved_at datetime DEFAULT NULL,
      note varchar(500) DEFAULT NULL,
      PRIMARY KEY (source_system)
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci
    """,
    """
    CREATE TABLE IF NOT EXISTS dim_crm_exclusion_rule (
      problem1 varchar(128) NOT NULL,
      problem2 varchar(128) NOT NULL,
      problem3_pattern varchar(255) NOT NULL,
      note varchar(1000) NOT NULL DEFAULT '',
      is_enabled tinyint(1) NOT NULL DEFAULT 1,
      updated_by varchar(128) NOT NULL DEFAULT 'system',
      updated_at timestamp NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
      PRIMARY KEY (problem1, problem2, problem3_pattern),
      KEY idx_exclusion_rule_enabled (is_enabled, problem1, problem2)
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci
    """,
    """
    CREATE TABLE IF NOT EXISTS ods_crm_ticket_raw (
      source_system varchar(32) NOT NULL,
      source_ticket_id varchar(128) NOT NULL,
      ticket_no varchar(128) DEFAULT NULL,
      source_created_at datetime DEFAULT NULL,
      source_updated_at datetime DEFAULT NULL,
      source_version bigint DEFAULT NULL,
      content_hash char(64) NOT NULL,
      raw_payload longtext NOT NULL,
      import_batch varchar(64) NOT NULL,
      synced_at datetime NOT NULL,
      PRIMARY KEY (source_system, source_ticket_id),
      KEY idx_ticket_raw_created (source_system, source_created_at),
      KEY idx_ticket_raw_updated (source_system, source_updated_at)
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci
    """,
    """
    CREATE TABLE IF NOT EXISTS ods_crm_aftersales (
      id bigint NOT NULL AUTO_INCREMENT,
      source_system varchar(32) NOT NULL,
      source_ticket_id varchar(128) NOT NULL,
      source_item_id varchar(128) NOT NULL,
      aftersales_business_key varchar(191) NOT NULL,
      ticket_no varchar(128) DEFAULT NULL,
      source_version bigint DEFAULT NULL,
      source_status varchar(64) DEFAULT NULL,
      item_type varchar(64) DEFAULT NULL,
      included_in_analytics tinyint NOT NULL DEFAULT 1,
      shop_id varchar(128) DEFAULT NULL,
      shop_name varchar(255) DEFAULT NULL,
      platform varchar(64) DEFAULT NULL,
      order_no varchar(128) DEFAULT NULL,
      sub_order_no varchar(255) DEFAULT NULL,
      aftersale_id varchar(128) DEFAULT NULL,
      logistics_no varchar(255) DEFAULT NULL,
      problem1 varchar(255) DEFAULT NULL,
      problem2 varchar(255) DEFAULT NULL,
      problem3 varchar(255) DEFAULT NULL,
      problem_path varchar(768) DEFAULT NULL,
      handle_method varchar(255) DEFAULT NULL,
      amount decimal(18,4) DEFAULT NULL,
      refund_amount decimal(18,4) DEFAULT NULL,
      product_title varchar(768) DEFAULT NULL,
      aftersales_product_id varchar(128) DEFAULT NULL,
      buy_qty decimal(18,4) DEFAULT NULL,
      unit_price decimal(18,4) DEFAULT NULL,
      sku_attr varchar(768) DEFAULT NULL,
      merchant_code varchar(255) DEFAULT NULL,
      source_warehouse_code varchar(128) DEFAULT NULL,
      source_warehouse_name varchar(255) DEFAULT NULL,
      source_logistics_company varchar(255) DEFAULT NULL,
      refund_apply_time datetime DEFAULT NULL,
      paid_amount decimal(18,4) DEFAULT NULL,
      wdt_pay_time datetime DEFAULT NULL,
      api_created_at datetime DEFAULT NULL,
      api_updated_at datetime DEFAULT NULL,
      api_synced_at datetime NOT NULL,
      match_status varchar(128) DEFAULT NULL,
      matched_by varchar(128) DEFAULT NULL,
      warehouse_match_status varchar(32) DEFAULT NULL,
      raw_payload longtext NOT NULL,
      import_batch varchar(64) NOT NULL,
      PRIMARY KEY (id),
      UNIQUE KEY uk_crm_business_key (aftersales_business_key),
      UNIQUE KEY uk_crm_source_item (source_system, source_ticket_id, source_item_id),
      KEY idx_crm_period (included_in_analytics, wdt_pay_time, api_created_at),
      KEY idx_crm_source_updated (source_system, api_updated_at),
      KEY idx_crm_order_suborder (shop_name, order_no, sub_order_no)
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci
    """,
    """
    CREATE TABLE IF NOT EXISTS etl_crm_ticket_batches (
      batch_id varchar(64) NOT NULL,
      source_system varchar(32) NOT NULL,
      coverage_start datetime NOT NULL,
      coverage_end datetime NOT NULL,
      status varchar(32) NOT NULL,
      reconciliation_status varchar(32) NOT NULL DEFAULT 'pending',
      pages_read int NOT NULL DEFAULT 0,
      tickets_read int NOT NULL DEFAULT 0,
      fact_rows int NOT NULL DEFAULT 0,
      new_rows int NOT NULL DEFAULT 0,
      changed_rows int NOT NULL DEFAULT 0,
      missing_rows int NOT NULL DEFAULT 0,
      error_summary varchar(1000) DEFAULT NULL,
      started_at datetime NOT NULL,
      completed_at datetime DEFAULT NULL,
      PRIMARY KEY (batch_id),
      KEY idx_ticket_batch_latest (source_system, status, completed_at)
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci
    """,
]


def ensure_schema(conn) -> None:
    with conn.cursor() as cur:
        for statement in DDL:
            cur.execute(statement)
        cur.execute("""
            SELECT column_name
            FROM information_schema.columns
            WHERE table_schema=DATABASE() AND table_name='dim_crm_source_state'
              AND column_name IN ('analytics_start_at', 'analytics_end_at')
        """)
        existing_source_columns = {row[0] for row in cur.fetchall()}
        if "analytics_start_at" not in existing_source_columns:
            cur.execute("ALTER TABLE dim_crm_source_state ADD COLUMN analytics_start_at datetime DEFAULT NULL AFTER analytics_enabled")
        if "analytics_end_at" not in existing_source_columns:
            cur.execute("ALTER TABLE dim_crm_source_state ADD COLUMN analytics_end_at datetime DEFAULT NULL AFTER analytics_start_at")
        cur.execute("""
            INSERT IGNORE INTO dim_crm_source_state (source_system, analytics_enabled, note)
            VALUES ('banniu', 1, '历史来源'), ('ticket_service', 0, '交接对账通过后启用')
        """)
    conn.commit()


def main() -> int:
    conn = connect_mysql()
    try:
        ensure_schema(conn)
    finally:
        conn.close()
    print("CRM unified schema is ready")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
