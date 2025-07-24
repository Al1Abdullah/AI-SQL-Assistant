function toggleSection(id) {
    const content = document.getElementById(id);
    content.style.display = content.style.display === 'none' || content.style.display === '' ? 'block' : 'none';
}

// Helper to fetch primary key columns for a table
async function getPrimaryKeyColumns(tableName) {
    try {
        const pkRes = await fetch(`/api/pk/${encodeURIComponent(tableName)}`);
        const pkJson = await pkRes.json();
        if (pkJson.primary_key && pkJson.primary_key.length > 0) {
            return pkJson.primary_key;
        }
    } catch (err) {}
    return [];
}

// Helper to fetch table schema
async function getTableSchema(tableName) {
    try {
        const res = await fetch(`/api/describe/${encodeURIComponent(tableName)}`);
        const schema = await res.json();
        if (!schema.error) return schema;
    } catch (err) {}
    return [];
}

async function loadTableData() {
    const tableSelect = document.getElementById('table-select');
    const tableName = tableSelect.value;
    const tableData = document.getElementById('table-data');
    const tableError = document.getElementById('table-error');
    if (!tableName) {
        tableData.querySelector('thead tr').innerHTML = '';
        tableData.querySelector('tbody').innerHTML = '';
        tableError.textContent = '';
        return;
    }

    let pkColumns = await getPrimaryKeyColumns(tableName);

    try {
        const response = await fetch(`/api/table/${encodeURIComponent(tableName)}`);
        const result = await response.json();
        if (result.error) {
            tableError.textContent = result.error;
            tableData.querySelector('thead tr').innerHTML = '';
            tableData.querySelector('tbody').innerHTML = '';
            return;
        }

        tableError.textContent = '';
        const data = result.data;
        if (data.length === 0) {
            tableData.querySelector('thead tr').innerHTML = '';
            tableData.querySelector('tbody').innerHTML = '<tr><td colspan="1">No data available</td></tr>';
            return;
        }

        const headers = Object.keys(data[0]);
        tableData.querySelector('thead tr').innerHTML = headers.map(h => `<th>${h}</th>`).join('');
        tableData.querySelector('tbody').innerHTML = data.map((row, index) =>
            `<tr data-index="${index}">${headers.map(h =>
                pkColumns.includes(h)
                    ? `<td data-column="${h}" style="background:#eee;" contenteditable="false">${row[h] || ''}</td>`
                    : `<td contenteditable="true" data-column="${h}">${row[h] || ''}</td>`
            ).join('')}</tr>`
        ).join('');

        tableData.querySelectorAll('td[contenteditable="true"]').forEach(cell => {
            cell.addEventListener('input', () => {
                const rowIndex = cell.parentElement.dataset.index;
                const column = cell.dataset.column;
                console.log(`Edited cell: Table=${tableName}, Row=${rowIndex}, Column=${column}, Value=${cell.textContent}`);
            });
        });
    } catch (error) {
        tableError.textContent = `Failed to load table data: ${error.message}`;
    }
}

function toMySQLDate(val) {
    const d = new Date(val);
    if (!isNaN(d.getTime())) {
        // If the original value includes time, return full datetime
        if (val.includes('T') || val.includes(':')) {
            const pad = n => n < 10 ? '0' + n : n;
            return `${d.getFullYear()}-${pad(d.getMonth()+1)}-${pad(d.getDate())} ${pad(d.getHours())}:${pad(d.getMinutes())}:${pad(d.getSeconds())}`;
        }
        // Otherwise, just date
        return d.toISOString().slice(0, 10);
    }
    return val;
}

