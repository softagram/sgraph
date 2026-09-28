"""Where a package was fetched from, carried into the document.

A consumer reading this document cannot today tell a package that came from the public registry
from one that came from a feed only the organisation can reach. Both halves of that question --
"where did this come from" and "is this ours" -- are answered by the same fact, and the analyzers
can state it: a NuGet restore writes the feed into `.nupkg.metadata` beside every package, and an
npm lockfile records the registry each package resolved from.

This module is the export half. The analyzer stamps the ecosystem-neutral attribute
`package_source` on the package element -- the same convention `_package_identity_in_subtree`
documents for `package_name`/`version`/`ecosystem` -- and the converter publishes it twice: as the
`softagram:packageSource` property whenever it is known, and as the purl qualifier the spec
defines for exactly this whenever it is not the type's default registry.

What it must not do is change what a component IS. The qualifier goes in `purl` only; `bom-ref`
keeps the unqualified spelling, because `dedup_key` folds on it and two checkouts of one package
that happen to name different feeds must still be one component.
"""
import ast
import inspect
import json
import re
import textwrap

import pytest

from sgraph import SElement, SElementAssociation, SGraph
from sgraph.converters import sbom_cyclonedx_generator

NPM_PUBLIC = 'https://registry.npmjs.org'
NPM_PRIVATE = 'https://npm.internal.example/repository/npm-private'
NUGET_PUBLIC = 'https://api.nuget.org/v3/index.json'
NUGET_PRIVATE = ('https://pkgs.dev.azure.com/example-org/example-project'
                 '/_packaging/internal-feed/nuget/v3/index.json')

SOURCE_PROPERTY = 'softagram:packageSource'


def model_with(packages, parent='NPM'):
    """A model whose External/<parent> holds these (name, version, attrs) packages."""
    model = SGraph(SElement(None, ''))
    root = model.createOrGetElementFromPath(f'/Org/External/{parent}')
    referrer = model.createOrGetElementFromPath('/Org/repoA/src/app.js')
    for name, version, attrs in packages:
        elem = SElement(root, name)
        elem.attrs['version'] = version
        for key, value in (attrs or {}).items():
            elem.attrs[key] = value
        SElementAssociation(referrer, elem, 'use').initElems()
    return model


def components_of(model):
    sbom = sbom_cyclonedx_generator.generate_from_sgraph(model)
    return {c['name']: c for c in sbom['components']}


def component_for(name, version, attrs, parent='NPM'):
    return components_of(model_with([(name, version, attrs)], parent))[name]


def source_property(component):
    values = [p['value'] for p in component.get('properties', []) if p['name'] == SOURCE_PROPERTY]
    assert len(values) <= 1
    return values[0] if values else None


def lodash_from_two_checkouts(first_source, second_source):
    """One package reached from two repositories, each checkout naming its own source."""
    first = {'package_source': first_source} if first_source is not None else {}
    model = model_with([('lodash', '4.17.21', first)])
    other = model.createOrGetElementFromPath('/Org/External/NPM2')
    elem = SElement(other, 'lodash')
    elem.attrs['version'] = '4.17.21'
    elem.attrs['repotype'] = 'NPM'
    if second_source is not None:
        elem.attrs['package_source'] = second_source
    referrer = model.createOrGetElementFromPath('/Org/repoB/src/app.js')
    SElementAssociation(referrer, elem, 'use').initElems()

    sbom = sbom_cyclonedx_generator.generate_from_sgraph(model)
    return [c for c in sbom['components'] if c['name'] == 'lodash']


