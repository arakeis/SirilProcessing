#!/usr/bin/env python3
"""
Identification du filtre astronomique utilisé pour des brutes de caméra couleur.

Pour chaque brute FITS CFA, non calibrée, le script résout l'astrométrie avec
Siril, mesure les couleurs des étoiles aux positions Gaia DR3, les compare aux
couleurs simulées à partir de leurs spectres XP pour chaque filtre de la base
SPCC de Siril, puis écrit un rapport JSON : classement des filtres, famille
retenue et cohérence avec le mot-clé FILTER.

Usage:
    python filterAnalyze.py <brute.fits> [<brute.fits> ...] [options]

Exemples:
    python filterAnalyze.py IC_5070_Light_017.fits
    python filterAnalyze.py lights/*.fits --output-dir rapports --filter-max-stars 50
    python filterAnalyze.py lights/*.fits --combine
"""

from __future__ import annotations

import argparse
import logging
import os
import sys
from collections import defaultdict
from pathlib import Path

from astropy.io import fits

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from lib.config import Config
from lib.filter_analysis import FilterAnalyzer
from lib.logging_utils import setup_logging
from lib.siril_utils import Siril


def report_path(input_file: Path, output_dir: str | None) -> Path:
    """Chemin du rapport ``<brute>_filterAnalyze.json`` dans le dossier choisi."""
    folder = Path(output_dir).resolve() if output_dir else input_file.parent
    return folder / f"{input_file.stem}_filterAnalyze.json"


def series_key(input_file: Path) -> tuple:
    """Clé de série d'une brute : objet, filtre, pose et caméra de l'en-tête."""
    header = fits.getheader(input_file)
    return tuple(str(header.get(key, "")).strip() for key in ("OBJECT", "FILTER", "EXPTIME", "INSTRUME"))


def group_series(input_files: list[Path]) -> list[list[Path]]:
    """Regroupe les brutes par série, dans l'ordre de première apparition."""
    series: dict[tuple, list[Path]] = defaultdict(list)
    for input_file in input_files:
        series[series_key(input_file)].append(input_file)
    return list(series.values())


def series_report_path(series: list[Path], output_dir: str | None) -> Path:
    """Chemin du rapport ``<première brute>_series_filterAnalyze.json``."""
    single = report_path(series[0], output_dir)
    return single.with_name(f"{series[0].stem}_series_filterAnalyze.json")


def summary_line(label: str, report: dict) -> str:
    """Ligne de synthèse : statut, famille, étoiles et trois premiers filtres."""
    decision = report["decision"]
    top = ", ".join(f"{item['name']} {item['score']:.2f}" for item in decision["top3"])
    return f"{label}: {decision['status']} — famille {decision['family']} — {report['stars']['used']} étoiles — {top}"


def main() -> int:
    """Analyse chaque brute et affiche sa décision.

    Avec ``--combine``, les brutes d'une même série sont analysées ensemble.
    Retourne 0 si toutes les brutes ou séries ont été analysées, 1 si au moins
    une a échoué et 130 après une interruption.
    """
    config = Config.from_command_line()
    parser = argparse.ArgumentParser(
        description="Identification du filtre d'acquisition de brutes couleur (OSC)",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument("input_files", nargs="+", help="Brutes FITS CFA non calibrées")
    parser.add_argument("-o", "--output-dir", dest="filter_output_dir", default=None,
                        help="Dossier des rapports (défaut : dossier de chaque brute)")
    parser.add_argument("-c", "--combine", dest="filter_combine", action="store_true",
                        help="Combiner les brutes d'une même série (OBJECT, FILTER, EXPTIME, INSTRUME)")
    parser.add_argument("-l", "--log-level", dest="log_level",
                        choices=["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"], default="INFO")
    config.register(Siril, parser)
    config.add_arguments(parser)
    config.register(FilterAnalyzer, parser)
    args = config.parse_args(parser)
    setup_logging(args.log_level)
    if not config.save_requested(args):
        return 1
    config.bind_parameters(args)

    failures = 0
    analyzer = FilterAnalyzer()
    files = []
    for name in args.input_files:
        input_file = Path(name).resolve()
        if input_file.is_file():
            files.append(input_file)
        else:
            failures += 1
            logging.error("Fichier introuvable: %s", input_file)
    if args.filter_combine:
        try:
            batches = [(series, f"série {series[0].name} ({len(series)} brutes)") for series in group_series(files)]
        except Exception as error:
            logging.error("Lecture des en-têtes : %s", error)
            return 1
    else:
        batches = [([input_file], input_file.name) for input_file in files]
    for series, label in batches:
        try:
            if args.filter_combine:
                report = analyzer.post_process_series(series, series_report_path(series, args.filter_output_dir))
            else:
                report = analyzer.post_process(series[0], report_path(series[0], args.filter_output_dir))
            print(summary_line(label, report))
        except KeyboardInterrupt:
            logging.warning("Traitement interrompu par l'utilisateur")
            return 130
        except Exception as error:
            failures += 1
            logging.error("%s : %s", label, error, exc_info=args.log_level == "DEBUG")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
