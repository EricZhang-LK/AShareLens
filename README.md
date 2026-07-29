# AShareLens（A股透镜）

开箱即用、可解释、可复现的本地 A 股量化选股平台。

> 当前处于早期开发阶段。仓库已经具备确定性离线闭环、BaoStock Provider、
> MySQL 持久化和可恢复 Runner；AkShare、Tushare、Web 与 Docker 能力仍在开发。

## 项目原则

- 每条选股信号都提供结构化解释。
- 每次运行都生成可复现指纹。
- 数据质量不合格时不静默产生正常结果。
- 历史回测与每日模拟使用同一事件内核。
- 默认本地运行，不默认上传策略、凭据或数据。

## 开发

要求 Python 3.12 或 3.13。

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e ".[dev]"
.\.venv\Scripts\python.exe -m pytest
```

## 离线演示

演示命令使用三只确定性合成股票完成收盘选股、下一交易日开盘模拟成交、
净值计算和运行指纹生成，不需要网络、账号或真实行情。

```powershell
.\.venv\Scripts\python.exe -m asharelens.cli demo
.\.venv\Scripts\python.exe -m asharelens.cli demo --json
```

## 免费真实数据

BaoStock 是默认真实数据源，匿名登录、不要求用户申请 Token。它作为可选依赖安装，
基础 SDK 和离线演示不会被数据源 SDK 绑定。

```powershell
.\.venv\Scripts\python.exe -m pip install -e ".[baostock,dev]"
.\.venv\Scripts\python.exe -m asharelens.cli provider list
.\.venv\Scripts\python.exe -m asharelens.cli provider check baostock
```

当前 BaoStock Provider 提供沪深股票列表、交易日历和日线行情。北交所数据将由
AkShare 补充 Provider 覆盖。外部数据的可用性、许可和使用限制以数据提供方说明为准。

## MySQL 持久化

服务端生产环境固定使用 MySQL 8.4 LTS、InnoDB 和 utf8mb4。数据库时间统一保存为
UTC，价格和金额使用定点 DECIMAL。SQLite 仅用于 SDK 开发和仓储单元测试，不是正式
服务端数据库。

```powershell
$env:ASHARELENS_DATABASE_URL = "mysql+pymysql://user:password@127.0.0.1:3306/asharelens?charset=utf8mb4"
.\.venv\Scripts\alembic.exe upgrade head
.\.venv\Scripts\python.exe -m asharelens.cli database check
```

正式升级必须先备份 MySQL，再执行迁移；迁移失败时不得启动新版本服务。

## 持久任务 Runner

首发 Runner 使用 MySQL 任务表，不要求 Redis 或 Celery。任务通过租约和心跳识别
失联 Worker，采用至少一次交付，并由任务幂等键、运行指纹和业务唯一约束防止重复
效果。只有在多机高并发或分钟级任务成为实际瓶颈时，才需要增加其他队列适配器。

```powershell
# 检查数据库、迁移版本和队列积压
.\.venv\Scripts\python.exe -m asharelens.cli runner doctor

# 运维或测试：分别执行一个轮次
.\.venv\Scripts\python.exe -m asharelens.cli runner schedule --once
.\.venv\Scripts\python.exe -m asharelens.cli runner work --once
.\.venv\Scripts\python.exe -m asharelens.cli runner reap --once

# Docker Runner 的单进程协调入口；收到 SIGINT/SIGTERM 后不再领取新任务
.\.venv\Scripts\python.exe -m asharelens.cli runner start
```

每日模拟账户和历史回测调用同一个 `DailyCycleEngine`。每个模拟日期会保存策略版本、
参数、精确数据分区、输入/输出状态哈希、解释型候选、订单、成交和净值。

完整设计见
[`docs/superpowers/specs/2026-07-29-asharelens-platform-design.md`](docs/superpowers/specs/2026-07-29-asharelens-platform-design.md)。

## 许可证与声明

项目使用 [MIT License](LICENSE)。项目仅用于研究和软件开发，不构成任何投资建议。
