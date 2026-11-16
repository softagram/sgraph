"""An estate-published npm package is one row in its consumer's document, not two (issue #224).

When one repository installs a package another repository of the same model publishes, the
analyzer stores the installed copy under External/NPM like any other installed release, and says
who publishes it in the copy's `internal_package` attribute: the path of the publisher's package
element. The publisher's element still reaches the consumer's document as an internal component.
Before the fold both were emitted, so the document named one package twice -- as
`pkg:generic/<name>@<publisher's current version>` and as the installed copy's npm purl -- and
the two even disagreed on the version once the publisher had moved on.

The fold keeps one component: the copy's version and purl, which describe the bytes the consumer
installed, with the internal identity as properties. It is driven by the attribute alone. A name
match without it is exactly the guess the analyzer's resolution ladder declines to make, since a
public package may share an internal package's name.

The fixture mirrors what the analyzer's own test estate stores (softagram-live,
test_npm_internal_copy_reaches_its_subtree.py): the consumer's package.json points at both the
publisher's package element and the installed copy, and the copy carries the lock's edges.
"""
import json

import pytest

from sgraph import SElement, SElementAssociation, SGraph
from sgraph.converters import sbom_cyclonedx_generator
from sgraph.converters.sbom_cyclonedx_generator import (generate_for_element_from_sgraph,
                                                        generate_from_sgraph,
                                                        generate_multi_from_sgraph,
                                                        slugify_bom_ref)

PROJECT = 'acme-platform'
CONSUMER = f'/{PROJECT}/acme.shop.webui'
PUBLISHER = f'/{PROJECT}/acme.libs.ui'
PUBLISHED = '@acme/ui'
ENCODED = '@acme__slash__ui'
INSTALLED = '1.2.0'
PRIVATE_FEED = 'https://pkgs.dev.azure.com'
PUBLIC_NPM = 'https://registry.npmjs.org'

COPY_REF = f'pkg:npm/%40acme/ui@{INSTALLED}'
PUBLISHER_REF = slugify_bom_ref('acme.libs.ui')
CONSUMER_REF = slugify_bom_ref('acme.shop.webui')

MODES = {
    'default': {},
    'transitive': {'transitive': True},
    'transitive-externals': {'transitive_externals': True},
    'both': {'transitive': True, 'transitive_externals': True},
}


def _npm_release(npm, encoded_name, version, source):
    package = npm.getChildByName(encoded_name) or SElement(npm, encoded_name)
    release = SElement(package, f'{encoded_name} of version {version}')
    release.attrs['version'] = version
    if source is not None:
        release.attrs['package_source'] = source
    return release


def estate(published_version=INSTALLED, stamp=True, source=PRIVATE_FEED, consumer_edge=True,
           second_copy=False, publisher_declares=None):
    """The consumer installs the publisher's package from a feed; the copy installs lodash.

    :param published_version: what the publisher's own package.json declares now
    :param stamp: whether the copy names its publisher in `internal_package`
    :param source: the feed the copy was installed from, or None when nobody recorded it
    :param consumer_edge: whether the consumer's declaration also reaches the publisher's element
    :param second_copy: also install an older copy, naming the same publisher, from the consumer
    :param publisher_declares: an npm package the publisher's own manifest declares, or None
    """
    model = SGraph()
    project = SElement(model.rootNode, PROJECT)
    project.setType('repository')
    npm = SElement(SElement(project, 'External'), 'NPM')

    consumer = project.createOrGetElement('acme.shop.webui')
    consumer.setType('dir')
    consumer_manifest = SElement(consumer, 'package.json')
    consumer_manifest.setType('file')

    publisher = project.createOrGetElement('acme.libs.ui')
    publisher.setType('dir')
    publisher_manifest = SElement(publisher, 'package.json')
    publisher_manifest.setType('file')
    package = publisher_manifest.createOrGetElement(ENCODED)
    package.attrs.update({'package_name': PUBLISHED, 'version': published_version,
                          'ecosystem': 'npm'})

    copy = _npm_release(npm, ENCODED, INSTALLED, source)
    if stamp:
        copy.attrs['internal_package'] = package.getPath()
    lodash = _npm_release(npm, 'lodash', '4.17.20', PUBLIC_NPM)

    if consumer_edge:
        SElementAssociation(consumer_manifest, package, 'packagejson').initElems()
    SElementAssociation(consumer_manifest, copy, 'packagejson').initElems()
    hop = SElementAssociation(copy, lodash, 'packagelock')
    hop.attrs['declared_in'] = CONSUMER
    hop.initElems()

    if second_copy:
        older = _npm_release(npm, ENCODED, '1.1.0', source)
        older.attrs['internal_package'] = package.getPath()
        SElementAssociation(consumer_manifest, older, 'packagejson').initElems()

    if publisher_declares is not None:
        declared = _npm_release(npm, publisher_declares, '18.2.0', PUBLIC_NPM)
        SElementAssociation(publisher_manifest, declared, 'packagejson').initElems()
    return model


