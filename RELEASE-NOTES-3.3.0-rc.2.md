# Jarvis Local 3.3.0-rc.2 — conversation autonome

Cette révision concerne Windows, Android, iOS et l'accès web. L'Agent Mac reste en 3.3.0-rc.1 : son DMG autonome et ses contrôles sont conservés dans la release correspondante. Ces éditions ont des fonctions différentes ; la disponibilité finale sur quatre plateformes n'est pas annoncée.

## Corrections Local

- Android : marges natives adaptées aux barres système, aux découpes d'écran et au clavier logiciel ; maintien du champ actif dans la zone visible et icônes système sombres sur fond clair.
- État du modèle plus court et lisible ; détails conservés dans son libellé explicatif.
- Rechargement prioritaire depuis le cache d'un modèle déjà présent, y compris quand une connexion réseau semble disponible.
- Identifiants d'application, clé Android, cache des modèles et historique conservés entre RC1 et RC2.
- Contrôles renforcés : utilisation des boutons de conversation Windows et Android, chargement hors ligne, clavier réel Android et mise à jour depuis RC1. Les résultats et captures sont joints au dossier de vérification.

## Paquets

Windows : installateur NSIS x64, Windows 10+. Electron embarqué ; aucun environnement de développement requis. Signature Authenticode absente ; comportement SmartScreen sur ordinateur personnel non vérifié. Validation sur Windows Server 2025 dans GitHub Actions.

Android : APK de production signé v3, Android 10+, WebView avec WebAssembly et CacheStorage. Installation directe, sans Google Play ni AAB public. Validation sur émulateur Android 15 x86_64, WebView 124 ; performances et installation sur téléphone ARM64 réel restent à vérifier. La clé de production est conservée hors dépôt et livraison.

iOS : archive Release arm64 compilée pour appareil physique, iOS 17+. Elle est NON INSTALLABLE sans signature et canal adaptés. Validation sur simulateur iPhone 18 Pro/iOS 27.2, mise à jour avec modèle et 40 messages conservés, réponse réelle hors ligne. Xcode ne dispose pas du compte actif de l'équipe nécessaire ni d'un profil Jarvis ; aucun certificat de distribution, accès App Store Connect ou canal public actif. Aucun IPA public n'est annoncé.

Mac : voir [Agent Mac RC1](https://github.com/raphaelflipo/jarvis/releases/tag/v3.3.0-rc.1). Apple Silicon/macOS 14+, signature ad hoc, non notarié ; Gatekeeper rejette ce paquet. Developer ID et notarisation manquent pour une distribution Apple normale. Intel non livré.

## Fonctionnement et limites

Windows, Android et iOS embarquent l'interface, un serveur de fichiers limité à 127.0.0.1 et un moteur WebAssembly exécutant le modèle sur l'appareil. Ils n'exigent aucun ordinateur distant et ne chargent pas simplement le site public. Ils proposent la conversation texte, sans les outils système de l'agent Mac. Internet est nécessaire pour télécharger le premier modèle : SmolLM2 135M (~140 Mo, surtout anglais) ou Qwen3 0.6B (~628 Mo, français plus adapté mais performances limitées). Les réponses peuvent être incorrectes. Les 40 derniers messages sont conservés localement ; le contexte du modèle est plus court. Aucun compte ni abonnement requis.

Les références techniques aux moteurs, modèles, fournisseurs, prompts fonctionnels, licences et droits sont conservées. Les traces facultatives de fabrication ont été retirées des contenus actuels. Trois anciens messages Git restent identifiés dans HISTORIQUE-AUTORISATION.md ; leur réécriture partagée attend un accord distinct et n'a pas été effectuée.
