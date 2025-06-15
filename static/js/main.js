// Main JavaScript file for Lead Generation Tool

// Helper function to show alerts
function showAlert(message, type = 'info') {
    const alertDiv = document.createElement('div');
    alertDiv.className = `alert alert-${type}`;
    alertDiv.textContent = message;
    
    const main = document.querySelector('main');
    main.insertBefore(alertDiv, main.firstChild);
    
    // Auto-remove after 5 seconds
    setTimeout(() => {
        alertDiv.remove();
    }, 5000);
}

// Helper function for API calls
async function apiCall(url, method = 'GET', data = null) {
    const options = {
        method,
        headers: {
            'Content-Type': 'application/json',
        }
    };
    
    if (data) {
        options.body = JSON.stringify(data);
    }
    
    try {
        const response = await fetch(url, options);
        const result = await response.json();
        
        if (!result.success && result.error) {
            throw new Error(result.error);
        }
        
        return result;
    } catch (error) {
        console.error('API call failed:', error);
        throw error;
    }
}

// Handle form submissions with loading states
function handleFormSubmit(formId, callback) {
    const form = document.getElementById(formId);
    if (!form) return;
    
    form.addEventListener('submit', async (e) => {
        e.preventDefault();
        
        const submitBtn = form.querySelector('button[type="submit"]');
        const originalText = submitBtn.textContent;
        
        // Add loading state
        submitBtn.disabled = true;
        submitBtn.innerHTML = originalText + ' <span class="loading"></span>';
        
        try {
            await callback(form);
        } catch (error) {
            showAlert(error.message, 'error');
        } finally {
            // Remove loading state
            submitBtn.disabled = false;
            submitBtn.textContent = originalText;
        }
    });
}

// Handle table row selection
function initTableSelection(tableId) {
    const table = document.getElementById(tableId);
    if (!table) return;
    
    // Select all checkbox
    const selectAllCheckbox = table.querySelector('thead input[type="checkbox"]');
    const rowCheckboxes = table.querySelectorAll('tbody input[type="checkbox"]');
    
    if (selectAllCheckbox) {
        selectAllCheckbox.addEventListener('change', (e) => {
            // Only select/deselect checkboxes in visible rows
            rowCheckboxes.forEach(checkbox => {
                const row = checkbox.closest('tr');
                // Check if the row is visible (not hidden by search filter)
                if (row.style.display !== 'none') {
                    checkbox.checked = e.target.checked;
                }
            });
            updateSelectionCount(tableId);
        });
    }
    
    // Individual row selection
    rowCheckboxes.forEach(checkbox => {
        checkbox.addEventListener('change', () => {
            updateSelectionCount(tableId);
            
            // Update the select all checkbox state based on visible selections
            updateSelectAllState(tableId);
        });
    });
}

// Helper function to update the "select all" checkbox state
function updateSelectAllState(tableId) {
    const table = document.getElementById(tableId);
    const selectAllCheckbox = table.querySelector('thead input[type="checkbox"]');
    
    if (!selectAllCheckbox) return;
    
    const visibleCheckboxes = [];
    table.querySelectorAll('tbody input[type="checkbox"]').forEach(checkbox => {
        const row = checkbox.closest('tr');
        if (row.style.display !== 'none') {
            visibleCheckboxes.push(checkbox);
        }
    });
    
    if (visibleCheckboxes.length === 0) {
        selectAllCheckbox.checked = false;
        selectAllCheckbox.indeterminate = false;
        return;
    }
    
    const checkedVisible = visibleCheckboxes.filter(cb => cb.checked);
    
    if (checkedVisible.length === 0) {
        selectAllCheckbox.checked = false;
        selectAllCheckbox.indeterminate = false;
    } else if (checkedVisible.length === visibleCheckboxes.length) {
        selectAllCheckbox.checked = true;
        selectAllCheckbox.indeterminate = false;
    } else {
        selectAllCheckbox.checked = false;
        selectAllCheckbox.indeterminate = true; // Show indeterminate state for partial selection
    }
}

// Update selection count
function updateSelectionCount(tableId) {
    const table = document.getElementById(tableId);
    const selectedCount = table.querySelectorAll('tbody input[type="checkbox"]:checked').length;
    const countElement = document.getElementById(`${tableId}-count`);
    
    if (countElement) {
        countElement.textContent = selectedCount;
    }
    
    // Enable/disable action buttons based on selection
    const actionBtn = document.getElementById(`${tableId}-action`);
    if (actionBtn) {
        actionBtn.disabled = selectedCount === 0;
    }
}

