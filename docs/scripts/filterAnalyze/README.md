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
| [star_photometry.py](../../../lib/star_photometry.py) | Mesurer les flux R, G, B des étoiles aux positions du catalogue |
| [cfa_superpixel.py](../../../lib/cfa_superpixel.py) | Dématricer une brute CFA en superpixels RGB selon `BAYERPAT` et `ROWORDER` |
| [gaia_xp.py](../../../lib/gaia_xp.py) | Télécharger et garder en cache les sources et spectres XP de Gaia DR3 |

<a id="1-chaine-prevue"></a>

## 1. Chaîne prévue

1. Lecture de l’image linéaire (FITS ou XISF) et de ses métadonnées.
2. Dématriçage superpixel d’une brute, sans calibration, et mesure des flux R,
   G, B des étoiles.
3. Astrométrie, puis interrogation de Gaia DR3 (spectres XP) avec cache local.
4. Simulation des flux de chaque étoile pour chaque filtre candidat.
5. Score par filtre, décision (filtre ou famille) et cohérence avec `FILTER`.

Les étapes 4 et 5 (modèle et score) sont décrites dans
[Modèle direct et score](MODEL.md). L’astrométrie (section 3), la mesure des
flux (section 4), le dématriçage des brutes (section 5) et l’accès aux
spectres Gaia (section 6) existent ; reste l’assemblage en script.

<a id="2-prerequis"></a>

## 2. Prérequis

- La base SPCC de Siril, téléchargée par Siril dans ses préférences SPCC.
  Emplacement vérifié sous macOS :
  `~/Library/Application Support/org.siril.Siril/siril-spcc-database`. Sous
  Linux, le module cherche `$XDG_DATA_HOME/siril/siril-spcc-database` puis le
  dossier Flatpak de Siril ; ces deux emplacements n’ont pas été vérifiés.
- Les dépendances de `requirements.txt` (NumPy, Astropy).
- Siril 1.4 ou plus récent pour l’astrométrie, et le réseau pour le catalogue
  Gaia distant et l’archive Gaia de l’ESA.

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

<a id="4-photometrie"></a>

## 4. Photométrie des étoiles

`measure_rgb(data, positions, aperture_radius=…)` mesure une image RGB
linéaire aux positions d’un catalogue projeté par le WCS. Le centroïde est
affiné sur la somme des canaux, puis la même ouverture circulaire mesure R, G
et B ; le fond est la médiane d’un anneau (par défaut de 1,5 à 2,5 fois le
rayon). L’incertitude ne contient que le bruit du fond, le gain d’un master
empilé étant inconnu.

Une étoile est rejetée et son motif est conservé : `edge` (trop près du
bord), `crowded` (autre astre fourni dans l’anneau), `saturated` (par défaut
90 % du maximum du canal), `offset` (centroïde à plus d’un demi-rayon de la
position prédite) ou `faint` (rapport signal sur bruit inférieur à 30 dans un
canal).

`select_colour_spread(colour, snr, max_stars)` limite ensuite le nombre
d’étoiles dont il faut télécharger le spectre. La gamme des couleurs Gaia
`BP − RP` est découpée en dix tranches de même largeur, parcourues tour à tour
en prenant chaque fois l’étoile restante au meilleur rapport signal sur bruit.
Le score dépend de l’écart entre étoiles bleues et rouges plus que de leur
nombre : les rares étoiles des extrémités sont donc gardées en priorité.

Essai sur les masters RGB, positions Gaia DR3 (G < 15,5) et voisins jusqu’à
G = 17, avec la couleur `B − R` mesurée comparée à `BP − RP` :

| Image | Étoiles retenues | Décalage médian | Pente | Corrélation |
|---|---|---|---|---|
| Master L-eXtreme, rayon 5 px | 1856 | 0,13 px | 0,55 | 0,95 |
| Master L-Pro, rayon 5 px | 633 | 0,20 px | 0,06 | 0,39 |
| Brute L-Pro, superpixel RGGB, rayon 3 px | 293 | — | 0,72 | 0,96 |

