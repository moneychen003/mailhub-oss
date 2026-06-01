import os
import psycopg
from psycopg.rows import dict_row
from contextlib import contextmanager
from dotenv import load_dotenv

load_dotenv("/opt/mailhub/.env")
load_dotenv(os.path.join(os.getcwd(), ".env"))
DATABASE_URL = os.environ["DATABASE_URL"]


@contextmanager
def conn():
    with psycopg.connect(DATABASE_URL, row_factory=dict_row) as c:
        yield c


def fetchone(sql: str, params: tuple = ()) -> dict | None:
    with conn() as c, c.cursor() as cur:
        cur.execute(sql, params)
        return cur.fetchone()


def fetchall(sql: str, params: tuple = ()) -> list[dict]:
    with conn() as c, c.cursor() as cur:
        cur.execute(sql, params)
        return cur.fetchall()


def execute(sql: str, params: tuple = ()) -> None:
    with conn() as c, c.cursor() as cur:
        cur.execute(sql, params)
        c.commit()


def execute_returning(sql: str, params: tuple = ()) -> dict | None:
    with conn() as c, c.cursor() as cur:
        cur.execute(sql, params)
        row = cur.fetchone()
        c.commit()
        return row
