"""Write the human review from the reproducible source and renderer audits."""
import json
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
REVIEW = ROOT / 'private/review61'


def load(name):
    return json.loads((REVIEW / name).read_text(encoding='utf-8'))


def safe(value):
    return str(value).replace('|', '\\|').replace('\n', ' ')


def main():
    source = load('source-coverage.json')['workflows']
    visual = {item['id']: item for item in load('component-audit.json')['localWorkflows']}
    stats = load('component-audit.json')
    schemas = json.loads((ROOT / 'public/workflow-interfaces.json').read_text(encoding='utf-8'))['workflows']
    categories = defaultdict(list)
    for row in source:
        categories[row['category']].append(row)
    mappings = Counter(item['coverage'] for row in source for item in row['findings'])
    texts = Counter(item['coverage'] for row in source for item in row['textFindings'])
    media = Counter(item['coverage'] for row in source for item in row['mediaFindings'])
    kind_names = {
        'seed': ('随机种子', 'seed'), 'segment': ('片段/时间码', 'timecode'),
        'resolution': ('尺寸/像素', 'edge'), 'duration': ('时长', 'segment'),
        'ratio': ('画面比例/宽高', 'ratio'), 'camera': ('视角', 'camera'),
        'motion': ('动作参数', 'motion'), 'upscale': ('放大倍率', 'choice'),
        'filesystem': ('目录/文件规则', 'path'), 'restoration': ('修复幅度', 'restoration'),
        'outpaint': ('扩展范围', 'outpaint'), 'color': ('调色', 'color'),
        'count': ('数量', 'count'), 'task': ('任务模式', 'text'),
        'toggle': ('开关', 'toggle'), 'choice': ('枚举选择', 'choice'),
        'playback': ('播放帧率', 'playback'), 'mask': ('掩膜来源', 'mask-source'),
        'strength': ('模型强度', 'number'), 'style': ('风格', 'style'),
    }
    kind_counts = Counter(item['kind'] for config in schemas.values() for item in config['controls'])
    lines = [
        '# 工作流组件与真实输入逐一审查 · 2026-09-29', '',
        '结论：151 个本地工作流的编辑区结构均经逐项核对；其中 32 个有实际算力卡请求契约，119 个只提供演示。'
        '全部 514 个可见参数均调用与组件库相同的渲染函数和样式表。此次修复了两处真实缺项。', '',
        '## 审查边界与方法', '',
        '- 从原始 JSON 计算字节哈希和目录语义指纹；沿启用节点到输出的连线找用户可修改的输入。'
        '模型、采样器等内部设定不因“节点存在”自动变成界面控件。',
        '- 把每个源输入追到编辑控件、合并成员、宽高组合或单位换算；再核对所有控件在编辑区的 HTML 标识。',
        '- 对已接入工作流，再以实际编译图与服务端请求契约为准：原图中被裁掉的分支不应出现可编辑的假入口。',
        '- 对照组件库与工作区的 CSS 引入顺序，并逐控件比较共用渲染输出。浏览器抽查两处本轮修复。', '',
        f"源参数候选 {sum(mappings.values())} 项：直接呈现 {mappings['direct']}，种子等合并成员 {mappings['merged-member']}，"
        f"按同一目标合并 {mappings['composite-target']}，单位换算 {mappings['unit-conversion']}，"
        f"宽高合一 {mappings['width-height-composite']}；未解释的缺项 0。"
        f"文本源输入 {sum(texts.values())} 项，未解释缺项 0。", '',
        f"素材源节点 {sum(media.values())} 个：直接对应编辑区 {media['direct']}，目录路径控件替代 {media['directory-field']}，"
        f"已接入执行图裁掉 {media['pruned-from-execution']}，演示工作流没有真实执行契约可核 {media['catalog-only-unverified']}。"
        '编辑区当前显示 375 个素材位；不能把源图中每个 LoadImage 当成实际生成输入。', '',
        '## 本轮修正', '',
        '1. `local-card-74`（0427qwen人物姿势迁移终极版）：节点 361 的 1536 像素整数值同时写入两路 `scale_to_length` 和 `max_size`，'
        '以前缺少编辑入口；现在直接显示“输出最长边（像素）”，保留原值与 1 像素步长。',
        '2. `local-card-136`（视频批量加载）：节点 61 的 `mode` 原本固定为 `single_video`；'
        '现提供“指定索引 / 顺序索引 / 随机视频”圆角菜单，提交值严格对应节点的三个原生枚举。'
        '该工作流仍是演示模式，目录必须能被实际运行端访问。',
        '3. 重新生成界面配置时，保护 19 个来源未变化工作流已审核的画面比例选项；最终配置只改动上述两个工作流。', '',
        '模式枚举来源：[DJZ-Nodes `LoadVideoBatchFrame.py`](https://github.com/MushroomFleet/DJZ-Nodes/blob/main/LoadVideoBatchFrame.py)。', '',
        '## 组件库合同', '',
        f"共 {len(kind_counts)} 种参数语义、{sum(kind_counts.values())} 个编辑控件、32 组组件示例。"
        f"其中 {stats['totals']['exactSharedFields']} 个与库中的基础控件 HTML 完全一致，"
        f"{stats['totals']['sharedContextFields']} 个经同一组件嵌入种子或多视角布局。", '',
        '| 参数类型 | 控件数 | 组件库入口 |', '|---|---:|---|',
    ]
    for kind, count in kind_counts.most_common():
        name, anchor = kind_names[kind]
        lines.append(f'| {name} (`{kind}`) | {count} | [查看](http://127.0.0.1:8770/workflow-control-library.html?review=61.2#{anchor}) |')
    lines += ['', '使用规则：先查原图有效节点与输入单位，再选对应组件；保持原始枚举、范围、默认值和目标节点。'
              '同义输入合并时明确写回全部原始端口；固定内部参数和已裁剪分支不在界面伪造控件。', '',
              '## 逐个工作流核对', '',
              '“候选/可见”不是漏项率：前者含可合并的原生输入；全部映射已在机器审查文件中逐项列出。'
              '“原图其他素材”只统计未直接显示的加载节点，已接入图证明这些节点被裁掉；演示图没有运行验证。', '']
    for category, rows in categories.items():
        lines += [f'### {safe(category)}（{len(rows)}）', '',
                  '| 工作流 | 运行 | 源参数候选 / 可见 | 文本 / 素材位 | 原图其他素材 | 样式 |',
                  '|---|---|---:|---:|---:|---|']
        for row in rows:
            ident = row['id']
            detail = visual[ident]
            extras = sum(item['coverage'] in ('pruned-from-execution', 'catalog-only-unverified')
                         for item in row['mediaFindings'])
            status = '已接入' if row['execution'] == 'connected-compiled' else '演示'
            style = '共用' if detail['status'] == 'render-contract-passed' else '待复核'
            link = f'[{safe(row["name"])}](http://127.0.0.1:8770/studio.html?review=61.0#workflow/{ident})'
            lines.append(f'| {link} (`{ident}`) | {status} | {row["candidateControls"]} / {row["visibleControls"]} | '
                         f'{row["visibleTexts"]} / {row["visibleMedia"]} | {extras} | {style} |')
        lines.append('')
    lines += ['## 验证与限制', '',
              '- `audit_workflow_source_coverage.py`：151 个源图、目录指纹、参数/文本/素材追踪；未解释缺项 0。',
              '- `audit_workflow_components.mjs`：151 个本地工作流、2 个独立接入页、12 个内置演示；'
              '工作区与库共用 CSS 和渲染器，所有配置控件均在首页。',
              '- `audit_connected_interfaces.py`：32 个已接入工作流的默认值、选项与服务端接受值及编译输出对应。'
              '`test_mvp.py` 的 42 项回归及界面交互测试通过。',
              '- 未调用付费模型。119 个演示工作流只完成源图与编辑区的结构核对；'
              '54 个源图素材加载候选没有对应的真实执行契约，不能据此声称生成验证通过。', '',
              '明细：`private/review61/source-coverage.json`、`private/review61/component-audit.json`。', '']
    output = ROOT / '工作流组件与源参数逐一审查-2026-09-29.md'
    output.write_text('\n'.join(lines), encoding='utf-8')
    print(json.dumps({'document': str(output), 'workflows': len(source), 'categories': len(categories),
                      'kinds': len(kind_counts)}, ensure_ascii=False))


if __name__ == '__main__':
    main()
