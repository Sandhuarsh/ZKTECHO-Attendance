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


def log_integration_request(title, status, response=None, error=None, details=None):
    """
    Create an Integration Log entry for tracking all API requests and responses
    """
    try:
        log_message = f"Status: {status}\n"
        
        if response:
            log_message += f"Response: {json.dumps(response, indent=2, default=str)}\n"
        
        if error:
            log_message += f"Error: {error}\n"
        
        if details:
            log_message += f"Details: {json.dumps(details, indent=2, default=str)}\n"
        
        # Create Integration Log entry
        log_doc = frappe.get_doc({
            "doctype": "Integration Log",
            "reference_doctype": "ZKTeco Config",
            "reference_name": frappe.get_single("ZKTeco Config").name,
            "method": title,
            "status": status,
            "request_headers": json.dumps({"Authorization": "Token ***"}),
            "response": log_message,
            "error": error or ""
        })
        log_doc.insert(ignore_permissions=True)
        frappe.db.commit()
        
    except Exception as e:
        frappe.logger().error(f"Failed to create integration log: {str(e)}")


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
        error_msg = _("Please configure server IP, port, username, and password.")
        log_integration_request("register_api_token", "Failed", error=str(error_msg))
        frappe.throw(error_msg)

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
            error_msg = f"Login Failed: {response.text}"
            log_integration_request("register_api_token", "Failed", error=error_msg)
            frappe.throw(_(error_msg))

        data = response.json()
        token = data.get("token")

        if not token:
            error_msg = f"Token not found: {response.text}"
            log_integration_request("register_api_token", "Failed", error=error_msg)
            frappe.throw(_(error_msg))

        # Save DRF token directly
        frappe.db.set_single_value("ZKTeco Config", "token", token)
        frappe.db.commit()

        log_integration_request("register_api_token", "Success", 
                              response={"token": token[:20] + "***"}, 
                              details={"status_code": response.status_code})

        return {
            "success": True,
            "message": "Token registered successfully",
            "token": token
        }

    except requests.exceptions.RequestException as e:
        error_msg = f"Connection error: {str(e)}"
        log_integration_request("register_api_token", "Failed", error=error_msg)
        frappe.throw(_(error_msg))


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
        error_msg = _("Token not set in ZKTeco Config. Please register/save a token first.")
        log_integration_request("test_connection", "Failed", error=str(error_msg))
        return {"ok": False, "error": error_msg}

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
        "page": 1,
        "page_size": 5
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
                    transaction_count = data.get('count', len(transactions))
                elif isinstance(data, dict) and 'count' in data:
                    transactions = data.get('results', data.get('data', []))
                    transaction_count = data.get('count', len(transactions))
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
                
                result = {
                    "ok": True,
                    "status_code": resp.status_code,
                    "url": resp.url,
                    "total_transactions": transaction_count,
                    "transactions_preview": formatted_transactions,
                    "raw_sample": transactions[:2] if transactions else [],
                    "message": f"Found {transaction_count} transactions for {day}"
                }
                
                log_integration_request("test_connection", "Success", response=result)
                return result
                
            except json.JSONDecodeError as e:
                error_dict = {
                    "ok": False,
                    "status_code": resp.status_code,
                    "error": f"Invalid JSON response: {str(e)}",
                    "raw_response": resp.text[:500]
                }
                log_integration_request("test_connection", "Failed", error=str(error_dict))
                return error_dict
        else:
            error_dict = {
                "ok": False,
                "status_code": resp.status_code,
                "url": resp.url,
                "error": f"HTTP {resp.status_code}: {resp.text[:200]}"
            }
            log_integration_request("test_connection", "Failed", error=str(error_dict))
            return error_dict
            
    except requests.RequestException as e:
        error_dict = {
            "ok": False,
            "error": f"Connection error: {str(e)}"
        }
        log_integration_request("test_connection", "Failed", error=str(error_dict))
        return error_dict


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
            
            sync_details = {
                "processed": processed_count,
                "errors": error_count,
                "total_fetched": len(transactions),
                "last_sync_time": str(current_time),
                "sync_period": f"{str(last_sync)} to {str(current_time)}"
            }
            
            log_integration_request("sync_zkteco_transactions", sync_status, 
                                  response=sync_details)
            
            frappe.logger().info(f"ZKTeco Sync completed: {processed_count} processed, {error_count} errors out of {len(transactions)} fetched")
        else:
            log_integration_request("sync_zkteco_transactions", "NoData", response={"message": "No transactions found"})
        
    except Exception as e:
        frappe.log_error(f"ZKTeco sync failed: {str(e)}", "ZKTeco Sync Fatal Error")
        log_integration_request("sync_zkteco_transactions", "Failed", error=str(e))
        
        # Update failed attempts counter
        failed_attempts = frappe.db.get_single_value("ZKTeco Config", "failed_sync_attempts") or 0
        frappe.db.set_single_value("ZKTeco Config", "failed_sync_attempts", failed_attempts + 1)
        frappe.db.set_single_value("ZKTeco Config", "last_sync_status", "Failed")
        frappe.db.commit()


