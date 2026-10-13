import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import getdate, nowdate, add_days, flt, now_datetime
from hospitality_core.hospitality_core.api.reservation import check_availability, create_folio
# Imports for immediate billing logic
from hospitality_core.hospitality_core.api.night_audit import (
    post_room_charge, get_rate, get_extra_bed_charge, already_charged_today
)

class HotelReservation(Document):
    def validate(self):
        if not self.is_company_guest:
            self.company = None

        self.validate_dates()

        # Every stay runs from the property's standard check-in time to its standard
        # check-out time (Hospitality Accounting Settings); rooms are allocated by night.
        from hospitality_core.hospitality_core.api.stay_policy import apply_stay_times
        apply_stay_times(self)

        self.sync_room_type_with_room()

        # Only validate availability if status is Reserved or Checked In
        if self.status in ["Reserved", "Checked In"]:
            self.validate_room_availability()
        
        self.guard_direct_date_edit()

        # Requirement: "billing to Company should be set... Folio is opened to the Company"
        # New Requirement: If Is Company Guest is checked, Company is mandatory
        if self.is_company_guest and not self.company:
            frappe.throw(_("Company is mandatory when 'Is Company Guest' is checked."))

        if self.company:
            self.ensure_company_folio()

    def validate_dates(self):
        if getdate(self.arrival_date) >= getdate(self.departure_date):
            frappe.throw(_("Departure Date must be after Arrival Date."))

    def sync_room_type_with_room(self):
        if not self.room:
            return

        room_type = frappe.db.get_value("Hotel Room", self.room, "room_type")
        if room_type and self.room_type != room_type:
            self.room_type = room_type

    def validate_room_availability(self):
        check_availability(
            room=self.room, 
            arrival_date=self.arrival_date, 
            departure_date=self.departure_date, 
            ignore_reservation=self.name,
            arrival_time=self.arrival_time,
            departure_time=self.departure_time,
            ignore_booking=self.get("hotel_booking"),
        )

    def before_insert(self):
        self.reserved_by = frappe.session.user

    def after_insert(self):
        # Requirement: "And a Folio is also opened for the guest"
        create_folio(self)

    def ensure_company_folio(self):
        """
        Ensures an OPEN Master Folio exists for the Company.
        Company Folios are indefinite and manually closed.
        """
        if not self.company:
            return

        # Check for existing Open Master Folio for this Company
        exists = frappe.db.exists("Guest Folio", {
            "company": self.company,
            "status": "Open",
            "is_company_master": 1
        })

        if not exists:
            # Create Master Company Folio
            guest_name = self.get_corporate_guest_name()
            
            folio = frappe.new_doc("Guest Folio")
            folio.is_company_master = 1 # Flag as Company Folio
            folio.guest = guest_name
            folio.company = self.company
            folio.status = "Open"
            folio.open_date = nowdate()
            # No specific reservation/room link for Master Folio
            folio.insert(ignore_permissions=True)
            frappe.msgprint(_("Created new Master Folio for Company: {0}").format(self.company))

    def get_corporate_guest_name(self):
        """
        Gets or creates a Representative Guest record for the Company to attach the Master Folio to.
        """
        g_name = frappe.db.get_value("Guest", {"customer": self.company}, "name")
        if not g_name:
            # Create a placeholder guest for the company
            cust = frappe.get_doc("Customer", self.company)
            g = frappe.new_doc("Guest")
            g.full_name = cust.customer_name + " (Master Rep)"
            g.customer = self.company
            g.guest_type = "Corporate"
            g.insert(ignore_permissions=True)
            g_name = g.name
        return g_name

    def process_check_in(self):
        """
        Transition: Reserved -> Checked In
        Room: Available -> Occupied
        Folio: Provisional -> Open
        Action: CHARGE FIRST NIGHT IMMEDIATELY
        """
        if self.status != "Reserved":
            frappe.throw(_("Only Reserved bookings can be Checked In."))
        
        if getdate(self.arrival_date) > getdate(nowdate()):
            frappe.throw(_("Cannot Check-In before Arrival Date."))

        # 1. Update Reservation and Folio in a single process
        # We use db_set to avoid triggering the full 'save' cycle which might be overkill here
        # but since we have other fields to update (in check-in it's just status), it's fine.
        self.status = "Checked In"
        
        # 2. Update Room Status (another guest may still be marked Checked In here
        # after their stay ended; that does not stop this one moving in).
        frappe.db.set_value("Hotel Room", self.room, "status", "Occupied")
        
        # 3. Update Folio Status
        if self.folio:
            frappe.db.set_value("Guest Folio", self.folio, "status", "Open")

            # 4. IMMEDIATE CHARGE for the first night of the stay.
            # Hospitality Day Logic: Check-in before 8:00 AM counts as "Yesterday" —
            # but never a night before the booked arrival, and never one on or after
            # the departure date (those nights are not part of the stay).
            current_hour = now_datetime().hour
            charge_date = getdate(nowdate())
            if current_hour < 8:
                charge_date = getdate(add_days(nowdate(), -1))
            charge_date = max(charge_date, getdate(self.arrival_date))
            # Checked in on (or after) the departure date — usually the desk forgot to
            # press Check In until the guest was leaving. The guest still used the
            # room, so bill the stay's last booked night rather than nothing.
            last_night = getdate(add_days(self.departure_date, -1))
            if charge_date > last_night:
                charge_date = max(last_night, getdate(self.arrival_date))
            in_stay = True

            if in_stay and not already_charged_today(self.folio, charge_date, room=self.room):
                rate = get_rate(self.rate_plan, self.room_type, charge_date, reservation=self)
                rate += get_extra_bed_charge(self, charge_date)
                if rate > 0:
                    post_room_charge(self, rate, charge_date)
                    frappe.msgprint(_("Check-in successful. Room charged {0} for date {1}.").format(rate, charge_date))
        
        self.save()
        self.sync_parent_booking()
        return "Checked In"

    def process_check_out(self):
        """
        Transition: Checked In -> Checked Out
        Room: Occupied -> Available
        Folio: Validate Balance -> Closed -> SUBMITTED (Immutable)
        Reservation: SUBMITTED (Immutable)
        """
        if self.status != "Checked In":
            frappe.throw(_("Guest is not currently Checked In."))

        # Departing early is normal in a hotel; departing in the past is not.
        # Shorten the stay to today so the room goes back on sale for tonight and the
        # nights the guest did not use are not billed by the night audit.
        # A guest checked out after their departure date (staff forgot) leaves on the
        # booked date: nothing is added, the stay already ended and the room may
        # already be someone else's. Only an explicit Extend lengthens a stay.
        if getdate(self.departure_date) > getdate(nowdate()):
            from hospitality_core.hospitality_core.api.stay_policy import stay_time_values
            original = self.departure_date
            self.db_set({"departure_date": nowdate(), **stay_time_values()})
            self.reload()
            self.add_comment("Info", _(
                "Early departure: stay shortened from {0} to {1} at check-out."
            ).format(original, nowdate()))
            frappe.msgprint(_("Early departure — stay shortened from {0} to today.").format(original))

        # Requirement: "When a reservation is part of a group booking, that reservation cannot be checked out until the master folio is cleared."
        if self.is_group_guest and self.group_booking:
            master_folio = frappe.db.get_value("Hotel Group Booking", self.group_booking, "master_folio")
            if master_folio:
                # Sync balance to get latest totals
                master_folio_doc = frappe.get_doc("Guest Folio", master_folio)
                from hospitality_core.hospitality_core.api.folio import sync_folio_balance
                sync_folio_balance(master_folio_doc)
                
                # Re-fetch balance
                master_balance = frappe.db.get_value("Guest Folio", master_folio, "outstanding_balance")
                if master_balance > 0.01:
                    frappe.throw(_("Cannot Check Out. The Group Master Folio ({0}) has an outstanding balance of {1}. All group charges must be settled first.").format(master_folio, master_balance))

        # 1. Handle Folio
        if self.folio:
            # Check status first - if Closed, we skip all operations to avoid "Cannot add transactions" error
            folio_status = frappe.db.get_value("Guest Folio", self.folio, "status")
            
            if folio_status == "Closed":
                frappe.msgprint(_("Guest Folio {0} is already Closed. Skipping financial updates.").format(self.folio))
            else:
                folio_doc = frappe.get_doc("Guest Folio", self.folio)
                
                # --- START: AUTOMATIC TRANSFER TO CITY LEDGER ---
                if self.company:
                    # Calculate total amount tagged as 'Bill To Company' on this folio
                    company_liability = frappe.db.sql("""
                        SELECT SUM(amount) FROM `tabFolio Transaction`
                        WHERE parent = %s 
                        AND bill_to = 'Company' 
                        AND is_void = 0
                    """, (self.folio,), as_dict=False)[0][0] or 0.0

                    if company_liability > 0:
                        # Check if we already posted a transfer to avoid double credit if button clicked twice
                        transfer_item = "TRANSFER"
                        if not frappe.db.exists("Item", transfer_item):
                            item = frappe.new_doc("Item")
                            item.item_code = transfer_item
                            item.item_name = "Transfer to City Ledger"
                            item.item_group = "Services"
                            item.is_stock_item = 0
                            item.insert(ignore_permissions=True)
                        
                        transfer_exists = frappe.db.exists("Folio Transaction", {
                            "parent": self.folio,
                            "item": transfer_item,
                            "posting_date": nowdate(),
                            "amount": -1 * flt(company_liability)
                        })

                        if not transfer_exists:
                            # Create the Credit Transaction on Guest Folio
                            # This zeros out the Company portion on the Guest's view
                            frappe.get_doc({
                                "doctype": "Folio Transaction",
                                "parent": self.folio,
                                "parenttype": "Guest Folio",
                                "parentfield": "transactions",
                                "posting_date": nowdate(),
                                "item": transfer_item,
                                "description": f"Transfer to Master Folio (City Ledger) - {self.company}",
                                "qty": 1,
                                "amount": -1 * flt(company_liability), # Credit
                                "bill_to": "Company",
                                "is_void": 0
                            }).insert(ignore_permissions=True)
                            
                            frappe.msgprint(_("Transferred {0} to City Ledger.").format(company_liability))
                # --- END: AUTOMATIC TRANSFER ---

                # --- START: AUTOMATIC TRANSFER TO GROUP MASTER ---
                if self.is_group_guest and self.group_booking:
                    # 1. Get Group Master Folio ID
                    group_master_folio = frappe.db.get_value("Hotel Group Booking", self.group_booking, "master_folio")
                    
                    if group_master_folio and group_master_folio != self.folio:
                        # 2. Calculate total liability on Guest Folio (excluding existing transfers)
                        # Re-sync balance first
                        from hospitality_core.hospitality_core.api.folio import sync_folio_balance
                        sync_folio_balance(folio_doc)
                        current_balance = frappe.db.get_value("Guest Folio", self.folio, "outstanding_balance")
                        
                        if current_balance > 0.01:
                            transfer_item = "TRANSFER-GROUP"
                            if not frappe.db.exists("Item", transfer_item):
                                item = frappe.new_doc("Item")
                                item.item_code = transfer_item
                                item.item_name = "Transfer to Group Master"
                                item.item_group = "Services"
                                item.is_stock_item = 0
                                item.insert(ignore_permissions=True)
                                
                            # 3. Credit Guest Folio to zero it out for checkout
                            # This transaction will NOT be mirrored to the Master Folio 
                            # (handled by skip logic in folio.py)
                            frappe.get_doc({
                                "doctype": "Folio Transaction",
                                "parent": self.folio,
                                "parenttype": "Guest Folio",
                                "parentfield": "transactions",
                                "posting_date": nowdate(),
                                "item": transfer_item,
                                "description": f"Internal Balance Settlement (Group Bill) - {self.group_booking}",
                                "qty": 1,
                                "amount": -1 * flt(current_balance), # Credit
                                "bill_to": "Group",
                                "is_void": 0
                            }).insert(ignore_permissions=True)
                            
                            frappe.msgprint(_("Individual balance of {0} settled via Group Master.").format(current_balance))
                # --- END: AUTOMATIC TRANSFER TO GROUP MASTER ---
                
                # Recalculate balance - NOTE: transfer transaction inserts above already triggered sync via hooks!
                from hospitality_core.hospitality_core.api.folio import sync_folio_balance
                sync_folio_balance(folio_doc)
                
                # Get latest balance from DB (sync_folio_balance updates DB directly)
                balance = frappe.db.get_value("Guest Folio", self.folio, "outstanding_balance")
                
                # Requirement: "folio once opened cannot be closed until all payments are made... enforced... for private guests"
                # Updated Requirement: Company Guests can check out with balance.
                
                if not self.is_company_guest:
                    if balance > 0.01:
                        frappe.throw(_("Cannot Check Out. Outstanding balance of {0} remains on Folio {1}. Please settle payment.").format(balance, self.folio))
                else:
                    if balance > 0.01:
                        frappe.msgprint(_("Company Guest Checkout: Outstanding balance of {0}. Liability remains on Company Master Folio.").format(balance))
                
                # Close Folio using db_set to avoid timestamp conflicts
                # (Transaction inserts trigger sync_folio_balance hooks which update DB timestamps)
                frappe.db.set_value("Guest Folio", self.folio, {
                    "status": "Closed",
                    "close_date": nowdate()
                })
                
                # Record guest balance if there's a credit balance
                # (after_save hook handles this, but we call it explicitly to ensure it runs)
                from hospitality_core.hospitality_core.api.folio import record_guest_balance
                record_guest_balance(folio_doc)

        # 2. Update Reservation Status
        # Use db_set to avoid "Document has been modified" errors caused by background updates 
        # (e.g. from Folio/Room logic) triggering optimistic locking failures during full save.
        self.db_set("status", "Checked Out")
        
        # 3. Update Room Status to Available
        # Available only if nobody else is now in it — the next guest may already have
        # checked in while this one was waiting to be checked out.
        from hospitality_core.hospitality_core.doctype.hotel_room.hotel_room import refresh_room_status
        refresh_room_status(self.room, exclude=self.name)

        # 4. Move the parent booking on if this was its last live room.
        self.sync_parent_booking()

        # 5. No self.save() needed - db_set handles the status update safely.

        return "Checked Out"
    
    def sync_parent_booking(self):
        """Keep the owning Hotel Booking's status in step with its rooms."""
        if not self.get("hotel_booking"):
            return
        from hospitality_core.hospitality_core.doctype.hotel_booking.hotel_booking import (
            sync_booking_for_reservation,
        )
        sync_booking_for_reservation(self.name)

    def process_cancel(self):
        """
        Transition: Reserved -> Cancelled
        """
        if self.status not in ["Reserved", "Checked In"]:
            frappe.throw(_("Only Reserved or Checked In bookings can be Cancelled."))
        
        self.db_set("status", "Cancelled")
        
        # If there's a folio, cancel it as well if it's not already closed
        if self.folio:
            folio_status = frappe.db.get_value("Guest Folio", self.folio, "status")
            if folio_status not in ["Closed", "Cancelled"]:
                folio_doc = frappe.get_doc("Guest Folio", self.folio)
                from hospitality_core.hospitality_core.api.folio import sync_folio_balance
                sync_folio_balance(folio_doc)
                
                if folio_doc.outstanding_balance < -0.01: # Guest has excess payment (credit)
                    # Transfer to guest balance ledger
                    amount_to_transfer = abs(folio_doc.outstanding_balance)
                    frappe.get_doc({
                        "doctype": "Guest Balance Ledger",
                        "guest": folio_doc.guest,
                        "amount": amount_to_transfer,
                        "status": "Available",
                        "date": frappe.utils.nowdate(),
                        "folio": self.folio
                    }).insert(ignore_permissions=True)
                    frappe.msgprint(_("Transferred {0} to Guest Balance Ledger.").format(amount_to_transfer))
                    
                    # Create a debit transaction to zero out the folio
                    transfer_item = "REFUND-TRANSFER"
                    if not frappe.db.exists("Item", transfer_item):
                        item = frappe.new_doc("Item")
                        item.item_code = transfer_item
                        item.item_name = "Transfer to Balance Ledger"
                        item.item_group = "Services"
                        item.is_stock_item = 0
                        item.insert(ignore_permissions=True)
                        
                    frappe.get_doc({
                        "doctype": "Folio Transaction",
                        "parent": self.folio,
                        "parenttype": "Guest Folio",
                        "parentfield": "transactions",
                        "posting_date": frappe.utils.nowdate(),
                        "item": transfer_item,
                        "description": "Transfer to Guest Balance Ledger on Cancellation",
                        "qty": 1,
                        "amount": amount_to_transfer, # Debit
                        "bill_to": "Guest",
                        "is_void": 0
                    }).insert(ignore_permissions=True)
                    
                    sync_folio_balance(folio_doc)
                    
                frappe.db.set_value("Guest Folio", self.folio, "status", "Cancelled")
                frappe.msgprint(_("Linked Guest Folio {0} has been cancelled.").format(self.folio))

        # A checked-in stay cancelled by a supervisor leaves the room empty.
        from hospitality_core.hospitality_core.doctype.hotel_room.hotel_room import refresh_room_status
        refresh_room_status(self.room, exclude=self.name)

        self.sync_parent_booking()

        return "Cancelled"

    def on_trash(self):
        """A reservation belonging to a live booking is cancelled, not deleted.

        Deleting it left the booking pointing at nothing: the booking still said
        Confirmed while no screen showed the stay and no room was held.
        """
        if self.hotel_booking and frappe.db.get_value("Hotel Booking", self.hotel_booking, "status") not in (
            "Cancelled", "Draft", None
        ):
            frappe.throw(_("{0} belongs to booking {1}. Cancel the stay (or the booking) instead of deleting it.").format(
                self.name, self.hotel_booking))

    def guard_direct_date_edit(self):
        """Refuse a form edit that would leave the bill and the stay disagreeing."""
        before = self.get_doc_before_save()
        if not before or self.status != "Checked In":
            return
        if getdate(before.arrival_date) != getdate(self.arrival_date):
            frappe.throw(_("The guest is already in house; only the departure can change."))
        if self.folio and getdate(self.departure_date) < getdate(before.departure_date):
            posted = frappe.db.get_value(
                "Folio Transaction",
                {"parent": self.folio, "item": "ROOM-RENT", "is_void": 0,
                 "posting_date": [">=", getdate(self.departure_date)]},
                "posting_date",
            )
            if posted:
                frappe.throw(_("The night of {0} is already on the bill. Check the guest out instead, "
                               "or void that night on the folio first.").format(frappe.format(posted, "Date")))

    def sync_after_direct_edit(self):
        """A reservation edited on its form keeps its booking, rooms and bill in step.

        The booking line follows the room, the booking is re-dated and repriced over
        its rooms, room statuses follow a checked-in guest who moved, and nights an
        extension makes due are billed straight away.
        """
        before = self.get_doc_before_save()
        if not before:
            return
        dates_changed = (
            getdate(before.arrival_date) != getdate(self.arrival_date)
            or getdate(before.departure_date) != getdate(self.departure_date)
        )
        room_changed = before.room != self.room
        if not (dates_changed or room_changed):
            return

        if self.hotel_booking and room_changed:
            frappe.db.set_value(
                "Hotel Booking Room", {"parent": self.hotel_booking, "reservation": self.name},
                {"room": self.room, "room_type": self.room_type},
            )
        if self.status == "Checked In":
            from hospitality_core.hospitality_core.doctype.hotel_room.hotel_room import refresh_room_status
            if room_changed:
                refresh_room_status(before.room)
                refresh_room_status(self.room)
            if getdate(self.departure_date) > getdate(before.departure_date):
                from hospitality_core.hospitality_core.api.night_audit import post_due_nights
                post_due_nights(self)
        self.add_comment("Info", _("Changed on the form: {0} – {1}, room {2}.").format(
            frappe.format(self.arrival_date, "Date"), frappe.format(self.departure_date, "Date"), self.room
        ))
        self.sync_parent_booking()

    def on_update(self):
        self.sync_after_direct_edit()

        # Requirement: "make it possible for everybody to edit the is company and company field"
        # We handle the impact on billing and folio management here.
        if self.folio:
            folio_doc = frappe.get_doc("Guest Folio", self.folio)
            
            if folio_doc.company != self.company:
                folio_doc.db_set("company", self.company)
                
                if self.is_company_guest and self.company:
                    self.ensure_company_folio()
                    # Transition existing 'Guest' transactions to 'Company'
                    self.sync_transactions_to_company(folio_doc)
                elif not self.is_company_guest:
                    # Transition existing 'Company' transactions back to 'Guest'
                    self.sync_transactions_from_company(folio_doc)
            
            if folio_doc.room != self.room:
                folio_doc.db_set("room", self.room)

    def sync_transactions_to_company(self, folio_doc):
        from hospitality_core.hospitality_core.api.folio import mirror_to_company_folio, sync_folio_balance
        
        updated = False
        for txn in folio_doc.transactions:
            if txn.bill_to == "Guest" and not txn.is_void:
                txn.db_set("bill_to", "Company")
                mirror_to_company_folio(txn)
                updated = True
        
        if updated:
            sync_folio_balance(folio_doc)

    def sync_transactions_from_company(self, folio_doc):
        from hospitality_core.hospitality_core.api.folio import sync_folio_balance
        
        updated = False
        for txn in folio_doc.transactions:
            if txn.bill_to == "Company" and not txn.is_void:
                txn.db_set("bill_to", "Guest")
                # Remove mirrored transaction from Company Folio
                self.remove_mirrored_transaction(txn)
                updated = True
        
        if updated:
            sync_folio_balance(folio_doc)

    def remove_mirrored_transaction(self, original_txn):
        # Mirrored transactions have reference_name = original_txn.name
        mirrored_txns = frappe.get_all("Folio Transaction", filters={
            "reference_doctype": "Folio Transaction",
            "reference_name": original_txn.name
        })
        
        for m_txn in mirrored_txns:
            m_doc = frappe.get_doc("Folio Transaction", m_txn.name)
            parent_folio = m_doc.parent
            frappe.delete_doc("Folio Transaction", m_txn.name, ignore_permissions=True)
            
            from hospitality_core.hospitality_core.api.folio import sync_folio_balance
            sync_folio_balance(frappe.get_doc("Guest Folio", parent_folio))

