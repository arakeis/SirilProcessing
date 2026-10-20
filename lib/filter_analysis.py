"""Identification du filtre d'acquisition d'une brute couleur à partir de ses étoiles.

La chaîne assemble les modules de l'analyse des filtres :

1. dématriçage superpixel de la brute (:mod:`lib.cfa_superpixel`) ;
2. astrométrie Siril sur Gaia DR3 (:mod:`lib.plate_solving`) ;
3. sources du champ et photométrie RGB aux positions Gaia
   (:mod:`lib.gaia_xp`, :mod:`lib.star_photometry`), puis choix d'au plus
   ``max_stars`` étoiles réparties en couleur ;
4. spectres XP de ces étoiles, simulation des flux pour chaque filtre candidat
   et score de compatibilité (:mod:`lib.filter_model`) ;
5. décision par famille puis par filtre, et cohérence avec le mot-clé
   ``FILTER``.

Les filtres candidats sont ceux de la base SPCC de Siril, plus l'Optolong
L-eXtreme synthétisé. Chaque candidat appartient à une famille
(:data:`FILTER_FAMILIES`). La famille est retenue lorsque son meilleur score
devance celui des autres familles d'au moins ``family_margin`` ; le filtre
l'est lorsque son score devance de ``filter_margin`` le deuxième de sa
famille. Les écarts sont absolus : un score réduit proche de 1 signifie un
ajustement compatible avec le bruit, et un écart relatif entre deux scores
proches de zéro n'aurait pas de sens. Voir ``docs/scripts/filterAnalyze/README.md``.

Exemple
-------
>>> report = FilterAnalyzer().post_process(Path("light.fits"), Path("light_filterAnalyze.json"))  # doctest: +SKIP
>>> report["decision"]["family"]  # doctest: +SKIP
'light_pollution'
"""

from __future__ import annotations

import argparse
import json
import logging
import re
from collections import Counter
from pathlib import Path

import numpy as np
from astropy.io import fits
from astropy.wcs import WCS
from astropy.wcs.utils import proj_plane_pixel_scales

from lib.cfa_superpixel import superpixel_rgb
from lib.filter_model import DEFAULT_MODEL_UNCERTAINTY, score_filter, simulate_rgb
from lib.gaia_xp import fetch_xp_spectra, query_field_sources, xp_to_grid
from lib.plate_solving import plate_solve
from lib.postprocess_paths import reset_work_dir
from lib.processor import processor
from lib.siril_utils import Siril
from lib.spectral_response import (
    L_EXTREME_BANDS,
    SpccDatabase,
    SpectralCurve,
    atmospheric_transmission,
    narrowband_filter,
)
from lib.star_photometry import measure_rgb, select_colour_spread
from lib.type_defs import JSONReport

L_EXTREME_NAME = "Optolong L-eXtreme (synth.)"
DEFAULT_CACHE_DIR = Path.home() / ".cache" / "sirilprocessing" / "gaia"
DEFAULT_FAMILY_MARGIN = 0.5
DEFAULT_FILTER_MARGIN = 0.3
DEFAULT_MIN_STARS = 20
# Réserve de rayon autour du champ pour les voisins proches des bords.
FIELD_RADIUS_MARGIN = 1.02

FAMILY_LABELS = {
    "narrowband": "bandes étroites (bi-, tri- ou quadri-bande)",
    "light_pollution": "antipollution large bande",
    "uv_ir_cut": "coupure UV/IR seule (y compris filtres internes d'APN)",
    "none": "sans filtre",
    "other": "non classé",
}
FILTER_FAMILIES = {
    **dict.fromkeys((
        "Antlia Quad Band Anti-Light Pollution Filter", "Askar Colour Magic C1 (Ha/OIII)",
        "Askar Colour Magic C2 (SII_OIII)", "Dwarf Mini Dual Band", "LEVIATHAN Spectral Pro",
        "Lumicon UHC", "SIghtron Quad BP", "Svbony SV240", "ZWO Duo-Band", "ZWO Seestar LP",
        L_EXTREME_NAME,
    ), "narrowband"),
    **dict.fromkeys((
        "Antlia Triband RGB Ultra II", "Astronomik CLS-CCD", "Baader Contrast Booster",
        "Baader Neodymium Moon & Skyglow", "Baader UHC-S", "Hutech IDAS LPS-P2", "IDAS LPS P3",
        "Optolong Optolong CLS-CCD", "Optolong L-Pro", "Optolong L-QEF", "SVBONY UHC", "SvBONY CLS",
        "SvBONY SV260", "Vaonis CLS",
    ), "light_pollution"),
    **dict.fromkeys((
        "Astronomik Astronomik L-1 UV/IR Block", "Astronomik Astronomik L-2 UV/IR Block",
        "Astronomik Astronomik L-3 UV/IR Block", "Baader BCF astromod LPF", "Baader Fringe Killer",
        "Baader UV/IR Cut", "Canon EOS 350D blocking filter", "Dwarf Mini Astro",
        "SVBONY SV231 Color Correction Filter", "UV/IR Block", "Nikon D100 LPF", "Nikon D3000 LPF",
        "Nikon D3100 LPF", "Nikon D40 LPF", "Nikon D40x LPF", "Nikon D50 LPF", "Nikon D60 LPF",
        "Nikon D70 LPF", "Nikon D80 LPF", "Nikon D90 LPF",
    ), "uv_ir_cut"),
    **dict.fromkeys(("Full spectrum (no filter)", "No filter"), "none"),
}
# Capteur SPCC déduit de INSTRUME (comparaison sans casse ni séparateurs).
SENSOR_BY_INSTRUMENT = {"asi294mc": "Sony IMX294"}


