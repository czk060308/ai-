# 安心接力 · Anxin Relay

**把家庭照护需求变成有依据、可追踪的服务安排。**

个人参赛项目的V0.1：把复诊陪同、返家与午餐需求整理为带字段依据、事项依赖及待确认条件的照护草案。当前已跑通真实模型抽取、字段核对、规则检查、草案保存和刷新／重启回读。

## 按类别查找代码

| 类别 | 位置 | 内容 |
|---|---|---|
| 前端界面 | [app/apps/web](app/apps/web) | React、TypeScript、Vite、Ant Design三栏工作台 |
| API与业务逻辑 | [app/backend/src/anxin](app/backend/src/anxin) | 需求接口、模型网关、确定性约束与草案编排 |
| 存储 | [storage.py](app/backend/src/anxin/storage.py) | SQLAlchemy模型、SQLite、版本与事件记录 |
| 后端测试 | [app/backend/tests](app/backend/tests) | 临时数据库、接口、故障、原文依据及模型参数检查 |
| 浏览器测试 | [app/apps/web/e2e](app/apps/web/e2e) | 草案主流程、窄屏、冲突与真实结果回读 |
| 演示资料 | [app/data/seeds](app/data/seeds) | 5条明确标为demo的合成资料，无真实服务供给 |
| 启动与验证工具 | [app](app)、[app/scripts](app/scripts) | 启动脚本、真实模型验收脚本、空值环境模板 |
| 使用与设计说明 | [app/README.md](app/README.md)、[docs](docs) | 安装、配置、代码阅读路线及模块职责 |
| 开发验收 | [app/docs](app/docs) | 实际完成范围、真实模型验证与已知限制 |

## 本机运行

环境：Python 3.11或以上、Node.js 24（本机已验证版本）、npm及uv。以下PowerShell命令在仓库根目录执行：

```powershell
Set-Location app
Remove-Item Env:PYTHONHOME,Env:PYTHONPATH -ErrorAction SilentlyContinue
uv venv --python 3.11 .venv
uv pip install --python .venv\Scripts\python.exe -r backend\requirements.lock.txt
uv pip install --python .venv\Scripts\python.exe --no-deps -e .\backend
if (-not (Test-Path -LiteralPath .env)) { Copy-Item .env.example .env }
# 在本机编辑.env；不要把真实密钥提交到Git。
Set-Location apps\web
npm.cmd ci
npm.cmd run build
Set-Location ..\..
powershell -ExecutionPolicy Bypass -File .\start.ps1
```

已存在.env时跳过复制，避免覆盖本机配置。浏览器访问 `http://127.0.0.1:8000`，Ctrl+C停止。启动脚本只监听本机回环地址。

不配置模型也可使用“使用演示字段”或“手工填写”。“识别需求”会实际请求配置的供应商；当前已验证kimi-k2.6。详细配置、开发双进程启动及验证命令见[工程说明](app/README.md)。

## 当前实现与边界

- 明确区分真实模型输出、演示字段和手工补充，字段依据可追溯到用户原文。
- 规则检查时间冲突、预算与依赖，未知费用不按0元计算，有空不等于已接受。
- 草案、需求版本和实际事件写入SQLite，旧草案保留并标记过期。
- 当前没有真实预约、家庭账号隔离、成员独立认领、worker和多智能体执行；这些是后续版本的工作。

当前后端19项检查通过；配置真实模型后的浏览器回归4项通过、1项因测试条件不适用跳过。真实中文合成样例已完成一次抽取、5步草案生成及数据库回读，详见[验收记录](app/docs/真实模型接入验收.md)。不将单个样例成功等同于真实服务落地成效。

目录保留app作为工程根，避免改变正在运行的服务路径。安装依赖、数据库、截图、.env及本地历史策划材料不纳入版本控制。
