import csv
from pathlib import Path

import psycopg


# ============================================================
# SAMRAKSHA KENDRA
# HOSPITAL DATA IMPORTER
# ============================================================


# ============================================================
# PROJECT PATH
# ============================================================

BASE_DIR = Path(__file__).resolve().parent.parent

CSV_FILE = BASE_DIR / "data" / "hospital_directory.csv"


# ============================================================
# DATABASE CONNECTION
# ============================================================

# IMPORTANT:
# Replace YOUR_PASSWORD with your PostgreSQL password.
#
# Example:
# postgresql://postgres:MyPassword@localhost:5432/samraksha_kendra

DATABASE_URL = (
    "postgresql://postgres:root@localhost:5432/samraksha_kendra"
)


# ============================================================
# CLEAN VALUE
# ============================================================

def clean(value):
    """
    Clean CSV values.

    Empty values and common placeholder values
    are converted to None.
    """

    if value is None:
        return None

    value = str(value).strip()

    if value == "":
        return None

    if value.lower() in {
        "null",
        "none",
        "nan",
        "na",
        "n/a",
    }:
        return None

    return value


# ============================================================
# IMPORT HOSPITALS
# ============================================================

def import_hospitals():

    print("=" * 46)
    print("SAMRAKSHA KENDRA - HOSPITAL DATA IMPORT")
    print("=" * 46)
    print()

    # --------------------------------------------------------
    # CHECK CSV FILE
    # --------------------------------------------------------

    if not CSV_FILE.exists():

        raise FileNotFoundError(
            f"Hospital CSV file was not found:\n{CSV_FILE}"
        )

    print("CSV file:")
    print(CSV_FILE)
    print()

    # --------------------------------------------------------
    # READ CSV
    # --------------------------------------------------------

    print("Reading hospital dataset...")

    with open(
        CSV_FILE,
        "r",
        encoding="utf-8-sig",
        newline=""
    ) as file:

        reader = csv.DictReader(file)

        rows = list(reader)

    print(f"Total CSV records: {len(rows)}")
    print()

    # --------------------------------------------------------
    # DATABASE CONNECTION
    # --------------------------------------------------------

    print("Connecting to PostgreSQL...")

    with psycopg.connect(DATABASE_URL) as conn:

        print("Database connection successful.")
        print()

        inserted = 0
        skipped = 0

        try:

            with conn.cursor() as cur:

                # ------------------------------------------------
                # PROCESS EVERY HOSPITAL
                # ------------------------------------------------

                for row in rows:

                    # --------------------------------------------
                    # HOSPITAL NAME
                    # --------------------------------------------

                    name = clean(
                        row.get("Hospital_Name")
                    )

                    # Hospital without a name is skipped.
                    if not name:

                        skipped += 1

                        continue

                    # --------------------------------------------
                    # STATE
                    # --------------------------------------------

                    state = (
                        clean(
                            row.get("State")
                        )
                        or "Not Specified"
                    )

                    # --------------------------------------------
                    # DISTRICT
                    # --------------------------------------------

                    district = (
                        clean(
                            row.get("District")
                        )
                        or "Not Specified"
                    )

                    # --------------------------------------------
                    # CITY
                    # --------------------------------------------

                    city = (
                        clean(
                            row.get("Town")
                        )
                        or clean(
                            row.get("Location")
                        )
                        or clean(
                            row.get("Village")
                        )
                        or "Not Specified"
                    )

                    # --------------------------------------------
                    # CATEGORY
                    # --------------------------------------------

                    category = (
                        clean(
                            row.get(
                                "Hospital_Category"
                            )
                        )
                        or "Not Specified"
                    )

                    # --------------------------------------------
                    # ADDRESS
                    # --------------------------------------------

                    address = (
                        clean(
                            row.get(
                                "Address_Original_First_Line"
                            )
                        )
                        or "Not Available"
                    )

                    # --------------------------------------------
                    # PINCODE
                    # --------------------------------------------

                    pincode = (
                        clean(
                            row.get("Pincode")
                        )
                        or "Not Available"
                    )

                    # --------------------------------------------
                    # PHONE
                    #
                    # We allow multiple phone numbers.
                    # Database column was increased to VARCHAR(100).
                    # --------------------------------------------

                    phone = (
                        clean(
                            row.get("Telephone")
                        )
                        or clean(
                            row.get("Mobile_Number")
                        )
                        or "Not Available"
                    )

                    # --------------------------------------------
                    # EMAIL
                    # --------------------------------------------

                    email = (
                        clean(
                            row.get(
                                "Hospital_Primary_Email_Id"
                            )
                        )
                        or clean(
                            row.get(
                                "Hospital_Secondary_Email_Id"
                            )
                        )
                        or "Not Available"
                    )

                    # --------------------------------------------
                    # WEBSITE
                    # --------------------------------------------

                    website = (
                        clean(
                            row.get("Website")
                        )
                        or "Not Available"
                    )

                    # --------------------------------------------
                    # INSERT INTO DATABASE
                    # --------------------------------------------

                    cur.execute(
                        """
                        INSERT INTO hospitals
                        (
                            name,
                            state,
                            district,
                            city,
                            category,
                            address,
                            pincode,
                            phone,
                            email,
                            website
                        )
                        VALUES
                        (
                            %s,
                            %s,
                            %s,
                            %s,
                            %s,
                            %s,
                            %s,
                            %s,
                            %s,
                            %s
                        )
                        """,
                        (
                            name,
                            state,
                            district,
                            city,
                            category,
                            address,
                            pincode,
                            phone,
                            email,
                            website,
                        )
                    )

                    inserted += 1

                    # --------------------------------------------
                    # PROGRESS
                    # --------------------------------------------

                    if inserted % 1000 == 0:

                        print(
                            f"Imported {inserted} hospitals..."
                        )

            # ----------------------------------------------------
            # COMMIT
            # ----------------------------------------------------

            conn.commit()

            print()
            print("=" * 46)
            print("IMPORT COMPLETED SUCCESSFULLY")
            print("=" * 46)
            print()
            print(f"Records inserted : {inserted}")
            print(f"Records skipped  : {skipped}")
            print()

        except Exception as error:

            # ----------------------------------------------------
            # ROLLBACK
            # ----------------------------------------------------

            conn.rollback()

            print()
            print("=" * 46)
            print("IMPORT FAILED")
            print("=" * 46)
            print()
            print("No partial records were committed.")
            print()
            print("Error:")
            print(error)
            print()

            raise


# ============================================================
# START PROGRAM
# ============================================================

if __name__ == "__main__":

    import_hospitals()