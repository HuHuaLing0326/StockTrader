# 数据模块 1a 设计文档：采集层核心

> 状态：**已确认，按此实现**（2026-10-25）　版本 0.2　日期 2026-10-25
>
> 0.2 的变更：第 16.1 节的待确认事项已定；补充脚本与测试的存放规则（3.2）、本机网络环境（2.10–2.12）。
>
> 依据：
> - 需求：`docs/conference_project/wm/ashare-data-collection-prompt.md`（以下简称"采集需求"）、`docs/conference_project/ww/ww_share_data_collection_prompt.md`；
> - 参考实现：wm 的 `src/ashare_agent/data/`、ww 的 `core/data/`（定向阅读，结论见对话记录）；
> - 实测：`docs/design/data-layer-1a-probe-record.md`（以下简称"实测记录"）。
>
> 标记说明：【待确认】需要你决定；【待复测】取决于交易日复测结果；【需核实】实现前要再查证。

---

## 一、范围

### 1.1 本阶段包含

| 编号 | 内容 |
|---|---|
| A1 | 证券标识、代码规范化、交易所与板块规则表 |
| A2 | 传输层：限速、重试、断路器、编码校验、原始响应存档 |
| A3 | 交易日历：是否交易日、上一个、下一个、最近已完成的交易日 |
| A4 | 证券名单与版本：含已退市证券，带生效区间 |
| A5 | 日线：股票、指数、ETF 的原始价；复权因子；按决策时点计算复权价 |
| A6 | 每日交易状态：停牌、ST；每周风险警示名单（ST 与 \*ST） |
| A7 | 全市场快照（股票、ETF）及其存档 |
| A8 | 单只与小批量实时报价 |
| A9 | 健康台账、同步审计、数据冲突记录 |
| A10 | DuckDB 存储：单写入通道、跨进程锁、迁移 |
| A11 | 统一数据接口：按数据类别的方法，带决策时点；回补与每日同步的命令行 |

### 1.2 本阶段不包含（及去向）

| 内容 | 去向 | 理由 |
|---|---|---|
| 行业分类与成分 | 1b 开始前 | 因子的行业上下文才用到；baostock 按日期回查已实测可用 |
| 历史涨跌停价（按规则计算） | 第 2 步模拟券商 | 规则表要带生效日期并逐条核实，券商才用到；1a 只存当日实测的涨跌停价 |
| 财务、公告、资金流、新闻 | 1c | |
| 智能体工具封装 | 第 5 步 | 接口从现在起就带决策时点，届时只需包一层 |
| 定时调度 | 第 8 步 | 1a 提供命令行，手工或外部触发 |
| 北交所数据 | 暂不采集 | 不在默认分析范围；1 万元账户无权限；baostock 不覆盖。规则表仍能识别北交所代码 |
| 东方财富、mootdx 适配器 | 复测之后 | 实测失败【待复测】；接口按适配器设计，之后接入不改结构 |

---

## 二、已确定的决策

1. 先只用免费数据源，不用 Tushare；以后作为一个适配器接入，表结构不变。
2. 分析范围：沪深主板、创业板、科创板；可交易范围由以后的权限规则决定，数据层不做裁剪。
3. 沪深 300 等指数和作为基准的 ETF 纳入数据层，但不进入候选池。
4. 只存原始价和复权因子，复权价由计算得出；不存任何数据源给的前复权序列。实测证实：腾讯和 baostock 的前复权算法不同，同一天相差 5 元以上。
5. 一律按北京时间处理，不依赖主机时区。
6. 测试分两类：受控输入的逻辑测试默认运行；联网测试单独标记，默认不运行。
7. 数据放在项目内的 `data/` 目录（已加入 `.gitignore`）。
8. pandas 锁定在 `>=2.2,<3`。
9. 数据层是普通 Python 模块，不依赖 AgentScope。
10. 1a 的范围按第一节执行：行业分类放到 1b 开始前，历史涨跌停价放到第 2 步，北交所暂不采集。
11. 历史回补从 2015-01-01 开始，包含期间退市的股票。
12. 本机网络（2026-10-25 检查）：直连家庭宽带，没有代理或 VPN 进程在运行，也没有 TUN 虚拟网卡；注册表里残留的系统代理设置 `127.0.0.1:7897` 未启用。所有行情类接口族一律不走代理，并忽略系统代理设置。若以后开启代理软件的 TUN 模式，它会接管全部流量，代码无法绕过，届时需要重新评估。

---

## 三、架构

```
调用方（因子、初筛、命令行、以后的智能体工具）
        │  只说"要什么"：证券、日期范围、复权方式、决策时点
        ▼
统一数据接口 MarketData          service.py
        │  先查库；缺的部分走路由抓取并写库；按决策时点过滤；按需计算复权价
        ▼
路由 Router                      router.py
        │  按优先级表依次尝试；跳过冷却中的源；覆盖不全视为失败；同一序列不拼接
        ▼
源适配器                         sources/tencent.py、sina.py、baostock.py（以后加 eastmoney.py、mootdx.py、tushare.py）
        │  代码格式转换、解析、单位换算、失败分类
        ▼
传输层 Transport                 transport.py
        │  按接口族限速、重试、断路器、超时、解码校验、原始响应存档
        ▼
外部数据源

旁路：存储 Store（store.py，DuckDB 单写入通道）、健康台账（health.py）、配置（config.py）
```

职责边界：
- 只有传输层能发网络请求；适配器不做回退、不碰存储；路由不做解析；统一接口不知道具体数据源。
- baostock 不是 HTTP，传输层为它提供"会话管理器"，同样受限速、断路器、超时和健康台账约束。
- akshare 在 1a 只用于新浪交易日历这一个函数，调用前同样经过新浪接口族的限速和断路器。

### 3.1 代码结构

```
src/stocktrader/data/
  __init__.py
  config.py        配置的校验规则（类型和取值范围）；数值在 config/data.toml
  clock.py         北京时间、交易时段常量、"定型"判断
  security.py      证券标识、规则表、代码规范化、各源代码写法转换
  models.py        标准记录、返回结果、尝试记录、缺口说明、错误类别、数据质量检查
  units.py         单位换算（换算系数只在这里定义）
  errors.py        异常类型
  health.py        健康台账的事件格式与写入通道（传输层与存储层之间唯一共享的契约）
  throttle.py      按接口族限速（进程内串行，可选跨进程串行）
  breaker.py       按接口族的断路器（状态文件多进程共享）
  archive.py       原始响应存档与敏感参数隐去
  watchdog.py      给没有超时参数的第三方调用加超时
  transport.py     HTTP 传输（HttpTransport）与第三方库调用保护（LibraryGuard）
  baostock_client.py  baostock 会话管理
  runtime.py       按配置组装上述组件；其他模块都不依赖它
  store.py         DuckDB 连接、迁移、单写入通道、跨进程锁、幂等写入与冲突检测（通用，不了解具体业务）
  schema.py        当前表结构声明
  migrations.py    迁移历史（已发布的迁移不再修改）
  ledger.py        健康台账入库（从事件文件导入）与查询
  router.py        优先级表与回退执行
  sources/
    __init__.py
    tencent.py     实时报价、日线
    sina.py        实时报价、全市场快照、交易日历
    baostock.py    交易日历、证券名单、日线、复权因子、风险警示名单
  service.py       统一数据接口 MarketData
  sync.py          回补与每日同步任务（写库、审计）
  cli.py           命令行：stocktrader data ...
tests/
  data/            逻辑测试（默认运行）
  live/            联网测试（pytest -m live）
  fixtures/        实测录下的少量真实响应，用于测试解析逻辑
```

