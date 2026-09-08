"""Demo property data for development and walkthroughs.

This is NOT production inventory. Pinnacle's real room list (~15 rooms) is not confirmed
yet; this creates a small, believable property so the availability engine, the CRM
console and the POS can be exercised end to end.

Everything is namespaced under a single Hotel Reception so it is easy to identify and
remove later.

    bench --site <site> execute hospitality_core.demo_data.create_demo_property
    bench --site <site> execute hospitality_core.demo_data.remove_demo_property
"""

import frappe

RECEPTION = "Pinnacle Main"

ROOM_TYPES = [
    {"room_type_name": "Deluxe Room", "default_rate": 4500, "max_adults": 2, "max_children": 1,
     "description": "Garden-facing room with a queen bed."},
    {"room_type_name": "Premium Cottage", "default_rate": 7500, "max_adults": 3, "max_children": 2,
     "description": "Standalone cottage with a private sit-out."},
    {"room_type_name": "Pool Villa", "default_rate": 12000, "max_adults": 4, "max_children": 2,
     "description": "Two-bedroom villa with a plunge pool."},
]

# Five rooms is enough to exercise availability, multi-room bookings and overbooking
# guards without pretending we know the real inventory.
ROOMS = [
    {"room_number": "101", "room_type": "Deluxe Room", "floor": "Ground"},
    {"room_number": "102", "room_type": "Deluxe Room", "floor": "Ground"},
    {"room_number": "201", "room_type": "Premium Cottage", "floor": "Garden"},
    {"room_number": "202", "room_type": "Premium Cottage", "floor": "Garden"},
    {"room_number": "301", "room_type": "Pool Villa", "floor": "Lakeside"},
]


def create_demo_property():
    if not frappe.db.exists("Hotel Reception", RECEPTION):
        frappe.get_doc({"doctype": "Hotel Reception", "reception_name": RECEPTION}).insert(
            ignore_permissions=True
        )
        print(f"created Hotel Reception: {RECEPTION}")

    for rt in ROOM_TYPES:
        if not frappe.db.exists("Hotel Room Type", rt["room_type_name"]):
            frappe.get_doc(dict(doctype="Hotel Room Type", **rt)).insert(ignore_permissions=True)
            print(f"created Hotel Room Type: {rt['room_type_name']} @ {rt['default_rate']}")

    for room in ROOMS:
        if not frappe.db.exists("Hotel Room", room["room_number"]):
            frappe.get_doc({
                "doctype": "Hotel Room",
                "room_number": room["room_number"],
                "room_type": room["room_type"],
                "floor": room["floor"],
                "hotel_reception": RECEPTION,
                "status": "Available",
                "is_enabled": 1,
            }).insert(ignore_permissions=True)
            print(f"created Hotel Room: {room['room_number']} ({room['room_type']})")

    frappe.db.commit()

    print("\nDemo property ready:")
    for rt in frappe.get_all("Hotel Room Type", fields=["name", "default_rate"], order_by="name"):
        count = frappe.db.count("Hotel Room", {"room_type": rt.name})
        print(f"  {rt.name:20} {count} room(s)  @ {rt.default_rate}")


def remove_demo_property():
    """Remove the demo rooms. Refuses to touch anything that has been used."""
    for room in ROOMS:
        name = room["room_number"]
        if not frappe.db.exists("Hotel Room", name):
            continue
        if frappe.db.exists("Hotel Reservation", {"room": name}):
            print(f"skipping {name}: it has reservations")
            continue
        frappe.delete_doc("Hotel Room", name, ignore_permissions=True)
        print(f"deleted Hotel Room: {name}")

    for rt in ROOM_TYPES:
        name = rt["room_type_name"]
        if frappe.db.exists("Hotel Room Type", name) and not frappe.db.exists(
            "Hotel Room", {"room_type": name}
        ):
            frappe.delete_doc("Hotel Room Type", name, ignore_permissions=True)
            print(f"deleted Hotel Room Type: {name}")

    frappe.db.commit()


