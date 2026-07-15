# Copyright (c) 2025, osama.ahmed@deliverydevs.com
# For license information, please see license.txt

import frappe
from frappe.model.document import Document
from frappe import _
import requests
from frappe.utils import today, now_datetime, get_datetime, flt
from datetime import datetime, timedelta
import json
import time


class ZKTecoConfig(Document):
    pass


@frappe.whitelist()
def register_api_token():
    """
    Register DRF API token from ZKTeco server
    """
    cfg = frappe.get_single("ZKTeco Config")

    server_ip = cfg.server_ip
    server_port = cfg.server_port
    username = (cfg.username or "").strip()
    password = cfg.get_password("password")

    if not all([server_ip, server_port, username, password]):
        frappe.throw(_("Please configure server IP, port, username, and password."))

    login_url = f"http://{server_ip}:{server_port}/api-token-auth/"

    try:
        response = requests.post(
            login_url,
            json={
                "username": username,
                "password": password
            },
            timeout=15
        )

        frappe.logger().info(
            f"ZKTeco Login URL: {login_url}\n"
            f"Response: {response.status_code} - {response.text}"
        )

        if response.status_code != 200:
            frappe.throw(_("Login Failed: {0}").format(response.text))

        data = response.json()
        token = data.get("token")

        if not token:
            frappe.throw(_("Token not found: {0}").format(response.text))

        # Save DRF token directly
        frappe.db.set_single_value("ZKTeco Config", "token", token)
        frappe.db.commit()

        return {
            "success": True,
            "message": "Token registered successfully",
            "token": token
        }

    except requests.exceptions.RequestException as e:
        frappe.throw(_("Connection error: {0}").format(str(e)))


