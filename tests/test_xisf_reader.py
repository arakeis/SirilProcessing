"""Lecture XISF : géométrie, formats, en-têtes et refus explicites des cas non pris en charge."""

import struct
from pathlib import Path

import numpy as np
import pytest

from lib.xisf_reader import read_xisf

ALIGNMENT = 4096


def write_xisf(
    path: Path,
    data: np.ndarray,
    *,
    sample_format: str,
    color_space: str = "Gray",
    pixel_storage: str | None = None,
    extra_attributes: str = "",
    keywords: str = "",
    properties: str = "",
    declared_size: int | None = None,
    signature: bytes = b"XISF0100",
) -> Path:
    """Écrit un XISF minimal, au format attendu des masters PixInsight.

    ``data`` est fourni en ``(canaux, hauteur, largeur)`` ; il est sérialisé en
    planaire, ou en entrelacé si ``pixel_storage='Normal'``.
    """
    channels, height, width = data.shape
    if pixel_storage == "Normal":
        payload = np.ascontiguousarray(data.transpose(1, 2, 0)).tobytes()
    else:
        payload = np.ascontiguousarray(data).tobytes()
    size = len(payload) if declared_size is None else declared_size
    storage = f' pixelStorage="{pixel_storage}"' if pixel_storage else ""
    xml = (
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<xisf version="1.0" xmlns="http://www.pixinsight.com/xisf">'
        f'<Image geometry="{width}:{height}:{channels}" sampleFormat="{sample_format}"'
        f' colorSpace="{color_space}" location="attachment:{ALIGNMENT}:{size}"'
        f'{storage}{extra_attributes}>{keywords}{properties}</Image></xisf>'
    ).encode()
    preamble = signature + struct.pack("<I", len(xml)) + b"\0" * 4
    padding = b"\0" * (ALIGNMENT - len(preamble) - len(xml))
    path.write_bytes(preamble + xml + padding + payload)
    return path


@pytest.fixture
def rgb_float32() -> np.ndarray:
    """Cube RGB flottant aux valeurs distinctes par canal, ligne et colonne."""
    return (np.arange(3 * 4 * 5, dtype=np.float32).reshape(3, 4, 5) / 100).astype("<f4")


def test_planar_rgb_float_and_metadata(tmp_path, rgb_float32):
    """Cas nominal d'un master light : pixels, mots-clés typés et propriétés scalaires."""
    keywords = (
        "<FITSKeyword name=\"INSTRUME\" value=\"'ZWO CCD ASI294MC Pro'\" comment=\"Camera\"/>"
        '<FITSKeyword name="EXPTIME" value="300.000" comment="s"/>'
        '<FITSKeyword name="XBINNING" value="1" comment=""/>'
        '<FITSKeyword name="PLTSOLVD" value="T" comment=""/>'
        "<FITSKeyword name=\"FILTER\" value=\"'L Extreme'\" comment=\"\"/>"
        "<FITSKeyword name=\"FILTER\" value=\"'Ignored'\" comment=\"\"/>"
        '<FITSKeyword name="COMMENT" value="" comment="Intégration"/>'
    )
    properties = (
        '<Property id="Instrument:Filter:Name" type="String" value="L Extreme"/>'
        '<Property id="Instrument:FrameExposureTime" type="Float64" value="300"/>'
        '<Property id="Instrument:Camera:XBinning" type="UInt32" value="1"/>'
        '<Property id="XISF:Flag" type="Boolean" value="true"/>'
        '<Property id="History" type="String">texte long</Property>'
        '<Property id="AstrometricSolution:Matrix" type="F64Matrix" location="inline:base64"/>'
    )
    path = write_xisf(
        tmp_path / "light.xisf", rgb_float32, sample_format="Float32",
        color_space="RGB", extra_attributes=' bounds="0:1"',
        keywords=keywords, properties=properties,
    )
    image = read_xisf(path)
    np.testing.assert_array_equal(image.data, rgb_float32)
    assert image.data.dtype == np.float32 and image.data.flags.c_contiguous
    assert image.color_space == "RGB" and image.bounds == (0.0, 1.0)
    header = image.header
    assert header["INSTRUME"] == "ZWO CCD ASI294MC Pro"
    assert header["EXPTIME"] == 300.0 and header["XBINNING"] == 1
    assert header["PLTSOLVD"] is True
    assert header["FILTER"] == "L Extreme"
    assert header["ROWORDER"] == "TOP-DOWN"
    assert "Int?gration" in str(header["COMMENT"])
    assert image.properties == {
        "Instrument:Filter:Name": "L Extreme",
        "Instrument:FrameExposureTime": 300.0,
        "Instrument:Camera:XBinning": 1,
        "XISF:Flag": True,
        "History": "texte long",
    }


