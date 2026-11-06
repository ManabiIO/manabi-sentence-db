"""Bounded, order-independent review samples containing citation metadata only."""

import hashlib
import json
from collections.abc import Iterable
from dataclasses import dataclass

MAX_TOPICS = 1024
MAX_PER_TOPIC = 10_000
MAX_STRING_LENGTH = 4096


def _string(value: str, name: str) -> str:
    if not isinstance(value, str) or not value or len(value) > MAX_STRING_LENGTH:
        raise ValueError(f"{name} must be a nonempty string of at most {MAX_STRING_LENGTH} characters")
    # Reject lone surrogates so every accepted value has a portable UTF-8 hash.
    try:
        value.encode("utf-8")
    except UnicodeEncodeError as error:
        raise ValueError(f"{name} must be valid UTF-8") from error
    return value


@dataclass(frozen=True)
class ReviewCandidate:
    topic: str
    sentence_id: str
    work_id: str
    archive: str


class TopicReviewSampler:
    """Keep the bottom-k SHA-256 identities per explicitly allowed topic.

    Identity is (topic, sentence_id); citations use minimum (archive, work_id).
    Only retained identities are stored. Once rejected or evicted, an identity
    cannot pass the monotonically decreasing cutoff, even on a later duplicate.
    Memory is O(number of allowed topics * per_topic), independent of stream size.
    Rejected candidates compare against a cached cutoff in constant time.
    Retained insertions scan at most per_topic entries to update that cutoff.
    """

    def __init__(self, allowed_topics: Iterable[str], *, seed: str, per_topic: int):
        self._seed = _string(seed, "seed")
        if type(per_topic) is not int or not 1 <= per_topic <= MAX_PER_TOPIC:
            raise ValueError(f"per_topic must be an integer from 1 to {MAX_PER_TOPIC}")
        if isinstance(allowed_topics, (str, bytes)):
            raise ValueError("allowed_topics must be an iterable of topic strings")
        self._samples: dict[str, dict[str, tuple[bytes, ReviewCandidate]]] = {}
        for topic in allowed_topics:
            topic = _string(topic, "topic")
            if topic in self._samples:
                raise ValueError("allowed_topics must be unique")
            if len(self._samples) >= MAX_TOPICS:
                raise ValueError(f"allowed_topics must contain at most {MAX_TOPICS} topics")
            self._samples[topic] = {}
        self._per_topic = per_topic
        self._cutoffs: dict[str, tuple[bytes, str]] = {}

    @property
    def retained_count(self) -> int:
        return sum(len(sample) for sample in self._samples.values())

    def add(self, topic: str, sentence_id: str, work_id: str, archive: str) -> None:
        topic = _string(topic, "topic")
        sentence_id = _string(sentence_id, "sentence_id")
        work_id = _string(work_id, "work_id")
        archive = _string(archive, "archive")
        if topic not in self._samples:
            raise ValueError(f"Topic is not allowed: {topic!r}")
        sample = self._samples[topic]
        if sentence_id in sample:
            rank, previous = sample[sentence_id]
            if (archive, work_id) < (previous.archive, previous.work_id):
                sample[sentence_id] = (rank, ReviewCandidate(topic, sentence_id, work_id, archive))
            return
        framed = json.dumps([self._seed, topic, sentence_id], ensure_ascii=False,
                            separators=(",", ":")).encode("utf-8")
        rank = hashlib.sha256(framed).digest()
        cutoff = self._cutoffs.get(topic)
        if cutoff is not None:
            if (rank, sentence_id) >= cutoff:
                return
            del sample[cutoff[1]]
        sample[sentence_id] = (rank, ReviewCandidate(topic, sentence_id, work_id, archive))
        if len(sample) == self._per_topic:
            self._cutoffs[topic] = max((value[0], identity) for identity, value in sample.items())

    def results(self) -> dict[str, tuple[ReviewCandidate, ...]]:
        """Return a detached snapshot ordered by topic, then hash and identity."""
        return {
            topic: tuple(candidate for _, candidate in sorted(
                sample.values(), key=lambda item: (item[0], item[1].sentence_id)
            ))
            for topic, sample in sorted(self._samples.items())
        }
