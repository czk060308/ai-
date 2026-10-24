# 安心接力

把家庭照护需求变成有依据、可追踪的服务安排。

当前默认场景为“广州番禺临时助餐与取餐交接”：需求补问、官方历史资源筛选、人工供餐核实、取餐人接受、取餐交接、异常重排、反馈与脱敏统计。原复诊场景在`/?scene=care`继续保留。当前本机未鉴权，不自动预约、派单或付款。

10月24日新增：官方名单中的154条番禺资源（截至2025-02-05，非当前营业保证），后端104项、浏览器17项通过。用法、真实API合成验收与试点边界见[番禺助餐实施与验收](docs/番禺助餐场景_实施与验收_20261024.md)。当前真实试点成果为0，演示不混入试点统计。

10月23日晚最新整改：后端79项、浏览器11项通过。A02明确事实检查及有上限修正已实现；原三个真实输入与一个注入输入最终通过。新增7条公开资源资料及事务并发检查。详情见[整改记录](docs/A02整改与资源接入记录_20261023.md)，[此前验收报告](docs/A01-A10验收报告_20261023.md)保留首次漏提失败。

## 快速打开

在app目录打开PowerShell，运行：

```powershell
powershell -ExecutionPolicy Bypass -File .\start.ps1
```

浏览器访问 http://127.0.0.1:8000 。API与构建后的页面由一个进程提供，Ctrl+C停止；前端有修改时使用：

```powershell
powershell -ExecutionPolicy Bypass -File .\start.ps1 -Rebuild
```

脚本只监听127.0.0.1，不修改系统执行策略或全局Python设置。若8000端口已占用，先确认是否已有本项目服务运行，不重复启动。

## 首次安装与依赖锁定

已在当前电脑建立app/.venv并安装依赖。复现环境要求Python 3.11或以上、可用Node.js与npm、uv。安装时清除当前进程继承的旧Python路径，避免系统已有Python 3.8库污染虚拟环境：

```powershell
Remove-Item Env:PYTHONHOME,Env:PYTHONPATH -ErrorAction SilentlyContinue
uv venv --python 3.11 .venv
uv pip install --python .venv\Scripts\python.exe -r backend\requirements.lock.txt
uv pip install --python .venv\Scripts\python.exe --no-deps -e .\backend
Set-Location apps\web
npm.cmd ci
npm.cmd run build
```

前端依赖由package-lock.json锁定，后端依赖由backend/requirements.lock.txt锁定，项目本身由pyproject.toml安装。

## 演示流程

1. 初始输入为2026年10月24日的合成需求。点击“使用演示字段”，系统载入明确标记的内置字段，**不会调用大模型**。
2. 核对日期、预算等信息；展开“完善陪同、交通与午餐信息”可编辑地点、成员窗口、接受情况、时长及费用项目。
3. 点击“确认并生成草案”。后端检查约束并将草案写入SQLite；时间线、依据、规则结果与事件记录由真实接口返回。
4. 修改预算为100元，再生成；需求和草案版本随保存变化。刷新后仍读取数据库中的当前记录。
5. 在展开字段中将候选陪同人可用起点改为10:00，再生成，可看到与09:00前到院要求的冲突。
6. 点击“查询厦门公开资源”并重新生成，可看到5个公开报道中的真实助餐地点、1个官方查询入口和1份官方说明，均有来源与时效提示；当前价格、营业及本次可用性仍未知。填湖里区时只列同区地点和市级资料，共4条。
7. 原5条合成demo仍保留：地区填“演示片区”、开启“包含合成演示资源”后重新生成，资料均标为演示。

“手工填写”保存原文并提供空字段表单，不自动编造事实。“识别需求”才会尝试调用真实模型；未配置、超时或结构校验失败时原文仍会保存，页面提示失败并允许手工填写。

## 配置真实模型API

当前电脑已在2026年10月23日完成kimi-k2.6真实抽取首个样例验证；原配置kimi-k3在本账号返回无权限或不存在，MODEL_NAME已调整。详情见docs/真实模型接入验收.md。下面保留新环境的配置方法。

复制app/.env.example为app/.env，在本机编辑以下值，然后重启后端：

```dotenv
MODEL_BASE_URL=
MODEL_NAME=
MODEL_API_KEY=
MODEL_TIMEOUT_SECONDS=35
```

