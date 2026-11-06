import hashlib
import json

import zstandard
from test_normalized_selection import _fixture

from manabi_sentence_db.cli import main


def test_review_cli_writes_deterministic_attributed_packet(tmp_path, capsys):
    root = tmp_path.resolve()
    archive, _, _ = _fixture(root)
    topics = root / "topics.json"
    topics.write_text(json.dumps({"selected": "food", "other": "travel"}))
    checksums = root / "checksums.json"
    checksums.write_text(json.dumps({archive.name: hashlib.sha256(archive.read_bytes()).hexdigest()}))
    base = ["review-normalized-topics", "--archive", str(archive), "--work-topics", str(topics),
            "--archive-checksums", str(checksums), "--seed", "cli-v1", "--per-topic", "1"]
    outputs = [root / "one.json.zst", root / "two.json.zst"]
    for output in outputs:
        assert main(base + ["--output", str(output)]) == 0
        report = json.loads(capsys.readouterr().out)
        assert report["by_topic"] == {"food": 1, "travel": 1}
        assert report["review_pending"] and not report["human_review"]
    assert outputs[0].read_bytes() == outputs[1].read_bytes()
    packet = json.loads(zstandard.ZstdDecompressor().decompress(outputs[0].read_bytes()))
    assert all(row["work"]["license"]["id"] == "CC0-1.0" for row in packet["cases"])
    assert all(row["sentence"]["text"] for row in packet["cases"])
    rejected = root / "rejected.json.zst"
    checksums.write_text(json.dumps({archive.name: "0" * 64}))
    assert main(base + ["--output", str(rejected)]) == 2
    assert not rejected.exists()
    assert "checksum" in capsys.readouterr().err
