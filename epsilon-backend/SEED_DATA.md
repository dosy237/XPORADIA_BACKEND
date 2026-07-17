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
