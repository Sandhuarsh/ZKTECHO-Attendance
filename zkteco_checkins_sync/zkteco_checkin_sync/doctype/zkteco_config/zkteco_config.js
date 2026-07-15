// Copyright (c) 2025, osama.ahmed@deliverydevs.com and contributors
// For license information, please see license.txt

frappe.ui.form.on("ZKTeco Config", {
    refresh(frm) {
        // Add custom buttons
        if (frm.doc.enable_sync && frm.doc.token) {
            frm.add_custom_button(__('Manual Sync'), function() {
                manual_sync(frm);
            }, __('Actions'));
            
            frm.add_custom_button(__('Sync Status'), function() {
                show_sync_status(frm);
            }, __('Actions'));
        }
        
        // Show sync status indicator
        if (frm.doc.enable_sync) {
            show_sync_indicator(frm);
        }
    },

    enable_sync(frm) {
        if (frm.doc.enable_sync) {
            frappe.show_alert({
                message: __('ZKTeco sync enabled. Configure server settings and test connection.'),
                indicator: 'blue'
            });
        }
    },

    test_connection(frm) {
        frappe.call({
            method: "zkteco_checkins_sync.zkteco_checkin_sync.doctype.zkteco_config.zkteco_config.test_connection",
            freeze: true,
            freeze_message: __("Testing connection...")
        }).then((r) => {
            const msg = r.message || {};
            if (msg.ok) {
                frappe.show_alert({
                    message: __(`✅ Connected successfully! Found ${msg.total_transactions || 0} transactions today.`),
                    indicator: "green"
                });
                
                // Show detailed transaction preview
                if (msg.transactions_preview && msg.transactions_preview.length > 0) {
                    show_transaction_preview(msg.transactions_preview, msg.total_transactions);
                } else {
                    frappe.msgprint({
                        title: __("Connection Successful"),
                        message: __(`✅ Connected to ZKTeco device successfully!<br>
                                   📊 Total transactions today: ${msg.total_transactions || 0}<br>
                                   🔗 URL: ${msg.url}<br>
                                   📡 Status: ${msg.status_code}`),
                        indicator: "green"
                    });
                }
            } else {
                frappe.show_alert({
                    message: __(`❌ Connection failed. Status: ${msg.status_code || "N/A"}`),
                    indicator: "red"
                });
                if (msg.error) {
                    frappe.msgprint({
                        title: __("Connection Error"),
                        message: `<pre style="white-space:pre-wrap; color: red;">${frappe.utils.escape_html(msg.error)}</pre>`,
                        indicator: "red"
                    });
                }
            }
        }).catch((e) => {
            frappe.msgprint({
                title: __("Error"),
                message: `<pre style="white-space:pre-wrap; color: red;">${frappe.utils.escape_html(e.message || e)}</pre>`,
                indicator: "red"
            });
        });
    },

    register_api_token(frm) {
        frappe.call({
            method: "zkteco_checkins_sync.zkteco_checkin_sync.doctype.zkteco_config.zkteco_config.register_api_token",
            freeze: true,
            freeze_message: __("Registering token...")
        }).then((r) => {
            if (r.message && r.message.token) {
                frm.set_value("token", r.message.token);
                frm.save().then(() => {
                    frappe.show_alert({ 
                        message: __("✅ API token registered and saved successfully!"), 
                        indicator: "green" 
                    });
                });
            }
        }).catch((e) => {
            frappe.msgprint({
                title: __("Token Registration Failed"),
                message: frappe.utils.escape_html(e.message || e),
                indicator: "red"
            });
        });
    },

    manual_pull_range(frm) {
        if (!frm.doc.start_date || !frm.doc.end_date) {
            frappe.show_alert({
                message: __('❌ Please select both Start Date and End Date'),
                indicator: 'red'
            });
            return;
        }

        frappe.call({
            method: "zkteco_checkins_sync.zkteco_checkin_sync.doctype.zkteco_config.zkteco_config.manual_pull_by_date_range",
            freeze: true,
            freeze_message: __("Pulling transactions for date range...")
        }).then((r) => {
            const result = r.message || {};
            if (result.success) {
                frappe.msgprint({
                    title: __("Date Range Pull Completed"),
                    message: `✅ <strong>Success!</strong><br>
                             📊 Processed: ${result.processed || 0}<br>
                             ⏭️ Skipped (Already Synced): ${result.skipped || 0}<br>
                             ❌ Errors: ${result.errors || 0}<br>
                             📈 Total Transactions: ${result.total || 0}`,
                    indicator: "green"
                });
                frm.reload_doc();
            } else {
                frappe.show_alert({
                    message: __(`❌ Pull failed: ${result.message || 'Unknown error'}`),
                    indicator: 'red'
                });
            }
        }).catch((e) => {
            frappe.msgprint({
                title: __("Pull Error"),
                message: `<pre style="white-space:pre-wrap; color: red;">${frappe.utils.escape_html(e.message || e)}</pre>`,
                indicator: "red"
            });
        });
    }
});

