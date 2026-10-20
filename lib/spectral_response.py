"""Courbes spectrales des filtres, capteurs et de l'atmosphère pour l'analyse des filtres.

Les courbes de capteurs et de filtres large bande viennent de la base SPCC de
Siril (``siril-spcc-database``, GPLv3), lue depuis l'installation de Siril sans
copie dans le dépôt. Cette base n'inclut volontairement pas les filtres à bande
étroite ni les bi-bandes : comme Siril, ce module les synthétise à partir du
centre et de la largeur à mi-hauteur de chaque bande.

Toutes les courbes sont rééchantillonnées sur une grille commune en nanomètres
et exprimées en transmission (ou réponse relative) comprise entre 0 et 1. En
dehors de l'intervalle mesuré, la réponse est nulle : une courbe SPCC tronquée
à 700 nm ne transmet donc rien au-delà.

Exemple
-------
>>> database = SpccDatabase()  # doctest: +SKIP
>>> sensor = database.osc_sensor("Sony IMX294")  # doctest: +SKIP
>>> l_pro = database.osc_filter("Optolong L-Pro")  # doctest: +SKIP
>>> l_extreme = narrowband_filter("Optolong L-eXtreme", L_EXTREME_BANDS)
"""

from __future__ import annotations

import json
import os
import sys
from dataclasses import dataclass
from pathlib import Path

import numpy as np

# Grille commune : 300-1100 nm couvre les capteurs CMOS et les courbes SPCC ;
# un pas de 0,5 nm échantillonne une bande de 3 nm sur au moins six points.
WAVELENGTH_MIN_NM = 300.0
WAVELENGTH_MAX_NM = 1100.0
WAVELENGTH_STEP_NM = 0.5
WAVELENGTH_GRID_NM = np.arange(
    WAVELENGTH_MIN_NM, WAVELENGTH_MAX_NM + WAVELENGTH_STEP_NM / 2, WAVELENGTH_STEP_NM
)

OSC_CHANNELS = ("RED", "GREEN", "BLUE")
# Unités rencontrées dans la base SPCC (les filtres d'APN sont en angströms).
WAVELENGTH_UNITS_TO_NM = {"nm": 1.0, "angstrom": 0.1}

# Ordre de la super-gaussienne des bandes synthétisées : flancs raides et
# sommet plat, proches d'un filtre interférentiel, sans discontinuité.
NARROWBAND_ORDER = 8

# Optolong L-eXtreme : Hα 656,3 nm et OIII 500,7 nm, 7 nm de largeur à
# mi-hauteur chacune (données fabricant). Transmission maximale supposée de
# 90 % : elle ne change pas les rapports de couleur, absorbés par les échelles.
L_EXTREME_BANDS = ((500.7, 7.0, 0.9), (656.3, 7.0, 0.9))

# Extinction atmosphérique au niveau de la mer, en magnitudes par masse d'air.
# Rayleigh : 0,0088 * λ[µm]^-4,15 (0,105 mag à 550 nm). Aérosols : 0,08 mag à
# 550 nm, en λ^-1,3 ; valeur typique d'un site de plaine, à ajuster par site.
RAYLEIGH_COEFFICIENT_MAG = 0.0088
RAYLEIGH_EXPONENT = 4.15
AEROSOL_EXTINCTION_550_MAG = 0.08
AEROSOL_EXPONENT = 1.3
REFERENCE_WAVELENGTH_NM = 550.0