@frappe.whitelist()
def test_connection():
    """
    Enhanced test connection that shows latest transactions with detailed info
    """
    # Get token from the singleton config
    cfg = frappe.get_single("ZKTeco Config")
    token = (cfg.token or "").strip()
    server_ip = frappe.db.get_single_value("ZKTeco Config", "server_ip")
    server_port = frappe.db.get_single_value("ZKTeco Config", "server_port")
    
    if not token:
        return {"ok": False, "error": _("Token not set in ZKTeco Config. Please register/save a token first.")}

    base_url = f"http://{server_ip}:{server_port}/iclock/api/transactions/"
    day = today()
    start_time = f"{day} 00:00:00"
    end_time = f"{day} 23:59:59"

    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Token {token}",
    }
    params = {
        "start_time": start_time,
        "end_time": end_time,
    }

    try:
        resp = requests.get(base_url, headers=headers, params=params, timeout=15)
        
        if resp.ok:
            try:
                data = resp.json()
                
                # Process and format transaction data for display
                formatted_transactions = []
                transaction_count = 0
                
                # Handle ZKTeco API response structure
                if isinstance(data, dict) and 'data' in data:
                    transactions = data['data']
                    transaction_count = data.get('count', len(transactions))
                elif isinstance(data, dict) and 'results' in data:
                    transactions = data['results']
                    transaction_count = len(transactions)
                elif isinstance(data, list):
                    transactions = data
                    transaction_count = len(transactions)
                else:
                    transactions = []
                
                # Format latest 5 transactions for preview
                for transaction in transactions[:5]:
                    try:
                        # Map ZKTeco transaction fields based on actual API response
                        emp_code = transaction.get('emp_code')
                        punch_time = transaction.get('punch_time')
                        punch_state = transaction.get('punch_state')
                        punch_state_display = transaction.get('punch_state_display')
                        device_id = transaction.get('terminal_alias') or transaction.get('terminal_sn')
                        first_name = transaction.get('first_name', '')
                        last_name = transaction.get('last_name', '') or ''
                        verify_type_display = transaction.get('verify_type_display')
                        
                        # Combine first and last name
                        zkteco_name = f"{first_name} {last_name}".strip()
                        
                        # Try to find employee name from ERPNext
                        employee_name = zkteco_name
                        erpnext_employee = None
                        if emp_code:
                            # Try to find employee by employee_id or user_id
                            employee = frappe.db.get_value("Employee", 
                                                         {"employee": emp_code}, 
                                                         ["name", "employee_name"])
                            if not employee:
                                employee = frappe.db.get_value("Employee", 
                                                             {"user_id": emp_code}, 
                                                             ["name", "employee_name"])
                            if employee:
                                erpnext_employee = employee[0] if isinstance(employee, tuple) else employee
                                employee_name = f"{employee[1]} (ERPNext)" if isinstance(employee, tuple) else f"{employee} (ERPNext)"
                        
                        # Determine log type based on punch_state
                        log_type = "IN"
                        if punch_state == "1" or punch_state_display == "Check Out":
                            log_type = "OUT"
                        
                        formatted_transactions.append({
                            "id": transaction.get('id'),
                            "employee_code": emp_code,
                            "employee_name": employee_name,
                            "erpnext_employee": erpnext_employee,
                            "punch_time": punch_time,
                            "log_type": log_type,
                            "punch_state_display": punch_state_display,
                            "device_id": device_id,
                            "verify_method": verify_type_display,
                            "zkteco_name": zkteco_name,
                            "department": transaction.get('department'),
                            "raw_data": transaction
                        })
                    except Exception as e:
                        frappe.log_error(f"Error processing transaction: {e}", "ZKTeco Transaction Processing")
                        continue
                
                return {
                    "ok": True,
                    "status_code": resp.status_code,
                    "url": resp.url,
                    "total_transactions": transaction_count,
                    "transactions_preview": formatted_transactions,
                    "raw_sample": transactions[:2] if transactions else [],
                    "message": f"Found {transaction_count} transactions for {day}"
                }
                
            except json.JSONDecodeError as e:
                return {
                    "ok": False,
                    "status_code": resp.status_code,
                    "error": f"Invalid JSON response: {str(e)}",
                    "raw_response": resp.text[:500]
                }
        else:
            return {
                "ok": False,
                "status_code": resp.status_code,
                "url": resp.url,
                "error": f"HTTP {resp.status_code}: {resp.text[:200]}"
            }
            
    except requests.RequestException as e:
        return {
            "ok": False,
            "error": f"Connection error: {str(e)}"
        }


def sync_zkteco_transactions():
    """
    Main function to sync ZKTeco transactions with ERPNext Employee Checkin records
    """
    # Check if sync is enabled
    cfg = frappe.get_single("ZKTeco Config")
    if not cfg.enable_sync:
        frappe.log_error("ZKTeco sync is disabled", "ZKTeco Sync")
        return
    
    if not cfg.token:
        frappe.log_error("ZKTeco token not configured", "ZKTeco Sync")
        return
    
    try:
        # Get transactions from last sync or last hour
        last_sync = frappe.db.get_single_value("ZKTeco Config", "last_sync")
        current_time = now_datetime()

        if not last_sync:
            last_sync = current_time - timedelta(days=1)
        else:
            last_sync = get_datetime(last_sync)

            if last_sync.year < 2000:
                last_sync = current_time - timedelta(days=1)

        transactions = fetch_zkteco_transactions_with_retry(cfg, last_sync, current_time)
        
        if transactions:
            processed_count = 0
            error_count = 0
            
            for transaction in transactions:
                try:
                    if create_employee_checkin(transaction):
                        processed_count += 1
                    else:
                        error_count += 1
                except Exception as e:
                    error_count += 1
                    frappe.log_error(f"Error creating checkin for transaction {transaction}: {str(e)}", "ZKTeco Sync Error")
            
            # Update last sync time and record count
            total_synced = frappe.db.get_single_value("ZKTeco Config", "total_synced_records") or 0
            frappe.db.set_single_value("ZKTeco Config", "last_sync", current_time)
            frappe.db.set_single_value("ZKTeco Config", "total_synced_records", total_synced + processed_count)
            
            # Update sync status
            sync_status = "Success" if error_count == 0 else "Partial" if processed_count > 0 else "Failed"
            frappe.db.set_single_value("ZKTeco Config", "last_sync_status", sync_status)
            frappe.db.set_single_value("ZKTeco Config", "failed_sync_attempts", 0)
            
            frappe.db.commit()
            
            frappe.logger().info(f"ZKTeco Sync completed: {processed_count} processed, {error_count} errors")
        
    except Exception as e:
        frappe.log_error(f"ZKTeco sync failed: {str(e)}", "ZKTeco Sync Fatal Error")
        # Update failed attempts counter
        failed_attempts = frappe.db.get_single_value("ZKTeco Config", "failed_sync_attempts") or 0
        frappe.db.set_single_value("ZKTeco Config", "failed_sync_attempts", failed_attempts + 1)
        frappe.db.set_single_value("ZKTeco Config", "last_sync_status", "Failed")
        frappe.db.commit()


