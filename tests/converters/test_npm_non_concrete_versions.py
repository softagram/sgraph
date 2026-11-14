"""An npm component is emitted only when its version names a published release.

The model stores whatever the analyzer put in the version field, and for npm that has included
declared ranges: `debug of version 4` is the range `https-proxy-agent` asks for, not a release.
Spliced into a purl it became `pkg:npm/debug@4`, which Dependency-Track matched against
MAL-2025-46974 (the malicious debug 4.4.2) in 66 repositories at once -- 66 CRITICAL findings for
a package none of them installs at that version.

A versionless purl would not do: consumers match those broadly, so dropping the version widens
the claim instead of withdrawing it. The component is withheld, and the document says how many
were withheld, so a consumer can tell an under-reported BOM from a complete one.

`is_unresolved_version` already covers build-property expressions (`${...}`) for every ecosystem.
This is the npm-specific rule beside it: a version that is not an exact semver.
"""
import pytest
from sgraph import SElement, SElementAssociation, SGraph

from sgraph.converters import sbom_cyclonedx_generator
from sgraph.converters.sbom_cyclonedx_generator import (OMITTED_NON_CONCRETE_PROPERTY,
                                                        is_exact_npm_version)

# Ranges, tags and plugin protocols seen in the estate's own models, with the count each had.
NON_CONCRETE = ['*', 'backstage:^', '3', '1', '2', '1 - 3', '4', '1.x', '2.x.x', '>=1',
                '^4.1.0', '~1.2.3', 'latest', 'next', '1.2', 'v1.x']

# Exact releases, including the two shapes semver allows beyond major.minor.patch.
CONCRETE = ['4.4.1', '1.0.0', '1.0.0-beta.1', '1.2.3+build.5', '0.0.0-use.local',
            '=1.2.3', 'v1.2.3', '10.20.30', '1.0.0-rc.1+exp.sha.5114f85']


def model_with(name, version, root='NPM'):
    model = SGraph(SElement(None, ''))
    user = model.createOrGetElementFromPath('/Org/repo/package.json')
    user.setType('file')
    add_package(model, name, version, root)
    return model


def add_package(model, name, version, root='NPM'):
    """A versioned external in the shape the analyzers store it, used by the repo's manifest.

    Something has to point at it: valid_for_bom declines an external nothing references.

    The element is built with SElement, not createOrGetElementFromPath: a version holding a
    slash -- `https://github.com/x/y.git` -- would otherwise be split into path segments and the
    fixture would describe a different package than the test says. sgraph itself encodes a slash
    in a name as `__slash__`; here the name is assembled directly, which is the same thing
    without the decoding step.
    """
    package = model.findElementFromPath(f'/Org/External/{root}/{name}')
    if package is None:
        ecosystem = model.createOrGetElementFromPath(f'/Org/External/{root}')
        package = SElement(ecosystem, name)
    versioned = SElement(package, f'{name} of version {version}')
    versioned.attrs['version'] = version
    SElementAssociation(model.findElementFromPath('/Org/repo/package.json'),
                        versioned, 'packagejson').initElems()
    return versioned


def components_of(model):
    return sbom_cyclonedx_generator.generate_from_sgraph(model)['components']


def metadata_properties(sbom):
    return {p['name']: p['value'] for p in sbom['metadata'].get('properties', [])}


class TestTheRule:
    @pytest.mark.parametrize('version', CONCRETE)
    def test_an_exact_release_is_concrete(self, version):
        assert is_exact_npm_version(version) is True

    @pytest.mark.parametrize('version', NON_CONCRETE)
    def test_a_range_or_tag_is_not(self, version):
        assert is_exact_npm_version(version) is False

    @pytest.mark.parametrize('version', [None, 42, b'1.2.3', []])
    def test_a_non_string_is_not(self, version):
        """Every version read out of a model is untrusted input."""
        assert is_exact_npm_version(version) is False


class TestWhatReachesTheDocument:
    @pytest.mark.parametrize('version', NON_CONCRETE)
    def test_a_non_concrete_npm_version_yields_no_component(self, version):
        assert components_of(model_with('debug', version)) == []

    @pytest.mark.parametrize('version', CONCRETE)
    def test_a_release_is_emitted_unchanged(self, version):
        [component] = components_of(model_with('debug', version))
        assert component['version'] == version
        assert component['purl'].startswith('pkg:npm/debug@')

    def test_the_malicious_match_that_started_this_is_gone(self):
        """`pkg:npm/debug@4` is the purl that produced 66 false CRITICAL findings."""
        purls = [c['purl'] for c in components_of(model_with('debug', '4'))]
        assert purls == []

    def test_a_scoped_package_follows_the_same_rule(self):
        assert components_of(model_with('@babel__slash__core', '^7.0.0')) == []
        assert len(components_of(model_with('@babel__slash__core', '7.26.0'))) == 1


