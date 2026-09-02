import frappe

def execute():
    frappe.init(site="loveshore.frcconsulting.co.in")
    frappe.connect()
    
    reservations = frappe.get_all("Hotel Reservation", fields=["name", "arrival_date", "departure_date"])
    for res in reservations:
        arr = str(res.arrival_date)
        dep = str(res.departure_date)
        
        # If it ends in 00:00:00, it means it just migrated from Date to Datetime
        if "00:00:00" in arr:
            arr = arr.replace("00:00:00", "14:00:00")
        if "00:00:00" in dep:
            dep = dep.replace("00:00:00", "12:00:00")
            
        frappe.db.set_value("Hotel Reservation", res.name, {
            "arrival_date": arr,
            "departure_date": dep
        }, update_modified=False)
        
    frappe.db.commit()
    print("Migration complete!")
    
if __name__ == "__main__":
    execute()
