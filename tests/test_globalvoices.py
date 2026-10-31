"""Single-work synthetic fixtures; no upstream article text or network."""

import copy
import hashlib
from collections import Counter
from pathlib import Path

import pytest

from manabi_sentence_db import globalvoices as gv
from manabi_sentence_db.build import build_corpus, canonical_document, iter_records, verify_build
from manabi_sentence_db.serialization import DataError, canonical_json
from manabi_sentence_db.snapshot import SnapshotError, create_snapshot
from manabi_sentence_db.validation import load_source


def html(*, japanese):
    url = gv.JA_URL if japanese else gv.EN_URL
    title = 'Synthetic report' if not japanese else '合成した記事'
    credit = (
        '<div class="contributor-name">記者 (English)<a href="https://globalvoices.org/author/jo-carter/">Jo Carter</a></div>'
        '<div class="contributor-name">翻訳 (日本語)<a href="https://jp.globalvoices.org/author/jo-carter/">Jo Carter</a></div>'
        if japanese else
        '<div class="contributor-name">Written by<a href="https://globalvoices.org/author/jo-carter/">Jo Carter</a></div>'
    )
    dates = ('<span class="post-date post-source-date">元記事掲載 2026/09/25</span>'
             '<span class="post-date">翻訳掲載 2026/10/23</span>' if japanese else
             '<span class="post-date">Posted 25 September 2026</span>')
    published = '2026-10-23T06:25:15+0000' if japanese else '2026-09-25T06:52:28+0000'
    license_url = 'https://creativecommons.org/licenses/by/3.0/' + ('deed.ja' if japanese else '')
    original = (f'<a title="他の言語で読む： English" href="{gv.EN_URL}">English</a>'
                if japanese else '')
    return (f'<html><head><link rel="canonical" href="{url}">'
            f'<meta property="article:published_time" content="{published}">'
            f'<meta property="article:modified_time" content="{published}"></head><body>'
            f'<div class="post-header"><h2 class="post-title">{title}</h2>'
            f'{credit}{dates}{original}</div><div class="entry">'
            '<p>駅の近くに図書館があります。毎朝、多くの人が訪れます。</p>'
            '<blockquote><p>第三者の引用です。</p></blockquote>'
            '<div class="wp-caption"><img src="never-fetch"><p>写真の説明</p></div>'
            '<p>午後には静かになります。</p></div>'
            f'<div class="postfooter">{credit}</div>'
            f'<div class="license"><a rel="license" href="{license_url}"></a></div>'
            f'<div class="footer-license"><a href="{license_url}">CC BY3</a></div>'
            '</body></html>').encode()


@pytest.fixture
def fixture(monkeypatch):
    ja, en = html(japanese=True), html(japanese=False)
    profile = gv.profile_from_pages(ja, en, {0: None, 1: 'third-party-blockquote',
                                           2: 'media-caption', 3: None})
    monkeypatch.setattr(gv, 'PROFILE', profile)
    monkeypatch.setattr(gv, 'PROFILE_SHA256', hashlib.sha256(canonical_json(profile)).hexdigest())
    source = load_source(Path('sources/globalvoices-65906-ja.yaml'))
    source['acquisition']['inventory_sha256'] = gv.PROFILE_SHA256
    return source, ja, en