def fetch_zkteco_transactions(cfg, start_time, end_time):
    """
    Fetch transactions from ZKTeco device
    """
    server_ip = cfg.server_ip
    server_port = cfg.server_port
    token = cfg.token
    
    base_url = f"http://{server_ip}:{server_port}/iclock/api/transactions/"
    
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Token {token}",
    }
    
    params = {
        "start_time": start_time.strftime("%Y-%m-%d %H:%M:%S"),
        "end_time": end_time.strftime("%Y-%m-%d %H:%M:%S"),
    }
    
    try:
        resp = requests.get(base_url, headers=headers, params=params, timeout=30)
        resp.raise_for_status()
        
        data = resp.json()
        
        # Handle ZKTeco API response format
        if isinstance(data, dict) and 'data' in data:
            return data['data']
        elif isinstance(data, dict) and 'results' in data:
            return data['results']
        elif isinstance(data, list):
            return data
        else:
            return []
            
    except Exception as e:
        frappe.log_error(f"Failed to fetch ZKTeco transactions: {str(e)}", "ZKTeco API Error")
        return []


def fetch_zkteco_transactions_with_retry(cfg, start_time, end_time):
    """
    Fetch transactions from ZKTeco device with retry mechanism
    Handles device unavailability gracefully
    """
    max_retries = int(cfg.max_retry_attempts or 3) if cfg.enable_retry_on_failure else 1
    retry_interval = int(cfg.retry_interval_seconds or 60) if cfg.enable_retry_on_failure else 0
    attempt = 0
    
    while attempt < max_retries:
        try:
            transactions = fetch_zkteco_transactions(cfg, start_time, end_time)
            if transactions:
                # Reset failed attempts on successful fetch
                frappe.db.set_single_value("ZKTeco Config", "failed_sync_attempts", 0)
                frappe.db.set_single_value("ZKTeco Config", "last_sync_status", "Success")
                frappe.db.commit()
                return transactions
            else:
                # Empty result but no error - might be no transactions
                return []
                
        except requests.exceptions.ConnectionError as e:
            attempt += 1
            frappe.log_error(
                f"ZKTeco device connection failed (Attempt {attempt}/{max_retries}): {str(e)}", 
                "ZKTeco Connection Error"
            )
            
            if attempt < max_retries and cfg.enable_retry_on_failure:
                frappe.logger().info(f"Retrying in {retry_interval} seconds...")
                time.sleep(retry_interval)
                # Update status to indicate we're retrying
                frappe.db.set_single_value("ZKTeco Config", "last_sync_status", "Retrying")
                frappe.db.set_single_value("ZKTeco Config", "failed_sync_attempts", attempt)
                frappe.db.commit()
            else:
                frappe.db.set_single_value("ZKTeco Config", "last_sync_status", "Failed")
                frappe.db.set_single_value("ZKTeco Config", "failed_sync_attempts", attempt)
                frappe.db.commit()
                frappe.log_error(
                    f"ZKTeco device unavailable after {max_retries} attempts. Will retry on next scheduled sync.", 
                    "ZKTeco Device Unavailable"
                )
                return []
                
        except Exception as e:
            attempt += 1
            frappe.log_error(f"Unexpected error fetching transactions (Attempt {attempt}/{max_retries}): {str(e)}", "ZKTeco Fetch Error")
            if attempt < max_retries and cfg.enable_retry_on_failure:
                time.sleep(retry_interval)
            else:
                return []
    
    return []


