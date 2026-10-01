from concurrent.futures import ThreadPoolExecutor
from threading import Barrier

from kirana import db


def test_two_simultaneous_approvals_post_one_ledger_entry(app, receipt):
    gate = Barrier(2)
    def worker():
        connection = db.connect(app.config['DATABASE'])
        try:
            gate.wait(timeout=5)
            return db.approve(connection, receipt['id'], 1, 'Meera Patel')
        finally:
            connection.close()
    with ThreadPoolExecutor(max_workers=2) as executor:
        futures = [executor.submit(worker) for _ in range(2)]
        results = [future.result(timeout=15) for future in futures]
    assert sorted(created for _, created in results) == [False, True]
    assert results[0][0]['id'] == results[1][0]['id']
    connection = db.connect(app.config['DATABASE'])
    try:
        assert connection.execute('SELECT COUNT(*) FROM ledger').fetchone()[0] == 1
        assert connection.execute("SELECT COUNT(*) FROM events WHERE action='approved'").fetchone()[0] == 1
    finally:
        connection.close()


def test_two_simultaneous_reviews_do_not_overwrite_each_other(app, receipt):
    gate = Barrier(2)
    def worker(name):
        connection = db.connect(app.config['DATABASE'])
        fields = dict(receipt['fields'], merchant=name)
        try:
            gate.wait(timeout=5)
            try:
                db.update_review(connection, receipt['id'], 1, fields)
                return 'saved'
            except db.Conflict:
                return 'conflict'
        finally:
            connection.close()
    with ThreadPoolExecutor(max_workers=2) as executor:
        futures = [executor.submit(worker, name) for name in ('Meera Supplier', 'Desai Supplier')]
        assert sorted(future.result(timeout=15) for future in futures) == ['conflict', 'saved']