class TestAPrivateSourceIsQualified:
    def test_a_package_from_a_private_npm_registry_says_so(self):
        component = component_for('lodash', '4.17.21', {'package_source': NPM_PRIVATE})

        assert component['purl'] == ('pkg:npm/lodash@4.17.21?repository_url='
                                     'https:%2F%2Fnpm.internal.example%2Frepository%2Fnpm-private')
        assert source_property(component) == NPM_PRIVATE

    def test_a_package_from_a_private_nuget_feed_says_so(self):
        component = component_for('Example.Internal.Core', '1.4.0',
                                  {'package_source': NUGET_PRIVATE}, parent='Assemblies')

        assert component['purl'].startswith('pkg:nuget/Example.Internal.Core@1.4.0?')
        assert component['purl'].endswith(
            '?repository_url=https:%2F%2Fpkgs.dev.azure.com%2Fexample-org%2Fexample-project'
            '%2F_packaging%2Finternal-feed%2Fnuget%2Fv3%2Findex.json')


class TestThePublicRegistryIsNotQualified:
    """An absent repository_url already means the type's default registry. Stating it would be
    redundant, and would change the purl string of nearly every public component."""

    @pytest.mark.parametrize('source', [
        NPM_PUBLIC,
        NPM_PUBLIC + '/',
        'https://registry.yarnpkg.com',
        'https://registry.npmjs.org:443/',
        'https://registry.npmjs.org./',
    ])
    def test_npm(self, source):
        component = component_for('lodash', '4.17.21', {'package_source': source})

        assert component['purl'] == 'pkg:npm/lodash@4.17.21'

    def test_nuget_as_a_restore_records_it(self):
        component = component_for('Newtonsoft.Json', '13.0.3', {'package_source': NUGET_PUBLIC},
                                  parent='Assemblies')

        assert component['purl'] == 'pkg:nuget/Newtonsoft.Json@13.0.3'

    @pytest.mark.parametrize('parent, name, source', [
        ('Assemblies', 'Newtonsoft.Json', 'https://www.nuget.org/api/v2'),
        ('Assemblies', 'Newtonsoft.Json', 'https://nuget.org/api/v2'),
        ('PIP', 'requests', 'https://pypi.python.org/simple'),
    ])
    def test_the_other_spellings_of_a_default_registry(self, parent, name, source):
        component = component_for(name, '1.0.0', {'package_source': source}, parent=parent)

        assert '?' not in component['purl']
        assert source_property(component) == source

    def test_the_property_still_says_where_it_came_from(self):
        """Without it, 'confirmed public' and 'nobody recorded a source' would look the same."""
        component = component_for('lodash', '4.17.21', {'package_source': NPM_PUBLIC + '/'})

        assert source_property(component) == NPM_PUBLIC

    def test_a_default_host_of_another_type_is_not_a_default_here(self):
        component = component_for('lodash', '4.17.21', {'package_source': 'https://pypi.org'})

        assert component['purl'] == 'pkg:npm/lodash@4.17.21?repository_url=https:%2F%2Fpypi.org'


def emitted_purl_types():
    """Every purl type the generator can emit, read from the code that builds purls."""
    generator = sbom_cyclonedx_generator
    tree = ast.parse(textwrap.dedent(inspect.getsource(generator.resolved_purl)))
    types = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign) and any(
                isinstance(target, ast.Name) and target.id == 'pkgtype'
                for target in node.targets):
            if isinstance(node.value, ast.Constant):
                types.add(node.value.value)
            elif isinstance(node.value, ast.Name):
                types.add(getattr(generator, node.value.id))
    types |= set(re.findall(r'pkg:([a-z]+)/', inspect.getsource(generator.maven_purl)))
    types |= set(generator.PURL_TYPE_BY_REFERENCING_EXTENSION.values())
    return types


class TestEveryEmittedTypeIsClassified:
    """A purl type missing from both tables would qualify its own public registry."""

    def test_the_derivation_sees_every_branch(self):
        assert {'npm', 'deb', 'pypi', 'golang', 'nuget', 'docker', 'maven', 'gem',
                'generic'} <= emitted_purl_types()

    def test_each_type_is_in_exactly_one_table(self):
        with_default = set(sbom_cyclonedx_generator.DEFAULT_REPOSITORY_HOSTS)
        without_default = sbom_cyclonedx_generator.NO_DEFAULT_REPOSITORY_TYPES

        assert not with_default & without_default
        assert emitted_purl_types() <= with_default | without_default