# def create_debug_log(message):
#     """Create Integration Log entry for debugging"""
#     try:
#         doc = frappe.get_doc({
#             "doctype": "Integration Log",
#             "response": message
#         })
#         doc.insert(ignore_permissions=True)
#         frappe.db.commit()

#     except Exception as e:
#         frappe.log_error(frappe.get_traceback(), "Integration Log Debug Error")
#         raise


def create_employee_checkin(transaction):
    """
    Create Employee Checkin record from ZKTeco transaction
    """
    try:
        # Extract transaction data based on ZKTeco API response structure
        emp_code = transaction.get('emp_code')
        punch_time = transaction.get('punch_time')
        punch_state = transaction.get('punch_state')
        punch_state_display = transaction.get('punch_state_display')
        device_id = transaction.get('terminal_alias') or transaction.get('terminal_sn')
        transaction_id = transaction.get('id')

        
        
        if not emp_code or not punch_time:
            frappe.log_error(f"Missing required fields in transaction: {transaction}", "ZKTeco Transaction Error")
            return False
        
        # Find employee
        employee = find_employee_by_code(emp_code)
        if not employee:
            frappe.log_error(f"Employee not found for code: {emp_code}", "ZKTeco Employee Mapping")
            return False
        
        # Convert punch_time to datetime
        if isinstance(punch_time, str):
            punch_datetime = get_datetime(punch_time)
        else:
            punch_datetime = punch_time
        
        # Determine log type based on punch_state
        # 1. Start by assuming IN by default
        log_type = "IN"
        punch_display_lower = str(punch_state_display).strip().lower() if punch_state_display else ""
        
        # If punch_state is 255, we should ignore display and use fallback alternating logic
        if str(punch_state) != "255" and (str(punch_state) == "1" or punch_display_lower in ["check out", "out", "checkout"]):
            log_type = "OUT"
        elif str(punch_state) != "255" and (str(punch_state) == "0" or punch_display_lower in ["check in", "in", "checkin"]):
            log_type = "IN"
        else:
            # Fallback for state 255 or unknown: alternate based on previous checkin today
            last_log = frappe.db.get_all(
                "Employee Checkin", 
                filters={"employee": employee, "time": ["<", punch_datetime]}, 
                fields=["log_type", "time"], 
                order_by="time desc", 
                limit=1
            )
            
            if last_log:
                last_log_type = last_log[0].get("log_type")
                # Safely convert to datetime to avoid string attribute errors
                last_log_time = get_datetime(last_log[0].get("time"))
                
                # If last log was on the same day, alternate the state
                if last_log_time.date() == punch_datetime.date():
                    if last_log_type == "IN":
                        log_type = "OUT"
                    else:
                        log_type = "IN"

        
        # Check if checkin already exists (use transaction ID for uniqueness)
        existing_checkin = frappe.db.exists("Employee Checkin", {
            "employee": employee,
            "time": punch_datetime,
            "device_id": device_id
        })
        
        if existing_checkin:
            return True  # Already processed
        
        # Also check by transaction ID if we store it
        if transaction_id:
            existing_by_id = frappe.db.get_value("Employee Checkin", 
                                               {"device_id": device_id, "employee": employee}, 
                                               "name", 
                                               {"time": ["between", [punch_datetime - timedelta(seconds=5), punch_datetime + timedelta(seconds=5)]]})
            if existing_by_id:
                return True

        # Fetch Shift from latest Shift Assignment
        shift = frappe.db.sql("""
            SELECT shift_type
            FROM `tabShift Assignment`
            WHERE employee = %s
              AND docstatus = 1
            ORDER BY creation DESC
            LIMIT 1
        """, (employee,), as_dict=True)

        shift_type = shift[0].shift_type if shift else None

        # Create Employee Checkin
        checkin = frappe.get_doc({
            "doctype": "Employee Checkin",
            "employee": employee,
            "time": punch_datetime,
            "log_type": log_type,
            "shift": shift_type,
            "device_id": f"{device_id} (ZKTeco-{transaction_id})" if transaction_id else device_id or "ZKTeco Device",
            "skip_auto_attendance": 0
        })

        
        checkin.insert(ignore_permissions=True)
        frappe.db.commit()
        
        return True
        
    except Exception as e:
        frappe.log_error(f"Error creating Employee Checkin: {str(e)}", "ZKTeco Checkin Creation")
        return False