def test_gray_uint16_returns_two_dimensions(tmp_path):
    """Une image monocanal (master dark/flat CFA) est retournée en (hauteur, largeur)."""
    data = np.arange(6 * 8, dtype="<u2").reshape(1, 6, 8)
    image = read_xisf(write_xisf(tmp_path / "dark.xisf", data, sample_format="UInt16"))
    assert image.data.shape == (6, 8) and image.data.dtype == np.uint16
    np.testing.assert_array_equal(image.data, data[0])
    assert image.bounds is None and image.properties == {}


def test_interleaved_storage_matches_planar(tmp_path, rgb_float32):
    """Le stockage entrelacé est réordonné en canaux, lignes, colonnes."""
    path = write_xisf(
        tmp_path / "normal.xisf", rgb_float32, sample_format="Float32",
        color_space="RGB", pixel_storage="Normal",
    )
    np.testing.assert_array_equal(read_xisf(path).data, rgb_float32)


def test_big_endian_samples_are_converted_to_native_order(tmp_path):
    """L'ordre d'octets déclaré est respecté et converti en ordre natif."""
    data = np.array([[[1.5, -2.25], [3.0, 4.75]]], dtype=">f8")
    path = write_xisf(
        tmp_path / "big.xisf", data, sample_format="Float64",
        extra_attributes=' byteOrder="big"',
    )
    image = read_xisf(path)
    np.testing.assert_array_equal(image.data, data[0].astype(float))
    assert image.data.dtype.byteorder in ("=", "<")


@pytest.mark.parametrize("attributes, message", [
    (' compression="zlib:96"', "compressée"),
    (' bounds="bad"', "Bornes"),
])
def test_unsupported_attributes_are_refused(tmp_path, rgb_float32, attributes, message):
    """Compression et bornes invalides échouent au lieu de produire des pixels faux."""
    path = write_xisf(
        tmp_path / "bad.xisf", rgb_float32, sample_format="Float32",
        extra_attributes=attributes,
    )
    with pytest.raises(ValueError, match=message):
        read_xisf(path)


def test_unknown_sample_format_is_refused(tmp_path, rgb_float32):
    """Les échantillons complexes ne sont pas pris en charge."""
    path = write_xisf(tmp_path / "complex.xisf", rgb_float32, sample_format="Complex32")
    with pytest.raises(ValueError, match="Format d'échantillon"):
        read_xisf(path)


def test_block_size_must_match_geometry(tmp_path, rgb_float32):
    """Une taille de bloc incohérente avec la géométrie est refusée."""
    path = write_xisf(
        tmp_path / "size.xisf", rgb_float32, sample_format="Float32",
        declared_size=rgb_float32.nbytes - 4,
    )
    with pytest.raises(ValueError, match="incohérente"):
        read_xisf(path)


def test_truncated_file_is_refused(tmp_path, rgb_float32):
    """Un bloc qui dépasse la fin du fichier est détecté avant la lecture."""
    path = write_xisf(tmp_path / "cut.xisf", rgb_float32, sample_format="Float32")
    path.write_bytes(path.read_bytes()[:-8])
    with pytest.raises(ValueError, match="fin du fichier"):
        read_xisf(path)


def test_invalid_signature_and_missing_file(tmp_path, rgb_float32):
    """Signature étrangère et fichier absent produisent des erreurs explicites."""
    path = write_xisf(
        tmp_path / "fits.xisf", rgb_float32, sample_format="Float32", signature=b"SIMPLE  ",
    )
    with pytest.raises(ValueError, match="signature"):
        read_xisf(path)
    with pytest.raises(FileNotFoundError):
        read_xisf(tmp_path / "absent.xisf")


def test_inline_location_and_invalid_geometry_are_refused(tmp_path):
    """Les blocs intégrés au XML et les géométries non numériques sont refusés."""
    xml = (
        b'<xisf version="1.0" xmlns="http://www.pixinsight.com/xisf">'
        b'<Image geometry="2:2:1" sampleFormat="UInt8" location="inline:base64">AAAA</Image></xisf>'
    )
    inline = tmp_path / "inline.xisf"
    inline.write_bytes(b"XISF0100" + struct.pack("<I", len(xml)) + b"\0" * 4 + xml)
    with pytest.raises(ValueError, match="Emplacement"):
        read_xisf(inline)
    geometry = tmp_path / "geometry.xisf"
    geometry.write_bytes(inline.read_bytes().replace(b'geometry="2:2:1"', b'geometry="a:b:c"'))
    with pytest.raises(ValueError, match="Géométrie"):
        read_xisf(geometry)
