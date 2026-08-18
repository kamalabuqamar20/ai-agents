"""
database.py — manages all interactions with the SQLite database.

A database is an organized way to store and retrieve data. We use SQLite,
which stores everything in a single file (resume.db) — no server needed.

This file is organized as a class called `database`. You learned about classes
in your OOP course: a class bundles related data and functions together.
Here, the class bundles all database operations (creating tables, inserting
data, querying data) into one place.

HOW THE DATA IS ORGANIZED:
  institutions  (e.g. Michigan State University)
      └── positions  (e.g. Instructor)
              └── experiences  (e.g. CSE 491)
                      └── skills  (e.g. Python, level 10)
"""

import sqlite3
import csv
import os
import json
import math
from io import StringIO

from flask_app.utils.embeddings import generate_embedding

# Path to the SQLite database file — created automatically on first run
DB_PATH = 'flask_app/database/resume.db'

TABLE_ORDER = ['institutions', 'positions', 'experiences', 'skills', 'llm_roles']

# Which columns get combined into the text that gets embedded for each
# table, and each table's primary key column.
EMBEDDING_FIELDS = {
    'institutions': ['name', 'department'],
    'positions':    ['title', 'responsibilities'],
    'experiences':  ['name', 'description'],
    'skills':       ['name'],
}
ID_COLUMNS = {
    'institutions': 'inst_id',
    'positions':    'position_id',
    'experiences':  'experience_id',
    'skills':       'skill_id',
}


