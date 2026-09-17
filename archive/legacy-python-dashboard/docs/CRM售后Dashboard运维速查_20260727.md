# CRM 售后 Dashboard 运维速查

生产目录：`/Users/Shared/ecom-profit/projects/crm`

## SSH 登录

```bash
ssh yyerybz@100.99.61.3
ssh yyerybz@192.168.3.135
```

## 查看服务状态

```bash
launchctl list | grep -E "com.ecom-profit.crm"
lsof -iTCP:8088 -sTCP:LISTEN -n -P
lsof -iTCP:8787 -sTCP:LISTEN -n -P
```

## 重启 CRM Web

```bash
launchctl kickstart -k gui/$(id -u)/com.ecom-profit.crm-dashboard
```

## 手动跑日更

```bash
cd /Users/Shared/ecom-profit/projects/crm
python3 scripts/run_crm_banniu_aftersales_daily.sh
```

如果 `python3 scripts/run_crm_banniu_aftersales_daily.sh` 报错，因为它是 shell 脚本，应改用：

```bash
bash scripts/run_crm_banniu_aftersales_daily.sh
```

## 分步手动跑

```bash
cd /Users/Shared/ecom-profit/projects/crm
python3 scripts/banniu_aftersales_sync.py --weeks 8 --page-size 100
python3 scripts/crm_warehouse_map_refresh.py
python3 scripts/crm_order_weekly_refresh.py --weeks 8
launchctl kickstart -k gui/$(id -u)/com.ecom-profit.crm-dashboard
```

## 查看日志

```bash
cd /Users/Shared/ecom-profit/projects/crm
 tail -100 logs/crm_banniu_aftersales_sync.out.log
 tail -100 logs/crm_banniu_aftersales_sync.err.log
 tail -100 logs/crm_dashboard.err.log
 tail -100 logs/crm_weekly_aftersales_service.out.log
```

## 验证页面

内网只读免登录：

```bash
curl -I http://127.0.0.1:8088/crm
curl -I http://127.0.0.1:8088/crm/dashboard
curl -I http://127.0.0.1:8088/crm/warehouse
curl -I http://127.0.0.1:8088/crm/products
```

验证只读不能导出：

```bash
curl -I "http://127.0.0.1:8088/crm/export?view=detail"
```

期望返回 `403`。

## 常用 SQL

```sql
USE ecom_profit;

SELECT COUNT(*) api_rows, MIN(wdt_pay_time) min_pay, MAX(wdt_pay_time) max_pay, MAX(api_synced_at) max_sync
FROM ods_banniu_aftersales
WHERE source_file_name = banniu_api;

SELECT COUNT(*) dws_rows, MIN(week_start) min_week_start, MAX(week_end) max_week_end
FROM dws_crm_order_weekly;

SELECT source_warehouse_code, warehouse_name_raw, match_count, confidence, source
FROM dim_crm_warehouse_map
WHERE is_active = 1
ORDER BY match_count DESC
LIMIT 50;
```

## 人工修正仓库映射

如果自动映射错了，可以手工修正，并把 `source` 设为 `manual`，这样日更不会覆盖：

```sql
UPDATE dim_crm_warehouse_map
SET warehouse_name_raw = 正确仓库名, source = manual, note = 人工确认
WHERE source_warehouse_code = 班牛仓库编码;
```

## 注意事项

- 不要把 `config/banniu_openapi.env` 内容发到聊天或文档。
- 修改 LaunchAgent 后要同步项目内 plist 和 `/Users/yyerybz/Library/LaunchAgents/` 中的 plist。
- 修改程序后以 Mac mini 生产路径验证为准，不以 MacAir 临时副本为准。
