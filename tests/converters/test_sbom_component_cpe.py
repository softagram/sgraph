"""The analyzer's `component_cpe` reaches the CycloneDX component as 'cpe', and nothing else does.

NVD indexes advisories by CPE, and a purl does not carry one, so a component whose ecosystem has
no purl-indexed advisory source -- a docker image above all -- matches nothing without it. Which
product an element is, the analyzer decides from its own evidence and stamps on the element; the
converter carries the value through, drops one that is malformed or claims more than one release,
and never derives a CPE of its own.
"""
import pytest

from sgraph import SElement, SElementAssociation, SGraph
from sgraph.converters import sbom_cyclonedx_generator
from sgraph.converters.sbom_cyclonedx_generator import (COMPONENT_CPE_ATTRIBUTE,
                                                        generate_for_element_from_sgraph,
                                                        generate_from_sgraph,
                                                        generate_multi_from_sgraph)

from .sbom_cyclonedx_generator_test import CYCLONEDX_1_6_KEYS, objects_by_cyclonedx_kind
from .test_sbom_installed_internal_copy import COPY_REF, consumer_document, estate

KEYCLOAK_CPE = 'cpe:2.3:a:redhat:keycloak:26.8.2:*:*:*:*:*:*:*'
KEYCLOAK_REF = 'pkg:docker/quay.io/keycloak/keycloak@26.8.2'


def image_model(cpe=None):
    """A Dockerfile building FROM the Keycloak image, the image stamped with `cpe` when given."""
    model = SGraph(SElement(None, ''))
    dockerfile = model.createOrGetElementFromPath('/Org/repoA/image/Dockerfile')
    dockerfile.setType('file')
    image = model.createOrGetElementFromPath(
        '/Org/External/Docker/Image/quay.io/keycloak/keycloak of tag 26.8.2')
    if cpe is not None:
        image.attrs[COMPONENT_CPE_ATTRIBUTE] = cpe
    SElementAssociation(dockerfile, image, 'from').initElems()
    return model


def the_image_component(model):
    components = {c['bom-ref']: c for c in generate_from_sgraph(model)['components']}
    return components[KEYCLOAK_REF]


def test_the_stamped_cpe_is_the_components_cpe():
    component = the_image_component(image_model(KEYCLOAK_CPE))

    assert component['cpe'] == KEYCLOAK_CPE
    assert component['purl'] == KEYCLOAK_REF


def test_an_unstamped_element_gets_no_cpe():
    """No lookup by name: a Keycloak image the analyzer did not identify stays without one."""
    assert 'cpe' not in the_image_component(image_model())


def test_surrounding_whitespace_is_not_part_of_the_name():
    assert the_image_component(image_model(f' {KEYCLOAK_CPE}\n'))['cpe'] == KEYCLOAK_CPE


def test_a_blank_value_means_none_and_is_not_reported(capsys):
    assert 'cpe' not in the_image_component(image_model('  '))
    assert COMPONENT_CPE_ATTRIBUTE not in capsys.readouterr().err


def test_an_escaped_special_character_is_part_of_a_value():
    """'\\+' is how CPE 2.3 writes a literal '+', so a build-metadata version stays one value."""
    cpe = r'cpe:2.3:a:example:product:1.0.0\+build1:*:*:*:*:*:*:*'

    assert the_image_component(image_model(cpe))['cpe'] == cpe


@pytest.mark.parametrize('cpe', [
    pytest.param('cpe:/a:redhat:keycloak:26.8.2', id='2.2-uri-binding'),
    pytest.param('cpe:2.3:a:redhat:keycloak:26.8.2', id='too-few-attributes'),
    pytest.param(KEYCLOAK_CPE + ':*', id='too-many-attributes'),
    pytest.param('cpe:2.3:a:redhat:keycloak:26.8.2:*:*:english:*:*:*:*', id='not-a-language-tag'),
    pytest.param('cpe:2.3:a:red hat:keycloak:26.8.2:*:*:*:*:*:*:*', id='unescaped-space'),
    pytest.param('redhat:keycloak', id='not-a-cpe'),
])
def test_a_malformed_name_is_dropped_and_reported(cpe, capsys):
    """A consumer rejects or mismatches a malformed CPE, and repairing it would invent a claim."""
    assert 'cpe' not in the_image_component(image_model(cpe))
    err = capsys.readouterr().err
    assert COMPONENT_CPE_ATTRIBUTE in err and 'keycloak of tag 26.8.2' in err