MODEL_BASE_URL填写供应商提供的兼容API基础地址，例如需要/v1的服务就包含/v1；后端追加/chat/completions。不要填写完整聊天端点两次。接口使用HTTP兼容协议，不假设具体供应商。模型应支持中文、JSON文本及此接口中的基本请求参数；不兼容时需调整网关适配。

密钥仅在后端读取，不写入前端或仓库。页面健康提示只表示配置项存在，不代表真实调用已经验证。真实API验收须在填写配置后，使用“识别需求”实际成功一次，并核对识别值及原文证据。

## 独立开发模式

两个终端分别运行：

```powershell
# 终端一，app目录
powershell -ExecutionPolicy Bypass -File .\dev-api.ps1
# 终端二，app目录
powershell -ExecutionPolicy Bypass -File .\dev-web.ps1
```

开发页面：http://127.0.0.1:5173 ，Vite代理/api到8000。API文档：http://127.0.0.1:8000/docs 。生产预览与开发模式不可同时争用8000端口。

## 检查命令

```powershell
# app目录
.\.venv\Scripts\python.exe -E -m pytest backend/tests -q
# apps/web目录
npm.cmd run build
# 启动8000服务后，在apps/web目录运行
npm.cmd run test:e2e
```

在app目录运行`./.venv/Scripts/python.exe -E -X utf8 scripts/verify_acceptance.py`可检查健康、独立进程重启和当前文件凭证。添加`--live`会真实执行三个合成输入的供应商验收，可能产生费用；每个输入最多两次供应商请求。脚本会保留失败结论，不把有字段遗漏的结果计为完整通过。

再加`--live-injection`可追加真实注入样例；`--live --case injection`只复测该样例。多例默认间隔22秒，账号仍可能触发429，网关不会因此自动重试。

Windows检测到已安装的Edge时，浏览器检查默认使用Edge；其他环境先执行npx.cmd playwright install chromium。可用ANXIN_BROWSER_CHANNEL环境变量显式指定msedge、chrome或chromium。浏览器检查会在当前数据库创建合成演示需求；后端单元和接口检查使用临时数据库。浏览器截图在app/runtime/screenshots，测试失败记录在apps/web/test-results。

## 代码结构

```text
app/
  apps/web/src/            React + TypeScript + Ant Design工作台
  apps/web/e2e/            浏览器流程检查
  backend/src/anxin/
    config.py             后端环境配置
    domain.py             需求Schema、缺项、演示字段
    model_gateway.py      真实兼容API、原文依据与错误处理
    planning.py           事项依赖、时段与预算规则
    storage.py            SQLAlchemy模型、SQLite事务与事件
    main.py               FastAPI接口与静态页面入口
  backend/tests/          字段、故障、版本与持久化检查
  data/seeds/             7条有来源的公开资料 + 5条明确标记的合成资料
  runtime/                本机数据库、截图，排除Git
```

## 数据与接口约定

SQLite默认存放app/runtime/anxin.db，启用WAL。Need、Resource、PlanDraft、Event分别保存需求、资源、草案及真实操作记录。未知值保存为null，不当作零或条件通过。当前不删除或重置用户记录；测试数据与开发数据分开。

时间戳使用带UTC偏移的ISO字符串保存，页面按Asia/Shanghai显示；服务日期与时刻按北京时间解释。V0.1仅处理当日时间窗口，跨日安排需后续扩展。

写入字段携带expected_version，旧版本返回409；生成草案在同一SQLite事务中检查需求版本。相同需求版本、相同输入重复生成返回已有草案。旧草案仍可回读并显示过期状态，不会被静默覆盖。

主要接口：GET /api/health、POST/GET /api/needs、GET/PATCH /api/needs/{id}、GET /api/resources、POST /api/needs/{id}/plan-drafts、GET /api/plans/{id}、GET /api/needs/{id}/plans、GET /api/needs/{id}/events。

## 当前边界

- 未配置真实模型前，只能验证演示／手工路径，不算真实智能抽取已验收。
- 当前是确定性草案规则与一个模型网关，不宣称四个自主智能体已经完成。
- 已加入公开报道中的真实地点和官方查询/说明资料，但未联系服务主体核实当前运营、价格或当次可用性；没有真实机构合作、服务预约或履约结果。
- 无登录和家庭隔离，仅用于本机演示，不对外部署、不录入真实家庭敏感资料。
- 成员接受情况是用户填报字段，尚无独立成员确认；保存草案不等于接受、派单或预约。
- 原文证据可定位检查不能证明模型语义必然正确，必须由用户核对。
- 依赖、接口与浏览器的实际检查结果见docs/开发验收记录.md。
