# 财序（NetWorthTracker）

个人资产负债记录与净资产追踪的 Windows 桌面应用。它不是日常消费记账工具，而是通过维护**账户 → 类别子项 → 估值快照**，计算净资产、资产分布、历史趋势与持仓盈亏；支持多币种、自动获取汇率，以及股票、基金、黄金白银与大宗商品行情。

- Python 3.9+ / PySide6（原生 Qt 窗口）
- SQLite（单文件，Python 内置）/ SQLAlchemy 2.x / Alembic
- 图表：Qt 原生绘制（环形图 + 折线图）
- 金额：`Decimal`，数据库 `NUMERIC(18,2)`
- 支持币种：人民币（CNY）、美元（USD）、日元（JPY）、澳门元（MOP）、港币（HKD）

## 一、项目结构

```
NetWorthTracker/
├─ main.py                    # 应用入口、启动连接、全局异常兜底
├─ dev_run.py                 # 开发用热重启（保存 .py 自动重启）
├─ seed.py                    # 演示数据（多子项账户 + 成本批次 + 近 12 月快照）
├─ requirements.txt
├─ config.example.ini         # 配置示例；实际 config.ini 首次运行时生成
├─ alembic.ini
├─ alembic/
│  ├─ env.py
│  ├─ script.py.mako
│  └─ versions/               # 0001 初始（SQLite 完整表结构）
├─ NetWorthTracker.spec       # PyInstaller 打包配置
├─ app/
│  ├─ config.py               # config.ini 读写、应用/资源目录
│  ├─ db/
│  │  ├─ engine.py            # Engine / Session、连接测试
│  │  ├─ models.py            # accounts / account_items / valuation_snapshots
│  │  │                       #   position_lots / cash_flows / exchange_rates / price_quotes
│  │  └─ migrate.py           # 编程式执行 Alembic upgrade head
│  ├─ services/
│  │  ├─ accounts.py          # 账户与子项 CRUD、归档、总览（含现价）
│  │  ├─ snapshots.py         # 单条/批量快照、冲突检测
│  │  ├─ analytics.py         # 前向填充、净资产、分布、历史、拆解
│  │  ├─ exchange_rates.py    # 汇率拉取、按日/最新汇率折算
│  │  ├─ quotes/              # 行情适配器：股票/ETF、基金、黄金白银、大宗商品、汇率
│  │  ├─ valuation/           # 按估值方式计息/行情/手动估值与批量刷新
│  │  ├─ cash_flows.py        # 利息、分红、租金、费用与买卖流水
│  │  ├─ profit.py            # 成本批次、市值/盈亏、区间盈亏
│  │  ├─ csv_io.py            # CSV 导入导出与校验
│  │  └─ backup.py            # SQLite 在线备份
│  ├─ ui/
│  │  ├─ styles.py            # 浅色/深色 QSS 与图表配色
│  │  ├─ common.py            # 卡片、表格、消息框等
│  │  ├─ main_window.py       # 侧边导航 + 页面栈 + 定时刷新
│  │  ├─ widgets/charts.py    # 环形图、折线图
│  │  ├─ dialogs/             # 数据库配置、账户、子项、估值、批量、CSV
│  │  └─ pages/               # 仪表盘 / 账户 / 盈亏 / 历史 / 数据 / 设置
│  └─ utils/                  # 金额、日期、异常、后台任务
└─ README.md
```

## 二、数据库

应用使用 **SQLite**，无需安装数据库服务：

- 默认数据库文件：应用目录下的 `networth.db`（相对路径，随程序目录一起移动）。
- 首次启动会自动创建文件并执行 Alembic 迁移，无需配置账号密码。
- 可在「设置 → 数据库文件」中更换为其它 `.db` 文件；文件不存在时会自动创建。
- 旧版本位于 `%LOCALAPPDATA%\NetWorthTracker\networth.db` 的数据库，首次启动会自动复制到应用目录并改写为相对路径。
- 应用只管理自身业务表，不会修改或删除其它文件。

## 三、安装与运行

```powershell
cd NetWorthTracker

py -3.11 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt

python main.py
```

开发时可用热重启，保存任意 `.py` 后自动重启应用：

```powershell
python dev_run.py
```

首次启动会自动在用户数据目录创建 SQLite 数据库并执行 Alembic 迁移，无需填写连接信息。如需使用其它数据库文件，可在「设置 → 数据库文件」中切换（支持选择已有 `.db` 或新建）。

配置保存在**应用目录**的 `config.ini`：

- 源码运行：项目根目录
- 打包运行：`NetWorthTracker.exe` 所在目录

`config.ini` 的 `[database]` 段仅保存数据库文件路径（`path`），不包含账号密码。

### Alembic 命令行（可选）

`alembic.ini` 配合 `config.ini` 使用：

