"""Pure, source-preserving rules for the CRM report. No I/O or guessed SKUs."""
from __future__ import annotations

import hashlib
import json
from collections import defaultdict
from datetime import date, datetime, timedelta
from decimal import Decimal


def text(value):
    return '' if value is None else str(value).strip()


def canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'), default=str)


def identity(*values):
    return hashlib.sha256(canonical(list(values)).encode()).hexdigest()


def source_fact_key(row):
    return identity(text(row.get('source_system')), text(row.get('source_ticket_id')), text(row.get('source_item_id')))


def _duplicate_proof_key(row):
    """Return only a source-native event identity strong enough to merge.

    Similar titles, base merchant codes, order numbers, and timestamps are
    deliberately absent.  They can identify review candidates, but they do
    not prove that two independently created tickets are one business event.
    """
    source=text(row.get('source_system'))
    aftersale=text(row.get('aftersale_id')) or (text(row.get('ticket_no')) if source=='banniu' else '')
    order=text(row.get('order_no'));sub=text(row.get('sub_order_no'))
    # Stable shop name is present in both systems; the migrated Banniu rows do
    # not carry the new system's internal shop id or normalized platform code.
    shop=text(row.get('shop_name')) or text(row.get('shop_id'))
    item=text(row.get('aftersales_product_id')) or text(row.get('merchant_code'))
    if not all((aftersale,order,sub,shop,item)):return None
    return shop,order,sub,aftersale,item


def reconcile_source_facts(rows, approved_pairs=()):
    """Build one canonical issue set while retaining every source reference.

    Approved mappings and exact platform aftersale identities are the only
    automatic cross-source merge evidence.  A different ticket remains a
    separate issue when no such evidence exists.
    """
    by_key={source_fact_key(row):dict(row) for row in rows}
    if len(by_key)!=len(rows):raise ValueError('source issue identities are not unique')
    parent={key:key for key in by_key}
    reasons={}
    def find(key):
        while parent[key]!=key:
            parent[key]=parent[parent[key]];key=parent[key]
        return key
    def union(a,b,reason):
        if a not in by_key or b not in by_key:raise ValueError('approved migration mapping references a missing source issue')
        left,right=find(a),find(b)
        if left!=right:parent[right]=left
        reasons[frozenset((a,b))]=reason
    for pair in approved_pairs:
        union(text(pair['left_input_key']),text(pair['right_input_key']),'approved_migration_mapping')
    proof_groups=defaultdict(list)
    for key,row in by_key.items():
        proof=_duplicate_proof_key(row)
        if proof:proof_groups[proof].append(key)
    for keys in proof_groups.values():
        sources=[text(by_key[key]['source_system']) for key in keys]
        if len(keys)==2 and len(set(sources))==2:
            left,right=keys
            semantic=('problem1','problem2','problem3','order_no','sub_order_no')
            if any(text(by_key[left].get(field))!=text(by_key[right].get(field)) for field in semantic):
                raise ValueError('cross-source duplicate evidence conflicts on business fields')
            union(left,right,'exact_platform_aftersale_identity')
    groups=defaultdict(list)
    for key in by_key:groups[find(key)].append(key)
    canonical=[]
    for keys in groups.values():
        keys=sorted(keys);members=[by_key[key] for key in keys]
        if len({text(row['source_system']) for row in members})!=len(members):
            raise ValueError('cross-source reconciliation merged two issues from one source')
        if len(members)>1:
            for field in ('order_no','sub_order_no','problem1','problem2','problem3'):
                values={text(row.get(field)) for row in members}
                if len(values)>1:raise ValueError(f'cross-source reconciliation conflicts on {field}')
            products={text(row.get('aftersales_product_id')) or text(row.get('merchant_code')) for row in members}
            products.discard('')
            if len(products)>1:raise ValueError('cross-source reconciliation conflicts on source product identity')
        primary=max(members,key=lambda row:(text(row['source_system'])=='ticket_service',str(row.get('api_updated_at') or ''),str(row.get('id') or '')))
        row=dict(primary)
        canonical_key=keys[0] if len(keys)==1 else identity('reconciled_issue',keys)
        reason='distinct_source_issue' if len(keys)==1 else next((value for pair,value in reasons.items() if pair.issubset(keys)),'exact_platform_aftersale_identity')
        refs=[dict(input_key=key,source_system=text(by_key[key]['source_system']),
                   source_ticket_id=text(by_key[key]['source_ticket_id']),source_item_id=text(by_key[key]['source_item_id']),
                   source_fact_id=by_key[key].get('id')) for key in keys]
        row['_canonical_issue_key']=canonical_key
        row['_source_inputs']=refs
        row['_reconciliation_reason']=reason
        if len(refs)>1:row['source_system']='+'.join(sorted({ref['source_system'] for ref in refs}))
        canonical.append(row)
    canonical.sort(key=lambda row:(row['api_created_at'],row['_canonical_issue_key']))
    return canonical


