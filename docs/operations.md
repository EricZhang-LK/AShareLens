# 运维手册

## 配置

Docker Compose 自动读取项目目录中的 `.env`。从 `.env.example` 复制后修改，不要把
`.env`、Token、Webhook 地址或数据库密码提交到 Git。

常用配置：

| 变量 | 说明 | 默认 |
|---|---|---|
| `ASHARELENS_PROVIDERS` | 按顺序回退的数据源 | `baostock` |
| `ASHARELENS_SYMBOLS` | 规范化股票代码，逗号分隔 | 三只功能示例 |
| `ASHARELENS_STRATEGY` | 策略 ID | `moving_average` |
| `ASHARELENS_STRATEGY_PARAMS` | JSON 参数对象 | `{}` |
| `ASHARELENS_LOOKBACK_DAYS` | 每次同步的日历日窗口 | `550` |
| `ASHARELENS_NOTIFIERS` | `console` / `webhook` | `console` |
| `ASHARELENS_SCHEDULE_TIME` | 本地每日时间 | `18:00` |
| `ASHARELENS_SCHEDULE_TIMEZONE` | IANA 时区 | `Asia/Shanghai` |

修改策略、股票池或日程后，已有同名日程不会被静默覆盖。执行：

```bash
docker compose run --rm initialize
```

若提示配置冲突，应先确认是否确实要替换现有规则。首版 CLI 只提供安全的幂等创建；
修改日程需要在备份后通过数据库管理流程明确处理，避免运行中的计划被意外改写。

## 启动与健康检查

```bash
docker compose up -d --build
docker compose ps --all
curl http://127.0.0.1:8000/api/v1/health
docker compose exec web asharelens database check
docker compose exec runner asharelens runner doctor
```

关键日志：

```bash
docker compose logs -f mysql migrate initialize
docker compose logs -f runner
docker compose logs -f runner-notifications
docker compose logs -f web
```

`migrate` 或 `initialize` 非零退出时，Web 和 Runner 不应启动。先查看对应日志，不要
通过删除数据库卷绕过迁移错误。

## 手动运行

幂等投递任务，适合验证调度和重试：

```bash
docker compose exec runner \
  asharelens runner enqueue-daily --date 2026-07-30
```

同步执行并等待结果，适合排查 Provider：

```bash
docker compose exec runner \
  asharelens run-daily --date 2026-07-30
```

外部数据源诊断：

```bash
docker compose exec runner asharelens provider list
docker compose exec runner asharelens provider check baostock
```

## 备份与恢复

升级前始终备份。以下命令把逻辑备份写到当前目录，命令行不包含密码：

```bash
docker compose exec -T mysql \
  sh -c 'exec mysqldump -u"$MYSQL_USER" -p"$MYSQL_PASSWORD" \
  --single-transaction --routines --triggers "$MYSQL_DATABASE"' \
  > asharelens-backup.sql
```

确认文件非空并放入受控存储。恢复应在停掉 Web/Runner、使用一个新建的空数据库并
确认备份来源后进行；不要直接覆盖仍在运行的生产库。示例：

```bash
docker compose stop web runner runner-notifications
docker compose exec -T mysql \
  sh -c 'exec mysql -u"$MYSQL_USER" -p"$MYSQL_PASSWORD" "$MYSQL_DATABASE"' \
  < asharelens-backup.sql
docker compose run --rm migrate
docker compose up -d web runner runner-notifications
```

恢复后检查 revision、账户最后交易日、任务积压和最新通知状态。

## 升级

1. 阅读 `CHANGELOG.md` 和迁移说明；
2. 备份数据库；
3. 获取目标代码或镜像；
4. 构建镜像；
5. 单独运行迁移并检查退出码；
6. 幂等运行初始化；
7. 启动常驻服务并执行健康检查。

```bash
docker compose build
docker compose run --rm migrate
docker compose run --rm initialize
docker compose up -d
```

不要在迁移失败后启动新版本 Runner。降级数据库只适用于可丢弃环境；生产恢复优先
使用升级前备份。

## 常见问题

### `no_data`

所有配置源都明确返回空记录。节假日属于正常情况；交易日出现时，检查代码格式、
股票上市状态、Provider 健康和请求日期。

### 任务不断重试

`runner doctor` 查看积压，日志只会输出脱敏错误。网络超时和上游不可用会重试；质量
失败、未知策略和无效配置不会无限重试。

### `quality_gate_failed`

至少一个返回交易日未达到股票池覆盖率或出现重复/日期问题。不要为了得到结果直接把
门限设为零；先确认是否包含已退市、不在该历史日期上市或 Provider 不覆盖的证券。

### Webhook 没有消息

确认 URL 为 HTTPS、`ASHARELENS_NOTIFIERS` 包含 `webhook`，并查看
`runner-notifications`。接收端应按 `Idempotency-Key` 去重。

### 数据库需要迁移

运行 `docker compose run --rm migrate`。若失败，保存日志并从备份恢复或提交问题；
不要手改 `alembic_version`。

## 网络与安全

Compose 不映射 MySQL 端口，Web 默认只绑定宿主机回环地址。需要远程访问时，应通过
有 TLS、身份认证和访问控制的反向代理；不要简单把端口改为 `0.0.0.0` 暴露到公网。
定期轮换 `.env` 中的数据库密码、Tushare Token 和 Webhook URL。
