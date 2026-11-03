# Documentation claim auditor

Compare written promises with static Python call evidence, entirely offline.
The auditor reads the root README and Markdown files with a docs path component.
It parses source without executing it. No network, telemetry, or output files
are used.

## Usage

Requires Python 3.9 or newer.

```sh
python3 -m pip install .
genre-classification-claim-audit /path/to/project
python3 -m genre_classification_claim_audit /path/to/project --json
```

Use `--verbose` to show inspected paths and evidence flags. Repeat `--ignore PATH`
to exclude relative path prefixes. `--fail-on` accepts LOW, MEDIUM, or HIGH;
HIGH is the default. Findings below the threshold exit 0, findings meeting it
exit 2, and usage or I/O errors exit 1. `--version` prints the installed version.
JSON includes a verdict and findings with identifiers, severities, and messages.

## Matching

Paragraphs are normalized by lowercasing, expanding negative contractions,
replacing hyphens with spaces, and collapsing whitespace. Exact phrases use
word boundaries; longer matches take priority. Negative spans are removed
before affirmative matching. Fenced code is excluded; inline code counts.

Evidence is confined to one module. Imported aliases are resolved and local
stubs suppress matching operations. A paired constructor must have a matching
prediction receiver. Tests count separately; fixtures, examples, documentation
source, symlinks, and invalid syntax supply no production evidence.

```text
Generic genre-named calls and GenreClassifier construction/predict pairs
are the supported indicators.
documented-genre-classification-claim-false HIGH
Same identifier: MEDIUM for evidence only in tests
documented-no-genre-classification-claim-false HIGH
```

These indicators do not establish runtime correctness. A positive promise with
no source produces a finding; a negative promise with no source passes.

## Development

```sh
python3 -m unittest discover
python3 -m build
```

Distributed under the MIT license.
