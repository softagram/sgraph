"""The XML reader must hand out one string object per distinct attribute name,
attribute value, element type and dependency type, instead of a fresh object per
occurrence. Models repeat these heavily, so the duplicates dominate the loaded
model's string footprint.

These tests assert object identity because it is the only cheap proxy for "this
string is stored once". Identity is not an sgraph guarantee: nothing in the
library compares attribute strings with `is`, and nothing may start to. Compare
attribute values with `==`."""
import io

from sgraph import SGraph

# Two sibling files carrying the same attribute names and the same values, plus a
# dependency between them. Values are multi-character so that CPython's own
# caching of latin-1 singletons cannot be mistaken for pooling.
MODEL = """<model version="2.1">
  <e n="repo">
    <e n="a.py" t="file" language="python">
      <a n="analyzer_name" v="python_analyzer" />
      <r r="2" t="function_ref">
        <a n="call_context" v="module_level" />
      </r>
    </e>
    <e n="b.py" t="file" language="python" i="2">
      <a n="analyzer_name" v="python_analyzer" />
      <r r="3" t="function_ref">
        <a n="call_context" v="module_level" />
      </r>
    </e>
    <e n="c.py" t="file" language="python" i="3" />
  </e>
</model>
"""


# Same shape, but the association attributes are written as XML attributes on <r>.
INLINE_ASSOC_MODEL = """<model version="2.1">
  <e n="repo">
    <e n="a.py">
      <r r="2" t="function_ref" call_context="module_level" />
    </e>
    <e n="b.py" i="2">
      <r r="3" t="function_ref" call_context="module_level" />
    </e>
    <e n="c.py" i="3" />
  </e>
</model>
"""


def parse():
    return SGraph.parse_xml_file_or_stream(io.StringIO(MODEL))


def files_of(graph):
    repo = graph.rootNode.children[0]
    return {child.name: child for child in repo.children}


def test_repeated_attribute_names_share_one_object():
    files = files_of(parse())
    name_a = next(k for k in files['a.py'].attrs if k == 'analyzer_name')
    name_b = next(k for k in files['b.py'].attrs if k == 'analyzer_name')

    assert name_a is name_b


def test_repeated_attribute_values_share_one_object():
    files = files_of(parse())

    assert files['a.py'].attrs['analyzer_name'] is files['b.py'].attrs['analyzer_name']


def test_repeated_inline_attribute_values_share_one_object():
    """Element attributes written as XML attributes on <e>, not as <a> children."""
    files = files_of(parse())

    assert files['a.py'].attrs['language'] is files['b.py'].attrs['language']


def test_repeated_inline_attribute_names_share_one_object():
    """expat does not reuse attribute-name objects across a document, so the inline
    form needs pooling just as much as the <a n=...> form does."""
    files = files_of(parse())
    name_a = next(k for k in files['a.py'].attrs if k == 'language')
    name_b = next(k for k in files['b.py'].attrs if k == 'language')

    assert name_a is name_b


def test_repeated_inline_association_attribute_names_share_one_object():
    """Association attributes written as XML attributes on <r>."""
    graph = SGraph.parse_xml_file_or_stream(io.StringIO(INLINE_ASSOC_MODEL))
    files = files_of(graph)
    attrs_a = files['a.py'].outgoing[0].attrs
    attrs_b = files['b.py'].outgoing[0].attrs

    name_a = next(k for k in attrs_a if k == 'call_context')
    name_b = next(k for k in attrs_b if k == 'call_context')
    assert name_a is name_b
    assert attrs_a['call_context'] is attrs_b['call_context']


def test_repeated_element_types_share_one_object():
    files = files_of(parse())

    assert files['a.py'].typeEquals(files['b.py'].getType())
    assert files['a.py'].attrs['type'] is files['b.py'].attrs['type']


def test_repeated_dependency_types_share_one_object():
    files = files_of(parse())
    dep_a = files['a.py'].outgoing[0]
    dep_b = files['b.py'].outgoing[0]

    assert dep_a.deptype == 'function_ref'
    assert dep_a.deptype is dep_b.deptype


def test_repeated_association_attributes_share_one_object():
    files = files_of(parse())
    attrs_a = files['a.py'].outgoing[0].attrs
    attrs_b = files['b.py'].outgoing[0].attrs

    name_a = next(k for k in attrs_a if k == 'call_context')
    name_b = next(k for k in attrs_b if k == 'call_context')
    assert name_a is name_b
    assert attrs_a['call_context'] is attrs_b['call_context']


def test_whitelisted_inline_attributes_are_pooled():
    """The whitelist branch of the inline-element-attribute path pools too."""
    graph = SGraph.parse_xml_file_or_stream(io.StringIO(MODEL),
                                            elem_attribute_filters=['language'])
    files = files_of(graph)

    assert 'language' in files['a.py'].attrs
    name_a = next(k for k in files['a.py'].attrs if k == 'language')
    name_b = next(k for k in files['b.py'].attrs if k == 'language')
    assert name_a is name_b
    assert files['a.py'].attrs['language'] is files['b.py'].attrs['language']


def test_pooling_does_not_outlive_the_parse():
    """The pool must not be process-global: two parses produce independent objects,
    so a long-lived process that loads many models can free each model's strings."""
    first = files_of(parse())['a.py'].attrs['analyzer_name']
    second = files_of(parse())['a.py'].attrs['analyzer_name']

    assert first == second
    assert first is not second


def test_attribute_without_value_still_parses_as_none():
    xml = '<model version="2.1"><e n="repo"><e n="f.py"><a n="novalue" /></e></e></model>'
    graph = SGraph.parse_xml_file_or_stream(io.StringIO(xml))
    elem = graph.rootNode.children[0].children[0]

    assert elem.attrs['novalue'] is None
