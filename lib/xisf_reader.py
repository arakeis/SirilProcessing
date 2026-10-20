"""Lecture minimale des images XISF non compressées produites par PixInsight.

Le format XISF 1.0 commence par la signature ``XISF0100``, la longueur de
l'en-tête XML (entier 32 bits little-endian), quatre octets réservés, puis cet
en-tête XML. Les pixels sont stockés dans des blocs ``attachment:<position>:<taille>``.

Ce lecteur couvre les masters PixInsight (WBPP, ImageIntegration) : première
image du fichier, échantillons entiers non signés ou flottants, stockage planaire
ou entrelacé, sans compression. Les mots-clés FITS sont convertis en en-tête
Astropy ; les propriétés XISF scalaires sont conservées telles quelles. Les
propriétés vectorielles ou matricielles, dont la solution astrométrique
PixInsight, sont ignorées.

Les lignes XISF sont rangées du haut vers le bas : l'en-tête retourné contient
``ROWORDER = 'TOP-DOWN'``, comme les FITS d'Ekos, pour les lecteurs du projet.

Exemple
-------
>>> image = read_xisf("masterLight.xisf")  # doctest: +SKIP
>>> image.data.shape, image.header["INSTRUME"]  # doctest: +SKIP
((3, 2822, 4144), 'ZWO CCD ASI294MC Pro')
"""

from __future__ import annotations

import struct
import xml.etree.ElementTree as ElementTree
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np
from astropy.io import fits

XISF_SIGNATURE = b"XISF0100"
# Signature (8 octets), longueur de l'en-tête (4 octets), réservé (4 octets).
XISF_PREAMBLE_SIZE = 16
XISF_NAMESPACE = "{http://www.pixinsight.com/xisf}"

SAMPLE_FORMATS = {
    "UInt8": "u1",
    "UInt16": "u2",
    "UInt32": "u4",
    "UInt64": "u8",
    "Float32": "f4",
    "Float64": "f8",
}
SCALAR_PROPERTY_TYPES = {
    "Boolean": lambda value: value.lower() == "true",
    "Int8": int,
    "Int16": int,
    "Int32": int,
    "Int64": int,
    "UInt8": int,
    "UInt16": int,
    "UInt32": int,
    "UInt64": int,
    "Float32": float,
    "Float64": float,
    "String": str,
    "TimePoint": str,
}


@dataclass
class XisfImage:
    """Image XISF lue en mémoire.

    Attributes
    ----------
    data : numpy.ndarray
        Pixels au format ``(hauteur, largeur)`` pour une image monocanal, ou
        ``(canaux, hauteur, largeur)`` comme Astropy pour un cube FITS. La
        première ligne est le haut de l'image.
    header : astropy.io.fits.Header
        Mots-clés FITS du fichier, complétés par ``ROWORDER = 'TOP-DOWN'``.
    properties : dict[str, bool | int | float | str]
        Propriétés XISF scalaires, indexées par leur identifiant.
    color_space : str
        Espace colorimétrique déclaré (``Gray`` ou ``RGB``).
    bounds : tuple[float, float] | None
        Intervalle de représentation déclaré pour les flottants, sinon ``None``.
    """

    data: np.ndarray
    header: fits.Header
    properties: dict[str, bool | int | float | str] = field(default_factory=dict)
    color_space: str = "Gray"
    bounds: tuple[float, float] | None = None


def _fits_value(raw: str) -> bool | int | float | str:
    """Convertit la valeur textuelle d'un mot-clé FITS XISF en type Python.

    Parameters
    ----------
    raw : str
        Valeur telle qu'écrite par PixInsight : chaîne entre apostrophes,
        ``T``/``F``, entier, réel, ou texte vide.

    Returns
    -------
    bool | int | float | str
        Valeur typée ; un texte non numérique est conservé tel quel.
    """
    text = raw.strip()
    if text.startswith("'") and text.endswith("'") and len(text) >= 2:
        return text[1:-1].replace("''", "'").rstrip()
    if text in ("T", "F"):
        return text == "T"
    for convert in (int, float):
        try:
            return convert(text)
        except ValueError:
            pass
    return text


def _read_header_xml(path: Path) -> ElementTree.Element:
    """Lit et analyse l'en-tête XML d'un fichier XISF.

    Raises
    ------
    ValueError
        Signature absente, en-tête tronqué ou XML invalide.
    """
    with path.open("rb") as stream:
        preamble = stream.read(XISF_PREAMBLE_SIZE)
        if len(preamble) < XISF_PREAMBLE_SIZE or preamble[:8] != XISF_SIGNATURE:
            raise ValueError(f"Fichier XISF 1.0 invalide (signature) : {path}")
        (header_length,) = struct.unpack("<I", preamble[8:12])
        xml = stream.read(header_length)
    if len(xml) != header_length:
        raise ValueError(f"En-tête XISF tronqué : {path}")
    try:
        return ElementTree.fromstring(xml)
    except ElementTree.ParseError as error:
        raise ValueError(f"En-tête XML XISF invalide : {path}") from error


def _attachment(location: str, path: Path) -> tuple[int, int]:
    """Retourne la position et la taille d'un bloc ``attachment``.

    Raises
    ------
    ValueError
        Bloc intégré au XML (``inline``, ``embedded``) ou syntaxe inattendue.
    """
    parts = location.split(":")
    if len(parts) != 3 or parts[0] != "attachment":
        raise ValueError(f"Emplacement XISF non pris en charge ({location}) : {path}")
    try:
        position, size = int(parts[1]), int(parts[2])
    except ValueError as error:
        raise ValueError(f"Emplacement XISF invalide ({location}) : {path}") from error
    if position < 0 or size < 0:
        raise ValueError(f"Emplacement XISF négatif ({location}) : {path}")
    return position, size


