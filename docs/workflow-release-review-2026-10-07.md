# 工作流参数与 0.81.1 发布审查

日期：2026-10-07。范围为当前 129 个已接入工作流（2 个主工作流、32 个既有适配器、95 个通用执行合同）；另外 6 个阻断工作流保持禁止提交。采用实际页面、后端合同、有效执行图和公开部署模板核对，不以目录界面数量代替真实生成验收。

## 结论与修正

- 逐项核对默认值、枚举、数值边界、种子恢复、独立描述、必填/可选素材、字段身份、派生单位和输出可达性；129 对本机有效图与公开部署模板一致，manifest 文件哈希全部匹配。
- 修正 11 个数值边界在浏览器解析后舍入的问题：2 个整数输入增加精确整数校验，9 个支持小数秒的时长控制保留小数，仅缩窄由原生 INT64 上限产生的页面上限。实际执行合同、节点默认值、图连线、正常时长和页面布局不变。FLOAT 类型的已有范围保持原样。
- 更新 3 个旧审查脚本，按当前有效分支识别固定比例文本、已关闭的中间帧参数及封装后的节点范围。审查仍会拒绝源身份漂移或无法确认的目标，不按旧告警盲改工作流。
- 部署 CI 改为公开健康检查，加上真实账户登录和 CSRF 后验证抠图；运行契约测试使用公开模板，只有私有原图字节的来源核验在干净克隆缺少原资料时明确跳过。
- 首启依据脱敏发布计划，仅补缺已确认的 93 个工具价格与 6 个套餐。现存管理员设置优先，同一初始化标记保证后续启动不回填人工删除；事务、私有数据库备份和保护指纹防止账户、积分、订单或作品变化。没有历史耗时的 36 个接入工具不设价。

公网升级验收补充：修复 HTTPS 反向代理转发至内部 HTTP 时账号来源校验失败的问题。云端以经过严格校验的 Railway 配置域名为准，登录 Cookie 保持 Secure 与 HttpOnly；不信任客户端伪造的 Host 或转发头，本机原有校验保留。该修正随 0.81.1 发布，前端缓存仍为 81.0。

为反向代理新增 5 项回归，覆盖登录后的会话和 CSRF、恶意 Host、伪造转发头、错误域名和本机兼容性；包含既有账号与部署访问测试的 62 项专项检查全部通过。

## 逐工作流参数检查

下面的“通过”指离线参数与界面合同通过，不表示本轮执行了远端生成。

