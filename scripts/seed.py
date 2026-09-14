"""
Seed script — generates ~500 realistic synthetic Pakistani applicant records
with deliberately varied data completeness.

Usage:
    # Start Postgres first:
    docker compose up -d

    # Run migrations:
    alembic upgrade head

    # Seed:
    python -m scripts.seed

Design decisions for realistic data:
  - 30% thin-file (1 signal category), 40% medium (2 categories),
    30% full (3 categories) — mirrors real intake data.
  - Cities and districts are real Pakistani locations.
  - CNICs follow the 13-digit format with realistic prefixes.
  - Income ranges reflect the informal economy (PKR 15k-150k/month).
  - Utility bills use realistic PKR amounts for Pakistani households.
"""

import math
import random
import sys
import uuid
from datetime import date, timedelta
from pathlib import Path

import numpy as np

# Ensure the project root is on the path.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy.orm import Session

from app.database import _get_session_factory
from app.models.applicant import Applicant
from app.models.academic_record import AcademicRecord
from app.models.income_signal import IncomeSignal
from app.models.utility_record import UtilityRecord
from app.services.feature_engineering import build_feature_vector
from app.utils.enums import (
    ApplicantType,
    EvidenceType,
    IncomeSourceType,
    QualificationLevel,
    ResultScale,
    UtilityType,
)

random.seed(42)
np.random.seed(42)

# ── Reference data ──────────────────────────────────────────────────────────

CITIES_DISTRICTS = [
    ("Karachi", "Karachi South"),
    ("Karachi", "Karachi East"),
    ("Lahore", "Lahore"),
    ("Islamabad", "Islamabad"),
    ("Rawalpindi", "Rawalpindi"),
    ("Faisalabad", "Faisalabad"),
    ("Multan", "Multan"),
    ("Peshawar", "Peshawar"),
    ("Quetta", "Quetta"),
    ("Sialkot", "Sialkot"),
    ("Gujranwala", "Gujranwala"),
    ("Hyderabad", "Hyderabad"),
    ("Bahawalpur", "Bahawalpur"),
    ("Sargodha", "Sargodha"),
    ("Sukkur", "Sukkur"),
    ("Larkana", "Larkana"),
    ("Abbottabad", "Abbottabad"),
    ("Mardan", "Mardan"),
    ("Muzaffarabad", "Muzaffarabad"),
    ("Dera Ghazi Khan", "Dera Ghazi Khan"),
    ("Sahiwal", "Sahiwal"),
    ("Nawabshah", "Nawabshah"),
    ("Mirpur Khas", "Mirpur Khas"),
    ("Jacobabad", "Jacobabad"),
    ("Rahim Yar Khan", "Rahim Yar Khan"),
]

INSTITUTIONS = [
    "University of the Punjab",
    "Quaid-i-Azam University",
    "LUMS",
    "FAST-NUCES",
    "NUST",
    "COMSATS University",
    "University of Karachi",
    "Dow University of Health Sciences",
    "Khyber Medical University",
    "University of Peshawar",
    "University of Balochistan",
    "Bahria University",
    "Air University",
    "Government College University Faisalabad",
    "University of Sargodha",
    "Islamia University Bahawalpur",
    "Gomal University",
    "University of Azad Jammu & Kashmir",
    "SZABIST",
    "Iqra University",
    "Beaconhouse National University",
    "Forman Christian College",
    "Kinnaird College",
    "Lahore College for Women University",
    "University of Education Lahore",
    "Punjab Group of Colleges",
    "Government College Lahore",
    "Cadet College Hasan Abdal",
    "Army Burn Hall College",
    "St. Patrick's High School Karachi",
]

# CNIC prefixes by province (first 5 digits).
CNIC_PREFIXES = {
    "Punjab": ["35202", "36101", "34201", "37301", "38403", "33100"],
    "Sindh": ["42101", "42201", "44101", "45101", "46101"],
    "KPK": ["17301", "16101", "15201", "14101", "13101"],
    "Balochistan": ["54101", "52101", "51101", "53101"],
}


def _generate_cnic() -> str:
    """Generate a realistic CNIC number (XXXXX-XXXXXXX-X)."""
    province = random.choice(list(CNIC_PREFIXES.keys()))
    prefix = random.choice(CNIC_PREFIXES[province])
    middle = "".join([str(random.randint(0, 9)) for _ in range(7)])
    check = str(random.randint(0, 9))
    return f"{prefix}-{middle}-{check}"


def _random_months(n: int, start_year: int = 2024) -> list[date]:
    """Generate n random month-start dates in the last 2 years."""
    base = date(start_year, 1, 1)
    months = []
    for i in range(n):
        offset = random.randint(0, 23)
        d = date(base.year + (base.month + offset - 1) // 12,
                 (base.month + offset - 1) % 12 + 1, 1)
        months.append(d)
    return sorted(months)


