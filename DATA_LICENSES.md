# Data licenses and attribution

This repository builds a **collection of separately licensed sources**. It does
not grant one new permissive license over all imported text. The repository's
MIT license covers its software and original documentation. Original synthetic
fixture sentences are also available under CC0 1.0.

The initial source grants are:

| Source | Recorded license and evidence |
| --- | --- |
| Wikipedia / Wikivoyage covered text | [CC BY-SA 4.0](https://creativecommons.org/licenses/by-sa/4.0/); [Wikimedia Terms of Use](https://foundation.wikimedia.org/wiki/Policy:Terms_of_Use) |
| Tatoeba sentence text | [CC BY 2.0 France](https://creativecommons.org/licenses/by/2.0/fr/); [publisher reuse guide](https://en.wiki.tatoeba.org/articles/show/using-the-tatoeba-corpus) |
| Japanese Wikinews archive | `LicenseRef-Wikinews-JA`, preserving [BY 4.0](https://creativecommons.org/licenses/by/4.0/), [BY 2.5](https://creativecommons.org/licenses/by/2.5/), and [BY 2.1 Japan](https://creativecommons.org/licenses/by/2.1/jp/) notices; [Japanese historical policy](https://ja.wikinews.org/wiki/ウィキニュース:ウィキニュースについて) |

`LicenseRef-Wikinews-JA` is a project identifier for historical requirements,
not a new license. Its full required notice travels in every imported document,
source configuration, SQLite license table, and generated license inventory.
The latest page revision does not identify the creation date of every sentence
or contribution. This archive does not incorrectly assign the English edition's
early public-domain rule to Japanese text.

Redistributed records retain source and revision URLs, contributor/history
attribution, precise license URLs and notices, and transformation descriptions.
Translations carry their own source URL, attribution, and license. The current
Tatoeba export names a current owner; the data does not falsely identify that
person as the sole author or prove native-speaker/human-translation status.

Consumers should retain this information in downloads and make the relevant
credit, license links, and modification notice available alongside displayed
examples. When adapting ShareAlike content, follow its applicable ShareAlike
requirements. Merely placing an entry in a database does not erase those terms.
The [Wikimedia reuse terms](https://foundation.wikimedia.org/wiki/Policy:Terms_of_Use)
and each Creative Commons license explain the actual obligations.

Source-level licenses do not cover every possible third-party quotation, image,
or contribution included under an exception. This pipeline is text-only and
conservatively excludes marked quotations, media, and recognized rights-problem
templates. That is a bounded extraction policy, not a claim to resolve the
copyright history of every sentence. Rights corrections should identify the
source, document/sentence ID, snapshot, and affected release so maintainers can
exclude the record and publish a corrected dataset. Old downloaded copies are
not silently rewritten.

NC and unreviewed license identifiers fail admission. ND material is outside the
initial transformation/translation pipeline. Adding a new license requires a
source review, an explicit allowlist entry, and tests; a dataset card or an
open-source scraping script alone is insufficient evidence. See the
[source review](docs/sources.md) for decisions and deferred sources.
