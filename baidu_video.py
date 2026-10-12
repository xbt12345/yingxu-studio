"""Baidu VOD Seedance client for the two owner-supplied CSV configurations.

The VOD v3 Bearer authentication is documented by Baidu:
https://cloud.baidu.com/doc/VOD/s/Mmmleact0
The CSV provides the proxy routes and the exact upstream model versions. Its
``contents/generations/tasks`` route is implemented using the Ark task contract:
https://docs.volcengine.com/docs/ark/create-video-generation-task-api?lang=zh
https://docs.volcengine.com/docs/ark/get-video-generation-task-api?lang=zh
This compatibility has not been verified against Baidu's Seedance proxy.

Importing this module and checking availability never contacts a service. Only
explicit submit/query calls perform HTTP requests. Credentials stay server-side.
"""

import base64
import binascii
import json
import os
import re
from collections.abc import Mapping
from urllib.parse import urlsplit

import requests

from configuration import DATA_DIR


_BASE_URL = "https://vod.bj.baidubce.com"
_TASK_PATH = "/v3/aigc/seedance/api/v3/contents/generations/tasks"
_CONFIG_PATH = DATA_DIR / "baidu-video.json"
_TASK_ID = re.compile(r"^[A-Za-z0-9_-]{1,200}$")
_SAFE_CODE = re.compile(r"^[A-Za-z0-9_.-]{1,100}$")
_IMAGE_DATA_URL = re.compile(
    r"^data:image/(jpeg|jpg|png|webp|bmp|tiff|gif|heic|heif);base64,([A-Za-z0-9+/=\r\n]+)$"
)
_MAX_REQUEST_BYTES = 64 * 1024 * 1024
_MODELS = {
    "baidu-sd2": {
        "upstream": "doubao-seedance-2-0-260128",
        "qualities": ("480p", "720p", "1080p"),
        "default_quality": "720p",
        "max_duration": 15,
        "upstream_reference_limit": 9,
    },
    "baidu-sd2.5": {
        "upstream": "doubao-seedance-2-5-260628",
        "qualities": ("480p", "720p"),
        "default_quality": "480p",
        "max_duration": 30,
        # The product entry keeps the same conservative 9-image bound as SD2.
        # Ark documents 30 for SD2.5; the Baidu proxy limit is not verified.
        "upstream_reference_limit": 9,
    },
}


class BaiduVideoError(ValueError):
    """A safe user-facing request, configuration, or provider error."""


def _configuration():
    """Load private credentials without printing values or raw parse errors."""
    config = {}
    try:
        if _CONFIG_PATH.is_file():
            with _CONFIG_PATH.open("r", encoding="utf-8-sig") as handle:
                loaded = json.load(handle)
            if not isinstance(loaded, dict):
                raise BaiduVideoError("百度视频服务的本机配置格式有误。")
            config = loaded
    except (OSError, json.JSONDecodeError):
        raise BaiduVideoError("无法读取百度视频服务的本机配置。") from None
    # AK/SK can be retained for a separately documented v2 asset operation. They
    # are deliberately never substituted for a v3 Bearer API key.
    values = {
        "api_key": os.environ.get("BAIDU_VOD_API_KEY") or config.get("api_key"),
        "access_key": os.environ.get("BCE_ACCESS_KEY") or config.get("access_key"),
        "secret_key": os.environ.get("BCE_SECRET_KEY") or config.get("secret_key"),
    }
    return {key: value.strip() if isinstance(value, str) else "" for key, value in values.items()}


def _model_id(model):
    if isinstance(model, Mapping):
        model = model.get("model_id") or model.get("id") or model.get("model")
    return model if isinstance(model, str) else ""


def model_availability(model):
    """Report local configuration availability; this is not a live API check."""
    if _model_id(model) not in _MODELS:
        return {"available": False, "availability_reason": "未配置该百度视频模型。"}
    try:
        api_key = _configuration()["api_key"]
        if api_key.lower().startswith("bearer "):
            api_key = api_key[7:].strip()
        ready = bool(api_key) and not any(char in api_key for char in ("\r", "\n"))
    except BaiduVideoError as error:
        return {"available": False, "availability_reason": str(error)}
    return {
        "available": ready,
        "availability_reason": "" if ready else "请先配置百度视频生成服务的访问凭据。",
    }


def _audio_enabled(request):
    value = request.get("generate_audio", request.get("audio_mode", 1))
    if value in (True, 1, "1", "audio", "on"):
        return True
    if value in (False, 0, "0", "silent", "off"):
        return False
    raise BaiduVideoError("请选择有声或静音。")


