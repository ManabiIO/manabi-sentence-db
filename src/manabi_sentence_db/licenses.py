"""Reviewed commercial-redistribution license allowlist, not a license guesser."""

from urllib.parse import urlsplit

from .serialization import DataError

LICENSE_URLS = {
    "CC0-1.0": "https://creativecommons.org/publicdomain/zero/1.0/",
    "CC-BY-2.0-FR": "https://creativecommons.org/licenses/by/2.0/fr/",
    "CC-BY-2.1-JP": "https://creativecommons.org/licenses/by/2.1/jp/",
    "CC-BY-2.5": "https://creativecommons.org/licenses/by/2.5/",
    "CC-BY-3.0": "https://creativecommons.org/licenses/by/3.0/",
    "CC-BY-4.0": "https://creativecommons.org/licenses/by/4.0/",
    "CC-BY-SA-3.0": "https://creativecommons.org/licenses/by-sa/3.0/",
    "CC-BY-SA-4.0": "https://creativecommons.org/licenses/by-sa/4.0/",
    "LicenseRef-Wikinews-JA": "https://ja.wikinews.org/wiki/ウィキニュース:ウィキニュースについて",
}

WIKINEWS_NOTICE = (
    "Japanese Wikinews current terms offer post-2005-09-25 text under CC BY 4.0; "
    "the historical policy says CC BY 2.5 or later. Contributions before "
    "2005-09-24 22:15 UTC were CC BY 2.1 Japan. This archive conservatively "
    "retains all three license notices and attribution requirements; a latest "
    "revision timestamp does not establish a contribution's original license. "
    "See https://creativecommons.org/licenses/by/4.0/, "
    "https://creativecommons.org/licenses/by/2.5/, and "
    "https://creativecommons.org/licenses/by/2.1/jp/."
)


def validate_license(value: dict) -> None:
    if not isinstance(value, dict):
        raise DataError("Invalid license object")
    identifier = value.get("id")
    if not isinstance(identifier, str) or identifier not in LICENSE_URLS:
        raise DataError(f"Unreviewed redistribution license: {identifier!r}")
    if value.get("url") != LICENSE_URLS[identifier]:
        raise DataError(f"License URL does not match reviewed license {identifier}")
    if identifier == "LicenseRef-Wikinews-JA" and value.get("notice") != WIKINEWS_NOTICE:
        raise DataError("Japanese Wikinews must preserve its historical license notice")


def validate_rights(record: dict, *, source_url_key: str) -> None:
    """Validate retained rights at interchange boundaries; never infer permission.

    The allowlist is not proof that a publisher owns every embedded passage.
    Source adapters must still exclude third-party material and retain notices.
    """
    validate_license(record.get("license"))
    attribution = record.get("attribution")
    if (
        not isinstance(attribution, dict)
        or not isinstance(attribution.get("text"), str)
        or not attribution["text"].strip()
    ):
        raise DataError("Missing or invalid attribution")
    notice = record["license"].get("notice")
    if notice is not None and (not isinstance(notice, str) or not notice.strip()):
        raise DataError("Invalid license notice")
    revision = record.get("revision", {})
    if not isinstance(revision, dict):
        raise DataError("Invalid citation revision")
    urls = [record.get(source_url_key), attribution.get("url")]
    urls.extend(value for key, value in revision.items() if key.endswith("url"))
    for url in urls:
        if (
            not isinstance(url, str)
            or any(c.isspace() or ord(c) < 32 or ord(c) == 127 for c in url)
        ):
            raise DataError("Invalid corpus citation URL")
        try:
            parsed = urlsplit(url)
            if (
                parsed.scheme not in {"https", "http"}
                or not parsed.hostname
                or parsed.username is not None
                or parsed.password is not None
            ):
                raise ValueError("Not a public HTTP(S) citation")
            parsed.port  # Reject malformed ports rather than deferring to a browser.
        except ValueError as exc:
            raise DataError("Invalid corpus citation URL") from exc