class TestOtherEcosystemsAreUntouched:
    """The rule is npm's; nothing else may start rejecting versions it has always emitted."""

    @pytest.mark.parametrize('version', ['4', '1.x', '*', '1 - 3'])
    def test_a_nuget_version_of_the_same_shape_is_still_emitted(self, version):
        model = model_with('Newtonsoft.Json', version, root='Assemblies')
        assert len(components_of(model)) == 1

    def test_a_pip_version_of_the_same_shape_is_still_emitted(self):
        assert len(components_of(model_with('requests', '2.x', root='PIP'))) == 1


class TestTheOmissionIsReported:
    """Silence would turn a withheld component into an absent dependency."""

    def test_the_count_is_in_the_metadata(self):
        sbom = sbom_cyclonedx_generator.generate_from_sgraph(model_with('debug', '4'))
        assert metadata_properties(sbom)[OMITTED_NON_CONCRETE_PROPERTY] == '1'

    def test_nothing_is_said_when_nothing_was_withheld(self):
        """A property reading 0 on every clean document is noise the consumer must filter."""
        sbom = sbom_cyclonedx_generator.generate_from_sgraph(model_with('debug', '4.4.1'))
        assert OMITTED_NON_CONCRETE_PROPERTY not in metadata_properties(sbom)

    def test_several_omissions_are_counted(self):
        model = model_with('debug', '4')
        for name, version in (('left-pad', '*'), ('ms', '1 - 3'), ('axios', '^1.2.0')):
            add_package(model, name, version)
        sbom = sbom_cyclonedx_generator.generate_from_sgraph(model)
        assert metadata_properties(sbom)[OMITTED_NON_CONCRETE_PROPERTY] == '4'

    def test_the_count_is_a_string(self):
        """CycloneDX types properties[].value as a string; a bare int fails schema validation."""
        sbom = sbom_cyclonedx_generator.generate_from_sgraph(model_with('debug', '4'))
        assert isinstance(metadata_properties(sbom)[OMITTED_NON_CONCRETE_PROPERTY], str)


class TestTheShapesThatKeepTheirComponent:
    """A purl that carries no version asserts no version, so there is nothing to withhold.

    resolved_purl deliberately returns a versionless npm purl for three shapes, each with the raw
    value still disclosed in the component's version field. The first attempt at this rule
    withheld all of them and dropped 44 tests' worth of components that the document has always
    listed -- packages identified by a git URL, by a build expression, or by name alone.
    """

    def test_a_git_url_version_still_yields_a_component(self):
        [component] = components_of(model_with('lodash', 'https://github.com/x/y.git'))
        assert component['purl'] == 'pkg:npm/lodash'
        assert component['version'] == 'https://github.com/x/y.git'

    def test_a_build_expression_version_still_yields_a_component(self):
        [component] = components_of(model_with('lodash', '${project.version}'))
        assert component['purl'] == 'pkg:npm/lodash'

    def test_a_versionless_element_still_yields_what_it_did(self):
        model = model_with('lodash', '1.2.3')
        versionless = model.findElementFromPath('/Org/External/NPM/lodash')
        SElementAssociation(model.findElementFromPath('/Org/repo/package.json'),
                            versionless, 'packagejson').initElems()
        purls = {c['purl'] for c in components_of(model)}
        assert 'pkg:npm/lodash@1.2.3' in purls

    def test_an_npm_alias_keeps_its_component(self):
        """`npm:string-width@^4.2.0` names a real package installed under another name, and nine
        components in the stored models carry one. The purl keeps it verbatim."""
        [component] = components_of(model_with('string-width-cjs', 'npm:string-width@^4.2.0'))
        assert component['purl'] == 'pkg:npm/string-width-cjs@npm:string-width@^4.2.0'

    def test_an_empty_version_keeps_its_versionless_component(self):
        """An element that asserts no version asserts nothing wrong. resolved_purl already
        returns `pkg:npm/<name>` for it, and withholding would drop a package the document has
        always listed."""
        [component] = components_of(model_with('lodash', ''))
        assert component['purl'] == 'pkg:npm/lodash'

    def test_a_declared_range_marked_as_such_is_still_the_models_business(self):
        """`version_kind='declared_range'` names a population sgraph deliberately still emits:
        one element per declaring dependent, each with real incoming edges. Suppressing it is a
        producer-side decision, not one this rule may take by reading the string."""
        text = model_with('thenify', '>= 3.1.0 < 4')
        elem = text.findElementFromPath('/Org/External/NPM/thenify/thenify of version >= 3.1.0 < 4')
        elem.attrs['version_kind'] = 'declared_range'
        assert [c['name'] for c in components_of(text)] == ['thenify']

    def test_none_of_those_is_counted_as_withheld(self):
        sbom = sbom_cyclonedx_generator.generate_from_sgraph(
            model_with('lodash', 'https://github.com/x/y.git'))
        assert OMITTED_NON_CONCRETE_PROPERTY not in metadata_properties(sbom)