def link_key(platform, shop_key, product_id, code):
    return identity(platform, shop_key, product_id, code) if platform and shop_key and product_id and code else ''


def sunday(day):
    return day - timedelta(days=(day.weekday() + 1) % 7)


def legacy_current_facts(rows):
    """Reconstruct each task from its newest complete embedded task snapshot.

    The old child key contains mutable order fields. It is not evidence that an
    old child still exists. Original database rows remain untouched for audit.
    """
    groups = defaultdict(list)
    for row in rows:
        groups[text(row['source_ticket_id'])].append(row)
    result, retired = [], []
    for ticket, existing in groups.items():
        latest = max(existing, key=lambda r: (str(r.get('api_updated_at') or ''), str(r.get('api_synced_at') or ''), r['id']))
        payload = json.loads(latest['raw_payload'])
        task = payload['task']
        children = task.get('13174', '')
        if isinstance(children, str):
            children = json.loads(children) if children.strip() else []
        if not isinstance(children, list) or any(not isinstance(item, dict) for item in children):
            raise ValueError(f'invalid complete task snapshot: {ticket}')
        children = children or [{}]  # one real unassigned ticket; never invent a SKU
        by_payload = defaultdict(list)
        for row in existing:
            by_payload[canonical(json.loads(row['raw_payload']).get('child', {}))].append(row)
        retained = set()
        for ordinal, child in enumerate(children):
            matches = by_payload.get(canonical(child), [])
            row = dict(max(matches, key=lambda r: r['id']) if matches else latest)
            # The historical import sometimes preserved a merchant code from
            # the source row even when the newest embedded child omitted it.
            # Keep it as audit evidence; never publish it without a second,
            # exact source proof.
            row['_imported_merchant_code'] = text(row.get('merchant_code'))
            source_id = row['id'] if matches else None
            if source_id is not None:
                retained.add(source_id)
            row.update(id=source_id, source_item_id=identity(ticket, child, ordinal),
                       merchant_code=text(child.get('13182')), sub_order_no=text(child.get('13175')),
                       product_title=text(child.get('13176')), aftersales_product_id=text(child.get('13177')),
                       buy_qty=child.get('13178') or None, sku_attr=text(child.get('13180')),
                       raw_payload=canonical({'task': task, 'child': child}))
            # Common fields belong to the latest complete task, not a stale child.
            for field in ('problem1', 'problem2', 'problem3', 'shop_name', 'order_no',
                          'api_created_at', 'api_updated_at', 'source_warehouse_code', 'source_warehouse_name'):
                row[field] = latest.get(field)
            result.append(row)
        retired.extend(r['id'] for r in existing if r['id'] not in retained)
    return result, retired


def resolve_sale(fact, candidates, *, order_complete=False):
    """Resolve an issue only to a real, preserved platform sales line.

    A native child key (including an exact WDT four-field bridge added to the
    sale's ``sub_keys``) is conclusive.  If the source child is missing or
    wrong, a complete order may be used only when every line has the same
    complete sales specification.  Titles, amounts, logistics numbers, raw
    merchant codes and intended-product fields are diagnostic evidence only;
    they can expose a conflict but can never select a winner.
    """
    source_sub = text(fact.get('sub_order_no'))
    if not candidates:
        return {'status': 'missing', 'reason': 'original_sales_line_missing', 'code': '', 'sales': []}

    direct = [sale for sale in candidates if source_sub and source_sub in sale['sub_keys']]
    if direct:
        candidates = direct
        recovered_reason = 'native_suborder'
    else:
        # Auxiliary evidence is retained only to detect contradictions.  It
        # cannot turn a row into a verified match.
        proof_groups=[]
        product_id=text(fact.get('aftersales_product_id'))
        title=text(fact.get('product_title'))
        logistics=text(fact.get('logistics_no'))
        raw_code=text(fact.get('merchant_code'))
        if product_id:
            proof_groups.append(('native_product_id',[sale for sale in candidates if sale.get('product_id')==product_id]))
            proof_groups.append(('native_sku_id',[sale for sale in candidates if sale.get('native_sku_id')==product_id]))
        if title:proof_groups.append(('native_exact_product_title',[sale for sale in candidates if sale.get('native_product_title')==title]))
        if logistics:proof_groups.append(('native_logistics_no',[sale for sale in candidates if sale.get('native_logistics_no')==logistics]))
        if raw_code:proof_groups.append(('native_exact_merchant_code',[sale for sale in candidates if sale.get('code')==raw_code]))
        amount=fact.get('amount')
        if amount not in (None,''):
            try:
                wanted=Decimal(str(amount))
                proof_groups.append(('native_exact_refund_amount',[sale for sale in candidates
                    if sale.get('native_refund_amount') not in (None,'')
                    and Decimal(str(sale['native_refund_amount']))==wanted]))
            except Exception:
                pass
        # An auxiliary attribute is informative only when it identifies one
        # original line inside this complete order. A title or base code shared
        # by several lines is ambiguous, not several contradictory votes.
        proofs=[(reason,rows[0]) for reason,rows in proof_groups if len(rows)==1]
        identities={sale['line_key'] for _,sale in proofs}
        if len(identities)>1:
            involved=[sale for sale in candidates if sale['line_key'] in identities]
            return {'status':'conflict','reason':'evidence_conflict','code':'','sales':involved,
                    'evidence_hits':[{'reason':reason,'line_key':sale['line_key']} for reason,sale in proofs]}
        codes={sale.get('code','') for sale in candidates}
        if order_complete and len(codes)==1 and '' not in codes and all(sale.get('sales_identity_known',True) for sale in candidates):
            recovered_reason='native_unique_complete_order_invalid_source_child'
        else:
            return {'status':'missing','reason':'suborder_not_found','code':'','sales':candidates,
                    'evidence_hits':[{'reason':reason,'line_key':sale['line_key']} for reason,sale in proofs]}
    if any(not s['code'] for s in candidates):
        return {'status': 'missing', 'reason': 'native_sales_code_missing', 'code': '', 'sales': candidates}
    codes = {s['code'] for s in candidates}
    if len(codes) != 1:
        return {'status': 'conflict', 'reason': 'multiple_sales_specs', 'code': '', 'sales': candidates}
    return {'status': 'verified', 'reason': recovered_reason,
            'code': next(iter(codes)), 'sales': candidates}