async function updateTable() {
    const tableName = document.getElementById('table-select').value;
    const tableData = document.getElementById('table-data');
    const tableError = document.getElementById('table-error');
    if (!tableName) {
        tableError.textContent = 'Please select a table';
        return;
    }

    const schema = await getTableSchema(tableName);
    const pkColumns = await getPrimaryKeyColumns(tableName);
    const rows = tableData.querySelectorAll('tbody tr');
    const data = Array.from(rows).map(row => {
        const cells = row.querySelectorAll('td');
        const rowData = {};
        const identifier = {};
        let hasEmptyPK = false;
        cells.forEach(cell => {
            const column = cell.dataset.column;
            let value = cell.textContent || null;
            const colSchema = schema.find(col => col.Field === column);
            if (colSchema) {
                if (/int|decimal|float|double/.test(colSchema.Type) && (value === '' || value === null)) {
                    value = null;
                }
            }
            if (value && Date.parse(value) && !/^\d{4}-\d{2}-\d{2}/.test(value)) {
                value = toMySQLDate(value);
            }
            rowData[column] = value;
            if (pkColumns.includes(column)) {
                if (!value) hasEmptyPK = true;
                identifier[column] = value;
            }
        });
        return pkColumns.length > 0 && !hasEmptyPK ? { pk: identifier, row: rowData } : { row_data: rowData };
    }).filter(item => Object.keys(item.pk || item.row_data).length > 0);

    if (data.length === 0) {
        tableError.textContent = 'No valid rows to update.';
        return;
    }

    console.log('Sending update request:', { table: tableName, data: data });
    try {
        const response = await fetch(`/api/update/${encodeURIComponent(tableName)}`, {
            method: 'PUT',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ data })
        });
        console.log('Response status:', response.status);
        console.log('Response headers:', response.headers.get('content-type'));
        const text = await response.text();
        console.log('Raw response:', text);
        try {
            const result = JSON.parse(text);
            console.log('Parsed JSON:', result);
            if (response.ok) {
                tableError.textContent = result.status || 'Table updated successfully';
                loadTableData();
            } else {
                tableError.textContent = `Failed to update table: ${result.error || 'Unknown error'}`;
            }
        } catch (e) {
            console.error('JSON parse error:', e.message);
            console.error('Raw response was:', text);
            tableError.textContent = `Failed to update table: Server returned invalid JSON - ${e.message}`;
        }
    } catch (error) {
        console.error('Fetch error:', error);
        tableError.textContent = `Failed to update table: ${error.message}`;
    }
}

async function insertRow() {
    const tableName = document.getElementById('table-select').value;
    const tableError = document.getElementById('table-error');
    const tableData = document.getElementById('table-data');
    if (!tableName) {
        tableError.textContent = 'Please select a table';
        return;
    }

    // Fetch table schema to determine AUTO_INCREMENT and NOT NULL columns
    let schema = [];
    try {
        const res = await fetch(`/api/describe/${encodeURIComponent(tableName)}`);
        schema = await res.json();
        if (schema.error) {
            tableError.textContent = schema.error;
            return;
        }
    } catch (err) {
        tableError.textContent = 'Failed to fetch table schema.';
        return;
    }

    // Build new row, omitting AUTO_INCREMENT columns
    const newRow = {};
    schema.forEach(col => {
        if (col.Extra && col.Extra.includes('auto_increment')) {
            // Skip auto_increment columns
            return;
        }
        // For NOT NULL columns, prompt the user for a value (simple prompt for now)
        let value = null;
        if (col.Null === 'NO') {
            value = prompt(`Enter value for required column '${col.Field}' (${col.Type}):`, '');
            if (value === null) value = '';
        }
        // Format as MySQL date if needed
        if (value && Date.parse(value) && !/^\d{4}-\d{2}-\d{2}/.test(value)) {
            value = toMySQLDate(value);
        }
        newRow[col.Field] = value;
    });

    try {
        const response = await fetch(`/api/insert/${encodeURIComponent(tableName)}`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ data: [newRow] })
        });
        const result = await response.json();
        if (result.error) {
            tableError.textContent = result.error;
            return;
        }
        tableError.textContent = result.status;
        loadTableData();
    } catch (error) {
        tableError.textContent = `Failed to insert row: ${error.message}`;
    }
}

