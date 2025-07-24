from flask import Flask, request, jsonify, render_template, redirect, url_for, session
import mysql.connector
import os
import re
from werkzeug.utils import secure_filename
from groq import Groq
from dotenv import load_dotenv
import pandas as pd
import traceback
import logging

load_dotenv()
groq_client = Groq(api_key=os.getenv('GROQ_API_KEY'))

app = Flask(__name__)
app.config['UPLOAD_FOLDER'] = 'Uploads'
app.config['MAX_CONTENT_LENGTH'] = 16 * 1024 * 1024  # 16MB
app.secret_key = os.getenv('FLASK_SECRET_KEY', 'supersecretkey')  # Load from env

# Database connection configuration
db_config = {
    'host': os.getenv('DB_HOST', 'localhost'),
    'port': int(os.getenv('DB_PORT', 3306)),
    'user': os.getenv('DB_USER', 'root'),
    'password': os.getenv('DB_PASSWORD', ''),
}

# Set up logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

def clean_sql_file(file_content):
    file_content = file_content.decode('utf-8') if isinstance(file_content, bytes) else file_content
    file_content = re.sub(r'/\*.*?\*/', '', file_content, flags=re.DOTALL)
    cleaned_lines = []
    for line in file_content.splitlines():
        line_strip = line.strip()
        if not line_strip or line_strip.startswith('--') or line_strip.startswith('#'):
            continue
        cleaned_lines.append(line)
    return '\n'.join(cleaned_lines)

def execute_sql(sql):
    try:
        conn = mysql.connector.connect(**db_config)
        cursor = conn.cursor()
        for statement in sql.split(';'):
            statement = statement.strip()
            if statement:
                cursor.execute(statement)
        conn.commit()
        return True, 'SQL executed successfully.'
    except mysql.connector.Error as err:
        return False, f"Error: {err}"
    finally:
        if 'cursor' in locals():
            cursor.close()
        if 'conn' in locals():
            conn.close()

def get_db_connection(db_name=None):
    config = db_config.copy()
    if db_name:
        config['database'] = db_name
    try:
        conn = mysql.connector.connect(**config)
        return conn, None
    except mysql.connector.Error as e:
        return None, f"Database connection failed: {str(e)}"

def get_schema_for_groq(db_name):
    try:
        conn, error = get_db_connection(db_name)
        if error:
            return None, error
        cursor = conn.cursor()
        cursor.execute(f"USE `{db_name}`")
        cursor.execute("SHOW TABLES")
        tables = [row[0] for row in cursor.fetchall()]
        schema = {}
        for table in tables:
            cursor.execute(f"DESCRIBE `{table}`")
            columns = [row[0] for row in cursor.fetchall()]
            schema[table] = columns
        cursor.close()
        conn.close()
        return schema, None
    except Exception as e:
        return None, str(e)

def get_create_table_statements(db_name):
    try:
        conn, error = get_db_connection(db_name)
        if error:
            return None, error
        cursor = conn.cursor()
        cursor.execute(f"USE `{db_name}`")
        cursor.execute("SHOW TABLES")
        tables = [row[0] for row in cursor.fetchall()]
        create_stmts = []
        for table in tables:
            cursor.execute(f"SHOW CREATE TABLE `{table}`")
            create_stmt = cursor.fetchone()[1]
            create_stmts.append(create_stmt)
        cursor.close()
        conn.close()
        return create_stmts, None
    except Exception as e:
        return None, str(e)

def extract_sql_from_response(response_text):
    code_block = re.search(r"```(?:sql)?\s*(.*?)```", response_text, re.DOTALL | re.IGNORECASE)
    if code_block:
        return code_block.group(1).strip()
    sql_match = re.search(r'(SELECT|INSERT|UPDATE|DELETE)[\s\S]+?;', response_text, re.IGNORECASE)
    if sql_match:
        return sql_match.group(0).strip()
    return response_text.strip()