// Get selected rows from table
function getSelectedRows(tableId) {
    const table = document.getElementById(tableId);
    const selectedRows = [];
    
    table.querySelectorAll('tbody tr').forEach(row => {
        const checkbox = row.querySelector('input[type="checkbox"]');
        if (checkbox && checkbox.checked) {
            const rowData = {};
            row.querySelectorAll('td').forEach((cell, index) => {
                const header = table.querySelectorAll('thead th')[index];
                if (header && header.dataset.field) {
                    const fieldName = header.dataset.field;
                    
                    // Special handling for Link field to extract href from anchor tags
                    if (fieldName === 'Link') {
                        const anchor = cell.querySelector('a');
                        if (anchor) {
                            let href = anchor.href;
                            // Clean up the href to remove the protocol prefix if it was added
                            if (href.startsWith('https://https://') || href.startsWith('http://https://')) {
                                href = href.substring(href.indexOf('https://') + 8);
                            } else if (href.startsWith('https://http://') || href.startsWith('http://http://')) {
                                href = href.substring(href.indexOf('http://') + 7);
                            } else if (href.startsWith('https://')) {
                                href = href.substring(8);
                            } else if (href.startsWith('http://')) {
                                href = href.substring(7);
                            }
                            rowData[fieldName] = href;
                        } else {
                            rowData[fieldName] = cell.textContent.trim();
                        }
                    } else {
                        rowData[fieldName] = cell.textContent.trim();
                    }
                }
            });
            selectedRows.push(rowData);
        }
    });
    
    return selectedRows;
}

// Initialize tabs
function initTabs() {
    const tabContainers = document.querySelectorAll('.tabs');
    
    tabContainers.forEach(container => {
        const tabs = container.querySelectorAll('.tab');
        const contents = container.parentElement.querySelectorAll('.tab-content');
        
        tabs.forEach((tab, index) => {
            tab.addEventListener('click', () => {
                // Remove active class from all tabs and contents
                tabs.forEach(t => t.classList.remove('active'));
                contents.forEach(c => c.classList.remove('active'));
                
                // Add active class to clicked tab and corresponding content
                tab.classList.add('active');
                if (contents[index]) {
                    contents[index].classList.add('active');
                }
            });
        });
    });
}

// Search functionality for tables
function initTableSearch(searchInputId, tableId) {
    const searchInput = document.getElementById(searchInputId);
    const table = document.getElementById(tableId);
    
    if (!searchInput || !table) return;
    
    searchInput.addEventListener('input', (e) => {
        const searchTerm = e.target.value.toLowerCase();
        const rows = table.querySelectorAll('tbody tr');
        
        rows.forEach(row => {
            const text = row.textContent.toLowerCase();
            row.style.display = text.includes(searchTerm) ? '' : 'none';
        });
        
        // Update count after filtering
        updateSelectionCount(tableId);
        
        // Update the select all checkbox state after filtering
        updateSelectAllState(tableId);
    });
}

// Progress bar update
function updateProgress(progressId, percent) {
    const progressBar = document.querySelector(`#${progressId} .progress-bar`);
    if (progressBar) {
        progressBar.style.width = `${percent}%`;
    }
}

// Initialize on page load
document.addEventListener('DOMContentLoaded', () => {
    // Initialize tabs
    initTabs();
    
    // Initialize any tables with selection
    ['leads-table', 'searches-table', 'sources-table'].forEach(tableId => {
        initTableSelection(tableId);
    });
    
    // Initialize search boxes
    initTableSearch('leads-search', 'leads-table');
    initTableSearch('searches-search', 'searches-table');
    
    // Handle spreadsheet ID update
    const spreadsheetInput = document.getElementById('spreadsheet-id');
    if (spreadsheetInput) {
        let timeout;
        spreadsheetInput.addEventListener('input', (e) => {
            clearTimeout(timeout);
            timeout = setTimeout(async () => {
                try {
                    await apiCall('/update_spreadsheet', 'POST', {
                        spreadsheet_id: e.target.value
                    });
                    showAlert('Spreadsheet ID updated', 'success');
                    // Reload page to refresh data
                    window.location.reload();
                } catch (error) {
                    showAlert('Failed to update spreadsheet ID', 'error');
                }
            }, 1000); // Debounce for 1 second
        });
    }
    
    // Handle cache refresh button
    const refreshBtn = document.getElementById('refresh-cache');
    if (refreshBtn) {
        refreshBtn.addEventListener('click', async () => {
            try {
                refreshBtn.disabled = true;
                refreshBtn.innerHTML = 'Refreshing... <span class="loading"></span>';
                
                await apiCall('/refresh_cache', 'POST');
                showAlert('Cache refreshed successfully', 'success');
                window.location.reload();
            } catch (error) {
                showAlert('Failed to refresh cache', 'error');
            } finally {
                refreshBtn.disabled = false;
                refreshBtn.textContent = '🔄 Refresh Data';
            }
        });
    }
}); 