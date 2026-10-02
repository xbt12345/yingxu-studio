# 真实生成接入

仓库附带 34 份 API 格式工作流，文件位于 `api/`。完整文件名、模型名、自定义节点类型和模板哈希见 [manifest.json](manifest.json)。其中 32 个图像工具和 2 个视频工具有网站适配器；151 个目录条目并非全部已接入模型。

## 接入步骤

1. 准备自己的 ComfyUI 服务，确认其 `/queue`、`/object_info`、`/upload/image`、`/prompt`、`/history`、`/view` 和 `/ws` 接口可用。网站通过后端连接，不把服务地址发到前端。
2. 对照 `manifest.json` 中需要的工作流，安装其 `node_types` 和 `models`。带平台专有节点的模板需要兼容的平台或自己的同等节点；网站仓库不会提供模型权重、付费额度或节点服务账号。
3. 在项目 `.env` 填写 `CHENYU_CARD_URL=http://127.0.0.1:8188`（示例），重启网站。Docker 连接宿主机时使用 `http://host.docker.internal:8188`。
4. 运行 `python scripts/check_setup.py --probe` 检查节点缺失。这个检查不生成作品，不能代替模型安装和实际出图验收。
5. 打开“创作工具”，从已接入工具选择任务，上传自己的素材后生成。先用一个任务验证输出，再启用其他模型。

参考文档：[ComfyUI 官方仓库](https://github.com/Comfy-Org/ComfyUI)、[API 工作流示例](https://github.com/Comfy-Org/ComfyUI/tree/master/script_examples)。可执行 API 图与画布 UI 图不是同一格式；当前网站不支持任意工作流导入。

## API 密钥

`local-card-82`、`local-card-105`、`local-card-106` 的语言模型 / 视觉 API 输入需要自己的密钥。可在网站的“自有 API”处填写 Base URL、Model 和 API key，或配置私有模板。公开模板中的密钥已留空。其他平台节点仍可能依赖平台授权或账户额度，模型清单仅记录静态依赖。

不要将填入密钥的模板提交 Git。自有 API 的输入密钥只在页面内存中保存，但提交真实任务时会进入后端私有任务图与算力服务；后端 `private/` 数据目录应按私人数据保管。作品下载中的工作流会清理密钥。

## 模板兼容

每份模板的节点 ID、输出节点与 `adapters.py` 一一对应。可替换模型路径、填入自己的服务配置，但不能随意重编号节点；更换拓扑需同步修改适配器和界面 schema。

`source_hash` 是原始目录图的身份，用于匹配前端与适配器；`template_sha256` 是清理后公开 API 文件的哈希，两者用途不同。输入提示词、素材和输出文件前缀在提交时由适配器覆盖，清理过的初始提示词不会代替用户描述。

查找顺序：已有 `private/` 中的同名私有模板优先，其次为 `YINGXU_WORKFLOW_DIR`（默认 `workflows/api/`）。新电脑不需要作者的私有文件即可构造任务图；真正执行仍取决于自己的算力环境。