def _reference_url(reference):
    if not isinstance(reference, Mapping):
        raise BaiduVideoError("参考图片格式有误。")
    source = reference.get("data_url") or reference.get("url")
    if not isinstance(source, str) or not source:
        raise BaiduVideoError("参考图片尚未准备完成。")
    if source.startswith("data:"):
        match = _IMAGE_DATA_URL.fullmatch(source)
        if not match:
            raise BaiduVideoError("参考素材必须是支持的图片格式。")
        try:
            image_bytes = base64.b64decode(re.sub(r"\s", "", match.group(2)), validate=True)
        except (ValueError, binascii.Error):
            raise BaiduVideoError("参考图片数据无法读取。") from None
        if not image_bytes or len(image_bytes) >= 30 * 1024 * 1024:
            raise BaiduVideoError("每张参考图片必须小于 30 MB。")
        return source
    parsed = urlsplit(source)
    if parsed.scheme not in ("http", "https") or not parsed.hostname or parsed.username or parsed.password:
        raise BaiduVideoError("参考图片需要可公开访问的图片链接。")
    return source


def validate_request(request, references=None):
    """Validate only the fields used by this integration; no service is called."""
    if not isinstance(request, Mapping):
        raise BaiduVideoError("视频生成参数格式有误。")
    model_id = _model_id(request.get("model_id") or request.get("model"))
    spec = _MODELS.get(model_id)
    if spec is None:
        raise BaiduVideoError("请选择已配置的百度视频模型。")
    prompt = request.get("prompt")
    if not isinstance(prompt, str) or not prompt.strip():
        raise BaiduVideoError("请填写视频描述。")
    quality = request.get("quality", request.get("resolution", spec["default_quality"]))
    if quality not in spec["qualities"]:
        raise BaiduVideoError("该模型不支持所选清晰度。")
    duration = request.get("duration", 5)
    if isinstance(duration, bool) or not re.fullmatch(r"\d+", str(duration)):
        raise BaiduVideoError("视频时长必须是整数秒。")
    duration = int(duration)
    if not 4 <= duration <= spec["max_duration"]:
        raise BaiduVideoError(f"该模型的视频时长为 4 至 {spec['max_duration']} 秒。")
    mode = request.get("mode", "text")
    if mode == "last_frame":
        # CSV lists a tail-frame enum, but the documented compatible contract
        # requires a first frame for strict last-frame control. Do not invent it.
        raise BaiduVideoError("当前接入契约尚未确认单独尾帧生视频，请使用首帧或参考图方式。")
    if mode not in ("text", "first_frame", "reference_image"):
        raise BaiduVideoError("该生成方式尚未接入。")
    follows_first_frame = model_id == "baidu-sd2.5" and mode == "first_frame"
    ratio = request.get("ratio", "adaptive" if follows_first_frame else "16:9")
    if follows_first_frame:
        if ratio != "adaptive":
            raise BaiduVideoError("SD2.5 首帧方式的画幅必须跟随首帧图片。")
    elif ratio not in ("16:9", "9:16"):
        raise BaiduVideoError("请选择 16:9 或 9:16 画幅。")
    references = references if references is not None else []
    if not isinstance(references, (list, tuple)):
        raise BaiduVideoError("参考图片列表格式有误。")
    if mode == "text" and references:
        raise BaiduVideoError("文生视频方式不使用参考图片。")
    if mode == "first_frame" and len(references) != 1:
        raise BaiduVideoError("首帧方式需要一张首帧图片。")
    if mode == "first_frame" and isinstance(references[0], Mapping) and references[0].get("slot") not in (None, 0):
        raise BaiduVideoError("请将参考图片放在首帧位置。")
    if mode == "reference_image" and not references:
        raise BaiduVideoError("请添加参考图片。")
    # SD2's upstream bound is also this entry's conservative bound for SD2.5;
    # neither is presented as a tested Baidu proxy capacity.
    if mode == "reference_image" and len(references) > spec["upstream_reference_limit"]:
        raise BaiduVideoError(f"当前入口最多接收 {spec['upstream_reference_limit']} 张参考图片。")
    normalized = {
        "model_id": model_id, "prompt": prompt.strip(), "quality": quality,
        "duration": duration, "ratio": ratio, "mode": mode,
        "generate_audio": _audio_enabled(request),
        "reference_urls": [_reference_url(item) for item in references],
    }
    return normalized


def build_payload(request, references=None):
    """Build the owner-configured Ark-compatible request without credentials."""
    selected = validate_request(request, references)
    spec = _MODELS[selected["model_id"]]
    content = [{"type": "text", "text": selected["prompt"]}]
    role = "first_frame" if selected["mode"] == "first_frame" else "reference_image"
    content.extend({"type": "image_url", "image_url": {"url": source}, "role": role}
                   for source in selected["reference_urls"])
    payload = {
        "model": spec["upstream"], "content": content,
        "resolution": selected["quality"], "duration": selected["duration"],
        "ratio": selected["ratio"], "generate_audio": selected["generate_audio"],
    }
    if len(json.dumps(payload, ensure_ascii=False).encode("utf-8")) > _MAX_REQUEST_BYTES:
        raise BaiduVideoError("参考图片合计过大，请减少图片或使用较小的图片。")
    return payload


