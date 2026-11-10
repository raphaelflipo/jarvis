# Validation de l’installateur macOS

Contrôles réalisés le 10 novembre 2026 sur un Mac Apple Silicon. Cette livraison est un installateur de préversion avec sources, sans modèle embarqué, certificat Developer ID ni notarisation Apple.

- Les 7 tests de `tests/test_packaging.py` passent : archive déterministe, empreintes, permissions exécutables, fichiers privés simulés exclus, liens symboliques rejetés, sources incomplètes refusées et syntaxe des scripts.
- La suite existante `tests/test_offline.py` passe : 263 réussites, aucun échec. Elle utilise un environnement temporaire et un modèle simulé ; elle ne mesure pas les réponses d’un vrai modèle.
- `JarvisApp.swift` et `JarvisAgenda.swift` compilent pour `arm64-apple-macos14.0`.
- Une copie de validation de l’application compilée passe `codesign --verify --deep --strict` avec une signature ad hoc. La vérification a été effectuée dans un répertoire temporaire local : le dossier Documents synchronisé ajoute des métadonnées Finder incompatibles avec la signature.
- `bash install.sh --check` s’arrête correctement avant toute écriture lorsque le stockage disponible est inférieur aux 30 Go requis. Aucun installateur n’a été exécuté sur le profil réel, aucun modèle téléchargé et aucun service global installé pour ces essais.
- L’archive ne contient que les sources explicitement autorisées, la licence, l’icône, les scripts et les empreintes. Aucun fichier de configuration personnelle, historique, jeton, cookie, modèle ou `.env` n’est ajouté. Une recherche ciblée de formes courantes de clés et de chemins personnels dans les sources incluses n’a trouvé aucun résultat ; elle ne constitue pas un audit de sécurité exhaustif.

## Refaire les contrôles

```sh
python3 -m unittest discover -s tests -p test_packaging.py -v
bash packaging/build.sh 3.2.0-beta.1
```

Le ZIP et son fichier `.sha256` sont écrits dans `dist/`. Le constructeur ne supprime pas les autres téléchargements présents dans ce dossier. Le contenu du ZIP est reproductible ; les dépendances téléchargées pendant l’installation ne sont pas verrouillées à des versions exactes.

## Limites avant une diffusion stable

L’installation complète sur un Mac neuf, le téléchargement des modèles, le lancement de l’application après installation et les autorisations macOS restent à vérifier sur une machine de test adaptée. La vérification locale des exécutables ne garantit pas leur acceptation par Gatekeeper après téléchargement.

Le programme exige macOS 14+, Apple Silicon, 16 Go de mémoire, 30 Go libres, les outils Apple et Homebrew. Il compile l’interface, prépare les bibliothèques et effectue les tests avant de remplacer les sources et l’application. Il conserve les copies précédentes ; l’environnement Python existant peut néanmoins être mis à jour, donc ce mécanisme n’est pas une restauration complète de l’installation.

L’édition de base prépare la conversation avec Ollama. Les fonctions de vision, dictée, images et MLX demandent des composants supplémentaires. Les comptes en ligne et l’accès distant ne sont pas activés par l’installation. Une instance Ollama existante est réutilisée sans la reconfigurer ni l’arrêter.
