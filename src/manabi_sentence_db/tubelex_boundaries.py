"""Optional local Japanese punctuation predictions used only as boundary offsets.

The four-label character profile follows AstroNier/japanese-punctuation-onnx:
none, comma, period, question. No model-generated text enters the corpus/index.
"""

from __future__ import annotations

import math
import re
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path

from .serialization import DataError, sha256_file

_CJK = re.compile(r"[぀-ヿ㐀-鿿豈-﫿]")


def split_character_predictions(
    text: str,
    predict_window,
    *,
    threshold=0.5,
    window_chars=400,
    overlap_chars=64,
) -> list[str]:
    """Use bounded overlapping windows, returning exact slices of the input."""
    if not 0 < threshold < 1 or not 0 <= overlap_chars < window_chars <= 510:
        raise DataError("Invalid Japanese character-boundary settings")
    if not text:
        return []
    parts, offset, position, owned_from = [], 0, 0, 0
    while position < len(text):
        stop = min(len(text), position + window_chars)
        fragment = text[position:stop]
        predictions = predict_window(fragment)
        if len(predictions) != len(fragment):
            raise DataError("Japanese character model returned invalid alignment")
        # Split ownership near the middle of the overlap. Interior predictions
        # see both left and right context; neither artificial window edge wins.
        keep_to = stop if stop == len(text) else stop - (overlap_chars + 1) // 2
        for local in range(max(0, owned_from - position), keep_to - position):
            row = predictions[local]
            if len(row) != 4 or any(not math.isfinite(float(value)) for value in row):
                raise DataError("Japanese character model returned invalid logits")
            label = max(range(4), key=row.__getitem__)
            if label not in {2, 3}:  # Commas never become sentence boundaries.
                continue
            maximum = max(row)
            probability = math.exp(row[label] - maximum) / sum(math.exp(v - maximum) for v in row)
            end = position + local + 1
            word_end = end == len(text) or text[end].isspace() or _CJK.match(text[end - 1])
            if probability < threshold or not word_end:
                continue
            while end < len(text) and text[end].isspace():
                end += 1
            if offset < end:
                parts.append(text[offset:end])
                offset = end
        if stop == len(text):
            break
        owned_from = keep_to
        position = stop - overlap_chars
    if offset < len(text):
        parts.append(text[offset:])
    return parts


def describe_japanese_character_model(directory: Path, *, threshold=0.5):
    """Describe the exact local inference profile without loading a session."""
    directory = directory.resolve()
    if not directory.is_dir() or not 0 < threshold < 1:
        raise DataError("Provide a local Japanese model directory and a threshold between 0 and 1")
    model = directory / "punct.int8.onnx"
    if not model.is_file():
        model = directory / "model.onnx"
    vocab_path = directory / "vocab.txt"
    if not model.is_file() or not vocab_path.is_file():
        raise DataError("Japanese character model needs punct.int8.onnx/model.onnx and vocab.txt")
    try:
        runtime = version("onnxruntime")
    except PackageNotFoundError as exc:
        raise DataError("Install onnxruntime in the local build environment") from exc
    return model, vocab_path, {
        "engine": "ja-character-onnx", "runtime": runtime,
        "model_sha256": sha256_file(model), "vocab_sha256": sha256_file(vocab_path),
        "threshold": threshold, "window_chars": 400, "overlap_chars": 64,
        "window_ownership": "centered-overlap-v1", "intra_op_threads": 2, "inter_op_threads": 1,
    }


def local_japanese_character_model(directory: Path, *, threshold=0.5):
    """Load known local ONNX/vocabulary files. No hub/network dependency."""
    model, vocab_path, identity = describe_japanese_character_model(directory, threshold=threshold)
    try:
        import numpy as np
        import onnxruntime as ort
    except ImportError as exc:
        raise DataError(
            "Install onnxruntime in the local build environment for Japanese boundary prediction"
        ) from exc
    vocabulary = {
        word: index for index, word in enumerate(vocab_path.read_text(encoding="utf-8").split("\n"))
    }
    if not {"[CLS]", "[SEP]", "[UNK]"} <= vocabulary.keys():
        raise DataError("Invalid Japanese character vocabulary")
    options = ort.SessionOptions()
    options.intra_op_num_threads = 2
    options.inter_op_num_threads = 1
    try:
        session = ort.InferenceSession(
            str(model), sess_options=options, providers=["CPUExecutionProvider"]
        )
    except Exception as exc:
        raise DataError(
            "Cannot load the local Japanese ONNX model; check files and runtime compatibility"
        ) from exc
    if {item.name: item.type for item in session.get_inputs()} != {
        "input_ids": "tensor(int64)",
        "attention_mask": "tensor(int64)",
    }:
        raise DataError("Japanese model must use the supported four-label character profile")

    def predict(fragment):
        ids = np.asarray(
            [
                [
                    vocabulary["[CLS]"],
                    *[vocabulary.get(char, vocabulary["[UNK]"]) for char in fragment],
                    vocabulary["[SEP]"],
                ]
            ],
            dtype=np.int64,
        )
        try:
            logits = session.run(None, {"input_ids": ids, "attention_mask": np.ones_like(ids)})[0]
        except Exception as exc:
            raise DataError("Local Japanese boundary inference failed") from exc
        if logits.shape != (1, len(fragment) + 2, 4):
            raise DataError("Japanese model returned an unsupported output shape")
        return logits[0, 1:-1].tolist()

    return (
        lambda text: split_character_predictions(text, predict, threshold=threshold),
        identity,
    )
