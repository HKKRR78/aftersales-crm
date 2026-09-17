"""Read native sales rows. Never sum ERP component quantities as sales packs.

    SELECTs deliberately name business fields only (no buyer/contact columns).
    Source row identifiers and hashes are retained for replay and audit.
"""
from __future__ import annotations

from collections import defaultdict
from decimal import Decimal
from datetime import timedelta
import hashlib
import json

import pymysql

from crm_report_model import identity, link_key, text
from crm_native_shipping import doudian_original_shipping,valid_ship_time,wechat_product_shipped

PLATFORMS = {'pdd':'pinduoduo', 'weixin':'wechat_shop', 'wechat':'wechat_shop',
             'xhs':'xiaohongshu', 'redbook':'xiaohongshu', 'doudian':'douyin',
             'dfzx':'dongfangzhenxuan', 'eastbuy':'dongfangzhenxuan'}
PREFIXES = {'抖音':'douyin','天猫':'tmall','淘宝':'taobao','拼多多':'pinduoduo',
            '快手':'kuaishou','京东':'jd','微信小店':'wechat_shop','微信':'wechat_shop',
            '视频号':'wechat_shop','小红书':'xiaohongshu','东方甄选':'dongfangzhenxuan','淘工厂':'tgc'}


def platform_code(value):
    value = text(value)
    return PLATFORMS.get(value, PREFIXES.get(value, value))


def query(conn, sql, params=()):
    with conn.cursor(pymysql.cursors.DictCursor) as cur:
        cur.execute(sql, params)
        return list(cur.fetchall())


class Shops:
    def __init__(self, conn):
        self.rows = query(conn, 'SELECT * FROM dim_shop')
        self.by_key = {}
        self.by_name = defaultdict(set)
        self.by_id = defaultdict(set)
        self.by_sk = {}
        for row in self.rows:
            key = (platform_code(row['platform_code']), text(row['platform_shop_id']))
            self.by_key[key] = row
            self.by_sk[row['shop_sk']] = key
            self.by_id[key].add(key)
            # The official shop master also stores the ERP/source shop ID
            # (e.g. p-56 -> the verified WeChat appid). It is an identity map,
            # not a name-based guess or SKU equivalence.
            if row.get('wdt_shop_id'):
                self.by_id[key[0],text(row['wdt_shop_id'])].add(key)
            self.add_name(key, row['shop_name_current'])
        for row in query(conn, 'SELECT * FROM dim_shop_alias'):
            key = self.by_sk.get(row['shop_sk'])
            if key:
                self.add_name(key, row['source_shop_name'])
                if row['source_shop_id']:
                    self.by_id[key[0],text(row['source_shop_id'])].add(key)

    def add_name(self, key, name):
        name = text(name)
        self.by_name[key[0],name].add(key)
        prefix, separator, bare = name.partition('-')
        if separator and PREFIXES.get(prefix) == key[0]:
            self.by_name[key[0],bare].add(key)

    def resolve(self, platform, shop_id, shop_name):
        platform = platform_code(platform)
        if platform in ('other','其他'):
            platform = ''
        name = text(shop_name)
        prefix, separator, bare = name.partition('-')
        inferred = PREFIXES.get(prefix) if separator else None
        if platform and inferred and platform != inferred:
            return None
        platform = platform or inferred or ''
        if inferred:
            name = bare
        ids = self.by_id.get((platform,text(shop_id)), set()) if shop_id else set()
        names = self.by_name.get((platform,name), set()) if platform else set().union(
            *(v for (p,n),v in self.by_name.items() if n==name))
        if ids and names and ids != names:
            return None
        candidates = ids or names
        return next(iter(candidates)) if len(candidates)==1 else None