| 工作流 | 原名称 | 合同类型 | 参数/描述/素材 | 合法输入变体 | 结果 |
|---|---|---|---:|---:|---|
| h3-reference | H3 多参考图生视频 | primary | 8 / 0 / 2 | 1 | 通过 |
| bernini-edit | Bernini 视频编辑 | primary | 7 / 0 / 2 | 1 | 通过 |
| local-card-11 | 0221flux-2-klein9b-单-多图编辑对比aio | legacy | 2 / 2 / 2 | 10 | 通过 |
| local-card-15 | 0221klein-9b局部重绘流 | legacy | 2 / 1 / 1 | 3 | 通过 |
| local-card-16 | 0221klein9b-图像标记替换流 | legacy | 2 / 1 / 2 | 6 | 通过 |
| local-card-17 | 基础-Flux.2 Klein 4B 蒸馏加速 图生图 | legacy | 3 / 1 / 2 | 15 | 通过 |
| local-card-18 | 基础-Flux.2 Klein 4b图生图 | legacy | 3 / 2 / 2 | 15 | 通过 |
| local-card-20 | 基础-Flux.2 Klein 9B 蒸馏加速 图生图 | legacy | 2 / 1 / 1 | 8 | 通过 |
| local-card-85 | 0427Anima文生图 | legacy | 4 / 2 / 0 | 10 | 通过 |
| local-card-1 | 0921qwenimage2.1图像生成 | legacy | 3 / 2 / 0 | 16 | 通过 |
| local-card-2 | 0921qwenimage2.1图像编辑 | legacy | 3 / 2 / 2 | 16 | 通过 |
| local-card-3 | 0923qwenimage2.1服装衣服穿衣工作流 | legacy | 3 / 2 / 2 | 16 | 通过 |
| local-card-9 | 0221flux-2-klein-9b-文生图base | legacy | 3 / 2 / 0 | 15 | 通过 |
| local-card-10 | 0221flux-2-klein-9b-文生图标准流 | legacy | 3 / 1 / 0 | 15 | 通过 |
| local-card-12 | 0221klein-9b-动漫转真人多模型对比 | legacy | 2 / 3 / 1 | 6 | 通过 |
| local-card-13 | 0221klein-9b图像扩展流 | legacy | 7 / 1 / 1 | 16 | 通过 |
| local-card-14 | 0221klein-9b多角度转换流 | legacy | 6 / 1 / 1 | 14 | 通过 |
| local-card-19 | 基础-Flux.2 Klein 4b文生图 | legacy | 2 / 2 / 0 | 8 | 通过 |
| local-card-21 | 基础Flux.2 Klein 9B 蒸馏加速 文生图 | legacy | 2 / 1 / 0 | 8 | 通过 |
| local-card-78 | Qwen-Edit-2511-多角度切换 | legacy | 2 / 2 / 1 | 8 | 通过 |
| local-card-82 | 0111qwen2511动漫转真人 | legacy | 3 / 2 / 1 | 6 | 通过 |
| local-card-83 | 0907krea2动漫转真人 | legacy | 1 / 1 / 1 | 1 | 通过 |
| local-card-84 | 0923qwenimage2.1动漫转真人 | legacy | 3 / 2 / 1 | 16 | 通过 |
| local-card-104 | 0531z_image文生图全量版本 | legacy | 2 / 2 / 0 | 10 | 通过 |
| local-card-105 | 0608image_ideogram4_t2i -破 | legacy | 4 / 1 / 0 | 11 | 通过 |
| local-card-106 | 0608image_ideogram4_t2i  | legacy | 4 / 1 / 0 | 11 | 通过 |
| local-card-107 | qwen2512文生图8步 | legacy | 4 / 2 / 0 | 13 | 通过 |
| local-card-108 | 文生图_krea2_turbo_t2i | legacy | 7 / 1 / 0 | 18 | 通过 |
| local-card-109 | 0531_z_image_turbo文生图 | legacy | 4 / 2 / 0 | 14 | 通过 |
| local-card-110 | krea2_sq大师v2文生图 | legacy | 2 / 2 / 0 | 7 | 通过 |
| local-card-128 | 0531_z_image_turbo | legacy | 4 / 2 / 0 | 14 | 通过 |
| local-card-129 | 0531z_image全量版本 | legacy | 2 / 2 / 0 | 10 | 通过 |
| local-card-130 | 1215Red-Z-Image+Detail去网红感真实文生图 | legacy | 3 / 1 / 0 | 8 | 通过 |
| local-card-134 | 图像调色 | legacy | 1 / 0 / 2 | 3 | 通过 |
| local-card-0 | 0811wan_animate2跳舞视频demo | generic | 7 / 3 / 2 | 11 | 通过 |
| local-card-4 | 0923最强minimax-h3-8step-私人参考生视频 | generic | 5 / 2 / 9 | 12 | 通过 |
| local-card-5 | 超强bernini去除字幕水印14B满血版 | generic | 4 / 2 / 1 | 8 | 通过 |
| local-card-6 | minimax-重生八零提示词优化版-分集001-片段018_a273f7ba | generic | 4 / 1 / 12 | 12 | 通过 |
| local-card-7 | h3面部修复 | generic | 5 / 1 / 2 | 7 | 通过 |
| local-card-8 | qwen3.8提示词反推润色 | generic | 1 / 2 / 0 | 1 | 通过 |
| local-card-22 | 0802【人物替换】Scail-2视频跳舞工作流  | generic | 8 / 2 / 2 | 11 | 通过 |
| local-card-23 | 0802【姿势迁移】Scail-2视频跳舞工作流  | generic | 7 / 2 / 2 | 11 | 通过 |
| local-card-24 | 0103人物替换姿势控制WanAnimate自定义背景 | generic | 6 / 3 / 3 | 11 | 通过 |
| local-card-25 | 0103人物替换姿势控制WanAnimate视频主体替换 | generic | 6 / 3 / 2 | 11 | 通过 |
| local-card-26 | 0103人物替换姿势控制WanAnimate视频姿势迁移 | generic | 6 / 2 / 2 | 11 | 通过 |
| local-card-27 | 0103人物替换姿势控制WanAnimate视频衣服修改 | generic | 6 / 3 / 2 | 11 | 通过 |
| local-card-28 | 0116最新wananimate视频人物替换官方for循环 | generic | 6 / 3 / 2 | 11 | 通过 |
| local-card-30 | 0427wananimate增强质量视频姿势迁移 | generic | 4 / 2 / 2 | 7 | 通过 |
| local-card-32 | grok4反推 | generic | 1 / 2 / 1 | 1 | 通过 |
| local-card-33 | 免费api反推-镜像专用-可以自己复制修改 | generic | 1 / 2 / 1 | 1 | 通过 |
| local-card-34 | 免费api提示词润色-支持自定义 | generic | 2 / 6 / 1 | 1 | 通过 |
| local-card-36 | Chatgpt-image2 图像生成 | generic | 7 / 2 / 1 | 29 | 通过 |
| local-card-37 | grok视频生成 | generic | 6 / 2 / 4 | 14 | 通过 |
| local-card-38 | nano-banana2 图像生成 | generic | 5 / 2 / 1 | 31 | 通过 |
| local-card-39 | 0608wan2.2Bernini 多惨生视频 | generic | 5 / 2 / 3 | 19 | 通过 |
| local-card-40 | 0608wan2.2Bernini 视频人物替换自动提示词版 | generic | 6 / 2 / 2 | 21 | 通过 |
| local-card-41 | 0629官方wan2.2bernini视频编辑 | generic | 4 / 2 / 2 | 10 | 通过 |
| local-card-43 | 0509ltx2.3视频编辑 | generic | 6 / 2 / 1 | 8 | 通过 |
| local-card-44 | 0510ltx2.3视频去模糊 | generic | 4 / 2 / 1 | 7 | 通过 |
| local-card-45 | 0510ltx2.3视频去水印字幕 | generic | 4 / 1 / 1 | 5 | 通过 |
| local-card-46 | 0511ltx2.3视频扩展 | generic | 7 / 1 / 1 | 12 | 通过 |
| local-card-48 | 0829ltx2.3视频编辑 | generic | 6 / 2 / 1 | 8 | 通过 |
| local-card-49 | 0902ltx视频衣服编辑工作流 | generic | 6 / 2 / 1 | 8 | 通过 |
| local-card-50 | EditAnythingLTX2.5 | generic | 7 / 2 / 1 | 15 | 通过 |
| local-card-51 | LTX2.3局部重绘工作流 | generic | 8 / 2 / 1 | 10 | 通过 |
| local-card-52 | 0923最强minimax-h3-8step-参考生视频 | generic | 5 / 2 / 9 | 12 | 通过 |
| local-card-53 | 0803minimax-h3-满血参考生视频对标sd2 | generic | 4 / 1 / 3 | 12 | 通过 |
| local-card-54 | 0803minimax-h3-满血图生视频 | generic | 4 / 2 / 1 | 5 | 通过 |
| local-card-55 | 0803minimax-h3-满血文生视频 | generic | 4 / 1 / 0 | 13 | 通过 |
| local-card-56 | 0803minimax-h3-满血首尾帧生视频 | generic | 3 / 1 / 2 | 5 | 通过 |
| local-card-57 | 0814最强minimax-h3-8step-首尾帧生视频 | generic | 4 / 1 / 2 | 5 | 通过 |
| local-card-58 | 0823最强minimax-h3-8step-文生视频 | generic | 4 / 1 / 0 | 13 | 通过 |
| local-card-59 | 0823最强minimax-h3-8step-视频编辑视频 | generic | 4 / 1 / 2 | 10 | 通过 |
| local-card-60 | 0916Minimax+H3模糊视频放大+纹理增强 | generic | 4 / 1 / 1 | 7 | 通过 |
| local-card-61 | 0918最强minimax视频换装衣服编辑 | generic | 5 / 1 / 2 | 7 | 通过 |
| local-card-62 | 0920minimax-h3-4step-参考生视频 | generic | 4 / 1 / 2 | 12 | 通过 |
| local-card-63 | 0920minimax-h3-4step-图生视频 | generic | 3 / 1 / 1 | 5 | 通过 |
| local-card-64 | 0920minimax-h3-4step-文生视频 | generic | 4 / 1 / 0 | 12 | 通过 |
| local-card-65 | 0920minimax-h3-4step-首尾帧视频 | generic | 3 / 1 / 2 | 5 | 通过 |
| local-card-66 | 0921最强minimax全能视频换脸 | generic | 5 / 1 / 2 | 7 | 通过 |
| local-card-67 | 0921最强minimax全能视频编辑 | generic | 5 / 1 / 2 | 7 | 通过 |
| local-card-68 | 0921最强minimax最强姿势参考 | generic | 5 / 1 / 2 | 7 | 通过 |
| local-card-69 | 0921最强minimax视频人物替换 | generic | 5 / 1 / 2 | 7 | 通过 |
| local-card-71 | 0823最强minimax-h3-8step-图生视频 | generic | 3 / 1 / 1 | 5 | 通过 |
| local-card-72 | 0111多角度人物道具场景视角加速版（九视角版本） | generic | 29 / 1 / 1 | 60 | 通过 |
| local-card-73 | 0427qwen2511换衣工作流 | generic | 2 / 1 / 1 | 6 | 通过 |
| local-card-75 | 0427多角度人物道具场景视角加速版 | generic | 20 / 7 / 1 | 42 | 通过 |
| local-card-76 | 1117qwen换头换脸工作流 | generic | 1 / 1 / 2 | 1 | 通过 |
| local-card-77 | Qwen-Edit-2511-一件场景生成 | generic | 3 / 2 / 1 | 6 | 通过 |
| local-card-79 | 0921qwenimage2.1一键套图写真 | generic | 6 / 2 / 1 | 13 | 通过 |
| local-card-80 | 1110动漫写真套图自由 | generic | 3 / 4 / 1 | 3 | 通过 |
| local-card-81 | 1110真人写真套图自由 | generic | 3 / 4 / 1 | 3 | 通过 |
| local-card-86 | 0802动漫anima局部重绘 | generic | 2 / 1 / 1 | 3 | 通过 |
| local-card-87 | 0802动漫anima深度生图 | generic | 1 / 1 / 1 | 1 | 通过 |
| local-card-88 | 0802动漫anima线稿生图 | generic | 1 / 1 / 1 | 1 | 通过 |
| local-card-89 | 动漫美图生成-多模型 | generic | 3 / 2 / 0 | 12 | 通过 |
| local-card-90 | 1119批量图像放大测试 | generic | 9 / 2 / 1 | 13 | 通过 |
| local-card-91 | wan图像放大-通用 | generic | 5 / 2 / 1 | 9 | 通过 |
| local-card-92 | 图像水印去除放大修复demo | generic | 6 / 3 / 1 | 11 | 通过 |
| local-card-93 | 0918qwen本地编辑图像工作流 | generic | 2 / 2 / 1 | 4 | 通过 |
| local-card-94 | Qwen-Rapid-AIO | generic | 1 / 2 / 1 | 1 | 通过 |
| local-card-95 | qwen2509meitu图像编辑工作流 | generic | 2 / 1 / 1 | 8 | 通过 |
| local-card-96 | qwen2511图像编辑工作流 | generic | 2 / 1 / 2 | 8 | 通过 |
| local-card-97 | qwen2511姿势参考工作流支持 | generic | 5 / 1 / 2 | 9 | 通过 |
| local-card-98 | (官方版)Wan2.2+S2V数字人骨骼驱动视频工作流V1 | generic | 4 / 2 / 3 | 5 | 通过 |
| local-card-99 | 0918infinite急速高质量数字人生成2.1图生视频 | generic | 4 / 2 / 2 | 3 | 通过 |
| local-card-100 | 0919infinite急速高质量数字人生成2.1视频生视频 | generic | 6 / 2 / 2 | 7 | 通过 |
| local-card-101 | 0923双人infinite急速高质量数字人生成2.1图生视频 | generic | 5 / 2 / 3 | 3 | 通过 |
| local-card-103 | 官方s2v | generic | 8 / 2 / 2 | 7 | 通过 |
| local-card-111 | zimage放大 | generic | 6 / 2 / 0 | 11 | 通过 |
| local-card-112 | klein-9b漫画本子一件去码上色 | generic | 2 / 2 / 2 | 1 | 通过 |
| local-card-113 | klein-9b漫画本子上色 | generic | 1 / 1 / 2 | 1 | 通过 |
| local-card-114 | klein-9b韩漫去白码 | generic | 2 / 1 / 2 | 8 | 通过 |
| local-card-115 | klein-9b黑白漫画去码 | generic | 1 / 1 / 1 | 1 | 通过 |
| local-card-116 | 0103人物替换姿势控制WanAnimate视频衣服修改 | generic | 6 / 3 / 2 | 11 | 通过 |
| local-card-117 | 0918最强minimax全能视频编辑 | generic | 5 / 1 / 2 | 7 | 通过 |
| local-card-118 | 视频flash放大-又快又好2倍 | generic | 4 / 0 / 1 | 5 | 通过 |
| local-card-119 | 视频flash放大-超长视频demo | generic | 4 / 0 / 1 | 5 | 通过 |
| local-card-120 | 视频flash放大-高动态高模糊4倍 | generic | 4 / 0 / 1 | 5 | 通过 |
| local-card-121 | 视频放大模型放大-适合清晰的 | generic | 2 / 0 / 1 | 3 | 通过 |
| local-card-122 | 0811seedvr2视频放大-1080p | generic | 4 / 0 / 1 | 5 | 通过 |
| local-card-123 | 0908flash放大长视频加速 | generic | 4 / 0 / 1 | 5 | 通过 |
| local-card-124 | 0427wan2.2多模型首尾帧 | generic | 2 / 2 / 2 | 3 | 通过 |
| local-card-125 | 0427最新ltx2_3首尾帧生视频 | generic | 6 / 2 / 2 | 10 | 通过 |
| local-card-126 | aio-mega-v11首尾帧 | generic | 4 / 2 / 2 | 7 | 通过 |
| local-card-131 | 测试版Z-Image-Turbo-Controlnet2+++Inpaint | generic | 2 / 1 / 1 | 3 | 通过 |
| local-card-133 | 一键去背景加白底图 | generic | 0 / 0 / 1 | 1 | 通过 |
| local-card-135 | 图片合成gif | generic | 5 / 0 / 0 | 12 | 通过 |
| local-card-136 | 视频批量加载 | generic | 10 / 0 / 0 | 15 | 通过 |

