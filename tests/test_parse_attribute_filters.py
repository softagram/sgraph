"""elem_attribute_filters and assoc_attribute_filters must each govern their own
kind of attribute, independently, and must reach both spellings the XML format
allows: an <a n=".." v=".."/> child, and an attribute written inline on the
enclosing <e> or <r> tag."""
import io

from sgraph import SGraph

# Every element and every association carries the same two attributes, once in
# each spelling, so a filter that reaches only one spelling is visible.
MODEL = """<model version="2.1">
  <e n="repo">
    <e n="a.py" t="file" elem_inline="ei">
      <a n="elem_child" v="ec" />
      <r r="2" t="use" assoc_inline="ai">
        <a n="assoc_child" v="ac" />
      </r>
    </e>
    <e n="b.py" t="file" i="2" elem_inline="ei">
      <a n="elem_child" v="ec" />
    </e>
  </e>
</model>
"""

ALL_ELEM = {'elem_inline': 'ei', 'elem_child': 'ec'}
ALL_ASSOC = {'assoc_inline': 'ai', 'assoc_child': 'ac'}


def load(**kwargs):
    """Element and association attributes of /repo/a.py, minus the structural ones.

    'type' on an element and deptype on an association describe what the thing is,
    not data attached to it, so no attribute filter is meant to reach them - see
    test_structural_type_survives_every_filter.
    """
    graph = SGraph.parse_xml_file_or_stream(io.StringIO(MODEL), **kwargs)
    repo = graph.rootNode.children[0]
    elem = next(c for c in repo.children if c.name == 'a.py')
    elem_attrs = {k: v for k, v in elem.attrs.items() if k != 'type'}
    return elem_attrs, dict(elem.outgoing[0].attrs or {})


def test_without_filters_every_attribute_is_kept():
    assert load() == (ALL_ELEM, ALL_ASSOC)


def test_assoc_ignore_all_drops_association_attributes_in_both_spellings():
    elem_attrs, assoc_attrs = load(assoc_attribute_filters=['IGNORE *'])

    assert assoc_attrs == {}
    assert elem_attrs == ALL_ELEM, 'association filters must not touch element attributes'


def test_elem_ignore_all_drops_element_attributes_in_both_spellings():
    elem_attrs, assoc_attrs = load(elem_attribute_filters=['IGNORE *'])

    assert elem_attrs == {}
    assert assoc_attrs == ALL_ASSOC, 'element filters must not touch association attributes'


def test_ignoring_everything_drops_everything():
    assert load(elem_attribute_filters=['IGNORE *'],
                assoc_attribute_filters=['IGNORE *']) == ({}, {})


def test_assoc_blacklist_reaches_both_spellings():
    assert load(assoc_attribute_filters=['IGNORE assoc_inline'])[1] == {'assoc_child': 'ac'}
    assert load(assoc_attribute_filters=['IGNORE assoc_child'])[1] == {'assoc_inline': 'ai'}


def test_assoc_whitelist_reaches_both_spellings():
    assert load(assoc_attribute_filters=['assoc_inline'])[1] == {'assoc_inline': 'ai'}
    assert load(assoc_attribute_filters=['assoc_child'])[1] == {'assoc_child': 'ac'}


def test_elem_blacklist_reaches_both_spellings():
    assert load(elem_attribute_filters=['IGNORE elem_inline'])[0] == {'elem_child': 'ec'}
    assert load(elem_attribute_filters=['IGNORE elem_child'])[0] == {'elem_inline': 'ei'}


def test_elem_whitelist_reaches_both_spellings():
    assert load(elem_attribute_filters=['elem_inline'])[0] == {'elem_inline': 'ei'}
    assert load(elem_attribute_filters=['elem_child'])[0] == {'elem_child': 'ec'}


def test_structural_type_survives_every_filter():
    """An element's type is set outside the attribute-filter path on purpose."""
    graph = SGraph.parse_xml_file_or_stream(io.StringIO(MODEL),
                                            elem_attribute_filters=['IGNORE *'],
                                            assoc_attribute_filters=['IGNORE *'])
    repo = graph.rootNode.children[0]
    elem = next(c for c in repo.children if c.name == 'a.py')

    assert elem.attrs == {'type': 'file'}


def test_filtering_association_attributes_keeps_the_association_itself():
    graph = SGraph.parse_xml_file_or_stream(io.StringIO(MODEL),
                                            assoc_attribute_filters=['IGNORE *'])
    repo = graph.rootNode.children[0]
    elem = next(c for c in repo.children if c.name == 'a.py')

    assert len(elem.outgoing) == 1
    assert elem.outgoing[0].deptype == 'use'
    assert elem.outgoing[0].toElement.name == 'b.py'
