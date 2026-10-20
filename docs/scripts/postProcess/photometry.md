# Astrométrie, SPCC et orientation

[postProcess](README.md) › Astrométrie et couleurs

`PhotometricColorCalibrator` dans `lib/postprocess.py` reçoit un FITS RGB
linéaire et produit un FITS étalonné ainsi qu’un rapport JSON. Siril 1.4 ou
plus récent et ses données SPCC sont nécessaires. Le traitement ne vérifie
pas automatiquement que l’image est linéaire : fournir une image non étirée.

## Méthode et catalogues

Le traitement charge l’image, exécute `platesolve -force -catalog=gaia`, puis
`spcc -catalog=gaia`, et sauvegarde dans un dossier de travail neuf. Gaia est
explicitement demandé, indépendamment du catalogue choisi dans l’interface.
Siril peut exploiter sa base astrométrique Gaia locale lorsqu’elle est disponible,
même avec `-catalog=gaia`. L’astrométrie et l’étalonnage des couleurs sont
systématiquement refaits lorsque l’étape est active, même avec un WCS ou une
calibration antérieure. `--photometry-force` reste accepté pour compatibilité ;
une ancienne valeur de configuration `photometry_force=false` ne change pas
ce comportement. `--no-photometry-force` n’est plus accepté. Lorsque des
coordonnées du centre sont connues, elles suivent directement le nom de la
commande (`platesolve 270.6,-23 -force …`) : Siril 1.4.1 les refuse si elles
sont placées après `-force`.

SPCC confronte les flux stellaires mesurés dans l’image aux flux prédits à
partir des spectres Gaia DR3 et des réponses spectrales de l’instrument. Siril
ajuste les rapports rouge/vert et bleu/vert, calcule les coefficients de balance
des blancs et neutralise le fond. La référence de blanc est également un
paramètre du calcul. Le module délègue ce calcul à Siril ; il ne fait aucun
étirement de l’histogramme.

`--photometry-catalog localgaia` choisit le catalogue spectral Gaia local de
Siril ; un catalogue astrométrique local seul ne suffit pas pour SPCC. Le
catalogue distant et l’installation des données SPCC nécessitent le réseau.
`--photometry-method pcc --photometry-catalog nomad` choisit explicitement PCC
sur NOMAD ; les paramètres spectraux SPCC sont alors refusés.

## Profils instrumentaux

Les noms de profils doivent correspondre exactement aux entrées de la base
SPCC Siril. Un nom contenant des espaces est protégé comme un seul argument
dans le script généré. Les caractères pouvant casser le script sont refusés.

- Caméra couleur : `--photometry-osc-sensor` et `--photometry-osc-filter` ;
  `--photometry-osc-lpf` permet de préciser le passe-bas d’un boîtier photo.
- RGB composé avec une caméra mono : `--photometry-mono-sensor`,
  `--photometry-red-filter`, `--photometry-green-filter`, `--photometry-blue-filter`.
- Référence de blanc : `--photometry-white-reference`.

Les deux types de capteurs sont exclusifs. Les combinaisons explicitement
incompatibles entre type de capteur et filtres sont refusées. Les paramètres
non précisés restent ceux mémorisés par Siril, sauf le filtre OSC. Pour celui-ci,
la priorité est : option CLI > configuration du projet > champ FITS `FILTER` >
`No filter` si le champ est absent ou vide. Le nom inscrit dans `FILTER` doit
correspondre exactement au profil SPCC ; aucun alias n’est deviné. Un nom
inconnu entraîne un échec Siril, sans remplacement silencieux par un autre filtre.
Les caractères pouvant casser le script et les valeurs non textuelles sont
refusés avant Siril lorsque le champ est utilisé. Le capteur n’est pas déduit du
FITS. Pour un RGB composé avec des profils mono déclarés, `FILTER` ne permet
pas de déduire les trois filtres : préciser les options rouge, vert et bleu.
Le module ne vérifie pas les préférences Siril non remplacées.
Préciser les profils rend l’exécution reproductible d’une installation à l’autre.
Ces options peuvent être mémorisées dans la configuration du projet avec `-S`.

Pour une Ares-C Pro (Sony IMX533), sans filtre supplémentaire, sur une image
RGB linéaire de M33 possédant déjà un WCS, les options vérifiées sont :

```text
--photometry-osc-sensor "Sony IMX533"
--photometry-osc-filter "No filter"
--photometry-white-reference "Average Spiral Galaxy"
```

Cette combinaison a été exécutée avec Siril 1.4.4 sur M33 : SPCC a utilisé
Gaia DR3 `xp_sampled` et trouvé une solution avec 370 étoiles après une nouvelle
résolution astrométrique Gaia et un retournement vertical. Ce contrôle
valide cette configuration ; il ne garantit pas la qualité d’un autre champ
ou d’une image déjà étirée. La saturation, un mauvais profil ou un nombre
insuffisant d’étoiles exploitables peuvent dégrader ou empêcher l’étalonnage.

## Orientation et audit

Le post-traitement refait l’astrométrie et autorise Siril à retourner l’image
à chaque exécution de l’étape, comme une nouvelle résolution dans l’interface. Le retournement
est décidé par Siril selon la solution, et n’est pas appliqué systématiquement.
Sur M33, ce comportement produit un retournement vertical.
Avec `--photometry-noflip`, Siril ne retourne pas l’image lors de la résolution.
Cette option conserve le sens des pixels ; elle n’effectue pas de rotation vers le nord. SPCC agit sur les couleurs.

Le journal principal indique la méthode, les catalogues, les commandes et les
profils explicitement choisis. Le journal Siril conservé dans le dossier de
travail décrit les profils effectivement utilisés, les étoiles retenues,
les coefficients et la réussite ou l’échec du calcul.

Le JSON contient notamment `method`, `solve_catalog`, `color_catalog`,
`platesolve_command`, `calibration_command`, `spcc_command` ou `pcc_command`,
`spectral_profiles` (paramètres transmis), `filter_source` (`options`,
`FITS FILTER`, `default` ou nul hors filtre OSC), `unspecified_profiles_source`,
`input_has_wcs`, `force_solve`, `flip_allowed`, `input_row_order` et
`output_row_order`. `ROWORDER` décrit l’ordre de stockage des lignes, pas à lui
seul l’orientation céleste ; il faut consulter le WCS pour cette dernière.
Le FITS n’est publié qu’après réussite de Siril, vérification des dimensions RGB
et présence d’un WCS céleste. Les fichiers sources sont conservés.

## Références

- [SPCC dans Siril](https://siril.readthedocs.io/en/stable/processing/color-calibration/spcc.html).
- [Commandes Siril](https://siril.readthedocs.io/en/stable/Commands.html).
- [Ares-C Pro et capteur IMX533](https://www.player-one-astronomy.com/product/ares-c-pro-usb3-0-color-camera-imx533/).

Les produits de photométrie sont conservés dans `<rapport>_work/001/`, par exemple
`02_photometry_work/001/`. Ce dossier visible est réinitialisé à chaque lancement,
sans suffixe aléatoire ni répertoire temporaire. Une entrée située dans le dossier
réinitialisé est refusée ; les fichiers sources extérieurs sont préservés.
