"""Explicitly reviewed Global Voices translations; no generic site admission."""

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

_PROFILE_65886 = json.loads(Path(__file__).with_name('globalvoices_65886.json').read_text())


def _legacy_work(native_id, ja_url, en_url, profile):
    """Keep the original two-page records byte-for-byte while describing roles explicitly."""
    return {
        'native_id': native_id,
        'source_id': f'globalvoices-{native_id}-ja',
        'ja_url': ja_url,
        'en_url': en_url,
        'original_url': en_url,
        'original_language': 'en',
        'language_chain': ['en', 'ja'],
        'pages': [
            {'key': 'ja', 'role': JA_ROLE, 'language': 'ja', 'url': ja_url,
             'filename': f'{native_id}-ja.html'},
            {'key': 'original', 'role': EN_ROLE, 'language': 'en', 'url': en_url,
             'filename': f'{native_id}-en-original.html'},
        ],
        'credits': [
            {'page': 'original', 'role': 'writer', 'language': 'en',
             'credit': profile['original_metadata']['credits'][0]},
            {'page': 'ja', 'role': 'translator', 'language': 'ja',
             'credit': profile['japanese_metadata']['credits'][1]},
        ],
        'language_link_aliases': [
            {'language': 'English', 'url': profile['japanese_metadata']['english_original_links'][0]},
        ],
        'citation_urls': [en_url, ja_url],
        'legacy_output': True,
        'profile': profile,
        'profile_sha256': hashlib.sha256(canonical_json(profile)).hexdigest(),
    }


def _profile_work(filename):
    profile = json.loads(Path(__file__).with_name(filename).read_text())
    work = dict(profile['work'])
    work['profile'] = profile
    work['profile_sha256'] = hashlib.sha256(canonical_json(profile)).hexdigest()
    work['en_url'] = next((p['url'] for p in work['pages'] if p['language'] == 'en'), None)
    return work


# Each entry is a separately reviewed work, never a discovery/crawl registry.
WORKS = {
    'globalvoices-65906-ja': _legacy_work('65906', JA_URL, EN_URL, PROFILE),
    'globalvoices-65886-ja': _legacy_work(
        '65886', 'https://jp.globalvoices.org/2026/10/09/65886/',
        ('https://globalvoices.org/2026/08/10/'
         'in-japan-ryukyuan-indigenous-claim-hindered-by-u-s-military-bases-in-okinawa/'),
        _PROFILE_65886,
    ),
    'globalvoices-25480-ja': _profile_work('globalvoices_25480.json'),
    'globalvoices-39595-ja': _profile_work('globalvoices_39595.json'),
}
ARTICLE_URLS = frozenset(page['url'] for work in WORKS.values() for page in work['pages'])


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


def _language_links(data):
    page = Tree(data)
    header = _one(page.by_class('post-header'), 'article header')
    result = []
    for node in header.walk():
        title = node.attrs.get('title', '')
        if node.tag == 'a' and title.startswith('他の言語で読む：'):
            result.append({'language': title.split('：', 1)[1].strip(),
                           'url': node.attrs.get('href')})
    return result


def _page_metadata(data, key, expected):
    metadata, blocks = _parts(data)
    if key == 'ja' and 'language_links' in expected:
        metadata['language_links'] = _language_links(data)
        page = Tree(data)
        body_credits = []
        for section in page.by_class('contributors'):
            for link in section.walk():
                if link.tag == 'a':
                    label = section.text().split(link.text(), 1)[0].strip(' ：:')
                    body_credits.append({'role': label, 'name': link.text(),
                                         'url': link.attrs.get('href')})
        if body_credits:
            metadata['body_credits'] = body_credits
    return metadata, blocks


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


def profile_from_chain(pages, decisions, work):
    """Review helper for a pinned original/intermediate/Japanese work chain."""
    if set(pages) != {page['key'] for page in work['pages']}:
        raise DataError('Incomplete Global Voices page chain')
    page_pins = {}
    for key, data in pages.items():
        expected = {'language_links': work['language_link_aliases']} if key == 'ja' else {}
        metadata, blocks = _page_metadata(data, key, expected)
        page_pins[key] = {
            'metadata': metadata,
            'response_sha256': _hash(data),
            'body_sha256': _hash(canonical_json([b.as_dict() for b in blocks])),
        }
    blocks = _parts(pages['ja'])[1]
    if set(decisions) != set(range(len(blocks))):
        raise DataError('Incomplete Global Voices review inventory')
    return {
        'schema_version': 1,
        'work': work,
        'pages': page_pins,
        'blocks': [{'ordinal': i, 'tag': b.tag, 'reason': decisions[i],
                    'text_sha256': _hash(b.text().encode()),
                    'html_tree_sha256': _hash(canonical_json(b.as_dict()))}
                   for i, b in enumerate(blocks)],
        'review_basis': ('Manual paragraph-level review of the exact pinned Japanese response and '
                         'source/intermediate metadata; no aligned text is emitted or asserted.'),
    }