class SalesAggregation:
    """Distinct real orders, original purchase quantities, exact sales specs.

    Prefixes within each Sunday week support both existing report modes. Order
    sets are re-counted for every prefix; daily distinct counts are never added.
    """
    def __init__(self):
        self.lines = {}

    def add(self, sale):
        key = sale['line_key']
        previous = self.lines.get(key)
        if previous is not None:
            if previous != sale:
                raise ValueError(f'conflicting native sales line {key}')
            return
        self.lines[key] = sale

    def periods(self, start, end):
        values = {}
        for sale in self.lines.values():
            if not sale['shipped'] or not sale.get('sales_identity_known', True):
                continue
            paid = sale['paid_at'].date() if isinstance(sale['paid_at'], datetime) else date.fromisoformat(str(sale['paid_at'])[:10])
            if not start <= paid < end:
                continue
            week = sunday(paid)
            grains = [('total', '__all__'), ('merchant_code', sale['code'])]
            if sale.get('link_key'):
                grains.append(('sales_link', sale['link_key']))
            # Only a proven single warehouse owns a whole sales line's quantity.
            if sale.get('warehouse'):
                grains.append(('warehouse', sale['warehouse']))
                if sale.get('link_key'):
                    grains.append(('warehouse_sales_link', sale['warehouse']+'|'+sale['link_key']))
            for day_offset in range((paid - week).days + 1, 8):
                stop = week + timedelta(days=day_offset)
                if stop > end:
                    continue
                for grain, code in grains:
                    if not code:
                        continue
                    bucket = values.setdefault((week, stop, grain, code), [set(), Decimal(0)])
                    bucket[0].add(sale['order_key'])
                    bucket[1] += sale['quantity']
        return [(a, b, grain, key, len(v[0]), v[1]) for (a, b, grain, key), v in values.items()]

    def coverage(self, start, end):
        """Mark exactly the affected denominator; missing keys affect all keys.

        One uncertain A*3 shipment does not erase proven A*6 sales. If the
        uncertain row has no spec or warehouse, every scope of that grain is
        uncertain because that row could belong to any of them.
        """
        result=[]
        stop=start+timedelta(days=1)
        while stop<=end:
            rows=[s for s in self.lines.values() if start <= s['paid_at'].date() < stop]
            missing={grain:{} for grain in ('total','merchant_code','sales_link','warehouse','warehouse_sales_link')}
            for sale in rows:
                shipping_known=sale.get('shipping_known',False)
                if not sale['shipped'] and shipping_known:continue
                reason=('sales_line_identity_incomplete' if not sale.get('sales_identity_known',True)
                        else 'shipping_evidence_incomplete' if not shipping_known else '')
                warehouse=sale.get('warehouse','');link=sale.get('link_key','')
                keys={'total':'__all__','merchant_code':sale['code'],'sales_link':link,'warehouse':warehouse,
                      'warehouse_sales_link':warehouse+'|'+link if warehouse and link else ''}
                for grain,key in keys.items():
                    if reason or not key:
                        missing[grain].setdefault(key,reason or 'grain_evidence_incomplete')
            for grain,invalid in missing.items():
                result.append((start,stop,grain,'',int('' not in invalid),invalid.get('','native_sales_verified')))
                for key,reason in sorted(invalid.items()):
                    if key:result.append((start,stop,grain,key,0,reason))
            stop+=timedelta(days=1)
        return result