# --- demo enquiries ----------------------------------------------------------
# So the console has something to show. Numbers are in the reserved 999xxxxxxx range
# except the first, which reuses a number already present in CRM Call Log so the call
# history pane demonstrates real linkage.
DEMO_ENQUIRIES = [
    {
        "guest_name": "Ramesh Kumar", "mobile_no": "+91 90721 40018", "city": "Kochi",
        "status": "Quoted", "source": "Phone Call", "adults": 4, "children": 2,
        "check_in_offset": 12, "nights": 3, "budget": 40000,
        "follow_up_offset": -1,
        "rooms": [("Premium Cottage", 2, 7500)],
    },
    {
        "guest_name": "Anita Menon", "mobile_no": "9995500011", "city": "Bengaluru",
        "status": "New", "source": "WhatsApp", "adults": 2, "children": 0,
        "check_in_offset": 25, "nights": 2, "budget": 12000,
        "follow_up_offset": 0,
        "rooms": [("Deluxe Room", 1, 4500)],
    },
    {
        "guest_name": "Vikram Shetty", "mobile_no": "9995500022", "city": "Mumbai",
        "status": "Negotiation", "source": "Travel Agent", "adults": 8, "children": 3,
        "check_in_offset": 40, "nights": 4, "budget": 150000,
        "follow_up_offset": -2,
        "rooms": [("Pool Villa", 1, 12000), ("Premium Cottage", 2, 7000)],
    },
    {
        "guest_name": "Fatima Rahman", "mobile_no": "9995500033", "city": "Calicut",
        "status": "Tentative Hold", "source": "Repeat Guest", "adults": 2, "children": 1,
        "check_in_offset": 7, "nights": 2, "budget": 20000,
        "follow_up_offset": 1,
        "rooms": [("Deluxe Room", 2, 4200)],
    },
    {
        "guest_name": "Joseph Thomas", "mobile_no": "9995500044", "city": "Thrissur",
        "status": "Contacted", "source": "Website", "adults": 3, "children": 0,
        "check_in_offset": 18, "nights": 5, "budget": 60000,
        "follow_up_offset": 2,
        "rooms": [("Premium Cottage", 1, 7500)],
    },
]


def create_demo_enquiries():
    from frappe.utils import add_days, add_to_date, nowdate

    for spec in DEMO_ENQUIRIES:
        if frappe.db.exists("Hotel Enquiry", {"guest_name": spec["guest_name"]}):
            print(f"skipping {spec['guest_name']}: already exists")
            continue

        check_in = add_days(nowdate(), spec["check_in_offset"])
        doc = frappe.get_doc({
            "doctype": "Hotel Enquiry",
            "guest_name": spec["guest_name"],
            "mobile_no": spec["mobile_no"],
            "city": spec["city"],
            "status": spec["status"],
            "source": spec["source"],
            "hotel_reception": RECEPTION,
            "adults": spec["adults"],
            "children": spec["children"],
            "check_in_date": check_in,
            "check_out_date": add_days(check_in, spec["nights"]),
            "budget": spec["budget"],
            "next_follow_up": add_to_date(nowdate(), days=spec["follow_up_offset"], hours=10),
            "room_lines": [
                {"room_type": rt, "qty": qty, "adults": 2, "rate_quoted": rate}
                for rt, qty, rate in spec["rooms"]
            ],
        })
        doc.insert(ignore_permissions=True)
        print(f"created {doc.name}: {doc.guest_name} — {doc.status} — quoted {doc.quoted_total}")

    frappe.db.commit()


def create_all():
    create_demo_property()
    print()
    create_demo_enquiries()


def remove_demo_enquiries():
    for spec in DEMO_ENQUIRIES:
        name = frappe.db.get_value("Hotel Enquiry", {"guest_name": spec["guest_name"]})
        if name:
            frappe.delete_doc("Hotel Enquiry", name, ignore_permissions=True, force=True)
            print(f"deleted {name}")
    frappe.db.commit()
