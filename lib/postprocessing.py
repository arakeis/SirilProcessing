"""Exécution complète du post-traitement commune aux deux points d’entrée.

Les paramètres des étapes, leur calcul, les diagnostics et les exports sont
identiques depuis postProcess et depuis lightProcess. Le parsing et la
sauvegarde explicite de Config restent à la charge du point d’entrée.
"""

from __future__ import annotations

import argparse
from copy import deepcopy
import json
import logging
from pathlib import Path
from shutil import copyfile

from lib.logging_utils import (
    add_session_file_logging, log_section, remove_session_file_logging,
)
from lib.postprocess import _PostProcessorSequence
from lib.processor import processor
from lib.siril_utils import default_siril_mode, default_siril_path
from lib.quality_preview import QualityMaskPreview
from lib.star_separation import StarNetSeparator
from lib.type_defs import JSONReport


class PostProcessingProcessor(processor):
    """Exécute les étapes, diagnostics et exports d’une image FITS unique.

    ``post_process(image, rapport)`` conserve le schéma historique du rapport
    sur disque (une clé par étape) et retourne une enveloppe ``processor`` avec
    ``output_image``, ``report_path`` et ``treatments``. Les chemins des produits
    dérivent du rapport, jamais du répertoire de travail de la calibration.
    Voir docs/scripts/postProcess/pipeline.md.
    """

    enabled_by_default = True
    parameter_dependencies = {"config", "log_level"}
    parameter_persistence = _PostProcessorSequence.parameter_persistence
    config_path_parameters = _PostProcessorSequence.config_path_parameters

    @classmethod
    def get_prefix(cls) -> str:
        """Identifie le traitement complet dans un pipeline de processeurs."""
        return "postprocess"

    @classmethod
    def parameter_children(cls) -> tuple[type[processor], ...]:
        """Déclare la séquence et ses moteurs pour la liaison hiérarchique."""
        return (_PostProcessorSequence,)

    @classmethod
    def add_arguments(
        cls, parser: argparse.ArgumentParser, include_activation: bool = False,
    ) -> None:
        """Déclare les mêmes paramètres scientifiques dans les deux scripts.

        include_activation ajoute uniquement dans lightProcess le choix
        persistant --postprocess/--no-postprocess, activé par défaut.
        Aucune instance de traitement n’est créée et aucun argument n’est parsé.
        """
        if include_activation:
            parser.add_argument(
                "--postprocess", action=argparse.BooleanOptionalAction,
                dest="enable_postprocess", default=cls.enabled_by_default,
                help=(
                    "Enchaîner le post-traitement du stack ou de la mosaïque "
                    "finale (activé par défaut)"
                ),
            )
        _PostProcessorSequence.add_arguments(parser)

    @staticmethod
    def prepare_config_save(args: argparse.Namespace) -> None:
        """Résout StarNet avant une sauvegarde demandée avec AutoGHS actif.

        Modifie uniquement args.starnet_path ; le script appelle ensuite
        Config.save_requested une seule fois, avant ses calculs. Les erreurs de
        découverte restent explicites. Sans -S ou sans AutoGHS, ne fait rien.
        """
        if (
            getattr(args, "save_config", False)
            and getattr(args, "enable_autoghs", True)
        ):
            args.starnet_path = StarNetSeparator.resolve_executable(args)

    @staticmethod
    def report_path_for(
        input_path: Path, output_arg: str | Path | None = None,
    ) -> Path:
        """Construit <image>_postprocess.json avec la convention du CLI autonome.

        output_arg est un répertoire ou un ancien chemin de rapport, dont seul
        le parent est utilisé. Sans argument, les produits côtoient la source.
        Cette méthode ne crée aucun fichier.
        """
        source = Path(input_path).resolve()
        if output_arg is None:
            directory = source.parent
        else:
            provided = Path(output_arg)
            directory = provided if provided.suffix == "" else provided.parent
        return directory.resolve() / f"{source.stem}_postprocess.json"

    @staticmethod
    def _final_image(results: JSONReport, fallback: Path) -> Path:
        """Résout la dernière sortie image, ou garde la source faute de sortie."""
        final_image = fallback
        for branch in results.values():
            if isinstance(branch, dict) and branch.get("output_image"):
                final_image = Path(str(branch["output_image"]))
        return final_image.resolve()

    @staticmethod
    def _log_settings(args: argparse.Namespace) -> None:
        """Consigne les réglages effectifs sans charger les moteurs de calcul."""
        logging.info(
            "Configuration: %s", getattr(args, "config", "paramètres liés"),
        )
        logging.info(
            "Siril: mode=%s, path=%s",
            getattr(args, "siril_mode", default_siril_mode()),
            getattr(args, "siril_path", default_siril_path()),
        )
        logging.info(
            "Backend: %s",
            "cosmic-clarity" if getattr(args, "enable_clarity", True) else "siril",
        )
        logging.info(
            "Politique de calcul commune : %s",
            getattr(args, "compute_backend", "auto"),
        )
        logging.info(
            "Restauration : comparaison %s ; ordre inverse=%s",
            "des chaînes complètes"
            if getattr(args, "restoration_compare_chains", True)
            else "par étapes isolées",
            getattr(args, "restoration_reverse_order", False),
        )

    def _export_results(
        self, results: JSONReport, source: Path, report: Path,
        quality_preview: Path | None,
    ) -> JSONReport:
        """Copie les exports finaux et retourne leurs chemins avec les rapports.

        La dernière image des étapes est exportée en FITS. Le JPEG n’est copié
        que si AutoGHS l’a fourni. Toute erreur est propagée ; la source n’est
        jamais modifiée et le rapport historique garde ses clés par étape.
        """
        final_path = report.with_suffix(".fits")
        final_image = self._final_image(results, source)
        if not final_image.is_file():
            raise FileNotFoundError(f"Image finale introuvable: {final_image}")
        if final_image != final_path:
            copyfile(final_image, final_path)
        logging.info("Image finale exportée: %s", final_path)
        summary: JSONReport = {
            "status": "SUCCESS", "image_path": str(source),
            "output_image": str(final_path), "report_path": str(report),
            "steps_dir": str(report.parent / report.stem), "treatments": results,
            "quality_preview_path": str(quality_preview) if quality_preview else None,
        }
        autoghs = results.get("autoghs")
        jpeg = autoghs.get("output_jpeg") if isinstance(autoghs, dict) else None
        if jpeg:
            jpeg_path = Path(str(jpeg)).resolve()
            jpeg_export = final_path.with_suffix(".jpg")
            if jpeg_path != jpeg_export:
                copyfile(jpeg_path, jpeg_export)
            summary["output_jpeg"] = str(jpeg_export)
            logging.info("Image finale JPEG exportée: %s", jpeg_export)
        return summary

    def post_process(
        self, input_path: Path, output_path: Path,
        args: argparse.Namespace | None = None,
    ) -> JSONReport:
        """Traite une image et publie ses produits avec le contrat processor.

        Parameters
        ----------
        input_path : Path
            FITS linéaire issu du stack, de la mosaïque ou fourni directement.
        output_path : Path
            Rapport JSON global ; son stem nomme le dossier d’étapes et les
            exports FITS/JPEG. Utiliser report_path_for pour les noms standards.
        args : argparse.Namespace, optional
            Surcharge ponctuelle, copiée sans modifier les paramètres mémorisés.

        Returns
        -------
        JSONReport
            Statut SUCCESS, chemins des sorties et rapports des traitements.

        Raises
        ------
        ValueError, FileNotFoundError, RuntimeError, OSError
            Entrée, traitement ou publication invalide. Les erreurs sont
            journalisées puis propagées ; aucune réussite n’est retournée.
        KeyboardInterrupt
            Propagée après libération des ressources et du journal.

        Notes
        -----
        Ne parse pas sys.argv, ne sauvegarde pas Config et ne configure pas la
        console. Le journal propre à cette image est fermé même en cas d’échec.
        La protection énergétique est gérée par le script appelant ; ce
        processeur ne demande pas de profil système ni d’inhibition de veille.
        Le début du post-traitement est annoncé par un bandeau INFO commun
        à la console et au journal, avant les réglages et les étapes.
        """
        runtime = deepcopy(self._get_args(args))
        source, report = Path(input_path).resolve(), Path(output_path).resolve()
        if report.suffix.lower() != ".json":
            raise ValueError(
                "Le chemin de sortie du post-traitement doit être un rapport JSON"
            )
        steps_dir = report.parent / report.stem
        final_path = report.with_suffix(".fits")
        log_file = steps_dir / f"00_{source.stem}_postProcess.log"
        if source in (report, final_path, log_file):
            raise ValueError(
                "Les produits du post-traitement ne peuvent pas remplacer la source"
            )
        runtime.postprocess_steps_dir = steps_dir
        level = getattr(runtime, "log_level", "INFO")
        handler = add_session_file_logging(log_file, level)
        try:
            if not source.is_file():
                raise FileNotFoundError(f"Fichier introuvable: {source}")
            log_section(f"Début du post-traitement : {source.name}")
            logging.info("Log de post-traitement: %s", log_file)
            self._log_settings(runtime)
            logging.info("Analyse de: %s", source)
            logging.info("Rapport global: %s", report)
            logging.info("Dossier des étapes: %s", steps_dir)
            logging.info("Résultat final: %s", final_path)
            sequence = _PostProcessorSequence()
            results = sequence.post_process(source, report, args=runtime)
            quality_preview = QualityMaskPreview.ensure_for_run(
                results, source, steps_dir, runtime,
            )
            gradient_preview = QualityMaskPreview.write_gradient_points(
                results, steps_dir,
            )
            report.write_text(
                json.dumps(results, indent=2, ensure_ascii=False),
                encoding="utf-8",
            )
            summary = self._export_results(
                results, source, report, quality_preview,
            )
            logging.info("Image des zones de qualité : %s", quality_preview)
            if gradient_preview:
                logging.info("Points du gradient original : %s", gradient_preview)
            for name, branch in results.items():
                logging.info("Traitement terminé: %s", name)
                if isinstance(branch, dict) and branch.get("summary_path"):
                    logging.info(
                        "Synthèse des essais %s : %s", name, branch["summary_path"],
                    )
            logging.info("Rapport sauvegardé: %s", report)
            logging.info("Post-traitements terminés")
            return summary
        except KeyboardInterrupt:
            logging.warning("Traitement interrompu par l’utilisateur")
            raise
        except Exception as error:
            logging.error("Erreur: %s", error, exc_info=level == "DEBUG")
            raise
        finally:
            remove_session_file_logging(handler)
