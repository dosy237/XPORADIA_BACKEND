"""
Xporadia — apps/grading/admission_report.py

Rapport d'admission (concours d'entrée, etc.) déposé par l'établissement —
PDF ou CSV. Le rapprochement avec les demandes de rattachement en attente
est une PROPOSITION, jamais une décision : rien n'est écrit en base tant
que le directeur n'a pas validé (voir ConfirmAdmissionReportView).
"""
import csv
import difflib
import io
import unicodedata


def _normalize_name(text: str) -> str:
    text = unicodedata.normalize("NFKD", text or "").encode("ascii", "ignore").decode()
    return " ".join(text.lower().split())


def _name_similarity(a: str, b: str) -> float:
    """Similarité entre deux noms — prend le meilleur des deux : la
    comparaison brute, et une comparaison par mots triés alphabétiquement
    (insensible à l'ordre nom/prénom, très fréquent dans les documents
    administratifs francophones — "Kouassi Yao" doit être reconnu
    équivalent à "Yao Kouassi")."""
    raw_score = difflib.SequenceMatcher(None, a, b).ratio()
    sorted_a = " ".join(sorted(a.split()))
    sorted_b = " ".join(sorted(b.split()))
    sorted_score = difflib.SequenceMatcher(None, sorted_a, sorted_b).ratio()
    return max(raw_score, sorted_score)


def parse_csv_report(file) -> list[dict]:
    """CSV attendu avec au moins une colonne nom ; une colonne statut
    (admis/rejeté, admitted/rejected) est utilisée si présente, sinon
    tout le monde est considéré "admis" par défaut — le directeur peut
    corriger chaque ligne avant confirmation de toute façon."""
    content = file.read().decode("utf-8-sig", errors="ignore")
    reader = csv.DictReader(io.StringIO(content))
    rows = []
    for row in reader:
        keys_lower = {k.lower().strip(): v for k, v in row.items() if k}
        name = keys_lower.get("name") or keys_lower.get("nom") or next(iter(row.values()), "")
        raw_status = (keys_lower.get("status") or keys_lower.get("statut") or "").strip().lower()
        status = "rejected" if raw_status in ("rejete", "rejeté", "rejected", "refuse", "refusé") else "admitted"
        if name and name.strip():
            rows.append({"name": name.strip(), "status": status})
    return rows


def parse_pdf_report(file) -> list[dict]:
    """PDF — extraction de texte brute uniquement. Contrairement au CSV,
    on ne tente JAMAIS de deviner automatiquement qui est admis ou rejeté
    depuis un PDF (mise en page trop variable pour être fiable) : chaque
    ligne extraite est renvoyée sans statut, à trancher par le directeur."""
    from pypdf import PdfReader

    reader = PdfReader(file)
    lines = []
    for page in reader.pages:
        text = page.extract_text() or ""
        for line in text.splitlines():
            cleaned = line.strip()
            # Ignore les lignes trop courtes ou purement numériques
            # (numéros de page, en-têtes de tableau, etc.)
            if len(cleaned) >= 3 and not cleaned.replace(" ", "").isdigit():
                lines.append({"name": cleaned, "status": None})
    return lines


def match_report_to_join_requests(extracted_lines: list[dict], pending_join_requests) -> list[dict]:
    """Rapproche chaque ligne extraite à la demande de rattachement en
    attente dont le nom d'élève est le plus proche — score de similarité
    inclus, jamais un rapprochement automatique appliqué sans relecture
    humaine. Seuil de 0.6 en dessous duquel on ne propose rien (mieux
    vaut ne rien proposer qu'un mauvais rapprochement)."""
    candidates = [
        (jr, _normalize_name(f"{jr.child.first_name} {jr.child.last_name}"))
        for jr in pending_join_requests
    ]

    proposals = []
    for line in extracted_lines:
        normalized_line = _normalize_name(line["name"])
        best_match = None
        best_score = 0.0
        for join_request, candidate_name in candidates:
            score = _name_similarity(normalized_line, candidate_name)
            if score > best_score:
                best_score = score
                best_match = join_request

        proposals.append({
            "extracted_name": line["name"],
            "extracted_status": line["status"],
            "matched_join_request_id": best_match.id if best_match and best_score >= 0.6 else None,
            "matched_child_name": (
                f"{best_match.child.first_name} {best_match.child.last_name}"
                if best_match and best_score >= 0.6 else None
            ),
            "match_score": round(best_score, 2),
        })
    return proposals