class TestAnUnknownSourceStatesNothing:
    def test_no_attribute(self):
        """Absent is 'unknown'. A default would relabel every private package as public, which
        is the exact failure this is meant to remove."""
        component = component_for('lodash', '4.17.21', {})

        assert component['purl'] == 'pkg:npm/lodash@4.17.21'
        assert source_property(component) is None

    @pytest.mark.parametrize('value', ['', '   '])
    def test_an_empty_attribute(self, value):
        """purl gives an empty qualifier value the same meaning as no qualifier."""
        component = component_for('lodash', '4.17.21', {'package_source': value})

        assert component['purl'] == 'pkg:npm/lodash@4.17.21'
        assert source_property(component) is None

    @pytest.mark.parametrize('value', [
        '/home/alice/nuget-local',
        'C:\\Users\\alice\\nuget-local',
        'file:///home/alice/nuget-local',
        'registry.npmjs.org',
        'https://host:notaport/feed',
        'https://evil.example\\@registry.npmjs.org/',
    ])
    def test_a_source_that_is_not_an_http_url(self, value):
        """A local feed directory is not a repository URL, and publishing it would publish the
        analysis host's paths and user names. A backslash is refused outright, because parsers
        disagree about which host such a URL names."""
        component = component_for('lodash', '4.17.21', {'package_source': value})

        assert component['purl'] == 'pkg:npm/lodash@4.17.21'
        assert source_property(component) is None


class TestNothingSecretIsPublished:
    def test_user_info_is_dropped(self):
        component = component_for(
            'lodash', '4.17.21',
            {'package_source': 'https://ci-user:s3cret-token@npm.internal.example/repo'})

        assert source_property(component) == 'https://npm.internal.example/repo'
        assert 's3cret' not in json.dumps(component)
        assert 'ci-user' not in json.dumps(component)

    def test_query_and_fragment_are_dropped(self):
        component = component_for(
            'lodash', '4.17.21',
            {'package_source': 'https://npm.internal.example/repo?token=s3cret#frag'})

        assert source_property(component) == 'https://npm.internal.example/repo'
        assert 's3cret' not in json.dumps(component)

    def test_the_port_is_kept(self):
        component = component_for('lodash', '4.17.21',
                                  {'package_source': 'https://npm.internal.example:8443/repo'})

        assert source_property(component) == 'https://npm.internal.example:8443/repo'
        assert component['purl'].endswith('repository_url=https:%2F%2Fnpm.internal.example:8443'
                                          '%2Frepo')

    def test_a_port_that_is_the_scheme_default_is_dropped(self):
        """So 'host:443' and 'host' are one source when duplicates are merged."""
        component = component_for('lodash', '4.17.21',
                                  {'package_source': 'https://npm.internal.example:443/repo'})

        assert source_property(component) == 'https://npm.internal.example/repo'


class TestIdentityIsNotAffected:
    def test_the_bom_ref_keeps_the_unqualified_purl(self):
        """`dedup_key` folds on bom-ref and dependency edges resolve through it. A qualifier
        there would split one package into one component per feed."""
        component = component_for('lodash', '4.17.21', {'package_source': NPM_PRIVATE})

        assert component['bom-ref'] == 'pkg:npm/lodash@4.17.21'
        assert component['purl'] != component['bom-ref']

    def test_the_component_type_is_still_read_from_the_purl_type(self):
        component = component_for('lodash', '4.17.21', {'package_source': NPM_PRIVATE})

        assert component['type'] == 'library'


