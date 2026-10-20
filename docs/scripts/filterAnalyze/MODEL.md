# Modèle direct et score de compatibilité

[Documentation](../../README.md) › [Scripts](../README.md) › [filterAnalyze](README.md) › Modèle

Cette page décrit `lib/spectral_response.py` et `lib/filter_model.py`.

<a id="1-courbes-spectrales"></a>

## 1. Courbes spectrales

Toutes les courbes sont rééchantillonnées sur une grille de **300 à 1100 nm,
au pas de 0,5 nm**, et exprimées entre 0 et 1. Hors de l’intervalle mesuré,
la réponse est nulle.

- **Capteurs et filtres large bande** : base SPCC de Siril (GPLv3), lue depuis
  l’installation de Siril. Les réponses en pourcentage (`range = 100`) sont
  ramenées à 1 ; les longueurs d’onde en angströms (filtres d’APN) sont
  converties en nanomètres. Chaque courbe garde son `dataQualityMarker`.
- **Filtres à bande étroite et bi-bandes** : absents de la base SPCC par
  choix de ses auteurs. Chaque bande est synthétisée par une super-gaussienne
  d’ordre 8, `T(λ) = T_max · exp(−ln 2 · |2(λ − λ₀)/FWHM|⁸)`, qui vaut exactement
  `T_max/2` à `λ₀ ± FWHM/2`. L’Optolong L-eXtreme est modélisé par deux bandes de
  7 nm centrées sur 500,7 nm (OIII) et 656,3 nm (Hα), avec une transmission
  maximale supposée de 90 %.
- **Atmosphère** : `T_atm(λ) = 10^(−0,4 · k(λ) · X)`, où `X` est la masse
  d’air et `k(λ) = 0,0088 · λ[µm]^−4,15 + 0,08 · (λ/550 nm)^−1,3` en magnitudes
  par masse d’air (Rayleigh au niveau de la mer et aérosols d’un site de
  plaine). L’ozone et les bandes moléculaires sont négligés.

<a id="2-flux-simules"></a>

## 2. Flux simulés

Pour une étoile de densité spectrale d’énergie `F(λ)`, le flux du canal
`c ∈ {R, G, B}` est proportionnel au nombre de photons reçus :

`M_c = Σ_λ F(λ) · λ · T_atm(λ) · T_filtre(λ) · S_c(λ) · Δλ`

Les constantes communes (surface, temps de pose, gain, transmission des
optiques supposée neutre) ne sont pas modélisées : elles sont absorbées par le
score.

<a id="3-score"></a>

## 3. Score de compatibilité

Le score compare des **couleurs**, et non des flux, pour annuler les pertes
achromatiques propres à chaque étoile (ouverture photométrique, flat imparfait,
voile nuageux). Pour chaque étoile `s` et chaque couleur `k ∈ {R/G, B/G}` :

- `d = ln(O_k / O_G) − ln(M_k / M_G)`, écart entre couleur observée et simulée ;
- `σ² = (σ_Ok/O_k)² + (σ_OG/O_G)² + 2·σ_modèle²`, avec `σ_modèle = 2 %` par défaut
  pour les erreurs des courbes et des spectres ;
- un décalage constant par couleur, équivalent à une balance des blancs, est
  estimé par une moyenne robuste de Huber (seuil 3σ) ;
- le score réduit vaut `2 · Σ ρ_Huber(résidu/σ) / (2N − 2)`.

