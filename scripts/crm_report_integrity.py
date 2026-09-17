"""Bind report tables to the exact immutable data that passed reconciliation."""
import hashlib

from crm_report_model import canonical

TABLE_KEYS = {
    'crm_report_issue': 'issue_key',
    'crm_report_issue_source': 'input_key',
    'crm_report_orders': 'period_start,period_end,grain_type,grain_key',
    'crm_report_product_metric': 'period_start,period_end,merchant_code',
    'crm_report_denominator_status': 'period_start,period_end,grain_type,grain_key',
    'crm_report_coverage': 'platform,shop_key,stat_date',
}


def record_sets(conn, batch):
    result = {}
    for table, keys in TABLE_KEYS.items():
        digest = hashlib.sha256(); count = 0
        with conn.cursor() as cur:
            cur.execute(f'SELECT * FROM {table} WHERE batch_id=%s ORDER BY {keys}', (batch,))
            columns = [column[0] for column in cur.description]
            while True:
                rows = cur.fetchmany(500)
                if not rows: break
                for values in rows:
                    row = dict(values) if isinstance(values, dict) else dict(zip(columns, values))
                    row.pop('batch_id')
                    digest.update(canonical(row).encode() + b'\n'); count += 1
        result[table] = {'rows': count, 'sha256': digest.hexdigest()}
    return result


def require_record_sets(conn, batch, expected):
    if not expected or set(expected) != set(TABLE_KEYS) or record_sets(conn, batch) != expected:
        raise ValueError('report facts, denominators or coverage changed after reconciliation')
