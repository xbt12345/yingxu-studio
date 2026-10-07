"""Read-only reference quotes; account charges remain in PlatformAccounts.

Only the public tariff whitelist is exposed. Missing or invalid configuration
disables model reference quotes instead of inventing a free price.
"""
from decimal import Decimal, InvalidOperation, ROUND_CEILING
import json
from pathlib import Path
from urllib.parse import urlsplit


POLICY_PATH = Path(__file__).resolve().parent / 'public' / 'pricing-policy.json'
CREDIT_POLICY = {'currency': 'CNY', 'credits_per_yuan': 100, 'rounding': 'ceil_to_fen'}
MODEL_CAPABILITIES = {
    'seedream-4.5': {'kind': 'image', 'qualities': ['1K', '1.5K', '2K']},
    'flux-2-pro': {'kind': 'image', 'qualities': ['1K', '1.5K', '2K']},
    'seedance-2.0': {'kind': 'video', 'qualities': ['480p', '720p', '1080p'], 'durations': {'min': 4, 'max': 15}},
    'veo-3.1': {'kind': 'video', 'qualities': ['480p', '720p', '1080p'], 'durations': [4, 6, 8]},
}
UNAVAILABLE = '参考费率尚未配置或配置暂不可用。'
REFERENCE_LABEL = '生成费用预估'
CREATION_UNAVAILABLE = '该模型尚未接入生成服务，暂不能生成。'


class PricingValidationError(ValueError):
    """The request contradicts the model's supported controls."""


def _text(value, maximum=500):
    return value[:maximum] if isinstance(value, str) else ''


def _price(value):
    if isinstance(value, bool) or not isinstance(value, (int, float, str)):
        raise ValueError('invalid unit price')
    try:
        amount = Decimal(str(value))
    except InvalidOperation as error:
        raise ValueError('invalid unit price') from error
    if not amount.is_finite() or amount <= 0 or amount > 1_000_000:
        raise ValueError('invalid unit price')
    return amount


def _fallback():
    return {'credit_policy': dict(CREDIT_POLICY), 'creation_pricing': {
        'mode': 'reference', 'label': REFERENCE_LABEL,
        'models': {identifier: {'kind': cap['kind'], 'configured': False, 'reason': UNAVAILABLE,
                               'available': False, 'availability_reason': CREATION_UNAVAILABLE}
                   for identifier, cap in MODEL_CAPABILITIES.items()}}}


def load_pricing_policy(path=None):
    """Load bounded, explicitly public fields; never return arbitrary file keys."""
    result = _fallback()
    try:
        file = Path(path) if path is not None else POLICY_PATH
        if file.stat().st_size > 256_000:
            return result
        data = json.loads(file.read_text(encoding='utf-8'))
        credit = data['credit_policy']
        if (not isinstance(credit, dict) or credit.get('currency') != 'CNY'
                or type(credit.get('credits_per_yuan')) is not int
                or credit['credits_per_yuan'] != 100
                or credit.get('rounding') != 'ceil_to_fen'):
            return result
        raw_models = data['creation_pricing']['models']
        if not isinstance(raw_models, dict):
            return result
    except (OSError, ValueError, TypeError, KeyError):
        return result
    for identifier, cap in MODEL_CAPABILITIES.items():
        raw = raw_models.get(identifier)
        if not isinstance(raw, dict) or raw.get('kind') != cap['kind']:
            continue
        model = result['creation_pricing']['models'][identifier]
        if raw.get('configured') is not True:
            model['reason'] = _text(raw.get('reason')) or UNAVAILABLE
            continue
        try:
            if cap['kind'] == 'image':
                if raw.get('unit') != 'image':
                    raise ValueError('invalid image tariff')
                if 'quality_amount_minor' in raw:
                    prices = raw['quality_amount_minor']
                    if ('amount_minor' in raw or not isinstance(prices, dict) or not prices
                            or any(q not in cap['qualities'] for q in prices)):
                        raise ValueError('invalid image quality tariff')
                    model.update(unit='image', quality_amount_minor={q: str(_price(p)) for q, p in prices.items()})
                else:
                    price = _price(raw['amount_minor'])
                    qualities = raw.get('qualities')
                    if (price != price.to_integral_value() or not isinstance(qualities, list) or not qualities
                            or any(q not in cap['qualities'] for q in qualities)):
                        raise ValueError('invalid image qualities or tariff')
                    model.update(unit='image', amount_minor=int(price), qualities=list(dict.fromkeys(qualities)))
            else:
                prices = raw['quality_amount_minor']
                if raw.get('unit') != 'second' or not isinstance(prices, dict) or not prices:
                    raise ValueError('invalid video tariff')
                if any(q not in cap['qualities'] for q in prices):
                    raise ValueError('invalid video qualities')
                sanitized_prices = {q: str(_price(p)) for q, p in prices.items()}
                durations = raw['durations']
                if isinstance(durations, dict):
                    if (type(durations.get('min')) is not int or type(durations.get('max')) is not int
                            or not 4 <= durations['min'] <= durations['max'] <= 15):
                        raise ValueError('invalid video duration range')
                    safe_durations = {'min': durations['min'], 'max': durations['max']}
                elif (isinstance(durations, list) and durations
                      and all(type(n) is int and 4 <= n <= 15 for n in durations)):
                    safe_durations = sorted(set(durations))
                else:
                    raise ValueError('invalid video durations')
                model.update(unit='second', quality_amount_minor=sanitized_prices, durations=safe_durations)
            model.update(configured=True)
            model.pop('reason', None)
            for name in ('source', 'verified_on', 'scope'):
                if _text(raw.get(name)):
                    model[name] = _text(raw[name])
            source_url = _text(raw.get('source_url'), 1500)
            parsed = urlsplit(source_url)
            if parsed.scheme == 'https' and parsed.netloc and not parsed.username and not parsed.password:
                model['source_url'] = source_url
        except (ValueError, TypeError, KeyError):
            # Reject the entire model tariff, including any partial update.
            result['creation_pricing']['models'][identifier] = {
                'kind': cap['kind'], 'configured': False, 'reason': UNAVAILABLE,
                'available': False, 'availability_reason': CREATION_UNAVAILABLE}
    return result


