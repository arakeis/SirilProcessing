# Chaîne de mesure : astrométrie, photométrie, dématriçage et Gaia

[Documentation](../../README.md) › [Scripts](../README.md) › [filterAnalyze](README.md) › Chaîne de mesure

Cette page décrit les modules qui transforment une brute en couleurs
d’étoiles et en spectres de référence : `lib/plate_solving.py`,
`lib/star_photometry.py`, `lib/cfa_superpixel.py` et `lib/gaia_xp.py`. Le
modèle et le score sont décrits dans [Modèle direct et score](MODEL.md).

<a id="1-astrometrie"></a>

## 1. Astrométrie

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

<a id="2-photometrie"></a>

## 2. Photométrie des étoiles

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

<a id="3-dematricage"></a>

## 3. Dématriçage des brutes

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
nettement les deux filtres. Le master L-Pro dématricé à tort (section 2) a été
retiré des données d’essai.

<a id="4-spectres-gaia"></a>

## 4. Sources et spectres Gaia XP

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
