"""Authenticated torrent retrieval and bounded metainfo validation.

HTTP RSS enclosures are downloaded by MoviePilot, then submitted as bytes to
qB. A computed infohash is only an expected identity, never an add confirmation.
"""
from __future__ import annotations
import base64
import hashlib
import math
import re
import time
from urllib.parse import parse_qsl, urlencode, urljoin, urlsplit, urlunsplit

MAX_TORRENT_BYTES = 8 * 1024 * 1024


class TorrentTransportError(ValueError):
    """Contains only a safe error category, not a response body or secret URL."""


def metainfo(raw):
    """Hash the original bencoded info slice, not a lossy decode/re-encode."""
    if not isinstance(raw, bytes) or not raw or len(raw) > MAX_TORRENT_BYTES:
        raise TorrentTransportError('种子文件为空或超过8 MiB限制')
    if raw[:1] != b'd':
        raise TorrentTransportError('下载结果不是torrent文件（可能是登录页、验证页或错误响应）')
    pos, nodes = 0, 0
    info_span = None

    def parse(depth=0):
        nonlocal pos, nodes, info_span
        nodes += 1
        if depth > 50 or nodes > 200000 or pos >= len(raw):
            raise ValueError('invalid bencode bounds')
        token = raw[pos:pos+1]
        if token == b'i':
            end = raw.index(b'e', pos + 1)
            value = raw[pos+1:end]
            if len(value) > 24 or not re.fullmatch(rb'0|-?[1-9][0-9]*', value):
                raise ValueError('invalid integer')
            pos = end + 1
            return int(value)
        if token in (b'l', b'd'):
            pos += 1
            value = [] if token == b'l' else {}
            last = None
            while pos < len(raw) and raw[pos:pos+1] != b'e':
                if token == b'l':
                    value.append(parse(depth+1))
                else:
                    key = parse(depth+1)
                    if not isinstance(key, bytes) or (last is not None and key <= last):
                        raise ValueError('invalid dict key/order')
                    last = key
                    start = pos
                    value[key] = parse(depth+1)
                    if depth == 0 and key == b'info':
                        info_span = (start, pos)
            if pos >= len(raw):
                raise ValueError('unterminated container')
            pos += 1
            return value
        if b'0' <= token <= b'9':
            end = raw.index(b':', pos)
            length = raw[pos:end]
            if len(length) > 8 or not re.fullmatch(rb'0|[1-9][0-9]*', length):
                raise ValueError('invalid length')
            size = int(length)
            pos = end + 1
            if pos + size > len(raw):
                raise ValueError('truncated bytes')
            value = raw[pos:pos+size]
            pos += size
            return value
        raise ValueError('invalid token')

    try:
        data = parse()
        if pos != len(raw) or not isinstance(data, dict) or not info_span:
            raise ValueError('invalid root')
        info = data[b'info']
        if not isinstance(info, dict) or not isinstance(info.get(b'name'), bytes) or not info[b'name']:
            raise ValueError('invalid info name')
        piece = info.get(b'piece length')
        if not isinstance(piece, int) or piece <= 0:
            raise ValueError('missing piece length')
        total = 0
        is_v2 = info.get(b'meta version') == 2
        has_v1 = b'pieces' in info
        if has_v1:
            if b'length' in info:
                sizes = [info[b'length']]
            else:
                files = info.get(b'files')
                if not isinstance(files, list) or not files:
                    raise ValueError('missing files')
                sizes = []
                for row in files:
                    if not isinstance(row, dict) or not isinstance(row.get(b'path'), list) or not row[b'path']:
                        raise ValueError('invalid file path')
                    if not all(isinstance(p, bytes) and p not in (b'', b'.', b'..') and b'/' not in p for p in row[b'path']):
                        raise ValueError('invalid path components')
                    sizes.append(row.get(b'length'))
            if any(not isinstance(size, int) or size < 0 for size in sizes):
                raise ValueError('invalid file size')
            total = sum(sizes)
            pieces = info[b'pieces']
            if not isinstance(pieces, bytes) or len(pieces) != ((total + piece - 1) // piece) * 20:
                raise ValueError('invalid piece hashes')
        if is_v2:
            tree = info.get(b'file tree')
            if not isinstance(tree, dict) or not tree:
                raise ValueError('invalid v2 file tree')
            def tree_size(node):
                if not isinstance(node, dict):
                    raise ValueError('invalid v2 node')
                if b'' in node:
                    leaf = node[b'']
                    length = leaf.get(b'length') if isinstance(leaf, dict) else None
                    if len(node) != 1 or not isinstance(length, int) or length < 0:
                        raise ValueError('invalid v2 length')
                    return length
                return sum(tree_size(child) for child in node.values())
            v2total = tree_size(tree)
            if not has_v1:
                total = v2total
        if not has_v1 and not is_v2:
            raise ValueError('no supported torrent metadata')
        encoded_info = raw[info_span[0]:info_span[1]]
        hashes = [hashlib.sha1(encoded_info).hexdigest()] if has_v1 else []
        if is_v2:
            h = hashlib.sha256(encoded_info).hexdigest()
            hashes.extend([h[:40], h])
        name = info.get(b'name.utf-8') or info[b'name']
        name = name.decode('utf-8', errors='replace')
        return {'hashes': list(dict.fromkeys(hashes)), 'name': name, 'size': total}
    except (ValueError, KeyError, TypeError, RecursionError, OverflowError) as exc:
        raise TorrentTransportError('下载结果不是有效torrent元数据，未提交到qB') from None


def _origin(url):
    parsed = urlsplit(url)
    if parsed.scheme not in ('http', 'https') or not parsed.hostname or parsed.username or parsed.password:
        raise TorrentTransportError('下载链接不是有效HTTP(S)地址')
    try:
        return parsed.scheme, parsed.hostname.casefold(), parsed.port or (443 if parsed.scheme == 'https' else 80)
    except ValueError:
        raise TorrentTransportError('下载链接端口无效') from None


def _magnet(url):
    hashes = []
    for key, value in parse_qsl(urlsplit(url).query):
        if key.casefold() != 'xt':
            continue
        if value.lower().startswith('urn:btih:'):
            raw = value[9:]
            if re.fullmatch(r'[0-9a-fA-F]{40}', raw):
                hashes.append(raw.lower())
            elif re.fullmatch(r'[a-zA-Z2-7]{32}', raw):
                hashes.append(base64.b32decode(raw.upper()).hex())
        elif value.lower().startswith('urn:btmh:1220'):
            raw = value[13:]
            if re.fullmatch(r'[a-fA-F0-9]{64}', raw):
                hashes.extend([raw[:40].lower(), raw.lower()])
    if not hashes:
        raise TorrentTransportError('磁力链接缺少有效infohash')
    return list(dict.fromkeys(hashes))


def _with_auth(url, auth, trusted):
    if _origin(url) != trusted:
        return url
    for field in ('uid', 'passkey'):
        value = str(auth.get(field) or '')
        if not value:
            continue
        from urllib.parse import quote
        for placeholder in ('{' + field + '}', '{' + field.upper() + '}', '%' + field.upper() + '%'):
            url = url.replace(placeholder, quote(value, safe=''))
    split = urlsplit(url)
    query = parse_qsl(split.query, keep_blank_values=True)
    keys = {key.casefold() for key, _ in query}
    for field, aliases in (('uid', {'uid','userid','user_id'}), ('passkey', {'passkey','pass_key','authkey'})):
        value = str(auth.get(field) or '')
        if value and not keys.intersection(aliases):
            query.append((field, value))
    return urlunsplit((split.scheme, split.netloc, split.path, urlencode(query), split.fragment))


def prepare_torrent(url, auth=None, timeout=20, proxies=None, mode='auto'):
    """Return content/expected hashes; no response here proves qB task creation.

    Authentication is scoped to the RSS origin (or the explicit enclosure if no
    RSS URL exists). Redirects never forward Cookie/Referer or query credentials.
    """
    url = str(url or '').strip()
    auth = auth or {}
    if url.lower().startswith('magnet:?'):
        return {'content': url, 'hashes': _magnet(url), 'name': '', 'size': 0, 'transport': 'magnet', 'cookie': ''}
    origin = _origin(url)
    trusted = _origin(auth.get('url') or url)
    url = _with_auth(url, auth, trusted)
    cookie = str(auth.get('cookie') or '') if origin == trusted else ''
    if mode == 'url':
        return {'content': url, 'hashes': [], 'name': '', 'size': 0, 'transport': 'url', 'cookie': cookie}
    if mode != 'auto':
        raise TorrentTransportError('未知种子提交模式')
    try:
        import requests
    except ImportError:
        raise TorrentTransportError('宿主缺少requests，无法获取种子文件') from None
    timeout = max(5, min(120, float(timeout)))
    deadline = time.monotonic() + timeout
    try:
        with requests.Session() as session:
            session.trust_env = False  # Only the explicitly configured MP proxy.
            for redirects in range(6):
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise TorrentTransportError('下载种子文件超时')
                session.cookies.clear()
                headers = {'User-Agent': str(auth.get('user_agent') or 'Mozilla/5.0'),
                           'Accept': 'application/x-bittorrent, application/octet-stream;q=0.9, */*;q=0.1'}
                if _origin(url) == trusted:
                    if cookie:
                        headers['Cookie'] = cookie
                    if auth.get('referer'):
                        headers['Referer'] = str(auth['referer'])
                with session.get(url, headers=headers, proxies=proxies, stream=True,
                                 allow_redirects=False, timeout=(min(10, remaining), remaining)) as response:
                    if response.status_code in (301, 302, 303, 307, 308):
                        location = response.headers.get('Location')
                        if not location or redirects == 5:
                            raise TorrentTransportError('种子下载重定向过多或缺少目标地址')
                        url = urljoin(url, location)
                        _origin(url)
                        continue
                    if response.status_code != 200:
                        raise TorrentTransportError('下载种子失败：HTTP %d，请检查站点认证和网络' % response.status_code)
                    length = response.headers.get('Content-Length', '')
                    if str(length).isdecimal() and int(length) > MAX_TORRENT_BYTES:
                        raise TorrentTransportError('种子响应超过8 MiB限制')
                    chunks, size = [], 0
                    for chunk in response.iter_content(65536):
                        if time.monotonic() > deadline:
                            raise TorrentTransportError('下载种子文件超时')
                        size += len(chunk)
                        if size > MAX_TORRENT_BYTES:
                            raise TorrentTransportError('种子响应超过8 MiB限制')
                        chunks.append(chunk)
                    raw = b''.join(chunks)
                    info = metainfo(raw)
                    return {**info, 'content': raw, 'transport': 'torrent_file', 'cookie': ''}
    except TorrentTransportError:
        raise
    except Exception as exc:
        # requests exceptions can include passkey-bearing URLs/proxy credentials.
        raise TorrentTransportError('获取种子文件失败（%s），请检查站点网络、Cookie或代理' % type(exc).__name__) from None
    raise TorrentTransportError('无法取得种子文件')
