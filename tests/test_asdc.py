"""Offline synthetic main inventory; no upstream corpus acquisition."""
import copy
import hashlib
import json
import zipfile
from collections import Counter
from pathlib import Path

import pytest
import yaml

from manabi_sentence_db import asdc
from manabi_sentence_db.build import build_corpus, canonical_document, iter_records, verify_build
from manabi_sentence_db.normalized import export_normalized
from manabi_sentence_db.serialization import DataError, digest_json, sha256_file, write_json
from manabi_sentence_db.snapshot import snapshot_identity


def fixture(tmp_path, monkeypatch, change=None, omit=None, duplicate=False):
    source = yaml.safe_load(Path('sources/asdc-main-ja.yaml').read_text())
    evidence = {name: ('Synthetic CC BY 4.0 evidence: ' + name).encode() for name in asdc.EVIDENCE}
    pins = {name: hashlib.sha256(raw).hexdigest() for name, raw in evidence.items()}
    monkeypatch.setattr(asdc, 'EVIDENCE', pins)
    source['acquisition']['evidence_sha256'] = pins
    path = tmp_path / 'asdc.zip'
    with zipfile.ZipFile(path, 'w', compression=zipfile.ZIP_DEFLATED) as archive:
        for name, raw in evidence.items():
            archive.writestr(asdc.ROOT + '/' + name, raw)
        for n in range(1, 211):
            if n == omit:
                continue
            identity = f'asdc.v4.{n:03}'
            value = {'meta': {'id': {'id': identity}, 'memo': 'private-scenario'}, 'utterances': [
                {'id': {'id': identity + '.0'}, 'name': 'operator_1', 'text': '今日は公園を散歩しました。川の水がきれいですね。', 'text_sbs': ['deliberately-unused'], 'time': 33},
                {'id': {'id': identity + '.2'}, 'name': 'customer_35', 'text': '明日は図書館に行きます。'}]}
            if change and n == 1:
                change(value)
            name = f'{asdc.ROOT}/data/main/dialog/json/{n:03}.json'
            archive.writestr(name, json.dumps(value, ensure_ascii=False))
            if duplicate and n == 1:
                with pytest.warns(UserWarning, match='Duplicate name'):
                    archive.writestr(name, '{}')
        archive.writestr(asdc.ROOT + '/data/supplemental/ignored.json', 'not JSON')
    manifest = {'schema_version': 1, 'source': source, 'source_id': source['id'],
                'source_config_sha256': digest_json(source), 'mode': 'sample', 'upstream_date': None,
                'retrieved_at': '2026-10-30T00:00:00Z', 'request': {'synthetic': True},
                'files': [{'path': path.name, 'role': asdc.ROLE, 'sha256': sha256_file(path),
                           'size': path.stat().st_size, 'url': source['acquisition']['url']}]}
    manifest['snapshot_id'] = snapshot_identity(manifest)
    return manifest


def test_main_identity_roles_and_context(tmp_path, monkeypatch):
    manifest = fixture(tmp_path, monkeypatch)
    documents = list(asdc.iter_documents(manifest, tmp_path))
    assert len(documents) == 210
    document = documents[0]
    assert document['native_id'] == 'asdc.v4.001'
    assert document['sentences'][0]['native_id'] == 'asdc.v4.001.0'
    assert document['sentences'][1] is asdc.CONTEXT_BREAK
    assert document['sentences'][2]['tags'] == ['speaker:customer']
    record = canonical_document(document, manifest, Counter(), set())
    assert [s['ordinal'] for s in record['sentences']] == [0, 1, 3]
    encoded = json.dumps(record, ensure_ascii=False)
    for private in ['private-scenario', 'operator_1', 'customer_35', 'text_sbs']:
        assert private not in encoded
    assert all(s['review_state'] == 'unreviewed' for s in record['sentences'])


@pytest.mark.parametrize('change', [
    lambda d: d['utterances'][0].update(text_fixed='修正した文です。'),
    lambda d: d['utterances'][0].update(name='bot_1'),
    lambda d: d['utterances'][1]['id'].update(id='asdc.v4.001.0'),
    lambda d: d['meta']['id'].update(id='wrong'),
    lambda d: d['utterances'][0].update(text=None),
])
def test_invalid_turns_fail_closed(tmp_path, monkeypatch, change):
    manifest = fixture(tmp_path, monkeypatch, change)
    with pytest.raises(DataError):
        list(asdc.iter_documents(manifest, tmp_path))


