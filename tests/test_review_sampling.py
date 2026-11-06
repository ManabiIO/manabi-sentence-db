import hashlib
import json
import random

import pytest

from manabi_sentence_db.review_sampling import (
    MAX_PER_TOPIC,
    MAX_STRING_LENGTH,
    MAX_TOPICS,
    ReviewCandidate,
    TopicReviewSampler,
)


def reference(rows, topics, seed, count):
    """Intentionally unbounded full deduplication followed by a complete sort."""
    citations = {topic: {} for topic in topics}
    for topic, sentence, work, archive in rows:
        old = citations[topic].get(sentence)
        citations[topic][sentence] = min(old, (archive, work)) if old else (archive, work)

    def rank(topic, sentence):
        payload = json.dumps([seed, topic, sentence], ensure_ascii=False, separators=(",", ":"))
        return hashlib.sha256(payload.encode()).digest(), sentence

    return {
        topic: tuple(
            ReviewCandidate(topic, sentence, citations[topic][sentence][1],
                            citations[topic][sentence][0])
            for sentence in sorted(citations[topic], key=lambda s: rank(topic, s))[:count]
        ) for topic in sorted(topics)
    }


def test_full_sort_reference_under_reordering_and_duplicate_eviction():
    topics = ["science", "日本語", "empty"]
    rows = [(topic, f"sentence-{i}", f"work-{i % 7}", "z-archive")
            for topic in topics[:2] for i in range(700)]
    # Repeat all identities with better and worse citations after many evictions.
    rows += [(t, s, "a-work", "a-archive") for t, s, _, _ in rows]
    rows += [(t, s, "z-work", "a-archive") for t, s, _, _ in rows[:1400]]
    expected = reference(rows, topics, "seed", 10)
    shuffled = rows.copy()
    random.Random(517).shuffle(shuffled)
    for order in (rows, list(reversed(rows)), shuffled):
        sampler = TopicReviewSampler(topics, seed="seed", per_topic=10)
        for row in order:
            sampler.add(*row)
            assert sampler.retained_count <= 20
        assert sampler.results() == expected
        assert sampler.retained_count == 20
        assert sum(map(len, sampler._samples.values())) == 20


def test_empty_stream_and_detached_results():
    sampler = TopicReviewSampler(["topic"], seed="seed", per_topic=1)
    assert sampler.results() == {"topic": ()}
    assert sampler.retained_count == 0
    sampler.add("topic", "sentence", "work", "archive")
    result = sampler.results()
    result.clear()
    assert sampler.retained_count == 1
    assert TopicReviewSampler([], seed="seed", per_topic=1).results() == {}


@pytest.mark.parametrize("count", [0, -1, MAX_PER_TOPIC + 1, True, 1.0, "1"])
def test_invalid_counts(count):
    with pytest.raises(ValueError):
        TopicReviewSampler(["topic"], seed="seed", per_topic=count)


@pytest.mark.parametrize("topics", [["a", "a"], "topic", [""], [None],
                                    (str(i) for i in range(MAX_TOPICS + 1))])
def test_invalid_topics(topics):
    with pytest.raises(ValueError):
        TopicReviewSampler(topics, seed="seed", per_topic=1)


@pytest.mark.parametrize("value", ["", None, 42, "x" * (MAX_STRING_LENGTH + 1), "\ud800"])
def test_invalid_strings(value):
    with pytest.raises(ValueError):
        TopicReviewSampler(["topic"], seed=value, per_topic=1)
    sampler = TopicReviewSampler(["topic"], seed="seed", per_topic=1)
    for index in range(4):
        row = ["topic", "sentence", "work", "archive"]
        row[index] = value
        with pytest.raises(ValueError):
            sampler.add(*row)
    assert sampler.retained_count == 0


def test_unknown_topic_and_upper_bounds():
    sampler = TopicReviewSampler((str(i) for i in range(MAX_TOPICS)), seed="seed",
                                 per_topic=MAX_PER_TOPIC)
    with pytest.raises(ValueError, match="not allowed"):
        sampler.add("other", "sentence", "work", "archive")
    assert sampler.retained_count == 0


def test_framing_and_hash_collision_tiebreak(monkeypatch):
    payloads = []

    class ConstantHash:
        def digest(self):
            return b"constant"

    def hash_payload(payload):
        payloads.append(json.loads(payload))
        return ConstantHash()

    monkeypatch.setattr("manabi_sentence_db.review_sampling.hashlib.sha256",
                        hash_payload)
    sampler = TopicReviewSampler(["a"], seed='[,"seed', per_topic=1)
    for sentence in ("z", "a", "z", "a"):
        sampler.add("a", sentence, "work", "archive")
    assert sampler.results()["a"][0].sentence_id == "a"
    assert payloads == [['[,"seed', "a", sentence] for sentence in ("z", "a", "z")]