# SQL expressions are static; all dates/shop identifiers remain parameters.
# Views that conceal indexed dates are avoided where their materialized source
# has the same authoritative business-key/version selection.
SOURCES = {
 'douyin': dict(table='dwd_doudian_order_item_detail', date='paid_date', shop='shop_id',
   select="""shop_id,shop_name,main_order_id order_no,sub_order_id sub_no,
     order_item_key source_key,product_id,sku_code code,quantity,paid_at,
     order_status status,NULL ship_time,source_loaded_at version_at,
     source_file source_file,content_hash source_hash,file_sha1 source_file_hash,
     product_name native_product_title,sku_name native_sku_attr,
     NULL native_logistics_no,NULL native_refund_amount"""),
 'kuaishou': dict(table='dwd_kuaishou_order_detail', date='order_paid_at', shop='shop_id',
   select="""shop_id,shop_name,platform_order_id order_no,platform_order_id sub_no,
     merge_key_hash source_key,product_id,sku_code code,quantity,order_paid_at paid_at,
     order_status status,JSON_UNQUOTE(JSON_EXTRACT(row_json,'$."发货时间"')) ship_time,source_version_at_resolved version_at,
     source_file,row_hash source_hash,product_name native_product_title,sku_desc native_sku_attr,
     NULL native_logistics_no,NULL native_refund_amount"""),
 'pinduoduo': dict(table='vw_pdd_order_ready', date='paid_at', shop='mall_id',
   select="""shop_id,shop_name,`订单号` order_no,`订单号` sub_no,
     HEX(business_key_v2) source_key,`商品id` product_id,`商家编码-规格维度` code,
     `商品数量(件)` quantity,paid_at,`订单状态` status,`发货时间` ship_time,
     source_version_at version_at,'' source_file,HEX(content_hash_v2) source_hash,`样式ID` native_sku_id,
     `商品` native_product_title,`商品规格` native_sku_attr,`快递单号` native_logistics_no,
     NULL native_refund_amount"""),
 'jd': dict(table='vw_jd_order_item', date='paid_at', shop='shop_id',
   select="""shop_id,shop_name,main_order_id order_no,main_order_id sub_no,
     CONCAT(main_order_id,':',product_id) source_key,product_id,
     JSON_UNQUOTE(JSON_EXTRACT(raw_row_json,'$."商家SKUID"')) code,
     qty quantity,paid_at,order_status status,ship_time,updated_at version_at,
     batch_id source_file,row_hash source_hash,product_id native_sku_id,
     product_name native_product_title,NULL native_sku_attr,NULL native_logistics_no,NULL native_refund_amount"""),
 'tmall': dict(table='ods_tmall_sales_detail', date='paid_at', shop='shop_id', extra="AND platform_code='tmall'",
   select="""shop_id,shop_name,main_order_id order_no,sub_order_id sub_no,
     sub_order_id source_key,product_id,
     COALESCE(NULLIF(JSON_UNQUOTE(JSON_EXTRACT(raw_row_json,'$."商家编码"')),''),
              NULLIF(JSON_UNQUOTE(JSON_EXTRACT(raw_row_json,'$."外部系统编号"')),'')) code,
     buy_qty quantity,paid_at,order_status status,ship_time,source_version_at version_at,
     source_file_sha256 source_file,content_hash source_hash,product_title native_product_title,
     JSON_UNQUOTE(JSON_EXTRACT(raw_row_json,'$."商品属性"')) native_sku_attr,
     logistics_no native_logistics_no,refund_amount native_refund_amount,
     JSON_UNQUOTE(JSON_EXTRACT(raw_row_json,'$."联系方式备注"')) native_contact_note"""),
 'taobao': dict(table='ods_tmall_sales_detail', date='paid_at', shop='shop_id', extra="AND platform_code='taobao'",
   select="""shop_id,shop_name,main_order_id order_no,sub_order_id sub_no,
     sub_order_id source_key,product_id,
     COALESCE(NULLIF(JSON_UNQUOTE(JSON_EXTRACT(raw_row_json,'$."商家编码"')),''),
              NULLIF(JSON_UNQUOTE(JSON_EXTRACT(raw_row_json,'$."外部系统编号"')),'')) code,
     buy_qty quantity,paid_at,order_status status,ship_time,source_version_at version_at,
     source_file_sha256 source_file,content_hash source_hash,product_title native_product_title,
     JSON_UNQUOTE(JSON_EXTRACT(raw_row_json,'$."商品属性"')) native_sku_attr,
     logistics_no native_logistics_no,refund_amount native_refund_amount,
     JSON_UNQUOTE(JSON_EXTRACT(raw_row_json,'$."联系方式备注"')) native_contact_note"""),
 'wechat_shop': dict(table='vw_wechat_shop_order_standard', date='pay_time', shop='shop_appid',
   select="""shop_id,shop_name,order_id order_no,order_id sub_no,line_key source_key,
     product_id,sku_code code,sku_cnt quantity,pay_time paid_at,order_status status,
     NULL ship_time,update_time version_at,source_file,'' source_hash,sku_id native_sku_id,
     JSON_EXTRACT(raw_order_json,'$.order_detail.delivery_info.delivery_product_info') native_shipments,
     title native_product_title,NULL native_sku_attr,NULL native_logistics_no,NULL native_refund_amount"""),
 'dongfangzhenxuan': dict(table='vw_dongfangzhenxuan_order_item',date='pay_time',shop='shop_id',
   select="""shop_id,shop_name,main_order_no order_no,sub_order_no sub_no,
     sub_order_no source_key,sku_product_code product_id,merchant_code code,quantity,
     pay_time paid_at,sub_order_status status,ship_time,updated_at version_at,
     '' source_file,'' source_hash"""),
 'tgc': dict(table='ods_tgc_order_detail',date='order_paid_time',shop='supplier_id',
   select="""supplier_id shop_id,NULL shop_name,main_order_no order_no,sub_order_no sub_no,
     shop_id native_shop_id,supplier_id native_supplier_id,
     CONCAT(sub_order_no,':',shop_id) source_key,item_code product_id,merchant_sku_code code,
     item_quantity quantity,paid_at,order_status status,confirmed_receipt_time ship_time,
     source_version_at version_at,'' source_file,record_content_hash source_hash"""),
 'xiaohongshu': dict(table='ods_xhs_order_item i JOIN vw_xhs_order_package p ON p.package_id=i.package_id',
   date='p.paid_at',shop='p.shop_id',
   select="""p.shop_id,p.shop_name,p.package_id order_no,p.package_id sub_no,
     JSON_UNQUOTE(JSON_EXTRACT(p.raw_json,'$.orderId')) native_order_no,
     CONCAT(i.package_id,':',i.sku_id) source_key,i.sku_id product_id,
     CASE WHEN JSON_LENGTH(i.raw_json,'$.scskus')=1 THEN
       JSON_UNQUOTE(JSON_EXTRACT(i.raw_json,'$.scskus[0].scskuCode')) ELSE NULL END code,
     i.quantity,p.paid_at,p.status_desc status,NULL ship_time,p.source_updated_at version_at,
     i.source_file,'' source_hash,JSON_EXTRACT(i.raw_json,'$.shipped') shipped_flag,
     i.sku_id native_sku_id,i.raw_json sales_item_json,i.display_name native_product_title,
     i.sku_specification native_sku_attr,NULL native_logistics_no,NULL native_refund_amount,
     JSON_UNQUOTE(JSON_EXTRACT(p.raw_json,'$.originalPackageId')) original_package_id"""),
}