def find_employee_by_code(emp_code):
    """
    Find Employee using ZKTeco/EasyTime employee code.
    Priority:
    1. attendance_device_id
    2. employee
    3. user_id
    """

    emp_code = str(emp_code).strip()

    # Attendance Device ID (Biometric/RF tag ID)
    if frappe.db.has_column("Employee", "attendance_device_id"):
        employee = frappe.db.get_value(
            "Employee",
            {"attendance_device_id": emp_code},
            "name"
        )
        if employee:
            return employee

    # Employee ID
    employee = frappe.db.get_value(
        "Employee",
        {"employee": emp_code},
        "name"
    )
    if employee:
        return employee

    # User ID
    employee = frappe.db.get_value(
        "Employee",
        {"user_id": emp_code},
        "name"
    )
    if employee:
        return employee

    frappe.logger().info(
        f"Employee mapping not found for emp_code: {emp_code}"
    )

    return None


@frappe.whitelist()
def manual_sync():
    """
    Manual sync trigger for testing
    """
    try:
        sync_zkteco_transactions()
        return {"success": True, "message": "Sync completed successfully"}
    except Exception as e:
        frappe.log_error(f"Manual sync failed: {str(e)}", "ZKTeco Manual Sync")
        return {"success": False, "message": f"Sync failed: {str(e)}"}


@frappe.whitelist()
def manual_pull_by_date_range():
    """
    Manual pull transactions for a specific date range
    Useful for backfilling missed transactions when device was unavailable
    """
    try:
        cfg = frappe.get_single("ZKTeco Config")
        
        if not cfg.start_date or not cfg.end_date:
            frappe.throw(_("Please specify both Start Date and End Date"))
        
        if not cfg.token:
            frappe.throw(_("ZKTeco token not configured"))
        
        start_date = get_datetime(cfg.start_date)
        end_date = get_datetime(cfg.end_date)
        
        # Add end of day to end_date
        end_date = end_date.replace(hour=23, minute=59, second=59)
        
        if start_date > end_date:
            frappe.throw(_("Start Date cannot be after End Date"))
        
        frappe.logger().info(f"Manual pull started for range: {start_date} to {end_date}")
        
        transactions = fetch_zkteco_transactions_with_retry(cfg, start_date, end_date)
        
        if transactions:
            processed_count = 0
            error_count = 0
            skipped_count = 0
            
            for transaction in transactions:
                try:
                    # Check if already exists to skip duplicates
                    emp_code = transaction.get('emp_code')
                    punch_time = transaction.get('punch_time')
                    
                    if isinstance(punch_time, str):
                        punch_datetime = get_datetime(punch_time)
                    else:
                        punch_datetime = punch_time
                    
                    device_id = transaction.get('terminal_alias') or transaction.get('terminal_sn')
                    
                    existing = frappe.db.exists("Employee Checkin", {
                        "employee": find_employee_by_code(emp_code),
                        "time": punch_datetime,
                        "device_id": device_id
                    })
                    
                    if existing:
                        skipped_count += 1
                        continue
                    
                    if create_employee_checkin(transaction):
                        processed_count += 1
                    else:
                        error_count += 1
                except Exception as e:
                    error_count += 1
                    frappe.log_error(f"Error in manual pull for transaction {transaction}: {str(e)}", "ZKTeco Manual Pull Error")
            
            return {
                "success": True,
                "message": f"Manual pull completed",
                "processed": processed_count,
                "errors": error_count,
                "skipped": skipped_count,
                "total": len(transactions)
            }
        else:
            return {
                "success": False,
                "message": "No transactions found for the specified date range"
            }
        
    except Exception as e:
        frappe.log_error(f"Manual pull failed: {str(e)}", "ZKTeco Manual Pull Fatal Error")
        return {"success": False, "message": f"Manual pull failed: {str(e)}"}