@pytest.mark.parametrize('kwargs', [{'omit': 210}, {'duplicate': True}])
def test_inventory_before_decode(tmp_path, monkeypatch, kwargs):
    manifest = fixture(tmp_path, monkeypatch, lambda d: d.update(utterances='invalid'), **kwargs)
    with pytest.raises(DataError, match='inventory'):
        next(asdc.iter_documents(manifest, tmp_path))


def test_evidence_before_decode(tmp_path, monkeypatch):
    manifest = fixture(tmp_path, monkeypatch, lambda d: d.update(utterances='invalid'))
    pins = copy.deepcopy(asdc.EVIDENCE)
    pins['README.md'] = '0' * 64
    monkeypatch.setattr(asdc, 'EVIDENCE', pins)
    manifest['source']['acquisition']['evidence_sha256'] = pins
    with pytest.raises(DataError, match='evidence'):
        next(asdc.iter_documents(manifest, tmp_path))


def test_compressed_fixture_build_and_normalized_export(tmp_path, monkeypatch):
    manifest = fixture(tmp_path, monkeypatch)
    path = tmp_path / 'manifest.json'
    write_json(path, manifest)
    build_corpus([path], tmp_path / 'build', record_format='jsonl', shard_compression='zstd')
    records = list(iter_records(tmp_path / 'build', verify_build(tmp_path / 'build')))
    assert len(records) == 210
    result = export_normalized(tmp_path / 'build', tmp_path / 'normalized.zip')
    with zipfile.ZipFile(result) as archive:
        works = [json.loads(line) for line in archive.read('works.jsonl').splitlines()]
        occurrences = [json.loads(line) for line in archive.read('occurrences.jsonl').splitlines()]
    assert len(works) == 210 and len(occurrences) == 630
    assert {row['ordinal'] for row in occurrences} == {0, 1, 3}


@pytest.mark.parametrize('mutation', ['root', 'symlink', 'bounds'])
def test_member_preflight_before_turn_decode(tmp_path, monkeypatch, mutation):
    def change(d):
        if mutation == 'bounds':
            d['utterances'][0]['text'] = 'x' * (2 * 1024**2 + 1)
        else:
            d.update(utterances='invalid')
    manifest = fixture(tmp_path, monkeypatch, change)
    with zipfile.ZipFile(tmp_path / 'asdc.zip', 'a') as archive:
        if mutation == 'root':
            archive.writestr('other-root/file.txt', 'unrelated')
        elif mutation == 'symlink':
            info = zipfile.ZipInfo(asdc.ROOT + '/link')
            info.create_system = 3
            info.external_attr = 0o120777 << 16
            archive.writestr(info, 'target')
    with pytest.raises(DataError, match='root/member|Oversized'):
        next(asdc.iter_documents(manifest, tmp_path))


def test_snapshot_pinned_full_archive_without_network(tmp_path, monkeypatch):
    from manabi_sentence_db import snapshot
    from manabi_sentence_db.validation import load_source

    source = load_source(Path('sources/asdc-main-ja.yaml'))
    calls = []

    def download(staging, filename, role, url, agent, **kwargs):
        calls.append((filename, role, url))
        raw = b'synthetic transport; extraction tests separately cover rights/ZIP'
        (staging / filename).write_bytes(raw)
        return {'path': filename, 'role': role, 'url': url, 'size': len(raw),
                'sha256': hashlib.sha256(raw).hexdigest()}

    monkeypatch.setattr(snapshot, '_download', download)
    path = snapshot.create_snapshot(source, tmp_path / 'snapshot', mode='full')
    manifest = snapshot.verify_snapshot(path)
    assert calls == [('asdc.zip', asdc.ROLE, source['acquisition']['url'])]
    assert asdc.REVISION in calls[0][2]
    assert manifest['mode'] == 'full'
    with pytest.raises(snapshot.SnapshotError, match='pinned full archive'):
        snapshot.create_snapshot(source, tmp_path / 'bad-sample', mode='sample')
    assert len(calls) == 1


@pytest.mark.parametrize('count', [True, 210.0, '210', 209])
def test_count_requires_exact_int(tmp_path, monkeypatch, count):
    manifest = fixture(tmp_path, monkeypatch)
    manifest['source']['acquisition']['dialogue_count'] = count
    with pytest.raises(DataError, match='210 main dialogues'):
        next(asdc.iter_documents(manifest, tmp_path))


def test_invalid_zip(tmp_path):
    source = yaml.safe_load(Path('sources/asdc-main-ja.yaml').read_text())
    (tmp_path / 'invalid.zip').write_bytes(b'not zip')
    with pytest.raises(DataError, match='ZIP archive'):
        next(asdc.iter_documents({'source': source, 'files': [{'role': asdc.ROLE, 'path': 'invalid.zip'}]}, tmp_path))