def fetch_zkteco_transactions(cfg, start_time, end_time, page=1, page_size=100):
    """
    Fetch transactions from ZKTeco device with pagination support
    Returns tuple of (transactions, total_count)
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
        "page": page,
        "page_size": page_size
    }
    
    try:
        resp = requests.get(base_url, headers=headers, params=params, timeout=30)
        resp.raise_for_status()
        
        data = resp.json()
        
        # Handle ZKTeco API response format - multiple variations
        if isinstance(data, dict):
            # Check for 'count' field to get total
            total_count = data.get('count', 0)
            
            # Get transactions from various possible keys
            if 'data' in data:
                transactions = data['data']
            elif 'results' in data:
                transactions = data['results']
            else:
                transactions = data.get('results', [])
            
            return transactions, total_count
        elif isinstance(data, list):
            return data, len(data)
        else:
            return [], 0
            
    except Exception as e:
        frappe.log_error(f"Failed to fetch ZKTeco transactions (Page {page}): {str(e)}", "ZKTeco API Error")
        return [], 0


def fetch_zkteco_transactions_with_retry(cfg, start_time, end_time):
    """
    Fetch ALL transactions from ZKTeco device with pagination and retry mechanism
    Handles device unavailability gracefully
    """
    max_retries = int(cfg.max_retry_attempts or 3) if cfg.enable_retry_on_failure else 1
    retry_interval = int(cfg.retry_interval_seconds or 60) if cfg.enable_retry_on_failure else 0
    attempt = 0
    all_transactions = []
    page_size = 100
    page = 1
    total_count = 0
    
    while attempt < max_retries:
        try:
            page = 1  # Reset page for this attempt
            all_transactions = []
            total_count = 0
            
            # Fetch all pages of transactions
            while True:
                frappe.logger().info(f"Fetching page {page} (page_size: {page_size}) from {start_time} to {end_time}")
                
                transactions, total_count = fetch_zkteco_transactions(cfg, start_time, end_time, page, page_size)
                
                if not transactions:
                    break
                
                all_transactions.extend(transactions)
                frappe.logger().info(f"Fetched page {page}: {len(transactions)} transactions. Total so far: {len(all_transactions)}/{total_count}")
                
                # Check if we have fetched all records
                if len(all_transactions) >= total_count > 0:
                    frappe.logger().info(f"All {total_count} transactions fetched successfully")
                    break
                
                page += 1
                # Add small delay between pages to avoid overwhelming the API
                time.sleep(0.5)
            
            # Success - we got all transactions (or no error occurred)
            if all_transactions or total_count == 0:
                # Reset failed attempts on successful fetch
                frappe.db.set_single_value("ZKTeco Config", "failed_sync_attempts", 0)
                frappe.db.set_single_value("ZKTeco Config", "last_sync_status", "Success")
                frappe.db.commit()
                
                log_integration_request("fetch_zkteco_transactions_with_retry", "Success",
                                      response={"total_fetched": len(all_transactions), "total_available": total_count, 
                                               "pages_fetched": page - 1})
                
                frappe.logger().info(f"Transaction fetch completed: {len(all_transactions)} records fetched")
                return all_transactions
                
        except requests.exceptions.ConnectionError as e:
            attempt += 1
            error_msg = f"ZKTeco device connection failed (Attempt {attempt}/{max_retries}): {str(e)}"
            frappe.log_error(error_msg, "ZKTeco Connection Error")
            
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
                log_integration_request("fetch_zkteco_transactions_with_retry", "Failed", error=error_msg)
                frappe.log_error(
                    f"ZKTeco device unavailable after {max_retries} attempts. Will retry on next scheduled sync.", 
                    "ZKTeco Device Unavailable"
                )
                return []
                
        except Exception as e:
            attempt += 1
            error_msg = f"Unexpected error fetching transactions (Attempt {attempt}/{max_retries}): {str(e)}"
            frappe.log_error(error_msg, "ZKTeco Fetch Error")
            log_integration_request("fetch_zkteco_transactions_with_retry", "Failed", error=error_msg)
            
            if attempt < max_retries and cfg.enable_retry_on_failure:
                time.sleep(retry_interval)
            else:
                return []
    
    return all_transactions


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
        log_integration_request("manual_sync", "Success", response={"message": "Sync completed successfully"})
        return {"success": True, "message": "Sync completed successfully"}
    except Exception as e:
        error_msg = f"Manual sync failed: {str(e)}"
        frappe.log_error(error_msg, "ZKTeco Manual Sync")
        log_integration_request("manual_sync", "Failed", error=error_msg)
        return {"success": False, "message": error_msg}


@frappe.whitelist()
def manual_pull_by_date_range():
    """
    Manual pull transactions for a specific date range with pagination
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
                    
                    employee = find_employee_by_code(emp_code)
                    if not employee:
                        skipped_count += 1
                        continue
                    
                    existing = frappe.db.exists("Employee Checkin", {
                        "employee": employee,
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
            
            result = {
                "success": True,
                "message": f"Manual pull completed",
                "processed": processed_count,
                "errors": error_count,
                "skipped": skipped_count,
                "total": len(transactions)
            }
            
            log_integration_request("manual_pull_by_date_range", "Success", response=result)
            
            return result
        else:
            error_msg = "No transactions found for the specified date range"
            log_integration_request("manual_pull_by_date_range", "NoData", response={"message": error_msg})
            return {
                "success": False,
                "message": error_msg
            }
        
    except Exception as e:
        error_msg = f"Manual pull failed: {str(e)}"
        frappe.log_error(error_msg, "ZKTeco Manual Pull Fatal Error")
        log_integration_request("manual_pull_by_date_range", "Failed", error=error_msg)
        return {"success": False, "message": error_msg}


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
        error_msg = f"Scheduled ZKTeco sync failed: {str(e)}"
        frappe.log_error(error_msg, "ZKTeco Scheduled Sync Error")
        log_integration_request("scheduled_sync", "Failed", error=error_msg)


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
