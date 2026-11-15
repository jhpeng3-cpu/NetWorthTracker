# 净资产管理（NetWorthTracker）

个人资产负债记录与净资产追踪的 Windows 桌面应用。它不是日常消费记账工具，而是通过手动维护各资产/负债账户的**当前估值快照**，计算净资产并展示资产分布与历史趋势。

- Python 3.11+ / PySide6（原生 Qt 窗口）
  - 代码保持 3.9+ 兼容；本次交付在 Python 3.9 + MySQL 8.0 环境完成运行验证。
- MySQL 8.0+ / SQLAlchemy 2.x / PyMySQL / Alembic
- 图表：matplotlib（嵌入 Qt）
- 金额：`Decimal`，数据库 `NUMERIC(18,2)`

## 一、项目结构

```
NetWorthTracker/
├─ main.py                    # 应用入口、启动连接与首次配置
├─ seed.py                    # 演示数据（3 资产 + 2 负债 + 近 12 月快照）
├─ requirements.txt
├─ config.example.ini         # 配置示例；实际 config.ini 在首次运行时生成
├─ alembic.ini
├─ alembic/
│  ├─ env.py
│  ├─ script.py.mako
│  └─ versions/0001_initial.py
├─ NetWorthTracker.spec       # PyInstaller 打包配置
├─ app/
│  ├─ config.py               # config.ini 读写、密码可逆混淆
│  ├─ db/
│  │  ├─ engine.py            # Engine / Session、连接测试
│  │  ├─ models.py            # accounts / valuation_snapshots
│  │  └─ migrate.py           # 编程式执行 Alembic upgrade head
│  ├─ services/
│  │  ├─ accounts.py          # 账户 CRUD、归档、最新估值
│  │  ├─ snapshots.py         # 单条/批量快照、冲突检测
│  │  ├─ analytics.py         # 前向填充、净资产、分布、历史、拆解
│  │  ├─ csv_io.py            # CSV 导入导出与校验
│  │  └─ backup.py            # mysqldump 备份
│  ├─ ui/
│  │  ├─ styles.py            # 浅色/深色 QSS 与图表配色
│  │  ├─ common.py            # 卡片、表格、消息框等
│  │  ├─ main_window.py       # 侧边导航 + 页面栈
│  │  ├─ widgets/charts.py    # 环形图、折线图
│  │  ├─ assets/              # 下拉箭头图标（浅色/深色）
│  │  ├─ dialogs/             # 数据库配置、账户、快照编辑、CSV 预览
│  │  └─ pages/               # 仪表盘 / 账户 / 录入 / 批量 / 历史 / 数据 / 设置
│  └─ utils/                  # 金额、日期、密码混淆、后台任务
└─ README.md
```

## 二、数据库准备

1. 安装 MySQL 8.0+（8.0.16 起才真正校验 `CHECK` 约束），确保服务已启动。
2. 数据库可由应用自动创建：首次「测试连接 / 保存并连接」时会以 `utf8mb4` 创建；若账号没有 `CREATE` 权限，请手动创建：

```sql
CREATE DATABASE networth
  CHARACTER SET utf8mb4
  COLLATE utf8mb4_unicode_ci;
```

3. 如需远程连接，确认 MySQL 账号允许该主机访问（如 `'root'@'%'`），并在防火墙放行 3306 端口。
4. MySQL 8 默认使用 `caching_sha2_password`，`requirements.txt` 已包含 `cryptography` 以完成认证。
5. 应用只管理自身业务表，不会修改或删除其它数据库。

## 三、安装与运行

```powershell
cd NetWorthTracker

py -3.11 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt

python main.py
```

首次启动会弹出数据库配置窗口：填写 host、port、database、user、password，点击「测试连接」，再点击「保存并连接」。应用会自动执行 Alembic 迁移；数据库不存在时会自动创建（utf8mb4）。

配置保存在**应用目录**的 `config.ini`：

- 源码运行：项目根目录
- 打包运行：`NetWorthTracker.exe` 所在目录

密码使用可逆混淆（`obf:` 前缀）保存，仅防止直接肉眼查看，并非强加密；请限制该文件的访问权限。

### Alembic 命令行（可选）

`alembic.ini` 配合 `config.ini` 使用：

```powershell
alembic upgrade head
alembic current
alembic downgrade base
```

应用运行时的迁移由 `app/db/migrate.py` 调用 Alembic API 完成。

## 四、核心计算与前向填充

### 数据模型

- `accounts`：名称全局唯一；`side` 为 `asset` / `liability`；归档账户保留历史但不计入净资产。
- `valuation_snapshots`：`UNIQUE(account_id, snapshot_date)`，同一账户同一天只能有一个估值。
- 净资产不落库，查询时实时计算。

### 前向填充 SQL 思路

取某日 `D` 各账户最新估值，使用窗口函数按账户分组、按日期倒序编号，只保留 `rn = 1`（MySQL 8.0+ 支持窗口函数）：

```sql
WITH ranked AS (
  SELECT s.account_id, s.value, s.snapshot_date,
         ROW_NUMBER() OVER (
           PARTITION BY s.account_id
           ORDER BY s.snapshot_date DESC
         ) AS rn
  FROM valuation_snapshots s
  WHERE s.snapshot_date <= :d
)
SELECT a.id, a.name, a.side, a.category, r.value, r.snapshot_date
FROM accounts a
JOIN ranked r ON r.account_id = a.id AND r.rn = 1
WHERE a.archived = 0;
```

- `D` 当天没有快照时，自动取 `D` 之前最近一条。
- 账户在 `D` 之前完全没有快照时不会出现在结果中，因此不计入。
- 实现位于 `app/services/analytics.py: holdings_as_of()`，使用 SQLAlchemy 2.x 的 `func.row_number().over(...)`。

