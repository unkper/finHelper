# finHelper AI Agent 规范指南 (AGENT.md)

## 1. 项目简介 (Project Overview)

finHelper 是一个基于 Python 和 Flask 框架构建的个人资产与投资管理辅助系统。其核心业务包括：多币种资金账户管理、历史资产快照追踪、汇率自动转换与本地缓存，以及个人投资主题（Themes）的生命周期与结构化管理。

## 2. 架构与目录结构 (Architecture & Structure)

项目采用经典的分层架构（工厂模式），将路由配置与具体业务分离：

- **`config.py` & `.env`**: 配置与环境变量（如 `SECRET_KEY`, `API_PROXY`）。
- **`app/`**: Flask 核心应用包。
  - **`__init__.py`**: 包含 `create_app` 工厂函数及系统组件注册。
  - **`database.py`**: SQLite 数据库初始化、连接获取 (`get_db`) 和结构迁移逻辑。
  - **`utils.py`**: 全局工具函数（如 `quantize` 精确计算）。
  - **`routes/`**: 路由控制器层，负责定义端点（Blueprint）、解析表单以及视图渲染（包含 `accounts.py`, `investments.py`, `main.py`, `snapshots.py`）。
  - **`services/`**: 业务逻辑层，封装所有数据库交互及核心业务算法（包含 `exchange.py`, `investment.py`, `snapshot.py`）。

*注意：根目录下虽然存在旧版的单文件 `app.py` 遗留代码，但在修改或新增功能时，请严格在 `app/` 内部的分层架构下开发。*

## 3. 技术栈说明 (Tech Stack)

- **后端语言**: Python 3.x
- **Web 框架**: Flask, Flask Blueprint
- **持久化**: SQLite 3 (原生 `sqlite3` 模块，使用 `sqlite3.Row` 返回字典格式行)
- **前端模板**: Jinja2 模板引擎
- **核心运算**: `decimal.Decimal` (处理金融浮点数四舍五入 `ROUND_HALF_UP`)
- **外部集成**: `urllib.request` (请求外部汇率数据，如 Frankfurter API，原生支持全局代理)

## 4. 数据库 Schema (Database Schema)

系统核心数据保存在本地的 `assets.db` 中，具体分属两大业务域：

1. **资产快照模块 (Snapshots)**:
   - `accounts`: 账户信息（支持分类及币种标识如 `CNY`, `HKD`, `USD`）。
   - `snapshots`: 历史资产快照头部（包含快照时间、备注等）。
   - `snapshot_entries`: 单次快照挂载的具体账户资产明细。
2. **汇率缓存模块 (Exchange)**:
   - `exchange_rates`: 用于对齐基准货币（Base Currency）和目标日期的汇率缓存。
3. **投资主题跟踪 (Investments)**:
   - `themes`: 主题状态机（包含观察期 `observing`、建仓期 `accumulating`、持有期 `holding` 等）。
   - `theme_articles`: 关联该主题的外部研报、参考网址。
   - `theme_assets`: 相关监控标的股票池与目标买卖价。
   - `theme_milestones`: 项目生命周期中的关键时间线/里程碑。

## 5. Agent 编码规范与约束 (Agent Guidelines)

为维护项目的健康迭代，AI Agent 在执行修改或提供代码时需遵守以下准则：

1. **严格的关注点分离 (SoC)**: 绝不能在 `routes/` 的视图函数中直接写 SQL 查询；所有的 SQL 操作（`SELECT`, `INSERT`, `UPDATE`）必须封装为函数放入 `services/` 目录下。
2. **浮点安全与格式化**: 任何前端资金展示的转换或本地库读取出的金额，必须经过 `utils.quantize()` 处理保留两位小数；多币种统计一律依赖 `services.exchange.convert_amount`。
3. **API与代理感知**: 国内或受限网络下外部 API 请求易超时，修改或编写外部请求逻辑时必须读取 `current_app.config.get("API_PROXY")` 提供代理支持（参考 `test.py` 的处理逻辑）。
4. **数据库操作安全**: 所有的 `db.execute()` 必须使用参数化查询（即 `?` 占位符）防止 SQL 注入风险。对写入操作需显式执行 `db.commit()`。
5. **平滑的数据库演进**: 若功能需求涉及表结构调整，应优先扩写 `database.py` 中的 `migrate_db()` 进行兼容性升级。