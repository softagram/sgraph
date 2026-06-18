from __future__ import annotations

import argparse
import contextlib
import json
import sys

from sgraph import SGraph
from sgraph.compare.modelcompare import ModelCompare

"""
Compare two sgraph models and report the differences.

Usage:
    python -m sgraph.cli.compare MODEL_A MODEL_B [options]

    MODEL_A is the "before"/old model, MODEL_B the "after"/new model
    (paths to .xml or .xml.zip files).

Exit codes (git-diff style):
    0  models are equivalent (no differences)
    1  differences were found
    2  an error occurred (bad path, parse failure, usage error)
"""


def _build_payload(model_a: str, model_b: str, infos) -> dict:
    """Turn ModelCompare.getCompareInfos() output into a JSON-friendly dict."""
    (new_deps, removed_deps, changed_elems, new_elems, removed_elems,
     attr_changes) = infos

    def dep_entry(item):
        association, length = item
        return {
            'from': association.fromElement.getPath(),
            'to': association.toElement.getPath(),
            'deptype': association.deptype,
            'length': length,
        }

    def changed_entry(item):
        elem, change_count = item
        entry = {'path': elem.getPath(), 'change_count': int(change_count)}
        if elem.attrs.get('renamed') == 'true' and 'old_name' in elem.attrs:
            entry['old_name'] = elem.attrs['old_name']
        return entry

    payload = {
        'model_a': model_a,
        'model_b': model_b,
        'new_elements': [{'path': e.getPath()} for _, e in new_elems],
        'removed_elements': [{'path': e.getPath()} for _, e in removed_elems],
        'changed_elements': [changed_entry(c) for c in changed_elems],
        'new_dependencies': [dep_entry(d) for d in new_deps],
        'removed_dependencies': [dep_entry(d) for d in removed_deps],
        # Drop entries whose diff is empty: they carry no information (e.g. an
        # element whose only differing attribute was excluded via --exclude-attrs).
        'attr_changes': [{'path': e.getPath(), 'diff': d}
                         for e, d in attr_changes if d],
    }
    payload['summary'] = {
        'new_elements': len(payload['new_elements']),
        'removed_elements': len(payload['removed_elements']),
        'changed_elements': len(payload['changed_elements']),
        'new_dependencies': len(payload['new_dependencies']),
        'removed_dependencies': len(payload['removed_dependencies']),
        'attr_changes': len(payload['attr_changes']),
    }
    return payload


def _write_output(payload: dict, compare_model: SGraph, mc: ModelCompare,
                  output_format: str, output: str | None):
    stream = open(output, 'w') if output else sys.stdout
    try:
        if output_format == 'json':
            stream.write(json.dumps(payload, indent=2) + '\n')
        else:
            # Reuse the library's human-readable summary printer.
            with contextlib.redirect_stdout(stream):
                mc.printCompareInfos(compare_model)
    finally:
        if output:
            stream.close()


def _parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog='python -m sgraph.cli.compare',
        description='Compare two sgraph models and report the differences.')
    parser.add_argument('model_a',
                        help='Path to the "before"/old model (.xml or .xml.zip)')
    parser.add_argument('model_b',
                        help='Path to the "after"/new model (.xml or .xml.zip)')
    parser.add_argument('-f', '--format', default='text', choices=['text', 'json'],
                        help='Output format (default: text)')
    parser.add_argument('-o', '--output', default=None, metavar='FILE',
                        help='Write output to FILE instead of stdout')
    parser.add_argument('--rename-detection', action='store_true',
                        help='Detect renamed elements (collapses an add+remove '
                        'into a single changed element annotated with old_name)')
    parser.add_argument('--exclude-attrs', default=None, metavar='a,b,c',
                        help='Comma-separated attribute names to ignore during '
                        'comparison')
    return parser.parse_args(argv)


def run(argv: list[str]) -> int:
    """Run the comparison. Returns the process exit code (0/1/2)."""
    args = _parse_args(argv)

    exclude_attrs = None
    if args.exclude_attrs:
        exclude_attrs = {name.strip() for name in args.exclude_attrs.split(',')
                         if name.strip()}

    mc = ModelCompare()
    try:
        if args.rename_detection:
            # rename_detection lives on compareModels, so load the models first.
            model1 = SGraph.parse_xml_or_zipped_xml(args.model_a)
            model2 = SGraph.parse_xml_or_zipped_xml(args.model_b)
            compare_model = mc.compareModels(model1, model2, rename_detection=True,
                                             exclude_attrs=exclude_attrs)
        else:
            compare_model = mc.compare(args.model_a, args.model_b,
                                       exclude_attrs=exclude_attrs)
    except Exception as e:  # noqa: BLE001 - surface any load/parse failure as exit 2
        print(f'Error: {e}', file=sys.stderr)
        return 2

    infos = mc.getCompareInfos(compare_model)
    payload = _build_payload(args.model_a, args.model_b, infos)
    has_diff = any(payload['summary'].values())

    _write_output(payload, compare_model, mc, args.format, args.output)

    return 1 if has_diff else 0


def main():
    sys.exit(run(sys.argv[1:]))


if __name__ == '__main__':
    main()
