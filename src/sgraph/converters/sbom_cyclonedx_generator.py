import uuid
from datetime import datetime
import json
import sys
from collections import defaultdict

from sgraph import SGraph, SElement


def valid_for_bom(elem):
    return 'version' in elem.attrs or ' of version ' in elem.name or ' of tag ' in elem.name \
           or 'license' in elem.attrs


def extract_version(elem):
    if 'version' in elem.attrs:
        return elem.attrs['version']
    if 'versions' in elem.attrs:
        return elem.attrs['versions']
    if ' of version ' in elem.name:
        return elem.name.split(' of version ')[-1].strip()
    if ' of tag ' in elem.name:
        return elem.name.split(' of tag ')[-1].strip()


def incoming_deps(elem, elem_name_patterns, deptypes):
    for association in elem.incoming:
        name_pat = False
        for n in elem_name_patterns:
            if n in association.fromElement.name:
                name_pat = True
                break
        if name_pat:
            for deptype in deptypes:
                if association.deptype == deptype:
                    return True


def parents_parent_or_parent_name_equals(elem, name):
    if elem.parent.name == name:
        return True
    return elem.parent.parent and elem.parent.parent.name == name


def bom_ref(elem, v):
    pkgid = elem.name  # todo also use url like github.com/foo/reponame
    if 'from' in elem.attrs:
        pkgid = elem.name

    pkgid = clean_name(pkgid)
    if elem.attrs.get('repotype', '') == 'NPM' or parents_parent_or_parent_name_equals(elem, 'NPM'):
        pkgtype = 'npm'
    elif elem.attrs.get('repotype', '') == 'APT' or parents_parent_or_parent_name_equals(
            elem, 'APT'):
        pkgtype = 'deb'
    elif elem.parent.name == 'Python' or elem.attrs.get(
            'repotype', '') == 'PIP' or parents_parent_or_parent_name_equals(elem, 'PIP'):
        pkgtype = 'pypi'  # ??
    elif elem.parent.name == 'Go':
        pkgtype = 'golang'
    elif elem.parent.name == 'Maven':
        pkgtype = 'maven'
    elif elem.parent.name == 'Java':
        pkgtype = '??Java'
    elif incoming_deps(elem, ['csproj', 'vbproj'],
                       ['assembly_ref']) or parents_parent_or_parent_name_equals(
                           elem, 'Assemblies'):
        pkgtype = 'nuget'
    elif '/External/Docker/Image/' in elem.getPath():
        pkgtype = 'docker'
        pkgid = elem.getPath().split('/External/Docker/Image/')[1]
        if ' of tag ' in pkgid:
            pkgid = pkgid.split(' of tag ')[0]
    else:
        pkgtype = '???'

    v = v.lstrip('^')
    return f'pkg:{pkgtype}/{pkgid}@{v}'


# TODO License mapping not implemented
license_mapping_to_spdx_id = {}


def resolve_license_spdx_id(license):
    acceptable_licenses = {'MIT'}
    if license in acceptable_licenses:
        return license
    else:
        if license in license_mapping_to_spdx_id:
            return license_mapping_to_spdx_id[license]
        return 'UNKNOWN LICENSE'  # TODO What is the proper value for this?


def bom_licenses(elem):
    """
    TODO License handling is still work-in-progress.
    :param elem:
    :return:
    """
    license_url = {
        'MIT': 'https://spdx.org/licenses/MIT.html',
        'GPL': 'TODO',
        'SPDX_OTHER_TODO': ''
    }
    if 'license' in elem.attrs:
        license_spdx_id = resolve_license_spdx_id(elem.attrs['license'])
        return [{
            'license': {
                'id': license_spdx_id,
                'url': license_url.get(license_spdx_id, 'UNKNOWN')
            }
        }]
    return []


def file_extension(e):
    if e is None or e.typeEquals('dir'):
        return ''
    elif e.typeEquals('file'):
        if '.' in e.name:
            return e.name.split('.')[-1]
        else:
            return ''
    return file_extension(e.parent)


def clean_name(name):
    if ' of version ' in name:
        return name.split(' of version ')[0].strip().replace('__slash__', '/')
    if ' of tag ' in name:
        return name.split(' of tag ')[0].strip().replace('__slash__', '/')
    return name.replace('__slash__', '/')


