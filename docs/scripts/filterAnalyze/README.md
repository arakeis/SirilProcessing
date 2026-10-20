# filterAnalyze — identification du filtre d’acquisition

[Documentation](../../README.md) › [Scripts](../README.md) › filterAnalyze

<a id="1-chaine-prevue"></a>

## 1. Objectif

`filterAnalyze` identifie le filtre astronomique utilisé pour une brute de
caméra couleur (OSC), à partir des couleurs de ses étoiles, sans se fier au
mot-clé `FILTER`. Pour chaque brute, il compare les couleurs mesurées aux
couleurs attendues avec chaque filtre de la base SPCC de Siril, puis écrit un
rapport JSON : classement des filtres, famille retenue (bi-bande, antipollution
large bande, UV/IR seul, sans filtre) et cohérence avec `FILTER`.

La chaîne, détaillée dans [Chaîne de mesure](MEASUREMENT.md) et
[Modèle direct et score](MODEL.md) :

1. dématriçage superpixel de la brute, sans calibration ;
2. astrométrie avec Siril `platesolve` sur Gaia DR3 ;
3. sources Gaia du champ et photométrie RGB aux positions Gaia ;
4. choix d’au plus 100 étoiles réparties en couleur, téléchargement de leurs
   spectres Gaia XP (mis en cache) ;
5. simulation des flux de chaque étoile pour chaque filtre candidat, score de
   compatibilité, puis décision par famille et par filtre.

<a id="2-prerequis"></a>

## 2. Prérequis

- Les dépendances de `requirements.txt` (NumPy, SciPy, Astropy).
- Siril 1.4 ou plus récent, et sa base SPCC, téléchargée par Siril dans ses
  préférences SPCC. Emplacement vérifié sous macOS :
  `~/Library/Application Support/org.siril.Siril/siril-spcc-database`. Sous
  Linux, le module cherche `$XDG_DATA_HOME/siril/siril-spcc-database` puis le
  dossier Flatpak de Siril ; ces deux emplacements n’ont pas été vérifiés.
- Un accès réseau : catalogue Gaia de Siril pour l’astrométrie, archive Gaia
  de l’ESA pour les sources et les spectres. Une fois le cache rempli, une
  nouvelle analyse du même champ ne télécharge plus de spectres.

<a id="3-lancement"></a>

## 3. Lancement

```bash
bin/filterAnalyze.sh IC_5070_Light_017.fits
```

```bash
bin/filterAnalyze.sh lights/*.fits --output-dir rapports --filter-max-stars 50
```

Le lanceur `bin/filterAnalyze.sh` prépare l’environnement Python du projet
(`.venv`, mis à jour depuis `requirements.txt`) puis exécute
`bin/filterAnalyze.py` avec les mêmes arguments. Chaque brute est analysée
indépendamment ; une ligne de synthèse est affichée par brute :

```text
IC_5070_Light_017.fits: family — famille light_pollution — 100 étoiles — Optolong L-QEF 1.38, ...
```

Les options et leurs valeurs par défaut sont décrites dans [Options](OPTIONS.md).

<a id="4-entrees"></a>

## 4. Entrées

Une ou plusieurs brutes FITS d’un capteur couleur, **non dématricées** et
**non calibrées** : `BAYERPAT` est obligatoire, `XBAYROFF`, `YBAYROFF` et
`ROWORDER` sont lus s’ils existent. Les mots-clés `RA`/`DEC` (ou
`OBJCTRA`/`OBJCTDEC`), `FOCALLEN` et `XPIXSZ` guident l’astrométrie ; `AIRMASS`
règle l’extinction atmosphérique (sans lui, l’atmosphère est ignorée) ;
`INSTRUME` permet de reconnaître le capteur.