def _header(image: ElementTree.Element) -> fits.Header:
    """Construit l'en-tête Astropy à partir des éléments ``FITSKeyword``."""
    header = fits.Header()
    for keyword in image.iter(f"{XISF_NAMESPACE}FITSKeyword"):
        name = keyword.get("name", "").strip().upper()
        value = keyword.get("value", "")
        comment = keyword.get("comment", "")
        if not name:
            continue
        if name == "COMMENT":
            header.add_comment(_ascii(comment or value))
        elif name == "HISTORY":
            header.add_history(_ascii(comment or value))
        elif name not in header:
            # La première occurrence prévaut, comme pour les mots-clés FITS uniques.
            typed = _fits_value(value)
            header[name] = (_ascii(typed) if isinstance(typed, str) else typed, _ascii(comment))
    header["ROWORDER"] = ("TOP-DOWN", "XISF: first row is the top of the image")
    return header


def _ascii(text: str) -> str:
    """Remplace les caractères hors ASCII imprimable, refusés par les en-têtes FITS."""
    return "".join(c if " " <= c <= "~" else "?" for c in text)


def _properties(image: ElementTree.Element) -> dict[str, bool | int | float | str]:
    """Extrait les propriétés XISF scalaires, en ignorant vecteurs et matrices."""
    properties: dict[str, bool | int | float | str] = {}
    for item in image.iter(f"{XISF_NAMESPACE}Property"):
        identifier, kind = item.get("id"), item.get("type")
        convert = SCALAR_PROPERTY_TYPES.get(kind or "")
        if not identifier or convert is None or identifier in properties:
            continue
        raw = item.get("value")
        if raw is None and kind == "String":
            raw = item.text or ""
        if raw is None:
            continue
        try:
            properties[identifier] = convert(raw)
        except ValueError:
            properties[identifier] = raw
    return properties


def read_xisf(path: Path | str) -> XisfImage:
    """Lit la première image d'un fichier XISF 1.0 non compressé.

    Parameters
    ----------
    path : pathlib.Path | str
        Fichier ``.xisf`` à lire ; il n'est jamais modifié.

    Returns
    -------
    XisfImage
        Pixels, en-tête FITS, propriétés scalaires et métadonnées d'affichage.

    Raises
    ------
    FileNotFoundError
        Fichier absent.
    ValueError
        Signature, XML, géométrie, format d'échantillon, compression,
        emplacement ou taille de bloc non pris en charge ou incohérents.

    Notes
    -----
    Les échantillons complexes, la compression et les blocs intégrés au XML
    ne sont pas pris en charge : le lecteur échoue explicitement plutôt que de
    retourner des pixels faux.
    """
    path = Path(path)
    if not path.is_file():
        raise FileNotFoundError(path)
    root = _read_header_xml(path)
    image = root.find(f"{XISF_NAMESPACE}Image")
    if image is None:
        raise ValueError(f"Aucune image dans le fichier XISF : {path}")
    if image.get("compression"):
        raise ValueError(f"Image XISF compressée non prise en charge : {path}")

    try:
        dimensions = [int(value) for value in image.get("geometry", "").split(":")]
    except ValueError as error:
        raise ValueError(f"Géométrie XISF invalide : {path}") from error
    if len(dimensions) not in (2, 3) or min(dimensions) <= 0:
        raise ValueError(f"Géométrie XISF non prise en charge : {path}")
    width, height = dimensions[:2]
    channels = dimensions[2] if len(dimensions) == 3 else 1

    sample_format = image.get("sampleFormat", "")
    if sample_format not in SAMPLE_FORMATS:
        raise ValueError(f"Format d'échantillon XISF non pris en charge ({sample_format}) : {path}")
    byte_order = "<" if image.get("byteOrder", "little") == "little" else ">"
    dtype = np.dtype(byte_order + SAMPLE_FORMATS[sample_format])

    position, size = _attachment(image.get("location", ""), path)
    count = width * height * channels
    if size != count * dtype.itemsize:
        raise ValueError(f"Taille de bloc XISF incohérente avec la géométrie : {path}")
    if position + size > path.stat().st_size:
        raise ValueError(f"Bloc XISF au-delà de la fin du fichier : {path}")
    with path.open("rb") as stream:
        stream.seek(position)
        samples = np.fromfile(stream, dtype=dtype, count=count)
    if samples.size != count:
        raise ValueError(f"Bloc XISF tronqué : {path}")

    if image.get("pixelStorage", "Planar") == "Normal":
        # Stockage entrelacé : (hauteur, largeur, canaux) vers (canaux, hauteur, largeur).
        data = samples.reshape(height, width, channels).transpose(2, 0, 1)
    else:
        data = samples.reshape(channels, height, width)
    data = np.ascontiguousarray(data.astype(dtype.newbyteorder("="), copy=False))
    if channels == 1:
        data = data[0]

    bounds = None
    if image.get("bounds"):
        try:
            low, high = (float(value) for value in image.get("bounds").split(":"))
            bounds = (low, high)
        except ValueError as error:
            raise ValueError(f"Bornes XISF invalides : {path}") from error

    return XisfImage(
        data=data,
        header=_header(image),
        properties=_properties(image),
        color_space=image.get("colorSpace", "Gray"),
        bounds=bounds,
    )