SHIPPED_STATUSES = {'已发货','已收货','已完成','交易成功','交易完成','卖家已发货','买家已签收','等待买家确认收货','待买家收货'}
UNSHIPPED_STATUSES = {'待付款','等待买家付款','待发货','等待卖家发货','待卖家发货','未付款','待支付','未发货，退款成功'}


def native_shipped(row, platform):
    if valid_ship_time(row.get('ship_time')):
        return True
    if platform == 'xiaohongshu':
        return str(row.get('shipped_flag')).lower() in ('true','1')
    if platform == 'wechat_shop':
        # An order-level completed state cannot prove every SKU shipped: one
        # line can be refunded before shipping while another line completes.
        return wechat_product_shipped(row)
    return text(row.get('status')) in SHIPPED_STATUSES


def read_sales(conn, shops, start, end, *, selected_platforms=None):
    """Read each payment day once per platform using its native stable shop IDs.

    Per-shop reads on a date-only index scanned the same platform repeatedly.
    Daily partitions bound query time without narrowing the historical scope.
    """
    for platform,spec in SOURCES.items():
        if selected_platforms and platform not in selected_platforms:continue
        shop_ids=sorted({key[1] for key in shops.by_key if key[0]==platform})
        if platform=='xiaohongshu':
            for shop_id in shop_ids:
                for sale in read_xhs_sales(conn,shops,shop_id):
                    if sale['paid_at'] and start<=sale['paid_at'].date()<end:yield sale
            continue
        if not shop_ids:continue
        native_rows=[]
        day=start
        while day<end:
            stop=min(day+timedelta(days=1),end)
            sql=f"SELECT {spec['select']} FROM {spec['table']} WHERE {spec['shop']} IN ({','.join(['%s']*len(shop_ids))}) AND {spec['date']} >= %s AND {spec['date']} < %s {spec.get('extra','')}"
            try:rows=query(conn,sql,(*shop_ids,day,stop))
            except Exception as exc:
                raise RuntimeError(f'native sales read failed: {platform} {day}..{stop}') from exc
            if platform in ('douyin','wechat_shop'):native_rows.extend(rows)
            else:
                for row in rows:yield normalize_sale(row,platform,spec,shops)
            day=stop
        if platform in ('douyin','wechat_shop'):
            # Restore each retained source file once for this report period.
            # Native SQL stays partitioned by day; every row keeps its own
            # original version/identity checks before shipment evidence joins.
            if platform=='douyin':
                doudian_original_shipping(native_rows,lambda row:native_shipped(row,platform))
            else:
                from crm_wechat_shipping import restore_shipments
                restore_shipments(conn,native_rows)
            for row in native_rows:yield normalize_sale(row,platform,spec,shops)


