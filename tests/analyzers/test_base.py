"""Testit analyzers/base.py -moduulille."""
import pytest
from pathlib import Path

from sgraph.analyzers.base import (
    AnalysisLevel,
    AnalyzerConfig,
    AnalysisError,
    AnalysisResult,
    DependencyKind,
    SourceLocation,
)
from sgraph import SGraph, SElement


class TestAnalysisLevel:
    """AnalysisLevel enum testit."""

    def test_level_ordering(self):
        """Tasot ovat oikeassa järjestyksessä."""
        assert AnalysisLevel.PACKAGES_ONLY.value < AnalysisLevel.FILES.value
        assert AnalysisLevel.FILES.value < AnalysisLevel.CLASSES.value
        assert AnalysisLevel.CLASSES.value < AnalysisLevel.FUNCTIONS.value
        assert AnalysisLevel.FUNCTIONS.value < AnalysisLevel.FULL.value


class TestAnalyzerConfig:
    """AnalyzerConfig testit."""

    def test_string_path_converted(self):
        """String-polku muunnetaan Path-objektiksi."""
        config = AnalyzerConfig(root_path="./src")
        assert isinstance(config.root_path, Path)
        assert config.root_path == Path("./src")

    def test_default_values(self):
        """Oletusarvot ovat järkevät."""
        config = AnalyzerConfig(root_path=Path("."))
        assert config.level == AnalysisLevel.FUNCTIONS
        assert "**/*.py" in config.include_patterns
        assert "**/__pycache__/**" in config.exclude_patterns
        assert config.follow_external_imports is False

    def test_custom_values(self):
        """Mukautetut arvot toimivat."""
        config = AnalyzerConfig(
            root_path=Path("/test"),
            level=AnalysisLevel.CLASSES,
            include_patterns=("*.py",),
            exclude_patterns=("**/test/**",),
            follow_external_imports=True,
        )
        assert config.level == AnalysisLevel.CLASSES
        assert config.include_patterns == ("*.py",)
        assert config.follow_external_imports is True


class TestAnalysisError:
    """AnalysisError testit."""

    def test_str_representation(self):
        """String-esitys on selkeä."""
        error = AnalysisError(
            file=Path("/test/file.py"),
            message="Test error",
            line=42,
        )
        assert "/test/file.py:42: Test error" == str(error)

    def test_str_without_line(self):
        """String ilman rivinumeroa."""
        error = AnalysisError(
            file=Path("/test/file.py"),
            message="Test error",
        )
        assert "/test/file.py: Test error" == str(error)


class TestAnalysisResult:
    """AnalysisResult testit."""

    def test_success_with_elements(self):
        """Success on True kun on elementtejä."""
        graph = SGraph(SElement(None, ''))
        SElement(graph.rootNode, "test")
        result = AnalysisResult(
            graph=graph,
            config=AnalyzerConfig(root_path=Path(".")),
        )
        assert result.success is True

    def test_file_count(self):
        """file_count palauttaa oikean arvon."""
        graph = SGraph(SElement(None, ''))
        result = AnalysisResult(
            graph=graph,
            config=AnalyzerConfig(root_path=Path(".")),
            stats={"files_analyzed": 10},
        )
        assert result.file_count == 10

    def test_error_count(self):
        """error_count palauttaa virheiden määrän."""
        graph = SGraph(SElement(None, ''))
        result = AnalysisResult(
            graph=graph,
            config=AnalyzerConfig(root_path=Path(".")),
            errors=[
                AnalysisError(file=Path("a.py"), message="Error 1"),
                AnalysisError(file=Path("b.py"), message="Error 2"),
            ],
        )
        assert result.error_count == 2

    def test_summary(self):
        """summary() palauttaa yhteenvedon."""
        graph = SGraph(SElement(None, ''))
        result = AnalysisResult(
            graph=graph,
            config=AnalyzerConfig(root_path=Path(".")),
            stats={
                "files_analyzed": 5,
                "packages": 1,
                "modules": 4,
                "classes": 3,
                "functions": 10,
                "dependencies": 2,
            },
        )
        summary = result.summary()
        assert "Files analyzed: 5" in summary
        assert "Classes: 3" in summary
        assert "Functions: 10" in summary


class TestSourceLocation:
    """SourceLocation testit."""

    def test_frozen_dataclass(self):
        """SourceLocation on muuttumaton."""
        loc = SourceLocation(file=Path("test.py"), line=10)
        with pytest.raises(AttributeError):
            loc.line = 20  # type: ignore

    def test_optional_fields(self):
        """Valinnaiset kentät toimivat."""
        loc = SourceLocation(
            file=Path("test.py"),
            line=10,
            column=5,
            end_line=15,
            end_column=10,
        )
        assert loc.column == 5
        assert loc.end_line == 15


class TestDependencyKind:
    """DependencyKind testit."""

    def test_values(self):
        """Enum-arvot ovat oikein."""
        assert DependencyKind.IMPORT.value == "import"
        assert DependencyKind.FROM_IMPORT.value == "from_import"
        assert DependencyKind.INHERITS.value == "inherits"