```powershell
alembic upgrade head
alembic current
alembic downgrade base
```

应用运行时的迁移由 `app/db/migrate.py` 调用 Alembic API 完成。

## 四、数据模型与计算口径

### 账户与子项

- `accounts`：名称全局唯一；`side` 为 `asset` / `liability`；归档账户保留历史但不计入净资产。
- `account_items`：账户下的类别子项（如证券账户下的现金 / 股票 / 债券），每个子项单独设置币种；类别包括现金、股票、债券、基金、黄金、白银、大宗商品、加密资产、固定资产与其他资产，不同类别可选的估值方式不同；行情类子项可填代码与市场（`CN` / `HK` / `US` / 基金 / 黄金 / 白银 / 大宗商品），市场按代码自动识别。
- `valuation_snapshots`：以**子项**为单位、按日期保存估值，`UNIQUE(item_id, snapshot_date)`；同一天重复录入会提示是否覆盖。
- `position_lots`：成本批次（买入日期、数量、单价、手续费、币种），用于计算市值、盈亏与区间收益。
- `exchange_rates`：各币种兑人民币的每日汇率，`UNIQUE(currency_code, rate_date)`。
- `price_quotes`：股票最新行情缓存（代码、市场、价格、币种、报价时间、来源），每个代码保留一条。
- 净资产、折算金额、盈亏等均为派生数据，查询时实时计算，不落库。

### 币种与汇率

- 每个子项可用不同币种；账户币种仅作为新增子项时的默认值。
- 汇率在启动后、每天 00:00 自动拉取，也可在「账户管理」点「刷新」手动更新；数据源为免费公开接口，多源回退。
- 实时金额（账户页、仪表盘、盈亏当前值）统一按各币种**最新汇率**折算为人民币；历史曲线与区间分析按「统计当日汇率」折算，缺失时前向填充。
- 金额按币种显示对应符号（¥ / $ / JP¥ / MOP$ / HK$）。

### 股票行情

- A 股、港股、美股最新价，来源为腾讯、东方财富、新浪（免费、无需 Key），逐源回退。
- 启动后自动拉取，运行期间每 5 分钟刷新一次；也可在账户管理点「刷新」同时更新汇率与行情。
- 有代码的子项，市值 = 持仓数量（成本批次合计）× 最新价；行情只写当日估值快照，且当天已有快照时跳过，不覆盖手工录入。
- 行情失败时保留上次报价，不影响其它功能；无行情时回退最近一次手工估值。

### 净资产与盈亏

- 净资产 = 各资产子项最新估值折算之和 − 各负债子项最新估值折算之和。
- 某日无快照时，取该日之前最近一条（窗口函数 `ROW_NUMBER() OVER (PARTITION BY item_id ORDER BY snapshot_date DESC)`）。
- 盈亏 =（市值 − 成本合计），盈亏率 = 盈亏 ÷ 成本合计，按成本币种计算，再折算人民币展示。
- 区间盈亏 =（期末市值 − 期末成本）−（期初市值 − 期初成本），即浮盈变化，期间新买入不计入收益；区间收益率 = 区间盈亏 ÷ 期初成本（期初无持仓时显示「—」）。
- 区间支持：近一个月、近一年、指定年度、指定月份。

### 资产分布

- 按类别统计时，类别内存在多种币种会拆分为「现金 · CNY」「现金 · USD」等扇区；单币种类别保持「股票」等原名称。
- 按账户统计时按账户合并；占比均以人民币口径计算。

## 五、功能与验证方法

| 模块 | 操作 | 验证 |
|---|---|---|
| 首次配置 | 首次启动自动创建数据库文件 | 自动建库建表，无需填写连接信息 |
| 账户管理 | 新增资产/负债账户，一个账户可含多个类别子项 | 主从布局；同名报错；归档/删除需确认并级联 |
| 子项管理 | 子项名称、币种、类别、股票代码 | 仅「股票」显示代码；多币种各自折算 |
| 估值录入 | 选中子项录入，或账户内批量录入 | 同日重复提示覆盖；即时刷新各页面 |
| 汇率刷新 | 账户管理点「刷新」 | 汇率条更新，账户估值同步变化 |
| 行情刷新 | 股票/ETF、公募基金、黄金、白银、原油/铜/天然气 | 显示现价与市值；失败回退缓存并提示「行情已过期」 |
| 仪表盘 | 卡片、分布环形图、净资产曲线 | 净资产在前；类别可切币种拆分；区间/粒度切换 |
| 盈亏分析 | 累计与区间视图，双击编辑成本批次 | 盈亏额/率按成本币种；区间口径正确 |
| 历史明细 | 按账户和日期筛选，编辑/删除 | 修改后图表同步；日期冲突有提示 |
| 变化拆解 | 选期初/期末日期点「对比」 | 显示两期总资产/负债/净资产与按子项变化额 |
| CSV | 导出账户/快照；导入快照 | Excel 正常打开（BOM）；导入前预览、校验、重复策略 |
| 备份 | 「数据管理 → 立即备份」 | 生成 `.db` 副本文件 |
| 持久化 | 关闭应用再启动 | 数据仍在（SQLite 文件） |