def consumer_document(model, mode='default'):
    return generate_for_element_from_sgraph(model, CONSUMER, **MODES[mode])


def library_rows(document):
    return [c for c in document['components'] if c['name'] == PUBLISHED]


def the_library_row(document):
    rows = library_rows(document)
    assert len(rows) == 1, json.dumps(rows, indent=1)
    return rows[0]


def find_property(component, name):
    for prop in component.get('properties', []):
        if prop['name'] == name:
            return prop['value']
    return None


def entry(document, ref):
    entries = [e for e in document['dependencies'] if e['ref'] == ref]
    assert len(entries) <= 1, entries
    return entries[0] if entries else None


@pytest.mark.parametrize('published_version', [INSTALLED, '1.3.0'])
@pytest.mark.parametrize('mode', list(MODES))
class TestThePackageIsListedOnce:
    """The criterion of the issue, with the publisher at the installed version and a newer one."""

    def test_one_row(self, mode, published_version):
        the_library_row(consumer_document(estate(published_version), mode))

    def test_the_row_is_the_release_the_consumer_installed(self, mode, published_version):
        row = the_library_row(consumer_document(estate(published_version), mode))
        assert row['version'] == INSTALLED
        assert row['purl'] == f'{COPY_REF}?repository_url=https:%2F%2Fpkgs.dev.azure.com'

    def test_the_row_says_it_is_the_estates_own(self, mode, published_version):
        row = the_library_row(consumer_document(estate(published_version), mode))
        assert find_property(row, 'softagram:internal') == 'true'
        assert find_property(row, 'softagram:elementPath') == PUBLISHER
        assert find_property(row, 'softagram:elementType') == 'dir'
        assert find_property(row, 'softagram:packageName') == PUBLISHED
        assert find_property(row, 'softagram:packageEcosystem') == 'npm'
        assert row['group'] == PROJECT
        bom_links = [r for r in row['externalReferences'] if r['type'] == 'bom']
        assert len(bom_links) == 1 and bom_links[0]['url'].startswith('urn:cdx:')

    def test_the_row_keeps_what_the_copy_said(self, mode, published_version):
        row = the_library_row(consumer_document(estate(published_version), mode))
        assert find_property(row, 'softagram:packageSource') == PRIVATE_FEED
        assert find_property(row, 'sourceCodeReferences') == f'{CONSUMER}/package.json'

    def test_the_publishers_own_version_is_still_stated(self, mode, published_version):
        """Folding must not lose the one fact only the publisher's row carried."""
        row = the_library_row(consumer_document(estate(published_version), mode))
        assert find_property(row, 'softagram:publishedVersion') == published_version

    def test_the_row_is_named_by_the_publishers_ref(self, mode, published_version):
        """The element's slug survives, as on every internal component: the dependency graph
        names the element by it."""
        row = the_library_row(consumer_document(estate(published_version), mode))
        assert row['bom-ref'] == PUBLISHER_REF

    def test_no_dependency_names_the_folded_copy(self, mode, published_version):
        document = consumer_document(estate(published_version), mode)
        refs = [e['ref'] for e in document['dependencies']]
        refs += [r for e in document['dependencies'] for r in e['dependsOn']]
        assert COPY_REF not in refs

    def test_the_consumer_depends_on_the_package_once(self, mode, published_version):
        depends_on = entry(consumer_document(estate(published_version), mode),
                           CONSUMER_REF)['dependsOn']
        assert depends_on.count(PUBLISHER_REF) == 1
        assert len(depends_on) == len(set(depends_on))

    def test_every_ref_resolves_and_none_repeats(self, mode, published_version):
        document = consumer_document(estate(published_version), mode)
        known = {c['bom-ref'] for c in document['components']} | {CONSUMER_REF}
        refs = [e['ref'] for e in document['dependencies']]
        assert len(refs) == len(set(refs))
        for e in document['dependencies']:
            assert e['ref'] in known
            assert e['ref'] not in e['dependsOn']
            for ref in e['dependsOn']:
                assert ref in known or ref.startswith('urn:cdx:'), ref

    def test_no_collection_time_key_reaches_the_document(self, mode, published_version):
        document = consumer_document(estate(published_version), mode)
        assert all(not key.startswith('_') for c in document['components'] for key in c)


def test_the_bom_link_to_the_publishers_document_stays():
    """It federates to another document, so the fold has nothing to say about it."""
    depends_on = entry(consumer_document(estate()), CONSUMER_REF)['dependsOn']
    assert any(ref.startswith('urn:cdx:') and ref.endswith(f'#{PUBLISHER_REF}')
               for ref in depends_on)


