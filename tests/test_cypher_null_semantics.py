"""Regression test: Cypher null semantics under pandas 3.

spycy marks Cypher ``null`` with ``pd.NA`` and tests for it with
``value is pd.NA``. pandas 3 infers the ``str`` dtype for string columns by
default, and that dtype stores a missing value as ``NaN`` rather than
``pd.NA``. Without a guard, a missing string property stops being null once it
has passed through a spycy table: ``IS NULL`` matches nothing, ``coalesce``
returns NaN, ``count`` counts it, and the JSON output emits ``NaN``, which is
not valid JSON. ``SGraphCypherExecutor.exec`` keeps string columns as
``object`` while spycy runs; these tests lock in pandas 2 behaviour.
"""

import json
import warnings

import pytest

pytest.importorskip("spycy")

import pandas as pd  # noqa: E402

from sgraph import SGraph  # noqa: E402
from sgraph.cypher import _dataframe_to_serializable, cypher_query  # noqa: E402
from sgraph.selementassociation import SElementAssociation  # noqa: E402


def build_model() -> SGraph:
    """Three files; b.py has no 'extra' attribute and is the only import target."""
    model = SGraph()
    for path, extra in [("/proj/a.py", "x"), ("/proj/b.py", None), ("/proj/c.py", "y")]:
        elem = model.createOrGetElementFromPath(path)
        elem.setType("file")
        if extra:
            elem.attrs["extra"] = extra
    a = model.findElementFromPath("/proj/a.py")
    b = model.findElementFromPath("/proj/b.py")
    SElementAssociation(a, b, "import").initElems()
    return model


def names(result) -> list:
    return sorted(result[result.columns[0]].tolist())


def test_is_null_on_missing_property_after_with():
    result = cypher_query(
        build_model(),
        "MATCH (f:file) WITH f.name AS n, f.extra AS e WHERE e IS NULL RETURN n")
    assert names(result) == ["b.py"]


def test_is_null_on_optional_match_after_with():
    result = cypher_query(
        build_model(), "MATCH (f:file) OPTIONAL MATCH (f)-[:import]->(g) "
        "WITH f.name AS n, g.name AS t WHERE t IS NULL RETURN n")
    assert names(result) == ["b.py", "c.py"]


def test_is_null_on_unwound_null():
    result = cypher_query(
        build_model(),
        "UNWIND ['a', null, 'b'] AS x WITH x WHERE x IS NULL RETURN count(*) AS c")
    assert result["c"].tolist() == [1]


def test_coalesce_replaces_missing_property():
    result = cypher_query(
        build_model(),
        "MATCH (f:file) RETURN f.name AS n, coalesce(f.extra, 'none') AS e ORDER BY n")
    assert result["e"].tolist() == ["x", "none", "y"]


def test_count_skips_missing_property():
    result = cypher_query(build_model(), "MATCH (f:file) RETURN count(f.extra) AS c")
    assert result["c"].tolist() == [2]


def test_missing_value_in_result_is_pd_na():
    result = cypher_query(
        build_model(), "MATCH (f:file) RETURN f.name AS n, f.extra AS e ORDER BY n")
    assert result["e"].iloc[1] is pd.NA


def test_json_output_uses_null_for_missing_property():
    result = cypher_query(
        build_model(), "MATCH (f:file) RETURN f.name AS n, f.extra AS e ORDER BY n")
    text = json.dumps(_dataframe_to_serializable(result))
    assert "NaN" not in text
    assert json.loads(text)[1] == {"n": "b.py", "e": None}


def test_no_infer_string_deprecation_warning_leaks():
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        cypher_query(build_model(), "MATCH (f:file) RETURN f.name")
    assert not [w for w in caught if "infer_string" in str(w.message)]