### 3.2 脚本与测试的存放

| 位置 | 内容 | 是否上传 git |
|---|---|---|
| `tests/` | pytest 自动化测试：逻辑测试、联网测试、测试用的响应录像 | 上传 |
| `scripts/probes/` | 数据源实测脚本 | 不上传 |
| `scripts/stage_checks/s1/` … `s8/` | 每一步的一次性验证脚本 | 不上传 |
| 部署、集成测试等需要保留的脚本 | 位置以后再定 | 上传 |

`scripts/` 整体不上传 git 的忽略规则，和需要上传的脚本放在哪里，以后一并处理。

---

## 四、证券标识

### 4.1 标识

一只证券由三项共同标识：

| 字段 | 取值 |
|---|---|
| `code` | 6 位数字字符串 |
| `exchange` | `SSE`（上交所）、`SZSE`（深交所）、`BSE`（北交所） |
| `kind` | `STOCK`、`INDEX`、`ETF`、`OTHER` |

派生属性 `board`（仅股票）：`MAIN`（主板）、`CHINEXT`（创业板）、`STAR`（科创板）、`BSE`（北交所）。

### 4.2 规则表

依据：baostock 全量证券名单（含退市）的代码分布，并用腾讯报价第 61 位品种类型抽查（实测记录第七节）。

| 交易所 | 品种 | 板块 | 代码前缀 |
|---|---|---|---|
| SSE | STOCK | MAIN | 600、601、603、605 |
| SSE | STOCK | STAR | 688、689 |
| SZSE | STOCK | MAIN | 000、001、002、003 |
| SZSE | STOCK | CHINEXT | 300、301、302 |
| BSE | STOCK | BSE | 43、83、87、92 开头 |
| SSE | INDEX | — | 000 |
| SZSE | INDEX | — | 399 |
| SSE | ETF | — | 51、52、53、55、56、58 开头 |
| SZSE | ETF | — | 158、159 |

- 规则表是一张数据表加一组测试，不散落在代码里；表中每行注明依据和核实日期。
- 不在表中的前缀一律拒绝识别，报"未知代码"，不猜测。

### 4.3 输入规范化

- 接受的写法：`600519`、`sh600519`、`SH600519`、`600519.SH`、`sh.600519`、`1.600519`（东方财富写法）。
- **裸 6 位代码必须同时给出品种**。`000001` 加 `STOCK` 是平安银行（深交所），加 `INDEX` 是上证指数（上交所）。
- 带交易所前缀或后缀时，以显式给出的交易所为准，并与规则表核对；不一致即报错。
- 规范化结果是不可变对象 `Security(code, exchange, kind)`，全系统只传这个对象。

### 4.4 各数据源的代码写法

| 数据源 | 上交所 | 深交所 | 说明 |
|---|---|---|---|
| 腾讯、新浪 | `sh600519` | `sz000001` | 北交所 `bj` |
| baostock | `sh.600519` | `sz.000001` | 不覆盖北交所 |
| 东方财富 | `1.600519` | `0.000001` | 【待复测】 |
| mootdx | 市场 `1` + `600519` | 市场 `0` + `000001` | 【待复测】 |

---

## 五、数据模型（DuckDB）

通用约定：
- 每张业务表都带 `source`（实际数据源）和 `fetched_at`（抓取时间，带时区的北京时间）。
- 金额统一为元，数量统一为股；保留原始值和原始单位。
- 日期列用 `DATE`，时间列用 `TIMESTAMPTZ`。
- 缺失就是 `NULL`，不填 0。

### 5.1 `schema_migrations`

| 字段 | 类型 | 说明 |
|---|---|---|
| version | INTEGER 主键 | 迁移版本号 |
| applied_at | TIMESTAMPTZ | |
| summary | VARCHAR | |

### 5.2 `instruments`：证券版本表

| 字段 | 类型 | 说明 |
|---|---|---|
| code、exchange、kind | VARCHAR | 证券标识 |
| board | VARCHAR | 仅股票 |
| name | VARCHAR | 名称 |
| list_date / delist_date | DATE | 上市 / 退市日期 |
| status | VARCHAR | `LISTED`、`DELISTED` |
| valid_from / valid_to | DATE | 本版本的生效区间，`valid_to` 为空表示当前有效 |
| history_mode | VARCHAR | `OBSERVED`（我们亲自观察到的变化）、`SOURCE_STATIC`（数据源只给当前值） |
| source、fetched_at | | |

- 主键：`(code, exchange, kind, valid_from)`。
- 每次同步把数据源结果与当前版本比较：名称、状态等有变化时关闭旧版本（填 `valid_to`），插入新版本。
- 我们开始采集之前的名称变化无法得知，这部分标为 `SOURCE_STATIC`，查询结果在缺口说明里注明。

### 5.3 `calendar_observations`：交易日历观测

| 字段 | 类型 | 说明 |
|---|---|---|
| source | VARCHAR | |
| trade_date | DATE | |
| is_open | BOOLEAN | |
| covered_from / covered_to | DATE | 本次观测覆盖的范围；只列开市日的源（新浪）靠它判断"不在列表中即休市" |
| fetched_at | TIMESTAMPTZ | |

- 主键：`(source, trade_date, fetched_at)`，只追加。
- 结论在查询时计算（见第七节）。

### 5.4 `daily_bars`：日线（原始价）