def test_exact_units_attribution_direction_and_context_gaps(fixture, tmp_path):
    source, ja, en = fixture
    raw = gv.extract(ja, en, source)
    assert raw['authorship'] == raw['language_origin'] == 'unknown'
    assert not any('native-review' in tag for tag in raw['tags'])
    assert 'translation:from-english' in raw['tags']
    assert raw['published_at'] == '2026-10-23T06:25:15+0000'
    assert 'original-published-at:2026-09-25T06:52:28+0000' in raw['tags']
    assert 'writer (English)' in raw['attribution']['text']
    assert 'translator (Japanese)' in raw['attribution']['text']
    assert gv.EN_URL in raw['attribution']['text']
    manifest = {'source': source, 'source_id': source['id'], 'snapshot_id': 'synthetic'}
    stats = Counter()
    doc = canonical_document(raw, manifest, stats, set())
    assert len(doc['sentences']) == 3
    assert [s['ordinal'] for s in doc['sentences']] == [0, 1, 4]
    assert doc['sentences'][0]['source_unit']['text'].endswith('毎朝、多くの人が訪れます。')
    start = len('駅の近くに図書館があります。毎朝、多くの人が訪れます。\n\n第三者の引用です。\n\n写真の説明\n\n')
    assert doc['sentences'][-1]['source_range'] == {
        'unit': 'character', 'start': start, 'end': start+len('午後には静かになります。')}
    assert stats['context_breaks'] == 2
    assert all(s['review_state'] == 'unreviewed' and s['translations'] == [] for s in doc['sentences'])
    assert 'human_translation' not in str(doc)
    assert '第三者' not in str(doc) and 'never-fetch' not in str(doc)
    assert raw['source_text_hash'] == hashlib.sha256(
        '駅の近くに図書館があります。毎朝、多くの人が訪れます。\n\n第三者の引用です。\n\n写真の説明\n\n午後には静かになります。'.encode()
    ).hexdigest()


@pytest.mark.parametrize('side,before,after', [
    ('ja', 'Jo Carter</a>', 'Another writer</a>'),
    ('en', 'Written by', 'Translated by'),
    ('ja', '翻訳 (日本語)', '記者 (日本語)'),
    ('ja', '2026/10/23', '2026/10/24'),
    ('en', '2026-09-25T06:52:28+0000', '2026-09-26T06:52:28+0000'),
    ('ja', 'by/3.0/deed.ja', 'by-nc/3.0/deed.ja'),
    ('en', 'by/3.0/', 'by-nd/3.0/'),
    ('ja', '駅の近くに', '駅の前に'),
    ('ja', '<p>駅', '<p><img src="x">駅'),
    ('ja', '<p>駅', '<p><span class="new">追加</span>駅'),
    ('ja', '<p>駅', '<p>「引用」駅'),
    ('en', '<p>駅', '<p>Republished with permission from a partner. 駅'),
    ('ja', '<div class="entry">', '<div class="entry"><p>コンテンツ共有契約に基づき転載</p>'),
    ('ja', '<blockquote><p>第三者の引用です。</p></blockquote>', ''),
    ('ja', '<div class="postfooter">', '<div class="postfooter"><div class="contributor-name">extra</div>'),
    ('ja', '</body>', '<p>Partner rights exception outside the article body.</p></body>'),
])
def test_metadata_rights_body_and_layout_drift_fail_closed(fixture, side, before, after):
    source, ja, en = fixture
    if side == 'ja':
        ja = ja.replace(before.encode(), after.encode())
    else:
        en = en.replace(before.encode(), after.encode())
    with pytest.raises(DataError):
        gv.extract(ja, en, source)


def test_cannot_repurpose_source_or_inventory(fixture):
    source, ja, en = fixture
    for field, value in [('id', 'other-ja'), ('homepage', 'https://example.com'),
                         ('language', 'en'), ('license', {'id': 'CC0-1.0'})]:
        changed = copy.deepcopy(source)
        changed[field] = value
        with pytest.raises(DataError):
            gv.extract(ja, en, changed)
    changed = copy.deepcopy(source)
    changed['acquisition']['inventory_sha256'] = '0' * 64
    with pytest.raises(DataError):
        gv.extract(ja, en, changed)