历史折线图只需一次读取区间内（含区间前）的快照，按日期指针推进做前向填充，避免对每个时间点重复查询：

- 日粒度：区间内逐日计算，无快照日期沿用最近一次估值；
- 月/年粒度：每个周期末，当前周期取今天（`build_period_points()`）。

净资产 = 当日各资产账户最新估值之和 − 各负债账户最新估值之和。

## 五、功能与验证方法

| 模块 | 操作 | 验证 |
|---|---|---|
| 首次配置 | 首次启动填写数据库 | 连接成功、自动建库建表，重启后不再弹窗 |
| 账户管理 | 新增 3 资产 + 2 负债；编辑、归档、删除 | 资产/负债分组显示；同名报错；删除需二次确认并级联 |
| 估值录入 | 选账户、日期、金额 | 同账户同日重复时提示覆盖；即时刷新仪表盘 |
| 批量录入 | 选日期，填多个账户后保存 | 空值跳过；冲突统一提示覆盖；一次性成功写入 |
| 仪表盘 | 查看卡片、环形图、折线图 | 总额正确；类别/账户切换；日/月/年与范围切换 |
| 历史明细 | 按账户和日期筛选，编辑/删除 | 修改后图表同步；日期冲突有提示 |
| 变化拆解 | 选期初/期末日期点「对比」 | 显示两期总资产/负债/净资产与按账户变化额（降序） |
| CSV | 导出账户/快照；导入快照 | Excel 正常打开（BOM）；导入前预览、校验、重复策略 |
| 备份 | 「数据管理 → 立即备份」 | 生成 `.sql`；PATH 无 `mysqldump` 时给出提示 |
| 持久化 | 关闭应用再启动 | 数据仍在（MySQL） |

### 演示数据

完成数据库配置后：

```powershell
python seed.py
```

会创建「自住房产、招商银行活期、沪深300指数基金、住房按揭、信用卡待还」并写入近 12 个月月末快照（幂等覆盖）。运行后在仪表盘切换月/年粒度即可看到三条曲线。

## 六、CSV 格式

快照导入模板：

```csv
account_name,snapshot_date,value,note
招商银行活期,2026-10-31,82500.00,十月月末
住房按揭,2026-10-31,888000.00,
```

- 必需列：`account_name`、`snapshot_date`、`value`；`note` 可选。
- 日期接受 `YYYY-MM-DD` 或 `YYYY/MM/DD`。
- 导出文件为 UTF-8 with BOM；导入支持 UTF-8 / GBK。
- 导入前会校验账户是否存在/是否归档、日期、金额、文件内重复与数据库重复；可选择跳过或覆盖。

## 七、备份与恢复

手动备份调用：

```text
mysqldump --single-transaction --quick --set-gtid-purged=OFF ...
```

需要 `mysqldump` 在 PATH 中，通常位于：

```text
C:\Program Files\MySQL\MySQL Server 8.0\bin
```

恢复示例（PowerShell 不支持 `<` 重定向，因此用 `cmd /c`）：

```powershell
$env:MYSQL_PWD="你的密码"
mysql -h 127.0.0.1 -u root -e "CREATE DATABASE IF NOT EXISTS networth CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci"
cmd /c 'mysql -h 127.0.0.1 -u root networth < networth_backup_YYYYMMDD_HHMMSS.sql'
```

「设置」中可开启启动时自动备份，并指定目录。自动备份失败只在状态栏提示，不阻塞启动。

## 八、PyInstaller 打包

```powershell
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
pyinstaller NetWorthTracker.spec --noconfirm
```

输出：

```text
dist\NetWorthTracker\NetWorthTracker.exe
```

说明：

- 打包采用 **onedir**，启动更快；将整个 `dist\NetWorthTracker` 目录分发即可。
- `alembic/`、`alembic.ini` 与界面箭头资源已通过 spec 的 `datas` 打包，首次运行仍会自动建表。
- spec 的 `hiddenimports` 显式包含 `logging.config`：Alembic 会动态加载 `env.py`，静态分析无法发现该依赖。
- `config.ini`、`networth.log` 生成在 exe 同目录，需保证该目录可写；不建议放在 `Program Files`。
- 备份功能依赖目标机器安装 MySQL 客户端并把 `bin` 加入 PATH；应用本身不打包 `mysqldump`。
- 数据库仍需用户自行安装/远程连接；应用不会捆绑 MySQL。

## 九、常见问题

**密码认证失败**：检查 MySQL 用户名/密码；远程连接需账号具备对应主机的访问授权（`host` 字段）。

**数据库不存在**：应用会尝试自动创建；若账号无 `CREATE` 权限，请先手动执行 `CREATE DATABASE networth CHARACTER SET utf8mb4;`。

**中文图表乱码**：代码已设置微软雅黑/黑体；如系统缺少字体，可安装或修改 `app/ui/widgets/charts.py` 中的 `font.sans-serif`。

**备份提示找不到 mysqldump**：把 MySQL 的 `bin` 目录加入系统 PATH，重启应用。

**应用启动后无数据**：确认当前数据库是否正确；可在「设置 → 数据库连接」查看连接信息（密码隐藏）。

## 十、实现约定

- 所有金额计算在 Python 侧使用 `Decimal`；matplotlib 仅为了绘图在最后一刻转 `float`。
- 数据库访问使用 SQLAlchemy 2.x `select()` 与 Session；每个操作使用独立会话。
- 仪表盘、历史查询与备份在 `QThreadPool` 后台线程执行，避免界面卡顿。
- 归档账户不参与当前净资产与分布，但历史快照保留；恢复后重新计入。
