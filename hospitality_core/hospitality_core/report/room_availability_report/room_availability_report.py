import frappe
from frappe import _
from frappe.utils import add_days, getdate, date_diff, flt

def execute(filters=None):
    if not filters:
        filters = {}

    columns = [
        {"label": _("Date"), "fieldname": "date", "fieldtype": "Date", "width": 110},
        {"label": _("Room Type"), "fieldname": "room_type", "fieldtype": "Link", "options": "Hotel Room Type", "width": 150},
        {"label": _("Total Rooms"), "fieldname": "total_rooms", "fieldtype": "Int", "width": 100},
        {"label": _("Out of Order"), "fieldname": "ooo", "fieldtype": "Int", "width": 100},
        {"label": _("Occupied/Sold"), "fieldname": "sold", "fieldtype": "Int", "width": 110, "description": "Confirmed + Checked In"},
        {"label": _("Available"), "fieldname": "available", "fieldtype": "Int", "width": 100},
        {"label": _("Occupancy %"), "fieldname": "occupancy_pct", "fieldtype": "Percent", "width": 100}
    ]

    data = []
    
    start_date = getdate(filters.get("from_date"))
    end_date = getdate(filters.get("to_date"))
    filter_type = filters.get("room_type")

    # 1. Get Inventory
    room_types_filters = {}
    if filter_type:
        room_types_filters["room_type_name"] = filter_type

    # Get counts of enabled rooms per type
    inventory = frappe.db.sql("""
        SELECT room_type, COUNT(name) as cnt 
        FROM `tabHotel Room` 
        WHERE is_enabled = 1 
        GROUP BY room_type
    """, as_dict=True)
    
    inventory_map = {i.room_type: i.cnt for i in inventory}
    
    all_types = list(inventory_map.keys())
    if filter_type and filter_type in all_types:
        all_types = [filter_type]

    # 2. Iterate Dates
    curr_date = start_date
    while curr_date <= end_date:
        str_date = curr_date.strftime("%Y-%m-%d")
        
        # Get OOO Rooms for this specific date (Assuming OOO status is live, not historical in this simplified model)
        # Note: A proper maintenance module would have OOO logs with dates. 
        # Here we check current OOO status for "Today", but for future dates this might be inaccurate unless we have OOO Schedule.
        # For simplicity, we assume current OOO status applies to the forecast range unless expanded.
        ooo_data = frappe.db.sql("""
            SELECT room_type, COUNT(name) as cnt 
            FROM `tabHotel Room` 
            WHERE status = 'Out of Order'
            GROUP BY room_type
        """, as_dict=True)
        ooo_map = {o.room_type: o.cnt for o in ooo_data}

        # Get Sold Rooms (Reservations covering this date, using datetime comparison)
        # We check for overlap with a datetime at 14:00 on the target date (standard check-in time)
        # A room checking out at 12:00 will NOT be counted as sold for the same date
        sold_conditions = ""
        sold_params = {"check_dt": f"{str_date} 14:00:00"}
        if filters.get("hotel_reception"):
            sold_conditions = "AND hotel_reception = %(hotel_reception)s"
            sold_params["hotel_reception"] = filters.get("hotel_reception")

        sold_sql = f"""
            SELECT room_type, COUNT(name) as cnt
            FROM `tabHotel Reservation`
            WHERE status IN ('Reserved', 'Checked In')
            AND CAST(CONCAT(arrival_date, ' ', IFNULL(NULLIF(arrival_time, ''), '14:00:00')) AS DATETIME) <= %(check_dt)s
            AND CAST(CONCAT(departure_date, ' ', IFNULL(NULLIF(departure_time, ''), '12:00:00')) AS DATETIME) > %(check_dt)s
            {sold_conditions}
            GROUP BY room_type
        """
        sold_data = frappe.db.sql(sold_sql, sold_params, as_dict=True)
        sold_map = {s.room_type: s.cnt for s in sold_data}

        for rt in all_types:
            total = inventory_map.get(rt, 0)
            ooo = ooo_map.get(rt, 0)
            sold = sold_map.get(rt, 0)
            
            # Net Availability
            avail = total - ooo - sold
            if avail < 0: avail = 0
            
            occ_pct = 0.0
            net_inventory = total - ooo
            if net_inventory > 0:
                occ_pct = (sold / net_inventory) * 100.0

            data.append({
                "date": str_date,
                "room_type": rt,
                "total_rooms": total,
                "ooo": ooo,
                "sold": sold,
                "available": avail,
                "occupancy_pct": flt(occ_pct, 1)
            })

        curr_date = add_days(curr_date, 1)

    return columns, data