class TestTheValueIsEncodedAsTheStandardRequires:
    def test_separators_in_the_path_are_encoded(self):
        """'&' and '=' would split the qualifier segment. '/' is encoded as in every
        repository_url example the standard gives, and '@' like every other separator character
        outside its separator role. Only ':' stays raw."""
        component = component_for('lodash', '4.17.21',
                                  {'package_source': 'https://host.example/a&b=c/@d e'})

        qualifier = component['purl'].split('?', 1)[1]
        assert qualifier == 'repository_url=https:%2F%2Fhost.example%2Fa%26b%3Dc%2F%40d%20e'

    def test_an_already_escaped_path_is_escaped_again(self):
        """The qualifier value is the URL string itself, so its '%' is data and must be encoded;
        decoding the qualifier gives back the URL unchanged."""
        component = component_for('lodash', '4.17.21',
                                  {'package_source': 'https://host.example/feed%2Fx'})

        assert component['purl'].endswith('repository_url=https:%2F%2Fhost.example%2Ffeed%252Fx')


class TestAVersionlessPurl:
    def test_the_qualifier_follows_the_name_with_no_stray_at(self):
        """Four of the five returns in resolved_purl emit a versionless purl. The qualifier has
        to attach to all of them, and must not resurrect the trailing '@' those returns exist to
        avoid."""
        component = component_for('lodash', 'https://github.com/x/y.git',
                                  {'package_source': NPM_PRIVATE})

        assert component['purl'].startswith('pkg:npm/lodash?repository_url=')
        assert '@?' not in component['purl']
        # The raw value still reaches the consumer; only the purl declines to carry it.
        assert component['version'] == 'https://github.com/x/y.git'


class TestAPurlThatAlreadyOpensASubpath:
    def test_a_git_shaped_version_gets_no_qualifier(self):
        """Versions are spliced in unencoded, so '#' already starts a subpath, and a qualifier
        appended after it would be read as part of that subpath."""
        component = component_for('dep1', 'github:user/repo#abc123',
                                  {'package_source': NPM_PRIVATE})

        assert 'repository_url' not in component['purl']
        assert source_property(component) == NPM_PRIVATE


class TestTwoSourcesForOnePackage:
    """One package, two checkouts, two sources. The document must not pick a winner."""

    def test_the_package_is_still_one_component(self):
        assert len(lodash_from_two_checkouts(NPM_PUBLIC, NPM_PRIVATE)) == 1

    @pytest.mark.parametrize('first, second', [
        (NPM_PUBLIC, NPM_PRIVATE),
        (NPM_PRIVATE, NPM_PUBLIC),
        (NPM_PRIVATE, 'https://npm2.internal.example'),
    ])
    def test_a_disagreement_drops_the_source_rather_than_choosing(self, first, second):
        [lodash] = lodash_from_two_checkouts(first, second)

        assert lodash['purl'] == 'pkg:npm/lodash@4.17.21'
        assert source_property(lodash) is None

    @pytest.mark.parametrize('source', [NPM_PUBLIC, NPM_PRIVATE])
    def test_agreement_survives_the_merge(self, source):
        [lodash] = lodash_from_two_checkouts(source, source)

        assert source_property(lodash) == source
        assert lodash['purl'] == sbom_cyclonedx_generator.source_qualified_purl(
            'pkg:npm/lodash@4.17.21', source)

    def test_two_spellings_of_one_registry_agree(self):
        [lodash] = lodash_from_two_checkouts(NPM_PRIVATE, NPM_PRIVATE + '/')

        assert source_property(lodash) == NPM_PRIVATE

    @pytest.mark.parametrize('first, second', [(NPM_PRIVATE, None), (None, NPM_PRIVATE)])
    def test_silence_on_one_side_does_not_corroborate_the_other(self, first, second):
        """'unknown' is not agreement. The same retraction the repair provenance already makes
        when any merged element did not support the claim."""
        [lodash] = lodash_from_two_checkouts(first, second)

        assert lodash['purl'] == 'pkg:npm/lodash@4.17.21'
        assert source_property(lodash) is None
