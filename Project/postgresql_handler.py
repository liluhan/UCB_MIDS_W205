import pandas as pd
import psycopg2


class Postgresql:
    def __init__(self, user_name=None, password=None, host=None, port=None, db=None):
        self.user_name = user_name
        self.password = password
        self.host = host
        self.port = port
        self.db = db
        self.conn = None
        self.table = None
        self.connect()

    def connect(self):
        try:
            self.conn = psycopg2.connect(database=self.db,
                                         user=self.user_name,
                                         password=self.password,
                                         host=self.host,
                                         port=self.port)
        except:
            raise ValueError('Invalid Postgresql db input.')

    def _table_exists(self, table):
        try:
            cur = self.conn.cursor()
            cur.execute("SELECT EXISTS(SELECT * FROM information_schema.tables where table_name='{name}')".format(
                name=table.lower()))
            return cur.fetchone()[0]
        except:
            self.conn.rollback()
            return False

    def initialize_table(self, table=None, recreate=False, **kwargs):
        self.connect()
        self.table = table
        if not self._table_exists(table):
            self.create_table(table, self.make_schema_string(**kwargs))
            return
        if recreate:
            self.drop_table(table)
            self.create_table(table, self.make_schema_string(**kwargs))

    def put_dataframe(self, df, fields_types, table=None):
        """
        Push dataframe data into Postgresql db
        Args:
            df: pandas dataframe
            fields_types: dict, {key:data_type, ...}
            table (object):

        Examples:
            .put_dataframe(pd.DataFrame(),
                           fields_type={'place_id': 'TEXT', 'city': 'TEXT', 'state': 'TEXT', 'population': 'INT',
                                        'lat': 'FLOAT', 'lng': 'FLOAT'},
                           table='TestMajorCities')
        """
        batch_size = 500
        start_idx = 0

        if table is None:
            table = self.table
        fields_list = list(fields_types.keys())
        fields_to_push = self.construct_db_field_string(fields_list)

        while start_idx < len(df):
            end_idx = min(start_idx + batch_size, len(df))
            print 'Processing {start} to {end}'.format(start=start_idx, end=end_idx)
            curr_data = df[start_idx:end_idx]
            curr_insert_string = self.parse_values_list(curr_data.to_dict('records'),
                                                        fields_types,
                                                        fields_list)
            start_idx = end_idx
            self.put(table, fields=fields_to_push, values=curr_insert_string)

    def put(self, table, fields=None, values=None, keys=None, key_field=None, update=False):
        """
        Puts data into the Postgresql database
        Args:
            table: str, table name, REQUIRED for both insert and update
            fields: str or list of str, REQUIRED for both insert and update
            values: str (for insert) or list of str (for update), REQUIRED for both insert and update
            keys: list of str, for update only
            key_field: str, for update only
            update: boolean, for update only

        Returns:
        Examples:
            .put('test_zipcode', keys = ['id1','id2'], values=['(value1a, value1b)', '(value2a, value2b)'], fields=['field1', 'field2'], update=True)
            .put('test_zipcode', keys = ['id1','id2'], values=['(value1a, value1b)', '(value2a, value2b)'], fields='(field1, field2)', update=True)
            .put('test_zipcode', keys = None, values='(value1a, value1b), (value2a, value2b)', fields=['field1', 'field2'], update=False)
        """
        if update:
            self._update(table, fields, keys, values, key_field)
        else:
            self._insert(table, fields, values)

    def _update(self, table, fields, keys, values, key_field='id'):
        if keys and values:
            cur = self.conn.cursor()
            fields_string = self.construct_db_field_string(fields)
            for (key, value) in zip(keys, values):
                cur.execute("UPDATE {table} SET {fields}={values} WHERE {key_field}='{key}';".format(table=table,
                                                                                                     fields=fields_string,
                                                                                                     values=value,
                                                                                                     key_field=key_field,
                                                                                                     key=key))
            self.conn.commit()

    def _insert(self, table, fields, values):
        if values:
            fields_string = self.construct_db_field_string(fields)
            cur = self.conn.cursor()
            cur.execute("INSERT INTO {table} {fields} VALUES {values};".format(table=table,
                                                                               fields=fields_string,
                                                                               values=values))
            self.conn.commit()

    def get(self, query):
        df = pd.read_sql(query, self.conn)
        return df

    def create_table(self, table, schema):
        """
        Creates a table given table name and schema
        Args:
            table: string, name of the table
            schema: string, schema

        Returns:
        Examples:
            .create_table('test_zipcode', '(id TEXT PRIMARY KEY NOT NULL, median_price FLOAT, median_rent FLOAT)')
        """
        if self.table is None:
            self.table = table
        cur = self.conn.cursor()
        cur.execute('''CREATE TABLE {table} {schema};'''.format(table=table, schema=schema))
        self.conn.commit()

    def drop_table(self, table):
        cur = self.conn.cursor()
        cur.execute('''TRUNCATE TABLE {name};'''.format(name=table))
        cur.execute('''DROP TABLE {name};'''.format(name=table))
        self.conn.commit()
        self.table = None

    def construct_db_field_string(self, fields, add_quote=False):
        if isinstance(fields, list):
            fields_string = '('
            for entry in fields:
                if add_quote:
                    fields_string += ("'" + entry + "'" + ',')
                else:
                    fields_string += (entry + ',')
            fields_string = fields_string[:-1] + ')'
        elif isinstance(fields, str):
            fields_string = fields
        else:
            raise TypeError('Unsupported type for input arguyment "fields".')
        return fields_string

    def parse_values_list(self, data, fields, field_list=None):
        """
        Parse a list of dict into strings for batch insertion
        Args:
            data: list, [dict(key1=value1, key2=value2, ...), dict()]
            fields: dict, {key: data_type}
            field_list: list, optional, can be passed in to ensure that the values match the columns being pushed

        Returns:
            insert_string: str, for inserting into db
        """
        insert_string = ''
        if field_list is None:
            field_list = list(fields.keys())
        for entry in data:
            curr_string = "("
            for key in field_list:
                if key not in entry:
                    curr_string += 'NULL,'
                else:
                    if fields[key] == 'TEXT':
                        curr_string += "'" + str(entry[key]).replace("'", "") + "',"
                    else:
                        curr_string += str(entry[key]) + ","
            curr_string = curr_string[:-1] + "),"
            insert_string += curr_string
        return insert_string[:-1]

    def make_schema_string(self, fields_types=None, primary_key=None, not_null_fields=None):
        primary_is_not_null = False
        if primary_key in not_null_fields:
            not_null_fields.remove(primary_key)
            primary_is_not_null = True

        correct_sequence = [primary_key] + not_null_fields
        for key in fields_types.keys():
            if key not in correct_sequence:
                correct_sequence.append(key)

        schema_string = '('
        for entry in correct_sequence:
            schema_string += entry + ' '
            schema_string += fields_types[entry] + ' '
            if entry == primary_key:
                schema_string += 'PRIMARY KEY' + ' '
                if primary_is_not_null:
                    schema_string += 'NOT NULL' + ' '
            if entry in not_null_fields:
                schema_string += 'NOT NULL' + ' '
            schema_string += ','
        schema_string = schema_string[:-1] + ')'
        return schema_string