def scheduled_sync():
    """
    Scheduled sync function that respects the frequency setting
    """
    try:
        cfg = frappe.get_single("ZKTeco Config")
        if not cfg.enable_sync:
            return
            
        # For frequent syncs (less than 60 seconds), check if we should actually run
        sync_seconds = int(cfg.seconds or 300)
        if sync_seconds < 60:
            last_run = frappe.cache().get_value("zkteco_last_sync_run")
            current_time = now_datetime()
            
            if last_run:
                time_diff = (current_time - get_datetime(last_run)).total_seconds()
                if time_diff < sync_seconds:
                    return  # Not yet time for next sync
            
            # Update last run time
            frappe.cache().set_value("zkteco_last_sync_run", current_time)
        
        sync_zkteco_transactions()
        
    except Exception as e:
        frappe.log_error(f"Scheduled ZKTeco sync failed: {str(e)}", "ZKTeco Scheduled Sync Error")


def cleanup_scheduler_check():
    """
    Cleanup function to ensure scheduler is working properly
    """
    try:
        cfg = frappe.get_single("ZKTeco Config")
        if cfg.enable_sync:
            # Log that the scheduler is active
            frappe.logger().info("ZKTeco scheduler check: Active")
    except Exception as e:
        frappe.log_error(f"ZKTeco scheduler check failed: {str(e)}", "ZKTeco Scheduler Check")


@frappe.whitelist()
def get_sync_status():
    """
    Get current sync status and statistics
    """
    try:
        cfg = frappe.get_single("ZKTeco Config")
        
        # Get last sync time
        last_sync = frappe.db.get_single_value("ZKTeco Config", "last_sync")
        last_sync_status = frappe.db.get_single_value("ZKTeco Config", "last_sync_status")
        failed_attempts = frappe.db.get_single_value("ZKTeco Config", "failed_sync_attempts") or 0
        
        # Count recent employee checkins from ZKTeco
        recent_checkins = frappe.db.count("Employee Checkin", {
            "device_id": ["like", "%ZKTeco%"],
            "creation": [">=", frappe.utils.add_days(today(), -1)]
        })
        
        return {
            "enabled": cfg.enable_sync,
            "sync_frequency": cfg.seconds,
            "last_sync": last_sync,
            "last_sync_status": last_sync_status or "Never",
            "failed_attempts": failed_attempts,
            "recent_checkins_24h": recent_checkins,
            "server_configured": bool(cfg.server_ip and cfg.server_port),
            "token_configured": bool(cfg.token),
            "retry_enabled": cfg.enable_retry_on_failure,
            "max_retry_attempts": cfg.max_retry_attempts,
            "retry_interval": cfg.retry_interval_seconds
        }
        
    except Exception as e:
        return {"error": str(e)}
