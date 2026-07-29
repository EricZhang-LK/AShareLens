# AShareLens（A股透镜）

开箱即用、可解释、可复现的本地 A 股量化选股平台。

> 当前处于早期开发阶段。仓库首先交付使用确定性合成行情运行的核心闭环，真实数据、Web 和 Docker 能力将按公开路线图逐步加入。

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

完整设计见
[`docs/superpowers/specs/2026-07-29-asharelens-platform-design.md`](docs/superpowers/specs/2026-07-29-asharelens-platform-design.md)。

## 许可证与声明

项目使用 [MIT License](LICENSE)。项目仅用于研究和软件开发，不构成任何投资建议。

