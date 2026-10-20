"""Séparation StarNet V2 via Siril 1.4, en domaine linéaire.

L'interface historique Siril réalise le pré-étirement MTF et sa pseudo-inverse.
Le résidu signé est recalculé après inversion, car le masque Siril peut être
un masque « unscreen » et ne constitue pas nécessairement un résidu additif.
Voir docs/scripts/postProcess/auto-ghs.md.
"""

from __future__ import annotations

import argparse
import configparser
import json
import os
import re
import sys
import time
from pathlib import Path

import numpy as np
from astropy.io import fits

from lib.processor import processor
from lib.restoration_quality import normalized_planes
from lib.siril_utils import Siril, default_siril_mode
from lib.type_defs import JSONReport


def quote_siril(value: Path | str) -> str:
    """Protège un chemin Siril et refuse les caractères d'injection de script."""
    text = str(value)
    if any(character in text for character in ('"', "\n", "\r", "\x00")):
        raise ValueError("Chemin incompatible avec un script Siril")
    return f'"{text}"'


def write_rgb(
    source: Path,
    destination: Path,
    data: np.ndarray,
    *,
    nonlinear: bool = False,
    role: str | None = None,
) -> None:
    """Écrit des plans RGB float32 en conservant extensions et métadonnées.

    Les données restent dans l'orientation native du fichier source. Les cartes
    d'échelle entières sont supprimées explicitement et les bornes recalculées.
    """
    with fits.open(source, memmap=False) as hdul:
        hdul[0].data = np.asarray(data, dtype=np.float32)
        for keyword in ("BZERO", "BSCALE", "BLANK"):
            hdul[0].header.pop(keyword, None)
        hdul[0].header["BUNIT"] = ("1", "Dimensionless normalized intensity")
        hdul[0].header["DATAMIN"] = float(np.min(data))
        hdul[0].header["DATAMAX"] = float(np.max(data))
        hdul[0].header["SPNLIN"] = (nonlinear, "Presentation stretch applied")
        if role is not None:
            hdul[0].header["SPROLE"] = (role, "AutoGHS branch role")
        hdul[0].header.add_history(
            "SirilProcessing AutoGHS: nonlinear rendering"
            if nonlinear
            else "SirilProcessing: linear StarNet separation"
        )
        hdul.writeto(destination, overwrite=False, checksum=True)


def validate_rgb(data: np.ndarray) -> None:
    """Exige trois plans RGB non vides, finis et normalisés sans écrêtage implicite."""
    if data.ndim != 3 or data.shape[0] != 3 or data.size == 0:
        raise ValueError("AutoGHS nécessite un FITS RGB linéaire à trois plans")
    if not np.isfinite(data).all():
        raise ValueError("AutoGHS refuse les pixels NaN/Inf")
    if data.min() < 0 or data.max() > 1:
        raise ValueError(
            "AutoGHS nécessite des intensités dans [0, 1], sans écrêtage implicite"
        )


def validate_linear_header(header: fits.Header) -> None:
    """Refuse les indicateurs explicites et historiques Siril de rendu déjà effectué.

    L'absence de ces marqueurs ne démontre pas la linéarité d'un fichier externe.
    Le contrat du pipeline reste nécessaire ; aucune inférence photométrique
    n'est faite à partir de la seule forme de l'histogramme.
    """
    history = header.get("HISTORY", [])
    if isinstance(history, str):
        history = [history]
    rendered = any(
        str(line).startswith(("GHS (", "GHS BP shift", "MTF (")) for line in history
    )
    if header.get("SPNLIN", False) or rendered:
        raise ValueError("AutoGHS refuse une entrée déjà non linéaire/étirée")