def _generate_utility_records(
    applicant_id: uuid.UUID, n_months: int | None = None
) -> list[UtilityRecord]:
    """Generate realistic utility bill records."""
    if n_months is None:
        n_months = random.randint(3, 18)

    records = []
    months = _random_months(n_months)

    # Each household typically has electricity, maybe gas and water.
    utility_types = [UtilityType.ELECTRICITY]
    if random.random() > 0.3:
        utility_types.append(UtilityType.GAS)
    if random.random() > 0.6:
        utility_types.append(UtilityType.WATER)

    # Payment behaviour profile for this applicant.
    is_reliable = random.random() > 0.35 # 65% are mostly reliable
    base_late_prob = 0.1 if is_reliable else 0.5

    for month in months:
        for utype in utility_types:
            # Realistic bill amounts in PKR.
            if utype == UtilityType.ELECTRICITY:
                amount = random.gauss(8000, 3000)
            elif utype == UtilityType.GAS:
                amount = random.gauss(2500, 1000)
            else:
                amount = random.gauss(1200, 400)

            amount = max(500, round(amount))

            # Late payment logic.
            if random.random() < base_late_prob:
                days_late = random.choice([1, 3, 5, 7, 10, 15, 20, 30])
                amount_paid = amount if random.random() > 0.2 else None
            else:
                days_late = 0
                amount_paid = amount

            # Occasionally leave amount_paid null (unpaid bill).
            if random.random() < 0.05:
                amount_paid = None

            records.append(UtilityRecord(
                id=uuid.uuid4(),
                applicant_id=applicant_id,
                utility_type=utype,
                billing_month=month,
                amount_billed=amount,
                amount_paid=amount_paid,
                days_late=days_late if random.random() > 0.1 else None,
            ))

    return records


def _generate_academic_records(applicant_type: ApplicantType) -> list[AcademicRecord]:
    """Generate 1-2 academic records appropriate to the applicant type."""
    records = []

    if applicant_type == ApplicantType.STUDENT:
        # Students typically have matric + intermediate or bachelors.
        n_records = random.choice([1, 2, 2, 3])
    elif applicant_type == ApplicantType.FREELANCER:
        # Freelancers may or may not have higher education.
        n_records = random.choice([0, 1, 1, 2])
    else:
        # Household applicants may have older qualifications.
        n_records = random.choice([0, 0, 1, 1])

    if n_records == 0:
        return records

    qualifications = []
    if applicant_type == ApplicantType.STUDENT:
        qualifications = random.sample(
            [QualificationLevel.MATRIC, QualificationLevel.INTERMEDIATE,
             QualificationLevel.BACHELORS],
            min(n_records, 3),
        )
    else:
        qualifications = random.sample(
            [QualificationLevel.MATRIC, QualificationLevel.INTERMEDIATE,
             QualificationLevel.BACHELORS, QualificationLevel.MASTERS,
             QualificationLevel.DIPLOMA],
            min(n_records, 5),
        )

    for qual in qualifications:
        # Choose scale based on qualification.
        if qual in (QualificationLevel.MATRIC, QualificationLevel.INTERMEDIATE):
            scale = ResultScale.PERCENTAGE
            value = random.gauss(68, 12) # Mean ~68%, SD 12
            value = round(max(33, min(95, value)), 1)
        elif qual == QualificationLevel.DIPLOMA:
            scale = random.choice([ResultScale.PERCENTAGE, ResultScale.DIVISION])
            if scale == ResultScale.PERCENTAGE:
                value = random.gauss(65, 10)
                value = round(max(33, min(95, value)), 1)
            else:
                value = float(random.choice([1, 2, 2, 3]))
        else:
            # Bachelors/Masters — mix of GPA and division.
            scale = random.choice([ResultScale.GPA, ResultScale.GPA, ResultScale.DIVISION])
            if scale == ResultScale.GPA:
                value = round(random.gauss(3.0, 0.5), 2)
                value = max(2.0, min(4.0, value))
            else:
                value = float(random.choice([1, 2, 2, 2, 3]))

        year = random.randint(2015, 2025)

        records.append(AcademicRecord(
            id=uuid.uuid4(),
            applicant_id=uuid.uuid4(), # Will be replaced.
            institution=random.choice(INSTITUTIONS),
            qualification_level=qual,
            result_value=value,
            result_scale=scale,
            year=year,
        ))

    return records


