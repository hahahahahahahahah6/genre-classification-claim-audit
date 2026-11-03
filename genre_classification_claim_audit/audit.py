"""Static source and Markdown inspection; inspected code is never executed."""
import argparse
import ast
import json
import os
from pathlib import Path
import re
import sys

from . import __version__
from .phrases import GENRE, NOGENRE

GENERIC = frozenset('''classify_genre detect_genre estimate_genre get_genre genre_detect genre_classify predict_genre genre_predict identify_genre genre_identify classify_music_genre detect_music_genre estimate_music_genre get_music_genre predict_music_genre identify_music_genre classify_song_genre detect_song_genre estimate_song_genre predict_song_genre identify_song_genre analyze_genre analyse_genre genre_analyze genre_analyse classify_audio_genre detect_audio_genre predict_audio_genre classify_track_genre detect_track_genre predict_track_genre recognize_genre recognise_genre genre_recognize genre_recognise label_genre genre_label determine_genre genre_determine classify_musical_genre detect_musical_genre'''.split())


def normalize(text):
    return ' '.join(text.lower().replace("n't", ' not').replace('-', ' ').split())


def prose(text):
    fence = None
    lines = []
    for line in text.splitlines():
        match = re.match(r'^ {0,3}(`{3,}|~{3,})(.*)$', line)
        if fence:
            if match and match[1][0] == fence[0] and len(match[1]) >= len(fence) and not match[2].strip():
                fence = None
            lines.append('')
        elif match:
            fence = match[1]
            lines.append('')
        else:
            lines.append(line)
    return '\n'.join(lines)


def pattern(phrases):
    return re.compile(r'\b(?:' + '|'.join(re.escape(p) for p in sorted(phrases, key=lambda p: (-len(p), p))) + r')\b')


POSITIVE, NEGATIVE = pattern(GENRE), pattern(NOGENRE)


def claims(text):
    positive = negative = False
    for paragraph in re.split(r'\n\s*\n', prose(text)):
        paragraph = normalize(paragraph)
        negative |= bool(NEGATIVE.search(paragraph))
        positive |= bool(POSITIVE.search(NEGATIVE.sub(' ', paragraph)))
    return positive, negative


def evidence(source):
    try:
        tree = ast.parse(source)
    except (SyntaxError, ValueError):
        return False
    nodes = list(ast.walk(tree))
    aliases = {}
    definitions = set()
    for node in nodes:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            definitions.add(node.name)
        elif isinstance(node, ast.ImportFrom):
            for item in node.names:
                aliases[item.asname or item.name] = item.name
        elif isinstance(node, ast.Import):
            for item in node.names:
                aliases[item.asname or item.name.split('.')[0]] = item.name

    def name(func):
        if isinstance(func, ast.Name):
            return aliases.get(func.id, func.id).split('.')[-1]
        if isinstance(func, ast.Attribute):
            return func.attr
        return ''

    def constructor(call):
        if not isinstance(call, ast.Call):
            return False
        resolved = name(call.func)
        local = call.func.id if isinstance(call.func, ast.Name) else resolved
        return (resolved.endswith('GenreClassifier') and
                resolved not in definitions and local not in definitions)

    bindings = set()
    for node in nodes:
        if isinstance(node, (ast.Assign, ast.AnnAssign)) and constructor(node.value):
            targets = node.targets if isinstance(node, ast.Assign) else [node.target]
            bindings.update(t.id for t in targets if isinstance(t, ast.Name))
    for node in nodes:
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        resolved = name(func)
        if resolved in GENERIC and resolved not in definitions:
            if isinstance(func, ast.Attribute):
                return True
            if isinstance(func, ast.Name) and func.id in aliases and func.id not in definitions:
                return True
        if isinstance(func, ast.Attribute) and func.attr == 'predict':
            if constructor(func.value) or (isinstance(func.value, ast.Name) and func.value.id in bindings):
                return True
    return False


def audit(root, ignore=()):
    root = Path(root)
    if not root.is_dir():
        raise OSError('root must be a readable directory: ' + str(root))
    if root.is_symlink():
        raise OSError('root must not be a symlink')
    ignored = [Path(i).as_posix().strip('/') for i in ignore]
    docs, sources = [], []
    pos = neg = production = tests = False

    def excluded(rel):
        value = rel.as_posix()
        return any(value == prefix or value.startswith(prefix + '/') for prefix in ignored)

    def walk_error(error):
        raise error

    for directory, dirs, files in os.walk(root, onerror=walk_error):
        base = Path(directory)
        dirs[:] = sorted(d for d in dirs if not (base / d).is_symlink() and not excluded((base / d).relative_to(root)))
        for filename in sorted(files):
            path = base / filename
            rel = path.relative_to(root)
            if path.is_symlink() or excluded(rel):
                continue
            if rel.as_posix() == 'README.md' or (path.suffix == '.md' and 'docs' in rel.parts[:-1]):
                docs.append(rel.as_posix())
                a, b = claims(path.read_text(encoding='utf-8'))
                pos |= a
                neg |= b
            if path.suffix == '.py' and not {'fixtures', 'docs', 'examples'}.intersection(rel.parts[:-1]):
                sources.append(rel.as_posix())
                found = evidence(path.read_text(encoding='utf-8'))
                is_test = 'tests' in rel.parts[:-1] or filename.startswith('test_') or filename.endswith('_test.py')
                if is_test:
                    tests |= found
                else:
                    production |= found
    findings = []
    if pos and not production:
        findings.append({'id': 'documented-genre-classification-claim-false', 'severity': 'MEDIUM' if tests else 'HIGH', 'message': 'Affirmative documentation lacks production call evidence.'})
    if neg and production:
        findings.append({'id': 'documented-no-genre-classification-claim-false', 'severity': 'HIGH', 'message': 'Negative documentation conflicts with production call evidence.'})
    return {'verdict': 'FAIL' if findings else 'PASS', 'findings': findings, 'docs': docs, 'sources': sources, 'production_evidence': production, 'test_evidence': tests}


class Parser(argparse.ArgumentParser):
    def error(self, message):
        self.print_usage(sys.stderr)
        self.exit(1, self.prog + ': error: ' + message + '\n')


def main(argv=None):
    parser = Parser(description=__doc__)
    parser.add_argument('root')
    parser.add_argument('--json', action='store_true')
    parser.add_argument('--verbose', action='store_true')
    parser.add_argument('--ignore', action='append', default=[])
    parser.add_argument('--fail-on', choices=['LOW', 'MEDIUM', 'HIGH'], default='HIGH')
    parser.add_argument('--version', action='version', version=__version__)
    try:
        args = parser.parse_args(argv)
    except SystemExit as error:
        return error.code
    try:
        result = audit(args.root, args.ignore)
    except (OSError, UnicodeError) as error:
        print(str(error), file=sys.stderr)
        return 1
    if args.json:
        print(json.dumps(result, indent=2))
    else:
        print(result['verdict'])
        for finding in result['findings']:
            print('{severity} {id}: {message}'.format(**finding))
        if args.verbose:
            print(json.dumps({k: v for k, v in result.items() if k not in ('verdict', 'findings')}, indent=2))
    ranks = {'LOW': 1, 'MEDIUM': 2, 'HIGH': 3}
    return 2 if any(ranks[f['severity']] >= ranks[args.fail_on] for f in result['findings']) else 0