class database:
    """
    Manages all interactions with the SQLite resume database.

    Usage:
        db = database()
        db.createTables(purge=True)   # sets up tables and loads CSV data
        data = db.getResumeData()     # returns the full resume as a dict
    """

    def __init__(self):
        """
        Store the path to the database file.
        Unlike PostgreSQL, SQLite needs no username, password, or host —
        just a file path.
        """
        self.db_path = DB_PATH

    # ------------------------------------------------------------------
    # CORE QUERY FUNCTION
    # ------------------------------------------------------------------

    def query(self, sql, params=()):
        """
        Execute any SQL statement and return results as a list of dicts.
        """
        connection = sqlite3.connect(self.db_path, timeout=10)
        try:
            connection.execute("PRAGMA foreign_keys = ON")
            connection.row_factory = sqlite3.Row
            cursor = connection.cursor()
            cursor.execute(sql, params)
            results = []
            if sql.strip().upper().startswith(('SELECT', 'PRAGMA')):
                results = [dict(row) for row in cursor.fetchall()]
            connection.commit()
        finally:
            connection.close()
        return results
    # ------------------------------------------------------------------
    # TABLE SETUP
    # ------------------------------------------------------------------

    def createTables(self, purge=False):
        """
        Create all database tables and load initial data from CSV files.

        Args:
            purge (bool): If True, drop existing tables first (fresh start).

        # QUESTION: What would happen if you ran the app twice without purge=True?
        #           The INSERT statements would try to insert duplicate IDs.
        #           Try it — comment out purge=True in __init__.py and restart.
        """
        data_folder = 'flask_app/database/'

        if purge:
            # Drop tables in reverse order so foreign keys don't block deletion
            for table in reversed(TABLE_ORDER):
                self.query(f"DROP TABLE IF EXISTS {table}")

        # Create each table using its .sql file, then seed it from its .csv file
        for table in TABLE_ORDER:
            self._create_table(data_folder, table)
            self._seed_table(data_folder, table)

    def _create_table(self, data_folder, table):
        """Read the .sql file for a table and execute it."""
        sql_file = os.path.join(data_folder, 'create_tables', f'{table}.sql')
        with open(sql_file) as f:
            self.query(f.read())

    def _seed_table(self, data_folder, table):
        """
        Load initial data from a CSV file into a table.

        The CSV files in flask_app/database/initial_data/ are where you
        customize the resume content. Each file corresponds to one table.

        # NOTE: Edit these CSV files to add your own resume data!
        #       Restart the app after editing to reload the database.
        """
        csv_file = os.path.join(data_folder, 'initial_data', f'{table}.csv')

        if not os.path.exists(csv_file):
            return

        with open(csv_file) as f:
            reader = csv.DictReader(f)
            rows = list(reader)

        if not rows:
            return

        columns = list(rows[0].keys())
        placeholders = ', '.join(['?' for _ in columns])
        column_names = ', '.join(columns)
        sql = f"INSERT OR IGNORE INTO {table} ({column_names}) VALUES ({placeholders})"

        # Convert "NULL" strings from CSV into Python None values
        values = [
            tuple(None if cell == 'NULL' else cell for cell in row.values())
            for row in rows
        ]

        connection = sqlite3.connect(self.db_path)
        connection.row_factory = sqlite3.Row
        cursor = connection.cursor()
        cursor.executemany(sql, values)
        connection.commit()
        connection.close()
        print(f"  Loaded data for table: {table}")

    # ------------------------------------------------------------------
    # RESUME DATA
    # ------------------------------------------------------------------

    def getResumeData(self):
        """
        Return the full resume as a nested dictionary.

        Structure:
            {
              inst_id: {
                'name': '...', 'type': '...',
                'positions': {
                  position_id: {
                    'title': '...', 'start_date': '...',
                    'experiences': {
                      experience_id: {
                        'name': '...', 'description': '...',
                        'skills': { skill_id: {'name': '...', 'skill_level': 7} }
                      }
                    }
                  }
                }
              }
            }

        This nested structure is passed directly to the resume.html template,
        where Jinja2 loops over it to render the page.
        """
        resume = {}

        for institution in self.query("SELECT * FROM institutions"):
            inst_id = institution['inst_id']
            resume[inst_id] = dict(institution)
            resume[inst_id]['positions'] = {}

            positions = self.query(
                "SELECT * FROM positions WHERE inst_id = ? ORDER BY start_date DESC",
                (inst_id,)
            )

            for position in positions:
                pos_id = position['position_id']
                resume[inst_id]['positions'][pos_id] = dict(position)
                resume[inst_id]['positions'][pos_id]['experiences'] = {}

                experiences = self.query(
                    "SELECT * FROM experiences WHERE position_id = ? ORDER BY start_date DESC",
                    (pos_id,)
                )

                for experience in experiences:
                    exp_id = experience['experience_id']
                    resume[inst_id]['positions'][pos_id]['experiences'][exp_id] = dict(experience)
                    resume[inst_id]['positions'][pos_id]['experiences'][exp_id]['skills'] = {}

                    skills = self.query(
                        "SELECT * FROM skills WHERE experience_id = ?",
                        (exp_id,)
                    )

                    for skill in skills:
                        skill_id = skill['skill_id']
                        resume[inst_id]['positions'][pos_id]['experiences'][exp_id]['skills'][skill_id] = dict(skill)

        self._format_dates(resume)
        return resume

    def _format_dates(self, resume):
        """
        Convert raw date strings like '2019-01-01' to 'YYYY-MM' format.
        None end_dates become 'Present'.
        Modifies the resume dict in place.
        """
        for institution in resume.values():
            for position in institution['positions'].values():
                position['start_date'] = self._short_date(position['start_date'])
                position['end_date'] = self._short_date(position['end_date']) or 'Present'

                for experience in position['experiences'].values():
                    experience['start_date'] = self._short_date(experience['start_date'])
                    experience['end_date'] = self._short_date(experience['end_date']) or ''

    def _short_date(self, date_string):
        """Return just the 'YYYY-MM' part of a date string, or None."""
        if date_string:
            return str(date_string)[:7]
        return None

    def getResumeText(self):
        """
        Return the resume as a plain-text string, used as context for the AI.

        # NOTE: This is exactly what the AI reads about you before answering
        #       questions. Edit your CSV files to change what it knows.
        # QUESTION: What information would you add to make the AI more helpful?
        """
        resume = self.getResumeData()
        lines = []

        for institution in resume.values():
            lines.append(f"\nInstitution: {institution['name']} ({institution['type']}) — {institution.get('city', '')}, {institution.get('state', '')}")

            for position in institution['positions'].values():
                lines.append(f"  Position: {position['title']} ({position['start_date']} to {position['end_date']})")
                lines.append(f"  Responsibilities: {position.get('responsibilities', '')}")

                for experience in position['experiences'].values():
                    lines.append(f"    Experience: {experience['name']} — {experience.get('description', '')}")

                    for skill in experience['skills'].values():
                        lines.append(f"      Skill: {skill['name']} (level {skill['skill_level']}/10)")

        return '\n'.join(lines)

    def getLLMRoles(self):
        """
        Return every row of llm_roles as a dict keyed by role name, e.g.
            {"Database Read Expert": {"role": ..., "domain": ..., ...}, ...}
        This is what each expert's config gets looked up from in llm.py.
        """
        rows = self.query("SELECT * FROM llm_roles")
        return {row['role']: row for row in rows}

    def insertRows(self, table, columns, values):
        """
        Insert one row into `table`. Any value that starts with "(SELECT"
        is inlined directly into the SQL instead of bound as a parameter,
        so the Database Write Expert's generated code can resolve a
        foreign key by name instead of needing to know the numeric ID,
        e.g. "(SELECT experience_id FROM experiences WHERE name = 'MSU Research')"

        Homework 2: if `table` is one of EMBEDDING_FIELDS, the new row's
        embedding is generated and stored right after the insert -- this
        needs the new row's ID (self.query() doesn't return one), so this
        method opens its own connection instead of calling self.query().
        """
        value_sql, bound_params = [], []
        for value in values:
            if isinstance(value, str) and value.strip().startswith("(SELECT"):
                value_sql.append(value)
            else:
                value_sql.append("?")
                bound_params.append(value)
        sql = f"INSERT INTO {table} ({', '.join(columns)}) VALUES ({', '.join(value_sql)})"

        connection = sqlite3.connect(self.db_path)
        try:
            connection.execute("PRAGMA foreign_keys = ON")
            cursor = connection.cursor()
            cursor.execute(sql, tuple(bound_params))
            new_row_id = cursor.lastrowid
            connection.commit()
        finally:
            connection.close()

        if table in EMBEDDING_FIELDS:
            self._updateEmbedding(table, new_row_id)

    def _updateEmbedding(self, table, row_id):
        """
        Regenerate and store the embedding for one row, combining that
        table's EMBEDDING_FIELDS columns into a single string first (e.g.
        an institution's name + department). Stored as JSON text since
        SQLite has no native vector/array column type.
        """
        id_column = ID_COLUMNS[table]
        rows = self.query(f"SELECT * FROM {table} WHERE {id_column} = ?", (row_id,))
        if not rows:
            return

        row = rows[0]
        text = " ".join(str(row[field]) for field in EMBEDDING_FIELDS[table] if row.get(field))
        embedding = generate_embedding(text)

        connection = sqlite3.connect(self.db_path)
        try:
            connection.execute(
                f"UPDATE {table} SET embedding = ? WHERE {id_column} = ?",
                (json.dumps(embedding), row_id),
            )
            connection.commit()
        finally:
            connection.close()

    def backfillEmbeddings(self):
        """
        Generate embeddings for any row that doesn't have one yet.

        insertRows() embeds new rows automatically, but the CSV-seeded
        starting data (loaded by _seed_table on every startup) never goes
        through insertRows -- so this fills in the gap. Safe to call every
        startup: a row with embedding IS NOT NULL is already done and gets
        skipped, so re-running this after the first startup is a no-op.
        """
        for table in EMBEDDING_FIELDS:
            id_column = ID_COLUMNS[table]
            rows = self.query(f"SELECT {id_column} FROM {table} WHERE embedding IS NULL")
            for row in rows:
                self._updateEmbedding(table, row[id_column])
            if rows:
                print(f"  Generated embeddings for {len(rows)} {table} row(s)")
	
    def _cosineSimilarity(self, vector_a, vector_b):
        """
        Return a similarity score between two vectors, from -1 (opposite
        meaning) to 1 (identical meaning). This is the standard way to
        compare embeddings: the angle between two vectors in 1536-
        dimensional space, not their raw distance.
        """
        dot_product = sum(a * b for a, b in zip(vector_a, vector_b))
        magnitude_a = math.sqrt(sum(a * a for a in vector_a))
        magnitude_b = math.sqrt(sum(b * b for b in vector_b))
        if magnitude_a == 0 or magnitude_b == 0:
            return 0.0
        return dot_product / (magnitude_a * magnitude_b)

    def semanticSearch(self, table, query_text, top_k=3):
        """
        Return the top_k rows in `table` whose embedding is closest in
        MEANING to query_text, ranked by cosine similarity -- e.g.
        searching institutions for "MSU" finds the row named "Michigan
        State University" even though the strings don't match at all.

        For 'institutions', each result also gets its `positions`
        attached (title/responsibilities/start_date/end_date) via a
        normal SQL join -- this is what lets a single Semantic Search
        Expert call answer "how long did they work at MSU?"-style
        questions without a second AI call.
        """
        id_column = ID_COLUMNS[table]
        query_embedding = generate_embedding(query_text)

        rows = self.query(f"SELECT * FROM {table} WHERE embedding IS NOT NULL")
        scored = [
            (self._cosineSimilarity(query_embedding, json.loads(row['embedding'])), row)
            for row in rows
        ]
        scored.sort(key=lambda pair: pair[0], reverse=True)

        results = []
        for similarity, row in scored[:top_k]:
            visible = {key: value for key, value in row.items() if key != 'embedding'}
            visible['similarity'] = round(similarity, 4)

            if table == 'institutions':
                visible['positions'] = self.query(
                    "SELECT title, responsibilities, start_date, end_date "
                    "FROM positions WHERE inst_id = ?",
                    (row[id_column],)
                )

            results.append(visible)

        return results
