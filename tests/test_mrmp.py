import copy
import hashlib
import json
import stat
import zipfile
from collections import Counter
from pathlib import Path

import pytest

from manabi_sentence_db.build import build_corpus, canonical_document, iter_records, verify_build
from manabi_sentence_db.mrmp import ROLE, iter_documents
from manabi_sentence_db.normalized import export_normalized
from manabi_sentence_db.segments import PUBLISHER_CONTEXT_VERSION
from manabi_sentence_db.serialization import DataError, digest_json, sha256_file, write_json
from manabi_sentence_db.snapshot import snapshot_identity
from manabi_sentence_db.validation import load_source

PREFIX = "repo/multi_relational_multi_party_chat_corpus/"
MEMBER = PREFIX + "dialogues/A_first_time/A00101.json"
LICENSE = b"Synthetic fixture: CC BY-SA 4.0"
README = b"Synthetic human dialogue fixture"


def dialogue():
    return {"dialogue_id": "A00101", "dialogue_type": "First time",
            "interlocutors": ["private-person"], "relationship": ["private-relationship"],
            "evaluations": [{"private-evaluation": "評価は例文ではない。"}],
            "utterances": [
                {"utterance_id": 0, "text": "今日は公園を散歩しました。", "interlocutor_id": "private-person"},
                {"utterance_id": 1, "text": "＊＊で働いています。"},
                {"utterance_id": 2, "text": "川の水がきれいですね。"},
                {"utterance_id": 5, "text": "明日は図書館に行きます。"},
            ]}


