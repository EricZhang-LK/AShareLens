# AShareLens（A股透镜）

开箱即用、可解释、可复现的本地 A 股量化选股平台。

> 当前处于早期开发阶段。仓库已经具备确定性离线闭环、三种数据源、
> 四种内置策略、MySQL 持久化、可恢复 Runner 和可靠通知；Web 与 Docker
> 能力仍在开发。

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

## Web 研究台

Web 研究台使用 FastAPI + Vue 3，同一端口提供界面和 `/api/v1`。默认只监听
`127.0.0.1`，不会无意暴露到局域网。策略参数表单直接由 Python 策略的 Pydantic
JSON Schema 生成；参数会先交回 Python 校验，再进入与每日模拟共用的回测内核。

```powershell
.\.venv\Scripts\python.exe -m pip install -e ".[server,dev]"
Set-Location web
npm ci
npm run build
Set-Location ..
.\.venv\Scripts\python.exe -m asharelens.cli web
```

访问 `http://127.0.0.1:8000`。源码开发时可分别运行后端 `asharelens web` 和前端
`npm run dev`；Vite 会把 `/api` 请求转发到本地 8000 端口。只有明确需要从其他设备
访问时，才使用 `--host 0.0.0.0 --allow-network`，并自行配置主机防火墙。

## 真实数据源

默认路由顺序为 BaoStock → AkShare → Tushare，用户可以调整。路由以完整数据分区为
单位切换，绝不把不同来源的股票行拼成一个“看似完整”的分区。

- BaoStock：默认源，匿名登录，覆盖沪深基础数据。
- AkShare：免注册补充源，重点补充北交所；当前股票列表不能用于历史时点股票池。
- Tushare：用户可选配置 Token，提供可追溯的历史上市/退市信息；接口权限和积分以
  Tushare 官方规则为准。

```powershell
.\.venv\Scripts\python.exe -m pip install -e ".[baostock,akshare,dev]"
.\.venv\Scripts\python.exe -m asharelens.cli provider list
.\.venv\Scripts\python.exe -m asharelens.cli provider check baostock
.\.venv\Scripts\python.exe -m asharelens.cli provider check akshare

# 可选：安装全部数据源并配置 Tushare
.\.venv\Scripts\python.exe -m pip install -e ".[data,dev]"
$env:TUSHARE_TOKEN = "你的 Token"
.\.venv\Scripts\python.exe -m asharelens.cli provider check tushare
```

三家 Provider 都把成交量规范为股、成交额规范为人民币元；原始接口单位与换算规则
会进入批次请求证据。AkShare 与 Tushare SDK 均为可选依赖，不影响基础 SDK 和离线
演示。外部数据的可用性、许可和使用限制以
[AKShare 文档](https://akshare.akfamily.xyz/)与
[Tushare 文档](https://tushare.pro/document/2)为准。

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

## 策略与通知

首批内置策略包括均线交叉、动量 RPS、价值质量和趋势回踩。策略参数使用 Pydantic
模型定义，同一份 JSON Schema 将用于后续 Web 表单自动生成。价值质量策略只接受
带 `as_of_date` 的时点基本面，拒绝把未来披露的数据带入历史回测。

通知采用 MySQL 事务性 Outbox：业务事务同时保存消息和 `notification.deliver`
任务，复用 Runner 的租约、心跳与重试机制。控制台渠道用于零配置预览；通用 HTTPS
Webhook 向飞书、企微、钉钉等中继服务发送渠道无关 JSON。每次请求同时在消息体和
HTTP Header 中携带幂等键，接收端可据此消除极端进程故障下的重复投递。Webhook
地址只存在于运行时配置中，错误日志不会记录完整地址或密钥。

完整设计见
[`docs/superpowers/specs/2026-07-29-asharelens-platform-design.md`](docs/superpowers/specs/2026-07-29-asharelens-platform-design.md)。

## 许可证与声明

项目使用 [MIT License](LICENSE)。项目仅用于研究和软件开发，不构成任何投资建议。
