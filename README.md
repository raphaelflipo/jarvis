# Jarvis

Un projet d’assistant personnel local de Raphaël Flipo. Deux éditions, avec des périmètres différents, sont disponibles en préversion.

**[Ouvrir et installer Jarvis Local](https://raphaelflipo.github.io/jarvis/app/)** · **[Téléchargements](https://github.com/raphaelflipo/jarvis/releases)** · **[Présentation](https://raphaelflipo.github.io/jarvis/)**

| | Jarvis Local · bêta 2 | Jarvis pour macOS · 3.2 bêta 2 |
|---|---|---|
| Installation | Application web installable | Installateur avec sources, compilation sur le Mac |
| Systèmes visés | iOS, Android, macOS, Windows, navigateur récent | Mac Apple Silicon, macOS 14+ |
| Calcul de l’IA | Directement sur l’appareil, WASM | Sur le Mac, Ollama ; MLX facultatif |
| Téléphone sans ordinateur | Oui | L’ancienne interface distante nécessite le Mac |
| Fonctions | Conversation texte, reformulation, idées | Agent, outils, fichiers, documents et intégrations Mac |
| Modèles | SmolLM2 135M ou Qwen3 0.6B | qwen3:8b par défaut ; autres modèles configurables |
| Frais | Aucun abonnement, pas de compte | Aucun abonnement obligatoire ; cloud facultatif |

## Jarvis Local : téléphone et ordinateur

1. Ouvrir **https://raphaelflipo.github.io/jarvis/app/**.
2. Installer depuis le navigateur. Sur iPhone/iPad : Safari → Partager → Sur l’écran d’accueil. Sur Android/Windows : Chrome ou Edge → Installer l’application. Sur Mac : Safari → Ajouter au Dock, ou Chrome/Edge.
3. Ouvrir l’application installée et télécharger un modèle : environ 140 Mo pour SmolLM2 (surtout anglais), ou 628 Mo pour Qwen (plus adapté au français), plus environ 23 Mo de moteur.
4. Une fois « Prêt hors ligne » affiché, l’application et le modèle sont conservés pour une utilisation sans réseau. Après fermeture, recharger le modèle depuis les fichiers locaux.

Cette édition fonctionne **sans ordinateur distant et sans serveur d’IA**. Les messages restent sur l’appareil. Le premier téléchargement contacte GitHub Pages et Hugging Face. Les données du navigateur peuvent être retirées en cas de manque de stockage.

Le modèle et le contexte sont petits pour limiter la mémoire utilisée. La qualité et la vitesse varient ; tous les téléphones ne peuvent pas faire tourner tous les modèles. C’est une bêta conversationnelle : elle ne contrôle pas les autres applications, n’ouvre pas de documents joints et ne remplace pas les outils de l’agent Mac.

Il s’agit d’une **application web installable**, pas d’un APK, IPA, EXE ou d’une publication sur les boutiques Apple/Google. [Guide complet et confidentialité](local-app/README.md) · [Tests effectivement réalisés](local-app/VERIFICATION.md).

## Jarvis pour Mac : agent et outils

Télécharger l’archive macOS depuis les [préversions publiques](https://github.com/raphaelflipo/jarvis/releases), la décompresser et lire la notice avant d’ouvrir `Installer Jarvis.app`. Le logiciel est compilé sur votre Mac ; l’archive ne contient ni modèle, ni compte, ni clé.

Prérequis : **Apple Silicon, macOS 14+, 16 Go de RAM, 30 Go d’espace libre**, connexion Internet, outils de ligne de commande Apple et Homebrew. Si un prérequis manque, l’installateur s’arrête en l’expliquant. Il ne demande pas de mot de passe, ne retire pas la quarantaine et ne désactive aucune protection.

L’installateur est **sans certificat Developer ID ni notarisation Apple** : macOS peut bloquer son ouverture. Pour les développeurs qui inspectent les sources :

```sh
git clone https://github.com/raphaelflipo/jarvis.git
cd jarvis
bash install.sh --check  # vérification sans installation ni écriture
bash install.sh         # installation après lecture des prérequis
```

Le parcours de base installe Ollama et le modèle qwen3:8b, puis l’application native. Il réutilise un moteur Ollama déjà actif. Les services distants et les connexions GitHub/Firebase ne sont pas activés par l’installateur. Vision, dictée, MLX et création d’images nécessitent une préparation supplémentaire.

Les sources comprennent notamment un moteur de tâches, une interface AppKit/WebKit, des outils de fichiers et de documents, un navigateur Playwright, des intégrations Calendrier/Rappels et des options de recherche web. Leur disponibilité dépend des dépendances, des autorisations et du modèle. Les recherches web et les renforts cloud facultatifs utilisent Internet ; tous les usages de l’édition Mac ne sont donc pas hors ligne.

L’agent peut modifier des fichiers. Commencer dans un dossier de test et vérifier les demandes d’accord. Ne pas lancer le backend macOS sous Windows en supposant ses outils et protections portables ; utiliser Jarvis Local sur Windows.

[Notice Mac détaillée](packaging/MACOS-INSTALL.txt) · [Architecture du backend](docs/ARCHITECTURE.md).

## Développement et vérifications

```sh
node --test tests/test_local_app.mjs
python3 -m unittest discover -s tests -p test_packaging.py
python3 tests/test_offline.py  # dépendances Python du backend nécessaires
python3 packaging/build_local.py
bash packaging/build.sh
```

Le site et l’application locale sont statiques, compatibles GitHub Pages. Le code de l’application installable est dans `local-app/`, celui du backend dans `jarvis/`. Les archives sont reproductibles et accompagnées d’empreintes SHA-256 ; les dépendances du programme d’installation Mac sont téléchargées lors de l’installation et peuvent évoluer.

Les comptes rendus de préversion distinguent tests automatisés, compilation native et essais réels. Une compilation n’atteste pas une installation réussie sur un Mac vierge ; une vérification dans un navigateur de bureau ne prouve pas les performances d’un téléphone réel.

## Licence

Code Jarvis sous [licence MIT](LICENSE). Bibliothèques et modèles conservent leurs propres licences : voir [les notices](local-app/THIRD-PARTY-NOTICES.txt). Aucun modèle n’est redistribué dans les archives.