def normalize_sale(row, platform, spec, shops):
    scope=shops.resolve(platform,row['shop_id'],row['shop_name'])
    if scope is None:
        raise ValueError(f'unknown/conflicting native shop identity: {platform}')
    lookup_scope=scope
    if platform=='tgc':
        # Supplier account chooses which company export to read. The original
        # storefront identifies the sale/order; one storefront can contain
        # several of our suppliers. Never count the same order per supplier.
        native_shop=text(row.get('native_shop_id'))
        if not native_shop:raise ValueError('original TGC storefront identity missing')
        scope=(platform,native_shop)
    code=text(row.get('code'))
    if code.lower()=='null':code=''
    if row.get('quantity') is None or text(row.get('quantity')) == '':
        raise ValueError(f'missing original sales quantity: {platform}')
    quantity=Decimal(str(row['quantity']))
    if quantity<0 or not quantity.is_finite():
        raise ValueError('invalid original sales quantity')
    order_no=text(row['order_no']);sub=text(row['sub_no'])
    if not order_no or not row.get('source_key'):
        raise ValueError('native order identity missing')
    # Native child/order identity survives changes in an importer's hash
    # algorithm. The opaque source row key remains only an audit locator.
    if platform in ('douyin','tmall','taobao','tgc','dongfangzhenxuan'):
        if not sub:raise ValueError('native sales child identity missing')
        line=identity(platform,scope[1],sub)
    elif platform=='kuaishou':
        line=identity(platform,scope[1],order_no)
    elif platform=='wechat_shop':
        product=text(row.get('product_id'));sku=text(row.get('native_sku_id'))
        if not product or not sku:raise ValueError('native WeChat product/SKU identity missing')
        line=identity(platform,scope[1],order_no,product,sku)
    else:
        line=identity(platform,scope[1],row['source_key'])
    native_order=text(row.get('native_order_no')) if platform=='xiaohongshu' else order_no
    # XHS orderId differs from packageId. Only the full-shop purchase-segment
    # reconciliation may certify its original order/SKU line identity.
    sales_identity_known=platform!='xiaohongshu' or row.get('sales_identity_verified',False)
    if platform=='xiaohongshu' and sales_identity_known:
        line=identity(platform,scope[1],native_order,text(row['native_sku_id']))
    product=text(row.get('product_id'))
    return dict(line_key=line,order_key=identity(platform,scope[1],native_order) if native_order else '',
               sales_identity_known=sales_identity_known,
               platform=platform,shop_key=scope[1],lookup_shop_key=lookup_scope[1],order_no=order_no,sub_keys={sub} if sub else set(),
               independent_suborder=bool(sub) and platform in ('douyin','tmall','taobao','tgc','dongfangzhenxuan'),
               code=code,product_id=product,quantity=quantity,paid_at=row['paid_at'],
               native_sku_id=text(row.get('native_sku_id')),
               native_product_title=text(row.get('native_product_title')),
               native_sku_attr=text(row.get('native_sku_attr')),
               native_logistics_no=text(row.get('native_logistics_no')),
               native_refund_amount=row.get('native_refund_amount'),
               native_contact_note=text(row.get('native_contact_note')),
               shipped=native_shipped(row,platform),
               shipping_known=native_shipped(row,platform) or text(row.get('status')) in UNSHIPPED_STATUSES
                 or (platform=='wechat_shop' and text(row.get('status')) in ('10','20')),
               warehouse='',
               link_key=link_key(platform,scope[1],product,code),
               evidence=dict(table=spec['table'],row_key=text(row['source_key']),
                             file=text(row.get('source_file')),hash=text(row.get('source_hash')),
                             version=str(row.get('version_at') or ''),status=text(row.get('status')),
                             native_ship_time=text(row.get('ship_time')),
                             native_shipping_proof=row.get('native_shipping_proof'),
                             shipping_source_reason=row.get('shipping_source_reason'),
                             native_shipment_hash=identity(row['native_shipments']) if row.get('native_shipments') else None,
                             native_order_no=native_order,
                             native_shop_id=scope[1],native_supplier_id=text(row.get('native_supplier_id')),
                             original_line_proof=row.get('original_line_proof'),
                             sales_identity_reason='native_sales_line' if sales_identity_known else 'package_to_sales_line_unverified'))


