"""Synthetic visual-dialogue text; never acquire images or upstream data in tests."""
import copy
import csv
import io
import json
import stat
import zipfile
from collections import Counter
from pathlib import Path

import pytest

from manabi_sentence_db import vfd
from manabi_sentence_db.build import build_corpus, canonical_document, iter_records, verify_build
from manabi_sentence_db.normalized import export_normalized
from manabi_sentence_db.serialization import DataError, digest_json, sha256_file, write_json
from manabi_sentence_db.snapshot import create_snapshot, snapshot_identity
from manabi_sentence_db.validation import load_source


def fixture(tmp_path, monkeypatch, rows=None, *, header=None, extra=None, mode=None, raw=None):
    rows = rows if rows is not None else [
        ['今日は公園を散歩しました。', '00000001/00000002.jpg', '9',
         '天気がよくて気持ちいいですね。', 'PRIVATE ACTION DESCRIPTION'],
        ['青い空', '00000001/00000002.jpg', '9', '明日は海へ行きます。', 'x']]
    text = io.StringIO(newline='')
    writer = csv.writer(text, delimiter='\t', lineterminator='\n')
    writer.writerow(vfd.HEADER if header is None else header)
    writer.writerows(rows)
    payload = raw if raw is not None else text.getvalue().encode()
    path = tmp_path / 'publisher.zip'
    with zipfile.ZipFile(path, 'w', compression=zipfile.ZIP_DEFLATED) as archive:
        for name, data in [('README.md', b'Synthetic publisher CC BY 4.0 notice.'),
                           ('prepare_data_for_selection_task.py', b'PRIVATE NEVER EXECUTE'),
                           ('vfd.tsv', payload)]:
            entry = zipfile.ZipInfo(vfd.PREFIX + name)
            if name == 'vfd.tsv' and mode is not None:
                entry.create_system = 3
                entry.external_attr = mode << 16
            archive.writestr(entry, data)
        if extra:
            archive.writestr(vfd.PREFIX + extra, b'PRIVATE DO NOT EXPORT')
    monkeypatch.setattr(vfd, 'SHA256', sha256_file(path))
    monkeypatch.setattr(vfd, 'ARCHIVE_BYTES', path.stat().st_size)
    monkeypatch.setattr(vfd, 'TEXT_BYTES', len(payload))
    monkeypatch.setattr(vfd, 'ROW_COUNT', len(rows))
    source = copy.deepcopy(load_source(Path('sources/yahoo-vfd-ja.yaml')))
    source['acquisition'].update(sha256=vfd.SHA256, size=vfd.ARCHIVE_BYTES)
    manifest = dict(schema_version=1, source_id=source['id'], source=source,
        source_config_sha256=digest_json(source), mode='sample', upstream_date=None,
        retrieved_at='2026-11-04T00:00:00Z', request={'synthetic': True}, files=[
            dict(path=path.name, role=vfd.ROLE, size=path.stat().st_size,
                 sha256=sha256_file(path), url=source['acquisition']['url'])])
    manifest['snapshot_id'] = snapshot_identity(manifest)
    return manifest


def test_spoken_pairs_preserve_origin_rights_and_gaps_without_actions_or_images(tmp_path, monkeypatch):
    manifest = fixture(tmp_path, monkeypatch)
    stats = Counter()
    docs = list(vfd.iter_documents(manifest, tmp_path, stats=stats))
    records = [canonical_document(raw, manifest, stats, set()) for raw in docs]
    assert stats['vfd_rows_seen'] == 2 and stats['rejected:vfd-incomplete-unit'] == 1
    assert [s['text'] for s in records[0]['sentences']] == [
        '今日は公園を散歩しました。', '天気がよくて気持ちいいですね。']
    assert [s['ordinal'] for s in records[1]['sentences']] == [1]
    assert len({r['id'] for r in records}) == 2  # Shared gaze IDs are not dialogue IDs.
    for record in records:
        assert record['authorship'] == 'human' and record['language_origin'] == 'original_japanese'
        assert record['license']['id'] == 'CC-BY-4.0' and record['content_type'] == 'dialogue'
        assert 'context:image-not-included' in record['tags']
        assert vfd.TRANSFORMATION in record['transformations']
        assert all(s['review_state'] == 'unreviewed' and not s['translations']
                   for s in record['sentences'])
    assert 'PRIVATE' not in json.dumps(records)
    assert '.jpg' not in json.dumps(records)


