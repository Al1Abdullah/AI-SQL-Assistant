# AI-SQL-Assistant

AI-SQL-Assistant is a powerful natural language interface for MySQL databases. It allows users to input questions or commands in plain English and get AI-generated SQL queries, which can be executed directly against a connected database. Built using Python, Flask, and OpenAI's API, this tool helps developers, analysts, and non-technical users interact with SQL databases more intuitively.

---

## Features

- Natural language to SQL translation using AI
- Direct execution of AI-generated SQL queries
- Result display in table format
- Schema-aware querying for improved accuracy
- Error handling and debugging support
- Web interface and API support (Flask backend)

---

## Getting Started

### 1. Clone the Repository

```bash
git clone https://github.com/Al1Abdullah/AI-SQL-Assistant.git
cd AI-SQL-Assistant
```

### 2. Install Dependencies

```bash
pip install -r requirements.txt
```

### 3. Set Environment Variables

Create a `.env` file in the project root and add:

```bash
GROQ_API_KEY=your_groq_key
DB_HOST=localhost
DB_USER=root
DB_PASSWORD=yourpassword
DB_NAME=your_database_name
```

You may rename and edit the existing `.env.example` file.

---

## Usage

### Run the Flask App

```bash
python app.py
```

### Interact

Open your browser and go to `http://localhost:5000`. Type your natural language query like:

```
Show all patients older than 60 who visited in the last 30 days.
```

The assistant will:
1. Analyze the prompt
2. Generate the corresponding SQL query
3. Execute it against the connected MySQL database
4. Show the result in a readable table

---

## Example

**Prompt:**
```
List the top 5 most sold products in June 2025.
```

**Generated SQL:**
```sql
SELECT product_name, SUM(quantity) AS total_sold
FROM sales
WHERE sale_date BETWEEN '2025-06-01' AND '2025-06-30'
GROUP BY product_name
ORDER BY total_sold DESC
LIMIT 5;
```

---

## Project Structure

```
AI-SQL-Assistant/
├── app.py              # Main Flask app
├── config.py           # Configuration and environment loading
├── query_generator.py  # Core AI SQL logic
├── schema_loader.py    # Optional: loads schema metadata
├── templates/          # HTML templates (if using UI)
├── static/             # CSS/JS files
├── .env.example        # Sample environment config
├── requirements.txt    # Python dependencies
└── README.md           # Project documentation
```

---

## Development Tips

- You can modify the prompt format to include schema hints
- Review generated SQL before executing for safety
- Logs and errors are printed to the terminal for debugging

---

## Contributing

Contributions are welcome!

1. Fork the repository
2. Create a new branch: `git checkout -b feature/your-feature`
3. Commit your changes: `git commit -am 'Add new feature'`
4. Push the branch: `git push origin feature/your-feature`
5. Open a pull request

---

## License

This project is licensed under the MIT License. See the [LICENSE](LICENSE) file for details.

---

## Author

**Ali Abdullah**  
BS AI Student  
GitHub: [@Al1Abdullah](https://github.com/Al1Abdullah)

---