def strip_use_statements(sql):
    return re.sub(r"USE\s+[`'\"]?\w+[`'\"]?;?", "", sql, flags=re.IGNORECASE).strip()

@app.route('/', methods=['GET', 'POST'])
def index():
    logger.info(f"Entered index route. Method: {request.method}")
    summary = None
    tables = []
    error = None
    results = None
    query = None
    db_name = session.get('db_name')
    logger.info(f"Session db_name: {db_name}")
    if request.method == 'POST':
        logger.info("Handling POST request.")
    elif db_name:
        logger.info(f"Loading tables for database: {db_name}")
        conn, db_error = get_db_connection(db_name)
        if db_error:
            logger.error(f"Database error: {db_error}")
            error = db_error
        else:
            try:
                cursor = conn.cursor()
                cursor.execute(f"USE `{db_name}`")
                cursor.execute("SHOW TABLES")
                tables = [row[0] for row in cursor.fetchall()]
                logger.info(f"Tables loaded: {tables}")
                cursor.close()
                conn.close()
            except Exception as e:
                logger.error(f"Error loading tables: {str(e)}")
                error = str(e)
    logger.info("Rendering template.")
    return render_template('index.html', summary=summary, tables=tables, error=error, results=results, query=query)

@app.route('/upload', methods=['POST'])
def upload():
    logger.info("Handling file upload at /upload.")
    summary = None
    tables = []
    error = None
    results = None
    query = None
    if 'sql_file' in request.files:
        logger.info("SQL file found in request.files.")
        file = request.files['sql_file']
        if file.filename:
            logger.info(f"File upload received: {file.filename}")
            filename = secure_filename(file.filename)
            filepath = os.path.join(app.config['UPLOAD_FOLDER'], filename)
            file.save(filepath)
            logger.info(f"File saved to: {filepath}")
            with open(filepath, 'rb') as f:
                file_content = f.read()
            logger.info(f"SQL file read, size: {len(file_content)} bytes")
            cleaned_sql = clean_sql_file(file_content)
            logger.info("SQL file cleaned")
            statements = [stmt.strip() for stmt in cleaned_sql.split(';') if stmt.strip()]
            logger.info(f"Parsed {len(statements)} SQL statements.")
            db_name = None
            for stmt in statements:
                match = re.match(r"CREATE\s+DATABASE\s+(?:IF\s+NOT\s+EXISTS\s+)?[`']?([^`';\s]+)[`']?", stmt, re.IGNORECASE)
                if match:
                    db_name = match.group(1)
                    session['db_name'] = db_name
                    logger.info(f"Database name extracted: {db_name}")
                    break
            try:
                conn, exec_error = get_db_connection()
                if exec_error:
                    logger.error(f"Database error: {exec_error}")
                    error = exec_error
                else:
                    conn.autocommit = True
                    cursor = conn.cursor()
                    for statement in statements:
                        upper_stmt = statement.upper()
                        if upper_stmt.startswith('CREATE DATABASE') or upper_stmt.startswith('DROP DATABASE'):
                            logger.info(f"Executing DB statement: {statement[:80]}")
                            cursor.execute(statement)
                    conn.commit()
                    if db_name:
                        logger.info(f"Checking if database '{db_name}' exists...")
                        cursor.execute("SELECT SCHEMA_NAME FROM information_schema.schemata WHERE SCHEMA_NAME = %s", (db_name,))
                        db_exists = cursor.fetchone()
                        if not db_exists:
                            logger.error(f"Database '{db_name}' was NOT created!")
                            error = f"Database '{db_name}' was NOT created!"
                            cursor.close()
                            conn.close()
                            return redirect(url_for('index'))
                    cursor.close()
                    conn.close()
                    logger.info("Database created/dropped as needed.")
                if db_name:
                    logger.info(f"Connecting to new database: {db_name}")
                    conn, db_error = get_db_connection(db_name)
                    if db_error:
                        logger.error(f"Database error: {db_error}")
                        error = db_error
                    else:
                        cursor = conn.cursor()
                        cursor.execute(f"USE `{db_name}`")
                        for statement in statements:
                            upper_stmt = statement.upper()
                            if upper_stmt.startswith('CREATE DATABASE') or upper_stmt.startswith('DROP DATABASE') or upper_stmt.startswith('USE '):
                                logger.debug(f"Skipping statement: {statement[:80]}")
                                continue
                            logger.info(f"Executing SQL statement: {statement[:80]}")
                            cursor.execute(statement)
                        conn.commit()
                        logger.info("All SQL statements executed.")
                        cursor.execute("SHOW TABLES")
                        tables = [row[0] for row in cursor.fetchall()]
                        logger.info(f"Tables loaded: {tables}")
                        cursor.close()
                        conn.close()
            except Exception as e:
                logger.error(f"Failed to execute SQL: {str(e)}")
                error = f"Failed to execute SQL: {str(e)}"
    return redirect(url_for('index'))

