"""
Migration Script: Convert arrival_date and departure_date from Datetime to Date + Time fields.
Step 2: Alter column types (DDL). Run after the time extraction is done.

Usage:
    bench --site <sitename> execute hospitality_core._dev_scripts.migrate_datetime_to_date_time.run_ddl
"""
import frappe

def run_ddl():
    site = frappe.local.site
    print(f"\n=== DDL Migration: Alter columns to DATE for Hotel Reservation on site {site} ===\n")

    # Check current types
    columns = frappe.db.sql("DESCRIBE `tabHotel Reservation`", as_dict=True)
    arr_col = next((c for c in columns if c["Field"] == "arrival_date"), None)
    dep_col = next((c for c in columns if c["Field"] == "departure_date"), None)

    print(f"Current arrival_date type: {arr_col['Type'] if arr_col else 'NOT FOUND'}")
    print(f"Current departure_date type: {dep_col['Type'] if dep_col else 'NOT FOUND'}")

    # Commit any pending transaction first
    frappe.db.commit()

    # Now run DDL outside of a transaction using the raw connection
    conn = frappe.db.sql("SELECT 1")  # ensure connection is alive
    
    print("\nConverting arrival_date column to DATE type...")
    frappe.db._cursor.execute("ALTER TABLE `tabHotel Reservation` MODIFY `arrival_date` DATE DEFAULT NULL")

    print("Converting departure_date column to DATE type...")
    frappe.db._cursor.execute("ALTER TABLE `tabHotel Reservation` MODIFY `departure_date` DATE DEFAULT NULL")

    print("Column types converted successfully.")

    # Verify
    columns = frappe.db.sql("DESCRIBE `tabHotel Reservation`", as_dict=True)
    arr_col = next((c for c in columns if c["Field"] == "arrival_date"), None)
    dep_col = next((c for c in columns if c["Field"] == "departure_date"), None)
    print(f"\nNew arrival_date type: {arr_col['Type'] if arr_col else 'NOT FOUND'}")
    print(f"New departure_date type: {dep_col['Type'] if dep_col else 'NOT FOUND'}")

    # Verify data
    print("\n--- Data Verification ---")
    result = frappe.db.sql("""
        SELECT name, arrival_date, arrival_time, departure_date, departure_time
        FROM `tabHotel Reservation`
        ORDER BY name
        LIMIT 10
    """, as_dict=True)

    for r in result:
        print(f"  {r.name}: arr={r.arrival_date} {r.arrival_time}, dep={r.departure_date} {r.departure_time}")

    print(f"\n=== DDL Migration Complete ===\n")
