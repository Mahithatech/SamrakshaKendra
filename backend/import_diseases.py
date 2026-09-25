from app.database import SessionLocal
from app.models import Disease


DISEASES = [
    {
        "name": "Dengue",
        "category": "Vector-borne",
        "description": "A viral disease transmitted mainly by Aedes mosquitoes."
    },
    {
        "name": "Malaria",
        "category": "Vector-borne",
        "description": "A mosquito-borne disease caused by Plasmodium parasites."
    },
    {
        "name": "Chikungunya",
        "category": "Vector-borne",
        "description": "A viral disease transmitted by infected Aedes mosquitoes."
    },
    {
        "name": "Tuberculosis",
        "category": "Bacterial",
        "description": "An infectious bacterial disease that mainly affects the lungs."
    },
    {
        "name": "Influenza",
        "category": "Viral",
        "description": "A contagious respiratory illness caused by influenza viruses."
    },
    {
        "name": "Typhoid",
        "category": "Bacterial",
        "description": "An infectious disease caused by Salmonella Typhi."
    },
    {
        "name": "Cholera",
        "category": "Water-borne",
        "description": "An acute intestinal infection caused by Vibrio cholerae."
    },
    {
        "name": "Hepatitis A",
        "category": "Viral",
        "description": "A viral infection affecting the liver, commonly transmitted through contaminated food or water."
    },
    {
        "name": "Hepatitis B",
        "category": "Viral",
        "description": "A viral infection that affects the liver and can become chronic."
    },
    {
        "name": "Measles",
        "category": "Viral",
        "description": "A highly contagious viral respiratory disease."
    },
    {
        "name": "Mumps",
        "category": "Viral",
        "description": "A contagious viral infection that commonly causes swelling of the salivary glands."
    },
    {
        "name": "COVID-19",
        "category": "Respiratory",
        "description": "Respiratory infection caused by the SARS-CoV-2 virus."
    },
    {
        "name": "Japanese Encephalitis",
        "category": "Vector-borne",
        "description": "A viral infection transmitted by mosquitoes that can cause inflammation of the brain."
    },
    {
        "name": "Leptospirosis",
        "category": "Bacterial",
        "description": "A bacterial infection commonly transmitted through water or soil contaminated by infected animals."
    }
]


def import_diseases():
    db = SessionLocal()

    try:
        inserted = 0
        skipped = 0

        print("=" * 50)
        print("SAMRAKSHA KENDRA - DISEASE DATA IMPORT")
        print("=" * 50)

        for disease_data in DISEASES:

            existing = (
                db.query(Disease)
                .filter(Disease.name == disease_data["name"])
                .first()
            )

            if existing:
                skipped += 1
                print(f"Skipped: {disease_data['name']}")
                continue

            disease = Disease(
                name=disease_data["name"],
                category=disease_data["category"],
                description=disease_data["description"]
            )

            db.add(disease)
            inserted += 1

        db.commit()

        print()
        print("=" * 50)
        print("IMPORT COMPLETED")
        print("=" * 50)
        print(f"Diseases inserted : {inserted}")
        print(f"Diseases skipped  : {skipped}")

    except Exception:
        db.rollback()
        print()
        print("=" * 50)
        print("IMPORT FAILED")
        print("=" * 50)
        raise

    finally:
        db.close()


if __name__ == "__main__":
    import_diseases()