| 字段 | 类型 | 单位或说明 |
|---|---|---|
| code、exchange、kind | VARCHAR | |
| trade_date | DATE | |
| open、high、low、close、pre_close | DOUBLE | 元 |
| volume_raw | DOUBLE | 原始值 |
| volume_raw_unit | VARCHAR | `SHARE` 或 `LOT` |
| volume_shares | DOUBLE | 股 |
| amount_raw | DOUBLE | 原始值，可空（腾讯日线没有成交额） |
| amount_raw_unit | VARCHAR | `CNY`、`TEN_THOUSAND_CNY` |
| amount_cny | DOUBLE | 元 |
| pct_chg | DOUBLE | % |
| pct_chg_computed | BOOLEAN | 数据源没给、由收盘价计算时为真 |
| turnover_pct | DOUBLE | %，可空 |
| completeness | VARCHAR | `COMPLETE`；缺成交额等时为 `PARTIAL`，并在 `missing_fields` 列出 |
| missing_fields | VARCHAR[] | |
| source、fetched_at、batch_id | | `batch_id` 关联同步批次 |

- 主键：`(kind, code, exchange, trade_date, source)`。同一天允许保存多个源的记录，用于交叉校验；查询时只选一个源（第六节）。
- 停牌日没有记录，不插值。baostock 对停牌股票也返回一行（交易状态为 0），这一行只写入 `daily_status`，不写入日线表。
- **单位自检**：有成交额时，成交额 ÷ 成交量 得到的成交均价必须落在当日最低价与最高价之间（允许 2% 偏差），否则视为单位错误，该行不写库并记入健康台账。起因是 S1 验证时发现腾讯对科创板按股、对其他板块按手计量（实测记录 2.1）。腾讯日线没有成交额，无法自检，只能依靠按板块的单位规则，并在联网测试中与 baostock 交叉校验。
- 同一源对同一天再次返回**不同**的值时，不覆盖原记录，写入 `data_conflicts`，同步批次标为部分完成。

### 5.5 `adj_factor_events`：复权因子事件

| 字段 | 类型 | 说明 |
|---|---|---|
| code、exchange、kind | VARCHAR | |
| ex_date | DATE | 除权除息日（baostock `dividOperateDate`） |
| back_factor | DOUBLE | 后复权因子（以上市为基准，不随新事件变化） |
| fore_factor_at_fetch | DOUBLE | 抓取时的前复权因子，只做审计，不参与计算 |
| source、fetched_at | | |

主键：`(kind, code, exchange, ex_date, source)`。

**复权价计算**（只用后复权因子）：
- 设 `B(t)` 为除权日不晚于 `t` 的最近一次事件的后复权因子；若 `t` 之前没有任何事件，`B(t) = 1`。这要求必须从上市日起完整抓取事件，否则该证券的复权价不可用。
- 后复权价：`P_hfq(t) = P_raw(t) × B(t)`。
- **以决策时点 `T` 为基准的前复权价**：`P_qfq(t | T) = P_raw(t) × B(t) / B(T)`。

这样回测时站在 `T` 看到的前复权序列，只包含 `T` 之前发生的除权。数据源给的前复权序列都以"今天"为基准，含有 `T` 之后的除权信息，用于回测会泄漏未来数据。

### 5.6 `daily_status`：每日交易状态

| 字段 | 类型 | 说明 |
|---|---|---|
| code、exchange、kind、trade_date | | |
| is_suspended | BOOLEAN | 来自 baostock `tradestatus`；可空 |
| is_st | BOOLEAN | 来自 baostock `isST`；可空 |
| limit_up / limit_down | DOUBLE | 仅当日实测（腾讯第 47、48 位）；历史留空 |
| limit_source | VARCHAR | `OBSERVED`；第 2 步加入 `COMPUTED` |
| source、fetched_at | | |

主键：`(kind, code, exchange, trade_date, source)`。

### 5.7 `risk_warning_lists`：风险警示名单（每周）

| 字段 | 类型 | 说明 |
|---|---|---|
| list_date | DATE | 名单的 `updateDate` |
| category | VARCHAR | `ST`、`STAR_ST`（即 \*ST） |
| code、exchange | | |
| name | VARCHAR | |
| source、fetched_at | | |

主键：`(list_date, category, code, exchange, source)`。用途：与每日 `is_st` 交叉校验；名单中有、日线标记为否时记为冲突。

### 5.8 `snapshot_runs` 与 `snapshot_rows`：全市场快照及存档

`snapshot_runs`：

| 字段 | 说明 |
|---|---|
| snapshot_id | 主键 |
| kind | `STOCK`、`ETF` |
| source、fetched_at | |
| status | `COMPLETE`、`PARTIAL` |
| expected_rows / rows | 预期数量 / 实际数量 |
| details | JSON |

`snapshot_rows`：snapshot_id、code、exchange、kind、name、price、pre_close、open、high、low、pct_chg、volume_shares、amount_cny、turnover_pct、pe、pb、total_mcap_cny、float_mcap_cny、limit_up、limit_down、quote_time，以及 `missing_fields`。

- 最新价为 0 或缺失记为"无有效报价"，`price` 为空，不当作 0。
- 每次抓取的快照都保存，从而**从今天起积累自己的历史快照**（名称、ST、市值、市盈率等可按时点回查）。

### 5.9 `sync_audits`：同步审计

| 字段 | 说明 |
|---|---|
| dataset | `daily_bars`、`daily_status`、`adj_factors`、`calendar`、`instruments` |
| trade_date | |
| batch_id | |
| expected / observed / known_suspended | 预期证券数 / 实际得到数 / 已知停牌数 |
| coverage | `observed / (expected − known_suspended)` |
| status | `COMPLETE`、`PARTIAL`、`FAILED` |
| details | JSON：各源结果、失败原因、冲突数 |
| recorded_at | |

- 主键：`(dataset, trade_date, batch_id)`，只追加。
- 某交易日最新一条审计为 `COMPLETE`，才视为已完成；否则下次同步重试。

### 5.10 `source_health_events`：健康台账（只追加）

字段：event_id（主键）、event_at、level（`REQUEST` 一次请求含每次重试 / `FETCH` 一次完整采集）、family、source、data_category、operation、code、target_date、status、error_category、attempt、http_status、row_count、elapsed_ms、detail、raw_id。

- `elapsed_ms` 从限速器放行、实际发出请求时算起，**不含在本机排队等待的时间**，反映的是数据源本身的响应速度。
- 写入路径：传输层把事件逐行追加到本进程的事件文件 `data/<模式>/runtime/events/<日期>-<进程号>.jsonl`（每行立即落盘），再由 `ledger.ingest_events` 增量导入本表。这样请求不会因为等待数据库锁而卡住（DuckDB 同一时间只允许一个进程写入）。导入按文件字节偏移续读、按 event_id 去重，可以重复调用。

### 5.11 `raw_responses`：原始响应索引

字段：raw_id（主键）、source、family、url（不含敏感参数）、fetched_at、http_status、byte_size、sha256、path。与健康台账走同一条写入路径。

> 列名避开了 DuckDB 的保留字：`at` → `event_at`，`rows` → `row_count`，`bytes` → `byte_size`。

