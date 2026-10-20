"""Comparaison exhaustive des chaînes, avec cache par entrée effective."""

from __future__ import annotations

import argparse
from copy import copy
import hashlib
from importlib.metadata import PackageNotFoundError, version
import json
import logging
import os
from pathlib import Path
from shutil import copyfile, which
import sys
import time

from lib.logging_utils import log_section
from lib.processor import processor
from lib.restoration import RestorationComparisonProcessor
from lib.restoration_quality import QualityReference
from lib.type_defs import JSONReport
from lib.postprocess_paths import reset_work_dir
from lib.restoration_summary import RestorationSummary


class RestorationChainProcessor(processor):
    """Compare identité, moteurs seuls et associations ; ordre inverse explicite.

    Le cache est limité à cet appel. Chaque étape passe ses propres contrôles ;
    tous les finalistes sont réévalués sur la référence commune, jamais par somme
    de scores locaux. Les appels GPU restent séquentiels.
    """

    parameter_prefixes = RestorationComparisonProcessor.parameter_prefixes
    parameter_dependencies = frozenset(
        {"enable_clarity", "enable_graxpert", "enable_denoise", "enable_deconvolution"}
    )

    @classmethod
    def parameter_children(cls) -> tuple[type[processor], ...]:
        """Déclare les orchestrateurs enfants avant leurs moteurs tardifs."""
        from lib.denoising import NoiseReductionProcessor
        from lib.deconvolution import DeconvolutionProcessor

        return (NoiseReductionProcessor, DeconvolutionProcessor)

    @classmethod
    def get_prefix(cls) -> str:
        """Identifie l’étape fusionnée de restauration."""
        return "restoration"

    @classmethod
    def add_arguments(cls, parser: argparse.ArgumentParser) -> None:
        """Expose les options des enfants sans les redéclarer dans une séquence."""
        from lib.denoising import NoiseReductionProcessor
        from lib.deconvolution import DeconvolutionProcessor

        RestorationComparisonProcessor.add_shared_arguments(parser)
        destinations = {action.dest for action in parser._actions}
        if "denoise_modulation" not in destinations:
            NoiseReductionProcessor.add_arguments(parser)
        if "deconvolution_iterations" not in destinations:
            DeconvolutionProcessor.add_arguments(parser)

    @staticmethod
    def variants(
        args: argparse.Namespace,
    ) -> list[tuple[tuple[str, str, type[processor]], ...]]:
        """Énumère 12/18 variantes avec tous les moteurs, sans plafond arbitraire."""
        from lib.denoising import NoiseReductionProcessor
        from lib.deconvolution import DeconvolutionProcessor

        denoisers = (
            [
                ("denoise", name, cls)
                for name, cls in NoiseReductionProcessor.engines(args)
            ]
            if getattr(args, "enable_denoise", True)
            else []
        )
        sharpeners = (
            [
                ("sharpen", name, cls)
                for name, cls in DeconvolutionProcessor.engines(args)
            ]
            if getattr(args, "enable_deconvolution", True)
            else []
        )
        variants = [(), *((engine,) for engine in denoisers + sharpeners)]
        variants += [
            (denoise, sharpen) for denoise in denoisers for sharpen in sharpeners
        ]
        if getattr(args, "restoration_reverse_order", False):
            variants += [
                (sharpen, denoise) for sharpen in sharpeners for denoise in denoisers
            ]
        return variants

    @staticmethod
    def _fingerprint(path: Path) -> str:
        """Empreinte du fichier effectif, incluant pixels, orientation et WCS."""
        digest = hashlib.sha256()
        with path.open("rb") as stream:
            for block in iter(lambda: stream.read(1024 * 1024), b""):
                digest.update(block)
        return digest.hexdigest()

    def _dependency_manifest(self, args: argparse.Namespace) -> JSONReport:
        """Identifie exécutables, code et modèles présents pour le cache de cet appel.

        Les fichiers sont hachés une seule fois avant calcul. Les modèles Clarity
        téléchargés ensuite sont identifiés dans leurs audits d’inférence. Ce
        cache n’est pas réutilisé entre lancements ou versions différentes.
        """
        from lib.cosmic_clarity.models import DEFAULT_MODEL_DIR
        from lib.siril_utils import default_siril_path
        from lib.graxpert_models import (
            DEFAULT_GRAXPERT_PATH,
            DEFAULT_MODEL_DIR as GRAXPERT_MODEL_DIR,
            MANIFEST_PATH as GRAXPERT_MANIFEST,
            native_data_root,
        )

        files = {}
        for name in (
            getattr(args, "siril_path", default_siril_path()),
            getattr(args, "graxpert_path", DEFAULT_GRAXPERT_PATH),
            "flatpak",
        ):
            executable = which(str(name))
            if executable is not None:
                files[executable] = self._fingerprint(Path(executable))
        model_dir = Path(
            getattr(args, "cosmic_model_dir", DEFAULT_MODEL_DIR)
        ).expanduser()
        for model in sorted(model_dir.glob("*.pth")):
            files[str(model.resolve())] = self._fingerprint(model)
        for model in sorted(
            (native_data_root() / "denoise-ai-models").glob("*/model.onnx")
        ):
            files[str(model.resolve())] = self._fingerprint(model)

        files[str(GRAXPERT_MANIFEST)] = self._fingerprint(GRAXPERT_MANIFEST)

        native_models = Path(
            getattr(args, "graxpert_model_dir", GRAXPERT_MODEL_DIR)
        ).expanduser()
        for model in sorted(native_models.glob("*/model.onnx")):
            files[str(model.resolve())] = self._fingerprint(model)
        for module in (
            "lib.restoration_chains",
            "lib.restoration_quality",
            "lib.restoration_summary",
            "lib.deconvolution",
            "lib.denoising",
            "lib.cosmic_clarity.processors",
            "lib.graxpert",
            "lib.graxpert_models",
            "lib.graxpert_inference",
        ):
            loaded = sys.modules.get(module)
            filename = getattr(loaded, "__file__", None)
            if filename:
                files[filename] = self._fingerprint(Path(filename))
        packages = {}
        for package in ("numpy", "torch", "onnxruntime", "onnxruntime-gpu"):
            try:
                packages[package] = version(package)
            except PackageNotFoundError:
                packages[package] = None
        return dict(
            package_versions=packages,
            files_sha256=files,
            python_version=sys.version,
            cache_scope="single_call_fixed_dependencies",
            environment={
                name: os.environ.get(name)
                for name in ("CUDA_VISIBLE_DEVICES", "OMP_NUM_THREADS", "XDG_DATA_HOME")
            },
        )

    def _final_evaluation(
        self,
        source: Path,
        candidate: Path,
        reference: QualityReference,
        work: Path,
        args: argparse.Namespace,
        operations: tuple[str, ...],
    ) -> JSONReport:
        """Contrôle final vs référence : étoiles, bruit, photométrie et structures.

        Le bandeau de contrôle final de l’appelant couvre les mesures stellaires.
        Un sous-titre INFO annonce ensuite les mesures de bruit, flux et artefacts.
        """
        from astropy.io import fits
        from lib.deconvolution import compare_star_catalogs, _quote
        from lib.deconvolution_quality import (
            artifact_metrics,
            assess_quality,
            assess_denoising,
            denoising_criteria,
        )
        from lib.restoration_quality import criterion
        from lib.siril_utils import Siril

        work.mkdir(parents=True, exist_ok=True)
        before = work.parent / "common_reference.tsv"
        after = work / "final.tsv"
        layer = getattr(args, "deconvolution_layer", None)
        if layer is None:
            layer = 1 if fits.getdata(source).ndim == 3 else 0
        lines = ["requires 1.4", f"cd {_quote(work)}", "setext fit", "set32bits"]
        images = [(candidate, after)]
        needs_reference = not before.is_file()
        staged_reference = work / "reference.tsv"
        if needs_reference:
            images.insert(0, (source, staged_reference))
        for image, catalog in images:
            lines += [
                f"load {_quote(image)}",
                "setfindstar reset",
                "setfindstar -gaussian",
                f"findstar -layer={layer} -out={catalog.name}",
                "close",
            ]
        service = Siril(
            siril_path=getattr(args, "siril_path", None),
            siril_mode=getattr(args, "siril_mode", None),
        )
        if not service.run_siril_script(
            "\n".join(lines) + "\n", str(work), "final_quality.sps"
        ):
            raise RuntimeError("Contrôle final Siril impossible")
        if needs_reference:
            copyfile(staged_reference, before)
        comparison = compare_star_catalogs(
            before,
            after,
            getattr(args, "deconvolution_match_radius", 1),
            getattr(args, "deconvolution_min_stars", 10),
            getattr(args, "deconvolution_min_match_fraction", 0.7),
            layer,
            reference_images=(source, candidate),
            quality_mode="reliable",
        )
        if comparison["status"] != "validated":
            return dict(
                status="rejected",
                rejection_reasons=[comparison["status"]],
                comparison=comparison,
                criteria=dict(
                    stars=comparison.get(
                        "criterion", criterion("UNKNOWN", comparison["status"])
                    )
                ),
            )
        log_section(
            "Restauration — Contrôle final : bruit, flux et artefacts",
            separator="-",
        )
        final_args = copy(args)
        final_args._quality_reference = reference
        artifacts = artifact_metrics(
            source, candidate, comparison["pairs"], args=final_args
        )
        if "sharpen" in operations:
            verdict = assess_quality(
                comparison,
                artifacts,
                min_gain=getattr(args, "deconvolution_min_gain", 0.02),
                max_noise=getattr(args, "deconvolution_max_noise", 1.15),
                max_rings=getattr(args, "deconvolution_max_rings", 0.1),
            )
            reasons = verdict["reasons"]
            criteria = dict(verdict["criteria"])
            criteria["stars"] = comparison.get(
                "criterion", criterion("PASS", "VALIDATED_MATCHES")
            )
            criteria["stellar_flux"] = artifacts.get(
                "stellar_flux", criterion("UNKNOWN", "NOT_MEASURED")
            )
            criteria["useful_noise_gain"] = artifacts.get(
                "noise", criterion("UNKNOWN", "NOT_MEASURED")
            )
        else:
            reasons = assess_denoising(
                comparison, artifacts, max_blur=getattr(args, "denoise_max_blur", 0.03)
            )
            criteria = denoising_criteria(
                comparison, artifacts, getattr(args, "denoise_max_blur", 0.03)
            )
        if "denoise" in operations:
            noise = artifacts["max_noise_ratio"]
            criteria["global_noise_reduction"] = criterion(
                "UNKNOWN" if noise is None else "PASS" if noise < 1 else "FAIL",
                "GLOBAL_NOISE_REDUCTION",
                value=noise,
                threshold=1,
            )
        if "denoise" in operations and (
            artifacts["max_noise_ratio"] is None or artifacts["max_noise_ratio"] >= 1
        ):
            reasons = [*reasons, "global_noise_reduction_not_demonstrated"]
        # Un score final unique : un gain n’est compté qu’une seule fois.
        score = 0.0
        if not reasons:
            mean = (
                comparison["after_fwhm_px"]["mean"]
                / comparison["before_fwhm_px"]["mean"]
            )
            median = comparison["paired_ratio"]["median"]
            gain = artifacts.get("noise", {}).get("proven_gain")
            score = 2 * (1 - mean) + 2 * (1 - median) if "sharpen" in operations else 0
            score += max(0, gain) if gain is not None else 0
            score -= 0.2 * artifacts["max_ring_fraction"]
            score -= (
                0.2 * max(0, artifacts["max_noise_ratio"] - 1)
                if artifacts["max_noise_ratio"] is not None
                else 0
            )
        return dict(
            status="rejected" if reasons else "accepted",
            comparison=comparison,
            artifacts=artifacts,
            selection_score=float(score),
            rejection_reasons=reasons,
            criteria=criteria,
        )

    def post_process(
        self,
        input_path: Path | str,
        output_path: Path | str,
        args: argparse.Namespace | None = None,
    ) -> JSONReport:
        """Évalue les variantes et garde les audits directement dans <rapport>_work.

        Les opérations et contrôles finaux y sont numérotés ; aucun niveau de
        répétition artificiel n'est créé. Le dossier est réinitialisé à chaque
        appel et une entrée qui s'y trouve est refusée avant suppression.
        Les préparations, calculs distincts, contrôles finaux et classement sont
        annoncés en INFO par des titres encadrés de tirets. Les réutilisations
        de cache sont détaillées en DEBUG, sans annoncer de nouveau calcul.
        """
        args = copy(self._get_args(args))
        if getattr(args, "quality_mode", "reliable") == "legacy":
            raise ValueError(
                "La comparaison des chaînes exige quality-mode reliable ; "
                "utiliser --no-restoration-compare-chains avec --quality-mode legacy"
            )
        source, report = Path(input_path).resolve(), Path(output_path).resolve()
        if source == report or source == report.with_suffix(".fits"):
            raise ValueError("Sorties distinctes de l’entrée requises")
        parent_work = report.parent / (report.stem + "_work")
        if source.is_relative_to(parent_work):
            raise ValueError(
                "L’entrée ne peut pas se trouver dans le dossier de travail réinitialisé"
            )
        work = reset_work_dir(report)
        log_section(
            "Restauration — Préparation de la référence et des masques", separator="-",
        )
        reference = QualityReference(source, args)
        preview = reference.save_masks(work / "common_masks.fits")
        configurations = {
            key: value for key, value in vars(args).items() if not key.startswith("_")
        }
        parameter_hash = hashlib.sha256(
            json.dumps(configurations, sort_keys=True, default=str).encode()
        ).hexdigest()
        dependencies = self._dependency_manifest(args)
        dependencies_hash = hashlib.sha256(
            json.dumps(dependencies, sort_keys=True).encode()
        ).hexdigest()
        cache, fingerprints, final_cache = {}, {source: self._fingerprint(source)}, {}
        result = dict(
            engine="chains",
            image_path=str(source),
            quality_reference=reference.audit(),
            quality_preview_path=str(preview),
            parameters_sha256=parameter_hash,
            dependencies=dependencies,
            dependencies_sha256=dependencies_hash,
            variants=[],
            operations=[],
            selected_chain=[],
            output_image=str(source),
            status="no_safe_improvement",
            selection_score=0.0,
        )
        best = 0.0
        variants = self.variants(args)
        operation_labels = {"denoise": "Débruitage", "sharpen": "Netteté"}
        engine_labels = {
            "siril": "Siril", "cosmic_clarity": "Cosmic Clarity", "graxpert": "GraXpert",
        }
        logging.info(
            "Comparaison des chaînes complètes : %d variantes ; contrôles locaux puis finaux sur %s ; ordre inverse=%s",
            len(variants),
            source,
            getattr(args, "restoration_reverse_order", False),
        )
        for index, chain in enumerate(variants):
            current, steps, rejected = source, [], None
            names = [operation + ":" + name for operation, name, _ in chain]
            description = " → ".join(
                f"{operation_labels[operation]} avec {engine_labels.get(name, name)}"
                for operation, name, _ in chain
            ) or "Image d’entrée conservée (référence)"
            logging.info(
                "Restauration — variante %d/%d : %s", index + 1, len(variants), description,
            )
            for operation, name, cls in chain:
                if current not in fingerprints:
                    fingerprints[current] = self._fingerprint(current)
                key = (
                    fingerprints[current],
                    operation,
                    cls.__module__,
                    cls.__name__,
                    parameter_hash,
                    dependencies_hash,
                )
                reused = key in cache
                if not reused:
                    log_section(
                        f"Restauration — Calcul {len(cache) + 1:02d} : "
                        f"{operation_labels[operation]} avec {engine_labels.get(name, name)}",
                        separator="-",
                    )
                    call_args = copy(args)
                    # Aucun décalage silencieux de la destination finale des variantes.
                    call_args.deconvolution_output = None
                    call_args._quality_reference = (
                        reference
                        if current == source
                        else QualityReference(current, args)
                    )
                    child_report = (
                        work / f"{len(cache) + 1:02d}_{operation}_{name}.json"
                    )
                    call_args._quality_reference.save_masks(
                        child_report.with_name(child_report.stem + "_masks.fits")
                    )
                    start = time.monotonic()
                    try:
                        entry = cls().post_process(current, child_report, call_args)
                    except (OSError, RuntimeError, ValueError, ImportError) as error:
                        entry = {}
                        if child_report.is_file():
                            try:
                                saved = json.loads(
                                    child_report.read_text(encoding="utf-8")
                                )
                                if isinstance(saved, dict):
                                    entry = saved
                            except (OSError, json.JSONDecodeError):
                                pass
                        entry.update(
                            status=(
                                "no_safe_improvement"
                                if entry.get("status") == "no_safe_improvement"
                                else "failed"
                            ),
                            error=str(error),
                            output_image=str(current),
                        )
                    entry = dict(
                        entry,
                        operation_id=len(cache) + 1,
                        report_path=str(child_report),
                        input_sha256=fingerprints[current],
                        operation=operation,
                        engine_name=name,
                        parameters_sha256=parameter_hash,
                        duration_seconds=time.monotonic() - start,
                        dependencies_sha256=dependencies_hash,
                    )
                    cache[key] = entry
                    result["operations"].append(entry)
                entry = cache[key]
                if reused:
                    logging.debug(
                        "Restauration — calcul #%d réutilisé pour la variante %d/%d",
                        entry["operation_id"], index + 1, len(variants),
                    )
                steps.append(
                    dict(
                        operation=operation,
                        engine=name,
                        status=entry["status"],
                        input_sha256=entry["input_sha256"],
                        operation_id=entry["operation_id"],
                        reused=reused,
                    )
                )
                if entry.get("status") != "accepted":
                    rejected = (
                        entry.get("rejection_reasons")
                        or entry.get("error")
                        or entry.get("availability")
                        or entry["status"]
                    )
                    break
                current = Path(entry["output_image"]).resolve()
                if not current.is_file():
                    rejected = "OUTPUT_ABSENT"
                    break
            variant = dict(
                number=index + 1, chain=names, steps=steps, output_image=str(current)
            )
            if not chain:
                variant.update(status="reference", selection_score=0.0)
            elif rejected is not None:
                variant.update(
                    status="excluded", reason=rejected, rejection_stage="local"
                )
            else:
                final_key = (
                    self._fingerprint(current),
                    tuple(sorted({op for op, _, _ in chain})),
                )
                if final_key not in final_cache:
                    log_section(
                        f"Restauration — Contrôle final de la variante "
                        f"{index + 1}/{len(variants)} : "
                        f"{description}", separator="-",
                    )
                    try:
                        final_cache[final_key] = self._final_evaluation(
                            source,
                            current,
                            reference,
                            work / f"final_{index:02d}",
                            args,
                            final_key[1],
                        )
                    except (OSError, ValueError, RuntimeError) as error:
                        final_cache[final_key] = dict(
                            status="unknown", error=str(error)
                        )
                final = final_cache[final_key]
                variant.update(final)
                if final["status"] != "accepted":
                    variant["rejection_stage"] = "final"
                if (
                    final["status"] == "accepted"
                    and final.get("selection_score", 0) > best
                ):
                    best = final["selection_score"]
                    result.update(
                        selected_chain=names,
                        output_image=str(current),
                        status="accepted",
                        selection_score=best,
                    )
            result["variants"].append(variant)
            report.write_text(
                json.dumps(result, indent=2, allow_nan=False), encoding="utf-8"
            )
        log_section(
            "Restauration — Classement et publication du résultat", separator="-",
        )
        result["operation_count"] = len(cache)
        if result["status"] == "accepted":
            destination = report.with_suffix(".fits")
            copyfile(result["output_image"], destination)
            result["output_image"] = str(destination)
        logging.info(
            "Restauration : %d chaînes, %d calculs distincts ; choix=%s",
            len(result["variants"]),
            len(cache),
            result["selected_chain"] or "image inchangée",
        )
        RestorationSummary.write(result, report, mode="chains", args=args)
        report.write_text(
            json.dumps(result, indent=2, allow_nan=False), encoding="utf-8"
        )
        return result
