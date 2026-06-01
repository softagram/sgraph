"""Python-analysaattorin integraaatiotestit."""
import pytest
from pathlib import Path
import tempfile
import os

from sgraph.analyzers import analyze_python, AnalyzerConfig, AnalysisLevel
from sgraph.analyzers.code.python import analyze_python_project


class TestAnalyzePython:
    """analyze_python() integraaatiotestit."""

    @pytest.fixture
    def sgraph_src_path(self) -> Path:
        """Sgraph-projektin src/sgraph hakemisto (dogfooding)."""
        return Path(__file__).parent.parent.parent.parent.parent / "src" / "sgraph"

    def test_analyze_sgraph_project(self, sgraph_src_path: Path):
        """Analysoi sgraph-projekti itse (dogfooding)."""
        if not sgraph_src_path.exists():
            pytest.skip("sgraph src directory not found")

        result = analyze_python(sgraph_src_path)

        assert result.success
        assert result.file_count > 10
        assert result.error_count == 0
        assert result.stats["classes"] > 0
        assert result.stats["functions"] > 0

    def test_analyze_with_different_levels(self, sgraph_src_path: Path):
        """Testaa eri tarkkuustasoja."""
        if not sgraph_src_path.exists():
            pytest.skip("sgraph src directory not found")

        results = {}
        for level in [AnalysisLevel.FILES, AnalysisLevel.CLASSES, AnalysisLevel.FUNCTIONS]:
            results[level] = analyze_python(sgraph_src_path, level=level)

        # Tarkempi taso = enemmän elementtejä
        files_count = results[AnalysisLevel.FILES].graph.rootNode.getNodeCount()
        classes_count = results[AnalysisLevel.CLASSES].graph.rootNode.getNodeCount()
        functions_count = results[AnalysisLevel.FUNCTIONS].graph.rootNode.getNodeCount()

        assert functions_count >= classes_count >= files_count

    def test_handles_syntax_errors_gracefully(self, tmp_path: Path):
        """Virheellinen syntaksi ei kaada analysaattoria."""
        bad_file = tmp_path / "bad.py"
        bad_file.write_text("def broken(:\n    pass")

        result = analyze_python(tmp_path)

        assert len(result.errors) == 1
        assert "Syntax error" in result.errors[0].message

    def test_empty_directory(self, tmp_path: Path):
        """Tyhjä hakemisto ei kaada analysaattoria."""
        result = analyze_python(tmp_path)

        assert result.file_count == 0
        assert result.error_count == 0

    def test_single_file(self, tmp_path: Path):
        """Yksittäinen tiedosto analysoidaan."""
        test_file = tmp_path / "test.py"
        test_file.write_text("""
def hello():
    pass

class MyClass:
    def method(self):
        pass
""")
        result = analyze_python(tmp_path)

        assert result.file_count == 1
        assert result.stats["functions"] == 2  # hello + method
        assert result.stats["classes"] == 1

    def test_package_with_init(self, tmp_path: Path):
        """Paketti __init__.py:llä tunnistetaan."""
        pkg = tmp_path / "mypackage"
        pkg.mkdir()
        (pkg / "__init__.py").write_text("# Package init")
        (pkg / "module.py").write_text("def func(): pass")

        result = analyze_python(tmp_path)

        assert result.stats["packages"] == 1
        assert result.stats["modules"] == 1

    def test_excludes_pycache(self, tmp_path: Path):
        """__pycache__ ohitetaan."""
        cache = tmp_path / "__pycache__"
        cache.mkdir()
        (cache / "cached.py").write_text("# Should be ignored")
        (tmp_path / "real.py").write_text("def func(): pass")

        result = analyze_python(tmp_path)

        assert result.file_count == 1

    def test_import_dependencies_created(self, tmp_path: Path):
        """Import-lauseet luovat riippuvuuksia."""
        (tmp_path / "main.py").write_text("""
from utils import helper
import other
""")
        (tmp_path / "utils.py").write_text("def helper(): pass")
        (tmp_path / "other.py").write_text("x = 1")

        result = analyze_python(tmp_path)

        # Tarkista että riippuvuuksia löytyy
        main_elem = result.graph.findElementFromPath("/main")
        assert main_elem is not None
        assert len(main_elem.outgoing) >= 1  # Ainakin utils-riippuvuus