async function deleteRow() {
    const tableName = document.getElementById('table-select').value;
    const rowIndex = document.getElementById('delete-row-index').value;
    const tableError = document.getElementById('table-error');
    const tableData = document.getElementById('table-data');
    if (!tableName || rowIndex === '') {
        tableError.textContent = 'Please select a table and enter a row index';
        return;
    }

    let pkColumns = await getPrimaryKeyColumns(tableName);
    const rows = tableData.querySelectorAll('tbody tr');
    if (rowIndex < 0 || rowIndex >= rows.length) {
        tableError.textContent = 'Row index out of range';
        return;
    }
    const row = rows[rowIndex];
    const cells = row.querySelectorAll('td');
    const headers = Array.from(tableData.querySelectorAll('thead th')).map(th => th.textContent);

    let pk = {};
    let row_data = {};
    headers.forEach((col, idx) => {
        const value = cells[idx].textContent;
        row_data[col] = value;
        if (pkColumns.includes(col)) {
            pk[col] = value;
        }
    });

    const body = pkColumns.length > 0 ? { pk } : { row_data };

    try {
        const response = await fetch(`/api/delete/${encodeURIComponent(tableName)}`, {
            method: 'DELETE',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(body)
        });
        const result = await response.json();
        if (result.error) {
            tableError.textContent = result.error;
            return;
        }
        tableError.textContent = result.status;
        loadTableData();
    } catch (error) {
        tableError.textContent = `Failed to delete row: ${error.message}`;
    }
}

function ensureQueryUIElements() {
    const queryForm = document.getElementById('query-form');
    let queryStatus = document.getElementById('query-status');
    if (!queryStatus) {
        queryStatus = document.createElement('div');
        queryStatus.id = 'query-status';
        queryStatus.className = 'mt-2';
        queryForm.parentNode.insertBefore(queryStatus, queryForm.nextSibling);
    }
    let aiSqlDiv = document.getElementById('ai-sql-response');
    if (!aiSqlDiv) {
        aiSqlDiv = document.createElement('div');
        aiSqlDiv.id = 'ai-sql-response';
        aiSqlDiv.className = 'mt-3';
        queryForm.parentNode.insertBefore(aiSqlDiv, queryStatus.nextSibling);
    }
}

async function runQuery() {
    ensureQueryUIElements();
    const query = document.getElementById('question').value;
    const isNaturalLanguage = document.getElementById('is-natural-language').checked;
    const queryResult = document.getElementById('query-result');
    let queryStatus = document.getElementById('query-status');
    let aiSqlDiv = document.getElementById('ai-sql-response');
    if (!query) {
        ensureQueryUIElements();
        document.getElementById('query-status').textContent = 'Please enter a query';
        aiSqlDiv.innerHTML = '';
        return;
    }

    try {
        const response = await fetch('/api/query', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ query, is_natural_language: isNaturalLanguage })
        });
        const result = await response.json();
        if (result.error) {
            let errorHtml = `<div class='alert alert-danger'><strong>Error:</strong> ${result.error}`;
            if (result.traceback) {
                errorHtml += `<br/><strong>Traceback:</strong><pre style='max-height:300px;overflow:auto;'>${result.traceback}</pre>`;
            }
            errorHtml += '</div>';
            aiSqlDiv.innerHTML = errorHtml;
            if (queryResult) {
                queryResult.querySelector('thead tr').innerHTML = '';
                queryResult.querySelector('tbody').innerHTML = '';
            }
            return;
        }
        ensureQueryUIElements();
        document.getElementById('query-status').textContent = result.status || '';
        // Show the AI-generated SQL if present
        if (result.query) {
            aiSqlDiv.innerHTML = `<div class='alert alert-info'><strong>AI Generated SQL:</strong><textarea id='ai-sql-textarea' class='form-control mt-2' rows='3' style='font-family:monospace;'>${result.query}</textarea><button id='execute-sql-btn' class='btn btn-sm btn-primary mt-2'>Execute SQL</button></div>`;
            // Add event listener for the execute button
            setTimeout(() => {
                const execBtn = document.getElementById('execute-sql-btn');
                const sqlTextarea = document.getElementById('ai-sql-textarea');
                if (execBtn && sqlTextarea) {
                    execBtn.onclick = () => executeSqlDirect(sqlTextarea.value);
                }
            }, 0);
        } else {
            aiSqlDiv.innerHTML = '';
        }
        if (result.data && result.data.length > 0 && queryResult) {
            const headers = Object.keys(result.data[0]);
            queryResult.querySelector('thead tr').innerHTML = headers.map(h => `<th>${h}</th>`).join('');
            queryResult.querySelector('tbody').innerHTML = result.data.map(row => 
                `<tr>${headers.map(h => `<td>${row[h] || ''}</td>`).join('')}</tr>`
            ).join('');
        } else if (queryResult) {
            queryResult.querySelector('thead tr').innerHTML = '';
            queryResult.querySelector('tbody').innerHTML = '<tr><td colspan="1">No results found</td></tr>';
        }
    } catch (error) {
        aiSqlDiv.innerHTML = `<div class='alert alert-danger'><strong>Request failed:</strong> ${error.message}</div>`;
        ensureQueryUIElements();
        document.getElementById('query-status').textContent = `Failed to execute query: ${error.message}`;
    }
}

