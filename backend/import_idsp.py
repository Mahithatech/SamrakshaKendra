import csv
from pathlib import Path
from datetime import datetime

from sqlalchemy.orm import Session

from app.database import SessionLocal
from app.models import IDSPSurveillance


CSV_FILE = Path("data/idsp_surveillance.csv")


def import_idsp():

    if not CSV_FILE.exists():
        print(f"CSV not found: {CSV_FILE}")
        return

    db: Session = SessionLocal()

    inserted = 0
    skipped = 0

    try:

        with open(
            CSV_FILE,
            "r",
            encoding="utf-8-sig",
            newline=""
        ) as file:

            reader = csv.DictReader(file)

            for row in reader:

                try:

                    record_id = row["record_id"].strip()

                    # Prevent duplicate records
                    existing = (
                        db.query(IDSPSurveillance)
                        .filter(
                            IDSPSurveillance.record_id == record_id
                        )
                        .first()
                    )

                    if existing:
                        skipped += 1
                        continue

                    record = IDSPSurveillance(
                        record_id=record_id,
                        year=int(row["year"]),
                        week=int(row["week"]),

                        reporting_start_date=datetime.strptime(
                            row["reporting_start_date"],
                            "%Y-%m-%d"
                        ).date(),

                        reporting_end_date=datetime.strptime(
                            row["reporting_end_date"],
                            "%Y-%m-%d"
                        ).date(),

                        state=row["state"].strip(),
                        district=row["district"].strip(),
                        disease=row["disease"].strip(),

                        cases=int(row["cases"]) if row["cases"] else 0,
                        deaths=int(row["deaths"]) if row["deaths"] else 0,

                        outbreak_status=(
                            row["outbreak_status"].strip()
                            if row["outbreak_status"]
                            else None
                        ),

                        source=(
                            row["source"].strip()
                            if row["source"]
                            else None
                        ),

                        source_url=(
                            row["source_url"].strip()
                            if row["source_url"]
                            else None
                        )
                    )

                    db.add(record)
                    inserted += 1

                except Exception as row_error:

                    print(
                        f"Row skipped: {row_error}"
                    )

                    skipped += 1

            db.commit()

        print()
        print("================================")
        print("IDSP IMPORT COMPLETE")
        print("================================")
        print(f"Inserted : {inserted}")
        print(f"Skipped  : {skipped}")
        print("================================")

    except Exception as error:

        db.rollback()

        print()
        print("IMPORT FAILED")
        print(error)

    finally:
        db.close()


if __name__ == "__main__":
    import_idsp()