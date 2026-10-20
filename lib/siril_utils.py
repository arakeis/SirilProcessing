#!/bin/env python3
"""Validation des exécutables Siril et exécution journalisée des scripts de traitement."""

from __future__ import annotations

import argparse
from typing import TYPE_CHECKING

from lib.type_defs import ConfigValue

if TYPE_CHECKING:
    from lib.config import Config


import logging
import os
import shutil
import signal
import subprocess
import sys
from datetime import datetime
from pathlib import Path

from lib.cpu_config import CpuConfig
from lib.parameterized_component import ParameterizedComponent

MACOS_SIRIL_CLI = "/Applications/Siril.app/Contents/MacOS/siril-cli"


def default_siril_mode() -> str:
    """Flatpak sous Linux, exécutable natif sur les autres systèmes."""
    return "flatpak" if sys.platform.startswith("linux") else "native"


def default_siril_path() -> str:
    """Exécutable Siril par défaut : `siril` sous Linux, `siril-cli` ailleurs."""
    if sys.platform.startswith("linux"):
        return "siril"
    if sys.platform == "darwin" and Path(MACOS_SIRIL_CLI).is_file():
        return MACOS_SIRIL_CLI
    return "siril-cli"


class Siril(ParameterizedComponent):
    """
    Classe pour gérer l'exécution de Siril avec validation et mémorisation des configurations.
    """

    CONFIG_DEFAULTS = {
        "siril_path": default_siril_path(),
        "siril_mode": default_siril_mode(),
    }

    @classmethod
    def add_arguments(
        cls,
        parser: argparse.ArgumentParser,
        config: Config | None = None,
        *,
        photometry_aliases: bool = False,
    ) -> None:
        """Déclare les options du service avec leurs valeurs locales."""

        def default(key: str) -> ConfigValue:
            """Résout une option Siril dans la configuration fournie ou ses défauts locaux."""
            return config.get(key) if config is not None else cls.CONFIG_DEFAULTS[key]

        path_options = ["-s", "--siril-path"]
        mode_options = ["-m", "--siril-mode"]
        if photometry_aliases:
            path_options.append("--photometry-siril-path")
            mode_options.append("--photometry-siril-mode")
        group = parser.add_argument_group("Exécution Siril")
        group.add_argument(
            *path_options,
            dest="siril_path",
            default=default("siril_path"),
            help="Exécutable Siril (en mode native/appimage ; sans effet en flatpak)",
        )
        group.add_argument(
            *mode_options,
            dest="siril_mode",
            choices=["native", "flatpak", "appimage"],
            default=default("siril_mode"),
            help="Mode d'exécution de Siril",
        )

    # Attributs de classe pour la configuration globale par défaut
    _default_siril_path = default_siril_path()
    _default_siril_mode = default_siril_mode()

    def __init__(
        self, siril_path: str | None = None, siril_mode: str | None = None
    ) -> None:
        """
        Initialise et valide Siril : constructeur > paramètres liés > défauts.

        Args:
            siril_path: Chemin explicite ; sinon paramètres liés, puis défauts globaux
            siril_mode: Mode explicite ; sinon paramètres liés, puis défauts globaux

        Raises:
            ValueError: Si la configuration n'est pas valide
        """
        bound = self._args
        self._siril_path = (
            siril_path
            if siril_path is not None
            else getattr(bound, "siril_path", self._default_siril_path)
        )
        self._siril_mode = (
            siril_mode
            if siril_mode is not None
            else getattr(bound, "siril_mode", self._default_siril_mode)
        )
        self._validated = False

        # Validation lors de l'initialisation
        if not self._validate_configuration():
            raise ValueError(
                f"Configuration Siril invalide: path='{self._siril_path}', mode='{self._siril_mode}'"
            )

    @classmethod
    def configure_defaults(
        cls, siril_path: str | None = None, siril_mode: str | None = None
    ) -> None:
        """
        Configure les valeurs par défaut pour toutes les instances Siril futures.
        Valide immédiatement la configuration.

        Args:
            siril_path: Chemin par défaut vers l'exécutable Siril
            siril_mode: Mode d'exécution par défaut ('native', 'flatpak', ou 'appimage')

        Raises:
            ValueError: Si la configuration n'est pas valide
        """
        if siril_path is not None:
            cls._default_siril_path = siril_path
        if siril_mode is not None:
            cls._default_siril_mode = siril_mode

        # Validation immédiate de la nouvelle configuration
        temp_instance = cls(
            siril_path=cls._default_siril_path,
            siril_mode=cls._default_siril_mode,
        )
        if not temp_instance._validated:
            # Restaurer les anciennes valeurs en cas d'échec
            if siril_path is not None:
                cls._default_siril_path = default_siril_path()
            if siril_mode is not None:
                cls._default_siril_mode = default_siril_mode()
            raise ValueError(
                f"Configuration Siril invalide: path='{cls._default_siril_path}', mode='{cls._default_siril_mode}'"
            )

        logging.info(
            f"Configuration Siril globale mise à jour et validée: path={cls._default_siril_path}, mode={cls._default_siril_mode}"
        )

    @classmethod
    def get_default_config(cls) -> tuple[str, str]:
        """
        Retourne la configuration par défaut actuelle.

        Returns:
            Tuple (siril_path, siril_mode)
        """
        return cls._default_siril_path, cls._default_siril_mode

    @classmethod
    def create_with_defaults(cls) -> Siril:
        """
        Crée une nouvelle instance Siril avec la configuration par défaut.

        Returns:
            Instance Siril configurée avec les valeurs par défaut
        """
        return cls(
            siril_path=cls._default_siril_path,
            siril_mode=cls._default_siril_mode,
        )

    @property
    def siril_path(self) -> str:
        """Retourne le chemin vers Siril."""
        return self._siril_path

    @siril_path.setter
    def siril_path(self, path: str) -> str:
        """Définit le chemin vers Siril et re-valide la configuration."""
        old_path = self._siril_path
        self._siril_path = path
        self._validated = False
        if not self._validate_configuration():
            # Restaurer l'ancienne valeur en cas d'échec
            self._siril_path = old_path
            self._validated = True  # L'ancienne configuration était valide
            raise ValueError(f"Chemin Siril invalide: '{path}'")

    @property
    def siril_mode(self) -> str:
        """Retourne le mode d'exécution de Siril."""
        return self._siril_mode

    @siril_mode.setter
    def siril_mode(self, mode: str) -> str:
        """Définit le mode d'exécution de Siril et re-valide la configuration."""
        old_mode = self._siril_mode
        self._siril_mode = mode
        self._validated = False
        if not self._validate_configuration():
            # Restaurer l'ancienne valeur en cas d'échec
            self._siril_mode = old_mode
            self._validated = True  # L'ancienne configuration était valide
            raise ValueError(f"Mode Siril invalide: '{mode}'")

    @property
    def is_validated(self) -> bool:
        """Retourne True si la configuration a été validée avec succès."""
        return self._validated

    def _validate_configuration(self) -> bool:
        """
        Valide la configuration Siril actuelle.

        Returns:
            True si la configuration est valide, False sinon
        """
        try:
            # Validation du mode
            valid_modes = ["native", "flatpak", "appimage"]
            if self._siril_mode not in valid_modes:
                logging.error(
                    f"Mode Siril invalide: {self._siril_mode}. Modes valides: {valid_modes}"
                )
                self._validated = False
                return False

            # Validation selon le mode
            if self._siril_mode == "flatpak":
                # Vérifier si flatpak est disponible
                result = subprocess.run(
                    ["flatpak", "--version"],
                    capture_output=True,
                    text=True,
                    check=False,
                )
                if result.returncode != 0:
                    logging.error("Flatpak n'est pas disponible sur ce système")
                    self._validated = False
                    return False

                # Vérifier si Siril est installé via flatpak
                result = subprocess.run(
                    ["flatpak", "list", "--app"],
                    capture_output=True,
                    text=True,
                    check=False,
                )
                if result.returncode != 0 or "org.siril.Siril" not in result.stdout:
                    logging.error("Siril n'est pas installé via Flatpak")
                    self._validated = False
                    return False

            elif self._siril_mode in ["native", "appimage"]:
                # Vérifier si l'exécutable existe et est accessible
                if not shutil.which(self._siril_path) and not os.path.isfile(
                    self._siril_path
                ):
                    logging.error(f"Exécutable Siril introuvable: {self._siril_path}")
                    self._validated = False
                    return False

                # Vérifier si le fichier est exécutable
                if os.path.isfile(self._siril_path) and not os.access(
                    self._siril_path, os.X_OK
                ):
                    logging.error(
                        f"Le fichier Siril n'est pas exécutable: {self._siril_path}"
                    )
                    self._validated = False
                    return False

            logging.info(
                f"Configuration Siril validée: mode={self._siril_mode}, path={self._siril_path}"
            )
            self._validated = True
            return True

        except Exception as e:
            logging.error(
                f"Erreur lors de la validation de la configuration Siril: {e}"
            )
            self._validated = False
            return False

    def run_siril_script(
        self,
        siril_script_content: str,
        working_dir: str,
        script_name: str | None = None,
        *,
        initfile: Path | None = None,
    ) -> bool:
        """
        Exécute un script Siril et conserve stdout/stderr dans le fichier .log associé.

        Args:
            siril_script_content: Contenu du script Siril à exécuter
            working_dir: Répertoire de travail pour l'exécution du script
            initfile: Préférences isolées facultatives, passées avec -i ; permet
                de configurer un outil externe sans modifier les préférences utilisateur.

        Returns:
            True si l'exécution a réussi, False sinon
        """
        # Vérifier que la configuration est valide
        if not self._validated:
            logging.error(
                "Configuration Siril non valide. Impossible d'exécuter le script."
            )
            return False

        working_path = Path(working_dir)
        working_path.mkdir(parents=True, exist_ok=True)
        if script_name:
            safe_name = "".join(
                ch if ch.isalnum() or ch in "._-" else "_" for ch in script_name
            )
            if not safe_name.endswith(".sps"):
                safe_name = f"{safe_name}.sps"
        else:
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
            safe_name = f"siril_script_{timestamp}.sps"

        script_path = working_path / safe_name
        log_path = script_path.with_suffix(".log")
        try:
            # Conserver l'en-tête « requires » avant toute commande Siril.
            lines = siril_script_content.splitlines(keepends=True)
            insertion = 0
            for line in lines:
                stripped = line.strip()
                if (
                    stripped
                    and not stripped.startswith("#")
                    and stripped.split()[0] != "requires"
                ):
                    break
                insertion += 1
            if insertion and not lines[insertion - 1].endswith("\n"):
                lines[insertion - 1] += "\n"
            lines.insert(insertion, f"setcpu {CpuConfig.get_limit()}\n")
            siril_script_content = "".join(lines)
            logging.info(
                "Exécution du script Siril %s dans %s", script_path, working_dir
            )
            with open(script_path, "w") as f:
                f.write(siril_script_content)

            logging.debug(
                "Contenu du script Siril %s :\n%s", script_path, siril_script_content
            )

            # Construction de la commande selon le mode
            if self._siril_mode == "native":
                cmd = [self._siril_path, "-s", script_path]
            elif self._siril_mode == "flatpak":
                # Batch scripts use the CLI and do not require a graphical session.
                cmd = [
                    "flatpak",
                    "run",
                    "--command=siril-cli",
                    "org.siril.Siril",
                    "-s",
                    script_path,
                ]
            elif self._siril_mode == "appimage":
                cmd = [self._siril_path, "-s", script_path]
            else:
                logging.error(f"Mode Siril inconnu: {self._siril_mode}")
                return False

            if initfile is not None:
                cmd.extend(["-i", str(Path(initfile).resolve())])
            with log_path.open("w", encoding="utf-8") as log_file:
                result = subprocess.run(
                    cmd,
                    cwd=working_dir,
                    stdout=log_file,
                    stderr=subprocess.STDOUT,
                    check=False,
                )
            if result.returncode != 0:
                logging.error(
                    f"Le script Siril a échoué avec le code d'erreur {result.returncode}."
                )
                if result.returncode < 0:
                    try:
                        name = signal.Signals(-result.returncode).name
                    except ValueError:
                        name = str(-result.returncode)
                    logging.error(
                        "Processus Siril interrompu par le signal %s (script %s).",
                        name,
                        script_path,
                    )
                    if result.returncode == -signal.SIGKILL:
                        logging.error(
                            "SIGKILL : vérifier les journaux système (OOM / pression mémoire ou arrêt externe)."
                        )
                logging.error(
                    "Sortie Siril (%s) :\n%s",
                    log_path,
                    log_path.read_text(encoding="utf-8", errors="replace"),
                )
                return False
            else:
                logging.info("Script Siril exécuté avec succès.")
                return True
        except FileNotFoundError:
            logging.error(
                f"Exécutable Siril introuvable à '{self._siril_path}'. Veuillez vérifier le chemin."
            )
            return False
        except Exception as e:
            logging.error(f"Erreur lors de l'exécution du script Siril: {e}")
            return False
