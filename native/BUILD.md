# Construire les applications natives

Versions de validation : **Agent Mac 3.3.0-rc.1**, **Local Windows/Android/iOS 3.3.0-rc.2**. Aucun des paquets ne nécessite une compilation chez l'utilisateur.

## Sources et périmètre

`local-app/` est l'unique source de l'interface conversationnelle et du moteur WebAssembly. `native/prepare.py` copie ces fichiers dans les projets natifs et produit les icônes à partir de `assets/icon_1024.png`. Ne pas modifier les copies générées. Les conversations et les modèles restent propres à chaque installation. Les modèles sont téléchargés depuis Hugging Face à une révision fixe ; aucun message ne leur est envoyé.

macOS conserve le serveur Python et les outils système de `jarvis/`. Windows utilise Electron ; Android, WebView ; iOS, WKWebView. Ces trois éditions de conversation embarquent leurs ressources et un serveur de fichiers limité à `127.0.0.1:18769`. Elles ne se connectent à aucun Mac ou PC. Aucun accès aux fichiers personnels, calendrier, souris ou autres applications n'est exposé par ces conteneurs. L'utilisateur doit télécharger un modèle avant le premier usage hors ligne. La version web reste un accès complémentaire.

Les identifiants sont `local.jarvis.app` sur Mac (conservé), et `io.github.raphaelflipo.jarvis` sur les nouvelles applications Windows/Android/iOS. Ne pas les modifier pour une mise à jour.

## Windows x64

Environnement de compilation : Windows, Node.js 24, Python 3.12 et Pillow.

```sh
python -m pip install pillow
python native/prepare.py
cd native/windows
npm ci
npm run dist
```

Installateur NSIS dans `native/windows/dist/`. Electron 45.3.1 et electron-builder 26.18.0 sont verrouillés par `package-lock.json`. Windows 10 64 bits ou ultérieur ; essais sur le runner Windows de GitHub Actions. Le paquet n'a pas de certificat Authenticode. Un avertissement SmartScreen reste possible et son comportement sur un PC personnel n'est pas validé.

## Android

Java 17, Android SDK 35, Gradle 8.11.1, Android Gradle Plugin 8.9.3. Android 10 minimum, WebView récent avec WebAssembly et CacheStorage. Le code Java et le moteur fourni par WebView ne contiennent pas de bibliothèque JNI propre à une architecture. La compatibilité ARM64 doit aussi être validée sur un téléphone réel.

```sh
python native/prepare.py
gradle -p native/android assembleRelease assembleDebug assembleDebugAndroidTest
```

Signer l'APK de production avec `apksigner` et vérifier avec `apksigner verify --verbose --print-certs`. La clé privée est conservée hors du dépôt et des livraisons ; ne jamais la recréer pour une mise à jour. Les mots de passe doivent provenir de variables d'environnement, jamais d'arguments en clair. Les tests automatisés sont dans `LocalInferenceTest.java`. Google Play n'est pas le circuit retenu : aucune soumission et aucun AAB public ne sont annoncés.

## iOS

Xcode 27.2 utilisé pour les vérifications. Cible iOS 17 minimum, iPhone et iPad ; essai sur simulateur iPhone 18 Pro/iOS 27.2. Les performances et permissions sur téléphone physique restent à vérifier.

```sh
python native/prepare.py
# Si le projet doit être régénéré : XcodeGen 2.46.0
xcodegen generate --spec native/ios/project.yml
xcodebuild -project native/ios/Jarvis.xcodeproj -scheme Jarvis -configuration Release -destination 'generic/platform=iOS' -archivePath Jarvis-iOS.xcarchive CODE_SIGNING_ALLOWED=NO archive
```

L'archive non signée sert à préparer la distribution ; elle n'est pas installable sur iPhone. Pour exporter et soumettre : sélectionner une équipe autorisée, conserver le Bundle ID, créer l'app App Store Connect, configurer les signatures de distribution et téléverser l'archive signée. Les éléments proposés sont dans `native/ios/SUBMISSION.md`. Aucun achat, contrat, connexion ou publication App Store n'est réalisé automatiquement.

## macOS Apple Silicon

macOS 14 minimum, 16 Go de RAM recommandés, espace libre pour l'application (environ 1,5 Go), ses modèles et les fichiers de travail. Les outils de développement restent nécessaires pour compiler un projet que l'utilisateur demande à Jarvis de modifier ; ils ne sont pas nécessaires au démarrage de Jarvis.

Le constructeur `packaging/build_native_macos.py` utilise les archives officielles de Python 3.12.16 et Ollama 0.40.16, épinglées et contrôlées par SHA-256 dans ce fichier. Préparer le cache suivant :

1. Télécharger les deux URL de `SOURCES` dans `CACHE/downloads/python-macos.tar.gz` et `CACHE/downloads/ollama-macos.tgz`.
2. Extraire Python dans `CACHE/runtime/python/` et Ollama dans `CACHE/ollama/`.
3. Exécuter `CACHE/runtime/python/bin/python3 -m pip install -r requirements-macos.lock`.
4. Exécuter `PLAYWRIGHT_BROWSERS_PATH=CACHE/chromium CACHE/runtime/python/bin/python3 -m playwright install chromium`.
5. Exécuter `python packaging/build_native_macos.py --cache CACHE --output dist`.

Le constructeur travaille dans un dossier temporaire hors de Documents/iCloud pour éviter les métadonnées Finder ajoutées aux paquets par la synchronisation. Il ne retire pas la quarantaine. Les bibliothèques et conteneurs sont signés localement puis vérifiés ; **la signature ad hoc n'est pas une signature Developer ID et le DMG n'est pas notarié**. Pour une distribution normale, reconstituer les signatures avec un certificat Developer ID, les entitlements adaptés aux composants, puis soumettre avec `notarytool` et agrafer le ticket avec `stapler`. Ne pas signer avec une clé de développement en prétendant remplacer cette étape.

## Vérifications reproductibles

```sh
node --test tests/test_local_app.mjs
python -m unittest discover -s tests -p test_release_quality.py
python -m unittest discover -s tests -p test_packaging.py
python tests/test_offline.py
```

Les tests Python exigent leurs dépendances ; une intégration HTTP/WebSocket manquante doit faire échouer la vérification. Le test historique simule le LLM ; il ne prouve pas l'inférence réelle. `native/common/selftest.js` charge et exécute au contraire un modèle réel, puis vérifie le cache et l'historique lors d'une deuxième ouverture. Windows bloque les requêtes extérieures pendant ce deuxième essai ; iOS et Android utilisent le chargement cache seul. Le workflow `.github/workflows/native-validation.yml` produit les paquets et rapports Windows/Android. Ne jamais inclure de clés, profils personnels ou jetons dans les artefacts.

## Validation de la révision Local RC2

Le workflow natif installe d'abord Windows RC1, conserve son profil puis installe RC2 et vérifie le chargement hors ligne et l'envoi depuis les contrôles visibles. Le workflow Android signé installe RC1 avec la même clé, conserve modèle et historique, met à jour vers RC2 puis vérifie le clavier logiciel, la visibilité du bouton Envoyer et une réponse hors ligne. Les captures sont conservées comme preuves. Exécuter ces workflows sur le commit de livraison et vérifier les assertions ; une compilation seule ne valide pas ces parcours. La signature APK vérifiée est v3.
