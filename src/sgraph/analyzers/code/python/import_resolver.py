"""Python import -resoluutio riippuvuuksien luomiseen."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from sgraph import SElement

from ...base import AnalyzerConfig


@dataclass(slots=True)
class ImportTarget:
    """Resolvoitu import-kohde."""
    element: SElement
    module_path: str
    is_external: bool = False


def resolve_import(
    import_info: dict[str, Any],
    from_element: SElement,
    module_registry: dict[str, SElement],
    config: AnalyzerConfig,
) -> list[ImportTarget]:
    """
    Resolvoi import-lauseke kohde-elementeiksi.

    Args:
        import_info: Import-tiedot (ast_visitor:lta)
        from_element: Elementti josta import tehdään
        module_registry: Rekisteröidyt moduulit (module_path -> SElement)
        config: Analysaattorin konfiguraatio

    Returns:
        Lista ImportTarget-objekteja (voi olla tyhjä jos ei löydy)
    """
    results: list[ImportTarget] = []
    module_name = import_info.get("module", "")
    level = import_info.get("level", 0)
    names = import_info.get("names", [])

    # Käsittele relatiiviset importit
    if level > 0:
        base_path = _resolve_relative_import_base(
            level=level,
            from_element=from_element,
        )
        if base_path is None:
            return []

        if module_name:
            # "from .subpkg import x" -> base_path.module_name
            full_module = f"{base_path}.{module_name}" if base_path else module_name
            target = _find_module(full_module, module_registry, config)
            if target:
                results.append(target)
        elif names:
            # "from . import x, y" -> resolvo jokainen nimi erikseen
            for name in names:
                full_module = f"{base_path}.{name}" if base_path else name
                target = _find_module(full_module, module_registry, config)
                if target:
                    results.append(target)
        else:
            # Pelkkä paketti-import
            target = _find_module(base_path, module_registry, config)
            if target:
                results.append(target)
    else:
        # Absoluuttinen import
        if module_name:
            target = _find_module(module_name, module_registry, config)
            if target:
                results.append(target)

    return results


def _find_module(
    module_name: str,
    module_registry: dict[str, SElement],
    config: AnalyzerConfig,
) -> ImportTarget | None:
    """Etsi moduuli rekisteristä."""
    if not module_name:
        return None

    # Tarkista suora osuma
    if module_name in module_registry:
        return ImportTarget(
            element=module_registry[module_name],
            module_path=module_name,
            is_external=False,
        )

    # Yritä löytää parent-moduuli
    parts = module_name.split(".")
    for i in range(len(parts), 0, -1):
        partial = ".".join(parts[:i])
        if partial in module_registry:
            return ImportTarget(
                element=module_registry[partial],
                module_path=module_name,
                is_external=False,
            )

    # Ulkoinen moduuli - ohitetaan jos ei seurata
    if not config.follow_external_imports:
        return None

    return None


def _resolve_relative_import_base(
    level: int,
    from_element: SElement,
) -> str | None:
    """
    Resolvoi relatiivisen importin base-polku.

    Args:
        level: Pisteiden määrä (1 = ".", 2 = "..", jne)
        from_element: Elementti josta import tehdään

    Returns:
        Base-polku (esim. "pkg" jos ollaan pkg/main.py:ssä) tai None

    Example:
        # Jos olemme pkg/sub/module.py:ssä
        # level=1 -> "pkg.sub"
        # level=2 -> "pkg"
    """
    # Kerää elementin polku juuresta
    path_parts: list[str] = []
    current = from_element
    while current is not None and current.name != '':
        path_parts.insert(0, current.name)
        current = current.parent

    # Jos tiedosto (ei __init__.py), poista tiedostonimi
    # __init__.py edustaa pakettia, muut tiedostot ovat moduuleja paketin sisällä
    if from_element.getType() == "file":
        if path_parts:
            path_parts = path_parts[:-1]

    # Siirry level-1 tasoa ylöspäin
    # level=1 (from . import x) = sama paketti
    # level=2 (from .. import x) = parent paketti
    if level > 1:
        steps_up = level - 1
        if steps_up >= len(path_parts):
            return None  # Liian monta tasoa ylös
        path_parts = path_parts[:-steps_up]

    if not path_parts:
        # Ollaan juuressa, relatiivinen import ei voi toimia
        return ""

    return ".".join(path_parts)


def get_dependency_type(import_info: dict[str, Any]) -> str:
    """Palauta riippuvuustyyppi import-tietojen perusteella."""
    if import_info.get("is_from"):
        return "from_import"
    return "import"
