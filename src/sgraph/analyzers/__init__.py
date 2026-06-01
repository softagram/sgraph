"""
Analysaattorit eri lähteiden mallintamiseen SGraph-rakenteiksi.

Tämä moduuli tarjoaa työkalut lähdekoodin, tietokantojen ja muiden
rakenteiden analysointiin hierarkkisiksi graafimalleiksi.

Käyttöesimerkit:

    # Yksinkertainen Python-analyysi
    >>> from sgraph.analyzers import analyze_python
    >>> result = analyze_python("./src")
    >>> result.graph.to_xml("model.xml")

    # Tarkempi kontrolli
    >>> from sgraph.analyzers import AnalyzerConfig, AnalysisLevel
    >>> from sgraph.analyzers.code.python import analyze_python_project
    >>> config = AnalyzerConfig(
    ...     root_path="./src",
    ...     level=AnalysisLevel.FULL,
    ...     exclude_patterns=("**/test/**",),
    ... )
    >>> result = analyze_python_project(config)
"""
from sgraph.analyzers.base import (
    AnalyzerConfig,
    AnalysisResult,
    AnalysisError,
    AnalysisLevel,
    DependencyKind,
    SourceLocation,
)


# Lazy import to avoid circular dependencies during package init
def analyze_python(
    path: str,
    level: "AnalysisLevel" = AnalysisLevel.FUNCTIONS,
    **kwargs,
) -> "AnalysisResult":
    """
    Analysoi Python-projekti ja tuota SGraph-malli.

    Args:
        path: Projektin juurihakemisto
        level: Analysoinnin tarkkuustaso
        **kwargs: Muut AnalyzerConfig-parametrit

    Returns:
        AnalysisResult sisältäen graafit, virheet ja tilastot

    Example:
        >>> result = analyze_python("./src/sgraph")
        >>> print(result.graph.rootNode.getNodeCount())
    """
    from sgraph.analyzers.code.python.python_analyzer import analyze_python as _analyze
    return _analyze(path, level, **kwargs)


__all__ = [
    # Pääfunktiot
    "analyze_python",
    # Konfiguraatio
    "AnalyzerConfig",
    "AnalysisLevel",
    # Tulokset
    "AnalysisResult",
    "AnalysisError",
    # Tyypit
    "DependencyKind",
    "SourceLocation",
]