@app.route('/tables', methods=['GET'])
def list_tables():
    db_name = session.get('db_name')
    if not db_name:
        return jsonify({'success': False, 'message': 'No database selected'}), 400
    conn, error = get_db_connection(db_name)
    if error:
        return jsonify({'success': False, 'message': error}), 500
    try:
        cursor = conn.cursor()
        cursor.execute(f"USE `{db_name}`")
        cursor.execute("SHOW TABLES")
        tables = [row[0] for row in cursor.fetchall()]
        cursor.close()
        conn.close()
        return jsonify({'success': True, 'tables': tables})
    except Exception as e:
        return jsonify({'success': False, 'message': str(e)}), 500

@app.route('/api/table/<table_name>')
def api_table_data(table_name):
    db_name = session.get('db_name')
    if not db_name:
        return jsonify({'error': 'No database selected'}), 400
    try:
        conn, error = get_db_connection(db_name)
        if error:
            return jsonify({'error': error}), 500
        cursor = conn.cursor(dictionary=True)
        cursor.execute(f"SELECT * FROM `{table_name}`")
        rows = cursor.fetchall()
        cursor.close()
        conn.close()
        return jsonify({'data': rows})
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/query', methods=['POST'])
def api_query():
    db_name = session.get('db_name')
    if not db_name:
        return jsonify({'error': 'No database selected'}), 400
    data = request.get_json()
    question = data.get('query')
    is_nl = data.get('is_natural_language', False)
    if not question:
        return jsonify({'error': 'No query provided'}), 400
    use_warning = None
    if is_nl and re.sub(r'[^a-zA-Z]', '', question).lower() in [
        'showalldatafromalltables', 'showmealltables', 'showeverything',
        'showalltables', 'showallrowsfromalltables', 'showallrecordsfromalltables',
        'showfulldatabase', 'showfulldb', 'showentiredatabase', 'showentiredb'
    ]:
        try:
            conn, error = get_db_connection(db_name)
            if error:
                return jsonify({'error': error}), 500
            cursor = conn.cursor(dictionary=True)
            cursor.execute(f"SHOW TABLES")
            tables = [row[0] for row in cursor.fetchall()]
            all_data = {}
            for table in tables:
                cursor.execute(f"SELECT * FROM `{table}`")
                rows = cursor.fetchall()
                all_data[table] = rows
            cursor.close()
            conn.close()
            return jsonify({'status': 'Query executed', 'data': all_data, 'note': 'All data from all tables returned.'})
        except Exception as e:
            tb = traceback.format_exc()
            return jsonify({'error': str(e), 'traceback': tb}), 500
    if not is_nl:
        sql = strip_use_statements(question)
        if sql != question:
            use_warning = 'A USE statement was removed from your query.'
        try:
            conn, error = get_db_connection(db_name)
            if error:
                return jsonify({'error': error}), 500
            cursor = conn.cursor(dictionary=True)
            cursor.execute(sql)
            rows = cursor.fetchall()
            cursor.close()
            conn.close()
            return jsonify({'status': 'Query executed', 'data': rows, 'warning': use_warning} if use_warning else {'status': 'Query executed', 'data': rows})
        except Exception as e:
            error_str = str(e)
            table_names = re.findall(r'FROM\s+`?(\w+)`?|INTO\s+`?(\w+)`?|UPDATE\s+`?(\w+)`?', sql, re.IGNORECASE)
            flat_tables = [item for sublist in table_names for item in sublist if item]
            schema_text = ''
            if flat_tables:
                create_stmts = []
                for t in flat_tables:
                    stmts, schema_error = get_create_table_statements(db_name)
                    if not schema_error and stmts:
                        for stmt in stmts:
                            if f'CREATE TABLE `{t}`' in stmt or f'CREATE TABLE {t}' in stmt:
                                create_stmts.append(stmt)
                schema_text = '\n\n'.join(create_stmts)
            prompt = f"The following SQL query failed with this error:\nQuery: {sql}\nError: {error_str}\nTable schema: {schema_text}\nPlease correct the query so it works in MySQL and return only the corrected SQL."
            try:
                groq_response = groq_client.chat.completions.create(
                    model="llama3-70b-8192",
                    messages=[{"role": "user", "content": prompt}]
                )
                corrected_sql = extract_sql_from_response(groq_response.choices[0].message.content.strip())
                corrected_sql_clean = strip_use_statements(corrected_sql)
                conn2, error2 = get_db_connection(db_name)
                if error2:
                    return jsonify({'error': error2}), 500
                cursor2 = conn2.cursor(dictionary=True)
                cursor2.execute(corrected_sql_clean)
                rows2 = cursor2.fetchall()
                cursor2.close()
                conn2.close()
                return jsonify({'status': 'Query executed (corrected by LLM)', 'query': corrected_sql_clean, 'data': rows2, 'original_error': error_str})
            except Exception as e2:
                tb2 = traceback.format_exc()
                return jsonify({'error': f'Original error: {error_str}\nLLM correction failed: {str(e2)}', 'traceback': tb + '\n' + tb2}), 500
    create_stmts, schema_error = get_create_table_statements(db_name)
    if schema_error:
        return jsonify({'error': schema_error}), 500
    schema_text = '\n\n'.join(create_stmts)
    prompt = f"Given the following MySQL table definitions:\n{schema_text}\n\nConvert this request to a SQL query. Only return the SQL query, nothing else.\nRequest: {question}"
    try:
        groq_response = groq_client.chat.completions.create(
            model="llama3-70b-8192",
            messages=[{"role": "user", "content": prompt}]
        )
        sql_query = extract_sql_from_response(groq_response.choices[0].message.content.strip())
        sql_query_clean = strip_use_statements(sql_query)
        if sql_query_clean != sql_query:
            use_warning = 'A USE statement was removed from the AI-generated query.'
        logger.info(f"Generated SQL: {sql_query_clean}")
        conn, error = get_db_connection(db_name)
        if error:
            return jsonify({'error': error}), 500
        cursor = conn.cursor(dictionary=True)
        cursor.execute(sql_query_clean)
        rows = cursor.fetchall()
        cursor.close()
        conn.close()
        return jsonify({'status': 'Query executed', 'query': sql_query_clean, 'data': rows, 'warning': use_warning} if use_warning else {'status': 'Query executed', 'query': sql_query_clean, 'data': rows})
    except Exception as e:
        tb = traceback.format_exc()
        error_str = str(e)
        if '503' in error_str or 'Service unavailable' in error_str:
            return jsonify({'error': 'Groq service is temporarily unavailable.', 'traceback': tb}), 503
        return jsonify({'error': f'Groq or SQL error: {error_str}', 'traceback': tb}), 500