@pytest.mark.parametrize('bad', ['', 'x', 'X', '青い空'])
def test_dummy_and_unpunctuated_turns_are_barriers_not_spoken_examples(tmp_path, monkeypatch, bad):
    row = [bad, '00000001/00000002.jpg', '0', '一緒に行きましょう。', '触ってみる。']
    manifest = fixture(tmp_path, monkeypatch, [row])
    stats = Counter()
    record = canonical_document(next(vfd.iter_documents(manifest, tmp_path, stats=stats)),
                                manifest, stats, set())
    assert [(s['text'], s['ordinal']) for s in record['sentences']] == [('一緒に行きましょう。', 1)]
    assert '触ってみる' not in json.dumps(record, ensure_ascii=False)


@pytest.mark.parametrize('change', [
    lambda r: r.pop(), lambda r: r.append('unexpected'),
    lambda r: r.__setitem__(2, '-1'), lambda r: r.__setitem__(2, '9.0'),
    lambda r: r.__setitem__(1, ''), lambda r: r.__setitem__(0, 'あ' * 20001),
])
def test_malformed_rows_fail_closed(tmp_path, monkeypatch, change):
    row = ['今日は晴れです。', '00000001/00000002.jpg', '9', 'いい天気ですね。', 'x']
    change(row)
    manifest = fixture(tmp_path, monkeypatch, [row])
    with pytest.raises(DataError):
        list(vfd.iter_documents(manifest, tmp_path))


@pytest.mark.parametrize('kwargs', [
    {'header': ['utterance', 'image_path', 'gfid', 'verbal_response', 'non_verbal_response']},
    {'extra': 'images/example.jpg'}, {'mode': stat.S_IFLNK | 0o777},
    {'raw': b'\xff'}, {'raw': b'utterance\tverbal_response\n'}])
def test_unreviewed_inventory_header_or_encoding_fails(tmp_path, monkeypatch, kwargs):
    with pytest.raises(DataError):
        list(vfd.iter_documents(fixture(tmp_path, monkeypatch, **kwargs), tmp_path))


def test_pinned_count_and_archive_hash_are_required(tmp_path, monkeypatch):
    manifest = fixture(tmp_path, monkeypatch)
    monkeypatch.setattr(vfd, 'ROW_COUNT', 3)
    with pytest.raises(DataError, match='row count'):
        list(vfd.iter_documents(manifest, tmp_path))
    monkeypatch.setattr(vfd, 'SHA256', '0' * 64)
    manifest['source']['acquisition']['sha256'] = '0' * 64
    with pytest.raises(DataError, match='checksum'):
        list(vfd.iter_documents(manifest, tmp_path))


def test_citations_follow_physical_tsv_lines_after_quoted_multiline_fields(tmp_path, monkeypatch):
    rows = [
        ['今日は晴れです。\n一緒に歩きましょう。', 'image.jpg', '0', 'いいですね。', 'x'],
        ['今日は雨です。', 'image.jpg', '1', '家で休みましょう。', 'x']]
    docs = list(vfd.iter_documents(fixture(tmp_path, monkeypatch, rows), tmp_path))
    assert docs[0]['url'].endswith('#L2') and docs[1]['url'].endswith('#L4')