def test_snapshot_and_offline_build_revalidate_pages(fixture, tmp_path, monkeypatch):
    source, ja, en = fixture
    calls = []

    def acquire(url, cache, agent):
        calls.append(url)
        return ja if url == gv.JA_URL else en

    monkeypatch.setattr(gv, 'cached_article', acquire)
    path = create_snapshot(source, tmp_path/'snapshot', mode='full', article_cache=tmp_path/'cache')
    assert calls == [gv.JA_URL, gv.EN_URL]
    assert create_snapshot(source, path.parent, mode='full', article_cache=tmp_path/'cache') == path
    assert len(calls) == 2
    output = tmp_path/'build'
    build_corpus([path], output)
    assert len(list(iter_records(output, verify_build(output)))) == 1
    manifest = {'source': source, 'source_id': source['id'], 'snapshot_id': 'synthetic',
                'files': [{'role': gv.JA_ROLE, 'url': gv.JA_URL, 'path': 'ja.html'},
                          {'role': gv.EN_ROLE, 'url': gv.EN_URL, 'path': 'en.html'}]}
    (tmp_path/'ja.html').write_bytes(ja)
    (tmp_path/'en.html').write_bytes(en.replace(b'Written by', b'Republished by'))
    with pytest.raises(DataError):
        list(gv.iter_documents(manifest, tmp_path))
    with pytest.raises(SnapshotError, match='cache'):
        create_snapshot(source, tmp_path/'missing-cache', mode='full')
    with pytest.raises(SnapshotError, match='refresh'):
        create_snapshot(source, tmp_path/'refresh', mode='full', refresh=True,
                        article_cache=tmp_path/'cache')


def test_cache_hits_never_network_and_corruption_fails(tmp_path, monkeypatch):
    import json

    data = b'synthetic cached bytes'
    key = hashlib.sha256(gv.JA_URL.encode()).hexdigest()
    (tmp_path/(key+'.body')).write_bytes(data)
    (tmp_path/(key+'.json')).write_text(json.dumps({
        'url': gv.JA_URL, 'status': 200, 'bytes': len(data),
        'sha256': hashlib.sha256(data).hexdigest(), 'body': key+'.body'}))
    monkeypatch.setattr(gv, '_request', lambda *args: pytest.fail('network on cache hit'))
    assert gv.cached_article(gv.JA_URL, tmp_path, 'test') == data
    (tmp_path/(key+'.body')).write_bytes(b'corrupt')
    with pytest.raises(DataError, match='cache'):
        gv.cached_article(gv.JA_URL, tmp_path, 'test')


def test_robots_denial_never_fetches_article(tmp_path, monkeypatch):
    calls = []

    def request(url, agent):
        calls.append(url)
        return b'User-agent: *\nCrawl-delay: 10\nDisallow: /2026/\n'

    monkeypatch.setattr(gv, '_request', request)
    with pytest.raises(DataError, match='robots'):
        gv.cached_article(gv.JA_URL, tmp_path, 'test')
    assert calls == ['https://jp.globalvoices.org/robots.txt']


def test_redirects_and_symlinked_cache_are_rejected(tmp_path):
    with pytest.raises(DataError, match='redirect'):
        gv._NoRedirect().redirect_request(None, None, 301, 'moved', {}, 'https://example.com')
    (tmp_path/'link').symlink_to(tmp_path, target_is_directory=True)
    with pytest.raises(DataError, match='canonical'):
        gv.cached_article(gv.JA_URL, tmp_path/'link', 'test')


def test_acquisition_rejects_changed_pages_before_snapshot_publication(fixture, tmp_path, monkeypatch):
    source, ja, en = fixture
    monkeypatch.setattr(gv, 'cached_article', lambda url, *args:
                        ja if url == gv.JA_URL else en.replace(b'Written by', b'Partner by'))
    with pytest.raises(DataError):
        create_snapshot(source, tmp_path/'snapshot', mode='full', article_cache=tmp_path/'cache')
    assert not (tmp_path/'snapshot').exists()