@app.route('/api/tables', methods=['GET'])
def api_tables():
    db_name = session.get('db_name')
    if not db_name:
        return jsonify({'success': False, 'message': 'No database selected'}), 400
    conn, error = get_db_connection(db_name)
    if error:
        return jsonify({'success': False, 'message': error}), 500
    try:
        cursor = conn.cursor()
        cursor.execute(f"USE `{db_name}`")
        cursor.execute("SHOW TABLES")
        tables = [row[0] for row in cursor.fetchall()]
        cursor.close()
        conn.close()
        return jsonify({'success': True, 'tables': tables})
    except Exception as e:
        return jsonify({'success': False, 'message': str(e)}), 500

def preprocess_row_data(row_data, schema):
    processed = {}
    for col in schema:
        name = col['Field']
        typ = col['Type'].lower()
        val = row_data.get(name)
        if val is None or val == '':
            processed[name] = None
        elif 'int' in typ:
            try:
                processed[name] = int(val)
            except (ValueError, TypeError):
                logger.warning(f"Invalid integer value for {name}: {val}, setting to None")
                processed[name] = None
        elif 'double' in typ or 'float' in typ or 'decimal' in typ:
            try:
                processed[name] = float(val)
            except (ValueError, TypeError):
                logger.warning(f"Invalid numeric value for {name}: {val}, setting to None")
                processed[name] = None
        elif 'date' in typ or 'datetime' in typ:
            if isinstance(val, str):
                try:
                    from datetime import datetime
                    d = datetime.fromisoformat(val.replace('Z', '+00:00') if 'Z' in val else val)
                    processed[name] = d.strftime('%Y-%m-%d') if 'date' in typ else d.strftime('%Y-%m-%d %H:%M:%S')
                except (ValueError, TypeError):
                    logger.warning(f"Invalid date value for {name}: {val}, setting to None")
                    processed[name] = None
            else:
                processed[name] = None
        else:
            processed[name] = str(val)
    return processed