def fixture(tmp_path, value=None, *, member=MEMBER, count=1):
    source = copy.deepcopy(load_source(Path("sources/mrmp-ja.yaml")))
    source["acquisition"]["dialogue_count"] = count
    source["acquisition"]["license_sha256"] = hashlib.sha256(LICENSE).hexdigest()
    source["acquisition"]["readme_sha256"] = hashlib.sha256(README).hexdigest()
    value = dialogue() if value is None else value
    raw = value if isinstance(value, bytes) else json.dumps(value, ensure_ascii=False).encode()
    archive_path = tmp_path / "mrmp.zip"
    with zipfile.ZipFile(archive_path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr(member, raw)
        archive.writestr("repo/LICENSE", LICENSE)
        archive.writestr("repo/README.md", README)
        archive.writestr(PREFIX + "interlocutors.json", '{"private-profile":"秘匿の人物紹介です。"}')
        archive.writestr("repo/model_experiments/outputs.json", '{"text":"機械の発話です。"}')
    manifest = {
        "schema_version": 1, "source": source, "source_id": source["id"],
        "source_config_sha256": digest_json(source), "mode": "sample", "upstream_date": None,
        "retrieved_at": "2026-10-30T00:00:00Z", "request": {"synthetic": True},
        "files": [{"path": "mrmp.zip", "role": ROLE, "sha256": sha256_file(archive_path),
                   "size": archive_path.stat().st_size, "url": source["acquisition"]["url"]}],
    }
    manifest["snapshot_id"] = snapshot_identity(manifest)
    return manifest, raw


def test_human_turns_keep_text_identity_credit_and_context_without_private_fields(tmp_path):
    manifest, raw = fixture(tmp_path)
    document = next(iter_documents(manifest, tmp_path))
    assert document["native_id"] == "A_first_time/A00101"
    assert document["source_text_hash"] == hashlib.sha256(raw).hexdigest()
    assert document["url"].endswith("/" + MEMBER.split("/", 1)[1])
    assert manifest["source"]["acquisition"]["revision"] in document["url"]
    assert document["authorship"] == "human"
    assert document["language_origin"] == "original_japanese"
    stats = Counter()
    record = canonical_document(document, manifest, stats, set())
    assert record["license"] == manifest["source"]["license"]
    assert record["attribution"] == manifest["source"]["attribution"]
    assert PUBLISHER_CONTEXT_VERSION in record["transformations"]
    assert [row["text"] for row in record["sentences"]] == [
        "今日は公園を散歩しました。", "川の水がきれいですね。", "明日は図書館に行きます。",
    ]
    assert [row["ordinal"] for row in record["sentences"]] == [0, 2, 4]
    assert [row["source_range"]["start"] for row in record["sentences"]] == [0, 2, 5]
    assert stats["rejected:masked-personal-information"] == 1
    assert all(row["review_state"] == "unreviewed" for row in record["sentences"])
    assert "private-" not in json.dumps(record, ensure_ascii=False)


def test_full_compressed_fixture_build_and_export_preserve_gaps(tmp_path):
    manifest, _ = fixture(tmp_path)
    path = tmp_path / "manifest.json"
    write_json(path, manifest)
    build_corpus([path], tmp_path / "build", record_format="jsonl", shard_compression="zstd")
    records = list(iter_records(tmp_path / "build", verify_build(tmp_path / "build")))
    assert len(records) == 1 and len(records[0]["sentences"]) == 3
    result = export_normalized(tmp_path / "build", tmp_path / "normalized.zip")
    with zipfile.ZipFile(result) as archive:
        occurrences = [json.loads(line) for line in archive.read("occurrences.jsonl").splitlines()]
        works = [json.loads(line) for line in archive.read("works.jsonl").splitlines()]
    assert [row["ordinal"] for row in occurrences] == [0, 2, 4]
    assert works[0]["revision"]["id"] == manifest["source"]["acquisition"]["revision"]
    assert works[0]["source_text_hash"] == records[0]["source_text_hash"]


@pytest.mark.parametrize("change", [
    lambda d: d.update(dialogue_id="other"),
    lambda d: d.update(dialogue_type="unknown"),
    lambda d: d.update(utterances={}),
    lambda d: d.update(utterances=[]),
    lambda d: d["utterances"][1].update(utterance_id=0),
    lambda d: d["utterances"][0].update(utterance_id=-1),
    lambda d: d["utterances"][0].update(utterance_id=True),
    lambda d: d["utterances"][0].update(text=None),
    lambda d: d["utterances"].reverse(),
])
def test_invalid_identity_order_type_or_turns_fail_closed(tmp_path, change):
    value = dialogue()
    change(value)
    manifest, _ = fixture(tmp_path, value)
    with pytest.raises(DataError):
        list(iter_documents(manifest, tmp_path))


@pytest.mark.parametrize("raw", [b'{"dialogue_id":', b'\xff', b'{"dialogue_id":1,"dialogue_id":2}'])
def test_malformed_or_duplicate_key_json_is_rejected(tmp_path, raw):
    manifest, _ = fixture(tmp_path, raw)
    with pytest.raises(DataError):
        list(iter_documents(manifest, tmp_path))


def test_sparse_turn_ids_reserve_one_barrier_without_allocating_the_missing_range(tmp_path):
    value = dialogue()
    value["utterances"][-1]["utterance_id"] = 10**12
    manifest, _ = fixture(tmp_path, value)
    record = canonical_document(next(iter_documents(manifest, tmp_path)), manifest, Counter(), set())
    assert [row["ordinal"] for row in record["sentences"]] == [0, 2, 4]
    assert record["sentences"][-1]["source_range"]["start"] == 10**12


@pytest.mark.parametrize("other", [MEMBER, MEMBER.replace("repo/", "other/")])
def test_duplicate_members_or_work_identities_are_rejected(tmp_path, other):
    manifest, raw = fixture(tmp_path)
    with zipfile.ZipFile(tmp_path / "mrmp.zip", "a") as archive:
        if other == MEMBER:
            with pytest.warns(UserWarning, match="Duplicate"):
                archive.writestr(other, raw)
        else:
            archive.writestr(other, raw)
    with pytest.raises(DataError, match="Duplicate"):
        list(iter_documents(manifest, tmp_path))


def test_non_dialogue_and_unknown_groups_cannot_satisfy_the_inventory(tmp_path):
    manifest, _ = fixture(tmp_path, member=PREFIX + "dialogues/model/A00101.json")
    with pytest.raises(DataError, match="inventory"):
        list(iter_documents(manifest, tmp_path))


def test_symlink_member_and_oversized_turn_collection_are_rejected(tmp_path):
    manifest, _ = fixture(tmp_path)
    info = zipfile.ZipInfo(MEMBER)
    info.external_attr = (stat.S_IFLNK | 0o777) << 16
    with zipfile.ZipFile(tmp_path / "mrmp.zip", "w") as archive:
        archive.writestr(info, b"target")
        archive.writestr("repo/LICENSE", LICENSE)
        archive.writestr("repo/README.md", README)
    with pytest.raises(DataError, match="symlink"):
        list(iter_documents(manifest, tmp_path))
    value = dialogue()
    value["utterances"] *= 251
    manifest, _ = fixture(tmp_path, value)
    with pytest.raises(DataError, match="turn collection"):
        list(iter_documents(manifest, tmp_path))


def test_license_pin_failure_precedes_every_dialogue_decode(tmp_path, monkeypatch):
    from manabi_sentence_db import mrmp

    manifest, _ = fixture(tmp_path)
    manifest["source"]["acquisition"]["license_sha256"] = "0" * 64
    def forbidden(*args):
        pytest.fail("Unqualified license reached dialogue decoding")
    monkeypatch.setattr(mrmp, "parse_json", forbidden)
    with pytest.raises(DataError, match="license evidence differs"):
        list(iter_documents(manifest, tmp_path))


def test_oversized_member_is_refused_before_reading_its_payload(tmp_path, monkeypatch):
    manifest, _ = fixture(tmp_path)
    original = zipfile.ZipFile.infolist
    def oversized(archive):
        items = original(archive)
        next(item for item in items if item.filename == MEMBER).file_size = 2 * 1024**2 + 1
        return items
    monkeypatch.setattr(zipfile.ZipFile, "infolist", oversized)
    with pytest.raises(DataError, match="Oversized"):
        list(iter_documents(manifest, tmp_path))


def test_snapshot_uses_only_the_pinned_full_archive_without_network(tmp_path, monkeypatch):
    from manabi_sentence_db import snapshot

    source = load_source(Path("sources/mrmp-ja.yaml"))
    calls = []
    def download(staging, filename, role, url, agent, **kwargs):
        calls.append((filename, role, url))
        payload = b"synthetic transport bytes; extraction tests cover ZIP/rights"
        (staging / filename).write_bytes(payload)
        return {"path": filename, "role": role, "url": url,
                "size": len(payload), "sha256": hashlib.sha256(payload).hexdigest()}
    monkeypatch.setattr(snapshot, "_download", download)
    path = snapshot.create_snapshot(source, tmp_path / "snapshot", mode="full")
    manifest = snapshot.verify_snapshot(path)
    assert calls == [("mrmp.zip", ROLE, source["acquisition"]["url"])]
    assert manifest["mode"] == "full" and manifest["source"]["acquisition"] == source["acquisition"]
    with pytest.raises(snapshot.SnapshotError, match="pinned full archive"):
        snapshot.create_snapshot(source, tmp_path / "bad-sample", mode="sample")
    assert len(calls) == 1


def test_corrupt_zip_is_a_displayable_corpus_error(tmp_path):
    manifest, _ = fixture(tmp_path)
    (tmp_path / "mrmp.zip").write_bytes(b"bad ZIP")
    with pytest.raises(DataError, match="Invalid MRMP ZIP"):
        list(iter_documents(manifest, tmp_path))


@pytest.mark.parametrize("addressed", [
    "@たまねぎ 長野なんですね。",
    "  @たまご 多分仲良くできそうですよ。",
    "＠うどん それより西です。",
    "今は猫でいいや！ @つくね",
    "そうだぞ@つくね",
    "今日は図書館へ行きます。\n@うさぎ 明日は公園へ行きます。",
])
@pytest.mark.parametrize("position", [0, 1, 2])
def test_addressed_turn_is_withheld_before_segmentation_and_reserves_gap(
    tmp_path, addressed, position
):
    from manabi_sentence_db.segments import CONTEXT_BREAK

    value = dialogue()
    value["utterances"] = [
        {"utterance_id": i, "text": addressed if i == position else
         "今日は公園を散歩しました。川の水がきれいですね。"}
        for i in range(3)
    ]
    manifest, _ = fixture(tmp_path, value)
    document = next(iter_documents(manifest, tmp_path))
    assert document["sentences"][position] is CONTEXT_BREAK
    record = canonical_document(document, manifest, Counter(), set())
    assert addressed not in json.dumps(record, ensure_ascii=False)
    assert all("@" not in s["text"] and "＠" not in s["text"] for s in record["sentences"])
    assert [s["ordinal"] for s in record["sentences"]] == {
        0: [1, 2, 3, 4], 1: [0, 1, 3, 4], 2: [0, 1, 2, 3],
    }[position]


def test_food_words_in_authored_prose_are_unchanged(tmp_path):
    value = dialogue()
    text = "たまねぎと卵を使って料理しました。"
    value["utterances"] = [{"utterance_id": 0, "text": text}]
    manifest, _ = fixture(tmp_path, value)
    document = next(iter_documents(manifest, tmp_path))
    assert document["sentences"][0]["text"] == text
    record = canonical_document(document, manifest, Counter(), set())
    assert [s["text"] for s in record["sentences"]] == [text]


def test_addressed_turn_stays_out_of_compressed_normalized_export(tmp_path):
    value = dialogue()
    withheld = "今日は料理をしました。\n@たまねぎ 長野なんですね。"
    value["utterances"][-1]["text"] = withheld
    value["utterances"].append({"utterance_id": 6, "text": "明日は図書館に行きます。"})
    manifest, _ = fixture(tmp_path, value)
    path = tmp_path / "manifest.json"
    write_json(path, manifest)
    build_corpus([path], tmp_path / "build", record_format="jsonl", shard_compression="zstd")
    result = export_normalized(tmp_path / "build", tmp_path / "normalized.zip")
    with zipfile.ZipFile(result) as archive:
        occurrences = [json.loads(line) for line in archive.read("occurrences.jsonl").splitlines()]
        sentences = archive.read("sentences.jsonl").decode()
    assert [row["ordinal"] for row in occurrences] == [0, 2, 5]
    assert "@" not in sentences and "料理をしました" not in sentences
