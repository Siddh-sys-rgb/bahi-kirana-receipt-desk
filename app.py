"""Run the local receipt desk. No remote services or API credentials required."""
import argparse
from kirana import create_app

if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='Bahi — Kirana Receipt Desk')
    parser.add_argument('--port', type=int, default=8104)
    parser.add_argument('--no-demo', action='store_true', help='Skip sample seeding on a new database')
    args = parser.parse_args()
    app = create_app({'SEED_DEMO': not args.no_demo})
    app.run(host='127.0.0.1', port=args.port, debug=False, threaded=True)