def test_compressed_pipeline_preserves_pair_boundaries_and_public_attribution(tmp_path, monkeypatch):
    manifest = fixture(tmp_path, monkeypatch)
    write_json(tmp_path / 'manifest.json', manifest)
    build_corpus([tmp_path / 'manifest.json'], tmp_path / 'build',
                 record_format='jsonl', shard_compression='zstd')
    catalog = verify_build(tmp_path / 'build')
    records = list(iter_records(tmp_path / 'build', catalog))
    assert len(records) == 2 and all(e['path'].endswith('.zst') for e in catalog['shards'])
    path = export_normalized(tmp_path / 'build', tmp_path / 'normalized.zip', catalog=catalog)
    with zipfile.ZipFile(path) as archive:
        works = [json.loads(line) for line in archive.read('works.jsonl').splitlines()]
        occurrences = [json.loads(line) for line in archive.read('occurrences.jsonl').splitlines()]
    assert len(works) == 2 and len(occurrences) == 3
    assert 'PRIVATE' not in json.dumps(works + occurrences)
    assert all('Hisashi Kamezawa' in w['attribution']['text'] for w in works)


@pytest.mark.parametrize('field,value', [('revision', 'unreviewed'), ('sha256', '0' * 64),
    ('size', True), ('url', 'https://example.org/other.zip')])
def test_acquisition_pins_cannot_be_overridden(tmp_path, monkeypatch, field, value):
    manifest = fixture(tmp_path, monkeypatch)
    manifest['source']['acquisition'][field] = value
    with pytest.raises(DataError, match='reviewed'):
        list(vfd.iter_documents(manifest, tmp_path))


def test_snapshot_uses_exact_compressed_pin_and_reuses_without_network(tmp_path, monkeypatch):
    from manabi_sentence_db import snapshot as snapshots

    inputs = tmp_path / 'inputs'
    inputs.mkdir()
    source = fixture(inputs, monkeypatch)['source']
    requests = []

    def download(destination, name, role, url, agent, *, expected_sha256, expected_size):
        origin = inputs / 'publisher.zip'
        assert role == vfd.ROLE and url == source['acquisition']['url']
        assert expected_sha256 == sha256_file(origin) and expected_size == origin.stat().st_size
        (destination / name).write_bytes(origin.read_bytes())
        requests.append(url)
        return dict(path=name, role=role, url=url, sha256=expected_sha256, size=expected_size)

    monkeypatch.setattr(snapshots, '_download', download)
    output = tmp_path / 'snapshot'
    result = create_snapshot(source, output, mode='full')
    assert requests == [source['acquisition']['url']]

    def no_network(*args, **kwargs):
        raise AssertionError('An unchanged VFD snapshot must not download again')

    monkeypatch.setattr(snapshots, '_download', no_network)
    assert create_snapshot(source, output, mode='full') == result


def test_translations_cannot_be_requested_from_a_monolingual_source(tmp_path, monkeypatch):
    inputs = tmp_path / 'inputs'
    inputs.mkdir()
    source = fixture(inputs, monkeypatch)['source']
    with pytest.raises(ValueError, match='translations applies only to Tatoeba'):
        create_snapshot(source, tmp_path / 'snapshot', mode='full', translations=['en'])


@pytest.mark.parametrize("role", ["utterance", "verbal_response"])
def test_reviewed_spoken_unit_is_withheld_before_splitting_with_gap(tmp_path, monkeypatch, role):
    import hashlib

    bad = "これは合成の除外対象です。同じ発話の残りも除外します。"
    row = ['今日は晴れています。', '00000001/00000002.jpg', '9',
           '明日は海へ行きます。', 'PRIVATE ACTION']
    row[0 if role == "utterance" else 3] = bad
    manifest = fixture(tmp_path, monkeypatch, [row])
    monkeypatch.setattr(vfd, 'REVIEWED_UNIT_EXCLUSIONS', {
        hashlib.sha256(bad.encode()).hexdigest(): 'vfd-reviewed-wording'})
    stats = Counter()
    raw = next(vfd.iter_documents(manifest, tmp_path, stats=stats))
    record = canonical_document(raw, manifest, stats, set())
    assert [(s['text'], s['ordinal']) for s in record['sentences']] == [
        (row[3], 1) if role == "utterance" else (row[0], 0)]
    assert stats['rejected:vfd-reviewed-wording'] == 1
    assert vfd.QUALITY_VERSION in record['transformations']


