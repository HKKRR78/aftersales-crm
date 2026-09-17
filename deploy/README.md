# 部署配置索引

`deploy/launchd` 只保存当前仍有效的两个任务配置：

| 文件 | 安装目标 | 职责 |
| --- | --- | --- |
| `com.company.aftersales-dashboard.plist` | `/Users/yyerybz/Library/LaunchAgents/` | 启动并保活 Next.js 售后看板 |
| `com.ecom-profit.crm-aftersales-sync.plist` | `/Users/yyerybz/Library/LaunchAgents/` | 定时执行统一售后数据日更 |

仓库中的 plist 是受版本管理的配置模板。修改后需要同步到服务器 LaunchAgents 并重新加载才会生效；该操作会改变生产状态，必须在明确授权后执行。

旧 Python Web、旧 Nginx 灰度、旧静态发布和旧周报任务配置已移入 [`archive/legacy-python-dashboard`](../archive/legacy-python-dashboard/README.md)，不得重新安装为当前系统的兼容入口。
