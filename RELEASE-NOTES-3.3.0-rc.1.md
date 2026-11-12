# Jarvis 3.3.0-rc.1 — applications natives en validation

Cette RC fournit un DMG Mac autonome, un installateur Windows et un APK Android signé. Une application iOS autonome est compilée pour appareil physique et testée sur simulateur ; **aucun canal public iPhone n'est actif**. La RC n'est pas présentée comme une version finale stable sur les quatre systèmes.

## Paquets et contrôles

| Plateforme | Livrable | Environnement et résultats | Signature et limites |
|---|---|---|---|
| macOS | Jarvis.app dans un DMG, arm64, macOS 14+ | MacBook Air M5, macOS 27.3 ; DMG monté et application copiée dans un dossier de test isolé ; dépendances intégrées cohérentes ; lancement, moteur Ollama local, installation d'un modèle depuis le menu et historique conservé après fermeture/réouverture | Signature ad hoc vérifiée en profondeur. Gatekeeper rejette le paquet ; aucun ticket de notarisation. Developer ID et notarisation manquent pour une diffusion Apple normale. Intel non livré |
| Windows | EXE NSIS x64, Windows 10+ | Runner Windows Server 2025 de GitHub Actions ; installation de l'EXE, SmolLM2 réellement exécuté, fermeture puis réouverture avec réseau extérieur bloqué, cache et 40 messages conservés | Authenticode : non signé. SmartScreen sur PC personnel non vérifié |
| Android | APK de production signé, Android 10+, WebView récent | APK signé exact installé sur émulateur Android 15 x86_64 ; génération réelle ; arrêt complet du processus puis rechargement du modèle depuis le cache, 40 messages conservés | Signatures APK v2/v3 vérifiées ; clé de production RSA 4096 conservée hors dépôt, mot de passe dans le Trousseau macOS. Pas de téléphone physique validé. Pas de Google Play/AAB annoncé |
| iOS/iPadOS | Archive Release arm64 pour appareil physique, iOS 17+ ; non installable sans signature adaptée | Simulateur iPhone 18 Pro, iOS 27.2 ; SmolLM2 et Qwen3 exécutés ; réouverture avec modèle en cache et 40 messages conservés ; réponse en français observée avec Qwen3 | Archive non signée. Un iPhone est détecté, mais Xcode signale l'absence de compte actif pour l'équipe du certificat de développement et l'absence de profil Jarvis. Aucun certificat de distribution/canal App Store ou TestFlight disponible |

Les éditions Windows, Android et iOS sont des conteneurs natifs de la conversation locale : ressources embarquées et modèle exécuté par WebAssembly sur l'appareil. Elles ne chargent pas simplement le site public et ne nécessitent pas d'ordinateur distant. Elles n'exposent pas les outils fichiers, calendrier ou pilotage d'applications de l'agent Mac. Les fonctionnalités existantes du Mac sont conservées ; MLX reste facultatif pour les installations déjà configurées.

Premier téléchargement nécessaire : SmolLM2 ~140 Mo (surtout anglais), Qwen3 ~628 Mo (mieux adapté au français). Le modèle proposé par défaut au premier démarrage de l'agent Mac est qwen3:1.7b (~1,4 Go) ; les choix existants sont conservés. Le test Mac a utilisé qwen3:0.6b. Le menu d'installation est vérifié avec ce modèle déjà en cache ; le téléchargement initial a également été effectué avec Ollama embarqué. La qualité du modèle et les fonctions complexes de l'agent ne sont pas validées par une simple réponse de conversation.

## Corrections

- Refus d'exécuter une commande si le bac à sable demandé est indisponible. Les dossiers personnels arbitraires ne deviennent plus inscriptibles automatiquement.
- Annulation avec empreinte de l'état final, détection des conflits et copies récupérables. Les modifications plus récentes sont conservées ; les anciens manifestes incomplets ne provoquent pas d'écrasement. Une nouvelle modification après annulation obtient son propre point de récupération.
- Verrous de patchs pris dans un ordre stable pour éviter une attente circulaire entre tâches.
- Détection des pièces jointes limitée à 20 Ko, au lieu de lire plusieurs fois le fichier entier.
- Historique conservé sur 40 messages après réouverture ; contexte du modèle limité séparément à 12 messages.
- Arrêt des surveillants d'alimentation et d'indexation ; arrêt propre de la tâche de nettoyage serveur ; diffusion protégée contre une boucle asynchrone fermée.
- Surveillance nocturne installée uniquement si activée explicitement.
- Service de ressources Android conservé au niveau du processus pour permettre la recréation de la fenêtre et la réouverture.
- Runtime Python, Ollama et navigateur intégrés dans le DMG ; pas de compilation, Homebrew ou installation Python demandés à l'utilisateur pour démarrer Jarvis.
- Versions et icônes harmonisées ; copie de l'interface issue d'une source unique ; dépendances de production et outils de construction épinglés.
- Dépendance de test manquante : échec explicite, sans masquer la vérification HTTP/WebSocket.