def _generate_income_signals(
    applicant_type: ApplicantType,
) -> list[IncomeSignal]:
    """Generate 1-3 income signals appropriate to the applicant type."""
    signals = []

    if applicant_type == ApplicantType.FREELANCER:
        source_types = random.sample(
            [IncomeSourceType.FREELANCE, IncomeSourceType.REMITTANCE],
            random.choice([1, 1, 2]),
        )
    elif applicant_type == ApplicantType.STUDENT:
        source_types = random.sample(
            [IncomeSourceType.INFORMAL_WORK, IncomeSourceType.REMITTANCE],
            random.choice([1, 1, 2]),
        )
    else:
        source_types = random.sample(
            [IncomeSourceType.INFORMAL_WORK, IncomeSourceType.AGRICULTURE,
             IncomeSourceType.REMITTANCE],
            random.choice([1, 2, 2]),
        )

    for source in source_types:
        # Income ranges in PKR/month.
        if source == IncomeSourceType.FREELANCE:
            amount = random.gauss(45000, 20000)
        elif source == IncomeSourceType.REMITTANCE:
            amount = random.gauss(35000, 15000)
        elif source == IncomeSourceType.AGRICULTURE:
            amount = random.gauss(25000, 10000)
        else:
            amount = random.gauss(20000, 8000)

        amount = max(8000, round(amount, -2)) # Round to nearest 100

        evidence = random.choices(
            [EvidenceType.SELF_DECLARED, EvidenceType.DOCUMENTED, EvidenceType.VERIFIED],
            weights=[0.5, 0.35, 0.15],
        )[0]

        confidence = evidence == EvidenceType.VERIFIED or (
            evidence == EvidenceType.DOCUMENTED and random.random() > 0.5
        )

        signals.append(IncomeSignal(
            id=uuid.uuid4(),
            applicant_id=uuid.uuid4(), # Will be replaced.
            source_type=source,
            declared_monthly_amount=amount,
            evidence_type=evidence,
            confidence_flag=confidence,
        ))

    return signals


def generate_applicants(n: int = 500) -> list[Applicant]:
    """
    Generate n synthetic applicants with deliberately varied data completeness.

    Distribution:
      - 30% thin file (1 signal category)
      - 40% medium (2 signal categories)
      - 30% full (3 signal categories)
    """
    applicants = []

    for i in range(n):
        # Determine data completeness profile.
        profile = random.choices(
            ["thin", "medium", "full"],
            weights=[0.30, 0.40, 0.30],
        )[0]

        applicant_type = random.choice([
            ApplicantType.STUDENT,
            ApplicantType.FREELANCER,
            ApplicantType.HOUSEHOLD,
        ])

        city, district = random.choice(CITIES_DISTRICTS)

        applicant = Applicant(
            id=uuid.uuid4(),
            identity_reference=_generate_cnic(),
            applicant_type=applicant_type,
            household_size=random.randint(2, 12) if random.random() > 0.15 else None,
            city=city,
            district=district,
            dependants=random.randint(0, 6) if random.random() > 0.2 else None,
        )

        # Generate records based on profile.
        if profile == "thin":
            # Only one signal category.
            category = random.choice(["utility", "academic", "income"])
            if category == "utility":
                applicant.utility_records = _generate_utility_records(
                    applicant.id, n_months=random.randint(2, 6)
                )
            elif category == "academic":
                acad = _generate_academic_records(applicant_type)
                for a in acad:
                    a.applicant_id = applicant.id
                applicant.academic_records = acad
            else:
                inc = _generate_income_signals(applicant_type)
                for s in inc:
                    s.applicant_id = applicant.id
                applicant.income_signals = inc

        elif profile == "medium":
            # Two signal categories.
            categories = random.sample(
                ["utility", "academic", "income"], 2
            )
            if "utility" in categories:
                applicant.utility_records = _generate_utility_records(
                    applicant.id, n_months=random.randint(3, 12)
                )
            if "academic" in categories:
                acad = _generate_academic_records(applicant_type)
                for a in acad:
                    a.applicant_id = applicant.id
                applicant.academic_records = acad
            if "income" in categories:
                inc = _generate_income_signals(applicant_type)
                for s in inc:
                    s.applicant_id = applicant.id
                applicant.income_signals = inc

        else:
            # Full data across all three categories.
            applicant.utility_records = _generate_utility_records(
                applicant.id, n_months=random.randint(6, 18)
            )
            acad = _generate_academic_records(applicant_type)
            for a in acad:
                a.applicant_id = applicant.id
            applicant.academic_records = acad
            inc = _generate_income_signals(applicant_type)
            for s in inc:
                s.applicant_id = applicant.id
            applicant.income_signals = inc

        applicants.append(applicant)

    return applicants


# ── Label generation (independent of rule-based scorer) ─────────────────
# The latent approval model uses DIFFERENT weights from the rule-based
# scorer so the ML model has something genuine to learn, not just the
# hand-tuned rules to memorise.