文件存于 `data/raw/<接口族>/<YYYYMMDD>/<raw_id>.gz`。baostock 不是 HTTP，存的是解析前的逐行结果（CSV 压缩），并在 `source` 中注明。

### 5.12 `data_conflicts`：数据冲突

字段：conflict_id（主键）、detected_at、table_name、key_json、existing_json、incoming_json、existing_source、incoming_source、kind（`SAME_SOURCE_REVISION`、`CROSS_SOURCE_MISMATCH`）、resolved（BOOLEAN）、signature（迁移 2 加入）。

- 去重：`signature` 由表名、键和新值中参与比较的列算出（不含抓取时间、批次号）。同一个未处理的冲突只记录一次，重复同步不会产生重复的冲突记录；数据源再次改成另一个值，才算新的冲突。

### 5.13 `event_ingest_offsets`：事件文件导入进度

字段：file_name（主键）、byte_offset、updated_at。与导入的数据在同一事务中提交。

### 5.14 表结构的声明与冲突比较

- 每张表在 `schema.py` 中用 `TableSpec` 声明列、主键和写入方式，描述的是全部迁移执行后的**当前结构**。
- 迁移历史在 `migrations.py`，以固定的 SQL 语句保存。最初版本曾由表声明动态生成建表语句，2026-10-26 发现这样一改声明就会改动已发布的迁移，已改为固定语句。
- `UPSERT` 表声明"比较列"：同一键再次写入时只比较这些列，抓取时间、批次号等元数据不参与比较。例如复权因子表只比较后复权因子，因为前复权因子本来就会随新的除权整体变化。
- `APPEND` 表只追加，主键重复的行忽略。
- 已发布的迁移由测试固定其内容哈希；表结构变化一律新增迁移，不修改已发布的迁移。另有测试检查建库后的实际列与声明一致，并验证只执行过迁移 1 的旧库能升级而不丢数据。

---

## 六、数据源优先级

依据见实测记录。【待复测】的源暂不排入。

| 数据类别 | 主源 | 后备 | 理由 |
|---|---|---|---|
| 交易日历 | baostock `query_trade_dates` | 新浪（akshare） | baostock 对每个自然日都给出明确标记；新浪只列开市日。两源独立，同步时交叉校验 |
| 证券名单与上市状态 | baostock `query_stock_basic` | 新浪快照（只有在市证券） | baostock 含已退市证券和退市日期，可缓解幸存者偏差 |
| 日线·历史回补 | baostock 逐只 `query_history_k_data_plus` | 腾讯 `fqkline` | baostock 字段完整（成交额、交易状态、是否 ST）；腾讯没有成交额，结果标为 `PARTIAL` |
| 日线·每日增量 | baostock 按日期全量 `query_daily_history_k_AStock` | 腾讯收盘后批量报价 | baostock 一次取全市场（实测 23 秒）；发布时间【待复测】。腾讯批量报价在 15:30 后抓取，含开高低收、成交量、成交额、昨收，缺交易状态 |
| 指数、ETF 日线 | baostock 逐只 | 腾讯 `fqkline` | 只采集配置清单中的少量指数和 ETF；ETF 全量接口实测 507 秒，不用 |
| 复权因子 | baostock `query_adjust_factor`（回补）、`query_daily_adjust_factor`（增量） | 无 | 腾讯日线里的分红信息用于交叉校验，不单独计算因子 |
| 停牌、ST（每日） | baostock 日线的 `tradestatus`、`isST` | 无 | 实测与 2015-07-08 的历史事件相符 |
| 风险警示名单（每周） | baostock `sectorinfo.query_st_stocks`、`query_starst_stocks` | 无 | 只做交叉校验 |
| 当日涨跌停价 | 腾讯报价第 47、48 位 | 无 | 新浪快照没有涨跌停价 |
| 全市场快照·股票 | 腾讯批量报价 | 新浪分页快照 | 腾讯单次 300 只、约 19 次请求拉完，带涨跌停价和市值，基本不封 IP；新浪约 56 页，无涨跌停价 |
| 全市场快照·ETF | 腾讯批量报价 | 新浪分页（节点【需核实】） | |
| 实时报价 | 腾讯 | 新浪 | |

查询时的选源规则：
- 库里同一证券同一天有多个源的记录时，按上表优先级选**一个源**，且这个源必须覆盖整个请求区间；没有任何单个源能覆盖时，按"覆盖不全"失败，不拼接。
- 快照所需的代码清单来自 `instruments` 中当前在市的证券。清单为空或过期（超过配置的天数）时，先同步名单；同步失败则快照失败。

---

## 七、可见时间、定型与存储规则

### 7.1 可见时间（决策时点过滤的依据）

| 数据 | 可见时间 |
|---|---|
| 某日日线、交易状态 | 当日 15:00 |
| 复权因子事件 | 除权除息日开盘（即日期等于除权日即可用） |
| 风险警示名单 | 名单 `updateDate` 当天 |
| 证券版本 | `valid_from` |
| 快照、实时报价 | 抓取时间 |
| 交易日历 | 不按时点过滤，但"未来日期"有新鲜度要求（7.3） |

- 每个查询方法都带 `as_of`（决策时点），只返回可见时间不晚于它的数据。
- 只给日期时，视为当日 15:00 之后（遵循采集需求的定义）。
- 例：`as_of` 为某日 10:00 时，最新的日线是前一个交易日的。

### 7.2 定型规则

- 某日日线在**当日 15:30** 之后抓取才算定型（`finalize_after`，可配置）。之所以比 15:00 晚半小时：科创板、创业板有 15:05–15:30 的盘后固定价格交易。部分数据源是否把这部分成交计入当日，【需核实】，晚一点定型更安全。
- 未定型的数据**不写入日线表**，只返回给调用方，并在结果里标明"未定型"。
- 快照不受定型限制，它本身就是带抓取时间的存档。

### 7.3 交易日历的结论

- 过去的日期：只要某个源的观测覆盖了这一天，就有结论；两个源都有观测且结论不同时，记为"冲突"，结论为"未核实"，并写入冲突表和健康台账。
- 当日及以前的已核实结论永久有效。
- **未来日期**：要求观测是最近 24 小时内抓取的（`calendar_future_max_age`），否则重新抓取，抓不到就是"未核实"。
- 查询下一个交易日时，窗口逐级扩大：14 天、45 天、370 天。
- 任何情况下都不按周一至周五推断。

### 7.4 "缓存"即数据库

- 读取顺序：库里已定型、覆盖请求区间的数据 → 缺的部分走路由抓取 → 定型的写库 → 返回。
- 快照：默认必须实时抓取；只有调用方传入 `allow_cache=True`，才可以返回库里的存档，并标注"存档"和存档时间。
- 历史决策时点的快照：返回存档中抓取时间不晚于 `as_of` 的最近一次快照，并标注其抓取时间；没有这样的存档时，返回明确的"无历史版本"。
- 快照接口的说明里注明：只含当时在市的证券，存在幸存者偏差。

