# 从仓库部署本地创作工作台

目标版本：0.91.2。原生 Python 启动可复现本机免登录界面；仓库包含前端、服务端和真实执行模板，不需要作者的 `private/`、浏览器数据或审查目录。

## 1. 安装和启动

准备 Python 3.12、Git。克隆后运行：

```sh
git clone https://github.com/xbt12345/yingxu-studio.git
cd yingxu-studio
python -m venv .venv
```

Windows PowerShell：

```powershell
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
Copy-Item .env.example .env
.\.venv\Scripts\python.exe scripts/check_setup.py
.\.venv\Scripts\python.exe server.py
```

macOS / Linux：

```sh
.venv/bin/python -m pip install -r requirements.txt
cp .env.example .env
.venv/bin/python scripts/check_setup.py
.venv/bin/python server.py
```

打开 [本地创作台](http://127.0.0.1:8770/studio.html)。默认直接进入本地工作区；首次启动自动创建自己的私有数据目录。更新已有部署时保留自己的 `.env` 和 `private/`，不要用示例文件覆盖它们。

网站不需要 Node.js 或前端构建。音画循环工作流需要把系统 `ffmpeg` 加入 PATH；确认 `ffmpeg -version` 可执行。Python 的 PyAV 处理普通视频封装，不能代替该工作流所需的 FFmpeg 命令行。

## 2. 接通 127 个工作流

这些功能由网站后端连接自己的 ComfyUI 算力端。公开 manifest 有 **129 个执行模板 = 127 个卡端工作流 + H3 与 Bernini 两个命名模板**；还有 6 个 blocked 条目，不应视为已接通。两个百度视频 API 单独计数，不属于这 129 个模板。

在 `.env` 设置自己的地址：

```dotenv
CHENYU_CARD_URL=http://127.0.0.1:8188
```

地址须是 ComfyUI 的实际 HTTP API 地址。模型权重、自定义节点、平台专有节点权限和外部模型额度在算力端配置，不随网站仓库分发。按 [manifest](../workflows/manifest.json) 的 `node_types` 与 `models` 安装依赖，再运行：

```sh
python scripts/check_setup.py --probe
```

这里的 `python` 应使用刚安装依赖的虚拟环境解释器。探测只查询节点定义，不提交任务。节点齐全仍不证明模型文件和输出质量通过；先选择所需工作流，导入自己的输入完成实际生成验收。详细依赖见 [工作流接入](../workflows/README.md)。

公开模板保留执行所需的通用固定协议、节点连接和参数合同。个人提示词、参考素材、API 密钥与旧显示缓存不随仓库发布。工作流已有参数可直接编辑，带“自有 API”的节点需填自己的 Model、API key，以及该节点支持时的 Base URL。

## 3. 接通两个百度视频 API

在 `.env` 填入自己的百度 VOD v3 Bearer API key，然后重启后端：

```dotenv
BAIDU_VOD_API_KEY=replace-with-your-own-vod-v3-api-key
```

替换整个占位值，不要照抄。该配置只由服务端读取；不需要改前端或提交到 Git。

| 网站模型 | 上游模型 | 当前接入的输入方式 |
| --- | --- | --- |
| 百度 SD2 | `doubao-seedance-2-0-260128` | 纯文本、单首帧、参考图 |
| 百度 SD2.5 | `doubao-seedance-2-5-260628` | 纯文本、单首帧、参考图；首帧画幅跟随图片 |

`check_setup.py` 会离线显示凭据是否配置；这不代表提供商已授权或有额度。页面按模型、清晰度和时长读取费用，用户点击生成才会调用供应商。提交、任务查询、结果保存和历史恢复的代码均在仓库中。供应商仍可能扣费；本地模式仅不扣网站积分。

当前其它自由创作模型尚未接入。通用首尾帧界面提供两个素材槽，但不能把它当成百度接口的首尾帧能力。上述两模型的完整新部署验收需要自己的有效凭据、额度和一次实际任务。

## 4. Docker 方式

复制 `.env.example` 为 `.env`，填写自己的配置，然后执行：

```sh
docker compose up --build --wait
```

镜像包含运行依赖和 FFmpeg。Compose 将算力地址与百度 API key 传给后端，数据保存到 `yingxu-data` 卷。本机 ComfyUI 地址改为 `http://host.docker.internal:8188`。

容器连接经过网桥，不能据此获得本机回环的免登录权限，因此 Compose 显式使用账户模式。首次管理员信息位于容器 `/app/private/admin-bootstrap.json`，在自己的受控终端读取并登录；不要公开该文件。要复现免登录界面，使用原生 Python 方式。此差异不会改变工作流与 API 执行合同。

停止使用 `docker compose down`，不加 `-v` 即保留数据卷。对外部署使用 HTTPS、持久存储和单进程，详见 [部署指南](railway-deployment.md)。GitHub Pages 只能预览静态界面，不能承载真实生成后端。

## 5. 自检与恢复

- `/healthz`：确认网站进程可响应，不代表 GPU 或供应商可用。
- `/version.json`：确认部署为目标版本。
- `scripts/check_setup.py`：检查模板哈希、界面和静态资源；百度配置检查不联网。
- 工作流：按需完成自己的图片、视频任务，刷新后能取回和下载输出。
- 更新或回退前备份自己的 `private/`；浏览器草稿和素材属于该站点的浏览器存储，需要另外保留。仓库更新不迁移作者的任务或账号。

开发回归另需 Node.js 22+，安装 `requirements-dev.txt` 后运行 `python -m unittest discover -v`、`python -m pytest -q tests` 和 `npm test`。这些合同测试不消费真实模型额度。