def test_reused_snapshot_rechecks_inventory_even_with_recomputed_manifest(fixture, tmp_path, monkeypatch):
    from manabi_sentence_db.serialization import read_json, sha256_file, write_json
    from manabi_sentence_db.snapshot import snapshot_identity

    source, ja, en = fixture
    monkeypatch.setattr(gv, 'cached_article', lambda url, *args: ja if url == gv.JA_URL else en)
    path = create_snapshot(source, tmp_path/'snapshot', mode='full', article_cache=tmp_path/'cache')
    manifest = read_json(path)
    entry = next(e for e in manifest['files'] if e['role'] == gv.JA_ROLE)
    raw_path = path.parent/entry['path']
    raw_path.write_bytes(ja.replace('図書館'.encode(), '映画館'.encode()))
    entry.update(sha256=sha256_file(raw_path), size=raw_path.stat().st_size)
    manifest['snapshot_id'] = snapshot_identity(manifest)
    write_json(path, manifest)
    with pytest.raises(DataError):
        create_snapshot(source, path.parent, mode='full', article_cache=tmp_path/'cache')


def test_network_spacing_including_retries_and_robots(tmp_path, monkeypatch):
    import io
    import urllib.error

    now = [1000.0]
    attempts = []

    def sleep(delay): now[0] += delay
    monkeypatch.setattr(gv.time, 'time', lambda: now[0])
    monkeypatch.setattr(gv.time, 'sleep', sleep)

    def request(url, agent):
        attempts.append((url, now[0]))
        if url.endswith('/robots.txt'):
            return b'User-agent: *\nCrawl-delay: 10\nDisallow: /wp-admin/\n'
        if sum(u == url for u, _ in attempts) == 1:
            raise urllib.error.HTTPError(url, 503, 'retry', {}, io.BytesIO())
        return b'synthetic page'

    monkeypatch.setattr(gv, '_request', request)
    assert gv.cached_article(gv.JA_URL, tmp_path, 'test') == b'synthetic page'
    assert gv.cached_article(gv.EN_URL, tmp_path, 'test') == b'synthetic page'
    assert len(attempts) == 6
    assert all(b[1]-a[1] >= 10 for a, b in zip(attempts, attempts[1:]))


def test_source_all_skips_this_opt_in_article(tmp_path, monkeypatch, capsys):
    from manabi_sentence_db import cli

    monkeypatch.setattr(cli, '_sources', lambda path: {
        'globalvoices-65906-ja': {'id': 'globalvoices-65906-ja', 'adapter': 'globalvoices'}})
    monkeypatch.setattr(cli, 'create_snapshot', lambda *a, **k: pytest.fail('implicit acquisition'))
    assert cli.main(['snapshot', '--source', 'all', '--mode', 'full', '--output', str(tmp_path)]) == 0
    assert 'explicit' in capsys.readouterr().err



def test_raw_article_evidence_cannot_be_packaged_as_public_release(fixture, tmp_path, monkeypatch):
    from manabi_sentence_db.transport import snapshot_pack

    source, ja, en = fixture
    monkeypatch.setattr(gv, 'cached_article', lambda url, *args: ja if url == gv.JA_URL else en)
    path = create_snapshot(source, tmp_path/'snapshot', mode='full', article_cache=tmp_path/'cache')
    with pytest.raises(SnapshotError, match='local rights evidence'):
        snapshot_pack(path, tmp_path/'raw-release')
    assert not (tmp_path/'raw-release').exists()
    build = tmp_path/'processed'
    build_corpus([path], build)
    assert list(iter_records(build, verify_build(build)))



def test_request_clock_cannot_overwrite_hardlinked_file(tmp_path, monkeypatch):
    import os

    target = tmp_path / 'preserved.json'
    target.write_bytes(b'{"time": 0}')
    os.link(target, tmp_path / 'last-attempt.json')
    monkeypatch.setattr(gv, '_request', lambda *args: pytest.fail('network with aliased clock'))
    with pytest.raises(DataError, match='request clock'):
        gv.cached_article(gv.JA_URL, tmp_path, 'test')
    assert target.read_bytes() == b'{"time": 0}'
