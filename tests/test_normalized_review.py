"""Small review packet tests; no production corpus access."""

import json

import pytest
import zstandard
from test_normalized_selection import _fixture

from manabi_sentence_db import normalized_review as review
from manabi_sentence_db.review_sampling import TopicReviewSampler
from manabi_sentence_db.serialization import DataError, sha256_file


def _build(paths, output, **options):
    return review.build_topic_review(paths, {"selected": "animals", "other": "animals"}, output,
                                    archive_sha256=options.pop("archive_sha256", {
                                        path.name: sha256_file(path) for path in paths}),
                                    seed="fixture", **options)


def _read(path):
    return json.loads(zstandard.ZstdDecompressor().decompress(path.read_bytes()))


def test_order_reference_citations_and_exact_records(tmp_path):
    folders = [tmp_path / name for name in ("one", "two")]
    for folder in folders:
        folder.mkdir()
    first, tables, _ = _fixture(folders[0])
    second, _, _ = _fixture(folders[1])
    second = second.rename(second.with_name("aaa.zip"))
    one, two = tmp_path / "one.zst", tmp_path / "two.zst"
    report = _build([first, second], one, per_topic=2)
    _build([second, first], two, per_topic=2)
    assert one.read_bytes() == two.read_bytes()
    packet = _read(one)
    sampler = TopicReviewSampler(["animals"], seed="fixture", per_topic=2)
    for path in (first, second):
        for row in tables["occurrences"]:
            sampler.add("animals", row["sentence_id"], row["work_id"], path.name)
    expected = sampler.results()["animals"]
    assert [case["sentence"]["id"] for case in packet["cases"]] == [
        candidate.sentence_id for candidate in expected]
    for case, candidate in zip(packet["cases"], expected, strict=True):
        assert case["archive"] == "aaa.zip"
        assert case["work"] == next(row for row in tables["works"]
                                    if row["id"] == candidate.work_id)
        assert case["sentence"] == next(row for row in tables["sentences"]
                                        if row["id"] == candidate.sentence_id)
    assert packet["assistant_only"] and packet["review_pending"]
    assert packet["human_review"] is False
    assert report["by_topic"] == {"animals": 2}
    assert report["sha256"] == sha256_file(one)
    assert zstandard.get_frame_parameters(one.read_bytes()).has_checksum


@pytest.mark.parametrize("change", [
    lambda t: t["occurrences"][0].update(work_id="unknown"),
    lambda t: t["works"].pop(),
    lambda t: t["sentences"].pop(),
    lambda t: t["works"].append(t["works"][0].copy()),
    lambda t: t["sentences"].append(t["sentences"][0].copy()),
    lambda t: t["sentences"][0].update(text="changed"),
    lambda t: t["works"][0]["license"].update(id="unknown"),
])
def test_bad_sample_or_unknown_work_never_emits(tmp_path, change):
    path, _, _ = _fixture(tmp_path, change=change)
    output = tmp_path / "review.zst"
    with pytest.raises(DataError):
        _build([path], output)
    assert not output.exists()


@pytest.mark.parametrize("expected", [{}, {"input.zip": "0" * 64},
                                      {"input.zip": "bad"}, {"other": "0" * 64}])
def test_exact_expected_checksums(tmp_path, expected):
    path, _, _ = _fixture(tmp_path)
    output = tmp_path / "review.zst"
    with pytest.raises(DataError):
        _build([path], output, archive_sha256=expected)
    assert not output.exists()


def test_output_existing_and_symlink_rejected(tmp_path):
    path, _, _ = _fixture(tmp_path)
    existing = tmp_path / "existing.zst"
    existing.write_bytes(b"keep")
    with pytest.raises(DataError):
        _build([path], existing)
    assert existing.read_bytes() == b"keep"
    linked = tmp_path / "linked"
    linked.symlink_to(tmp_path, target_is_directory=True)
    with pytest.raises(DataError):
        _build([path], linked / "output.zst")
    dangling = tmp_path / "dangling"
    dangling.symlink_to(tmp_path / "absent")
    with pytest.raises(DataError):
        _build([path], dangling)


def test_changed_input_rejected(tmp_path, monkeypatch):
    path, _, _ = _fixture(tmp_path)
    original = review._rows

    def changing(archive, table, manifest):
        yield from original(archive, table, manifest)
        if table == "sentences":
            with path.open("ab") as stream:
                stream.write(b"mutation")

    monkeypatch.setattr(review, "_rows", changing)
    output = tmp_path / "review.zst"
    with pytest.raises(DataError, match="changed"):
        _build([path], output)
    assert not output.exists()


def test_member_checks_complete_after_selected_rows(tmp_path):
    path, _, _ = _fixture(tmp_path, extra=lambda members: members.update({
        "sentences.jsonl": members["sentences.jsonl"] + b"{}\n"}))
    output = tmp_path / "review.zst"
    with pytest.raises(DataError, match="digest"):
        _build([path], output)
    assert not output.exists()


def test_unique_basenames_and_invalid_parameters(tmp_path):
    path, _, _ = _fixture(tmp_path)
    for options in ({"seed": "", "per_topic": 1}, {"seed": "x", "per_topic": 0}):
        with pytest.raises(ValueError):
            review.build_topic_review([path], {"selected": "animals"}, tmp_path / "review.zst",
                                      archive_sha256={path.name: sha256_file(path)}, **options)
    with pytest.raises(DataError, match="unique"):
        _build([path, path], tmp_path / "review.zst")
