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
"""

from __future__ import annotations

import argparse
import logging
import os
import sys
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from lib.config import Config
from lib.filter_analysis import FilterAnalyzer
from lib.logging_utils import setup_logging
from lib.siril_utils import Siril


def report_path(input_file: Path, output_dir: str | None) -> Path:
    """Chemin du rapport ``<brute>_filterAnalyze.json`` dans le dossier choisi."""
    folder = Path(output_dir).resolve() if output_dir else input_file.parent
    return folder / f"{input_file.stem}_filterAnalyze.json"


def main() -> int:
    """Analyse chaque brute et affiche sa décision.

    Retourne 0 si toutes les brutes ont été analysées, 1 si au moins une a
    échoué et 130 après une interruption.
    """
    config = Config.from_command_line()
    parser = argparse.ArgumentParser(
        description="Identification du filtre d'acquisition de brutes couleur (OSC)",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument("input_files", nargs="+", help="Brutes FITS CFA non calibrées")
    parser.add_argument("-o", "--output-dir", dest="filter_output_dir", default=None,
                        help="Dossier des rapports (défaut : dossier de chaque brute)")
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
    for name in args.input_files:
        input_file = Path(name).resolve()
        try:
            if not input_file.is_file():
                raise FileNotFoundError(f"Fichier introuvable: {input_file}")
            report = analyzer.post_process(input_file, report_path(input_file, args.filter_output_dir))
            decision = report["decision"]
            top = ", ".join(f"{item['name']} {item['score']:.2f}" for item in decision["top3"])
            print(f"{input_file.name}: {decision['status']} — famille {decision['family']}"
                  f" — {report['stars']['used']} étoiles — {top}")
        except KeyboardInterrupt:
            logging.warning("Traitement interrompu par l'utilisateur")
            return 130
        except Exception as error:
            failures += 1
            logging.error("%s : %s", input_file.name, error, exc_info=args.log_level == "DEBUG")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