def verify_xhs_sales_rows(rows):
    """Reconcile original order/SKU against all current packages for one shop.

    The preserved API item contains purchase skuQuantity plus scskus purchase
    segments (including separately priced purchases of the same SKU). Require
    their quantity sum and SKU/code to agree and a one-to-one order/SKU/package
    relation. A repeated SKU across packages needs further source evidence;
    neither adding nor discarding those package quantities is safe.
    """
    packages=defaultdict(set)
    for row in rows:
        packages[text(row.get('native_order_no')),text(row.get('native_sku_id'))].add(text(row['order_no']))
    for row in rows:
        raw=json.loads(row['sales_item_json']) if isinstance(row['sales_item_json'],str) else row['sales_item_json']
        segments=raw.get('scskus') or []
        native=text(row.get('native_order_no'));sku=text(row.get('native_sku_id'))
        codes={text(part.get('scskuCode')) for part in segments}
        same_sku=bool(segments) and all(text(part.get('skuId'))==sku and part.get('quantity') is not None for part in segments)
        qty=sum((Decimal(str(part['quantity'])) for part in segments),Decimal(0)) if same_sku else None
        verified=bool(native and sku and len(packages[native,sku])==1 and same_sku
                      and len(codes)==1 and '' not in codes and qty==Decimal(str(row['quantity']))
                      and qty==Decimal(str(raw.get('skuQuantity')))
                      and not raw.get('compositeFlag') and not raw.get('childSkus')
                      and text(row.get('original_package_id')) in ('','null'))
        row['sales_identity_verified']=verified
        if verified:
            row['code']=next(iter(codes))
            row['original_line_proof']=dict(native_order_no=native,native_sku_id=sku,
                package_id=text(row['order_no']),observed_packages=1,purchase_segments=len(segments),
                source_quantity=str(qty),item_hash=identity(raw))
    return rows


def read_xhs_sales(conn,shops,shop_id):
    spec=SOURCES['xiaohongshu']
    # Deliberately inspect every package for the shop before applying a payment
    # window, so a duplicate package outside that window cannot evade the check.
    rows=query(conn,f"SELECT {spec['select']} FROM {spec['table']} WHERE p.shop_id=%s",(shop_id,))
    for row in verify_xhs_sales_rows(rows):yield normalize_sale(row,'xiaohongshu',spec,shops)


def shipping_evidence(conn, shops, start, end):
    """Verified fulfillment proves shipping, not sales pack quantities/codes."""
    result=defaultdict(list)
    day=start
    while day<end:
        stop=min(day+timedelta(days=1),end)
        for row in read_fulfillment_day(conn,day,stop):
            shop=shops.resolve(row['platform_code'],row['platform_shop_id'],row['shop_name_observed'])
            if shop:
                native_order=text(row.get('native_order_no'))
                order=native_order if native_order and native_order!='null' else text(row['platform_order_no'])
                result[(*shop,order)].append(row)
        day=stop
    return result


