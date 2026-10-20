"""Acquisition des poids GraXpert par cache existant ou mécanisme officiel.

La distribution amont nécessite GraXpert pour accéder à son catalogue S3. Cet
adaptateur ne lit ni ne reproduit ses identifiants internes. Le modèle 3.0.2 est
épinglé avec l’empreinte observée dans le cache Siril et vérifiée par inférence.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import logging
import os
from pathlib import Path
from shutil import copyfile, which
import subprocess
import sys
from tempfile import NamedTemporaryFile, TemporaryDirectory
from typing import TypedDict

import numpy as np
from astropy.io import fits

from lib.parameterized_component import ParameterizedComponent

DEFAULT_MODEL_DIR = Path(__file__).resolve().parents[1] / "tmp/models/graxpert"
DEFAULT_MODEL_VERSION = "3.0.2"
MANIFEST_PATH = Path(__file__).with_name("graxpert_models.json")
DEFAULT_GRAXPERT_PATH = (
    "/Applications/GraXpert.app/Contents/MacOS/GraXpert"
    if sys.platform == "darwin"
    else "GraXpert-linux"
)


def native_data_root() -> Path:
    """Dossier de données de l’application GraXpert native selon le système."""
    if sys.platform == "darwin":
        return Path.home() / "Library/Application Support/GraXpert"
    data_home = os.environ.get("XDG_DATA_HOME", str(Path.home() / ".local/share"))
    return Path(data_home) / "GraXpert"


class GraXpertModelEntry(TypedDict):
    """Empreinte épinglée et provenance d’un modèle pris en charge."""

    size: int
    sha256: str
    provenance: str
    reference: str
    license: str


class GraXpertModels(ParameterizedComponent):
    """Installe atomiquement les poids, sans modifier le cache Siril existant."""

    parameter_prefixes = ("graxpert_",)

    def __init__(self, args: argparse.Namespace | None = None) -> None:
        """Résout version/dossier ; aucun téléchargement avant ensure_model."""
        self.args = self._get_args(args)
        self.directory = (
            Path(getattr(self.args, "graxpert_model_dir", DEFAULT_MODEL_DIR))
            .expanduser()
            .resolve()
        )
        self.version = (
            getattr(self.args, "graxpert_model_version", None) or DEFAULT_MODEL_VERSION
        )
        entries: dict[str, GraXpertModelEntry] = json.loads(
            MANIFEST_PATH.read_text(encoding="utf-8")
        )
        if self.version not in entries:
            raise ValueError(f"Version GraXpert non prise en charge : {self.version}")
        self.entry = entries[self.version]

    @classmethod
    def add_arguments(cls, parser: argparse.ArgumentParser) -> None:
        """Déclare un emplacement ignoré par Git et une version reproductible."""
        if any(action.dest == "graxpert_model_dir" for action in parser._actions):
            return
        parser.add_argument(
            "--graxpert-path",
            default=DEFAULT_GRAXPERT_PATH,
            help="Exécutable utilisé uniquement pour télécharger les poids absents",
        )
        parser.add_argument(
            "--graxpert-model-dir", type=Path, default=DEFAULT_MODEL_DIR
        )
        parser.add_argument("--graxpert-model-version", default=DEFAULT_MODEL_VERSION)

    @staticmethod
    def checksum(path: Path) -> str:
        """Calcule SHA256 par blocs, sans charger les poids en mémoire."""
        digest = hashlib.sha256()
        with path.open("rb") as stream:
            for block in iter(lambda: stream.read(1024 * 1024), b""):
                digest.update(block)
        return digest.hexdigest()

    def _valid(self, path: Path) -> bool:
        """Vérifie taille et empreinte attendues avant chargement ou installation."""
        return (
            path.is_file()
            and path.stat().st_size == self.entry["size"]
            and self.checksum(path) == self.entry["sha256"]
        )

    def _local_sources(self) -> tuple[Path, ...]:
        """Recherche les caches GraXpert natif et Siril Flatpak sans les modifier."""
        roots = (
            native_data_root(),
            Path.home() / ".var/app/org.siril.Siril/data/GraXpert",
        )
        return tuple(
            root / "denoise-ai-models" / self.version / "model.onnx" for root in roots
        )

    def find_local_model(self) -> Path | None:
        """Retourne le premier poids local vérifié, sans copie ni téléchargement.

        Le cache du projet précède les caches GraXpert/Siril. Les fichiers
        absents, corrompus ou inaccessibles sont ignorés. Aucun dossier n’est
        créé ; cette lecture permet de décider de l’activation automatique.
        """
        destination = self.directory / self.version / "model.onnx"
        for candidate in (destination, *self._local_sources()):
            try:
                if self._valid(candidate):
                    return candidate
            except OSError:
                logging.debug(
                    "Poids GraXpert inaccessible : %s", candidate, exc_info=True
                )
        return None

    def _install(self, source: Path, destination: Path) -> Path:
        """Copie vérifiée puis remplacement atomique ; protège un cache précédent."""
        temporary = None
        try:
            with NamedTemporaryFile(
                dir=destination.parent, suffix=".part", delete=False
            ) as stream:
                temporary = Path(stream.name)
            copyfile(source, temporary)
            if not self._valid(temporary):
                raise ValueError("Empreinte du poids GraXpert reçu incorrecte")
            os.replace(temporary, destination)
            return destination
        finally:
            if temporary is not None:
                temporary.unlink(missing_ok=True)

    def ensure_model(self) -> Path:
        """Réutilise, importe ou télécharge la version attendue, puis vérifie son SHA.

        Le CLI GraXpert est utilisé uniquement pour acquérir un poids absent,
        sur un FITS synthétique jetable. XDG_DATA_HOME isole ce téléchargement.
        Un échec ne remplace aucun poids existant et les temporaires sont nettoyés.
        """
        destination = self.directory / self.version / "model.onnx"
        local_model = self.find_local_model()
        if local_model == destination:
            return destination
        destination.parent.mkdir(parents=True, exist_ok=True)
        if local_model is not None:
            logging.info(
                "Import du poids GraXpert %s depuis %s", self.version, local_model
            )
            return self._install(local_model, destination)
        executable = which(getattr(self.args, "graxpert_path", DEFAULT_GRAXPERT_PATH))
        if executable is None:
            raise RuntimeError(
                "Poids GraXpert absent : le téléchargement officiel exige "
                "GraXpert (--graxpert-path), utilisé uniquement pour acquérir les poids"
            )
        logging.info("Téléchargement officiel du poids GraXpert %s", self.version)
        with TemporaryDirectory(dir=self.directory, prefix="download-") as directory:
            work = Path(directory)
            image = work / "download.fits"
            # Image non constante : évite la division par MAD zéro dans le CLI.
            data = (
                np.random.default_rng(17)
                .normal(0.1, 0.001, (256, 256))
                .astype("float32")
            )
            fits.writeto(image, data)
            env = os.environ.copy()
            env["XDG_DATA_HOME"] = str(work / "data")
            env["XDG_CONFIG_HOME"] = str(work / "config")
            env["XDG_CACHE_HOME"] = str(work / "cache")
            (work / "config/GraXpert").mkdir(parents=True)
            command = [
                executable,
                str(image),
                "-cli",
                "-cmd",
                "denoising",
                "-ai_version",
                self.version,
                "-gpu",
                "false",
                "-batch_size",
                "1",
                "-output",
                str(work / "download-output"),
            ]
            log_path = destination.parent / "download.log"
            with log_path.open("w", encoding="utf-8") as stream:
                result = subprocess.run(
                    command,
                    env=env,
                    cwd=work,
                    stdout=stream,
                    stderr=subprocess.STDOUT,
                    timeout=600,
                )
            received = (
                work / "data/GraXpert/denoise-ai-models" / self.version / "model.onnx"
            )
            if not self._valid(received):
                raise RuntimeError(
                    f"Téléchargement GraXpert invalide (code {result.returncode}) : {log_path}"
                )
            if result.returncode:
                logging.warning(
                    "Le CLI a échoué après acquisition ; le poids reçu est néanmoins vérifié"
                )
            return self._install(received, destination)
