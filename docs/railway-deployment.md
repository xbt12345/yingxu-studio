# Railway 部署映序：费用与操作

核对日期：2026-10-03。目标是把现有前端、Python 后端和作品存储放在 Railway，继续调用自己的远程算力。网站服务器不安装 GPU 模型。以下步骤是部署指南，不代表云端已经创建或真实生成已经验收。

## 钱花在哪里

| 项目 | 费用与用途 |
| --- | --- |
| Hobby 套餐 | 每月至少 $5，包含 $5 资源用量；总用量 $3 时付 $5，用量 $8 时付 $8，并非 $5 再加全部用量 |
| 内存 | 约 $10 / GB·月，按实际占用时间计费 |
| CPU | 约 $20 / vCPU·月，按实际使用计费；配置 1 核上限不代表整月满额计费 |
| 持久卷 | 约 $0.15 / GB·月，按使用量计费，文件系统元数据也占空间 |
| 出站流量 | $0.05 / GB；下载作品、网站向算力端发送素材等都会产生出站流量 |
| Railway 域名与 HTTPS | 平台提供的域名和自动证书无需另外购买；自定义域名的注册费另算 |
| 远程算力 / 模型 API | 向原算力或 API 提供商付款，不包含在 Railway 账单里 |

算例仅用于理解账单，不是本项目的实测报价：平均 0.25GB 内存、0.05 核 CPU、1GB 持久数据、10GB 出站流量，30 天约为 $2.50 + $1 + $0.15 + $0.50 = $4.15，Hobby 仍付 $5。若平均内存升到 0.5GB，其余不变，约付 $6.65。以 Railway Usage 的实际读数为准，税费或换汇费依结算情况。

新账号的试用是最多 30 天或用完 $5 额度，先到者结束；之后 Free 每月 $1 免费额度。免费档内存和持久卷各 0.5GB，不适合持续保存视频。本指南先做小规模试用，长期使用再选 Hobby；不要预先开 Pro、额外数据库或 Railway Agent。