## Preuves

Contrôles locaux : **263 contrôles serveur, 8 tests de régression, 7 tests de packaging, 12 tests JavaScript réussis**. Les 263 contrôles simulent le LLM ; les essais d'inférence native ci-dessus utilisent de vrais modèles. Le workflow [validation native](https://github.com/raphaelflipo/jarvis/actions/runs/43274755119) a passé les contrôles Mac, Windows et Android. L'essai du [paquet Android de production signé](https://github.com/raphaelflipo/jarvis/actions/runs/43274606440) est réussi.

Les empreintes sont dans `SHA256SUMS.txt` et les associations version/source dans `BUILD-MANIFEST.json`, livrés avec les paquets. Les archives antérieures restent disponibles comme préversions historiques. Les instructions reproductibles se trouvent dans `native/BUILD.md`.

## Installation

- Mac : ouvrir le DMG, glisser Jarvis dans Applications ; le menu Jarvis permet de télécharger un modèle. Le paquet n'est pas notarié : la distribution Apple normale reste à finaliser. Ne pas désactiver les protections de macOS.
- Windows : ouvrir l'EXE, suivre l'assistant, ouvrir Jarvis et charger un modèle.
- Android : installer l'APK depuis le navigateur choisi, ouvrir Jarvis puis charger un modèle. Le modèle peut ensuite être rechargé depuis le cache.
- iOS : aucun accès natif public. L'archive est réservée à la préparation technique. L'accès web reste distinct de l'application iOS.

Une désinstallation ou un nettoyage du stockage peut effacer les conversations et modèles locaux. Les mises à jour Android devront conserver la même clé et augmenter le numéro de build. Aucun essai de migration de données personnelles depuis une ancienne installation réelle n'est annoncé ; les identifiants et chemins de profil existants sont conservés.

## Contenus et références

Les textes actuels ne comportent plus de crédit facultatif de fabrication par un assistant. Les nouveaux commits n'ajoutent aucune signature promotionnelle. Les prompts, noms de fournisseurs, fichiers d'instructions de projet reconnus, modèles et identifiants nécessaires sont conservés. Les licences de bibliothèques et modèles, ainsi que les métadonnées de droits/provenance des illustrations, restent présentes. Aucune origine entièrement humaine n'est affirmée.

Trois anciens messages de commit contiennent encore des mentions facultatives. Aucune réécriture de l'historique, modification de tag existant ou suppression de release antérieure n'a été effectuée. Une proposition séparée est fournie à l'éditeur avant toute opération affectant ces références partagées.

## Actions extérieures et suites

1. iOS : connecter le compte dans Xcode, rendre disponible une équipe habilitée et les profils/certificats de distribution, configurer App Store Connect, tester sur iPhone puis soumettre à Apple. Un Personal Team gratuit avec profils expirant après 7 jours ne fournit pas une distribution publique durable : [documentation Apple](https://developer.apple.com/help/account/basics/about-your-developer-account/).
2. macOS : rendre disponibles Developer ID et le moyen de notarisation, signer les composants avec les réglages adaptés, notarier puis refaire les contrôles du paquet signé. Aucun achat engagé.
3. Windows : fournir un moyen de signature Authenticode si disponible et vérifier le parcours sur PC personnel. Le RC non signé reste distinct de cette validation.
4. Priorités non bloquantes : essais sur Android physique et davantage d'iPhone ; évaluation du français, de la mémoire, de la batterie et des modèles ; amélioration de la reprise des téléchargements et des retours de progression ; essai de mise à jour sur des installations réelles avec données de test sauvegardées.
