# Rôle général des bibliothèques

[Documentation](../README.md) › [Architecture](README.md) › Bibliothèques

| Module | Rôle général |
|---|---|
| [parameterized_component.py](../../lib/parameterized_component.py) | Partager la déclaration et la capture des paramètres entre services et traitements |
| [processor.py](../../lib/processor.py) | Ajouter le contrat de traitement d’image aux composants configurables |
| [postprocessing.py](../../lib/postprocessing.py) | Exécuter le [pipeline complet de post-traitement](../scripts/postProcess/pipeline.md) commun à lightProcess et postProcess |
| [final_render.py](../../lib/final_render.py) | Orchestrer et publier le [rendu final AutoGHS](../scripts/postProcess/auto-ghs.md) après les traitements linéaires |
| [auto_ghs.py](../../lib/auto_ghs.py) | Calculer les étirements et rechercher leurs paramètres sur histogrammes |
| [star_separation.py](../../lib/star_separation.py) | Adapter StarNet V2 via le service Siril existant |
| [star_rendering.py](../../lib/star_rendering.py) | Étendre modérément les étoiles et recomposer les branches |
| [compute_config.py](../../lib/compute_config.py) | Partager la [politique CPU/GPU](../scripts/postProcess/compute-backend.md) et les surcharges des moteurs |
| [config.py](../../lib/config.py) | Centraliser les réglages, leurs valeurs par défaut et leur persistance |
| [fits_info.py](../../lib/fits_info.py) | Donner accès aux caractéristiques des FITS et aux informations nécessaires à leur regroupement et à leur validation |
| [xisf_reader.py](../../lib/xisf_reader.py) | Lire les masters XISF non compressés de PixInsight (pixels, mots-clés FITS, propriétés scalaires) |
| [restoration_quality.py](../../lib/restoration_quality.py) | Évaluer les candidats sur des masques indépendants des moteurs et du gradient |
| [restoration_chains.py](../../lib/restoration_chains.py) | Organiser la comparaison des chaînes complètes, active par défaut |
| [restoration_summary.py](../../lib/restoration_summary.py) | Présenter les essais, contrôles et motifs de sélection dans les journaux et rapports |
| [quality_preview.py](../../lib/quality_preview.py) | Illustrer les exclusions de qualité et les tuiles de ciel retenues |
| [power_guard.py](../../lib/power_guard.py) | Fournir le contexte de performance et d’inhibition de veille D-Bus, activé uniquement par les scripts de lancement |
| [graxpert_inference.py](../../lib/graxpert_inference.py) | Exécuter le modèle ONNX avec préservation des FITS |
| [graxpert_models.py](../../lib/graxpert_models.py) | Acquérir et vérifier les poids à la demande |
| [graxpert.py](../../lib/graxpert.py) | Encapsuler le débruitage ONNX natif GraXpert |
| [siril_utils.py](../../lib/siril_utils.py) | Encapsuler la configuration et l’exécution de Siril |
| [siril_sequence.py](../../lib/siril_sequence.py) | Représenter les séquences Siril et leurs images, en conservant l’association entre fichiers, mesures et transformations |
| [darkprocess.py](../../lib/darkprocess.py) | Gérer la constitution et la mise à jour de la bibliothèque de master darks |
| [lightprocessor.py](../../lib/lightprocessor.py) | Organiser les sessions de lights, leur calibration et la préparation des entrées du stack final |
| [quality_filter.py](../../lib/quality_filter.py) | Centraliser les décisions de sélection, les contrôles d’alignement et les pondérations des poses |
| [stellar_quality.py](../../lib/stellar_quality.py) | Mesurer la forme et l’étalement des étoiles dans les pixels des images |
| [drizzle.py](../../lib/drizzle.py) | Évaluer l’intérêt du Drizzle et orchestrer les étapes du stacking |
| [mosaic.py](../../lib/mosaic.py) | Organiser l’assemblage des champs en mosaïque |

Les bibliothèques de représentation alimentent les traitements de calibration
et de stacking. La mesure des profils stellaires fournit des observations au
module de sélection ; l’orchestration du stack consomme ensuite cette sélection.
L’accès à Siril est partagé par les traitements qui exécutent ses commandes.

Pour les règles de traitement et les formats détaillés, consulter la
documentation de [lightProcess](../scripts/lightProcess/README.md), de
[postProcess](../scripts/postProcess/README.md) ou de
[darkLibUpdate](../scripts/darkLibUpdate/README.md).
