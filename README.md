# Jarvis

Assistant personnel local de Raphaël Flipo. **3.3.0-rc.1 est une version de validation**, avec des paquets natifs et des niveaux de vérification distincts selon les plateformes.

**[Téléchargements et statuts](https://raphaelflipo.github.io/jarvis/)** · **[Releases](https://github.com/raphaelflipo/jarvis/releases)** · **[Accès web complémentaire](https://raphaelflipo.github.io/jarvis/app/)**

| Édition | Installation | Fonctions |
|---|---|---|
| Mac Apple Silicon | Application autonome dans un DMG ; macOS 14+ | Conversation, agent, fichiers, documents, outils système ; Ollama intégré, MLX facultatif si déjà configuré |
| Windows x64 | Installateur EXE ; Windows 10+ | Conversation locale avec modèle WebAssembly ; aucun ordinateur distant |
| Android | APK de production signé ; Android 10+, WebView récent | Conversation locale ; interface et moteur embarqués ; premier téléchargement du modèle nécessaire |
| iOS/iPadOS | Projet natif et archive pour appareil physique préparés ; iOS 17+ | Conversation locale testée sur simulateur ; **pas de distribution publique iPhone active** |

Les trois nouvelles éditions de conversation conservent les fonctions de Jarvis Local. Elles ne fournissent pas les outils système de l'agent Mac. Aucun compte ni abonnement n'est nécessaire. Les deux modèles proposés sont petits : SmolLM2 135M (~140 Mo, surtout anglais) et Qwen3 0.6B (~628 Mo, mieux adapté au français). La qualité, la mémoire nécessaire et les performances varient selon l'appareil. Un minimum de 4 Go de RAM est conseillé pour commencer ; davantage pour Qwen3. Il ne s'agit pas d'une certification de chaque téléphone.

## Installer et ouvrir

Consulter la page de téléchargement pour connaître le statut du fichier avant de l'installer.

- **Mac** : ouvrir le DMG, glisser Jarvis dans Applications puis l'ouvrir. Le menu Jarvis → Installer le modèle local propose le téléchargement initial. Aucun Homebrew, Python externe ou commande de compilation n'est requis. Le paquet est signé ad hoc, **non notarié**, et ne bénéficie pas d'un certificat Developer ID ; macOS peut bloquer l'ouverture. Ne pas désactiver Gatekeeper ni supprimer la quarantaine. Intel n'est pas pris en charge par ce paquet.
- **Windows** : ouvrir l'EXE et suivre l'assistant, puis choisir un modèle dans Jarvis. Le paquet n'a pas de signature Authenticode ; les avertissements sur un PC personnel restent à évaluer. Les essais d'installation et de réouverture sont effectués sur un runner Windows de GitHub Actions.
- **Android** : télécharger l'APK depuis la release, autoriser son installation depuis le navigateur choisi puis ouvrir Jarvis. Cette autorisation peut être retirée ensuite. Télécharger un modèle dans Jarvis. Les essais sur émulateur et les limites sur appareil physique sont détaillés dans le bilan de release.
- **iPhone/iPad** : aucun IPA public installable n'est annoncé. Les moyens de signature et le canal de distribution doivent être configurés. L'accès web reste disponible séparément ; il ne remplace pas une application iOS distribuée.

## Stockage, données et permissions

Les conversations sont conservées sur l'appareil. Les nouveaux conteneurs utilisent un profil local persistant. Les 40 derniers messages sont conservés ; seuls les 12 derniers, avec une limite de longueur, sont transmis au modèle local. Les réglages permettent d'effacer la conversation et les modèles en cache. Une désinstallation ou le nettoyage du stockage peut supprimer ces données.

Sur Mac, les profils existants dans `~/.jarvis` sont conservés. Ne pas utiliser l'ancien installateur avec compilation pour remplacer le paquet autonome. Les outils peuvent modifier des fichiers ; autoriser uniquement les dossiers de travail nécessaires et vérifier les demandes sensibles. Le shell protégé refuse de s'exécuter si son bac à sable est indisponible. L'annulation garde les fichiers modifiés depuis par l'utilisateur et conserve des copies récupérables.

Le premier téléchargement des applications contacte GitHub ; les modèles de conversation viennent de Hugging Face, et ceux de l'agent Mac d'Ollama. Ces services voient les informations réseau habituelles, dont l'adresse IP, mais ne reçoivent pas les conversations locales. Les outils web, services externes ou renforts cloud de l'agent Mac nécessitent Internet et leur propre configuration ; ne pas les confondre avec une conversation hors ligne. Les fournisseurs, prompts fonctionnels, identifiants et licences nécessaires sont conservés.

## Vérifications et maintenance

[Compilation et publication reproductibles](native/BUILD.md) · [Préparation iOS](native/ios/SUBMISSION.md) · [Historique des essais web](local-app/VERIFICATION.md).

Le workflow de validation Windows/Android compile les paquets, installe l'application Windows et exécute un vrai modèle local, puis recommence avec cache et historique conservés. Les nouveaux conteneurs embarquent leurs ressources et n'ouvrent pas simplement le site public. Les sources de l'interface restent dans `local-app/` ; `native/prepare.py` produit les copies natives.

La signature de distribution Apple, la notarisation Mac et la validation sur des téléphones physiques restent des critères distincts. Un fichier compilé ou une archive Xcode ne prouve pas une disponibilité publique. Les notes de chaque release indiquent précisément les environnements, résultats et blocages. Aucune dépense n'est engagée.

## Licences

Code Jarvis sous MIT, voir [LICENSE](LICENSE). Les dépendances et modèles conservent leurs propres licences et attributions : [notices de l'édition locale](local-app/THIRD-PARTY-NOTICES.txt). Le paquet Mac contient les licences des bibliothèques Python, d'Ollama et de Chromium. Les noms de fournisseurs dans les intégrations fonctionnelles ne sont pas des crédits de fabrication du projet.
