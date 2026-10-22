import json
import zipfile
from collections import Counter

from manabi_sentence_db.build import canonical_document
from manabi_sentence_db.realpersonachat import iter_documents
from manabi_sentence_db.validation import load_source


def test_dialogue_file_identity_survives_publisher_id_collisions(tmp_path):
    source = load_source(__import__("pathlib").Path("sources/realpersonachat-ja.yaml"))
    with zipfile.ZipFile(tmp_path / "data.zip", "w") as archive:
        for name in ("10279", "10577"):
            archive.writestr(
                f"repo/real_persona_chat/dialogues/{name}.json",
                json.dumps(
                    {
                        "dialogue_id": 10577,
                        "utterances": [
                            {"utterance_id": 0, "text": "今日は雨が降っています。"},
                            {"utterance_id": 1, "text": "＊＊で働いています。"},
                        ],
                    }
                ),
            )
        archive.writestr("repo/llm_dialogue_system/model.json", "{}")
        archive.writestr("repo/real_persona_chat/interlocutors.json", "{}")
    manifest = {
        "source": source,
        "source_id": source["id"],
        "snapshot_id": "fixture",
        "files": [{"role": "realpersonachat-zip", "path": "data.zip"}],
    }
    raw = list(iter_documents(manifest, tmp_path))
    assert [r["native_id"] for r in raw] == ["10279", "10577"]
    stats = Counter()
    records = [canonical_document(r, manifest, stats, set()) for r in raw]
    assert records[0]["id"] != records[1]["id"]
    assert all(len(r["sentences"]) == 1 for r in records)
    assert records[0]["authorship"] == "human"
    assert records[0]["sentences"][0]["source_range"] == {"unit": "utterance", "start": 0, "end": 1}
    assert stats["rejected:masked-personal-information"] == 2
