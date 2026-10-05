# 映序 YINGXU Studio

将复杂工作流转换为素材、描述和参数组成的创作界面。包含前端、Python 后端、交互组件库和 **151 个目录工作流的界面配置**；界面数量不等于逐图真实生成通过。当前指定算力卡有 **127 个 ready 工作流、6 个 blocked**，另有 1 个空文件和 3 个同图别名。2 个外部命名模板另计，当前 manifest 注册 **129 份 API 模板**（34 份既有适配器、95 份通用执行合同）。ready 表示可构造任务，模型加载与真实输出仍需验收。逐图输入与阻碍见 [参数审查](docs/card-workflow-parameter-audit.md)。

[在线演示](https://xbt12345.github.io/yingxu-studio/) · [组件库](https://xbt12345.github.io/yingxu-studio/workflow-control-library.html) · [真实生成接入说明](workflows/README.md)

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
| 自由创作 | 图像/视频演示生成、参考图编辑、结果操作 | 内置模型列表尚未接入真实 API |
| 创作工具目录 | 151 个工作流的素材、参数、种子、草稿与演示 | 未接入条目仍明确显示演示 |
| 已接入工具 | 127 个 ready 卡工作流 + 2 个外部命名模板；可选素材、独立描述分支和主体点选 | 自己的 ComfyUI、模型和自定义节点；6 个卡工作流 blocked；95 份通用合同完成结构检查，尚未逐图生成 |
| 参考图编辑 | 框选、圈选、画笔、擦除、本地自动抠图、撤销、保存 | 自动抠图需要 Python 后端；参考强度目前只保存偏好，尚未影响生成 |
| 作品与素材 | 对比、拖入创作、下载、批量导出、移除确认、恢复、引用定位 | 保存在本机浏览器和后端 |
| 灵感库 | 图片/视频保存到素材、带配方进入创作 | 发布只保存到当前浏览器，尚无跨用户共享 |
| 本机目录选择 | 原生选择器 + 手填运行端目录 | 桌面 Python 的 Tkinter；不会自动上传文件夹 |
| 工作流导入 | 尚未实现 | 使用仓库提供的目录和模板 |

演示结果使用内置素材，不消费算力，也不代表模型实时生成。**GitHub Pages 只有静态前端**，不能运行本地自动抠图、文件夹选择或真实生成；体验这些功能请本地搭建。

真实生成采用“上传 → 提交 → 查询 → 保存”，支持重新编辑、更新种子再次生成、按任务取消及连接恢复后的查询。远端不支持按 ID 取消时会提示，不使用全局中断；取消不保证退回外部费用。不同电脑上的模型、节点版本与 API 额度须各自核对，模板齐全不等于所有模型已经在新环境验收。

2026-10-04 本轮仅 `local-card-15` 的基础区域编辑已真实验证：原图与选区配对上传后生成红星，保护边界外像素保持一致。此结果不代表复杂图片、所有编辑工具或其他工作流全部通过。

## 配置和数据

| 配置 | 默认值 / 用途 |
| --- | --- |
| `CHENYU_CARD_URL` | 空为演示；填写自己的 ComfyUI HTTP(S) 地址 |
| `HOST` / `PORT` | `127.0.0.1` / `8770` |
| `YINGXU_DATA_DIR` | 项目 `private/`；SQLite、上传、作品和回执 |
| `YINGXU_WORKFLOW_DIR` | 项目 `workflows/api/`；可使用自己的模板目录 |
| `YINGXU_ALLOWED_ORIGINS` | 可选反向代理的完整 Origin，多个以逗号分隔 |
| `YINGXU_ACCESS_USERNAME` | 对外共享创作台的访问账号，默认 `yingxu` |
| `YINGXU_ACCESS_PASSWORD` | 对外访问的随机密码，至少 16 位；Railway 未配置时拒绝网站访问 |

新克隆直接使用公开模板，不依赖作者电脑的配置。已有所有者环境继续优先使用 `private/*.api.json`、`private/platform-compiled/*.api.json`、新增通用图的 `private/card-compiled/*.api.json` 和 `private/backend.json`。公开模板已清理密钥、个人输入提示词、素材名和素材选点，保留模型和节点绑定；详见模板清单。

浏览器素材、草稿、作品列表使用 IndexedDB / 本地状态；真实生成文件及任务另存后端数据目录。备份需要同时保留浏览器数据与后端数据。清除站点数据、换浏览器或删除数据目录会影响对应记录。

当前是个人创作台，没有多人账号与数据隔离，默认只监听本机；共享体验建议每人独立搭建。对外共享可设置上述访问账号与密码（HTTP Basic，须使用 HTTPS），只向受邀用户开放。Railway 的自动域名会自动放行对应 HTTPS Origin，健康检查使用不依赖 GPU 的 `/healthz`。访问密码不能代替多人数据隔离，不能直接当成公共多人服务。

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
local_cutout.py    CPU 本地抠图
workflows/         公开 API 模板、模型/节点清单、接入说明
scripts/           测试、配置检查、目录维护工具
private/           运行时创建，不进入 Git 或 Docker 镜像
```

## 设计与素材

设计参考 [即梦](https://jimeng.jianying.com/)、[Krea](https://www.krea.ai/)、[Resend](https://resend.com/)。没有包含研究网页源码或截图。预置素材用于界面演示，相关作品、模型与品牌权利归各自权利人；接入外部服务时遵守对应许可和服务条款。
