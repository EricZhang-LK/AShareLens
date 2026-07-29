# Python 策略插件

AShareLens 通过 Python 包的 entry point 发现策略。插件安装后会与内置策略一起出现在
Web 策略目录中；Pydantic 参数模型的 JSON Schema 会直接生成参数表单，不需要修改
前端。

## 最小结构

仓库中的 [`examples/strategy_plugin`](../examples/strategy_plugin) 是一个可安装示例：

```bash
python -m pip install -e ./examples/strategy_plugin
asharelens web
```

插件包在 `pyproject.toml` 中声明：

```toml
[project.entry-points."asharelens.strategies"]
example_momentum = "example_strategy:ExampleMomentumStrategy"
```

目标可以是一个无需参数即可构造的类，也可以是已构造的策略对象。策略必须提供：

- `metadata`：`StrategyMetadata`，其中 `strategy_id` 在当前进程内唯一；
- `parameter_model()`：返回 `pydantic.BaseModel` 子类；
- `generate(context, params)`：返回不可变的 `SelectionCandidate` 元组；
- `plugin_api_version="1.0"`：用于阻止不兼容插件被静默加载。

加载顺序按 entry point 名称排序；ID 与内置策略或其他插件冲突时，应用会明确失败，
不会随机覆盖。参数模型应设置 `extra="forbid"`，这样拼错的字段不会被忽略。

## 时点与解释约束

`StrategyContext` 只允许访问不晚于 `signal_date` 的行情和基本面快照。策略应为入选与
排除结果都提供稳定的理由代码，并把参与判断的数值写入 `metrics`，以便 Web、推送和
复现实验使用同一份证据。

不要在策略内部自行下载行情、读取未来数据、发送消息或修改账户。数据获取、执行、
持久化和通知分别由平台适配器负责，这样同一个策略才能在回测和每日模拟中保持一致。

## 安全边界

Python 插件是**受信任代码**，安装后拥有与 AShareLens 进程相同的文件、网络和环境
变量权限。只安装自己编写或已经审查源码的插件。AShareLens 会验证接口和版本，但
Python 本身无法把恶意插件安全地限制在进程内；不可信策略应放在独立容器或虚拟机中
运行。
