# Jarvis Local · bêta 2

Assistant de conversation autonome, gratuit et sans compte, pour navigateur récent sur macOS, Windows, iOS et Android. L’IA s’exécute sur **l’appareil qui ouvre l’application**. Aucun ordinateur distant, Ollama ou abonnement n’est nécessaire pour cette édition.

## Installer et utiliser

Ouvrir https://raphaelflipo.github.io/jarvis/app/ depuis l’appareil souhaité.

1. Installer l’application avec le bouton du navigateur. Sur iPhone/iPad : Safari → Partager → Sur l’écran d’accueil → Ouvrir comme app web. Sur Mac : Safari → Ajouter au Dock, ou installation Chrome/Edge. Sur Windows et Android : installation Chrome/Edge depuis leur menu.
2. **Ouvrir l’application installée**, puis choisir et télécharger un modèle. Safari peut séparer le stockage du site et de l’application installée : télécharger dans l’application à conserver.
3. Garder l’application ouverte pendant le téléchargement et le chargement. Envoyer un message lorsque le modèle est prêt. Le premier message peut prendre plus longtemps.
4. Lorsque le statut indique « Prêt hors ligne », les fichiers de l’application et du modèle sont conservés. L’application peut être rouverte et le modèle rechargé sans réseau. Le navigateur peut néanmoins retirer les données locales en cas de manque d’espace ; la navigation privée ne convient pas à cet usage.

Le modèle doit être remis en mémoire après la fermeture de l’application. Cela n’impose pas un nouveau téléchargement si ses fichiers sont toujours présents. L’annulation arrête immédiatement le moteur ; utiliser « Télécharger / charger » pour reprendre depuis le cache.

## Modèles et limites

| Modèle | Téléchargement approximatif | Usage |
|---|---:|---|
| SmolLM2 135M Instruct, q8 | 140 Mo | Plus léger ; principalement anglais, français limité |
| Qwen3 0.6B Instruct, q8 | 628 Mo | Plus adapté au français ; davantage de mémoire et de temps |

Ajouter environ 23 Mo pour le moteur et l’interface. Le téléchargement et la RAM nécessaire sont différents : tous les téléphones ne disposent pas d’assez de mémoire. Le modèle léger est conseillé pour un premier essai. Ces petits modèles peuvent se tromper et offrent des réponses moins élaborées que de grands modèles de bureau. Aucune vitesse universelle n’est promise.

Cette bêta répond à du texte. Elle ne possède pas les commandes système, la navigation web, les documents joints, la voix, les outils Mac, ni les fonctions d’agent de Jarvis pour macOS. Les conversations longues sont limitées aux derniers échanges, puis à un contexte de 1 024 jetons ; une réponse compte au plus 192 nouveaux jetons. Pas de génération en arrière-plan garantie, particulièrement sur téléphone.

Ce dossier contient l’édition **web installable**. Les nouveaux conteneurs natifs réutilisent cette interface ; leurs paquets et statuts sont décrits dans le README principal. L’édition web seule ne constitue pas un APK, IPA ou EXE. Les quatre systèmes peuvent ouvrir la même application ; la compatibilité de l’inférence dépend du navigateur et du matériel. Voir VERIFICATION.md pour les essais effectivement réalisés et leurs limites.

## Confidentialité

Les messages et les réponses ne sont envoyés à aucun service d’IA. L’historique courant est enregistré dans le stockage local du navigateur, sans chiffrement applicatif ; il est visible aux personnes utilisant le même profil. Les réglages permettent d’effacer l’historique et les modèles. Aucune télémétrie, clé API ni connexion à un compte.

La première visite télécharge les fichiers depuis GitHub Pages ; le téléchargement des modèles contacte Hugging Face et son infrastructure de fichiers. Ces services reçoivent les informations habituelles de connexion (par exemple l’adresse IP), **pas les messages de conversation**. Le modèle et le moteur sont figés à des versions précises. Le téléchargement utilise HTTPS.

## Modifier, tester, héberger

Tous les fichiers HTML/CSS/JS sont modifiables. Aucun assemblage n’est nécessaire : le moteur est inclus dans `vendor/`. Servir ce répertoire avec HTTPS ou, pour le développement, `python3 -m http.server 18765 --bind 127.0.0.1 --directory local-app` depuis la racine du dépôt. L’ouverture directe en `file://` ne fonctionne pas avec les workers/service workers.

Tests : `node --test tests/test_local_app.mjs` depuis la racine. Une copie complète de `local-app/` peut être déposée dans un sous-dossier d’un site statique. Conserver tous les fichiers, y compris les fichiers `.wasm`, les licences et le service worker. À chaque modification des fichiers distribués, incrémenter la version du cache dans `sw.js`. Les modèles ne sont pas inclus dans l’archive source.

Moteur : Transformers.js 3.8.1 et ONNX Runtime Web 1.22.0-dev.20250409-89f8206ba4 (version fournie par ce paquet Transformers.js), WASM mono-thread, sans WebGPU obligatoire. Fichiers pris dans le paquet officiel npm `@huggingface/transformers@3.8.1`, avec `transformers.min.js`, `ort-wasm-simd-threaded.jsep.mjs` et `.wasm`. La version exacte et les révisions des modèles sont définies dans `models.js`.

## Licences et références

Code Jarvis : MIT, voir LICENSE. Le moteur inclut Transformers.js (Apache-2.0), ONNX Runtime (MIT) et Jinja (MIT), avec leurs licences et attributions dans `vendor/`. Les modèles sont téléchargés séparément : [SmolLM2](https://huggingface.co/HuggingFaceTB/SmolLM2-135M-Instruct) (Apache-2.0), [Qwen3 original](https://huggingface.co/Qwen/Qwen3-0.6B) (Apache-2.0), [conversion ONNX Qwen](https://huggingface.co/onnx-community/Qwen3-0.6B-ONNX).

Documentation du moteur : https://huggingface.co/docs/transformers.js/v3.8.1/index
Compatibilité WASM : https://onnxruntime.ai/docs/get-started/with-javascript/web.html
Stockage Safari : https://webkit.org/blog/14403/updates-to-storage-policy/