@dataclass(frozen=True)
class SpectralCurve:
    """Courbe de transmission ou de réponse relative sur la grille commune.

    Attributes
    ----------
    name : str
        Nom lisible, tel qu'il figure dans la base SPCC ou fourni à la synthèse.
    kind : str
        Type SPCC (``OSC_SENSOR``, ``OSC_FILTER``, ``OSC_LPF``...) ou
        ``NARROWBAND`` pour une courbe synthétisée.
    channel : str | None
        Canal du capteur (``RED``, ``GREEN``, ``BLUE``) ou ``None`` pour un filtre.
    values : numpy.ndarray
        Réponse entre 0 et 1 sur ``WAVELENGTH_GRID_NM``.
    quality : int | None
        ``dataQualityMarker`` SPCC (1 à 5), ``None`` pour une courbe synthétisée.
    source : str
        Provenance déclarée des données.
    """

    name: str
    kind: str
    channel: str | None
    values: np.ndarray
    quality: int | None = None
    source: str = ""

    @classmethod
    def from_samples(
        cls,
        name: str,
        kind: str,
        wavelength_nm: np.ndarray,
        response: np.ndarray,
        *,
        channel: str | None = None,
        quality: int | None = None,
        source: str = "",
    ) -> SpectralCurve:
        """Rééchantillonne des mesures sur la grille commune.

        Parameters
        ----------
        wavelength_nm, response : numpy.ndarray
            Mesures de même longueur, déjà normalisées entre 0 et 1. Les
            longueurs d'onde dupliquées gardent leur première valeur.

        Raises
        ------
        ValueError
            Moins de deux points, longueurs différentes, valeurs non finies,
            réponse hors de [0, 1] (tolérance de 1 %) ou nulle partout.
        """
        wavelength_nm = np.asarray(wavelength_nm, dtype=float)
        response = np.asarray(response, dtype=float)
        if wavelength_nm.shape != response.shape or wavelength_nm.ndim != 1:
            raise ValueError(f"Courbe {name} : longueurs d'onde et valeurs incohérentes")
        if wavelength_nm.size < 2:
            raise ValueError(f"Courbe {name} : au moins deux points sont nécessaires")
        if not (np.isfinite(wavelength_nm).all() and np.isfinite(response).all()):
            raise ValueError(f"Courbe {name} : valeurs non finies")
        if response.min() < -0.01 or response.max() > 1.01:
            raise ValueError(f"Courbe {name} : réponse hors de [0, 1]")
        order = np.argsort(wavelength_nm, kind="stable")
        wavelength_nm, response = wavelength_nm[order], response[order]
        wavelength_nm, unique = np.unique(wavelength_nm, return_index=True)
        response = np.clip(response[unique], 0.0, 1.0)
        values = np.interp(WAVELENGTH_GRID_NM, wavelength_nm, response, left=0.0, right=0.0)
        if not values.any():
            raise ValueError(f"Courbe {name} : aucune réponse sur {WAVELENGTH_MIN_NM:g}-{WAVELENGTH_MAX_NM:g} nm")
        return cls(name, kind, channel, values, quality, source)


def narrowband_filter(
    name: str, bands: tuple[tuple[float, float, float], ...]
) -> SpectralCurve:
    """Synthétise un filtre à une ou plusieurs bandes étroites.

    Chaque bande est une super-gaussienne d'ordre ``NARROWBAND_ORDER`` dont la
    largeur à mi-hauteur vaut exactement ``fwhm_nm``.

    Parameters
    ----------
    name : str
        Nom du filtre.
    bands : tuple[tuple[float, float, float], ...]
        ``(centre_nm, fwhm_nm, transmission_max)`` pour chaque bande.

    Returns
    -------
    SpectralCurve
        Somme des bandes, bornée à 1.

    Raises
    ------
    ValueError
        Aucune bande, centre hors de la grille, largeur nulle ou négative,
        transmission hors de ]0, 1].
    """
    if not bands:
        raise ValueError(f"Filtre {name} : au moins une bande est nécessaire")
    values = np.zeros_like(WAVELENGTH_GRID_NM)
    for center, fwhm, peak in bands:
        if not WAVELENGTH_MIN_NM < center < WAVELENGTH_MAX_NM:
            raise ValueError(f"Filtre {name} : centre {center} nm hors de la grille")
        if fwhm <= 0 or not 0 < peak <= 1:
            raise ValueError(f"Filtre {name} : largeur ou transmission invalide")
        # exp(-ln2 * |2x/FWHM|^n) vaut 1/2 à x = ±FWHM/2 quel que soit n.
        distance = np.abs(2 * (WAVELENGTH_GRID_NM - center) / fwhm)
        values += peak * np.exp(-np.log(2) * distance**NARROWBAND_ORDER)
    return SpectralCurve(name, "NARROWBAND", None, np.minimum(values, 1.0))


def atmospheric_transmission(
    airmass: float, aerosol_extinction_550_mag: float = AEROSOL_EXTINCTION_550_MAG
) -> np.ndarray:
    """Transmission atmosphérique sur la grille commune (Rayleigh et aérosols).

    Parameters
    ----------
    airmass : float
        Masse d'air, au moins 1 (zénith). L'absorption de l'ozone (≈0,02 mag
        dans la bande de Chappuis) et les bandes moléculaires sont négligées.
    aerosol_extinction_550_mag : float
        Extinction des aérosols à 550 nm, en magnitudes par masse d'air.

    Returns
    -------
    numpy.ndarray
        Transmission entre 0 et 1, plus faible dans le bleu.

    Raises
    ------
    ValueError
        Masse d'air inférieure à 1 ou non finie, extinction négative.
    """
    if not np.isfinite(airmass) or airmass < 1:
        raise ValueError(f"Masse d'air invalide : {airmass}")
    if aerosol_extinction_550_mag < 0:
        raise ValueError("Extinction des aérosols négative")
    microns = WAVELENGTH_GRID_NM / 1000
    extinction = RAYLEIGH_COEFFICIENT_MAG * microns**-RAYLEIGH_EXPONENT + (
        aerosol_extinction_550_mag
        * (WAVELENGTH_GRID_NM / REFERENCE_WAVELENGTH_NM) ** -AEROSOL_EXPONENT
    )
    return 10 ** (-0.4 * extinction * airmass)


