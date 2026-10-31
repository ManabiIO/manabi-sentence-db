"""One explicitly reviewed Global Voices translation; no generic site admission."""

import fcntl
import hashlib
import json
import math
import time
import urllib.error
import urllib.parse
import urllib.request
import urllib.robotparser
from collections import Counter
from pathlib import Path

from .html_tree import Element, Tree
from .segments import CONTEXT_BREAK
from .serialization import DataError, canonical_json, safe_relative

JA_URL = 'https://jp.globalvoices.org/2026/10/23/65906/'
EN_URL = ('https://globalvoices.org/2026/09/25/'
          'young-japanese-find-new-outlets-for-peace-activism-amid-rising-tensions-in-the-pacific/')
JA_ROLE = 'globalvoices-japanese-html'
EN_ROLE = 'globalvoices-original-html'
LICENSE = {'id': 'CC-BY-3.0', 'url': 'https://creativecommons.org/licenses/by/3.0/'}
MAX_BYTES = 1_500_000
PROFILE = json.loads(Path(__file__).with_name('globalvoices_65906.json').read_text())
PROFILE_SHA256 = hashlib.sha256(canonical_json(PROFILE)).hexdigest()
TRANSFORMATION = 'globalvoices-reviewed-paragraph-inventory-v1'


def _hash(data):
    return hashlib.sha256(data).hexdigest()


def _one(items, label):
    if len(items) != 1:
        raise DataError(f'Global Voices requires exactly one {label}')
    return items[0]


def _parts(data):
    if not isinstance(data, bytes) or len(data) > MAX_BYTES:
        raise DataError('Oversized Global Voices HTML')
    page = Tree(data)
    header = _one(page.by_class('post-header'), 'article header')
    footer = _one(page.by_class('postfooter'), 'article footer')

    def credits(section):
        result = []
        for block in section.walk():
            if 'contributor-name' in (block.attrs.get('class') or '').split():
                link = _one([n for n in block.walk() if n.tag == 'a'], 'credit link')
                result.append({'display': block.text(), 'name': link.text(),
                               'url': link.attrs.get('href')})
        return result

    if credits(header) != credits(footer) or not credits(header):
        raise DataError('Global Voices header/footer contributor mismatch')
    meta = {key: _one([n.attrs.get('content') for n in page.root.walk()
                       if n.tag == 'meta' and n.attrs.get('property') == key], key)
            for key in ('article:published_time', 'article:modified_time')}
    canonical = _one([n.attrs.get('href') for n in page.root.walk()
                      if n.tag == 'link' and n.attrs.get('rel') == 'canonical'], 'canonical URL')
    entry = _one(page.by_class('entry'), 'article body')
    if any(isinstance(n, str) and n.strip() for n in entry.children):
        raise DataError('Unexpected Global Voices body character data')
    metadata = {
        'url': canonical,
        'title': _one([n for n in header.walk()
                       if 'post-title' in (n.attrs.get('class') or '').split()], 'title').text(),
        'credits': credits(header),
        'display_dates': [n.text().strip() for n in header.walk()
                          if 'post-date' in (n.attrs.get('class') or '').split()],
        'publisher_datetimes': meta,
        'english_original_links': [n.attrs.get('href') for n in header.walk()
                                   if n.tag == 'a' and n.attrs.get('title') ==
                                   '他の言語で読む： English'],
        'article_license_sha256': _hash(canonical_json(
            _one(page.by_class('license'), 'article license').as_dict())),
        'footer_license_sha256': _hash(canonical_json(
            _one(page.by_class('footer-license'), 'footer license').as_dict())),
        'entry_attrs': entry.attrs,
    }
    return metadata, [n for n in entry.children if isinstance(n, Element)]


def profile_from_pages(japanese, original, decisions):
    """Review helper used by synthetic fixtures; runtime accepts only the shipped pin."""
    ja_meta, blocks = _parts(japanese)
    en_meta, en_blocks = _parts(original)
    if set(decisions) != set(range(len(blocks))):
        raise DataError('Incomplete Global Voices review inventory')
    return {'japanese_metadata': ja_meta, 'original_metadata': en_meta,
            'japanese_response_sha256': _hash(japanese),
            'original_response_sha256': _hash(original),
            'original_body_sha256': _hash(canonical_json([b.as_dict() for b in en_blocks])),
            'blocks': [{'ordinal': i, 'tag': b.tag, 'reason': decisions[i],
                        'text_sha256': _hash(b.text().encode()),
                        'html_tree_sha256': _hash(canonical_json(b.as_dict()))}
                       for i, b in enumerate(blocks)]}


def reviewed_source(source):
    acquisition = {'url': JA_URL, 'original_url': EN_URL,
                   'inventory_sha256': PROFILE_SHA256}
    if (source.get('id') != 'globalvoices-65906-ja'
            or source.get('adapter') != 'globalvoices' or source.get('language') != 'ja'
            or source.get('homepage') != JA_URL or source.get('license') != LICENSE
            or source.get('acquisition') != acquisition):
        raise DataError('Global Voices requires the reviewed single-work identity, license and inventory')