def produce_source_code_references(elem, external_root):

    direct_references = []
    traverse_externals = []
    for incoming_assoc in elem.incoming + elem.parent.incoming:
        if not incoming_assoc.fromElement.isDescendantOf(external_root):
            direct_references.append(incoming_assoc.fromElement.getPath())
        else:
            traverse_externals.append(incoming_assoc.fromElement)


    indirect_dependencies = []
    for external_dependency in traverse_externals:
        stack = list((external_dependency,))
        while stack:
            e = stack.pop(0)
            if not e.isDescendantOf(external_root):
                indirect_dependencies.append(e.getPath())
            else:
                if e.incoming:
                    stack += [a.fromElement for a in e.incoming]
                if e.parent.incoming:
                    stack += [a.fromElement for a in e.incoming]

    return '; '.join(sorted(direct_references))


def elem_as_bom_data(elem, other_externals_by_name, external_root):
    """
    Example data of an element:
      "bom-ref": "pkg:golang/github.com/0xAX/notificator@v0.0.0-20191016112426-3962a5ea8da1",
      "type": "library",
      "name": "github.com/0xAX/notificator",
      "version": "v0.0.0-20191016112426-3962a5ea8da1",
      "scope": "required",
      "hashes": [
        {
          "alg": "SHA-256",
          "content": "8fd1da69f6a90db3db1910e4bba7bf1d1b3a28131c287896726d7ff526f19e5e"
        }
      ],
      "licenses": [
        {
          "license": {
            "id": "BSD-3-Clause",
            "url": "https://spdx.org/licenses/BSD-3-Clause.html"
          }
        }
      ],
      "purl": "pkg:golang/github.com/0xAX/notificator@v0.0.0-20191016112426-3962a5ea8da1",
      "externalReferences": [
        {
          "url": "https://github.com/0xAX/notificator",
          "type": "vcs"
        }
      ]

    :param elem: element
    :param other_externals_by_name: dict of external elements by name
    :param external_root:
    :return:
    """
    licenses = bom_licenses(elem)
    output = []

    # Check for some legacy cases that were previosly the convention.
    if ';' in elem.attrs.get('version', '') or ';' in elem.attrs.get('versions', ''):
        raise Exception(
            f'Multiple versions associated to a single element {elem.getPath()}, cannot continue'
        )  # Multiple versions exist, as merged element (legacy way in sgraph, won't

    if valid_for_bom(elem):
        v = extract_version(elem)
        if v is None:
            v = ''
        ref = bom_ref(elem, v)

        custom_properties = [{'name': 'sourceCodeReferences',
                             'value': produce_source_code_references(elem, external_root)}]
        component = {
            'name': clean_name(elem.name),
            'version': v,
            'bom-ref': ref,
            'purl': ref,
            'type': 'library',
            'licenses': licenses,
            'scope': 'required',
            'properties': custom_properties,
            'description': ''
        }
        output.append(component)
    else:
        if elem.incoming:
            dep_summary = defaultdict(int)
            for association in elem.incoming:
                dep_summary[(file_extension(association.fromElement), association.deptype)] += 1
            if len(other_externals_by_name[clean_name(elem.name)]) > 1:
                other_excluding_parent = list(
                    filter(lambda x: x != elem.parent,
                           other_externals_by_name[clean_name(elem.name)]))
                if len(other_excluding_parent) > 1:
                    sys.stderr.write(f'Processing {elem.getPath()} Other similarly named exists  : \n')
                    for e in other_excluding_parent:
                        sys.stderr.write('  - ' + e.getPath() + '\n')

    return output


def contains_incoming_ea_from_elems(e, elem_patterns):
    for association in e.incoming:
        for pat in elem_patterns:
            if pat in association.fromElement.name:
                return True


def combine_elems(elem, other_externals_by_name):
    if not valid_for_bom(elem):
        dep_summary = defaultdict(int)
        pkg_deps = defaultdict(int)
        for association in elem.incoming:
            if association.deptype != 'new' and association.deptype != 'inherits':
                pkg_deps[(file_extension(association.fromElement), association.deptype)] += 1
            dep_summary[(file_extension(association.fromElement), association.deptype)] += 1

        if len(other_externals_by_name[clean_name(elem.name)]) > 1:
            other_excluding_parent = list(
                filter(lambda x: x != elem.parent, other_externals_by_name[clean_name(elem.name)]))
            if len(other_excluding_parent) > 1:
                sys.stderr.write('Other similarly named exists     : ')

                all_n = other_excluding_parent
                for e in other_excluding_parent:
                    sys.stderr.write('  - ' + e.getPath() + ' ')
                    dep_summary_1 = defaultdict(int)
                    for association in e.incoming:
                        dep_summary_1[(file_extension(
                            association.fromElement), association.deptype)] += 1
                    sys.stderr.write('     * ' + str(dict(dep_summary_1)) + ' ')
                    for d in dep_summary_1:
                        e.attrs.setdefault('user_exts', set()).add(d[0])

                while len(all_n) > 1:
                    under_ext = None
                    better_place = None
                    for e in all_n:
                        if e.parent.name == 'External':
                            under_ext = e
                        else:
                            if better_place is not None and len(e.getPath()) > len(
                                    better_place.getPath()):
                                better_place = e
                            elif better_place is None:
                                better_place = e
                    if under_ext is None and better_place:
                        for n in all_n:
                            if n != better_place and n.parent == better_place.parent:
                                under_ext = n
                    if under_ext and better_place:
                        if better_place.parent.name == 'PIP' and contains_incoming_ea_from_elems(
                                under_ext, ['Dockerfile', '.py']):
                            print('MERGING:'
                                  '  ' + better_place.getPath() + ' another elem ' +
                                  under_ext.getPath())
                            better_place.merge(under_ext)
                            all_n.remove(under_ext)
                        else:
                            print(better_place.getPath())
                            break
                    else:
                        break