@pytest.mark.parametrize('mode', ['transitive-externals', 'both'])
def test_what_the_copy_installs_hangs_off_the_folded_row(mode):
    document = consumer_document(estate(), mode)
    assert entry(document, PUBLISHER_REF)['dependsOn'] == ['pkg:npm/lodash@4.17.20']
    assert 'pkg:npm/lodash@4.17.20' not in entry(document, CONSUMER_REF)['dependsOn']


@pytest.mark.parametrize('mode', ['transitive-externals', 'both'])
def test_the_folded_row_keeps_the_depth_the_copy_was_found_at(mode):
    row = the_library_row(consumer_document(estate(), mode))
    assert find_property(row, 'dependencyDepth') == '1'


def test_the_publishers_declared_dependencies_and_the_copys_installed_ones_share_one_entry():
    """In the transitive view the publisher's element brings its own manifest's dependencies,
    and the copy what the consumer's lock installed. One component, so one entry with both."""
    document = consumer_document(estate(publisher_declares='react'), 'both')
    assert entry(document, PUBLISHER_REF)['dependsOn'] == \
        ['pkg:npm/react@18.2.0', 'pkg:npm/lodash@4.17.20']


def test_a_copy_from_the_public_registry_keeps_its_npm_purl():
    """The estate publishing to npmjs.org itself is the one case where pkg:npm is the truth."""
    row = the_library_row(consumer_document(estate(source=PUBLIC_NPM)))
    assert row['purl'] == COPY_REF


def test_a_copy_whose_source_nobody_recorded_is_not_claimed_to_be_on_the_public_registry():
    """An unqualified pkg:npm purl asserts the public registry. For a package the estate
    publishes, with no recorded feed, that is the dependency-confusion claim the generic type
    exists to avoid -- so the row keeps the generic type, at the version actually installed."""
    row = the_library_row(consumer_document(estate(source=None)))
    assert row['purl'] == f'pkg:generic/{PUBLISHED}@{INSTALLED}'
    assert row['version'] == INSTALLED


class TestNothingIsFoldedOnAGuess:

    def test_without_the_attribute_both_rows_stay(self):
        """A shared name is not evidence: a public package may carry an internal one's name."""
        rows = library_rows(consumer_document(estate(stamp=False)))
        assert sorted(r['purl'] for r in rows) == [
            f'pkg:generic/{PUBLISHED}@{INSTALLED}',
            f'{COPY_REF}?repository_url=https:%2F%2Fpkgs.dev.azure.com']

    def test_without_the_publisher_in_the_document_the_copy_is_unchanged(self):
        row = the_library_row(consumer_document(estate(consumer_edge=False)))
        assert row['bom-ref'] == COPY_REF
        assert find_property(row, 'softagram:internal') is None

    def test_two_installed_copies_of_one_publisher_are_not_folded(self):
        """Which of the two the publisher's row duplicates is not something the model says."""
        rows = library_rows(consumer_document(estate(second_copy=True)))
        assert sorted(r['version'] for r in rows) == ['1.1.0', '1.2.0', '1.2.0']
        assert sum(find_property(r, 'softagram:internal') == 'true' for r in rows) == 1


def test_the_fold_is_byte_stable():
    def content():
        document = consumer_document(estate(), 'both')
        return json.dumps([document['components'], document['dependencies']])
    assert content() == content()


@pytest.mark.parametrize('generate', [
    lambda model: [generate_from_sgraph(model)],
    lambda model: generate_multi_from_sgraph(model, level=2),
    lambda model: generate_multi_from_sgraph(model, level=2, transitive=True),
], ids=['single', 'multi', 'multi-transitive'])
def test_no_collection_time_key_reaches_any_document(generate):
    for document in generate(estate()):
        assert all(not key.startswith('_') for c in document['components'] for key in c)


def test_the_attribute_name_is_the_analyzers():
    assert sbom_cyclonedx_generator.INTERNAL_PACKAGE_ATTRIBUTE == 'internal_package'


@pytest.mark.parametrize('duplicate_publisher, survives', [
    ('/p/pkg', True), ('/q/pkg', False), (None, False)])
def test_a_merged_row_names_its_publisher_only_when_every_element_agrees(
        duplicate_publisher, survives):
    """The fold replaces the row's identity, so it must not rest on one element of several."""
    key = sbom_cyclonedx_generator.PUBLISHER_KEY
    surviving = {'bom-ref': COPY_REF, 'properties': [], key: '/p/pkg'}
    duplicate = {'bom-ref': COPY_REF, 'properties': []}
    if duplicate_publisher is not None:
        duplicate[key] = duplicate_publisher
    sbom_cyclonedx_generator.merge_component_evidence(surviving, duplicate)
    assert (surviving.get(key) == '/p/pkg') is survives