def extract(japanese, original, source, *, stats=None):
    reviewed_source(source)
    stats = stats if stats is not None else Counter()
    ja_meta, blocks = _parts(japanese)
    en_meta, en_blocks = _parts(original)
    if ja_meta != PROFILE['japanese_metadata'] or en_meta != PROFILE['original_metadata']:
        raise DataError('Global Voices metadata/rights/bylines/dates changed')
    if _hash(canonical_json([b.as_dict() for b in en_blocks])) != PROFILE['original_body_sha256']:
        raise DataError('Global Voices original article body/exception changed')
    if len(blocks) != len(PROFILE['blocks']):
        raise DataError('Global Voices body inventory changed')
    # Even a new work-specific notice outside div.entry must force re-review.
    # These exact response pins intentionally reject unrelated wrapper changes too.
    if (_hash(japanese) != PROFILE['japanese_response_sha256']
            or _hash(original) != PROFILE['original_response_sha256']):
        raise DataError('Global Voices raw page changed; explicit rights/layout review required')
    sentences, position = [], 0
    for ordinal, (block, pin) in enumerate(zip(blocks, PROFILE['blocks'], strict=True)):
        stats['publisher_blocks_seen'] += 1
        if (pin['ordinal'] != ordinal or block.tag != pin['tag']
                or _hash(block.text().encode()) != pin['text_sha256']
                or _hash(canonical_json(block.as_dict())) != pin['html_tree_sha256']):
            raise DataError('Global Voices paragraph text/markup changed')
        start = position
        position += len(block.text()) + 2
        if pin['reason'] is not None:
            stats['rejected:globalvoices-' + pin['reason']] += 1
            sentences.append(CONTEXT_BREAK)
            continue
        text = block.text()
        if (block.tag != 'p' or any(n.tag not in {'p', 'span', 'a'} or n.duplicate_attrs
                                   for n in block.walk())
                or any(c in text for c in '「」『』“”"')):
            raise DataError('Unexpected quotation/media in Global Voices eligible paragraph')
        stats['eligible_publisher_paragraphs'] += 1
        sentences.append({'native_id': f'65906:paragraph:{ordinal}', 'text': text,
                          'source_range': {'unit': 'character', 'start': start, 'end': start+len(text)},
                          'tags': [], 'content_flags': [], 'translations': []})
    en_dates = en_meta['publisher_datetimes']
    ja_dates = ja_meta['publisher_datetimes']
    attribution = (
        f"{ja_meta['title']} — Jo Carter, writer (English) and translator (Japanese); Global Voices. "
        f"Original English: {EN_URL} (published {en_dates['article:published_time']}; "
        f"modified {en_dates['article:modified_time']}). Japanese translation: {JA_URL} "
        f"(published {ja_dates['article:published_time']}). CC BY 3.0. "
        'Reviewed narrative paragraphs selected, HTML inline markup removed and text split into sentences.'
    )
    return {'native_id': '65906', 'language': 'ja', 'title': ja_meta['title'], 'url': JA_URL,
            'license': LICENSE, 'attribution': {'text': attribution, 'url': JA_URL},
            'revision': {'id': PROFILE_SHA256, 'url': JA_URL,
                         'timestamp': ja_dates['article:modified_time']},
            'published_at': ja_dates['article:published_time'],
            'authorship': 'unknown', 'language_origin': 'unknown', 'content_type': 'news',
            'source_text_hash': _hash('\n\n'.join(block.text() for block in blocks).encode()),
            'tags': ['translation:from-english', 'translation:method-unknown',
                     f'original-url:{EN_URL}',
                     f"original-published-at:{en_dates['article:published_time']}",
                     f"original-modified-at:{en_dates['article:modified_time']}",
                     'scope:single-reviewed-work'], 'sentences': sentences}


def iter_documents(manifest, snapshot_dir, *, stats=None):
    entries = manifest['files']
    if len(entries) != 2 or {e['role'] for e in entries} != {JA_ROLE, EN_ROLE}:
        raise DataError('Global Voices requires exactly the Japanese and original article inventory')
    data = {}
    for role, url in ((JA_ROLE, JA_URL), (EN_ROLE, EN_URL)):
        entry = _one([e for e in entries if e['role'] == role], role)
        if entry['url'] != url:
            raise DataError('Global Voices snapshot article URL changed')
        path = safe_relative(snapshot_dir, entry['path'])
        if path.is_symlink() or not path.is_file() or path.stat().st_size > MAX_BYTES:
            raise DataError('Invalid Global Voices snapshot article file')
        data[role] = path.read_bytes()
    yield extract(data[JA_ROLE], data[EN_ROLE], manifest['source'], stats=stats)


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        raise DataError('Global Voices redirects require explicit review')