def try_llm_correction(original_sql, error_str, table_name, row_data, db_name, columns, pk_columns):
    conn, _ = get_db_connection(db_name)
    cursor = conn.cursor(dictionary=True)
    cursor.execute(f"DESCRIBE `{table_name}`")
    schema = cursor.fetchall()
    cursor.execute(f"SHOW CREATE TABLE `{table_name}`")
    create_stmt = cursor.fetchone()['Create Table']
    cursor.close()
    conn.close()
    column_types = {col['Field']: col['Type'] for col in schema}
    prompt = (
        f"The following SQL query failed with this error:\n"
        f"Query: {original_sql}\n"
        f"Error: {error_str}\n"
        f"Table schema: {create_stmt}\n"
        f"Column types: {column_types}\n"
        f"Row data: {row_data}\n"
        f"Primary keys: {pk_columns}\n"
        f"Generate a corrected MySQL UPDATE query. Use %s placeholders for values in the SET and WHERE clauses, "
        f"matching the order of non-primary key columns ({len([col for col in columns if col not in pk_columns])}) "
        f"followed by primary key columns ({len(pk_columns)}) if primary keys are provided, or all columns ({len(columns)}) twice if no primary keys. "
        f"Ensure values match column types (e.g., 'YYYY-MM-DD' for DATE, numbers for DOUBLE/INT, strings for VARCHAR). "
        f"Exclude any columns from SET clause where the value is NULL or incompatible with the column type. "
        f"Return only the SQL query."
    )
    try:
        groq_response = groq_client.chat.completions.create(
            model="llama3-70b-8192",
            messages=[{"role": "user", "content": prompt}]
        )
        return extract_sql_from_response(groq_response.choices[0].message.content.strip())
    except Exception as e:
        logger.error(f"LLM correction request failed: {str(e)}")
        raise

