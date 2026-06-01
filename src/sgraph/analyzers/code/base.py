"""Koodianalyysien yhteiset rakenteet."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Iterator
import fnmatch


@dataclass(frozen=True, slots=True)
class SourceFile:
    """
    Lähdetiedoston metatiedot.

    Attributes:
        path: Absoluuttinen polku tiedostoon
        relative_path: Suhteellinen polku juurihakemistosta
        content: Tiedoston sisältö (ladataan erikseen)
    """
    path: Path
    relative_path: Path
    content: str | None = None

    @property
    def module_path(self) -> str:
        """
        Muunna tiedostopolku Python-moduulipoluksi.

        Esim: src/sgraph/analyzers/__init__.py -> src.sgraph.analyzers
        """
        parts = list(self.relative_path.with_suffix('').parts)
        if parts and parts[-1] == '__init__':
            parts = parts[:-1]
        return '.'.join(parts)

    @property
    def is_package_init(self) -> bool:
        """Onko tiedosto paketin __init__.py."""
        return self.relative_path.name == '__init__.py'


def discover_source_files(
    root: Path,
    include_patterns: tuple[str, ...],
    exclude_patterns: tuple[str, ...],
) -> Iterator[SourceFile]:
    """
    Etsi lähdetiedostot hakemistosta.

    Args:
        root: Juurihakemisto
        include_patterns: Glob-patternit sisällytettäville tiedostoille
        exclude_patterns: Glob-patternit ohitettaville

    Yields:
        SourceFile objekteja löydetyille tiedostoille
    """
    root = root.resolve()

    def is_excluded(path: Path) -> bool:
        rel_path = path.relative_to(root)
        rel_str = str(rel_path)
        rel_parts = rel_path.parts

        for pat in exclude_patterns:
            # Tarkista onko pattern yksinkertainen hakemistonimi (esim. "__pycache__")
            # tai muotoa **/name/** tai **/name/*
            clean_pat = pat.strip("*").strip("/")
            if not clean_pat:
                continue

            # Jos pattern on "**/__pycache__/**", tarkista onko "__pycache__" polussa
            if pat.startswith("**/") and (pat.endswith("/**") or pat.endswith("/*")):
                dir_name = clean_pat.rstrip("/*")
                if dir_name in rel_parts:
                    return True

            # Yksinkertainen fnmatch ilman ** tukea
            if fnmatch.fnmatch(rel_str, pat):
                return True

        return False

    for pattern in include_patterns:
        for file_path in root.glob(pattern):
            if file_path.is_file() and not is_excluded(file_path):
                yield SourceFile(
                    path=file_path,
                    relative_path=file_path.relative_to(root),
                )


def read_source_file(source: SourceFile, encoding: str = 'utf-8') -> SourceFile:
    """
    Lue tiedoston sisältö SourceFile-objektiin.

    Args:
        source: SourceFile josta puuttuu sisältö
        encoding: Merkistökoodaus (oletus: utf-8)

    Returns:
        Uusi SourceFile jossa content täytetty
    """
    try:
        content = source.path.read_text(encoding=encoding)
    except UnicodeDecodeError:
        # Fallback latin-1:een
        content = source.path.read_text(encoding='latin-1')
    return SourceFile(
        path=source.path,
        relative_path=source.relative_path,
        content=content
    )
