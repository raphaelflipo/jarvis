# Installation personnelle gratuite sur iPhone

Jarvis Local 3.3.0-rc.2, build 33002, peut être signé avec une équipe personnelle gratuite dans Xcode. Cette installation de développement est distincte d'une diffusion App Store ou TestFlight : le profil expire après 7 jours et l'application doit alors être réinstallée depuis le Mac. Ne pas la présenter comme un téléchargement public durable.

## Étapes dans Xcode

1. Brancher son iPhone au Mac et le déverrouiller. Valider personnellement la confiance envers le Mac et le mode développeur si iOS les demande.
2. Ouvrir `native/ios/Jarvis.xcodeproj`. Sélectionner le projet, puis la cible Jarvis et l'onglet **Signing & Capabilities**.
3. Activer **Automatically manage signing** et sélectionner sa **Personal Team**. Si nécessaire, se connecter soi-même dans **Xcode > Settings > Apple Accounts** ; aucun mot de passe ne doit être communiqué à une autre personne.
4. Conserver l'identifiant `io.github.raphaelflipo.jarvis`, sélectionner son iPhone comme destination, puis utiliser **Product > Run**.
5. Dans Jarvis, télécharger le modèle léger puis envoyer un premier message. Une connexion Internet est nécessaire au téléchargement ; le calcul s'effectue sur le téléphone.

L'identifiant entre parenthèses dans le nom d'un certificat Apple Development n'est pas nécessairement l'identifiant de l'équipe. La sélection de Personal Team dans Xcode évite cette confusion. Pour une compilation en ligne de commande, utiliser le véritable Team ID, jamais le déduire du suffixe du certificat.

Pour renouveler : reconnecter l'iPhone et refaire **Product > Run** avec la même équipe et le même identifiant. Ne pas désinstaller Jarvis avant la mise à jour : cela peut effacer ses données. Conserver des sauvegardes avant toute opération de maintenance importante.

Apple limite les équipes personnelles à 3 appareils, 3 applications par appareil et 10 identifiants d'application ; ces ressources sont renouvelables selon ses règles. [Conditions officielles](https://developer.apple.com/help/account/basics/about-your-developer-account/).

## Diffusion publique sans nouvelle dépense

Une équipe personnelle ne donne pas accès à une diffusion publique native durable. Si une organisation possède déjà une adhésion adaptée et autorise ce projet, son responsable peut inviter le développeur et organiser la publication. Certains organismes sans but lucratif, établissements d'enseignement et organismes publics peuvent demander une exonération à Apple. Une personne seule ou le seul statut d'étudiant ne suffisent pas ; l'organisme doit être éligible et accepter les responsabilités de publication. [Critères officiels de l'exonération](https://developer.apple.com/help/account/membership/fee-waivers/).

La validation de compte, les accords et toute éventuelle demande d'exonération sont réalisés personnellement par le titulaire ou le représentant habilité. Aucune inscription payante n'est nécessaire pour les essais personnels décrits ci-dessus.
