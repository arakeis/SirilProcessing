# GraXpert : inférence native ONNX et acquisition des poids

[postProcess](README.md) · [Qualité astrophotographique](quality.md)

Le débruitage utilise directement ONNX Runtime dans notre processus Python.
`GraXpert-linux` ne traite pas les images utilisateur : il intervient seulement
si un poids manque et n’est pas déjà disponible dans un cache GraXpert/Siril.
Le moteur est activé automatiquement si des poids locaux valides sont présents
dans le cache du projet ou dans un cache GraXpert/Siril. Il conserve les contrôles
communs des candidats (étoiles aux positions initiales, bruit, anneaux et signal
diffus).

## Classes et dépendances

- `GraXpertDenoiseProcessor` (`lib/graxpert.py`) produit, contrôle et publie son
  candidat ; les autres moteurs restent indépendants.
- `GraXpertEngine` (`lib/graxpert_inference.py`) effectue l’inférence et restitue
  le FITS avec sa géométrie, son orientation, ses unités, son WCS et ses autres HDU.
- `GraXpertModels` (`lib/graxpert_models.py`) vérifie, importe ou acquiert le
  modèle. La version et l’empreinte sont fixées dans `graxpert_models.json`.

Les services héritent de `ParameterizedComponent` et déclarent leurs enfants ;
les paramètres suivent CLI > configuration JSON > défauts. Le manifeste contient
uniquement les métadonnées, pas les poids. Les modèles restent exclus de Git et
de l’archive dans `tmp/models/graxpert/3.0.2/model.onnx` par défaut.

ONNX Runtime est une dépendance optionnelle :

```bash
bin/postProcess.sh --install-graxpert
```

Ce lancement installe le runtime CPU dans le venv du projet. Les poids sont
acquis au premier traitement. Pour un GPU NVIDIA, installer la variante
`onnxruntime-gpu` compatible avec l’environnement CUDA à la place du runtime
CPU ; le projet ne prétend pas qu’un runtime CPU fournit CUDA.

```bash
bin/postProcess.sh image_RGB.fits sorties/ --enable-graxpert
```

Si les poids sont déjà présents, `--enable-graxpert` peut être omis. Cette option
force l’activation et autorise l’acquisition des poids manquants.
`--no-enable-graxpert` désactive le moteur même si les poids existent.
L’activation ajoute GraXpert à la comparaison ; elle n’impose pas son candidat.
`--restoration-compare-chains` inclut le moteur dans les chaînes complètes.

Le choix suit CLI > configuration JSON > automatique. La valeur sauvegardée
`enable_graxpert: null` (ou une clé absente) conserve le mode automatique ;
`true` force l’activation et `false` la désactive. Une ancienne configuration
contenant `false` reste prioritaire. La détection vérifie taille/SHA256 sans copier
ni télécharger les poids. S’ils manquent ou sont corrompus dans tous les caches,
le mode automatique laisse GraXpert inactif ; seul un choix explicite d’activation
autorise alors leur acquisition. ONNX Runtime reste nécessaire au traitement :
son absence est auditée et les autres moteurs continuent.

## Acquisition automatique

La version prise en charge est **3.0.2**, explicitement épinglée. Une configuration
ancienne contenant `graxpert_model_version: null` utilise cette version. Toute
version inconnue du manifeste est refusée plutôt qu’interprétée arbitrairement.

À chaque besoin de poids, le gestionnaire :

1. Vérifie le cache du projet par taille et SHA256.
2. S’il manque ou est corrompu, recherche le poids dans les caches GraXpert natif
   (`$XDG_DATA_HOME/GraXpert`, ou `~/Library/Application Support/GraXpert` sous
   macOS) et Siril Flatpak. Un fichier conforme est copié sans modifier sa source.
3. Sinon, invoque le mécanisme officiel GraXpert sur un FITS synthétique jetable,
   avec version explicite et CPU. Les répertoires XDG de données, configuration
   et cache sont temporaires ; les préférences utilisateur restent intactes.
4. Vérifie le fichier reçu puis le remplace atomiquement dans le cache du projet.
   Un téléchargement invalide laisse le fichier précédent intact.

L’empreinte **e61c880e7fb955917e91141660e66801c9de5c4f3d9946dc449e5a7dd7346563**
et la taille **477703971 octets** ont été observées dans le modèle 3.0.2 déjà
installé par le gestionnaire Siril et validé par inférence. Ce n’est pas une
signature publiée par l’éditeur : la provenance de cette empreinte est auditée.
Le manifeste prévient les changements ultérieurs et les fichiers incomplets.

La distribution officielle repose sur le catalogue S3 de GraXpert ; le script
Siril utilise lui aussi le programme GraXpert pour acquérir les poids.
Nous n’inventons pas d’URL publique ni ne reproduisons ses identifiants internes.
Sans poids local ni exécutable d’acquisition, le moteur est écarté avec une raison
explicite. Dès que les poids sont installés, l’inférence fonctionne sans GraXpert.

## Paramètres

