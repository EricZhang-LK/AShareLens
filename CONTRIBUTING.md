# 参与贡献

感谢你改进 AShareLens。项目优先接受能提升正确性、可解释性、可复现性和本地易用性
的贡献。

## 开始之前

- 功能或架构变化先创建 Issue，说明用户场景、时点假设和不做的范围。
- 安全问题不要创建公开 Issue，请按 `SECURITY.md` 报告。
- 新策略应说明为什么值得内置；个人或实验性策略优先作为 entry point 插件发布。
- 不提交数据源账号、Token、Webhook、真实个人持仓或受许可限制的数据样本。

## 开发环境

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e ".[dev,data]"
Set-Location web
npm ci
Set-Location ..
```

提交前运行：

```powershell
.\.venv\Scripts\python.exe -m pytest --cov=asharelens
.\.venv\Scripts\python.exe -m ruff check .
.\.venv\Scripts\python.exe -m mypy src
Set-Location web
npm test
npm run typecheck
npm run build
```

有 Docker 时再执行：

```bash
docker compose config --quiet
docker compose up -d --build
curl --fail http://127.0.0.1:8000/api/v1/health
docker compose down --volumes
```

## 代码约束

- Bug 和功能使用测试先描述行为；修复后保留回归测试。
- `core` 不依赖 ORM、Web、具体 Provider 或通知传输。
- 所有历史数据必须带时点语义，不能把未来披露信息带入过去。
- 新持久字段需要 Alembic 迁移、SQLite 迁移测试和 MySQL 集成测试。
- 外部异常要转成稳定错误代码，日志与测试输出不得包含凭据。
- 不静默混合 Provider，不静默放宽质量门限，不用收益结果替代正确性测试。
- 用户可见文字以中文为主；公共 Python 名称和代码注释使用清晰英文。

## Pull Request

PR 保持单一目的，并包含：

- 解决的问题和非目标；
- 行为或架构变化；
- 时点、成交、重试和兼容性影响；
- 测试证据；
- 数据源或 UI 变化的截图/样例；
- 迁移、配置和升级说明。

提交代码即表示你有权在项目 MIT 许可证下提供它。