---

## 八、失败语义

### 8.1 返回结果

```python
DataResult(
    status,       # OK（有数据）或 EMPTY（成功但确实没有数据）
    records,      # 标准化记录
    source,       # 实际使用的数据源
    fetched_at,   # 数据的抓取时间
    from_store,   # 是否来自数据库
    flags,        # 例如 ARCHIVED（存档）、UNFINALIZED（未定型）、PARTIAL（字段不全）
    attempts,     # 每个源的尝试：源、结果、错误类别、耗时
    gaps,         # 缺口：缺什么、为什么
)
```

- **所有源都失败时抛出 `DataUnavailable`**，其中带有每个源的尝试记录。不用返回状态表示失败，防止调用方忘记检查。
- 交易日历是例外：按采集需求的要求返回 `(is_open, verified, source, reason)`；无法核实时 `verified=False`，不抛异常。依赖交易日的调用方必须检查 `verified`。
- 执行价格这类关键数据不可用时，一律抛异常，不返回默认值。

### 8.2 错误类别

| 类别 | 例子 | 是否重试 | 计入断路器 |
|---|---|---|---|
| `TIMEOUT` | 读取超时 | 有限次 | 是 |
| `NETWORK` / `DNS` / `CONNECTION_RESET` | 连接失败 | 有限次 | 是 |
| `RATE_LIMITED` | HTTP 429 | 有限次，退避 | 是 |
| `HTTP_ERROR` | 5xx | 有限次 | 是 |
| `BLOCKED` | 403、456、验证码；东方财富的"直接断开连接" | **否** | 是 |
| `SESSION_LOST` | baostock `10002xxx`、`10001001` | 重新登录后重试一次 | 是 |
| `PARSE_ERROR` / `SCHEMA_CHANGED` | 字段数不对、JSON 结构变化 | 否 | 是 |
| `ENCODING` | 解码后出现替换字符 | 否 | 是 |
| `SILENT_EMPTY` | 响应成功，但缺少数据字段（如腾讯 `data` 里没有 `day`） | 否 | 是 |
| `TRUNCATED` / `COVERAGE_GAP` | 返回范围未覆盖请求范围 | 否，换下一个源 | 否 |
| `SOURCE_ERROR` | 数据源返回的业务错误（如腾讯 `msg="param error"`） | 否 | 否 |
| `COOLDOWN` | 断路器冷却中，未发请求 | — | — |
| `DISABLED` | 接口族在配置中停用，未发请求 | — | 否 |
| `BUSY` | 等待本机其他线程或进程的请求超时；或 baostock 上一次超时的调用仍占着会话 | 否 | 否（不是数据源的问题） |
| `CONFLICT` | 交叉校验不一致 | — | — |

断路器按"一次完整请求"计数：一个请求重试多次后最终失败，只算一次失败。

---

## 九、传输层

### 9.1 接口族与默认参数

| 接口族 | 最小间隔 | 随机抖动 | 超时 | 重试次数 | 断路器阈值 / 冷却 | 风控信号冷却 | 跨进程串行 |
|---|---|---|---|---|---|---|---|
| tencent | 0.5 秒 | 0.1–0.4 秒 | 10 秒 | 2 | 3 次 / 30 分钟 | 30 分钟 | 否 |
| sina | 1.0 秒 | 0.1–0.4 秒 | 10 秒 | 2 | 3 次 / 30 分钟 | 30 分钟 | 否 |
| baostock | 0.3 秒 | 无 | 120 秒（全量 600 秒） | 1（重新登录后） | 3 次 / 30 分钟 | 12 小时 | 是（每个进程一个会话） |
| eastmoney（复测后启用） | 1.5 秒 | 0.1–0.5 秒 | 15 秒 | 2（403 和断开连接不重试） | 2 次 / 6 小时 | 6 小时 | 是 |

### 9.2 规则

1. 每个 HTTP 接口族一个长连接会话；`trust_env=False`，不读取系统代理；代理按接口族配置，默认不走代理。User-Agent 来自配置。
2. 每次请求依次经过：接口族是否启用 → 断路器 → 限速 → 发送 → 分类与重试 → 存档 → 健康台账。
3. 状态码规则来自配置 `[http]`：`blocked_status_codes`（默认 403、456）视为风控信号，不重试；`retryable_status_codes`（默认 429、5xx）可重试；其他 4xx 不重试。重试前等待 `backoff_base_s × 2^(n-1)` 秒，上限 `backoff_max_s`。
4. 服务器不回应直接断开连接：`disconnect_means_blocked` 为真的接口族（东方财富）视为 `BLOCKED`，不重试；其他接口族视为 `CONNECTION_RESET`，可重试。
5. 限速：同一接口族的请求串行，上一次结束到下一次开始至少间隔 `min_interval_s`，再加 `jitter_s` 范围内的随机抖动；`cross_process_serial` 为真时，用文件锁和共享的"上次结束时间"让多个进程也满足这一间隔，最多等待 `cross_process_wait_s`（必须大于该接口族的最长超时）。
6. 断路器状态存于 `data/<模式>/runtime/breakers/<接口族>.json`，多进程共享；读改写在文件锁内完成，写入时先写临时文件再替换。**状态文件读不出来或已损坏时按"冷却中"处理，并重写为一个新的冷却期**，到期后可自动恢复，不默认放行（这是 wm 的缺陷）。
7. 冷却期间不发任何请求，直接返回 `COOLDOWN`，并给出冷却截止时间。冷却结束后进入"试探"：试探成功即恢复正常计数，试探失败立即再次冷却，不再等满阈值。一次成功即清零计数。
8. **风控信号（`BLOCKED`）立即冷却**，不等满阈值，冷却时长为该接口族的 `blocked_cooldown_s`；如果已经处在更长的冷却中，不会被缩短。理由：封禁期间继续请求只会让封禁延长（wm 东方财富"滑动封禁"、baostock 拉黑的教训）。
9. 每次请求（含每次重试）写一条健康台账；HTTP 响应体（包括失败的响应）压缩存档并记录哈希；存档索引中的 URL 隐去 `redact_query_keys` 所列参数的值。
10. 解码：调用方声明编码（腾讯报价、新浪为 GBK，腾讯日线为 UTF-8），统计替换字符数，大于 0 即 `ENCODING` 失败，不重试。
11. 第三方库（akshare）的调用经过 `LibraryGuard`：与同一接口族的 HTTP 请求共用断路器和限速器；调用在后台线程中限时执行；库内部的 requests 异常按上述规则分类；返回内容不是 JSON（例如风控时的 HTML 验证页）以及其他异常（如 KeyError）视为 `PARSE_ERROR`。
12. **baostock 会话管理器**（实测行为见实测记录 4.1、4.2）：
    - 每个进程一个会话，按需登录；"是否已登录""是否有卡住的线程"按进程共享，同一进程里有几个客户端都不会在同一个会话上并发调用；
    - 登录或查询返回拉黑码 `10001011` 时报 `BLOCKED`：不重试，断路器立即冷却 12 小时；
    - 遇到 `10001001` 或 `10002xxx` 时重新登录，并按 `retries` 重试；
    - 查询函数返回 `None`（参数不合法）时报 `SOURCE_ERROR`，不重试，不计入断路器；其他错误码同样报 `SOURCE_ERROR`；
    - 用 `rs.next()` 逐行读取，不用 `rs.get_data()`；只依据错误码判断，不依赖 `error_msg`；
    - 超时保护：调用在后台线程中限时执行。超时即报 `TIMEOUT`（计入断路器）并视会话失效；超时的线程无法强行终止，在它结束之前，本进程内的 baostock 调用一律报 `BUSY`，避免两个线程同时使用同一个会话；它结束后重新登录即可恢复。已用测试验证。
    - 查询结果以 CSV 压缩存档（baostock 不是 HTTP，存的是逐行结果）。

