"""Xporadia — apps/employment/constants.py"""

# CDC US-03-08 : l'avis employeur ne se déclenche que 30 jours après la
# confirmation du recrutement — laisse le temps à l'enseignant de se faire
# une vraie opinion plutôt qu'une impression à chaud.
REVIEW_MIN_DAYS_AFTER_RECRUITMENT = 30

# Affichage agrégé sur la fiche établissement seulement à partir de ce
# nombre d'avis — protège l'anonymat (un seul avis identifierait
# implicitement son auteur) et évite qu'un avis isolé ne pèse trop.
MIN_REVIEWS_FOR_PUBLIC_DISPLAY = 3
