#!/usr/bin/env python3
from __future__ import annotations

import json
import os
from pathlib import Path

import pymysql


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_RULES_FILE = PROJECT_ROOT / "config" / "aftersales-exclusion-rules.json"


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


def ensure_schema(conn) -> None:
    with conn.cursor() as cur:
        cur.execute("""
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
        """)


def load_defaults() -> list[dict]:
    rules = json.loads(DEFAULT_RULES_FILE.read_text(encoding="utf-8"))
    if len(rules) != 6:
        raise ValueError("可剔除规则必须与已确认的六条清单一致")
    return rules


def seed_defaults(conn) -> int:
    rules = load_defaults()
    sql = """
        INSERT INTO dim_crm_exclusion_rule (
          problem1, problem2, problem3_pattern, note, is_enabled, updated_by
        ) VALUES (%s, %s, %s, %s, 1, 'bootstrap')
        ON DUPLICATE KEY UPDATE
          note=IF(updated_by='bootstrap', VALUES(note), note)
    """
    values = [(rule["p1"], rule["p2"], rule["p3"], rule.get("note", "")) for rule in rules]
    with conn.cursor() as cur:
        return cur.executemany(sql, values)


def remove_obsolete_bootstrap_rules(conn) -> int:
    rules = load_defaults()
    keys = [(rule["p1"], rule["p2"], rule["p3"]) for rule in rules]
    placeholders = ",".join(["(%s,%s,%s)"] * len(keys))
    with conn.cursor() as cur:
        return cur.execute(
            f"DELETE FROM dim_crm_exclusion_rule WHERE updated_by='bootstrap' AND (problem1, problem2, problem3_pattern) NOT IN ({placeholders})",
            [value for key in keys for value in key],
        )


def main() -> int:
    conn = connect_mysql()
    try:
        ensure_schema(conn)
        defaults = seed_defaults(conn)
        removed = remove_obsolete_bootstrap_rules(conn)
        conn.commit()
        print({"exclusion_rules_added_or_reconciled": defaults, "obsolete_bootstrap_rules_removed": removed})
    finally:
        conn.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