def analyze_3rdparty(external_root, sbom):
    stack = list(external_root.children)
    other_externals_by_name: dict[str, list[SElement]] = {}
    while stack:
        elem = stack.pop(0)
        other_externals_by_name.setdefault(clean_name(elem.name), []).append(elem)
        stack += elem.children
    """
    stack = list(external_elem.children)
    while stack:
        elem = stack.pop(0)
        combine_elems(elem, other_externals_by_name)
        stack += elem.children
    """

    stack = list(external_root.children)
    while stack:
        elem = stack.pop(0)
        for bom_component in elem_as_bom_data(elem, other_externals_by_name, external_root):
            sbom.components.append(bom_component)
        stack += elem.children


class SBOM:

    BASIC_INFO = {
        'bomFormat': 'CycloneDX',
        'specVersion': '1.6',
        'serialNumber': '<REPLACED LATER>',  # TODO what?
        'version': 1,
        'metadata': {
            'timestamp': '<REPLACED LATER>',
            'tools': [{
                'vendor': 'Softagram',
                'name': 'Softagram Analyzer',
                'version': '3.0'
            }]
        }
    }

    def __init__(self):
        self.metadata_component = {}
        self.components = []

    def as_cyclonedx_json(self):
        data = SBOM.BASIC_INFO

        # RFC 3339 format
        data['metadata']['timestamp'] = datetime.now().isoformat() + 'Z'

        data['metadata']['component'] = self.metadata_component
        data['components'] = self.components

        # RFC-4122: ^urn:uuid:[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$
        data['serialNumber'] = f'urn:uuid:{uuid.uuid4()}'
        return data


def analyze_component_section(elem, sbom):
    """
    ],
    "component": {
      "bom-ref": "pkg:golang/github.com/ProtonMail/proton-bridge@v1.6.3",
      "type": "application",
      "name": "github.com/ProtonMail/proton-bridge",
      "version": "v1.6.3",
      "purl": "pkg:golang/github.com/ProtonMail/proton-bridge@v1.6.3",
      "externalReferences": [
        {
          "url": "https://github.com/ProtonMail/proton-bridge",
          "type": "vcs"
        }
      ]
    }
    :param elem:
    :param sbom:
    :return:
    """
    c = {
        'bom-ref': elem.getPath(),
        'type': 'application',
        'name': elem.name,
        'version': '',
        'purl': '',
        'externalReferences': []
    }
    for repo in elem.children:
        if 'type' in repo.attrs:
            if 'repo_url' in repo.attrs:
                c['externalReferences'].append({'url': repo.attrs['repo_url'], 'type': 'vcs'})
            else:
                # HACK
                c['externalReferences'].append({
                    'url': f'https://UNKNOWN-REPOSITORY_LOCATION/{repo.name}',
                    'type': 'vcs'
                })
    sbom.metadata_component = c


def generate_from_sgraph(sgraph: SGraph):
    """
    :return:
    """
    sbom = SBOM()
    for elem in sgraph.rootNode.children:
        for repo_or_ext in elem.children:
            if repo_or_ext.name == 'External' and repo_or_ext.getType() not in {'dir', 'repo'}:
                analyze_3rdparty(repo_or_ext, sbom)
        analyze_component_section(elem, sbom)
    return sbom.as_cyclonedx_json()


if __name__ == '__main__':
    g = SGraph.parse_xml_or_zipped_xml(sys.argv[1])
    sbom = generate_from_sgraph(g)
    with open(sys.argv[2], 'w') as f:
        json.dump(sbom, f, indent=4)
