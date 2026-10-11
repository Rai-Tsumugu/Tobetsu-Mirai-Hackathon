"""Local SQLite persistence, immutable quote versions and append-only events."""
from contextlib import contextmanager
from copy import deepcopy
import json
import sqlite3
from threading import RLock

class QuoteStore:
    def __init__(self, database_path=':memory:'):
        self._lock = RLock()
        self._transaction_depth = 0
        self.connection = sqlite3.connect(database_path, check_same_thread=False)
        self.connection.execute('PRAGMA foreign_keys=ON')
        self.connection.executescript('''
        CREATE TABLE IF NOT EXISTS quote_versions (
          quote_id TEXT NOT NULL, quote_version INTEGER NOT NULL,
          customer_ref TEXT, vehicle_ref TEXT, job_ref TEXT,
          snapshot TEXT NOT NULL, PRIMARY KEY(quote_id, quote_version));
        CREATE TABLE IF NOT EXISTS communications (
          communication_id TEXT PRIMARY KEY, quote_id TEXT NOT NULL,
          quote_version INTEGER NOT NULL, snapshot TEXT NOT NULL,
          FOREIGN KEY(quote_id, quote_version) REFERENCES quote_versions);
        CREATE TABLE IF NOT EXISTS change_events (
          event_id TEXT PRIMARY KEY, quote_id TEXT NOT NULL,
          quote_version INTEGER NOT NULL, snapshot TEXT NOT NULL,
          FOREIGN KEY(quote_id, quote_version) REFERENCES quote_versions);
        CREATE TABLE IF NOT EXISTS drafts (draft_id TEXT PRIMARY KEY, snapshot TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS price_history (history_id INTEGER PRIMARY KEY, item_id TEXT NOT NULL, snapshot TEXT NOT NULL);
        ''')
        self.connection.commit()

    @contextmanager
    def transaction(self):
        with self._lock:
            outermost = self._transaction_depth == 0
            if outermost:
                self.connection.execute('BEGIN IMMEDIATE')
            self._transaction_depth += 1
            try:
                yield self
            except BaseException:
                if outermost:
                    self.connection.rollback()
                raise
            else:
                if outermost:
                    self.connection.commit()
            finally:
                self._transaction_depth -= 1

    @staticmethod
    def _encode(value):
        return json.dumps(value, ensure_ascii=False, allow_nan=False)

    def save_quote(self, quote):
        quote = deepcopy(quote)
        quote_id = quote.get('quote_id')
        quote_version = quote.get('quote_version')
        if not isinstance(quote_id, str) or not quote_id.strip():
            raise ValueError('quote_id is required')
        if isinstance(quote_version, bool) or not isinstance(quote_version, int) or quote_version < 1:
            raise ValueError('quote_version must be positive integer')
        with self.transaction():
            self.connection.execute('INSERT INTO quote_versions VALUES (?, ?, ?, ?, ?, ?)',
                (quote_id, quote_version, quote.get('customer_ref'), quote.get('vehicle_ref'), quote.get('job_ref'), self._encode(quote)))
        return quote

    def get_quote(self, quote_id, quote_version=None):
        if quote_version is None:
            row = self.connection.execute('SELECT snapshot FROM quote_versions WHERE quote_id=? ORDER BY quote_version DESC LIMIT 1', (quote_id,)).fetchone()
        else:
            row = self.connection.execute('SELECT snapshot FROM quote_versions WHERE quote_id=? AND quote_version=?', (quote_id, quote_version)).fetchone()
        if row is None:
            raise ValueError('quote version not found')
        return json.loads(row[0])

    def list_quotes(self, customer_ref=None, vehicle_ref=None, job_ref=None):
        clauses, values = [], []
        for field, value in [('customer_ref', customer_ref), ('vehicle_ref', vehicle_ref), ('job_ref', job_ref)]:
            if value is not None:
                clauses.append(field + '=?')
                values.append(value)
        query = 'SELECT snapshot FROM quote_versions'
        if clauses:
            query += ' WHERE ' + ' AND '.join(clauses)
        return [json.loads(row[0]) for row in self.connection.execute(query + ' ORDER BY quote_version DESC, quote_id', values)]

    def append_communication(self, record):
        with self.transaction():
            self.connection.execute('INSERT INTO communications VALUES (?, ?, ?, ?)',
                (record['communication_id'], record['quote_id'], record['quote_version'], self._encode(record)))
        return deepcopy(record)

    def list_communications(self, quote_id):
        return [json.loads(row[0]) for row in self.connection.execute('SELECT snapshot FROM communications WHERE quote_id=? ORDER BY rowid', (quote_id,))]

    def append_change_event(self, event):
        with self.transaction():
            self.connection.execute('INSERT INTO change_events VALUES (?, ?, ?, ?)',
                (event['event_id'], event['quote_id'], event['to_version'], self._encode(event)))
        return deepcopy(event)

    def list_change_events(self, quote_id):
        return [json.loads(row[0]) for row in self.connection.execute('SELECT snapshot FROM change_events WHERE quote_id=? ORDER BY rowid', (quote_id,))]

    def save_draft(self, draft):
        with self.transaction():
            self.connection.execute('INSERT INTO drafts VALUES (?, ?) ON CONFLICT(draft_id) DO UPDATE SET snapshot=excluded.snapshot',
                (draft['draft_id'], self._encode(draft)))
        return deepcopy(draft)

    def get_draft(self, draft_id):
        row = self.connection.execute('SELECT snapshot FROM drafts WHERE draft_id=?', (draft_id,)).fetchone()
        if row is None:
            raise ValueError('draft not found')
        return json.loads(row[0])

    def list_drafts(self):
        return [json.loads(row[0]) for row in self.connection.execute('SELECT snapshot FROM drafts ORDER BY rowid DESC')]

    def save_price(self, item):
        with self.transaction():
            self.connection.execute('INSERT INTO price_history(item_id,snapshot) VALUES (?,?)', (item['item_id'], self._encode(item)))

    def list_prices(self, item_id):
        return [json.loads(row[0]) for row in self.connection.execute('SELECT snapshot FROM price_history WHERE item_id=? ORDER BY history_id', (item_id,))]

    def close(self):
        self.connection.close()