Les masters déjà dématricés ne sont pas acceptés : un dématriçage erroné passe
inaperçu et fausse les couleurs (voir [Chaîne de mesure](MEASUREMENT.md#2-photometrie)).

<a id="5-sorties"></a>

## 5. Sorties

Pour chaque brute, `<brute>_filterAnalyze.json` et le dossier
`<brute>_filterAnalyze_work/` (fichiers de l’astrométrie Siril, réinitialisé à
chaque analyse). Le rapport contient :

| Clé | Contenu |
|---|---|
| `input`, `header` | Brute analysée et mots-clés utiles (`FILTER`, `INSTRUME`, `EXPTIME`…) |
| `sensor`, `airmass` | Capteur SPCC utilisé et masse d’air retenue |
| `astrometry` | Centre en degrés et échelle en secondes d’arc par superpixel |
| `stars` | Sources du champ, étoiles mesurées, motifs de rejet et étoiles utilisées |
| `scores` | Tous les candidats, triés du plus compatible au moins compatible, avec leur famille |
| `decision` | Statut, famille, filtre, écarts, trois premiers et filtres ambigus |
| `header_consistency` | Valeur `FILTER`, candidats correspondants et cohérence avec la famille retenue |

Un score réduit proche de 1 signifie des écarts compatibles avec le bruit et
l’incertitude du modèle ; plus il est grand, moins le filtre est compatible.

<a id="6-decision"></a>

## 6. Décision

Chaque candidat appartient à une famille : `narrowband` (bi-, tri- ou
quadri-bande), `light_pollution` (antipollution large bande), `uv_ir_cut`
(coupure UV/IR seule, y compris les filtres internes d’APN) ou `none` (sans
filtre). La table complète est `FILTER_FAMILIES` dans
`lib/filter_analysis.py`.

- `undetermined` : la meilleure famille ne devance pas la suivante d’au moins
  `--filter-family-margin` (0,5) ;
- `family` : la famille est retenue, mais le meilleur filtre ne devance pas le
  suivant de sa famille d’au moins `--filter-margin` (0,3). `ambiguous_with`
  liste les filtres trop proches ;
- `filter` : famille et filtre sont retenus.

Les écarts sont absolus : deux scores proches de zéro décrivent deux
ajustements parfaits, même si leur rapport est grand.

La cohérence avec `FILTER` cherche les candidats dont le nom contient la
valeur de l’en-tête, sans casse ni ponctuation (`L Extreme` → `Optolong
L-eXtreme`). Une valeur trop courte (`L`) ou sans correspondance donne
`consistent: null` ; sinon `consistent` indique si la famille retenue est
celle d’un des candidats correspondants.

<a id="7-erreurs"></a>

## 7. Erreurs possibles

| Message | Cause et remède |
|---|---|
| `Motif de Bayer absent ou inconnu` | Image déjà dématricée ou sans `BAYERPAT` |
| `Capteur inconnu pour INSTRUME=…` | Caméra non reconnue : indiquer `--filter-sensor` |
| `Échec de Siril : platesolve …` | Astrométrie impossible ; journal dans `<brute>_filterAnalyze_work/` |
| `Archive Gaia : …` | Archive de l’ESA indisponible ou limite atteinte ; relancer plus tard, le cache conserve ce qui est déjà téléchargé |
| `N étoiles exploitables, M requises` | Trop peu d’étoiles isolées, non saturées et assez lumineuses ; augmenter `--filter-max-g` ou baisser `--filter-min-snr` |

Le script retourne 0 si toutes les brutes ont été analysées, 1 si au moins une
a échoué (les autres sont tout de même traitées) et 130 après une interruption.

<a id="8-limites"></a>

## 8. Validation et limites

Vérifié le 20 octobre 2026 sous macOS avec Siril 1.4.1, sur 9 brutes d’une
ASI294MC Pro à 800 mm (options par défaut, 100 étoiles au plus) :

| Brutes | Filtre réel | Famille retenue | Écart avec la famille suivante | Écart dans la famille | Rang du filtre réel | `FILTER` |
|---|---|---|---|---|---|---|
| 4 × IC 5070, 120 s | Optolong L-Pro | `light_pollution` (4/4) | 2,0 à 4,1 | 0,08 à 0,21 | 3 à 5 | `L` : non comparable |
| 5 × NGC 6960, 300 s | Optolong L-eXtreme | `narrowband` (5/5) | 1,5 à 2,1 | 0,00 à 0,17 | 1 à 3 | `L Extreme` : cohérent |

La famille est retenue sur les 9 brutes, avec une avance bien supérieure au
seuil de 0,5. Dans la famille, le premier filtre ne devance jamais le suivant
de plus de 0,21 : le statut reste `family`, et le seuil de 0,3 évite d’annoncer
à tort Optolong L-QEF ou Askar C1, souvent classés devant le vrai filtre. Avec
le cache rempli, les 9 analyses prennent 11 s ; un champ neuf demande environ
2 minutes de téléchargement pour 100 spectres.

- Les spectres Gaia XP ont une résolution faible : une bande de 7 nm n’y est
  pas résolue, et les raies Hα et SII ne peuvent pas être distinguées.
- Les filtres d’une même famille donnent des couleurs voisines : le filtre
  exact n’est retenu que s’il se détache nettement.
- La table des familles et le capteur reconnu par `INSTRUME` (ASI294MC) ne
  couvrent que la base SPCC actuelle et le matériel testé.
- Les filtres à bande étroite absents de la base SPCC ne sont pas candidats,
  hormis l’Optolong L-eXtreme synthétisé (voir [Modèle](MODEL.md)).