### 演示数据

完成数据库配置后：

```powershell
python seed.py
```

会创建多子项账户、成本批次与近 12 个月月末快照（幂等覆盖）。运行后在仪表盘切换月/年粒度即可看到曲线，在盈亏页切换区间查看收益。

## 六、CSV 格式

快照导入模板：

```csv
account_name,item_name,snapshot_date,value,note
招商银行活期,活期现金,2026-10-31,82500.00,十月月末
住房按揭,按揭本金,2026-10-31,888000.00,
```

- 必需列：`account_name`、`snapshot_date`、`value`；`item_name` 与 `note` 可选。
- 账户只有一个子项时可省略 `item_name`；多个子项时必须填写。
- 日期接受 `YYYY-MM-DD` 或 `YYYY/MM/DD`。
- 导出文件为 UTF-8 with BOM；导入支持 UTF-8 / GBK。
- 导入前会校验账户/子项是否存在、是否归档、日期、金额、文件内重复与数据库重复；可选择跳过或覆盖。

## 七、备份与恢复

「数据管理 → 立即备份」会调用 SQLite 在线备份接口，把当前数据库复制为独立的 `.db` 文件（默认命名为 `networth_backup_YYYYMMDD_HHMMSS.db`），无需额外安装任何客户端。

恢复方式：

1. 关闭应用。
2. 用备份文件覆盖当前数据库文件（默认位于应用目录下的 `networth.db`），或在「设置 → 数据库文件」中直接切换到备份文件。
3. 重新启动应用。

「设置」中可开启启动时自动备份，并指定目录。自动备份失败只在状态栏提示，不阻塞启动。

## 八、PyInstaller 打包

```powershell
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
pyinstaller NetWorthTracker.spec --noconfirm
```

输出（onedir，整体约 190 MB）：

```text
dist\NetWorthTracker\NetWorthTracker.exe
```

分发与运行说明：

- 必须复制整个 `dist\NetWorthTracker` 目录，不能只拷 exe。
- 目标机需 64 位 Windows；数据库为本地 SQLite 文件，无需安装数据库服务。
- 放到可写目录（不要放 `Program Files`），因为 `config.ini`、`networth.log`、`networth.db` 都写在 exe 同目录。
- 首次运行自动创建数据库文件与表结构；需要联网才能获取汇率与股票行情。
- 未签名 exe 首次运行可能被 SmartScreen 拦截，选择「更多信息 → 仍要运行」。
- 迁移数据时直接复制 SQLite `.db` 文件即可（默认位于应用目录下的 `networth.db`）。
- `alembic/`、`alembic.ini` 与界面资源通过 spec 的 `datas` 打包；`hiddenimports` 含 `logging.config` 等动态依赖。

## 九、常见问题

**启动即退出 / 无窗口**：查看应用目录下的 `startup_error.log`（启动失败详情）与 `networth.log`（运行日志）。

**数据库文件无法打开**：检查文件路径所在目录是否存在、是否有写入权限；文件被其它程序占用时请关闭后重试。

**数据库文件损坏或不是 SQLite**：换回备份文件，或在「设置 → 数据库文件」中选择有效的 `.db` 文件。

**汇率或行情拉取失败**：检查网络与防火墙；失败不影响已有数据，保留上次缓存，可稍后点「刷新」重试。

**股票没有现价**：确认子项类别为「股票」且代码正确（如 `600519` / `00700` / `AAPL`），并检查是否已录入成本批次（数量来源）。

**中文图表乱码**：图表默认使用微软雅黑，Qt 会在缺少该字体时自动回退；也可修改 `app/ui/widgets/charts.py` 中的 `FONT_FAMILY`。

**应用启动后无数据**：确认「设置 → 数据库文件」指向的是正确的 `.db` 文件。

## 十、实现约定

- 所有金额计算在 Python 侧使用 `Decimal`；图表绘制时仅为像素坐标将金额转为 `float`。
- 数据库访问使用 SQLAlchemy 2.x `select()` 与 Session；每个操作使用独立会话。
- 仪表盘、历史查询、行情/汇率刷新与备份在 `QThreadPool` 后台线程执行，避免界面卡顿。
- 全局异常捕获：未捕获异常写入 `networth.log` 并转为中文提示，启动失败写入 `startup_error.log` 并弹窗。
- 归档账户不参与当前净资产与分布，但历史快照保留；恢复后重新计入。
