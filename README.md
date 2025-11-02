🧩 Angular → Django Wizard

Assistant graphique universel pour intégrer et déployer une application Angular sur un backend Django, sans configuration manuelle.

⚙️ Fonctionnalités principales

Ajout automatique des paramètres STATIC_URL, STATICFILES_DIRS, TEMPLATES dans settings.py

Gestion idempotente des urls.py (root + fallback SPA)

Transformation automatique du index.html Angular ({% load static %})

Copie et synchronisation des assets dans static/

Sauvegarde automatique des fichiers modifiés dans _backups/

Interface Tkinter

Sauvegarde et chargement des chemins via JSON

Compatible Windows, sans installation (exécutable portable)

🧱 Structure du projet

angular-django-wizard/
├── angular_django_wizard.py
├── build.ps1
├── version_info.txt
├── assets/
│ └── wizard.ico
└── dist/
└── AngularDjangoWizard.exe

🪄 Build

Set-ExecutionPolicy -Scope Process RemoteSigned
.\build.ps1 -Clean

🧰 Utilisation

Double-clique sur AngularDjangoWizard.exe
Choisis ton projet Django et ton dossier dist/browser
Le wizard configure tout automatiquement : settings.py, urls.py, templates/index.html, etc.
Clique sur collectstatic pour finaliser.

🪪 Licence

MIT © 2025 — Open Source