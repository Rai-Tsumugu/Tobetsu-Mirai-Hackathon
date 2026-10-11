"""Shared names, validation and append-only SQLite persistence.

Amounts/quantities use Decimal, serialized as decimal strings without rounding.
The eight items fields match the design document. Extra bookkeeping remains
inside price versions and records and never silently changes that contract.
"""
from contextlib import contextmanager
from datetime import date, datetime, timezone
from decimal import Decimal, InvalidOperation
import json
from pathlib import Path
import sqlite3
from uuid import uuid4

ITEM_FIELDS = ('item_id', 'name', 'category', 'unit', 'unit_price', 'price_type', 'source', 'updated_at')
CATEGORIES = ('部品', '塗料', '溶剤', '消耗品')
PRICE_TYPES = ('仕入', '販売')
DEMO_DATE = '2026-10-11'


class ValidationError(ValueError):
    """An input needs human correction; never replace it with zero."""


def text_value(value, field):
    if not isinstance(value, str) or not value.strip():
        raise ValidationError(f'{field}: 入力が必要です')
    return value.strip()


def decimal_value(value, field='value', *, positive=False):
    if value is None or isinstance(value, bool):
        raise ValidationError(f'{field}: 数値を確認してください')
    try:
        result = Decimal(str(value))
    except (InvalidOperation, ValueError, TypeError):
        raise ValidationError(f'{field}: 数値を確認してください') from None
    if not result.is_finite() or result < 0 or (positive and result == 0):
        raise ValidationError(f'{field}: 有限の正数/非負数を入力してください')
    if len(result.as_tuple().digits) > 28 or abs(result.as_tuple().exponent) > 12:
        raise ValidationError(f'{field}: 数値の桁数が大きすぎます')
    return result


def date_value(value, field='date'):
    value = text_value(value, field)
    try:
        return date.fromisoformat(value)
    except ValueError:
        try:
            return datetime.fromisoformat(value.replace('Z', '+00:00')).date()
        except ValueError:
            raise ValidationError(f'{field}: ISO形式の日付が必要です') from None


def approved_by(payload):
    return text_value(payload.get('confirmed_by'), 'confirmed_by')


def validate_item(item):
    if not isinstance(item, dict):
        raise ValidationError('item: 品目が必要です')
    result = {field: text_value(item.get(field), field) for field in ITEM_FIELDS if field != 'unit_price'}
    if result['category'] not in CATEGORIES or result['price_type'] not in PRICE_TYPES:
        raise ValidationError('category / price_type: 選択値を確認してください')
    result['unit_price'] = str(decimal_value(item.get('unit_price'), 'unit_price'))
    date_value(result['updated_at'], 'updated_at')
    return {field: result[field] for field in ITEM_FIELDS}


def demo_item(item_id='demo-paint', price_type='販売', unit_price='120', unit='ml'):
    return dict(item_id=item_id, name='架空サンプル塗料', category='塗料', unit=unit,
                unit_price=unit_price, price_type=price_type, source='simulator:架空値', updated_at=DEMO_DATE)


def price_conditions(version):
    """Normalize commercial terms across supplier, history and snapshot ideas.

    Flattened supplier terms and an explicit conditions dictionary denote the
    same terms. Freshness/provenance fields do not participate in comparison.
    Unknown currency defaults to this Simulator's explicit JPY contract; no
    exchange-rate conversion takes place. Other absent terms remain absent.
    """
    metadata = version.get('metadata') or {}
    nested = metadata.get('conditions', {})
    if not isinstance(nested, dict):
        raise ValidationError('conditions: 取引条件の形式を確認してください')
    allowed = ('freight_basis', 'freight_amount', 'tax_basis', 'delivery_days',
               'currency', 'transaction_conditions')
    result = {key: nested[key] for key in allowed if key in nested}
    for key in allowed:
        if key in metadata:
            if key in result and result[key] != metadata[key]:
                raise ValidationError('conditions: 取引条件の二重定義が一致しません')
            result[key] = metadata[key]
    result.setdefault('currency', 'JPY')
    return result


def dumps(value):
    return json.dumps(value, ensure_ascii=False, allow_nan=False,
                      default=lambda obj: str(obj) if isinstance(obj, Decimal) else _unsupported(obj))


def _unsupported(obj):
    raise TypeError(f'Unsupported value: {type(obj).__name__}')


