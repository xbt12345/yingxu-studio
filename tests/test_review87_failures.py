import ast
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
def actual_friendly():
    tree=ast.parse((ROOT/'server.py').read_text(encoding='utf-8'))
    node=next(n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name=='friendly')
    scope={}
    exec(compile(ast.Module(body=[node],type_ignores=[]),'actual-friendly','exec'),scope)
    return scope['friendly']

def test_birefnet_failure_names_dependency_without_recommending_parameter_changes():
    failure="Repo id must be in the form repo_name: /root/synthetic/models/BiRefNet-General"
    result=actual_friendly()(failure)
    assert 'BiRefNet-General' in result and '模型' in result and '原图已保留' in result
    assert '/root/' not in result and '参数' not in result

def test_different_model_or_general_runtime_errors_keep_their_existing_classification():
    friendly=actual_friendly()
    assert friendly('CUDA out of memory').startswith('显存不足')
    assert friendly('model not found').startswith('算力卡缺少')
    assert friendly('Repo id must be in the form repo_name: invalid').startswith('工作流执行失败')
    assert friendly('connection timeout').startswith('暂时无法连接')