def read_fulfillment_day(conn,start,end):
    """Keyset pagination over the existing payment index and primary key.

    Fetch large raw JSON by primary key separately. A joined whole-day query
    exceeded the source query budget on real high-volume days. The ordered
    cursor includes the unique business key, so equal payment times cannot
    skip or duplicate rows. Callers retain one consistent source transaction.
    """
    cursor=None
    while True:
        predicate=''
        params=[start,end]
        if cursor:
            predicate='AND (pay_time>%s OR (pay_time=%s AND business_key>%s))'
            params.extend([cursor[0],cursor[0],cursor[1]])
        rows=query(conn,f"""SELECT platform_code,platform_shop_id,shop_name_observed,
          platform_order_no,source_sub_order_no,warehouse_no,warehouse_name,merchant_code,
          business_key,pay_time,source_code,source_row_count,source_row_id,qty,stockout_no,logistics_no
          FROM vw_wdt_fulfillment_verified_current WHERE pay_time >= %s AND pay_time < %s
          {predicate} ORDER BY pay_time,business_key LIMIT 2000""",params)
        if not rows:return
        ids=sorted({r['source_row_id'] for r in rows if r['source_code']=='wdt_stockout_api'
                    and r['source_row_count']==1 and r['source_row_id'] is not None})
        raw={}
        if ids:
            raw={r['id']:r for r in query(conn,f"""SELECT id,
              JSON_UNQUOTE(JSON_EXTRACT(raw_detail_json,'$.src_tid')) native_order_no,
              JSON_UNQUOTE(JSON_EXTRACT(raw_detail_json,'$.api_spec_id')) native_sku_id,
              JSON_UNQUOTE(JSON_EXTRACT(raw_detail_json,'$.api_goods_id')) native_product_id,
              JSON_UNQUOTE(JSON_EXTRACT(raw_order_json,'$.trade_type')) native_trade_type,
              JSON_UNQUOTE(JSON_EXTRACT(raw_order_json,'$.order_type')) native_stockout_type,
              JSON_UNQUOTE(JSON_EXTRACT(raw_detail_json,'$.suite_no')) original_suite_code,
              JSON_UNQUOTE(JSON_EXTRACT(raw_detail_json,'$.suite_num')) original_suite_quantity
              FROM ods_wdt_stock_out_api_line WHERE id IN ({','.join(['%s']*len(ids))})""",ids)}
        for row in rows:
            if row['source_code']=='wdt_stockout_api' and row['source_row_count']==1:
                row.update({k:v for k,v in raw.get(row['source_row_id'],{}).items() if k!='id'})
            yield row
        cursor=(rows[-1]['pay_time'],rows[-1]['business_key'])


def attach_shipping(sale, evidence):
    candidates=evidence.get((sale['platform'],sale['lookup_shop_key'],sale['order_no']),[])
    matches=[r for r in candidates if
             (text(r['source_sub_order_no']) in sale['sub_keys']
              and (sale.get('independent_suborder') or (sale['code'] and text(r.get('merchant_code'))==sale['code'])))
             or exact_native_ids(sale,r)]
    if matches:
        sale['evidence']['fulfillment_keys']=sorted({r['business_key'] for r in matches})
        # A component or a replacement shipment proves neither the complete
        # original sales line nor ownership of its full quantity by a warehouse.
        # Compare only exact original-spec units, never multiply/sum bundle
        # members into a guessed pack quantity.
        direct={r['business_key']:r for r in matches if sale['code'] and text(r.get('merchant_code'))==sale['code']
                and text(r.get('native_trade_type'))=='1' and text(r.get('native_stockout_type'))=='1'
                and r.get('qty') is not None and r.get('stockout_no') and r.get('logistics_no')}
        complete=bool(direct) and sum(Decimal(str(r['qty'])) for r in direct.values())==sale['quantity']>0
        sale['evidence']['fulfillment_complete_original_spec']=complete
        if complete:
            sale['shipped']=True
            sale['shipping_known']=True
            warehouses={text(r.get('warehouse_no')) for r in direct.values()}
            if len(warehouses)==1 and '' not in warehouses:sale['warehouse']=next(iter(warehouses))
    return sale