function show_transaction_preview(transactions, total_count) {
    let html = `<div style="margin-bottom: 15px;">
                    <strong>📊 Found ${total_count} transactions today</strong><br>
                    <small>Showing latest ${transactions.length} transactions:</small>
                </div>`;
    
    html += `<div style="max-height: 400px; overflow-y: auto;">
             <table class="table table-bordered table-striped" style="font-size: 12px;">
                <thead>
                    <tr style="background-color: #f8f9fa;">
                        <th>ID</th>
                        <th>Employee</th>
                        <th>Time</th>
                        <th>Type</th>
                        <th>Device</th>
                        <th>ERPNext Status</th>
                    </tr>
                </thead>
                <tbody>`;
    
    transactions.forEach(txn => {
        const statusBadge = txn.erpnext_employee ? 
            '<span style="color: green;">✅ Mapped</span>' : 
            '<span style="color: orange;">⚠️ Not Found</span>';
        
        const logTypeColor = txn.log_type === 'IN' ? 'blue' : 'red';
        
        html += `<tr>
                    <td>${txn.id || 'N/A'}</td>
                    <td>
                        <strong>${txn.employee_code}</strong><br>
                        <small>${txn.zkteco_name || 'Unknown'}</small>
                    </td>
                    <td>${txn.punch_time}</td>
                    <td><span style="color: ${logTypeColor}; font-weight: bold;">${txn.log_type}</span></td>
                    <td>${txn.device_id || 'Unknown'}</td>
                    <td>${statusBadge}</td>
                </tr>`;
    });
    
    html += `</tbody></table></div>`;
    
    html += `<div style="margin-top: 15px; padding: 10px; background-color: #e7f3ff; border-radius: 4px;">
                <small><strong>💡 Tips:</strong><br>
                • Make sure employee codes in ERPNext match the emp_code from ZKTeco<br>
                • Employees with "Not Found" status won't be synced to ERPNext<br>
                • Enable sync and set frequency to automatically import these transactions</small>
             </div>`;
    
    const d = new frappe.ui.Dialog({
        title: __('ZKTeco Transactions Preview'),
        fields: [{
            fieldtype: 'HTML',
            fieldname: 'transaction_preview',
            options: html
        }],
        size: 'large'
    });
    
    d.show();
}

function manual_sync(frm) {
    frappe.call({
        method: "zkteco_checkins_sync.zkteco_checkin_sync.doctype.zkteco_config.zkteco_config.manual_sync",
        freeze: true,
        freeze_message: __("Syncing transactions...")
    }).then((r) => {
        if (r.message && r.message.success) {
            frappe.show_alert({
                message: __('✅ Manual sync completed successfully!'),
                indicator: 'green'
            });
        } else {
            frappe.show_alert({
                message: __(`❌ Sync failed: ${r.message.message || 'Unknown error'}`),
                indicator: 'red'
            });
        }
    });
}

function show_sync_status(frm) {
    frappe.call({
        method: "zkteco_checkins_sync.zkteco_checkin_sync.doctype.zkteco_config.zkteco_config.get_sync_status"
    }).then((r) => {
        const status = r.message || {};
        
        let html = '<div style="padding: 10px;">';
        
        if (status.error) {
            html += `<div style="color: red;">❌ Error: ${status.error}</div>`;
        } else {
            // Determine status indicator color
            let statusColor = 'orange';
            if (status.last_sync_status === 'Success') statusColor = 'green';
            else if (status.last_sync_status === 'Failed') statusColor = 'red';
            else if (status.last_sync_status === 'Retrying') statusColor = 'blue';
            
            html += `<table class="table table-bordered">
                        <tr><td><strong>Sync Enabled:</strong></td><td>${status.enabled ? '✅ Yes' : '❌ No'}</td></tr>
                        <tr><td><strong>Sync Frequency:</strong></td><td>Every ${status.sync_frequency || 'N/A'} seconds</td></tr>
                        <tr><td><strong>Last Sync:</strong></td><td>${status.last_sync || 'Never'}</td></tr>
                        <tr><td><strong>Last Sync Status:</strong></td><td><span style="color: ${statusColor === 'green' ? 'green' : statusColor === 'red' ? 'red' : statusColor === 'blue' ? 'blue' : 'orange'};">● ${status.last_sync_status || 'Never'}</span></td></tr>
                        <tr><td><strong>Failed Attempts:</strong></td><td>${status.failed_attempts || 0}</td></tr>
                        <tr><td><strong>Recent Check-ins (24h):</strong></td><td>${status.recent_checkins_24h || 0}</td></tr>
                        <tr><td><strong>Server Configured:</strong></td><td>${status.server_configured ? '✅ Yes' : '❌ No'}</td></tr>
                        <tr><td><strong>Token Configured:</strong></td><td>${status.token_configured ? '✅ Yes' : '❌ No'}</td></tr>
                        <tr style="background-color: #f0f0f0;"><td colspan="2"><strong>Retry Mechanism</strong></td></tr>
                        <tr><td><strong>Retry on Failure:</strong></td><td>${status.retry_enabled ? '✅ Enabled' : '❌ Disabled'}</td></tr>
                        <tr><td><strong>Max Retry Attempts:</strong></td><td>${status.max_retry_attempts || 'N/A'}</td></tr>
                        <tr><td><strong>Retry Interval:</strong></td><td>${status.retry_interval || 'N/A'} seconds</td></tr>
                     </table>`;
        }
        
        html += '</div>';
        
        frappe.msgprint({
            title: __('ZKTeco Sync Status'),
            message: html,
            indicator: status.enabled ? 'green' : 'orange'
        });
    });
}

function show_sync_indicator(frm) {
    const sync_frequency = frm.doc.seconds;
    const token_configured = frm.doc.token ? true : false;
    const retry_enabled = frm.doc.enable_retry_on_failure ? true : false;
    
    let indicator_color = 'red';
    let indicator_text = 'Sync Disabled';
    
    if (frm.doc.enable_sync && token_configured) {
        indicator_color = 'green';
        let retryInfo = retry_enabled ? ` | Retry: ${frm.doc.max_retry_attempts}x` : '';
        indicator_text = `Sync Active (${sync_frequency}s${retryInfo})`;
    } else if (frm.doc.enable_sync) {
        indicator_color = 'orange';
        indicator_text = 'Sync Enabled (Token Missing)';
    }
    
    frm.dashboard.add_indicator(indicator_text, indicator_color);
}