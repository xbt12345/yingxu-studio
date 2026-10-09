# 映序 YINGXU Studio

当前界面版本：**0.88.0（2026-10-08）**，包含 C 方案封面、三轮工作流参数优化、尺寸校验和实际结果识别。部署版本以服务的 `/version.json` 为准；本次范围与验收边界见 [发布摘要](docs/workflow-release-review-2026-10-09.md)，部署方式见 [Railway 部署](docs/railway-deployment.md)。

将复杂工作流转换为素材、描述和参数组成的创作界面。包含前端、Python 后端、交互组件库和 **151 个目录工作流的界面配置**；界面数量不等于逐图真实生成通过。当前指定算力卡有 **127 个 ready 工作流、6 个 blocked**，另有 1 个空文件和 3 个同图别名。2 个外部命名模板另计，当前 manifest 注册 **129 份 API 模板**（34 份既有适配器、95 份通用执行合同）。ready 表示可构造任务，模型加载与真实输出仍需验收。逐图输入与阻碍见 [参数审查](docs/card-workflow-parameter-audit.md)。

[在线平台](https://yingxu-studio-production.up.railway.app/studio.html) · [静态预览](https://xbt12345.github.io/yingxu-studio/) · [组件库](https://xbt12345.github.io/yingxu-studio/workflow-control-library.html) · [真实生成接入说明](workflows/README.md)

## Python 搭建

安装 **Python 3.12** 和 Git。运行网站不需要 Node.js，也不需要前端构建。

```bash
git clone https://github.com/xbt12345/yingxu-studio.git
cd yingxu-studio
python -m venv .venv
```

Windows PowerShell：

```powershell
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
Copy-Item .env.example .env
.\.venv\Scripts\python.exe server.py
```

macOS / Linux：

```bash
.venv/bin/python -m pip install -r requirements.txt
cp .env.example .env
.venv/bin/python server.py
```

打开 **http://127.0.0.1:8770/studio.html**；组件库位于 **http://127.0.0.1:8770/workflow-control-library.html**。`Ctrl+C` 停止服务。Windows 也可在安装后运行 `启动映序.ps1`，它优先使用项目的 `.venv`。

本地运行 `启动映序.ps1` 使用用户模式：保留用户信息，直接进入创作，不启用登录、积分与充值。本地模式由私有 `.env` 中的 `YINGXU_LOCAL_MODE=1` 开启，仅对本机回环请求生效；已部署版本保持原登录计费流程。正式部署创作台需要登录。首次启动会在数据目录生成 `admin-bootstrap.json`，管理员用户名和随机初始密码只保存在该私有文件中。旧作品和素材归初始管理员，新注册用户使用独立账户。登录后可在“我的账号”修改密码；文件不可上传到公开仓库。具体操作见 [账户、权限与积分](docs/platform-accounts-and-credits.md)。

`.env` 保持默认即可演示，不需要密钥。启用真实生成，在 `.env` 中填写自己的 `CHENYU_CARD_URL`，按 [接入说明](workflows/README.md) 安装模型和节点，再重启服务。

## Docker 搭建

安装 Docker 和 Compose，克隆仓库后：

```bash
docker compose up --build --wait
```

访问同一个本地地址。停止用 `docker compose down`；数据保存在 `yingxu-data` 数据卷。加 `-v` 会删除数据卷。

需要真实生成时先复制 `.env.example` 为 `.env` 并填写算力地址。本机 ComfyUI 在容器中填写 `http://host.docker.internal:8188`，远程 ComfyUI 填其实际地址。容器不弹出电脑的原生文件夹窗口，可直接填写运行端路径。

## 功能与真实接入范围

| 功能 | 当前能力 | 条件 / 边界 |
| --- | --- | --- |
| 自由创作 | 图像/视频创作输入、费用预估、参考图编辑与结果操作 | 内置模型列表尚未接入真实 API，正常环境暂不可生成 |
| 创作工具目录 | 151 个工作流的素材、参数、种子、草稿与演示 | 未接入条目仍明确显示演示 |
| 已接入工具 | 127 个 ready 卡工作流 + 2 个外部命名模板；可选素材、独立描述分支和主体点选 | 自己的 ComfyUI、模型和自定义节点；6 个卡工作流 blocked；95 份通用合同完成结构检查，尚未逐图生成 |
| 参考图编辑 | 框选、圈选、画笔、擦除、本地自动抠图、撤销、保存 | 自动抠图需要 Python 后端；参考强度目前只保存偏好，尚未影响生成 |
| 作品与素材 | 对比、拖入创作、下载、批量导出、移除确认、恢复、引用定位 | 保存在本机浏览器和后端 |
| 灵感库 | 图片/视频保存到素材、带配方进入创作 | 发布只保存到当前浏览器，尚无跨用户共享 |
| 本机目录选择 | 原生选择器 + 手填运行端目录 | 桌面 Python 的 Tkinter；不会自动上传文件夹 |
| 工作流导入 | 尚未实现 | 使用仓库提供的目录和模板 |
| 账户与权限 | 注册、登录、退出、修改密码、普通用户与管理员、任务和媒体归属校验 | 草稿与素材浏览器存储也按账户分开；跨设备草稿同步未实现 |
| 管理员后台 | 独立 `admin.html`，用户搜索/分页、权限、停用/恢复、积分调整、账本与操作记录 | 入口收在账号菜单，仅管理员可用；积分调整填写原因，保留冻结积分 |
| 积分与充值 | 套餐、订单、积分账本、生成冻结/结算、管理员核对 | 真实工具费用须由管理员配置；支付宝/微信需商户配置，银行卡/管理员走人工到账；尚未实收验收 |

演示结果使用内置素材，不消费算力，也不代表模型实时生成。**GitHub Pages 只有静态前端**，不能运行本地自动抠图、文件夹选择或真实生成；体验这些功能请本地搭建。

真实生成采用“上传 → 提交 → 查询 → 保存”，支持重新编辑、更新种子再次生成、按任务取消及连接恢复后的查询。远端不支持按 ID 取消时会提示，不使用全局中断；取消不保证退回外部费用。不同电脑上的模型、节点版本与 API 额度须各自核对，模板齐全不等于所有模型已经在新环境验收。

2026-10-08 已通过本地网站完成 13 类代表工作流的 15 个实际任务，能取回和保存结果。完整记录与画质限制见本地工作流审查；这不代表 151 个工作流全部经过 GPU 验收，也不代表部署后再次运行了全部代表。

## 配置和数据

| 配置 | 默认值 / 用途 |
| --- | --- |
| `CHENYU_CARD_URL` | 空为演示；填写自己的 ComfyUI HTTP(S) 地址 |
| `HOST` / `PORT` | `127.0.0.1` / `8770` |
| `YINGXU_DATA_DIR` | 项目 `private/`；SQLite、上传、作品和回执 |
| `YINGXU_WORKFLOW_DIR` | 项目 `workflows/api/`；可使用自己的模板目录 |
| `YINGXU_ALLOWED_ORIGINS` | 可选反向代理的完整 Origin，多个以逗号分隔 |
| 支付渠道变量 | 支付宝、微信商户及银行卡收款配置，见 [充值配置](docs/payment-configuration.md)；默认不开自动收款 |

新克隆直接使用公开模板，不依赖作者电脑的配置。已有所有者环境继续优先使用 `private/*.api.json`、`private/platform-compiled/*.api.json`、新增通用图的 `private/card-compiled/*.api.json` 和 `private/backend.json`。公开模板已清理密钥、个人输入提示词、素材名和素材选点，保留模型和节点绑定；详见模板清单。

浏览器素材、草稿、作品列表使用每账户独立的 IndexedDB / 本地状态；真实生成文件、任务、账户、订单和积分账本另存后端数据目录。备份需要同时保留浏览器数据与后端数据。清除站点数据、换浏览器或删除数据目录会影响对应记录。旧浏览器数据首次登录初始管理员时复制迁移，保留原数据库。

创作台现使用账户会话、来源与 CSRF 校验、资源归属及管理员权限，旧共享 HTTP Basic 入口已被账户系统替代。默认只监听本机。对外部署须使用 HTTPS、持久卷和单服务进程，并另做实际部署、用户隔离、模型生成和支付对账验收；本地测试不代表公开商业运行已验收。健康检查继续使用不依赖 GPU 的 `/healthz`。

Railway 的费用、变量、持久卷、预算与逐步操作见 [Railway 部署指南](docs/railway-deployment.md)。

在线真实生成的部署路线、Pages 的边界与多人体验条件见 [在线工作流接入](docs/online-workflows.md)。自由创作的参考素材加号支持“本地导入”和“素材库选择”；本地文件先保存在当前浏览器，提交真实任务时才上传到后端。

## 开发与检查

测试另需 Node.js **22 或更高版本**：

```bash
python -m pip install -r requirements-dev.txt
python -m unittest discover -v
python scripts/check_setup.py
npm test
```

`check_setup.py` 检查模板哈希、全部界面配置及静态资源；加 `--probe` 可查询自己的 ComfyUI 节点类型，不提交生成任务。模型文件和输出质量仍需实际生成验证。GitHub Actions 在 Windows / Linux 运行契约测试，在 Linux 构建和启动 Docker，并更新 Pages。

目录配置已经预生成，启动不需执行 `scripts/build_*`。目录维护脚本用于原始 ComfyUI 图、目录快照和审查资料；重新构建时需提供相应输入，这些研究资料不是运行依赖。组件规范见 [属性组件库与拼装规范](工作流属性组件库与拼装规范-2026-09-29.md)。

```text
public/            前端、示例素材、组件库、预生成界面配置
server.py          FastAPI、素材上传、任务和结果保存
adapters.py        工作流节点绑定与参数校验
schema_adapters.py 通用执行合同、字段绑定、音频/文字结果与主体选点
configuration.py  环境配置与模板回退加载
platform_accounts.py  账户、归属、积分账本与订单事务
platform_api.py       登录会话、权限及账户/管理接口
payment_gateway.py    支付宝/微信签名收款与可信支付证据
local_cutout.py    CPU 本地抠图
workflows/         公开 API 模板、模型/节点清单、接入说明
scripts/           测试、配置检查、目录维护工具
private/           运行时创建，不进入 Git 或 Docker 镜像
```

## 设计与素材

设计参考 [即梦](https://jimeng.jianying.com/)、[Krea](https://www.krea.ai/)、[Resend](https://resend.com/)。没有包含研究网页源码或截图。预置素材用于界面演示，相关作品、模型与品牌权利归各自权利人；接入外部服务时遵守对应许可和服务条款。
