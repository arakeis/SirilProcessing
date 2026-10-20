# Rendu final AutoGHS

[postProcess](README.md) › AutoGHS

La phase AutoGHS, activée par défaut, termine le pipeline existant, après la
restauration, sur son résultat **RGB linéaire avec étoiles**. Elle effectue une
séparation StarNet, un étirement dédié aux étoiles, puis deux optimisations du
fond sans étoiles et deux recompositions. Les étapes amont gardent leur ordre.
La phase est activée par défaut ; `--disable-autoghs` la désactive même si
elle a été mémorisée dans la configuration.

## Prérequis et entrée

- Dépendances habituelles de postProcess : NumPy, Astropy, SciPy et Matplotlib.
- **Siril 1.4.x et StarNet++ V2** pour l'adaptateur historique `starnet -stretch`.
  Validation locale : Siril Flatpak 1.4.4, StarNet++ 2.0.2. Le script installé
  `StarNet.py` cible StarNet 2.5 et n'est pas utilisé avec le binaire V2.
- FITS RGB à trois plans `(3, hauteur, largeur)`, linéaire, dématricé, étoilé.
  Les entiers sont normalisés selon le mécanisme existant `normalized_planes` ;
  les flottants doivent déjà être dans `[0,1]`. NaN, Inf, valeurs hors domaine,
  monochrome, CFA et entrée déclarée starless sont refusés.
- Les images marquées `SPNLIN=True`, ou `SPROLE=STARLESS/STARS`, sont refusées. L'absence de cette carte
  **ne prouve pas la linéarité** : celle-ci relève du contrat du pipeline ou de
  l'utilisateur pour un fichier externe. Aucun diagnostic d'histogramme ne
  permet de certifier qu'une image a conservé sa réponse linéaire.

L'installation de StarNet et de son modèle reste externe au dépôt. Les
bibliothèques et le modèle doivent être accessibles depuis le mode Siril
choisi. L'adaptateur échoue explicitement si StarNet ne peut pas fonctionner.
Sur l'installation V2 testée, un essai 256 × 256 a échoué ; utiliser au moins
512 × 512 pour la validation réelle.

## Lancement et chemin StarNet sauvegardé

Avec le venv existant, pour ajouter le rendu à toute la chaîne :

```bash
.venv/bin/python bin/postProcess.py image_RGB_lineaire.fits rapports/ \
  --enable-autoghs --ghs-strategy both --compute-backend cpu \
  --starnet-path /chemin/StarNetv2CLI_linux/starnet++ --save-config
```

Le lanceur `bin/postProcess.sh` accepte les mêmes arguments et prépare le venv
comme décrit dans [Installation](../../INSTALLATION.md). Il ne possède pas de
mécanisme AutoGHS distinct. Aucun nouveau lanceur n'est nécessaire.

`--starnet-path` suit la priorité **CLI > configuration JSON > découverte dans
les préférences Siril**. Sans chemin explicite, la découverte lit
`core.starnet_exe` dans `config.1.4.ini`, puis `config.ini`, du mode choisi :

- Flatpak : `~/.var/app/org.siril.Siril/config/siril/` ;
- natif/AppImage : `$XDG_CONFIG_HOME/siril/`, ou `~/.config/siril/` ;
- macOS (hors Flatpak) : `~/Library/Application Support/org.siril.Siril/siril/`.

Avec AutoGHS actif et `-S/--save-config`, le point d'entrée résout aussi le chemin
découvert et le sauvegarde sous la clé **`starnet_path`**, en chemin absolu. Le
fichier par défaut reste `~/.siril_darklib_config.json` ; `--config fichier.json`
en sélectionne un autre. Sans `-S`, aucune configuration n'est sauvegardée.
Les préférences Siril sont copiées dans le travail de l'étape et passées avec
`-i` : la séparation ne remplace pas les préférences personnelles de Siril.

Pour ne faire que le rendu d'un résultat linéaire déjà restauré :

```bash
.venv/bin/python bin/postProcess.py image_RGB_lineaire.fits rapports/ \
  --disable-gradient --disable-photometry \
  --disable-deconvolution --disable-denoise \
  --enable-autoghs --ghs-strategy both --compute-backend cpu
```

