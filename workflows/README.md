# 真实生成接入

当前 [manifest.json](manifest.json) 注册 129 份 API 格式工作流，文件位于 `api/`：指定卡 127 个 ready 工作流与 2 个外部命名模板，包含原 34 份适配器和 95 份通用执行合同。指定卡另有 6 个 blocked（3 个缺节点、1 个源图断链、2 个控件版本不兼容）、1 个空文件与 3 个同图别名，均保留状态且不猜测执行内容。目录中未注册的旧模板不计入 ready，也不能直接绕过执行合同提交。完整文件名、模型名、自定义节点类型和模板哈希见 manifest，137 项状态与输入见 [逐图审查](../docs/card-workflow-parameter-audit.md)。151 个界面配置不等于全部实测；ready 和结构通过不等于模型生成验收通过。

逐图依赖与官方节点迁移依据见 [依赖审查](../docs/card-workflow-dependency-audit.md)。设置 `CHENYU_CARD_URL` 后，可以依次运行 `python scripts/sync_card_workflows.py`、`python scripts/compile_card_workflows.py`、`python scripts/audit_compiled_contracts.py`，复核同一批已审查源图。下载内容留在忽略的 `private/` 中；源文件变化时编译会阻止发布，必须先更新和审查界面绑定，不能以旧参数套用新图。这不是任意工作流自动导入功能。

## 接入步骤

1. 准备自己的 ComfyUI 服务，确认其 `/queue`、`/object_info`、`/upload/image`、`/prompt`、`/history`、`/view` 和 `/ws` 接口可用。网站通过后端连接，不把服务地址发到前端。
2. 对照 `manifest.json` 中需要的工作流，安装其 `node_types` 和 `models`。带平台专有节点的模板需要兼容的平台或自己的同等节点；网站仓库不会提供模型权重、付费额度或节点服务账号。
3. 在项目 `.env` 填写 `CHENYU_CARD_URL=http://127.0.0.1:8188`（示例），重启网站。Docker 连接宿主机时使用 `http://host.docker.internal:8188`。
4. 运行 `python scripts/check_setup.py --probe` 检查节点缺失。这个检查不生成作品，不能代替模型安装和实际出图验收。
5. 打开“创作工具”，从已接入工具选择任务，上传自己的素材后生成。先用一个任务验证输出，再启用其他模型。

参考文档：[ComfyUI 官方仓库](https://github.com/Comfy-Org/ComfyUI)、[API 工作流示例](https://github.com/Comfy-Org/ComfyUI/tree/master/script_examples)。可执行 API 图与画布 UI 图不是同一格式；当前网站不支持任意工作流导入。

## API 密钥

带“自有 API”的工具可填写自己的 Model 和 API key。通用 LLM / 视觉节点同时需要 Base URL；GPT、Grok、Banana 等固定供应商节点只显示实际支持的模型与密钥。公开模板中的密钥已留空；所有者私有模板可保留既有授权。其他平台节点仍可能依赖平台授权或账户额度，模型清单仅记录静态依赖。

不要将填入密钥的模板提交 Git。自有 API 的输入密钥只在页面内存中保存，但提交真实任务时会进入后端私有任务图与算力服务；后端 `private/` 数据目录应按私人数据保管。作品下载中的工作流会清理密钥。

## 模板兼容

原 34 份模板的节点 ID、输出节点与 `adapters.py` 一一对应；新增模板由 `compiled-registry.json` 和 `schema_adapters.py` 绑定。浏览器只提交稳定字段 ID，不能提交节点连线。可替换模型路径、填入自己的服务配置，但不能随意重编号节点；更换拓扑需同步修改执行合同和界面 schema。

`source_hash` 是原始目录图的身份，用于匹配前端与适配器；`template_sha256` 是清理后公开 API 文件的哈希，两者用途不同。输入提示词、素材和输出文件前缀在提交时由适配器覆盖，清理过的初始提示词不会代替用户描述。

查找顺序：新增通用图优先 `private/card-compiled/`，原适配器沿用同名私有图，再回退 `YINGXU_WORKFLOW_DIR`（默认 `workflows/api/`）。新电脑不需要作者的私有文件即可构造任务图；真正执行仍取决于自己的算力环境。主体跟踪先导入原视频，再在首帧点选人物；不复用作者的坐标。

维护时 `scripts/sync_card_workflows.py` 只读保存卡端文件与节点定义；`scripts/compile_card_workflows.py` 生成通用模板、注册表和哈希清单；`scripts/audit_card_parameters.py` 输出逐图审查。快照保存于忽略提交的 `private/`，不会调用 `/prompt` 或启动生成。
