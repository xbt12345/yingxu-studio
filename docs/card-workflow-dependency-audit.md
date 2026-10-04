# 算力卡工作流依赖审查

2026-10-04 通过已配置算力卡的只读 API 核实；未安装节点、未重启、未下载模型、未提交生成任务。

`/manager/version`、`/customnode/installed`、`/customnode/getlist?mode=local&skip_update=true`、`/customnode/getmappings?mode=local` 均返回 200。Manager 报告 V3.42，管理队列为空。管理接口可读取，不代表安装权限已经验证。[官方 Manager API](https://github.com/Comfy-Org/ComfyUI-Manager/blob/main/openapi.yaml)

## 已确定的版本迁移

工作流 8 的旧 `MultimodalChat` 和 `MultimodalQwen38Loader` 没有注册，但当前 `VisionChat` 和 `Qwen38VLLoader` 实际存在；相同插件已经启用。这是节点版本变化。

迁移依据：

- [原工作流保存版本的节点实现，commit 5d9378e](https://github.com/xzbdqian10nian/ComfyUI-TankNodes/blob/5d9378e11496b3c6bc4f04ad821396b792105f42/generic_nodes.py)。
- [Manager 报告的安装版本节点实现，commit 63d2136](https://github.com/xzbdqian10nian/ComfyUI-TankNodes/blob/63d21361e08440a8836edc23dca4fb0d6c616c05/generic_nodes.py)。现场字段最终以 `/object_info` 为准，安装版本标识不证明本地文件没有其他改动。
- [官方 reasoning.py](https://github.com/xzbdqian10nian/ComfyUI-TankNodes/blob/main/reasoning.py) 明确兼容旧枚举：`backend_default→auto`、`thinking→medium`、`instruct→off`。

编译器只在旧类缺失、新类已注册时进行这两个明确迁移；按旧控件名称读取保存值，避免 prompt/system_prompt 顺序变化造成互换。两个节点间 backend 类型同步变为 `VISION_LLM_BACKEND`，聊天四个 STRING 输出顺序不变。原始工作流不修改。

原图选定的主模型与对应视觉 projector 在现场 loader 枚举中精确存在，没有替换成另一模型。枚举、字段和连线校验属于结构验证，真实模型推理仍需另外验收。

## 剩余阻塞工作流与最小修复

| 工作流 | 完整缺失类及节点 | 最小节点包 |
| --- | --- | --- |
| 42：0706加速版-多参版Bernini | 547 `BerniniPromptEnhancer` | [RH-RunningHub/ComfyUI-RH-Bernini](https://github.com/RH-RunningHub/ComfyUI-RH-Bernini) |
| 74：0427qwen人物姿势迁移终极版 | 331 `ImageCompositeMaskedWithSwitch`；336 `MaskFastGrow`；356 `ConcatTextOfUtils`；366 `GroundingDinoModelLoader (segment anything2)` | [zhangp365/ComfyUI-utils-nodes](https://github.com/zhangp365/ComfyUI-utils-nodes) 与 [neverbiasu/ComfyUI-SAM2](https://github.com/neverbiasu/ComfyUI-SAM2) |
| 102：wan-s2v 无限数字人唱歌 | 24 `MelBandRoFormerModelLoader`；12 `MelBandRoFormerSampler` | [kijai/ComfyUI-MelBandRoFormer](https://github.com/kijai/ComfyUI-MelBandRoFormer) |

上述节点包在现场 Manager 中均为 `not-installed`，并非单纯被禁用；不存在以已有相近名字节点直接替代的依据。

恢复顺序：安装这些精确节点包及其必要依赖 → 让节点实际加载 → 回读 `/object_info` 确认所有缺类已注册 → 检查模型 → 重新编译与结构验证 → 实际生成验收。重启须避开正在执行的任务。

工作流 42 的 RH-Bernini 官方说明提示词组装包不需要额外 Python 包或自动下载模型。工作流 74 还需要对应 GroundingDINO 权重及配置；SAM2 包可能在首次运行时自动下载，必须先核对模型准备情况。[SAM2 模型说明](https://github.com/neverbiasu/ComfyUI-SAM2#models)

工作流 102 的源模型是 `MelBandRoformer_fp16.safetensors`，该包要求模型位于 `models/diffusion_models`。本次未验证这份文件在卡端实际存在，安装节点不等于模型已准备好。[MelBandRoFormer 模型说明](https://github.com/kijai/ComfyUI-MelBandRoFormer#readme)

阻塞工作流保留完整编辑界面和具体原因，缺类未恢复前禁止提交。API 类工作流另需自己的服务账号或私有模板配置；公开目录不包含账户密钥。

## 既有适配器的独立复核

32 个既有算力卡适配器以及 2 个外部命名适配器，均分别用最少与最多的虚拟参考素材离线构图，并与本次取得的卡端 `/object_info` 比较。所有实际节点类、必需输入、默认模型枚举、数值类型与范围、连线的输出槽和类型均通过；没有上传素材或调用 `/prompt`。

4 个模板中的 13 个额外字段已逐项核实：`JoinStringMulti.Update inputs` 是前端按钮，`ShowText|pysssss.text_0` 与 `easy showAnything.text` 是前端显示数据；ComfyUI 不会把未注册的 V1 字面输入传给执行函数。`CustomCombo.index` 与 `option1..option4` 则由官方 V3 节点的 `accept_all_inputs=True`、`execute(choice,index=0,**kwargs)` 明确接收。验证器仅放行这些精确类、字段及正确字面类型，没有普遍忽略未知输入或未知连线。[官方执行器](https://github.com/Comfy-Org/ComfyUI/blob/master/execution.py)、[官方 CustomCombo 实现](https://github.com/Comfy-Org/ComfyUI/blob/master/comfy_extras/nodes_logic.py)

此检查证明保存模板能按当前节点接口构图，不能证明模型能完成推理、外部账户有额度或生成质量达标。完整运行仍需逐图真实生成验收。
