# Jeu de données de démonstration

Générées par `python manage.py seed_demo_data` (voir aussi `make setup` /
`make seed`). La commande est idempotente : la relancer ne duplique rien,
elle complète juste ce qui manque.

**Mot de passe commun à tous les comptes ci-dessous : `Xporadia2026!`**

---

## Comptes enseignants

| Email | Niveau de certification | Particularité |
|---|---|---|
| `awa.teacher@xporadia.ci` | Bronze | Disponible cours particuliers + emploi |
| `yao.teacher@xporadia.ci` | Bronze + Argent | Titulaire de la classe 5ème A |
| `aminata.teacher@xporadia.ci` | Bronze + Argent + **Or** | Privilège "demande d'emploi" actif, recrutée (voir Recrutements) |
| `ibrahim.teacher@xporadia.ci` | Aucune | Titulaire de la classe CM2 A, a postulé à une offre d'emploi, inscrit à une session de formation (payée) |
| `mariam.teacher@xporadia.ci` | Bronze | Enseignante dédiée de Mathématiques (CM2 A) |
| `konan.trainer@xporadia.ci` | — (rôle formateur) | Anime toutes les sessions de formation en présentiel |

## Comptes directeurs / établissements

| Email | Établissement |
|---|---|
| `kouassi.director@xporadia.ci` | Groupe Scolaire La Réussite (Cocody) — Primaire+Collège, 2 classes, 4 matières |
| `adjoua.director@xporadia.ci` | Institution Sainte Marie (Yopougon) — Collège, 1 classe |

## Comptes parents / enfants

| Email | Enfants (classe réelle) |
|---|---|
| `fatou.parent@xporadia.ci` | Aïcha (5ème A, La Réussite) · Ibrahim Jr (CM2 A, La Réussite) |
| `aya.parent@xporadia.ci` | Kouadio (6ème B, Sainte Marie) |
| `bakary.parent@xporadia.ci` | Mariam Jr (5ème A, La Réussite) |

## Comptes entreprises

| Email | Entreprise |
|---|---|
| `contact.entreprise@xporadia.ci` | Ivoire Digital Solutions |
| `rh.entreprise2@xporadia.ci` | Abidjan Tech Hub |

---

## Ce qui est déjà rempli, par fonctionnalité

- **Certification** : 5 modules (Bronze→Or), 4 questions QCM/Vrai-Faux sur le
  module Bronze (examen en ligne testable), 6 sessions en présentiel à venir,
  7 certifications déjà délivrées, 1 inscription payée à une session.
- **Structure académique** : 2 établissements, 2 départements, 3 classes,
  5 matières, 4 inscriptions d'élèves.
- **Espace élève (Classes)** : 2 devoirs publiés avec copies (une déjà
  corrigée avec note, une en attente), 1 devoir en brouillon.
- **Bibliothèque** : 2 ressources (cours + fiche de révision).
- **Emploi** : 1 offre active + 1 candidature en attente, 1 offre brouillon,
  1 recrutement déjà conclu, 1 demande d'emploi (privilège Or).
- **Stages** : 1 offre avec candidature acceptée → convention complète (signée
  des deux côtés) avec un journal de stage et une évaluation, 1 offre avec
  candidature encore en attente.
- **Cours particuliers** : 1 séance terminée avec avis 5★ et paiement libéré,
  1 séance confirmée (paiement séquestré, pas encore terminée).

## Se connecter

Toutes les captures d'écran de ce projet ont été vérifiées avec ces comptes.
Connectez-vous simplement avec l'un des emails ci-dessus et le mot de passe
`Xporadia2026!` sur http://localhost:19006 (web) une fois le backend et le
frontend lancés.

## Réinitialiser

```bash
python manage.py seed_demo_data --reset   # supprime tous les comptes @xporadia.ci puis les recrée
```

---

# Écosystème vitrine (élève / enseignant / parent)