Le master L-Pro ne présente presque aucune dépendance à la couleur, alors que
sa brute dématricée selon son `BAYERPAT` (RGGB) se comporte normalement. Le
master se comporte comme un dématriçage GRBG ou GBRG : un retournement vertical
d’une image de hauteur paire transforme RGGB en GBRG. Un master déjà dématricé
ne peut donc pas être utilisé sans contrôle ; la chaîne partira des brutes.

<a id="5-dematricage"></a>

## 5. Dématriçage des brutes

`superpixel_rgb(data, header)` transforme chaque bloc 2×2 de la matrice de
Bayer en un pixel RGB : rouge, moyenne des deux verts, bleu. Les trois canaux
d’une étoile proviennent des mêmes photosites, sans interpolation. Le motif
`BAYERPAT`, décalé par `XBAYROFF`/`YBAYROFF`, se lit du haut vers le bas ; pour
une image `BOTTOM-UP` de hauteur paire, la parité des lignes est inversée.
Sans `ROWORDER`, l’image est supposée `TOP-DOWN`, comme chez Ekos et NINA.
L’en-tête retourné double la taille des pixels et le binning, et retire la
matrice et le WCS, qui ne s’appliquent plus.

**Pas de calibration.** Le fond pris dans l’anneau de chaque étoile retire
l’offset, le courant d’obscurité et le gradient d’amp glow. Le vignetage et la
couleur globale du flat sont communs à l’échantillon et s’annulent dans les
couleurs ou dans le décalage de balance des blancs du score. Seule une
variation de couleur dans le champ (bandes d’un filtre interférentiel décalées
au bord à f/4, vignetage chromatique) échappe à ces corrections ; son effet
reste à mesurer.

Essai sur chaque brute, astrométrie de l’image superpixel, rayon 3 superpixels,
étoiles Gaia G < 15 et voisins jusqu’à G = 17 :

| Filtre | Brutes | Étoiles retenues par brute | Décalage médian | Pente B − R | Pente G − R | Corrélations |
|---|---|---|---|---|---|---|
| L-eXtreme, 300 s | 5 | 76 à 129 | < 0,1 superpixel | 0,77 à 0,83 | 0,74 à 0,78 | 0,96 à 0,99 |
| L-Pro, 120 s | 4 | 167 à 286 | ≈ 0,1 superpixel | 0,69 à 0,78 | 0,44 à 0,48 | 0,94 à 0,96 |

Les pentes sont stables d’une brute à l’autre, et la pente G − R sépare déjà
nettement les deux filtres. Le master L-Pro dématricé à tort (section 4) a été
retiré des données d’essai.

<a id="6-spectres-gaia"></a>

## 6. Sources et spectres Gaia XP

`query_field_sources(ra, dec, rayon, max_g, cache)` interroge le service TAP de
l’archive Gaia de l’ESA en mode asynchrone, sur la table allégée
`gaiadr3.gaia_source_lite` : position, magnitude G, `BP − RP` et
`has_xp_sampled`. `fetch_xp_spectra(identifiants, cache)` télécharge les
spectres XP échantillonnés (343 points de 336 à 1020 nm, en W·m⁻²·nm⁻¹) et
`xp_to_grid` les ramène sur la grille du modèle. Tout est gardé dans le
dossier de cache : une table par requête, un fichier par spectre, y compris
pour une source sans spectre.

Limites constatées en accès anonyme, le 20 octobre 2026 :

- une requête TAP, même asynchrone, est interrompue après 60 s. Sur la table
  complète `gaia_source`, un champ de 0,84° jusqu’à G = 17 dépasse parfois
  cette durée ; la table allégée répond en quelques secondes ;
- le service DataLink accepte au plus 50 identifiants par requête ; un lot de
  50 spectres a pris environ 70 s ;
- les services de l’ESA (et VizieR) ont été indisponibles un moment : les
  erreurs 5xx et les délais dépassés sont réessayés trois fois avant d’échouer.
