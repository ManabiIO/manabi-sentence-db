"""Reviewed commercial-redistribution license allowlist, not a license guesser."""

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
    identifier = value.get("id")
    if identifier not in LICENSE_URLS:
        raise DataError(f"Unreviewed redistribution license: {identifier!r}")
    if value.get("url") != LICENSE_URLS[identifier]:
        raise DataError(f"License URL does not match reviewed license {identifier}")
    if identifier == "LicenseRef-Wikinews-JA" and value.get("notice") != WIKINEWS_NOTICE:
        raise DataError("Japanese Wikinews must preserve its historical license notice")