def exact_native_ids(sale, row):
    return bool(sale.get('native_sku_id') and sale.get('product_id')
                and text(row.get('native_sku_id'))==sale['native_sku_id']
                and (sale['platform']=='jd' or text(row.get('native_product_id'))==sale['product_id'])
                and text(row.get('native_order_no'))==sale['order_no'])


def bridge_source_suborders(conn,shops,facts,orders):
    """Map ERP suborder IDs to native lines using preserved platform IDs.

    WDT raw src_tid / src_oid / api_goods_id / api_spec_id are explicit links.
    Never strip an _001 suffix, select an ordinal, or substitute a base SKU.
    """
    waybills=sorted({text(f.get('logistics_no')) for f in facts if f.get('_shop')
                    and f.get('sub_order_no') and f.get('logistics_no')
                    and any(s.get('native_sku_id') for s in orders.get((*f['_shop'],text(f['order_no'])),{}).values())})
    if not waybills:return
    routes={text(r['wdt_platform_id']):platform_code(r['canonical_platform_code'])
            for r in query(conn,'SELECT wdt_platform_id,canonical_platform_code FROM control_wdt_platform_route')}
    for offset in range(0,len(waybills),200):
        chunk=waybills[offset:offset+200]
        rows=query(conn,f"""SELECT id,platform_id,shop_no,shop_name,origin_sub_order_no,logistics_no,
            JSON_UNQUOTE(JSON_EXTRACT(raw_detail_json,'$.src_tid')) native_order_no,
            JSON_UNQUOTE(JSON_EXTRACT(raw_detail_json,'$.src_oid')) source_sub_order_no,
            JSON_UNQUOTE(JSON_EXTRACT(raw_detail_json,'$.api_spec_id')) native_sku_id,
            JSON_UNQUOTE(JSON_EXTRACT(raw_detail_json,'$.api_goods_id')) native_product_id
            FROM ods_wdt_stock_out_api_line WHERE logistics_no IN ({','.join(['%s']*len(chunk))})""",chunk)
        for row in rows:
            shop=shops.resolve(routes.get(text(row['platform_id']),''),row['shop_no'],row['shop_name'])
            if not shop or not text(row['source_sub_order_no']):continue
            candidates=[s for s in orders.get((*shop,text(row['native_order_no'])),{}).values() if exact_native_ids(s,row)]
            if len(candidates)!=1:continue
            sale=candidates[0];sub=text(row['source_sub_order_no'])
            sale['sub_keys'].add(sub)
            proof={k:row[k] for k in ('id','native_order_no','source_sub_order_no','native_sku_id','native_product_id')}
            proof['table']='ods_wdt_stock_out_api_line'
            sale['evidence'].setdefault('suborder_bridges',[]).append(proof)


def bridge_ticket_product_keys(facts,orders):
    """The new PDD source explicitly identifies an item as order:goodsId.

    This exact composite key is not the platform's bare order number. Preserve
    it and prove both fields against one native sales row; never strip suffixes
    or choose one of several SKU candidates for the same product.
    """
    for fact in facts:
        shop=fact.get('_shop')
        if fact.get('source_system')!='ticket_service' or not shop or shop[0]!='pinduoduo':continue
        order=text(fact.get('order_no'));product=text(fact.get('aftersales_product_id'))
        sub=text(fact.get('sub_order_no'))
        if not order or not product or sub!=order+':'+product:continue
        candidates=[sale for sale in orders.get((*shop,order),{}).values() if sale['product_id']==product]
        if len(candidates)!=1:continue
        sale=candidates[0];sale['sub_keys'].add(sub)
        sale['evidence'].setdefault('ticket_product_keys',[]).append(
            dict(source_ticket_id=str(fact['source_ticket_id']),source_item_id=str(fact['source_item_id']),
                 source_sub_order_no=sub,order_no=order,product_id=product,native_line_key=sale['line_key']))


ORDER_COLUMNS = {
 'douyin':'main_order_id','kuaishou':'platform_order_id','pinduoduo':'`订单号`',
 'jd':'main_order_id','tmall':'main_order_id','taobao':'main_order_id',
 'wechat_shop':'order_id','dongfangzhenxuan':'main_order_no','xiaohongshu':'p.package_id','tgc':'main_order_no',
}