| Option | Défaut | Rôle |
|---|---|---|
| `--enable-graxpert` / `--no-enable-graxpert` | automatique si poids locaux valides | Forcer l’activation / désactiver le moteur |
| `--graxpert-model-dir` | `tmp/models/graxpert` dans le projet | Cache de poids |
| `--graxpert-model-version` | `3.0.2` | Version épinglée et prise en charge |
| `--graxpert-path` | `GraXpert-linux` (macOS : `/Applications/GraXpert.app/Contents/MacOS/GraXpert`) | Exécutable utilisé seulement pour l’acquisition |
| `--graxpert-strength` | 0,5 | Mélange relatif, de 0 à 1 |
| `--graxpert-batch-size` | 1 | Nombre de tuiles par appel ONNX, de 1 à 32 |
| `--graxpert-gpu` / `--no-graxpert-gpu` | `null` (hérite du choix général) | Surcharge GPU/CPU explicite |
| `--graxpert-cpu-fallback` | faux | Autoriser un redémarrage complet sur CPU |

Un modèle local conforme rend `--graxpert-path` inutile. Les options booléennes
acceptent leurs variantes `--no-…`. `-S` mémorise les réglages selon les règles
communes, sans intégrer les poids au fichier de configuration.

## Contrat numérique

Le modèle 3.0.2 reçoit des tenseurs **NHWC float32**, 256 × 256 × 3. Une image mono
est dupliquée sur trois canaux, puis le premier canal est restitué. Les FITS CFA
non dématricés, les pixels non finis, le MAD nul et les contrats ONNX incompatibles
sont refusés. Les entrées flottantes et uint16 sont prises en charge.

Pour chaque canal, la médiane et le MAD sont mesurés sur un pixel sur quatre dans
les deux dimensions. La normalisation est `0,04 × (image − médiane) / MAD` ;
l’inversion est `prédiction / 0,04 × MAD + médiane`. Ce MAD sert au modèle, pas au
score de qualité du fond de ciel. Les pixels normalisés au-dessus du seuil 10 sont
conservés, suivant le script Siril.

Les tuiles avancent de 128 pixels, avec une bordure de 64 pixels écartée de chaque
prédiction. Les marges recopient les pixels comme le script de référence ; les
images trop petites pour une marge entière répètent leur queue sans modifier
leur taille finale. Seules les parties centrales sont replacées. La dernière
fourniture de tuiles contient les éléments réels, sans compléter artificiellement
le lot. Le résultat est mélangé avec l’original selon l’intensité ; le uint16 est
remis dans son échelle avant mélange, comme Siril.

Les fournisseurs effectifs sont auditables. Si le GPU est demandé, le repli ONNX
implicite vers CPU est désactivé. En cas de défaillance GPU, une nouvelle inférence
sur toute l’image n’est autorisée que par `--graxpert-cpu-fallback`, et journalisée.
Un contrat de modèle incorrect n’est pas traité comme une simple erreur GPU.
Les appels restent séquentiels. La RAM contient l’image, ses marges et le modèle ;
un grand lot augmente aussi la mémoire des activations du réseau.

## Vérification et portée

```bash
PIP_NO_INDEX=1 .venv/bin/python -m pytest -q tests/test_graxpert.py
```

Les tests couvrent cache, corruption, téléchargement officiel simulé, remplacement
atomique, nettoyage, dimensions, mono/RGB, uint16/HDU et repli CPU explicite.
Ils vérifient également l’activation automatique dans les deux types de caches,
l’absence de téléchargement lors de la détection, l’intégration aux chaînes,
la priorité CLI/configuration et la sauvegarde du mode automatique.
Un test conditionnel utilise les vrais poids déjà en cache et un extrait 128×128
RGB de `imagesExample/M_33_combined.fits`, sans télécharger dans la non-régression.

La validation locale avec ONNX Runtime 1.31.0 et les vrais poids 3.0.2 a produit
un FITS fini avec géométrie/WCS préservés. Sur cet extrait, l’inférence à intensité
1 a été comparée à la méthode `DenoiserProcessing.denoise` du script Siril installé :
**écart maximal nul** sur CPU. Cette vérification porte sur les pixels de ce cas,
pas sur toutes les versions, tous les périphériques ou la fidélité astrophysique.
Le GPU et un téléchargement réseau réel de poids absents restent non validés ici.

Références : [script officiel Siril](https://gitlab.com/free-astro/siril-scripts/-/blob/main/processing/GraXpert-AI.py),
[interface GraXpert dans Siril](https://siril.readthedocs.io/en/stable/processing/graxpert.html),
[API ONNX Runtime](https://onnxruntime.ai/docs/api/python/api_summary.html).
Les conventions d’inférence sont adaptées du script GPL-3.0-or-later d’Adrian
Knagg-Baugh ; les poids GraXpert indiquent la licence CC-BY-NC-SA-4.0.

Le périphérique hérite de la [politique générale de calcul](README.md#choix-du-calcul-cpugpu).
En `auto`, ONNX utilise un fournisseur GPU fonctionnel ou CPU, avec résolution
au démarrage de la session avant toute inférence. Un fournisseur annoncé mais
non initialisable (pilote absent, par exemple) permet encore le choix CPU à ce
stade. `cuda` exige `CUDAExecutionProvider` ; les surcharges historiques GPU/CPU
restent prioritaires. Une erreur pendant l'inférence ne relance pas l'image sur
CPU, sauf activation explicite de `--graxpert-cpu-fallback`.