class Store:
    """A caller-owned SQLite connection. Each HTTP request opens its own Store.

    record namespaces are internal model tables represented as append-only JSON
    records. latest() provides logical versioning; update/delete are not exposed.
    Transactions compose through savepoints, including a whole import batch.
    """
    def __init__(self, path=':memory:'):
        self.connection = sqlite3.connect(str(path), timeout=10)
        self.connection.row_factory = sqlite3.Row
        self.connection.execute('PRAGMA foreign_keys=ON')
        self.connection.executescript('''
            CREATE TABLE IF NOT EXISTS records (
                sequence INTEGER PRIMARY KEY AUTOINCREMENT,
                namespace TEXT NOT NULL, record_id TEXT NOT NULL,
                payload TEXT NOT NULL, created_at TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS records_lookup ON records(namespace, record_id, sequence);
            CREATE TABLE IF NOT EXISTS prices (
                sequence INTEGER PRIMARY KEY AUTOINCREMENT,
                price_version_id TEXT UNIQUE NOT NULL,
                item_id TEXT NOT NULL, price_type TEXT NOT NULL,
                unit TEXT NOT NULL, supplier_id TEXT NOT NULL,
                payload TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS prices_lookup ON prices(item_id, price_type, sequence);
        ''')

    def close(self):
        self.connection.close()

    @contextmanager
    def transaction(self):
        savepoint = 's_' + uuid4().hex
        self.connection.execute(f'SAVEPOINT {savepoint}')
        try:
            yield self
            self.connection.execute(f'RELEASE SAVEPOINT {savepoint}')
        except BaseException:
            self.connection.execute(f'ROLLBACK TO SAVEPOINT {savepoint}')
            self.connection.execute(f'RELEASE SAVEPOINT {savepoint}')
            raise

    def put(self, namespace, record, record_id=None):
        namespace = text_value(namespace, 'namespace')
        if not isinstance(record, dict):
            raise ValidationError('record: 記録項目の集合が必要です')
        record_id = text_value(record_id, 'record_id') if record_id is not None else uuid4().hex
        payload = dumps(record)
        with self.transaction():
            self.connection.execute('INSERT INTO records(namespace,record_id,payload,created_at) VALUES(?,?,?,?)',
                (namespace, record_id, payload, datetime.now(timezone.utc).isoformat()))
        return dict(record, record_id=record_id)

    def records(self, namespace, record_id=None):
        sql = 'SELECT record_id,payload FROM records WHERE namespace=?'
        params = [namespace]
        if record_id is not None:
            sql += ' AND record_id=?'
            params.append(record_id)
        rows = self.connection.execute(sql + ' ORDER BY sequence', params).fetchall()
        return [dict(json.loads(row['payload']), record_id=row['record_id']) for row in rows]

    def latest(self, namespace, record_id):
        records = self.records(namespace, record_id)
        if not records:
            raise ValidationError(f'{namespace}: 指定した記録がありません')
        return records[-1]

    def add_price(self, item, confirmed_by, *, supplier_id='', valid_from=None, valid_until=None,
                  status='approved', reason='初回登録', **metadata):
        item = validate_item(item)
        confirmed_by = text_value(confirmed_by, 'confirmed_by')
        reason = text_value(reason, 'reason')
        if status not in ('approved', 'pending'):
            raise ValidationError('status: 承認状態を確認してください')
        valid_from = date_value(valid_from or item['updated_at'], 'valid_from').isoformat()
        if valid_until is not None:
            valid_until = date_value(valid_until, 'valid_until').isoformat()
            if valid_until < valid_from:
                raise ValidationError('valid_until: 開始日より前です')
        # Protect the identity/unit of an item across all price types/suppliers.
        prior = self.price_versions(item['item_id'])
        if prior and any(prior[-1]['item'][key] != item[key] for key in ('name', 'category', 'unit')):
            raise ValidationError('品目の名称・分類・基準単位は価格更新で変更できません')
        version = dict(price_version_id=uuid4().hex, item=item, confirmed_by=confirmed_by,
                       supplier_id=supplier_id, valid_from=valid_from, valid_until=valid_until,
                       status=status, reason=reason, metadata=metadata)
        with self.transaction():
            self.connection.execute('INSERT INTO prices(price_version_id,item_id,price_type,unit,supplier_id,payload) VALUES(?,?,?,?,?,?)',
                (version['price_version_id'], item['item_id'], item['price_type'], item['unit'], supplier_id, dumps(version)))
        return version

    def price_versions(self, item_id=None, price_type=None, supplier_id=None):
        sql = 'SELECT payload FROM prices WHERE 1=1'
        params = []
        for key, value in (('item_id', item_id), ('price_type', price_type), ('supplier_id', supplier_id)):
            if value is not None:
                sql += f' AND {key}=?'
                params.append(value)
        return [json.loads(row[0]) for row in self.connection.execute(sql + ' ORDER BY sequence', params)]

    def get_price(self, item_id, price_type='販売', *, as_of=DEMO_DATE, supplier_id=None, unit=None):
        if price_type not in PRICE_TYPES:
            raise ValidationError('price_type: 選択値を確認してください')
        as_of = date_value(as_of, 'as_of').isoformat()
        versions = [version for version in self.price_versions(item_id, price_type, supplier_id)
                    if version['status'] == 'approved' and version['valid_from'] <= as_of]
        suppliers = {version['supplier_id'] for version in versions}
        if supplier_id is None and len(suppliers) > 1:
            raise ValidationError('supplier_id: 仕入先の選択が必要です')
        if not versions:
            raise ValidationError('価格未確認: 承認済みの対象価格がありません')
        # Select by effective date then append sequence, not insertion alone.
        version = max(enumerate(versions), key=lambda pair: (pair[1]['valid_from'], pair[0]))[1]
        if version['valid_until'] is not None and as_of > version['valid_until']:
            raise ValidationError('価格期限切れ: 再確認してください')
        if version['metadata'].get('currency', 'JPY') != 'JPY':
            raise ValidationError('比較条件不一致: 通貨が異なるため円価格へ自動換算できません')
        if unit is not None and version['item']['unit'] != unit:
            raise ValidationError('単位不一致: 換算根拠を確認してください')
        return version


def seed_demo(store):
    """An explicit Simulator seed; never invoked by individual proposal runs."""
    if store.price_versions('demo-paint'):
        return
    for price_type, unit_price in (('仕入', '80'), ('販売', '120')):
        store.add_price(demo_item(price_type=price_type, unit_price=unit_price), '架空デモ担当')
