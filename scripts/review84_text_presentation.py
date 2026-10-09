"""Source-checked presentation of internal rules and independent text branches."""
from copy import deepcopy

CONTRACTS = {'local-card-4': {'hash': '204e1f8d6eccd1995721ee8f1281a57edd0ee3b86af2edef33ba64bd2afa3549', 'hidden': ['187:value'], 'labels': {}}, 'local-card-52': {'hash': '5be77a076e8ec3988556a8259499661c6fca728e4a809c093cb6994b3f59ed1b', 'hidden': ['187:value'], 'labels': {}}, 'local-card-54': {'hash': '47fe1f8301a17197c7b06a089ac61c97e22310651a496bd69df50c1500c41446', 'hidden': ['159:value'], 'labels': {}}, 'local-card-70': {'hash': 'a0c1328c98d930ec8a3b5159e819bdf78bd4fb5caa0b64b7a6ea01ce607cf638', 'hidden': ['243:value'], 'labels': {}}, 'local-local-146c03e248': {'hash': 'dba2d89d3efc3a62d1e0b157d91b0cf61409dc0e2484a14c9f7609999e16a028', 'hidden': ['266:value'], 'labels': {}}, 'local-local-4c6bbc5889': {'hash': '803d88d3ce37a652ebd634434b5d5e4398fb2a5cdceae5b09ced6ac1ec56fd4c', 'hidden': ['266:value'], 'labels': {}}, 'local-local-f34886485b': {'hash': '848b9af11291c38dc60be13eec1df71d40d6adb8914f352a9348435ef9946c2d', 'hidden': ['266:value'], 'labels': {}}, 'local-local-9c7926856d': {'hash': '46c8fb942b445f27e429653e48372d7f7264c895969c717a9d729c76dc119a21', 'hidden': ['266:value'], 'labels': {}}, 'local-local-1c7dacb53c': {'hash': '853e9402e6508f907ff15719ba36f525cde16c56608aeaf9695d24d287b7bdb0', 'hidden': ['266:value'], 'labels': {}}, 'local-local-c4125e5345': {'hash': '5f391c4ca3842ae9ed21f8eea28d86b2a208a4ad6355981e54fe958a4889c3c5', 'hidden': ['288:value'], 'labels': {}}, 'local-local-98c13b4732': {'hash': 'fc502d3e22a873ee56a02f50d9b2cab29e11aa6452bba399eef1d5625bbc26b0', 'hidden': ['288:value'], 'labels': {}}, 'local-card-34': {'hash': '7e42310611fd39b2591be056ba5795a9620b4a436fa127ddc6821f67772bc537', 'hidden': [], 'labels': {'1479:text': '文字分支 · 用户描述', '1488:text': '文字分支 · 扩写指令', '1514:prompt': '文字分支 · 补充要求', '1520:text': '图片分支 · 用户描述', '1518:text': '图片分支 · 扩写指令', '1525:prompt': '图片分支 · 补充要求'}}, 'local-card-75': {'hash': '0eb7da0d8c7d97d59a093d361c0eb357222fbca0e1423eb9459137df960b7945', 'hidden': [], 'labels': {'6:text': '视角 1 · 不希望出现的内容', '57:text': '视角 2 · 不希望出现的内容', '87:text': '视角 3 · 不希望出现的内容', '107:text': '视角 4 · 不希望出现的内容', '117:text': '视角 5 · 不希望出现的内容', '97:text': '视角 6 · 不希望出现的内容'}}}

def reviewed_text_presentation(workflow, texts, *, source_hash=None):
    contract = CONTRACTS.get(workflow['id'])
    if contract is None:
        return texts
    if source_hash != contract['hash']:
        raise ValueError('工作流文本用途的原始来源已改变，需要重新审查。')
    result = [deepcopy(field) for field in texts if field['id'] not in contract['hidden']]
    for field in result:
        if field['id'] in contract['labels']:
            field['label'] = contract['labels'][field['id']]
    return result