def reviewed_source(source):
    work = WORKS.get(source.get('id'))
    if work is None:
        raise DataError('Global Voices requires an explicitly reviewed work identity')
    acquisition = {'url': work['ja_url'], 'original_url': work['original_url'],
                   'inventory_sha256': work['profile_sha256']}
    intermediate_urls = [p['url'] for p in work['pages']
                         if p['key'] not in {'ja', 'original'}]
    if intermediate_urls:
        acquisition['intermediate_urls'] = intermediate_urls
    if (source.get('adapter') != 'globalvoices' or source.get('language') != 'ja'
            or source.get('homepage') != work['ja_url'] or source.get('license') != LICENSE
            or source.get('acquisition') != acquisition):
        raise DataError('Global Voices requires the reviewed single-work identity, license and inventory')
    return work


def extract(japanese, original, source, *, stats=None):
    work = reviewed_source(source)
    profile, profile_sha256 = work['profile'], work['profile_sha256']
    ja_url, native_id = work['ja_url'], work['native_id']
    stats = stats if stats is not None else Counter()
    if isinstance(original, bytes):
        page_data = {'ja': japanese, 'original': original}
    elif isinstance(original, dict):
        page_data = {'ja': japanese, **original}
    else:
        raise DataError('Global Voices requires all pinned article pages')
    page_specs = work['pages']
    if set(page_data) != {page['key'] for page in page_specs}:
        raise DataError('Global Voices requires the complete reviewed language chain')
    page_metadata, page_blocks = {}, {}
    if 'pages' in profile:
        if set(profile['pages']) != set(page_data):
            raise DataError('Global Voices profile page roles changed')
        for key, data in page_data.items():
            pin = profile['pages'][key]
            metadata, blocks_for_page = _page_metadata(data, key, pin['metadata'])
            if metadata != pin['metadata']:
                raise DataError('Global Voices metadata/rights/bylines/dates changed')
            if (_hash(data) != pin['response_sha256']
                    or _hash(canonical_json([b.as_dict() for b in blocks_for_page]))
                    != pin['body_sha256']):
                raise DataError('Global Voices raw page/body changed; explicit review required')
            page_metadata[key] = metadata
            page_blocks[key] = blocks_for_page
    else:
        ja_meta, ja_blocks = _parts(page_data['ja'])
        original_meta, original_blocks = _parts(page_data['original'])
        if (ja_meta != profile['japanese_metadata']
                or original_meta != profile['original_metadata']):
            raise DataError('Global Voices metadata/rights/bylines/dates changed')
        if (_hash(canonical_json([b.as_dict() for b in original_blocks]))
                != profile['original_body_sha256']):
            raise DataError('Global Voices original article body/exception changed')
        if (_hash(page_data['ja']) != profile['japanese_response_sha256']
                or _hash(page_data['original']) != profile['original_response_sha256']):
            raise DataError('Global Voices raw page changed; explicit rights/layout review required')
        page_metadata.update(ja=ja_meta, original=original_meta)
        page_blocks.update(ja=ja_blocks, original=original_blocks)
    observed_links = page_metadata['ja'].get('language_links')
    if observed_links is None:
        observed_links = [{'language': 'English', 'url': url}
                          for url in page_metadata['ja']['english_original_links']]
    if observed_links != work['language_link_aliases']:
        raise DataError('Global Voices language-chain links changed')
    for role in work['credits']:
        if role['page'] not in page_metadata:
            raise DataError('Global Voices credited role does not match its pinned page byline')
        credits = (page_metadata[role['page']].get('body_credits', [])
                   if role.get('evidence') == 'body'
                   else page_metadata[role['page']]['credits'])
        if role['credit'] not in credits:
            raise DataError('Global Voices credited role does not match its pinned page byline')
    ja_meta = page_metadata['ja']
    blocks = page_blocks['ja']
    if len(blocks) != len(profile['blocks']):
        raise DataError('Global Voices body inventory changed')
    sentences, position = [], 0
    for ordinal, (block, pin) in enumerate(zip(blocks, profile['blocks'], strict=True)):
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
                or (work.get('legacy_output') and any(c in text for c in '「」『』“”"'))):
            raise DataError('Unexpected quotation/media in Global Voices eligible paragraph')
        stats['eligible_publisher_paragraphs'] += 1
        sentences.append({'native_id': f'{native_id}:paragraph:{ordinal}', 'text': text,
                          'source_range': {'unit': 'character', 'start': start, 'end': start+len(text)},
                          'tags': [], 'content_flags': [], 'translations': []})
    ja_dates = ja_meta['publisher_datetimes']
    origin_spec = next(p for p in page_specs if p['language'] == work['original_language'])
    origin_meta = page_metadata[origin_spec['key']]
    origin_dates = origin_meta['publisher_datetimes']
    if work.get('legacy_output'):
        writer = _one([r for r in work['credits'] if r['role'] == 'writer'], 'writer credit')
        translator = _one([r for r in work['credits'] if r['role'] == 'translator'], 'translator credit')
        attribution = (
            f"{ja_meta['title']} — {writer['credit']['name']}, writer (English) and "
            f"{translator['credit']['name']}, translator (Japanese); Global Voices. "
            f"Original English: {work['original_url']} "
            f"(published {origin_dates['article:published_time']}; "
            f"modified {origin_dates['article:modified_time']}). Japanese translation: {ja_url} "
            f"(published {ja_dates['article:published_time']}). CC BY 3.0. "
            'Reviewed narrative paragraphs selected, HTML inline markup removed and text split into sentences.'
        )
        tags = ['translation:from-english', 'translation:method-unknown',
                f"original-url:{work['original_url']}",
                f"original-published-at:{origin_dates['article:published_time']}",
                f"original-modified-at:{origin_dates['article:modified_time']}",
                'scope:single-reviewed-work']
        language_origin = 'unknown'
    else:
        language_names = {'en': 'English', 'es': 'Spanish', 'ja': 'Japanese'}
        contributors = '; '.join(
            f"{role['credit']['name']}, {role['role']} ({language_names[role['language']]})"
            for role in work['credits']
        )
        chain = []
        for index, language in enumerate(work['language_chain']):
            spec = next(p for p in page_specs if p['language'] == language)
            metadata = page_metadata[spec['key']]
            dates = metadata['publisher_datetimes']
            label = ('Original' if index == 0 else
                     'Japanese translation' if language == 'ja' else
                     f"{language_names[language]} intermediary translation")
            chain.append(
                f"{label}: {spec['url']} (published {dates['article:published_time']}; "
                f"modified {dates['article:modified_time']})"
            )
        attribution = (
            f"{ja_meta['title']} — {contributors}; Global Voices. "
            f"Verified language chain: {'; '.join(chain)}. CC BY 3.0. "
            "Reviewed Japanese editorial paragraphs selected; quotations, captions, and third-party blocks withheld. "
            "No sentence-level alignment is asserted."
        )
        tags = [f"translation:from-{work['original_language']}", 'translation:method-unknown',
                f"original-url:{work['original_url']}",
                f"original-language:{work['original_language']}",
                f"translation:chain:{'-'.join(work['language_chain'])}",
                f"original-published-at:{origin_dates['article:published_time']}",
                f"original-modified-at:{origin_dates['article:modified_time']}"]
        for spec in page_specs:
            if spec['language'] not in {'ja', work['original_language']}:
                metadata = page_metadata[spec['key']]
                dates = metadata['publisher_datetimes']
                tags.extend([f"intermediate-url:{spec['url']}",
                             f"intermediate-language:{spec['language']}",
                             f"intermediate-published-at:{dates['article:published_time']}"])
        tags.append('scope:single-reviewed-work')
        # This record field classifies Japanese-language origin, while the observed
        # source language and each intermediate step remain explicit in the tags.
        language_origin = 'unknown'
    return {'native_id': native_id, 'language': 'ja', 'title': ja_meta['title'], 'url': ja_url,
            'license': LICENSE, 'attribution': {'text': attribution, 'url': ja_url},
            'revision': {'id': profile_sha256, 'url': ja_url,
                         'timestamp': ja_dates['article:modified_time']},
            'published_at': ja_dates['article:published_time'],
            'authorship': 'unknown', 'language_origin': language_origin, 'content_type': 'news',
            'source_text_hash': _hash('\n\n'.join(block.text() for block in blocks).encode()),
            'tags': tags, 'sentences': sentences}


def iter_documents(manifest, snapshot_dir, *, stats=None):
    work = reviewed_source(manifest['source'])
    entries = manifest['files']
    specs = work['pages']
    if len(entries) != len(specs) or {e['role'] for e in entries} != {p['role'] for p in specs}:
        raise DataError('Global Voices requires exactly the reviewed page chain inventory')
    data = {}
    for spec in specs:
        entry = _one([e for e in entries if e['role'] == spec['role']], spec['role'])
        if entry['url'] != spec['url']:
            raise DataError('Global Voices snapshot article URL changed')
        path = safe_relative(snapshot_dir, entry['path'])
        if path.is_symlink() or not path.is_file() or path.stat().st_size > MAX_BYTES:
            raise DataError('Invalid Global Voices snapshot article file')
        data[spec['key']] = path.read_bytes()
    yield extract(data.pop('ja'), data, manifest['source'], stats=stats)


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
    if url not in ARTICLE_URLS:
        raise DataError('Only explicitly reviewed Global Voices article URLs may be acquired')
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
