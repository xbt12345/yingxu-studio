"""Password gate for an invited, shared studio; this is not per-user isolation."""
import base64
import binascii
import ipaddress
import json
import os
from pathlib import Path
import secrets
from urllib.parse import urlsplit

from fastapi.responses import JSONResponse


def access_denied(path, authorization):
    # Railway probes this route without credentials or a running GPU service.
    if path == '/healthz':
        return None
    password = os.environ.get('YINGXU_ACCESS_PASSWORD', '')
    railway = bool(os.environ.get('RAILWAY_ENVIRONMENT_ID') or os.environ.get('RAILWAY_PUBLIC_DOMAIN'))
    if not password and not railway:
        return None
    username = os.environ.get('YINGXU_ACCESS_USERNAME', 'yingxu')
    if len(password) < 16 or not username or ':' in username:
        return JSONResponse(
            {'detail': '请在服务器设置至少 16 位的网站访问密码 YINGXU_ACCESS_PASSWORD，再重新部署。'},
            status_code=503, headers={'Cache-Control': 'no-store'},
        )
    try:
        scheme, encoded = (authorization or '').split(' ', 1)
        if scheme.lower() != 'basic':
            raise ValueError('Unsupported authorization')
        supplied_user, supplied_password = base64.b64decode(encoded, validate=True).decode('utf-8').split(':', 1)
        user_matches = secrets.compare_digest(supplied_user.encode('utf-8'), username.encode('utf-8'))
        password_matches = secrets.compare_digest(supplied_password.encode('utf-8'), password.encode('utf-8'))
        if user_matches and password_matches:
            return None
    except (ValueError, binascii.Error, UnicodeError):
        pass
    return JSONResponse(
        {'detail': '请使用网站访问账号和密码登录。'}, status_code=401,
        headers={'WWW-Authenticate': 'Basic realm="YINGXU Studio", charset="UTF-8"', 'Cache-Control': 'no-store'},
    )


def railway_origin():
    """Trust Railway's configured domain, never a caller-controlled Host header."""
    domain = os.environ.get('RAILWAY_PUBLIC_DOMAIN', '').strip()
    try:
        parsed = urlsplit('https://' + domain)
    except ValueError:
        return None
    if (domain and parsed.hostname == domain.lower() and parsed.netloc == domain
            and not parsed.path and not parsed.query and not parsed.fragment and not parsed.username):
        return 'https://' + domain.lower()
    return None


def _origin(value):
    """Normalize a complete origin, never a URL with credentials or a path."""
    if not isinstance(value, str) or any(char.isspace() for char in value):
        return None
    try:
        parsed = urlsplit(value)
        if (parsed.scheme not in ('http', 'https') or not parsed.hostname
                or parsed.username is not None or parsed.password is not None
                or parsed.path not in ('', '/') or parsed.query or parsed.fragment):
            return None
        host = parsed.hostname.lower()
        if ':' in host:
            host = '[' + host + ']'
        port = parsed.port
        if port is not None and port != {'http':80, 'https':443}[parsed.scheme]:
            host += ':' + str(port)
        return parsed.scheme + '://' + host
    except ValueError:
        return None


def trusted_origins(request, private_dir):
    """Share one configured browser-origin policy across both HTTP guards.

    A caller-controlled Host or proxy header never adds an external origin.
    Loopback origins use the request's actual scheme/port, including IPv6.
    """
    allowed = {origin for item in os.environ.get('YINGXU_ALLOWED_ORIGINS', '').split(',')
               if (origin := _origin(item.strip()))}
    canonical = railway_origin()
    if canonical:
        allowed.add(canonical)
    else:
        host = request.url.hostname or ''
        try:
            loopback = host == 'localhost' or ipaddress.ip_address(host).is_loopback
        except ValueError:
            loopback = host == 'localhost'
        if loopback and (origin := _origin(str(request.base_url))):
            allowed.add(origin)
    try:
        configured = json.loads((Path(private_dir) / 'access.json').read_text('utf-8-sig'))
        origin = _origin(configured.get('origin', ''))
        if origin and origin.startswith('https://') and urlsplit(origin).hostname.endswith('.ts.net'):
            allowed.add(origin)
    except (OSError, ValueError, AttributeError):
        pass
    return allowed
