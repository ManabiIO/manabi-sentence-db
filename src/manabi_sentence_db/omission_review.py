"""Bounded attributed omission samples gathered during normalized refinement."""

from .review_sampling import TopicReviewSampler
from .serialization import DataError, canonical_json

MAX_REASONS = 64
MAX_SAMPLE_RECORD_BYTES = 16 * 1024
MAX_RETAINED_BYTES = 16 * 1024 * 1024


class OmissionReview:
    def __init__(self, *, seed, per_reason):
        if type(per_reason) is not int or not 1 <= per_reason <= 20:
            raise DataError("Use 1..20 omission examples per reason")
        # Reuse the sampler's seed/Unicode validation before opening inputs.
        try:
            TopicReviewSampler([], seed=seed, per_topic=per_reason)
        except ValueError as exc:
            raise DataError(str(exc)) from exc
        self.seed = seed
        self.per_reason = per_reason
        self.samplers = {}
        self.sentences = {}
        self.works = {}
        self.candidates = None
        self.retained_bytes = 0

    def add(self, reason, sentence_id, work_id, archive):
        if reason not in self.samplers:
            if len(self.samplers) >= MAX_REASONS:
                raise DataError("Too many omission reasons for bounded review")
            self.samplers[reason] = TopicReviewSampler(
                [reason], seed=self.seed, per_topic=self.per_reason
            )
        self.samplers[reason].add(reason, sentence_id, work_id, archive)

    def seal(self):
        self.candidates = [
            candidate
            for reason, sampler in sorted(self.samplers.items())
            for candidate in sampler.results()[reason]
        ]
        self.sentence_ids = {c.sentence_id for c in self.candidates}
        self.work_ids = {c.work_id for c in self.candidates}

    def observe(self, table, row):
        if table == "sentences" and row["id"] in self.sentence_ids:
            fields = ("id", "language", "text", "text_sha256")
            target = self.sentences
        elif table == "works" and row["id"] in self.work_ids:
            fields = ("id", "source_id", "language", "title", "url", "license",
                      "attribution", "revision_id", "published_at")
            target = self.works
        else:
            return
        value = {key: row[key] for key in fields if key in row}
        size = len(canonical_json(value))
        if size > MAX_SAMPLE_RECORD_BYTES:
            raise DataError("Omission review citation/text exceeds its bounded record size")
        previous = len(canonical_json(target[row["id"]])) if row["id"] in target else 0
        if self.retained_bytes + size - previous > MAX_RETAINED_BYTES:
            raise DataError("Omission review exceeds its total retained-size bound")
        self.retained_bytes += size - previous
        target[row["id"]] = value

    def packet(self, *, binding, counts):
        if self.candidates is None:
            raise DataError("Omission sample is not sealed")
        return {
            "schema_version": 1,
            "kind": "normalized-wikipedia-omission-review",
            "assistant_only": True, "human_review": False, "review_pending": True,
            "seed": self.seed, "per_reason": self.per_reason,
            "sampling": "sha256-bottom-k-topic-sentence-v1",
            "scope": "Rejected Wikipedia occurrences; shared text may remain under other rights",
            "binding": binding,
            "rejected_occurrences_by_reason": dict(sorted(counts.items())),
            "cases": [
                {"reason": c.topic, "archive": c.archive,
                 "sentence": self.sentences[c.sentence_id], "work": self.works[c.work_id]}
                for c in self.candidates
            ],
        }
