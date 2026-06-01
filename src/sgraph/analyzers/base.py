"""Analysaattori-arkkitehtuurin yhteiset tyypit ja apufunktiot."""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum, auto
from pathlib import Path
from typing import TYPE_CHECKING
from collections.abc import Sequence

if TYPE_CHECKING:
    from sgraph import SGraph


class AnalysisLevel(Enum):
    """Analysoinnin tarkkuustaso."""
    PACKAGES_ONLY = auto()  # Vain paketit/hakemistot
    FILES = auto()          # + tiedostot
    CLASSES = auto()        # + luokat
    FUNCTIONS = auto()      # + funktiot/metodit
    FULL = auto()           # + attribuutit, parametrit, decoratorit


class DependencyKind(Enum):
    """Riippuvuustyypit."""
    IMPORT = "import"
    FROM_IMPORT = "from_import"
    INHERITS = "inherits"
    IMPLEMENTS = "implements"
    CALLS = "calls"
    TYPE_REF = "type_ref"


@dataclass(frozen=True, slots=True)
class SourceLocation:
    """Lähdekoodiviittaus."""
    file: Path
    line: int
    column: int = 0
    end_line: int | None = None
    end_column: int | None = None


@dataclass
class AnalyzerConfig:
    """
    Analysaattorin konfiguraatio.

    Attributes:
        root_path: Analysoitavan projektin juurihakemisto
        level: Analysoinnin tarkkuustaso
        include_patterns: Glob-patternit sisällytettäville tiedostoille
        exclude_patterns: Glob-patternit ohitettaville tiedostoille/hakemistoille
        follow_external_imports: Seurataanko ulkoisia riippuvuuksia
        include_stdlib: Sisällytetäänkö standardikirjaston moduulit
    """
    root_path: Path
    level: AnalysisLevel = AnalysisLevel.FUNCTIONS
    include_patterns: Sequence[str] = ("**/*.py",)
    exclude_patterns: Sequence[str] = (
        "**/__pycache__/**",
        "**/.*",
        "**/venv/**",
        "**/.venv/**",
        "**/env/**",
        "**/node_modules/**",
        "**/*.egg-info/**",
        "**/build/**",
        "**/dist/**",
    )
    follow_external_imports: bool = False
    include_stdlib: bool = False

    def __post_init__(self):
        # Muunna string Pathiksi
        if isinstance(self.root_path, str):
            object.__setattr__(self, 'root_path', Path(self.root_path))


@dataclass
class AnalysisError:
    """Yksittäinen virhe analysoinnissa."""
    file: Path
    message: str
    line: int | None = None
    exception: Exception | None = None

    def __str__(self) -> str:
        loc = f":{self.line}" if self.line else ""
        return f"{self.file}{loc}: {self.message}"


@dataclass
class AnalysisResult:
    """
    Analyysin tulos.

    Attributes:
        graph: Tuotettu SGraph-malli
        config: Käytetty konfiguraatio
        errors: Lista virheistä analysoinnin aikana
        stats: Tilastot (analysoidut tiedostot, elementit jne.)
    """
    graph: "SGraph"
    config: AnalyzerConfig
    errors: list[AnalysisError] = field(default_factory=list)
    stats: dict[str, int] = field(default_factory=dict)

    @property
    def success(self) -> bool:
        """Onnistuiko analyysi (vähintään yksi elementti)."""
        return self.graph.rootNode.getNodeCount() > 0

    @property
    def file_count(self) -> int:
        """Analysoitujen tiedostojen määrä."""
        return self.stats.get("files_analyzed", 0)

    @property
    def error_count(self) -> int:
        """Virheiden määrä."""
        return len(self.errors)

    def summary(self) -> str:
        """Palauta yhteenveto analyysistä."""
        lines = [
            f"Files analyzed: {self.file_count}",
            f"Packages: {self.stats.get('packages', 0)}",
            f"Modules: {self.stats.get('modules', 0)}",
            f"Classes: {self.stats.get('classes', 0)}",
            f"Functions: {self.stats.get('functions', 0)}",
            f"Dependencies: {self.stats.get('dependencies', 0)}",
            f"Errors: {self.error_count}",
        ]
        return "\n".join(lines)
