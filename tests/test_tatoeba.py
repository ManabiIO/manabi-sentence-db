"""Synthetic fixtures exercise source semantics without copied corpus content."""

from __future__ import annotations

import bz2
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from manabi_sentence_db.tatoeba import MAX_FIELD_CHARS, iter_documents


class TatoebaTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.manifest = {
            "source_id": "tatoeba-ja",
            "snapshot_id": "synthetic",
            "source": {
                "id": "tatoeba-ja",
                "language": "ja",
                "license": {
                    "id": "CC-BY-2.0-FR",
                    "url": "https://creativecommons.org/licenses/by/2.0/fr/",
                },
                "attribution": {"text": "Tatoeba contributors", "url": "https://tatoeba.org/"},
            },
            "files": [],
        }

    def write_rows(self, role: str, rows: list[list[str]], compressed: bool = True) -> Path:
        name = f"{len(self.manifest['files'])}-{role}.tsv" + (".bz2" if compressed else "")
        path = self.root / name
        text = "".join("\t".join(row) + "\n" for row in rows)
        if compressed:
            path.write_bytes(bz2.compress(text.encode("utf-8")))
        else:
            path.write_text(text, encoding="utf-8")
        self.manifest["files"].append({"path": name, "role": role})
        return path

    @staticmethod
    def sentence(
        identifier: str, language: str, text: str, owner: str = "ExampleOwner"
    ) -> list[str]:
        return [identifier, language, text, owner, "2020-01-01 00:00:00", "2021-02-03 04:05:06"]

    def test_direct_links_preserve_attribution_and_ignore_transitive_links(self) -> None:
        self.write_rows(
            "sentences-jpn",
            [
                self.sentence("2", "jpn", "次の例文です。", r"\N"),
                self.sentence("1", "jpn", "例文です。"),
            ],
        )
        self.write_rows(
            "sentences-eng",
            [
                self.sentence("11", "eng", 'An "example" sentence.', "OtherOwner"),
                self.sentence("12", "eng", "An indirect sentence."),
                self.sentence("13", "eng", "A second direct sentence.", r"\N"),
            ],
        )
        self.write_rows(
            "links",
            [["1", "11"], ["11", "1"], ["11", "12"], ["13", "1"], ["1", "999"], ["1", "1"]],
        )
        self.write_rows(
            "tags", [["1", "archaic"], ["1", "archaic"], ["1", "@change"], ["99", "unused"]]
        )
        documents = list(iter_documents(self.manifest, self.root))
        self.assertEqual([doc["native_id"] for doc in documents], ["1", "2"])
        self.assertEqual(documents[0]["published_at"], "2020-01-01T00:00:00Z")
        self.assertEqual(documents[0]["revision"]["timestamp"], "2021-02-03T04:05:06Z")
        sentence = documents[0]["sentences"][0]
        self.assertEqual(sentence["text"], "例文です。")
        self.assertEqual(sentence["tags"], ["@change", "archaic"])
        self.assertEqual(sentence["content_flags"], [])
        self.assertEqual([item["native_id"] for item in sentence["translations"]], ["11", "13"])
        translation = sentence["translations"][0]
        self.assertEqual(translation["text"], 'An "example" sentence.')
        self.assertEqual(translation["language"], "en")
        self.assertEqual(translation["alignment"], "direct-link")
        self.assertEqual(translation["license"]["id"], "CC-BY-2.0-FR")
        self.assertEqual(
            translation["attribution"]["url"], "https://tatoeba.org/en/sentences/show/11"
        )
        self.assertIn("current owner: OtherOwner", translation["attribution"]["text"])
        self.assertNotIn("method", translation)
        self.assertNotIn("provenance", translation)
        self.assertEqual(documents[0]["revision"]["timestamp"], "2021-02-03T04:05:06Z")
        self.assertIn("no current owner in export", documents[1]["attribution"]["text"])
        self.assertNotIn(r"\N", documents[1]["attribution"]["text"])

    def test_unquoted_tsv_text_and_unknown_dates_are_preserved(self) -> None:
        text = '"引用"と\\文字をそのまま保存する。  '
        row = self.sentence("1", "jpn", text)
        row[-1] = r"\N"
        self.write_rows("sentences-jpn", [row, self.sentence("2", "jpn", "  ")], compressed=False)
        self.write_rows("tags-jpn", [["1", "multi word tag"]])
        documents = list(iter_documents(self.manifest, self.root))
        self.assertEqual(len(documents), 1)
        self.assertEqual(documents[0]["sentences"][0]["text"], text)
        self.assertEqual(documents[0]["sentences"][0]["tags"], ["multi word tag"])
        self.assertNotIn("timestamp", documents[0]["revision"])
        self.assertEqual(documents[0]["sentences"][0]["translations"], [])

    def test_additional_translation_language_does_not_require_a_new_join(self) -> None:
        self.write_rows("sentences-jpn", [self.sentence("1", "jpn", "例文です。")])
        self.write_rows("sentences-fra", [self.sentence("11", "fra", "Une phrase exemple.")])
        self.write_rows("links", [["1", "11"]])
        document = next(iter_documents(self.manifest, self.root))
        self.assertEqual(document["sentences"][0]["translations"][0]["language"], "fra")

    def test_missing_primary_file_and_escaping_paths_fail(self) -> None:
        with self.assertRaisesRegex(ValueError, "requires.*sentences-jpn"):
            list(iter_documents(self.manifest, self.root))
        self.manifest["files"] = [{"role": "sentences-jpn", "path": "../outside.tsv"}]
        with self.assertRaisesRegex(ValueError, "Unsafe"):
            list(iter_documents(self.manifest, self.root))
        self.manifest["files"] = [{"role": "sentences-jpn", "path": "missing.tsv"}]
        with self.assertRaisesRegex(ValueError, "Missing"):
            list(iter_documents(self.manifest, self.root))

    def test_malformed_tsv_does_not_produce_a_partial_silent_import(self) -> None:
        self.write_rows("sentences-jpn", [["1", "jpn", "Only three fields"]])
        with self.assertRaisesRegex(ValueError, "expected 6 TSV fields"):
            list(iter_documents(self.manifest, self.root))

    def test_duplicate_primary_ids_fail_instead_of_replacing_attribution(self) -> None:
        self.write_rows(
            "sentences-jpn",
            [
                self.sentence("1", "jpn", "一つ目です。"),
                self.sentence("1", "jpn", "別の文です。", "Other"),
            ],
        )
        with self.assertRaisesRegex(ValueError, "duplicate primary sentence ID"):
            list(iter_documents(self.manifest, self.root))

    def test_long_fields_are_supported_but_finite(self) -> None:
        text = "例" * 150_000
        self.write_rows("sentences-jpn", [self.sentence("1", "jpn", text)])
        self.assertEqual(
            next(iter_documents(self.manifest, self.root))["sentences"][0]["text"], text
        )
        self.manifest["files"] = []
        self.write_rows("sentences-jpn", [self.sentence("1", "jpn", "例" * (MAX_FIELD_CHARS + 1))])
        with self.assertRaisesRegex(ValueError, "field exceeds size limit"):
            list(iter_documents(self.manifest, self.root))

    def test_temporary_join_files_are_removed_when_iterator_is_closed(self) -> None:
        self.write_rows(
            "sentences-jpn",
            [self.sentence("1", "jpn", "一つ目です。"), self.sentence("2", "jpn", "二つ目です。")],
        )
        scratch = self.root / "join-temp"
        scratch.mkdir()
        original = tempfile.TemporaryDirectory
        with patch("manabi_sentence_db.tatoeba.tempfile.TemporaryDirectory") as factory:
            factory.side_effect = lambda **kwargs: original(dir=scratch, **kwargs)
            documents = iter_documents(self.manifest, self.root)
            next(documents)
            self.assertTrue(list(scratch.iterdir()))
            documents.close()
            self.assertEqual(list(scratch.iterdir()), [])


if __name__ == "__main__":
    unittest.main()