def default_spcc_roots() -> tuple[Path, ...]:
    """Emplacements usuels de la base SPCC téléchargée par Siril.

    Seul l'emplacement macOS a été vérifié sur une installation réelle ; ceux de
    Linux natif et Flatpak suivent le dossier de données utilisateur de Siril.
    """
    home = Path.home()
    if sys.platform == "darwin":
        return (home / "Library/Application Support/org.siril.Siril/siril-spcc-database",)
    data_home = Path(os.environ.get("XDG_DATA_HOME", home / ".local/share"))
    return (
        data_home / "siril/siril-spcc-database",
        home / ".var/app/org.siril.Siril/data/siril/siril-spcc-database",
    )


class SpccDatabase:
    """Accès en lecture seule aux courbes de la base SPCC de Siril.

    Parameters
    ----------
    root : pathlib.Path | str | None
        Dossier ``siril-spcc-database`` ; par défaut, le premier emplacement
        existant parmi :func:`default_spcc_roots`.

    Raises
    ------
    FileNotFoundError
        Aucune base trouvée : la télécharger depuis Siril (préférences SPCC)
        ou indiquer son dossier.
    """

    def __init__(self, root: Path | str | None = None) -> None:
        """Résout le dossier de la base sans lire les courbes."""
        candidates = (Path(root).expanduser(),) if root is not None else default_spcc_roots()
        for candidate in candidates:
            if (candidate / "osc_filters").is_dir():
                self.root = candidate
                break
        else:
            raise FileNotFoundError(
                "Base SPCC de Siril introuvable : " + ", ".join(map(str, candidates))
            )

    def _entries(self, folder: str) -> list[dict]:
        """Lit toutes les entrées JSON d'un dossier de la base, triées par fichier."""
        entries = []
        for path in sorted((self.root / folder).glob("*.json")):
            with path.open(encoding="utf-8") as stream:
                content = json.load(stream)
            for entry in content if isinstance(content, list) else [content]:
                entries.append(dict(entry, _path=str(path)))
        return entries

    @staticmethod
    def _curve(entry: dict) -> SpectralCurve:
        """Convertit une entrée SPCC (réponse en fraction ou en pourcentage)."""
        values = entry["values"]
        scale = float(values.get("range", 1) or 1)
        units = entry["wavelength"].get("units", "nm")
        if units not in WAVELENGTH_UNITS_TO_NM:
            raise ValueError(f"Unités {units} non prises en charge dans {entry['_path']}")
        return SpectralCurve.from_samples(
            entry["name"],
            entry["type"],
            np.asarray(entry["wavelength"]["value"], dtype=float)
            * WAVELENGTH_UNITS_TO_NM[units],
            np.asarray(values["value"], dtype=float) / scale,
            channel=entry.get("channel"),
            quality=entry.get("dataQualityMarker"),
            source=entry.get("dataSource", ""),
        )

    def osc_filter_names(self) -> list[str]:
        """Noms des filtres pour capteurs couleur (dont ``OSC_LPF`` des APN)."""
        return [entry["name"] for entry in self._entries("osc_filters")]

    def osc_filter(self, name: str) -> SpectralCurve:
        """Retourne un filtre OSC par son nom exact.

        Raises
        ------
        KeyError
            Nom absent de ``osc_filters``.
        """
        for entry in self._entries("osc_filters"):
            if entry["name"] == name:
                return self._curve(entry)
        raise KeyError(f"Filtre OSC absent de la base SPCC : {name}")

    def osc_sensor(self, model: str) -> dict[str, SpectralCurve]:
        """Retourne les trois courbes R, G, B d'un capteur couleur.

        Parameters
        ----------
        model : str
            Champ ``model`` de la base, par exemple ``"Sony IMX294"``.

        Raises
        ------
        KeyError
            Modèle absent ou canal R, G ou B manquant.
        """
        curves = {
            entry["channel"]: self._curve(entry)
            for entry in self._entries("osc_sensors")
            if entry.get("model") == model and entry.get("channel") in OSC_CHANNELS
        }
        missing = [channel for channel in OSC_CHANNELS if channel not in curves]
        if missing:
            raise KeyError(f"Capteur {model} incomplet ou absent : {missing}")
        return curves