def test_vfd_compressed_refinement_removes_whole_units_but_preserves_other_speakers_and_rights(
        tmp_path, monkeypatch):
    import hashlib
    import sqlite3

    from manabi_sentence_db.cli import main
    from manabi_sentence_db.normalized_database import build_normalized_database
    from manabi_sentence_db.refinement import refine_vfd

    first = "今日は晴れています。"
    bad = first + "これは合成の除外対象です。"
    rows = [[first, '00000001/00000002.jpg', '9', bad, 'PRIVATE ACTION'],
            [bad, '00000001/00000002.jpg', '9', '明日は海へ行きます。', 'x']]
    manifest = fixture(tmp_path, monkeypatch, rows)
    snapshot = tmp_path / 'manifest.json'
    write_json(snapshot, manifest)
    parent = tmp_path / 'parent'
    build_corpus([snapshot], parent, record_format='jsonl', shard_compression='zstd')
    original = list(iter_records(parent, verify_build(parent)))
    before = {str(p.relative_to(parent)): sha256_file(p) for p in parent.rglob('*') if p.is_file()}
    snapshot.rename(tmp_path / 'retired-manifest.json')
    (tmp_path / 'publisher.zip').rename(tmp_path / 'retired-raw.zip')
    monkeypatch.setattr(vfd, 'REVIEWED_UNIT_EXCLUSIONS', {
        hashlib.sha256(bad.encode()).hexdigest(): 'vfd-reviewed-wording'})
    output = tmp_path / 'refined'
    assert main(['refine-vfd', '--build', str(parent), '--output', str(output)]) == 0
    records = list(iter_records(output, verify_build(output)))
    expected = copy.deepcopy(original)
    expected[0]['sentences'] = [original[0]['sentences'][0]]
    expected[1]['sentences'] = [original[1]['sentences'][-1]]
    assert records == expected
    assert records[0]['sentences'][0]['text'] == first
    assert records[1]['sentences'][0]['ordinal'] == 2
    assert before == {str(p.relative_to(parent)): sha256_file(p) for p in parent.rglob('*') if p.is_file()}
    catalog = verify_build(output)
    assert catalog['statistics']['rejected:vfd-reviewed-wording'] == 4
    assert catalog['options']['refinement']['policy'] == vfd.QUALITY_VERSION
    archive = export_normalized(output, tmp_path / 'refined.zip')
    with zipfile.ZipFile(archive) as z:
        occurrences = [json.loads(line) for line in z.read('occurrences.jsonl').splitlines()]
    assert all(r['previous_id'] is None and r['next_id'] is None for r in occurrences)
    database = tmp_path / 'consumer.sqlite'
    build_normalized_database(archive, database)
    with sqlite3.connect(database) as db:
        metadata = dict(db.execute('SELECT key,value FROM metadata'))
    assert json.loads(metadata['catalog'])['options']['refinement']['policy'] == vfd.QUALITY_VERSION
    assert json.loads(metadata['refinement_parent_catalog']) == verify_build(parent)
    again = tmp_path / 'again'
    refine_vfd(output, again)
    assert list(iter_records(again, verify_build(again))) == records
    assert not list(output.rglob('*.sqlite*'))


def test_vfd_reviewed_exact_units_do_not_ban_related_photography_or_clothing():
    assert vfd.assess_reviewed_unit("この市場の日常風景を撮っっています。") == 'vfd-reviewed-wording'
    assert vfd.assess_reviewed_unit("私のファースト・トップレスよ。") == 'vfd-reviewed-adult-context'
    assert vfd.assess_reviewed_unit("この市場の日常風景を撮っています。") is None
    assert vfd.assess_reviewed_unit("私の新しいトップスよ。") is None