_LABEL_WEIGHTS: dict[str, float] = {
    "payment_on_time_ratio": 0.12, # rule-based: 0.30
    "longest_on_time_streak": 0.03, # rule-based: 0.10
    "mean_days_late": 0.05, # rule-based: 0.10
    "payment_consistency": 0.18, # rule-based: 0.10
    "academic_signal": 0.22, # rule-based: 0.15
    "household_burden": 0.25, # rule-based: 0.10
    "income_confidence": 0.05, # rule-based: 0.08
    "total_income_normalised": 0.10, # rule-based: 0.07
}

_FEATURE_MEANS: dict[str, float] = {
    "payment_on_time_ratio": 0.65,
    "longest_on_time_streak": 0.30,
    "mean_days_late": 0.75,
    "payment_consistency": 0.70,
    "academic_signal": 0.55,
    "household_burden": 0.60,
    "income_confidence": 0.55,
    "total_income_normalised": 0.45,
}


def generate_labels(applicants: list[Applicant]) -> None:
    """
    Generate synthetic reviewer-approval labels from an independent latent
    model. The weights deliberately differ from the rule-based scorer so
    that the ML model learns genuine patterns rather than memorising rules.

    Adds ``reviewer_approved`` (bool) and ``approval_score`` (float 0-1)
    to each applicant in-place.
    """
    n = len(applicants)
    print(" Generating independent labels...")

    for idx, applicant in enumerate(applicants):
        feature_set = build_feature_vector(applicant)
        features = feature_set.features

        # Weighted sum with imputed means for missing features.
        latent = 0.0
        for name, weight in _LABEL_WEIGHTS.items():
            val = features.get(name)
            latent += weight * (val if val is not None else _FEATURE_MEANS.get(name, 0.5))

        # Gaussian noise — represents unpredictable reviewer judgement.
        noise = np.random.normal(0, 0.10)
        latent = max(0.0, min(1.0, latent + noise))

        # Sigmoid → approval probability.
        approval_prob = 1.0 / (1.0 + math.exp(-8.0 * (latent - 0.48)))

        # Bernoulli sample → binary decision.
        approved = bool(np.random.random() < approval_prob)

        # Random label flip (~8%): represents reviewer inconsistency.
        if np.random.random() < 0.08:
            approved = not approved

        # Contrarian cases (~5%): observable signals disagree with outcome.
        non_null = feature_set.non_null_count
        if non_null >= 5 and np.random.random() < 0.05:
            approved = not approved

        # Continuous target with independent noise for the regression model.
        score_noise = np.random.normal(0, 0.06)
        continuous = max(0.05, min(0.95, latent * 0.85 + score_noise + 0.08))

        applicant.reviewer_approved = approved
        applicant.approval_score = round(continuous, 4)

    approved_count = sum(1 for a in applicants if a.reviewer_approved)
    print(f" Approved: {approved_count}/{n} ({approved_count / n:.0%})")
    print(f" Denied: {n - approved_count}/{n} ({(n - approved_count) / n:.0%})")


def main():
    """Seed the database with synthetic applicants."""
    print("Generating 500 synthetic Pakistani applicants...")
    applicants = generate_applicants(500)

    # Count profiles.
    thin = sum(
        1 for a in applicants
        if sum([
            bool(a.utility_records),
            bool(a.academic_records),
            bool(a.income_signals),
        ]) == 1
    )
    medium = sum(
        1 for a in applicants
        if sum([
            bool(a.utility_records),
            bool(a.academic_records),
            bool(a.income_signals),
        ]) == 2
    )
    full = sum(
        1 for a in applicants
        if sum([
            bool(a.utility_records),
            bool(a.academic_records),
            bool(a.income_signals),
        ]) == 3
    )
    zero = len(applicants) - thin - medium - full

    print(f" Thin (1 category): {thin}")
    print(f" Medium (2 categories): {medium}")
    print(f" Full (3 categories): {full}")
    print(f" Zero (no data): {zero}")

    # Count total records.
    n_utility = sum(len(a.utility_records) for a in applicants)
    n_academic = sum(len(a.academic_records) for a in applicants)
    n_income = sum(len(a.income_signals) for a in applicants)
    print(f"\n Total utility records: {n_utility}")
    print(f" Total academic records: {n_academic}")
    print(f" Total income signals: {n_income}")

    # Generate independent training labels from features.
    generate_labels(applicants)

    # Insert into database.
    print("\nInserting into database...")
    SessionLocal = _get_session_factory()
    db: Session = SessionLocal()
    try:
        db.add_all(applicants)
        db.commit()
        print(f"Successfully seeded {len(applicants)} applicants.")
    except Exception as e:
        db.rollback()
        print(f"Error seeding database: {e}")
        raise
    finally:
        db.close()


if __name__ == "__main__":
    main()