def _validate_request(model, kind, quality, count, duration):
    if kind not in ('image', 'video'):
        raise PricingValidationError('请选择图像或视频生成。')
    if type(count) is not int or not 1 <= count <= 8:
        raise PricingValidationError('图像数量须为 1 至 8 张。')
    if kind == 'image' and duration is not None:
        raise PricingValidationError('图像生成不需要视频时长。')
    if kind == 'video' and (count != 1 or type(duration) is not int or not 4 <= duration <= 15):
        raise PricingValidationError('视频须为 1 个，时长须为 4 至 15 秒的整数。')
    cap = MODEL_CAPABILITIES.get(model)
    if cap:
        if cap['kind'] != kind:
            raise PricingValidationError('模型与创作类型不匹配。')
        if quality not in cap['qualities']:
            raise PricingValidationError('请选择该模型支持的画质。')
        if kind == 'video' and isinstance(cap.get('durations'), list) and duration not in cap['durations']:
            raise PricingValidationError('请选择该模型支持的视频时长。')


def creation_quote(model, kind, quality, count, duration, policy=None):
    _validate_request(model, kind, quality, count, duration)
    policy = load_pricing_policy() if policy is None else policy
    credit = dict(policy['credit_policy'])
    quoted = {'model': model, 'kind': kind, 'quality': quality, 'count': count,
              'duration': duration, 'configured': False, 'credits': None,
              'amount_minor': None, 'currency': credit['currency'], 'mode': 'reference',
              'label': REFERENCE_LABEL, 'credit_policy': credit,
              'available': False, 'availability_reason': CREATION_UNAVAILABLE}
    tariff = policy['creation_pricing']['models'].get(model)
    if not tariff or not tariff.get('configured'):
        quoted['reason'] = tariff.get('reason', UNAVAILABLE) if tariff else '该模型参考费率待核实。'
        return quoted
    if kind == 'image':
        if 'quality_amount_minor' in tariff:
            unit = tariff['quality_amount_minor'].get(quality)
        else:
            unit = tariff['amount_minor'] if quality in tariff['qualities'] else None
        if unit is None:
            quoted['reason'] = '该画质参考费率待核实。'
            return quoted
        total = Decimal(unit) * count
    else:
        durations = tariff['durations']
        if ((isinstance(durations, list) and duration not in durations)
                or (isinstance(durations, dict) and not durations['min'] <= duration <= durations['max'])):
            raise PricingValidationError('该时长暂未配置参考费率。')
        unit = tariff['quality_amount_minor'].get(quality)
        if unit is None:
            quoted['reason'] = '该画质参考费率待核实。'
            return quoted
        total = Decimal(unit) * duration
    amount_minor = int(total.to_integral_value(rounding=ROUND_CEILING))
    # Convert the rounded total only once: 100 confirmed credits equal 1 yuan.
    credits = int((Decimal(amount_minor) * credit['credits_per_yuan'] / 100)
                  .to_integral_value(rounding=ROUND_CEILING))
    quoted.update(configured=True, credits=credits, amount_minor=amount_minor)
    return quoted


def enrich_workflow_quote(quote, policy=None):
    policy = load_pricing_policy() if policy is None else policy
    credit = dict(policy['credit_policy'])
    result = {**quote, 'credit_policy': credit, 'currency': credit['currency']}
    if quote['configured']:
        result['amount_minor'] = int((Decimal(quote['credits']) * 100 / credit['credits_per_yuan'])
                                     .to_integral_value(rounding=ROUND_CEILING))
    return result