---

## 十、存储与并发

依据：实测记录第八节。DuckDB 同一时间要么一个进程读写，要么多个进程只读。

1. 1a 使用一个数据库文件，按运行模式隔离：真实模式为 `data/real/market.duckdb`，测试模式为 `data/test/market.duckdb`；原始响应存档、断路器状态、锁文件也都放在对应模式的目录下。
2. **进程内**：同一数据库的所有读写都经过同一把锁串行执行，同一时刻只有一个连接。这样避免 wm 在 Windows 上遇到的"多线程并发访问 DuckDB 导致原生崩溃"。连接设置为北京时区，并禁止运行时联网下载扩展（ICU、JSON 扩展已内置，已核实离线可用）。
3. **跨进程**：
   - 写入方先获取文件锁 `data/runtime/market.duckdb.lock`，再以读写方式打开数据库；
   - 长任务（如历史回补）**按批提交**：每批（一只股票或一个交易日）写完就关闭连接、释放锁，让其他进程有机会读取；
   - 读取方同样先获取这把文件锁，再以只读方式打开；等待超过 `store_lock_timeout_s`（默认 30 秒）报 `StoreLocked`。读取也取独占锁是为了简单可靠：读取都很短，串行的代价可以接受。
   - 文件锁使用 `filelock` 库（需新增依赖），它同时支持 Windows 和 Linux。
4. 写入是幂等的：键已存在且值相同则跳过；值不同则写冲突表，不覆盖。
5. 迁移：按版本号顺序执行，已执行的跳过；每个迁移在一个事务内完成。
6. 网络请求、解析这类慢操作不在持锁期间进行：先抓取、解析完，再获取锁写入。
7. 同一线程内嵌套使用数据库（例如写事务中又调用读取）直接报出明确的错误，外层事务回滚；写事务中需要查询时用 `batch.execute`。
8. 进程崩溃：提交后、关闭前被杀会留下 WAL，读写双方都能正确处理；提交前被杀，未提交的写入不可见，持有的文件锁由系统释放。两种情况都有测试。wm 记录的 DuckDB 1.5.5 "WAL 恢复后检查点遗漏索引条目"缺陷在 2.0.0 上未能复现，只记录不防御（实测记录 8.1）。

---

## 十一、统一数据接口

```python
class MarketData:
    # 交易日历
    def trading_day(self, day: date) -> CalendarAnswer: ...          # is_open, verified, source, reason
    def previous_trading_day(self, day: date) -> CalendarAnswer: ...
    def next_trading_day(self, day: date) -> CalendarAnswer: ...
    def last_completed_trading_day(self, as_of: datetime) -> CalendarAnswer: ...

    # 证券
    def instruments(self, as_of, kinds=(STOCK,), boards=None, include_delisted=False) -> DataResult: ...

    # 日线与复权
    def daily_bars(self, security, start, end, adjust=Adjust.NONE, as_of=None) -> DataResult: ...
    def adjustment_events(self, security, as_of=None) -> DataResult: ...

    # 交易状态
    def daily_status(self, day, as_of=None, securities=None) -> DataResult: ...
    def risk_warning_list(self, as_of) -> DataResult: ...

    # 快照与报价
    def market_snapshot(self, kind=STOCK, as_of=None, allow_cache=False) -> DataResult: ...
    def quotes(self, securities) -> DataResult: ...                  # 只支持当前时刻

    # 健康
    def source_health(self, hours=24) -> HealthSummary: ...
```

- `adjust` 取 `NONE`、`QFQ`、`HFQ`。`QFQ` 以 `as_of` 为基准（5.5），`as_of` 为空时以当前时刻为基准。
- `as_of` 为空表示"现在"。
- 同步任务（`sync.py`）与命令行：

| 命令 | 作用 |
|---|---|
| `stocktrader data sync-calendar --year 2026` | 同步交易日历并交叉校验 |
| `stocktrader data sync-instruments` | 同步证券名单与版本 |
| `stocktrader data backfill --start 2015-01-01 [--codes ...]` | 历史回补（日线、复权因子、交易状态），可中断、可续跑 |
| `stocktrader data sync-daily --date 2026-10-26` | 某个交易日的增量同步与审计 |
| `stocktrader data sync-risk-warning` | 同步当周风险警示名单 |
| `stocktrader data snapshot --kind stock` | 抓取并存档一次全市场快照 |
| `stocktrader data health --hours 24` | 各数据源成功率与最近失败 |
| `stocktrader data audit --start ... --end ...` | 查看同步审计 |

---

## 十二、配置项

所有可调数值只写在配置文件 `config/data.toml` 里（上传 git，每项附说明）；`config.py` 只用 pydantic 声明类型和取值范围，**不提供默认值**。配置文件缺失、缺项或越界时，加载即报错，不会悄悄改用某个值。换用其他配置文件（例如测试）时，由环境变量 `STOCKTRADER_DATA_CONFIG` 指定路径；相对路径以项目根目录为基准。

规则和事实不属于配置，以常量形式留在代码中并配有测试：证券代码规则表、交易时段、"1 手 = 100 股"等单位定义。

下表的"默认值"即 `config/data.toml` 中的初始取值。