def _request(url, agent):
    request = urllib.request.Request(url, headers={'User-Agent': agent, 'Accept': 'text/html,text/plain'})
    opener = urllib.request.build_opener(_NoRedirect())
    with opener.open(request, timeout=30) as response:
        if response.status != 200:
            raise DataError('Unexpected Global Voices HTTP status')
        data = response.read(MAX_BYTES+1)
    if len(data) > MAX_BYTES:
        raise DataError('Oversized Global Voices response')
    return data


def _cache_response(url, cache, agent):
    key = _hash(url.encode())
    meta_path, body = cache/(key+'.json'), cache/(key+'.body')
    if meta_path.exists():
        try:
            if (meta_path.is_symlink() or body.is_symlink() or not meta_path.is_file()
                    or not body.is_file() or meta_path.stat().st_size > 65536):
                raise ValueError('unsafe cache file')
            meta = json.loads(meta_path.read_text())
            if meta['body'] != body.name or body.stat().st_size > MAX_BYTES:
                raise ValueError('unsafe cache body')
            data = body.read_bytes()
            if (len(data) > MAX_BYTES or meta['url'] != url or meta['status'] != 200
                    or meta['bytes'] != len(data) or meta['sha256'] != _hash(data)):
                raise ValueError('cache mismatch')
            return data
        except (OSError, ValueError, KeyError, TypeError) as error:
            raise DataError('Invalid Global Voices cache; never silently refetch') from error
    if body.exists():
        raise DataError('Incomplete Global Voices cache; use a fresh explicit cache')
    clock = cache/'last-attempt.json'
    if clock.is_symlink():
        raise DataError('Unsafe Global Voices request clock')
    for attempt in range(3):
        try:
            if clock.exists():
                if not clock.is_file() or clock.stat().st_nlink != 1:
                    raise DataError('Invalid Global Voices request clock')
                try:
                    if clock.stat().st_size > 65536:
                        raise ValueError('oversized clock')
                    last = json.loads(clock.read_text())['time']
                except (OSError, ValueError, KeyError, TypeError) as error:
                    raise DataError('Invalid Global Voices request clock') from error
                if type(last) not in (int, float) or not math.isfinite(last) or last < 0:
                    raise DataError('Invalid Global Voices request clock')
                delay = max(0, 10.1-(time.time()-last))
                if delay > 60:
                    raise DataError('Global Voices request clock is in the future; retry later')
                time.sleep(delay)
            now = time.time()
            clock.write_text(json.dumps({'time': now, 'url': url}))
            data = _request(url, agent)
            break
        except urllib.error.HTTPError as error:
            retry = error.headers.get('Retry-After')
            error.close()
            if error.code not in {429, 500, 502, 503, 504} or attempt == 2:
                raise DataError('Global Voices HTTP acquisition failed') from error
            if retry:
                try:
                    pause = float(retry)
                except ValueError as invalid:
                    raise DataError('Global Voices Retry-After requires a later explicit retry') from invalid
                if not 0 <= pause <= 60:
                    raise DataError('Global Voices server requested a later retry')
                time.sleep(pause)
        except (urllib.error.URLError, TimeoutError) as error:
            if attempt == 2:
                raise DataError('Global Voices acquisition failed') from error
    meta = {'url': url, 'status': 200, 'bytes': len(data), 'sha256': _hash(data),
            'body': body.name, 'retrieved_at': now}
    with body.open('xb') as output:
        output.write(data)
    with meta_path.open('x') as output:
        output.write(json.dumps(meta, sort_keys=True)+'\n')
    return data


def cached_article(url, cache, agent):
    """One worker across both hosts/retries; URL-keyed durable cache outside snapshots."""
    if url not in {JA_URL, EN_URL}:
        raise DataError('Only the two reviewed Global Voices article URLs may be acquired')
    cache = Path(cache)
    if cache.resolve() != cache.absolute():
        raise DataError('Global Voices cache must use its canonical, symlink-free path')
    cache.mkdir(parents=True, exist_ok=True)
    lock_path = cache/'network.lock'
    if (lock_path.is_symlink() or (lock_path.exists()
            and (not lock_path.is_file() or lock_path.stat().st_nlink != 1))):
        raise DataError('Unsafe Global Voices acquisition lock')
    with lock_path.open('a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        # A verified article cache hit makes zero HTTP requests, including robots.
        key = _hash(url.encode())
        if (cache/(key+'.json')).exists():
            return _cache_response(url, cache, agent)
        origin = 'https://'+urllib.parse.urlsplit(url).netloc
        robots_data = _cache_response(origin+'/robots.txt', cache, agent)
        robots = urllib.robotparser.RobotFileParser()
        robots.parse(robots_data.decode('utf-8').splitlines())
        delay = robots.crawl_delay(agent)
        if not robots.can_fetch(agent, url) or delay is None or delay > 10:
            raise DataError('Global Voices robots changed; explicit policy review required')
        return _cache_response(url, cache, agent)
