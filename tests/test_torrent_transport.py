"""No host required: test torrent bytes, auth scope, and error boundaries."""
from pathlib import Path
import importlib.util
import hashlib
import json
import sys
import types
from urllib.parse import parse_qs, urlsplit
import pytest

spec = importlib.util.spec_from_file_location('brush_transport_test', Path(__file__).parents[1] / 'plugins.v2/brushflowtracker/torrent_transport.py')
t = importlib.util.module_from_spec(spec); spec.loader.exec_module(t)


def bencode(value):
    if isinstance(value, bytes): return str(len(value)).encode() + b':' + value
    if isinstance(value, int): return b'i' + str(value).encode() + b'e'
    if isinstance(value, list): return b'l' + b''.join(map(bencode, value)) + b'e'
    return b'd' + b''.join(bencode(k) + bencode(v) for k, v in sorted(value.items())) + b'e'


def torrent(name='Example 电影.mkv', size=123):
    info = {b'name': name.encode(), b'length': size, b'piece length': 16384,
            b'pieces': b'\x11' * (((size+16383)//16384)*20)}
    return bencode({b'announce': b'https://tracker.invalid/announce', b'info': info}), hashlib.sha1(bencode(info)).hexdigest()


class Response:
    def __init__(self, body=b'', status=200, headers=None):
        self.body, self.status_code, self.headers = body, status, headers or {}
    def __enter__(self): return self
    def __exit__(self, *args): pass
    def iter_content(self, n):
        for i in range(0, len(self.body), n):yield self.body[i:i+n]


@pytest.fixture
def network(monkeypatch):
    class Session:
        def __init__(self):
            self.cookies = types.SimpleNamespace(clear=lambda: None)
            self.trust_env = True
        def __enter__(self):return self
        def __exit__(self,*args):pass
        def get(self,url,**kwargs):
            assert self.trust_env is False
            calls.append((url,kwargs))
            response=responses.pop(0)
            if isinstance(response,Exception):raise response
            return response
    calls, responses=[],[]
    monkeypatch.setitem(sys.modules,'requests',types.SimpleNamespace(Session=Session))
    return calls,responses


def test_metainfo_hashes_original_info_bytes():
    raw,h=torrent()
    result=t.metainfo(raw)
    assert result=={'hashes':[h],'name':'Example 电影.mkv','size':123}


@pytest.mark.parametrize('body',[b'',b'<html>login</html>',b'{"success":true}',b'd4:infodee',b'd4:info',b'd4:infoi2ee'])
def test_invalid_enclosures_not_submitted(body):
    with pytest.raises(t.TorrentTransportError):t.metainfo(body)


def test_trailing_data_bad_piece_count_and_duplicate_info_rejected():
    raw,_=torrent()
    for bad in (raw+b'garbage',raw[:-1],bencode({b'info':{b'name':b'x',b'length':10,b'piece length':16,b'pieces':b''}})):
        with pytest.raises(t.TorrentTransportError):t.metainfo(bad)


def test_multifile_and_v2_identity():
    info={b'name':b'Season',b'files':[{b'length':1,b'path':[b'a.mkv']},{b'length':2,b'path':[b'b.mkv']}],b'piece length':16,b'pieces':b'x'*20}
    raw=bencode({b'info':info})
    assert t.metainfo(raw)['size']==3
    v2={b'name':b'x',b'meta version':2,b'piece length':16384,b'file tree':{b'x':{b'':{b'length':3,b'pieces root':b'x'*32}}}}
    h=hashlib.sha256(bencode(v2)).hexdigest()
    assert t.metainfo(bencode({b'info':v2}))['hashes']==[h[:40],h]


def test_cookie_proxy_and_referer_used_to_fetch_torrent(network):
    calls,responses=network;raw,h=torrent();responses.append(Response(raw))
    value=t.prepare_torrent('https://pt.invalid/download?id=1', {'url':'https://pt.invalid/rss','cookie':'SID=test-secret','referer':'https://pt.invalid/','user_agent':'Fixture','passkey':'test-pass'},proxies={'https':'http://proxy.invalid:8080'})
    assert value['content']==raw and value['hashes']==[h]
    assert value['transport']=='torrent_file'
    url,kwargs=calls[0]
    assert parse_qs(urlsplit(url).query)['passkey']==['test-pass']
    assert kwargs['headers']['Cookie']=='SID=test-secret'
    assert kwargs['headers']['Referer']=='https://pt.invalid/'
    assert kwargs['proxies']=={'https':'http://proxy.invalid:8080'}
    assert kwargs['allow_redirects'] is False


def test_cross_origin_redirect_does_not_leak_cookie_or_referer(network):
    calls,responses=network;raw,_=torrent()
    responses.extend([Response(status=302,headers={'Location':'https://cdn.invalid/file.torrent'}),Response(raw)])
    t.prepare_torrent('https://pt.invalid/file',{'url':'https://pt.invalid/rss','cookie':'SID=secret','referer':'https://pt.invalid/details?token=secret'})
    assert calls[0][1]['headers']['Cookie']=='SID=secret'
    assert 'Cookie' not in calls[1][1]['headers'] and 'Referer' not in calls[1][1]['headers']


def test_cross_origin_enclosure_does_not_receive_site_auth(network):
    calls,responses=network;responses.append(Response(torrent()[0]))
    t.prepare_torrent('https://cdn.invalid/file',{'url':'https://pt.invalid/rss','cookie':'SID=secret','passkey':'secret','referer':'https://pt.invalid/'})
    assert 'Cookie' not in calls[0][1]['headers']
    assert 'passkey' not in calls[0][0]


@pytest.mark.parametrize('response',[Response(b'<html>login</html>'),Response(b'forbidden',403),Response(headers={'Content-Length':str(9*1024*1024)}),ValueError('https://secret.invalid?passkey=private')])
def test_download_failures_redact_secrets(network,response):
    calls,responses=network;responses.append(response)
    with pytest.raises(t.TorrentTransportError) as exc:
        t.prepare_torrent('https://pt.invalid?passkey=private')
    assert 'private' not in str(exc.value)
    assert 'secret.invalid' not in str(exc.value)


def test_url_mode_and_magnets_do_not_download(network):
    calls,_=network
    result=t.prepare_torrent('https://pt.invalid/file',{'cookie':'SID=test'},mode='url')
    assert isinstance(result['content'],str) and result['cookie']=='SID=test'
    h='a'*40
    assert t.prepare_torrent('magnet:?xt=urn:btih:'+h)['hashes']==[h]
    h2='b'*64
    assert t.prepare_torrent('magnet:?xt=urn:btmh:1220'+h2)['hashes']==[h2[:40],h2]
    assert not calls


def test_invalid_magnet_never_falls_back_to_unidentified_url(network):
    with pytest.raises(t.TorrentTransportError):t.prepare_torrent('magnet:?dn=movie')


def test_strict_hash_identity_does_not_claim_qb_creation(network):
    calls,responses=network;responses.append(Response(torrent()[0]))
    data=t.prepare_torrent('https://pt.invalid/download')
    assert 'success' not in data and 'confirmed' not in data