`score_filter` calcule ces couleurs à partir des flux ; `score_colours` part
directement des couleurs et de leurs écarts-types, par exemple moyennés sur
plusieurs poses (voir [Combinaison d’une série](README.md#6-decision)).

Avec le bon filtre, le score est proche de 1 lorsque les incertitudes sont
justes (inférieur à 1 si elles sont surestimées). Avec un mauvais filtre, les
résidus dérivent avec la couleur des étoiles et le score augmente. La perte de
Huber limite l’influence d’une étoile aberrante sans exclure d’étoile, de
sorte que tous les filtres sont évalués sur le même échantillon.

<a id="4-validation"></a>

## 4. Validation actuelle et limites

Validation **synthétique** (tests `tests/test_filter_model.py` et
essai sur 150 corps noirs de 3500 à 12 000 K, capteur Sony IMX294, masse d’air
1,1, bruit de 2 % par canal, 47 candidats) :

| Vrai filtre | Score du vrai filtre | Score du L-Pro | Score du L-eXtreme |
|---|---|---|---|
| Optolong L-eXtreme | 0,50 | 4,84 | — |
| Optolong L-Pro | 0,57 | — | 4,87 |

- Les **familles** se distinguent nettement : bi-bande, antipollution large
  bande, UV/IR seul, sans filtre.
- À l’intérieur d’une famille, les écarts sont faibles : avec 5 % de bruit,
  le L-Pro n’est que troisième, à égalité avec IDAS LPS-P2/P3 et SV260 ; le
  L-eXtreme reste premier, mais à peine devant les autres bi-bandes.
- Les corps noirs n’ont pas de raies d’absorption ; les vrais spectres
  stellaires (Balmer, bandes moléculaires) modifient surtout les flux en bande
  étroite. La reconstruction à partir de Gaia XP, de résolution faible, ne
  résout pas une bande de 7 nm.

Les résultats sur images réelles sont dans le [manuel](README.md#8-limites).

<a id="5-biais"></a>

## 5. Biais du modèle à l’intérieur d’une famille

Étude du 20 octobre 2026 sur les deux séries réelles du manuel, combinées
(`--combine`, 100 étoiles chacune) : 4 brutes L-Pro, où le vrai filtre est
4ᵉ derrière L-QEF, et 5 brutes L-eXtreme, où il est 3ᵉ derrière Askar C1.

- **Signal faible.** La dispersion des couleurs d’une étoile à l’autre est
  d’environ 3 %, contre 0,4 à 0,8 % d’erreur de mesure. Une fois retirée une
  pente linéaire en BP − RP, les cinq meilleurs filtres antipollution ont la
  même dispersion : seule une pente de 1 à 4 % par magnitude de BP − RP les
  sépare.
- **Sensibilité aux erreurs plausibles.** Incliner la réponse du capteur de
  ±7 % entre 400 et 700 nm, ou passer la masse d’air de 1 à 2, change l’ordre
  de L-QEF, LPS-P2, LPS-P3 et SV260 ; le L-Pro ne passe jamais premier.
- **Étoiles rouges.** Le L-Pro perd surtout sur les étoiles de BP − RP > 2,5,
  dont le B/G observé dépasse de 7 % le modèle. Sans elles (BP − RP ≤ 2,0),
  il passe premier, mais à égalité avec SV260, L-QEF et LPS-P3 (écarts de
  0,00 à 0,03). Le L-eXtreme passe premier pour BP − RP ≤ 1,5. Les étoiles
  rouges portent à la fois le pouvoir de séparation et le biais.

| Hypothèse testée | Effet | Verdict |
|---|---|---|
| Fuite rouge de 1 à 2 % dans le canal bleu du capteur | Chaque vrai filtre gagne un rang, sur les deux séries, sans passer premier | Contribution partielle |
| Bandes décalées vers le bleu par le faisceau convergent (2 à 8 nm) | Classement dégradé | Rejetée |
| Spectres Gaia XP trop lissés | Les bandes d’oxyde de titane des étoiles M (590–630 et 670–710 nm) tombent là où L-Pro et L-QEF diffèrent | Cause la plus probable, non testable sans spectres mieux résolus |

Conclusion : avec ces données et ce modèle, les filtres d’une même famille ne
sont pas départageables, et le statut `family` est la réponse correcte. Un
étalonnage de la réponse du capteur sur des brutes de filtre connu (sans
filtre ou UV/IR seul) pourrait réduire la part instrumentale du biais ; avec
seulement deux séries, il risquerait de s’ajuster aux données.
