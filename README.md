# 售后经营看板

榆园内部售后经营分析系统，使用 Next.js 16、React 19 和 TypeScript。

**本目录当前是 2026-09-16 的修复候选源码，版本保持 0.6.1，尚未发布。** 实际进度、真实数据证据和阻塞项见[同版本修复实施记录](docs/operations/同版本修复实施记录_20260916.md)。下述数据链路描述候选实现；历史发布文档不能作为本次验收证明。

当前工程只维护两条生产链路：

1. Next.js 售后看板与 Excel 导出。
2. 新工单完整历史核对、原销售规格匹配、真实销售事实汇总及报告批次发布。

历史代码保存在 [`archive/legacy-python-dashboard`](archive/legacy-python-dashboard/README.md)，不参与候选构建、测试或部署。服务器上另有旧 Python 进程，尚未在本轮操作中停用；不可将归档状态误认为进程已退出。

## 从这里开始

| 需要了解的内容 | 文档入口 |
| --- | --- |
| 全部文档导航 | [docs/README.md](docs/README.md) |
| 版本变更记录 | [CHANGELOG.md](CHANGELOG.md) |
| 现有业务和用户工作流 | [现有业务梳理](docs/product/售后CRM现有业务梳理_20260818.md) |
| 改版结论、实施记录和验收标准 | [改版复盘与修正计划](docs/product/售后看板改版复盘与修正计划_20260825.md) |
| 系统边界、模块和数据流 | [新版面板重构说明](docs/architecture/新版售后面板重构说明_20260825.md) |
| 缓存、分页和 MySQL 策略 | [数据策略](docs/architecture/售后看板数据策略_20260825.md) |
| 视觉与响应式规范 | [视觉系统](docs/design/视觉系统.md) |
| 生产服务、健康检查和回滚 | [运维入口](docs/operations/README.md) |
| 数据脚本职责 | [scripts/README.md](scripts/README.md) |
| 部署配置职责 | [deploy/README.md](deploy/README.md) |

## 工程结构

```text
售后CRM/
├── app/                         Next.js 路由、页面和 Route Handlers
├── src/
│   ├── auth/                    公司员工身份读取
│   ├── components/              业务 UI 与虚拟表格
│   ├── db/                      MySQL 连接
│   └── modules/                 分析口径、查询、筛选与 Excel
├── public/brand/                榆园品牌资源与本地字体
├── scripts/                     生产数据任务和构建辅助脚本
├── tests/                       Next.js 业务测试与数据同步测试
├── deploy/launchd/              现役服务和数据任务配置
├── docs/                        产品、架构、设计和运维文档
└── archive/legacy-python-dashboard/
                                 已退出主链路的历史实现
```

根目录只保留框架规定的入口文件、依赖清单和工程级说明。页面路由继续位于根目录 `app/`，通用业务代码集中在 `src/`；这是当前 Next.js 支持的标准结构，不再进行无收益的目录迁移。

## 本地开发

要求 Node.js 24 及 pnpm 10。

```bash
pnpm install
pnpm dev
```

开发服务监听 `127.0.0.1:18091`。没有本地 MySQL 时，可使用仅在开发环境生效的验收数据：

```bash
AFTERSALES_DEV_DATA=fixture pnpm dev
```

生产环境不会读取该开关，也不能通过它绕过员工身份校验。

## 质量检查

提交或发布前统一执行：

```bash
pnpm verify
```

该命令依次执行 TypeScript 与 ESLint、Vitest、售后同步测试和 Next.js 生产构建。

## 当前路由

- `/aftersales`：售后问题数、经营异常数、产品销量、每周售后率与周环比总览。
- `/aftersales/detail`：按“产品 → 商品链接 → 一级问题 → 二级问题 → 三级问题”实时级联检索。
- `/aftersales/products`：按完整销售规格归并的产品分析，可下钻到商品链接和问题明细。
- `/aftersales/warehouses`：完整仓库分析与问题下钻。
- `/aftersales/settings`：管理员查看五大业务分类并启停已确认的可剔除规则。
- `/aftersales/export`：类别、明细、商品、仓库及完整经营分析 Excel。
- `/aftersales/api/issues`、`/aftersales/api/products`：虚拟表格按需分页接口。
- `/aftersales/healthz`：进程健康检查。
- `/aftersales/readyz`：MySQL、数据新鲜度和订单水位检查。

## 数据边界

候选 Web 分析只读取以下批次数据，规则编辑使用独立事务：

- `ecom_profit.crm_report_current`、`crm_report_batch`
- `ecom_profit.crm_report_issue`、`crm_report_orders`
- `ecom_profit.crm_report_coverage`、`crm_report_denominator_status`
- `ecom_profit.dim_crm_exclusion_rule`

所有问题统一按源工单创建时间归周，上海时区周日至周六；同进度沿用相同时间依据。销售分母是同期付款且有真实发货证据的原销售行，销量按购买份数，订单数按真实订单身份去重。A×3、A×6 和组合规格分别统计，商品标题不参与猜测归属。同期问题数与销售订单之比不是同批订单最终发生售后的概率。

页面、筛选、分页及 Excel 固定同一报告批次。未知分母保留“—”，只有平台、店铺、日期和原件完整性均得到核验才允许使用真实零。规则修改产生共享相同事实的新规则快照，并原子切换报告指针。一级问题直接归入“快递问题、库房问题、买家问题、产品问题、运营问题”；命中可剔除规则的记录保留在全量明细和 Excel 中，但不进入经营、产品、仓库与趋势统计。五类之外的历史问题标记为“待归类”，在业务确认前不进入统计。

商品标识继续按文本展示；原始接口编码和从原订单核实的销售规格分别保存，派生归属带原件定位与内容摘要。

发布按最近五个完整周及现有交互必需的比较期间滚动验收。历史周选择仍保留，尚未核验的旧期间不返回伪造零值，也不使用旧算法回退。更早留存历史的核验不阻塞已经明确划定并通过验收的近周范围。执行状态见[同版本修复实施记录](docs/operations/同版本修复实施记录_20260916.md)。

当前不引入 Redis。MySQL 汇总表承担稳定数据读取，Next.js Cache Components 复用分析结果，虚拟表格只分页传输和渲染可见数据；筛选及 Excel 始终针对完整匹配结果。

## 身份与部署边界

公司网关负责员工登录，并向只监听回环地址的售后服务注入：

- `X-Company-User-Id`
- `X-Company-User-Name`
- `X-Company-Role`，仅接受 `admin` 或 `viewer`

缺少有效身份头的业务请求返回 `401`。健康与就绪接口不依赖员工身份。生产部署、服务验证与回滚步骤见[运维入口](docs/operations/README.md)。
