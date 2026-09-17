# 脚本索引

本目录为 0.6.1 修复候选实现，尚未替换生产计划任务。先阅读[实施记录](../docs/operations/同版本修复实施记录_20260916.md)。

| 文件 | 职责 |
| --- | --- |
| `run_crm_aftersales_daily.sh` | 互斥执行完整新工单历史核对、候选报告构建、验证和原子发布；任一步失败均不选择新报告 |
| `crm_schema.py` | 初始化原始工单、统一售后事实及同步批次结构；不清理历史数据 |
| `crm_report_schema.py` | 初始化工单版本留痕、稳定读取证明、不可变报告及发布指针；不是生产验收命令 |
| `crm_ticket_sync.py` | 200 条/页、至少 7 秒间隔、固定历史终点、直到真实空页；分段复读一致后替换最新完整工单的有效子行集合 |
| `crm_sales_sources.py` | 从公司正式原订单库读取完整规格和原购买份数，按稳定销售行去重；WDT 仅补真实履约证据 |
| `crm_report_model.py` | 重建班牛最新完整子行、严格子订单归属、整周与同进度原销售事实统计 |
| `crm_report_audit.py` | 只读核查所有已保存的有效售后历史及其引用的原订单，输出记录级证据，不发布数据 |
| `crm_report_coverage.py` | 核查各店铺日期的采集证明；创建日覆盖不能冒充付款日覆盖。现有原件清单和订单生命周期证明的接入尚未完成 |
| `crm_report_build.py` | 在一致的只读数据库快照中读取源事实，另行写入隔离报告候选及审计文件，不切换正式报告 |
| `crm_report_publish.py` | 验证分类、数量、覆盖、来源和审计文件；选择报告时再次核验，并使用当前批次比较交换防止覆盖并发变更 |
| `crm_banniu_history_import.py` | 一次性历史导入工具，保留来源及原始载荷；不可因本次修复重复导入 |
| `crm_cutover_reconcile.py` | 新旧来源交接核对 |
| `crm_classification_reconcile.py` | 只读分类及剔除规则对账 |
| `crm_exclusion_rules_refresh.py` | 已确认剔除规则初始化，保留人工启停状态 |
| `prepare-standalone.mjs` | 构建 standalone 静态资源，由 `pnpm build` 调用 |

旧的日/周分母刷新、WDT 补码及低置信度仓库映射脚本已从候选路径删除，没有运行时兼容回退。原版本保存在工作区备份中用于审计。

只读对账示例（原订单查询不设付款时间下界）：

```bash
python3 scripts/crm_report_audit.py --end 2026-09-16 --output evidence/native-audit.json.gz
```

`--end` 为售后创建时间的排他终点。数据库信息通过环境注入；接口令牌只能由 Secret 注入，不写入源码或日志。完整任务还要求 `TICKET_HISTORY_START_DATE=2026-09-15`。`--dry-run` 不建表、不更新事实；报告构建和发布为写操作，需在真实数据门槛通过后按运维记录执行。
