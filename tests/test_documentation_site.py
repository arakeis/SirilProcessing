"""Contrôles du site MkDocs et des exports, sans navigateur ni dépendances Siril."""

import base64
import importlib.util
import json
from pathlib import Path
import sys
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

SCRIPT = Path(__file__).resolve().parents[1] / "bin/build_documentation.py"
spec = importlib.util.spec_from_file_location("documentation_builder", SCRIPT)
builder = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = builder
with patch("sys.path", [str(SCRIPT.parent), *sys.path]):
    spec.loader.exec_module(builder)


class DocumentationSiteTests(unittest.TestCase):
    """Vérifie les liens autonomes et la protection des sources."""

    def test_navigation_groups_scripts_and_does_not_repeat_option_chapters(self) -> None:
        """Site et exports partagent l’ordre, les groupes et les liens vers les options."""
        with TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            sources = [Path(path) for path in (
                "AGENTS.md", "README.md", "docs/README.md",
                "docs/sample/OPTIONS.md", "docs/sample/README.md",
            )]
            for path in sources:
                (root / path).parent.mkdir(parents=True, exist_ok=True)
                (root / path).write_text("# Page\n", encoding="utf-8")
            navigation = [
                {"Accueil": "README.md"},
                {"2. Scripts <outils>": [{"2.1. Exemple": [
                    {"Manuel": "docs/sample/README.md"},
                    {"Options": "docs/sample/OPTIONS.md"},
                    {"Raccourci des options": "docs/sample/OPTIONS.md"},
                ]}]},
            ]
            (root / "mkdocs.yml").write_text(
                "site_name: Test\nnav: " + json.dumps(navigation), encoding="utf-8",
            )
            document = builder.DocumentationBuilder(root, root / "out")
            ordered, tree = document._navigation(sources)
            self.assertEqual(ordered[:3], [
                Path("README.md"), Path("docs/sample/README.md"),
                Path("docs/sample/OPTIONS.md"),
            ])
            self.assertEqual(len(ordered), len(set(ordered)))
            self.assertEqual(tree[-1].label, "Annexes")
            chapters = {root / path: f"chapter-{i}" for i, path in enumerate(ordered)}
            contents = document._contents(tree, chapters)
            self.assertIn("<strong>2. Scripts &lt;outils&gt;</strong><ul>", contents)
            self.assertIn("<strong>2.1. Exemple</strong><ul>", contents)
            self.assertEqual(contents.count('href="#chapter-2"'), 2)

    def test_navigation_rejects_missing_or_external_source(self) -> None:
        """Un lien hors des sources ne disparaît pas silencieusement des exports."""
        with TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            (root / "docs").mkdir()
            (root / "README.md").write_text("# Projet\n")
            for target, message in (
                ("docs/missing.md", "Page absente"),
                ("../outside.md", "Page absente"),
                ("https://example.org/doc.md", "Page absente"),
                ("README.md#section", "page sans ancre"),
            ):
                with self.subTest(target=target):
                    (root / "mkdocs.yml").write_text(
                        "site_name: Test\nnav: " + json.dumps([{"Page": target}]),
                    )
                    document = builder.DocumentationBuilder(root, root / "out")
                    with self.assertRaisesRegex(ValueError, message):
                        document._navigation([Path("README.md")])

    def test_navigation_without_configuration_keeps_source_order(self) -> None:
        """Le constructeur reste utilisable sur un petit arbre sans configuration."""
        with TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            sources = [Path("second.md"), Path("first.md")]
            for path in sources:
                (root / path).write_text("# " + path.stem + "\n")
            document = builder.DocumentationBuilder(root, root / "out")
            ordered, tree = document._navigation(sources)
            self.assertEqual(ordered, sources)
            self.assertEqual([section.source for section in tree], sources)

    def test_project_navigation_targets_and_anchors_exist(self) -> None:
        """Les accès directs aux manuels et options restent valides après numérotation."""
        root = SCRIPT.parents[1]
        document = builder.DocumentationBuilder(root, root / "tmp/nav-test-output")
        sources = builder.renderer.discover_markdown_files(root, root / "out")
        _, tree = document._navigation(sources)

        def check(sections: tuple[builder.DocumentationSection, ...]) -> None:
            """Parcourt aussi les liens à ancre conservés pour les anciens accès."""
            for section in sections:
                if section.source is not None:
                    self.assertTrue((root / section.source).is_file(), section.source)
                check(section.children)

        check(tree)
        for relative, fragment in (
            ("lightProcess/GUIDE.md", "options-par-étape"),
            ("postProcess/README.md", "configuration-et-mémorisation"),
            ("solarEclipseGif/GUIDE.md", "parametres"),
            ("kstarsAnalyze/README.md", "options-de-ligne-de-commande"),
            ("guideLogAnalyze/README.md", "options-de-ligne-de-commande"),
            ("generate_docs_html/README.md", "options-du-constructeur"),
        ):
            with self.subTest(page=relative):
                source = Path("docs/scripts") / relative
                body, _ = builder.renderer.render_markdown_document(
                    (root / source).read_text(encoding="utf-8"), source,
                )
                self.assertIn(f'id="{fragment}"', body)
                self.assertIn("OPTIONS.html", body)

    def test_metadata_links_survive_github_pages_archiving(self) -> None:
        """Les références .github ne dépendent pas d’un dossier exclu par Pages."""
        with TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            (root / ".github").mkdir()
            (root / ".github/instructions.md").write_text("# Consignes\n")
            (root / ".copilot").mkdir()
            (root / ".copilot/config.json").write_text("{}")
            (root / "AGENTS.md").write_text(
                "[Consignes](.github/instructions.md)\n"
                "[Configuration](.copilot/config.json)\n"
                "[Source](https://github.com/example/.github/file.md)\n"
            )
            builder.DocumentationBuilder._stage_metadata(root)
            self.assertFalse((root / ".github").exists())
            self.assertTrue((root / "github_meta/instructions.md").is_file())
            self.assertTrue((root / "copilot_meta/config.json").is_file())
            result = (root / "AGENTS.md").read_text()
            self.assertIn("(github_meta/instructions.md)", result)
            self.assertIn("(copilot_meta/config.json)", result)
            self.assertIn("https://github.com/example/.github/file.md", result)

    def test_chapter_links_and_duplicate_ids_are_namespaced(self) -> None:
        """Les mêmes titres dans deux chapitres gardent des ancres distinctes."""
        with TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            first, second = root / "README.md", root / "docs/README.md"
            chapters = {first: "chapter-0", second: "chapter-1"}
            parser = builder.SingleFileLinks(root, first, chapters)
            parser.feed(
                '<h2 id="intro">Titre</h2><a href="#intro">Ici</a>'
                '<a href="docs/README.html#intro">Autre</a>'
            )
            result = "".join(parser.parts)
            self.assertIn('id="chapter-0-intro"', result)
            self.assertIn('href="#chapter-0-intro"', result)
            self.assertIn('href="#chapter-1-intro"', result)

    def test_sources_are_embedded_but_models_and_external_files_are_not(self) -> None:
        """Le monofichier inclut ses références textuelles et exclut les poids."""
        with TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            document = root / "README.md"
            source = root / "example.py"
            source.write_text("VALUE = 1\n")
            (root / "weights.onnx").write_bytes(b"model")
            parser = builder.SingleFileLinks(root, document, {document: "chapter-0"})
            parser.feed(
                '<a href="example.py">Code</a><a href="weights.onnx">Poids</a>'
                '<a href="https://example.org/guide">Externe</a>'
            )
            result = "".join(parser.parts)
            self.assertIn(base64.b64encode(source.read_bytes()).decode("ascii"), result)
            self.assertIn('href="weights.onnx"', result)
            self.assertIn('download="example.py"', result)
            self.assertIn('href="https://example.org/guide"', result)
            self.assertNotIn(base64.b64encode(b"model").decode("ascii"), result)

    def test_output_cannot_replace_sources_or_build_cache(self) -> None:
        """Une configuration dangereuse est refusée avant toute suppression."""
        with TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            for relative in (".", "docs", "docs/generated", "lib", "tmp/documentation"):
                with self.subTest(output=relative):
                    with self.assertRaises(ValueError):
                        builder.DocumentationBuilder(root, root / relative)
            self.assertEqual(
                builder.DocumentationBuilder(root, root / "out").output, root / "out"
            )

    def test_generated_directories_do_not_become_documentation_sources(self) -> None:
        """Les caches et sites précédents ne polluent pas la génération suivante."""
        with TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            for relative in (
                "README.md",
                "docs/guide.md",
                "tmp/build/copy.md",
                "out/copy.md",
                "node_modules/copy.md",
            ):
                path = root / relative
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text("# Document\n")
            self.assertEqual(
                builder.renderer.discover_markdown_files(root, root / "out"),
                [Path("README.md"), Path("docs/guide.md")],
            )


if __name__ == "__main__":
    unittest.main()