def _normalized(text: str) -> str:
    """Minuscules sans espaces ni ponctuation, pour comparer des noms de matériel."""
    return re.sub(r"[^a-z0-9]", "", str(text).lower())


def filter_family(name: str) -> str:
    """Famille d'un filtre candidat, ``other`` s'il n'est pas répertorié."""
    return FILTER_FAMILIES.get(name, "other")


def sensor_for_instrument(instrument: str) -> str | None:
    """Capteur SPCC correspondant à ``INSTRUME``, ou ``None`` s'il est inconnu."""
    key = _normalized(instrument)
    return next((sensor for model, sensor in SENSOR_BY_INSTRUMENT.items() if model in key), None)


def header_filter_candidates(header_filter: str, names: list[str]) -> list[str]:
    """Candidats dont le nom contient la valeur ``FILTER`` de l'en-tête.

    Les valeurs de moins de trois caractères utiles (``L``, ``R``…) ne
    permettent aucune correspondance fiable : la liste est alors vide.
    """
    key = _normalized(header_filter)
    if len(key) < 3:
        return []
    return [name for name in names if key in _normalized(name)]


def decide(scores: list[tuple[str, float]], family_margin: float, filter_margin: float) -> JSONReport:
    """Retient une famille puis, si possible, un filtre.

    Parameters
    ----------
    scores : list[tuple[str, float]]
        Couples (filtre, score réduit), dans n'importe quel ordre.
    family_margin, filter_margin : float
        Écart minimal entre le meilleur score et celui de la famille suivante,
        puis celui du filtre suivant de la même famille.

    Returns
    -------
    dict
        ``status`` (``filter``, ``family`` ou ``undetermined``), ``family``,
        ``family_margin``, ``filter``, ``filter_margin``, ``top3`` et
        ``ambiguous_with`` (filtres de la famille à moins de ``filter_margin``).
    """
    ranked = sorted(scores, key=lambda item: item[1])
    best_by_family: dict[str, float] = {}
    for name, score in ranked:
        best_by_family.setdefault(filter_family(name), score)
    families = sorted(best_by_family.items(), key=lambda item: item[1])
    family, family_score = families[0]
    family_lead = families[1][1] - family_score if len(families) > 1 else float("inf")
    members = [(name, score) for name, score in ranked if filter_family(name) == family]
    filter_lead = members[1][1] - members[0][1] if len(members) > 1 else float("inf")
    ambiguous = [name for name, score in members[1:] if score - members[0][1] < filter_margin]
    if family_lead < family_margin:
        status = "undetermined"
    elif filter_lead < filter_margin:
        status = "family"
    else:
        status = "filter"
    return {
        "status": status,
        "family": family if status != "undetermined" else None,
        "family_label": FAMILY_LABELS[family] if status != "undetermined" else None,
        "best_family": family,
        "family_margin": round(family_lead, 4) if np.isfinite(family_lead) else None,
        "filter": members[0][0] if status == "filter" else None,
        "filter_margin": round(filter_lead, 4) if np.isfinite(filter_lead) else None,
        "top3": [{"name": name, "family": filter_family(name), "score": round(score, 4)}
                 for name, score in ranked[:3]],
        "ambiguous_with": ambiguous if status == "family" else [],
    }


