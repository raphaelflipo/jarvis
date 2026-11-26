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

## Candidat web bilingue du 26 novembre 2026

- Chromium sur Mac a vérifié le français et l’anglais à 320, 390, 768 et 1 440 pixels. Le test couvre les réglages, la recommandation sur appareil à mémoire limitée, la conservation de l’historique lors du changement de langue et l’interface d’erreur, d’annulation et de reprise.
- Le test de navigateur a isolé le réseau et utilisé un worker simulé. Il a contrôlé le calcul de l’indicateur avec huit tokens produits en deux secondes, ainsi que le refus de démarrer hors ligne avec un cache incomplet.
- Quatre tests Node passent pour l’installation du cache léger, la récupération à la demande du moteur et sa lecture hors ligne, la migration de la version précédente sans effacer les modèles et le périmètre du service worker.
- Le code d’inférence conserve les deux modèles et les mêmes révisions de leurs fichiers. La génération avec les poids réels reste couverte par les essais antérieurs décrits ci-dessus. Les nouveaux essais ne mesurent pas la vitesse d’inférence sur ces poids.

### Paquets natifs publiés

Les fiches française et anglaise reprennent les empreintes SHA-256 que l’API GitHub associe aux trois paquets publiés. Les essais de signature et d’installation restent ceux des notes de version jointes aux paquets.

| Paquet | Taille exacte | Statut |
|---|---:|---|
| macOS arm64 RC1 | 722 054 824 octets | Signature locale ad hoc. Gatekeeper a bloqué le paquet lors de la validation. |
| Windows x64 RC2 | 125 032 625 octets | Signature Authenticode absente. Essai documenté sur Windows Server 2025. |
| Android RC2 | 5 638 632 octets | APK signé. Essai documenté sur émulateur Android 15. |
| iPhone et iPad | — | Version web installable depuis Safari. Archive native de préparation à la distribution, réservée aux vérifications techniques. |

Le paquet Mac regroupe l’application, Python et Ollama. Les séparer allégerait le paquet initial et reporterait une partie de l’installation au premier démarrage. Le DMG publié correspond à l’édition autonome. Une diffusion notarialisée requiert les accès et certificats décrits par Apple. [Certificats Developer ID](https://developer.apple.com/help/account/certificates/create-developer-id-certificates)

## Réception web du 26 novembre 2026

Sur Linux x86-64, Chromium 149.0.7827.0, fenêtre 390 × 844. Le worker de production a exécuté SmolLM2-135M-Instruct q8, révision 12fd25f77366fa6b3b4b768ec3050bf629380bac, en WebAssembly mono-thread. L’ONNX de 137 147 981 octets téléchargé depuis Hugging Face avait pour SHA-256 ecc1a19eece6494e2963cf74f78ace35916e8d0b803168ddd41db00979f18e39.

Les réponses HTTP du serveur de test ont rejoué les octets authentiques. Une interruption imposée après le premier bloc a laissé un bloc dans CacheStorage. Le nouvel essai a demandé l’octet 4 194 304 et a terminé le fichier. Les quatre fichiers de configuration et de tokenizer ont été chargés. Le modèle a produit « The capital of France is Paris. ». Après coupure réseau et rechargement complet, il a produit « The capital of Italy is Rome. ». L’historique contenait les quatre messages. Un arrêt durant une nouvelle génération puis le retour à l’interface française ont été vérifiés. Les réponses du modèle sont calculées dans le véritable worker. La livraison Internet par le CDN, le temps d’un téléphone et Qwen font l’objet de validations distinctes.

Les tests Node exécutent le service worker distribué avec des API de cache et de réseau simulées. Les essais de novembre cités plus haut constituent l’historique de la bêta.

La migration a aussi été exercée dans CacheStorage sur la même origine. L’ancienne source installait le cache `jarvis-local-shell-3.3.0-rc.2`. Après mise à jour, les octets du moteur WASM avaient la même empreinte, l’entrée témoin du cache modèle et un message d’historique étaient conservés. Le second nom historique `-web.1` est couvert par un test du service worker exécuté avec des API simulées.
