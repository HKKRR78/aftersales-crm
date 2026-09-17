# CRM 售后 Dashboard 项目移交说明

更新时间：2026-07-27  
生产机器：Mac mini  
生产项目目录：`/Users/Shared/ecom-profit/projects/crm`

## 1. 项目目标

把售后经营异常看板从“每周上传 WPS/HTML 文件”升级为“班牛 API 日更入库 + CRM 网页读取 MySQL”。

当前使用方式：

- 内网只读免登录：`http://192.168.3.135:8088/crm`
- 外网/Tailscale 访问：`http://100.99.61.3:8088/crm`，需要账号密码
- 内网管理员强制登录：`http://192.168.3.135:8088/crm/login?force=1`

## 2. 权限规则

- 内网来源：自动识别为 `内网访客 / 只读访问`，不能导出、不能管理用户。
- 外网来源：必须登录。
- 登录角色：
  - `viewer`：只读访问
  - `exporter`：只读 + 导出
  - `admin`：只读 + 导出 + 用户管理

用户文件位置：

- `/Users/Shared/ecom-profit/projects/crm/runtime/crm_dashboard/users.json`
- 初始管理员密码文件：`/Users/Shared/ecom-profit/projects/crm/runtime/crm_dashboard/initial_admin_password.txt`

注意：不要把密码、班牛 AppSecret、AccessToken 写入文档、日志或聊天回复。

## 3. 当前页面路由

- `/crm`：首页 / 导航
- `/crm/dashboard`：日更售后 Dashboard
- `/crm/dashboard/detail`：售后明细
- `/crm/warehouse`：仓库问题视图
- `/crm/products`：商品问题视图
- `/crm/export?view=detail`：导出明细，仅 `exporter/admin` 可用
- `/crm/admin/users`：用户管理，仅 `admin` 可用

## 4. 核心数据链路

```text
班牛 OpenAPI
  -> scripts/banniu_aftersales_sync.py
  -> MySQL ods_banniu_aftersales
  -> scripts/crm_warehouse_map_refresh.py
  -> MySQL dim_crm_warehouse_map
  -> scripts/crm_order_weekly_refresh.py
  -> MySQL dws_crm_order_weekly
  -> crm_mysql_data.py
  -> crm_server.py 页面展示
```

当前 Dashboard 优先读取 MySQL。旧的 WPS/HTML 快照仍保留为兜底，不再作为主数据源。

## 5. 自动任务

LaunchAgent 文件在：

- 项目内：`/Users/Shared/ecom-profit/projects/crm/*.plist`
- 实际加载目录：`/Users/yyerybz/Library/LaunchAgents/*.plist`

主要任务：

- `com.ecom-profit.crm-dashboard`  
  CRM Web 服务，监听 `8088`。

- `com.ecom-profit.crm-banniu-aftersales-sync`  
  每天 `07:20` 执行日更：拉班牛 API、刷新仓库映射、刷新订单周汇总。

- `com.ecom-profit.crm-weekly-aftersales`  
  原 WPS 周报流程保留为兼容/兜底。

- `com.ecom-profit.crm-aftersales-publisher` / `com.ecom-profit.crm-aftersales-static-server`  
  原 HTML 周报发布/静态服务，保留为兜底。

## 6. 关键程序文件

- `crm_server.py`：轻量 CRM Web 服务、登录、路由、权限控制。
- `crm_mysql_data.py`：把 MySQL 聚合成页面需要的数据结构。
- `run_crm_dashboard.sh`：启动 8088 Web 服务。
- `scripts/banniu_openapi_client.py`：班牛 OpenAPI 基础客户端。
- `scripts/banniu_aftersales_sync.py`：班牛售后工单同步入库。
- `scripts/crm_warehouse_map_refresh.py`：班牛仓库编码到 WDT 仓库名的自动映射。
- `scripts/crm_order_weekly_refresh.py`：WDT 订单分母按周汇总。
- `scripts/run_crm_banniu_aftersales_daily.sh`：日更总入口。

## 7. 配置文件

- `config/banniu_openapi.env`：班牛 API 配置，权限 `600`，含敏感信息。
- `config/crm_aftersales.env`：旧 WPS/HTML 周报流程配置。
- `config/wps_aftersales.env`：指向 `crm_aftersales.env` 的兼容软链接。

## 8. 当前数据库状态快照

查询时间：2026-07-27

- `ods_banniu_aftersales` 中班牛 API 数据：`11296` 行
- 班牛付款时间覆盖：`2026-06-01 11:15:09` 到 `2026-07-26 13:10:35`
- 最近同步时间：`2026-07-27 07:22:41`
- `dws_crm_order_weekly`：`20964` 行
- 订单周汇总覆盖：`2026-05-30` 到 `2026-07-26`
- `dim_crm_warehouse_map` 有效映射：`50` 条

## 9. 周期口径

现在按“周日到周六”作为一周：

- 例如 `2026-07-19` 到 `2026-07-25` 算一周，页面显示 `0719-0725`。
- Dashboard 默认展示近 5 个完整周。
- 每天同步近 8 周班牛数据，目的是修正售后工单滞后创建/更新导致的历史周变化。

注意：今天产生的售后，如果付款时间属于当前未闭合周，会进入下一周周期；如果是历史付款时间的滞后售后，会回填到对应历史周。

## 10. 已知限制 / 下一步优化

1. 商品编码分母仍有部分为 0  
   典型原因是班牛商家编码含组合编码，WDT 订单表没有完全一致编码。当前已尝试 `+` 拆分，但仍可能无法匹配。后续可引入商品组合拆解映射表。

2. 仓库映射是自动推断  
   当前用订单号/运单号关联 WDT 出库明细，按最高匹配次数生成映射。高频仓库置信度很高，但低频仓库建议人工抽查。人工修正时把 `dim_crm_warehouse_map.source` 改成 `manual`，日更不会覆盖人工映射。

3. 班牛 API 按接口返回的总页数完整拉取，再用付款时间过滤近 8 周
   同步会以第一页最大任务 ID 固定本轮快照并校验任务总数；分页期间新增的任务留到下一轮，快照任务数不完整则失败。后续若接口正式支持更新时间筛选，可在保持完整性校验的前提下改成更新时间增量，降低 API 请求量。

4. 旧 WPS/HTML 任务仍保留  
   目前作为兜底。确认 API 版稳定一段时间后，可逐步下线旧任务和 8787 静态服务。
