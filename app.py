"""Run the local receipt desk. No remote services or API credentials required."""
import argparse
from pathlib import Path
from kirana import create_app

if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='Bahi — Kirana Receipt Desk')
    parser.add_argument('--port', type=int, default=8104)
    parser.add_argument('--no-demo', action='store_true', help='Skip sample seeding on a new database')
    parser.add_argument('--data-dir', type=Path, default=Path('instance'),
                        help='Directory for the local database and uploaded images')
    args = parser.parse_args()
    if not 1 <= args.port <= 65535:
        parser.error('--port must be between 1 and 65535')
    data_dir = args.data_dir.resolve()
    app = create_app({'SEED_DEMO': not args.no_demo,
                      'DATABASE': str(data_dir / 'bahi.db'),
                      'UPLOAD_DIR': str(data_dir / 'uploads')})
    app.run(host='127.0.0.1', port=args.port, debug=False, threaded=True)