@pytest.mark.parametrize('cpe', [
    pytest.param('cpe:2.3:a:redhat:keycloak:*:*:*:*:*:*:*:*', id='any-version'),
    pytest.param('cpe:2.3:a:redhat:keycloak:-:*:*:*:*:*:*:*', id='na-version'),
    pytest.param('cpe:2.3:a:redhat:keycloak:26.*:*:*:*:*:*:*:*', id='version-wildcard'),
    pytest.param('cpe:2.3:a:redhat:keycloak:26.8.?:*:*:*:*:*:*:*', id='version-single-wildcard'),
    pytest.param('cpe:2.3:a:*:keycloak:26.8.2:*:*:*:*:*:*:*', id='any-vendor'),
    pytest.param('cpe:2.3:a:redhat:*:26.8.2:*:*:*:*:*:*:*', id='any-product'),
    pytest.param('cpe:2.3:a:redhat:key*:26.8.2:*:*:*:*:*:*:*', id='product-wildcard'),
    pytest.param('cpe:2.3:*:redhat:keycloak:26.8.2:*:*:*:*:*:*:*', id='any-part'),
])
def test_a_name_covering_more_than_one_release_is_dropped(cpe, capsys):
    """Well-formed, but a consumer would match it against releases the component is not."""
    assert 'cpe' not in the_image_component(image_model(cpe))
    assert COMPONENT_CPE_ATTRIBUTE in capsys.readouterr().err


def test_the_converter_derives_no_cpe_from_a_name():
    """Guards the boundary: product knowledge lives in the analyzer, not in this module."""
    assert not any(name.startswith('CPE_PRODUCT') for name in vars(sbom_cyclonedx_generator))


def folding_pair(plain_cpe, install_path_cpe):
    """Two npm elements that emit one component, each stamped with the given CPE (or none)."""
    model = SGraph(SElement(None, ''))
    a_file = model.createOrGetElementFromPath('/Org/repoA/src/a.js')
    b_file = model.createOrGetElementFromPath('/Org/repoA/src/b.js')
    npm = model.createOrGetElementFromPath('/Org/External/NPM')
    for name, source, cpe in (('strip-ansi', a_file, plain_cpe),
                              ('wrap-ansi-cjs/strip-ansi', b_file, install_path_cpe)):
        element = SElement(npm, name)
        element.attrs['version'] = '6.0.1'
        if cpe is not None:
            element.attrs[COMPONENT_CPE_ATTRIBUTE] = cpe
        SElementAssociation(source, element, 'packagejson').initElems()
    components = generate_from_sgraph(model)['components']
    assert len(components) == 1, [c['purl'] for c in components]
    return components[0]


STRIP_ANSI_CPE = 'cpe:2.3:a:strip-ansi_project:strip-ansi:6.0.1:*:*:*:*:node.js:*:*'
OTHER_CPE = 'cpe:2.3:a:someone:strip-ansi:6.0.1:*:*:*:*:node.js:*:*'


def test_a_merge_of_agreeing_elements_keeps_the_cpe():
    assert folding_pair(STRIP_ANSI_CPE, STRIP_ANSI_CPE)['cpe'] == STRIP_ANSI_CPE


@pytest.mark.parametrize('plain, install_path', [
    pytest.param(STRIP_ANSI_CPE, OTHER_CPE, id='disagree'),
    pytest.param(STRIP_ANSI_CPE, None, id='survivor-only'),
    pytest.param(None, STRIP_ANSI_CPE, id='duplicate-only'),
])
def test_a_merge_without_agreement_drops_the_cpe(plain, install_path):
    """Either CPE alone would match advisories the other element's identity denies, and an
    element that says nothing does not corroborate one that does."""
    assert 'cpe' not in folding_pair(plain, install_path)


def test_a_folded_installed_copy_brings_its_cpe_to_the_row():
    """The folded row describes the bytes the consumer installed, so it names their product."""
    model = estate()
    copy = model.findElementFromPath(
        '/acme-platform/External/NPM/@acme__slash__ui/@acme__slash__ui of version 1.2.0')
    cpe = 'cpe:2.3:a:acme:ui:1.2.0:*:*:*:*:node.js:*:*'
    copy.attrs[COMPONENT_CPE_ATTRIBUTE] = cpe

    rows = [c for c in consumer_document(model)['components'] if c.get('cpe')]

    assert len(rows) == 1 and rows[0]['cpe'] == cpe
    assert rows[0]['bom-ref'] != COPY_REF


@pytest.mark.parametrize('generate', [
    pytest.param(lambda m: [generate_from_sgraph(m)], id='single'),
    pytest.param(lambda m: generate_multi_from_sgraph(m, level=2), id='multi'),
    pytest.param(lambda m: generate_multi_from_sgraph(m, level=2, transitive=True),
                 id='multi-transitive'),
    pytest.param(lambda m: [generate_for_element_from_sgraph(m, '/Org/repoA')], id='element'),
])
def test_every_document_mode_carries_the_cpe_and_stays_valid(generate):
    """'cpe' is a member of the component definition in every supported CycloneDX version."""
    documents = generate(image_model(KEYCLOAK_CPE))

    assert any(c.get('cpe') == KEYCLOAK_CPE for d in documents for c in d.get('components', []))
    for document in documents:
        for kind, obj in objects_by_cyclonedx_kind(document):
            assert not set(obj) - CYCLONEDX_1_6_KEYS[kind], (kind, sorted(obj))