Cette forme a été exécutée sur un extrait réel de M33 dans les tests
[d'intégration](../../../tests/README.md). La validation de la phase n'impose pas
de réexécuter la calibration, la photométrie ou la restauration.

## Sorties et publication

Le dossier d'étapes habituel contient `05_autoghs.json` et le dossier visible
`05_autoghs_work/`, sans suffixe aléatoire ni dossier temporaire. Le numéro 05
reste fixe quand la restauration regroupe les étapes 03/04. Les transformations
sont ordonnées dans les sous-dossiers suivants :

```text
05_autoghs_work/
  001/separation_work/  # entrée, fond et étoiles linéaires, script et journal Siril
  002_stars/           # couche d’étoiles rendue commune
  003_ghs/             # fonds étirés et comparatifs PNG
  004_recomposition/   # résultats finaux avec étoiles, FITS et JPEG
  005_diagnostics/     # graphiques et rapport détaillé
```

Les fichiers sont répartis dans ces sous-dossiers :

| Fichier | Contenu |
|---|---|
| `<image>_render_range.fits` | **Résultat principal étoilé**, stratégie range |
| `<image>_render_peak.fits` | **Résultat principal étoilé**, stratégie peak |
| `<image>_render_range.jpg`, `<image>_render_peak.jpg` | Exports JPEG RGB pleine résolution des résultats finaux |
| `<image>_ghs_comparison_starless.png` | Comparatif sans étoiles dans `003_ghs/` |
| `<image>_ghs_comparison_with_stars.png` | Comparatif avec étoiles dans `003_ghs/` |
| `<image>_starless_ghs_range.fits` | Fond étiré range pour comparaison |
| `<image>_starless_ghs_peak.fits` | Fond étiré peak pour comparaison |
| `<image>_stars_render.fits` | Couche d'étoiles étirée commune aux deux résultats |
| `<image>_stars_render.jpg` | Couche d'étoiles entière en JPEG, dans `002_stars/` |
| `<image>_stars_diagnostic.png` | Étoiles seules : extraits avant/après, histogrammes log et bilan d'adaptation dans `002_stars/` |
| `<image>_ghs_report.json` | Rapport complet, paramètres, histogrammes et métriques |
| `<image>_ghs_histograms.png` | Sans étoiles : entrée, étape intermédiaire et rendu final ; axes Y linéaire et logarithmique |
| `<image>_ghs_histograms_with_stars.png` | Avec étoiles : rendu final recomposé seul ; axes Y linéaire et logarithmique |
| `separation_work/` | FITS linéaires, script, préférences isolées et journal StarNet |

`both` est le défaut. `range` ou `peak` produit seulement la variante choisie.
Le rapport expose les résultats principaux dans `output_images`. Pour rester
compatible avec les consommateurs de `output_image`, cette clé et l'export
FITS historique de postProcess désignent **range**, ou peak lorsque seul peak
est demandé. Le JPEG principal est également copié sous
`<image>_postprocess.jpg` à côté du FITS final. Les deux résultats principaux de `both` restent dans le dossier
publié ; l'export historique ne les fusionne pas et ne les départage pas.

Les métadonnées et extensions du FITS source sont conservées, ainsi que WCS et
`ROWORDER`. Les anciennes cartes entières `BZERO/BSCALE/BLANK` sont retirées,
les bornes recalculées et `BUNIT` devient dimensionless (`1`). `SPROLE` identifie chaque branche (`STARLESS`, `STARS`, `WITHSTARS`). Les rendus sont float32 et marqués **`SPNLIN=True`** avec HISTORY :
ce sont des images de présentation non linéaires, impropres à des mesures de
flux linéaires. La source reste intacte. Les JPEG sont quantifiés sur 8 bits, qualité 95, sans
étirement ni gamma supplémentaire. Les comparatifs PNG et les histogrammes
sont des figures de présentation et de diagnostic. Le rapport fournit
leurs chemins dans `histogram_paths` (`starless` et `with_stars`) ;
`histogram_path` conserve le chemin de la figure sans étoiles.

Les produits sont écrits directement dans cette arborescence visible. Au
lancement suivant, le dossier de travail de l’étape est réinitialisé, comme
celui des autres traitements ; copier ailleurs les produits à conserver avant
une relance. Une entrée située dans ce dossier est refusée pour la préserver.
Le rapport de réussite n’est écrit qu’après les deux rendus demandés. En cas
d’erreur, le rapport indique `ERROR` et les produits partiels et journaux restent
disponibles pour diagnostic ; leur présence ne signifie pas que l’étape a réussi.
Les rapports JSON utilisent un fichier visible `.pending` en suffixe avant
remplacement, sans création de répertoire temporaire.

## Paramètres

Tous les réglages ci-dessous sont persistants avec `-S`. Les défauts sont
expérimentaux et configurables ; ils ne constituent pas des normes de qualité
astronomique.

| Option | Défaut | Rôle |
|---|---|---|
| `--ghs-strategy` | `both` | `both`, `range` ou `peak` |
| `--compute-backend` | `auto` | Politique commune de postProcess ; NumPy/CuPy pour le GHS |
| `--ghs-max-iterations` | `8` | Limite de 1 à 32 recherches GHS |
| `--ghs-dynamic-target` | `1.0` | Étendue RGB minimale du fond après GHS, dans `]0,1]` ; par exemple `0.8` |
| `--ghs-dynamic-max-iterations` | `32` | Limite de 1 à 64 passages d’expansion linéaire |
| `--ghs-histogram-strength` | `0.7` | Égalisation globale partielle, de 0 (désactivée) à 1 |
| `--ghs-histogram-clip` | `4.0` | Plafond d’effectifs relatif à la moyenne, de 1 à 16 |
| `--ghs-bins` | `4096` | Histogramme, de 64 à 65536 classes |
| `--ghs-q-low`, `--ghs-q-high` | `0.1`, `99.9` | Percentiles en pourcentage |
| `--ghs-min-gain` | `0.01` | Amélioration relative minimale |
| `--ghs-plateau-fraction` | `0.2` | Fraction du meilleur gain marginal définissant un plateau |
| `--ghs-max-clip` | `0.001` | Fraction maximale de nouveaux pixels écrêtés par contrôle |
| `--ghs-max-noise-gain` | `30` | Limite cumulée des proxys bruit et IQR |
| `--ghs-color-mode` | `human` | Luminosité pondérée human ou moyenne `even` |
| `--ghs-chroma` | `off` | `off`, `balanced`, `enhanced` ; RGB expérimental |
| `--star-render` | `conservative` | Rendu asinh commun des étoiles |
| `--star-strength` | `2.0` | Force asinh, dans `]0,20]` |
| `--star-faint-boost` | `5.0` | Renforcement des étoiles faibles, de 1 (ancien rendu) à 10 |
| `--star-histogram-strength` | `0.8` | Répartition des amplitudes des pics en logarithme, de 0 (gain fixe) à 1 ; réduite si la garde FWHM le demande |
| `--star-ceiling` | `0.85` | Plafond du maximum RGB des étoiles seules |
| `--star-max-width-ratio` | `2.0` | Rapport FWHM médian maximal, si mesurable |
| `--star-max-color-drift` | `0.08` | Dérive moyenne maximale de chromaticité RGB après fusion |
| `--star-max-chroma-excess` | `0.10` | Hausse moyenne maximale de chroma RGB après fusion |
| `--ghs-negative-tolerance` | `0.005` | Seuil d’alerte des résidus négatifs, dans `[0,0.05]` ; compensation conservant la somme linéaire |
| `--ghs-headroom` | `0.95` | Facteur commun du fond avant fusion screen |

Les plages `[0,1]` s'expriment en unités Siril normalisées, les fractions ne
sont pas des pourcentages. Les mesures de couleur ne prétendent pas décrire
une colorimétrie perceptuelle calibrée.

## Erreurs, résultats et limites de validation

Les dépassements négatifs StarNet corrigeables sont compensés avant étirement,
avec avertissement et mesures dans `residual_compensation`. Ils n’interrompent
pas le rendu. Les couches corrigées doivent rester finies et bornées ; voir
la [politique de compensation](star-rendering.md#politique-des-résidus-négatifs).

Une panne StarNet, CUDA en cours de calcul, FITS, disque ou publication est
**fatale**, sans reprise CPU ou substitution de rendu. La CLI retourne `1`.
Le rapport d'étape porte `ERROR` si son écriture est possible et conserve le
chemin du dossier de travail pour diagnostic. Un arrêt de recherche sans gain est
normal : `NO_IMPROVEMENT`, avec recomposition malgré tout des branches valides.
Le statut global `SUCCESS` signifie qu’au moins une stratégie a appliqué une transformation,
pas qu'une expertise visuelle certifie la qualité astronomique.

Le choix hérite de la [politique générale de calcul](README.md#choix-du-calcul-cpugpu).
CPU seul a été exécuté sans CuPy. Le backend `auto` teste CUDA avant la
séparation, avec une estimation des temporaires et une marge de VRAM de 20 %.
`cuda` exige un moteur fonctionnel. Le backend StarNet reste indépendant.
La comparaison matérielle CPU/CUDA reste à effectuer sur une machine CuPy/CUDA
opérationnelle ; le test correspondant est ignoré quand elle manque.

Les validations numériques Siril et une exécution réelle complète sur un
extrait de M33 sont disponibles. La qualification visuelle sur nébuleuse,
IFN, bande étroite, fond fortement bruité et étoiles très brillantes reste à
réaliser. Les heuristiques ne peuvent pas distinguer universellement un détail
diffus d'une amplification de bruit. Un noyau déjà saturé n'est pas restauré.

## Références spécialisées

- [Moteur GHS, histogrammes, optimisation et backends](auto-ghs-algorithm.md).
- [StarNet, rendu stellaire et recomposition](star-rendering.md).
- [Tests et procédure de validation réelle](../../../tests/README.md).

Un encart par stratégie rappelle son objectif et résume la boucle GHS : recherches
ayant évalué des candidats / limite configurée, GHS acceptés, recherches sans
application, nombre de candidats examinés et corrections du point noir appliquées.
Il indique la raison d’arrêt et la largeur initiale/finale du critère, avec son
gain relatif si la largeur initiale est positive. Ces mesures concernent le fond
avant fusion, y compris sur la figure avec étoiles. Un arrêt avant toute recherche
(distribution constante ou pic ambigu) compte zéro recherche ; la chroma ne compte
pas comme une itération GHS. Les données absentes ne sont pas remplacées par zéro.

La seconde boucle complète les GHS si `max(RGB)-min(RGB)` n’atteint pas la cible.
Chaque passage recale le point noir sur la première intensité RGB strictement
positive et applique un gain commun borné. Le point noir est également recalé
avant chaque recherche GHS. L’ancienne option `--ghs-black-margin` n’est plus
utilisée. Les encarts et le rapport `dynamic_range` indiquent les passages,
les étendues et l’atteinte de la cible ; une image constante reste inchangée.
La cible porte sur le fond sans étoiles avant la marge de recomposition.
Voir les [règles de la seconde boucle](auto-ghs-algorithm.md#boucle-complémentaire-dexpansion-de-la-dynamique).

Pour viser une étendue de 0,8 et enregistrer ce choix dans la configuration :

```bash
bin/postProcess.sh image_RGB.fit --ghs-dynamic-target 0.8 --save-config
```

La valeur est résolue selon CLI > configuration > défaut (1,0). Une ancienne
valeur sauvegardée reste prioritaire ; `--ghs-dynamic-target 1 --save-config`
permet de la remplacer explicitement.

Pour relever davantage les structures diffuses et les étoiles faibles, les réglages
`--ghs-histogram-strength` (défaut 0,7) et `--star-faint-boost` (défaut 5)
sont indépendants et persistants avec `--save-config`. Le premier égalise
partiellement les intensités du fond, sous plafond de contraste ; le second
renforce uniquement la couche stellaire extraite. Les valeurs 0 et 1,
respectivement, désactivent ces deux ajouts. L'adaptation stellaire est pilotée
séparément par `--star-histogram-strength` (défaut 0,8 ; 0 la désactive).
Le diagnostic dédié et les exports des étoiles se trouvent dans `002_stars/`.
Voir les pages
[algorithme](auto-ghs-algorithm.md) et [étoiles](star-rendering.md).

Les deux comparatifs PNG sont générés automatiquement dans `003_ghs/` et gardent
les images avec étoiles séparées de celles sans étoiles. Ils montrent RANGE et
PEAK, ou la seule stratégie demandée. Si le rapport précédent est exploitable,
ses images sont capturées avant réinitialisation et affichées sur une ligne
« exécution précédente », face aux rendus actuels. En l’absence d’historique,
seuls les rendus actuels sont affichés, sans inventer d’avant traitement.

Le rapport fournit `comparison_paths`, `comparison_previous`, `output_jpegs` et
`output_jpeg` (JPEG principal), ainsi que `output_jpeg` dans chaque branche.
Voir [exports et comparatifs](render-exports.md) pour l’orientation, la conversion
RGB et les limites de ces formats.
