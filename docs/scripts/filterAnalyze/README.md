# filterAnalyze — identification du filtre d’acquisition (en développement)

[Documentation](../../README.md) › [Scripts](../README.md) › filterAnalyze

L’objectif est d’identifier le filtre astronomique utilisé lors d’une
acquisition avec un capteur couleur (OSC), à partir des couleurs des étoiles
d’une image linéaire, sans se fier au champ `FILTER` de l’en-tête. Le résultat
attendu est un classement des filtres compatibles, ou d’une famille de filtres
lorsque l’identification n’est pas assez discriminante, dans un rapport JSON.

**État actuel :** aucun script n’est encore disponible. Les bibliothèques
suivantes sont en place et testées :

| Module | Rôle |
|---|---|
| [xisf_reader.py](../../../lib/xisf_reader.py) | Lire les masters PixInsight (`.xisf`) non compressés |
| [spectral_response.py](../../../lib/spectral_response.py) | Charger les courbes de la base SPCC de Siril, synthétiser les filtres à bande étroite, modéliser l’atmosphère |
| [filter_model.py](../../../lib/filter_model.py) | Simuler les flux RGB des étoiles et calculer un score de compatibilité par filtre |

<a id="1-chaine-prevue"></a>

## 1. Chaîne prévue

1. Lecture de l’image linéaire (FITS ou XISF) et de ses métadonnées.
2. Calibration (darks, dark flats, flats) et mesure des flux R, G, B des étoiles.
3. Astrométrie, puis interrogation de Gaia DR3 (spectres XP) avec cache local.
4. Simulation des flux de chaque étoile pour chaque filtre candidat.
5. Score par filtre, décision (filtre ou famille) et cohérence avec `FILTER`.

Seules les étapes 4 et 5 (modèle et score) existent aujourd’hui ; elles sont
décrites dans [Modèle direct et score](MODEL.md).

<a id="2-prerequis"></a>

## 2. Prérequis

- La base SPCC de Siril, téléchargée par Siril dans ses préférences SPCC.
  Emplacement vérifié sous macOS :
  `~/Library/Application Support/org.siril.Siril/siril-spcc-database`. Sous
  Linux, le module cherche `$XDG_DATA_HOME/siril/siril-spcc-database` puis le
  dossier Flatpak de Siril ; ces deux emplacements n’ont pas été vérifiés.
- Les dépendances de `requirements.txt` (NumPy, Astropy).