def _request(method, path, payload=None):
    api_key = _configuration()["api_key"]
    if not api_key or any(char in api_key for char in ("\r", "\n")):
        raise BaiduVideoError("百度视频生成服务的访问凭据未配置或格式有误。")
    if api_key.lower().startswith("bearer "):
        api_key = api_key[7:].strip()
    if not api_key:
        raise BaiduVideoError("百度视频生成服务的访问凭据未配置或格式有误。")
    headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
    try:
        response = requests.request(method, _BASE_URL + path, headers=headers,
                                    json=payload, timeout=(10, 90), allow_redirects=False)
    except requests.RequestException:
        # A timeout can happen after a paid task was created. The caller must
        # preserve its reservation and reconcile instead of treating it as a
        # confirmed rejection or automatically submitting again.
        raise requests.RequestException("百度视频服务连接中断，任务是否创建尚待确认。") from None
    try:
        result = response.json()
    except (ValueError, requests.exceptions.JSONDecodeError):
        if method == "POST" and 400 <= response.status_code < 500:
            raise BaiduVideoError(f"百度视频生成服务拒绝请求（HTTP {response.status_code}）。") from None
        raise requests.RequestException("百度视频服务响应无法识别，任务状态尚待确认。") from None
    if not 200 <= response.status_code < 300:
        code = result.get("code") if isinstance(result, dict) else None
        if isinstance(result, dict) and isinstance(result.get("error"), dict):
            code = result["error"].get("code", code)
        suffix = f"，代码 {code}" if isinstance(code, str) and _SAFE_CODE.fullmatch(code) else ""
        # Do not expose raw provider messages, request bodies, or credentials.
        message = f"百度视频生成服务返回 HTTP {response.status_code}{suffix}。"
        if method == "POST" and 400 <= response.status_code < 500:
            raise BaiduVideoError(message)
        # For a GET even 404/403 does not establish the generation's outcome.
        # Do not attach response/prepared-request objects containing secrets.
        raise requests.HTTPError(message)
    if not isinstance(result, dict):
        raise requests.RequestException("百度视频服务返回格式与当前接入契约不符，任务状态尚待确认。")
    return result


def submit(payload):
    """Submit once. Automatic retry could create duplicate paid generations."""
    if not isinstance(payload, dict) or payload.get("model") not in {s["upstream"] for s in _MODELS.values()}:
        raise BaiduVideoError("视频生成请求缺少有效模型。")
    result = _request("POST", _TASK_PATH, payload)
    task_id = result.get("id")
    if not isinstance(task_id, str) or not _TASK_ID.fullmatch(task_id):
        raise requests.RequestException("百度视频服务未返回符合当前契约的任务编号，创建结果尚待确认。")
    return task_id


def query(task_id):
    """Read a task once and normalize only documented status/result fields."""
    if not isinstance(task_id, str) or not _TASK_ID.fullmatch(task_id):
        raise BaiduVideoError("视频任务编号格式有误。")
    result = _request("GET", _TASK_PATH + "/" + task_id)
    upstream_status = result.get("status")
    statuses = {"queued": "queued", "running": "running", "succeeded": "done",
                "failed": "failed", "expired": "failed", "cancelled": "failed"}
    if upstream_status not in statuses:
        raise requests.RequestException("百度视频任务状态与当前接入契约不符，结果尚待确认。")
    normalized = {"status": statuses[upstream_status], "video_url": None, "error": None}
    if upstream_status == "succeeded":
        content = result.get("content")
        video_url = content.get("video_url") if isinstance(content, dict) else None
        parsed = urlsplit(video_url) if isinstance(video_url, str) else None
        if parsed is None or parsed.scheme not in ("http", "https") or not parsed.hostname:
            raise requests.RequestException("任务已完成，但百度服务未返回符合当前契约的视频地址，请继续核对结果。")
        normalized["video_url"] = video_url
    elif upstream_status in ("failed", "expired", "cancelled"):
        messages = {"failed": "百度视频生成任务失败。", "expired": "百度视频生成任务已超时。",
                    "cancelled": "百度视频生成任务已取消。"}
        normalized["error"] = messages[upstream_status]
    usage = result.get("usage")
    if isinstance(usage, dict):
        normalized["usage"] = {key: value for key, value in usage.items()
                               if key in ("completion_tokens", "total_tokens")
                               and isinstance(value, (int, float)) and not isinstance(value, bool)}
    return normalized