class TestAnalyzePythonProject:
    """analyze_python_project() testit."""

    def test_custom_exclude_patterns(self, tmp_path: Path):
        """Mukautetut exclude-patternit toimivat."""
        (tmp_path / "main.py").write_text("def main(): pass")
        test_dir = tmp_path / "tests"
        test_dir.mkdir()
        (test_dir / "test_main.py").write_text("def test(): pass")

        config = AnalyzerConfig(
            root_path=tmp_path,
            exclude_patterns=("**/tests/**",),
        )
        result = analyze_python_project(config)

        assert result.file_count == 1

    def test_full_level_extracts_parameters(self, tmp_path: Path):
        """FULL-taso poimii parametrit."""
        (tmp_path / "test.py").write_text("""
def func(a, b, *args, key=None, **kwargs):
    pass
""")
        result = analyze_python(tmp_path, level=AnalysisLevel.FULL)

        # Etsi funktio
        func_elem = result.graph.findElementFromPath("/test/func")
        assert func_elem is not None
        params = func_elem.attrs.get("parameters", "")
        assert "a" in params
        assert "b" in params
        assert "*args" in params
        assert "**kwargs" in params

    def test_decorators_extracted(self, tmp_path: Path):
        """Decoratorit poimitaan FULL-tasolla."""
        (tmp_path / "test.py").write_text("""
@staticmethod
def static_func():
    pass

@property
def prop(self):
    pass
""")
        result = analyze_python(tmp_path, level=AnalysisLevel.FULL)

        static_elem = result.graph.findElementFromPath("/test/static_func")
        assert static_elem is not None
        decorators = static_elem.attrs.get("decorators", "")
        assert "staticmethod" in decorators


class TestRelativeImports:
    """Relatiivisten importtien testit."""

    def test_relative_import_same_package(self, tmp_path: Path):
        """from . import x toimii."""
        pkg = tmp_path / "pkg"
        pkg.mkdir()
        (pkg / "__init__.py").write_text("")
        (pkg / "main.py").write_text("from . import utils")
        (pkg / "utils.py").write_text("x = 1")

        result = analyze_python(tmp_path)

        main_elem = result.graph.findElementFromPath("/pkg/main")
        assert main_elem is not None
        # Tarkista riippuvuus
        deps = [ea.toElement.name for ea in main_elem.outgoing]
        assert "pkg" in deps or "utils" in deps

    def test_relative_import_parent_package(self, tmp_path: Path):
        """from .. import x toimii."""
        pkg = tmp_path / "pkg"
        sub = pkg / "sub"
        pkg.mkdir()
        sub.mkdir()
        (pkg / "__init__.py").write_text("ROOT = 1")
        (pkg / "utils.py").write_text("x = 1")
        (sub / "__init__.py").write_text("")
        (sub / "module.py").write_text("from .. import utils")

        result = analyze_python(tmp_path)

        module_elem = result.graph.findElementFromPath("/pkg/sub/module")
        assert module_elem is not None


class TestAsyncFunctions:
    """Async-funktioiden testit."""

    def test_async_function_marked(self, tmp_path: Path):
        """Async-funktiot merkitään."""
        (tmp_path / "test.py").write_text("""
async def async_func():
    pass

def sync_func():
    pass
""")
        result = analyze_python(tmp_path)

        async_elem = result.graph.findElementFromPath("/test/async_func")
        sync_elem = result.graph.findElementFromPath("/test/sync_func")

        assert async_elem is not None
        assert async_elem.attrs.get("async") == "true"
        assert sync_elem is not None
        assert sync_elem.attrs.get("async") is None