@app.route('/api/update/<table_name>', methods=['PUT'])
def api_update_table(table_name):
    db_name = session.get('db_name')
    if not db_name:
        logger.error("No database selected")
        return jsonify({'error': 'No database selected'}), 400
    try:
        data = request.get_json()
        if not data:
            logger.error("No JSON data received")
            return jsonify({'error': 'No JSON data provided'}), 400
        rows = data.get('data')
        if not rows or not isinstance(rows, list):
            logger.error("No data provided or invalid data format")
            return jsonify({'error': 'No data provided or invalid format'}), 400
        conn, error = get_db_connection(db_name)
        if error:
            logger.error(f"Database connection error: {error}")
            return jsonify({'error': error}), 500
        cursor = conn.cursor(dictionary=True)
        cursor.execute(f"DESCRIBE `{table_name}`")
        schema = cursor.fetchall()
        if not schema:
            cursor.close()
            conn.close()
            logger.error(f"Table '{table_name}' does not exist or has no schema")
            return jsonify({'error': f"Table '{table_name}' does not exist or has no schema"}), 404
        columns = [row['Field'] for row in schema]
        cursor.execute(f"SHOW KEYS FROM `{table_name}` WHERE Key_name = 'PRIMARY'")
        pk_info = cursor.fetchall()
        pk_columns = [row['Column_name'] for row in pk_info] if pk_info else []
        logger.info(f"Table '{table_name}' schema: {columns}, primary keys: {pk_columns}")

        # Get schema for LLM
        cursor.execute(f"SHOW CREATE TABLE `{table_name}`")
        create_stmt = cursor.fetchone()['Create Table']
        column_types = {col['Field']: col['Type'] for col in schema}
        for item in rows:
            if pk_columns and 'pk' in item and 'row' in item:
                pk = item['pk']
                row = item['row']
                processed_row = preprocess_row_data(row, schema)
                # Filter out NULL or incompatible values for SET clause
                valid_set_columns = [col for col in columns if col not in pk_columns and processed_row.get(col) is not None]
                if not valid_set_columns:
                    logger.warning("No valid columns to update")
                    continue
                prompt = (
                    f"Given the following MySQL table schema:\n{create_stmt}\n"
                    f"Column types: {column_types}\n"
                    f"Primary keys: {pk_columns}\n"
                    f"Row data to update: {processed_row}\n"
                    f"Primary key values: {pk}\n"
                    f"Generate a MySQL UPDATE query to update the row with the given primary key values. "
                    f"Use %s placeholders for values in the SET clause (for non-primary key columns: {valid_set_columns}) "
                    f"and WHERE clause (for primary key columns: {pk_columns}). "
                    f"Ensure the number of %s placeholders matches the number of non-primary key columns to update ({len(valid_set_columns)}) "
                    f"plus primary key columns ({len(pk_columns)}). "
                    f"Ensure values match column types (e.g., 'YYYY-MM-DD' for DATE, numbers for DOUBLE/INT). "
                    f"Exclude NULL or incompatible values from the SET clause. "
                    f"Return only the SQL query."
                )
                try:
                    groq_response = groq_client.chat.completions.create(
                        model="llama3-70b-8192",
                        messages=[{"role": "user", "content": prompt}]
                    )
                    sql = extract_sql_from_response(groq_response.choices[0].message.content.strip())
                    sql = strip_use_statements(sql)
                    logger.info(f"Generated UPDATE SQL: {sql}")
                    set_values = [processed_row.get(col) for col in valid_set_columns]
                    pk_values = [pk.get(col) for col in pk_columns]
                    placeholder_count = sql.count('%s')
                    expected_count = len(set_values) + len(pk_values)
                    if placeholder_count != expected_count:
                        logger.error(f"Placeholder mismatch: expected {expected_count}, found {placeholder_count}")
                        raise ValueError(f"SQL query has {placeholder_count} placeholders, but {expected_count} values provided")
                    cursor.execute(sql, set_values + pk_values)
                except Exception as e:
                    error_str = str(e)
                    logger.error(f"UPDATE failed: {error_str}")
                    corrected_sql = try_llm_correction(sql, error_str, table_name, processed_row, db_name, columns, pk_columns)
                    logger.info(f"Corrected UPDATE SQL: {corrected_sql}")
                    placeholder_count = corrected_sql.count('%s')
                    if placeholder_count != expected_count:
                        logger.error(f"Corrected SQL placeholder mismatch: expected {expected_count}, found {placeholder_count}")
                        raise ValueError(f"Corrected SQL has {placeholder_count} placeholders, expected {expected_count}")
                    try:
                        cursor.execute(corrected_sql, set_values + pk_values)
                    except Exception as e2:
                        logger.error(f"LLM correction failed: {str(e2)}")
                        raise Exception(f"Original error: {error_str}\nLLM correction failed: {str(e2)}")
            elif 'row_data' in item:
                row_data = item['row_data']
                processed_row = preprocess_row_data(row_data, schema)
                valid_set_columns = [col for col in columns if processed_row.get(col) is not None]
                if not valid_set_columns:
                    logger.warning("No valid columns to update")
                    continue
                prompt = (
                    f"Given the following MySQL table schema:\n{create_stmt}\n"
                    f"Column types: {column_types}\n"
                    f"Row data to update: {processed_row}\n"
                    f"Generate a MySQL UPDATE query to update the row where all column values match the provided data. "
                    f"Use %s placeholders for values in the SET clause and WHERE clause (for columns: {valid_set_columns}). "
                    f"Ensure the number of %s placeholders matches the number of columns to update ({len(valid_set_columns)}) "
                    f"for SET and ({len(valid_set_columns)}) for WHERE. "
                    f"Ensure values match column types (e.g., 'YYYY-MM-DD' for DATE, numbers for DOUBLE/INT). "
                    f"Exclude NULL or incompatible values from the SET clause. "
                    f"Return only the SQL query."
                )
                try:
                    groq_response = groq_client.chat.completions.create(
                        model="llama3-70b-8192",
                        messages=[{"role": "user", "content": prompt}]
                    )
                    sql = extract_sql_from_response(groq_response.choices[0].message.content.strip())
                    sql = strip_use_statements(sql)
                    logger.info(f"Generated UPDATE SQL: {sql}")
                    set_values = [processed_row.get(col) for col in valid_set_columns]
                    where_values = [processed_row.get(col) for col in valid_set_columns]
                    placeholder_count = sql.count('%s')
                    expected_count = len(set_values) + len(where_values)
                    if placeholder_count != expected_count:
                        logger.error(f"Placeholder mismatch: expected {expected_count}, found {placeholder_count}")
                        raise ValueError(f"SQL query has {placeholder_count} placeholders, but {expected_count} values provided")
                    cursor.execute(sql, set_values + where_values)
                except Exception as e:
                    error_str = str(e)
                    logger.error(f"UPDATE failed: {error_str}")
                    corrected_sql = try_llm_correction(sql, error_str, table_name, processed_row, db_name, columns, [])
                    logger.info(f"Corrected UPDATE SQL: {corrected_sql}")
                    placeholder_count = corrected_sql.count('%s')
                    if placeholder_count != expected_count:
                        logger.error(f"Corrected SQL placeholder mismatch: expected {expected_count}, found {placeholder_count}")
                        raise ValueError(f"Corrected SQL has {placeholder_count} placeholders, expected {expected_count}")
                    try:
                        cursor.execute(corrected_sql, set_values + where_values)
                    except Exception as e2:
                        logger.error(f"LLM correction failed: {str(e2)}")
                        raise Exception(f"Original error: {error_str}\nLLM correction failed: {str(e2)}")
            else:
                logger.error("Invalid row format: missing pk or row_data")
                raise ValueError("Invalid row format: missing pk or row_data")
        conn.commit()
        logger.info(f"Table '{table_name}' updated successfully")
        return jsonify({'status': 'Table updated successfully'})
    except Exception as e:
        logger.error(f"Update error: {str(e)}")
        return jsonify({'error': str(e)}), 500
    finally:
        if 'cursor' in locals():
            cursor.close()
        if 'conn' in locals():
            conn.close()

