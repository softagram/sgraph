"""Tests for the `python -m sgraph.cli.compare` command-line entry point."""
import json

from sgraph import SGraph, SElement
from sgraph.cli import compare as compare_cli

MODEL_A = 'tests/modelfile.xml'
MODEL_B = 'tests/modelfile_direct_indirect.xml'


def _write_file_model(path, attrs):
    """Write a tiny one-file model with the given attrs on /proj/src/file.py."""
    m = SGraph(SElement(None, ''))
    e = m.createOrGetElementFromPath('/proj/src/file.py')
    for k, v in attrs.items():
        e.addAttribute(k, v)
    m.to_xml(path)


def _write_single_child(path, name):
    """Write a model whose only leaf is /p/src/<name>."""
    m = SGraph(SElement(None, ''))
    m.createOrGetElementFromPath('/p/src/' + name)
    m.to_xml(path)


def test_text_output_prints_summary_and_exits_one_on_difference(capsys):
    code = compare_cli.run([MODEL_A, MODEL_B])
    out = capsys.readouterr().out
    assert code == 1  # git-diff style: differences found
    assert 'New elements' in out
    assert 'Removed elements' in out


def test_json_output_reports_correct_counts(capsys):
    code = compare_cli.run([MODEL_A, MODEL_B, '-f', 'json'])
    out = capsys.readouterr().out
    assert code == 1
    data = json.loads(out)
    s = data['summary']
    assert s['new_elements'] == 6
    assert s['removed_elements'] == 26
    assert s['new_dependencies'] == 4
    assert s['removed_dependencies'] == 6
    assert s['changed_elements'] == 2
    # summary counts must match the list lengths
    assert len(data['new_elements']) == s['new_elements']
    assert len(data['removed_dependencies']) == s['removed_dependencies']
    # dependency entries carry from/to/deptype/length
    dep = data['removed_dependencies'][0]
    assert {'from', 'to', 'deptype', 'length'} <= set(dep)
    assert data['model_a'] == MODEL_A and data['model_b'] == MODEL_B


def test_identical_models_exit_zero_with_empty_summary(capsys):
    code = compare_cli.run([MODEL_A, MODEL_A, '-f', 'json'])
    out = capsys.readouterr().out
    assert code == 0
    data = json.loads(out)
    assert all(v == 0 for v in data['summary'].values())


def test_missing_file_exits_two(capsys):
    code = compare_cli.run(['tests/does_not_exist_xyz.xml', MODEL_B])
    err = capsys.readouterr().err
    assert code == 2
    assert 'rror' in err  # "Error: ..."


def test_exclude_attrs_suppresses_attribute(tmp_path, capsys):
    a = str(tmp_path / 'a.xml')
    b = str(tmp_path / 'b.xml')
    _write_file_model(a, {'hash': 'same', 'commit_count_30': '5'})
    _write_file_model(b, {'hash': 'same', 'commit_count_30': '15'})

    # Without exclude: the attribute change is reported, exit 1
    code = compare_cli.run([a, b, '-f', 'json'])
    data = json.loads(capsys.readouterr().out)
    assert code == 1
    diffs = ' '.join(e['diff'] for e in data['attr_changes'])
    assert 'commit_count_30' in diffs

    # With exclude: no meaningful change remains, exit 0 and no attr_changes
    code = compare_cli.run([a, b, '-f', 'json', '--exclude-attrs', 'commit_count_30'])
    data = json.loads(capsys.readouterr().out)
    assert code == 0
    assert data['attr_changes'] == []


def test_rename_detection_collapses_add_remove_into_change(tmp_path, capsys):
    a = str(tmp_path / 'a.xml')
    b = str(tmp_path / 'b.xml')
    _write_single_child(a, 'alpha.py')
    _write_single_child(b, 'beta.py')

    # Without rename detection: alpha removed, beta added
    compare_cli.run([a, b, '-f', 'json'])
    data = json.loads(capsys.readouterr().out)
    assert any(e['path'].endswith('alpha.py') for e in data['removed_elements'])
    assert any(e['path'].endswith('beta.py') for e in data['new_elements'])

    # With rename detection: collapsed into a changed element carrying old_name
    compare_cli.run([a, b, '-f', 'json', '--rename-detection'])
    data = json.loads(capsys.readouterr().out)
    assert data['removed_elements'] == []
    assert data['new_elements'] == []
    assert any(e.get('old_name') == 'alpha.py' for e in data['changed_elements'])


def test_output_flag_writes_to_file_not_stdout(tmp_path, capsys):
    out_file = tmp_path / 'out.json'
    code = compare_cli.run([MODEL_A, MODEL_B, '-f', 'json', '-o', str(out_file)])
    assert code == 1
    assert capsys.readouterr().out.strip() == ''  # nothing on stdout
    data = json.loads(out_file.read_text())
    assert data['summary']['new_elements'] == 6