# Whitelisted methods for client-side buttons
@frappe.whitelist()
def extend_stay(reservation, new_departure_date, new_departure_time=None):
    """Push a guest's departure out, if the room is still free for the extra nights.

    The counterpart to early departure at check-out. Without this the only way a stay got
    longer was the night audit's overstay handler, which fires at 2 PM and cannot be used
    to plan ahead — so a guest asking at the desk to stay another night could not be
    accommodated without editing the record and bypassing the availability check.
    """
    from hospitality_core.hospitality_core.api.availability import is_room_free

    doc = frappe.get_doc("Hotel Reservation", reservation)
    doc.check_permission("write")

    if doc.status not in ("Reserved", "Checked In"):
        frappe.throw(_("Only a Reserved or Checked In stay can be extended."))

    if getdate(new_departure_date) <= getdate(doc.departure_date):
        frappe.throw(_("New departure must be after the current departure ({0}).").format(
            doc.departure_date
        ))

    # Only the added nights need checking; the guest already holds the room until now.
    result = is_room_free(
        doc.room, doc.departure_date, new_departure_date,
        arrival_time=doc.departure_time, departure_time=new_departure_time,
        ignore_reservation=doc.name, ignore_booking=doc.get("hotel_booking"),
    )
    if not result["free"]:
        frappe.throw(_("Cannot extend: {0}").format(result["reason"]))

    from hospitality_core.hospitality_core.api.stay_policy import stay_time_values

    previous = doc.departure_date
    doc.db_set({"departure_date": getdate(new_departure_date), **stay_time_values()})
    doc.add_comment("Info", _("Stay extended from {0} to {1}.").format(previous, new_departure_date))

    # Bill the added nights that are already due (tonight, if the 2 PM audit has run,
    # or past nights when an overdue guest is extended because they really stayed).
    # Later nights are posted by the audit as usual.
    if doc.status == "Checked In":
        from hospitality_core.hospitality_core.api.night_audit import post_due_nights
        doc.reload()
        post_due_nights(doc)

    # Stretch the parent booking over the new dates and reprice it, so its total and
    # balance due include the extra nights rather than staying at the original quote.
    doc.sync_parent_booking()

    return {
        "reservation": doc.name,
        "previous_departure": str(previous),
        "departure_date": str(getdate(new_departure_date)),
    }


@frappe.whitelist()
def check_in_guest(name):
    doc = frappe.get_doc("Hotel Reservation", name)
    return doc.process_check_in()

@frappe.whitelist()
def check_out_guest(name):
    doc = frappe.get_doc("Hotel Reservation", name)
    return doc.process_check_out()

@frappe.whitelist()
def cancel_reservation(name):
    doc = frappe.get_doc("Hotel Reservation", name)
    return doc.process_cancel()