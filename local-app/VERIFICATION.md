# Vérifications de Jarvis Local

Essais de la bêta 1 du 10 novembre 2026, sur macOS Apple Silicon, dans le navigateur Chromium intégré à l’environnement de développement. Les essais d’inférence utilisent les vrais modèles, sans serveur de réponse ni simulation du texte généré.

## Essais réalisés

- Téléchargement réel de SmolLM2 135M q8 et de Qwen3 0.6B q8 depuis leurs révisions figées sur Hugging Face.
- Chargement dans un Web Worker et calcul CPU avec WebAssembly ; interface utilisable pendant le chargement.
- **SmolLM2 : réseau coupé dans les outils du navigateur, rechargement complet de la page, chargement depuis le cache, puis nouvelle réponse.** Le modèle répond « The capital of France is Paris. » à une demande en anglais.
- **Qwen3 : même rechargement complet hors réseau, chargement depuis le cache, puis nouvelle reformulation en français.** Une question simple en français reçoit aussi une réponse correcte lors de l’essai en ligne.
- Les essais courts ont pris environ 1 seconde avec SmolLM2 et 7 à 10 secondes avec Qwen3 sur cette machine. Ce sont quelques observations locales, pas un benchmark, une garantie de qualité ni une estimation pour un téléphone.
- Arrêt d’une réponse en cours : worker terminé, contrôles réactivés et invitation à recharger le modèle.
- Effacement de la conversation d’essai et des modèles depuis les réglages. Après suppression, une tentative de chargement hors réseau affiche l’instruction de se connecter une première fois.
- Conservation du modèle choisi après rechargement ; conservation de l’historique avant son effacement.
- Vérification visuelle sur ordinateur et à 390 px ; contrôle à 320 px sans débordement horizontal. Ces dimensions simulent un écran étroit, **pas un appareil iOS ou Android**.
- Aucune erreur JavaScript signalée pendant les essais finaux de génération, après correction d’une conversion de tenseur et du chargement strict depuis le cache.

## Vérifications automatisées

`node --test tests/test_local_app.mjs` : **11 tests réussis**. Ils couvrent l’historique borné, les modèles figés, les chemins du manifeste, les fichiers distribués, la politique des scripts, l’installation atomique du cache, le rechargement hors ligne et le périmètre du service worker. Les tests de cache utilisent des objets simulés ; les essais navigateur ci-dessus complètent ces contrôles.

Archives : fichiers explicitement autorisés, aucune donnée du navigateur ni aucun poids de modèle embarqué, licences et empreintes SHA-256 incluses. Deux constructions avec les mêmes fichiers produisent la même archive. Les contrôles de l’installateur Mac sont décrits séparément dans `packaging/VALIDATION.md`.

## Ce qui n’est pas encore validé

- Pas d’essai sur un iPhone ou un Android physique, ni sur un PC Windows ou Safari. Pas de simulateur iOS disponible dans cet environnement. L’installation depuis l’écran d’accueil/le Dock n’a pas été exécutée sur ces systèmes.
- La compatibilité WASM de ces navigateurs est documentée par [ONNX Runtime](https://onnxruntime.ai/docs/get-started/with-javascript/web.html), mais cela ne valide ni la RAM disponible ni les performances d’un appareil particulier.
- Pas de garantie de fonctionnement sur tous les téléphones, de conservation illimitée du cache, de fonctionnement en arrière-plan ou de reprise d’un téléchargement interrompu. Un téléchargement interrompu peut reprendre depuis le début du fichier manquant.
- Pas d’évaluation exhaustive de la qualité des modèles : une réponse correcte ne garantit pas la fiabilité des suivantes. Le modèle léger est surtout anglophone ; Qwen3 reste un très petit modèle.
- Cette bêta autonome ne fournit pas les outils système, la voix, les pièces jointes ou les intégrations de l’édition Mac.

La publication est une **préversion publique**, pas une version stable certifiée sur les quatre systèmes.

## Maintenance du 12 novembre 2026 · bêta 2

Les textes d’accueil et de réglages ont été précisés. Les identifiants HTML, les clés de stockage, les modèles et le moteur d’inférence sont conservés. Le cache de l’interface porte un nouveau numéro de version ; les fichiers de modèles déjà téléchargés ne sont pas supprimés.

Les 11 tests automatisés de l’application web passent. Les fichiers HTML, les liens, le manifeste, les politiques de scripts et la correspondance entre les sources et la copie du site sont contrôlés. Les archives sont reconstruites avec leurs empreintes. Aucun nouveau test d’inférence, d’installation sur téléphone ou de rendu navigateur n’a été réalisé pour cette maintenance. Les observations du 10 novembre ci-dessus restent celles de la bêta 1.

## Nouvelle validation native · 3.3.0-rc.1

Les sections précédentes décrivent les versions bêta et leurs environnements à la date indiquée. Elles ne constituent pas le bilan de la RC.

Le 12 novembre, les nouveaux conteneurs Windows et iOS ont exécuté un vrai modèle SmolLM2, puis l'ont rechargé depuis le cache lors d'une deuxième ouverture, avec 40 messages conservés. Windows : installation de l'EXE sur le runner Windows de GitHub Actions ; requêtes extérieures bloquées durant le second test. iOS : WKWebView dans le simulateur iPhone 18 Pro, iOS 27.2, chargement cache seul. Il ne s'agit pas d'un iPhone physique ni d'une distribution App Store.

Les 12 tests JavaScript passent. Le serveur Mac passe 263 contrôles hors ligne (LLM simulé, intégrations HTTP/WebSocket réelles) ; les tests de régression additionnels vérifient le refus d'exécuter sans protection, les conflits d'annulation, les copies récupérables, la lecture bornée des pièces jointes et l'arrêt des surveillants. Les résultats Android et la vérification des paquets finaux sont consignés dans les notes de RC et le dossier de livraison.