来源：[套餐与秒级单价](https://railway.com/pricing)、[账单与资源费](https://docs.railway.com/pricing)、[持久卷计费](https://docs.railway.com/volumes/reference)、[试用限制](https://docs.railway.com/pricing/free-trial)、[免费 HTTPS](https://docs.railway.com/networking/public-networking)。

## 1. 登录并选择仓库

1. 打开 [Railway 控制台](https://railway.com/dashboard)，使用 GitHub 登录；首次注册的条款和银行卡信息由账号所有者完成。
2. 选择 `New Project` → `Deploy from GitHub repo` → `xbt12345/yingxu-studio`。若需要安装 GitHub App，只授权这个仓库。
3. 分支选择 `main`，Root Directory 保持仓库根目录。GitHub 仓库根目录已经包含 `Dockerfile`，不要填写作者本机的 `mvp-v0.7` 路径。
4. 确认构建使用 `Dockerfile`。无需 `npm install`，无需前端构建命令，启动命令使用镜像自带的 `python server.py`。

暂时不要生成公网域名。先完成数据卷和访问密码设置，避免开放未保护的生成入口。没有配置密码时，本项目在 Railway 会拒绝网站访问，仍允许健康检查。

## 2. 设置变量

在网站服务的 `Variables` 添加下表。占位说明不是可直接粘贴的真实值。

| 变量 | 填写值 |
| --- | --- |
| `HOST` | `0.0.0.0` |
| `PORT` | `8770` |
| `YINGXU_DATA_DIR` | `/app/private` |
| `YINGXU_ACCESS_USERNAME` | `yingxu`，或自己选择的账号名，不含冒号 |
| `YINGXU_ACCESS_PASSWORD` | 自己生成并保管的随机密码，至少 16 位；只填 Railway 变量，不提交到 GitHub |
| `CHENYU_CARD_URL` | 算力平台给出的 ComfyUI HTTP(S) 接口地址，不是管理后台页面 |

`CHENYU_CARD_URL` 可先留空验证网站和抠图，之后填写再重新部署，以接通真实工作流。远程服务必须在运行，并能从 Railway 访问；不要填 `127.0.0.1` 或你电脑的内网 IP。算力地址如自带凭据，也只保存在服务端。

用 Railway 自动域名时，服务读取平台的 `RAILWAY_PUBLIC_DOMAIN` 自动放行对应 HTTPS Origin，无需手工追加。自定义域名则另设 `YINGXU_ALLOWED_ORIGINS=https://你的实际域名`。Origin 设置用于防止别的网站调用，网站访问密码用于认证，两者不能替代。

## 3. 添加持久卷

在项目画布右键或命令面板新增 `Volume`，连接网站服务，Mount Path 填 **`/app/private`**。

它保存 SQLite、上传素材、生成作品和任务回执。不要把卷挂在 `/app`，否则会遮住网站源码。试用卷默认 0.5GB，先用少量小文件；Hobby 默认 5GB。给网站保留 **一个实例和一个 Python 进程**，不要开多副本。无需额外购买 PostgreSQL 或 Redis。

作者电脑上浏览器里的素材、草稿、作品列表不会自动迁移到新域名；它们仍属于各浏览器的站点数据。新部署的后端数据卷也从空状态开始。如需保留旧任务，先备份并迁移后端数据，不要把 `private/` 推送到公开仓库。

持久卷保留数据，不等同于备份；可定期下载备份或设置平台备份，并查看相应费用。

## 4. 部署设置

在服务 `Settings` 设置：

- Healthcheck Path：`/healthz`；这个接口只表示网站进程可响应，不访问 GPU。
- Healthcheck Timeout：`120` 秒。
- Restart Policy：`On Failure`，最多 `5` 次。
- Replicas：`1`。按平台可用额度设置资源上限；大视频上传和高分辨率抠图需要留出内存余量。
- Serverless / App Sleep：关闭。当前任务在进程内跟踪，首次部署先保证生成期间不被休眠打断。

应用变量、卷和设置后部署，查看 Build Logs / Deploy Logs，确认服务已启动且 `/healthz` 检查通过。

现有 `Dockerfile` 可直接构建。Railway 官方已将旧 `railway.json` / `railway.toml` 配置方案标为弃用，故本指南使用当前控制台设置，不新增即将失效的旧格式文件。[官方说明](https://docs.railway.com/config-as-code/reference)

## 5. 生成访问地址

服务 `Settings` → `Networking` → `Public Networking` → `Generate Domain`，目标端口填 `8770`。

如果域名创建后才增加 `RAILWAY_PUBLIC_DOMAIN`，重新部署一次，让进程读取新值。打开实际域名后的 `/studio.html`，输入第 2 步的网站账号、密码。访问组件库用 `/workflow-control-library.html`。

这是一个有密码的共享创作台，不是多人独立账号系统。知道密码的人可以访问这个实例的后端任务与作品，只分享给受邀体验者。要让不同用户的内容保密，须增加用户与资源归属校验。

## 6. 接通真实工作流

服务必须已经设置 `CHENYU_CARD_URL`。在网站查看算力连接状态，然后选择明确标为已接入的创作工具，导入素材并生成。

公开仓库包含 34 份 API 模板；模型和自定义节点需要在算力端配齐。作者本机的 `private/*.api.json`、`private/platform-compiled/*.api.json` 不进入镜像，若其中有必要的专用模板或外部模型 API key，应放入服务私有数据卷的对应目录，而不是公开 GitHub。

免费试用如果显示 `Limited Trial`，其出站网络可能无法访问你的算力；先通过 GitHub 验证。仍受限时需账号所有者选择 Hobby。不要把 HTTP 200 或“已配置地址”当成真实生成已经成功。

## 7. 设置预算

Workspace → `Usage` → `Set Usage Limits`，在 **Compute Usage** 设置邮件提醒和预算硬限。例如愿意最多花 $10/月，可设 $5 提醒、$10 硬限，平台允许的最低值以表单为准。触及硬限会停止网站，可能打断任务；这个限制也不控制外部算力账单。[官方预算说明](https://docs.railway.com/pricing/cost-control)

不要仅停止服务就以为 Hobby 订阅已取消。停止运行、保留持久数据和取消套餐是不同操作；不再使用时先备份，再到 Billing 按平台取消规则处理。

## 8. 验收

上线需要以下实际结果，不能只看 Deploy 成功：

1. 手机用移动网络打开网站；未登录时无法读取任务、素材或提交生成。
2. 登录后上传图片，完成一次真实图像工作流，刷新后仍能取回并下载原文件。
3. 完成一次目标视频工作流，视频可播放、下载。
4. 没有运行任务时重启网站服务，验证旧任务和生成文件仍在。
5. 查看 Usage 里的实际费用预测和磁盘占用。

自由创作内置模型仍是演示、参考强度尚未参与真实生成、任意工作流导入尚未实现，部署不会自动补齐。详情见 [在线工作流接入](online-workflows.md)。