class FilterAnalyzer(processor):
    """Classe les filtres candidats d'une brute OSC selon les couleurs de ses étoiles.

    Le traitement lit une brute CFA non calibrée, la résout avec Siril, mesure
    ses étoiles aux positions Gaia DR3 et compare leurs couleurs aux flux
    simulés à partir des spectres XP pour chaque filtre de la base SPCC. Il
    écrit un rapport JSON et ne produit pas d'image.

    Parameters
    ----------
    database : SpccDatabase | None
        Base SPCC ; ``None`` utilise celle de l'installation de Siril.
    siril : Siril | None
        Service Siril ; ``None`` utilise la configuration liée.
    """

    def __init__(self, database: SpccDatabase | None = None, siril: Siril | None = None) -> None:
        """Mémorise les services injectés ; ils sont créés au premier traitement sinon."""
        self._database = database
        self._siril = siril

    @classmethod
    def get_prefix(cls) -> str:
        """Préfixe des options et identifiant du traitement."""
        return "filter"

    @classmethod
    def add_arguments(cls, parser: argparse.ArgumentParser) -> None:
        """Déclare les options de l'analyse, préfixées par ``--filter-``."""
        group = parser.add_argument_group("Analyse du filtre")
        group.add_argument("--filter-max-stars", dest="filter_max_stars", type=int, default=100,
                           help="Nombre maximal d'étoiles dont le spectre Gaia XP est utilisé")
        group.add_argument("--filter-min-stars", dest="filter_min_stars", type=int,
                           default=DEFAULT_MIN_STARS,
                           help="Nombre minimal d'étoiles exploitables pour conclure")
        group.add_argument("--filter-max-g", dest="filter_max_g", type=float, default=15.0,
                           help="Magnitude G Gaia limite des étoiles mesurées")
        group.add_argument("--filter-neighbor-g", dest="filter_neighbor_g", type=float, default=17.0,
                           help="Magnitude G limite des voisins pris en compte pour l'encombrement")
        group.add_argument("--filter-aperture", dest="filter_aperture", type=float, default=3.0,
                           help="Rayon d'ouverture photométrique, en superpixels (2×2 photosites)")
        group.add_argument("--filter-min-snr", dest="filter_min_snr", type=float, default=30.0,
                           help="Rapport signal sur bruit minimal dans chaque canal")
        group.add_argument("--filter-sensor", dest="filter_sensor", default=None,
                           help="Capteur de la base SPCC (défaut : déduit de INSTRUME)")
        group.add_argument("--filter-cache-dir", dest="filter_cache_dir", default=str(DEFAULT_CACHE_DIR),
                           help="Cache des sources et spectres Gaia")
        group.add_argument("--filter-family-margin", dest="filter_family_margin", type=float,
                           default=DEFAULT_FAMILY_MARGIN,
                           help="Écart de score minimal entre la meilleure famille et la suivante")
        group.add_argument("--filter-margin", dest="filter_margin", type=float, default=DEFAULT_FILTER_MARGIN,
                           help="Écart de score minimal entre le meilleur filtre et le suivant de sa famille")
        group.add_argument("--filter-model-uncertainty", dest="filter_model_uncertainty", type=float,
                           default=DEFAULT_MODEL_UNCERTAINTY,
                           help="Incertitude relative du modèle par flux")

    def candidates(self) -> dict[str, SpectralCurve]:
        """Filtres de la base SPCC et L-eXtreme synthétisé, par nom."""
        database = self._database or SpccDatabase()
        curves = {name: database.osc_filter(name) for name in database.osc_filter_names()}
        curves[L_EXTREME_NAME] = narrowband_filter(L_EXTREME_NAME, L_EXTREME_BANDS)
        return curves

    def post_process(self, input_path: Path, output_path: Path,
                     args: argparse.Namespace | None = None) -> JSONReport:
        """Analyse une brute et écrit le rapport JSON ``output_path``.

        Parameters
        ----------
        input_path : pathlib.Path
            Brute FITS CFA (``BAYERPAT`` requis), non calibrée.
        output_path : pathlib.Path
            Rapport JSON ; les fichiers de l'astrométrie vont dans
            ``<rapport>_work/``, réinitialisé à chaque appel.
        args : argparse.Namespace | None
            Surcharge ponctuelle des options.

        Returns
        -------
        dict
            Rapport : en-tête utile, astrométrie, étoiles, scores triés,
            décision et cohérence avec ``FILTER``.

        Raises
        ------
        ValueError
            Brute non CFA, capteur inconnu ou trop peu d'étoiles exploitables.
        RuntimeError
            Échec de Siril ou de l'archive Gaia.
        """
        options = self._get_args(args)
        input_path, output_path = Path(input_path).resolve(), Path(output_path).resolve()
        with fits.open(input_path) as hdul:
            data, header = hdul[0].data, hdul[0].header.copy()
        sensor_name = options.filter_sensor or sensor_for_instrument(header.get("INSTRUME", ""))
        if not sensor_name:
            raise ValueError(f"Capteur inconnu pour INSTRUME={header.get('INSTRUME')!r} : utiliser --filter-sensor")
        database = self._database or SpccDatabase()
        sensor = database.osc_sensor(sensor_name)
        rgb, rgb_header = superpixel_rgb(data, header)

        logging.info("Astrométrie de %s", input_path.name)
        work_dir = reset_work_dir(output_path)
        siril = self._siril or Siril()
        wcs = WCS(plate_solve(rgb, rgb_header, work_dir, siril=siril), naxis=2)
        height, width = rgb.shape[1:]
        centre = wcs.pixel_to_world((width - 1) / 2, (height - 1) / 2)
        scale_deg = float(np.mean(proj_plane_pixel_scales(wcs.celestial)))
        radius = FIELD_RADIUS_MARGIN * scale_deg * np.hypot(width, height) / 2

        cache = Path(options.filter_cache_dir).expanduser()
        sources = query_field_sources(float(centre.ra.deg), float(centre.dec.deg), radius,
                                      options.filter_neighbor_g, cache)
        positions = np.column_stack(wcs.world_to_pixel_values(
            np.asarray(sources["ra"], float), np.asarray(sources["dec"], float)))
        magnitude = np.asarray(sources["phot_g_mean_mag"], float)
        targets = np.flatnonzero((magnitude < options.filter_max_g) & np.asarray(sources["has_xp_sampled"], bool))
        photometry = measure_rgb(rgb, positions[targets], aperture_radius=options.filter_aperture,
                                 neighbors=positions, min_snr=options.filter_min_snr)
        valid = np.flatnonzero(photometry.valid)
        snr = (photometry.flux / photometry.sigma).min(axis=1)
        chosen = valid[select_colour_spread(np.asarray(sources["bp_rp"], float)[targets[valid]], snr[valid],
                                            options.filter_max_stars)]
        flux, _ = fetch_xp_spectra(np.asarray(sources["source_id"])[targets[chosen]], cache)
        with_spectrum = np.isfinite(flux).all(axis=1)
        chosen, flux = chosen[with_spectrum], flux[with_spectrum]
        if chosen.size < max(options.filter_min_stars, 3):
            raise ValueError(f"{chosen.size} étoiles exploitables, {options.filter_min_stars} requises")

        airmass = header.get("AIRMASS")
        atmosphere = atmospheric_transmission(float(airmass)) if airmass else None
        spectra = xp_to_grid(flux)
        observed, sigma = photometry.flux[chosen], photometry.sigma[chosen]
        scores = [
            (name, score_filter(name, observed, sigma, simulate_rgb(spectra, curve, sensor, atmosphere),
                                options.filter_model_uncertainty).reduced_score)
            for name, curve in self.candidates().items()
        ]
        decision = decide(scores, options.filter_family_margin, options.filter_margin)
        report = self._report(input_path, header, sensor_name, airmass, centre, scale_deg,
                              sources, targets, photometry.reason, chosen, scores, decision)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
        return report

    @staticmethod
    def _report(input_path, header, sensor_name, airmass, centre, scale_deg, sources, targets,
                reasons, chosen, scores, decision) -> JSONReport:
        """Assemble le rapport JSON à partir des résultats de chaque étape."""
        names = [name for name, _ in scores]
        header_filter = str(header.get("FILTER", "") or "").strip()
        matches = header_filter_candidates(header_filter, names)
        match_families = sorted({filter_family(name) for name in matches})
        if not matches:
            consistent = None
        else:
            consistent = decision["family"] is not None and decision["family"] in match_families
        return {
            "input": str(input_path),
            "header": {key: header.get(key) for key in (
                "FILTER", "INSTRUME", "TELESCOP", "EXPTIME", "GAIN", "DATE-OBS", "OBJECT", "AIRMASS")},
            "sensor": sensor_name,
            "airmass": float(airmass) if airmass else None,
            "astrometry": {"ra_deg": round(float(centre.ra.deg), 6), "dec_deg": round(float(centre.dec.deg), 6),
                           "scale_arcsec_per_superpixel": round(scale_deg * 3600, 4)},
            "stars": {
                "field_sources": len(sources),
                "measured": int(targets.size),
                "rejected": dict(Counter(str(reason) for reason in reasons if reason)),
                "used": int(chosen.size),
            },
            "scores": [{"name": name, "family": filter_family(name), "score": round(score, 4)}
                       for name, score in sorted(scores, key=lambda item: item[1])],
            "decision": decision,
            "header_consistency": {
                "header_filter": header_filter or None,
                "matching_candidates": matches,
                "consistent": consistent,
            },
        }