class StarNetSeparator(processor):
    """Adaptateur StarNet V2 historique, sans remplacement automatique du moteur.

    Une invocation produit une séparation, conserve le journal Siril et mesure
    le résidu additif signé. Toute erreur externe ou géométrique est fatale.
    """

    config_path_parameters = frozenset({"starnet_path"})

    @classmethod
    def get_prefix(cls) -> str:
        """Identifie les paramètres de séparation."""
        return "starnet"

    @classmethod
    def add_arguments(cls, parser: argparse.ArgumentParser) -> None:
        """Déclare le chemin persistant ; None autorise la lecture des préférences Siril."""
        parser.add_argument(
            "--starnet-path",
            type=cls.path_argument,
            default=None,
            help="Exécutable StarNet V2 ; sinon préférences Siril",
        )

    @staticmethod
    def path_argument(value: str) -> Path:
        """Normalise aussi les chemins avec tilde avant leur sauvegarde JSON."""
        return Path(value).expanduser().resolve()

    @staticmethod
    def preferences(
        args: argparse.Namespace,
    ) -> tuple[configparser.ConfigParser, Path | None]:
        """Lit les préférences du mode Siril choisi sans les modifier."""
        config_home = Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config"))
        if getattr(args, "siril_mode", default_siril_mode()) == "flatpak":
            directory = Path.home() / ".var/app/org.siril.Siril/config/siril"
        elif sys.platform == "darwin":
            directory = Path.home() / "Library/Application Support/org.siril.Siril/siril"
        else:
            directory = config_home / "siril"
        for name in ("config.1.4.ini", "config.ini"):
            path = directory / name
            if path.is_file():
                preferences = configparser.ConfigParser(interpolation=None)
                preferences.optionxform = str
                preferences.read(path, encoding="utf-8")
                return preferences, path
        return configparser.ConfigParser(interpolation=None), None

    @classmethod
    def resolve_executable(cls, args: argparse.Namespace) -> Path:
        """Résout CLI/JSON puis préférences Siril et vérifie le droit d'exécution.

        Le point d'entrée mémorise ce résultat avec -S, y compris lorsqu'il
        provient d'une découverte dans les préférences Siril.
        """
        preferences, _ = cls.preferences(args)
        configured = getattr(args, "starnet_path", None)
        executable = configured or preferences.get("core", "starnet_exe", fallback="")
        if not executable:
            raise ValueError("StarNet introuvable : renseigner --starnet-path")
        executable = Path(executable).expanduser().resolve()
        if not executable.is_file() or not os.access(executable, os.X_OK):
            raise ValueError(
                f"Exécutable StarNet absent ou non exécutable : {executable}"
            )
        quote_siril(executable)
        return executable

    def post_process(
        self,
        input_path: Path,
        output_path: Path,
        args: argparse.Namespace | None = None,
    ) -> JSONReport:
        """Sépare un RGB linéaire dans le sous-dossier visible du rapport.

        Parameters
        ----------
        input_path : Path
            FITS original, en unités Siril (entiers normalisés ou flottants 0..1).
        output_path : Path
            Rapport JSON dans un dossier de travail neuf appartenant à l'appelant.
        args : argparse.Namespace, optional
            Chemin StarNet et service Siril résolus par Config.

        Returns
        -------
        dict
            Chemins starless_linear/stars_linear, provenance et diagnostics.

        Raises
        ------
        ValueError
            Entrée non linéaire déclarée, CFA, pixels invalides ou chemin invalide.
        RuntimeError
            Échec Siril/StarNet ou sortie incompatible.
        """
        args = self._get_args(args)
        source, report = Path(input_path).resolve(), Path(output_path).resolve()
        if source == report:
            raise ValueError("Le rapport ne peut pas remplacer la source")
        header = fits.getheader(source)
        validate_linear_header(header)
        if header.get("BAYERPAT"):
            raise ValueError("StarNet exige une image RGB linéaire dématricée")
        if "starless" in str(header.get("FILTER", "")).lower() or header.get(
            "SPROLE"
        ) in ("STARLESS", "STARS"):
            raise ValueError("Entrée déclarée starless : séparation refusée")
        data = normalized_planes(source)
        validate_rgb(data)
        preferences, preference_path = self.preferences(args)
        executable = self.resolve_executable(args)
        report.parent.mkdir(parents=True, exist_ok=True)
        work = report.parent / f"{report.stem}_work"
        work.mkdir(exist_ok=False)
        if not preferences.has_section("core"):
            preferences.add_section("core")
        preferences.set("core", "starnet_exe", str(executable))
        preferences.set("core", "force_16bit", "false")
        # V2 utilise son modèle embarqué dans son dossier, pas un chemin V1 résiduel.
        preferences.set("core", "starnet_weights", "")
        isolated = work / "siril.ini"
        with isolated.open("w", encoding="utf-8") as stream:
            preferences.write(stream, space_around_delimiters=False)
        staged = work / "input.fits"
        starless = work / "starless_linear.fits"
        stars = work / "stars_linear.fits"
        write_rgb(source, staged, data)
        script = "\n".join(
            [
                "requires 1.4",
                f"cd {quote_siril(work)}",
                "setext fits",
                "set32bits",
                f"load {quote_siril(staged)}",
                "starnet -stretch",
                f"save {quote_siril(starless)}",
                "close",
                "",
            ]
        )
        siril = Siril(
            siril_path=getattr(args, "siril_path", None),
            siril_mode=getattr(args, "siril_mode", None),
        )
        started = time.monotonic()
        if not siril.run_siril_script(
            script, str(work), script_name="separate.sps", initfile=isolated
        ):
            raise RuntimeError(
                f"Séparation StarNet échouée ; consulter {work / 'separate.log'}"
            )
        if not starless.is_file():
            raise RuntimeError("StarNet n’a pas produit de starless linéaire")
        result = normalized_planes(starless)
        result_header = fits.getheader(starless)
        if result.shape != data.shape:
            raise RuntimeError("StarNet a modifié les dimensions RGB")
        if result_header.get("ROWORDER", "BOTTOM-UP") != header.get(
            "ROWORDER", "BOTTOM-UP"
        ):
            result = result[:, ::-1, :].copy()
        validate_rgb(result)
        # Réécrire sur le modèle original garantit WCS, extensions et orientation.
        starless.unlink()
        write_rgb(source, starless, result, role="STARLESS")
        residual = data - result
        write_rgb(source, stars, residual, role="STARS")
        reconstruction = data.astype(np.float64) - (
            result.astype(np.float64) + residual.astype(np.float64)
        )
        log = work / "separate.log"
        text = log.read_text(encoding="utf-8", errors="replace") if log.exists() else ""
        version = re.search(r"siril\s+(\d+\.\d+(?:\.\d+)?)", text, re.IGNORECASE)
        readme = executable.parent / "README.txt"
        banner = readme.read_text(errors="replace")[:256] if readme.is_file() else ""
        starnet_version = re.search(r"StarNet\+\+\s+v([\d.]+)", banner)
        report_data = {
            "status": "SUCCESS",
            "image_path": str(source),
            "output_image": str(starless),
            "starless_linear": str(starless),
            "stars_linear": str(stars),
            "executable": str(executable),
            "siril_preferences": str(preference_path) if preference_path else None,
            "siril_version": version.group(1) if version else None,
            "starnet_version": starnet_version.group(1) if starnet_version else None,
            "method": "siril-1.4-legacy-starnet-stretch",
            "prestretch": "Siril unlinked MTF + pseudoinverse; TIFF16 quantization",
            "mask": "signed linear subtraction after inverse MTF",
            "negative_fraction": float(np.mean(residual < 0)),
            "negative_minimum": float(residual.min()),
            "reconstruction_max_abs": float(np.max(abs(reconstruction))),
            "duration_seconds": time.monotonic() - started,
            "script_path": str(work / "separate.sps"),
            "log_path": str(log),
            "input_linear": True,
            "linearity_source": "pipeline contract + FITS flags",
            "shape": list(data.shape),
        }
        report.write_text(json.dumps(report_data, indent=2), encoding="utf-8")
        return report_data