Généré par `python manage.py seed_student_showcase`, en complément de
`seed_demo_data` ci-dessus. Différence de philosophie : au lieu de
comptes isolés montrant chacun une seule fonctionnalité, cette commande
construit **un seul établissement cohérent** (Lycée Démo Complet) où
élève, enseignant titulaire et parent sont réellement liés entre eux —
se connecter avec n'importe lequel des trois comptes principaux donne
accès à de vraies données interconnectées, pas des fixtures isolées.
Entièrement idempotente elle aussi (`--reset` n'existe pas ici : relancer
la commande ne duplique jamais rien, elle complète seulement ce qui
manque).

**Mot de passe commun : `Xporadia2026!`**

## Les trois comptes principaux

| Rôle | Email | Ce qui est couvert |
|---|---|---|
| Élève | `demo.eleve.showcase@xporadia.ci` (Kevin Ouattara, Terminale D2) | Dashboard complet (radar, courbe, devoirs, activité sociale), Ma classe (5 matières dont Philosophie), Mes devoirs (3 états), Bulletins (T1/T2 publiés, T3 non publié), Mes résultats (notes du tableur), Bibliothèque (5 ressources), Agenda (cours + créneau perso + exception + jour férié), Messagerie (DM enseignant + camarade + canal de matière), Vie & objectifs |
| Enseignante | `demo.titulaire.showcase@xporadia.ci` (Fatou Diabaté, titulaire Terminale D2 + professeure de Philosophie) | Gestion de classe (bulletins, événements, promotion de fin d'année vers Terminale D1, délégation d'emploi du temps reçue de la direction), grille de notes + copies à corriger, certification (Bronze déjà obtenu, Argent disponible pour un examen en ligne réel), formation continue (session à venir, inscription payée), emploi (candidature en attente + recrutement confirmé chez un second établissement), portefeuille (un mois déjà payé + des heures en attente de validation) |
| Parent | `demo.parent.showcase@xporadia.ci` (Ramata Ouattara) | Trois enfants dans des états différents (Kevin, pleinement suivi ; Aminata, ajoutée manuellement sans compte propre ; Yssouf, réclamé et approuvé par le passé), historique de demande de rattachement résolue, espace enfant riche (mêmes données que la vue élève) |

## Comptes secondaires (support de l'écosystème)

| Email | Rôle |
|---|---|
| `demo.directeur.showcase@xporadia.ci` (Solange Bakayoko) | Directrice du Lycée Démo Complet |
| `demo.directeur2.showcase@xporadia.ci` (Yves N'Guessan) | Directeur du Collège Passerelle — second établissement, employeur de Fatou en vacation |
| `demo.prof.maths.showcase@xporadia.ci` / `demo.prof.pc.showcase@xporadia.ci` / `demo.prof.francais.showcase@xporadia.ci` / `demo.prof.anglais.showcase@xporadia.ci` | Les 4 autres enseignants dédiés de la classe de Kevin |
| `demo.formateur.showcase@xporadia.ci` (Konan Assouan) | Formateur animant la session de certification à venir |
| `demo.camarade.showcase@xporadia.ci` / `demo.camarade2.showcase@xporadia.ci` | Camarades de classe de Kevin (le second n'a aucune conversation existante, pour tester le démarrage d'une toute nouvelle DM) |
| `demo.eleve.autoinscrit.showcase@xporadia.ci` (Salimata Coulibaly) + `demo.parent.enattente.showcase@xporadia.ci` (Yacouba Coulibaly) | Élève auto-inscrite avec une demande de rattachement encore **en attente** |
| `demo.eleve.libre.showcase@xporadia.ci` (Nafissatou Diallo) | Élève auto-inscrite **jamais réclamée par personne** — pour tester une toute nouvelle demande de rattachement en conditions réelles depuis n'importe quel compte parent |

## Réinitialiser

Pas d'option `--reset` dédiée : ces comptes portent le suffixe
`.showcase@xporadia.ci`, distinct des comptes `seed_demo_data` — les
supprimer manuellement (`User.objects.filter(email__endswith=".showcase@xporadia.ci").delete()`)
avant de relancer la commande reconstruit tout depuis zéro si besoin.