def read_orders(conn, shops, platform, shop_id, orders):
    """Enumerate native order lines without a payment-time cutoff."""
    if platform=='xiaohongshu':
        wanted=set(orders)
        for sale in read_xhs_sales(conn,shops,shop_id):
            if sale['order_no'] in wanted:yield sale
        return
    spec=SOURCES[platform]
    for offset in range(0,len(orders),200):
        chunk=orders[offset:offset+200]
        column=ORDER_COLUMNS[platform]
        if platform=='douyin':
            column='main_order_key'
            chunk=[hashlib.sha256(f'{shop_id}|{order}'.encode()).hexdigest() for order in chunk]
        rows=query(conn, f"SELECT {spec['select']} FROM {spec['table']} WHERE {spec['shop']}=%s AND {column} IN ({','.join(['%s']*len(chunk))}) {spec.get('extra','')}", [shop_id,*chunk])
        seen={}
        for row in rows:
            sale=normalize_sale(row,platform,spec,shops)
            old=seen.get(sale['line_key'])
            if old is not None:
                raise ValueError(f'duplicate current native order line: {platform}')
            seen[sale['line_key']]=sale
            yield sale


def match_native_orders(conn, shops, facts, progress=None):
    """Recover historical shop names only through exact native order evidence.

    Display names never establish SKU equivalence. For an unknown shop, read
    the exact order in every registered shop on the source platform; require
    one stable shop with the exact supplied suborder (when present).
    """
    targets=defaultdict(set)
    unknown=[]
    for fact in facts:
        shop=shops.resolve(fact['platform'],fact['shop_id'],fact['shop_name'])
        fact['_shop']=shop
        if not fact['order_no']:
            continue
        if shop:
            targets[shop].add(text(fact['order_no']))
        else:
            platform=platform_code(fact['platform'])
            prefix,separator,_=text(fact['shop_name']).partition('-')
            if not platform or platform in ('other','其他'):
                platform=PREFIXES.get(prefix,'') if separator else ''
            if platform not in SOURCES:
                continue
            unknown.append((fact,platform))
            for candidate in shops.by_key:
                if candidate[0]==platform:
                    targets[candidate].add(text(fact['order_no']))
    orders=defaultdict(dict)
    for (platform,shop),requested in sorted(targets.items()):
        if platform not in SOURCES:
            raise ValueError(f'native source not configured: {platform}/{shop}')
        for sale in read_orders(conn,shops,platform,shop,sorted(requested)):
            orders[platform,shop,sale['order_no']][sale['line_key']]=sale
        if progress:
            progress(platform,shop,len(requested))
    for fact,platform in unknown:
        sub=text(fact['sub_order_no']);order_no=text(fact['order_no'])
        matches=[]
        for candidate in shops.by_key:
            if candidate[0]!=platform:
                continue
            rows=orders.get((*candidate,order_no),{}).values()
            if any(not sub or sub in row['sub_keys'] for row in rows):
                matches.append(candidate)
        if len(matches)==1:
            fact['_shop']=matches[0]
            fact['_shop_evidence']='unique_native_order_and_suborder' if sub else 'unique_native_order_shop'
    stable_ids=defaultdict(set)
    for fact in facts:
        if fact.get('_shop') and fact.get('shop_id'):
            stable_ids[fact['source_system'],text(fact['shop_id'])].add(fact['_shop'])
    for fact in facts:
        if fact.get('_shop') or not fact.get('shop_id'):
            continue
        matches=stable_ids.get((fact['source_system'],text(fact['shop_id'])),set())
        if len(matches)==1:
            fact['_shop']=next(iter(matches))
            fact['_shop_evidence']='source_stable_shop_id_verified_by_native_orders'
    bridge_source_suborders(conn,shops,facts,orders)
    bridge_ticket_product_keys(facts,orders)
    from crm_original_order_proof import apply_original_order_proofs
    apply_original_order_proofs(conn,orders)
    from crm_pdd_original_proof import apply_original_file_proofs
    apply_original_file_proofs(conn,orders)
    return orders