| 配置项 | 默认值 | 取值范围 | 说明 |
|---|---|---|---|
| `data_dir` | `data` | 路径 | |
| `mode` | `real` | `real`、`test` | 两种模式使用不同的目录：`data/<模式>/`，数据库为其中的 `market.duckdb` |
| `finalize_after` | 15:30 | 15:00–23:59 | 日线定型时刻 |
| `calendar_future_max_age_hours` | 24 | 1–168 | 未来日期结论的最长有效时间 |
| `calendar_next_windows_days` | [14, 45, 370] | 递增正整数 | |
| `backfill_start` | 2015-01-01 | 不早于 1990-12-19 | 【待确认】 |
| `include_delisted` | true | 布尔 | 回补时包含已退市股票 |
| `boards` | MAIN、CHINEXT、STAR | 子集 | 采集范围 |
| `reference_indices` | 000300.SH、000001.SH、399001.SZ、399006.SZ、000905.SH、000852.SH、000688.SH | 代码列表 | 【待确认】 |
| `reference_etfs` | 510300.SH、510500.SH、159915.SZ、588000.SH | 代码列表 | 【待确认】 |
| `snapshot_batch_size` | 200 | 1–300 | 腾讯批量报价单次代码数（实测 300 可用） |
| `instruments_max_age_days` | 7 | 1–30 | 快照所用代码清单的最长有效期 |
| `coverage_threshold` | 0.98 | 0.5–1.0 | 每日同步覆盖率达到多少才算完成 |
| `implied_price_tolerance` | 0.02 | 0–0.2 | 成交均价允许超出当日最低价、最高价的比例（单位自检） |
| `http.user_agent` | Chrome 130 的 UA | 非空 | 所有 HTTP 请求的 User-Agent |
| `http.retryable_status_codes` | 429、500、502、503、504 | 400–599 | 可有限次重试的状态码 |
| `http.blocked_status_codes` | 403、456 | 400–599，不得与上一项重叠 | 风控信号，不重试 |
| `http.backoff_base_s` / `http.backoff_max_s` | 1.0 / 8.0 | 0–60 / ≥ base | 重试等待 |
| `http.redact_query_keys` | token、apikey、api_key、key | 字符串列表 | 写入台账和存档索引时隐去的参数 |
| `families.<接口族>.*` | 见 9.1 | 间隔 ≥ 0、阈值 ≥ 1、冷却 ≥ 60 秒 | 限速、超时、重试、断路器 |
| `families.<接口族>.blocked_cooldown_s` | 腾讯、新浪 1800；baostock 43200；东方财富 21600 | 60 秒到 7 天 | 收到风控信号时立即冷却的秒数 |
| `families.<接口族>.cross_process_wait_s` | 腾讯、新浪 60；baostock 900；东方财富 120 | 大于该接口族最长超时 | 跨进程串行时最多等待其他进程的秒数 |
| `families.<接口族>.disconnect_means_blocked` | 东方财富为真，其余为假 | 布尔 | 直接断开连接是否视为风控信号 |
| `families.<接口族>.proxy` | 无 | URL | |
| `store_lock_timeout_seconds` | 30 | 1–600 | |
| `raw_archive` | true | 布尔 | 是否存档原始响应 |
| `raw_archive_retention_days` | 0（永久） | ≥ 0 | |

---

## 十三、测试计划

### 13.1 逻辑测试（默认运行，不联网）

| 对象 | 测什么 |
|---|---|
| 规则表与规范化 | 表中每个前缀；各种输入写法；裸代码缺少品种时报错；交易所与规则不一致时报错；未知前缀拒绝；各源代码写法转换 |
| 时钟与定型 | 北京时间与主机时区无关；15:30 前后的定型判断；`as_of` 只给日期时视为 15:00 之后 |
| 交易日历 | 两源一致、冲突、单源覆盖；新浪"不在列表即休市"仅在覆盖范围内成立；未来日期新鲜度；窗口逐级扩大；全部失败返回"未核实" |
| 单位换算 | 手→股、万元→元、亿元→元；新浪指数成交量按手；腾讯科创板成交量按股；腾讯日线缺成交额时标 `PARTIAL`；成交均价单位自检 |
| 复权计算 | 以 `as_of` 为基准的前复权；`as_of` 之后的除权不影响结果；缺少上市以来事件时报不可用；与手算样例一致 |
| 解析 | 用实测录下的真实响应（`tests/fixtures/`）测试解析逻辑：腾讯 88 字段、日线 7 列分红行、`param error`、缺少 `day` 字段、新浪 403、baostock 错误码 |
| 断路器与限速 | 达到阈值进入冷却；冷却期间零请求；成功清零；状态文件损坏按冷却处理；多线程下实际间隔不小于设定值 |
| 路由 | 用假适配器：失败换源、冷却跳过、覆盖不全换源、不拼接、复权方式严格匹配、全部失败抛 `DataUnavailable` 且含每源原因 |
| 存储 | 迁移幂等；重复写入不产生重复行；同源不同值写冲突表；跨进程锁（子进程测试）；按批提交后其他进程可读 |
| 决策时点 | 每个查询方法在历史 `as_of` 下不返回之后才可见的数据 |
| 健康台账 | 每次成功和失败都有记录；只追加 |

解析测试用的是真实响应录像，只证明"我们的解析逻辑对这些输入是对的"。采集是否正确，只由联网测试证明。

测试的真实性约定（S2、S3 起执行）：
- 传输层测试使用真实的本地 HTTP 服务器（`tests/data/conftest.py`）复现实测中出现过的数据源行为：GBK 报价、403、429 后恢复、5xx、超时、直接断开连接、GBK 乱码、缺少 Referer；走真实的 requests 和套接字，不对请求打桩。
- 限速、断路器、存储的并发测试使用真实线程和真实子进程（`tests/data/helpers/proc_worker.py`）。
- 存储测试使用真实的 DuckDB 文件。
- baostock 是私有 TCP 协议，离线测试用按实测行为编写的替身（错误码、返回 `None` 等全部取自实测记录），同类场景另有联网测试在真实 baostock 上验证（包括真实登出后自动重新登录）。
- 分层约束测试（`tests/data/test_architecture.py`）检查 import 关系：传输层不依赖存储层，存储层不依赖传输层，只有 runtime 负责组装，数据层不依赖 AgentScope 与 ReMe。

### 13.2 联网测试（`pytest -m live`，默认不运行）

- 每个适配器：字段齐全、单位合理、编码无替换字符；
- 交叉校验：同一天腾讯、新浪、baostock 的收盘价和成交量一致；
- 交易日历：已知节假日和交易日判断正确；
- 快照：股票数量超过 5000；停牌股票没有价格；
- baostock 会话失效后重新登录可恢复。

---

## 十四、验收清单