## 验证证据与边界

前端逐项审查覆盖 1,198 个变体，95 个通用合同的 849 个前端提交快照经后端校验全部通过。后端逐项审查覆盖 558 个控件、207 个文本入口、185 个素材入口和 15 个派生单位控件，共 2,475 次离线构建和 2,856 次非法输入拒绝。

本机后端完整回归 476 项：475 通过，1 项因 Windows 文件系统不允许符号链接而跳过。干净发布候选后端 476 项：468 通过，7 项缺少不公开的原始资料而跳过来源核验，另 1 项为相同符号链接限制；执行合同和公开模板检查仍正常运行。两套均无失败或错误，并阻断真实网络、使用临时数据库。前端回归 116 项全部通过，配置检查确认 151 个界面和 129 个执行模板齐备。

节点约束依据本机 2026-10-04 的节点定义。VisionAPIDirect 的实际抽帧行为仍需节点运行证据，相关内部参数保持原值并隐藏。此轮没有提交收费生成或真实收款，不代表远端全部模型当前可运行、全部输出质量或真实支付验收通过。

本机详细审查与回归日志保存在被 Git 忽略的 private/review81/ 和 private/review81-backend/；公开文件不包含任务编号、回执、账户数据库或凭据。发布版本标记为 public/version.json 的 0.81.1，使用 cache 81.0。
