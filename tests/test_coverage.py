import hashlib
import json
import zipfile

import pytest

from manabi_sentence_db.coverage import vocabulary_coverage
from manabi_sentence_db.normalized import sentence_identity
from manabi_sentence_db.serialization import DataError, canonical_json, sha256_file, write_json


def _archive(tmp_path, source, texts):
    rows = {"works": [{"id": source + "-work", "source_id": source}],
            "sentences": [], "occurrences": [], "translations": [], "references": []}
    for index, text in enumerate(texts):
        identity = sentence_identity("ja", text)
        rows["sentences"].append({"id": identity, "language": "ja", "text": text,
                                  "text_sha256": hashlib.sha256(text.encode()).hexdigest()})
        rows["occurrences"].append({"id": f"{source}-{index}", "work_id": source+"-work",
                                    "sentence_id": identity, "ordinal": index})
    members = {name + ".jsonl": b"".join(canonical_json(row)+b"\n" for row in values)
               for name, values in rows.items()}
    manifest = {"schema_version": 2, "kind": "normalized-corpus", "build_id": source,
                "scope": "sample", "counts": {name: len(values) for name, values in rows.items()},
                "members": {name: hashlib.sha256(value).hexdigest() for name, value in members.items()}}
    path = tmp_path / (source+".zip")
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("manifest.json", canonical_json(manifest))
        for name, value in members.items():
            archive.writestr(name, value)
    return path


def _analysis(tmp_path, pairs):
    path = tmp_path / "analysis.jsonl"
    path.write_bytes(b"".join(canonical_json({"sentence_id": sentence_identity("ja", text),
                                            "lemmas": lemmas})+b"\n" for text, lemmas in pairs))
    return path


def test_marginal_vocabulary_deduplicates_texts_and_exposes_unknown_analysis(tmp_path):
    common, new, missing = "犬が走っています。", "鳥が飛んでいます。", "猫が眠っています。"
    archives = [_archive(tmp_path, "base", [common]), _archive(tmp_path, "new", [common, new, missing])]
    analysis = _analysis(tmp_path, [(common, ["犬", "走る", "犬"]), (new, ["鳥", "飛ぶ"])])
    target = tmp_path / "target.json"
    write_json(target, ["犬", "猫", "鳥"])
    result = vocabulary_coverage(archives, analysis, tmp_path / "report.json", analyzer="fixture-v1",
                                 baseline_sources=["base"], target_vocabulary=target)
    report = json.loads(result.read_text())
    assert report["unique_sentences"] == 3
    base, added = report["sources"]
    assert base["unique_lemmas"] == 2 and base["novel_lemmas_vs_baseline"] == 0
    assert added["unique_lemmas"] == 4 and added["novel_lemmas_vs_baseline"] == 2
    assert added["analysis_coverage"] == 2/3 and added["missing_analysis"] == 1
    assert added["target_vocabulary_coverage"] == 2/3
    assert added["novel_target_lemmas_vs_baseline"] == 1
    assert report["baseline_target_vocabulary_coverage"] == 1/3
    assert report["combined_target_vocabulary_coverage"] == 2/3


def test_analysis_sidecar_pins_analyzer_digest_and_row_count(tmp_path):
    text = "犬が走っています。"
    archive = _archive(tmp_path, "base", [text])
    analysis = _analysis(tmp_path, [(text, ["犬"])])
    metadata = tmp_path / "meta.json"
    write_json(metadata, {"schema_version": 1, "analyzer": "fixture-v1", "sha256": sha256_file(analysis),
                          "exported_sentence_count": 1})
    vocabulary_coverage([archive], analysis, tmp_path / "ok.json", analyzer="fixture-v1", metadata=metadata)
    with pytest.raises(DataError, match="metadata"):
        vocabulary_coverage([archive], analysis, tmp_path / "bad.json", analyzer="other", metadata=metadata)
    assert not (tmp_path / "bad.json").exists()


def test_duplicate_analysis_and_overlapping_sources_fail_without_report(tmp_path):
    text = "犬が走っています。"
    archive = _archive(tmp_path, "base", [text])
    analysis = _analysis(tmp_path, [(text, ["犬"]), (text, ["犬"])])
    for paths in ([archive], [archive, archive]):
        with pytest.raises(DataError):
            vocabulary_coverage(paths, analysis, tmp_path / "bad.json", analyzer="fixture-v1")
        assert not (tmp_path / "bad.json").exists()


def test_coverage_without_target_list_is_not_a_percentage_claim(tmp_path):
    text = "犬が走っています。"
    archive = _archive(tmp_path, "base", [text])
    analysis = _analysis(tmp_path, [(text, [])])
    path = vocabulary_coverage([archive], analysis, tmp_path / "report.json", analyzer="fixture-v1")
    report = json.loads(path.read_text())
    assert report["sources"][0]["analyzed_sentences"] == 1
    assert report["sources"][0]["unique_lemmas"] == 0
    assert report["sources"][0]["target_vocabulary_coverage"] is None