1. 交易日历：2026-10-01 判断为休市、2026-10-23 判断为开市，并标明来源；所有日历源都不可用时返回"未核实"。
2. 日线：茅台（股票）、沪深 300（指数，`000300.SH`）、沪深 300 ETF（`510300.SH`）近一年的原始价和前复权价，字段齐全、来源已标注；不同品种互相隔离。
3. 定型：盘中请求包含当天的窗口时，当天数据不写库；15:30 后请求则写库，再次请求从库中读取。
4. 快照：返回 5000 只以上股票；停牌股票没有价格；主源处于冷却期时自动切换到后备源，并在来源中体现；所有源都失败时报错，不返回存档。
5. 限速：多线程并发请求同一接口族时，实际间隔不小于设定值。
6. 健康台账：每一次成功和失败都能查到。
7. 决策时点：给定历史决策时点，任何接口都不返回之后才可见的数据，包括前复权价。
8. 回补可中断、可续跑，不产生重复数据；每个交易日都有审计记录。
9. 交叉校验报告：抽样日期上 baostock 与腾讯的收盘价一致。

---

## 十五、实现步骤

每一步都能独立运行、带测试，完成后向你报告测试结果再进入下一步。

| 步骤 | 内容 | 新增依赖 |
|---|---|---|
| S1 | 骨架：目录结构、配置、时钟、证券标识与规则表、数据模型、错误类型；pytest 框架 | pytest（开发依赖） |
| S2 | 传输层：HTTP 会话、限速、重试、断路器、解码校验、原始响应存档；baostock 会话管理器；健康台账 | |
| S3 | 存储：建表与迁移、单写入通道、跨进程锁、幂等写入与冲突检测 | filelock |
| S4 | 交易日历：baostock、新浪适配器，交叉校验，日历查询方法，`sync-calendar` | |
| S5 | 证券名单与版本、风险警示名单，`sync-instruments`、`sync-risk-warning` | |
| S6 | 日线、复权因子、交易状态：baostock、腾讯适配器，复权计算，`backfill`、`sync-daily`，同步审计 | |
| S7 | 全市场快照与存档、实时报价：腾讯、新浪适配器，`snapshot` | |
| S8 | 统一接口收口、联网测试、按验收清单验收，补充实测记录 | |

东方财富、mootdx 适配器在复测通过后插入，不改变上述结构。

### 15.1 进度

| 步骤 | 状态 | 测试 |
|---|---|---|
| S1 | 完成（2026-10-25） | 逻辑测试；验证脚本 `scripts/stage_checks/s1/`：规则表核对 baostock 全量 7878 只证券 0 失败，腾讯成交量单位按板块核对通过 |
| S2 | 完成（2026-10-25） | 逻辑测试（本地 HTTP 服务器、真实子进程）；联网测试 7 项通过；验证脚本 `scripts/stage_checks/s2/`：全市场 5224 只股票分 27 批请求腾讯报价，0 失败、0 缺失，相邻请求实际间隔 0.601–0.891 秒（配置 0.5 秒加 0.1–0.4 秒抖动） |
| S3 | 完成（2026-10-25） | 逻辑测试（真实 DuckDB、真实子进程）；联网全链路测试 1 项通过；验证脚本 `scripts/stage_checks/s3/`：5224 只 × 243 个交易日共 126.9 万行，每批写入 0.14–0.17 秒且不随表增大而变慢，满表时重复写入与冲突检测均约 0.09 秒，读取单只股票全年 0.031 秒、一天截面 0.078 秒；按 2015 年至今推算数据库约 2.8 GB |

---

## 十六、待确认与待复测

### 16.1 决策记录（2026-10-25）

| 事项 | 结论 |
|---|---|
| 范围 | 按第一节执行 |
| 回补起点 | 2015-01-01，含期间退市的股票。粗略估计首次回补需要几个小时：按 baostock 逐只请求的实测耗时（0.3–7.6 秒不等）推算，约 5600 只股票加少量指数和 ETF，可中断续跑 |
| 代理 | 不走代理（见第二节第 12 条） |
| 脚本与测试的存放 | 见 3.2 |

仍未定：

1. **每日增量的时间**：取决于 baostock 当日数据的发布时间【待复测】。如果要到晚间才发布，当天的分析就安排在晚间；后备的腾讯收盘后报价 15:30 即可取到，但缺交易状态。
2. **参考指数和 ETF 清单**：先按第十二节的默认值实现，可以随时在配置里增减。

### 16.2 【待复测】（交易日进行）

1. mootdx 的日线和报价；
2. 东方财富（每个接口最多 3 个请求，累计 2 次失败即停）；
3. baostock 当日数据的发布时间；
4. 腾讯报价第 39 位市盈率的口径。

### 16.3 【需核实】（实现时查证）

1. 盘后固定价格交易的成交量是否计入各源的当日成交量；
2. baostock 超时保护机制（9.2 第 7 条）；
3. 新浪 ETF 快照所用的节点名。

### 15.2 2026-10-26 缺陷修复

| 缺陷 | 影响 | 修复 | 测试 |
|---|---|---|---|
| baostock 拉黑码 `10001011` 被当作普通业务错误 | 被拉黑期间仍会反复登录，使封禁延长 | 归为 `BLOCKED`，不重试，断路器立即冷却 12 小时（配置项 `blocked_cooldown_s`） | 登录被拉黑、查询被拉黑两个场景 |
| 风控信号要等满阈值才冷却 | 403 或封禁后还会继续请求 | `BLOCKED` 立即冷却，冷却时长按接口族配置，不缩短已有的更长冷却 | 传输层与断路器测试；新浪缺少 Referer 的联网测试 |
| 同一进程内多个 baostock 客户端各自记录会话状态 | 可能在同一个会话上并发调用 | 会话状态按 baostock 模块对象在进程内共享（弱引用，避免对象回收后状态被误继承） | 两个客户端共享会话的场景 |
| 风控时返回 HTML 验证页被归为 `HTTP_ERROR` | 错误分类不准 | 归为 `PARSE_ERROR` | 本地服务器返回 HTML 验证页 |
| 同一冲突在每次重复同步时被重复记录 | 冲突表膨胀、冲突计数失真 | 冲突按签名去重（迁移 2 增加 `signature` 列） | 连续三次同步同一修订只记一条 |
| 迁移语句由当前表声明动态生成 | 修改表声明会悄悄改动已发布的迁移 | 迁移历史改为固定语句（`migrations.py`），表声明只描述当前结构 | 迁移指纹、版本递增、旧库升级 |
| 同一线程内嵌套使用数据库报出难懂的底层错误 | 排查困难 | 直接报出明确错误并回滚外层事务 | 嵌套使用场景 |
| 未使用的常量 `RETRYABLE_CATEGORIES` | 无 | 删除 | — |

联网验证：全部 9 项联网测试通过（2026-10-26 21:25）。其中 baostock 相关的 4 项在当晚 baostock 服务端恢复后补跑（实测记录 4.2）。离线测试 241 项通过。
