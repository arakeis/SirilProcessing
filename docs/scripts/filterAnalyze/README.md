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
| [plate_solving.py](../../../lib/plate_solving.py) | Résoudre l’astrométrie d’une image avec Siril, sur Gaia DR3 |

<a id="1-chaine-prevue"></a>

## 1. Chaîne prévue

1. Lecture de l’image linéaire (FITS ou XISF) et de ses métadonnées.
2. Calibration (darks, dark flats, flats) et mesure des flux R, G, B des étoiles.
3. Astrométrie, puis interrogation de Gaia DR3 (spectres XP) avec cache local.
4. Simulation des flux de chaque étoile pour chaque filtre candidat.
5. Score par filtre, décision (filtre ou famille) et cohérence avec `FILTER`.

Les étapes 4 et 5 (modèle et score) sont décrites dans
[Modèle direct et score](MODEL.md). De l’étape 3, seule l’astrométrie existe
(section 3 ci-dessous) ; l’interrogation de Gaia et les étapes 1 et 2 restent
à faire, hormis la lecture des masters XISF.

<a id="2-prerequis"></a>

## 2. Prérequis

- La base SPCC de Siril, téléchargée par Siril dans ses préférences SPCC.
  Emplacement vérifié sous macOS :
  `~/Library/Application Support/org.siril.Siril/siril-spcc-database`. Sous
  Linux, le module cherche `$XDG_DATA_HOME/siril/siril-spcc-database` puis le
  dossier Flatpak de Siril ; ces deux emplacements n’ont pas été vérifiés.
- Les dépendances de `requirements.txt` (NumPy, Astropy).
- Siril 1.4 ou plus récent pour l’astrométrie, et le réseau pour le catalogue
  Gaia distant.

<a id="3-astrometrie"></a>

## 3. Astrométrie

`plate_solve(data, header, work_dir)` écrit l’image dans `work_dir`, lance
`platesolve -force -noflip -catalog=gaia` avec Siril et retourne l’en-tête
résolu (WCS avec distorsions SIP). Le centre (`RA`/`DEC` en degrés, sinon
`OBJCTRA`/`OBJCTDEC`), la focale (`FOCALLEN`) et la taille des pixels
(`XPIXSZ`) sont lus dans l’en-tête lorsqu’ils existent.

- `-noflip` garde les pixels tels quels : le WCS s’applique directement au
  tableau fourni, y compris pour une image rangée `TOP-DOWN`.
- Les coordonnées du centre précèdent `-force`, que Siril 1.4.1 refuse sinon.
- Le catalogue `gaia` distant exige le réseau. Après une résolution, Siril
  enregistre la focale et la taille de pixel trouvées dans ses préférences.

Vérifié avec Siril 1.4.1 sous macOS sur des images ASI294MC Pro à 800 mm de
focale (1,19″/px) : masters RGB L-eXtreme et L-Pro lus depuis XISF, et une
brute CFA non dématricée. Le centre de la brute concorde avec celui du master
à 1″ près, et les étoiles Gaia brillantes projetées par le WCS tombent sur
les étoiles de l’image.
