# 在线体验真实工作流

用户要完成的是“添加素材 → 调整参数 → 生成 → 取回作品”。节点图由服务器保管，浏览器只提交这几个输入。当前项目已经有上传、参数绑定、任务提交、进度查询和结果保存的实现；上线缺的是持续运行的后端与可执行模型环境。

## 推荐路线：同域名部署完整项目

```text
浏览器 → HTTPS 域名 / 认证反向代理
                       ↓
              映序 Python 后端 + 持久数据卷
                       ↓
              私有 ComfyUI / 兼容算力服务
```

1. 在可持续运行 Docker 的服务器上克隆本项目。复制 `.env.example` 到 `.env`，填写服务器能访问的 `CHENYU_CARD_URL`。
2. 在算力端按 `workflows/manifest.json` 配齐目标工作流的模型与自定义节点。先运行 `python scripts/check_setup.py --probe`；再用一个已接入工具完成上传、真实出图、下载，作为接入验收。
3. 运行 `docker compose up --build --wait`。现有 Compose 将网站绑定到宿主机 `127.0.0.1:8770`，适合宿主机反向代理转发；如果代理也在容器内，应使用受控容器网络连接网站服务。
4. 域名反向代理统一转发整个网站（页面、`/api/*`、`/api/media/*`），配置 HTTPS、访问认证、上传大小和生成等待时间。创作台使用每用户独立账户会话；首次管理员凭据由私有数据目录的 `admin-bootstrap.json` 获取。`.env` 的 `YINGXU_ALLOWED_ORIGINS` 填实际完整 Origin，例如 `https://studio.example.com`，然后重启容器。这个变量只放行请求来源，不能代替登录认证，也不会自动启用跨域 CORS。
5. 保留 `yingxu-data` 数据卷，定期备份。浏览器中的草稿和素材仍属于各自浏览器；后端任务与真实输出保存在数据卷。

网站后端只需承担文件和任务管理，GPU 可放在另一台服务器。算力地址与凭据保留在服务端；用户无需看到节点图或配置 ComfyUI 地址。已有的相对 `/api/*` 路径可直接使用，同域部署不需要新增跨域前端配置。

使用 Railway 可按 [Railway 部署指南](railway-deployment.md) 操作。自动域名的 HTTPS Origin 会自动放行；私有 API 要求账户登录，健康检查使用 `/healthz`。代理须保留实际 HTTPS scheme/Host，浏览器与 API 保持同域。

## 现有 GitHub Pages 的作用

Pages 托管静态 HTML、CSS、JavaScript，无法运行本项目 Python 后端。因此当前公开地址保留演示模式。推荐另设真实体验域名，部署上面的完整项目。

如果坚持在 Pages 上调用另一个域名的后端，需要增加前端 API Base 配置，调整所有上传、任务、媒体 URL，以及后端 HTTPS、CORS、认证。当前代码对 `github.io` 明确禁用真实任务；只修改算力地址不能让 Pages 自动接入。

## 谁可以体验

2026-10-07 已接入账户、资源归属、管理员权限、积分账本和订单。初始管理员保留旧数据，普通账户仅访问自己的任务和素材；本机草稿也按账户分开。公开商业运行仍需真实 HTTPS 部署、多账户实测、上传与存储容量管理、模型运行以及支付对账验收。详细设置见 [账户、权限与积分](platform-accounts-and-credits.md) 与 [充值渠道配置](payment-configuration.md)。

当前指定卡有 127 个 ready 工作流与 6 个 blocked；2 个外部命名模板另计，manifest 共注册 129 份 API 模板（34 份既有适配器、95 份通用执行合同）。阻塞项包括 3 个缺节点、1 个源图断链与 2 个控件版本不兼容，空文件需卡端补回。151 个目录界面不等于逐图实测，ready 也不证明模型加载与输出质量通过。本轮 `local-card-15` 的基础区域编辑已实测，未扩大到复杂图片、全部工具或其他工作流。自由创作内置模型尚未接入，正常环境已停止模拟生成；参考强度尚未参与真实生成，任意工作流导入尚未实现；自由创作须补模型 API，不能只把演示开关改成“真实”。

依据：[GitHub Pages 官方说明](https://docs.github.com/en/pages/getting-started-with-github-pages/what-is-github-pages)、[ComfyUI HTTP / WebSocket 接口](https://docs.comfy.org/development/comfyui-server/comms_routes)、本项目 `server.py`、`configuration.py`、`compose.yaml` 与 `public/app.js`。