@app.route('/api/delete/<table_name>', methods=['DELETE'])
def api_delete_row(table_name):
    db_name = session.get('db_name')
    if not db_name:
        return jsonify({'error': 'No database selected'}), 400
    data = request.get_json()
    pk = data.get('pk')
    row_data = data.get('row_data')
    try:
        conn, error = get_db_connection(db_name)
        if error:
            return jsonify({'error': error}), 500
        cursor = conn.cursor()
        cursor.execute(f"DESCRIBE `{table_name}`")
        schema = cursor.fetchall()
        cursor.execute(f"SHOW KEYS FROM `{table_name}` WHERE Key_name = 'PRIMARY'")
        pk_info = cursor.fetchall()
        pk_columns = [row[4] for row in pk_info] if pk_info else []
        if pk and pk_columns:
            where_clause = ' AND '.join([f"`{col}` = %s" for col in pk.keys()])
            values = list(pk.values())
            sql = f"DELETE FROM `{table_name}` WHERE {where_clause}"
            try:
                cursor.execute(sql, values)
            except Exception as e:
                error_str = str(e)
                processed_row = preprocess_row_data(pk, [dict(zip([desc[0] for desc in cursor.description], s)) for s in schema])
                corrected_sql = try_llm_correction(sql, error_str, table_name, processed_row, db_name, values)
                try:
                    if '%s' in corrected_sql:
                        cursor.execute(corrected_sql, values)
                    else:
                        cursor.execute(corrected_sql)
                except Exception as e2:
                    return jsonify({'error': f'Original error: {error_str}\nLLM correction failed: {str(e2)}'})
        elif row_data:
            processed_row = preprocess_row_data(row_data, [dict(zip([desc[0] for desc in cursor.description], s)) for s in schema])
            where_clause = ' AND '.join([f"`{col}` = %s" for col in row_data.keys()])
            values = list(processed_row.values())
            sql = f"DELETE FROM `{table_name}` WHERE {where_clause}"
            try:
                cursor.execute(sql, values)
            except Exception as e:
                error_str = str(e)
                corrected_sql = try_llm_correction(sql, error_str, table_name, processed_row, db_name, values)
                try:
                    if '%s' in corrected_sql:
                        cursor.execute(corrected_sql, values)
                    else:
                        cursor.execute(corrected_sql)
                except Exception as e2:
                    return jsonify({'error': f'Original error: {error_str}\nLLM correction failed: {str(e2)}'})
        else:
            return jsonify({'error': 'No identifier provided'}), 400
        conn.commit()
        cursor.close()
        conn.close()
        return jsonify({'status': 'Row deleted successfully'})
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/pk/<table_name>', methods=['GET'])
def api_get_primary_key(table_name):
    db_name = session.get('db_name')
    if not db_name:
        return jsonify({'error': 'No database selected'}), 400
    try:
        conn, error = get_db_connection(db_name)
        if error:
            return jsonify({'error': error}), 500
        cursor = conn.cursor()
        cursor.execute(f"SHOW KEYS FROM `{table_name}` WHERE Key_name = 'PRIMARY'")
        pk_info = cursor.fetchall()
        pk_columns = [row[4] for row in pk_info]
        cursor.close()
        conn.close()
        return jsonify({'primary_key': pk_columns})
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/describe/<table_name>', methods=['GET'])
def api_describe_table(table_name):
    db_name = session.get('db_name')
    if not db_name:
        return jsonify({'error': 'No database selected'}), 400
    try:
        conn, error = get_db_connection(db_name)
        if error:
            return jsonify({'error': error}), 500
        cursor = conn.cursor(dictionary=True)
        cursor.execute(f"DESCRIBE `{table_name}`")
        schema = cursor.fetchall()
        cursor.close()
        conn.close()
        return jsonify(schema)
    except Exception as e:
        return jsonify({'error': str(e)}), 500

if __name__ == '__main__':
    if not os.path.exists(app.config['UPLOAD_FOLDER']):
        os.makedirs(app.config['UPLOAD_FOLDER'])
    app.run(host='0.0.0.0', port=5001, debug=True)