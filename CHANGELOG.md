# Changelog

本项目遵循 [Keep a Changelog](https://keepachangelog.com/zh-CN/1.1.0/) 的结构，
版本采用语义化版本。

## [Unreleased]

### Planned

- 时点基本面 Provider 与价值质量每日流程；
- 板块/日期版本化涨跌停和公司行动；
- Web 真实任务配置、运行历史与本地认证。

## [0.1.0] - 2026-07-30

### Added

- 解释型策略协议与四个内置参数化策略；
- D 日收盘、下一交易日开盘的共享回测/每日模拟内核；
- BaoStock、AkShare、Tushare 日线 Provider；
- 不可变批次、分区发布、质量门禁和数据血缘；
- MySQL 8.4 模型与 Alembic 迁移；
- 持久 Runner、日程、租约、心跳、重试和回收；
- 模拟账户、候选/订单/成交/净值账本与完整运行指纹；
- Console、HTTPS Webhook 和事务 Outbox；
- FastAPI + Vue 研究工作台与 JSON Schema 参数表单；
- Python entry point 策略插件和独立示例包；
- Docker Compose 一键部署与完整 CI。

### Security

- 默认 Web 仅映射到回环地址，MySQL 不映射宿主机端口；
- 容器使用非 root 用户；
- 运行配置和错误路径避免输出数据库、Token 与 Webhook 凭据。