async function executeSqlDirect(sql) {
    ensureQueryUIElements();
    const queryResult = document.getElementById('query-result');
    let queryStatus = document.getElementById('query-status');
    let aiSqlDiv = document.getElementById('ai-sql-response');
    let noResultsMsg = document.getElementById('no-results-msg');
    try {
        console.log('[DEBUG] Executing SQL:', sql);
        const response = await fetch('/api/query', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ query: sql, is_natural_language: false })
        });
        const result = await response.json();
        console.log('[DEBUG] API response:', result);
        if (result.error) {
            let errorHtml = `<div class='alert alert-danger'><strong>Error:</strong> ${result.error}`;
            if (result.traceback) {
                errorHtml += `<br/><strong>Traceback:</strong><pre style='max-height:300px;overflow:auto;'>${result.traceback}</pre>`;
            }
            errorHtml += '</div>';
            aiSqlDiv.innerHTML = errorHtml;
            if (queryResult) {
                queryResult.querySelector('thead tr').innerHTML = '';
                queryResult.querySelector('tbody').innerHTML = '';
            }
            if (!noResultsMsg) {
                noResultsMsg = document.createElement('div');
                noResultsMsg.id = 'no-results-msg';
                noResultsMsg.className = 'alert alert-warning mt-2';
                queryResult.parentNode.insertBefore(noResultsMsg, queryResult);
            }
            noResultsMsg.textContent = 'No results found for the query. Check your data or try a different question.';
            return;
        }
        ensureQueryUIElements();
        document.getElementById('query-status').textContent = result.status || '';
        if (result.data && result.data.length > 0 && queryResult) {
            if (noResultsMsg) noResultsMsg.remove();
            const headers = Object.keys(result.data[0]);
            queryResult.querySelector('thead tr').innerHTML = headers.map(h => `<th>${h}</th>`).join('');
            queryResult.querySelector('tbody').innerHTML = result.data.map(row => 
                `<tr>${headers.map(h => `<td>${row[h] || ''}</td>`).join('')}</tr>`
            ).join('');
            // Scroll to and highlight the table
            queryResult.scrollIntoView({ behavior: 'smooth', block: 'center' });
            queryResult.classList.add('table-highlight');
            setTimeout(() => queryResult.classList.remove('table-highlight'), 1200);
        } else if (queryResult) {
            queryResult.querySelector('thead tr').innerHTML = '';
            queryResult.querySelector('tbody').innerHTML = '<tr><td colspan="1">No results found</td></tr>';
            queryResult.scrollIntoView({ behavior: 'smooth', block: 'center' });
            if (!noResultsMsg) {
                noResultsMsg = document.createElement('div');
                noResultsMsg.id = 'no-results-msg';
                noResultsMsg.className = 'alert alert-warning mt-2';
                queryResult.parentNode.insertBefore(noResultsMsg, queryResult);
            }
            noResultsMsg.textContent = 'No results found for the query. Check your data or try a different question.';
        }
    } catch (error) {
        console.error('[DEBUG] Request failed:', error);
        aiSqlDiv.innerHTML = `<div class='alert alert-danger'><strong>Request failed:</strong> ${error.message}</div>`;
        ensureQueryUIElements();
        document.getElementById('query-status').textContent = `Failed to execute query: ${error.message}`;
    }
}

// Prevent form submit from reloading the page for the query form
const queryForm = document.getElementById('query-form');
if (queryForm) {
    queryForm.addEventListener('submit', function(e) {
        e.preventDefault();
        runQuery();
    });
}

document.addEventListener('DOMContentLoaded', async () => {
    ensureQueryUIElements();
    try {
        const response = await fetch('/api/tables');
        const result = await response.json();
        const tableSelect = document.getElementById('table-select');
        tableSelect.innerHTML = '<option value="">Select a table</option>' + 
            result.tables.map(table => `<option value="${table}">${table}</option>`).join('');
    } catch (error) {
        document.getElementById('table-error').textContent = `Failed to load tables: ${error.message}`;
    }
});
